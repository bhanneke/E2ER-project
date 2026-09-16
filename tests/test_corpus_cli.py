"""The commands, and the full-text waterfall underneath them.

Acquiring literature fails constantly and in boring ways — a paywall, a dead
link, a scanned image — so most of what matters here is that one bad paper does
not stop a refresh of a hundred. The tests are built around failures for that
reason.

PDFs are real files built for the test and read by the real pypdf path, not
mocked. Mocking both sides of an extraction seam is how this repo once produced
a green suite over a broken product.
"""

from __future__ import annotations

import json

import pytest

from src.cli_corpus import _ingest, _metadata_for, main
from src.modules.literature import corpus
from src.modules.literature.fulltext import (
    FullText,
    download_pdf_text,
    fetch_full_text,
    looks_like_pdf,
    read_pdf_file,
    resolve_oa_pdf,
)
from src.modules.literature.models import PaperMetadata
from src.modules.literature.review import Claim, Evidence, StructuredReview, stamp, verify_review

BODY = (
    "We find no detectable change in the equity loading of bitcoin following the listing. "
    "We estimate a difference-in-differences specification with asset and day fixed effects."
)
FINDING = "We find no detectable change in the equity loading of bitcoin"


def minimal_pdf(text: str) -> bytes:
    """A real, readable PDF. Small enough to build inline, real enough to parse."""
    lines = text.splitlines() or [""]
    parts = ["BT", "/F1 12 Tf", "72 720 Td", "14 TL"]
    for line in lines:
        escaped = line.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        parts += [f"({escaped}) Tj", "T*"]
    parts.append("ET")
    stream = "\n".join(parts).encode("latin-1")

    objs = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>",
        b"<</Length " + str(len(stream)).encode() + b">>stream\n" + stream + b"\nendstream",
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj".encode() + body + b"endobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(objs) + 1}\n".encode() + b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer<</Size {len(objs) + 1}/Root 1 0 R>>\nstartxref\n{xref_at}\n%%EOF\n".encode()
    return bytes(out)


@pytest.fixture
def db(tmp_path):
    with corpus.connect(tmp_path / "corpus.db") as conn:
        yield conn


@pytest.fixture
def pdf(tmp_path):
    p = tmp_path / "paper.pdf"
    p.write_bytes(minimal_pdf(BODY))
    return p


def _stored_review(doi: str = "10.1/a") -> StructuredReview:
    review = StructuredReview(
        title="Spot ETFs",
        doi=doi,
        year=2024,
        key_findings=[Claim(text="No change.", evidence=Evidence(quote=FINDING))],
    )
    stamp(review, source_text=BODY, model="m")
    verify_review(review, BODY)
    return review


# ---------------------------------------------------------------------------
# Full text: local, then URL, then the OA chain
# ---------------------------------------------------------------------------


def test_a_real_pdf_on_disk_is_read(pdf):
    result = read_pdf_file(pdf)

    assert result.ok
    assert "equity loading" in result.text
    assert result.origin == "local"


def test_a_missing_file_is_an_error_not_an_exception(tmp_path):
    result = read_pdf_file(tmp_path / "nope.pdf")
    assert not result.ok
    assert "no file at" in result.error


def test_a_pdf_with_no_text_layer_is_reported_as_such(tmp_path):
    """A scanned paper is the single most common unusable case."""
    p = tmp_path / "scan.pdf"
    p.write_bytes(minimal_pdf(""))

    result = read_pdf_file(p)
    assert not result.ok
    assert "no extractable text" in result.error


def test_a_file_that_is_not_a_pdf_does_not_crash(tmp_path):
    p = tmp_path / "not.pdf"
    p.write_text("this is plainly not a PDF")

    result = read_pdf_file(p)
    assert not result.ok
    assert result.error


async def test_an_html_landing_page_is_not_called_a_scanned_pdf(monkeypatch):
    """Found on the first real run against live OA resolvers.

    Resolvers routinely hand back a landing page or paywall interstitial at a
    URL ending in .pdf. Parsing it fails, and reporting that as "no extractable
    text (likely scanned)" is confidently wrong — it sends whoever reads it
    looking for an OCR problem that does not exist.
    """

    async def _html(url, headers=None, max_bytes=None):
        return b"<!DOCTYPE html>\n<html><body>Sign in to view this article</body></html>"

    monkeypatch.setattr("src.modules.fetch.http.fetch_bytes", _html)

    result = await download_pdf_text("https://example.org/article.pdf")

    assert not result.ok
    assert "HTML page" in result.error
    assert "scanned" not in result.error


async def test_an_api_error_payload_is_named_as_such(monkeypatch):
    async def _json(url, headers=None, max_bytes=None):
        return b'{"error": "not authorised"}'

    monkeypatch.setattr("src.modules.fetch.http.fetch_bytes", _json)

    result = await download_pdf_text("https://example.org/article.pdf")
    assert "JSON" in result.error


async def test_an_empty_response_is_named_as_such(monkeypatch):
    async def _empty(url, headers=None, max_bytes=None):
        return b""

    monkeypatch.setattr("src.modules.fetch.http.fetch_bytes", _empty)

    result = await download_pdf_text("https://example.org/article.pdf")
    assert "empty response" in result.error


def test_a_real_pdf_is_recognised_as_one(pdf):
    assert looks_like_pdf(pdf.read_bytes())
    assert not looks_like_pdf(b"<!DOCTYPE html>")


async def test_the_local_copy_is_preferred_over_the_network(pdf, monkeypatch):
    """Free, instant, and the copy the researcher actually has."""

    async def _never(*a, **k):
        raise AssertionError("must not download when a local copy reads")

    monkeypatch.setattr("src.modules.fetch.http.fetch_bytes", _never)

    meta = PaperMetadata(title="x", pdf_path=str(pdf), pdf_url="https://example.org/p.pdf", doi="10.1/a")
    result = await fetch_full_text(meta)

    assert result.ok
    assert result.origin == "local"


async def test_a_bad_local_path_falls_through_to_the_url(tmp_path, monkeypatch):
    async def _bytes(url, headers=None, max_bytes=None):
        return minimal_pdf(BODY)

    monkeypatch.setattr("src.modules.fetch.http.fetch_bytes", _bytes)

    meta = PaperMetadata(title="x", pdf_path=str(tmp_path / "gone.pdf"), pdf_url="https://example.org/p.pdf")
    result = await fetch_full_text(meta)

    assert result.ok
    assert result.origin == "pdf_url"


async def test_the_oa_chain_is_the_last_resort(monkeypatch):
    class Resolver:
        name = "unpaywall"

        async def resolve(self, doi):
            return "https://oa.example.org/p.pdf"

    async def _bytes(url, headers=None, max_bytes=None):
        return minimal_pdf(BODY)

    monkeypatch.setattr("src.modules.literature.registry.oa_pdf_resolvers", lambda s: [Resolver()])
    monkeypatch.setattr("src.modules.fetch.http.fetch_bytes", _bytes)

    result = await fetch_full_text(PaperMetadata(title="x", doi="10.1/a"))

    assert result.ok
    assert result.origin == "oa:unpaywall"


async def test_a_resolver_that_raises_does_not_end_the_chain(monkeypatch):
    """Resolvers are contractually forbidden from raising. They raise anyway."""

    class Broken:
        name = "broken"

        async def resolve(self, doi):
            raise RuntimeError("provider down")

    class Works:
        name = "works"

        async def resolve(self, doi):
            return "https://oa.example.org/p.pdf"

    monkeypatch.setattr("src.modules.literature.registry.oa_pdf_resolvers", lambda s: [Broken(), Works()])

    assert await resolve_oa_pdf("10.1/a") == ("https://oa.example.org/p.pdf", "works")


async def test_nothing_anywhere_is_an_error_not_an_exception():
    result = await fetch_full_text(PaperMetadata(title="x"))
    assert not result.ok
    assert "no open-access full text" in result.error


async def test_a_failed_download_is_reported(monkeypatch):
    async def _boom(url, headers=None, max_bytes=None):
        raise OSError("connection reset by peer")

    monkeypatch.setattr("src.modules.fetch.http.fetch_bytes", _boom)

    result = await download_pdf_text("https://example.org/p.pdf")
    assert not result.ok
    assert "connection reset" in result.error


# ---------------------------------------------------------------------------
# Routing a target to papers
# ---------------------------------------------------------------------------


async def test_a_pdf_path_becomes_one_local_paper(pdf):
    papers = await _metadata_for(str(pdf), limit=10, search=False)

    assert len(papers) == 1
    assert papers[0].source == "local_pdf"
    assert papers[0].pdf_path == str(pdf)


async def test_a_doi_is_fetched_rather_than_searched(monkeypatch):
    class Source:
        name = "openalex"

        async def fetch(self, doi):
            assert doi == "10.1234/abc", "the DOI must be normalised before lookup"
            return PaperMetadata(title="Found", doi=doi)

        async def search(self, q, limit):
            raise AssertionError("a DOI must not go to search")

    monkeypatch.setattr("src.modules.literature.registry.doi_fetch_sources", lambda s: [Source()])

    papers = await _metadata_for("https://doi.org/10.1234/ABC", limit=10, search=False)
    assert [p.title for p in papers] == ["Found"]


async def test_search_deduplicates_across_providers(monkeypatch):
    from src.modules.literature.models import SearchResult

    class A:
        name = "a"

        async def search(self, q, limit):
            return SearchResult(papers=[PaperMetadata(title="One", doi="10.1/x")], source="a", query=q)

    class B:
        name = "b"

        async def search(self, q, limit):
            return SearchResult(
                papers=[
                    PaperMetadata(title="One again", doi="10.1/X"),
                    PaperMetadata(title="Two", doi="10.1/y"),
                ],
                source="b",
                query=q,
            )

    monkeypatch.setattr("src.modules.literature.registry.search_sources", lambda s: [A(), B()])

    papers = await _metadata_for("query", limit=10, search=True)
    assert [p.doi for p in papers] == ["10.1/x", "10.1/y"]


async def test_every_provider_is_consulted_not_just_the_first(monkeypatch):
    """Found on a real run: four OpenAlex hits filled the limit, all of them
    landing pages, and arXiv — which serves actual PDFs — was never reached."""
    from src.modules.literature.models import SearchResult

    class Landing:
        name = "openalex"

        async def search(self, q, limit):
            return SearchResult(
                papers=[PaperMetadata(title=f"Paywalled {i}", doi=f"10.1/p{i}") for i in range(4)],
                source="openalex",
                query=q,
            )

    class Readable:
        name = "arxiv"

        async def search(self, q, limit):
            return SearchResult(
                papers=[PaperMetadata(title="Preprint", pdf_url="https://arxiv.org/pdf/2401.00001")],
                source="arxiv",
                query=q,
            )

    monkeypatch.setattr("src.modules.literature.registry.search_sources", lambda s: [Landing(), Readable()])

    papers = await _metadata_for("query", limit=4, search=True)

    titles = [p.title for p in papers]
    assert "Preprint" in titles, "the readable source must be reached"
    # Round-robin: each source's top hit before either source's second.
    assert titles[:2] == ["Paywalled 0", "Preprint"]


async def test_one_prolific_source_cannot_take_the_whole_budget(monkeypatch):
    from src.modules.literature.models import SearchResult

    def _source(name: str, n: int):
        class S:
            async def search(self, q, limit):
                return SearchResult(
                    papers=[PaperMetadata(title=f"{name}-{i}", doi=f"10.1/{name}{i}") for i in range(n)],
                    source=name,
                    query=q,
                )

        S.name = name
        return S()

    monkeypatch.setattr(
        "src.modules.literature.registry.search_sources", lambda s: [_source("big", 20), _source("small", 2)]
    )

    papers = await _metadata_for("query", limit=6, search=True)
    names = [p.title for p in papers]

    assert "small-0" in names and "small-1" in names, "the smaller source must still be represented"
    assert len(papers) == 6


async def test_a_provider_that_raises_does_not_stop_the_search(monkeypatch):
    from src.modules.literature.models import SearchResult

    class Broken:
        name = "broken"

        async def search(self, q, limit):
            raise RuntimeError("429 rate limited")

    class Works:
        name = "works"

        async def search(self, q, limit):
            return SearchResult(papers=[PaperMetadata(title="One", doi="10.1/x")], source="w", query=q)

    monkeypatch.setattr("src.modules.literature.registry.search_sources", lambda s: [Broken(), Works()])

    papers = await _metadata_for("query", limit=10, search=True)
    assert [p.title for p in papers] == ["One"]


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------


def _patch_pipeline(monkeypatch, *, text: FullText | None = None, review=None, error: str = ""):
    """Stub the two expensive steps: acquiring text and calling a model."""
    from src.modules.literature.extract import ExtractionAttempt, ExtractionResult

    async def _text(meta, **kw):
        return text if text is not None else FullText(text=BODY, origin="local")

    async def _extract(src, meta, backend, **kw):
        out = ExtractionResult(review=review if review is not None else _stored_review(meta.doi or "10.1/a"))
        out.error = error
        out.attempts = [ExtractionAttempt(index=0, parsed=True, proposed=2, verified=1, rejected=1)]
        out.verification = verify_review(out.review, BODY)
        return out

    monkeypatch.setattr("src.modules.literature.fulltext.fetch_full_text", _text)
    monkeypatch.setattr("src.modules.literature.extract.extract_review", _extract)
    monkeypatch.setattr("src.modules.llm.registry.get_backend", lambda s, name=None: object())


async def test_the_extracting_model_is_recorded(db, monkeypatch):
    """A corpus that records "unknown" cannot report a fabrication rate.

    Found on a real run: the model field resolved to an attribute that does not
    exist on Settings, so every paper was stored as extracted by "unknown" —
    which quietly destroys the one measurement this is all for.
    """
    seen: dict[str, str] = {}

    async def _extract(src, meta, backend, **kw):
        seen["model"] = kw.get("model", "")
        return await _fake_extraction(meta)

    _patch_pipeline(monkeypatch)
    monkeypatch.setattr("src.modules.literature.extract.extract_review", _extract)

    await _ingest(db, [PaperMetadata(title="P", doi="10.1/a")], model="", skip_known=True, verbose=False)

    assert seen["model"], "an empty model label means the corpus cannot attribute anything"
    assert seen["model"] != "unknown"


async def _fake_extraction(meta):
    from src.modules.literature.extract import ExtractionAttempt, ExtractionResult

    out = ExtractionResult(review=_stored_review(meta.doi or "10.1/a"))
    out.attempts = [ExtractionAttempt(index=0, parsed=True, proposed=1, verified=1, rejected=0)]
    out.verification = verify_review(out.review, BODY)
    return out


async def test_ingest_stores_a_verified_review(db, monkeypatch):
    _patch_pipeline(monkeypatch)

    report = await _ingest(db, [PaperMetadata(title="P", doi="10.1/a")], model="m", skip_known=True, verbose=False)

    assert report["stored"] == 1
    assert corpus.stats(db).papers == 1
    assert corpus.search_claims(db, "equity loading")


async def test_a_known_paper_is_skipped_before_any_model_is_called(db, monkeypatch):
    """What makes `refresh` affordable: the skip happens before the spend."""
    corpus.add_review(db, _stored_review("10.1/a"))

    async def _never_extract(*a, **k):
        raise AssertionError("must not call the model for a paper already covered")

    async def _never_fetch(*a, **k):
        raise AssertionError("must not download a paper already covered")

    monkeypatch.setattr("src.modules.literature.extract.extract_review", _never_extract)
    monkeypatch.setattr("src.modules.literature.fulltext.fetch_full_text", _never_fetch)
    monkeypatch.setattr("src.modules.llm.registry.get_backend", lambda s, name=None: object())

    report = await _ingest(db, [PaperMetadata(title="P", doi="10.1/a")], model="m", skip_known=True, verbose=False)

    assert report["skipped"] == 1
    assert report["stored"] == 0


async def test_force_re_extracts_a_known_paper(db, monkeypatch):
    corpus.add_review(db, _stored_review("10.1/a"))
    _patch_pipeline(monkeypatch)

    report = await _ingest(db, [PaperMetadata(title="P", doi="10.1/a")], model="m", skip_known=False, verbose=False)

    assert report["stored"] == 1
    assert corpus.stats(db).papers == 1, "re-extraction replaces rather than duplicates"


async def test_a_paper_with_no_full_text_is_recorded_and_the_run_continues(db, monkeypatch):
    calls = {"n": 0}

    async def _text(meta, **kw):
        calls["n"] += 1
        if meta.doi == "10.1/paywalled":
            return FullText(error="no open-access full text found")
        return FullText(text=BODY, origin="local")

    _patch_pipeline(monkeypatch)
    monkeypatch.setattr("src.modules.literature.fulltext.fetch_full_text", _text)

    report = await _ingest(
        db,
        [
            PaperMetadata(title="Paywalled", doi="10.1/paywalled"),
            PaperMetadata(title="Open", doi="10.1/open"),
        ],
        model="m",
        skip_known=True,
        verbose=False,
    )

    assert calls["n"] == 2, "the second paper must still be attempted"
    assert report["no_text"] == 1
    assert report["stored"] == 1
    assert report["failures"][0]["stage"] == "fulltext"


async def test_a_paper_whose_claims_all_fail_is_not_stored(db, monkeypatch):
    """Nothing checkable is not a paper worth keeping, and says so."""
    empty = StructuredReview(title="P", doi="10.1/a")
    stamp(empty, source_text=BODY, model="m")
    _patch_pipeline(monkeypatch, review=empty)

    report = await _ingest(db, [PaperMetadata(title="P", doi="10.1/a")], model="m", skip_known=True, verbose=False)

    assert report["no_claims"] == 1
    assert report["stored"] == 0
    assert corpus.stats(db).papers == 0


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def test_topics_round_trip(tmp_path, capsys):
    db = str(tmp_path / "c.db")

    assert main(["--db", db, "topics", "add", "crypto ETF"]) == 0
    assert main(["--db", db, "topics", "list"]) == 0
    assert "crypto ETF" in capsys.readouterr().out
    assert main(["--db", db, "topics", "remove", "crypto ETF"]) == 0
    assert main(["--db", db, "topics", "remove", "crypto ETF"]) == 1


def test_refresh_without_topics_says_what_to_do(tmp_path, capsys):
    assert main(["--db", str(tmp_path / "c.db"), "refresh"]) == 1
    assert "topics add" in capsys.readouterr().err


def test_search_on_an_empty_corpus_exits_nonzero(tmp_path, capsys):
    assert main(["--db", str(tmp_path / "c.db"), "search", "anything"]) == 1
    assert "No claims match" in capsys.readouterr().out


def test_search_prints_the_quote(tmp_path, capsys):
    db = str(tmp_path / "c.db")
    with corpus.connect(db) as conn:
        corpus.add_review(conn, _stored_review())

    assert main(["--db", db, "search", "equity loading"]) == 0
    out = capsys.readouterr().out
    assert FINDING in out
    assert "key_findings" in out


def test_search_json_is_machine_readable(tmp_path, capsys):
    db = str(tmp_path / "c.db")
    with corpus.connect(db) as conn:
        corpus.add_review(conn, _stored_review())

    main(["--db", db, "--json", "search", "equity loading"])
    payload = json.loads(capsys.readouterr().out)

    assert payload[0]["quote"] == FINDING
    assert payload[0]["field"] == "key_findings"


def test_stats_does_not_report_a_zero_fabrication_rate_for_no_data(tmp_path, capsys):
    db = str(tmp_path / "c.db")
    with corpus.connect(db) as conn:
        corpus.add_review(conn, _stored_review())

    main(["--db", db, "stats"])
    out = capsys.readouterr().out

    assert "nothing measured yet" in out
    assert "0.0%" not in out


def test_list_on_an_empty_corpus_tells_you_what_to_do(tmp_path, capsys):
    assert main(["--db", str(tmp_path / "c.db"), "list"]) == 0
    assert "corpus add" in capsys.readouterr().out


def test_export_writes_files(tmp_path):
    db = str(tmp_path / "c.db")
    with corpus.connect(db) as conn:
        corpus.add_review(conn, _stored_review())

    dest = tmp_path / "out"
    assert main(["--db", db, "export", str(dest)]) == 0
    assert json.loads((dest / "index.json").read_text())["papers"] == 1


def test_remove_accepts_a_bare_doi(tmp_path):
    db = str(tmp_path / "c.db")
    with corpus.connect(db) as conn:
        corpus.add_review(conn, _stored_review("10.1/a"))

    assert main(["--db", db, "remove", "10.1/a"]) == 0
    assert main(["--db", db, "remove", "10.1/a"]) == 1


def test_an_unknown_subcommand_exits_rather_than_traceback(tmp_path):
    with pytest.raises(SystemExit):
        main(["--db", str(tmp_path / "c.db"), "frobnicate"])
