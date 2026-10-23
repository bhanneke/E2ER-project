"""E2ER v3 CLI entry point — `e2er serve` or `e2er migrate`."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

#: Set by e2er in the environment of every AI CLI call (modules/llm/cli_support.run_env).
_INSIDE_AI_STEP = "E2ER_AI_STEP"


def _refuse_inside_a_specialist() -> None:
    """`e2er` itself is not a specialist's tool.

    Seen live on Codex (2026-10-05): while a study was in its review step, a
    reviewer's shell started a second study on the same server with `e2er run`.
    Claude Code's allowlist never lets a specialist reach `e2er`; Codex and
    Gemini have no allowlist (docs/BACKENDS.md). A specialist's tools are
    e2er-data, e2er-lit, e2er-run, e2er-check-tables and e2er-fieldmap, separate commands.
    """
    who = os.environ.get(_INSIDE_AI_STEP)
    if who:
        print(
            f"e2er: this command does not run inside a study's step (the {who} step is running). "
            "A step uses e2er-data, e2er-lit, e2er-run, e2er-check-tables and e2er-fieldmap.",
            file=sys.stderr,
        )
        sys.exit(2)


def main() -> None:
    _refuse_inside_a_specialist()
    # `e2er corpus …` delegates wholesale to its own parser. Done before the
    # main parser sees anything, so `corpus search --limit 5` and
    # `corpus --help` reach cli_corpus intact instead of being claimed here.
    # `library` is the name used everywhere a person sees it — the dashboard
    # page, the nav, the docs. `corpus` is what it was called first and what
    # existing scripts type, so both work and neither is going away.
    if len(sys.argv) > 1 and sys.argv[1] in ("library", "corpus"):
        from .cli_corpus import main as _corpus

        sys.exit(_corpus(sys.argv[2:], prog=f"e2er {sys.argv[1]}"))

    if len(sys.argv) > 1 and sys.argv[1] == "skills":
        from .cli_skills import main as _skills

        sys.exit(_skills(sys.argv[2:]))

    parser = argparse.ArgumentParser(
        prog="e2er",
        description="e2er is the open infrastructure for publishing, verifying, reproducing and reusing "
        "AI-enabled research. Run `e2er` alone to open it in your browser.",
    )
    from . import __version__

    parser.add_argument("--version", action="version", version=f"e2er {__version__}")
    # For bare `e2er` (which serves the dashboard). Own dests, so that the serve
    # subcommand's defaults cannot overwrite them.
    parser.add_argument(
        "--no-browser",
        dest="top_no_browser",
        action="store_true",
        help="Start the dashboard without opening a browser.",
    )
    parser.add_argument(
        "--port",
        dest="top_port",
        type=int,
        default=None,
        help="Port for the dashboard (default: PORT from .env, else 8280).",
    )
    subparsers = parser.add_subparsers(dest="command")

    serve = subparsers.add_parser("serve", help="Start the API server (default command)")
    serve.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    serve.add_argument("--port", type=int, default=None, help="Port (default: PORT from .env, else 8280)")
    serve.add_argument("--reload", action="store_true", help="Auto-reload on code changes (dev mode)")
    serve.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not open a browser (for servers, containers and CI).",
    )

    subparsers.add_parser("migrate", help="Run the Postgres migrations in sql/; SQLite auto-initializes")

    init_p = subparsers.add_parser(
        "init",
        help="Guided first-paper setup: scaffold data/ + literature/, write .env, copy skills for the chosen CLI.",
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
        "scaffold data/ + literature/, write .env, copy e2er's skill files into ~/.claude/skills). "
        "Works in CI / non-TTY.",
    )

    run_p = subparsers.add_parser(
        "run",
        help="Submit a research question to the pipeline (one-command quickstart).",
    )
    run_p.add_argument(
        "research_question", nargs="?", default=None, help="The research question, in quotes (or use --rq/--rq-file)."
    )
    # Explicit --rq. Without it argparse prefix-expands `--rq "…"` to
    # `--rq-file "…"` and tries to OPEN the question as a filename.
    run_p.add_argument(
        "--rq", dest="rq_opt", default=None, help="The research question, in quotes (same as positional)."
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
        "--template",
        "--pipeline",
        dest="template",
        default="empirical",
        help="Template (pipeline file) the run follows, resolved in ./pipelines, ~/.e2er/pipelines, "
        "then the built-in ones (empirical-preregistered, event-study-finance, policy-evaluation, "
        "spatial-analysis, replication, field-map, descriptive-study, time-series-forecasting, systematic-review, "
        "text-analysis). "
        "Default: empirical.",
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
            "preregister",
        ],
        help="Pause for human review after this pipeline stage (repeatable). The run pauses; "
        "then `e2er review <paper_id>` to edit, instruct, send back or approve (or `e2er resume` to continue). "
        "`preregister` turns on a template's optional pre-registration (time-series-forecasting).",
    )
    run_p.add_argument(
        "--data",
        nargs="+",
        default=None,
        metavar="FILE",
        help="The data files this study uses (.csv, .tsv, .jsonl, .parquet, .xlsx), as on New study. "
        "Without --data the study takes every data file of the data folder (LOCAL_DATA_DIR).",
    )
    run_p.add_argument(
        "--papers",
        nargs="+",
        default=None,
        metavar="FILE",
        help="The papers this study reads and cites: PDFs and .bib files (or a folder of them), as on New study. "
        "Without --papers it takes every paper of the literature folder and .bib files.",
    )
    run_p.add_argument(
        "--only-my-papers",
        action="store_true",
        help="No web search for further literature: the study cites only the researcher's papers.",
    )
    run_p.add_argument(
        "--max-cost",
        type=float,
        default=5.0,
        help="Per-paper USD cost cap (default $5). $0 on the Claude Code / Codex CLI backends. The Gemini "
        "backend (not tested) is also recorded as $0, while Google bills its API key.",
    )
    run_p.add_argument(
        "--monitor-seconds",
        type=float,
        default=1800.0,
        help="How long to tail the run before detaching. Default 30 min. ^C is safe — run continues in background.",
    )
    run_p.add_argument(
        "--demonstration",
        action="store_true",
        help="A demonstration or test run: recorded with the study, and its paper, report and dossier say it is "
        "published as is and not a research contribution. `e2er resume` and `e2er rerun` keep it.",
    )
    run_p.add_argument(
        "--acknowledge-unproven",
        action="store_true",
        help="Lift the $1 first-run floor for an unproven (model, methodology, mode) tuple "
        "and use the full --max-cost. Auto-enabled on the CLI backends (claude_code/codex/gemini).",
    )

    matrix_p = subparsers.add_parser(
        "run-matrix",
        help="Run the same RQ across several backends (k backends × n repeats) for later comparison.",
    )
    matrix_p.add_argument(
        "research_question", nargs="?", default=None, help="The RQ in quotes (or use --rq/--rq-file)."
    )
    matrix_p.add_argument("--rq", dest="rq_opt", default=None, help="The RQ in quotes (same as positional).")
    matrix_p.add_argument("--rq-file", default=None, help="Read the research question from a file.")
    matrix_p.add_argument(
        "--backends",
        default=None,
        help="Comma-separated backends to run, e.g. claude_code,codex. Default: every subscription CLI "
        "(Claude Code, Codex) that is installed and signed in on this computer, as `e2er doctor` "
        "finds them; if there is none, every API backend with a key. Gemini (not tested) runs only "
        "when named here.",
    )
    matrix_p.add_argument(
        "--models",
        default=None,
        metavar="BACKEND=MODEL,...",
        help="Model per backend, e.g. claude_code=sonnet,codex=gpt-6-luna. A backend left out runs its "
        "configured model (CLAUDE_CODE_MODEL, CODEX_MODEL, ...).",
    )
    matrix_p.add_argument("--repeats", type=int, default=3, help="Repeats per backend (default 3).")
    matrix_p.add_argument("--methodology", choices=["empirical", "theoretical", "mixed"], default="empirical")
    matrix_p.add_argument(
        "--template",
        "--pipeline",
        dest="template",
        default="empirical",
        help="Template (pipeline file) every run follows, as for `e2er run`. Default: empirical.",
    )
    matrix_p.add_argument(
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
            "preregister",
        ],
        help="Pause every run for human review after this stage (repeatable). A paused run is recorded "
        "as paused and not exported; review it with `e2er review <paper_id>`, then `e2er export` it.",
    )
    matrix_p.add_argument(
        "--demonstration",
        action="store_true",
        help="Mark every run as a demonstration or test run, as `e2er run --demonstration` does.",
    )
    matrix_p.add_argument("--mode", choices=["single_pass", "iterative"], default="single_pass")
    matrix_p.add_argument("--governance", choices=["off", "contracts", "full"], default=None)
    matrix_p.add_argument("--max-cost", type=float, default=5.0, help="Per-paper cost cap (default $5).")
    matrix_p.add_argument(
        "--out", default=None, help="Output dir for bundles + matrix.json (default: ./matrix-<slug>/)."
    )
    matrix_p.add_argument("--monitor-seconds", type=float, default=3600.0, help="Max time to poll each paper.")

    status_p = subparsers.add_parser(
        "status",
        help="Show the status of a run (paper id), or of a study folder published with `e2er publish --to`.",
    )
    status_p.add_argument(
        "paper_id",
        help="The paper UUID returned by `e2er run` (its first characters suffice), or a published study folder.",
    )
    status_p.add_argument(
        "--url", default=None, help="For a study folder: platform address (default: its .e2er/link.json)."
    )
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

    list_p = subparsers.add_parser(
        "list",
        help="List studies: repeated runs of one question are grouped as attempts (v1, v2, …).",
    )
    list_p.add_argument("--attempts", action="store_true", help="Show each study's attempts.")
    list_p.add_argument("--archived", action="store_true", help="Include archived attempts.")
    list_p.add_argument("--search", "-q", default="", help="Only studies whose question or title contains this.")

    archive_p = subparsers.add_parser(
        "archive",
        help="Hide attempts from the lists. Nothing is deleted; running and paused attempts are refused.",
    )
    archive_p.add_argument("paper_id", nargs="?", help="The attempt (paper id, or its first 8 characters).")
    archive_target = archive_p.add_mutually_exclusive_group()
    archive_target.add_argument("--study", metavar="KEY_OR_ID", help="Archive every attempt of this study.")
    archive_target.add_argument(
        "--failed", action="store_true", help="Archive all failed and cancelled attempts (a dry run without --yes)."
    )
    archive_p.add_argument("--yes", "-y", action="store_true", help="With --failed: archive, not just show.")

    unarchive_p = subparsers.add_parser("unarchive", help="Bring archived attempts back into the lists.")
    unarchive_p.add_argument("paper_id", nargs="?", help="The attempt (paper id, or its first 8 characters).")
    unarchive_p.add_argument("--study", metavar="KEY_OR_ID", help="Unarchive every attempt of this study.")

    cancel_p = subparsers.add_parser(
        "cancel",
        help="Cancel a running or paused paper. Workspace + completed phases are preserved.",
    )
    cancel_p.add_argument("paper_id", help="The paper UUID returned by `e2er run` (its first characters suffice).")
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
    resume_p.add_argument("paper_id", help="The paper UUID returned by `e2er run` (its first characters suffice).")
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

    review_p = subparsers.add_parser(
        "review",
        help="Act at a researcher step: approve, edit a file, give an instruction, or send a step back.",
    )
    review_p.add_argument("paper_id", help="The paper UUID returned by `e2er run` (its first characters suffice).")
    review_p.add_argument(
        "--approve",
        action="store_true",
        help="Approve the step and continue the run (after the --edit or --instruction given with it).",
    )
    review_p.add_argument("--instruction", default=None, help="An instruction every following step receives.")
    review_p.add_argument("--edit", default=None, metavar="FILE", help="Edit one of the step's files in $EDITOR.")
    review_p.add_argument("--send-back", default=None, metavar="STEP", help="Send a template step or specialist back.")
    review_p.add_argument("--remark", default=None, help="What should change (with --send-back).")

    rerun_p = subparsers.add_parser(
        "rerun",
        help="Send a study (finished, failed or stopped) back to one of its steps: it and every later step run "
        "again with your remark.",
    )
    rerun_p.add_argument("paper_id", help="The paper UUID (its first characters suffice).")
    rerun_p.add_argument(
        "--from",
        dest="from_step",
        required=True,
        metavar="STEP",
        help="The template step to rerun, or a specialist (its step reruns).",
    )
    rerun_p.add_argument("--remark", required=True, help="What should change; recorded for the dossier.")

    prereg_p = subparsers.add_parser("preregister", help="Pre-registration commands (`e2er preregister deposit`).")
    prereg_sub = prereg_p.add_subparsers(dest="prereg_command")
    dep_p = prereg_sub.add_parser("deposit", help="Deposit the frozen pre-registration with your own account (DOI).")
    dep_p.add_argument("target", help="Paper UUID, or an exported study folder.")
    dep_p.add_argument(
        "--zenodo", action="store_true", help="Deposit on Zenodo (token from `e2er zenodo login`, or ZENODO_TOKEN)."
    )
    dep_p.add_argument("--osf", action="store_true", help="OSF Registries (not built yet; says what to do instead).")
    dep_p.add_argument(
        "--sandbox",
        action="store_true",
        help="Use Zenodo's sandbox (`e2er zenodo login --sandbox`, or ZENODO_SANDBOX_TOKEN).",
    )

    # Superseded by `e2er skills sync`. Kept working because it is in the
    # README, in shell history, and in whatever people have scripted — renaming
    # a command is not a reason to break it.
    install_skills = subparsers.add_parser(
        "install-skills",
        help="Deprecated alias for `e2er skills sync`.",
        # In the description too, not only in the runtime note: `--help` exits
        # during parsing, so anyone reading the help would never see the note.
        description="Deprecated: this is now `e2er skills sync`. The old name still works. "
        "Copies e2er's own skill files to ~/.{backend}/skills/ so a headless "
        "claude/codex/gemini process can see them.",
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
    verify_p.add_argument(
        "bundle",
        help="An exported study folder (from `e2er export`) or a .e2er package (from `e2er pack`); a package is "
        "unpacked into a temporary folder and every file is checked against its list first.",
    )
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
    verify_p.add_argument(
        "--against",
        default=None,
        metavar="URL",
        help="Compare the folder with what e2er.org published: a study address (https://e2er.org/<owner>/<project>), "
        "an anonymous version's address (https://e2er.org/r/<code>) or a dossier address (https://e2er.org/d/<id>). "
        "Read with GET only. Without it, the folder is verified "
        "against itself only.",
    )
    verify_p.add_argument(
        "--against-file",
        default=None,
        metavar="FILE",
        help="Like --against, from a saved copy of the study record, the dossier or e2er.json.",
    )

    reproduce_p = subparsers.add_parser(
        "reproduce",
        help="Run a study's code again in a new environment and compare the results with the published ones.",
        description="Runs the steps in the folder's reproduce.json in a run folder of its own, inside a new "
        "virtual environment with the study's pinned requirements, then compares every result value with the "
        "published one and renders the paper's tables again. The study folder is not changed. Exit code 0: "
        "reproduced; 1: values or tables differ; 2: the code could not be run.",
    )
    reproduce_p.add_argument(
        "folder",
        help="The study folder (with reproduce.json), or a .e2er package: it is unpacked, every file is checked "
        "against its list, and the packages are installed from its pinned list (from its wheels, when they are "
        "for this computer).",
    )
    reproduce_p.add_argument(
        "--keep",
        action="store_true",
        help="Keep the run folder (and an unpacked package) and say where; without it both are removed when the "
        "command ends, also after a failure.",
    )
    reproduce_p.add_argument(
        "--allow-network",
        action="store_true",
        help="Let the study's code reach the web also outside the step that loads its inputs again "
        "(the report names what it reached).",
    )
    reproduce_p.add_argument(
        "--json", dest="json_out", default=None, metavar="FILE", help="Also write the report as JSON."
    )

    # `question` says what it does; `rq` is the abbreviation researchers type.
    rq_p = subparsers.add_parser(
        "question",
        aliases=["rq"],
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

    redact_p = subparsers.add_parser(
        "redact",
        help="Remove personal data (an e-mail address, a phone number) from a study folder before publishing.",
        description="Replaces every occurrence of the text in the folder's text files, changes nothing else, and "
        'records an amendment per file in provenance.json (kind "redacted", the fingerprints before and after). '
        "The next `e2er publish` shows the redactions in the dossier; `e2er verify` accepts a redacted "
        "pre-registration as redacted, not changed. A PDF, a database or another binary file that holds the text "
        "stops the redaction: nothing is changed.",
    )
    redact_p.add_argument("folder", help="The exported study folder.")
    redact_p.add_argument(
        "--text", action="append", required=True, dest="texts", help="The text to remove (repeatable)."
    )
    redact_p.add_argument(
        "--replace", default="<redacted>", dest="replacement", help='What takes its place (default "<redacted>").'
    )
    redact_p.add_argument("--dry-run", action="store_true", help="Say what would change; change nothing.")
    redact_p.add_argument(
        "--check",
        action="store_true",
        help="Change nothing: with the removed text, rebuild each redacted file's earlier version and compare "
        "its fingerprint with the one provenance.json recorded.",
    )

    abstract_p = subparsers.add_parser(
        "abstract",
        help="Write a finished study's abstract again with e2er's abstract step (one AI call, one resend at most).",
        description="Runs the abstract writer on the study's final paper with the configured backend, then the "
        "abstract check (at most 160 words, no test statistics, at most three numbers and each a value of the "
        "results, a finding, no negation at the end). On a pass it puts the abstract into paper/paper.tex, "
        "writes paper/abstract.tex, recompiles paper/paper.pdf (tectonic) and shows it in report.html, and "
        'records an amendment per file in provenance.json (kind "abstract_rewritten"); the next `e2er publish` '
        "shows them in the dossier. Nothing changes when the check fails or the folder does not verify.",
    )
    abstract_p.add_argument("folder", help="The exported study folder.")
    abstract_p.add_argument("--backend", default=None, help="The AI backend (default: the configured one).")
    abstract_p.add_argument("--model", default=None, help="The model (default: the backend's configured model).")
    abstract_p.add_argument(
        "--from-file",
        default=None,
        dest="from_file",
        metavar="FILE",
        help="Your own abstract (a LaTeX abstract environment, or its text) instead of the writer's: no AI call; "
        'the same check and number check; recorded as kind "abstract_edited_by_researcher". Needs --reason.',
    )
    abstract_p.add_argument("--reason", default=None, help="Why you changed the abstract (with --from-file).")

    publish_p = subparsers.add_parser(
        "publish",
        help="Verify an exported bundle; write its research-object manifest (e2er.json) and registry entry.",
    )
    publish_p.add_argument("bundle", help="Path to an exported bundle directory (from `e2er export`).")
    publish_p.add_argument(
        "--owner", default=None, help="Your handle on e2er.org (your GitHub login, lower case). Not with --blind."
    )
    publish_p.add_argument(
        "--project", default=None, help="Project name within your namespace, e.g. etf-comovement. Not with --blind."
    )
    publish_p.add_argument(
        "--github",
        nargs="?",
        const=True,
        default=None,
        metavar="OWNER/REPO",
        help="Put the study's files (what `e2er pack` ships: no data a source's terms keep out) in a public GitHub "
        "repository with your own gh login, and link them at the pushed commit. Alone: <your login>/<project>, "
        "created when missing; with OWNER/REPO: that repository. The files go up only as part of a publish on a "
        "platform: without --to, the one .e2er/link.json records, else e2er.org (signed in with `e2er login`). "
        "A value without / is read as --github-login (its earlier meaning).",
    )
    publish_p.add_argument(
        "--github-path",
        default=None,
        metavar="FOLDER",
        help="With --github: the study's folder in the repository, so several studies can share one repository.",
    )
    publish_p.add_argument("--github-login", default=None, help="Your GitHub login (author identity).")
    publish_p.add_argument("--orcid", default=None, help="Your ORCID iD, e.g. 0000-0002-1825-0097.")
    publish_p.add_argument("--name", default=None, help="Your name as it should appear in citations.")
    publish_p.add_argument("--role", action="append", default=None, dest="roles", help="CRediT role (repeatable).")
    publish_p.add_argument(
        "--coauthor",
        action="append",
        default=None,
        dest="coauthors",
        metavar='"NAME|github=LOGIN|orcid=ID|role=ROLE"',
        help="A co-author (repeatable): the name, then github= and/or orcid=, and role= (CRediT, repeatable). "
        "e2er.org asks each co-author to confirm the credit.",
    )
    publish_p.add_argument("--repo", default=None, help="URL of the repository that holds the bundle.")
    publish_p.add_argument(
        "--commit", default=None, help="Commit that pins the bundle (needed for registry verification)."
    )
    publish_p.add_argument("--path", default=None, help="Path of the bundle inside the repository.")
    publish_p.add_argument(
        "--db",
        default=None,
        help="The study's run database (default: the one the study folder's settings name, as the server finds "
        "it). It must hold the run of the paper the folder was exported from.",
    )
    publish_p.add_argument(
        "--no-db",
        action="store_true",
        help="Publish without the run's database: the dossier then lists no steps, no commit and no researcher "
        "actions, and says so. Only for a folder whose database is gone. (Without --no-db, a folder published "
        "before whose database is gone carries over the dossier of the version it published.)",
    )
    publish_p.add_argument(
        "--template",
        default=None,
        help="Template the run followed. Default: the one the export records (provenance.json), else empirical. "
        "A template other than the recorded one is refused.",
    )
    publish_p.add_argument(
        "--license", default=None, dest="license_id", help="Licence of the research object, e.g. CC-BY-4.0."
    )
    publish_p.add_argument(
        "--derived-from",
        action="append",
        default=None,
        dest="derived_from",
        help="owner/project of a research object this one builds on (repeatable).",
    )
    publish_p.add_argument(
        "--no-stamp",
        action="store_true",
        help="Do not write the e2er author line and dossier footnote into paper/paper.tex.",
    )
    publish_p.add_argument(
        "--demonstration",
        action="store_true",
        help="Mark the study as a demonstration or test run, published as is: e2er.json and the dossier record it, "
        "and the paper and the reproduction report carry a disclaimer (default: the choice made at `e2er run "
        "--demonstration`, else E2ER_PURPOSE from the environment or .env).",
    )
    publish_p.add_argument(
        "--out", default=None, help="Where to write the registry entry (default: ./e2er-registry-entry)."
    )
    publish_p.add_argument(
        "--to",
        default=None,
        dest="to_url",
        metavar="URL",
        help="Publish on this platform, e.g. https://e2er.org (after `e2er login`). Sends the description, "
        "the dossier and file fingerprints; the files stay here.",
    )
    publish_p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the exact request --to would send; change nothing and send nothing.",
    )
    publish_p.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Publish without the question \"Publish '<title>' to <platform> as <handle>? [y/N]\". Needed when "
        "standard input is not a terminal (scripts, CI); without it such a run sends nothing.",
    )
    publish_p.add_argument(
        "--data",
        choices=["public", "private"],
        default=None,
        help="Whether the study's data are public (default: private; asked when run in a terminal).",
    )
    publish_p.add_argument(
        "--code",
        choices=["public", "private"],
        default=None,
        help="Whether the study's code is public (default: private; asked when run in a terminal).",
    )
    publish_p.add_argument("--data-url", default=None, help="Where the public data live (repository or DOI).")
    publish_p.add_argument(
        "--code-url", default=None, help="Where the public code lives (default: the repository at --commit)."
    )
    publish_p.add_argument(
        "--paper",
        choices=["public", "private"],
        default=None,
        help="Whether the paper (PDF) is public: e2er.org then links it (default: private; readers on e2er.org see "
        "a button to ask you for it).",
    )
    publish_p.add_argument(
        "--paper-url",
        default=None,
        help="https address of the public paper PDF (default with --repo and --commit: paper/paper.pdf in the "
        "repository at that commit).",
    )
    publish_p.add_argument(
        "--zenodo",
        action="store_true",
        help="Deposit the public data and code on Zenodo with your own token (`e2er zenodo login`, or "
        "ZENODO_TOKEN) and record the DOIs.",
    )
    publish_p.add_argument(
        "--zenodo-sandbox",
        action="store_true",
        help="Use sandbox.zenodo.org (`e2er zenodo login --sandbox`, or ZENODO_SANDBOX_TOKEN).",
    )
    publish_p.add_argument(
        "--accept-data-terms",
        action="append",
        default=None,
        dest="accept_data_terms",
        metavar="CONNECTOR",
        help="Confirm the terms of a data source the study used, so its data can be published with the study "
        "(--data public), e.g. --accept-data-terms gmd for the Global Macro Database, --accept-data-terms yfinance "
        "for Yahoo Finance (its terms allow personal use only). In a terminal you are asked.",
    )
    publish_p.add_argument(
        "--offline",
        action="store_true",
        help="Prepare the folder for publishing in the browser (e2er.org/publish): write the dossier and "
        "e2er.json, send nothing.",
    )
    publish_p.add_argument(
        "--blind",
        action="store_true",
        help="Publish an anonymous version for double-blind review at an address nobody can guess "
        "(e2er.org/r/<code>): a copy of the folder is anonymised and checked for anything that names you before "
        "anything is sent; e2er.org shows no author and lists it nowhere. Needs no --owner or --project. GitHub, "
        "Zenodo and public addresses are refused. `e2er pack --blind` then makes the file for the journal.",
    )
    publish_p.add_argument(
        "--blind-identifier",
        action="append",
        default=None,
        dest="blind_identifiers",
        metavar="TEXT",
        help="With --blind: one more thing that identifies you (a co-author, your institute, a project name), "
        "taken out and checked like your name (repeatable; also E2ER_BLIND_IDENTIFIERS, separated by ;).",
    )
    publish_p.add_argument(
        "--blind-ack-self-citations",
        action="store_true",
        help="With --blind: you read the places listed that may cite your own work, and they may stay.",
    )
    publish_p.add_argument(
        "--unblind",
        default=None,
        metavar="CODE",
        help="After the review: publish a version with authors of the anonymous version CODE (or its address "
        "…/r/CODE) as --owner/--project. The bundle is the anonymised copy (same files, your name shown) or a "
        "named export of the study (its files become the new version). The anonymous version stays as it is.",
    )

    url_help = "Platform address (default: E2ER_URL, else https://e2er.org)."
    login_p = subparsers.add_parser(
        "login", help="Sign in to e2er.org from the command line (approve a code in the browser)."
    )
    login_p.add_argument("--url", default=None, help=url_help)
    login_p.add_argument("--no-browser", action="store_true", help="Do not open the browser; print the address only.")
    login_p.add_argument(
        "--scope",
        default=None,
        metavar="study:OWNER/SLUG",
        help="Create a token for automation (CI) that can only publish new versions of this one study: it cannot "
        "create studies or handles and cannot withdraw. The token is printed once (pipe it into your CI secret, "
        "e.g. `| gh secret set E2ER_TOKEN`) and not kept; your personal login stays as it is.",
    )
    token_p = subparsers.add_parser("token", help="Tokens for automation (`e2er token create --study OWNER/SLUG`).")
    token_sub = token_p.add_subparsers(dest="token_command", required=True)
    token_create = token_sub.add_parser(
        "create",
        help="With your personal login, create a token that can only publish new versions of one study (for CI).",
    )
    token_create.add_argument("--study", required=True, metavar="OWNER/SLUG", help="The published study, e.g. ada/fx.")
    token_create.add_argument("--name", default=None, help="A name for the token (shown on your account page).")
    token_create.add_argument("--url", default=None, help=url_help)
    logout_p = subparsers.add_parser("logout", help="End the command-line sign-in and forget the token.")
    logout_p.add_argument("--url", default=None, help=url_help)
    whoami_p = subparsers.add_parser("whoami", help="Show the account the command line is signed in as.")
    whoami_p.add_argument("--url", default=None, help=url_help)
    zenodo_p = subparsers.add_parser(
        "zenodo", help="Your own Zenodo token for deposits (`e2er zenodo login`, `status`, `logout`)."
    )
    zenodo_sub = zenodo_p.add_subparsers(dest="zenodo_command", required=True)
    sandbox_help = "sandbox.zenodo.org, Zenodo's test site (a separate account with its own tokens)."
    zl = zenodo_sub.add_parser(
        "login", help="Open Zenodo's new-token page, paste the token (not shown); it is checked and kept."
    )
    zl.add_argument("--sandbox", action="store_true", help=sandbox_help)
    zl.add_argument("--no-browser", action="store_true", help="Do not open the browser; print the address only.")
    zs = zenodo_sub.add_parser("status", help="Whether a Zenodo token is stored and works (it is not shown).")
    zs.add_argument("--sandbox", action="store_true", help=sandbox_help)
    zo = zenodo_sub.add_parser("logout", help="Remove the stored Zenodo token from this computer.")
    zo.add_argument("--sandbox", action="store_true", help=sandbox_help)
    dossier_p = subparsers.add_parser("dossier", help="Dossier commands (`e2er dossier push`).")
    dossier_sub = dossier_p.add_subparsers(dest="dossier_command", required=True)
    push_p = dossier_sub.add_parser("push", help="Register the dossier alone, so a private study's footnote resolves.")
    push_p.add_argument("bundle", nargs="?", default=".", help="The study folder with e2er.json (default: here).")
    push_p.add_argument("--url", default=None, help=url_help)

    submit_p = subparsers.add_parser(
        "submit",
        help="Send a skill, template, specialist or connector to e2er.org for review (after `e2er login`).",
    )
    submit_p.add_argument(
        "path", nargs="?", default=None, help="A skill folder (with SKILL.md), a template .toml or a specialist file."
    )
    submit_p.add_argument("--kind", choices=["skill", "template", "agent", "connector"], default=None)
    submit_p.add_argument("--name", default=None, help="Display name (a skill's comes from SKILL.md).")
    submit_p.add_argument(
        "--slug", default=None, help="Identifier, e.g. codebook-development (default: from the file)."
    )
    submit_p.add_argument("--version", required=True, help="Version of this part, e.g. 0.1.0.")
    submit_p.add_argument("--summary", default=None, help="What it does and for whom (a skill's comes from SKILL.md).")
    submit_p.add_argument("--licence", required=True, help="SPDX identifier, e.g. MIT, CC-BY-4.0, CC-BY-NC-4.0.")
    submit_p.add_argument(
        "--source",
        default=None,
        help="https address where the part is published (required under a non-commercial licence).",
    )
    submit_p.add_argument(
        "--improves", default=None, help="A listed part this is a new version of, e.g. skill:ines/codebook-development."
    )
    submit_p.add_argument(
        "--handle",
        default=None,
        help="The handle to contribute as: one of your account's handles (add them in account settings on e2er.org).",
    )
    submit_p.add_argument("--discipline", default=None, help="Field, e.g. organization-science.")
    submit_p.add_argument("--role", default=None, help="Specialist: its role, in a sentence.")
    submit_p.add_argument("--output", default=None, help="Specialist: the file it writes, e.g. codebook.md.")
    submit_p.add_argument("--direction", choices=["in", "out", "both"], default=None, help="Connector: data direction.")
    submit_p.add_argument(
        "--egress",
        choices=["none", "query", "reference-list", "prompts", "files", "paper-text"],
        default=None,
        help="Connector: what leaves the machine.",
    )
    submit_p.add_argument("--egress-note", default=None, help="Connector: a sentence on what it sends out.")
    submit_p.add_argument("--resubmit", default=None, metavar="SUB_ID", help="Send a returned submission again, fixed.")
    submit_p.add_argument("--url", default=None, help=url_help)
    submit_p.add_argument("--dry-run", action="store_true", help="Print the request; send nothing.")

    export_p = subparsers.add_parser(
        "export",
        help="Assemble a clean, structured project folder (paper/code/data/results/design/reviews) from a run.",
    )
    export_p.add_argument(
        "paper_id", help="The paper id returned by `e2er run`, or its first characters (at least 4) when unique."
    )
    export_p.add_argument(
        "--to",
        default=None,
        help="Destination root for the exported folder (default: OUTPUT_DIR, else exports/ in the studies folder).",
    )
    export_p.add_argument(
        "--package",
        action="store_true",
        help="Also write the study as one .e2er file next to the folder (as `e2er pack` does).",
    )

    pack_p = subparsers.add_parser(
        "pack",
        help="Write a study into one .e2er file: paper, code, data, results and the pinned environment.",
        description="Writes an exported study folder (or a study, exported first) into one .e2er file: a zip "
        "with e2er-package.json at its root, which lists every file with its SHA-256. The packages the code needs "
        "are pinned with their hashes. Data whose source's terms do not allow passing them on are left out; "
        "`e2er reproduce` on the package loads them again. The same folder always gives the same file and "
        "fingerprint.",
    )
    pack_p.add_argument("target", help="An exported study folder, or a study id (the study is exported first).")
    pack_p.add_argument(
        "-o", "--out", default=None, metavar="PATH", help="Where to write the file (default: next to the folder)."
    )
    pack_p.add_argument(
        "--offline",
        action="store_true",
        help="Also put in the wheels of every package for this computer, so a rerun here needs no internet "
        "(adds tens to hundreds of MB).",
    )
    pack_p.add_argument(
        "--no-data", action="store_true", help="Leave every data file out; `e2er reproduce` loads them again."
    )
    pack_p.add_argument(
        "--blind",
        action="store_true",
        help="Pack the anonymised copy `e2er publish --blind` made (the folder itself or its copy next to it): the "
        "file for the journal names no author and is checked for anything that names you.",
    )

    unpack_p = subparsers.add_parser(
        "unpack",
        help="Unpack a .e2er file into a folder, checking every file against its list (nothing is run).",
        description="Unpacks a .e2er file into a new folder. Every name is checked (no absolute path, no `..`, no "
        "link), sizes are capped, and every file is checked against the package's list (SHA-256) as it is written; "
        "a file that does not match stops the unpacking and names the file. Nothing is run.",
    )
    unpack_p.add_argument("package", help="The .e2er file.")
    unpack_p.add_argument("dest", nargs="?", default=None, help="A new folder (default: the file's name, here).")

    inspect_p = subparsers.add_parser(
        "inspect",
        help="Show what a .e2er file holds: title, authors, data, size and fingerprint.",
        description="Prints what a .e2er file holds, from its list of files: title, authors, the e2er version, "
        "which data are included and which are left out (and how a rerun loads them again), the Python version and "
        "pinned packages, the size and the fingerprint. Nothing is unpacked; `e2er verify` checks every file.",
    )
    inspect_p.add_argument("package", help="The .e2er file.")

    # Declared so it appears in `e2er --help`; never parsed here. `corpus` owns
    # a subcommand tree of its own and is intercepted before parse_args below —
    # nargs=REMAINDER cannot hold a leading `--help` or `--limit`, which argparse
    # claims for the top-level parser first.
    subparsers.add_parser(
        "skills",
        help="Install skill packs, or sync e2er's own out to a CLI backend (`e2er skills --help`)",
        add_help=False,
    )
    subparsers.add_parser(
        "library",
        aliases=["corpus"],
        help="A local library of paper claims, each checked against its source (`e2er library --help`)",
        add_help=False,
    )

    args = parser.parse_args()
    if getattr(args, "json", None) is True:
        # The command prints its report as JSON on stdout: log lines go to stderr.
        from .logging_config import logs_to_stderr

        logs_to_stderr()
    _clean_path_args(args)

    if args.command == "abstract":
        from .cli_abstract import abstract as _abstract

        sys.exit(
            _abstract(args.folder, backend=args.backend, model=args.model, from_file=args.from_file, reason=args.reason)
        )

    if args.command == "redact":
        from .cli_redact import redact as _redact

        sys.exit(_redact(args.folder, args.texts, replacement=args.replacement, dry_run=args.dry_run, check=args.check))

    if args.command == "publish":
        from .cli_publish import publish as _publish

        if not args.blind and not (args.owner and args.project):
            publish_p.error("--owner and --project are required (an anonymous version with --blind needs neither)")

        sys.exit(
            _publish(
                args.bundle,
                owner=args.owner,
                project=args.project,
                github=_github_login(args),
                github_repo=_github_repo(args),
                github_path=args.github_path,
                orcid=args.orcid,
                name=args.name,
                roles=args.roles,
                coauthors=args.coauthors,
                repo=args.repo,
                commit=args.commit,
                path=args.path,
                db=args.db,
                no_db=args.no_db,
                template=args.template,
                license_id=args.license_id,
                derived_from=args.derived_from,
                out=args.out,
                stamp=not args.no_stamp,
                dry_run=args.dry_run,
                to_url=args.to_url,
                offline=args.offline,
                data=args.data,
                code=args.code,
                data_url=args.data_url,
                code_url=args.code_url,
                zenodo=args.zenodo or args.zenodo_sandbox,
                zenodo_sandbox=args.zenodo_sandbox,
                site=args.to_url,
                demonstration=args.demonstration,
                accept_data_terms=args.accept_data_terms,
                paper=args.paper,
                paper_url=args.paper_url,
                yes=args.yes,
                blind=args.blind,
                blind_identifiers=args.blind_identifiers,
                blind_ack_self_citations=args.blind_ack_self_citations,
                unblind=args.unblind,
            )
        )

    if args.command == "zenodo":
        from . import cli_zenodo

        if args.zenodo_command == "login":
            sys.exit(cli_zenodo.login(sandbox=args.sandbox, open_browser=not args.no_browser))
        if args.zenodo_command == "logout":
            sys.exit(cli_zenodo.logout(sandbox=args.sandbox))
        sys.exit(cli_zenodo.status(sandbox=args.sandbox))

    if args.command in ("login", "logout", "whoami", "dossier", "token"):
        from . import cli_platform

        if args.command == "login":
            sys.exit(cli_platform.login(args.url, open_browser=not args.no_browser, scope=args.scope))
        if args.command == "token":
            sys.exit(cli_platform.token_create(args.study, url=args.url, name=args.name))
        if args.command == "logout":
            sys.exit(cli_platform.logout(args.url))
        if args.command == "whoami":
            sys.exit(cli_platform.whoami(args.url))
        sys.exit(cli_platform.dossier_push(args.bundle, args.url))

    if args.command == "submit":
        from .cli_submit import submit as _submit

        sys.exit(
            _submit(
                args.path,
                url=args.url,
                resubmit=args.resubmit,
                dry_run=args.dry_run,
                kind=args.kind,
                name=args.name,
                slug=args.slug,
                version=args.version,
                summary=args.summary,
                licence=args.licence,
                source=args.source,
                improves=args.improves,
                handle=args.handle,
                discipline=args.discipline,
                role=args.role,
                output=args.output,
                direction=args.direction,
                egress=args.egress,
                egress_note=args.egress_note,
            )
        )

    if args.command == "export":
        from .cli_export import export as _export

        sys.exit(_export(paper_id=args.paper_id, to=args.to, package=args.package))

    if args.command == "pack":
        from .cli_package import pack as _pack

        if args.blind:
            from .cli_blind import pack_blind

            sys.exit(pack_blind(args.target, args.out, offline=args.offline, no_data=args.no_data))
        sys.exit(_pack(args.target, args.out, offline=args.offline, no_data=args.no_data))

    if args.command == "unpack":
        from .cli_package import unpack as _unpack

        sys.exit(_unpack(args.package, args.dest))

    if args.command == "inspect":
        from .cli_package import inspect as _inspect

        sys.exit(_inspect(args.package))

    if args.command == "reproduce":
        from .cli_reproduce import reproduce as _reproduce

        sys.exit(_reproduce(args.folder, keep=args.keep, json_out=args.json_out, allow_network=args.allow_network))

    if args.command == "verify":
        from .cli_verify import verify as _verify

        sys.exit(
            _verify(
                bundle=args.bundle,
                online=args.online,
                json_output=args.json,
                against=args.against,
                against_file=args.against_file,
            )
        )

    if args.command == "compare":
        from .core.compare import compare as _compare

        sys.exit(_compare(paths=args.paths, out=args.out, json_output=args.json))

    if args.command in ("question", "rq"):
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
        from .cli_run import RQInputError, resolve_rq_input
        from .cli_run_matrix import run_matrix as _run_matrix

        try:
            rq = resolve_rq_input(args.research_question or args.rq_opt, args.rq_file)
        except RQInputError as e:
            print(f"run-matrix: {e}", file=sys.stderr)
            sys.exit(2)
        if not rq:
            print("run-matrix: provide a research question (positional or --rq) or --rq-file", file=sys.stderr)
            sys.exit(2)
        from .cli_run_matrix import MatrixArgError, available_backends, parse_models

        if args.backends:
            backends = [b.strip() for b in args.backends.split(",") if b.strip()]
        else:
            backends = available_backends()
            print(
                f"run-matrix: no --backends given; using {', '.join(backends) or 'none'} "
                "(the ones ready on this computer)",
                file=sys.stderr,
            )
        try:
            models = parse_models(args.models, backends)
        except MatrixArgError as e:
            print(f"run-matrix: {e}", file=sys.stderr)
            sys.exit(2)
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
                template=args.template,
                review_stages=args.review_at,
                demonstration=args.demonstration,
                models=models,
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

    if args.command in {"status", "cancel", "resume", "review", "rerun"} and not (
        args.command == "status" and Path(args.paper_id).expanduser().is_dir()
    ):
        # The first characters of the id suffice, as for `export` and `archive`.
        from .cli_export import ExportLookupError, expand_paper_id

        try:
            args.paper_id = expand_paper_id(args.paper_id)
        except ExportLookupError as e:
            print(f"e2er {args.command}: {e}", file=sys.stderr)
            sys.exit(1)

    if args.command == "install-skills":
        from .cli_install_skills import install_skills as _install

        print(
            "note: `e2er install-skills` is now `e2er skills sync`. The old name still works.",
            file=sys.stderr,
        )
        sys.exit(_install(backend=args.backend, force=args.force))
    elif args.command == "run":
        from .cli_run import RQInputError, resolve_rq_input
        from .cli_run import run as _run

        try:
            rq_text = resolve_rq_input(args.research_question or args.rq_opt, args.rq_file)
        except RQInputError as e:
            print(f"e2er run: {e}", file=sys.stderr)
            sys.exit(2)
        if not rq_text:
            print('e2er run: provide a research question (positional or --rq) or --rq-file. Example: e2er run "<RQ>"')
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
                template=args.template,
                demonstration=args.demonstration,
                data=args.data,
                papers=args.papers,
                only_my_papers=args.only_my_papers,
            )
        )
    elif args.command == "init":
        from .cli_init import init as _init

        sys.exit(_init(force=args.force, defaults=args.defaults))
    elif args.command == "status" and Path(args.paper_id).expanduser().is_dir():
        from . import cli_platform

        sys.exit(cli_platform.status(args.paper_id, args.url))
    elif args.command == "status":
        from .cli_status import status as _status

        sys.exit(
            _status(
                paper_id=args.paper_id,
                tail=args.tail,
                monitor_seconds=args.monitor_seconds,
            )
        )
    elif args.command == "list":
        from .cli_studies import list_studies as _list

        sys.exit(_list(attempts=args.attempts, archived=args.archived, q=args.search))
    elif args.command == "archive":
        from .cli_studies import archive as _archive

        if args.paper_id and (args.study or args.failed):
            archive_p.error("give a paper id, --study or --failed, not more than one")
        sys.exit(_archive(args.paper_id, study=args.study, failed=args.failed, yes=args.yes))
    elif args.command == "unarchive":
        from .cli_studies import unarchive as _unarchive

        sys.exit(_unarchive(args.paper_id, study=args.study))
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
    elif args.command == "review":
        from .cli_review import review as _review

        sys.exit(
            _review(
                args.paper_id,
                approve=args.approve,
                instruction=args.instruction,
                edit=args.edit,
                send_back=args.send_back,
                remark=args.remark,
            )
        )
    elif args.command == "rerun":
        from .cli_review import rerun as _rerun

        sys.exit(_rerun(args.paper_id, step=args.from_step, remark=args.remark))
    elif args.command == "preregister":
        from .cli_review import deposit as _deposit

        if args.prereg_command != "deposit":
            prereg_p.print_help()
            sys.exit(1)
        sys.exit(_deposit(args.target, zenodo=args.zenodo, osf=args.osf, sandbox=args.sandbox))
    elif args.command == "migrate":
        # Importable module (works in both pip-installed wheel AND dev
        # checkout). The previous implementation pointed at
        # `scripts/migrate.py` which is excluded from the wheel — see
        # pyproject.toml `[tool.setuptools.packages.find]` exclude rules.
        from .db.migrate import main as _migrate_main

        _migrate_main()

    else:
        sys.exit(
            _serve(
                host=getattr(args, "host", "127.0.0.1"),
                port=getattr(args, "port", None) or args.top_port or _settings_port(),
                reload=getattr(args, "reload", False),
                no_browser=getattr(args, "no_browser", False) or args.top_no_browser,
            )
        )


#: Arguments that take a path, per command. Each is cleaned with the forgiving
#: path helper, so a path pasted with a prompt glyph, quotes or drag-and-drop
#: escapes works the same as a typed one.
_PATH_ARGS: dict[str, tuple[str, ...]] = {
    "run": ("rq_file",),
    "run-matrix": ("rq_file", "out"),
    "status": ("paper_id",),
    "verify": ("bundle",),
    "redact": ("folder",),
    "abstract": ("folder", "from_file"),
    "reproduce": ("folder", "json_out"),
    "verify-citations": ("draft", "bib"),
    "publish": ("bundle", "out", "db"),
    "export": ("to",),
    "pack": ("target", "out"),
    "unpack": ("package", "dest"),
    "inspect": ("package",),
    "compare": ("paths", "out"),
    "question": ("out",),
    "rq": ("out",),
    "preregister": ("target",),
    "submit": ("path",),
    "dossier": ("bundle",),
}


def _clean_path_args(args: argparse.Namespace) -> None:
    from .paths import clean_path_input

    for name in _PATH_ARGS.get(str(getattr(args, "command", "") or ""), ()):
        value = getattr(args, name, None)
        if isinstance(value, str):
            setattr(args, name, clean_path_input(value))
        elif isinstance(value, list):
            setattr(args, name, [clean_path_input(v) if isinstance(v, str) else v for v in value])


def _github_login(args: argparse.Namespace) -> str | None:
    """The author's GitHub login: --github-login, else a --github value without "/" (its earlier meaning)."""
    if args.github_login:
        return str(args.github_login)
    value = args.github
    if isinstance(value, str) and "/" not in value:
        print(
            f"note: --github {value} is read as your GitHub login (--github-login {value}); "
            "--github OWNER/REPO, or --github alone, puts the study's files in a GitHub repository",
            file=sys.stderr,
        )
        return value
    return None


def _github_repo(args: argparse.Namespace) -> str | bool | None:
    """--github alone (True: <login>/<project>), --github OWNER/REPO, or None (no files on GitHub)."""
    value = args.github
    if value is True or (isinstance(value, str) and "/" in value):
        return value
    return None


def _already_serving(host: str, port: int) -> bool:
    """Is an E2ER already answering there?

    Checked against the API rather than the raw socket, so an unrelated service
    on the port is not mistaken for ours and silently reused.
    """
    try:
        import httpx

        r = httpx.get(f"http://{host}:{port}/api/papers", timeout=1.5)
        return r.status_code == 200
    except Exception:  # noqa: BLE001 — any failure means "not ours"
        return False


def _interactive() -> bool:
    """A person at a terminal (not a script, a service or CI)."""
    try:
        return sys.stdout.isatty() and sys.stdin.isatty()
    except (AttributeError, ValueError):
        return False


def _launch_url(host: str, port: int, token: str | None) -> str:
    """The address to open. Carries the session token, which the dashboard trades for a cookie."""
    shown = "127.0.0.1" if host in ("0.0.0.0", "::", "") else host
    base = f"http://{shown}:{port}/"
    return f"{base}?t={token}" if token else base


def _open_browser(url: str, delay: float = 1.2) -> None:
    """Open the dashboard, a moment after the server is up.

    Best-effort: a headless machine, a container or a locked-down desktop has no
    browser to open, and that is not a reason to fail a server start.
    """
    import threading
    import webbrowser

    def _later() -> None:
        import time

        time.sleep(delay)
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001
            pass

    threading.Thread(target=_later, daemon=True).start()


def _serve(*, host: str, port: int, reload: bool, no_browser: bool) -> int:
    """Run the dashboard. Returns the process exit code.

    Opens the browser when a person started it at a terminal (never for
    scripts or with --no-browser); the address is always printed. When e2er is
    already running on the port, it opens that one instead of failing.
    """
    import os

    import uvicorn

    from .api import local_session as ls

    open_it = not no_browser and _interactive()

    if _already_serving(host, port):
        url = _launch_url(host, port, ls.read_session_token(port))
        print(f"e2er is already running at {url} — opening it.")
        if open_it:
            import webbrowser

            try:
                webbrowser.open(url)
            except Exception:  # noqa: BLE001
                pass
        return 0

    token = os.environ.get(ls.ENV_TOKEN) or ls.stable_token()
    os.environ[ls.ENV_TOKEN] = token  # the uvicorn app (and a --reload worker) read it from here
    from .home import ENV_PROJECT, project_dir

    if reload:
        # A --reload worker is another process: it uses the studies folder chosen now.
        os.environ.setdefault(ENV_PROJECT, str(project_dir().resolve()))
    url = _launch_url(host, port, token)

    if open_it and not reload:
        _open_browser(url)

    from .home import print_storage_warnings

    print_storage_warnings()
    print(f"e2er is running at {url}")
    print("   (keep this window open while you work; ctrl-c stops e2er)")
    stop = _write_session_file_when_up(host, port, token)
    try:
        uvicorn.run("src.api.app:app", host=host, port=port, reload=reload, log_level="warning")
    except SystemExit as e:  # uvicorn raises this on a bind failure
        code = e.code if isinstance(e.code, int) else 1
        if code:
            print(
                f"Could not start on port {port}: something else is using it.\nTry:  e2er --port {port + 1}",
                file=sys.stderr,
            )
        return code
    except OSError as e:
        print(f"Could not start on {url}: {e}", file=sys.stderr)
        return 1
    finally:
        stop.set()
        ls.remove_session_file(port)
    return 0


def _settings_port() -> int:
    """The dashboard's port from settings (PORT in .env), the same one `e2er run` talks to."""
    from .cli_run import _api_port

    return _api_port()


def _write_session_file_when_up(host: str, port: int, token: str) -> Any:
    """Write ``~/.e2er/session-<port>.json`` once this server answers on the port, never before.

    Written before binding, a second `e2er` started on a port already in use
    replaced the running server's session file with its own and then failed to
    start. The file is written when ``/health`` on the port answers from this
    process (or, with ``--reload``, from its worker). Returns an event that
    stops the wait.
    """
    import os
    import threading

    from .api import local_session as ls

    stop = threading.Event()
    mine = {os.getpid()}

    def _ours() -> bool:
        try:
            import httpx

            ident = httpx.get(f"http://{host}:{port}/health", timeout=1.0).json().get("process") or {}
        except Exception:  # noqa: BLE001 - not up yet, or not e2er
            return False
        return ident.get("pid") in mine or ident.get("ppid") in mine

    def _wait() -> None:
        while not stop.wait(0.2):
            if _ours():
                try:
                    ls.write_session_file(port, token)
                except OSError:
                    pass  # only a second `e2er` needs it; the printed address works regardless
                return

    threading.Thread(target=_wait, daemon=True).start()
    return stop


if __name__ == "__main__":
    main()
