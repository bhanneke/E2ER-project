"""Titles read off a PDF's first page.

A truncated title is worse than a missing one. It looks right in a listing, and
it deduplicates against nothing — so the same paper arriving later from the web
is stored a second time, and the corpus quietly grows duplicates.

Found on two real arXiv PDFs, whose titles wrap onto a second line:
"HOW DECENTRALIZED IS THE GOVERNANCE OF" was the whole stored title.
"""

from __future__ import annotations

from src.modules.literature.local_pdf_meta import _title_from_first_page


def test_a_title_that_wraps_is_joined():
    page = """HOW DECENTRALIZED IS THE GOVERNANCE OF
BLOCKCHAIN-BASED FINANCE?

Johannes Rude Jensen
University of Copenhagen

Abstract
We approach the research question...
"""
    assert _title_from_first_page(page) == "HOW DECENTRALIZED IS THE GOVERNANCE OF BLOCKCHAIN-BASED FINANCE?"


def test_a_subtitle_after_a_colon_is_kept():
    page = "Short Squeeze in DeFi Lending Market:\nDecentralization in Jeopardy?\n\nLioba Heimbach\n"
    assert _title_from_first_page(page) == "Short Squeeze in DeFi Lending Market: Decentralization in Jeopardy?"


def test_a_single_line_title_is_unchanged():
    page = "Crypto Wash Trading\n\nLin William Cong\n\nAbstract\n"
    assert _title_from_first_page(page) == "Crypto Wash Trading"


def test_authors_are_not_swallowed_into_the_title():
    """The failure mode of joining too eagerly."""
    page = "Leverage and Stablecoin Pegs.\nAriah Klages-Mundt and Andreea Minca\n"
    assert _title_from_first_page(page) == "Leverage and Stablecoin Pegs."


def test_an_affiliation_line_stops_the_title():
    page = "Designing Autonomous Markets\nfor Stablecoin Monetary Policy\nCornell University\n"
    assert _title_from_first_page(page) == "Designing Autonomous Markets for Stablecoin Monetary Policy"


def test_an_email_stops_the_title():
    page = "Direct Evidence of Bitcoin\nWash Trading\nauthor@example.edu\n"
    assert _title_from_first_page(page) == "Direct Evidence of Bitcoin Wash Trading"


def test_boilerplate_before_the_title_is_skipped():
    page = "arXiv:2302.04068v2 [q-fin.TR]\nhttps://doi.org/10.1234/x\nShort Squeeze in DeFi Lending\n\nAuthor\n"
    assert _title_from_first_page(page) == "Short Squeeze in DeFi Lending"


def test_the_abstract_stops_the_title():
    page = "A Very Long Title That Wraps\nOnto A Second Line\nAbstract\nWe study...\n"
    assert _title_from_first_page(page) == "A Very Long Title That Wraps Onto A Second Line"


def test_a_page_with_no_usable_title_returns_empty():
    """The caller falls back to the filename; it must not get junk instead."""
    assert _title_from_first_page("") == ""
    assert _title_from_first_page("doi:10.1/x\nhttp://example.org\n") == ""


def test_a_runaway_title_is_bounded():
    page = "\n".join(["Word " * 20] * 10)
    assert len(_title_from_first_page(page)) < 400


# ---------------------------------------------------------------------------
# DocInfo titles that are not titles
# ---------------------------------------------------------------------------


def test_a_docinfo_title_that_is_really_a_filename_is_rejected():
    """Surfaced by putting the library on screen.

    PDF producers write whatever the authoring tool was pointed at. Two showed
    up in the first 69 papers: "C:\\Working Papers\\10449.wpd" and "base.dvi".
    Both are valid DocInfo and useless — a wrong title deduplicates against
    nothing and tells a reader nothing, so the first page is a better source.
    """
    from src.modules.literature.local_pdf_meta import _is_junk_title

    for junk in [
        "C:\\Working Papers\\10449.wpd",
        "base.dvi",
        "paper.tex",
        "submission.docx",
        "Microsoft Word - draft3.doc",
        "/Users/someone/out.ps",
        "untitled",
        "",
        "   ",
    ]:
        assert _is_junk_title(junk), f"{junk!r} should not be used as a title"


def test_a_real_title_is_kept():
    from src.modules.literature.local_pdf_meta import _is_junk_title

    for good in [
        "Crypto Wash Trading",
        "Short Squeeze in DeFi Lending Market: Decentralization in Jeopardy?",
        "Bargaining and Markets",
        "A Theory of the Firm",
    ]:
        assert not _is_junk_title(good), f"{good!r} is a perfectly good title"
