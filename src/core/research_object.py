"""The research-object manifest: what a published E2ER bundle is, in one file.

An exported bundle already proves its own integrity: ``provenance.json`` hashes
every file and records how results were derived. What it does not say is who
made it, which template and agents produced it, which literature and data it
rests on, and what a registry should list about it. ``e2er.json`` says that.

The manifest is derived, never typed in by hand. Every field comes from the
bundle, from the run database when one is given, or from the arguments of
``e2er publish``, and each list records where it came from (``recorded`` from
the run database, ``declared`` from the bundle or the template file). The
object's content identity is the SHA-256 of ``provenance.json``: since that file
fixes the hash of every other file, one digest identifies the whole bundle.

Schema: docs/schemas/research-object.schema.json (``e2er-research-object/0.1``).
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = "e2er-research-object/0.1"
MANIFEST_NAME = "e2er.json"
_ID = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,38})$")
_PROJECT = re.compile(r"^[a-z0-9][a-z0-9._-]{0,99}$")


class PublishError(ValueError):
    """The bundle or the arguments cannot produce a valid research object."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _question_and_title(bundle: Path) -> tuple[str, str]:
    readme = (bundle / "README.md").read_text(encoding="utf-8") if (bundle / "README.md").is_file() else ""
    q = re.search(r"\*\*Research question:\*\*\s*(.+)", readme)
    question = q.group(1).strip() if q else ""
    title = ""
    abstract = bundle / "paper" / "abstract.tex"
    if abstract.is_file():
        m = re.search(r"\\title\{(.+?)\}\s*\n", abstract.read_text(encoding="utf-8"), re.S)
        if m:
            title = re.sub(r"\s+", " ", m.group(1).replace("\\\\", " ")).strip()
    if not title:
        h = re.search(r"^#\s+(.+)$", readme, re.M)
        title = h.group(1).strip() if h else question
    return question, title


def _recorded_usage(db: Path, paper_id: str) -> list[dict[str, Any]]:
    """Per-agent AI usage as the run recorded it (table ``llm_usage``)."""
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT specialist, backend, model, COUNT(*), SUM(input_tokens), SUM(output_tokens), "
            "SUM(cache_read_tokens), SUM(cache_write_tokens), SUM(COALESCE(cost_usd, 0)), "
            "MIN(created_at), MAX(created_at) "
            "FROM llm_usage WHERE paper_id = ? GROUP BY specialist, backend, model ORDER BY MIN(created_at)",
            (paper_id,),
        ).fetchall()
    finally:
        con.close()
    return [
        {
            "agent": r[0],
            "backend": r[1],
            "model": r[2],
            "calls": r[3],
            "input_tokens": r[4] or 0,
            "output_tokens": r[5] or 0,
            "cache_read_tokens": r[6] or 0,
            "cache_write_tokens": r[7] or 0,
            "cost_usd": round(r[8] or 0.0, 4),
            "first": r[9],
            "last": r[10],
        }
        for r in rows
    ]


def _recorded_run(db: Path, paper_id: str) -> dict[str, Any]:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        cols = {r[1] for r in con.execute("PRAGMA table_info(papers)")}
        want = [c for c in ("mode", "methodology", "governance", "pipeline") if c in cols]
        row = con.execute(f"SELECT {', '.join(want)} FROM papers WHERE id = ?", (paper_id,)).fetchone()
    finally:
        con.close()
    return dict(zip(want, row, strict=True)) if row else {}


def _template_agents(template_file: Path, mode: str) -> list[str]:
    """Agents a template dispatches in a mode, from the template file itself."""
    spec = tomllib.loads(template_file.read_text(encoding="utf-8"))
    agents: list[str] = []
    for step in spec.get("steps", []):
        if mode in step.get("modes", [mode]):
            agents += [a for a in step.get("run", []) if a not in agents]
    return agents


def _skills_for(agents: list[str]) -> dict[str, list[str]]:
    from .specialists.registry import SPECIALIST_SKILLS

    return {a: list(SPECIALIST_SKILLS.get(a, [])) for a in agents}


def build_manifest(
    bundle: Path,
    *,
    owner: str,
    project: str,
    contributors: list[dict[str, Any]],
    repository: dict[str, str] | None = None,
    db: Path | None = None,
    template: str = "empirical",
    template_file: Path | None = None,
    license_id: str | None = None,
    derived_from: list[str] | None = None,
    verification: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    bundle = Path(bundle)
    prov_path = bundle / "provenance.json"
    prov = _json(prov_path)
    if not isinstance(prov, dict) or "files" not in prov:
        raise PublishError(f"{bundle} has no provenance.json; export it with `e2er export` first")
    if not _ID.match(owner):
        raise PublishError(f"owner {owner!r} must be a GitHub login in lower case")
    if not _PROJECT.match(project):
        raise PublishError(f"project {project!r} must be lower case: letters, digits, '.', '_' or '-'")
    if not contributors:
        raise PublishError("name at least one contributor (--github and/or --orcid)")

    run = prov.get("run", {})
    question, title = _question_and_title(bundle)

    # AI actors: recorded by the run when the database is given, else what the template declares.
    usage: list[dict[str, Any]] = []
    recorded: dict[str, Any] = {}
    if db is not None and run.get("paper_id"):
        usage = _recorded_usage(db, run["paper_id"])
        recorded = _recorded_run(db, run["paper_id"])
    mode = recorded.get("mode", "single_pass")
    if usage:
        agents = [u["agent"] for u in usage if not u["agent"].startswith("strategist")]
        agents_source = "recorded"
    elif template_file is not None and template_file.is_file():
        agents = _template_agents(template_file, mode)
        agents_source = "declared"
    else:
        agents, agents_source = [], "unknown"
    skills = _skills_for(agents)

    citations = [e for e in prov.get("edges", []) if e.get("type") == "citation"]
    files = prov["files"]
    data_files = sorted(p for p in files if p.startswith("data/"))
    outputs = sorted(p for p in files if p.startswith(("paper/", "results/", "replication/")))

    uses = [f"template:{template}"] + [f"agent:{a}" for a in agents]
    uses += sorted({f"skill:e2er/{s}" for ss in skills.values() for s in ss})

    manifest: dict[str, Any] = {
        "schema": SCHEMA,
        "id": f"{owner}/{project}",
        "content_id": "sha256:" + _sha256(prov_path),
        "title": title,
        "question": question,
        "contributors": contributors,
        "ai": {
            "backend": run.get("backend"),
            "model": run.get("model"),
            "agents": agents,
            "agents_source": agents_source,
            "usage": usage,
        },
        "process": {
            "template": template,
            "mode": mode,
            "methodology": recorded.get("methodology"),
            "governance": recorded.get("governance", run.get("governance")),
            "e2er_version": run.get("e2er_version"),
            "exported": run.get("exported_at"),
        },
        "components": {"skills": skills},
        "literature": [
            {
                "cite_key": e.get("key"),
                "doi": (e.get("external_id") or "").removeprefix("doi:") or None,
                "status": e.get("status"),
                "verified_by": e.get("registry"),
            }
            for e in citations
        ],
        "data": [{"path": p, "sha256": files[p]["sha256"], "bytes": files[p]["bytes"]} for p in data_files],
        "outputs": [{"path": p, "sha256": files[p]["sha256"]} for p in outputs],
        "provenance": {
            "files": len(files),
            "edges": {
                t: sum(1 for e in prov.get("edges", []) if e.get("type") == t)
                for t in sorted({e.get("type") for e in prov.get("edges", [])})
            },
        },
        "verification": verification or [],
        "dependencies": {"uses": uses, "derived_from": derived_from or []},
        "repository": repository or {},
        "license": license_id,
        "published": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    return manifest


def write_manifest(bundle: Path, manifest: dict[str, Any]) -> Path:
    out = Path(bundle) / MANIFEST_NAME
    out.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return out
