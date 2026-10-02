"""A small run database for publish tests: the run of one paper, as the runner records it.

``e2er publish`` refuses a folder without its run's database (it builds the
dossier's workflow from it). Tests that publish an example bundle create one
with :func:`make_run_db` next to the bundle, and a study-folder ``.env`` that
names it, as ``e2er init`` writes one.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

COMMIT = "0" * 40  # a commit no checkout has: every pin is recorded as unresolved


def make_run_db(
    folder: Path,
    paper_id: str,
    *,
    env: bool = True,
    workspace: Path | None = None,
    researcher_actions: int = 1,
) -> Path:
    """``folder/e2er.db`` with one recorded run of ``paper_id``; with ``env``, ``folder/.env`` naming it."""
    folder.mkdir(parents=True, exist_ok=True)
    db = folder / "e2er.db"
    con = sqlite3.connect(db)
    con.executescript(
        "CREATE TABLE IF NOT EXISTS papers (id TEXT PRIMARY KEY, status TEXT, last_error TEXT, updated_at TEXT,"
        " mode TEXT, methodology TEXT, governance TEXT, pipeline TEXT, workspace TEXT);"
        "CREATE TABLE IF NOT EXISTS pipeline_events (id TEXT, paper_id TEXT, event_type TEXT, stage TEXT,"
        " specialist TEXT, payload TEXT, created_at TEXT);"
        "CREATE TABLE IF NOT EXISTS contributions (id TEXT, paper_id TEXT, specialist TEXT, stage TEXT,"
        " output_file TEXT, success INT, error_msg TEXT, usage_tokens INT, cost_usd REAL, duration_sec REAL,"
        " created_at TEXT);"
        "CREATE TABLE IF NOT EXISTS llm_usage (id TEXT, paper_id TEXT, specialist TEXT, backend TEXT, model TEXT,"
        " input_tokens INT, output_tokens INT, cache_read_tokens INT, cache_write_tokens INT, cost_usd REAL,"
        " created_at TEXT);"
    )
    con.execute(
        "INSERT OR REPLACE INTO papers VALUES (?, 'completed', NULL, '2026-09-11 10:30:00', 'single_pass',"
        " 'empirical', 'full', 'empirical', ?)",
        (paper_id, str(workspace) if workspace else None),
    )
    events: list[tuple[str, str | None, str | None, dict]] = [
        ("run_identity", None, None, {"git_sha": COMMIT, "git_dirty": False, "package_version": "0.12.1"}),
        ("phase_start", "initial", None, {}),
        ("specialist_start", None, "idea_developer", {}),
        ("specialist_end", None, "idea_developer", {"success": True}),
        ("specialist_start", None, "paper_drafter", {}),
        ("specialist_end", None, "paper_drafter", {"success": True}),
    ]
    events += [
        ("researcher_action", "review_draft", None, {"action": "approve", "step": "review_draft"})
    ] * researcher_actions
    for i, (etype, stage, sp, payload) in enumerate(events):
        con.execute(
            "INSERT INTO pipeline_events VALUES (?,?,?,?,?,?,?)",
            (f"{paper_id}-{i}", paper_id, etype, stage, sp, json.dumps(payload), f"2026-09-11 10:{i:02d}:00"),
        )
    ws = f"/Users/someone/e2er-studies/s/workspaces/{paper_id}/"
    for i, sp, out in ((3, "idea_developer", "paper_plan.md"), (5, "paper_drafter", "paper_draft.tex")):
        con.execute(
            "INSERT INTO llm_usage VALUES (?,?,?,'claude_code','claude-sonnet-4-5',10,20,0,0,0.0,?)",
            (f"{paper_id}-u{i}", paper_id, sp, f"2026-09-11 10:{i:02d}:00"),
        )
        # the file each step wrote, as the runner records it (an absolute workspace path)
        con.execute(
            "INSERT INTO contributions VALUES (?,?,?,NULL,?,1,NULL,0,0.0,1.0,?)",
            (f"{paper_id}-c{i}", paper_id, sp, ws + out, f"2026-09-11 10:{i:02d}:00"),
        )
    con.commit()
    con.close()
    if env:
        (folder / ".env").write_text(f"DATABASE_URL=sqlite:///{db}\n", encoding="utf-8")
    return db


def paper_id_of(bundle: Path) -> str:
    return json.loads((bundle / "provenance.json").read_text(encoding="utf-8"))["run"]["paper_id"]
