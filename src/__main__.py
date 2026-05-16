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

    install_skills = subparsers.add_parser(
        "install-skills",
        help="Copy bundled skill files to ~/.{backend}/skills/ for headless CLI backends.",
    )
    install_skills.add_argument(
        "--backend",
        choices=["claude", "codex", "gemini", "all"],
        default="all",
        help="Which backend's skills directory to populate. Default: all installed CLIs.",
    )
    install_skills.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing skill files. Default: skip files that already exist.",
    )

    args = parser.parse_args()

    if args.command == "install-skills":
        from .cli_install_skills import install_skills as _install

        sys.exit(_install(backend=args.backend, force=args.force))
    elif args.command == "migrate":
        import asyncio
        import importlib.util
        from pathlib import Path

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
