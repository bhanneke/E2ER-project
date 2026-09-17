"""``e2er corpus`` — build and query a library of checked claims.

    e2er corpus add ~/papers/               every PDF in a folder
    e2er corpus add workspace/p1/literature/  a project's own staged papers
    e2er corpus add "10.1234/example"       one paper by DOI
    e2er corpus add paper.pdf               one paper from a local file
    e2er corpus add --search "crypto ETF"   the top hits for a query

    e2er corpus topics add "crypto ETF"     a standing interest
    e2er corpus refresh                     re-run every topic, extract what is new
    e2er corpus search "null effects"       search the claims
    e2er corpus stats                       size, coverage, and the fabrication rate
    e2er corpus export ./corpus-export      portable JSON

A folder is the path worth reaching for first. Papers you already have are
always readable; roughly two in five web hits sit behind a paywall or resolve to
a publisher landing page, so a corpus built only from the web is a corpus of
whatever happened to be open access.

``refresh`` is the command the whole thing is for: it is incremental and
idempotent, so running it weekly accumulates coverage instead of redoing work.
Papers already in the corpus are skipped before any model is called, which is
what keeps a metered backend affordable and a subscription backend fast.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

from .logging_config import get_logger
from .modules.literature import corpus
from .modules.literature.models import PaperMetadata

logger = get_logger(__name__)

#: How many search hits a single `add --search` or `refresh` considers per
#: topic. Deliberately modest: each one is a download and a model call.
DEFAULT_LIMIT = 10


# ── output helpers ───────────────────────────────────────────────────────────


def _out(payload: Any, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value:.1%}"


# ── acquisition ──────────────────────────────────────────────────────────────


def _paper_from_pdf(path: Path) -> PaperMetadata:
    """Read a local PDF's own metadata rather than guessing from its filename.

    `extract_pdf_metadata` pulls title, authors, DOI and year out of the
    document — from DocInfo, falling back to the first page. Using `path.stem`
    instead, as this did, meant a paper was titled "1-s2.0-S0378426619301..."
    with no DOI and no authors: unciteable, and impossible to deduplicate
    against the same paper arriving from the web.
    """
    from .modules.literature.local_pdf_meta import extract_pdf_metadata

    meta = extract_pdf_metadata(path)
    meta.pdf_path = str(path)
    meta.source = meta.source or "byod_pdf"
    return meta


def _papers_from_folder(folder: Path, *, recursive: bool) -> list[PaperMetadata]:
    """Every PDF in a folder, with its own metadata."""
    from .modules.local_corpus import PDF_EXTENSIONS, iter_corpus_files

    papers = [_paper_from_pdf(pdf) for _root, pdf in iter_corpus_files([folder], PDF_EXTENSIONS, recursive=recursive)]
    logger.info("corpus: %d PDF(s) found under %s", len(papers), folder)
    return papers


async def _metadata_for(target: str, *, limit: int | None, search: bool) -> list[PaperMetadata]:
    """Turn a DOI, a file path, or a query into papers to extract from."""
    from .config import get_settings
    from .modules.literature.registry import doi_fetch_sources, search_sources

    settings = get_settings()

    path = Path(target).expanduser()

    # A folder of PDFs — the researcher's own library, or a paper's staged
    # `literature/` folder. This is the primary case, not a convenience: papers
    # you already have are always readable, whereas roughly two in five web hits
    # are behind a paywall or resolve to a landing page.
    if path.is_dir():
        # No default cap here. Truncating a folder to ten would silently ignore
        # most of a researcher's library and look like the tool losing papers;
        # an explicit --limit still applies, for trying a big folder out first.
        in_folder = _papers_from_folder(path, recursive=True)
        return in_folder[:limit] if limit else in_folder

    if path.is_file() and path.suffix.lower() == ".pdf":
        return [_paper_from_pdf(path)]

    if not search and ("/" in target and target.lower().startswith(("10.", "doi:", "http"))):
        doi = corpus.normalize_doi(target)
        for source in doi_fetch_sources(settings):
            try:
                found = await source.fetch(doi)
            except Exception as e:
                logger.debug("DOI fetch via %s failed: %s", getattr(source, "name", source), e)
                continue
            if found is not None:
                return [found]
        return []

    # Ask every source, then interleave round-robin so each one contributes to
    # the limit.
    #
    # Taking the first provider's hits until the limit fills sounds reasonable
    # and is not: on a real run, five OpenAlex records filled it, every one of
    # their "open access" URLs was a publisher landing page, and arXiv — which
    # serves actual PDFs — was never reached. Zero papers stored from a query
    # with plenty of readable matches.
    #
    # Ranking by "has a pdf_url" does not fix it either, because the landing
    # pages have one too. Interleaving is provider-agnostic: it preserves each
    # source's own ordering and only refuses to let one of them monopolise the
    # budget.
    # A web search is unbounded, so it always needs a cap.
    capped = limit or DEFAULT_LIMIT
    per_source: list[list[PaperMetadata]] = []
    for source in search_sources(settings):
        try:
            result = await source.search(target, capped)
        except Exception as e:
            logger.warning("literature search via %s failed: %s", getattr(source, "name", source), e)
            continue
        per_source.append(list(result.papers))

    papers: list[PaperMetadata] = []
    seen: set[str] = set()
    for rank in range(capped):
        for bucket in per_source:
            if rank >= len(bucket):
                continue
            paper = bucket[rank]
            ident = corpus.normalize_doi(paper.doi) or paper.title.lower()
            if not ident or ident in seen:
                continue
            seen.add(ident)
            papers.append(paper)
    return papers[:capped]


async def _ingest(
    conn: sqlite3.Connection,
    papers: list[PaperMetadata],
    *,
    model: str,
    skip_known: bool,
    verbose: bool,
) -> dict[str, Any]:
    """Acquire, extract, verify and store. Never raises on one bad paper."""
    from .config import get_settings
    from .modules.literature.extract import extract_review
    from .modules.literature.fulltext import fetch_full_text
    from .modules.llm.registry import get_backend

    settings = get_settings()
    backend = get_backend(settings)
    # Which model produced the claims is not decoration: the fabrication rate is
    # a property of a model, and a corpus that records "unknown" cannot report
    # one. default_model_for resolves against the backend actually in use, which
    # is the same reason the run matrix uses it.
    resolved_model = model or settings.default_model_for(settings.llm_backend) or settings.llm_backend

    report: dict[str, Any] = {"considered": len(papers), "skipped": 0, "no_text": 0, "no_claims": 0, "stored": 0}
    stored_keys: list[str] = []
    failures: list[dict[str, str]] = []

    for paper in papers:
        label = (paper.title or paper.doi or "untitled")[:70]

        if skip_known and corpus.is_covered(conn, doi=paper.doi, title=paper.title, year=paper.year):
            report["skipped"] += 1
            if verbose:
                print(f"  skip   {label}  (already covered)")
            continue

        text = await fetch_full_text(paper)
        if not text.ok:
            report["no_text"] += 1
            failures.append({"paper": label, "stage": "fulltext", "error": text.error})
            if verbose:
                print(f"  ✗      {label}\n         no full text: {text.error}")
            continue

        result = await extract_review(text.text, paper, backend, model=resolved_model)
        if not result.ok:
            report["no_claims"] += 1
            failures.append({"paper": label, "stage": "extract", "error": result.error or "no claims survived"})
            if verbose:
                reason = result.error or f"0 of {result.proposed} claims verified"
                print(f"  ✗      {label}\n         {reason}")
            continue

        result.review.access_license = paper.raw.get("license", "") if isinstance(paper.raw, dict) else ""
        outcome = corpus.add_review(conn, result.review, extraction=result.to_dict())
        stored_keys.append(outcome.key)
        report["stored"] += 1
        if verbose:
            rate = _pct(result.first_pass_rejection_rate)
            verb = "update" if outcome.replaced else "add"
            print(f"  {verb:<6} {label}")
            print(
                f"         {outcome.claims} claims kept, {result.dropped} dropped "
                f"({rate} of first-pass rejected) [{text.origin}]"
            )

    report["keys"] = stored_keys
    report["failures"] = failures
    return report


# ── commands ─────────────────────────────────────────────────────────────────


def _cmd_add(args: argparse.Namespace) -> int:
    with corpus.connect(args.db) as conn:
        papers = asyncio.run(_metadata_for(args.target, limit=args.limit, search=args.search))
        if not papers:
            print(f"Nothing found for {args.target!r}.", file=sys.stderr)
            return 1
        if not args.json:
            print(f"{len(papers)} paper(s) to consider.")
        report = asyncio.run(_ingest(conn, papers, model=args.model, skip_known=not args.force, verbose=not args.json))

    _out(report, as_json=args.json)
    if not args.json:
        print(
            f"\nstored {report['stored']}, skipped {report['skipped']} already covered, "
            f"{report['no_text']} without full text, {report['no_claims']} with nothing checkable."
        )
    return 0 if report["stored"] or report["skipped"] else 1


def _cmd_refresh(args: argparse.Namespace) -> int:
    with corpus.connect(args.db) as conn:
        topics = corpus.list_topics(conn)
        if not topics:
            print('No topics registered. Add one with:\n  e2er corpus topics add "your query"', file=sys.stderr)
            return 1

        totals = {"considered": 0, "skipped": 0, "no_text": 0, "no_claims": 0, "stored": 0}
        per_topic: list[dict[str, Any]] = []

        for topic in topics:
            if not args.json:
                print(f"\n{topic.query}")
            papers = asyncio.run(_metadata_for(topic.query, limit=args.limit, search=True))
            report = asyncio.run(_ingest(conn, papers, model=args.model, skip_known=True, verbose=not args.json))
            corpus.record_topic_run(conn, topic.query, found=len(papers), added=report["stored"])
            for k in totals:
                totals[k] += report[k]
            per_topic.append({"topic": topic.query, **{k: report[k] for k in totals}})

    _out({"topics": per_topic, "totals": totals}, as_json=args.json)
    if not args.json:
        print(
            f"\n{len(topics)} topic(s): {totals['stored']} new, {totals['skipped']} already covered, "
            f"{totals['no_text']} without full text."
        )
    return 0


def _cmd_search(args: argparse.Namespace) -> int:
    with corpus.connect(args.db) as conn:
        hits = corpus.search_claims(conn, args.query, limit=args.limit, fields=args.field or None)

    if args.json:
        _out([h.to_dict() for h in hits], as_json=True)
        return 0 if hits else 1

    if not hits:
        print(f"No claims match {args.query!r}.")
        return 1

    for hit in hits:
        print(f"\n{hit.cite()}")
        print(f"  [{hit.field}] {hit.text}")
        print(f'  "{hit.quote}"')
        if hit.locator:
            print(f"  — {hit.locator}")
        if hit.doi:
            print(f"  {hit.doi}")
    print(f"\n{len(hits)} claim(s).")
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    with corpus.connect(args.db) as conn:
        rows = corpus.list_papers(conn, limit=args.limit)

    if args.json:
        _out([r.to_dict() for r in rows], as_json=True)
        return 0
    if not rows:
        print("The corpus is empty. Add a paper with:\n  e2er corpus add <doi|file.pdf>")
        return 0
    for r in rows:
        year = r.year or "n.d."
        print(f"{r.n_claims:>3} claims  {year}  {r.title[:70]}")
        if r.doi:
            print(f"            {r.doi}")
    print(f"\n{len(rows)} paper(s).")
    return 0


def _cmd_stats(args: argparse.Namespace) -> int:
    with corpus.connect(args.db) as conn:
        s = corpus.stats(conn)
        path = corpus.corpus_path(args.db)

    if args.json:
        _out({**s.to_dict(), "path": str(path)}, as_json=True)
        return 0

    print(f"{path}\n")
    print(f"  papers   {s.papers}")
    print(f"  claims   {s.claims}")
    print(f"  topics   {s.topics}")
    if s.claims_by_field:
        print("\n  claims by field")
        for fname, n in s.claims_by_field.items():
            print(f"    {fname:<24} {n}")
    if s.models:
        print("\n  extracted by")
        for m, n in s.models.items():
            print(f"    {m:<24} {n} paper(s)")

    print("\n  extraction")
    if not s.extractions_measured:
        # Not zero. A corpus imported from elsewhere has no measurement, and
        # printing 0.0% would assert the model never fabricated.
        print("    nothing measured yet")
    else:
        print(f"    first-pass claims proposed  {s.first_pass_proposed}")
        print(f"    rejected (quote not found)  {s.first_pass_rejected}")
        print(f"    fabrication rate            {_pct(s.first_pass_rejection_rate)}")
        by_field = s.rejection_rate_by_field()
        if by_field:
            print("\n    rejection rate by field")
            for fname, rate in by_field.items():
                print(f"      {fname:<22} {_pct(rate)}")
        if s.rejections_by_reason:
            print("\n    why claims were rejected")
            for reason, n in sorted(s.rejections_by_reason.items(), key=lambda kv: -kv[1]):
                print(f"      {reason:<22} {n}")
    return 0


def _cmd_topics(args: argparse.Namespace) -> int:
    with corpus.connect(args.db) as conn:
        if args.topic_action == "add":
            added = corpus.add_topic(conn, args.query)
            print(f"{'Registered' if added else 'Already registered'}: {args.query}")
            return 0
        if args.topic_action == "remove":
            removed = corpus.remove_topic(conn, args.query)
            print(f"{'Removed' if removed else 'No such topic'}: {args.query}")
            return 0 if removed else 1

        topics = corpus.list_topics(conn)

    if args.json:
        _out([t.to_dict() for t in topics], as_json=True)
        return 0
    if not topics:
        print('No topics. Add one with:\n  e2er corpus topics add "your query"')
        return 0
    for t in topics:
        when = t.last_run_at or "never"
        print(f"{t.query}\n    last run {when} · {t.n_found} found · {t.n_added} added")
    return 0


def _cmd_export(args: argparse.Namespace) -> int:
    with corpus.connect(args.db) as conn:
        written = corpus.export_corpus(conn, Path(args.dest))
    _out({"papers": written, "dest": args.dest}, as_json=args.json)
    if not args.json:
        print(f"Wrote {written} review(s) to {args.dest}/")
    return 0


def _cmd_remove(args: argparse.Namespace) -> int:
    with corpus.connect(args.db) as conn:
        key = args.key if ":" in args.key else f"doi:{corpus.normalize_doi(args.key)}"
        removed = corpus.remove_paper(conn, key)
    print(f"{'Removed' if removed else 'Not found'}: {key}")
    return 0 if removed else 1


# ── parser ───────────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="e2er corpus",
        description="A local library of paper claims, each checked against the paper it came from.",
    )
    p.add_argument("--db", default=None, help="Corpus file (default: CORPUS_DB, else ~/.e2er/corpus.db)")
    p.add_argument("--json", action="store_true", help="Machine-readable output")
    sub = p.add_subparsers(dest="action", required=True)

    add = sub.add_parser("add", help="Add papers by DOI, local PDF, or search query")
    add.add_argument("target", help="A DOI, a path to a PDF, or a search query with --search")
    add.add_argument("--search", action="store_true", help="Treat the target as a search query")
    add.add_argument(
        "--limit",
        type=int,
        default=None,
        help=f"Cap papers considered (default: {DEFAULT_LIMIT} for a search, no cap for a folder)",
    )
    add.add_argument("--model", default="", help="Record which model extracted (default: configured model)")
    add.add_argument("--force", action="store_true", help="Re-extract papers already in the corpus")
    add.set_defaults(func=_cmd_add)

    refresh = sub.add_parser("refresh", help="Re-run every topic and extract what is new")
    refresh.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="Hits to consider per topic")
    refresh.add_argument("--model", default="")
    refresh.set_defaults(func=_cmd_refresh)

    search = sub.add_parser("search", help="Search the claims")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=20)
    search.add_argument(
        "--field",
        action="append",
        help="Restrict to a review field (repeatable): key_findings, limitations, methodology, ...",
    )
    search.set_defaults(func=_cmd_search)

    listing = sub.add_parser("list", help="List the papers in the corpus")
    listing.add_argument("--limit", type=int, default=50)
    listing.set_defaults(func=_cmd_list)

    stats_p = sub.add_parser("stats", help="Size, coverage, and the measured fabrication rate")
    stats_p.set_defaults(func=_cmd_stats)

    topics = sub.add_parser("topics", help="Standing interests that `refresh` re-runs")
    tsub = topics.add_subparsers(dest="topic_action")
    tadd = tsub.add_parser("add")
    tadd.add_argument("query")
    trm = tsub.add_parser("remove")
    trm.add_argument("query")
    tsub.add_parser("list")
    topics.set_defaults(func=_cmd_topics, topic_action=None)

    export = sub.add_parser("export", help="Write every review as portable JSON")
    export.add_argument("dest")
    export.set_defaults(func=_cmd_export)

    remove = sub.add_parser("remove", help="Remove one paper and its claims")
    remove.add_argument("key", help="A corpus key (doi:10.…) or a bare DOI")
    remove.set_defaults(func=_cmd_remove)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result: int = args.func(args)
        return result
    except corpus.CorpusError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
