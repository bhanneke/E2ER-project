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
      unassessed with a reason;
  (e) ``reproduction_report.md``, the report the researcher reads, agrees
      with the JSON: e2er writes its counts and environment section from the
      JSON, and the prose's counts, labels and package versions are compared
      with it (``reproduction_md``).

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
from .reproduction_md import MD_FILE, markdown_problems, render_summary, with_summary
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


def label_for(
    value: float,
    published: float,
    published_decimals: int,
    minor_rel_tolerance: float,
    *,
    target_level: int = 2,
) -> dict[str, Any]:
    """The level one compared number earns, and the differences behind it.

    "reproduced": equal to the target (``equal_to_target``: at full precision
    for a package cell, at the printed precision for the paper);
    "reproduced_minor": relative difference within the tolerance and no sign
    change; otherwise "not_reproduced". The pipeline's check and ``e2er
    verify`` both call this, so the thresholds cannot drift apart.
    """
    diff = value - published
    rel_diff = abs(diff) / abs(published) if published else (0.0 if diff == 0 else math.inf)
    same = equal_to_target(value, published, target_level, published_decimals)
    sign_flip = (value > 0) != (published > 0) and not same and value != 0 and published != 0
    label = label_from(same, rel_diff, sign_flip, minor_rel_tolerance)
    return {"label": label, "abs_diff": diff, "rel_diff": rel_diff, "same": same, "sign_flip": sign_flip}


def _summary_problems(
    report: dict[str, Any], checked: list[dict[str, Any]], by_level: dict[int, Counter[str]]
) -> tuple[list[str], dict[str, Any]]:
    """Does the report's summary state the counts the check recomputed?

    A summary may count compared numbers by their label or results by their
    level; either basis is accepted when every count agrees, and the one that
    agrees is recorded.
    """
    summary = report.get("summary")
    if not isinstance(summary, dict):
        return [], {}
    numbers: dict[int, Counter[str]] = {tier: Counter() for tier in TARGET_LEVELS}
    for c in checked:
        tier = c.get("target_level")
        lab = c.get("recomputed_label") or ("could_not_run" if c.get("level") == "could_not_run" else None)
        if tier in numbers and lab:
            numbers[tier][lab] += 1
    problems: list[str] = []
    bases: dict[str, Any] = {}
    for tier in TARGET_LEVELS:
        stated = summary.get(f"level_{tier}")
        if not isinstance(stated, dict):
            continue
        want = {
            lv: int(v) for lv, v in stated.items() if lv in LEVELS and isinstance(v, int) and not isinstance(v, bool)
        }
        as_numbers = {lv: numbers[tier].get(lv, 0) for lv in LEVELS}
        as_results = {lv: by_level[tier].get(lv, 0) for lv in LEVELS}
        full = {lv: want.get(lv, 0) for lv in LEVELS}
        if full == as_numbers:
            bases[f"level_{tier}"] = {"counts": "compared numbers", **as_numbers}
        elif full == as_results:
            bases[f"level_{tier}"] = {"counts": "results", **as_results}
        else:
            shown = ", ".join(f"{as_numbers[lv]} {lv}" for lv in LEVELS if as_numbers[lv])
            problems.append(
                f"summary.level_{tier} {', '.join(f'{v} {k}' for k, v in want.items() if v) or 'is empty'}: "
                f"the recomputed labels give {shown or 'nothing'} (numbers) and "
                f"{', '.join(f'{as_results[lv]} {lv}' for lv in LEVELS if as_results[lv]) or 'nothing'} (results)"
            )
    return problems, bases


def evaluate(
    plan: dict[str, Any],
    report: Any,
    log: dict[str, Any],
    run_dir: Path,
    *,
    minor_rel_tolerance: float = DEFAULT_MINOR_REL_TOLERANCE,
) -> dict[str, Any]:
    """Recompute a reproduction report from the run's output files.

    The one implementation behind the pipeline's check (``check_reproduction``)
    and ``e2er verify``'s reproduction check. Returns the document written to
    ``reproduction_check.json``: passed, reasons, stats, every checked number
    with its recomputed value and label, and the tolerance used.
    """
    if not isinstance(report, dict) or not isinstance(report.get("results"), list):
        return {"passed": False, "reasons": [f"{REPORT_FILE} must be an object with a results list"], "stats": {}}
    targets = {t["id"]: t for t in plan.get("targets") or [] if isinstance(t, dict) and isinstance(t.get("id"), str)}
    written = {o["path"] for o in log.get("outputs") or [] if isinstance(o, dict) and o.get("written_by_run")}
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
        result_expected: list[str] = []
        result_equal: list[bool] = []
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
            lab = label_for(value, published, dp, minor_rel_tolerance, target_level=tier)
            diff = lab["abs_diff"]
            result_expected.append(lab["label"])
            result_equal.append(lab["same"])
            claimed_diff = comp.get("abs_diff")
            if isinstance(claimed_diff, int | float) and not isinstance(claimed_diff, bool):
                if not math.isclose(
                    float(claimed_diff), diff, rel_tol=1e-3, abs_tol=0.5 * 10 ** (-max(dp, decimals)) + _EPS
                ):
                    reasons.append(f"{cw}: abs_diff {claimed_diff} is not reproduced minus published ({diff:.6g})")
            stated_label = comp.get("label")
            if stated_label is not None and stated_label != lab["label"]:
                why = _why(lab["label"], lab["rel_diff"], lab["sign_flip"], minor_rel_tolerance)
                reasons.append(f"{cw}: labelled {stated_label!r}, but the numbers make it {lab['label']!r} ({why})")
            checked.append(
                {
                    **entry,
                    "claimed": claimed,
                    "recomputed": value,
                    "file": rel,
                    "abs_diff": diff,
                    "rel_diff": lab["rel_diff"],
                    "equal_to_target": lab["same"],
                    "sign_change": lab["sign_flip"],
                    "recomputed_label": lab["label"],
                    "ok": True,
                }
            )
            if level == "reproduced" and lab["label"] != "reproduced":
                reasons.append(f"{cw}: 'reproduced' but {value} differs from the published {target.get('reported')}")
            if level == "reproduced_minor" and lab["label"] == "not_reproduced":
                reasons.append(
                    f"{cw}: 'reproduced_minor' but the difference ({lab['rel_diff']:.1%}"
                    f"{', sign change' if lab['sign_flip'] else ''}) exceeds the minor tolerance "
                    f"of {minor_rel_tolerance:.0%}"
                )

        # The result's label is its worst number's, by the protocol's thresholds.
        if result_expected and level != "could_not_run":
            worst = max(result_expected, key=LEVELS.index)
            if level != worst:
                reasons.append(f"{where}: labelled {level!r}, but its worst number makes it {worst!r}")
        for text in [res.get("reason"), *[c.get("reason") for c in comps if isinstance(c, dict)]]:
            reasons += [f"{where}: {p}" for p in reason_text_problems(text, result_equal)]

    reasons += check_environment(report, log)
    unassessed = {u.get("target_id") for u in report.get("unassessed") or [] if isinstance(u, dict) and u.get("reason")}
    for tier in TARGET_LEVELS:
        tier_ids = {t for t, v in targets.items() if v.get("level") == tier}
        missing = sorted(tier_ids - covered - unassessed)
        if missing:
            shown = ", ".join(missing[:10]) + (f" and {len(missing) - 10} more" if len(missing) > 10 else "")
            reasons.append(f"level-{tier} target(s) neither compared nor listed as unassessed with a reason: {shown}")

    summary_problems, summary_basis = _summary_problems(report, checked, by_level)
    reasons += summary_problems

    stats: dict[str, Any] = {
        "results": len(report["results"]),
        "numbers_checked": sum(1 for c in checked if "recomputed" in c),
        "targets": len(targets),
        "unassessed": len(unassessed & set(targets)),
    }
    for tier in TARGET_LEVELS:
        tier_checked = [c for c in checked if c.get("target_level") == tier]
        labels = Counter(c["recomputed_label"] for c in tier_checked if "recomputed_label" in c)
        labels.update(c["level"] for c in tier_checked if c.get("level") == "could_not_run")
        stats[f"level_{tier}"] = {
            "targets": sum(1 for v in targets.values() if v.get("level") == tier),
            "numbers_checked": sum(1 for c in tier_checked if "recomputed" in c),
            "results": dict(by_level[tier]),
            "numbers": dict(labels),
        }
    install = log.get("install") or {}
    doc = {
        # the environment of the rerun, recorded by code from the sandbox log
        "environment": {
            "snapshot": log.get("snapshot"),
            "platform": install.get("platform"),
            "image": log.get("image"),
            "image_digest": log.get("image_digest"),
            "declared_versions": log.get("declared_versions"),
            "installed": install.get("installed"),
        },
        "passed": not reasons,
        "reasons": reasons,
        "stats": stats,
        "checked": checked,
        "minor_rel_tolerance": minor_rel_tolerance,
    }
    if summary_basis:
        doc["summary"] = summary_basis
    return doc


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

    run_dir = workspace / str(log.get("run_dir") or "sandbox/run")
    doc = evaluate(plan, report, log, run_dir, minor_rel_tolerance=minor_rel_tolerance)
    # The written report: e2er writes its counts and environment from the JSON
    # (only once the JSON itself checks out), then compares the prose with it.
    md_path = workspace / MD_FILE
    text = md_path.read_text(encoding="utf-8") if md_path.is_file() else None
    written = False
    if text is not None and doc["passed"]:
        new = with_summary(text, render_summary(report, log))
        if new != text:
            md_path.write_text(new, encoding="utf-8")
            text, written = new, True
    md_reasons = report_text_reasons(text, report, log)
    doc["reasons"] = [*doc["reasons"], *md_reasons]
    doc["passed"] = not doc["reasons"]
    doc["report_text"] = {"file": MD_FILE, "agrees": not md_reasons, "summary_written": written}
    (workspace / CHECK_FILE).write_text(json.dumps(doc, indent=2, default=str) + "\n", encoding="utf-8")
    stats = doc["stats"]
    flat = {k: v for k, v in stats.items() if not isinstance(v, dict)}
    for tier in TARGET_LEVELS:
        flat[f"level_{tier}_numbers_checked"] = stats[f"level_{tier}"]["numbers_checked"]
    return CheckResult(doc["passed"], tuple(doc["reasons"][:20]), stats=flat)


#: A full-precision cell of a package's result file (level 1) is reproduced when
#: the rerun value is within this relative distance of it; a printed number
#: (level 2) when it rounds to the printed value. Stated the same way in
#: skills/files/replication/reproduction-protocol.md.
LEVEL_1_REL_TOLERANCE = 1e-9
LEVEL_1_ABS_FLOOR = 1e-12


def equal_to_target(value: float, published: float, target_level: int, printed_decimals: int) -> bool:
    """Reproduced exactly: at full precision for a package cell, at the printed precision for the paper."""
    if target_level == 1:
        return math.isclose(value, published, rel_tol=LEVEL_1_REL_TOLERANCE, abs_tol=LEVEL_1_ABS_FLOOR)
    return _equal_at(value, published, printed_decimals)


def label_from(equal: bool, rel_diff: float, sign_change: bool, minor_rel_tolerance: float) -> str:
    """The protocol's label for one number that the rerun produced."""
    if equal:
        return "reproduced"
    if sign_change or rel_diff > minor_rel_tolerance:
        return "not_reproduced"
    return "reproduced_minor"


def _why(label: str, rel_diff: float, sign_change: bool, tol: float) -> str:
    if label == "reproduced":
        return "equal to the target"
    if sign_change:
        return "the sign changes"
    return f"relative difference {rel_diff:.3%}, minor tolerance {tol:.0%}"


_NEG = r"(?<!not )(?<!n't )(?<!no longer )(?<!no )"
_ASSERTS_EQUAL = re.compile(
    _NEG + r"\b(equals?|equal to|identical|exactly|at full precision|no difference|matches the (shipped|published))\b",
    re.I,
)
_ASSERTS_DIFF = re.compile(
    _NEG + r"\b(differs?|differences? of|deviates?|diverges?|reverses? sign|sign (flip|change))\b", re.I
)
_CAUSAL = re.compile(
    r"\b(because|caused by|due to|the cause|results? from|stems? from|attributable to|is explained by|explains|"
    r"owing to|the reason|bug|mistake|fault|erroneous)\b",
    re.I,
)
_HEDGE = re.compile(
    r"\b(possibl[ey]|may|might|could|perhaps|potential(ly)?|candidate|not established|unverified|one explanation)\b",
    re.I,
)


def reason_text_problems(text: Any, equal_flags: list[bool]) -> list[str]:
    """What a reason text says that the numbers or the protocol do not allow.

    It may not assert equality when no compared number is equal, nor a
    difference when every number is; and it may name causes only as possible
    ones (no "because", "due to", "caused by", "bug" without "possibly",
    "may", "could" …), since a reproduction does not establish why a number
    differs.
    """
    if not isinstance(text, str) or not text.strip():
        return []
    out: list[str] = []
    says_equal, says_diff = _ASSERTS_EQUAL.search(text), _ASSERTS_DIFF.search(text)
    if equal_flags and not any(equal_flags) and says_equal:
        out.append(f"the reason says {says_equal.group(0)!r}, but no compared number equals its target")
    if equal_flags and all(equal_flags) and says_diff:
        out.append(f"the reason says {says_diff.group(0)!r}, but every compared number equals its target")
    for sentence in re.split(r"(?<=[.;!?])\s+", text):
        m = _CAUSAL.search(sentence)
        if m and not _HEDGE.search(sentence):
            out.append(f"the reason states a cause as established ({m.group(0)!r}); name possible causes only")
    return out


def check_environment(report: dict[str, Any], log: dict[str, Any]) -> list[str]:
    """The report's environment block must agree with the sandbox log.

    The report states the snapshot (date and URL) and the versions of the
    packages it discusses; each must be the log's. The full list of installed
    versions is a fact of the run, so code records it (``sandbox_log.json``
    and ``reproduction_check.json``) rather than a model transcribing it.
    """
    env = report.get("environment")
    if not isinstance(env, dict):
        return [
            "the report has no environment block: add environment.snapshot (date and url from sandbox_log.json "
            "-> snapshot) and environment.installed with the versions of the packages you discuss"
        ]
    out: list[str] = []
    snap = log.get("snapshot") or {}
    raw = env.get("snapshot")
    rsnap: dict[str, Any] = raw if isinstance(raw, dict) else {}
    for key in ("date", "url"):
        if rsnap.get(key) != snap.get(key):
            out.append(f"environment.snapshot.{key} is {rsnap.get(key)!r}; the sandbox used {snap.get(key)!r}")
    installed = (log.get("install") or {}).get("installed") or {}
    raw_inst = env.get("installed")
    claimed: dict[str, Any] = raw_inst if isinstance(raw_inst, dict) else {}
    wrong = sorted(k for k in claimed if k in installed and claimed[k] != installed[k])
    extra = sorted(set(claimed) - set(installed))
    if wrong:
        out.append(
            f"environment.installed differs from sandbox_log.json for {len(wrong)} package(s): {', '.join(wrong[:8])}"
        )
    if extra:
        out.append(f"environment.installed lists package(s) the sandbox did not install: {', '.join(extra[:8])}")
    return out


def report_text_reasons(text: str | None, report: dict[str, Any], log: dict[str, Any] | None) -> list[str]:
    """Where reproduction_report.md contradicts reproduction_report.json (see ``reproduction_md``).

    The pipeline's check and ``e2er verify`` both call this; a missing
    Markdown report is a failure, since it is what the researcher reads.
    """
    if text is None:
        return [f"{MD_FILE} is missing: the reproduction comparer must write it"]
    # By now e2er has written its summary section: it must be there.
    return markdown_problems(text, report, log, require_summary=True)


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
        else:
            for c in res.get("comparisons") or []:
                if isinstance(c, dict) and c.get("label") not in LEVELS:
                    errs.append(
                        f"results[{i}] comparison {c.get('target_id')}: label must be one of {', '.join(LEVELS)}"
                    )
            texts = [res.get("reason"), *[c.get("reason") for c in res.get("comparisons") or [] if isinstance(c, dict)]]
            for text in texts:
                # causal wording only here; the numbers are compared by the check
                errs += [f"results[{i}]: {p}" for p in reason_text_problems(text, [])]
    log_path = Path(workspace) / LOG_FILE
    log: dict[str, Any] | None = None
    if log_path.is_file():
        try:
            log = json.loads(log_path.read_text(encoding="utf-8"))
        except ValueError:
            log = None
        if isinstance(log, dict):
            errs += check_environment(report, log)
    # The prose of the Markdown report must not contradict the JSON; e2er writes
    # its summary section later (the reproduction check), so that is not compared here.
    md_path = Path(workspace) / MD_FILE
    if md_path.is_file():
        errs += markdown_problems(
            md_path.read_text(encoding="utf-8"), report, log if isinstance(log, dict) else None, check_summary=False
        )
    return errs
