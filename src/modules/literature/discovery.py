"""BYOD literature discovery: folder → staged PDFs → enriched → persisted.

Orchestrates the new-user flow at paper creation. For each configured
``LITERATURE_DIR`` root: auto-detect a Zotero folder vs a plain PDF folder,
read item metadata, stage each PDF into ``workspace/<id>/literature/`` (so
``read_reference`` can read it), enrich thin metadata via CrossRef/OpenAlex,
and persist into the per-paper SQLite ``literature_items`` so ``search_papers``
serves the local library offline.

Best-effort throughout — never raises into paper creation. Bounded by
``max_items`` so a 1000-PDF library doesn't stall startup or hammer CrossRef.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from ...logging_config import get_logger
from ..local_corpus import PDF_EXTENSIONS, iter_corpus_files
from .local_pdf_meta import extract_pdf_metadata
from .local_zotero import detect_zotero, read_zotero_sqlite
from .models import PaperMetadata

logger = get_logger(__name__)

_ENRICH_CONCURRENCY = 4


def discover_corpus(roots: list[Path], max_items: int) -> list[PaperMetadata]:
    """Discover papers across roots (Zotero folder or PDF folder). Sync — pure
    filesystem + sqlite reads. Each item's source PDF path lives in
    ``raw['source_pdf']`` until staged."""
    items: list[PaperMetadata] = []
    for root in roots:
        if len(items) >= max_items:
            break
        zotero_db = detect_zotero(root)
        if zotero_db is not None:
            for meta in read_zotero_sqlite(root):
                items.append(meta)
                if len(items) >= max_items:
                    break
            continue
        # Plain PDF folder.
        for _r, pdf in iter_corpus_files([root], PDF_EXTENSIONS, recursive=True):
            meta = extract_pdf_metadata(pdf)
            meta.raw = {**meta.raw, "source_pdf": str(pdf)}
            items.append(meta)
            if len(items) >= max_items:
                break
    return items


def stage_pdf(workspace: Path, item: PaperMetadata) -> None:
    """Symlink an item's source PDF into ``workspace/literature/`` and set
    ``item.pdf_path`` to the workspace-relative path. Idempotent; best-effort."""
    source = (item.raw or {}).get("source_pdf")
    if not source:
        return
    src = Path(source)
    if not src.is_file():
        return
    lit_dir = Path(workspace) / "literature"
    lit_dir.mkdir(parents=True, exist_ok=True)
    target = lit_dir / src.name
    n = 2
    # Avoid clobbering a different file that happens to share a basename.
    while target.exists() and target.resolve() != src.resolve():
        target = lit_dir / f"{src.stem}_{n}{src.suffix}"
        n += 1
    try:
        if not target.exists():
            target.symlink_to(src.resolve())
        item.pdf_path = f"literature/{target.name}"
    except OSError as e:
        logger.debug("could not stage PDF %s: %s", src, e)


async def _enrich_one(item: PaperMetadata) -> PaperMetadata:
    """Fill missing authors/year/journal/abstract via DOI or title lookup.
    Never raises; returns the item (possibly unchanged)."""
    from . import crossref, openalex

    needs = not item.authors or not item.year or not item.journal
    if not needs:
        return item
    try:
        hit: PaperMetadata | None = None
        if item.doi:
            hit = await openalex.fetch_by_doi(item.doi) or await crossref.fetch_by_doi(item.doi)
        elif len(item.title) >= 12:
            res = await crossref.search_papers(item.title, limit=1)
            if res.papers:
                cand = res.papers[0]
                # Only trust the hit if the titles plausibly match.
                if _title_match(item.title, cand.title):
                    hit = cand
        if hit:
            item.authors = item.authors or hit.authors
            item.year = item.year or hit.year
            item.journal = item.journal or hit.journal
            item.abstract = item.abstract or hit.abstract
            item.doi = item.doi or hit.doi
            item.citations = item.citations or hit.citations
    except Exception as e:  # noqa: BLE001
        logger.debug("enrich failed for %r: %s", item.title[:60], e)
    return item


def _title_match(a: str, b: str) -> bool:
    def norm(s: str) -> set[str]:
        return {w for w in "".join(c if c.isalnum() else " " for c in s.lower()).split() if len(w) > 2}

    ta, tb = norm(a), norm(b)
    if not ta or not tb:
        return False
    overlap = len(ta & tb) / min(len(ta), len(tb))
    return overlap >= 0.6


async def ingest_literature(workspace: Path, paper_id: str, roots: list[Path], max_items: int, enrich: bool) -> int:
    """Full pipeline: discover → stage → enrich → persist. Returns count stored.
    Never raises."""
    from .storage import store_paper

    try:
        items = await asyncio.to_thread(discover_corpus, roots, max_items)
    except Exception as e:  # noqa: BLE001
        logger.warning("literature discovery failed: %s", e)
        return 0
    if not items:
        return 0

    for item in items:
        stage_pdf(workspace, item)

    if enrich:
        sem = asyncio.Semaphore(_ENRICH_CONCURRENCY)

        async def _bounded(it: PaperMetadata) -> PaperMetadata:
            async with sem:
                return await _enrich_one(it)

        items = list(await asyncio.gather(*(_bounded(it) for it in items)))

    stored = 0
    for item in items:
        try:
            await store_paper(item, paper_id)
            stored += 1
        except Exception as e:  # noqa: BLE001
            logger.debug("store_paper failed for %r: %s", item.title[:60], e)

    # Write literature.bib so the drafter's \cite{key} entries actually resolve
    # at compile time. save_bibtex (the SDK tool that normally builds this) is
    # ignored on the CLI backends, so without this refs.bib stays empty and every
    # citation is undefined. Keys match PaperMetadata.bibtex_key — the same key
    # surfaced to the drafter in _load_reference_summary.
    _write_literature_bib(workspace, items)

    logger.info("BYOD literature: discovered=%d stored=%d (paper %s)", len(items), stored, paper_id)
    return stored


def _write_literature_bib(workspace: Path, items: list[PaperMetadata]) -> None:
    """Write/merge the discovered library into workspace/literature.bib (deduped
    by bibtex key). Best-effort; assemble_refs_bib later merges it into refs.bib."""
    if not items:
        return
    try:
        entries: dict[str, str] = {}
        bib_path = Path(workspace) / "literature.bib"
        if bib_path.is_file():  # preserve anything a save_bibtex call already wrote
            for block in bib_path.read_text(encoding="utf-8").split("\n@"):
                block = block if block.startswith("@") else "@" + block
                if "{" in block and "," in block:
                    entries.setdefault(block.split("{", 1)[1].split(",", 1)[0].strip(), block.strip())
        for it in items:
            if it.title:
                entries[it.bibtex_key] = it.to_bibtex()
        bib_path.write_text("\n\n".join(entries.values()) + "\n", encoding="utf-8")
        logger.info("Wrote %d bib entries to %s", len(entries), bib_path.name)
    except OSError as e:
        logger.warning("could not write literature.bib: %s", e)
