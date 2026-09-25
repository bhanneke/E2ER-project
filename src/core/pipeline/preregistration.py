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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PREREG_FILE = "preregistration.md"
LOCK_FILE = "preregistration.lock.json"

#: (heading, workspace file) — what a pre-registration is assembled from.
SOURCES: tuple[tuple[str, str], ...] = (
    ("Research question and hypotheses", "paper_plan.md"),
    ("Identification strategy", "identification_strategy.md"),
    ("Identification (machine-readable)", "identification_spec.json"),
    ("Analysis plan", "econometric_spec.md"),
)
#: The files whose later change counts as a deviation from the plan.
PLAN_FILES: tuple[str, ...] = ("identification_spec.json", "econometric_spec.md")


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


ZENODO_URL = "https://zenodo.org"
ZENODO_SANDBOX_URL = "https://sandbox.zenodo.org"


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
    import httpx

    lock = load_lock(workspace)
    if lock is None:
        raise RuntimeError("the pre-registration is not frozen yet; approve it at its researcher step first")
    prereg = workspace / lock.get("file", PREREG_FILE)
    http = client or httpx.Client(base_url=base_url, timeout=60.0)
    auth = {"Authorization": f"Bearer {token}"}
    r = http.post("/api/deposit/depositions", json={}, headers=auth)
    r.raise_for_status()
    dep = r.json()
    bucket = dep["links"]["bucket"]
    with prereg.open("rb") as fh:
        up = http.put(f"{bucket}/{prereg.name}", content=fh.read(), headers=auth)
    up.raise_for_status()
    meta = {
        "metadata": {
            "title": title or "Pre-registration",
            "upload_type": "publication",
            "publication_type": "other",
            "description": f"Pre-registration frozen by e2er on {lock['frozen_at']} (SHA-256 {lock['sha256']}).",
            "creators": creators or [{"name": "Unknown"}],
            "keywords": ["pre-registration", "e2er"],
        }
    }
    m = http.put(f"/api/deposit/depositions/{dep['id']}", json=meta, headers=auth)
    m.raise_for_status()
    p = http.post(f"/api/deposit/depositions/{dep['id']}/actions/publish", headers=auth)
    p.raise_for_status()
    done = p.json()
    deposit = {
        "service": "zenodo" if base_url == ZENODO_URL else base_url,
        "doi": done.get("doi"),
        "url": (done.get("links") or {}).get("record_html") or (done.get("links") or {}).get("html"),
    }
    record_deposit(workspace, deposit)
    return deposit
