"""A run's outcome is whether it finished; the internal quality review is a score (2026-10-02).

The FOMC demonstration study finished every step, the researcher approved its
draft, and its dossier said "Outcome: Rejected": the internal quality review
had aggregated to MAJOR_REVISION (6.11 of 10) and the runner stored
`rejected` after the revision round. The review gives a score and nothing
else. These tests pin that: the status says whether the run finished, the
score is reported separately, old stored review words read as completed, and
no visible text calls the review a verdict.
"""

from __future__ import annotations

import ast
import json
import re
import sqlite3
from pathlib import Path

import pytest

from src.core.dossier import build_dossier, read_run
from src.core.run_outcome import (
    effective_status,
    internal_review,
    review_detail,
    score_words,
    status_words,
    workspace_status,
)

ROOT = Path(__file__).resolve().parents[1]
PID = "9a623c39-87df-4f46-9d6f-d9dcabc84e7a"

#: The FOMC study's review_aggregation.json (verbatim numbers).
FOMC = {
    "verdict": "MAJOR_REVISION",
    "weighted_avg": 6.114285714285714,
    "rule_triggered": "Rule 3: weighted average",
    "rationale": "Weighted average score: 6.11/10. Verdict: MAJOR_REVISION. Breakdown: …",
    "panel": {
        "expected": 6,
        "reported": 6,
        "complete": True,
        "missing": [],
        "scored_without_a_review_file": [],
        "scores": [
            {"reviewer": "mechanism_reviewer", "score": 5.9, "recommendation": "major_revision", "weight": 1.0},
            {"reviewer": "technical_reviewer", "score": 7.0, "recommendation": "minor_revision", "weight": 1.5},
            {"reviewer": "literature_reviewer", "score": 5.65, "recommendation": "major_revision", "weight": 1.0},
            {"reviewer": "writing_reviewer", "score": 8.0, "recommendation": "minor_revision", "weight": 0.75},
            {"reviewer": "data_reviewer", "score": 7.0, "recommendation": "minor_revision", "weight": 1.25},
            {"reviewer": "identification_reviewer", "score": 4.0, "recommendation": "major_revision", "weight": 1.5},
        ],
    },
}


# ── statuses ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("stored", "reviewed", "shown"),
    [
        ("completed", True, "completed"),
        ("completed", False, "completed"),
        ("failed", False, "failed"),
        ("cancelled", True, "cancelled"),
        ("paused", False, "paused"),
        ("in_progress", False, "in_progress"),
        # Up to 0.13.1: a low score stored `rejected` on a run that finished.
        ("rejected", True, "completed"),
        # A check stopped the run before the review.
        ("rejected", False, "stopped"),
        ("accepted", False, "completed"),
        ("major_revision", True, "completed"),
        ("MINOR_REVISION", True, "completed"),
        ("hard_reject", True, "completed"),
    ],
)
def test_the_status_says_whether_the_run_finished(stored: str, reviewed: bool, shown: str):
    assert effective_status(stored, reviewed) == shown


def test_status_words_are_plain():
    assert status_words("stopped") == "stopped by a check"
    assert status_words("in_progress") == "in progress"
    assert status_words("completed") == "completed"


def test_a_workspace_with_the_review_file_reads_as_completed(tmp_path: Path):
    assert workspace_status("rejected", tmp_path) == "stopped"
    (tmp_path / "review_aggregation.json").write_text(json.dumps(FOMC))
    assert workspace_status("rejected", tmp_path) == "completed"
    assert workspace_status("rejected", None) == "stopped"


# ── the score ────────────────────────────────────────────────────────────────


def test_internal_review_records_every_reviewer_and_weight():
    review = internal_review(FOMC, rounds=1)
    assert review == {
        "score": 6.11,
        "scale": 10,
        "combined": "weighted average",
        "reviewers": {
            "mechanism_reviewer": 5.9,
            "technical_reviewer": 7.0,
            "literature_reviewer": 5.65,
            "writing_reviewer": 8.0,
            "data_reviewer": 7.0,
            "identification_reviewer": 4.0,
        },
        "weights": {
            "mechanism_reviewer": 1.0,
            "technical_reviewer": 1.5,
            "literature_reviewer": 1.0,
            "writing_reviewer": 0.75,
            "data_reviewer": 1.25,
            "identification_reviewer": 1.5,
        },
        "rounds": 1,
    }
    # The combined score is the weighted average of exactly these numbers.
    w = review["weights"]
    avg = sum(review["reviewers"][r] * w[r] for r in w) / sum(w.values())
    assert round(avg, 2) == review["score"]
    # Nothing in it is a review word.
    assert not _banned(json.dumps(review))


def test_a_score_one_reviewer_decided_is_labelled_as_such():
    one = {**FOMC, "verdict": "HARD_REJECT", "weighted_avg": 3.5, "rule_triggered": "Rule 2: data_reviewer scored 3.5"}
    assert internal_review(one)["combined"] == "lowest reviewer score"
    mech = {
        **FOMC,
        "verdict": "MECHANISM_FAIL",
        "weighted_avg": 4.2,
        "rule_triggered": "Rule 1: mechanism_reviewer < 5",
    }
    assert internal_review(mech)["combined"] == "mechanism score"


def test_the_round_the_runner_records_wins():
    assert internal_review({**FOMC, "round": 2}, rounds=1)["rounds"] == 2


def test_no_file_or_no_score_means_no_review():
    assert internal_review(None) is None
    assert internal_review({"verdict": "REJECTED"}) is None


def test_score_words():
    assert score_words(6.114285714285714) == "e2er's internal quality review: 6.1 of 10"
    assert review_detail(FOMC).startswith("6.1 of 10 (weighted average): data 7.0, identification 4.0")


# ── the dossier ──────────────────────────────────────────────────────────────


def _run_db(tmp_path: Path, status: str, workspace: Path | None, error: str | None = None) -> Path:
    db = tmp_path / "run.db"
    con = sqlite3.connect(db)
    con.executescript(
        "CREATE TABLE papers (id TEXT, status TEXT, last_error TEXT, updated_at TEXT, workspace TEXT);"
        "CREATE TABLE pipeline_events (id TEXT, paper_id TEXT, event_type TEXT, stage TEXT, specialist TEXT,"
        " payload TEXT, created_at TEXT);"
    )
    con.execute(
        "INSERT INTO papers VALUES (?,?,?,?,?)",
        (PID, status, error, "2026-09-29 15:59:32", str(workspace) if workspace else None),
    )
    for i, (etype, stage, at) in enumerate(
        [
            ("phase_start", "review", "2026-09-29 15:47:45"),
            ("phase_end", "review", "2026-09-29 15:55:12"),
            ("phase_start", "revision", "2026-09-29 15:55:12"),
            ("phase_end", "revision", "2026-09-29 15:57:15"),
        ]
    ):
        con.execute("INSERT INTO pipeline_events VALUES (?,?,?,?,?,?,?)", (str(i), PID, etype, stage, None, "{}", at))
    con.commit()
    con.close()
    return db


def _manifest() -> dict:
    return {
        "title": "FOMC",
        "ai": {"backend": "claude_code", "model": "m", "usage": []},
        "process": {"paper_id": PID, "template": "event-study-finance", "mode": "single_pass"},
        "dependencies": {"uses": []},
        "data": [],
    }


def test_a_finished_run_with_a_low_score_is_completed_with_its_score(tmp_path: Path):
    """The FOMC case: stored `rejected`, review file in the workspace."""
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "review_aggregation.json").write_text(json.dumps(FOMC))
    db = _run_db(tmp_path, "rejected", ws, error="MAJOR_REVISION: Weighted average score: 6.11/10. Verdict: …")
    run = read_run(db, PID)
    assert run.outcome == {"status": "completed", "at": "2026-09-29T15:59:32Z"}
    doc = build_dossier(_manifest(), run=run)
    assert doc["run"]["outcome"] == {"status": "completed", "at": "2026-09-29T15:59:32Z"}
    assert doc["run"]["internal_review"]["score"] == 6.11
    assert doc["run"]["internal_review"]["rounds"] == 1
    assert len(doc["run"]["internal_review"]["reviewers"]) == 6
    assert not _banned(json.dumps(doc["run"]["outcome"]) + json.dumps(doc["run"]["internal_review"]))


@pytest.mark.parametrize("code", ["MAJOR_REVISION", "HARD_REJECT", "MECHANISM_FAIL", "ACCEPT"])
def test_every_aggregated_code_gives_completed_and_a_score(tmp_path: Path, code: str):
    bundle = tmp_path / "bundle"
    (bundle / "reviews").mkdir(parents=True)
    (bundle / "reviews" / "review_aggregation.json").write_text(json.dumps({**FOMC, "verdict": code}))
    stored = "completed" if code == "ACCEPT" else "rejected"
    run = read_run(_run_db(tmp_path, stored, None), PID, bundle=bundle)
    assert run.outcome["status"] == "completed"
    assert run.internal_review and run.internal_review["score"] == 6.11


def test_the_bundle_file_is_read_before_the_workspace(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "review_aggregation.json").write_text(json.dumps({**FOMC, "weighted_avg": 2.0}))
    bundle = tmp_path / "bundle"
    (bundle / "reviews").mkdir(parents=True)
    (bundle / "reviews" / "review_aggregation.json").write_text(json.dumps(FOMC))
    run = read_run(_run_db(tmp_path, "rejected", ws), PID, bundle=bundle)
    assert run.internal_review["score"] == 6.11


def test_the_replication_template_completes_without_a_score(tmp_path: Path):
    """The replication template has no internal quality review."""
    run = read_run(_run_db(tmp_path, "completed", tmp_path / "nowhere"), PID)
    assert run.outcome["status"] == "completed"
    assert run.internal_review is None
    assert "internal_review" not in build_dossier(_manifest(), run=run)["run"]


def test_a_check_that_stopped_the_run_keeps_its_error(tmp_path: Path):
    run = read_run(_run_db(tmp_path, "rejected", None, error="verify_numbers: 2 critical mismatch(es)"), PID)
    assert run.outcome["status"] == "stopped"
    assert run.outcome["error"].startswith("verify_numbers")


# ── no review words in visible text ──────────────────────────────────────────

_BANNED = re.compile(
    r"\b(reject(ed|s|ion)?|accept(ed|s)?|major[\s_-]*revision|minor[\s_-]*revision|"
    r"revise[\s-]+and[\s-]+resubmit|R&R|desk[\s-]*reject(ed)?|verdicts?)\b",
    re.IGNORECASE,
)


def _banned(text: str) -> list[str]:
    return [m.group(0) for m in _BANNED.finditer(text)]


#: Identifiers in templates that are not visible text: a CSS class, a JSON key of `e2er verify`, and the
#: file types a file field takes (``accept=".pdf,.bib"``).
_TEMPLATE_IDENTIFIERS = ("pf-verdict", "d.verdict", 'accept="')


@pytest.mark.parametrize("path", sorted((ROOT / "src" / "api" / "templates").glob("*.html")), ids=lambda p: p.name)
def test_dashboard_templates_use_no_review_words(path: Path):
    text = path.read_text(encoding="utf-8")
    for ident in _TEMPLATE_IDENTIFIERS:
        text = text.replace(ident, "")
    # Jinja and HTML comments are not shown.
    text = re.sub(r"\{#.*?#\}|<!--.*?-->", "", text, flags=re.S)
    assert not _banned(text), f"{path.name}: {_banned(text)}"


#: Modules whose strings reach a reader: CLI output, the dashboard's words, the export's README and report.
_VISIBLE_MODULES = [
    "src/cli_status.py",
    "src/cli_run.py",
    "src/cli_studies.py",
    "src/core/run_outcome.py",
    "src/core/export/report.py",
    "src/core/export/structured.py",
    "src/db/studies.py",
    "src/core/strategist/runner.py",
]


def _visible_strings(path: Path) -> list[str]:
    """String constants that can be shown, minus docstrings and bare identifiers (internal codes)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docstrings.add(id(body[0].value))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            if re.fullmatch(r"[A-Za-z_]+", node.value):
                continue  # an identifier or status code compared in code, never a sentence
            out.append(node.value)
    return out


@pytest.mark.parametrize("rel", _VISIBLE_MODULES)
def test_visible_strings_use_no_review_words(rel: str):
    found = [s for s in _visible_strings(ROOT / rel) if _banned(s)]
    assert not found, f"{rel}: {found}"


def test_the_dashboard_review_row_is_a_score(tmp_path: Path):
    from src.api.app import _gate_verdicts

    (tmp_path / "review_aggregation.json").write_text(json.dumps(FOMC))
    [row] = _gate_verdicts(tmp_path)
    assert row["ok"] is None
    assert row["label"] == "Internal quality review"
    assert row["note"].startswith("6.1 of 10")
    assert not _banned(json.dumps(row))


def test_the_export_report_shows_the_score(tmp_path: Path):
    from src.core.export.report import _verdicts

    (tmp_path / "reviews").mkdir()
    (tmp_path / "reviews" / "review_aggregation.json").write_text(json.dumps(FOMC))
    [row] = _verdicts(tmp_path)
    assert row["name"] == "e2er's internal quality review" and row["ok"] is None
    assert not _banned(json.dumps(row))
