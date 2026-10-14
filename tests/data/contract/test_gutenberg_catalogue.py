"""Project Gutenberg searches: cached per query, a timeout on Gutendex, and PG's catalogue file instead.

The weather-words demo (2026-10-13) waited 78 s per Gutendex page; each
100-320-row catalogue search took about ten minutes. All requests are mocked.
"""

from __future__ import annotations

import asyncio
import gzip
import json
from pathlib import Path

import httpx
import pytest
import respx

from src.modules.data import cli
from src.modules.data.sources import gutenberg

PID = "gutenberg-catalogue-test"
CSV = (
    "Text#,Type,Issued,Title,Language,Authors,Subjects,LoCC,Bookshelves\n"
    '1342,Text,1998-06-01,Pride and Prejudice,en,"Austen, Jane, 1775-1817",'
    '"Courtship -- Fiction; England -- Fiction",PR,"Best Books Ever Listings; Category: Novels"\n'
    '84,Text,1993-10-01,"Frankenstein; Or, The Modern Prometheus",en,"Shelley, Mary Wollstonecraft, 1797-1851",'
    '"Science fiction; Monsters -- Fiction",PR,"Gothic Fiction; Category: Novels"\n'
    '17489,Text,2006-01-01,Les misérables,fr,"Hugo, Victor, 1802-1885","Historical fiction",PQ,"Category: Novels"\n'
    '1,Text,1971-12-01,The Declaration of Independence,en,"Jefferson, Thomas, 1743-1826",History,E201,Politics\n'
    "99999,Sound,2020-01-01,An audio book,en,,,,\n"
)
SLOW_PAGE = {"count": 1, "next": None, "results": [{"id": 1342, "title": "Pride and Prejudice", "authors": []}]}


@pytest.fixture(autouse=True)
def _env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr("src.modules.data.sources.http.PACING", False)
    monkeypatch.setenv("E2ER_WORKSPACE_ROOT", str(tmp_path / "ws"))
    monkeypatch.setenv("E2ER_CACHE_DIR", str(tmp_path / "cache"))
    from src import config

    monkeypatch.setattr(config, "get_settings", lambda: config.Settings(_env_file=None))
    monkeypatch.setattr(gutenberg, "GUTENDEX_TIMEOUT", 0.2)
    w = tmp_path / "ws" / PID
    w.mkdir(parents=True)
    return w


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, dict]:
    code = cli.main(["--paper-id", PID, *argv])
    return code, json.loads(capsys.readouterr().out)


CALLS = {"gutendex": 0}


async def _slow(request: httpx.Request) -> httpx.Response:
    CALLS["gutendex"] += 1
    await asyncio.sleep(2)
    return httpx.Response(200, json=SLOW_PAGE)


def _mock_catalogue() -> respx.Route:
    return respx.get(gutenberg.CATALOGUE_CSV).mock(
        return_value=httpx.Response(200, content=gzip.compress(CSV.encode()))
    )


@respx.mock
def test_a_slow_gutendex_search_reads_the_catalogue_file_instead(capsys) -> None:
    CALLS["gutendex"] = 0
    respx.get(gutenberg.GUTENDEX).mock(side_effect=_slow)
    catalogue = _mock_catalogue()
    code, out = _run(["gutenberg", "books", "--search", "austen pride", "--languages", "en", "--table", "b"], capsys)
    assert code == 0, out
    assert [r["id"] for r in out["items"]] == [1342]
    row = out["items"][0]
    assert row["authors"] == "Austen, Jane" and row["author_birth_year"] == 1775 and row["copyright"] is None
    assert "did not answer within" in out["note"] and "pg_catalog.csv" in out["note"]
    assert CALLS["gutendex"] == 1 and catalogue.call_count == 1
    # Within the hour another search goes to the catalogue file directly (downloaded once that day).
    code, out = _run(["gutenberg", "books", "--topic", "gothic", "--table", "g"], capsys)
    assert code == 0 and [r["id"] for r in out["items"]] == [84]
    assert CALLS["gutendex"] == 1 and catalogue.call_count == 1


@respx.mock
def test_a_search_is_kept_for_the_day(capsys) -> None:
    route = respx.get(gutenberg.GUTENDEX).mock(return_value=httpx.Response(200, json=SLOW_PAGE))
    assert _run(["gutenberg", "books", "--search", "pride", "--table", "a"], capsys)[0] == 0
    code, out = _run(["gutenberg", "books", "--search", "pride", "--table", "b"], capsys)
    assert code == 0 and out["items"][0]["id"] == 1342
    assert route.call_count == 1


@respx.mock
def test_both_unreachable_says_so_plainly(capsys) -> None:
    respx.get(gutenberg.GUTENDEX).mock(side_effect=_slow)
    respx.get(gutenberg.CATALOGUE_CSV).mock(return_value=httpx.Response(503))
    code, out = _run(["gutenberg", "books", "--search", "austen", "--table", "b"], capsys)
    assert code != 0
    assert "did not answer within" in out["error"] and "catalogue file could not be read either" in out["error"]
    assert "Try again later" in out["error"]


@respx.mock
def test_a_slow_gutendex_text_load_stops_with_a_plain_message(capsys) -> None:
    respx.get(gutenberg.GUTENDEX).mock(side_effect=_slow)
    code, out = _run(["gutenberg", "text", "--ids", "1342", "--table", "t"], capsys)
    assert code != 0
    assert "did not answer within" in out["error"] and "No text was loaded" in out["error"]


def test_catalogue_rows_follow_gutendex_filters() -> None:
    import io

    def ids(**q) -> list[int]:
        return [r["id"] for r in gutenberg.catalogue_rows(io.StringIO(CSV), q, 100)]

    assert ids(search="shelley frankenstein") == [84]
    assert ids(languages="fr") == [17489]
    assert ids(languages="en,fr") == [1, 84, 1342, 17489, 99999]
    assert ids(topic="fiction") == [84, 1342, 17489]
    assert ids(author_year_start=1820) == [1, 84, 17489]  # alive at or after 1820 (Jefferson died 1826)
    assert ids(author_year_end=1780) == [1, 1342]  # born by 1780
    assert ids(ids="84,1") == [1, 84]
    assert ids(topic="novels", sort="descending") == [17489, 1342, 84]
    [audio] = [r for r in gutenberg.catalogue_rows(io.StringIO(CSV), {"ids": "99999"}, 5)]
    assert audio["has_plain_text"] is False and audio["authors"] is None


def test_author_years_are_read_off_the_name() -> None:
    assert gutenberg._author("Austen, Jane, 1775-1817") == ("Austen, Jane", 1775, 1817)
    assert gutenberg._author("Homer, 751? BCE-651? BCE") == ("Homer", -751, -651)
    assert gutenberg._author("Twain, Mark, 1835-1910 [Editor]") == ("Twain, Mark", 1835, 1910)
    assert gutenberg._author("Anonymous") == ("Anonymous", None, None)
