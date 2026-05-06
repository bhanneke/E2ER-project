"""Literature module — LLM tool definitions and handler.

Mirrors the Allium tools pattern. Specialists allow-listed via
LITERATURE_SPECIALISTS get these tools wired into their tool_loop.

Tool calls dispatch to existing async clients in this module:
- search_papers: OpenAlex (no key) with arXiv as fallback if it errors
- fetch_paper: OpenAlex by DOI, falling back to Semantic Scholar
- save_bibtex: append a discovered paper to the workspace's literature.bib

The handler also persists a running list of citations to literature.bib in
the paper workspace so the LaTeX compiler can wire up \\bibliography{refs}.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ...logging_config import get_logger
from ..llm.base import ToolHandler
from .models import PaperMetadata

logger = get_logger(__name__)

# Specialists permitted to use these tools — mirrors the bib-injection list.
LITERATURE_SPECIALISTS = frozenset({
    "literature_scanner",
    "polish_bibliography",
    "revisor",
    "paper_drafter",
})

LITERATURE_TOOLS: list[dict[str, Any]] = [
    {
        "name": "search_papers",
        "description": (
            "Search the academic literature for papers matching a query. "
            "Uses OpenAlex (free, no key) with arXiv as a fallback. "
            "Returns up to `limit` papers with title, authors, year, DOI, and abstract. "
            "Use this to discover prior work, find seminal references, or identify "
            "relevant econometric methods for a research question."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Free-text query — e.g. 'concentrated liquidity Uniswap v3'",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max papers to return (1-50). Default 10.",
                    "default": 10,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "fetch_paper",
        "description": (
            "Fetch a single paper's metadata by DOI. Returns title, authors, year, "
            "abstract, journal, and citation count when available."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "doi": {
                    "type": "string",
                    "description": "DOI in plain form — e.g. '10.1093/rfs/hhab123'",
                },
            },
            "required": ["doi"],
        },
    },
    {
        "name": "save_bibtex",
        "description": (
            "Save a paper to the workspace's literature.bib so the final paper can "
            "cite it. Pass either a `doi` (the tool will fetch metadata) or a fully "
            "constructed `bibtex_entry` string. Returns the BibTeX key written, "
            "which the writer should use in \\cite{} commands."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "doi": {"type": "string", "description": "DOI to fetch and save"},
                "bibtex_entry": {
                    "type": "string",
                    "description": "Pre-built @article{...} entry (if no DOI is available)",
                },
            },
        },
    },
]


class LiteratureToolHandler(ToolHandler):
    """Intercepts literature tool calls. One handler instance per specialist run.

    Enforces a per-specialist call budget so models like Sonnet 4.6 don't go
    on a search-and-save spree. A single literature_scanner run on Sonnet
    burned 522K tokens with 36 tool calls before this cap was added.
    """

    # Per-specialist hard caps. After these the tool returns a budget-exceeded
    # message instructing the model to stop searching and write its output.
    _MAX_SEARCHES = 8
    _MAX_FETCHES = 12
    _MAX_SAVES = 30

    def __init__(self, workspace: Path) -> None:
        self._workspace = Path(workspace)
        self._bib_path = self._workspace / "literature.bib"
        self._search_calls = 0
        self._fetch_calls = 0
        self._save_calls = 0

    def can_handle(self, tool_name: str) -> bool:
        return tool_name in {"search_papers", "fetch_paper", "save_bibtex"}

    async def handle(self, tool_name: str, tool_input: dict[str, Any]) -> str:
        # Budget guard — return a stop signal rather than execute the call.
        if tool_name == "search_papers" and self._search_calls >= self._MAX_SEARCHES:
            return json.dumps({
                "error": f"search budget exhausted ({self._MAX_SEARCHES} calls). "
                "Stop searching and write your output now using the references "
                "you have already found.",
            })
        if tool_name == "fetch_paper" and self._fetch_calls >= self._MAX_FETCHES:
            return json.dumps({
                "error": f"fetch budget exhausted ({self._MAX_FETCHES} calls). "
                "Stop fetching and proceed with what you have.",
            })
        if tool_name == "save_bibtex" and self._save_calls >= self._MAX_SAVES:
            return json.dumps({
                "error": f"save_bibtex budget exhausted ({self._MAX_SAVES} entries). "
                "Use what's saved and write your output.",
            })

        try:
            if tool_name == "search_papers":
                self._search_calls += 1
                return await self._search(tool_input)
            if tool_name == "fetch_paper":
                self._fetch_calls += 1
                return await self._fetch(tool_input)
            if tool_name == "save_bibtex":
                self._save_calls += 1
                return await self._save(tool_input)
        except Exception as e:
            logger.warning("Literature tool %s failed: %s", tool_name, e)
            return json.dumps({"error": str(e)})
        return json.dumps({"error": f"unknown tool: {tool_name}"})

    async def _search(self, inp: dict[str, Any]) -> str:
        from . import openalex, arxiv
        query = inp["query"]
        limit = max(1, min(int(inp.get("limit", 10)), 50))
        try:
            result = await openalex.search_papers(query, limit=limit)
            if result.papers:
                return json.dumps({
                    "source": "openalex",
                    "query": query,
                    "count": len(result.papers),
                    "papers": [_to_dict(p) for p in result.papers],
                })
        except Exception as e:
            logger.info("OpenAlex search failed (%s) — falling back to arXiv", e)
        # Fallback
        try:
            result = await arxiv.search_papers(query, limit=limit)
            return json.dumps({
                "source": "arxiv",
                "query": query,
                "count": len(result.papers),
                "papers": [_to_dict(p) for p in result.papers],
            })
        except Exception as e:
            return json.dumps({"error": f"all search backends failed: {e}"})

    async def _fetch(self, inp: dict[str, Any]) -> str:
        from . import openalex, semantic_scholar
        doi = inp["doi"].strip()
        try:
            paper = await openalex.fetch_by_doi(doi)
            if paper:
                return json.dumps({"source": "openalex", "paper": _to_dict(paper)})
        except Exception as e:
            logger.info("OpenAlex fetch failed (%s) — falling back to S2", e)
        try:
            paper = await semantic_scholar.fetch_by_doi(doi)
            if paper:
                return json.dumps({"source": "semantic_scholar", "paper": _to_dict(paper)})
        except Exception as e:
            logger.info("S2 fetch failed: %s", e)
        return json.dumps({"error": f"paper not found for DOI {doi}"})

    async def _save(self, inp: dict[str, Any]) -> str:
        # If a literal BibTeX entry was provided, append it directly.
        entry: str | None = inp.get("bibtex_entry")
        key: str | None = None
        if entry:
            entry = entry.strip()
            key = _extract_bibtex_key(entry)
        elif inp.get("doi"):
            from . import openalex, semantic_scholar
            doi = inp["doi"].strip()
            paper = None
            try:
                paper = await openalex.fetch_by_doi(doi)
            except Exception:
                pass
            if paper is None:
                try:
                    paper = await semantic_scholar.fetch_by_doi(doi)
                except Exception:
                    pass
            if paper is None:
                return json.dumps({"error": f"could not fetch DOI {doi}"})
            entry = paper.to_bibtex()
            key = paper.bibtex_key
        else:
            return json.dumps({"error": "either doi or bibtex_entry is required"})

        # Skip duplicates by key.
        if self._bib_path.exists():
            existing = self._bib_path.read_text(encoding="utf-8")
            if key and f"{{{key}," in existing:
                return json.dumps({"key": key, "status": "already_present"})
            with self._bib_path.open("a", encoding="utf-8") as f:
                f.write("\n\n" + entry + "\n")
        else:
            self._bib_path.write_text(entry + "\n", encoding="utf-8")
        return json.dumps({"key": key or "unknown", "status": "saved"})


def _to_dict(p: PaperMetadata) -> dict[str, Any]:
    return {
        "title": p.title,
        "authors": p.authors,
        "year": p.year,
        "doi": p.doi,
        "abstract": (p.abstract or "")[:1500],  # cap for token economy
        "journal": p.journal,
        "citations": p.citations,
        "bibtex_key": p.bibtex_key,
    }


def _extract_bibtex_key(entry: str) -> str | None:
    # @article{key, ... → "key"
    if "{" not in entry:
        return None
    head = entry.split("{", 1)[1]
    if "," not in head:
        return None
    return head.split(",", 1)[0].strip()
