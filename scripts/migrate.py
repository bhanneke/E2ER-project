"""Run SQL migrations in order."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


async def main():
    from src.db.client import execute, get_pool

    sql_dir = Path(__file__).parent.parent / "sql"
    migrations = sorted(sql_dir.glob("*.sql"))

    print(f"Running {len(migrations)} migrations...")
    for path in migrations:
        print(f"  {path.name}")
        sql = path.read_text()
        try:
            await execute(sql)
            print(f"  ✓ {path.name}")
        except Exception as e:
            print(f"  ✗ {path.name}: {e}")

    from src.db.client import close_pool
    await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
