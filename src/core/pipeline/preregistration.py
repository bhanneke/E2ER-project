"""Pre-registration: the analysis plan fixed before any analysis runs.

A `preregister` step assembles ``preregistration.md`` from the design files the
specialists wrote (question and hypotheses, identification, analysis plan) and
stops for the researcher, who may edit it. On approval e2er freezes it: the
file's SHA-256, the SHA-256 of each plan file it was built from and the time go
into ``preregistration.lock.json`` and the event log. The estimation gate and
``e2er verify`` then compare the plan files with the frozen fingerprints. A
later change to the plan stops the run at the estimation check until the
researcher decides: approve the deviation (recorded in the lock and the
dossier, and reported by ``e2er verify``), or put the plan back. Depositing the frozen file on
Zenodo, with the researcher's own account, gives it a DOI.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..zenodo import ZENODO_SANDBOX_URL as ZENODO_SANDBOX_URL  # re-exported for `e2er preregister deposit`
from ..zenodo import ZENODO_URL, deposit_files

PREREG_FILE = "preregistration.md"
LOCK_FILE = "preregistration.lock.json"

#: (heading, workspace file) — what a pre-registration is assembled from.
SOURCES: tuple[tuple[str, str], ...] = (
    ("Research question and hypotheses", "paper_plan.md"),
    ("Identification strategy", "identification_strategy.md"),
    ("Identification (machine-readable)", "identification_spec.json"),
    # Written only in templates that ask for it (event-study-finance).
    ("Events and windows (machine-readable)", "event_design.json"),
    ("Analysis plan", "econometric_spec.md"),
)
#: The files whose later change counts as a deviation from the plan.
PLAN_FILES: tuple[str, ...] = ("identification_spec.json", "event_design.json", "econometric_spec.md")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


#: The heading of the machine-readable hypotheses-and-sample block in preregistration.md.
MACHINE_HEADING = "Hypotheses and sample (machine-readable)"

#: A hypothesis named at the start of a heading or list item: "### H1: …",
#: "- **H1a (Rate hikes)**: …", "**H2.** …". A passing mention ("H1 and H2
#: results") is not a declaration.
_HYPOTHESIS_LINE = re.compile(
    r"^\s*(?:#{1,6}\s+|[-*+]\s+|\d+[.)]\s+)?(?:\*\*|__)?\s*([Hh]\d+[A-Za-z]?)\b"
    r"(?:\s*\(([^)]*)\))?\s*(?:\*\*|__)?\s*[:.—–-]\s*(?:\*\*|__)?\s*(.*)$"
)
_PARENT = re.compile(r"^H\d+")


def _norm_hypothesis(value: Any) -> str:
    """'h1A ' -> 'H1a': the H and number, and a part letter in lower case."""
    s = str(value).strip()
    m = re.fullmatch(r"[Hh](\d+)([A-Za-z]?)", re.sub(r"\s+", "", s))
    return f"H{m.group(1)}{m.group(2).lower()}" if m else s


def hypothesis_parent(hid: str) -> str:
    """'H1a' -> 'H1'; an id that is not of the H<n> form is its own parent."""
    m = _PARENT.match(_norm_hypothesis(hid))
    return m.group(0) if m else _norm_hypothesis(hid)


def extract_hypotheses(text: str) -> list[dict[str, Any]]:
    """The hypotheses a plan declares, in order: [{"id": "H1", "statement": …, "parts": ["H1a", …]}].

    A declaration is a heading or list item that starts with the id (H1, H2a…).
    Parts (H1a, H1b) are listed under their hypothesis; a part without a
    declared parent still makes the parent a hypothesis.
    """
    found: dict[str, dict[str, Any]] = {}
    for line in text.splitlines():
        m = _HYPOTHESIS_LINE.match(line)
        if not m:
            continue
        hid = _norm_hypothesis(m.group(1))
        statement = " ".join(x for x in (m.group(2) or "", m.group(3).strip().strip("*_ ")) if x).strip()
        parent = hypothesis_parent(hid)
        entry = found.setdefault(parent, {"id": parent, "statement": "", "parts": []})
        if hid == parent:
            entry["statement"] = entry["statement"] or statement
        elif hid not in entry["parts"]:
            entry["parts"].append(hid)
    out = []
    for h in found.values():
        item: dict[str, Any] = {"id": h["id"], "statement": h["statement"]}
        if h["parts"]:
            item["parts"] = h["parts"]
        out.append(item)
    return out


def declared_sample_size(workspace: Path) -> dict[str, Any] | None:
    """The sample size the design fixes: the events of event_design.json, or a
    ``sample_size`` that identification_spec.json declares (top level or primary)."""
    design = _read_json(workspace / "event_design.json")
    events = design.get("events") if isinstance(design, dict) else None
    if isinstance(events, list) and events:
        return {"n": len(events), "unit": "events", "source": "event_design.json"}
    spec = _read_json(workspace / "identification_spec.json")
    if isinstance(spec, dict):
        for holder in (spec, spec.get("primary")):
            n = holder.get("sample_size") if isinstance(holder, dict) else None
            if isinstance(n, dict):
                n = n.get("n")
            if isinstance(n, int) and not isinstance(n, bool) and n > 0:
                return {"n": n, "unit": "observations", "source": "identification_spec.json"}
    return None


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def machine_readable_block(workspace: Path) -> dict[str, Any]:
    """The hypotheses (from paper_plan.md) and sample size a pre-registration fixes."""
    plan = workspace / "paper_plan.md"
    text = plan.read_text(encoding="utf-8") if plan.is_file() else ""
    block: dict[str, Any] = {"hypotheses": extract_hypotheses(text)}
    sample = declared_sample_size(workspace)
    if sample:
        block["sample_size"] = sample
    return block


def assemble(workspace: Path, files: tuple[str, ...] = ()) -> Path:
    """Write preregistration.md from the design files (idempotent: keeps an existing one).

    The last section is machine-readable: the hypotheses the plan names and the
    sample size the design fixes, as JSON. The researcher may correct it; on
    approval it is frozen into preregistration.lock.json, and the estimation
    check and ``e2er verify`` require a result for every hypothesis in it.
    """
    out = workspace / PREREG_FILE
    if out.is_file():
        return out
    wanted = [(h, f) for h, f in SOURCES if not files or f in files]
    parts = [
        "# Pre-registration",
        "",
        "Assembled by e2er from the study's design files before any analysis ran. "
        "The researcher reviews and may edit it; on approval it is frozen with its fingerprint.",
    ]
    for heading, name in wanted:
        p = workspace / name
        if not p.is_file():
            continue
        body = p.read_text(encoding="utf-8").strip()
        fence = "```json\n" + body + "\n```" if name.endswith(".json") else body
        parts += ["", f"## {heading}", "", f"_From `{name}`._", "", fence]
    block = json.dumps(machine_readable_block(workspace), indent=2, ensure_ascii=False)
    parts += [
        "",
        f"## {MACHINE_HEADING}",
        "",
        "_Every hypothesis listed here must have at least one result, and the headline "
        "estimate's number of observations must equal the sample size unless the results "
        "declare the exclusions. Correct the list before approving if it is wrong._",
        "",
        "```json\n" + block + "\n```",
    ]
    out.write_text("\n".join(parts) + "\n", encoding="utf-8")
    return out


_JSON_FENCE = re.compile(r"```json\s*\n(.*?)\n```", re.DOTALL)


def parse_machine_block(text: str) -> dict[str, Any] | None:
    """The JSON under the machine-readable heading of a preregistration.md, if any."""
    idx = text.find(f"## {MACHINE_HEADING}")
    if idx == -1:
        return None
    m = _JSON_FENCE.search(text, idx)
    if not m:
        return None
    try:
        data = json.loads(m.group(1))
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _clean_hypotheses(raw: Any) -> list[dict[str, Any]]:
    out = []
    for h in raw if isinstance(raw, list) else []:
        hid = h.get("id") if isinstance(h, dict) else h
        if isinstance(hid, str | int) and str(hid).strip():
            item = dict(h) if isinstance(h, dict) else {}
            item["id"] = _norm_hypothesis(hid)
            out.append(item)
    return out


def freeze(workspace: Path) -> dict[str, Any]:
    """Fix the pre-registration: fingerprints, time, hypotheses and sample size into preregistration.lock.json."""
    prereg = workspace / PREREG_FILE
    if not prereg.is_file():
        raise FileNotFoundError(f"{PREREG_FILE} does not exist in {workspace}")
    lock_path = workspace / LOCK_FILE
    if lock_path.is_file():
        return json.loads(lock_path.read_text(encoding="utf-8"))
    text = prereg.read_text(encoding="utf-8")
    block = parse_machine_block(text)
    if block is None:
        block = {"hypotheses": extract_hypotheses(text)}
        sample = declared_sample_size(workspace)
        if sample:
            block["sample_size"] = sample
    lock: dict[str, Any] = {
        "file": PREREG_FILE,
        "sha256": _sha256(prereg),
        "frozen_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "plan_files": {name: _sha256(workspace / name) for name in PLAN_FILES if (workspace / name).is_file()},
        "hypotheses": _clean_hypotheses(block.get("hypotheses")),
    }
    if isinstance(block.get("sample_size"), dict):
        lock["sample_size"] = block["sample_size"]
    lock_path.write_text(json.dumps(lock, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return lock


def preregistered(folder: Path, lock: dict[str, Any], prereg_dir: Path | None = None) -> dict[str, Any]:
    """The hypotheses and sample size a frozen pre-registration fixes.

    Read from the lock; a lock frozen before the lock carried them falls back
    to the machine-readable block of the frozen file, then to the hypotheses
    its text declares and the events of event_design.json.
    """
    if "hypotheses" in lock:
        out: dict[str, Any] = {"hypotheses": _clean_hypotheses(lock.get("hypotheses")), "source": LOCK_FILE}
        if isinstance(lock.get("sample_size"), dict):
            out["sample_size"] = lock["sample_size"]
        return out
    prereg = (prereg_dir or folder) / lock.get("file", PREREG_FILE)
    text = prereg.read_text(encoding="utf-8") if prereg.is_file() else ""
    block = parse_machine_block(text)
    source = f"{prereg.name} (machine-readable block)"
    if block is None:
        block = {"hypotheses": extract_hypotheses(text)}
        source = f"{prereg.name} (declared in the text)"
        sample = declared_sample_size(folder)
        if sample:
            block["sample_size"] = sample
    out = {"hypotheses": _clean_hypotheses(block.get("hypotheses")), "source": source}
    if isinstance(block.get("sample_size"), dict):
        out["sample_size"] = block["sample_size"]
    return out


# ── every pre-registered hypothesis has a result ────────────────────────────


def _entry_hypotheses(entry: dict[str, Any]) -> list[str]:
    raw = entry.get("hypothesis", entry.get("hypotheses"))
    if isinstance(raw, str | int):
        raw = [raw]
    return [_norm_hypothesis(h) for h in raw or [] if isinstance(h, str | int) and str(h).strip()]


def _excluded_count(item: dict[str, Any]) -> int:
    n = item.get("n", item.get("count"))
    if isinstance(n, int) and not isinstance(n, bool) and n >= 0:
        return n
    ids = item.get("ids")
    return len(ids) if isinstance(ids, list) else 1


def result_coverage(
    results: list[dict[str, Any]], prereg: dict[str, Any], headline: dict[str, Any] | None = None
) -> tuple[list[str], list[str]]:
    """Problems and notes: does every pre-registered hypothesis have a result, and is the sample the registered one?

    ``results`` are the result files' contents (estimation_results.json first);
    each top-level entry names the hypothesis it tests in ``hypothesis`` (an id
    or a list; a part such as H1a counts for H1). ``headline`` is the ``main``
    entry, whose ``n_observations`` must equal the registered sample size
    unless ``exclusions`` (top level or on ``main``) account for the
    difference, each with a reason.
    """
    problems: list[str] = []
    notes: list[str] = []
    wanted = [h["id"] for h in prereg.get("hypotheses") or []]
    tested: dict[str, list[str]] = {}
    untagged = 0
    exclusions: list[Any] = []
    for doc in results:
        if not isinstance(doc, dict):
            continue
        if isinstance(doc.get("exclusions"), list):
            exclusions += doc["exclusions"]
        for key, entry in doc.items():
            if not isinstance(entry, dict) or key == "exclusions":
                continue
            tags = _entry_hypotheses(entry)
            if not tags and "coefficients" in entry:
                untagged += 1
            for t in tags:
                for hid in {t, hypothesis_parent(t)}:
                    tested.setdefault(hid, []).append(key)
    missing = [h for h in wanted if h not in tested]
    if missing:
        hint = f"; {untagged} result entr{'y names' if untagged == 1 else 'ies name'} no hypothesis" if untagged else ""
        strays = sorted(t for t in tested if t not in wanted and hypothesis_parent(t) not in wanted)
        if strays:
            hint += f"; named but not pre-registered: {', '.join(repr(t) for t in strays[:5])}"
        problems.append(
            f"pre-registered hypothes{'is' if len(missing) == 1 else 'es'} without a result: {', '.join(missing)}"
            f" (each result entry names the hypothesis it tests in a 'hypothesis' field{hint})"
        )
    elif wanted:
        notes.append(f"every pre-registered hypothesis has a result ({', '.join(wanted)})")

    sample = prereg.get("sample_size")
    n_reg = sample.get("n") if isinstance(sample, dict) else None
    if isinstance(n_reg, int) and not isinstance(n_reg, bool) and isinstance(headline, dict):
        if isinstance(headline.get("exclusions"), list):
            exclusions += headline["exclusions"]
        n_obs = headline.get("n_observations", headline.get("n_events"))
        unit = sample.get("unit", "observations") if isinstance(sample, dict) else "observations"
        declared = [e for e in exclusions if isinstance(e, dict)]
        with_reason = [e for e in declared if str(e.get("reason") or "").strip()]
        shown = "; ".join(
            f"{e.get('id') or ', '.join(map(str, e.get('ids') or [])) or e.get('n', 1)}: {str(e['reason']).strip()}"
            for e in with_reason
        )
        if shown:
            notes.append(f"declared exclusions: {shown}")
        if isinstance(n_obs, int | float) and not isinstance(n_obs, bool) and n_obs != n_reg:
            excluded = sum(_excluded_count(e) for e in with_reason)
            gap = n_reg - int(n_obs)
            if len(with_reason) < len(declared):
                problems.append("an exclusion without a reason is not a declared exclusion")
            if gap < 0:
                problems.append(f"the results use {int(n_obs)} observations, more than the {n_reg} {unit} registered")
            elif not with_reason:
                problems.append(
                    f"the pre-registration fixes {n_reg} {unit}, the headline result uses {int(n_obs)}; "
                    "declare the excluded ones with a reason under 'exclusions'"
                )
            elif excluded != gap:
                problems.append(
                    f"the pre-registration fixes {n_reg} {unit}, the headline result uses {int(n_obs)}, "
                    f"but the declared exclusions account for {excluded}, not {gap}"
                )
    return problems, notes


def check_results_against_preregistration(workspace: Path) -> tuple[list[str], list[str]] | None:
    """Rule 1 for a workspace: None when nothing is pre-registered."""
    lock = load_lock(workspace)
    if lock is None:
        return None
    docs = [_read_json(workspace / n) for n in ("estimation_results.json", "robustness_results.json")]
    docs = [d for d in docs if isinstance(d, dict)]
    prereg = preregistered(workspace, lock)
    return result_coverage(docs, prereg, headline_entry(docs[0] if docs else {}, prereg))


def headline_entry(results: dict[str, Any], prereg: dict[str, Any]) -> dict[str, Any] | None:
    """The result whose sample is the registered one: ``main``; failing that the first
    entry testing the first pre-registered hypothesis; failing that the first estimate."""
    main = results.get("main")
    if isinstance(main, dict):
        return main
    entries = [e for e in results.values() if isinstance(e, dict) and isinstance(e.get("coefficients"), dict)]
    first = next(iter(prereg.get("hypotheses") or []), None)
    if first:
        for e in entries:
            if first["id"] in {hypothesis_parent(t) for t in _entry_hypotheses(e)}:
                return e
    return entries[0] if entries else None


def load_lock(folder: Path) -> dict[str, Any] | None:
    p = folder / LOCK_FILE
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def deviations(folder: Path, lock: dict[str, Any], prereg_dir: Path | None = None) -> list[str]:
    """What changed since the freeze: the pre-registration itself, or a plan file."""
    out = []
    prereg = (prereg_dir or folder) / lock.get("file", PREREG_FILE)
    if not prereg.is_file():
        out.append(f"{prereg.name} is missing")
    elif _sha256(prereg) != lock.get("sha256"):
        out.append(f"{prereg.name} was changed after it was frozen")
    for name, digest in (lock.get("plan_files") or {}).items():
        p = folder / name
        if not p.is_file():
            out.append(f"{name} is missing")
        elif _sha256(p) != digest:
            out.append(f"{name} changed after the pre-registration")
    return out


def deviation_details(folder: Path, lock: dict[str, Any], prereg_dir: Path | None = None) -> list[dict[str, Any]]:
    """Each change since the freeze, with its fingerprints.

    [{"file", "sha256_frozen", "sha256_now" (None when the file is missing),
    "text" (as ``deviations`` words it), "approved" (the researcher approved
    exactly this version of the file)}].
    """
    approvals = {
        (a.get("file"), a.get("sha256_approved")) for a in lock.get("approved_deviations") or [] if isinstance(a, dict)
    }
    pairs: list[tuple[str, Path, str | None, str]] = []
    name = lock.get("file", PREREG_FILE)
    pairs.append((name, (prereg_dir or folder) / name, lock.get("sha256"), "was changed after it was frozen"))
    for plan, digest in (lock.get("plan_files") or {}).items():
        pairs.append((plan, folder / plan, digest, "changed after the pre-registration"))
    out: list[dict[str, Any]] = []
    for fname, path, frozen, verb in pairs:
        now = _sha256(path) if path.is_file() else None
        if now == frozen:
            continue
        out.append(
            {
                "file": fname,
                "sha256_frozen": frozen,
                "sha256_now": now,
                "text": f"{fname} {verb}" if now is not None else f"{fname} is missing",
                "approved": (fname, now) in approvals,
            }
        )
    return out


def unapproved_deviations(folder: Path, lock: dict[str, Any], prereg_dir: Path | None = None) -> list[str]:
    """The changes since the freeze that the researcher has not approved (as ``deviations`` words them)."""
    return [d["text"] for d in deviation_details(folder, lock, prereg_dir) if not d["approved"]]


def describe_deviation(d: dict[str, Any]) -> str:
    """'identification_spec.json changed after the pre-registration (SHA-256 1a2b3c4d5e6f → 9f8e7d6c5b4a)'."""
    before = (d.get("sha256_frozen") or "")[:12] or "none"
    after = (d.get("sha256_now") or "")[:12] or "missing"
    return f"{d['text']} (SHA-256 {before} → {after})"


def approve_deviations(workspace: Path) -> list[dict[str, Any]]:
    """Record the researcher's approval of every change since the freeze, in preregistration.lock.json.

    The frozen fingerprints stay as they were; the lock gains one entry per
    approved file version under ``approved_deviations`` (file, SHA-256 frozen,
    SHA-256 approved, time). A later change to the same file is a new deviation
    and needs approving again. Returns the entries added.
    """
    lock_path = workspace / LOCK_FILE
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    added = [
        {
            "file": d["file"],
            "sha256_frozen": d["sha256_frozen"],
            "sha256_approved": d["sha256_now"],
            "deviation": d["text"],
            "approved_at": at,
        }
        for d in deviation_details(workspace, lock)
        if not d["approved"]
    ]
    if added:
        lock.setdefault("approved_deviations", []).extend(added)
        lock_path.write_text(json.dumps(lock, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return added


def record_deposit(workspace: Path, deposit: dict[str, Any]) -> dict[str, Any]:
    lock_path = workspace / LOCK_FILE
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock["deposit"] = deposit
    lock_path.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    return lock


def deposit_zenodo(
    workspace: Path,
    token: str,
    *,
    base_url: str = ZENODO_URL,
    title: str | None = None,
    creators: list[dict[str, str]] | None = None,
    client: Any = None,
) -> dict[str, Any]:
    """Deposit the frozen pre-registration on Zenodo with the researcher's own token.

    Creates a deposition, uploads the file, sets its metadata and publishes it;
    returns {service, doi, url}. Nothing passes through e2er.org.
    """
    lock = load_lock(workspace)
    if lock is None:
        raise RuntimeError("the pre-registration is not frozen yet; approve it at its researcher step first")
    prereg = workspace / lock.get("file", PREREG_FILE)
    metadata = {
        "title": title or "Pre-registration",
        "upload_type": "publication",
        "publication_type": "other",
        "description": f"Pre-registration frozen by e2er on {lock['frozen_at']} (SHA-256 {lock['sha256']}).",
        "creators": creators or [{"name": "Unknown"}],
        "keywords": ["pre-registration", "e2er"],
    }
    deposit = deposit_files([(prereg.name, prereg.read_bytes())], metadata, token, base=base_url, client=client)
    record_deposit(workspace, deposit)
    return deposit


# ── nothing estimated before the freeze ─────────────────────────────────────

#: Words that mark a file, figure or data.db table as a result rather than data.
_RESULT_TOKENS: frozenset[str] = frozenset(
    {
        "car",
        "cars",
        "caar",
        "abnormal",
        "result",
        "results",
        "estimate",
        "estimates",
        "estimation",
        "estimated",
        "regression",
        "regressions",
        "coef",
        "coefs",
        "coefficient",
        "coefficients",
        "tstat",
        "pvalue",
    }
)
#: Source fragments that mark a Python script as estimation code.
_ESTIMATION_CODE = (
    "estimation_results.json",
    "statsmodels",
    "sm.OLS",
    "smf.ols",
    "linregress",
    "lstsq",
    "linearmodels",
    "abnormal",
)
_FIGURE_SUFFIXES = (".pdf", ".png", ".svg", ".jpg", ".jpeg")
SET_ASIDE_DIR = "set_aside"

#: Data-shaped files that can hold results.
_RESULT_FILE_SUFFIXES = (".csv", ".tsv", ".parquet", ".json", ".xlsx")
#: Name fragments that mark such a file as a result.
_RESULT_NAME = re.compile(r"(result|estimat|(^|[^a-z])car([^a-z]|$)|abnormal|(^|[^a-z])ar_|regress|coef)")
#: Column names that mark such a file as a result.
_RESULT_COLUMN = re.compile(
    r"^(car|car_.*|caar.*|abnormal.*|ar_.*|coef.*|estimate.*|t_?stat.*|p_?value.*|alpha_.*|beta_.*)$"
)
#: Machine-readable plan and description files that are never results.
_NOT_RESULTS = frozenset(
    {
        "summary_statistics.json",
        "data_dictionary.json",
        "figure_spec.json",
        "identification_spec.json",
        "event_design.json",
        "table_spec.json",
        "manifest.json",
        "figure_render_report.json",
        "literature_survey.json",
        "preregistration.lock.json",
    }
)
#: Folders that hold inputs, bookkeeping or what was already set aside.
_SKIP_DIRS = frozenset({"data", SET_ASIDE_DIR, "literature", "replication", ".contract_feedback"})


def _columns(path: Path) -> list[str]:
    """The column names of a data file, lower case; [] when they cannot be read."""
    suffix = path.suffix.lower()
    try:
        if suffix in (".csv", ".tsv"):
            with path.open(encoding="utf-8", errors="replace") as f:
                first = f.readline()
            sep = "\t" if suffix == ".tsv" or ("\t" in first and "," not in first) else ","
            return [c.strip().strip('"').lower() for c in first.rstrip("\r\n").split(sep)]
        if suffix == ".json":
            data = json.loads(path.read_text(encoding="utf-8"))
            row = data[0] if isinstance(data, list) and data else data
            return [str(k).lower() for k in row] if isinstance(row, dict) else []
        if suffix == ".parquet":
            import pyarrow.parquet as pq

            return [n.lower() for n in pq.read_schema(path).names]
        if suffix == ".xlsx":
            import openpyxl

            wb = openpyxl.load_workbook(path, read_only=True)
            first_row = next(wb.worksheets[0].iter_rows(max_row=1, values_only=True), ())
            return [str(v).lower() for v in first_row if v is not None]
    except Exception:  # noqa: BLE001 — an unreadable file is judged by its name alone
        return []
    return []


def _result_files(ws: Path) -> set[str]:
    """Data-shaped files outside data/ that are results by name or by their columns."""
    from ..specialists.contract_check import declared_tables

    declared = {t.lower() for t in (declared_tables(ws) or [])}
    found: set[str] = set()
    for p in ws.rglob("*"):
        rel = p.relative_to(ws)
        if not p.is_file() or p.suffix.lower() not in _RESULT_FILE_SUFFIXES:
            continue
        if rel.parts[0] in _SKIP_DIRS or any(part.startswith(".") for part in rel.parts):
            continue
        if p.name in _NOT_RESULTS or p.stem.lower() in declared:
            continue
        name_hit = bool(_RESULT_NAME.search(p.stem.lower()))
        if name_hit or any(_RESULT_COLUMN.match(c) for c in _columns(p)):
            found.add(str(rel))
    return found


def _tokens(name: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", name.lower()) if t}


def estimation_outputs(workspace: Path) -> list[str]:
    """Everything in the workspace that is an estimate or estimation code.

    Called before a pre-registration is frozen, when none of it may exist yet:
    the estimation specialist's files (results JSON, its scripts and logs),
    result tables (``tables/*.tex``), figures named as results, any Python
    script that estimates, data.db tables named as results, and result files
    (csv/tsv/parquet/json/xlsx outside ``data/`` and the declared data tables,
    named as results or with result columns such as car_*, abnormal*, ar_*,
    coef*, estimate*, t_stat, p_value, alpha_*, beta_*). Returns
    workspace-relative paths, and ``data.db:<table>`` for tables.
    """
    from ..specialists.post_execution import EXECUTION_CONVENTIONS

    ws = Path(workspace)
    conv = EXECUTION_CONVENTIONS["econometrics_specialist"]
    named = {conv.sidecar, conv.log, *conv.script_candidates, *conv.output_candidates, "robustness_results.json"}
    found: set[str] = {n for n in named if (ws / n).is_file()}
    for py in ws.glob("*.py"):
        try:
            src = py.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if any(frag in src for frag in _ESTIMATION_CODE):
            found.add(py.name)
    found.update(str(p.relative_to(ws)) for p in (ws / "tables").glob("*.tex"))
    found.update(_result_files(ws))
    for folder in (ws, ws / "figures"):
        for p in folder.glob("*"):
            if p.suffix.lower() in _FIGURE_SUFFIXES and _tokens(p.stem) & _RESULT_TOKENS:
                found.add(str(p.relative_to(ws)))
    db = ws / "data.db"
    if db.is_file():
        import sqlite3

        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
        finally:
            con.close()
        found.update(f"data.db:{t}" for t in tables if _tokens(t) & _RESULT_TOKENS)
    return sorted(found)


def set_aside(workspace: Path, found: list[str]) -> dict[str, Any]:
    """Move estimation outputs out of the way before a specialist is sent back.

    Files go to ``set_aside/<time>/`` with their paths kept; data.db tables are
    copied into ``set_aside/<time>/tables.db`` and then dropped from data.db.
    Nothing is deleted: ``set_aside/<time>/manifest.json`` records every item
    with its SHA-256 (files) or row count (tables), and the returned manifest
    is logged, so the dossier shows what was moved and when.
    """
    import shutil
    import sqlite3

    ws = Path(workspace)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    dest = ws / SET_ASIDE_DIR / stamp
    dest.mkdir(parents=True, exist_ok=True)
    items: list[dict[str, Any]] = []
    tables = [f.split(":", 1)[1] for f in found if f.startswith("data.db:")]
    for rel in (f for f in found if not f.startswith("data.db:")):
        src = ws / rel
        if not src.is_file():
            continue
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        digest = _sha256(src)
        shutil.move(str(src), str(target))
        items.append({"file": rel, "sha256": digest, "moved_to": str(target.relative_to(ws))})
    if tables:
        db = ws / "data.db"
        con = sqlite3.connect(db)
        try:
            con.execute("ATTACH DATABASE ? AS aside", (str(dest / "tables.db"),))
            for t in tables:
                n = con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]  # noqa: S608 — names from sqlite_master
                con.execute(f'CREATE TABLE aside."{t}" AS SELECT * FROM main."{t}"')  # noqa: S608
                con.execute(f'DROP TABLE main."{t}"')  # noqa: S608
                items.append({"table": t, "rows": int(n), "moved_to": f"{SET_ASIDE_DIR}/{stamp}/tables.db"})
            con.commit()
            con.execute("DETACH DATABASE aside")
        finally:
            con.close()
    manifest = {
        "set_aside_at": stamp,
        "reason": "estimation output found before the pre-registration was frozen",
        "items": items,
    }
    (dest / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest
