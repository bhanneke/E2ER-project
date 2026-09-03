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
