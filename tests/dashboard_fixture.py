"""A dashboard full of studies, one at every kind of stop, for page tests and screenshots.

``build(folder)`` writes a study folder (``.env``, ``workspaces/``), a SQLite
run database and, per study, the workspace files, the saved run state and the
event log a real run leaves behind. Nothing runs: the pages read what is on
disk and in the database, as they do after a real run.

Used by tests/test_dashboard_vocabulary.py (every page rendered and read for
internal names) and by the before/after screenshots of the dashboard. Run it
directly to make a folder for a local server::

    python -m tests.dashboard_fixture /tmp/fixture

The environment (``DATABASE_URL``, ``WORKSPACE_ROOT``) must point at the
folder before the e2er modules read their settings: :func:`env_for` gives it.
"""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

QUESTION = "Do FOMC announcements move regional bank stocks more than large banks?"

TABLE_TEX = r"""\begin{table}
\caption{Sample prices}
\begin{tabular}{lr}
KBE mean & 41.20 \\
\end{tabular}
\end{table}
"""

_FILES: dict[str, str] = {
    "paper_plan.md": "# Paper plan\n\nWe study the reaction of regional bank stocks to FOMC announcements.\n",
    "identification_strategy.md": "# Identification\n\nAn event study around 64 scheduled announcements.\n",
    "identification_spec.json": json.dumps({"design": "event_study", "estimator": "ols", "window": [-1, 1]}, indent=2),
    "literature_review.md": "# Literature\n\nBernanke and Kuttner (2005) measure the stock market response.\n",
    "data_summary.md": "# Data\n\nDaily returns of KBE and KRE, 2015 to 2024, from Yahoo Finance.\n",
    "summary_statistics.json": json.dumps({"price_series": {"kbe": {"mean": 36.69}}}, indent=2),
    "estimation_results.json": json.dumps({"coefficients": {"announcement": 0.42}}, indent=2),
    "paper_draft.tex": "\\documentclass{article}\n\\begin{document}\n\\section{Results}\n"
    + TABLE_TEX
    + "\\end{document}\n",
    "preregistration.md": "# Pre-registration\n\nHypothesis: regional banks react more strongly.\n",
}


@dataclass
class Fixture:
    folder: Path
    study: Path
    db: Path
    ids: dict[str, str] = field(default_factory=dict)
    keys: dict[str, str] = field(default_factory=dict)


def env_for(folder: Path) -> dict[str, str]:
    """The settings that point e2er at the fixture folder (with a data folder and a literature folder)."""
    study = folder / "study"
    return {
        "DATABASE_URL": f"sqlite:///{folder / 'papers.db'}",
        "WORKSPACE_ROOT": str(study / "workspaces"),
        "OUTPUT_DIR": str(study / "exports"),
        "LLM_BACKEND": "claude_code",
        "LOCAL_DATA_DIR": str(study / "data"),
        "LITERATURE_DIR": str(study / "literature"),
    }


_BIB = """@article{Bernanke:2005,
  title = {What Explains the Stock Market's Reaction to Federal Reserve Policy?},
  author = {Bernanke, Ben S. and Kuttner, Kenneth N.},
  journal = {Journal of Finance},
  year = {2005},
}
"""


def _folders(study: Path) -> None:
    """The researcher's data and literature folders, as New study lists them."""
    (study / "data").mkdir(parents=True, exist_ok=True)
    (study / "data" / "fomc_announcement_dates.csv").write_text("date\n2015-12-16\n", encoding="utf-8")
    (study / "data" / "bank_tickers.csv").write_text("ticker\nKBE\nKRE\n", encoding="utf-8")
    (study / "literature").mkdir(parents=True, exist_ok=True)
    (study / "literature" / "refs.bib").write_text(_BIB, encoding="utf-8")


def _write_inputs(ws: Path) -> None:
    """What the study used: chosen files, a table, the researcher's paper and one found on the web, cited."""
    import sqlite3

    from src.core.study_inputs import write_record
    from src.modules.literature.models import PaperMetadata

    write_record(
        ws,
        {
            "data": {
                "chosen": True,
                "files": [
                    {"name": "fomc_announcement_dates.csv", "origin": "folder", "size": 20},
                    {"name": "bank_balance_sheets.csv", "origin": "upload", "size": 4096},
                ],
            },
            "papers": {
                "chosen": True,
                "web_search": True,
                "items": [{"key": "Bernanke:2005", "title": "What Explains", "kind": "bib", "origin": "folder"}],
            },
        },
    )
    mine = PaperMetadata(
        title="What Explains the Stock Market's Reaction to Federal Reserve Policy?",
        authors=["Bernanke, Ben S.", "Kuttner, Kenneth N."],
        year=2005,
        source="bibtex",
        cite_key="Bernanke:2005",
    )
    web = PaperMetadata(
        title="Monetary Policy, Bank Equity and the Federal Budget",
        authors=["Ann English"],
        year=2018,
        source="openalex",
    )
    (ws / "literature.bib").write_text(mine.to_bibtex() + "\n\n" + web.to_bibtex() + "\n", encoding="utf-8")
    draft = ws / "paper_draft.tex"
    draft.write_text(
        draft.read_text(encoding="utf-8").replace(
            "\\section{Results}",
            "\\section{Results}\nAs \\citet{Bernanke:2005} and \\citet{english2018monetary} find.\n",
        ),
        encoding="utf-8",
    )
    con = sqlite3.connect(ws / "data.db")
    con.execute("CREATE TABLE IF NOT EXISTS fomc_announcement_dates (date TEXT)")
    con.execute("INSERT INTO fomc_announcement_dates VALUES ('2015-12-16')")
    con.commit()
    con.close()
    (ws / "data_sources.json").write_text(
        json.dumps(
            {
                "loads": [
                    {
                        "connector": "data-folder",
                        "dataset": "The researcher's data folder",
                        "series": "fomc_announcement_dates.csv",
                        "table": "fomc_announcement_dates",
                        "files": [{"path": "data/fomc_announcement_dates.csv", "sha256": "c" * 64}],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


#: name → (template, mode, status, last_error, pending step, review metadata, extra state metadata)
def _studies() -> dict[str, dict[str, Any]]:
    return {
        "design_review": {
            "pipeline": "empirical-preregistered",
            "status": "paused",
            "pending": "review_design",
            "completed": ["initial"],
            "review": {"kind": "researcher", "files": ["paper_plan.md", "identification_strategy.md"]},
        },
        "preregistration": {
            "pipeline": "empirical-preregistered",
            "status": "paused",
            "pending": "preregister",
            "completed": ["initial"],
            "approved": ["review_design"],
            "review": {"kind": "preregister", "files": ["preregistration.md"]},
        },
        "contract": {
            "pipeline": "empirical",
            "status": "paused",
            "pending": "output_contract",
            "completed": [],
            "review": {
                "kind": "contract",
                "files": ["paper_draft.tex"],
                "reasons": ["paper_drafter, attempt 1 of 3: inline tabular instead of \\input{tables/...}"],
            },
            "meta": {
                "contract_pause": {
                    "phase": "initial",
                    "failed": [
                        {
                            "specialist": "paper_drafter",
                            "attempts": [
                                {"attempt": n, "violations": ["inline tabular instead of \\input{tables/...}"]}
                                for n in (1, 2, 3)
                            ],
                            "files": ["paper_draft.tex"],
                        }
                    ],
                    "succeeded": ["idea_developer", "data_analyst"],
                }
            },
        },
        "numbers": {
            "pipeline": "empirical",
            "status": "paused",
            "pending": "number_check",
            "completed": ["initial", "estimation_gate"],
            "review": {
                "kind": "numbers",
                "files": ["paper_draft.tex", "summary_statistics.json"],
                "reasons": [
                    "Sample prices: the table says 41.20, the results say 36.69 "
                    "(summary_statistics.json.price_series.kbe.mean)"
                ],
            },
            "meta": {
                "number_check": {
                    "mismatches": [
                        {
                            "cell": "Sample prices",
                            "in_table": "41.20",
                            "in_results": "36.69",
                            "source_key": "summary_statistics.json.price_series.kbe.mean",
                            "source_file": "summary_statistics.json",
                            "key": "summary_statistics.json.price_series.kbe.mean|41.20",
                        }
                    ],
                    "auto_patch": "it made no edits",
                }
            },
        },
        "deviation": {
            "pipeline": "empirical-preregistered",
            "status": "paused",
            "pending": "estimation_gate",
            "completed": ["initial"],
            "approved": ["review_design", "preregister"],
            "review": {
                "kind": "deviation",
                "files": ["identification_spec.json"],
                "reasons": ["identification_spec.json changed after the pre-registration was frozen"],
            },
        },
        "gate": {
            "pipeline": "event-study-finance",
            "status": "paused",
            "pending": "event_window_gate",
            "completed": ["initial"],
            "review": {
                "kind": "gate",
                "files": [],
                "reasons": ["3 of 64 event windows overlap another event (share 0.05, allowed 0.00)"],
            },
        },
        "asked_stop": {
            "pipeline": "empirical",
            "status": "paused",
            "pending": "review",
            "completed": ["initial", "estimation_gate", "review"],
            "review": {"kind": "review_at", "files": []},
            "review_stages": ["review"],
            "stage_outputs": {"review": {"technical_reviewer": "review_technical.md"}},
        },
        "spending_limit": {
            "pipeline": "empirical",
            "status": "paused",
            "completed": ["initial"],
            "last_error": "BudgetExceededError: spent $0.52 of the $0.50 limit",
            "cap": 0.5,
        },
        "interrupted": {
            "pipeline": "empirical",
            "status": "paused",
            "completed": ["initial"],
            "last_error": "Server shutdown while in-flight; POST /resume to continue.",
        },
        "finished": {
            "pipeline": "empirical",
            "status": "completed",
            "completed": ["initial", "estimation_gate", "review", "revision", "replication"],
            "finished": True,
        },
        "failed": {
            "pipeline": "empirical",
            "status": "failed",
            "completed": [],
            "last_error": "RuntimeError: All specialists failed in the review step: technical_reviewer, "
            "writing_reviewer; the model returned an error",
            "feedback": {"technical_reviewer": "file not written: review_technical.md"},
        },
        "stopped": {
            "pipeline": "empirical",
            "status": "rejected",
            "completed": ["initial"],
            "last_error": "Stopped by the estimation check: estimation_results.json has no regression",
        },
        "cancelled": {"pipeline": "empirical", "status": "cancelled", "completed": ["initial"]},
        # The iterative mode: two rounds, a ceiling check after each, a change of approach, the self-critique.
        "iterative": {
            "pipeline": "empirical",
            "mode": "iterative",
            "status": "completed",
            "completed": ["initial", "iterative", "estimation_gate", "self_attack", "polish", "review", "revision"]
            + ["replication"],
            "finished": True,
            "rounds": [
                (
                    "improvement_round",
                    {
                        "round": 1,
                        "specialists": ["econometrics_specialist", "paper_drafter"],
                        "reason": "Confirm the estimates before more writing builds on them.",
                    },
                ),
                ("ceiling_check", {"round": 1, "verdict": "continue", "reason": "The H2 discussion can be sharper."}),
                (
                    "improvement_round",
                    {
                        "round": 2,
                        "specialists": ["section_writer"],
                        "reason": "section:discussion overstates what 31 events show (paper_drafter).",
                    },
                ),
                (
                    "ceiling_check",
                    {
                        "round": 2,
                        "verdict": "pivot",
                        "reason": "The abstract needs a different step.",
                        "pivot": ["abstract_writer"],
                    },
                ),
                ("pivot", {"round": 2, "specialists": ["abstract_writer"], "focus": ["Rewrite the abstract."]}),
                (
                    "self_critique",
                    {
                        "findings": 2,
                        "serious": 1,
                        "max_severity": 7,
                        "categories": ["framing"],
                        "corrections_made": 1,
                        "corrections_failed": 0,
                    },
                ),
                (
                    "polish_applied",
                    {"notes": ["polish_formula", "polish_numerics"], "decision": "applied", "changes_made": 1},
                ),
            ],
        },
    }


def _events(paper_id: str, spec: dict[str, Any]) -> list[tuple[Any, ...]]:
    ev: list[tuple[Any, ...]] = [("phase_start", "initial", None)]
    for sp in ("idea_developer", "literature_scanner", "data_analyst", "econometrics_specialist", "paper_drafter"):
        ev += [("specialist_start", "initial", sp), ("specialist_end", "initial", sp)]
    if "initial" in spec.get("completed", []):
        ev.append(("phase_end", "initial", None))
    if spec.get("feedback"):
        for sp in spec["feedback"]:
            ev += [("specialist_start", "review", sp), ("specialist_failed", "review", sp)]
    if spec.get("rounds"):
        ev.append(("phase_start", "iterative", None))
        for et, payload in spec["rounds"]:
            stage = {"self_critique": "self_attack", "polish_applied": "polish"}.get(et, "iterative")
            ev.append((et, stage, None, payload))
            if et == "improvement_round":
                for sp in payload["specialists"]:
                    ev += [("specialist_start", stage, sp), ("specialist_end", stage, sp)]
        ev.append(("phase_end", "iterative", None))
    if spec.get("finished"):
        for st in ("review", "revision", "replication"):
            ev += [("phase_start", st, None), ("phase_end", st, None)]
    for stage, outs in spec.get("stage_outputs", {}).items():
        ev.append(("phase_start", stage, None))
        for sp in outs:
            ev += [("specialist_start", stage, sp), ("specialist_end", stage, sp)]
        ev.append(("phase_end", stage, None))
    if spec.get("pending") in {"event_window_gate", "estimation_gate"}:
        ev.append(("gate_halted", spec["pending"], None))
    return ev


def _write_workspace(ws: Path, paper_id: str, name: str, spec: dict[str, Any]) -> None:
    ws.mkdir(parents=True, exist_ok=True)
    for fname, body in _FILES.items():
        (ws / fname).write_text(body, encoding="utf-8")
    (ws / "tables").mkdir(exist_ok=True)
    (ws / "tables" / "h2_results.tex").write_text(TABLE_TEX, encoding="utf-8")
    manifest = {
        "paper_id": paper_id,
        "title": f"FOMC and bank stocks ({name.replace('_', ' ')})",
        "research_question": QUESTION,
        "mode": "single_pass",
        "methodology": "empirical",
        "pipeline": spec["pipeline"],
        "purpose": "demonstration",
    }
    (ws / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    _write_inputs(ws)
    state = {
        "paper_id": paper_id,
        "mode": "single_pass",
        "completed_stages": list(spec.get("completed", [])),
        "approved_stages": list(spec.get("approved", [])),
        "pending_review_stage": spec.get("pending"),
        "metadata": {**({"review": spec["review"]} if spec.get("review") else {}), **spec.get("meta", {})},
    }
    from src.core.pipeline.state import PipelineState

    st = PipelineState.load(ws, paper_id, "single_pass")
    st.completed_stages = state["completed_stages"]
    st.approved_stages = state["approved_stages"]
    st.pending_review_stage = state["pending_review_stage"]
    st.metadata = state["metadata"]
    if spec.get("finished"):
        st.last_status = "completed"
    st.save(ws)
    if spec.get("finished"):
        (ws / "review_aggregation.json").write_text(
            json.dumps({"weighted_score": 7.4, "decision": "minor_revision", "scores": {"technical_reviewer": 7.0}}),
            encoding="utf-8",
        )
        (ws / "number_verification.json").write_text(json.dumps({"matched": 12, "mismatches": []}), encoding="utf-8")
        (ws / "citation_integrity.json").write_text(
            json.dumps({"passed": True, "verified": 9, "total_cites": 9, "missing_in_bib": 0}), encoding="utf-8"
        )
        (ws / "paper_draft.pdf").write_bytes(b"%PDF-1.4\n%fixture\n")
    for outs in spec.get("stage_outputs", {}).values():
        for fname in outs.values():
            (ws / fname).write_text("# Technical review\n\nOVERALL SCORE: 7.0/10\n", encoding="utf-8")
    if spec.get("feedback"):
        fb = ws / ".contract_feedback"
        fb.mkdir(exist_ok=True)
        for sp, text in spec["feedback"].items():
            (fb / f"{sp}.txt").write_text(text, encoding="utf-8")


async def _populate(fx: Fixture) -> None:
    from src.config import get_settings
    from src.db import client
    from src.db.studies import study_key

    get_settings.cache_clear()
    client._backend = ""
    client._sqlite_bootstrapped = False
    await client.fetch_all("SELECT 1")
    for name, spec in _studies().items():
        paper_id = str(uuid.uuid4())
        ws = fx.study / "workspaces" / paper_id
        _write_workspace(ws, paper_id, name, spec)
        title = f"FOMC and bank stocks ({name.replace('_', ' ')})"
        await client.execute(
            """
            INSERT INTO papers (id, title, research_question, status, workspace, mode, methodology, model, backend,
                                governance, review_stages, max_cost_usd, pipeline, study_key)
            VALUES (%(id)s, %(title)s, %(rq)s, %(status)s, %(ws)s, %(mode)s, 'empirical', 'claude-sonnet-4-6',
                    'claude_code', 'full', %(rs)s, %(cap)s, %(pipeline)s, %(key)s)
            """,
            {
                "id": paper_id,
                "title": title,
                "rq": QUESTION,
                "status": spec["status"],
                "ws": str(ws.resolve()),
                "rs": json.dumps(spec.get("review_stages", [])),
                "cap": spec.get("cap", 5.0),
                "pipeline": spec["pipeline"],
                "mode": spec.get("mode", "single_pass"),
                "key": study_key(QUESTION, spec["pipeline"], title),
            },
        )
        if spec.get("last_error"):
            await client.execute(
                "UPDATE papers SET last_error = %(e)s WHERE id = %(id)s", {"e": spec["last_error"], "id": paper_id}
            )
        for et, stage, who, *payload in _events(paper_id, spec):
            await client.execute(
                "INSERT INTO pipeline_events (paper_id, event_type, stage, specialist, payload) "
                "VALUES (%(p)s, %(t)s, %(st)s, %(sp)s, %(pl)s::jsonb)",
                {"p": paper_id, "t": et, "st": stage, "sp": who, "pl": json.dumps(payload[0] if payload else {})},
            )
        if spec.get("approved"):
            await client.execute(
                "INSERT INTO pipeline_events (paper_id, event_type, stage, specialist, payload) "
                "VALUES (%(p)s, 'researcher_action', %(st)s, NULL, %(pl)s::jsonb)",
                {
                    "p": paper_id,
                    "st": spec["approved"][0],
                    "pl": json.dumps({"action": "approve", "step": spec["approved"][0]}),
                },
            )
        fx.ids[name] = paper_id
        row = await client.fetch_one("SELECT study_key FROM papers WHERE id = %(id)s", {"id": paper_id})
        fx.keys[name] = str((row or {}).get("study_key") or "")
    await client.close_pool()


def _exports(fx: Fixture) -> None:
    """The finished study's folders: two older copies, then the current one, published as version 2."""
    import time

    from src.core.export.structured import export_paper

    pid = fx.ids["finished"]
    ws = fx.study / "workspaces" / pid
    for _ in range(3):
        out = export_paper(ws, fx.study / "exports", date_str="20261008")
        time.sleep(0.01)
    (out / ".e2er").mkdir()
    (out / ".e2er" / "link.json").write_text(
        json.dumps(
            {
                "platform_url": "https://e2er.org",
                "owner_project": "kim-dash/fomc-bank-stocks",
                "version": 2,
                "dossier_id": "sha256:" + "b" * 64,
            }
        ),
        encoding="utf-8",
    )


def build(folder: Path) -> Fixture:
    """Write the fixture into ``folder``. The environment must already point at it (:func:`env_for`)."""
    folder = folder.resolve()
    study = folder / "study"
    (study / "workspaces").mkdir(parents=True, exist_ok=True)
    env = env_for(folder)
    (study / ".env").write_text("".join(f"{k}={v}\n" for k, v in env.items()), encoding="utf-8")
    fx = Fixture(folder=folder, study=study, db=folder / "papers.db")
    _folders(study)
    asyncio.run(_populate(fx))
    _exports(fx)
    (folder / "fixture.json").write_text(json.dumps({"ids": fx.ids, "keys": fx.keys}, indent=2), encoding="utf-8")
    return fx


if __name__ == "__main__":
    import os

    target = Path(sys.argv[1])
    os.environ.update(env_for(target.resolve()))
    print(json.dumps(build(target).ids, indent=2))
