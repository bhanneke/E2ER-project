"""The `reproduction` check: every number the comparer reports must be in the run's output.

The reproduction comparer (a model) reads the sandbox's output files and writes
``reproduction_report.json``: per result a level (reproduced, reproduced with
minor differences, not reproduced, could not be run) and, per compared number,
the published value, the reproduced value and the output file it came from.
This check redoes the arithmetic from the files themselves and fails when the
report says something the files do not:

  (a) each compared target exists in ``replication_plan.json`` and its
      published value is the plan's (the comparer cannot move the target);
  (b) each reproduced number is read again from the file the report names —
      the cell a ``locator`` points to in a CSV, or else a number in the file
      that rounds to the claimed value — and that file must be one the sandbox
      run wrote (``sandbox_log.json``), never a result shipped in the package;
  (c) the differences are recomputed, and the level must agree with them:
      "reproduced" needs every number equal at the published precision,
      "reproduced_minor" needs every relative difference within the tolerance
      and no change of sign, "could_not_run" carries no reproduced numbers;
  (d) every target of the plan is accounted for, compared or listed as
      unassessed with a reason.

It is the same idea as the numbers check for drafts: a model may describe and
judge, but every number it states is traced to a file by code. The verdict and
each recomputed value are written to ``reproduction_check.json``.
"""

from __future__ import annotations

import csv
import io
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

from .replication import LEVELS, PLAN_FILE, TARGET_LEVELS, CheckResult, load_plan
from .sandbox import LOG_FILE

REPORT_FILE = "reproduction_report.json"
CHECK_FILE = "reproduction_check.json"
DEFAULT_MINOR_REL_TOLERANCE = 0.10

_NUM = re.compile(r"(?<![\w.])[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?")
_TEXT_EXT = frozenset(
    {".csv", ".tsv", ".txt", ".json", ".md", ".log", ".tex", ".html", ".htm", ".out", ".Rout", ".xml"}
)
_EPS = 1e-9


def _decimals(text: str) -> int:
    """Decimal places of the first number in a printed value ('-0.012***' -> 3)."""
    m = _NUM.search(text.replace("−", "-").replace(",", ""))
    if not m:
        return 0
    token = m.group(0).lower().split("e")[0]
    return len(token.split(".", 1)[1]) if "." in token else 0


def _claimed_decimals(value: Any, printed: Any = None) -> int:
    if isinstance(printed, str) and printed.strip():
        return _decimals(printed)
    text = repr(float(value))
    if "e" in text or "E" in text:
        return 12
    return len(text.split(".", 1)[1].rstrip("0")) if "." in text else 0


def _equal_at(a: float, b: float, decimals: int) -> bool:
    return abs(a - b) <= 0.5 * 10 ** (-decimals) + _EPS * max(1.0, abs(b))


def _to_float(text: Any) -> float | None:
    if isinstance(text, bool):
        return None
    if isinstance(text, int | float):
        return float(text)
    if not isinstance(text, str):
        return None
    m = _NUM.search(text.replace("−", "-").replace(",", ""))
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


def _numbers_in(text: str) -> list[float]:
    out = []
    for tok in _NUM.findall(text.replace("−", "-")):
        try:
            out.append(float(tok))
        except ValueError:
            continue
    return out


def _cell(path: Path, locator: dict[str, Any]) -> tuple[float | None, str]:
    """The number in the CSV/TSV cell a locator names: ``{"row": {col: value, ...}, "column": col}``."""
    row_match = locator.get("row")
    column = locator.get("column")
    if not isinstance(row_match, dict) or not row_match or not isinstance(column, str):
        return None, "locator needs a row (column: value pairs) and a column"
    text = path.read_text(encoding="utf-8", errors="replace")
    dialect = "excel-tab" if path.suffix.lower() == ".tsv" else "excel"
    rows = list(csv.DictReader(io.StringIO(text), dialect=dialect))
    if rows and column not in rows[0]:
        return None, f"column {column!r} is not in {path.name}"

    def exact(v: Any) -> float | None:
        if isinstance(v, bool):
            return None
        try:
            return float(str(v).strip().replace("\u2212", "-"))
        except ValueError:
            return None

    def matches(row: dict[str, str]) -> bool:
        for k, want in row_match.items():
            have = row.get(k)
            if have is None:
                return False
            if str(have).strip() == str(want).strip():
                continue
            hv, wv = exact(have), exact(want)
            if hv is None or wv is None or not math.isclose(hv, wv, rel_tol=1e-9, abs_tol=1e-12):
                return False
        return True

    hits = [r for r in rows if matches(r)]
    if len(hits) != 1:
        return None, f"locator matches {len(hits)} rows of {path.name}, not exactly one"
    value = _to_float(hits[0].get(column))
    if value is None:
        return None, f"the located cell of {path.name} holds no number ({hits[0].get(column)!r})"
    return value, ""


def _recompute(run_dir: Path, source: dict[str, Any], claimed: float, printed: Any) -> tuple[float | None, str]:
    rel = source.get("file")
    if not isinstance(rel, str) or not rel or rel.startswith("/") or ".." in rel.split("/"):
        return None, "names no output file"
    path = run_dir / rel
    if not path.is_file():
        return None, f"{rel} does not exist in the run's output"
    if path.suffix not in _TEXT_EXT and path.suffix.lower() not in _TEXT_EXT:
        return None, f"{rel} is not a text output the check can read"
    locator = source.get("locator")
    if isinstance(locator, dict) and path.suffix.lower() in (".csv", ".tsv"):
        return _cell(path, locator)
    decimals = _claimed_decimals(claimed, printed)
    found = [
        x for x in _numbers_in(path.read_text(encoding="utf-8", errors="replace")) if _equal_at(x, claimed, decimals)
    ]
    if not found:
        return None, f"no number in {rel} rounds to {claimed}"
    return min(found, key=lambda x: abs(x - claimed)), ""


def check_reproduction(workspace: Path, *, minor_rel_tolerance: float = DEFAULT_MINOR_REL_TOLERANCE) -> CheckResult:
    workspace = Path(workspace)
    plan, why = load_plan(workspace)
    if plan is None:
        return CheckResult(False, (why,))
    report_path = workspace / REPORT_FILE
    log_path = workspace / LOG_FILE
    if not report_path.is_file():
        return CheckResult(False, (f"{REPORT_FILE} is missing: the reproduction comparer must write it",))
    if not log_path.is_file():
        return CheckResult(False, (f"{LOG_FILE} is missing: nothing was run, so nothing can be compared",))
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        log = json.loads(log_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return CheckResult(False, (f"{REPORT_FILE} or {LOG_FILE} is not valid JSON: {e}",))
    if not isinstance(report, dict) or not isinstance(report.get("results"), list):
        return CheckResult(False, (f"{REPORT_FILE} must be an object with a results list",))

    targets = {t["id"]: t for t in plan.get("targets") or [] if isinstance(t, dict) and isinstance(t.get("id"), str)}
    run_dir = workspace / str(log.get("run_dir") or "sandbox/run")
    written = {o["path"] for o in log.get("outputs") or [] if o.get("written_by_run")}
    reasons: list[str] = []
    checked: list[dict[str, Any]] = []
    covered: set[str] = set()
    by_level: dict[int, Counter[str]] = {tier: Counter() for tier in TARGET_LEVELS}

    for r_i, res in enumerate(report["results"]):
        rid = res.get("id") if isinstance(res, dict) else None
        where = f"result {rid or r_i}"
        if not isinstance(res, dict):
            reasons.append(f"{where} is not an object")
            continue
        level = res.get("level")
        if level not in LEVELS:
            reasons.append(f"{where}: level {level!r} is not one of {', '.join(LEVELS)}")
            continue
        tier = res.get("target_level")
        if tier not in TARGET_LEVELS:
            reasons.append(f"{where}: target_level must be 1 (package result files) or 2 (the paper)")
            continue
        by_level[tier][level] += 1
        comps = res.get("comparisons") or []
        if level != "could_not_run" and not comps:
            reasons.append(f"{where}: level {level} compares no number")
        for comp in comps:
            tid = comp.get("target_id") if isinstance(comp, dict) else None
            cw = f"{where}, target {tid}"
            if not isinstance(tid, str) or tid not in targets:
                reasons.append(f"{cw}: not a target of {PLAN_FILE}")
                continue
            covered.add(tid)
            target = targets[tid]
            if target.get("level") != tier:
                reasons.append(f"{cw}: a level-{target.get('level')} target reported under a level-{tier} result")
                continue
            published = float(target["value"])
            if not isinstance(comp.get("published"), int | float) or not math.isclose(
                float(comp["published"]), published, rel_tol=1e-12, abs_tol=1e-15
            ):
                reasons.append(f"{cw}: published value {comp.get('published')!r} is not the plan's {published}")
            claimed = comp.get("reproduced")
            entry: dict[str, Any] = {
                "result": rid,
                "target_id": tid,
                "target_level": tier,
                "level": level,
                "published": published,
            }
            if level == "could_not_run":
                if claimed is not None:
                    reasons.append(f"{cw}: 'could_not_run' but a reproduced number {claimed!r} is claimed")
                checked.append({**entry, "reproduced": None, "ok": claimed is None})
                continue
            if isinstance(claimed, bool) or not isinstance(claimed, int | float):
                reasons.append(f"{cw}: level {level} needs a reproduced number")
                continue
            source = dict(comp["source"]) if isinstance(comp.get("source"), dict) else {}
            rel = str(source.get("file") or "")
            if tier == 1:
                # Level 1 asks whether the code rebuilds the package's own result
                # file: the number is read from the rebuilt copy of that file.
                shipped = (target.get("source") or {}).get("file")
                if rel != shipped:
                    reasons.append(f"{cw}: a level-1 number is read from the rebuilt {shipped}, not {rel or 'no file'}")
                    checked.append({**entry, "claimed": claimed, "file": rel, "ok": False})
                    continue
                source.setdefault("locator", (target.get("source") or {}).get("locator"))
            if rel and rel not in written:
                reasons.append(
                    f"{cw}: {rel} is not a file the sandbox run wrote (a shipped result is not a reproduction)"
                )
                checked.append({**entry, "claimed": claimed, "file": rel, "ok": False})
                continue
            value, problem = _recompute(run_dir, source, float(claimed), comp.get("reproduced_printed"))
            if value is None:
                reasons.append(f"{cw}: claimed {claimed} {problem}")
                checked.append({**entry, "claimed": claimed, "file": rel, "ok": False})
                continue
            decimals = _claimed_decimals(claimed, comp.get("reproduced_printed"))
            if not _equal_at(value, float(claimed), decimals):
                reasons.append(f"{cw}: the output holds {value}, not the claimed {claimed}")
            dp = _decimals(str(target.get("reported") or ""))
            diff = value - published
            rel_diff = abs(diff) / abs(published) if published else (0.0 if diff == 0 else math.inf)
            same = _equal_at(value, published, dp)
            sign_flip = (value > 0) != (published > 0) and not same and value != 0 and published != 0
            claimed_diff = comp.get("abs_diff")
            if isinstance(claimed_diff, int | float) and not isinstance(claimed_diff, bool):
                if not math.isclose(
                    float(claimed_diff), diff, rel_tol=1e-3, abs_tol=0.5 * 10 ** (-max(dp, decimals)) + _EPS
                ):
                    reasons.append(f"{cw}: abs_diff {claimed_diff} is not reproduced minus published ({diff:.6g})")
            checked.append(
                {
                    **entry,
                    "claimed": claimed,
                    "recomputed": value,
                    "file": rel,
                    "abs_diff": diff,
                    "rel_diff": rel_diff,
                    "equal_at_published_precision": same,
                    "sign_change": sign_flip,
                    "ok": True,
                }
            )
            if level == "reproduced" and not same:
                reasons.append(f"{cw}: 'reproduced' but {value} differs from the published {target.get('reported')}")
            if level == "reproduced_minor" and (rel_diff > minor_rel_tolerance or sign_flip):
                reasons.append(
                    f"{cw}: 'reproduced_minor' but the difference ({rel_diff:.1%}"
                    f"{', sign change' if sign_flip else ''}) exceeds the minor tolerance of {minor_rel_tolerance:.0%}"
                )

    unassessed = {u.get("target_id") for u in report.get("unassessed") or [] if isinstance(u, dict) and u.get("reason")}
    for tier in TARGET_LEVELS:
        tier_ids = {t for t, v in targets.items() if v.get("level") == tier}
        missing = sorted(tier_ids - covered - unassessed)
        if missing:
            shown = ", ".join(missing[:10]) + (f" and {len(missing) - 10} more" if len(missing) > 10 else "")
            reasons.append(f"level-{tier} target(s) neither compared nor listed as unassessed with a reason: {shown}")

    stats: dict[str, Any] = {
        "results": len(report["results"]),
        "numbers_checked": sum(1 for c in checked if "recomputed" in c),
        "targets": len(targets),
        "unassessed": len(unassessed & set(targets)),
    }
    for tier in TARGET_LEVELS:
        tier_checked = [c for c in checked if c.get("target_level") == tier]
        stats[f"level_{tier}"] = {
            "targets": sum(1 for v in targets.values() if v.get("level") == tier),
            "numbers_checked": sum(1 for c in tier_checked if "recomputed" in c),
            "results": dict(by_level[tier]),
        }
    doc = {
        "passed": not reasons,
        "reasons": reasons,
        "stats": stats,
        "checked": checked,
        "minor_rel_tolerance": minor_rel_tolerance,
    }
    (workspace / CHECK_FILE).write_text(json.dumps(doc, indent=2, default=str) + "\n", encoding="utf-8")
    flat = {k: v for k, v in stats.items() if not isinstance(v, dict)}
    for tier in TARGET_LEVELS:
        flat[f"level_{tier}_numbers_checked"] = stats[f"level_{tier}"]["numbers_checked"]
    return CheckResult(not reasons, tuple(reasons[:20]), stats=flat)


def check_report(workspace: Path) -> list[str]:
    """Contract check for the comparer: the report parses and uses the protocol's levels."""
    path = Path(workspace) / REPORT_FILE
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return [f"{REPORT_FILE} cannot be read: {e}"]
    if not isinstance(report, dict) or not isinstance(report.get("results"), list):
        return [f"{REPORT_FILE} must be an object with a results list"]
    errs = []
    for i, res in enumerate(report["results"]):
        if not isinstance(res, dict) or res.get("level") not in LEVELS:
            errs.append(f"results[{i}].level must be one of {', '.join(LEVELS)}")
        elif res.get("target_level") not in TARGET_LEVELS:
            errs.append(f"results[{i}].target_level must be 1 (package result files) or 2 (the paper)")
        elif not res.get("reason"):
            errs.append(f"results[{i}] needs a reason for its level")
    return errs
