"""E2ER v3 CLI entry point — `e2er serve` or `e2er migrate`."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


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

    subparsers.add_parser("migrate", help="Run Postgres migrations (sql/001–010); SQLite auto-initializes")

    init_p = subparsers.add_parser(
        "init",
        help="Guided first-paper setup: scaffold data/ + literature/, write .env, bundle skills.",
    )
    init_p.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing .env without prompting.",
    )
    init_p.add_argument(
        "--defaults",
        action="store_true",
        help="Non-interactive setup with sensible defaults (claude_code backend, "
        "scaffold data/ + literature/, write .env). Works in CI / non-TTY.",
    )

    run_p = subparsers.add_parser(
        "run",
        help="Submit a research question to the pipeline (one-command quickstart).",
    )
    run_p.add_argument(
        "research_question", nargs="?", default=None, help="The research question, in quotes (or use --rq-file)."
    )
    run_p.add_argument(
        "--rq-file", default=None, help="Read the RQ from a file — an rq.json (from `e2er rq`) or plain text."
    )
    run_p.add_argument(
        "--methodology",
        choices=["empirical", "theoretical", "mixed"],
        default="empirical",
        help="Which methodology specialists to dispatch. Default: empirical.",
    )
    run_p.add_argument(
        "--mode",
        choices=["single_pass", "iterative"],
        default="single_pass",
        help="single_pass = fast (one design+draft+review pass). iterative = full loop with self-attack + revision.",
    )
    run_p.add_argument(
        "--backend",
        choices=["anthropic", "openrouter", "claude_code", "codex", "gemini"],
        default=None,
        help="Override the LLM backend for this paper (default: LLM_BACKEND from .env). "
        "Lets you run the same RQ on different backends without restarting the server.",
    )
    run_p.add_argument(
        "--model",
        default=None,
        help="Override the model for this paper (default: the backend's configured model).",
    )
    run_p.add_argument(
        "--governance",
        choices=["off", "contracts", "full"],
        default=None,
        help="Governance regime for this paper (default: GOVERNANCE from .env, or 'full'). "
        "full = all gates block; contracts = only specialist contracts block; off = nothing "
        "blocks (gates still run in shadow and log what they would have caught).",
    )
    run_p.add_argument(
        "--review-at",
        action="append",
        default=None,
        metavar="STAGE",
        choices=[
            "initial",
            "iterative",
            "estimation_gate",
            "self_attack",
            "polish",
            "review",
            "revision",
            "replication",
        ],
        help="Pause for human review after this pipeline stage (repeatable). The run pauses; "
        "inspect/edit the workspace, then `e2er resume <paper_id>` to continue.",
    )
    run_p.add_argument(
        "--max-cost",
        type=float,
        default=5.0,
        help="Per-paper USD cost cap (default $5). $0 if on the Claude Code / Codex / Gemini CLI backends.",
    )
    run_p.add_argument(
        "--monitor-seconds",
        type=float,
        default=1800.0,
        help="How long to tail the run before detaching. Default 30 min. ^C is safe — run continues in background.",
    )
    run_p.add_argument(
        "--acknowledge-unproven",
        action="store_true",
        help="Lift the $1 first-run floor for an unproven (model, methodology, mode) tuple "
        "and use the full --max-cost. Auto-enabled on the $0 CLI backends (claude_code/codex/gemini).",
    )

    matrix_p = subparsers.add_parser(
        "run-matrix",
        help="Run the same RQ across several backends (k backends × n repeats) for later comparison.",
    )
    matrix_p.add_argument("research_question", nargs="?", default=None, help="The RQ in quotes (or use --rq-file).")
    matrix_p.add_argument("--rq-file", default=None, help="Read the research question from a file.")
    matrix_p.add_argument(
        "--backends",
        default="claude_code,codex,gemini",
        help="Comma-separated backends to run (default: claude_code,codex,gemini — the $0 CLI backends).",
    )
    matrix_p.add_argument("--repeats", type=int, default=3, help="Repeats per backend (default 3).")
    matrix_p.add_argument("--methodology", choices=["empirical", "theoretical", "mixed"], default="empirical")
    matrix_p.add_argument("--mode", choices=["single_pass", "iterative"], default="single_pass")
    matrix_p.add_argument("--governance", choices=["off", "contracts", "full"], default=None)
    matrix_p.add_argument("--max-cost", type=float, default=5.0, help="Per-paper cost cap (default $5).")
    matrix_p.add_argument(
        "--out", default=None, help="Output dir for bundles + matrix.json (default: ./matrix-<slug>/)."
    )
    matrix_p.add_argument("--monitor-seconds", type=float, default=3600.0, help="Max time to poll each paper.")

    status_p = subparsers.add_parser(
        "status",
        help="Show the current status of a paper (and optionally tail it).",
    )
    status_p.add_argument("paper_id", help="The paper UUID returned by `e2er run`.")
    status_p.add_argument(
        "--tail",
        action="store_true",
        help="Poll status until the paper reaches a terminal state. ^C is safe — paper continues.",
    )
    status_p.add_argument(
        "--monitor-seconds",
        type=float,
        default=1800.0,
        help="With --tail, max time to poll before detaching. Default 30 min.",
    )

    cancel_p = subparsers.add_parser(
        "cancel",
        help="Cancel an in-flight paper. Workspace + completed phases are preserved.",
    )
    cancel_p.add_argument("paper_id", help="The paper UUID returned by `e2er run`.")
    cancel_p.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Skip the confirmation prompt.",
    )

    resume_p = subparsers.add_parser(
        "resume",
        help=(
            "Resume a paused / failed paper. Resume-from-disk skips phases that "
            "already produced their canonical artifact, so completed work isn't repeated."
        ),
    )
    resume_p.add_argument("paper_id", help="The paper UUID returned by `e2er run`.")
    resume_p.add_argument(
        "--max-cost",
        type=float,
        default=None,
        help="Raise the per-paper cost cap atomically with the resume (common after BudgetExceededError).",
    )
    resume_p.add_argument(
        "--tail",
        action="store_true",
        help="Poll the resumed paper until terminal. ^C is safe — paper continues.",
    )
    resume_p.add_argument(
        "--monitor-seconds",
        type=float,
        default=1800.0,
        help="With --tail, max time to poll before detaching. Default 30 min.",
    )

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

    doctor_p = subparsers.add_parser(
        "doctor",
        help="Preflight: backend installed? skills + DB ok? which data/lit providers are live for this setup?",
    )
    doctor_p.add_argument(
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON report instead of the human-readable summary.",
    )

    verify_cites_p = subparsers.add_parser(
        "verify-citations",
        help="Anti-hallucination gate: every \\cite{key} resolves to a real paper (OpenAlex / S2 / Crossref).",
    )
    verify_cites_p.add_argument("draft", help="Path to the LaTeX draft (paper_draft.tex).")
    verify_cites_p.add_argument(
        "--bib",
        default=None,
        help="Path to references.bib (default: <draft_dir>/references.bib).",
    )
    verify_cites_p.add_argument(
        "--strict",
        action="store_true",
        help="Also fail on unverifiable cites (default: only missing-in-bib fails).",
    )
    verify_cites_p.add_argument(
        "--json",
        action="store_true",
        help="Emit the citation_integrity.json report on stdout instead of the human summary.",
    )

    verify_p = subparsers.add_parser(
        "verify",
        help="Offline, keyless check that an exported bundle is internally consistent + untampered "
        "(hashes, numbers, spec, citations).",
    )
    verify_p.add_argument("bundle", help="Path to an exported bundle directory (from `e2er export`).")
    verify_p.add_argument(
        "--online",
        action="store_true",
        help="Also re-verify citations against live registries (OpenAlex / S2 / Crossref). Default is fully offline.",
    )
    verify_p.add_argument(
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON report instead of the human-readable summary.",
    )

    rq_p = subparsers.add_parser(
        "rq",
        help="Sharpen a draft research question against your data + literature (advisory; never starts a run).",
    )
    rq_p.add_argument("--draft", required=True, help="Your draft research question, in quotes.")
    rq_p.add_argument("--no-data", action="store_true", help="Skip the data-catalog context.")
    rq_p.add_argument("--no-literature", action="store_true", help="Skip the local-literature context.")
    rq_p.add_argument("--out", default=None, help="Write the structured rq.json to this path.")

    compare_p = subparsers.add_parser(
        "compare",
        help="Diff the design choices across a run-matrix (estimator/FE/controls/clustering/coefficient).",
    )
    compare_p.add_argument(
        "paths",
        nargs="+",
        help="A matrix.json (from run-matrix), OR 2+ exported bundle directories to compare.",
    )
    compare_p.add_argument(
        "--out", default=None, help="Output dir for comparison.json + report (default: alongside input)."
    )
    compare_p.add_argument(
        "--json",
        action="store_true",
        help="Emit comparison.json on stdout instead of the human-readable report.",
    )

    export_p = subparsers.add_parser(
        "export",
        help="Assemble a clean, structured project folder (paper/code/data/results/design/reviews) from a run.",
    )
    export_p.add_argument("paper_id", help="The paper UUID returned by `e2er run`.")
    export_p.add_argument(
        "--to",
        default=None,
        help="Destination root for the exported folder (default: OUTPUT_DIR / <LOCAL_DATA_DIR>/e2er_papers).",
    )

    args = parser.parse_args()

    if args.command == "export":
        from .cli_export import export as _export

        sys.exit(_export(paper_id=args.paper_id, to=args.to))

    if args.command == "verify":
        from .cli_verify import verify as _verify

        sys.exit(_verify(bundle=args.bundle, online=args.online, json_output=args.json))

    if args.command == "compare":
        from .core.compare import compare as _compare

        sys.exit(_compare(paths=args.paths, out=args.out, json_output=args.json))

    if args.command == "rq":
        from .cli_rq import rq as _rq

        sys.exit(
            _rq(
                draft=args.draft,
                use_data=not args.no_data,
                use_literature=not args.no_literature,
                out=args.out,
            )
        )

    if args.command == "run-matrix":
        from .cli_run_matrix import run_matrix as _run_matrix

        rq = args.research_question
        if args.rq_file:
            rq = Path(args.rq_file).expanduser().read_text(encoding="utf-8").strip()
        if not rq:
            print("run-matrix: provide a research question (positional) or --rq-file", file=sys.stderr)
            sys.exit(2)
        backends = [b.strip() for b in args.backends.split(",") if b.strip()]
        sys.exit(
            _run_matrix(
                rq=rq,
                backends=backends,
                repeats=args.repeats,
                methodology=args.methodology,
                mode=args.mode,
                max_cost=args.max_cost,
                governance=args.governance,
                out=args.out,
                monitor_seconds=args.monitor_seconds,
            )
        )

    if args.command == "doctor":
        from .doctor import main_doctor

        sys.exit(main_doctor(json_output=args.json))

    if args.command == "verify-citations":
        from .core.pipeline.verify_citations import main_verify_citations

        sys.exit(
            main_verify_citations(
                draft=args.draft,
                bib=args.bib,
                json_output=args.json,
                strict=args.strict,
            )
        )

    if args.command == "install-skills":
        from .cli_install_skills import install_skills as _install

        sys.exit(_install(backend=args.backend, force=args.force))
    elif args.command == "run":
        from .cli_run import resolve_rq_input
        from .cli_run import run as _run

        rq_text = resolve_rq_input(args.research_question, args.rq_file)
        if not rq_text:
            print('e2er run: provide a research question (positional) or --rq-file. Example: e2er run "<RQ>"')
            sys.exit(2)
        sys.exit(
            _run(
                rq=rq_text,
                methodology=args.methodology,
                mode=args.mode,
                max_cost=args.max_cost,
                monitor_seconds=args.monitor_seconds,
                acknowledge=args.acknowledge_unproven,
                backend=args.backend,
                model=args.model,
                governance=args.governance,
                review_stages=args.review_at,
            )
        )
    elif args.command == "init":
        from .cli_init import init as _init

        sys.exit(_init(force=args.force, defaults=args.defaults))
    elif args.command == "status":
        from .cli_status import status as _status

        sys.exit(
            _status(
                paper_id=args.paper_id,
                tail=args.tail,
                monitor_seconds=args.monitor_seconds,
            )
        )
    elif args.command == "cancel":
        from .cli_status import cancel as _cancel

        sys.exit(_cancel(paper_id=args.paper_id, yes=args.yes))
    elif args.command == "resume":
        from .cli_status import resume as _resume

        sys.exit(
            _resume(
                paper_id=args.paper_id,
                max_cost=args.max_cost,
                tail=args.tail,
                monitor_seconds=args.monitor_seconds,
            )
        )
    elif args.command == "migrate":
        # Importable module (works in both pip-installed wheel AND dev
        # checkout). The previous implementation pointed at
        # `scripts/migrate.py` which is excluded from the wheel — see
        # pyproject.toml `[tool.setuptools.packages.find]` exclude rules.
        from .db.migrate import main as _migrate_main

        _migrate_main()

    else:
        import uvicorn

        host = getattr(args, "host", "127.0.0.1")
        port = getattr(args, "port", 8280)
        reload = getattr(args, "reload", False)
        uvicorn.run("src.api.app:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    main()
