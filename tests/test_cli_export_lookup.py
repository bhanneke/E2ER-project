"""`e2er export <id>` finds the workspace from any folder and takes a unique id prefix."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from src import cli_export
from src.cli_export import ExportLookupError, resolve_workspace
from src.modules.local_corpus import iter_corpus_files

PID = "e432cf3f-9008-4202-8ee6-ff09a93948ec"


def _settings(root: Path) -> SimpleNamespace:
    return SimpleNamespace(workspace_root=str(root))


def test_stored_absolute_workspace_is_used_from_another_folder(tmp_path, monkeypatch):
    ws = tmp_path / "study" / "workspaces" / PID
    ws.mkdir(parents=True)
    monkeypatch.setattr(cli_export, "_paper_rows", lambda: [{"id": PID, "workspace": str(ws)}])
    monkeypatch.chdir(tmp_path)  # not the study folder
    assert resolve_workspace(PID, _settings(Path("workspaces"))) == (PID, ws.resolve())


def test_a_unique_prefix_is_enough(tmp_path, monkeypatch):
    ws = tmp_path / PID
    ws.mkdir()
    rows = [{"id": PID, "workspace": str(ws)}, {"id": "ffff0000-1", "workspace": ""}]
    monkeypatch.setattr(cli_export, "_paper_rows", lambda: rows)
    assert resolve_workspace("e432", _settings(tmp_path))[0] == PID


def test_an_ambiguous_prefix_is_refused(tmp_path, monkeypatch):
    rows = [{"id": "abcd1111", "workspace": ""}, {"id": "abcd2222", "workspace": ""}]
    monkeypatch.setattr(cli_export, "_paper_rows", lambda: rows)
    with pytest.raises(ExportLookupError, match="matches 2 papers"):
        resolve_workspace("abcd", _settings(tmp_path))


def test_a_relative_record_falls_back_to_the_workspace_root(tmp_path, monkeypatch):
    root = tmp_path / "workspaces"
    (root / PID).mkdir(parents=True)
    monkeypatch.setattr(cli_export, "_paper_rows", lambda: [{"id": PID, "workspace": f"elsewhere/{PID}"}])
    assert resolve_workspace(PID, _settings(root)) == (PID, (root / PID).resolve())


def test_a_missing_workspace_says_what_to_do(tmp_path, monkeypatch):
    monkeypatch.setattr(cli_export, "_paper_rows", lambda: [{"id": PID, "workspace": f"workspaces/{PID}"}])
    with pytest.raises(ExportLookupError, match="WORKSPACE_ROOT"):
        resolve_workspace(PID, _settings(tmp_path / "none"))


def test_without_a_database_a_workspace_folder_prefix_works(tmp_path, monkeypatch):
    (tmp_path / PID).mkdir()
    monkeypatch.setattr(cli_export, "_paper_rows", lambda: [])
    assert resolve_workspace("e432cf", _settings(tmp_path))[0] == PID


def test_exported_studies_in_the_data_folder_are_not_staged(tmp_path):
    (tmp_path / "e2er_papers" / "old-study" / "data").mkdir(parents=True)
    (tmp_path / "e2er_papers" / "old-study" / "data" / "x.csv").write_text("a\n1\n")
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw" / "y.csv").write_text("a\n1\n")
    found = [p.relative_to(tmp_path).as_posix() for _, p in iter_corpus_files([tmp_path], frozenset({".csv"}), True)]
    assert found == ["raw/y.csv"]


def test_staging_copies_when_links_are_not_allowed(tmp_path, monkeypatch, capsys):
    from src.modules import local_corpus

    src_file = tmp_path / "a.csv"
    src_file.write_text("x\n1\n")

    def no_links(self, *_a, **_k):
        raise OSError("A required privilege is not held by the client")

    monkeypatch.setattr(Path, "symlink_to", no_links)
    monkeypatch.setattr(local_corpus, "_copy_notice_shown", False)
    assert local_corpus.link_or_copy(src_file, tmp_path / "b.csv") == "copied"
    assert (tmp_path / "b.csv").read_text() == "x\n1\n"
    assert "Developer Mode" in capsys.readouterr().err
