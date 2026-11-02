"""`e2er run`, `status` and `list` from a terminal on any system (tester report, 2026-11-02).

* A paused or failed run says why, and names `e2er status <id>` as the next
  command: no curl or jq, which PowerShell does not have.
* `e2er status` takes the study key `e2er list` prints and shows the study's
  latest run; `e2er list` shows each study's latest run id.
* The methodology is a line of its own, not a word inside the template's brackets.
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src import cli_export
from src.cli_run import short_reason
from src.cli_status import _format_status_summary
from src.db import client as _client
from src.db import studies as st

_REAL_EXECUTE = _client.execute
_REAL_FETCH_ONE = _client.fetch_one
_REAL_FETCH_ALL = _client.fetch_all

PAUSED = (
    "Stopped for you: the output of Research plan, Literature review, Identification strategy did not pass "
    "its contract check after 3 attempts. Open the run to review it: keep the output as it is, edit a file, "
    "give an instruction, or send the specialist back with a remark."
)


# ── the reason, in a few sentences ───────────────────────────────────────────


def test_short_reason_keeps_the_first_sentences_and_collapses_whitespace():
    text = "First   sentence.\n  Second one!  Third? Fourth sentence. Fifth."
    assert short_reason(text) == "First sentence. Second one! Third?"
    assert short_reason(text, max_sentences=1) == "First sentence."
    assert short_reason(None) == ""
    assert short_reason("   ") == ""


def test_short_reason_caps_a_long_raw_error():
    out = short_reason("x" * 2000)
    assert len(out) <= 400 and out.endswith("…")


def test_short_reason_keeps_the_paused_sentence_whole():
    assert short_reason(PAUSED) == PAUSED


def _run_final(monkeypatch, capsys, final: str, paper: dict) -> tuple[int, str]:
    from src import cli_run

    monkeypatch.setattr(cli_run, "_ensure_api_up", lambda: (True, ""))
    monkeypatch.setattr("src.home.print_storage_warnings", lambda: None)
    monkeypatch.setattr(cli_run, "_submit_paper", lambda *a, **k: {"paper_id": "p-1", "workspace": "ws"})
    monkeypatch.setattr(cli_run, "_poll_status", lambda *a, **k: final)
    monkeypatch.setattr(cli_run, "_fetch_paper", lambda pid: paper)
    code = cli_run.run(rq="Does X raise Y?", acknowledge=True)
    return code, capsys.readouterr().err


def test_a_paused_run_says_why_and_names_e2er_status(monkeypatch, capsys):
    code, err = _run_final(monkeypatch, capsys, "paused", {"status": "paused", "last_error": PAUSED})
    assert code == 1
    assert "Why: Stopped for you: the output of Research plan" in err
    assert "Next: e2er status p-1" in err
    assert "curl" not in err and "jq" not in err


def test_a_failed_run_without_a_reason_still_names_the_next_command(monkeypatch, capsys):
    code, err = _run_final(monkeypatch, capsys, "failed", {})
    assert code == 1
    assert "Why:" not in err
    assert "Next: e2er status p-1" in err


def test_no_user_facing_hint_in_src_uses_curl_or_jq():
    """PowerShell has neither; the hints name e2er commands."""
    src = Path(__file__).resolve().parents[1] / "src"
    offenders = []
    for p in [*src.glob("cli*.py"), src / "__main__.py", src / "doctor.py"]:
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if ("curl " in line or "| jq" in line or "jq -r" in line) and "print" in line:
                offenders.append(f"{p.name}:{n}")
    assert offenders == []


# ── e2er status ──────────────────────────────────────────────────────────────


def _payload(**kw) -> dict:
    base = {
        "id": "41be695b-1fc5-4f6d-8866-fde29e36c651",
        "title": "How does temperature influence electricity consumption",
        "research_question": "How does temperature influence electricity consumption?",
        "status": "completed",
        "pipeline": "empirical",
        "methodology": "empirical",
        "mode": "single_pass",
        "max_cost_usd": 2.0,
        "usage": {},
    }
    base.update(kw)
    return base


def test_status_says_why_a_paused_run_stopped():
    out = _format_status_summary(_payload(status="paused", last_error=PAUSED))
    assert "Why:" in out
    assert "send the specialist back with a remark." in " ".join(out.split())  # whole, wrapped, not cut at 120
    assert all(len(line) <= 100 for line in out.splitlines() if not line.startswith("Dashboard"))


def test_status_says_why_a_failed_run_stopped():
    out = _format_status_summary(_payload(status="failed", last_error="Codex changed no file. " * 10))
    assert "Why:        Codex changed no file." in out
    assert "Last error" not in out


def test_methodology_is_its_own_line():
    out = _format_status_summary(_payload(methodology="theoretical"))
    assert "Template:   empirical (one pass)" in out
    assert "Method:     theoretical: a formal model, no data" in out
    assert "single pass, theoretical" not in out


# ── study keys and run ids ───────────────────────────────────────────────────


@pytest.fixture
def db(tmp_path: Path, monkeypatch) -> Path:
    path = tmp_path / "papers.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{path}")
    monkeypatch.setattr("src.db.client.execute", _REAL_EXECUTE)
    monkeypatch.setattr("src.db.client.fetch_one", _REAL_FETCH_ONE)
    monkeypatch.setattr("src.db.client.fetch_all", _REAL_FETCH_ALL)
    from src.config import get_settings

    get_settings.cache_clear()
    _client._backend = ""
    _client._sqlite_bootstrapped = False
    yield path
    get_settings.cache_clear()
    _client._backend = ""
    _client._sqlite_bootstrapped = False


async def _add(rq: str, status: str, created: str) -> str:
    pid = str(uuid.uuid4())
    await _client.execute(
        "INSERT INTO papers (id, title, research_question, status, pipeline, created_at, updated_at) "
        "VALUES (%(id)s, %(t)s, %(rq)s, %(s)s, 'empirical', %(c)s, %(c)s)",
        {"id": pid, "t": rq[:40], "rq": rq, "s": status, "c": created},
    )
    return pid


def test_a_study_key_resolves_to_its_latest_run(db):
    q = "How does temperature influence electricity consumption?"
    asyncio.run(_add(q, "failed", "2026-11-01 10:00:00"))
    latest = asyncio.run(_add(q, "completed", "2026-11-02 10:00:00"))
    key = st.study_key(q, "empirical")
    pid, note = cli_export.expand_paper_ref(key)
    assert pid == latest
    assert key in note and latest[:8] in note and "v2 of 2" in note
    # A run id and its prefix work as before, without a note.
    assert cli_export.expand_paper_ref(latest) == (latest, "")
    assert cli_export.expand_paper_ref(latest[:8]) == (latest, "")


def test_an_unknown_key_is_passed_on_for_the_not_found_message(db):
    asyncio.run(_add("Some question", "completed", "2026-11-02 10:00:00"))
    assert cli_export.expand_paper_ref("0123456789") == ("0123456789", "")


def test_the_cli_status_takes_the_study_key(db, monkeypatch, capsys):
    import sys

    from src import __main__ as cli
    from src import cli_status

    q = "How does temperature influence electricity consumption?"
    pid = asyncio.run(_add(q, "completed", "2026-11-02 10:00:00"))
    key = st.study_key(q, "empirical")
    seen: dict[str, str] = {}

    def fake_status(paper_id, tail=False, monitor_seconds=0):
        seen["id"] = paper_id
        return 0

    monkeypatch.setattr(cli_status, "status", fake_status)
    monkeypatch.setattr(sys, "argv", ["e2er", "status", key])
    with pytest.raises(SystemExit):
        cli.main()
    assert seen["id"] == pid
    assert f"Study {key}" in capsys.readouterr().err


def test_list_shows_the_latest_run_id_and_says_both_ids_work(db):
    from src.cli_studies import format_list

    q = "How does temperature influence electricity consumption?"
    pid = asyncio.run(_add(q, "in_progress", "2026-11-02 18:10:00"))
    studies, archived = asyncio.run(st.list_studies())
    out = format_list(studies, archived, attempts=False, archived=False)
    assert f"(run {pid[:8]})" in out
    assert "e2er status <key or run id>" in out


def test_status_404_names_e2er_list(capsys):
    from src.cli_status import status

    r = MagicMock()
    r.status_code = 404
    with patch("src.cli_status._api_reachable", return_value=True), patch("httpx.get", return_value=r):
        assert status("b33f3ad47b") == 4
    err = capsys.readouterr().err
    assert "not found" in err and "e2er list --attempts" in err
