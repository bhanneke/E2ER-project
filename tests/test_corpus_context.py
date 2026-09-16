"""The pipeline reading the corpus.

Two things have to hold. When a corpus exists, its verified claims reach the
drafter and its papers reach the bibliography, so a cite has something behind
it. When one does not — the normal case for a first-time user — nothing changes
at all, and nothing warns.
"""

from __future__ import annotations

import sqlite3

import pytest

from src.core.strategist.context import build_tier2_context
from src.modules.literature import corpus, corpus_context
from src.modules.literature.review import Claim, Evidence, StructuredReview, stamp, verify_review

SOURCE = (
    "We find no detectable change in the equity loading of bitcoin following the listing. "
    "Our control group consists of never-listed cryptocurrencies, which may be affected by spillovers. "
    "We estimate a difference-in-differences specification with asset and day fixed effects."
)
FINDING = "We find no detectable change in the equity loading of bitcoin"
LIMITATION = "never-listed cryptocurrencies, which may be affected by spillovers"


def _review(*, doi: str = "10.1/a", title: str = "Spot ETFs and bitcoin", year: int = 2024) -> StructuredReview:
    review = StructuredReview(
        title=title,
        authors=["A. Author", "B. Coauthor"],
        year=year,
        doi=doi,
        source="openalex",
        key_findings=[Claim(text="No change in equity loading.", evidence=Evidence(quote=FINDING, locator="Results"))],
        limitations=[Claim(text="Controls may be contaminated.", evidence=Evidence(quote=LIMITATION))],
    )
    stamp(review, source_text=SOURCE, model="test-model")
    verify_review(review, SOURCE)
    return review


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "corpus.db"
    with corpus.connect(path) as conn:
        corpus.add_review(conn, _review())
    return path


# ---------------------------------------------------------------------------
# Gathering
# ---------------------------------------------------------------------------


def test_claims_bearing_on_the_question_are_found(db_path):
    evidence = corpus_context.gather(["did the ETF listing change the equity loading"], db=db_path)

    assert evidence.ok
    quotes = {h.quote for h in evidence.hits}
    assert FINDING in quotes
    assert len(evidence.papers) == 1


def test_the_same_claim_matched_by_two_queries_appears_once(db_path):
    evidence = corpus_context.gather(["equity loading bitcoin", "bitcoin equity loading change"], db=db_path)

    assert len([h for h in evidence.hits if h.quote == FINDING]) == 1


def test_no_corpus_is_not_an_error(tmp_path):
    """The normal case for a first-time user. It must cost nothing and warn about nothing."""
    missing = tmp_path / "does-not-exist.db"
    evidence = corpus_context.gather(["anything"], db=missing)

    assert not evidence.ok
    assert evidence.hits == []
    # connect() creates the file it is given, so consulting a corpus that was
    # never built would leave ~/.e2er/corpus.db behind on every paper run for
    # people who never asked for one. Looking must not be a side effect.
    assert not missing.exists()


def test_an_unreadable_corpus_does_not_break_the_run(tmp_path):
    broken = tmp_path / "corpus.db"
    broken.write_bytes(b"this is not a database")

    evidence = corpus_context.gather(["anything"], db=broken)
    assert not evidence.ok


def test_no_query_means_no_lookup(db_path):
    assert not corpus_context.gather([], db=db_path).ok
    assert not corpus_context.gather(["", "   "], db=db_path).ok


def test_an_empty_corpus_yields_nothing(tmp_path):
    with corpus.connect(tmp_path / "c.db") as conn:
        assert not corpus_context.gather(["anything"], conn=conn).ok


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def test_the_evidence_file_carries_the_quotes(db_path, tmp_path):
    evidence = corpus_context.gather(["equity loading"], db=db_path)
    written = corpus_context.write_evidence(tmp_path / "ws", evidence)

    assert written is not None
    text = written.read_text()

    assert FINDING in text, "a claim without its quote is exactly what this replaces"
    assert "No change in equity loading." in text
    assert "Spot ETFs and bitcoin" in text
    assert "Results" in text  # the locator
    assert "10.1/a" in text


def test_nothing_found_writes_no_file(tmp_path):
    """An empty file reads like a corpus that was consulted and had nothing to
    say, which a reader cannot tell from one that was never built."""
    written = corpus_context.write_evidence(tmp_path / "ws", corpus_context.CorpusEvidence())

    assert written is None
    assert not (tmp_path / "ws" / "literature").exists()


def test_claims_are_grouped_by_paper(tmp_path):
    """Two findings from one study are one piece of evidence, not two."""
    path = tmp_path / "corpus.db"
    with corpus.connect(path) as conn:
        corpus.add_review(conn, _review(doi="10.1/a", title="Paper A", year=2024))
        corpus.add_review(conn, _review(doi="10.1/b", title="Paper B", year=2022))

    evidence = corpus_context.gather(["equity loading spillovers"], db=path)
    text = corpus_context.render_markdown(evidence)

    assert text.count("## Paper A") == 1
    assert text.count("## Paper B") == 1
    assert text.index("## Paper A") < text.index("## Paper B"), "newest first"
    assert "**Findings**" in text
    assert "**Limitations the authors concede**" in text


def test_a_quote_spanning_lines_stays_one_blockquote(tmp_path):
    """Found rendering the real corpus.

    Quotes are verbatim spans of PDF text and routinely contain newlines mid
    sentence. Emitted as-is, the second line loses its `>` prefix and the
    blockquote breaks apart — the quote stops looking like a quote.
    """
    source = "1) what are the common IT elements?\n2) How do they connect to alignment?"
    review = StructuredReview(
        title="Wrapped",
        doi="10.1/w",
        year=2024,
        research_question=Claim(
            text="Two questions.",
            evidence=Evidence(quote="1) what are the common IT elements?\n2) How do they connect to alignment?"),
        ),
    )
    stamp(review, source_text=source, model="m")
    verify_review(review, source)

    path = tmp_path / "corpus.db"
    with corpus.connect(path) as conn:
        corpus.add_review(conn, review)

    text = corpus_context.render_markdown(corpus_context.gather(["IT elements"], db=path))

    quote_lines = [ln for ln in text.splitlines() if "what are the common IT elements" in ln]
    assert len(quote_lines) == 1, "the quote must not be split across lines"
    assert quote_lines[0].lstrip().startswith(">")
    assert "How do they connect" in quote_lines[0]


def test_a_field_heading_is_separated_from_the_previous_claim(db_path, tmp_path):
    """Without a blank line the heading runs into the bullet above it."""
    text = corpus_context.render_markdown(corpus_context.gather(["equity loading spillovers"], db=db_path))
    lines = text.splitlines()

    for i, line in enumerate(lines):
        if line.startswith("**") and i > 0:
            assert lines[i - 1] == "", f"heading {line!r} has no blank line before it"


def test_the_file_says_the_quotes_were_checked(db_path, tmp_path):
    evidence = corpus_context.gather(["equity loading"], db=db_path)
    text = corpus_context.render_markdown(evidence)

    assert "located in the source text" in text
    assert "citation gate" in text


# ---------------------------------------------------------------------------
# Reaching the pipeline
# ---------------------------------------------------------------------------


def test_corpus_papers_become_citable(db_path):
    evidence = corpus_context.gather(["equity loading"], db=db_path)
    papers = evidence.as_metadata()

    assert len(papers) == 1
    assert papers[0].doi == "10.1/a"
    assert papers[0].bibtex_key
    assert "Spot ETFs" in papers[0].to_bibtex()


def test_the_drafter_sees_the_evidence(db_path, tmp_path):
    """Written to disk is not the same as reaching the model."""
    workspace = tmp_path / "ws"
    evidence = corpus_context.gather(["equity loading"], db=db_path)
    corpus_context.write_evidence(workspace, evidence)

    context = build_tier2_context(workspace, "paper-1")

    assert "Evidence From The Corpus" in context
    assert FINDING in context


def test_without_a_corpus_the_context_is_unchanged(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()

    context = build_tier2_context(workspace, "paper-1")

    assert "Evidence From The Corpus" not in context


async def test_acquisition_seeds_the_bibliography_from_the_corpus(db_path, tmp_path, monkeypatch):
    """End to end through the real stage: corpus → literature.bib + evidence file."""
    from src.config import get_settings
    from src.modules.literature.discovery import acquire_literature

    workspace = tmp_path / "ws"
    workspace.mkdir()

    monkeypatch.setattr("src.modules.literature.corpus_context.corpus_path", lambda explicit=None: db_path)
    monkeypatch.setattr("src.modules.literature.registry.search_sources", lambda s: [])

    async def _no_store(item, paper_id):
        return None

    monkeypatch.setattr("src.modules.literature.storage.store_paper", _no_store)

    written = await acquire_literature(workspace, "paper-1", ["equity loading bitcoin"], get_settings())

    assert written == 1, "the corpus paper alone should produce a bibliography"
    bib = (workspace / "literature.bib").read_text()
    assert "Spot ETFs" in bib
    assert (workspace / "literature" / "corpus_evidence.md").is_file()


async def test_an_existing_bibliography_is_not_overwritten_but_evidence_is_still_written(
    db_path, tmp_path, monkeypatch
):
    """A BYOD library must not have web hits merged in — but a new evidence file
    is not a merge, and withholding it would punish exactly the users who have
    built a corpus."""
    from src.config import get_settings
    from src.modules.literature.discovery import acquire_literature

    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "literature.bib").write_text("@article{mine2020,\n  title = {Mine},\n}\n")

    monkeypatch.setattr("src.modules.literature.corpus_context.corpus_path", lambda explicit=None: db_path)

    written = await acquire_literature(workspace, "paper-1", ["equity loading"], get_settings())

    assert written == 0
    assert "Spot ETFs" not in (workspace / "literature.bib").read_text()
    assert (workspace / "literature" / "corpus_evidence.md").is_file()


async def test_a_corpus_failure_does_not_stop_acquisition(tmp_path, monkeypatch):
    from src.config import get_settings
    from src.modules.literature.discovery import acquire_literature

    workspace = tmp_path / "ws"
    workspace.mkdir()

    def _boom(*a, **k):
        raise sqlite3.DatabaseError("corpus is toast")

    monkeypatch.setattr("src.modules.literature.corpus_context.gather", lambda *a, **k: corpus_context.CorpusEvidence())
    monkeypatch.setattr("src.modules.literature.registry.search_sources", lambda s: [])
    monkeypatch.setattr("src.modules.literature.corpus.search_claims", _boom)

    written = await acquire_literature(workspace, "paper-1", ["q"], get_settings())
    assert written == 0
