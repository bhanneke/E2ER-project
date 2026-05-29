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
from .models import PaperMetadata, SearchResult

logger = get_logger(__name__)

# Specialists permitted to use these tools — mirrors the bib-injection list.
LITERATURE_SPECIALISTS = frozenset(
    {
        "literature_scanner",
        "polish_bibliography",
        "revisor",
        "paper_drafter",
    }
)

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
    {
        "name": "read_reference",
        "description": (
            "Read the full text of a reference's PDF to deepen the literature review "
            "(read what a paper actually says, not just its abstract). Pass `path` "
            "to read a PDF staged into the workspace from LOCAL_DATA_DIR (e.g. "
            "literature/smith2024.pdf), or `pdf_url` (from a search_papers / "
            "fetch_paper result, or a reference list entry that shows one), or a "
            "`doi` (the tool will resolve an open-access PDF). Returns extracted "
            "text, truncated. Use sparingly — read only papers central to the "
            "argument; it is token-expensive."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Workspace-relative path to a local PDF (e.g. literature/foo.pdf)",
                },
                "pdf_url": {
                    "type": "string",
                    "description": "Direct PDF URL — an open-access link or a Zotero attachment href",
                },
                "doi": {
                    "type": "string",
                    "description": "DOI to resolve to an open-access PDF when no pdf_url is known",
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
    _MAX_READS = 6  # full-text PDF reads — token-expensive, so a tight cap
    # Per-read extracted-text cap (~5K tokens). Guards the token budget the
    # search/fetch budgets exist to protect (the 522K-token incident).
    _READ_CHAR_CAP = 20_000
    _PDF_MAX_BYTES = 25 * 1024 * 1024  # PDFs blow past the default 2 MB cap

    def __init__(self, workspace: Path) -> None:
        self._workspace = Path(workspace)
        self._bib_path = self._workspace / "literature.bib"
        self._search_calls = 0
        self._fetch_calls = 0
        self._save_calls = 0
        self._read_calls = 0

    def can_handle(self, tool_name: str) -> bool:
        return tool_name in {"search_papers", "fetch_paper", "save_bibtex", "read_reference"}

    async def handle(self, tool_name: str, tool_input: dict[str, Any]) -> str:
        # Budget guard — return a stop signal rather than execute the call.
        if tool_name == "search_papers" and self._search_calls >= self._MAX_SEARCHES:
            return json.dumps(
                {
                    "error": f"search budget exhausted ({self._MAX_SEARCHES} calls). "
                    "Stop searching and write your output now using the references "
                    "you have already found.",
                }
            )
        if tool_name == "fetch_paper" and self._fetch_calls >= self._MAX_FETCHES:
            return json.dumps(
                {
                    "error": f"fetch budget exhausted ({self._MAX_FETCHES} calls). "
                    "Stop fetching and proceed with what you have.",
                }
            )
        if tool_name == "save_bibtex" and self._save_calls >= self._MAX_SAVES:
            return json.dumps(
                {
                    "error": f"save_bibtex budget exhausted ({self._MAX_SAVES} entries). "
                    "Use what's saved and write your output.",
                }
            )
        if tool_name == "read_reference" and self._read_calls >= self._MAX_READS:
            return json.dumps(
                {
                    "error": f"read_reference budget exhausted ({self._MAX_READS} reads). "
                    "Proceed with what you have read.",
                }
            )

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
            if tool_name == "read_reference":
                self._read_calls += 1
                return await self._read_reference(tool_input)
        except Exception as e:
            logger.warning("Literature tool %s failed: %s", tool_name, e)
            return json.dumps({"error": str(e)})
        return json.dumps({"error": f"unknown tool: {tool_name}"})

    async def _search(self, inp: dict[str, Any]) -> str:
        from ...config import get_settings
        from .registry import search_sources

        query = inp["query"]
        limit = max(1, min(int(inp.get("limit", 10)), 50))

        # Iterate the registry's search chain (OpenAlex → arXiv). Return the
        # first source that yields papers; if none does, return the last
        # source's (empty) result; if every source raised, return an error.
        last_result: SearchResult | None = None
        last_error: Exception | None = None
        for source in search_sources(get_settings()):
            try:
                result = await source.search(query, limit)
            except Exception as e:
                last_error = e
                logger.info("%s search failed (%s) — trying next source", source.name, e)
                continue
            last_result = result
            if result.papers:
                break

        if last_result is not None:
            return json.dumps(
                {
                    "source": last_result.source,
                    "query": query,
                    "count": len(last_result.papers),
                    "papers": [_to_dict(p) for p in last_result.papers],
                }
            )
        return json.dumps({"error": f"all search backends failed: {last_error}"})

    async def _resolve_doi(self, doi: str) -> tuple[str, PaperMetadata] | None:
        """Resolve a DOI through the registry's fetch chain (OpenAlex → S2).

        Returns ``(source_name, paper)`` for the first source that finds it,
        else ``None``. Shared by ``_fetch`` and ``_save``.
        """
        from ...config import get_settings
        from .registry import doi_fetch_sources

        for source in doi_fetch_sources(get_settings()):
            try:
                paper = await source.fetch(doi)
            except Exception as e:
                logger.info("%s fetch failed: %s", source.name, e)
                continue
            if paper:
                return source.name, paper
        return None

    async def _fetch(self, inp: dict[str, Any]) -> str:
        doi = inp["doi"].strip()
        resolved = await self._resolve_doi(doi)
        if resolved is not None:
            source_name, paper = resolved
            return json.dumps({"source": source_name, "paper": _to_dict(paper)})
        return json.dumps({"error": f"paper not found for DOI {doi}"})

    @staticmethod
    def _download_target(pdf_url: str, settings: Any) -> tuple[str, dict[str, str]]:
        """Resolve a PDF href to (download_url, headers).

        Zotero attachment hrefs are ``.../file/view`` (an HTML viewer) and
        require the API key; normalize to the ``.../file`` download endpoint
        and attach the key. Everything else (open-access PDFs) downloads
        unauthenticated as-is.
        """
        from urllib.parse import urlparse

        host = urlparse(pdf_url).hostname or ""
        if host == "api.zotero.org" and settings.zotero_api_key:
            url = pdf_url[: -len("/view")] if pdf_url.endswith("/view") else pdf_url
            return url, {"Zotero-API-Key": settings.zotero_api_key}
        return pdf_url, {}

    async def _read_reference(self, inp: dict[str, Any]) -> str:
        from ...config import get_settings
        from ..fetch.http import fetch_bytes
        from .pdf import extract_pdf_text

        settings = get_settings()
        local_path = (inp.get("path") or "").strip()
        pdf_url = (inp.get("pdf_url") or "").strip()
        doi = (inp.get("doi") or "").strip()

        # Local PDF (staged from LOCAL_DATA_DIR into workspace/literature/).
        # Sandboxed to the paper's workspace; no fetch, no auth needed.
        if local_path:
            ws = self._workspace.resolve()
            target = (self._workspace / local_path).resolve()
            try:
                target.relative_to(ws)
            except ValueError:
                return json.dumps({"error": "path must be inside the workspace", "path": local_path})
            if not target.is_file():
                return json.dumps({"error": f"no file at workspace path {local_path!r}"})
            try:
                data = target.read_bytes()
            except Exception as e:
                return json.dumps({"error": f"could not read {local_path}: {e}"})
            text = extract_pdf_text(data, max_chars=self._READ_CHAR_CAP)
            if not text.strip():
                return json.dumps({"error": "PDF read but no extractable text (scanned?)", "path": local_path})
            return json.dumps({"path": local_path, "chars": len(text), "text": text})

        # No direct URL but a DOI → resolve an open-access PDF via the fetch chain.
        if not pdf_url and doi:
            resolved = await self._resolve_doi(doi)
            if resolved is not None:
                pdf_url = (resolved[1].pdf_url or "").strip()
        if not pdf_url:
            return json.dumps(
                {
                    "error": "no readable PDF for that reference — pass a `pdf_url`, "
                    "or a `doi` that has an open-access PDF.",
                }
            )

        url, headers = self._download_target(pdf_url, settings)
        try:
            data = await fetch_bytes(url, headers=headers, max_bytes=self._PDF_MAX_BYTES)
        except Exception as e:
            return json.dumps({"error": f"could not download PDF: {e}", "pdf_url": pdf_url})

        text = extract_pdf_text(data, max_chars=self._READ_CHAR_CAP)
        if not text.strip():
            return json.dumps(
                {
                    "error": "PDF downloaded but no extractable text (likely a scanned image).",
                    "pdf_url": pdf_url,
                }
            )
        return json.dumps({"pdf_url": pdf_url, "chars": len(text), "text": text})

    async def _save(self, inp: dict[str, Any]) -> str:
        # If a literal BibTeX entry was provided, append it directly.
        entry: str | None = inp.get("bibtex_entry")
        key: str | None = None
        if entry:
            entry = entry.strip()
            key = _extract_bibtex_key(entry)
        elif inp.get("doi"):
            doi = inp["doi"].strip()
            resolved = await self._resolve_doi(doi)
            if resolved is None:
                return json.dumps({"error": f"could not fetch DOI {doi}"})
            _source_name, paper = resolved
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
        "pdf_url": p.pdf_url,  # lets the model pass it to read_reference
    }


def _extract_bibtex_key(entry: str) -> str | None:
    # @article{key, ... → "key"
    if "{" not in entry:
        return None
    head = entry.split("{", 1)[1]
    if "," not in head:
        return None
    return head.split(",", 1)[0].strip()
