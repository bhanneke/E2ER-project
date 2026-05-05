"""E2ER v3 CLI entry point — `e2er serve` or `e2er migrate`."""
from __future__ import annotations

import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="e2er",
        description="E2ER v3 — End-to-End Researcher pipeline",
    )
    subparsers = parser.add_subparsers(dest="command")

    serve = subparsers.add_parser("serve", help="Start the API server (default command)")
    serve.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    serve.add_argument("--port", type=int, default=8280, help="Port (default: 8280)")
    serve.add_argument("--reload", action="store_true", help="Auto-reload on code changes (dev mode)")

    subparsers.add_parser("migrate", help="Run database migrations (sql/001 through sql/006)")

    args = parser.parse_args()

    if args.command == "migrate":
        import asyncio
        from pathlib import Path
        import importlib.util

        migrate_path = Path(__file__).parent.parent / "scripts" / "migrate.py"
        if not migrate_path.exists():
            print(f"migrate.py not found at {migrate_path}", file=sys.stderr)
            sys.exit(1)
        spec = importlib.util.spec_from_file_location("migrate", migrate_path)
        mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        asyncio.run(mod.main())

    else:
        import uvicorn

        host = getattr(args, "host", "127.0.0.1")
        port = getattr(args, "port", 8280)
        reload = getattr(args, "reload", False)
        uvicorn.run("src.api.app:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    main()
