"""Tests for GitHub integration — create repos, push files, push directories."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest


def _make_mock_github(repo: MagicMock | None = None) -> tuple[MagicMock, MagicMock, MagicMock]:
    """Return (mock_Github_class, mock_user, mock_repo)."""
    mock_gh_cls = MagicMock()
    mock_user = MagicMock()
    mock_repo = repo or MagicMock()
    mock_gh_cls.return_value.get_user.return_value = mock_user
    mock_user.create_repo.return_value = mock_repo
    mock_user.get_repo.return_value = mock_repo
    mock_repo.clone_url = "https://github.com/test/paper-test.git"
    mock_repo.html_url = "https://github.com/test/paper-test"
    mock_repo.ssh_url = "git@github.com:test/paper-test.git"
    return mock_gh_cls, mock_user, mock_repo


# ---------------------------------------------------------------------------
# create_paper_repo
# ---------------------------------------------------------------------------

def test_create_paper_repo_returns_urls():
    mock_gh_cls, mock_user, mock_repo = _make_mock_github()

    with patch("github.Github", mock_gh_cls):
        from src.modules.github.client import GitHubClient

        client = GitHubClient("fake-token", "fake-user")
        result = client.create_paper_repo("paper-uuid-1234", "DeFi Liquidity Study")

    assert "repo_name" in result
    assert "clone_url" in result
    assert "html_url" in result
    assert "ssh_url" in result
    assert result["clone_url"] == "https://github.com/test/paper-test.git"


def test_create_paper_repo_commits_gitignore_first():
    """Critical invariant: .gitignore must be the FIRST commit, before README."""
    mock_gh_cls, mock_user, mock_repo = _make_mock_github()

    with patch("github.Github", mock_gh_cls):
        from src.modules.github.client import GitHubClient

        client = GitHubClient("fake-token", "fake-user")
        client.create_paper_repo("paper-uuid-1234", "Test Paper")

    calls = mock_repo.create_file.call_args_list
    # Should have at least 2 create_file calls (.gitignore and README)
    assert len(calls) >= 2
    first_path = calls[0][1].get("path") or calls[0][0][0]
    assert first_path == ".gitignore", (
        f".gitignore must be the first commit; got '{first_path}' instead. "
        "This invariant ensures Overleaf import works cleanly."
    )


def test_create_paper_repo_existing_repo_reused():
    """If the repo already exists, the client should reuse it, not crash."""
    mock_gh_cls, mock_user, mock_repo = _make_mock_github()
    mock_user.create_repo.side_effect = Exception("Repository creation failed: name already exists")
    mock_user.get_repo.return_value = mock_repo

    with patch("github.Github", mock_gh_cls):
        from src.modules.github.client import GitHubClient

        client = GitHubClient("fake-token", "fake-user")
        result = client.create_paper_repo("paper-uuid-1234", "Test Paper")

    assert "repo_name" in result


def test_create_paper_repo_slug_from_title():
    mock_gh_cls, mock_user, mock_repo = _make_mock_github()

    with patch("github.Github", mock_gh_cls):
        from src.modules.github.client import GitHubClient

        client = GitHubClient("fake-token", "fake-user")
        result = client.create_paper_repo("abcd1234", "DeFi Liquidity & Market Quality!")

    # Slug should be lowercase, alphanumeric and hyphens only, prefixed with "paper-"
    name = result["repo_name"]
    assert name.startswith("paper-")
    assert "&" not in name
    assert "!" not in name
    assert name == name.lower()


# ---------------------------------------------------------------------------
# push_file
# ---------------------------------------------------------------------------

def test_push_file_creates_when_not_exists():
    mock_gh_cls, mock_user, mock_repo = _make_mock_github()
    mock_repo.get_contents.side_effect = Exception("404 Not Found")

    with patch("github.Github", mock_gh_cls):
        from src.modules.github.client import GitHubClient

        client = GitHubClient("fake-token", "fake-user")
        client.push_file("my-repo", "main.tex", "\\documentclass{article}", "feat: add draft")

    mock_repo.create_file.assert_called_once()
    args = mock_repo.create_file.call_args
    assert args[1]["path"] == "main.tex" or args[0][0] == "main.tex"


def test_push_file_updates_when_exists():
    mock_gh_cls, mock_user, mock_repo = _make_mock_github()
    existing = MagicMock()
    existing.sha = "sha-abc-123"
    mock_repo.get_contents.return_value = existing

    with patch("github.Github", mock_gh_cls):
        from src.modules.github.client import GitHubClient

        client = GitHubClient("fake-token", "fake-user")
        client.push_file("my-repo", "main.tex", "Updated content", "update: revision")

    mock_repo.update_file.assert_called_once()
    update_args = mock_repo.update_file.call_args[1]
    assert update_args["sha"] == "sha-abc-123"


def test_push_file_accepts_bytes():
    mock_gh_cls, mock_user, mock_repo = _make_mock_github()
    mock_repo.get_contents.side_effect = Exception("404")

    with patch("github.Github", mock_gh_cls):
        from src.modules.github.client import GitHubClient

        client = GitHubClient("fake-token", "fake-user")
        client.push_file("my-repo", "figure.pdf", b"\x25\x50\x44\x46", "feat: add figure")

    mock_repo.create_file.assert_called_once()


# ---------------------------------------------------------------------------
# push_directory
# ---------------------------------------------------------------------------

def test_push_directory_pushes_all_files(tmp_path: Path):
    (tmp_path / "main.tex").write_text("\\documentclass{article}")
    (tmp_path / "refs.bib").write_text("@article{test,title={Test}}")
    (tmp_path / "estimation.py").write_text("import pandas as pd")

    mock_gh_cls, mock_user, mock_repo = _make_mock_github()
    mock_repo.get_contents.side_effect = Exception("404")

    with patch("github.Github", mock_gh_cls):
        from src.modules.github.client import GitHubClient

        client = GitHubClient("fake-token", "fake-user")
        count = client.push_directory("my-repo", tmp_path)

    assert count == 3
    assert mock_repo.create_file.call_count == 3


def test_push_directory_respects_extension_filter(tmp_path: Path):
    (tmp_path / "main.tex").write_text("content")
    (tmp_path / "data.csv").write_text("a,b\n1,2")
    (tmp_path / "ignored.json").write_text("{}")

    mock_gh_cls, mock_user, mock_repo = _make_mock_github()
    mock_repo.get_contents.side_effect = Exception("404")

    with patch("github.Github", mock_gh_cls):
        from src.modules.github.client import GitHubClient

        client = GitHubClient("fake-token", "fake-user")
        count = client.push_directory("my-repo", tmp_path, extensions=[".tex", ".csv"])

    assert count == 2


def test_push_directory_with_remote_prefix(tmp_path: Path):
    (tmp_path / "estimation.py").write_text("# code")

    mock_gh_cls, mock_user, mock_repo = _make_mock_github()
    mock_repo.get_contents.side_effect = Exception("404")

    with patch("github.Github", mock_gh_cls):
        from src.modules.github.client import GitHubClient

        client = GitHubClient("fake-token", "fake-user")
        client.push_directory("my-repo", tmp_path, remote_prefix="replication")

    called_path = mock_repo.create_file.call_args[1].get("path") or mock_repo.create_file.call_args[0][0]
    assert called_path.startswith("replication/")


def test_push_directory_continues_on_individual_file_error(tmp_path: Path):
    """A single file failing to push should not abort the whole directory push."""
    (tmp_path / "file_a.tex").write_text("content a")
    (tmp_path / "file_b.tex").write_text("content b")
    (tmp_path / "file_c.tex").write_text("content c")

    mock_gh_cls, mock_user, mock_repo = _make_mock_github()
    mock_repo.get_contents.side_effect = Exception("404")
    # Second create_file call raises an error
    mock_repo.create_file.side_effect = [None, Exception("API error"), None]

    with patch("github.Github", mock_gh_cls):
        from src.modules.github.client import GitHubClient

        client = GitHubClient("fake-token", "fake-user")
        count = client.push_directory("my-repo", tmp_path)

    # 2 succeeded (3 attempted - 1 failed, but only successful ones counted)
    assert count == 2


# ---------------------------------------------------------------------------
# ensure_replication_scaffold
# ---------------------------------------------------------------------------

def test_ensure_replication_scaffold_creates_gitkeeps():
    mock_gh_cls, mock_user, mock_repo = _make_mock_github()
    mock_repo.get_contents.side_effect = Exception("404")

    with patch("github.Github", mock_gh_cls):
        from src.modules.github.client import GitHubClient

        client = GitHubClient("fake-token", "fake-user")
        client.ensure_replication_scaffold("my-repo")

    paths_pushed = {
        call[1].get("path") or call[0][0]
        for call in mock_repo.create_file.call_args_list
    }
    assert "replication/.gitkeep" in paths_pushed
