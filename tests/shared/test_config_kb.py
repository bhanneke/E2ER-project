"""Regression: literature_kb_enabled tracks the *resolved* DB URL.

The KB needs Postgres. The old check only looked at legacy postgres_url/
db_password, so the documented `DATABASE_URL=postgresql://…` path left the
KB silently off. Now it derives from resolved_database_url.
"""

from __future__ import annotations

from src.config import Settings


def test_kb_enabled_with_database_url_postgres():
    s = Settings(_env_file=None, database_url="postgresql://u:p@localhost:5432/e2er")
    assert s.resolved_database_url.startswith("postgres")
    assert s.literature_kb_enabled is True


def test_kb_disabled_on_sqlite_default():
    # No postgres configured → resolved URL is empty (SQLite) → KB off.
    # _env_file=None isolates the test from any local .env.
    s = Settings(_env_file=None, database_url="", postgres_url=None, db_password="changeme")
    assert not s.resolved_database_url.startswith("postgres")
    assert s.literature_kb_enabled is False
