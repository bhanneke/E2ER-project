"""Study dossiers: the settings a study was produced with, addressed by a hash.

A dossier lists the E2ER version, the run settings (template, mode, governance,
backend, models), every template, specialist, skill and connector the study
used with a content hash of the file that defines it, and the SHA-256 of the
input data files, and the workflow: every step of the run in order, the
specialist and model that did it, the checks at each gate, steps a check
stopped, and the intermediate file each step wrote with its SHA-256 when the
file is in the exported folder. It deliberately leaves out the paper: the paper carries the
dossier's address in a footnote, so the dossier cannot depend on the paper.

The dossier's id is ``sha256:`` plus the SHA-256 of its canonical JSON (object
keys sorted, no whitespace, UTF-8). The E2ER site computes and checks ids the
same way, so ``https://e2er.org/d/<first 16 hex characters>`` resolves to
exactly this document.

Files are pinned by their git blob SHA (sha1 of ``blob <size>\\0`` + content),
which equals ``git rev-parse <commit>:<path>`` for the same file, so anyone can
compare a pin with the repository.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import subprocess
from pathlib import Path
from typing import Any

SCHEMA = "e2er-dossier/0.3"
SITE = "https://e2er.org"
ROOT = Path(__file__).resolve().parents[2]  # the E2ER checkout or installed package root
BACKEND_CONNECTOR = {
    "anthropic": "anthropic",
    "openrouter": "openrouter",
    "claude_code": "claude-code",
    "codex": "codex",
    "gemini": "gemini",
}


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def dossier_id(doc: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical(doc).encode("utf-8")).hexdigest()


def short_id(did: str) -> str:
    return did.removeprefix("sha256:")[:16]


def dossier_url(did: str) -> str:
    return f"{SITE}/d/{short_id(did)}"


def git_blob_sha(path: Path) -> str:
    data = path.read_bytes()
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def _e2er_commit() -> str | None:
    try:
        out = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def _blob_at(commit: str, rel: str) -> str | None:
    """git blob SHA of ``rel`` at ``commit`` in the E2ER checkout, if both exist."""
    try:
        out = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", f"{commit}:{rel}"], capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def _path_for(component: str) -> str | None:
    kind, _, rest = component.partition(":")
    if kind == "template":
        return f"pipelines/{rest}.toml"
    if kind == "agent" and "/" not in rest:
        return "src/core/specialists/registry.py"
    if kind == "skill" and rest.startswith("e2er/"):
        return f"skills/files/{rest.removeprefix('e2er/')}.md"
    if kind == "connector":
        backend = {v: k for k, v in BACKEND_CONNECTOR.items()}.get(rest)
        return f"src/modules/llm/{backend}.py" if backend else None
    return None


def _pin(component: str, repository: str | None, commit: str | None) -> dict[str, Any]:
    rel = _path_for(component)
    if rel and commit and (blob := _blob_at(commit, rel)):
        pin: dict[str, Any] = {"path": rel, "git_blob": blob}
        if repository:
            pin.update(repository=repository, commit=commit)
        return pin
    if rel and (ROOT / rel).is_file():
        pin: dict[str, Any] = {"path": rel, "git_blob": git_blob_sha(ROOT / rel)}
        if repository and commit:
            pin.update(repository=repository, commit=commit)
        return pin
    return {"note": "built into E2ER; no separate file"}


def _bundle_file(name: str, files: dict[str, Any]) -> str | None:
    """Where a workspace file ended up in the exported folder, matched by its path tail."""
    parts = Path(name).parts
    for n in range(len(parts), 0, -1):
        tail = "/".join(parts[-n:])
        hits = sorted(f for f in files if f == tail or f.endswith("/" + tail))
        if hits:
            return hits[0]
    return None


def _tables(con: sqlite3.Connection) -> set[str]:
    return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def recorded_run_identity(db: Path, paper_id: str) -> dict[str, Any]:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        if "pipeline_events" not in _tables(con):
            return {}
        row = con.execute(
            "SELECT payload FROM pipeline_events WHERE paper_id = ? AND event_type = 'run_identity' "
            "ORDER BY created_at LIMIT 1",
            (paper_id,),
        ).fetchone()
    finally:
        con.close()
    return json.loads(row[0]) if row and row[0] else {}


def recorded_workflow(db: Path, paper_id: str, bundle: Path | None = None) -> list[dict[str, Any]]:
    """The run's steps in order, from ``pipeline_events``, ``contributions`` and ``llm_usage``.

    Each specialist step names its phase, model, start and end, whether it was
    accepted, and the file it wrote with the SHA-256 recorded in the bundle's
    provenance.json. Gate checks appear as their own steps.
    """
    files: dict[str, Any] = {}
    if bundle is not None and (bundle / "provenance.json").is_file():
        files = json.loads((bundle / "provenance.json").read_text(encoding="utf-8")).get("files", {})
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        if not {"pipeline_events", "contributions", "llm_usage"} <= _tables(con):
            return []
        events = con.execute(
            "SELECT event_type, stage, specialist, payload, created_at FROM pipeline_events "
            "WHERE paper_id = ? ORDER BY created_at, rowid",
            (paper_id,),
        ).fetchall()
        contribs = con.execute(
            "SELECT specialist, output_file, success, error_msg FROM contributions "
            "WHERE paper_id = ? ORDER BY created_at, rowid",
            (paper_id,),
        ).fetchall()
        calls = con.execute(
            "SELECT specialist, backend, model FROM llm_usage WHERE paper_id = ? ORDER BY created_at, rowid",
            (paper_id,),
        ).fetchall()
    finally:
        con.close()
    queue: dict[str, list[Any]] = {}
    for c in contribs:
        queue.setdefault(c[0], []).append(c)
    models: dict[str, list[tuple[str, str]]] = {}
    for sp, backend, model in calls:
        models.setdefault(sp, []).append((backend, model))
    steps: list[dict[str, Any]] = []
    phase, started = None, {}
    for etype, stage, sp, payload, at in events:
        data = json.loads(payload) if payload else {}
        if etype == "phase_start":
            phase = stage
        elif etype == "specialist_start":
            started[sp] = at
        elif etype == "specialist_end":
            c = queue.get(sp, [None]).pop(0) if queue.get(sp) else None
            bm = models.get(sp, [None]).pop(0) if models.get(sp) else None
            step: dict[str, Any] = {
                "type": "specialist",
                "phase": phase,
                "specialist": sp,
                "backend": bm[0] if bm else None,
                "model": bm[1] if bm else None,
                "started": started.pop(sp, None),
                "ended": at,
                "accepted": bool(data.get("success", c[2] if c else True)),
            }
            if c and c[3]:
                step["stopped_by"] = c[3][:240]
            if c and c[1]:
                name = Path(c[1]).name if "workspaces/" not in c[1] else c[1].split("/", 2)[2]
                where = _bundle_file(name, files) if step["accepted"] else None
                step["output"] = (
                    {"file": where, "sha256": files[where]["sha256"]} if where else {"file": name, "exported": False}
                )
            steps.append(step)
        elif etype == "gate_enforced":
            steps.append(
                {
                    "type": "check",
                    "phase": phase,
                    "check": data.get("gate") or stage,
                    "passed": bool(data.get("passed")),
                    "enforced": bool(data.get("enforced")),
                    "at": at,
                    **({"detail": str(data["detail"])[:240]} if data.get("detail") and not data.get("passed") else {}),
                }
            )
    return steps


def build_dossier(
    manifest: dict[str, Any],
    repository: str | None = "https://github.com/bhanneke/E2ER-project",
    db: Path | None = None,
    bundle: Path | None = None,
) -> dict[str, Any]:
    """The dossier document for a research-object manifest (see research_object.py).

    With the run database, the E2ER commit is the one the run itself recorded,
    parts are pinned at that commit, and the workflow is included.
    """
    paper_id = (manifest.get("process") or {}).get("paper_id") or (manifest.get("run") or {}).get("paper_id")
    if paper_id is None and bundle is not None and (bundle / "provenance.json").is_file():
        paper_id = json.loads((bundle / "provenance.json").read_text(encoding="utf-8")).get("run", {}).get("paper_id")
    identity = recorded_run_identity(db, paper_id) if db and paper_id else {}
    commit = identity.get("git_sha") or _e2er_commit()
    ai, proc = manifest["ai"], manifest["process"]
    uses = list(manifest["dependencies"]["uses"])
    backend_conn = BACKEND_CONNECTOR.get(ai.get("backend") or "")
    if backend_conn:
        uses.append(f"connector:{backend_conn}")
    models = sorted({(u["backend"], u["model"]) for u in ai.get("usage", [])})
    return {
        "schema": SCHEMA,
        "study": {"title": manifest["title"]},
        "e2er": {
            "version": proc.get("e2er_version"),
            "repository": repository if commit else None,
            "commit": commit,
            **({"uncommitted_changes": bool(identity["git_dirty"])} if "git_dirty" in identity else {}),
        },
        "run": {
            "template": proc.get("template"),
            "mode": proc.get("mode"),
            "governance": proc.get("governance"),
            "backend": ai.get("backend"),
            "models": [{"backend": b, "model": m} for b, m in models]
            or ([{"backend": ai.get("backend"), "model": ai.get("model")}] if ai.get("model") else []),
            "exported": proc.get("exported"),
        },
        "components": [
            {
                "id": c,
                "kind": c.split(":", 1)[0],
                "name": c.split(":", 1)[1].split("/")[-1],
                "pin": _pin(c, repository, commit),
            }
            for c in sorted(set(uses))
        ],
        "data": [{"path": d["path"], "sha256": d["sha256"]} for d in manifest.get("data", [])],
        "workflow": recorded_workflow(db, paper_id, bundle) if db and paper_id else [],
    }


_AUTHOR = re.compile(r"\\author\{((?:[^{}]|\{(?:[^{}]|\{[^{}]*\})*\})*)\}")


def stamp_paper(tex: str, author: str, did: str) -> str:
    """Write the standard E2ER author line and first-page footnote into a paper.

    ``\\author{<author> with E2ER\\thanks{...dossier link...}}``. An existing
    stamp is replaced, so stamping twice gives the same text.
    """
    note = (
        "This paper was produced with E2ER. Its dossier lists every step of the run, the files each step "
        "produced, and the template, specialists, skills, connectors and AI models used, pinned to their "
        f"exact versions: \\url{{{dossier_url(did)}}}."
    )
    block = f"\\author{{{author} with E2ER\\thanks{{{note}}}}}"
    if _AUTHOR.search(tex):
        return _AUTHOR.sub(lambda _: block, tex, count=1)
    return tex.replace("\\begin{document}", block + "\n\\begin{document}", 1)
