"""Literature module — pgvector storage and semantic search for paper KB."""

from __future__ import annotations

import json
from typing import Any

from ...logging_config import get_logger
from .models import PaperMetadata

logger = get_logger(__name__)


async def store_paper(paper: PaperMetadata, paper_project_id: str) -> str:
    """Store paper metadata in the literature_items table. Returns item ID.

    Backend-aware: Postgres uses ``ON CONFLICT (doi)`` + ``RETURNING``; SQLite
    (which translates neither) generates the id app-side and upserts manually
    by ``(paper_id, doi)`` / ``(paper_id, title, year)``.
    """
    from ...db.client import current_backend

    if current_backend() == "sqlite":
        return await _store_paper_sqlite(paper, paper_project_id)

    from ...db.client import fetch_one

    row = await fetch_one(
        """
        INSERT INTO literature_items
            (paper_id, title, authors, year, doi, abstract, journal, url, pdf_url, source, citations, raw)
        VALUES
            (%(pid)s, %(title)s, %(authors)s, %(year)s, %(doi)s, %(abstract)s,
             %(journal)s, %(url)s, %(pdf_url)s, %(source)s, %(citations)s, %(raw)s)
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
            "citations": paper.citations,
            "raw": json.dumps(paper.raw),
        },
    )
    return str(row["id"]) if row else ""


async def _store_paper_sqlite(paper: PaperMetadata, paper_project_id: str) -> str:
    """SQLite upsert: find an existing row by (paper_id, doi) or
    (paper_id, title, year), then UPDATE it or INSERT a new app-side-uuid row."""
    import uuid

    from ...db.client import execute, fetch_one

    doi = (paper.doi or "").strip()
    existing = None
    if doi:
        existing = await fetch_one(
            "SELECT id FROM literature_items WHERE paper_id = %(pid)s AND doi = %(doi)s LIMIT 1",
            {"pid": paper_project_id, "doi": doi},
        )
    if existing is None:
        existing = await fetch_one(
            "SELECT id FROM literature_items WHERE paper_id = %(pid)s "
            "AND LOWER(title) = LOWER(%(title)s) AND COALESCE(year, -1) = COALESCE(%(year)s, -1) LIMIT 1",
            {"pid": paper_project_id, "title": paper.title, "year": paper.year},
        )

    common = {
        "title": paper.title,
        "authors": json.dumps(paper.authors),
        "year": paper.year,
        "doi": doi or None,
        "abstract": paper.abstract,
        "journal": paper.journal,
        "url": paper.url,
        "pdf_url": paper.pdf_url,
        "pdf_path": paper.pdf_path,
        "source": paper.source,
        "citations": paper.citations,
        "raw": json.dumps(paper.raw),
    }
    if existing is not None:
        item_id = str(existing["id"])
        await execute(
            """
            UPDATE literature_items SET
                title=%(title)s, authors=%(authors)s, year=%(year)s, doi=%(doi)s,
                abstract=%(abstract)s, journal=%(journal)s, url=%(url)s, pdf_url=%(pdf_url)s,
                pdf_path=%(pdf_path)s, source=%(source)s, citations=%(citations)s, raw=%(raw)s,
                updated_at=NOW()
            WHERE id=%(id)s
            """,
            {**common, "id": item_id},
        )
        return item_id

    item_id = str(uuid.uuid4())
    await execute(
        """
        INSERT INTO literature_items
            (id, paper_id, title, authors, year, doi, abstract, journal, url, pdf_url,
             pdf_path, source, citations, raw)
        VALUES
            (%(id)s, %(pid)s, %(title)s, %(authors)s, %(year)s, %(doi)s, %(abstract)s,
             %(journal)s, %(url)s, %(pdf_url)s, %(pdf_path)s, %(source)s, %(citations)s, %(raw)s)
        """,
        {**common, "id": item_id, "pid": paper_project_id},
    )
    return item_id


async def search_literature(
    query: str,
    paper_project_id: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Search stored literature.

    SQLite: keyword (LIKE) search over the local BYOD library.
    Postgres: pgvector semantic search, falling back to keyword (ILIKE).
    """
    from ...db.client import current_backend

    if current_backend() == "sqlite":
        return await _keyword_search_sqlite(query, paper_project_id, limit)
    try:
        return await _vector_search(query, paper_project_id, limit)
    except Exception as e:
        logger.debug("Vector search unavailable (%s), using keyword search", e)
        return await _keyword_search(query, paper_project_id, limit)


async def _keyword_search_sqlite(
    query: str,
    paper_project_id: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    """LIKE search over the local SQLite library. Matches any whitespace token
    of the query against title/abstract/authors; ranks by citations."""
    from ...db.client import fetch_all

    tokens = [t for t in query.lower().split() if len(t) > 2][:6] or [query.lower()]
    clauses = []
    params: dict[str, Any] = {"limit": limit}
    for i, tok in enumerate(tokens):
        params[f"q{i}"] = f"%{tok}%"
        clauses.append(
            f"(LOWER(title) LIKE %(q{i})s OR LOWER(COALESCE(abstract,'')) LIKE %(q{i})s "
            f"OR LOWER(COALESCE(authors,'')) LIKE %(q{i})s)"
        )
    where = " OR ".join(clauses)
    pid_clause = ""
    if paper_project_id:
        pid_clause = "AND paper_id = %(pid)s"
        params["pid"] = paper_project_id

    return await fetch_all(
        f"""
        SELECT id, title, authors, year, doi, abstract, journal, url, pdf_url, pdf_path,
               0.5 AS similarity
        FROM literature_items
        WHERE ({where}) {pid_clause}
        ORDER BY citations DESC
        LIMIT %(limit)s
        """,
        params,
    )


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
