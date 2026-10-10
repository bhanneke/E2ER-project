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
import math
import re
from pathlib import Path

from ...config import Settings
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
            from ..local_corpus import link_or_copy

            link_or_copy(src, target)
        item.pdf_path = f"literature/{target.name}"
    except OSError as e:
        logger.debug("could not stage PDF %s: %s", src, e)


async def _enrich_one(item: PaperMetadata) -> PaperMetadata:
    """Complete a paper's authors/year/journal/abstract from CrossRef/OpenAlex.
    Never raises; returns the item (possibly unchanged).

    A PDF's own metadata is often wrong rather than missing (the 2026-10-10 live
    run: "Federal Reserve Board" as the author, 1936 as the year, read from the
    first page of a Fed working paper). So when the PDF names its DOI and the
    record found by that DOI has the same title, the record's authors, year,
    title and journal replace the PDF's; otherwise only missing fields are filled.
    """
    from . import crossref, openalex

    needs = not item.authors or not item.year or not item.journal
    if not needs and not item.doi:
        return item
    try:
        hit: PaperMetadata | None = None
        by_doi = False
        if item.doi:
            hit = await openalex.fetch_by_doi(item.doi) or await crossref.fetch_by_doi(item.doi)
            by_doi = hit is not None
        elif len(item.title) >= 12:
            res = await crossref.search_papers(item.title, limit=1)
            if res.papers:
                cand = res.papers[0]
                # Only trust the hit if the titles plausibly match.
                if _title_match(item.title, cand.title):
                    hit = cand
        if hit and by_doi and item.source == "byod_pdf" and hit.title and _title_match(item.title, hit.title):
            item.title = hit.title
            item.authors = hit.authors or item.authors
            item.year = hit.year or item.year
            item.journal = hit.journal or item.journal
            item.abstract = item.abstract or hit.abstract
            item.citations = item.citations or hit.citations
        elif hit:
            if not by_doi and item.source == "byod_pdf" and hit.title:
                # A title matched by search is the record's clean title (not "Munich Personal RePEc Archive …").
                item.title = hit.title
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


def _write_literature_bib(workspace: Path, items: list[PaperMetadata], *, keep_existing: bool = False) -> None:
    """Write/merge the discovered library into workspace/literature.bib (deduped
    by bibtex key). Best-effort; assemble_refs_bib later merges it into refs.bib.

    ``keep_existing``: an entry already in the file wins over a new one with the
    same key (the web search never replaces one of the researcher's papers)."""
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
            if it.title and not (keep_existing and it.bibtex_key in entries):
                entries[it.bibtex_key] = it.to_bibtex()
        bib_path.write_text("\n\n".join(entries.values()) + "\n", encoding="utf-8")
        logger.info("Wrote %d bib entries to %s", len(entries), bib_path.name)
    except OSError as e:
        logger.warning("could not write literature.bib: %s", e)


_BIB_ENTRY_RE = re.compile(r"^@\w+\s*\{\s*[^,\s]+", re.MULTILINE)


def bib_entry_count(workspace: Path) -> int:
    """How many entries ``workspace/literature.bib`` already holds (0 if absent)."""
    path = Path(workspace) / "literature.bib"
    if not path.is_file():
        return 0
    try:
        return len(_BIB_ENTRY_RE.findall(path.read_text(encoding="utf-8", errors="replace")))
    except OSError:
        return 0


# ── which web hits belong to the question ───────────────────────────────────

#: Where the study records what the web search kept and left out (shown on the run page).
WEB_SEARCH_FILE = "web_search.json"

#: Words that say nothing about a question's topic: function words, and the words every research
#: question uses ("how", "effect", "changes", "compared", "since").
_STOP_WORDS = frozenset(
    """a about after against all also among an and any are as at be been before between both but by can could
    did do does during each either for from had has have how however if in into is it its many may more most much
    not of on or our over same should since so some such than that the their them then there these they this those
    to under until upon us was we were what when where whether which while who whom why will with within
    without would year years new study studies effect effects evidence analysis data using use used based approach
    change changes changed compared compare earlier later fully full ran role impact case paper research question
    questions""".split()
)
#: How many of the question's words a hit must share, as a share of them, with a floor and a cap.
#: With an abstract: a quarter of the question's words, at least 2 and at most 4. Title only (some
#: records have no abstract): a fifth, at least 2 and at most 3.
RELEVANCE_SHARE_ABSTRACT, RELEVANCE_SHARE_TITLE = 0.25, 0.20
RELEVANCE_FLOOR, RELEVANCE_CAP_ABSTRACT, RELEVANCE_CAP_TITLE = 2, 4, 3


def _stem(word: str) -> str:
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def question_terms(text: str) -> frozenset[str]:
    """The content words of a text: lower case, 3 letters or more, no numbers, no stop words, plurals as singular."""
    words = re.findall(r"[a-z][a-z0-9]+", (text or "").lower())
    return frozenset(_stem(w) for w in words if len(w) >= 3 and w not in _STOP_WORDS)


def is_relevant(paper: PaperMetadata, question: frozenset[str]) -> bool:
    """Does a web hit belong to the question? It must share enough of the question's content words.

    Deterministic, no model call. The 2026-10-10 live run (a question on the pass-through of the federal
    funds rate to mortgage rates) put 53 web hits into the bibliography, among them solar asset-backed
    bonds, the federal budget and teen birth rates: the search engines match single words of a long
    question. The rule (see RELEVANCE_*): with an abstract, the title and abstract together share at
    least a quarter of the question's content words (2 to 4); without one, the title shares a fifth (2 to 3).
    A question with no content words keeps every hit.
    """
    if not question:
        return True
    have_abstract = bool((paper.abstract or "").strip())
    words = question_terms(f"{paper.title} {paper.abstract or ''}")
    share, cap = (
        (RELEVANCE_SHARE_ABSTRACT, RELEVANCE_CAP_ABSTRACT)
        if have_abstract
        else (RELEVANCE_SHARE_TITLE, RELEVANCE_CAP_TITLE)
    )
    # Never more words than the question has (a two-word question: both).
    need = min(len(question), cap, max(RELEVANCE_FLOOR, math.ceil(share * len(question))))
    return len(question & words) >= need


def _record_web_search(workspace: Path, question: frozenset[str], kept: int, left_out: list[str]) -> None:
    import json

    path = Path(workspace) / "literature" / WEB_SEARCH_FILE
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "rule": "a hit is kept when its title and abstract share enough of the question's content words "
                    "(src/modules/literature/discovery.py, is_relevant)",
                    "question_terms": sorted(question),
                    "kept": kept,
                    "left_out_count": len(left_out),
                    "left_out": left_out[:100],
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
    except OSError as e:
        logger.warning("could not record the web search: %s", e)


def _bib_marks(workspace: Path) -> set[str]:
    """DOIs and titles already in ``literature.bib``: a web hit for one of them is the same paper."""
    from ...core.pipeline.verify_citations import load_bib

    marks: set[str] = set()
    for fields in load_bib(Path(workspace) / "literature.bib").values():
        if fields.get("doi"):
            marks.add("doi:" + str(fields["doi"]).lower().strip())
        if fields.get("title"):
            marks.add("t:" + _norm_title(str(fields["title"])))
    return marks


def _norm_title(title: str) -> str:
    return " ".join("".join(c if c.isalnum() else " " for c in title.lower()).split())


def _same_paper(paper: PaperMetadata, marks: set[str]) -> bool:
    return bool(
        (paper.doi and "doi:" + paper.doi.lower().strip() in marks) or ("t:" + _norm_title(paper.title) in marks)
    )


async def acquire_literature(
    workspace: Path,
    paper_id: str,
    queries: list[str],
    settings: Settings,
    limit: int = 30,
    *,
    web_search: bool = True,
    chosen: list[PaperMetadata] | None = None,
) -> int:
    """Search the web providers for this paper's own research question and record
    the hits in ``literature.bib``. Returns the number of entries written.

    WHY THIS IS A STAGE AND NOT A TOOL

    E2ER v1 ran a literature agent as a mandatory pipeline step: it wrote
    ``bibliography.bib`` from the 100xOS pgvector knowledge base before the
    drafter started, and its papers still pass v3's own citation gate today
    (31/33 and 37/38 cites verified, zero missing_in_bib, measured 2026-09-04).

    v3 is standalone — no knowledge base, no ingested corpus — and replaced that
    step with LITERATURE_TOOLS, which ``tool_loop`` ignores on every CLI backend.
    Adding the ``e2er-lit`` bash bridge made the capability *reachable* and
    changed nothing: canary #7 was granted it, told about it in its skill file,
    and never called it. The drafter then cited 23 keys from memory against a
    ``references.bib`` that did not exist.

    So this does not ask. It runs before any specialist does, and the drafter
    finds a real bibliography already on disk — v1's arrangement, restored.

    Since 0.15.0 it runs in addition to the researcher's own papers (which
    ``study_inputs.prepare_papers`` wrote first): its entries are tagged
    ``e2er_source = {web}`` and shown as "found on the web", never mixed in
    silently, and none replaces one of the researcher's entries. The researcher
    turns it off with "Use only my papers" (``web_search=False``). When the
    researcher chose the study's papers (``chosen``), the Library's evidence is
    limited to those papers, with or without the web search.

    Best-effort: a failing provider is skipped, a failing store is logged, and a
    dead network costs the bibliography rather than the run. The caller wraps
    this as a backstop — a paper with no bibliography is a bad paper, but a
    crashed run is worse.
    """
    from . import corpus_context
    from .registry import search_sources
    from .storage import store_paper

    wanted = [q.strip() for q in queries if q and q.strip()]

    # Read this paper's own staged PDFs into the corpus first, so the evidence
    # gathered below can include them. These are the papers the researcher
    # actually supplied; going to the web for what is already on disk was the
    # wrong order.
    await corpus_context.ingest_staged_pdfs(workspace)

    # Then the corpus: offline, free, and already checked. Degrades to nothing
    # when no corpus has been built.
    evidence = corpus_context.gather(wanted)
    if chosen is not None:
        # The researcher chose this study's papers: the Library's other papers are not among them.
        # (The 2026-10-10 live run without this: a search of the whole Library for a mortgage question
        # brought 25 unrelated papers, NFT and stablecoin studies, into the bibliography as "your papers".)
        evidence = corpus_context.with_chosen(evidence, chosen, only=True)
    corpus_context.write_evidence(workspace, evidence)

    existing = bib_entry_count(workspace)
    if not web_search:
        # "Use only my papers": no request goes out; the Library's evidence (already limited to the
        # chosen papers above) may still seed the entries its claims come from.
        marks = _bib_marks(workspace) if existing else set()
        seeded = [p for p in evidence.as_metadata() if p.title and not _same_paper(p, marks)]
        if seeded:
            _write_literature_bib(workspace, seeded, keep_existing=True)
        logger.info("literature web search for %s is off (use only my papers); %d entries", paper_id, existing)
        return 0

    if not wanted:
        logger.warning("literature acquisition for %s got no query to search with", paper_id)
        return 0

    # LITERATURE_ACQUIRE_LIMIT=0 turns the web search off: no request goes out
    # (the offline corpus still seeds the bibliography).
    sources = search_sources(settings) if limit > 0 else []
    if limit <= 0:
        logger.info("literature web search for %s is off (LITERATURE_ACQUIRE_LIMIT=0)", paper_id)
    # Corpus papers seed the bibliography so the drafter can cite what the
    # evidence file quotes. Seeded first, so a web hit for the same paper does
    # not displace the entry whose claims are already on disk.
    found: dict[str, PaperMetadata] = {p.bibtex_key: p for p in evidence.as_metadata() if p.title}
    question = question_terms(" ".join(wanted))
    left_out: list[str] = []
    for query in wanted:
        for source in sources:
            try:
                result = await source.search(query, limit)
            except Exception as e:  # noqa: BLE001 — try the next source
                logger.info("%s search failed (%s) — trying next source", source.name, e)
                continue
            if result.papers:
                for paper in result.papers:
                    if not paper.title or paper.bibtex_key in found:
                        continue
                    if is_relevant(paper, question):
                        found[paper.bibtex_key] = paper
                    elif paper.title not in left_out:
                        left_out.append(paper.title)
                break
    if sources:
        _record_web_search(workspace, question, sum(1 for p in found.values() if p.origin == "web"), left_out)

    # The researcher's own papers are already in the file: a hit for one of them is not a second entry.
    marks = _bib_marks(workspace) if existing else set()
    found = {k: p for k, p in found.items() if not _same_paper(p, marks)}

    if not found:
        if not existing:
            logger.warning(
                "literature acquisition found nothing for %s (%d query/queries, %d source(s)) — "
                "the drafter will have no bibliography and every cite will report missing_in_bib",
                paper_id,
                len(wanted),
                len(sources),
            )
        return 0

    items = list(found.values())
    _write_literature_bib(workspace, items, keep_existing=True)

    # Parity with the BYOD path: persist so search_papers can serve these
    # offline. Per-item best-effort — a storage failure must not cost the bib.
    for item in items:
        try:
            await store_paper(item, paper_id)
        except Exception as e:  # noqa: BLE001
            logger.debug("store_paper failed for %r: %s", item.title[:60], e)

    logger.info("literature acquisition: %d entries written for %s", len(items), paper_id)
    return len(items)
