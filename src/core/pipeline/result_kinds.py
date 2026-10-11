"""What a study's results file must contain, by the kind of results its template declares.

Until 0.16.0 every study had to report a regression: the estimation contract
asked ``estimation_results.json`` for a ``coefficients`` block, t = estimate /
se, and a ``main`` entry with the declared fixed effects and clustering. That
is right for an economics template and wrong for an astronomy, earth-science
or text study, which reports distributions, forecasts, spatial statistics or
term frequencies. A template now names the kind of results it produces
(``results = "..."`` in the template file, default ``regression``), and the
estimation check, the number check and the analysis specialist's skills
follow it.

Every kind writes the same file, ``estimation_results.json``, by the same
script (``run_estimation.py``), so the steps that rerun, export and reproduce a
study work unchanged. A results file of a kind other than ``regression``
names its kind at the top (``"result_kind": "descriptive"``), so the file says
what contract it follows even outside the run (``e2er verify`` on an export).

The schemas are documented in the skills named below
(``skills/files/data/<kind>-results-schema.md``); the checks here are the
deterministic half: the structure each kind requires, and the relations its
numbers must satisfy (a quartile between the minimum and the maximum, a
forecast inside its interval, a p-value that follows from z, a frequency per
10,000 tokens that follows from the count).
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: The results file every kind writes (the analysis script's output).
RESULTS_FILE = "estimation_results.json"
#: The key that names a results file's kind (absent: regression).
KIND_KEY = "result_kind"
DEFAULT_KIND = "regression"


def _num(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, int | float):
        return None
    x = float(v)
    return x if math.isfinite(x) else None


def _count(v: Any) -> int | None:
    """A whole, non-negative count (``12`` or ``12.0``), else None."""
    x = _num(v)
    if x is None or x < 0 or x != int(x):
        return None
    return int(x)


def _close(a: float, b: float, rel: float = 0.01, abs_: float = 1e-9) -> bool:
    return abs(a - b) <= max(abs_, rel * max(abs(a), abs(b)))


def _table(doc: dict[str, Any], key: str, problems: list[str], what: str) -> dict[str, Any]:
    """``doc[key]`` as a non-empty object of named entries, or a problem."""
    value = doc.get(key)
    if not isinstance(value, dict) or not value:
        problems.append(f"'{key}' must be a non-empty object of {what}")
        return {}
    bad = [k for k, v in value.items() if not isinstance(v, dict)]
    if bad:
        problems.append(f"'{key}' entries must be objects: {', '.join(bad[:5])}")
    return {k: v for k, v in value.items() if isinstance(v, dict)}


# ── descriptive ─────────────────────────────────────────────────────────────

#: Order statistics that must be non-decreasing when stated.
_ORDER = ("min", "p5", "p10", "p25", "median", "p75", "p90", "p95", "max")
_DESCRIPTIVE_STATS = frozenset({"mean", "sd", "median", "min", "max", "p25", "p75", "share", "count"})


def _check_distribution(name: str, dist: dict[str, Any], problems: list[str]) -> None:
    bins = dist.get("bins")
    cats = dist.get("categories")
    if isinstance(bins, list) and bins:
        total = 0
        prev_upper: float | None = None
        for i, b in enumerate(bins):
            lo, hi = _num((b or {}).get("lower")), _num((b or {}).get("upper"))
            c = _count((b or {}).get("count"))
            if lo is None or hi is None or c is None or not lo < hi:
                problems.append(
                    f"distributions.{name}.bins[{i}] needs numeric lower < upper and a whole non-negative count"
                )
                return
            if prev_upper is not None and lo < prev_upper - 1e-12:
                problems.append(f"distributions.{name}.bins overlap or are out of order at bin {i}")
                return
            prev_upper = hi
            total += c
    elif isinstance(cats, list) and cats:
        total = 0
        for i, c in enumerate(cats):
            n = _count((c or {}).get("count"))
            if not str((c or {}).get("category") or "").strip() or n is None:
                problems.append(f"distributions.{name}.categories[{i}] needs a 'category' and a whole 'count'")
                return
            total += n
    else:
        problems.append(f"distributions.{name} needs 'bins' (lower, upper, count) or 'categories' (category, count)")
        return
    n = _count(dist.get("n"))
    if n is not None and total != n:
        problems.append(f"distributions.{name}: the counts add up to {total}, not to its n = {n}")


def check_descriptive(doc: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    sample = doc.get("sample")
    if not isinstance(sample, dict) or _count(sample.get("n_observations")) in (None, 0):
        problems.append("'sample.n_observations' must be the whole number of observations described (> 0)")
        n_sample = None
    else:
        n_sample = _count(sample.get("n_observations"))
    stats = _table(doc, "statistics", problems, "variables, each with its summary statistics")
    for var, s in stats.items():
        n = _count(s.get("n"))
        if n is None:
            problems.append(f"statistics.{var} needs 'n', the number of non-missing values")
        elif n_sample is not None and n > n_sample:
            problems.append(f"statistics.{var}.n = {n} exceeds sample.n_observations = {n_sample}")
        if not any(_num(s.get(k)) is not None for k in _DESCRIPTIVE_STATS):
            problems.append(f"statistics.{var} states no statistic (mean, sd, median, min, max, quartiles, share)")
        sd = _num(s.get("sd"))
        if sd is not None and sd < 0:
            problems.append(f"statistics.{var}.sd is negative")
        ordered = [(k, _num(s.get(k))) for k in _ORDER if _num(s.get(k)) is not None]
        for (k1, v1), (k2, v2) in zip(ordered, ordered[1:]):
            if v1 is not None and v2 is not None and v1 > v2 + 1e-12:
                problems.append(f"statistics.{var}: {k1} ({v1}) is above {k2} ({v2})")
                break
        mean, lo, hi = _num(s.get("mean")), _num(s.get("min")), _num(s.get("max"))
        if mean is not None and lo is not None and hi is not None and not lo - 1e-12 <= mean <= hi + 1e-12:
            problems.append(f"statistics.{var}.mean ({mean}) lies outside [min, max]")
        share = _num(s.get("share"))
        if share is not None and not 0 <= share <= 1:
            problems.append(f"statistics.{var}.share must lie between 0 and 1")
    dists = _table(doc, "distributions", problems, "distributions (bins or categories with counts)")
    for name, d in dists.items():
        _check_distribution(name, d, problems)
    figures = doc.get("figures")
    if not isinstance(figures, list) or not figures or not all(isinstance(f, str) and f.strip() for f in figures):
        problems.append("'figures' must list the figure_spec.json filenames that show the distributions")
    return problems


# ── time series ─────────────────────────────────────────────────────────────


def check_timeseries(doc: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    series = doc.get("series")
    if not isinstance(series, dict) or not str(series.get("frequency") or "").strip():
        problems.append("'series' must name the series and its 'frequency', with start, end and n_observations")
    elif _count(series.get("n_observations")) in (None, 0):
        problems.append("'series.n_observations' must be the whole number of periods (> 0)")
    models = _table(doc, "models", problems, "fitted models")
    for key, m in models.items():
        if not str(m.get("model") or "").strip():
            problems.append(f"models.{key} needs 'model', the model fitted (e.g. 'ARIMA(1,1,1)')")
        fit = m.get("fit")
        if not isinstance(fit, dict) or not any(_num(v) is not None for v in fit.values()):
            problems.append(f"models.{key}.fit needs at least one fit statistic (aic, bic, log_likelihood, sigma2)")
    forecasts = _table(doc, "forecasts", problems, "forecasts with intervals")
    for key, f in forecasts.items():
        if f.get("model") not in models:
            problems.append(f"forecasts.{key}.model must name an entry of 'models'")
        level = _num(f.get("interval_level"))
        if level is None or not 0 < level < 1:
            problems.append(f"forecasts.{key}.interval_level must be a share between 0 and 1 (e.g. 0.95)")
        points = f.get("points")
        if not isinstance(points, list) or not points:
            problems.append(f"forecasts.{key}.points must list the forecast periods")
            continue
        for i, p in enumerate(points):
            fc, lo, hi = _num((p or {}).get("forecast")), _num((p or {}).get("lower")), _num((p or {}).get("upper"))
            if fc is None or lo is None or hi is None or not str((p or {}).get("period") or "").strip():
                problems.append(f"forecasts.{key}.points[{i}] needs period, forecast, lower and upper")
                break
            if not lo - 1e-12 <= fc <= hi + 1e-12:
                problems.append(f"forecasts.{key}.points[{i}]: the forecast {fc} lies outside [{lo}, {hi}]")
                break
        horizon = _count(f.get("horizon"))
        if horizon is not None and horizon != len(points):
            problems.append(f"forecasts.{key}: horizon {horizon} but {len(points)} point(s)")
    oos = _table(doc, "out_of_sample", problems, "out-of-sample evaluations")
    for key, e in oos.items():
        if e.get("model") not in models:
            problems.append(f"out_of_sample.{key}.model must name an entry of 'models'")
        if _count(e.get("n_test")) in (None, 0):
            problems.append(f"out_of_sample.{key}.n_test must be the whole number of test periods (> 0)")
        rmse, mae = _num(e.get("rmse")), _num(e.get("mae"))
        if rmse is None or mae is None:
            problems.append(f"out_of_sample.{key} needs 'rmse' and 'mae'")
        elif rmse < 0 or mae < 0:
            problems.append(f"out_of_sample.{key}: errors cannot be negative")
        elif mae > rmse * (1 + 1e-6) + 1e-12:
            problems.append(f"out_of_sample.{key}: mae {mae} exceeds rmse {rmse}, which no set of errors allows")
    return problems


# ── spatial ─────────────────────────────────────────────────────────────────


def check_spatial(doc: dict[str, Any]) -> list[str]:
    from .statistics import normal_two_sided_p

    problems: list[str] = []
    units = doc.get("units")
    n_units = _count(units.get("n_units")) if isinstance(units, dict) else None
    if not isinstance(units, dict) or not str(units.get("type") or "").strip() or n_units in (None, 0):
        problems.append("'units' must name the spatial unit ('type') and the number of units ('n_units' > 0)")
        n_units = None
    stats = _table(doc, "spatial_statistics", problems, "spatial statistics (e.g. Moran's I)")
    for key, s in stats.items():
        missing = [k for k in ("statistic", "variable", "weights") if not str(s.get(k) or "").strip()]
        if missing:
            problems.append(f"spatial_statistics.{key} needs {', '.join(missing)}")
        est = _num(s.get("estimate"))
        if est is None:
            problems.append(f"spatial_statistics.{key} needs a numeric 'estimate'")
            continue
        is_moran = "moran" in str(s.get("statistic") or "").lower()
        expected = _num(s.get("expected"))
        if is_moran and expected is not None and n_units and n_units > 1:
            if not _close(expected, -1.0 / (n_units - 1), rel=0.01, abs_=1e-6):
                problems.append(
                    f"spatial_statistics.{key}.expected {expected} is not -1/(n_units - 1) = {-1.0 / (n_units - 1):.6g}"
                )
        z, p = _num(s.get("z")), _num(s.get("p_value"))
        method = str(s.get("p_value_method") or "normal").lower()
        if p is not None and not 0 <= p <= 1:
            problems.append(f"spatial_statistics.{key}.p_value must lie between 0 and 1")
        elif z is not None and p is not None and method in ("normal", "z", "analytic", ""):
            want = normal_two_sided_p(z)
            if abs(want - p) > 0.005:
                problems.append(
                    f"spatial_statistics.{key}: p = {p} does not follow from z = {z} "
                    f"(two-sided normal p = {want:.4f}); "
                    "name a permutation p-value in 'p_value_method'"
                )
    maps = doc.get("maps")
    if not isinstance(maps, list) or not maps:
        problems.append("'maps' must list the map specifications (id, variable, classification)")
    else:
        for i, m in enumerate(maps):
            if (
                not isinstance(m, dict)
                or not str(m.get("id") or "").strip()
                or not str(m.get("variable") or "").strip()
            ):
                problems.append(f"maps[{i}] needs an 'id' and the 'variable' it shows")
                break
    return problems


# ── text ────────────────────────────────────────────────────────────────────


def check_text(doc: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    corpus = doc.get("corpus")
    n_tokens = None
    if not isinstance(corpus, dict):
        problems.append("'corpus' must state n_documents, n_tokens and n_types")
    else:
        n_docs, n_tokens, n_types = (_count(corpus.get(k)) for k in ("n_documents", "n_tokens", "n_types"))
        if n_docs in (None, 0) or n_tokens in (None, 0) or n_types in (None, 0):
            problems.append("'corpus' needs whole numbers n_documents, n_tokens and n_types (each > 0)")
        elif n_types > n_tokens:
            problems.append(f"corpus.n_types {n_types} exceeds n_tokens {n_tokens}")
    tf = _table(doc, "term_frequencies", problems, "term-frequency lists (per corpus or group)")
    for group, entry in tf.items():
        group_tokens = _count(entry.get("n_tokens")) or n_tokens
        terms = entry.get("terms")
        if not isinstance(terms, list) or not terms:
            problems.append(f"term_frequencies.{group}.terms must list terms with their counts")
            continue
        total = 0
        for i, t in enumerate(terms):
            c = _count((t or {}).get("count"))
            if c is None or not str((t or {}).get("term") or "").strip():
                problems.append(f"term_frequencies.{group}.terms[{i}] needs a 'term' and a whole 'count'")
                break
            total += c
            per = _num((t or {}).get("per_10k"))
            if per is not None and group_tokens and not _close(per, c / group_tokens * 10_000, rel=0.01, abs_=0.006):
                problems.append(
                    f"term_frequencies.{group}.terms[{i}] ({t.get('term')}): per_10k {per} is not "
                    f"count / n_tokens x 10,000 = {c / group_tokens * 10_000:.4g}"
                )
                break
        if group_tokens and total > group_tokens:
            problems.append(
                f"term_frequencies.{group}: the counts add up to {total}, more than its {group_tokens} tokens"
            )
    models = _table(doc, "models", problems, "text-model outputs (e.g. keyness, topics)")
    for key, m in models.items():
        if not str(m.get("method") or "").strip():
            problems.append(f"models.{key} needs 'method'")
        outputs = m.get("outputs")
        if not isinstance(outputs, dict | list) or not outputs:
            problems.append(f"models.{key}.outputs must hold the model's results")
    return problems


# ── the kinds ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ResultKind:
    name: str
    #: In plain words, for the dashboard and the specialists' context.
    label: str
    #: The skill that documents the results schema of this kind.
    schema_skill: str
    #: Method skills the analysis specialist reads for this kind.
    method_skills: tuple[str, ...]
    #: The files the number check traces the paper's numbers to.
    number_sources: tuple[str, ...]
    #: Whether a template of this kind is causal unless it says otherwise.
    causal_by_default: bool
    #: Structure and consistency problems of a parsed results file (None: the regression checks).
    check: Callable[[dict[str, Any]], list[str]] | None = None


#: The number-check sources of the regression contract, as before 0.16.0.
_REGRESSION_SOURCES = (
    "summary_statistics.json",
    "estimation_results.json",
    "robustness_results.json",
    "figure_spec.json",
    # The field map's results (src/modules/fieldmap/workflow.py), written by code.
    "field_map_results.json",
)
_NEUTRAL_SOURCES = ("summary_statistics.json", "estimation_results.json", "robustness_results.json", "figure_spec.json")

KINDS: dict[str, ResultKind] = {
    "regression": ResultKind(
        name="regression",
        label="regression estimates",
        schema_skill="econometrics/estimation-results-schema",
        method_skills=(),
        number_sources=_REGRESSION_SOURCES,
        causal_by_default=True,
    ),
    "descriptive": ResultKind(
        name="descriptive",
        label="descriptive statistics and distributions",
        schema_skill="data/descriptive-results-schema",
        method_skills=("data/cleaning", "data/figure-spec"),
        # The data check's report (data_quality.py): rows, missing values and units the paper states.
        number_sources=(*_NEUTRAL_SOURCES, "data_quality.json"),
        causal_by_default=False,
        check=check_descriptive,
    ),
    "timeseries": ResultKind(
        name="timeseries",
        label="time-series models, forecasts and out-of-sample errors",
        schema_skill="data/timeseries-results-schema",
        method_skills=("econometrics/time-series", "data/figure-spec"),
        # The forecast check's recomputed errors (forecast_checks.py), e.g. RMSE relative to the baseline.
        number_sources=(*_NEUTRAL_SOURCES, "forecast_check.json"),
        causal_by_default=False,
        check=check_timeseries,
    ),
    "spatial": ResultKind(
        name="spatial",
        label="spatial statistics and maps",
        schema_skill="data/spatial-results-schema",
        method_skills=("data/figure-spec",),
        number_sources=_NEUTRAL_SOURCES,
        causal_by_default=False,
        check=check_spatial,
    ),
    "text": ResultKind(
        name="text",
        label="corpus statistics, term frequencies and text-model outputs",
        schema_skill="data/text-results-schema",
        method_skills=("data/figure-spec",),
        number_sources=_NEUTRAL_SOURCES,
        causal_by_default=False,
        check=check_text,
    ),
}

RESULT_KINDS: tuple[str, ...] = tuple(KINDS)


def get(name: str | None) -> ResultKind:
    return KINDS.get(name or DEFAULT_KIND, KINDS[DEFAULT_KIND])


def declared_kind(data: Any) -> str | None:
    """The kind a parsed results file names (``result_kind``), None when it names none or an unknown one."""
    if isinstance(data, dict):
        k = data.get(KIND_KEY)
        if isinstance(k, str) and k in KINDS:
            return k
    return None


def file_kind(workspace: Path, relative: str = RESULTS_FILE) -> str | None:
    """The kind the workspace's results file names, None when absent or unreadable."""
    try:
        return declared_kind(json.loads((Path(workspace) / relative).read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return None


def active_kind(workspace: Path | None = None) -> str:
    """The kind of results this study produces.

    The running template's ``results`` when a template is active; otherwise
    what the results file names (an export checked outside its run); else
    regression.
    """
    from .components import active

    spec = active()
    if spec is not None:
        return spec.results
    if workspace is not None:
        found = file_kind(workspace)
        if found:
            return found
    return DEFAULT_KIND


def active_causal() -> bool:
    """Whether the running template asks for an identification strategy (True without a template)."""
    from .components import active

    spec = active()
    return True if spec is None else spec.causal


def figure_problems(data: dict[str, Any], workspace: Path) -> list[str]:
    """Figures the results name (``figures``) that ``figure_spec.json`` does not declare."""
    named = [f for f in data.get("figures") or [] if isinstance(f, str) and f.strip()]
    if not named:
        return []
    try:
        spec = json.loads((Path(workspace) / "figure_spec.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [f"'figures' names {', '.join(named)} but there is no readable figure_spec.json"]
    declared = {
        str(f.get("filename"))
        for f in (spec.get("figures") if isinstance(spec, dict) else None) or []
        if isinstance(f, dict) and f.get("filename")
    }
    missing = [f for f in named if f not in declared]
    if missing:
        return [f"'figures' names {', '.join(missing)}, which figure_spec.json does not declare"]
    return []


def check_results(kind: str, data: Any, workspace: Path | None = None) -> list[str]:
    """The problems of a parsed results file against the contract of ``kind`` (not for regression).

    With ``workspace``, also the figures it names against ``figure_spec.json``.
    """
    k = get(kind)
    if k.check is None:
        return []
    if not isinstance(data, dict):
        return ["the results file must be a JSON object"]
    problems: list[str] = []
    named = data.get(KIND_KEY)
    if named != k.name:
        problems.append(f'the results file must name its kind at the top: "{KIND_KEY}": "{k.name}"')
    problems += k.check(data)
    if workspace is not None:
        problems += figure_problems(data, workspace)
    return problems
