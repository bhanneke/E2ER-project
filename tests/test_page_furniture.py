"""Running heads and page numbers, removed before a quote has to match.

A sentence spanning a page break comes out of pypdf with the next page's
furniture inside it:

    "...preliminary because of difficulties 4 Chapter 1. Introduction
     with the solution concept..."

A verbatim quote of that sentence then cannot be located, and a true claim is
rejected as fabricated. Measured across a 50-paper sample, this was the largest
remaining cause of false rejection after ligatures and hyphenation — fourteen of
twenty-five rejections were quotes that are in the paper.

The danger in the other direction is deleting evidence, so the tests here are
mostly about what must NOT be removed.
"""

from __future__ import annotations

from src.modules.literature.pdf import strip_page_furniture


def _pages(*bodies: str) -> list[str]:
    return list(bodies)


def test_a_sentence_across_a_page_break_becomes_contiguous():
    """The bug, in miniature."""
    pages = _pages(
        "Chapter 1. Introduction 3\nWe view the analysis as preliminary because of difficulties",
        "4 Chapter 1. Introduction\nwith the solution concept that lie at the root.",
        "Chapter 1. Introduction 5\nFurther discussion follows in the next section here.",
        "6 Chapter 1. Introduction\nAnd a final paragraph of body text to close it.",
    )
    joined = " ".join(" ".join(p.split()) for p in strip_page_furniture(pages))

    assert "preliminary because of difficulties with the solution concept" in joined


def test_a_bare_page_number_is_removed():
    pages = _pages("Body one here.\n12", "Body two here.\n13", "Body three here.\n14")
    out = " ".join(strip_page_furniture(pages))

    assert "Body one here." in out
    assert "12" not in out and "13" not in out


def test_roman_numeral_page_numbers_are_removed():
    pages = _pages("Preface text one.\nix", "Preface text two.\nx", "Preface text three.\nxi")
    out = " ".join(strip_page_furniture(pages))

    assert "Preface text two." in out
    assert "\nix" not in out


def test_body_text_is_never_removed_however_often_it_repeats():
    """The failure that would be silent: deleting the evidence."""
    sentence = "We find no detectable change in the equity loading of bitcoin following the listing of the product."
    pages = _pages(*[f"Header {i}\n{sentence}\n{i}" for i in range(6)])
    out = " ".join(strip_page_furniture(pages))

    assert out.count(sentence) == 6, "a repeated sentence in the body is content, not furniture"


def test_a_long_line_at_the_edge_survives():
    """Furniture is short. A sentence at the top of a page is not furniture."""
    long_line = "This opening sentence runs well past ninety characters and is plainly body text, not a running head."
    pages = _pages(*[f"{long_line}\nmore body {i}" for i in range(5)])
    out = " ".join(strip_page_furniture(pages))

    assert out.count(long_line) == 5


def test_a_line_that_repeats_only_twice_is_left_alone():
    pages = _pages("Shared line\nbody a", "Shared line\nbody b", "different\nbody c", "another\nbody d")
    out = " ".join(strip_page_furniture(pages))

    assert out.count("Shared line") == 2


def test_a_short_document_is_untouched():
    """Two pages cannot establish a pattern, so nothing is inferred from them."""
    pages = _pages("Header\nbody one\n1", "Header\nbody two\n2")
    assert strip_page_furniture(pages) == pages


def test_a_running_head_whose_number_moves_is_still_recognised():
    """ "3 Chapter 1" and "7 Chapter 1" are the same running head."""
    pages = _pages(
        *[
            f"{n} Chapter 1. Introduction\nThe argument of this section proceeds in three parts, beginning with {n}."
            for n in (3, 5, 7, 9)
        ]
    )
    out = " ".join(strip_page_furniture(pages))

    assert "Chapter 1. Introduction" not in out
    assert "beginning with 7." in out


def test_a_known_limitation_a_short_numbered_edge_line_looks_like_furniture():
    """Documented, not defended.

    A running head is a short line at a page edge whose only variation is a
    number. A line of body text shaped exactly like that is indistinguishable
    from one, and gets removed. Real papers do not end successive pages with
    "body text 3" / "body text 5", so the trade is worth it — but the limit is
    real and belongs in the record rather than in a surprised bug report.
    """
    pages = _pages(*[f"Head\nbody text {n}" for n in (3, 5, 7, 9)])
    out = " ".join(strip_page_furniture(pages))

    assert "body text" not in out


def test_furniture_in_the_middle_of_a_page_is_not_touched():
    """Only page edges are eligible; a mid-page line is content by position."""
    pages = _pages(*[f"top {i}\nChapter 1\nmiddle body {i}\nChapter 1\nbottom {i}" for i in range(5)])
    out = strip_page_furniture(pages)

    assert all("Chapter 1" in p for p in out), "a mid-page occurrence must survive"


def test_empty_input_is_handled():
    assert strip_page_furniture([]) == []
    assert strip_page_furniture(["", "", ""]) == ["", "", ""]
