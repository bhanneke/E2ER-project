"""``e2er rq`` — sharpen a draft research question (refine-only, WS-P2).

Pillar (b) of the MVP: help the researcher turn a rough draft RQ into a
precise, feasible, falsifiable one — grounded in the data sources and the
literature actually available to THIS project. One backend call; the output
is a structured ``rq.json`` the researcher can inspect and edit.

Researcher sovereignty: `rq` NEVER starts a run. It only advises. The
researcher decides, then invokes `e2er run` themselves (optionally
`e2er run --rq-file rq.json`).
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

RQ_KEYS = ("research_question", "rationale", "candidate_variables", "identification_options", "feasibility_notes")
_LIST_KEYS = ("candidate_variables", "identification_options", "feasibility_notes")

_SYSTEM = (
    "You are a research-design assistant for empirical social science. You help a "
    "researcher sharpen a draft research question into one that is precise, "
    "falsifiable, and feasible given the data and literature ACTUALLY available. "
    "Never invent data sources or citations. Respond with ONLY a JSON object."
)


def _build_prompt(draft: str, data_sources: list[dict], papers: list[dict]) -> str:
    ds = "\n".join(f"- {s.get('name', '?')}: {s.get('description', '')}" for s in data_sources) or "(none configured)"
    lit = (
        "\n".join(f"- {p.get('title', '?')} ({p.get('year', 'n.d.')})" for p in papers)
        or "(no matches in the local library)"
    )
    return (
        f"Draft research question:\n{draft}\n\n"
        f"Data sources actually available to this project:\n{ds}\n\n"
        f"Relevant papers from the researcher's own library:\n{lit}\n\n"
        "Refine the draft into a precise, feasible, falsifiable empirical research question "
        "grounded in the data + literature above. Do not invent data or citations. "
        "Return ONLY this JSON object:\n"
        "{\n"
        '  "research_question": "<one sharpened RQ>",\n'
        '  "rationale": "<why this framing; what it improves over the draft>",\n'
        '  "candidate_variables": ["<outcome / treatment / controls the available data can support>"],\n'
        '  "identification_options": ["<plausible identification strategies given the data>"],\n'
        '  "feasibility_notes": ["<caveats: data gaps, power, measurement, threats to validity>"]\n'
        "}"
    )


async def _gather_context(draft: str, use_data: bool, use_literature: bool) -> tuple[list[dict], list[dict]]:
    """Best-effort: available data sources + local-library papers for the draft.
    Each source is independent and never fatal (an offline / unconfigured
    provider just contributes nothing)."""
    data_sources: list[dict] = []
    papers: list[dict] = []
    if use_data:
        try:
            from .modules.data.discovery_tools import SeriesDataToolHandler

            raw = await SeriesDataToolHandler().handle("list_data_sources", {})
            got = json.loads(raw).get("sources", [])
            data_sources = [s for s in got if isinstance(s, dict)]
        except Exception as e:  # noqa: BLE001 — context is best-effort
            print(f"  (data catalog unavailable: {e})", file=sys.stderr)
    if use_literature:
        try:
            from .modules.literature.tools import LiteratureToolHandler

            raw = await LiteratureToolHandler(Path.cwd()).handle("search_papers", {"query": draft, "limit": 5})
            got = json.loads(raw).get("papers", [])
            papers = [p for p in got if isinstance(p, dict)]
        except Exception as e:  # noqa: BLE001
            print(f"  (literature search unavailable: {e})", file=sys.stderr)
    return data_sources, papers


async def _call_backend(system: str, prompt: str) -> str:
    from .config import get_settings
    from .modules.llm.registry import get_backend

    backend = get_backend(get_settings())
    result = await backend.tool_loop(
        system=system,
        messages=[{"role": "user", "content": prompt}],
        tools=[],
        tool_handler=None,
        max_turns=1,
    )
    if not result.output:
        raise RuntimeError(result.error or "backend returned no output")
    return result.output


def _normalize(parsed: dict[str, Any]) -> dict[str, Any]:
    data: dict[str, Any] = {}
    data["research_question"] = str(parsed.get("research_question", "")).strip()
    data["rationale"] = str(parsed.get("rationale", "")).strip()
    for k in _LIST_KEYS:
        v = parsed.get(k)
        data[k] = [str(x) for x in v] if isinstance(v, list) else ([str(v)] if v else [])
    return data


def _render(data: dict[str, Any]) -> str:
    out = [f"Research question:\n  {data.get('research_question') or '—'}", ""]
    if data.get("rationale"):
        out += [f"Rationale:\n  {data['rationale']}", ""]
    for key, label in (
        ("candidate_variables", "Candidate variables"),
        ("identification_options", "Identification options"),
        ("feasibility_notes", "Feasibility notes"),
    ):
        vals = data.get(key) or []
        if vals:
            out.append(f"{label}:")
            out += [f"  - {v}" for v in vals]
            out.append("")
    return "\n".join(out)


def rq(draft: str, use_data: bool = True, use_literature: bool = True, out: str | None = None) -> int:
    """Entry point for `e2er rq`. Exit 0 on success, 1 on backend failure, 2 on bad input."""
    if not draft or not draft.strip():
        print("e2er rq: provide a draft research question with --draft", file=sys.stderr)
        return 2

    data_sources, papers = asyncio.run(_gather_context(draft, use_data, use_literature))
    prompt = _build_prompt(draft, data_sources, papers)
    try:
        output = asyncio.run(_call_backend(_SYSTEM, prompt))
    except Exception as e:  # noqa: BLE001 — surface a clean error, no traceback
        print(f"e2er rq: backend call failed: {e}", file=sys.stderr)
        return 1

    from .modules.llm.base import extract_json

    parsed = extract_json(output) or {}
    if not parsed.get("research_question"):
        print("e2er rq: the model did not return a research_question. Raw output:", file=sys.stderr)
        print(output[:600], file=sys.stderr)
        return 1

    data = _normalize(parsed)
    print(_render(data))
    print(
        '\nAdvisory only — you choose the RQ. Run it with:\n  e2er run "<your RQ>"'
        + ("   (or: e2er run --rq-file <file>)" if out else ""),
        file=sys.stderr,
    )
    if out:
        Path(out).expanduser().write_text(json.dumps(data, indent=2), encoding="utf-8")
        print(f"Wrote {out}", file=sys.stderr)
    return 0
