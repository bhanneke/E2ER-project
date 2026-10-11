"""Checks of a time-series study: the hold-out frozen before fitting, the forecasts judged on it.

A forecast is only as good as its evaluation on data the model never saw.
The common ways to fool oneself are all mechanical: choosing the hold-out
after looking at how models do on it, fitting (or testing for trends) on
periods that belong to the hold-out, reporting in-sample errors as forecast
errors, and having no simple benchmark to give the errors a scale. The two
checks here catch them deterministically in the time-series template
(``pipelines/time-series-forecasting.toml``).

``forecast_design`` (inside the dispatch, after the forecast designer and
before the analysis) reads ``forecast_design.json`` (schema in the skill
``methods/time-series-forecasting``) and the series in ``data.db``. It fails
when the series is not there or its periods repeat, the hold-out is not the
last periods of the series, fewer than ``min_train_periods`` (default 24)
periods are left to fit on, no baseline (naive, seasonal naive, mean or
drift), no candidate model, no stationarity test and no trend test is
declared, or the interval level is not a share. When it passes it freezes the
setup: ``holdout_freeze.json`` records the SHA-256 of ``forecast_design.json``,
the hold-out periods and the SHA-256 of their values, and the end of the
training periods. The freeze is refused when a model was already fitted
(estimation output in the study), and a changed setup is refused once results
exist; before that, a changed setup is frozen again and the change is listed.

``forecast_evaluation`` (a step after the estimation check) holds
``estimation_results.json`` to the frozen setup: the setup and the hold-out
values unchanged; every declared diagnostic reported with its statistic, its
p-value and the end of the sample it was computed on, inside the training
periods; every declared model and baseline fitted on training periods only
(``train_end`` before the hold-out) and evaluated out of sample on exactly
the hold-out periods, with its predictions listed; RMSE and MAE recomputed
from those predictions and the actual values in ``data.db``; and at least one
forecast beyond the data with the declared horizon and interval level. It
writes ``forecast_check.json`` with the recomputed errors and each model's
RMSE relative to the best baseline.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .data_quality import DATA_DB, CheckResult, _connect, _empty, _names, _quote, _table_columns

FORECAST_DESIGN_FILE = "forecast_design.json"
FREEZE_FILE = "holdout_freeze.json"
FORECAST_CHECK_FILE = "forecast_check.json"
RESULTS_FILE = "estimation_results.json"
DEFAULT_MIN_TRAIN_PERIODS = 24
DEFAULT_ERROR_TOLERANCE = 0.005

#: Simple benchmarks a forecast must beat to mean anything (Hyndman & Athanasopoulos, ch. 5.2).
BASELINE_METHODS = frozenset({"naive", "seasonal naive", "mean", "drift"})
DIAGNOSTIC_KINDS = frozenset({"stationarity", "trend"})


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _method(text: Any) -> str:
    return " ".join(str(text or "").lower().replace("_", " ").replace("-", " ").split())


def _sortable(values: list[Any]) -> list[Any]:
    """Periods in time order: numerically when every period is a number, else as text (ISO dates sort as text)."""
    try:
        return sorted(values, key=float)
    except (TypeError, ValueError):
        return sorted(values, key=str)


def _same(a: Any, b: Any) -> bool:
    """Two period labels name the same period (2021 == "2021", "2021-01" == "2021-01")."""
    if str(a).strip() == str(b).strip():
        return True
    try:
        return float(a) == float(b)
    except (TypeError, ValueError):
        return False


def _index(periods: list[Any], label: Any) -> int | None:
    for i, p in enumerate(periods):
        if _same(p, label):
            return i
    return None


def _read_series(ws: Path, series: dict[str, Any]) -> tuple[list[Any], list[Any], str | None]:
    """(periods in order, values, problem) of the series a design names."""
    table = str(series.get("table") or "").strip()
    tcol = str(series.get("time_column") or "").strip()
    vcol = str(series.get("value_column") or "").strip()
    if not table or not tcol or not vcol:
        return [], [], "series must name its data.db 'table', 'time_column' and 'value_column'"
    if not (ws / DATA_DB).is_file():
        return [], [], f"there is no {DATA_DB} with the series"
    con = _connect(ws)
    try:
        cols = _table_columns(con, table)
        if not cols:
            return [], [], f"table {table} is not in {DATA_DB}"
        missing = [c for c in (tcol, vcol) if c not in cols]
        if missing:
            return [], [], f"table {table} has no column(s) {', '.join(missing)}"
        rows = con.execute(
            f"SELECT {_quote(tcol)}, {_quote(vcol)} FROM {_quote(table)} WHERE NOT {_empty(tcol)}"  # noqa: S608
        ).fetchall()
    except sqlite3.Error as e:
        return [], [], f"{DATA_DB} could not be read: {e}"
    finally:
        con.close()
    if not rows:
        return [], [], f"table {table} has no rows"
    periods = [r[0] for r in rows]
    if len({str(p) for p in periods}) != len(periods):
        seen: set[str] = set()
        dups = sorted({str(p) for p in periods if str(p) in seen or seen.add(str(p))})  # type: ignore[func-returns-value]
        return [], [], f"periods repeat in {table}.{tcol}: {_names(dups)}"
    order = _sortable(periods)
    by = {str(r[0]): r[1] for r in rows}
    return order, [by[str(p)] for p in order], None


def _fingerprint(periods: list[Any], values: list[Any]) -> str:
    payload = json.dumps([[str(p), v] for p, v in zip(periods, values, strict=True)], separators=(",", ":"))
    return _sha256_bytes(payload.encode("utf-8"))


def _design_problems(
    design: dict[str, Any], periods: list[Any], values: list[Any], min_train: int
) -> tuple[list[str], dict[str, Any]]:
    """Problems of a design against its series, and the hold-out it declares (when it is usable)."""
    problems: list[str] = []
    info: dict[str, Any] = {}
    series = design.get("series") or {}
    if not str(series.get("frequency") or "").strip():
        problems.append("series.frequency is missing (e.g. 'monthly')")

    hold = design.get("holdout")
    if not isinstance(hold, dict):
        problems.append("holdout must state 'start', 'end' and 'n_periods' of the hold-out")
    else:
        i0, i1 = _index(periods, hold.get("start")), _index(periods, hold.get("end"))
        if i0 is None or i1 is None:
            problems.append(
                f"holdout start {hold.get('start')!r} and end {hold.get('end')!r} must be periods of the series "
                f"({periods[0]} to {periods[-1]})"
            )
        elif i1 != len(periods) - 1:
            problems.append(
                f"the hold-out must be the last periods of the series: it ends at {hold.get('end')}, the series at "
                f"{periods[-1]}"
            )
        elif i0 > i1:
            problems.append("holdout.start lies after holdout.end")
        else:
            n = i1 - i0 + 1
            stated = hold.get("n_periods")
            if stated is not None and stated != n:
                problems.append(
                    f"holdout.n_periods is {stated}, but {hold.get('start')} to {hold.get('end')} are {n} periods"
                )
            if i0 < min_train:
                problems.append(
                    f"only {i0} periods are left to fit on before the hold-out (at least {min_train}); "
                    "shorten the hold-out or use a longer series"
                )
            gaps = [str(periods[i]) for i in range(i0, i1 + 1) if values[i] is None]
            if gaps:
                problems.append(f"the hold-out has periods without a value: {_names(gaps)}")
            info = {
                "start": periods[i0],
                "end": periods[i1],
                "n_periods": n,
                "periods": [periods[i] for i in range(i0, i1 + 1)],
                "train_start": periods[0],
                "train_end": periods[i0 - 1] if i0 > 0 else None,
                "n_train": i0,
                "values_sha256": _fingerprint(periods[i0 : i1 + 1], values[i0 : i1 + 1]),
            }

    horizon = design.get("horizon")
    if isinstance(horizon, bool) or not isinstance(horizon, int) or horizon < 1:
        problems.append("horizon must be a whole number of periods (>= 1) to forecast beyond the data")
    level = design.get("interval_level")
    if isinstance(level, bool) or not isinstance(level, int | float) or not 0 < level < 1:
        problems.append("interval_level must be a share between 0 and 1 (e.g. 0.95): forecasts need intervals")

    keys: list[str] = []
    baselines = design.get("baselines")
    if not isinstance(baselines, list) or not baselines:
        problems.append(
            "baselines must list at least one simple benchmark: {'model': key, 'method': 'naive' | "
            "'seasonal naive' | 'mean' | 'drift'}"
        )
    else:
        for b in baselines:
            if not isinstance(b, dict) or not str(b.get("model") or "").strip():
                problems.append("every baseline needs a 'model' key")
                continue
            if _method(b.get("method")) not in BASELINE_METHODS:
                problems.append(
                    f"baseline {b.get('model')}: method {b.get('method')!r} is not naive, seasonal naive, mean or drift"
                )
            keys.append(str(b["model"]))
    candidates = design.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        problems.append("candidates must list the models to compare with the baselines ({'model': key, 'method': ...})")
    else:
        for c in candidates:
            if (
                not isinstance(c, dict)
                or not str(c.get("model") or "").strip()
                or not str(c.get("method") or "").strip()
            ):
                problems.append("every candidate needs a 'model' key and a 'method'")
                continue
            keys.append(str(c["model"]))
    dup = sorted({k for k in keys if keys.count(k) > 1})
    if dup:
        problems.append(f"model keys repeat: {', '.join(dup)}")

    diags = design.get("diagnostics")
    kinds = set()
    if isinstance(diags, list):
        for d in diags:
            if isinstance(d, dict) and str(d.get("name") or "").strip() and str(d.get("test") or "").strip():
                kinds.add(_method(d.get("kind")))
            else:
                problems.append("every diagnostic needs a 'name', a 'kind' (stationarity or trend) and a 'test'")
    missing_kinds = sorted(DIAGNOSTIC_KINDS - kinds)
    if missing_kinds:
        problems.append(
            f"diagnostics must declare at least one {' and one '.join(missing_kinds)} test "
            "(e.g. KPSS or ADF; Mann-Kendall with Sen's slope)"
        )
    return problems, info


def _design(ws: Path) -> tuple[dict[str, Any] | None, bytes, str | None]:
    path = ws / FORECAST_DESIGN_FILE
    try:
        raw = path.read_bytes()
        doc = json.loads(raw.decode("utf-8"))
    except OSError:
        return None, b"", f"there is no {FORECAST_DESIGN_FILE}: the forecast designer declares the setup"
    except ValueError as e:
        return None, b"", f"{FORECAST_DESIGN_FILE} is not valid JSON: {e}"
    if not isinstance(doc, dict):
        return None, raw, f"{FORECAST_DESIGN_FILE} must be a JSON object"
    return doc, raw, None


def check_forecast_design(workspace: Path, *, min_train_periods: int = DEFAULT_MIN_TRAIN_PERIODS) -> CheckResult:
    """The forecast setup and its hold-out, frozen before any model is fitted (module docstring)."""
    from .preregistration import estimation_outputs

    ws = Path(workspace)
    design, raw, err = _design(ws)
    if err or design is None:
        return CheckResult(False, (err or "no design",))
    series = design.get("series")
    if not isinstance(series, dict):
        return CheckResult(False, ("series must name the data.db table, time_column, value_column and frequency",))
    periods, values, err = _read_series(ws, series)
    if err:
        return CheckResult(False, (err,))
    problems, hold = _design_problems(design, periods, values, min_train_periods)
    if problems:
        return CheckResult(False, tuple(problems))

    design_sha = _sha256_bytes(raw)
    fitted = estimation_outputs(ws)
    freeze_path = ws / FREEZE_FILE
    previous: dict[str, Any] | None = None
    if freeze_path.is_file():
        try:
            previous = json.loads(freeze_path.read_text(encoding="utf-8"))
        except ValueError:
            previous = None
    notes: list[str] = []
    stats = {
        "hold_out": f"{hold['start']} to {hold['end']}",
        "n_holdout": hold["n_periods"],
        "n_train": hold["n_train"],
    }
    if (
        previous
        and previous.get("design_sha256") == design_sha
        and previous.get("values_sha256") == hold["values_sha256"]
    ):
        return CheckResult(True, (), (f"frozen at {previous.get('frozen_at')}",), stats)
    if fitted:
        what = "changed after the hold-out was frozen" if previous else "was not frozen before a model was fitted"
        return CheckResult(
            False,
            (
                f"the forecast setup {what}: estimation output exists ({_names(fitted)}). "
                f"Put {FORECAST_DESIGN_FILE} back as frozen, or set the output aside and start the analysis again",
            ),
        )
    record = {
        "design_file": FORECAST_DESIGN_FILE,
        "design_sha256": design_sha,
        "series": {k: series.get(k) for k in ("table", "time_column", "value_column", "frequency")},
        **hold,
        "frozen_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "changes": list((previous or {}).get("changes") or []),
    }
    if previous:
        record["changes"].append(
            {"from_design_sha256": previous.get("design_sha256"), "frozen_at": previous.get("frozen_at")}
        )
        notes.append("the setup changed before any model was fitted and was frozen again")
    freeze_path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return CheckResult(True, (), tuple(notes), {**stats, "design_sha256": design_sha[:12]})


def _num(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, int | float):
        return None
    x = float(v)
    return x if math.isfinite(x) else None


def _decimals(v: float) -> int:
    from .data_quality import _decimals as d

    return d(v)


def _after(a: Any, b: Any) -> bool:
    """Period a lies after period b."""
    try:
        return float(a) > float(b)
    except (TypeError, ValueError):
        return str(a) > str(b)


def _within(stated: float, computed: float, tol: float) -> bool:
    return abs(stated - computed) <= max(tol * abs(computed), 0.5 * 10 ** (-_decimals(stated)) + 1e-12)


def check_forecast_evaluation(workspace: Path, *, error_tolerance: float = DEFAULT_ERROR_TOLERANCE) -> CheckResult:
    """The results held to the frozen setup and hold-out (module docstring)."""
    ws = Path(workspace)
    try:
        freeze = json.loads((ws / FREEZE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return CheckResult(False, (f"there is no {FREEZE_FILE}: the hold-out was never frozen before fitting",))
    design, raw, err = _design(ws)
    if err or design is None:
        return CheckResult(False, (err or "no design",))
    reasons: list[str] = []
    if _sha256_bytes(raw) != freeze.get("design_sha256"):
        reasons.append(f"{FORECAST_DESIGN_FILE} changed after the hold-out was frozen ({freeze.get('frozen_at')})")
    periods, values, err = _read_series(ws, design.get("series") or {})
    if err:
        return CheckResult(False, (err,))
    hold_periods = list(freeze.get("periods") or [])
    idx = [_index(periods, p) for p in hold_periods]
    if not hold_periods or any(i is None for i in idx):
        return CheckResult(False, ("the frozen hold-out periods are no longer in the series", *reasons))
    actual = {str(periods[i]): values[i] for i in idx if i is not None}
    if _fingerprint(
        [periods[i] for i in idx if i is not None], [values[i] for i in idx if i is not None]
    ) != freeze.get("values_sha256"):
        reasons.append("the hold-out values in data.db changed after they were frozen")
    train_end = freeze.get("train_end")
    hold_start, hold_end, n_hold = freeze.get("start"), freeze.get("end"), int(freeze.get("n_periods") or 0)

    try:
        results = json.loads((ws / RESULTS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return CheckResult(False, (f"{RESULTS_FILE} is missing or not valid JSON ({e})", *reasons))
    models = results.get("models") if isinstance(results.get("models"), dict) else {}
    oos = results.get("out_of_sample") if isinstance(results.get("out_of_sample"), dict) else {}
    forecasts = results.get("forecasts") if isinstance(results.get("forecasts"), dict) else {}

    # Diagnostics: declared, reported, computed on the training periods only.
    diags = results.get("diagnostics") if isinstance(results.get("diagnostics"), dict) else {}
    for d in design.get("diagnostics") or []:
        name = str(d.get("name"))
        got = diags.get(name)
        if not isinstance(got, dict):
            reasons.append(f"diagnostics.{name} ({d.get('test')}) is not in {RESULTS_FILE}")
            continue
        p = _num(got.get("p_value"))
        if _num(got.get("statistic")) is None or p is None or not 0 <= p <= 1:
            reasons.append(f"diagnostics.{name} needs a numeric 'statistic' and a 'p_value' between 0 and 1")
        end = got.get("sample_end")
        if end is None:
            reasons.append(f"diagnostics.{name} must state 'sample_end', the last period it was computed on")
        elif train_end is not None and _after(end, train_end):
            reasons.append(
                f"diagnostics.{name} was computed on periods up to {end}, inside the hold-out (training ends "
                f"{train_end}): a diagnostic that sees the hold-out leaks it into the model choice"
            )

    # Models: every declared one fitted on training periods only and evaluated on the hold-out.
    declared = [str(b.get("model")) for b in design.get("baselines") or []] + [
        str(c.get("model")) for c in design.get("candidates") or []
    ]
    baselines = [str(b.get("model")) for b in design.get("baselines") or []]
    missing = [m for m in declared if m not in models]
    if missing:
        reasons.append(f"model(s) {_names(missing)} of {FORECAST_DESIGN_FILE} are not in {RESULTS_FILE} 'models'")
    evaluated: dict[str, list[str]] = {}
    recomputed: dict[str, Any] = {}
    for key, entry in oos.items():
        if not isinstance(entry, dict):
            continue
        ev = entry
        model = str(ev.get("model"))
        evaluated.setdefault(model, []).append(key)
        m = models.get(model) if isinstance(models.get(model), dict) else {}
        m_end = m.get("train_end") if m else None
        if m_end is None:
            reasons.append(f"models.{model} must state 'train_end', the last period it was fitted on")
        elif train_end is not None and _after(m_end, train_end):
            reasons.append(
                f"leakage: models.{model} was fitted on periods up to {m_end}, inside the hold-out "
                f"({hold_start} to {hold_end}); out_of_sample.{key} is not out of sample"
            )
        if ev.get("train_end") is not None and train_end is not None and _after(ev.get("train_end"), train_end):
            reasons.append(f"leakage: out_of_sample.{key} trains up to {ev.get('train_end')}, inside the hold-out")
        if not (_same(ev.get("test_start"), hold_start) and _same(ev.get("test_end"), hold_end)):
            reasons.append(
                f"out_of_sample.{key} tests {ev.get('test_start')} to {ev.get('test_end')}; the frozen hold-out is "
                f"{hold_start} to {hold_end}"
            )
        if ev.get("n_test") != n_hold:
            reasons.append(
                f"out_of_sample.{key}.n_test is {ev.get('n_test')}; the frozen hold-out has {n_hold} periods"
            )
        preds = ev.get("predictions")
        if not isinstance(preds, list) or not preds:
            reasons.append(
                f"out_of_sample.{key} must list its 'predictions' (period, forecast) so its errors can be recomputed"
            )
            continue
        errs: list[float] = []
        covered = 0
        with_interval = 0
        bad = False
        seen: list[str] = []
        for i, p in enumerate(preds):
            fc = _num((p or {}).get("forecast"))
            per = (p or {}).get("period")
            match = next((k for k in actual if _same(k, per)), None)
            if fc is None or match is None:
                reasons.append(
                    f"out_of_sample.{key}.predictions[{i}] needs a numeric forecast for a hold-out period "
                    f"(got period {per!r})"
                )
                bad = True
                break
            seen.append(match)
            a = float(actual[match])
            errs.append(a - fc)
            lo, hi = _num(p.get("lower")), _num(p.get("upper"))
            if lo is not None and hi is not None:
                with_interval += 1
                covered += int(lo <= a <= hi)
        if bad:
            continue
        if sorted(seen) != sorted(str(k) for k in actual) or len(seen) != len(actual):
            reasons.append(f"out_of_sample.{key}.predictions do not cover each hold-out period exactly once")
            continue
        rmse = math.sqrt(sum(x * x for x in errs) / len(errs))
        mae = sum(abs(x) for x in errs) / len(errs)
        rec: dict[str, Any] = {"model": model, "rmse": rmse, "mae": mae, "n_test": len(errs)}
        for name, val in (("rmse", rmse), ("mae", mae)):
            stated = _num(ev.get(name))
            if stated is not None and not _within(stated, val, error_tolerance):
                reasons.append(
                    f"out_of_sample.{key}.{name} is {stated}; the predictions and the hold-out values give {val:.6g}"
                )
        if with_interval:
            share = covered / with_interval
            rec["interval_coverage"] = share
            stated_cov = _num(ev.get("coverage"))
            if stated_cov is not None and not _within(stated_cov, share, error_tolerance):
                reasons.append(f"out_of_sample.{key}.coverage is {stated_cov}; the intervals cover {share:.4g}")
        recomputed[key] = rec
    not_evaluated = [m for m in declared if m in models and m not in evaluated]
    if not_evaluated:
        reasons.append(f"model(s) {_names(not_evaluated)} have no out-of-sample evaluation on the hold-out")
    if not oos:
        reasons.append("out_of_sample is empty: a forecast is judged on the hold-out, not on the data it was fitted on")

    # Forecasts beyond the data, with intervals at the declared level.
    horizon, level = design.get("horizon"), design.get("interval_level")
    beyond = []
    for key, f in forecasts.items():
        pts = f.get("points") if isinstance(f, dict) else None
        if not isinstance(pts, list) or not pts:
            continue
        if _after((pts[0] or {}).get("period"), periods[-1]):
            beyond.append(key)
            if horizon is not None and len(pts) != horizon:
                reasons.append(f"forecasts.{key} has {len(pts)} periods; the declared horizon is {horizon}")
            if level is not None and _num(f.get("interval_level")) != float(level):
                reasons.append(
                    f"forecasts.{key}.interval_level is {f.get('interval_level')}; the declared level is {level}"
                )
    if not beyond:
        reasons.append(
            f"no forecast beyond the data (after {periods[-1]}) with its intervals: forecasts must include the "
            f"declared horizon of {horizon} periods"
        )

    # Each model's RMSE relative to the best baseline (below 1: better than the benchmark).
    base_rmse = [r["rmse"] for r in recomputed.values() if r["model"] in baselines]
    best = min(base_rmse) if base_rmse else None
    if best:
        for r in recomputed.values():
            r["relative_rmse"] = r["rmse"] / best
    (ws / FORECAST_CHECK_FILE).write_text(
        json.dumps(
            {
                "passed": not reasons,
                "holdout": {"start": hold_start, "end": hold_end, "n_periods": n_hold, "train_end": train_end},
                "best_baseline_rmse": best,
                "out_of_sample": recomputed,
                "problems": reasons,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    stats = {"evaluations": len(recomputed), "hold_out": f"{hold_start} to {hold_end}"}
    return CheckResult(not reasons, tuple(reasons), (), stats)
