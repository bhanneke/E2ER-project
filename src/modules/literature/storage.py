"""Literature module — pgvector storage and semantic search for paper KB."""

from __future__ import annotations

import json
from typing import Any

from ...logging_config import get_logger
from .models import PaperMetadata

logger = get_logger(__name__)


async def store_paper(paper: PaperMetadata, paper_project_id: str) -> str:
    """Store paper metadata in the literature_items table. Returns item ID."""
    from ...db.client import fetch_one

    row = await fetch_one(
        """
        INSERT INTO literature_items
            (paper_id, title, authors, year, doi, abstract, journal, url, pdf_url, source, raw)
        VALUES
            (%(pid)s, %(title)s, %(authors)s, %(year)s, %(doi)s, %(abstract)s,
             %(journal)s, %(url)s, %(pdf_url)s, %(source)s, %(raw)s)
        ON CONFLICT (doi) DO UPDATE SET
            title = EXCLUDED.title, abstract = EXCLUDED.abstract,
            citations = EXCLUDED.citations, updated_at = NOW()
        RETURNING id
        """,
        {
            "pid": paper_project_id,
            "title": paper.title,
            "authors": json.dumps(paper.authors),
            "year": paper.year,
            "doi": paper.doi or None,
            "abstract": paper.abstract,
            "journal": paper.journal,
            "url": paper.url,
            "pdf_url": paper.pdf_url,
            "source": paper.source,
            "raw": json.dumps(paper.raw),
        },
    )
    return str(row["id"]) if row else ""


async def search_literature(
    query: str,
    paper_project_id: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Semantic search over stored literature using pgvector.
    Falls back to keyword search if embeddings are not configured.
    """
    try:
        return await _vector_search(query, paper_project_id, limit)
    except Exception as e:
        logger.debug("Vector search unavailable (%s), using keyword search", e)
        return await _keyword_search(query, paper_project_id, limit)


async def _vector_search(
    query: str,
    paper_project_id: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    from ...config import get_settings
    from ...db.client import fetch_all

    settings = get_settings()
    if not settings.literature_kb_enabled:
        raise RuntimeError("Literature KB disabled")

    embedding = await _embed(query)
    embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"

    where = "WHERE paper_id = %(pid)s" if paper_project_id else ""
    params: dict = {"emb": embedding_str, "limit": limit}
    if paper_project_id:
        params["pid"] = paper_project_id

    return await fetch_all(
        f"""
        SELECT id, title, authors, year, doi, abstract, journal, url,
               1 - (embedding <=> %(emb)s::vector) AS similarity
        FROM literature_items
        {where}
        ORDER BY embedding <=> %(emb)s::vector
        LIMIT %(limit)s
        """,
        params,
    )


async def _keyword_search(
    query: str,
    paper_project_id: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    from ...db.client import fetch_all

    where = "AND paper_id = %(pid)s" if paper_project_id else ""
    params: dict = {"q": f"%{query}%", "limit": limit}
    if paper_project_id:
        params["pid"] = paper_project_id

    return await fetch_all(
        f"""
        SELECT id, title, authors, year, doi, abstract, journal, url, 0.5 AS similarity
        FROM literature_items
        WHERE (title ILIKE %(q)s OR abstract ILIKE %(q)s) {where}
        ORDER BY citations DESC
        LIMIT %(limit)s
        """,
        params,
    )


async def _embed(text: str) -> list[float]:
    """Generate embedding vector using sentence-transformers (CPU only)."""
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer("all-MiniLM-L6-v2", device="cpu")
    return model.encode(text, show_progress_bar=False).tolist()
