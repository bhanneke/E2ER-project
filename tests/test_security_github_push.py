"""GitHub publish writes nothing outside its clone (the reviewer's repro_symlink.py, 2026-10-23).

A shared repository where a collaborator committed ``code -> /some/dir`` made ``e2er publish --github``
write the study's files into that directory on the publisher's computer.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.core import github_files as gf


@pytest.fixture(autouse=True)
def _local_remotes_only(monkeypatch):
    """The remotes here are local bare repositories; e2er's test guard allows git only when told so."""
    monkeypatch.setenv("E2ER_TEST_GITHUB", "fake")
    for k in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL"):
        monkeypatch.delenv(k, raising=False)


def _git(*args: str, cwd: Path | None = None) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _remote(base: Path, link_target: Path | None, *, link_name: str = "code") -> Path:
    seed = base / "seed"
    seed.mkdir()
    _git("init", "-q", "-b", "main", str(seed))
    (seed / "provenance.json").write_text(json.dumps({"run": {"paper_id": "P1"}}), encoding="utf-8", newline="\n")
    if link_target is not None:
        os.symlink(str(link_target), seed / link_name)
    _git("add", "-A", cwd=seed)
    _git("-c", "user.name=a", "-c", "user.email=a@b", "commit", "-qm", "seed", cwd=seed)
    bare = base / "remote.git"
    _git("clone", "-q", "--bare", str(seed), str(bare))
    return bare


class _Local(gf.Target):
    def __init__(self, bare: Path) -> None:
        super().__init__("owner", "repo", "")
        self._bare = bare

    @property
    def remote(self) -> str:
        return str(self._bare)


def _staged(base: Path) -> gf.Staged:
    stage = base / "staged"
    (stage / "code").mkdir(parents=True)
    (stage / "code" / "run.py").write_text("print('written by e2er push')\n", encoding="utf-8", newline="\n")
    (stage / "provenance.json").write_text(json.dumps({"run": {"paper_id": "P1"}}), encoding="utf-8", newline="\n")
    return gf.Staged(root=stage, files=["code/run.py", "provenance.json"], left_out=[])


@pytest.mark.parametrize("link_name", ["code", "other"])
def test_a_tracked_symlink_in_the_study_folder_stops_the_push(tmp_path, link_name):
    outside = tmp_path / "victim_dir"
    outside.mkdir()
    bare = _remote(tmp_path, outside, link_name=link_name)
    with pytest.raises(gf.GitHubError, match="symbolic links"):
        gf.push(
            _Local(bare),
            _staged(tmp_path),
            study_ids={"P1"},
            message="m",
            user={"login": "x"},
            restricted=set(),
            exists=True,
        )
    assert list(outside.iterdir()) == []


def test_a_clean_repository_still_takes_the_push(tmp_path):
    bare = _remote(tmp_path, None)
    r = gf.push(
        _Local(bare),
        _staged(tmp_path),
        study_ids={"P1"},
        message="m",
        user={"login": "x"},
        restricted=set(),
        exists=True,
    )
    assert r.changed


def test_the_legacy_client_never_uploads_a_link_or_a_hidden_file(tmp_path, monkeypatch):
    from src.modules.github import client as gc

    secret = tmp_path / "id_rsa"
    secret.write_text("PRIVATE KEY", encoding="utf-8", newline="\n")
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "paper.tex").write_text("\\documentclass{article}", encoding="utf-8", newline="\n")
    (ws / "key.tex").symlink_to(secret)
    (ws / ".env").write_text("ANTHROPIC_API_KEY=x", encoding="utf-8", newline="\n")
    c = gc.GitHubClient.__new__(gc.GitHubClient)
    pushed: list[str] = []
    monkeypatch.setattr(c, "push_file", lambda repo, path, content, msg, branch="main": pushed.append(path))
    assert c.push_directory("r", ws) == 1
    assert pushed == ["paper.tex"]


@pytest.mark.parametrize("bad", ["../x.tex", "/etc/x", "a/../../b", ""])
def test_the_legacy_client_refuses_a_path_outside_the_repository(bad):
    from src.modules.github import client as gc

    c = gc.GitHubClient.__new__(gc.GitHubClient)
    c._user = MagicMock()
    with pytest.raises(ValueError):
        c.push_file("r", bad, b"x", "m")
