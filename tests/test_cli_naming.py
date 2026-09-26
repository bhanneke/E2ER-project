"""The names the commands go by.

Three of them were wrong in the same way: they described the implementation
rather than the thing. `corpus` is a library, `rq` is a question, and
`install-skills` was doing the opposite of `skills install` under a name one
letter of word order away from it.

Renaming a command is not a reason to break it, so every old name still works.
What is tested here is that both spellings reach the same code, and that the
pair that actually collided is now two clearly opposite verbs.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def e2er(*argv: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "src", *argv],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )


# ---------------------------------------------------------------------------
# library / corpus
# ---------------------------------------------------------------------------


def test_library_and_corpus_are_the_same_command():
    a = e2er("library", "--help")
    b = e2er("corpus", "--help")

    assert a.returncode == 0
    assert b.returncode == 0
    assert "search" in a.stdout and "search" in b.stdout


def test_the_help_echoes_back_the_name_that_was_typed():
    """Answering `e2er library --help` with "usage: e2er corpus" invites the
    reader to wonder which one is real."""
    assert "e2er library" in e2er("library", "--help").stdout
    assert "e2er corpus" in e2er("corpus", "--help").stdout


def test_library_is_listed_in_the_top_level_help():
    """An alias nobody can discover is not a rename."""
    out = e2er("--help").stdout
    assert "library" in out


# ---------------------------------------------------------------------------
# question / rq
# ---------------------------------------------------------------------------


def test_question_and_rq_are_the_same_command():
    a = e2er("question", "--help")
    b = e2er("rq", "--help")

    assert a.returncode == 0
    assert b.returncode == 0
    assert "--draft" in a.stdout and "--draft" in b.stdout


def test_question_is_the_name_shown_in_help():
    out = e2er("--help").stdout
    assert "question" in out


# ---------------------------------------------------------------------------
# The collision
# ---------------------------------------------------------------------------


def test_skills_has_both_directions_under_one_command():
    """`install` pulls other people's packs in; `sync` pushes E2ER's own out.

    These were `e2er skills install` and `e2er install-skills` — near-identical
    names for opposite operations, which is a thing only the person who wrote
    them can keep straight.
    """
    out = e2er("skills", "--help").stdout

    assert "install" in out
    assert "sync" in out


def test_sync_takes_the_backend_the_old_command_took():
    out = e2er("skills", "sync", "--help").stdout

    assert "--backend" in out
    assert "--force" in out
    assert "claude" in out


def test_the_old_name_still_works_and_says_what_replaced_it():
    """It is in the README and in people's shell history."""
    r = e2er("install-skills", "--help")

    assert r.returncode == 0
    assert "skills sync" in r.stdout.lower() + r.stderr.lower()


def test_sync_actually_runs_the_installer(monkeypatch):
    """Not just help text.

    Run in-process rather than as a subprocess: the real thing writes into
    ~/.claude/skills, and a test must not touch the machine it runs on.
    """
    called: dict[str, object] = {}

    def fake_install(backend: str = "all", force: bool = False) -> int:
        called.update(backend=backend, force=force)
        return 0

    import src.cli_install_skills as installer

    monkeypatch.setattr(installer, "install_skills", fake_install)

    from src.cli_skills import main as skills_main

    assert skills_main(["sync", "--backend", "codex", "--force"]) == 0
    assert called == {"backend": "codex", "force": True}


def test_the_two_skills_directions_are_described_as_opposites():
    """The help has to do the disambiguating, since the names are close."""
    out = e2er("skills", "--help").stdout.lower()

    assert "in" in out and "out" in out
    assert "rise" in out, "where packs come from"
