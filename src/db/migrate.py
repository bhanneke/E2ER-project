"""Run SQL migrations in order.

Importable counterpart to the dev-checkout `scripts/migrate.py`. Used by
`e2er migrate` so the command works from a pip-installed wheel (where
`scripts/` is excluded from packaging).

The SQL files live in the top-level `sql/` package which IS shipped in
the wheel (see pyproject.toml `[tool.setuptools.package-data]`).
"""

from __future__ import annotations

import asyncio
from importlib import resources
from pathlib import Path


async def run() -> int:
    """Run every `*.sql` migration in the bundled `sql/` package in name order.

    Returns the count of files that ran without raising; failures are
    printed and counted as 0. The function does not stop on error —
    Postgres migrations are usually idempotent under IF NOT EXISTS, and
    early failures shouldn't block later (independent) migrations.
    """
    from .client import close_pool, execute

    sql_pkg = resources.files("sql")
    migrations = sorted(
        (p for p in sql_pkg.iterdir() if p.is_file() and p.name.endswith(".sql")),
        key=lambda p: p.name,
    )
    if not migrations:
        # Fall back to the source-checkout layout (scripts/migrate.py
        # behaviour) when running from a dev install where `sql/` isn't
        # importable as a package.
        sql_dir = Path(__file__).resolve().parent.parent.parent / "sql"
        migrations = sorted(p for p in sql_dir.glob("*.sql") if p.is_file())

    print(f"Running {len(migrations)} migrations...")
    ok = 0
    for path in migrations:
        name = getattr(path, "name", str(path))
        print(f"  {name}")
        sql = path.read_text(encoding="utf-8")
        try:
            await execute(sql)
            print(f"  ✓ {name}")
            ok += 1
        except Exception as e:
            print(f"  ✗ {name}: {e}")

    await close_pool()
    return ok


def main() -> None:
    """Sync entry point for the `e2er migrate` CLI handler."""
    asyncio.run(run())


if __name__ == "__main__":
    main()
