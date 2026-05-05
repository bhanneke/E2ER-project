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

_MAX_TURNS = 40


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
    system = _build_system_prompt(specialist, skills_text)

    tools = list(FILE_TOOLS)
    if extra_tools:
        tools.extend(extra_tools)

    file_handler = FileToolHandler(workspace)
    handlers: list[ToolHandler] = list(extra_handlers or []) + [file_handler]
    handler = CompositeToolHandler(handlers)

    messages = [{"role": "user", "content": _build_user_prompt(work_order)}]

    result = await backend.tool_loop(
        system=system,
        messages=messages,
        tools=tools,
        tool_handler=handler,
        max_turns=_MAX_TURNS,
    )

    duration = time.time() - t0

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


def _build_system_prompt(specialist: str, skills_text: str) -> str:
    name = specialist.replace("_", " ").title()
    lines = [
        f"You are the {name} specialist in an end-to-end empirical research pipeline.",
        "You produce high-quality academic research outputs.",
        "Always write output to files using the write_file tool.",
        "Never stop until your assigned artifact is complete.",
        "",
    ]
    if skills_text:
        lines.append("## Your Expertise\n")
        lines.append(skills_text)
    return "\n".join(lines)


_BIB_SPECIALISTS = frozenset([
    "literature_scanner", "paper_drafter", "section_writer",
    "abstract_writer", "revisor",
])


def _build_user_prompt(work_order: WorkOrder) -> str:
    parts = [f"## Work Order\n{work_order.focus}"]
    if work_order.context:
        parts.append(f"\n## Context\n{work_order.context}")
    bib = _load_reference_summary(work_order.specialist)
    if bib:
        parts.append(f"\n{bib}")
    if work_order.output_file:
        parts.append(f"\nWrite your output to: `{work_order.output_file}`")
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
