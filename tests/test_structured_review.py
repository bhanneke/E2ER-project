"""A claim is only worth storing if it can be traced back to a sentence.

E2ER already refuses a table cell that does not trace to a sidecar key. This is
the same rule one level up: an extracted claim must trace to a verbatim sentence
in the paper, and one that cannot is rejected rather than flagged.

The tests that matter here are the ones where the extraction is plausible and
wrong — a fabricated finding, a paraphrase presented as a quote, a fragment so
short it matches anything. Those are what an unverified corpus quietly fills up
with, and they are indistinguishable from good extractions by reading.
"""

from __future__ import annotations

from src.modules.literature.review import (
    MIN_QUOTE_CHARS,
    Claim,
    Evidence,
    StructuredReview,
    drop_unverified,
    normalize,
    review_from_dict,
    source_fingerprint,
    stamp,
    verify_review,
)

PAPER = """
    Introduction. We study whether the approval of spot exchange-traded products
    altered the factor structure of bitcoin. Our identification exploits the
    January 2024 listing as an access shock.

    Results. We find no detectable change in the equity loading of bitcoin
    following the listing. The estimated differential shift is small and of the
    wrong sign for the broadened-access hypothesis.

    Limitations. Our control group consists of never-listed cryptocurrencies,
    which may themselves be affected by the listing through sentiment spillovers.
"""


def _claim(text: str, quote: str) -> Claim:
    return Claim(text=text, evidence=Evidence(quote=quote))


def test_a_claim_whose_quote_is_in_the_paper_verifies():
    review = StructuredReview(
        key_findings=[
            _claim("No change in equity loading.", "We find no detectable change in the equity loading of bitcoin")
        ]
    )
    report = verify_review(review, PAPER)

    assert report.passed
    assert report.verified == 1
    assert review.key_findings[0].verified
    assert review.key_findings[0].evidence.char_start >= 0


def test_a_fabricated_finding_is_rejected():
    """The case the whole design exists for.

    The claim is plausible, well-formed, and in the register of the paper. Only
    the quote gives it away, because the paper never says it.
    """
    review = StructuredReview(
        key_findings=[
            _claim(
                "Equity correlation rose sharply after the listing.",
                "We document a sharp and persistent increase in the equity correlation of bitcoin",
            )
        ]
    )
    report = verify_review(review, PAPER)

    assert not report.passed
    assert report.rejected == 1
    assert "does not appear" in report.rejections[0]["reason"]


def test_a_paraphrase_offered_as_a_quote_is_rejected():
    """Close is not verbatim. A quote that has been tidied is not evidence."""
    review = StructuredReview(
        key_findings=[_claim("No change.", "We found no detectable changes in bitcoin's equity loadings")]
    )
    assert not verify_review(review, PAPER).passed


def test_a_quote_too_short_to_be_evidence_is_rejected():
    """ "We find" occurs in every empirical paper ever written."""
    review = StructuredReview(key_findings=[_claim("Something.", "We find")])
    report = verify_review(review, PAPER)

    assert report.rejected == 1
    assert "too short" in report.rejections[0]["reason"]
    assert len("We find") < MIN_QUOTE_CHARS


def test_a_claim_with_no_quote_at_all_is_rejected():
    review = StructuredReview(key_findings=[_claim("Asserted without support.", "")])
    report = verify_review(review, PAPER)
    assert report.rejected == 1
    assert report.rejections[0]["reason"] == "no quote given"


def test_line_breaks_and_hyphenation_do_not_cause_false_rejections():
    """PDF text carries newlines mid-sentence and hyphens at line ends.

    Rejecting a true quote over an artefact of extraction is how a checker earns
    a reputation for crying wolf and gets switched off.
    """
    source = "We find no detectable change in the equity load-\ning of bitcoin following the listing."
    review = StructuredReview(
        key_findings=[_claim("No change.", "We find no detectable change in the equity loading of bitcoin")]
    )
    assert verify_review(review, source).passed


class TestPdfArtifactsAreNotFabrications:
    """The artefacts that made this module call four true quotes fabrications.

    Across eighteen open-access PDFs it rejected six claims. Re-checking each
    against its paper showed four were true quotes that failed only on whitespace,
    hyphenation or a ligature; two were genuine. A checker whose own errors
    outnumber the errors it catches is worse than no checker.

    The first two and the ligature case are taken from those real rejections.
    The intra-word-spacing case is a capability test rather than a reproduction:
    PDF extraction does split words that way, but the one real quote that looked
    like it turned out to be absent from the paper for other reasons.
    """

    def test_a_hyphenated_line_break_that_became_hyphen_space(self):
        """'DeFi pro-jects' — the newline turned into a space, the hyphen stayed."""
        source = "We aggregate, parse and clean data from the Ethereum blockchain for four DeFi  pro-jects: Balancer."
        review = StructuredReview(
            data_sources=[
                _claim(
                    "Ethereum data for four projects.",
                    "We aggregate, parse and clean data from the Ethereum blockchain for four DeFi projects: Balancer.",
                )
            ]
        )
        assert verify_review(review, source).passed

    def test_a_word_split_across_a_line_in_the_middle(self):
        """'centralized ex- change OKX'."""
        source = "he transferred large amounts of borrowed CRV to the centralized ex- change OKX over November"
        review = StructuredReview(
            key_findings=[
                _claim(
                    "Moved CRV to OKX.",
                    "he transferred large amounts of borrowed CRV to the centralized exchange OKX",
                )
            ]
        )
        assert verify_review(review, source).passed

    def test_an_fi_ligature(self):
        """pypdf emits U+FB01 where the font used one; a model types 'fi'."""
        source = "Speciﬁcally, the implementation only requires a constant number of arithmetic operations."
        review = StructuredReview(
            key_findings=[
                _claim(
                    "Constant arithmetic.",
                    "Specifically, the implementation only requires a constant number of arithmetic operations.",
                )
            ]
        )
        assert verify_review(review, source).passed

    def test_intra_word_spacing_corruption(self):
        """'will b e the time' — extraction broke the word; the model repaired it."""
        source = "The moment of releasing the additional nodes will b e the time  when an attacker catches half"
        review = StructuredReview(
            key_findings=[
                _claim(
                    "Release timing.",
                    "The moment of releasing the additional nodes will be the time when an attacker catches half",
                )
            ]
        )
        assert verify_review(review, source).passed

    def test_the_offset_still_points_into_the_real_text(self):
        """A fallback match must not report a meaningless location."""
        source = "Preamble text. Speciﬁcally, the implementation requires a constant number of operations."
        review = StructuredReview(
            key_findings=[
                _claim(
                    "x",
                    "Specifically, the implementation requires a constant number of operations.",
                )
            ]
        )
        verify_review(review, source)
        start = review.key_findings[0].evidence.char_start

        assert start > 0
        assert normalize(source)[start:].lower().startswith("specifically")


class TestLeniencyHasLimits:
    """The fallback must not turn the checker into a rubber stamp."""

    def test_a_paraphrase_is_still_rejected_under_the_fallback(self):
        review = StructuredReview(
            key_findings=[_claim("No change.", "We found no detectable changes in bitcoin's equity loadings")]
        )
        assert not verify_review(review, PAPER).passed

    def test_reordered_words_are_still_rejected(self):
        review = StructuredReview(
            key_findings=[_claim("x", "the equity loading of bitcoin no detectable change we find in")]
        )
        assert not verify_review(review, PAPER).passed

    def test_a_fabrication_is_still_rejected(self):
        review = StructuredReview(
            key_findings=[
                _claim("x", "We document a sharp and persistent increase in the equity correlation of bitcoin")
            ]
        )
        assert not verify_review(review, PAPER).passed

    def test_dropping_spaces_does_not_let_a_short_quote_through(self):
        review = StructuredReview(key_findings=[_claim("x", "W e f i n d")])
        report = verify_review(review, PAPER)
        assert report.rejected == 1


def test_verification_counts_every_field_not_just_findings():
    review = StructuredReview(
        research_question=_claim(
            "Did listing change factor structure?", "We study whether the approval of spot exchange-traded products"
        ),
        limitations=[
            _claim(
                "Controls may be contaminated.",
                "which may themselves be affected by the listing through sentiment spillovers",
            )
        ],
        key_findings=[_claim("Made up.", "we observe a large and significant increase in trading volume")],
    )
    report = verify_review(review, PAPER)

    assert report.total == 3
    assert report.verified == 2
    assert report.rejected == 1


def test_an_empty_extraction_is_not_a_clean_bill_of_health():
    """`passed` with nothing checked reads exactly like a verified review.

    The numbers gate reported precisely this for months, so the report carries
    `conclusive` separately from `passed`.
    """
    report = verify_review(StructuredReview(), PAPER)

    assert report.passed is True
    assert report.conclusive is False


def test_dropping_unverified_claims_leaves_only_checkable_content():
    review = StructuredReview(
        research_question=_claim("Real.", "We study whether the approval of spot exchange-traded products"),
        methodology=_claim("Invented.", "we estimate a structural vector autoregression with sign restrictions"),
        key_findings=[
            _claim("Real.", "We find no detectable change in the equity loading of bitcoin"),
            _claim("Invented.", "the effect is statistically significant at the one percent level"),
        ],
    )
    verify_review(review, PAPER)
    dropped = drop_unverified(review)

    assert dropped == 2
    assert review.methodology is None
    assert len(review.key_findings) == 1
    assert review.research_question is not None


def test_the_source_is_fingerprinted_so_a_review_can_be_matched_to_its_text():
    digest, length = source_fingerprint(PAPER)
    assert len(digest) == 64
    assert length == len(normalize(PAPER))

    # Whitespace differences must not change the fingerprint: the same PDF read
    # twice by different extractors is the same source.
    other, _ = source_fingerprint(PAPER.replace("\n", "  "))
    assert other == digest


def test_a_stamped_review_records_what_made_it():
    review = stamp(StructuredReview(title="X"), source_text=PAPER, model="claude-sonnet-4-5")
    assert review.extractor_model == "claude-sonnet-4-5"
    assert review.extracted_at
    assert review.source_sha256
    assert review.schema_version.startswith("e2er-structured-review/")


def test_a_review_survives_a_round_trip_through_json():
    original = stamp(
        StructuredReview(
            title="Spot ETFs",
            key_findings=[_claim("No change.", "We find no detectable change in the equity loading of bitcoin")],
        ),
        source_text=PAPER,
        model="m",
    )
    verify_review(original, PAPER)

    restored = review_from_dict(original.to_dict())

    assert restored.title == "Spot ETFs"
    assert restored.key_findings[0].verified is True
    assert restored.key_findings[0].evidence.quote == original.key_findings[0].evidence.quote
    assert restored.source_sha256 == original.source_sha256


def test_a_partial_record_does_not_break_loading():
    """Corpora outlive schemas; a record missing fields must still load."""
    restored = review_from_dict({"title": "Old record", "key_findings": [{"text": "x"}]})
    assert restored.title == "Old record"
    assert restored.key_findings[0].verified is False
