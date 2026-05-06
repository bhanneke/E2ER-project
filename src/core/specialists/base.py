"""Specialist execution — owns the tool-use loop for each specialist call."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from ...logging_config import get_logger
from ...modules.llm.base import LLMBackend, CompositeToolHandler, ToolHandler
from ...modules.llm.tools import FILE_TOOLS, FileToolHandler
from ...modules.tracking.costs import compute_cost
from ...modules.tracking.usage import save_usage
from ..specialists.contracts import Contribution, WorkOrder
from ..specialists.registry import SPECIALIST_SKILLS

logger = get_logger(__name__)

_MAX_TURNS = 25  # Sonnet tool-rich specialists need more headroom; 15 was too tight


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
    has_allium = any(
        (t.get("name") == "query_allium") for t in (extra_tools or [])
    )
    system = _build_system_prompt(specialist, skills_text, has_allium=has_allium)

    tools = list(FILE_TOOLS)
    if extra_tools:
        tools.extend(extra_tools)

    file_handler = FileToolHandler(workspace)
    handlers: list[ToolHandler] = list(extra_handlers or []) + [file_handler]
    handler = CompositeToolHandler(handlers)

    user_prompt = _build_user_prompt(work_order)
    messages = [{"role": "user", "content": user_prompt}]

    logger.info(
        "%s: starting tool_loop (system=%d chars, user=%d chars, %d tools, max_turns=%d)",
        specialist, len(system), len(user_prompt), len(tools), _MAX_TURNS,
    )
    t_loop = time.time()

    result = await backend.tool_loop(
        system=system,
        messages=messages,
        tools=tools,
        tool_handler=handler,
        max_turns=_MAX_TURNS,
    )

    duration = time.time() - t0
    logger.info(
        "%s: tool_loop returned in %.1fs (success=%s, tools_called=%d, tokens=%d)",
        specialist, time.time() - t_loop, result.success,
        result.tool_calls_made, result.usage.total_tokens,
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
        "4. After the single write_file call succeeds, end your turn — "
        "no further commentary, no follow-up files.",
        "5. If you need to gather information, use read_file or other tools, "
        "but produce exactly one final write_file at the end.",
        "",
    ]
    if specialist == "data_analyst" and has_allium:
        lines.extend([
            "## Mandatory Data Sourcing — DO NOT SYNTHESIZE",
            "The Allium tool `query_allium` is wired into your tool list. You MUST use it.",
            "- Do NOT write \"synthetic\", \"calibrated\", \"plausible\", \"illustrative\", \"hypothetical\" "
            "or \"representative\" numbers. Inventing data is a hard failure.",
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
        ])
    if skills_text:
        lines.append("## Your Expertise\n")
        lines.append(skills_text)
    return "\n".join(lines)


_BIB_SPECIALISTS = frozenset([
    "literature_scanner", "paper_drafter", "section_writer",
    "abstract_writer", "revisor",
])


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
            "your context directly, then write your single review file."
        )
    if work_order.output_file:
        parts.append(
            f"\n## Required Output\n"
            f"Write your work to EXACTLY ONE file: `{work_order.output_file}`.\n"
            f"Do not create any other files. After the single `write_file` call "
            f"succeeds, end your turn."
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
        lines.append(f"- {authors}{year}. \"{p.title}\"{journal}")
    if len(papers) > 60:
        lines.append(f"  ... and {len(papers) - 60} more. See `{bib_path}` for the full list.")
    return "\n".join(lines)


def _find_output_file(workspace: Path, specialist: str, expected: str) -> str:
    from ..specialists.registry import SPECIALIST_ARTIFACTS

    target = expected or SPECIALIST_ARTIFACTS.get(specialist, "")
    if target:
        path = workspace / target
        if path.exists():
            return str(path)
    return ""
