"""Dashboard file and folder fixes from the review of 2026-11-21 (finding 16)."""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path, PureWindowsPath
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from src.api import setup as setup_mod
from src.api.app import app


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks")
def test_a_plainly_named_link_to_a_hidden_file_is_not_served(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / ".env").write_text("ALLIUM_API_KEY=secret\n")
    (ws / "notes.txt").symlink_to(ws / ".env")
    (ws / "paper.md").write_text("fine")
    pid = str(uuid.uuid4())
    with patch("src.api.app._workspace_of", return_value=ws):
        c = TestClient(app)
        r = c.get(f"/api/papers/{pid}/artifacts/notes.txt")
        assert r.status_code == 400 and "secret" not in r.text
        assert c.get(f"/api/papers/{pid}/artifacts/paper.md").status_code == 200


def test_the_review_of_a_study_without_a_folder_is_404_not_500():
    async def fetch_one(query, params=None):
        return {"id": params["id"], "workspace": None, "mode": "single_pass", "pipeline": "empirical"}

    with patch("src.db.client.fetch_one", side_effect=fetch_one):
        r = TestClient(app).get(f"/api/papers/{uuid.uuid4()}/review")
    assert r.status_code == 404 and "no folder" in r.json()["detail"]


def test_a_home_on_a_network_share_keeps_the_system_drive_closed(monkeypatch):
    monkeypatch.setattr(setup_mod.Path, "home", classmethod(lambda cls: PureWindowsPath(r"\\server\users\me")))
    monkeypatch.setenv("SystemDrive", "C:")
    assert setup_mod._home_drive() == "C:"
    monkeypatch.setattr(setup_mod.sys, "platform", "win32")
    monkeypatch.setattr(setup_mod, "_windows_drives", lambda: ["C:\\", "D:\\"])
    assert [str(r) for r in setup_mod.drive_roots()] == [str(Path("D:\\"))]


@pytest.fixture
def browse_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".ssh").mkdir(parents=True)
    (home / "Studies").mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(setup_mod, "drive_roots", lambda: [])
    return home


def test_hidden_folders_are_neither_listed_nor_opened(browse_home):
    listing = setup_mod.list_folder(setup_mod.safe_resolve(str(browse_home)), "folder")
    assert [d["name"] for d in listing["dirs"]] == ["Studies"]
    with pytest.raises(HTTPException) as e:
        setup_mod.safe_resolve(str(browse_home / ".ssh"))
    assert e.value.status_code == 403


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks")
def test_a_link_into_a_hidden_folder_is_not_opened(browse_home):
    (browse_home / "keys").symlink_to(browse_home / ".ssh")
    with pytest.raises(HTTPException):
        setup_mod.safe_resolve(str(browse_home / "keys"))


def test_time_machine_and_snapshot_volumes_are_skipped(tmp_path, monkeypatch):
    volumes = tmp_path / "Volumes"
    (volumes / "Data").mkdir(parents=True)
    (volumes / "Backup Disk" / "Backups.backupdb").mkdir(parents=True)
    (volumes / "com.apple.TimeMachine.localsnapshots").mkdir()
    (volumes / ".timemachine").mkdir()
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    monkeypatch.setattr(setup_mod, "drive_roots", lambda: [Path(os.path.realpath(volumes))])
    listing = setup_mod.list_folder(setup_mod.safe_resolve(str(volumes)), "folder")
    assert [d["name"] for d in listing["dirs"]] == ["Data"]
    with pytest.raises(HTTPException):
        setup_mod.safe_resolve(str(volumes / "com.apple.TimeMachine.localsnapshots"))
