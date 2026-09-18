"""The published schema has to describe what the code actually writes.

A format published as "implementable by others" is a promise, and a promise
nobody checks drifts. `provenance.schema.json` has sat in docs/ unvalidated
since it was written; this makes sure the newer one cannot go the same way.

The test that earns its keep is `test_every_emitted_field_is_described`: it
fails when someone adds a field to StructuredReview and does not add it to the
schema, which is the only way this file goes stale silently.
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from src.modules.literature.review import (
    SCHEMA_VERSION,
    Claim,
    Evidence,
    StructuredReview,
    stamp,
    verify_review,
)

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "docs" / "schemas" / "structured_review.schema.json"


@pytest.fixture(scope="module")
def schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def validator(schema: dict):
    cls = jsonschema.validators.validator_for(schema)
    cls.check_schema(schema)  # the schema itself must be a legal 2020-12 schema
    return cls(schema)


def _full_review() -> StructuredReview:
    """A review with every field populated, so nothing escapes validation."""

    def claim(text: str, quote: str) -> Claim:
        return Claim(text=text, evidence=Evidence(quote=quote, locator="Results"))

    return StructuredReview(
        paper_id="p1",
        title="Spot ETFs and the factor structure of bitcoin",
        authors=["A. Author", "B. Coauthor"],
        year=2024,
        doi="10.1234/example.5678",
        source="openalex",
        access_license="cc-by",
        research_question=claim("Did listing change factor structure?", "We study whether the approval of spot"),
        theoretical_framework=claim("Broadened access.", "the broadened-access hypothesis predicts a rise"),
        hypotheses=[claim("H1: loadings rise.", "we expect the equity loading to increase after listing")],
        methodology=claim("Difference-in-differences.", "we estimate a difference-in-differences specification"),
        data_sources=[claim("Daily prices.", "daily closing prices from a commercial vendor")],
        sample=claim("40 assets.", "our sample comprises forty cryptocurrencies observed daily"),
        key_findings=[claim("No change.", "We find no detectable change in the equity loading")],
        limitations=[claim("Spillovers.", "controls may themselves be affected through sentiment spillovers")],
        implications=claim("Access is not the margin.", "access does not appear to be the binding margin"),
    )


def test_the_schema_is_a_legal_json_schema(validator) -> None:
    assert validator is not None


def test_the_version_in_the_schema_matches_the_version_in_the_code(schema: dict) -> None:
    """The one mismatch that would make every record mislabelled."""
    assert schema["properties"]["schema_version"]["const"] == SCHEMA_VERSION


def test_an_empty_review_validates(validator) -> None:
    """The degenerate record is still a record, and must not be a schema error."""
    validator.validate(StructuredReview().to_dict())


def test_a_fully_populated_review_validates(validator) -> None:
    review = stamp(_full_review(), source_text="x" * 100, model="claude-sonnet-4-5")
    validator.validate(review.to_dict())


def test_a_verified_review_validates(validator) -> None:
    """Verification mutates evidence in place; the mutated shape must still fit."""
    review = _full_review()
    verify_review(review, "We find no detectable change in the equity loading of bitcoin.")
    validator.validate(review.to_dict())


def test_a_review_with_its_verdict_attached_validates(validator) -> None:
    review = _full_review()
    report = verify_review(review, "We find no detectable change in the equity loading of bitcoin.")
    record = review.to_dict()
    record["verification"] = report.to_dict()

    validator.validate(record)
    assert record["verification"]["rejected"] > 0  # the fixture is mostly fabricated on purpose


def test_every_emitted_field_is_described(schema: dict) -> None:
    """The drift guard.

    `additionalProperties: false` means an undescribed field makes every record
    this project writes invalid. Catch it here rather than in someone else's
    parser.
    """
    emitted = set(StructuredReview().to_dict())
    described = set(schema["properties"])

    assert emitted - described == set(), "StructuredReview emits fields the schema does not describe"
    # `verification` is described but never emitted by to_dict(); it is attached
    # by the corpus. Anything else undescribed-but-expected is a mistake.
    assert described - emitted == {"verification"}


def test_an_unknown_field_is_rejected(validator) -> None:
    record = StructuredReview().to_dict()
    record["confidence"] = 0.93  # the kind of thing an extractor invents

    with pytest.raises(jsonschema.ValidationError):
        validator.validate(record)


def test_a_claim_without_evidence_is_not_a_valid_record(validator) -> None:
    """Tolerated on read, refused on write.

    review_from_dict() loads bare {"text": ...} so old corpora keep working, but
    nothing this project writes may look like that — a claim with no quote is
    exactly what the format exists to prevent.
    """
    record = StructuredReview().to_dict()
    record["key_findings"] = [{"text": "asserted without support"}]

    with pytest.raises(jsonschema.ValidationError):
        validator.validate(record)


def test_a_mislabelled_schema_version_is_rejected(validator) -> None:
    record = StructuredReview().to_dict()
    record["schema_version"] = "e2er-structured-review/99"

    with pytest.raises(jsonschema.ValidationError):
        validator.validate(record)
