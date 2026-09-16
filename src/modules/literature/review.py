"""Structured reviews of papers, where every claim is checkable against the source.

A literature search tells you a paper exists. It does not tell you what the
paper claims, and a drafter given thirty BibTeX entries can only cite
plausibly — it cannot situate a contribution against what the field has
actually found. The fix is to extract the content: research question,
framework, hypotheses, method, sample, findings, limitations.

Extraction by a language model is easy and untrustworthy for exactly the reason
this project exists. So the unit here is not a string, it is a ``Claim``: the
extracted statement *plus* the verbatim sentence it came from. Verification then
asks one question of every claim — does that sentence actually occur in the
source text? A claim whose quote cannot be located is rejected, not flagged.

That is the same discipline the numbers gate applies to table cells, one level
up. A number must trace to a sidecar key; a claim must trace to a sentence.
Neither asks a model whether it is telling the truth.

Nothing here calls a model. The extractor does that and hands its output to
``verify_review``, so the check is a pure function of (review, source text) and
is tested without a backend.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

#: Schema version. Bump when a field's meaning changes, so a stored corpus can
#: say which contract it was written under rather than being silently reread
#: under a newer one.
SCHEMA_VERSION = "e2er-structured-review/1"

#: Below this, a "quote" is too short to be evidence of anything — a three-word
#: fragment occurs in any paper and would verify against text it never came from.
MIN_QUOTE_CHARS = 24


@dataclass
class Evidence:
    """The sentence a claim was taken from, and where it was found."""

    quote: str = ""
    locator: str = ""  # section heading, page, or other human hint
    char_start: int = -1  # filled in by verification; -1 means not located
    verified: bool = False
    reason: str = ""  # why it failed, when it did


@dataclass
class Claim:
    """One extracted statement, with the evidence for it.

    ``text`` is the model's paraphrase and is never treated as fact on its own.
    ``evidence.quote`` is what makes it checkable.
    """

    text: str
    evidence: Evidence = field(default_factory=Evidence)

    @property
    def verified(self) -> bool:
        return self.evidence.verified


@dataclass
class StructuredReview:
    """What a paper claims, in a form another program can read."""

    paper_id: str = ""
    title: str = ""
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    doi: str = ""
    source: str = ""
    access_license: str = ""

    research_question: Claim | None = None
    theoretical_framework: Claim | None = None
    hypotheses: list[Claim] = field(default_factory=list)
    methodology: Claim | None = None
    data_sources: list[Claim] = field(default_factory=list)
    sample: Claim | None = None
    key_findings: list[Claim] = field(default_factory=list)
    limitations: list[Claim] = field(default_factory=list)
    implications: Claim | None = None

    # Provenance of the extraction itself.
    schema_version: str = SCHEMA_VERSION
    extracted_at: str = ""
    extractor_model: str = ""
    source_sha256: str = ""
    source_chars: int = 0

    def claims(self) -> list[tuple[str, Claim]]:
        """Every claim with the field it belongs to, for verification and display."""
        out: list[tuple[str, Claim]] = []
        for name in ("research_question", "theoretical_framework", "methodology", "sample", "implications"):
            claim = getattr(self, name)
            if isinstance(claim, Claim):
                out.append((name, claim))
        for name in ("hypotheses", "data_sources", "key_findings", "limitations"):
            for claim in getattr(self, name) or []:
                if isinstance(claim, Claim):
                    out.append((name, claim))
        return out

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)


@dataclass
class ReviewVerification:
    """The verdict on one extraction."""

    total: int = 0
    verified: int = 0
    rejected: int = 0
    rejections: list[dict[str, str]] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        """No claim survived that could not be located in the source."""
        return self.rejected == 0

    @property
    def conclusive(self) -> bool:
        """Did the check have anything to judge?

        An extraction with no claims verifies vacuously, and a report that reads
        the same as one which checked twenty claims would repeat the mistake the
        numbers gate made for months.
        """
        return self.total > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "verified": self.verified,
            "rejected": self.rejected,
            "passed": self.passed,
            "conclusive": self.conclusive,
            "rejections": self.rejections,
        }


_WS = re.compile(r"\s+")

#: Typographic ligatures. pypdf emits these as single codepoints where the PDF
#: font used them, and a model writing the same sentence out types the ASCII
#: letters instead. Two extractors disagreeing about "fi" must not mean two
#: different papers, so this is folded before hashing as well as before matching.
_LIGATURES = {
    "\ufb01": "fi",
    "\ufb02": "fl",
    "\ufb00": "ff",
    "\ufb03": "ffi",
    "\ufb04": "ffl",
    "\ufb05": "ft",
    "\ufb06": "st",
}


def normalize(text: str) -> str:
    """Collapse whitespace, soft hyphenation and ligatures so a quote survives PDF extraction.

    Text pulled out of a PDF carries line breaks mid-sentence, hyphens at line
    ends, non-breaking spaces and ligature codepoints. A verbatim quote that
    fails only because the source had a newline where the model wrote a space is
    a false rejection, and false rejections are how a checker gets switched off.
    """
    for lig, plain in _LIGATURES.items():
        if lig in text:
            text = text.replace(lig, plain)
    text = text.replace("\u00ad", "").replace("\u2010", "-")
    text = re.sub(r"-\s*\n\s*", "", text)  # hyphenated line break
    text = text.replace("\u00a0", " ").replace("\u2019", "'").replace("\u201c", '"').replace("\u201d", '"')
    return _WS.sub(" ", text).strip()


#: Whitespace and every flavour of dash, dropped before comparing a quote.
_DROPPED_IN_MATCH = re.compile(r"[\s\-\u2010-\u2015]")


def _match_form(text: str) -> tuple[str, list[int]]:
    """The form quotes are compared in, plus a map back to offsets in ``text``.

    Measured on real papers rather than guessed. Across eighteen open-access
    PDFs this module rejected six claims; re-checking each against the paper
    showed FOUR of them were not fabrications at all, but artefacts of how the
    text came out of the PDF:

        "DeFi  pro-jects"         a hyphenated line break that became hyphen+space
        "centralized ex- change"  the same
        "Speci{fi}cally"          an fi ligature (folded in normalize)
        "arith- metic"            the same hyphen+space break

    Two were genuine: one reworded sentence, and one quote that is absent from
    the paper however generously whitespace is treated. So two thirds of what
    this check called fabrication was the check being wrong — and a checker whose
    own errors outnumber the errors it catches is worse than no checker at all.

    Comparison therefore drops whitespace and hyphens entirely, which is what
    those artefacts are made of, while leaving wording and word order untouched.
    Those are what separate a quote from a paraphrase and still have to match
    exactly. With a floor of 24 characters, a spurious hit on a space-free,
    hyphen-free string is not a realistic failure mode.
    """
    out: list[str] = []
    index: list[int] = []
    for i, ch in enumerate(text):
        if _DROPPED_IN_MATCH.match(ch):
            continue
        out.append(ch.lower())
        index.append(i)
    return "".join(out), index


def verify_review(review: StructuredReview, source_text: str) -> ReviewVerification:
    """Locate every claim's quote in the source. Mutates the claims' evidence.

    Strict by intent: a quote either occurs in the paper or it does not. The
    only latitude is whitespace and hyphenation, which are artefacts of how the
    text was extracted rather than of what the paper said.
    """
    haystack = normalize(source_text)
    haystack_lower = haystack.lower()
    squashed_hay, hay_index = _match_form(haystack)
    report = ReviewVerification()

    for field_name, claim in review.claims():
        report.total += 1
        evidence = claim.evidence
        quote = normalize(evidence.quote or "")

        if not quote:
            evidence.verified = False
            evidence.reason = "no quote given"
        elif len(quote) < MIN_QUOTE_CHARS:
            evidence.verified = False
            evidence.reason = f"quote too short to be evidence ({len(quote)} chars)"
        else:
            idx = haystack_lower.find(quote.lower())
            if idx < 0:
                # Fall back to the whitespace- and hyphen-free form. This is the
                # difference between catching a fabrication and punishing a
                # model for a PDF that broke a word across a line.
                squashed_quote, _ = _match_form(quote)
                hit = squashed_hay.find(squashed_quote) if squashed_quote else -1
                idx = hay_index[hit] if hit >= 0 else -1

            if idx >= 0:
                evidence.verified = True
                evidence.char_start = idx
                evidence.reason = ""
            else:
                evidence.verified = False
                evidence.reason = "quote does not appear in the source text"

        if evidence.verified:
            report.verified += 1
        else:
            report.rejected += 1
            report.rejections.append(
                {
                    "field": field_name,
                    "claim": claim.text[:160],
                    "quote": (evidence.quote or "")[:160],
                    "reason": evidence.reason,
                }
            )

    return report


def drop_unverified(review: StructuredReview) -> int:
    """Remove claims that failed verification. Returns how many were dropped.

    A corpus is only worth reading if everything in it is checkable, so the
    default is to discard rather than to keep-with-a-warning. The rejections
    stay in the verification report, which is where someone auditing the
    extractor should look.
    """
    dropped = 0

    for name in ("research_question", "theoretical_framework", "methodology", "sample", "implications"):
        claim = getattr(review, name)
        if isinstance(claim, Claim) and not claim.verified:
            setattr(review, name, None)
            dropped += 1

    for name in ("hypotheses", "data_sources", "key_findings", "limitations"):
        kept = [c for c in (getattr(review, name) or []) if c.verified]
        dropped += len(getattr(review, name) or []) - len(kept)
        setattr(review, name, kept)

    return dropped


def source_fingerprint(source_text: str) -> tuple[str, int]:
    """SHA-256 and length of the text an extraction was made from.

    Stored with the review so a corpus entry can be checked against the document
    it claims to describe — the same reason the export bundle hashes every file.
    """
    normalized = normalize(source_text)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return digest, len(normalized)


def stamp(review: StructuredReview, *, source_text: str, model: str) -> StructuredReview:
    """Record when, by what, and from which exact text this review was made."""
    digest, length = source_fingerprint(source_text)
    review.schema_version = SCHEMA_VERSION
    review.extracted_at = datetime.now(UTC).isoformat(timespec="seconds")
    review.extractor_model = model
    review.source_sha256 = digest
    review.source_chars = length
    return review


def review_from_dict(data: dict[str, Any]) -> StructuredReview:
    """Rebuild a review from stored JSON, tolerating older or partial records."""

    def _claim(raw: Any) -> Claim | None:
        if not isinstance(raw, dict):
            return None
        ev = raw.get("evidence") or {}
        return Claim(
            text=str(raw.get("text", "")),
            evidence=Evidence(
                quote=str(ev.get("quote", "")),
                locator=str(ev.get("locator", "")),
                char_start=int(ev.get("char_start", -1)),
                verified=bool(ev.get("verified", False)),
                reason=str(ev.get("reason", "")),
            ),
        )

    def _claims(raw: Any) -> list[Claim]:
        return [c for c in (_claim(x) for x in (raw or [])) if c is not None]

    review = StructuredReview(
        paper_id=str(data.get("paper_id", "")),
        title=str(data.get("title", "")),
        authors=list(data.get("authors") or []),
        year=data.get("year"),
        doi=str(data.get("doi", "")),
        source=str(data.get("source", "")),
        access_license=str(data.get("access_license", "")),
        research_question=_claim(data.get("research_question")),
        theoretical_framework=_claim(data.get("theoretical_framework")),
        hypotheses=_claims(data.get("hypotheses")),
        methodology=_claim(data.get("methodology")),
        data_sources=_claims(data.get("data_sources")),
        sample=_claim(data.get("sample")),
        key_findings=_claims(data.get("key_findings")),
        limitations=_claims(data.get("limitations")),
        implications=_claim(data.get("implications")),
        schema_version=str(data.get("schema_version", SCHEMA_VERSION)),
        extracted_at=str(data.get("extracted_at", "")),
        extractor_model=str(data.get("extractor_model", "")),
        source_sha256=str(data.get("source_sha256", "")),
        source_chars=int(data.get("source_chars", 0)),
    )
    return review
