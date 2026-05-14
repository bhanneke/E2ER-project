"""Specialist execution — owns the tool-use loop for each specialist call."""

from __future__ import annotations

import time
from pathlib import Path

from ...logging_config import get_logger
from ...modules.llm.base import CompositeToolHandler, LLMBackend, ToolHandler
from ...modules.llm.tools import FILE_TOOLS, FileToolHandler
from ...modules.tracking.costs import compute_cost
from ...modules.tracking.usage import save_usage
from ..specialists.contracts import Contribution, WorkOrder

logger = get_logger(__name__)

_MAX_TURNS = 80  # Bumped from 40 after May 2026 hack-event run: data_analyst hit the
# 40-cap while paginating the new Allium developer endpoints (each get-transfers /
# get-wallet-tx page = ~2 turns; 10 events × 3 endpoints × 3 pages = ~180 turns
# in the worst case). Previously 25 was enough when only SQL was wired up.
# 80 gives data_analyst headroom for real paginated data extraction; specialists
# that don't need it won't burn what they don't use — turns is a cap, not a target.


async def run_specialist(
    work_order: WorkOrder,
    backend: LLMBackend,
    workspace: Path,
    model: str,
    extra_tools: list[dict] | None = None,
    extra_handlers: list[ToolHandler] | None = None,
    backend_name: str = "anthropic",
) -> Contribution:
    """Execute a specialist using the pipeline's own tool-use loop.

    This replaces the Claude Code CLI subprocess pattern — we own the loop,
    which enables intercepting tool calls for guardrails.
    """
    from ...skills.loader import load_skills_for_specialist

    t0 = time.time()
    paper_id = work_order.paper_id
    specialist = work_order.specialist

    skills_text = load_skills_for_specialist(specialist)
    has_allium = any((t.get("name") == "query_allium") for t in (extra_tools or []))
    system = _build_system_prompt(specialist, skills_text, has_allium=has_allium)
    user_prompt = _build_user_prompt(work_order)

    # CLI backend uses Claude Code's native tool names (Write/Read/Edit/Glob)
    # rather than the SDK's (write_file/read_file/...). Translate references
    # in both prompts so the model finds the tools it's told to call.
    # Discovered May 2026 NFT-paper run #3: specialists "succeeded" with
    # tools_called=0 because they read "use `write_file`" but only `Write`
    # was available, and just emitted text instead.
    if backend_name == "claude_code":
        system = _translate_tool_names_for_cli(system)
        user_prompt = _translate_tool_names_for_cli(user_prompt)

    tools = list(FILE_TOOLS)
    if extra_tools:
        tools.extend(extra_tools)

    file_handler = FileToolHandler(workspace)
    handlers: list[ToolHandler] = list(extra_handlers or []) + [file_handler]
    handler = CompositeToolHandler(handlers)

    messages = [{"role": "user", "content": user_prompt}]

    logger.info(
        "%s: starting tool_loop (system=%d chars, user=%d chars, %d tools, max_turns=%d)",
        specialist,
        len(system),
        len(user_prompt),
        len(tools),
        _MAX_TURNS,
    )
    t_loop = time.time()

    result = await backend.tool_loop(
        system=system,
        messages=messages,
        tools=tools,
        tool_handler=handler,
        max_turns=_MAX_TURNS,
        # Forwarded so the CLI backend can wire E2ER_PAPER_ID / E2ER_SPECIALIST
        # into the subprocess env. SDK backends ignore them — the in-process
        # tool handler already carries this state.
        paper_id=paper_id,
        specialist=specialist,
    )

    duration = time.time() - t0
    logger.info(
        "%s: tool_loop returned in %.1fs (success=%s, tools_called=%d, tokens=%d)",
        specialist,
        time.time() - t_loop,
        result.success,
        result.tool_calls_made,
        result.usage.total_tokens,
    )

    cost = compute_cost(model, result.usage)
    try:
        await save_usage(
            paper_id=paper_id,
            specialist=specialist,
            backend=backend_name,
            model=model,
            usage=result.usage,
        )
    except Exception as e:
        logger.warning("Could not save usage: %s", e)

    output_file = _find_output_file(workspace, specialist, work_order.output_file)

    # Persist a row in `contributions` so the audit bundle has a permanent
    # record of every specialist invocation (success or failure).
    try:
        from ...db.client import execute

        await execute(
            """
            INSERT INTO contributions
                (paper_id, specialist, output_file, success, error_msg,
                 usage_tokens, cost_usd, duration_sec)
            VALUES (%(p)s, %(sp)s, %(of)s, %(s)s, %(em)s, %(ut)s, %(cu)s, %(ds)s)
            """,
            {
                "p": paper_id,
                "sp": specialist,
                "of": output_file,
                "s": result.success,
                "em": result.error or None,
                "ut": result.usage.total_tokens,
                "cu": str(cost),
                "ds": round(duration, 2),
            },
        )
    except Exception as e:
        logger.debug("Contribution log skipped (no DB?): %s", e)

    return Contribution(
        paper_id=paper_id,
        specialist=specialist,
        output=result.output,
        output_file=output_file,
        usage_tokens=result.usage.total_tokens,
        cost_usd=float(cost),
        duration_seconds=duration,
        success=result.success,
        error=result.error or "",
    )


_DATA_SPECIALISTS = frozenset(["data_analyst", "data_architect", "econometrics_specialist"])


# Tool-name aliases. The Anthropic SDK exposes JSON-schema tools named
# `write_file`, `read_file`, `edit_file`, `list_directory` (defined in
# src/modules/llm/tools.py). The Claude Code CLI exposes its own native
# tools named `Write`, `Read`, `Edit`, `Glob`. The system + user prompts
# reference the SDK names; when the active backend is the CLI, we translate
# those names so the model finds the tool it's instructed to call.
_CLI_TOOL_ALIASES = {
    "write_file": "Write",
    "read_file": "Read",
    "edit_file": "Edit",
    "list_directory": "Glob",
}


def _translate_tool_names_for_cli(text: str) -> str:
    """Replace SDK tool names with their Claude Code CLI equivalents.

    Replaces both backtick-quoted forms (`write_file`) and bare references
    that appear in skill files. Order matters: replace the longest names
    first so we don't truncate (e.g. read_file before read).
    """
    for sdk_name, cli_name in sorted(_CLI_TOOL_ALIASES.items(), key=lambda kv: -len(kv[0])):
        text = text.replace(f"`{sdk_name}`", f"`{cli_name}`")
        text = text.replace(sdk_name, cli_name)
    return text


def _build_system_prompt(specialist: str, skills_text: str, has_allium: bool = False) -> str:
    name = specialist.replace("_", " ").title()
    lines = [
        f"You are the {name} specialist in an end-to-end empirical research pipeline.",
        "You produce high-quality academic research outputs.",
        "",
        "## Output Discipline (strict)",
        "1. Your work order names ONE output file. Write that single file with `write_file`.",
        "2. Do not create indexes, summaries, completion reports, status files, "
        "checklists, READMEs, manifests, or any auxiliary deliverables. "
        "One specialist = one artifact.",
        "3. Do not invent additional filenames. The orchestrator only collects "
        "the canonical artifact named in the work order.",
        "4. After the single write_file call succeeds, end your turn — no further commentary, no follow-up files.",
        "5. If you need to gather information, use read_file or other tools, "
        "but produce exactly one final write_file at the end.",
        "",
    ]
    if specialist == "data_analyst" and has_allium:
        lines.extend(
            [
                "## Mandatory Data Sourcing — DO NOT SYNTHESIZE",
                "The Allium tool `query_allium` is wired into your tool list. You MUST use it.",
                '- Do NOT write "synthetic", "calibrated", "plausible", "illustrative", "hypothetical" '
                'or "representative" numbers. Inventing data is a hard failure.',
                "- Workflow:",
                "  1. Call `list_allium_tables` once to confirm the table you'll query.",
                "  2. Submit a `query_allium` call with `query_type='feasibility'` (auto-approved, "
                "samples 1000 rows). Inspect the result.",
                "  3. Submit production queries with `query_type='production'`. These return a "
                "`query_id` and require human approval — poll `check_approval` until status='approved' "
                "(typically takes minutes; do NOT give up). Once approved, query_allium returns the rows.",
                "  4. Build the data_summary.md from the actual returned rows. Cite the query_ids.",
                "- If a query is rejected or never approves within reasonable time, report this in "
                "data_summary.md as a transparent failure — do NOT fall back to invented data.",
                "",
            ]
        )
    if skills_text:
        lines.append("## Your Expertise\n")
        lines.append(skills_text)
    return "\n".join(lines)


_BIB_SPECIALISTS = frozenset(
    [
        "literature_scanner",
        "paper_drafter",
        "section_writer",
        "abstract_writer",
        "revisor",
    ]
)


def _build_user_prompt(work_order: WorkOrder) -> str:
    from ..specialists.registry import REVIEWER_SPECIALISTS

    parts = [f"## Work Order\n{work_order.focus}"]
    if work_order.context:
        parts.append(f"\n## Context\n{work_order.context}")
    bib = _load_reference_summary(work_order.specialist)
    if bib:
        parts.append(f"\n{bib}")
    # Reviewers get the full draft + supporting docs pre-loaded above.
    # Stop them from re-reading via read_file (each tool result re-enters
    # the conversation history on every subsequent turn — quadratic blow-up).
    if work_order.specialist in REVIEWER_SPECIALISTS:
        parts.append(
            "\n## Reviewing Instructions\n"
            "The full paper draft and all supporting documents are already "
            "above in your Context. Do NOT call read_file or list_directory "
            "— they are unnecessary and waste tokens. Review the material in "
            "your context directly, then write your single review file.\n"
            "\n## MANDATORY closing format — parser-enforced\n"
            "Your review file MUST end with these two lines EXACTLY, on their "
            "own lines, no markdown bold, no extra punctuation:\n"
            "```\n"
            "OVERALL SCORE: <number>/10\n"
            "RECOMMENDATION: <Accept | Minor Revision | Major Revision | Reject>\n"
            "```\n"
            "The mechanical review aggregator parses these two lines to compute "
            "the panel verdict. Reviews without them are dropped from the "
            "weighted average, which biases the aggregation and may hide a "
            "MECHANISM_FAIL or HARD_REJECT signal. Do not end with prose; "
            "end with the two required lines."
        )
    if work_order.output_file:
        parts.append(
            f"\n## Required Output\n"
            f"Write your work to EXACTLY ONE file at this exact path, directly in "
            f"the current working directory: `./{work_order.output_file}`.\n"
            f"Do NOT create subdirectories. Do NOT add prefixes like "
            f"`workspace/`, `{work_order.specialist}/`, `output/`, etc. The file "
            f"must appear as `./{work_order.output_file}` relative to cwd, "
            f"nothing else. Use the exact filename — do not rename or extend it.\n"
            f"After the single `write_file` call succeeds, end your turn — "
            f"no further commentary, no follow-up files."
        )
    return "\n".join(parts)


def _load_reference_summary(specialist: str) -> str:
    """Return a compact bibliography block if LITERATURE_BIBTEX_FILE is set."""
    if specialist not in _BIB_SPECIALISTS:
        return ""
    from ...config import get_settings

    settings = get_settings()
    if not settings.literature_bibtex_file:
        return ""
    bib_path = Path(settings.literature_bibtex_file)
    if not bib_path.exists():
        return ""
    try:
        from ...modules.literature.bibtex import parse_bibtex_file

        papers = parse_bibtex_file(bib_path)
    except Exception:
        return ""
    if not papers:
        return ""
    lines = [f"## Available References ({len(papers)} papers from {bib_path.name})\n"]
    for p in papers[:60]:
        authors = ", ".join(p.authors[:2])
        if len(p.authors) > 2:
            authors += " et al."
        year = f" ({p.year})" if p.year else ""
        journal = f". _{p.journal}_" if p.journal else ""
        lines.append(f'- {authors}{year}. "{p.title}"{journal}')
    if len(papers) > 60:
        lines.append(f"  ... and {len(papers) - 60} more. See `{bib_path}` for the full list.")
    return "\n".join(lines)


def _find_output_file(workspace: Path, specialist: str, expected: str) -> str:
    """Locate the specialist's canonical artifact in the workspace.

    Looks first at the expected path. If the model nested the file in a
    subdirectory (CLI backend behaviour observed May 2026: writes to
    `workspace/<specialist>/<artifact>` or similar despite explicit "no
    subdirectories" instruction), recover by scanning the workspace for
    any file matching the basename and moving it to the canonical location.
    """
    from ..specialists.registry import SPECIALIST_ARTIFACTS

    target = expected or SPECIALIST_ARTIFACTS.get(specialist, "")
    if not target:
        return ""

    canonical = workspace / target
    if canonical.exists():
        return str(canonical)

    # Recovery: find by basename, prefer shortest path (least nesting),
    # ignore replication/ (legitimate subdir).
    basename = Path(target).name
    candidates = [p for p in workspace.rglob(basename) if p.is_file() and "replication" not in p.parts]
    if not candidates:
        return ""
    candidates.sort(key=lambda p: len(p.parts))
    found = candidates[0]
    logger.warning(
        "%s: artifact found at %s instead of canonical %s — moving to canonical location",
        specialist,
        found.relative_to(workspace),
        target,
    )
    canonical.parent.mkdir(parents=True, exist_ok=True)
    found.rename(canonical)
    return str(canonical)
