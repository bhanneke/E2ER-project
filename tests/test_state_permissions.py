"""e2er's folder and the run database are the user's alone (review of 2026-11-21, finding 1c)."""

from __future__ import annotations

import os
import sys

import pytest

from src.home import secure_state

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX modes")


def test_state_folder_700_and_database_600(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    d = tmp_path / ".e2er"
    d.mkdir(mode=0o755)
    os.chmod(d, 0o755)
    for name in ("papers.db", "papers.db-wal"):
        (d / name).write_bytes(b"x")
        os.chmod(d / name, 0o644)
    secure_state()
    assert d.stat().st_mode & 0o777 == 0o700
    assert (d / "papers.db").stat().st_mode & 0o777 == 0o600
    assert (d / "papers.db-wal").stat().st_mode & 0o777 == 0o600


def test_a_database_elsewhere_is_made_private_too(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    db = tmp_path / "db" / "runs.db"
    db.parent.mkdir()
    db.write_bytes(b"x")
    os.chmod(db, 0o644)
    secure_state(db)
    assert db.stat().st_mode & 0o777 == 0o600
    assert (tmp_path / "home" / ".e2er").stat().st_mode & 0o777 == 0o700


def test_the_sqlite_bootstrap_makes_the_database_private(tmp_path, monkeypatch):
    import asyncio

    from src.config import get_settings
    from src.db import client

    monkeypatch.setenv("HOME", str(tmp_path))
    db = tmp_path / "papers.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    get_settings.cache_clear()
    try:
        asyncio.run(client._ensure_sqlite_schema())
    finally:
        get_settings.cache_clear()
    assert db.stat().st_mode & 0o777 == 0o600
