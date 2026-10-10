"""Specialist output-contract enforcement — v0.9 M4.3.

A specialist's tool_loop can return ``success=True`` while its
declared output artifact is logically empty (the literal ``{}`` was
written, a one-byte ``.md`` was written, the file is whitespace-only).
The M4 paper run surfaced this: ``econometrics_specialist`` returned
``success=True`` but ``estimation_results.json`` was literally
``{}``. The pipeline then burned ~13.7M tokens / 29 specialist calls
writing a paper around an empty result before the mechanism reviewer
caught it.

This module is the cheap, deterministic gate that catches that class
of failure at the specialist boundary, *before* the rest of the
pipeline runs on a hollow contract.

Rules per file extension (intentionally generous — we're catching
``{}`` not "is this a good paper"):

- ``.json`` — must parse, and parsed value must not be ``{}`` / ``[]``
  / ``null``. Empty dicts/lists are the M4 failure mode.
- ``.md`` / ``.tex`` / ``.py`` — > 100 non-whitespace characters.
  A real specialist output is always at least a paragraph.
- Any other file — exists with size > 0.

Coverage:

- The specialist's PRIMARY artifact (``SPECIALIST_ARTIFACTS[name]``)
  is always checked.
- Listed sidecars (``SPECIALIST_SIDECAR_ARTIFACTS[name]``) are
  required and checked too — EXCEPT those in
  ``SPECIALIST_OPTIONAL_SIDECARS[name]`` (e.g. ``figure_spec.json`` for
  ``data_analyst``), which are best-effort: still prompted and checked
  by verify_numbers when present, but not hard-gated here because they
  have no deterministic producer at the specialist boundary.
- Optional sidecars not in the registry at all (e.g.,
  ``robustness_results.json`` for ``econometrics_specialist``) are not
  checked — they're "produce if you ran the analysis".
- Specialists not in ``SPECIALIST_ARTIFACTS`` (none today, but if any
  appear) get no contract check — better to be silent than to false-
  trip on undeclared outputs.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from ...logging_config import get_logger

logger = get_logger(__name__)

#: A check that the pipeline EXECUTED correctly: the file was written, it
#: parses, it is not `{}`. A failure here is a bug in the run, not a property
#: of the paper, so no governance regime may switch it off. The 2026-08-05
#: validation cell is the case in point: `run_estimation.py` crashed, wrote
#: `{}`, and because the regime was `off` nothing flipped the specialist to
#: failure, so the traceback was never fed back and the drafter invented the
#: tables. That is not "an ungoverned paper", it is a broken run.
KIND_RELIABILITY = "reliability"

#: A check on whether the paper's CLAIMS hold: a real regression was run, and
#: it implements the declared specification. These are the verification
#: institutions the governance experiment varies, so a regime may shadow them.
KIND_VERIFICATION = "verification"

# Specialists whose results JSON must contain an actual estimated regression
# (a non-empty ``coefficients`` block), not just descriptive summaries. The
# basic non-empty check passes a ``{"raw_gap": …, "_note": …}`` descriptive
# dump; a real run produced a clean FE regression while another produced only
# descriptives (capping the data/identification review scores). The schema
# (skills/files/econometrics/estimation-results-schema.md) already mandates
# "one entry per estimated specification, each with coefficients and
# diagnostics" — this enforces it deterministically at the boundary.
_REGRESSION_REQUIRED: dict[str, str] = {"econometrics_specialist": "estimation_results.json"}

# Specialists that write `paper_draft.tex`. Their draft may REFERENCE tables
# but may not CONTAIN one: every table has to arrive via `\input{tables/...}`
# from the deterministic renderer.
#
# Without this, "no LLM in the number path" is only true of the path the
# renderer takes. In the 2026-08-05 validation cell the renderer produced
# tables/regime_baseline.tex, tables/regime_break.tex and
# tables/eth_comparison.tex; the draft `\input`-ed none of them and instead
# carried four inline `tabular` blocks under the SAME labels, with numbers the
# model wrote itself. 53 of 110 values traced to nothing. The gate that
# checks numbers ran afterwards and could only report the damage.
_NO_INLINE_TABLES: frozenset[str] = frozenset(
    {"paper_drafter", "section_writer", "latex_formatter", "revisor", "field_review_writer"}
)

_TABULAR_RE = re.compile(r"\\begin\{tabular\}")
_TABLE_INPUT_RE = re.compile(r"\\input\{[^}]*\}")


# Minimum non-whitespace character count for prose / code artifacts.
# 100 is generous (a real specialist output is always at least a
# paragraph, usually 1k+ chars) and easily exceeds the failure modes
# we're catching: empty file (0), single-line stub (~20), placeholder
# comment (~50).
_MIN_PROSE_CHARS = 100

# File extensions that get the prose-character check.
_PROSE_EXTS = frozenset({".md", ".tex", ".py", ".txt"})


@dataclass(frozen=True)
class ContractCheck:
    """One specialist output's contract verification result."""

    artifact: str  # workspace-relative path
    ok: bool
    reason: str = ""  # one-liner explanation when not ok
    #: What KIND of failure this is, which decides whether governance may
    #: switch it off. See `KIND_RELIABILITY` / `KIND_VERIFICATION`.
    kind: str = KIND_RELIABILITY


#: Outputs for which an empty list is a valid answer, not an empty file: the
#: patch file of patch_revisor (``[]`` = nothing in the findings it can fix by
#: editing the draft, as its skill writing/scoped-revision says). Treating it
#: as a violation made the revisor's honest "no edit" read as a broken step.
EMPTY_LIST_IS_AN_ANSWER = frozenset({"paper_draft.tex.edits.json"})


def check_artifact_nonempty(workspace: Path, relative: str) -> ContractCheck:
    """Verify a single declared artifact has non-trivial content.

    ``relative`` is the workspace-relative path (matches the values
    in ``SPECIALIST_ARTIFACTS``). Returns a ``ContractCheck`` — never
    raises, even for permission errors or missing parents (those
    surface as ``ok=False`` with the OS error in ``reason``).
    """
    target = workspace / relative
    if not target.exists():
        return ContractCheck(relative, False, "file not written")
    try:
        size = target.stat().st_size
    except OSError as e:
        return ContractCheck(relative, False, f"stat failed: {e}")
    if size == 0:
        return ContractCheck(relative, False, "file is empty (0 bytes)")

    ext = target.suffix.lower()
    if ext == ".json":
        try:
            text = target.read_text(encoding="utf-8")
        except OSError as e:
            return ContractCheck(relative, False, f"read failed: {e}")
        # Cheap up-front: trim whitespace and check for the literal
        # empty containers before paying for a parse.
        stripped = text.strip()
        if stripped == "[]" and relative in EMPTY_LIST_IS_AN_ANSWER:
            return ContractCheck(relative, True, "")
        if stripped in ("{}", "[]", "null", ""):
            return ContractCheck(relative, False, f"empty JSON ({stripped or 'whitespace-only'!r})")
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as e:
            return ContractCheck(relative, False, f"invalid JSON: {e.msg}")
        if isinstance(parsed, dict | list) and len(parsed) == 0:
            return ContractCheck(relative, False, "empty JSON (parsed to empty container)")
        if parsed is None:
            return ContractCheck(relative, False, "JSON parsed to null")
        return ContractCheck(relative, True, "")

    if ext in _PROSE_EXTS:
        try:
            text = target.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            return ContractCheck(relative, False, f"read failed: {e}")
        non_ws = sum(1 for c in text if not c.isspace())
        if non_ws < _MIN_PROSE_CHARS:
            return ContractCheck(relative, False, f"only {non_ws} non-whitespace chars (min {_MIN_PROSE_CHARS})")
        return ContractCheck(relative, True, "")

    # Unknown extension — accept any non-zero file size.
    return ContractCheck(relative, True, "")


def _has_coefficients(obj: Any) -> bool:
    """True if ``obj`` contains any non-empty ``coefficients`` dict, anywhere in
    its nested structure (specs may be top-level or nested, e.g. ``main_level``)."""
    if isinstance(obj, dict):
        coeffs = obj.get("coefficients")
        if isinstance(coeffs, dict) and coeffs:
            return True
        return any(_has_coefficients(v) for v in obj.values())
    if isinstance(obj, list):
        return any(_has_coefficients(v) for v in obj)
    return False


def check_has_regression(workspace: Path, relative: str) -> ContractCheck:
    """Verify a results JSON holds at least one estimated specification (a
    non-empty ``coefficients`` block) — not a descriptive-only dump. Assumes the
    basic non-empty/parse check already passed; degrades to ok on read error so
    it never double-reports a problem the non-empty check already flagged."""
    target = workspace / relative
    try:
        parsed = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ContractCheck(relative, True, "")
    if _has_coefficients(parsed):
        return ContractCheck(relative, True, "")
    return ContractCheck(
        relative,
        False,
        "no estimated regression: estimation_results.json has no non-empty 'coefficients' block "
        "(descriptive-only output). Estimate at least one identified specification and write its "
        "coefficients/SEs/p-values per the estimation-results-schema — descriptive summaries do not "
        "substitute for the estimation.",
    )


# ── Identified-spec contract (declared vs estimated) ────────────────────────
#
# The binding quality problem after M5: econometrics rigor was high-variance
# run-to-run — one run estimated the identification strategy's clean
# collection×month TWFE (identification score 8), the next reported a weaker
# spec (score 5) under identical steering. Prompts shift the odds; this
# contract makes it deterministic: the identification strategist DECLARES the
# primary spec machine-readably (identification_spec.json, see the
# identification-spec-schema skill), and the econometrics specialist's
# headline `main` entry must ECHO the declared fixed effects, controls, and
# clustering. Echo fields are self-reported, so this enforces declared-vs-
# reported consistency — it eliminates the "silently substitute a raw gap"
# failure mode, raising the bar from "forgot" to "actively fabricates".

_IDENTIFICATION_SPEC_FILE = "identification_spec.json"


def _norm_token(value: Any) -> str:
    """Case/punctuation-insensitive comparison key (``Collection`` ≡
    ``collection``), but not fuzzy: ``month`` != ``year_month``."""
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def _declared_names(primary: dict, key: str) -> list[str]:
    raw = primary.get(key)
    if not isinstance(raw, list):
        return []
    return [str(x).strip() for x in raw if str(x).strip()]


def check_matches_declared_spec(workspace: Path, results_relative: str) -> ContractCheck:
    """Verify the headline estimate implements the DECLARED identification.

    Reads ``identification_spec.json`` (written by identification_strategist);
    when it exists and declares fixed effects / controls / clustering, the
    results JSON must have a ``main`` entry with non-empty coefficients that
    echoes them (``fixed_effects`` / ``controls`` / ``cluster_level`` +
    ``n_clusters``). Degrades to ok when the spec is absent, unparseable, or
    declares nothing checkable — old papers and clean natural experiments
    (no FE, no controls, no clustering) pass untouched.
    """
    spec_path = workspace / _IDENTIFICATION_SPEC_FILE
    if not spec_path.is_file():
        return ContractCheck(results_relative, True, "")
    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ContractCheck(results_relative, True, "")
    primary = spec.get("primary") if isinstance(spec, dict) else None
    if not isinstance(primary, dict):
        return ContractCheck(results_relative, True, "")

    declared_fe = _declared_names(primary, "fixed_effects")
    declared_controls = _declared_names(primary, "controls")
    declared_cluster = str(primary.get("cluster_level") or "").strip()
    wants_cluster = bool(declared_cluster) and _norm_token(declared_cluster) != "none"
    if not declared_fe and not declared_controls and not wants_cluster:
        return ContractCheck(results_relative, True, "")

    try:
        results = json.loads((workspace / results_relative).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # Parse/read problems are owned by check_artifact_nonempty.
        return ContractCheck(results_relative, True, "")
    if not isinstance(results, dict):
        return ContractCheck(results_relative, True, "")

    problems: list[str] = []
    main = results.get("main")
    coefficients = main.get("coefficients") if isinstance(main, dict) else None
    if not isinstance(main, dict) or not (isinstance(coefficients, dict) and coefficients):
        problems.append(
            "the headline estimate must live under the top-level key 'main' with a non-empty "
            "'coefficients' block (identification_spec.json declares an identified design, so a "
            "'main' entry implementing it is required)"
        )
    else:
        echoed_fe = [str(x) for x in main.get("fixed_effects") or [] if str(x).strip()]
        missing_fe = [f for f in declared_fe if not any(_norm_token(e) == _norm_token(f) for e in echoed_fe)]
        if missing_fe:
            problems.append(
                f"main.fixed_effects {echoed_fe or '(absent)'} does not include the declared "
                f"fixed effects {missing_fe} — estimate WITH those FE absorbed and echo them in "
                "a 'fixed_effects' list on the 'main' entry"
            )
        echoed_controls = [str(x) for x in main.get("controls") or [] if str(x).strip()]
        echoed_controls += list(coefficients.keys())
        missing_controls = [
            c for c in declared_controls if not any(_norm_token(e) == _norm_token(c) for e in echoed_controls)
        ]
        if missing_controls:
            problems.append(
                f"declared controls {missing_controls} appear neither in main.controls nor among "
                "main.coefficients — include them in the estimation and echo them"
            )
        if wants_cluster:
            echoed_cluster = str(main.get("cluster_level") or "").strip()
            if _norm_token(echoed_cluster) != _norm_token(declared_cluster):
                problems.append(
                    f"identification_spec.json declares cluster_level {declared_cluster!r} but main "
                    f"reports {echoed_cluster or 'nothing'!r} — cluster the SEs as declared and echo it"
                )
            n_clusters = main.get("n_clusters")
            if not isinstance(n_clusters, int | float) or isinstance(n_clusters, bool) or n_clusters <= 0:
                problems.append(
                    "clustered SEs are declared but main.n_clusters is missing/invalid — report the "
                    "actual cluster count"
                )

    if not problems:
        return ContractCheck(results_relative, True, "")
    return ContractCheck(
        results_relative,
        False,
        "identified-spec contract: "
        + "; ".join(problems)
        + ". The declared primary design is in identification_spec.json — the headline 'main' entry "
        "must implement and echo it (see the estimation-results-schema skill).",
    )


# ── p-values follow from t; every pre-registered hypothesis has a result ────


def check_statistics_consistent(workspace: Path, results_relative: str) -> ContractCheck:
    """t = estimate / se and p follows from t, for every coefficient (src/core/pipeline/statistics.py).

    Covers the results file and robustness_results.json when it exists.
    """
    from ..pipeline.statistics import check_statistics

    docs: list[tuple[str, Any]] = []
    for name in (results_relative, "robustness_results.json"):
        try:
            docs.append((name, json.loads((workspace / name).read_text(encoding="utf-8"))))
        except (OSError, json.JSONDecodeError):
            continue
    report = check_statistics(docs)
    if report.ok:
        return ContractCheck(results_relative, True, "", kind=KIND_VERIFICATION)
    more = f"; and {len(report.problems) - 8} more" if len(report.problems) > 8 else ""
    shown = "; ".join(report.problems[:8]) + more
    return ContractCheck(
        results_relative,
        False,
        f"statistics do not agree: {shown}. Compute the p-value from t with the test's degrees of freedom "
        "(scipy.stats.t.sf or statsmodels), write the df you used as 'df', and name any p-value that does not "
        "come from t in 'p_value_method' (see the estimation-results-schema skill).",
        kind=KIND_VERIFICATION,
    )


def check_preregistered_results(workspace: Path, results_relative: str) -> ContractCheck | None:
    """Every hypothesis of the frozen pre-registration has a result, on the registered sample.

    None when the study has no frozen pre-registration.
    """
    from ..pipeline.preregistration import check_results_against_preregistration

    found = check_results_against_preregistration(workspace)
    if found is None:
        return None
    problems, _notes = found
    if not problems:
        return ContractCheck(results_relative, True, "", kind=KIND_VERIFICATION)
    return ContractCheck(
        results_relative,
        False,
        "pre-registration: "
        + "; ".join(problems)
        + ". The hypotheses and sample size are frozen in preregistration.lock.json (and in the "
        "machine-readable block of preregistration.md).",
        kind=KIND_VERIFICATION,
    )


# ── Contract-violation feedback (self-correction across attempts) ───────────
#
# A contract violation flips the specialist result to failure, but before
# this existed the WHY never reached the next attempt's prompt — the model
# retried blind up to _MAX_SPECIALIST_ATTEMPTS times, then the run PAUSED.
# (read_execution_error can't carry it: it early-returns when the sidecar is
# populated, which is exactly the state after a populated-but-noncompliant
# output.) The violation summary is persisted here and consumed — once — by
# the specialist's next attempt.

_FEEDBACK_DIR = ".contract_feedback"


def write_contract_feedback(workspace: Path, specialist: str, summary: str) -> None:
    """Persist a contract-violation summary for the specialist's next attempt.
    Best-effort: never raises (a lost feedback note must not fail the run)."""
    try:
        feedback_dir = workspace / _FEEDBACK_DIR
        feedback_dir.mkdir(parents=True, exist_ok=True)
        (feedback_dir / f"{specialist}.txt").write_text(summary, encoding="utf-8")
    except OSError as e:
        logger.warning("could not persist contract feedback for %s: %s", specialist, e)


def has_contract_feedback(workspace: Path, specialist: str) -> bool:
    """Whether a violation note is waiting for this specialist's next attempt.

    Non-consuming, unlike :func:`read_contract_feedback` — for callers that
    only need to know whether the next attempt will be *coached* (retrying a
    contract violation with the reason in the prompt) or *blind* (retrying a
    crash or a timeout). Reading it to decide that would eat the note the
    retry is about to consume.
    """
    return (workspace / _FEEDBACK_DIR / f"{specialist}.txt").is_file()


def read_contract_feedback(workspace: Path, specialist: str) -> str | None:
    """Return a ready-to-inject prompt section for a prior contract violation,
    consuming the note (one violation feeds exactly one retry). ``None`` when
    there's nothing to feed back."""
    path = workspace / _FEEDBACK_DIR / f"{specialist}.txt"
    if not path.is_file():
        return None
    try:
        summary = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    try:
        path.unlink()
    except OSError:
        pass
    if not summary:
        return None
    return (
        "## PREVIOUS ATTEMPT REJECTED — OUTPUT-CONTRACT VIOLATION\n\n"
        "Your previous attempt completed, but its output failed a deterministic "
        "contract check and was rejected:\n\n"
        f"{summary}\n\n"
        "Fix exactly this in the current attempt. Keep everything else about your "
        "approach unless the fix requires changing it."
    )


def check_no_inline_tables(workspace: Path, relative: str = "paper_draft.tex") -> ContractCheck:
    """The draft may reference tables but must not contain them.

    A `\\begin{tabular}` in `paper_draft.tex` is a table the model typed rather
    than one the renderer filled from result files, so its numbers bypass the
    provenance chain entirely. Tables belong in `tables/*.tex`, pulled in with
    `\\input`.
    """
    target = workspace / relative
    if not target.is_file():
        # Absence is the non-empty check's business, not ours.
        return ContractCheck(relative, True, "", kind=KIND_VERIFICATION)
    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return ContractCheck(relative, False, f"read failed: {e}", kind=KIND_VERIFICATION)

    inline = len(_TABULAR_RE.findall(text))
    if not inline:
        return ContractCheck(relative, True, "", kind=KIND_VERIFICATION)
    inputs = len(_TABLE_INPUT_RE.findall(text))
    return ContractCheck(
        relative,
        False,
        f"{inline} inline tabular environment(s) in the draft "
        f"({inputs} \\input reference(s)) — tables must come from tables/*.tex "
        "via \\input so their numbers trace to result files, not from the draft itself",
        kind=KIND_VERIFICATION,
    )


def check_draft_includes_declared_tables(workspace: Path, relative: str = "paper_draft.tex") -> ContractCheck:
    """Every table the drafter declares in ``table_spec.json`` is ``\\input`` in the draft.

    The renderer fills declared tables from the results files; a declared table
    the draft never includes ships in tables/ but not in the paper, and the
    number check (which reads the paper) then traces no cell of it. The
    2026-10-10 Haiku run declared two tables, included neither, and passed the
    number check on prose alone.
    """
    from ..pipeline.verify_numbers import included_tables

    target = workspace / relative
    spec_path = workspace / "table_spec.json"
    if not target.is_file() or not spec_path.is_file():
        return ContractCheck(relative, True, "", kind=KIND_VERIFICATION)
    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        text = target.read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        # An unreadable spec is the renderer's to report; the draft is not at fault.
        return ContractCheck(relative, True, "", kind=KIND_VERIFICATION)
    tables = spec.get("tables") if isinstance(spec, dict) else None
    declared = sorted(
        {
            t["filename"] if t["filename"].endswith(".tex") else f"{t['filename']}.tex"
            for t in tables or []
            if isinstance(t, dict) and isinstance(t.get("filename"), str) and t["filename"].strip()
        }
    )
    missing = [name for name in declared if name not in included_tables(text)]
    if not missing:
        return ContractCheck(relative, True, "", kind=KIND_VERIFICATION)
    inputs = ", ".join(f"\\input{{tables/{name}}}" for name in missing)
    return ContractCheck(
        relative,
        False,
        f"table_spec.json declares {len(declared)} table(s) and the draft includes "
        f"{'none of them' if len(missing) == len(declared) else f'{len(declared) - len(missing)} of them'}: "
        f"add {inputs} where each table belongs, or drop the table from table_spec.json",
        kind=KIND_VERIFICATION,
    )


#: Writers of the paper's draft whose draft must cite the study's references.
_MUST_CITE: frozenset[str] = frozenset({"paper_drafter", "field_review_writer"})


def check_draft_cites(workspace: Path, relative: str = "paper_draft.tex") -> ContractCheck:
    """A draft written for a study with references cites at least one of them.

    The 2026-10-10 Haiku draft cited nothing although literature.bib held 21
    entries; the citation check, which checks the cites a draft makes, had
    nothing to check and the paper went through. A study with no references
    at all is not held to this (the citation check then says "no references").
    """
    from ..pipeline.verify_citations import parse_bibitem_keys, parse_cite_keys, study_references

    target = workspace / relative
    if not target.is_file():
        return ContractCheck(relative, True, "", kind=KIND_VERIFICATION)
    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return ContractCheck(relative, False, f"read failed: {e}", kind=KIND_VERIFICATION)
    if parse_cite_keys(text) or parse_bibitem_keys(text) or not study_references(workspace):
        return ContractCheck(relative, True, "", kind=KIND_VERIFICATION)
    return ContractCheck(
        relative,
        False,
        "The draft cites no work; cite the papers in literature.bib where they support the text",
        kind=KIND_VERIFICATION,
    )


def _plan_problems(workspace: Path) -> list[str]:
    from ..pipeline.replication import check_plan

    return check_plan(workspace)


def _boundary_problems(workspace: Path) -> list[str]:
    from ...modules.fieldmap.workflow import boundary_problems

    return boundary_problems(workspace)


def _lanes_problems(workspace: Path) -> list[str]:
    from ...modules.fieldmap.workflow import lanes_problems

    return lanes_problems(workspace)


def _report_problems(workspace: Path) -> list[str]:
    from ..pipeline.reproduction import check_report

    return check_report(workspace)


#: specialist -> (file, structural check returning its problems as sentences)
_STRUCTURAL_CHECKS: dict[str, tuple[str, Any]] = {
    "replication_planner": ("replication_plan.json", _plan_problems),
    "reproduction_comparer": ("reproduction_report.json", _report_problems),
    "field_boundary_designer": ("field_boundary.json", _boundary_problems),
    "field_lane_mapper": ("field_lanes.json", _lanes_problems),
}

DATA_DICTIONARY_FILE = "data_dictionary.json"
DATA_SUMMARY_FILE = "data_summary.md"


def declared_tables(workspace: Path) -> list[str] | None:
    """The data.db tables ``data_dictionary.json`` declares under ``tables``.

    Entries are table names or objects with a ``name``. None when the
    dictionary is absent, unreadable or declares no ``tables`` key: the
    check below then does not apply (older runs, Allium-only dictionaries).
    """
    path = Path(workspace) / DATA_DICTIONARY_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    raw = data.get("tables") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        return None
    names = [t.get("name") if isinstance(t, dict) else t for t in raw]
    return [str(n) for n in names if isinstance(n, str) and n.strip()]


def table_row_counts(workspace: Path) -> dict[str, int]:
    """Every table in the paper's data.db with its row count ({} without a data.db)."""
    import sqlite3

    db = Path(workspace) / "data.db"
    if not db.is_file():
        return {}
    counts: dict[str, int] = {}
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        for (name,) in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall():
            counts[name] = int(con.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0])  # noqa: S608 — names from sqlite_master
    finally:
        con.close()
    return counts


#: Share of non-null values a loaded column needs unless the dictionary declares its own.
DEFAULT_MIN_NON_NULL = 0.9
_DATE_NAMES = frozenset({"date", "datetime", "timestamp", "time", "period", "day", "month", "year", "index"})
_DATE_TYPES = ("DATE", "TIME")
#: Sources whose tables the researcher supplied: their columns are checked only when declared.
_RESEARCHER_SOURCES = ("researcher", "data folder", "byod", "user")


def _is_date_column(name: str, sql_type: str) -> bool:
    n = name.lower()
    return (
        n in _DATE_NAMES
        or n.endswith(("_date", "_time", "_at", "_timestamp"))
        or any(t in (sql_type or "").upper() for t in _DATE_TYPES)
    )


def _declared_entries(workspace: Path) -> dict[str, dict[str, Any]]:
    path = Path(workspace) / DATA_DICTIONARY_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    raw = data.get("tables") if isinstance(data, dict) else None
    out: dict[str, dict[str, Any]] = {}
    for t in raw if isinstance(raw, list) else []:
        if isinstance(t, dict) and isinstance(t.get("name"), str):
            out[t["name"]] = t
        elif isinstance(t, str):
            out[t] = {"name": t}
    return out


def _share(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value) if 0.0 <= float(value) <= 1.0 else None


def empty_columns(workspace: Path, names: list[str]) -> list[str]:
    """Declared tables' value columns that are (nearly) all NULL: "dgs2.value: 0 of 2765 non-null".

    Checks the columns a table's dictionary entry declares under ``columns``
    (names, or objects with a ``name`` and optionally ``min_non_null``); for a
    table without declared columns, every column in data.db that is not a
    date — except in tables the researcher supplied, which are checked only
    where the dictionary declares columns. A column needs the declared share
    (``min_non_null`` on the column or the table) or 90% non-null values.
    """
    import sqlite3

    db = Path(workspace) / "data.db"
    if not db.is_file():
        return []
    entries = _declared_entries(workspace)
    problems: list[str] = []
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        for name in names:
            entry = entries.get(name, {})
            info = con.execute(f'PRAGMA table_info("{name}")').fetchall()  # noqa: S608 — declared names, quoted
            types = {row[1]: row[2] for row in info}
            if not types:
                continue
            table_share = _share(entry.get("min_non_null"))
            declared = entry.get("columns")
            wanted: list[tuple[str, float]] = []
            if isinstance(declared, list) and declared:
                for c in declared:
                    cname = c.get("name") if isinstance(c, dict) else c
                    if not isinstance(cname, str) or _is_date_column(cname, types.get(cname, "")):
                        continue
                    col_share = _share(c.get("min_non_null")) if isinstance(c, dict) else None
                    wanted.append((cname, col_share if col_share is not None else table_share or DEFAULT_MIN_NON_NULL))
            elif not any(r in str(entry.get("source") or "").lower() for r in _RESEARCHER_SOURCES):
                share = table_share if table_share is not None else DEFAULT_MIN_NON_NULL
                wanted = [(c, share) for c, t in types.items() if not _is_date_column(c, t)]
            total = int(con.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0])  # noqa: S608
            if not total:
                continue
            for cname, share in wanted:
                if cname not in types:
                    problems.append(f"{name}.{cname}: declared in the data dictionary but not a column of the table")
                    continue
                filled = int(con.execute(f'SELECT COUNT("{cname}") FROM "{name}"').fetchone()[0])  # noqa: S608
                if filled < share * total:
                    problems.append(f"{name}.{cname}: {filled} of {total} non-null (needs {share:.0%})")
    finally:
        con.close()
    return problems


def _count_forms(n: int) -> tuple[str, ...]:
    return (str(n), f"{n:,}", f"{n:,}".replace(",", " "), f"{n:,}".replace(",", "\u202f"))


def check_declared_tables(workspace: Path) -> list[ContractCheck]:
    """The data analyst loaded what the data dictionary declares, and reports it truthfully.

    1. Every table named in ``data_dictionary.json`` ``tables`` exists in
       data.db, has rows, and its value columns hold values (see
       ``empty_columns``; reliability: the data were not loaded).
    2. ``data_summary.md`` names each table with its actual row count
       (verification: a written "expected ~2,520 rows" is not a count).
    """
    names = declared_tables(workspace)
    if not names:
        return []
    counts = table_row_counts(workspace)
    absent = [n for n in names if n not in counts]
    empty = [n for n in names if counts.get(n) == 0]
    problems = []
    if absent:
        problems.append(f"missing from data.db: {', '.join(absent)}")
    if empty:
        problems.append(f"empty in data.db: {', '.join(empty)}")
    hollow = empty_columns(workspace, [n for n in names if counts.get(n)])
    if hollow:
        problems.append("loaded without values: " + "; ".join(hollow))
    available = ", ".join(f"{k} ({v} rows)" for k, v in sorted(counts.items())) or "none"
    checks = [
        ContractCheck(
            artifact="data.db",
            ok=not problems,
            reason=(
                "data_dictionary.json declares tables that were not loaded — "
                + "; ".join(problems)
                + f". Tables in data.db: {available}. Load each series with `e2er-data ... --table <name>`; "
                "a table whose values are NULL was not loaded (check the connector's error, e.g. an API key)."
            )
            if problems
            else "",
        )
    ]
    if problems:
        return checks
    summary = Path(workspace) / DATA_SUMMARY_FILE
    text = summary.read_text(encoding="utf-8", errors="replace") if summary.is_file() else ""
    wrong = [n for n in names if n not in text or not any(f in text for f in _count_forms(counts[n]))]
    checks.append(
        ContractCheck(
            artifact=DATA_SUMMARY_FILE,
            ok=not wrong,
            reason=(
                "data_summary.md must name each loaded table with its actual row count from data.db; "
                + "missing or wrong for: "
                + ", ".join(f"{n} (actual {counts[n]} rows)" for n in wrong)
            )
            if wrong
            else "",
            kind=KIND_VERIFICATION,
        )
    )
    return checks


def check_specialist_artifacts(workspace: Path, specialist: str) -> list[ContractCheck]:
    """Check every required artifact for ``specialist`` — the primary
    plus any declared sidecars. Returns one ``ContractCheck`` per
    declared path, in order. Empty list when the specialist has no
    declared artifacts (no check applies).
    """
    # Imported lazily so this module stays dependency-light and can
    # be unit-tested without the registry side effects.
    from .registry import (
        SPECIALIST_ARTIFACTS,
        SPECIALIST_OPTIONAL_SIDECARS,
        SPECIALIST_SIDECAR_ARTIFACTS,
    )

    checks: list[ContractCheck] = []
    primary = SPECIALIST_ARTIFACTS.get(specialist)
    if primary:
        checks.append(check_artifact_nonempty(workspace, primary))
    # Best-effort sidecars are prompted + verify_numbers-checked when
    # present, but not hard-gated here (no deterministic producer).
    optional = SPECIALIST_OPTIONAL_SIDECARS.get(specialist, frozenset())
    for sidecar in SPECIALIST_SIDECAR_ARTIFACTS.get(specialist, []):
        if sidecar in optional:
            continue
        checks.append(check_artifact_nonempty(workspace, sidecar))

    # Deterministic "an actual regression was run" gate. Only applied once the
    # basic non-empty check for that file passed, so we don't pile a second
    # failure on top of an already-flagged empty/invalid file.
    regression_file = _REGRESSION_REQUIRED.get(specialist)
    if regression_file:
        base_failed = any(c.artifact == regression_file and not c.ok for c in checks)
        if not base_failed:
            # These two are VERIFICATION, not reliability: the file exists and
            # parses (reliability is satisfied), and we are now asking whether
            # what it contains supports the paper's claims. Governance may
            # shadow them; it may not shadow the checks above.
            regression_check = replace(check_has_regression(workspace, regression_file), kind=KIND_VERIFICATION)
            checks.append(regression_check)
            # Identified-spec contract: only meaningful once a regression
            # exists at all ("estimate SOMETHING" precedes "estimate the
            # DECLARED thing"), and layering both failures would muddy the
            # retry feedback.
            if regression_check.ok:
                checks.append(replace(check_matches_declared_spec(workspace, regression_file), kind=KIND_VERIFICATION))
                checks.append(check_statistics_consistent(workspace, regression_file))
                prereg = check_preregistered_results(workspace, regression_file)
                if prereg is not None:
                    checks.append(prereg)

    # The estimation runs on its own: `e2er reproduce` reruns it without the web and
    # without e2er's tools, so a script that fetches web data or calls a loader is a
    # broken run of the study's code, not a property of the paper (reliability).
    if specialist == "econometrics_specialist" and regression_file and not base_failed:
        from .standalone_check import check_estimation_standalone

        checks.append(check_estimation_standalone(workspace, regression_file))

    # The replication template's JSON files are contracts other code executes
    # (the plan) or verifies (the report): a file that parses but breaks its
    # schema is as unusable as a missing one, so this is reliability.
    structural = _STRUCTURAL_CHECKS.get(specialist)
    if structural:
        filename, check = structural
        if not any(c.artifact == filename and not c.ok for c in checks):
            problems = check(workspace)
            checks.append(ContractCheck(filename, not problems, "; ".join(problems[:8])))

    # The data analyst loads what the data dictionary declares, into data.db,
    # and reports the real row counts (docs: skills/files/data/data-tables.md).
    if specialist == "data_analyst" and not any(c.artifact == primary and not c.ok for c in checks):
        checks.extend(check_declared_tables(workspace))

    # The data architect declares only tables an available source can load
    # (a connector usable now, or a file in the study's data folder).
    if specialist == "data_architect" and not any(c.artifact == primary and not c.ok for c in checks):
        from .data_sources import check_declared_sources

        checks.extend(check_declared_sources(workspace))

    # Draft-writing specialists may reference tables, never contain them.
    if specialist in _NO_INLINE_TABLES:
        draft = SPECIALIST_ARTIFACTS.get(specialist, "paper_draft.tex")
        if draft.endswith(".tex") and not any(c.artifact == draft and not c.ok for c in checks):
            checks.append(check_no_inline_tables(workspace, draft))
    # The checks below look at a draft that exists; each reports on its own, so
    # one attempt's feedback names every problem at once.
    draft = SPECIALIST_ARTIFACTS.get(specialist, "paper_draft.tex")
    draft_written = draft.endswith(".tex") and not any(
        c.artifact == draft and not c.ok and c.kind == KIND_RELIABILITY for c in checks
    )
    # The drafter writes table_spec.json and the draft together: what it
    # declares, it includes.
    if specialist == "paper_drafter" and draft_written:
        checks.append(check_draft_includes_declared_tables(workspace, draft))
    # A draft for a study with references cites them.
    if specialist in _MUST_CITE and draft_written:
        checks.append(check_draft_cites(workspace, draft))
    return checks
