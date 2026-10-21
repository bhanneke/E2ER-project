"""Studies, runs and their database never default to a temporary folder; a chosen one is warned about.

On 2026-10-19 macOS deleted the run databases of five published demos, which
lived under /tmp. e2er started in a temporary folder with nothing set up now
uses the default studies folder (~/e2er-studies); a temporary folder the
researcher chose (a .env there, WORKSPACE_ROOT, DATABASE_URL, OUTPUT_DIR, the
studies folder in Setup) is used, with a warning that the OS may delete it.
"""

from __future__ import annotations

import types
from pathlib import Path

import pytest

from src import home

NOT_TEMPORARY = Path("/e2er-test-home/e2er-studies")  # never created; only compared


@pytest.fixture
def nothing_set_up(tmp_path: Path, monkeypatch) -> Path:
    """No settings anywhere, a default studies folder outside any temporary folder, cwd = a temporary folder."""
    monkeypatch.delenv(home.ENV_PROJECT, raising=False)
    monkeypatch.delenv(home.ENV_TEMPORARY_OK, raising=False)
    # pytest's folders are in the temporary folder; said explicitly, whatever TMPDIR the suite runs with.
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.setattr(home, "state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(home, "default_studies_folder", lambda: NOT_TEMPORARY)
    cwd = tmp_path / "work"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    return cwd


@pytest.mark.parametrize("path", ["/tmp/e2er-demos/papers.db", "/private/tmp/x", "/var/folders/ab/T/x", "/tmp"])
def test_the_systems_temporary_folders_are_recognised(path):
    assert home.temporary_root(path) is not None


def test_tmpdir_is_a_temporary_folder(tmp_path: Path, monkeypatch):
    mine = tmp_path / "my-tmpdir"
    mine.mkdir()
    monkeypatch.setenv("TMPDIR", str(mine))
    assert home.temporary_root(mine / "studies" / "papers.db") is not None


def test_a_folder_in_the_home_folder_is_not_temporary():
    assert home.temporary_root(NOT_TEMPORARY) is None
    assert home.temporary_warning(NOT_TEMPORARY, "the studies folder") is None


def test_nothing_set_up_in_a_temporary_folder_uses_the_default_studies_folder(nothing_set_up: Path):
    assert home.temporary_root(nothing_set_up) is not None, "pytest's folders are temporary"
    assert home.project_dir() == NOT_TEMPORARY


def test_the_test_suites_opt_out_keeps_the_current_folder(nothing_set_up: Path, monkeypatch):
    monkeypatch.setenv(home.ENV_TEMPORARY_OK, "1")
    assert home.project_dir() == Path.cwd()


def test_a_temporary_folder_the_researcher_chose_is_used_with_a_warning(nothing_set_up: Path):
    (nothing_set_up / ".env").write_text("LLM_BACKEND=claude_code\n", encoding="utf-8")
    assert home.project_dir() == nothing_set_up
    (warning,) = home.storage_warnings()
    assert warning.startswith("warning: the studies folder") and "may delete it" in warning
    assert str(nothing_set_up) in warning


def test_run_database_workspaces_and_exports_in_a_temporary_folder_are_each_named(nothing_set_up: Path):
    settings = types.SimpleNamespace(
        workspace_root="/tmp/e2er-demos/studies/workspaces",
        resolved_database_url="sqlite:////tmp/e2er-demos/studies/papers.db",
        output_dir="/tmp/e2er-demos/exports",
    )
    found = home.storage_warnings(settings)
    assert any("the run database (DATABASE_URL) /tmp/e2er-demos/studies/papers.db" in w for w in found)
    assert any("WORKSPACE_ROOT" in w for w in found)
    assert any("OUTPUT_DIR" in w for w in found)


def test_the_defaults_give_no_warning(nothing_set_up: Path, monkeypatch):
    monkeypatch.setattr("src.db.client._sqlite_path", lambda url: str(NOT_TEMPORARY.parent / ".e2er" / "papers.db"))
    settings = types.SimpleNamespace(
        workspace_root=str(NOT_TEMPORARY / "workspaces"), resolved_database_url="", output_dir=None
    )
    assert home.storage_warnings(settings) == []


def test_init_defaults_in_a_temporary_folder_warns(nothing_set_up: Path, monkeypatch, capsys):
    from src import cli_init

    monkeypatch.setattr(cli_init, "_copy_skills_for", lambda *a, **k: None)
    assert cli_init._init_defaults() == 0
    out = capsys.readouterr().out
    assert "warning: the folder you set up e2er in," in out and "may delete it" in out


def test_setup_says_a_chosen_studies_folder_is_temporary(nothing_set_up: Path, tmp_path: Path, monkeypatch):
    from src.api import setup

    req = types.SimpleNamespace(studies_folder=str(tmp_path / "studies"), make_studies_folder=False)
    target, note = setup._choose_folder(req)  # type: ignore[arg-type]
    assert target == (tmp_path / "studies").resolve()
    assert "Warning: this folder," in note and "may delete it" in note
