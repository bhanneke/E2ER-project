"""Lane A — DB-client dispatch: SQLite vs Postgres routing.

Hermetic. Verifies:
  - empty / sqlite URL → backend="sqlite"
  - postgres URL → backend="postgres"
  - %(name)s → :name parameter translation
  - ::jsonb / ::uuid casts stripped on SQLite
  - sqlite path expansion (~/.e2er/papers.db default)
"""

from __future__ import annotations

import pytest

from src.db.client import _resolve_backend, _sqlite_path, _translate_to_sqlite


def test_resolve_backend_sqlite_default():
    assert _resolve_backend("") == "sqlite"
    assert _resolve_backend("sqlite:///path/to.db") == "sqlite"
    assert _resolve_backend("sqlite://relative.db") == "sqlite"


def test_resolve_backend_postgres():
    assert _resolve_backend("postgresql://user@host/db") == "postgres"
    assert _resolve_backend("postgres://user@host/db") == "postgres"


def test_resolve_backend_rejects_unknown_scheme():
    with pytest.raises(ValueError, match="Unsupported DATABASE_URL"):
        _resolve_backend("mysql://user@host/db")


def test_sqlite_path_default():
    """Empty URL → ~/.e2er/papers.db (expanded)."""
    p = _sqlite_path("")
    assert p.endswith("/.e2er/papers.db")
    assert "~" not in p, "tilde should be expanded"


def test_sqlite_path_explicit():
    """Per SQLAlchemy convention:
    sqlite:///rel.db      → relative
    sqlite:////abs/x.db   → absolute (four slashes for an absolute path)
    """
    assert _sqlite_path("sqlite:///relative.db") == "relative.db"
    assert _sqlite_path("sqlite:////abs/path/x.db") == "/abs/path/x.db"


def test_sqlite_path_expands_tilde():
    """Home-relative ~/.e2er/x.db should be expanded."""
    import os

    p = _sqlite_path("sqlite:///~/.e2er/custom.db")
    assert p.startswith(os.path.expanduser("~"))
    assert p.endswith("/.e2er/custom.db")


def test_translate_param_style():
    """%(name)s → :name on SQLite."""
    sql = "SELECT * FROM papers WHERE id = %(id)s AND status = %(s)s"
    out = _translate_to_sqlite(sql)
    assert out == "SELECT * FROM papers WHERE id = :id AND status = :s"


def test_translate_strips_pg_casts():
    """::jsonb, ::uuid, ::timestamptz are stripped for SQLite."""
    sql = "INSERT INTO events (p, payload) VALUES (%(p)s::uuid, %(pl)s::jsonb)"
    out = _translate_to_sqlite(sql)
    assert "::uuid" not in out
    assert "::jsonb" not in out
    assert out == "INSERT INTO events (p, payload) VALUES (:p, :pl)"


def test_translate_preserves_legit_double_colon():
    """A `::` inside a string literal would be a Postgres oddity; our regex
    only matches type keywords after :: so unrelated text is preserved."""
    sql = "SELECT 'a::b' AS x"  # string content, no real cast
    out = _translate_to_sqlite(sql)
    # `::b` isn't in our type list — preserved
    assert out == "SELECT 'a::b' AS x"
