"""Pre-registration: the analysis plan fixed before any analysis runs.

A `preregister` step assembles ``preregistration.md`` from the design files the
specialists wrote (question and hypotheses, identification, analysis plan) and
stops for the researcher, who may edit it. On approval e2er freezes it: the
file's SHA-256, the SHA-256 of each plan file it was built from and the time go
into ``preregistration.lock.json`` and the event log. The estimation gate and
``e2er verify`` then compare the plan files with the frozen fingerprints, so a
later change to the plan shows as a deviation. Depositing the frozen file on
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


def assemble(workspace: Path, files: tuple[str, ...] = ()) -> Path:
    """Write preregistration.md from the design files (idempotent: keeps an existing one)."""
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
    out.write_text("\n".join(parts) + "\n", encoding="utf-8")
    return out


def freeze(workspace: Path) -> dict[str, Any]:
    """Fix the pre-registration: fingerprints and time into preregistration.lock.json."""
    prereg = workspace / PREREG_FILE
    if not prereg.is_file():
        raise FileNotFoundError(f"{PREREG_FILE} does not exist in {workspace}")
    lock_path = workspace / LOCK_FILE
    if lock_path.is_file():
        return json.loads(lock_path.read_text(encoding="utf-8"))
    lock = {
        "file": PREREG_FILE,
        "sha256": _sha256(prereg),
        "frozen_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "plan_files": {name: _sha256(workspace / name) for name in PLAN_FILES if (workspace / name).is_file()},
    }
    lock_path.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    return lock


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


def _tokens(name: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", name.lower()) if t}


def estimation_outputs(workspace: Path) -> list[str]:
    """Everything in the workspace that is an estimate or estimation code.

    Called before a pre-registration is frozen, when none of it may exist yet:
    the estimation specialist's files (results JSON, its scripts and logs),
    result tables (``tables/*.tex``), figures named as results, any Python
    script that estimates, and data.db tables named as results. Returns
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
