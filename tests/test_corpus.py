"""The corpus keeps one promise: everything in it has been checked.

So the tests that matter are the ones that try to break that promise — storing
an unverified claim, re-extracting a paper and leaving the old claims behind,
typing a search term that is not a legal query. Each of those would leave the
corpus quietly wrong rather than visibly broken, which is the only kind of wrong
worth writing tests about.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from src.modules.literature.corpus import (
    CorpusError,
    add_review,
    add_topic,
    claims_for_papers,
    connect,
    corpus_path,
    export_corpus,
    fts_query,
    get_review,
    has_doi,
    is_covered,
    list_papers,
    list_topics,
    normalize_doi,
    paper_key,
    record_topic_run,
    remove_paper,
    remove_topic,
    search_claims,
    stats,
)
from src.modules.literature.review import (
    Claim,
    Evidence,
    StructuredReview,
    stamp,
    verify_review,
)

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "docs" / "schemas" / "structured_review.schema.json"

SOURCE = """
We study whether the approval of spot exchange-traded products altered the
factor structure of bitcoin. We find no detectable change in the equity loading
of bitcoin following the listing. We estimate a difference-in-differences
specification with asset and day fixed effects. Our control group consists of
never-listed cryptocurrencies, which may be affected by sentiment spillovers.
"""

FINDING = "We find no detectable change in the equity loading of bitcoin"
METHOD = "We estimate a difference-in-differences specification with asset and day fixed effects"
LIMIT = "never-listed cryptocurrencies, which may be affected by sentiment spillovers"


@pytest.fixture
def db(tmp_path):
    """A throwaway corpus. Never the user's real one at ~/.e2er/corpus.db."""
    with connect(tmp_path / "corpus.db") as conn:
        yield conn


def _review(
    *,
    title: str = "Spot ETFs and bitcoin",
    doi: str = "10.1234/example.1",
    findings: list[str] | None = None,
    method: str | None = METHOD,
    year: int = 2024,
    verified: bool = True,
) -> StructuredReview:
    review = StructuredReview(
        title=title,
        authors=["A. Author"],
        year=year,
        doi=doi,
        source="openalex",
        key_findings=[Claim(text=f"finding: {q[:30]}", evidence=Evidence(quote=q)) for q in (findings or [FINDING])],
        methodology=Claim(text="DiD.", evidence=Evidence(quote=method)) if method else None,
    )
    stamp(review, source_text=SOURCE, model="test-model")
    if verified:
        verify_review(review, SOURCE)
    return review


# ---------------------------------------------------------------------------
# The promise
# ---------------------------------------------------------------------------


def test_an_unverified_claim_is_refused_at_the_door(db):
    """The whole value of the corpus is that no check is needed on the way out."""
    review = StructuredReview(
        title="X",
        doi="10.1/x",
        key_findings=[Claim(text="never checked", evidence=Evidence(quote="q" * 40))],
    )

    with pytest.raises(CorpusError, match="unverified"):
        add_review(db, review)

    assert stats(db).papers == 0, "nothing may be written when the refusal fires"


def test_a_claim_that_failed_verification_is_refused(db):
    review = _review(findings=["We document a sharp increase in equity correlation"], verified=True)
    assert not review.key_findings[0].verified  # the fixture is fabricated on purpose

    with pytest.raises(CorpusError):
        add_review(db, review)


def test_a_verified_review_round_trips(db):
    outcome = add_review(db, _review())

    assert outcome.added and not outcome.replaced
    assert outcome.claims == 2

    restored = get_review(db, outcome.key)
    assert restored is not None
    assert restored.title == "Spot ETFs and bitcoin"
    assert restored.key_findings[0].evidence.quote == FINDING
    assert restored.methodology is not None
    assert restored.source_sha256 == _review().source_sha256


# ---------------------------------------------------------------------------
# Identity and deduplication
# ---------------------------------------------------------------------------


def test_the_same_doi_replaces_rather_than_duplicates(db):
    first = add_review(db, _review(findings=[FINDING]))
    second = add_review(db, _review(findings=[FINDING, LIMIT]))

    assert first.key == second.key
    assert second.replaced and not second.added
    assert stats(db).papers == 1
    assert stats(db).claims == 3, "the newer extraction's claims, not both extractions'"


def test_a_re_extraction_does_not_leave_the_old_claims_behind(db):
    """A superseded reading of a paper must not sit alongside the current one.

    This is the failure that would be invisible: search returns a claim the
    current extraction no longer makes, attributed to a paper that no longer
    supports it.
    """
    add_review(db, _review(findings=[FINDING, LIMIT]))
    add_review(db, _review(findings=[METHOD]))

    quotes = {c.quote for c in claims_for_papers(db, [paper_key(_review())])}
    assert FINDING not in quotes
    assert LIMIT not in quotes
    assert stats(db).claims == 2  # the one finding plus methodology

    hits = search_claims(db, "sentiment spillovers")
    assert hits == [], "a dropped claim must not survive in the search index"


def test_a_re_extraction_leaves_no_orphans_in_the_search_index(db):
    """The leak that queries cannot see.

    search_claims joins claims_fts to corpus_claims, so orphaned index rows are
    invisible in results — and therefore grow without bound, one stale copy per
    re-extraction, in a file that is supposed to be the durable artifact.
    """
    add_review(db, _review(findings=[FINDING, LIMIT]))
    for _ in range(3):
        add_review(db, _review(findings=[METHOD]))

    indexed = db.execute("SELECT COUNT(*) AS n FROM claims_fts").fetchone()["n"]
    stored = db.execute("SELECT COUNT(*) AS n FROM corpus_claims").fetchone()["n"]
    assert indexed == stored

    remove_paper(db, paper_key(_review()))
    assert db.execute("SELECT COUNT(*) AS n FROM claims_fts").fetchone()["n"] == 0


def test_replace_can_be_declined(db):
    add_review(db, _review(findings=[FINDING]))
    outcome = add_review(db, _review(findings=[LIMIT]), replace=False)

    assert not outcome.added and not outcome.replaced
    assert stats(db).claims == 2, "the original extraction is untouched"


def test_dois_are_normalised_so_the_same_paper_is_one_paper(db):
    assert normalize_doi("https://doi.org/10.1234/ABC") == "10.1234/abc"
    assert normalize_doi("doi:10.1234/abc") == "10.1234/abc"
    assert normalize_doi("  10.1234/ABC  ") == "10.1234/abc"

    add_review(db, _review(doi="10.1234/ABC"))
    add_review(db, _review(doi="https://doi.org/10.1234/abc"))
    assert stats(db).papers == 1


def test_a_paper_without_a_doi_is_identified_by_its_text(db):
    """Preprints and BYOD PDFs often have no DOI. They still need one identity."""
    a = _review(doi="", title="Untitled working paper")
    b = _review(doi="", title="Untitled working paper")

    assert paper_key(a) == paper_key(b)
    assert paper_key(a).startswith("text:")

    add_review(db, a)
    add_review(db, b)
    assert stats(db).papers == 1


def test_has_doi_answers_the_question_refresh_asks(db):
    assert not has_doi(db, "10.1234/example.1")
    add_review(db, _review())
    assert has_doi(db, "https://doi.org/10.1234/EXAMPLE.1")
    assert not has_doi(db, "")


def test_a_paper_without_a_doi_is_still_recognised_as_covered(db):
    """The bug that made `refresh` not incremental.

    arXiv returns no DOI, so a DOI-only coverage check re-downloaded and
    re-extracted every preprint on every refresh, forever. The canonical key for
    such a paper is the hash of its full text, which is only knowable after the
    download and the model call the check exists to avoid.
    """
    review = _review(doi="", title="A preprint with no DOI", year=2024)
    add_review(db, review)

    assert is_covered(db, doi="", title="A preprint with no DOI", year=2024)
    assert is_covered(db, doi="", title="  a   PREPRINT with no DOI  ", year=2024), (
        "whitespace and case must not matter"
    )
    assert not is_covered(db, doi="", title="A different preprint", year=2024)
    assert not is_covered(db, doi="", title="A preprint with no DOI", year=2023), (
        "a different year is a different paper"
    )


def test_a_paper_that_later_gains_a_doi_stays_one_paper(db):
    """Found by re-extracting five real papers: three came back as NEW rows.

    arXiv supplies no DOI, so the paper is keyed by the hash of its text. Met
    again through a source that does supply one, it keys by the DOI — and keying
    purely on paper_key() made that two papers. A library that duplicates its
    entries as its metadata improves is not a library.
    """
    add_review(db, _review(doi="", title="A preprint", year=2024, findings=[FINDING]))
    assert stats(db).papers == 1

    outcome = add_review(db, _review(doi="10.48550/arxiv.1234", title="A preprint", year=2024, findings=[LIMIT]))

    assert stats(db).papers == 1, "the same paper must not become two"
    assert outcome.replaced and not outcome.added
    assert has_doi(db, "10.48550/arxiv.1234"), "and the DOI it arrived with must be recorded"


def test_a_paper_that_loses_its_doi_stays_one_paper(db):
    """The mirror case: a DOI-bearing record met again without one."""
    add_review(db, _review(doi="10.1/a", title="Same paper", year=2024))
    add_review(db, _review(doi="", title="Same paper", year=2024, findings=[LIMIT]))

    assert stats(db).papers == 1


def test_two_genuinely_different_papers_are_not_merged(db):
    """Different titles AND different text. The shared-fixture SOURCE would make
    these one paper by the text hash, which is correct but not what is under
    test here."""
    other_source = "We examine gas fees on Ethereum. Median fees fell sharply after the merge in 2022."
    first = StructuredReview(
        title="First paper",
        year=2024,
        key_findings=[Claim(text="a", evidence=Evidence(quote=FINDING))],
    )
    stamp(first, source_text=SOURCE, model="m")
    verify_review(first, SOURCE)

    second = StructuredReview(
        title="Second paper",
        year=2024,
        key_findings=[Claim(text="b", evidence=Evidence(quote="Median fees fell sharply after the merge in 2022"))],
    )
    stamp(second, source_text=other_source, model="m")
    verify_review(second, other_source)

    add_review(db, first)
    add_review(db, second)

    assert stats(db).papers == 2


def test_two_papers_sharing_a_title_but_not_a_doi_stay_separate(db):
    """A title is not an identity. Two DOIs are two papers."""
    add_review(db, _review(doi="10.1/a"))
    add_review(db, _review(doi="10.1/b"))

    assert stats(db).papers == 2


def test_the_same_paper_from_a_pdf_and_from_the_web_is_covered_once(db):
    """The real case: a preprint PDF and its OpenAlex record.

    The PDF's title page says "How Decentralized is the Governance of
    Blockchain-based Finance?"; OpenAlex appends ": Empirical Evidence from four
    Governance Token Distributions". Neither shares a DOI with the other, and
    exact title matching calls them two papers.
    """
    from_pdf = _review(doi="", title="HOW DECENTRALIZED IS THE GOVERNANCE OF BLOCKCHAIN-BASED FINANCE?", year=2021)
    add_review(db, from_pdf)

    assert is_covered(
        db,
        doi="",
        title="How Decentralized is the Governance of Blockchain-based Finance: "
        "Empirical Evidence from four Governance Token Distributions",
        year=2021,
    )


def test_a_short_title_does_not_match_by_prefix(db):
    """ "Bitcoin" must not cover every paper beginning with the word."""
    add_review(db, _review(doi="", title="Stablecoins", year=2024))
    assert not is_covered(db, doi="", title="Stablecoins and Bank Runs in Decentralized Finance", year=2024)


def test_prefix_matching_never_decides_where_a_review_is_stored(db):
    """The asymmetry that makes generous matching safe.

    A coverage false-positive skips a paper. A storage false-positive would
    overwrite one paper's claims with another's.
    """
    long_a = "Designing Autonomous Markets for Stablecoin Monetary Policy"
    long_b = "Designing Autonomous Markets for Stablecoin Monetary Policy and Redemption Curves"

    add_review(db, _review(doi="10.1/a", title=long_a, findings=[FINDING]))
    add_review(db, _review(doi="10.1/b", title=long_b, findings=[LIMIT]))

    assert stats(db).papers == 2, "two DOIs are two papers, whatever their titles share"
    assert get_review(db, "doi:10.1/a") is not None
    assert get_review(db, "doi:10.1/b") is not None


def test_coverage_still_prefers_the_doi(db):
    add_review(db, _review(doi="10.1234/example.1", title="Original title"))

    # Same paper, retitled upstream: the DOI still identifies it.
    assert is_covered(db, doi="10.1234/example.1", title="Completely different title")


def test_an_untitled_doi_less_paper_is_never_falsely_covered(db):
    add_review(db, _review(doi="", title="Something"))
    assert not is_covered(db, doi="", title="", year=None)


def test_a_corpus_written_before_title_keys_existed_still_opens(tmp_path):
    """A corpus is meant to outlive the code that wrote it.

    The old shape is built directly rather than by dropping the column from the
    current one. `ALTER TABLE ... DROP COLUMN` makes SQLite re-parse the stored
    table definition, which older builds refuse to do — so a test written that
    way passes on a new SQLite and fails on CI's, testing the local library
    version rather than the migration.
    """
    path = tmp_path / "old.db"

    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE corpus_papers (
            key           TEXT PRIMARY KEY,
            doi           TEXT,
            title         TEXT NOT NULL DEFAULT '',
            authors_json  TEXT NOT NULL DEFAULT '[]',
            year          INTEGER,
            source        TEXT NOT NULL DEFAULT '',
            access_license TEXT NOT NULL DEFAULT '',
            added_at      TEXT NOT NULL,
            updated_at    TEXT NOT NULL
        );
        INSERT INTO corpus_papers (key, doi, title, year, added_at, updated_at)
        VALUES ('text:abc', '', 'Legacy preprint', 2024, '2026-01-01', '2026-01-01');
        """
    )
    conn.commit()
    conn.close()

    with connect(path) as opened:
        assert stats(opened).papers == 1, "an older file must still open"
        assert is_covered(opened, doi="", title="Legacy preprint", year=2024), "the backfill must run"


def test_removing_a_paper_takes_its_claims_with_it(db):
    key = add_review(db, _review()).key

    assert remove_paper(db, key)
    assert stats(db).papers == 0
    assert stats(db).claims == 0
    assert search_claims(db, "equity loading") == []
    assert not remove_paper(db, key)


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


def test_search_returns_the_sentence_not_just_the_paper(db):
    add_review(db, _review())

    hits = search_claims(db, "equity loading")

    assert hits
    assert hits[0].quote == FINDING
    assert hits[0].title == "Spot ETFs and bitcoin"
    assert hits[0].field == "key_findings"
    assert "2024" in hits[0].cite()


def test_a_search_term_with_punctuation_does_not_crash(db):
    """Raw user text is not a legal FTS5 expression.

    `null effects (ETF)` is a syntax error in MATCH, and so is anything with a
    bare hyphen or quote. A person typing an ordinary search term must not get a
    stack trace.
    """
    add_review(db, _review())

    for term in [
        "null effects (ETF)",
        'bitcoin "equity" loading',
        "difference-in-differences",
        "what did they find?",
        "AND OR NOT",
        "*",
        "'",
        "NEAR(a b)",
    ]:
        hits = search_claims(db, term)
        assert isinstance(hits, list), f"{term!r} should return a list, not raise"


def test_an_empty_search_returns_nothing_rather_than_everything(db):
    add_review(db, _review())
    assert search_claims(db, "") == []
    assert search_claims(db, "   ") == []
    assert search_claims(db, "!!!") == []


def test_search_can_be_restricted_to_a_field(db):
    add_review(db, _review())

    assert search_claims(db, "difference", fields=["methodology"])
    assert search_claims(db, "difference", fields=["limitations"]) == []


def test_a_natural_language_question_still_finds_the_claim(db):
    """ANDing every word of a question matches nothing; OR plus ranking does."""
    add_review(db, _review())

    hits = search_claims(db, "who found no change in the equity loading of bitcoin")
    assert hits
    assert hits[0].quote == FINDING


def test_the_fts_query_builder_quotes_every_token():
    assert fts_query("null effects (ETF)") == '"null" OR "effects" OR "ETF"'
    assert fts_query("difference-in-differences") == '"difference" OR "in" OR "differences"'
    assert fts_query("!!!") == ""
    assert fts_query("") == ""


def test_search_works_without_fts5(db):
    """Some SQLite builds omit FTS5. The corpus must still be searchable."""
    add_review(db, _review())
    db.execute("DROP TABLE claims_fts")

    hits = search_claims(db, "equity loading")

    assert hits
    assert hits[0].quote == FINDING
    # The better-matching claim should rank first even in the fallback.
    assert search_claims(db, "difference fixed effects")[0].field == "methodology"


def test_a_broken_fts_query_falls_back_rather_than_raising(db, monkeypatch):
    add_review(db, _review())
    monkeypatch.setattr("src.modules.literature.corpus.fts_query", lambda q: "((((")

    hits = search_claims(db, "equity loading")
    assert hits, "a malformed MATCH must fall through to LIKE, not surface as an error"


# ---------------------------------------------------------------------------
# Topics
# ---------------------------------------------------------------------------


def test_a_topic_is_registered_once(db):
    assert add_topic(db, "crypto ETF approval")
    assert not add_topic(db, "crypto ETF approval")
    assert [t.query for t in list_topics(db)] == ["crypto ETF approval"]


def test_a_topic_needs_a_query(db):
    with pytest.raises(CorpusError):
        add_topic(db, "   ")


def test_topic_runs_accumulate(db):
    add_topic(db, "q")
    record_topic_run(db, "q", found=10, added=4)
    record_topic_run(db, "q", found=12, added=1)

    topic = list_topics(db)[0]
    assert topic.n_found == 22
    assert topic.n_added == 5
    assert topic.last_run_at


def test_a_topic_can_be_removed(db):
    add_topic(db, "q")
    assert remove_topic(db, "q")
    assert not remove_topic(db, "q")
    assert list_topics(db) == []


# ---------------------------------------------------------------------------
# Statistics — the part that is a measurement rather than bookkeeping
# ---------------------------------------------------------------------------


def _extraction(proposed: int, rejections: list[tuple[str, str]]) -> dict:
    return {
        "attempts": [
            {
                "index": 0,
                "proposed": proposed,
                "verified": proposed - len(rejections),
                "rejected": len(rejections),
                "rejections": [{"field": f, "reason": r, "claim": "c", "quote": "q"} for f, r in rejections],
            }
        ],
        "verification": {"total": proposed, "verified": proposed - len(rejections), "rejected": 0},
    }


def test_stats_counts_what_is_there(db):
    add_review(db, _review(doi="10.1/a", year=2024))
    add_review(db, _review(doi="10.1/b", year=2023))
    add_topic(db, "t")

    s = stats(db)
    assert s.papers == 2
    assert s.reviews == 2
    assert s.claims == 4
    assert s.claims_by_field["key_findings"] == 2
    assert s.claims_by_field["methodology"] == 2
    assert s.papers_by_year == {"2024": 1, "2023": 1}
    assert s.models == {"test-model": 2}
    assert s.topics == 1


def test_the_corpus_measures_how_often_the_model_fabricated(db):
    add_review(
        db,
        _review(doi="10.1/a"),
        extraction=_extraction(4, [("key_findings", "quote does not appear in the source text")]),
    )
    add_review(
        db,
        _review(doi="10.1/b"),
        extraction=_extraction(
            6,
            [
                ("limitations", "quote does not appear in the source text"),
                ("limitations", "quote too short to be evidence (9 chars)"),
                ("key_findings", "no quote given"),
            ],
        ),
    )

    s = stats(db)
    assert s.extractions_measured == 2
    assert s.first_pass_proposed == 10
    assert s.first_pass_rejected == 4
    assert s.first_pass_rejection_rate == 0.4
    assert s.rejections_by_field == {"key_findings": 2, "limitations": 2}
    assert s.rejections_by_reason == {
        "quote not in source": 2,
        "quote too short": 1,
        "no quote given": 1,
    }


def test_the_measurement_reads_the_first_pass_not_the_repaired_one(db):
    """The retry cleans the corpus and destroys the measurement.

    After a coached retry the surviving review verifies clean, so a statistic
    computed from the last attempt would report that the model almost never
    fabricates — which is exactly backwards, and is the number the whole
    exercise exists to get right.
    """
    two_attempts = {
        "attempts": [
            {
                "index": 0,
                "proposed": 4,
                "verified": 1,
                "rejected": 3,
                "rejections": [{"field": "key_findings", "reason": "quote does not appear in the source text"}] * 3,
            },
            {"index": 1, "proposed": 3, "verified": 3, "rejected": 0, "rejections": []},
        ],
        "verification": {"total": 4, "verified": 4, "rejected": 0},
    }
    add_review(db, _review(), extraction=two_attempts)

    s = stats(db)
    assert s.first_pass_proposed == 4, "the retry's proposals are not the first pass"
    assert s.first_pass_rejected == 3
    assert s.first_pass_rejection_rate == 0.75
    assert sum(s.rejections_by_field.values()) == 3


def test_nothing_measured_is_not_the_same_as_nothing_rejected(db):
    """A corpus imported from elsewhere legitimately has no measurement.

    Reporting 0.0 would say the model never fabricated, which is a claim the
    data does not support.
    """
    add_review(db, _review())
    s = stats(db)

    assert s.extractions_measured == 0
    assert s.first_pass_rejection_rate is None


def test_rejection_rate_by_field_shows_where_fabrication_concentrates(db):
    """The expectation worth testing: findings are quotable, limitations diffuse."""
    add_review(
        db,
        _review(doi="10.1/a"),
        extraction=_extraction(
            4,
            [
                ("limitations", "quote does not appear in the source text"),
                ("limitations", "quote does not appear in the source text"),
            ],
        ),
    )

    by_field = stats(db).rejection_rate_by_field()
    assert by_field["limitations"] == 1.0  # 2 rejected, 0 kept
    assert "key_findings" not in by_field or by_field["key_findings"] < 1.0


def test_a_corrupt_extraction_record_does_not_break_stats(db):
    key = add_review(db, _review()).key
    db.execute("UPDATE corpus_reviews SET extraction_json = ? WHERE key = ?", ("{not json", key))
    db.commit()

    s = stats(db)
    assert s.papers == 1
    assert s.extractions_measured == 0


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def test_export_writes_schema_valid_records(tmp_path, db):
    jsonschema = pytest.importorskip("jsonschema")
    add_review(db, _review(doi="10.1/a"), extraction=_extraction(2, []))
    add_review(db, _review(doi="10.1/b"))

    written = export_corpus(db, tmp_path / "out")

    assert written == 2
    index = json.loads((tmp_path / "out" / "index.json").read_text())
    assert index["papers"] == 2
    assert len(index["index"]) == 2

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    for entry in index["index"]:
        record = json.loads((tmp_path / "out" / entry["file"]).read_text(encoding="utf-8"))
        jsonschema.validate(record, schema)


def test_an_empty_corpus_exports_cleanly(tmp_path, db):
    assert export_corpus(db, tmp_path / "out") == 0
    assert json.loads((tmp_path / "out" / "index.json").read_text())["papers"] == 0


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


def test_the_corpus_lives_outside_any_workspace():
    """A library that resets per project is not a library."""
    assert corpus_path().name == "corpus.db"
    assert corpus_path("/tmp/x/other.db").as_posix() == "/tmp/x/other.db"


def test_the_database_is_created_on_first_use(tmp_path):
    path = tmp_path / "nested" / "dir" / "corpus.db"
    with connect(path) as conn:
        assert stats(conn).papers == 0
    assert path.is_file()


def test_reopening_keeps_what_was_stored(tmp_path):
    path = tmp_path / "corpus.db"
    with connect(path) as conn:
        add_review(conn, _review())
    with connect(path) as conn:
        assert stats(conn).papers == 1
        assert search_claims(conn, "equity loading")


def test_listing_papers_reports_claim_counts(db):
    add_review(db, _review(doi="10.1/a"))
    rows = list_papers(db)

    assert len(rows) == 1
    assert rows[0].n_claims == 2
    assert rows[0].authors == ["A. Author"]
    assert rows[0].extractor_model == "test-model"


def test_foreign_keys_are_enforced(db):
    """Orphan claims would be invisible in every query except the count."""
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO corpus_claims (key, field, text, quote) VALUES ('nope', 'key_findings', 't', 'q')",
        )
        db.commit()
