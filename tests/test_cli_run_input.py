"""How `e2er run` / `e2er run-matrix` take the research question.

Three ways in: positional, `--rq`, `--rq-file`. `--rq` needs its own option —
argparse prefix-expands an unknown `--rq` to `--rq-file` and then tries to OPEN
the research question as a filename, which used to end in a raw
FileNotFoundError traceback for the most obvious command a new user types.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from src.__main__ import main
from src.cli_run import RQInputError, resolve_rq_input


def _argv(monkeypatch, *args: str) -> None:
    monkeypatch.setattr(sys, "argv", ["e2er", *args])


@pytest.fixture
def captured_run(monkeypatch):
    """Intercept cli_run.run so nothing is actually submitted."""
    seen: dict = {}

    def fake_run(**kwargs):
        seen.update(kwargs)
        return 0

    monkeypatch.setattr("src.cli_run.run", fake_run)
    return seen


# ── resolve_rq_input ─────────────────────────────────────────────────────────


def test_positional_rq_passes_through():
    assert resolve_rq_input("does X cause Y", None) == "does X cause Y"


def test_rq_file_reads_plain_text(tmp_path: Path):
    f = tmp_path / "q.txt"
    f.write_text("  does X cause Y  \n")
    assert resolve_rq_input(None, str(f)) == "does X cause Y"


def test_rq_file_reads_rq_json(tmp_path: Path):
    f = tmp_path / "rq.json"
    f.write_text(json.dumps({"research_question": "does X cause Y", "rationale": "..."}))
    assert resolve_rq_input(None, str(f)) == "does X cause Y"


def test_missing_rq_file_raises_a_reportable_error(tmp_path: Path):
    with pytest.raises(RQInputError, match="could not read --rq-file"):
        resolve_rq_input(None, str(tmp_path / "nope.json"))


# ── argv handling ────────────────────────────────────────────────────────────


def test_run_accepts_rq_option(monkeypatch, captured_run):
    """The regression: `e2er run --rq "<RQ>"` prefix-expanded to --rq-file and
    crashed trying to open the question as a file."""
    _argv(monkeypatch, "run", "--rq", "does X cause Y")
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0
    assert captured_run["rq"] == "does X cause Y"


def test_run_accepts_positional_rq(monkeypatch, captured_run):
    _argv(monkeypatch, "run", "does X cause Y")
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0
    assert captured_run["rq"] == "does X cause Y"


def test_run_reports_unreadable_rq_file_without_traceback(monkeypatch, capsys):
    _argv(monkeypatch, "run", "--rq-file", "/nonexistent/rq.json")
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
    assert "could not read --rq-file" in capsys.readouterr().err


def test_run_matrix_accepts_rq_option(monkeypatch):
    seen: dict = {}

    def fake_matrix(**kwargs):
        seen.update(kwargs)
        return 0

    monkeypatch.setattr("src.cli_run_matrix.run_matrix", fake_matrix)
    _argv(monkeypatch, "run-matrix", "--rq", "does X cause Y", "--backends", "codex")
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0
    assert seen["rq"] == "does X cause Y"
    assert seen["backends"] == ["codex"]


# ── the API port `run` talks to ──────────────────────────────────────────────


def test_run_honours_the_configured_port(monkeypatch):
    """cli_run hardcoded 8280 for both the reachability probe and the uvicorn
    spawn, so PORT in .env did nothing.

    The consequence is worse than an ignored setting: if anything already
    listens on 8280 the probe succeeds and `e2er run` submits the paper to it —
    another project's server, or an older E2ER whose process predates the last
    upgrade. uvicorn runs without --reload, so that server serves stale code and
    the run silently exercises a version the user no longer has installed.
    """
    from src import cli_run

    monkeypatch.delenv("E2ER_API_URL", raising=False)
    monkeypatch.setattr(cli_run, "_api_port", lambda: 8391)

    assert cli_run._api_root() == "http://127.0.0.1:8391"


def test_explicit_api_url_still_wins(monkeypatch):
    """The escape hatch has to keep working — it is how a user points `run` at
    a server they started themselves."""
    from src import cli_run

    monkeypatch.setenv("E2ER_API_URL", "http://127.0.0.1:8399/")
    assert cli_run._api_root() == "http://127.0.0.1:8399"


def test_api_port_falls_back_when_settings_are_unreadable(monkeypatch):
    """A broken config must not stop `run` from working at the default."""
    from src import cli_run

    def _boom():
        raise RuntimeError("unreadable .env")

    monkeypatch.setattr("src.config.get_settings", _boom)
    assert cli_run._api_port() == 8280
