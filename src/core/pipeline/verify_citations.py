"""Programmatic citation-integrity gate — anti-hallucination for references.

The biggest credibility killer for an AI-written paper is a fake
citation: a plausibly-named author + year + title that doesn't
correspond to any real paper. Reviewers catch this only sometimes,
late, and at high token cost. This module catches it mechanically.

What it does:

1. Parse every ``\\cite{key}`` (and the natbib / biblatex variants
   ``\\citep``, ``\\citet``, ``\\citeauthor``, ``\\citeyear``,
   ``\\autocite``, ``\\textcite``) from the LaTeX draft. Also parses
   ``\\bibitem{key}`` for hand-rolled ``thebibliography`` blocks.
2. Load ``references.bib`` and index it by cite-key.
3. For each cited key, verify the entry exists in the real world via
   a verifier chain — OpenAlex by DOI, Semantic Scholar by DOI,
   Crossref by DOI; then OpenAlex / S2 / Crossref title search with
   a fuzzy-match cutoff. First hit wins.
4. Emit ``citation_integrity.json`` with one record per key:
   status, verifier source, matched DOI/title, the original bib
   entry, and a one-line explanation if unverifiable.
5. Coverage: cited keys not in the bib (``missing_in_bib``) and bib
   entries that were never cited (``bibbed_uncited``).

Pattern: mirrors :mod:`verify_numbers` — deterministic, no LLM
calls. Runs BEFORE reviewers in the pipeline so a hallucinated
cite rejects the draft at the audit gate instead of slipping
through to publication.

Open design choice (v0.9 plan, M2): hard-block vs warn-only on
``unverifiable`` cites. Default: ``unverifiable`` is warn-only
(working papers, preprints, conference posters legitimately aren't
in OpenAlex/S2/Crossref); ``missing_in_bib`` is always hard-block
(unambiguous — LaTeX would have failed too). Flip the default with
``E2ER_STRICT_CITATION_INTEGRITY=true`` in the environment.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from ...logging_config import get_logger
from ...modules.literature import crossref, openalex, semantic_scholar
from ...modules.literature.models import PaperMetadata

logger = get_logger(__name__)


# Statuses for a single cited key. Order matters for the verdict.
STATUS_VERIFIED_DOI = "verified_doi"
STATUS_VERIFIED_TITLE = "verified_title"
STATUS_UNVERIFIABLE = "unverifiable"
STATUS_MISSING_IN_BIB = "missing_in_bib"


@dataclass
class CitationCheck:
    """One cited key's verification result."""

    cite_key: str
    status: str  # see STATUS_* constants
    verifier: str = ""  # "openalex" | "semantic_scholar" | "crossref" | "" if unresolved
    matched_doi: str = ""
    matched_title: str = ""
    bib_title: str = ""
    bib_year: int | None = None
    bib_doi: str = ""
    explanation: str = ""  # one-liner for unverifiable / missing


@dataclass
class CitationIntegrityReport:
    """Result of the citation-integrity gate."""

    passed: bool = True
    total_cites: int = 0
    verified: int = 0
    unverifiable: int = 0
    missing_in_bib: int = 0
    bibbed_uncited: list[str] = field(default_factory=list)
    checks: list[CitationCheck] = field(default_factory=list)
    skipped_reason: str | None = None
    strict: bool = False

    @property
    def conclusive(self) -> bool:
        """Did the gate reach a definite verdict on every cite it looked at?

        `passed` is the gating decision and, in warn mode, stays True with any
        number of unverifiable cites — deliberately, because working papers
        and posters legitimately aren't indexed. That makes `passed` alone
        unsafe to read as "the citations are sound": the 2026-08-05 validation
        cell reported passed=True with 11 of 18 cites unverifiable. This
        carries the missing half of that sentence. Derived, not stored, so it
        cannot drift from the counts it summarises.
        """
        return self.total_cites > 0 and self.unverifiable == 0

    def to_dict(self) -> dict[str, Any]:
        # `conclusive` is a property, so asdict() misses it — and the saved
        # JSON is what reviewers and the experiment harvester read.
        return {**asdict(self), "conclusive": self.conclusive}

    @property
    def unverifiable_checks(self) -> list[CitationCheck]:
        return [c for c in self.checks if c.status == STATUS_UNVERIFIABLE]

    @property
    def missing_checks(self) -> list[CitationCheck]:
        return [c for c in self.checks if c.status == STATUS_MISSING_IN_BIB]


# ── Parsing ──────────────────────────────────────────────────────────────────


# Every LaTeX citation command we know about. Group 1 is the key list.
# ``\\cite``, ``\\citep``, ``\\citet``, ``\\citeauthor``, ``\\citeyear``,
# ``\\citealp``, ``\\citealt``, ``\\autocite``, ``\\textcite`` plus
# starred variants (``\\cite*``) and biblatex's ``\\parencite``.
# Optional ``[prenote][postnote]`` brackets are allowed before the key
# brace — we just skip them.
_CITE_CMDS = (
    r"cite|citep|citet|citeauthor|citeyear|citealp|citealt|"
    r"autocite|textcite|parencite|smartcite|footcite|fullcite"
)
_CITE_RE = re.compile(
    r"\\(?:" + _CITE_CMDS + r")\*?"
    r"(?:\[[^\]]*\]){0,2}"  # optional [prenote] / [postnote]
    r"\{([^}]+)\}"
)

# Hand-rolled thebibliography environments — ``\\bibitem{key}``.
_BIBITEM_RE = re.compile(r"\\bibitem(?:\[[^\]]*\])?\{([^}]+)\}")

# End-of-environment marker — bounds the last bibitem's body.
_END_THEBIB_RE = re.compile(r"\\end\{thebibliography\}")

# DOI matcher for in-body DOI text. Accepts ``doi:`` / ``DOI:`` prefixes and
# ``https://doi.org/`` URLs. Trailing punctuation is stripped later.
_INBODY_DOI_RE = re.compile(
    r"(?:doi:|DOI:|https?://(?:dx\.)?doi\.org/)?(10\.\d{4,9}/[-._;()/:A-Za-z0-9]+)",
)

# A 4-digit year wrapped in parentheses — the canonical author-block
# terminator in in-tex APA/Chicago bibliographies. Captures the year.
_BODY_YEAR_RE = re.compile(r"\((\d{4})[a-z]?\)\.?\s*")

# Year in the bibitem ``[label]`` — fallback when the body's author block
# uses a different format (``Welch and Goyal, 2008.`` instead of ``(2008)``).
_LABEL_YEAR_RE = re.compile(r"\((\d{4})[a-z]?\)")

# Italic/emph markup that almost always wraps the journal name. Used to
# bound the title on the right.
_JOURNAL_MARK_RE = re.compile(r"\\(?:textit|emph|textbf)\{")

# LaTeX text-style commands whose content is plain text we want to keep:
# ``\textit{Review of Financial Studies}`` → ``Review of Financial Studies``.
_LATEX_TEXT_CMD_RE = re.compile(r"\\(?:textit|emph|textbf|texttt|textsc)\{([^}]*)\}")


def parse_cite_keys(tex: str) -> list[str]:
    """Return every cite-key referenced in the LaTeX source, in order
    of first appearance. Comma-separated key lists are split."""
    seen: dict[str, None] = {}  # dict preserves insertion order, dedupes
    for m in _CITE_RE.finditer(_strip_comments(tex)):
        for key in m.group(1).split(","):
            key = key.strip()
            if key:
                seen.setdefault(key, None)
    return list(seen.keys())


def parse_bibitem_keys(tex: str) -> list[str]:
    """Return every ``\\bibitem`` key, in order. For hand-rolled
    bibliographies (no ``.bib`` file)."""
    seen: dict[str, None] = {}
    for m in _BIBITEM_RE.finditer(_strip_comments(tex)):
        key = m.group(1).strip()
        if key:
            seen.setdefault(key, None)
    return list(seen.keys())


def parse_bibitem_entries(tex: str) -> dict[str, dict]:
    """Parse a hand-rolled ``thebibliography`` block into a bib-shaped
    dict — ``{cite_key: {"title", "year", "doi"}}``.

    Pre-M4.2 the citation gate's fallback for ``\\bibitem``-only papers
    constructed entries with empty titles, so every cite came back
    ``unverifiable`` with no real verifier call. The M4 live test
    surfaced this: the Welch-Goyal replication's draft had 9 cites and
    0 went to OpenAlex/S2/Crossref because the body text was discarded.

    What we parse from each entry body:

    - **DOI** — first ``10.xxxx/yyyy`` match anywhere in the body, with
      optional ``doi:`` / ``https://doi.org/`` prefix. Trailing
      punctuation stripped.
    - **Year** — the first ``(YYYY)`` after the cite-key, falling back
      to the year in the ``[label]`` if no parenthesised year appears
      in the body.
    - **Title** — the chunk between the closing ``(YYYY).`` of the
      author block and the next ``\\textit{`` / ``\\emph{`` (which
      almost always wraps the journal name). Falls back to "first
      sentence after the year" when no italic journal marker is
      present.

    The verifier chain only needs *something* in ``bib_title`` /
    ``bib_doi`` to start working — even a noisy title with trailing
    punctuation is enough for the OpenAlex title-search to find the
    canonical paper.
    """
    cleaned = _strip_comments(tex)
    matches = list(_BIBITEM_RE.finditer(cleaned))
    if not matches:
        return {}

    end_match = _END_THEBIB_RE.search(cleaned)
    end_pos = end_match.start() if end_match else len(cleaned)

    out: dict[str, dict] = {}
    for i, m in enumerate(matches):
        cite_key = m.group(1).strip()
        if not cite_key:
            continue
        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else end_pos
        body_raw = cleaned[body_start:body_end]

        # Strip ``\textit{Foo}`` → ``Foo`` so the journal name is plain
        # text in subsequent regex passes. Done early so the journal-
        # marker bound (still present in ``body_raw``) can be used as
        # the title's right edge BEFORE the strip.
        journal_cut = _JOURNAL_MARK_RE.search(body_raw)
        journal_pos = journal_cut.start() if journal_cut else len(body_raw)

        body_clean = _LATEX_TEXT_CMD_RE.sub(r"\1", body_raw)
        body_collapsed = " ".join(body_clean.split())

        # DOI — anywhere in the body. Strip trailing punctuation that
        # regex matchers commonly include.
        doi = ""
        dm = _INBODY_DOI_RE.search(body_collapsed)
        if dm:
            doi = dm.group(1).rstrip(".,;)")

        # Year — body first, then [label].
        year_match = _BODY_YEAR_RE.search(body_collapsed)
        if year_match:
            year_str: str = year_match.group(1)
            year_end_in_collapsed = year_match.end()
        else:
            label_y = _LABEL_YEAR_RE.search(m.group(0))
            year_str = label_y.group(1) if label_y else ""
            year_end_in_collapsed = 0  # title-cut falls through

        # Title — the chunk between the closing ``(YYYY).`` and the
        # journal marker (whichever comes first). Re-cut on the
        # collapsed string by recomputing the journal-marker position
        # there; if the body had no italic marker, fall back to first
        # sentence after the year.
        title = ""
        if year_end_in_collapsed:
            after_year = body_collapsed[year_end_in_collapsed:]
            # If there's an italic-wrapped journal name in body_raw, the
            # right edge of the title is the start of that block. We
            # already stripped the markup in body_clean, but the journal
            # *content* is still a distinctive substring — find its
            # position in the collapsed body and cut there.
            right_edge = len(after_year)
            if journal_cut:
                inside = _LATEX_TEXT_CMD_RE.match(body_raw, journal_pos)
                if inside:
                    journal_text = " ".join(inside.group(1).split())
                    idx = after_year.find(journal_text)
                    if idx >= 0:
                        right_edge = idx
            title = after_year[:right_edge].strip()
            # Drop trailing punctuation / comma before the journal name.
            title = title.rstrip(" .,;:—-")
            # Reject obviously-broken titles (single char, no spaces, etc.)
            if len(title) < 5 or not any(c.isalpha() for c in title):
                title = ""
        if not title:
            # Last-ditch fallback: whole body up to the journal marker,
            # less the author block. Noisy but the OpenAlex title-search
            # tolerates noise.
            if year_match:
                title = body_collapsed[year_end_in_collapsed:].rstrip(" .,;:—-")
            else:
                title = body_collapsed.rstrip(" .,;:—-")

        out[cite_key] = {"title": title, "year": year_str, "doi": doi}
    return out


def _strip_comments(tex: str) -> str:
    """Strip LaTeX line comments (``% ...`` to end-of-line), preserving
    escaped percent signs (``\\%``). Cite keys inside comments don't
    count — same rule LaTeX itself follows.
    """
    out: list[str] = []
    for line in tex.splitlines(keepends=True):
        i = 0
        while i < len(line):
            ch = line[i]
            if ch == "\\" and i + 1 < len(line):
                # Escaped char — copy both and skip past.
                out.append(line[i : i + 2])
                i += 2
                continue
            if ch == "%":
                # Comment runs to end of line — keep the newline so line
                # numbers stay meaningful; drop the body.
                nl_idx = line.find("\n", i)
                if nl_idx >= 0:
                    out.append(line[nl_idx:])
                break
            out.append(ch)
            i += 1
    return "".join(out)


def load_bib(bib_path: Path) -> dict[str, dict]:
    """Load a ``.bib`` file and return ``{cite_key: fields_dict}``.

    Uses bibtexparser v2 directly (the existing
    ``literature/bibtex.py`` helper drops the cite-key, which we
    need). Returns an empty dict if the file is missing or
    unparseable — caller treats absence as "no bib gate" (skip)
    rather than "bib failure".
    """
    if not bib_path.is_file():
        return {}
    try:
        import bibtexparser

        library = bibtexparser.parse_file(str(bib_path))
    except Exception as e:
        logger.warning("verify_citations: failed to parse %s: %s", bib_path, e)
        return {}

    out: dict[str, dict] = {}
    for entry in library.entries:
        # bibtexparser v2: `entry.key` is the cite-key; `fields_dict`
        # maps field-name → Field(value=...).
        try:
            fields = {k: v.value for k, v in entry.fields_dict.items()}
        except Exception:  # noqa: BLE001 — malformed entry; skip
            continue
        out[entry.key] = fields
    return out


# ── Verifier chain ───────────────────────────────────────────────────────────


def _normalize_doi(doi: str) -> str:
    doi = (doi or "").strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if doi.startswith(prefix):
            doi = doi[len(prefix) :]
            break
    return doi


_TITLE_PUNCT_RE = re.compile(r"[^a-z0-9\s]")


def _normalize_title(title: str) -> str:
    """Lower-case, strip accents, drop punctuation, collapse whitespace.
    LaTeX title fields routinely contain ``{...}`` braces, math, and
    em-dashes — we want a comparison key that's stable across those.
    """
    # Strip braces / NFC-decompose accents first.
    title = title.replace("{", "").replace("}", "")
    title = unicodedata.normalize("NFKD", title)
    title = "".join(c for c in title if not unicodedata.combining(c))
    title = title.lower()
    title = _TITLE_PUNCT_RE.sub(" ", title)
    return " ".join(title.split())


# Fuzzy-match cutoff for title verification. 0.85 catches abbreviation
# vs full-form ("PNAS" vs "Proceedings of the National Academy of
# Sciences"), missing subtitles, and minor punctuation drift without
# matching unrelated papers. Tightened from 0.80 after spot-checking
# false positives on AER + JF titles.
_TITLE_MATCH_CUTOFF = 0.85


def _title_similar(a: str, b: str) -> float:
    """Similarity in [0, 1] between two titles after normalization."""
    a_n = _normalize_title(a)
    b_n = _normalize_title(b)
    if not a_n or not b_n:
        return 0.0
    return SequenceMatcher(None, a_n, b_n).ratio()


async def _verify_one(
    cite_key: str,
    bib_entry: dict,
    *,
    doi_first: bool = True,
) -> CitationCheck:
    """Run the verifier chain for one bib entry. Returns a populated
    CitationCheck with status = verified_doi / verified_title /
    unverifiable.
    """
    bib_title = (bib_entry.get("title") or "").strip("{} ")
    bib_year = _coerce_year(bib_entry.get("year"))
    bib_doi = _normalize_doi(bib_entry.get("doi", ""))

    check = CitationCheck(
        cite_key=cite_key,
        status=STATUS_UNVERIFIABLE,
        bib_title=bib_title,
        bib_year=bib_year,
        bib_doi=bib_doi,
    )

    # --- DOI verifier chain (OpenAlex → S2 → Crossref) ---
    if doi_first and bib_doi:
        for source_name, fetch in (
            ("openalex", openalex.fetch_by_doi),
            ("semantic_scholar", semantic_scholar.fetch_by_doi),
            ("crossref", crossref.fetch_by_doi),
        ):
            try:
                paper = await fetch(bib_doi)
            except Exception as e:  # noqa: BLE001 — verifier outages are normal
                logger.debug("verify_citations: %s DOI lookup failed for %s: %s", source_name, bib_doi, e)
                paper = None
            if paper and paper.title:
                check.status = STATUS_VERIFIED_DOI
                check.verifier = source_name
                check.matched_doi = paper.doi or bib_doi
                check.matched_title = paper.title
                return check

    # --- Title-search fallback (OpenAlex → S2 → Crossref) ---
    if bib_title:
        for source_name, search in (
            ("openalex", openalex.search_papers),
            ("semantic_scholar", semantic_scholar.search_papers),
            ("crossref", crossref.search_papers),
        ):
            try:
                # limit=10 (not 5) — for very-common titles like
                # "Attention Is All You Need", recent reprints and
                # derivative entries can crowd out the canonical
                # paper from the top 5.
                result = await search(bib_title, limit=10)
            except Exception as e:  # noqa: BLE001
                logger.debug("verify_citations: %s search failed for %r: %s", source_name, bib_title[:80], e)
                continue
            match = _pick_title_match(result.papers, bib_title, bib_year)
            if match is not None:
                check.status = STATUS_VERIFIED_TITLE
                check.verifier = source_name
                check.matched_doi = match.doi or ""
                check.matched_title = match.title
                return check

    # Nothing matched.
    if not bib_title and not bib_doi:
        check.explanation = "bib entry has neither title nor DOI — nothing to verify"
    elif not bib_title:
        check.explanation = "DOI not found in OpenAlex / S2 / Crossref; no title to fall back on"
    elif not bib_doi:
        check.explanation = (
            f"no title match (>{_TITLE_MATCH_CUTOFF:.2f} similarity) for {bib_title[:80]!r} in any verifier"
        )
    else:
        check.explanation = "DOI not in any verifier and no title match above cutoff"
    return check


def _pick_title_match(
    papers: list[PaperMetadata],
    bib_title: str,
    bib_year: int | None,
) -> PaperMetadata | None:
    """Pick the best title match above the cutoff.

    Year-gate is graduated by match strength: exact title matches
    (sim ≥ 0.99) accept any year — identical titles are almost
    certainly the same paper across preprint / proceedings / reprint
    drift (live-test surfaced this on Vaswani 2017, where OpenAlex's
    top hit was a 2025 reprint of "Attention Is All You Need"). Fuzzy
    matches (cutoff ≤ sim < 0.99) still require year within ±1 to
    reject unrelated papers from different decades.
    """
    best: tuple[float, PaperMetadata] | None = None
    for p in papers:
        if not p.title:
            continue
        score = _title_similar(p.title, bib_title)
        if score < _TITLE_MATCH_CUTOFF:
            continue
        if bib_year and p.year and abs(p.year - bib_year) > 1 and score < 0.99:
            continue
        if best is None or score > best[0]:
            best = (score, p)
    return best[1] if best else None


def _coerce_year(raw: object) -> int | None:
    if raw is None:
        return None
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return None


# ── Orchestrator ─────────────────────────────────────────────────────────────


async def verify(
    draft_path: Path,
    bib_path: Path | None = None,
    *,
    strict: bool | None = None,
    concurrency: int = 4,
) -> CitationIntegrityReport:
    """Run the citation-integrity gate.

    Args:
        draft_path: paper_draft.tex (or any .tex with \\cite commands)
        bib_path: the bibliography to check against. Defaults to the first
                  existing of references.bib / refs.bib / literature.bib
                  next to the draft.
        strict: if True, ``unverifiable`` cites also fail the gate.
                None means "read from E2ER_STRICT_CITATION_INTEGRITY env".
        concurrency: parallel verifier calls (default 4 to be polite
                     to free-tier APIs).

    Returns:
        CitationIntegrityReport. ``passed=False`` iff missing-in-bib
        is present, or strict-mode is on and there are unverifiable
        cites. A draft with no ``\\cite`` calls and no bib file is
        skipped with ``passed=True`` and ``skipped_reason`` set —
        identical to the verify_numbers convention.
    """
    if strict is None:
        strict = os.getenv("E2ER_STRICT_CITATION_INTEGRITY", "").strip().lower() in {"1", "true", "yes"}

    report = CitationIntegrityReport(strict=strict)

    if not draft_path.is_file():
        report.skipped_reason = f"draft not found at {draft_path}"
        logger.warning("verify_citations: %s", report.skipped_reason)
        return report

    tex = draft_path.read_text(encoding="utf-8", errors="replace")
    cite_keys = parse_cite_keys(tex)
    bibitem_keys = parse_bibitem_keys(tex)

    if not cite_keys and not bibitem_keys:
        report.skipped_reason = "no \\cite or \\bibitem commands in draft"
        logger.info("verify_citations: %s", report.skipped_reason)
        return report

    if bib_path is None:
        # Fallback chain mirrors what the pipeline actually writes:
        # references.bib (legacy/hand-supplied) → refs.bib (assembled for
        # compile) → literature.bib (written at ingest). Before this chain
        # existed the gate looked only for references.bib — which nothing
        # in the standard flow writes — and silently skipped every paper.
        candidates = [draft_path.parent / name for name in ("references.bib", "refs.bib", "literature.bib")]
        bib_path = next((p for p in candidates if p.is_file()), candidates[0])
    bib = load_bib(bib_path)

    # Hand-rolled thebibliography: parse the \bibitem bodies (M4.2).
    # Pre-M4.2 this fell back to ``{key: {"title": ""}}`` which made
    # every cite unverifiable and effectively silenced the gate on the
    # class of paper most likely to ship hallucinated cites. We now
    # parse title / year / DOI out of the body so the verifier chain
    # has something to actually look up.
    if not bib and bibitem_keys:
        bib = parse_bibitem_entries(tex)
        # Defensive: if parse_bibitem_entries somehow missed a key the
        # cite-key parser found, fall back to an empty entry for it so
        # the cite reports as ``unverifiable`` rather than
        # ``missing_in_bib`` (LaTeX would link it fine via \bibitem).
        for k in bibitem_keys:
            bib.setdefault(k, {"title": "", "year": "", "doi": ""})

    if not bib:
        report.skipped_reason = f"no bibliography source found (.bib at {bib_path} missing and no \\bibitem in draft)"
        logger.warning("verify_citations: %s", report.skipped_reason)
        return report

    report.total_cites = len(cite_keys)

    # Coverage: bibbed but never cited (warning-only — not a failure).
    cite_key_set = set(cite_keys)
    report.bibbed_uncited = sorted(k for k in bib.keys() if k not in cite_key_set)

    # Resolve in parallel with a small concurrency budget so we don't
    # hammer the free-tier APIs.
    sem = asyncio.Semaphore(max(1, concurrency))

    async def _bounded(key: str) -> CitationCheck:
        if key not in bib:
            return CitationCheck(
                cite_key=key,
                status=STATUS_MISSING_IN_BIB,
                explanation="cited in draft but no entry in references.bib",
            )
        async with sem:
            return await _verify_one(key, bib[key])

    report.checks = await asyncio.gather(*(_bounded(k) for k in cite_keys))

    for c in report.checks:
        if c.status in (STATUS_VERIFIED_DOI, STATUS_VERIFIED_TITLE):
            report.verified += 1
        elif c.status == STATUS_UNVERIFIABLE:
            report.unverifiable += 1
        elif c.status == STATUS_MISSING_IN_BIB:
            report.missing_in_bib += 1

    # Verdict: missing_in_bib always fails. unverifiable fails only in
    # strict mode — false positives are real (working papers,
    # conference posters legitimately aren't in OpenAlex/S2/Crossref).
    report.passed = report.missing_in_bib == 0 and (not strict or report.unverifiable == 0)
    return report


async def verify_and_save(
    draft_path: Path,
    workspace: Path,
    bib_path: Path | None = None,
    *,
    strict: bool | None = None,
) -> CitationIntegrityReport:
    """Run :func:`verify` and persist the report at
    ``<workspace>/citation_integrity.json`` for reviewers + the
    dashboard.

    Async because the strategist runner calls this from inside its
    own event loop; a sync wrapper using ``asyncio.run`` would crash
    with "asyncio.run() cannot be called from a running event loop".
    """
    report = await verify(draft_path, bib_path=bib_path, strict=strict)
    output_path = workspace / "citation_integrity.json"
    output_path.write_text(
        json.dumps(report.to_dict(), indent=2, default=str),
        encoding="utf-8",
    )
    logger.info(
        "verify_citations: verified=%d unverifiable=%d missing_in_bib=%d total=%d "
        "bibbed_uncited=%d passed=%s strict=%s",
        report.verified,
        report.unverifiable,
        report.missing_in_bib,
        report.total_cites,
        len(report.bibbed_uncited),
        report.passed,
        report.strict,
    )
    return report


# ── CLI rendering ────────────────────────────────────────────────────────────


def render_human(report: CitationIntegrityReport) -> str:
    if report.skipped_reason:
        return f"⚠️  Skipped — {report.skipped_reason}"
    lines: list[str] = []
    lines.append(
        f"  {report.verified} verified · {report.unverifiable} unverifiable · "
        f"{report.missing_in_bib} missing-in-bib · {len(report.bibbed_uncited)} uncited entries"
    )
    if report.missing_checks:
        lines.append("\n  ✗ Cited keys not in references.bib (hallucinated or typo):")
        for c in report.missing_checks[:20]:
            lines.append(f"      - {c.cite_key}")
        if len(report.missing_checks) > 20:
            lines.append(f"      … and {len(report.missing_checks) - 20} more")
    if report.unverifiable_checks:
        lines.append("\n  ⚠ Unverifiable cites (in bib but no DOI/title match in OpenAlex/S2/Crossref):")
        for c in report.unverifiable_checks[:20]:
            yr = f" ({c.bib_year})" if c.bib_year else ""
            lines.append(f"      - {c.cite_key}: {c.bib_title[:80]}{yr}")
        if len(report.unverifiable_checks) > 20:
            lines.append(f"      … and {len(report.unverifiable_checks) - 20} more")
    if report.bibbed_uncited:
        lines.append(
            f"\n  · Bibliography has {len(report.bibbed_uncited)} entries that are never cited "
            "(housekeeping — not a failure)."
        )
    if report.passed and report.conclusive:
        lines.append("\n✅ Passed — every cited key resolves and exists in a verifier.")
    elif report.passed:
        # Warn mode with unverifiable cites. Not a clean bill of health: say
        # what was actually established rather than printing a bare ✅.
        lines.append(
            f"\n⚠️  Passed the gate (warn mode) but INCONCLUSIVE — "
            f"{report.unverifiable} of {report.total_cites} cites could not be verified. "
            "Set E2ER_STRICT_CITATION_INTEGRITY=1 to fail on these."
        )
    elif report.missing_in_bib:
        lines.append("\n❌ Failed — cited keys missing from references.bib (LaTeX would also fail).")
    else:
        mode = "strict mode" if report.strict else "warn mode"
        lines.append(f"\n❌ Failed — unverifiable cites under {mode}.")
    return "\n".join(lines)


def main_verify_citations(
    draft: str,
    bib: str | None = None,
    *,
    json_output: bool = False,
    strict: bool = False,
) -> int:
    """Entry point for ``e2er verify-citations``. Exit 0 iff
    report.passed."""
    draft_path = Path(draft).resolve()
    bib_path = Path(bib).resolve() if bib else None
    workspace = draft_path.parent
    report = asyncio.run(verify_and_save(draft_path, workspace, bib_path=bib_path, strict=strict))
    if json_output:
        print(json.dumps(report.to_dict(), indent=2, default=str))
    else:
        print(render_human(report))
    return 0 if report.passed else 1
