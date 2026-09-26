"""The corpus, reachable without a terminal.

Everything the corpus does was CLI-only, which meant that for anyone who
reaches E2ER by typing `e2er` and getting a dashboard — the normal case — it did
not exist. Searching your own library by claim is the thing E2ER does that
nothing else does, and it was invisible.

The states that matter are the two ends: a first run with no library at all,
which must read as a starting point rather than a fault, and a real library with
a search that finds a sentence.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.app import app
from src.modules.literature import corpus
from src.modules.literature.review import Claim, Evidence, StructuredReview, stamp, verify_review

SOURCE = (
    "We find no detectable change in the equity loading of bitcoin following the listing. "
    "Our control group consists of never-listed cryptocurrencies."
)
FINDING = "We find no detectable change in the equity loading of bitcoin"


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _review(doi: str = "10.1/a", title: str = "Spot ETFs and bitcoin") -> StructuredReview:
    r = StructuredReview(
        title=title,
        authors=["A. Author"],
        year=2024,
        doi=doi,
        key_findings=[Claim(text="No change in equity loading.", evidence=Evidence(quote=FINDING, locator="Results"))],
    )
    stamp(r, source_text=SOURCE, model="test-model")
    verify_review(r, SOURCE)
    return r


@pytest.fixture
def library(tmp_path: Path, monkeypatch) -> Path:
    db = tmp_path / "corpus.db"
    with corpus.connect(db) as conn:
        corpus.add_review(conn, _review())
    monkeypatch.setattr("src.modules.literature.corpus.corpus_path", lambda explicit=None: db)
    return db


@pytest.fixture
def no_library(tmp_path: Path, monkeypatch) -> Path:
    absent = tmp_path / "absent.db"
    monkeypatch.setattr("src.modules.literature.corpus.corpus_path", lambda explicit=None: absent)
    return absent


# ---------------------------------------------------------------------------
# First run
# ---------------------------------------------------------------------------


def test_no_library_is_a_starting_point_not_an_error(client, no_library):
    r = client.get("/library")

    assert r.status_code == 200
    assert "No library yet" in r.text
    assert "e2er corpus add" in r.text, "tell them the one command that fixes it"


def test_looking_at_an_empty_library_does_not_create_one(client, no_library):
    """connect() creates the file it is given; a page view must not."""
    client.get("/library")
    assert not no_library.exists()


# ---------------------------------------------------------------------------
# A real library
# ---------------------------------------------------------------------------


def test_the_library_lists_its_papers(client, library):
    r = client.get("/library")

    assert r.status_code == 200
    assert "Spot ETFs and bitcoin" in r.text
    assert "checked claims" in r.text


def test_searching_returns_the_sentence_not_just_the_paper(client, library):
    """The whole point: a bibliography cannot answer "who found X"."""
    r = client.get("/library", params={"q": "equity loading"})

    assert r.status_code == 200
    assert FINDING in r.text, "the verbatim quote must be on the page"
    assert "Results" in r.text, "and where in the paper it came from"


def test_a_search_with_no_matches_explains_how_search_works(client, library):
    r = client.get("/library", params={"q": "quantum teleportation"})

    assert r.status_code == 200
    assert "Nothing matches" in r.text
    assert "not the title" in r.text, "the likely misunderstanding, addressed"


def test_a_punctuated_query_does_not_500(client, library):
    """Raw user text is not a legal FTS5 expression; the page must survive it."""
    for q in ["null effects (ETF)", 'a "quoted" phrase', "difference-in-differences", "*", "AND OR"]:
        assert client.get("/library", params={"q": q}).status_code == 200


def test_an_unreadable_library_does_not_break_the_dashboard(client, tmp_path, monkeypatch):
    broken = tmp_path / "corpus.db"
    broken.write_bytes(b"this is not a database")
    monkeypatch.setattr("src.modules.literature.corpus.corpus_path", lambda explicit=None: broken)

    r = client.get("/library")

    assert r.status_code == 200
    assert "could not be read" in r.text


def test_the_library_is_reachable_from_every_page(client, library):
    """A feature nobody can navigate to is a feature nobody has."""
    assert "/library" in client.get("/").text
