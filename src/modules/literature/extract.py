"""Turn a paper's full text into a structured review whose claims are checkable.

This is the only part of the literature engine that calls a model, and it is
built on the assumption that the model will sometimes invent things. Everything
it produces goes straight to ``verify_review``, which locates each quote in the
source text; anything that cannot be located is dropped before the review is
returned.

The contract with the model is stated plainly in the prompt: quotes are checked
mechanically, and a claim whose quote is not in the paper is discarded. That is
not a threat, it is information — a model told its quotes will be checked has no
reason to guess, and the measured difference between what it proposes and what
survives is the most interesting number this module produces.

One coached retry. When claims are rejected, the rejected ones go back with
their reasons and the model may supply correct quotes or withdraw them. A second
failure means the claim probably is not in the paper, so we stop asking.

Chunking is for long papers only, and verification always runs against the
**full** text — a quote found in the fourth chunk still verifies, and a model
that stitches two chunks together still gets caught.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ...logging_config import get_logger
from ..llm.base import LLMBackend, TokenUsage, extract_json
from ..security import sanitize_for_prompt
from .models import PaperMetadata
from .review import (
    Claim,
    Evidence,
    ReviewVerification,
    StructuredReview,
    drop_unverified,
    normalize,
    stamp,
    verify_review,
)

logger = get_logger(__name__)

#: How much source text goes into one extraction call. Most papers fit whole.
#: Past this we split, because a prompt that overruns the window fails in ways
#: that look like a bad extraction rather than like a truncated one.
CHUNK_CHARS = 40_000

#: Overlap between chunks, so a sentence spanning a boundary is not lost from
#: both sides.
CHUNK_OVERLAP = 1_000

#: Below this there is nothing to extract — an abstract-only record produces
#: claims that verify against the abstract and misrepresent the paper.
MIN_SOURCE_CHARS = 400

_SINGULAR_FIELDS = ("research_question", "theoretical_framework", "methodology", "sample", "implications")
_LIST_FIELDS = ("hypotheses", "data_sources", "key_findings", "limitations")

_SYSTEM = """You extract structured summaries of academic papers.

Every statement you extract must be supported by a VERBATIM quote from the paper
— an exact span of characters copied from the text, not a paraphrase, not a
tidied version, not two sentences joined together.

Quotes are checked mechanically against the source text. A claim whose quote
cannot be found is discarded, and so is the claim it supports. You are not
penalised for omitting a field; you gain nothing by guessing at one.

Rules that decide whether a claim survives:
  - The quote must appear in the paper character for character. Only whitespace
    and end-of-line hyphenation are forgiven.
  - The quote must be at least 30 characters. Short fragments match text they
    never came from and are rejected on sight.
  - If the paper does not state something, omit the field. Use null for a
    missing single field and [] for a missing list.

Output ONLY a JSON object. No prose, no markdown fences, no commentary."""

_SCHEMA_BLOCK = """{
  "research_question":     {"text": "...", "quote": "...", "locator": "Introduction"} | null,
  "theoretical_framework": {"text": "...", "quote": "...", "locator": "..."} | null,
  "hypotheses":            [{"text": "...", "quote": "...", "locator": "..."}],
  "methodology":           {"text": "...", "quote": "...", "locator": "..."} | null,
  "data_sources":          [{"text": "...", "quote": "...", "locator": "..."}],
  "sample":                {"text": "...", "quote": "...", "locator": "..."} | null,
  "key_findings":          [{"text": "...", "quote": "...", "locator": "..."}],
  "limitations":           [{"text": "...", "quote": "...", "locator": "..."}],
  "implications":          {"text": "...", "quote": "...", "locator": "..."} | null
}

"text" is your own one-sentence statement of the point.
"quote" is the verbatim span from the paper that supports it.
"locator" is a human hint (section heading, table number) and is never matched."""


@dataclass
class ExtractionAttempt:
    """What one call to the model produced, before anything was dropped.

    Kept per attempt rather than in aggregate because the first pass is the
    measurement and the retry is the repair. Collapsing them would hide the
    number worth reporting: how often a model fabricates a quote when it has
    been told the quote will be checked.
    """

    index: int
    parsed: bool = False
    proposed: int = 0
    verified: int = 0
    rejected: int = 0
    rejections: list[dict[str, str]] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "parsed": self.parsed,
            "proposed": self.proposed,
            "verified": self.verified,
            "rejected": self.rejected,
            "rejections": self.rejections,
            "error": self.error,
        }


@dataclass
class ExtractionResult:
    """A review, the verdict on it, and the record of how it was obtained."""

    review: StructuredReview
    verification: ReviewVerification = field(default_factory=ReviewVerification)
    attempts: list[ExtractionAttempt] = field(default_factory=list)
    #: Claim *offers* discarded across all attempts, not distinct claims — a
    #: claim rejected on the first pass and re-offered on the retry was offered
    #: twice, and both offers count.
    dropped: int = 0
    usage: TokenUsage = field(default_factory=TokenUsage)
    error: str = ""

    @property
    def ok(self) -> bool:
        """Did this produce anything worth storing?

        Deliberately not ``verification.passed``: after ``drop_unverified`` the
        surviving review always passes, so passing says nothing. What matters is
        whether any claim survived.
        """
        return bool(self.review.claims()) and not self.error

    @property
    def proposed(self) -> int:
        """Claims the model offered across all attempts."""
        return sum(a.proposed for a in self.attempts)

    @property
    def first_pass_rejection_rate(self) -> float | None:
        """Share of first-pass claims whose quote was not in the paper.

        The retry repairs some of these, so the final corpus is cleaner than
        this number — which is precisely why the final corpus cannot be used to
        measure the model. ``None`` when the first pass produced nothing.
        """
        if not self.attempts or not self.attempts[0].proposed:
            return None
        first = self.attempts[0]
        return first.rejected / first.proposed

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "proposed": self.proposed,
            "dropped": self.dropped,
            "first_pass_rejection_rate": self.first_pass_rejection_rate,
            "verification": self.verification.to_dict(),
            "attempts": [a.to_dict() for a in self.attempts],
            "error": self.error,
        }


# --------------------------------------------------------------------------
# Parsing what the model returned
# --------------------------------------------------------------------------


def _claim_from(raw: Any) -> Claim | None:
    """Accept a claim in either the flat or nested shape.

    Models reliably produce ``{"text": ..., "quote": ...}`` and less reliably
    produce ``{"text": ..., "evidence": {"quote": ...}}``. Both mean the same
    thing, and rejecting one of them over shape would discard real work.
    """
    if not isinstance(raw, dict):
        return None
    text = str(raw.get("text") or "").strip()
    if not text:
        return None

    nested = raw.get("evidence")
    if isinstance(nested, dict):
        quote = str(nested.get("quote") or "")
        locator = str(nested.get("locator") or "")
    else:
        quote = str(raw.get("quote") or "")
        locator = str(raw.get("locator") or "")

    return Claim(text=text, evidence=Evidence(quote=quote, locator=locator))


def _claims_from(raw: Any) -> list[Claim]:
    if not isinstance(raw, list):
        return []
    return [c for c in (_claim_from(x) for x in raw) if c is not None]


def review_from_model_output(payload: dict[str, Any]) -> StructuredReview:
    """Build an unverified review from a parsed model response."""
    review = StructuredReview()
    for name in _SINGULAR_FIELDS:
        setattr(review, name, _claim_from(payload.get(name)))
    for name in _LIST_FIELDS:
        setattr(review, name, _claims_from(payload.get(name)))
    return review


# --------------------------------------------------------------------------
# Merging
# --------------------------------------------------------------------------


def _quote_key(claim: Claim) -> str:
    return normalize(claim.evidence.quote).lower()


def merge_reviews(base: StructuredReview, incoming: StructuredReview) -> StructuredReview:
    """Fold ``incoming`` into ``base``, in place, preferring what is already there.

    Used for both chunked extraction and the coached retry. Singular fields are
    first-wins, because a paper has one research question and the earlier chunk
    is the one likelier to contain it. List fields accumulate, deduplicated by
    quote — the same finding quoted identically from an overlapping chunk is one
    finding, not two.
    """
    for name in _SINGULAR_FIELDS:
        if getattr(base, name) is None and getattr(incoming, name) is not None:
            setattr(base, name, getattr(incoming, name))

    for name in _LIST_FIELDS:
        existing: list[Claim] = list(getattr(base, name) or [])
        seen = {_quote_key(c) for c in existing}
        for claim in getattr(incoming, name) or []:
            key = _quote_key(claim)
            if key and key in seen:
                continue
            seen.add(key)
            existing.append(claim)
        setattr(base, name, existing)

    return base


# --------------------------------------------------------------------------
# Chunking
# --------------------------------------------------------------------------

_HEADING = re.compile(
    r"\n(?=\s*(?:\d+\.?\s+)?(?:Abstract|Introduction|Background|Related Work|Literature|Theory|"
    r"Hypotheses|Data|Method|Methods|Methodology|Empirical|Identification|Results|Findings|"
    r"Discussion|Robustness|Limitations|Conclusion|References)\b)",
    re.IGNORECASE,
)


def chunk_source(text: str, *, max_chars: int = CHUNK_CHARS, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split long text for extraction, preferring section boundaries.

    Whole text when it fits, which is the common case. When it does not, split
    on headings where they exist and fall back to fixed windows with overlap
    where they do not, so a sentence straddling a boundary survives in one piece
    on at least one side.
    """
    if len(text) <= max_chars:
        return [text]

    # Prefer heading boundaries; they keep a method section intact.
    pieces = _HEADING.split(text)
    chunks: list[str] = []
    current = ""
    for piece in pieces:
        if len(current) + len(piece) <= max_chars:
            current += piece
            continue
        if current:
            chunks.append(current)
        if len(piece) <= max_chars:
            current = piece
        else:
            # A single oversized section: fixed windows with overlap.
            start = 0
            while start < len(piece):
                chunks.append(piece[start : start + max_chars])
                start += max_chars - overlap
            current = ""
    if current:
        chunks.append(current)

    return [c for c in chunks if c.strip()]


# --------------------------------------------------------------------------
# Prompts
# --------------------------------------------------------------------------


def _header(meta: PaperMetadata, part: int, total: int) -> str:
    bits = [f"Title: {meta.title}"] if meta.title else []
    if meta.authors:
        bits.append(f"Authors: {', '.join(meta.authors[:8])}")
    if meta.year:
        bits.append(f"Year: {meta.year}")
    if total > 1:
        bits.append(f"(This is part {part} of {total} of the paper's text.)")
    return "\n".join(bits)


def build_extraction_prompt(text: str, meta: PaperMetadata, *, part: int = 1, total: int = 1) -> str:
    """The first-pass prompt.

    The paper text is untrusted: it comes from a PDF someone else wrote, and a
    PDF can contain instructions addressed to whatever reads it. It goes inside
    the sanitizer's boundary tags for the same reason fetched URLs do.
    """
    bounded = sanitize_for_prompt(text, max_chars=len(text) + 1)
    return (
        f"{_header(meta, part, total)}\n\n"
        f"{bounded}\n\n"
        "Extract the structured review of the text above, as JSON in exactly this shape:\n\n"
        f"{_SCHEMA_BLOCK}\n\n"
        "Every quote must be copied verbatim from the text above. Output only the JSON object."
    )


def build_retry_prompt(rejections: list[dict[str, str]], text: str, meta: PaperMetadata) -> str:
    """The coached retry: hand back exactly what failed, and why.

    Only the rejected claims are re-asked. Re-asking for everything would invite
    the model to restate what already verified, and the verified claims are not
    in question.
    """
    lines = []
    for r in rejections[:20]:
        lines.append(f"- [{r.get('field', '?')}] {r.get('claim', '')}\n    quote given: {r.get('quote', '')}")
        lines.append(f"    rejected: {r.get('reason', '')}")

    bounded = sanitize_for_prompt(text, max_chars=len(text) + 1)
    return (
        f"{_header(meta, 1, 1)}\n\n"
        f"{bounded}\n\n"
        "These claims were rejected because their quotes could not be found in the text above:\n\n"
        + "\n".join(lines)
        + "\n\nFor each one, either supply the correct verbatim quote from the text, or omit it "
        "because the paper does not state it. Omitting is the right answer when the paper does "
        "not say it — a wrong quote is worse than a missing claim.\n\n"
        "Return ONLY the corrected claims, as JSON in this shape (include only fields you are "
        f"correcting):\n\n{_SCHEMA_BLOCK}"
    )


# --------------------------------------------------------------------------
# The extractor
# --------------------------------------------------------------------------


async def _one_call(
    backend: LLMBackend,
    prompt: str,
    *,
    paper_id: str | None,
) -> tuple[dict[str, Any] | None, TokenUsage, str]:
    """One tool-less completion, parsed. Never raises."""
    try:
        result = await backend.tool_loop(
            system=_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            tools=[],
            tool_handler=None,
            max_turns=2,
            paper_id=paper_id,
            specialist="literature_extractor",
        )
    except Exception as e:  # a backend failure is not an extraction verdict
        logger.warning("extract: backend call failed: %s", e)
        return None, TokenUsage(), f"backend error: {e}"

    if not result.success:
        return None, result.usage, result.error or "backend reported failure"

    payload = extract_json(result.output)
    if payload is None:
        return None, result.usage, "model output was not JSON"
    return payload, result.usage, ""


async def extract_review(
    text: str,
    meta: PaperMetadata,
    backend: LLMBackend,
    *,
    model: str = "",
    max_retries: int = 1,
    paper_id: str | None = None,
) -> ExtractionResult:
    """Extract a verified structured review from a paper's full text.

    Returns a review containing only claims whose quotes were located in
    ``text``. Partial success is success: five checkable claims are worth more
    than twelve unchecked ones, and an empty result is reported honestly rather
    than padded.
    """
    review = StructuredReview(
        paper_id=paper_id or "",
        title=meta.title,
        authors=list(meta.authors),
        year=meta.year,
        doi=(meta.doi or "").strip().lower().removeprefix("https://doi.org/"),
        source=meta.source,
    )
    out = ExtractionResult(review=review)

    if len(normalize(text)) < MIN_SOURCE_CHARS:
        out.error = f"source text too short to extract from ({len(normalize(text))} chars)"
        stamp(review, source_text=text, model=model)
        return out

    chunks = chunk_source(text)
    logger.info("extract: %s — %d chars, %d chunk(s)", meta.title[:60] or "untitled", len(text), len(chunks))

    # ---- first pass, once per chunk -------------------------------------
    attempt = ExtractionAttempt(index=0)
    for i, chunk in enumerate(chunks, start=1):
        payload, usage, err = await _one_call(
            backend, build_extraction_prompt(chunk, meta, part=i, total=len(chunks)), paper_id=paper_id
        )
        out.usage = out.usage + usage
        if payload is None:
            attempt.error = (attempt.error + f"; chunk {i}: {err}").lstrip("; ")
            continue
        attempt.parsed = True
        merge_reviews(review, review_from_model_output(payload))

    if not attempt.parsed:
        out.error = attempt.error or "no chunk produced parseable output"
        out.attempts.append(attempt)
        stamp(review, source_text=text, model=model)
        return out

    # Verification always runs against the WHOLE text, never the chunk a claim
    # came from. A quote is either in the paper or it is not.
    report = verify_review(review, text)
    attempt.proposed = report.total
    attempt.verified = report.verified
    attempt.rejected = report.rejected
    attempt.rejections = list(report.rejections)
    out.attempts.append(attempt)

    # ---- coached retry, once ---------------------------------------------
    for n in range(max_retries):
        if not report.rejections:
            break
        retry = ExtractionAttempt(index=n + 1)
        payload, usage, err = await _one_call(
            backend, build_retry_prompt(report.rejections, text, meta), paper_id=paper_id
        )
        out.usage = out.usage + usage
        if payload is None:
            retry.error = err
            out.attempts.append(retry)
            break

        retry.parsed = True
        repaired = review_from_model_output(payload)
        repaired_report = verify_review(repaired, text)
        retry.proposed = repaired_report.total
        retry.verified = repaired_report.verified
        retry.rejected = repaired_report.rejected
        retry.rejections = list(repaired_report.rejections)
        out.attempts.append(retry)

        # Only verified repairs are merged. A repair that failed again is a
        # second guess at the same claim and gets no third chance.
        drop_unverified(repaired)
        drop_unverified(review)
        merge_reviews(review, repaired)
        report = verify_review(review, text)

    # ---- settle -----------------------------------------------------------
    drop_unverified(review)
    out.verification = verify_review(review, text)
    # Offers discarded, not distinct claims: a claim rejected on the first pass
    # and re-offered on the retry was offered twice. Computed rather than
    # accumulated, because drop_unverified() already ran inside the retry loop
    # and its return value there is not the total.
    out.dropped = max(0, out.proposed - out.verification.verified)
    stamp(review, source_text=text, model=model)

    logger.info(
        "extract: %s — %d proposed, %d kept, %d dropped",
        meta.title[:60] or "untitled",
        out.proposed,
        out.verification.verified,
        out.dropped,
    )
    return out
