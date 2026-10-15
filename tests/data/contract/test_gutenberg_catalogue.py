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


# ── translators and authors' years stay in the table (2026-10-14 weather-words demo) ──

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _table(ws: Path, table: str) -> list[dict]:
    import sqlite3

    con = sqlite3.connect(ws / "data.db")
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute(f"SELECT * FROM {table} ORDER BY id")]
    finally:
        con.close()


def test_the_loaded_table_keeps_translators_and_the_authors_years(_env: Path, capsys) -> None:
    """Ten translated novels stayed in the demo's English corpus: the table had no translators column."""
    from src.modules.data.sources.http import use_cassette

    with use_cassette(FIXTURES / "gutenberg_translators.json", record=False):
        code, out = _run(["gutenberg", "books", "--ids", "2413,1342", "--table", "books"], capsys)
    assert code == 0, out
    pride, bovary = _table(_env, "books")
    assert bovary["id"] == 2413 and bovary["translators"] == "Aveling, Eleanor Marx (1855-1898)"
    assert bovary["authors_years"] == "Flaubert, Gustave (1821-1880)" and bovary["author_birth_year"] == 1821
    assert bovary["author_death_year"] == 1880 and bovary["languages"] == "en"
    assert "Category: French Literature" in bovary["bookshelves"]
    assert pride["translators"] is None and pride["authors_years"] == "Austen, Jane (1775-1817)"


def test_the_catalogue_file_lists_a_translator_apart_from_the_authors() -> None:
    import io

    csv_text = (
        "Text#,Type,Issued,Title,Language,Authors,Subjects,LoCC,Bookshelves\n"
        '2413,Text,2004-07-01,Madame Bovary,en,"Flaubert, Gustave, 1821-1880; '
        'Aveling, Eleanor Marx, 1855-1898 [Translator]",Adultery -- Fiction,PQ,"Category: French Literature"\n'
    )
    [row] = gutenberg.catalogue_rows(io.StringIO(csv_text), {"ids": "2413"}, 5)
    assert row["authors"] == "Flaubert, Gustave" and row["author_birth_year"] == 1821
    assert row["translators"] == "Aveling, Eleanor Marx (1855-1898)"
    assert row["authors_years"] == "Flaubert, Gustave (1821-1880)"


# ── texts load in batches, each written at once; one call stops after its time ──


def _book(i: int) -> dict:
    return {
        "id": i,
        "title": f"Book {i}",
        "authors": [{"name": "Writer, A", "birth_year": 1800, "death_year": 1870}],
        "translators": [],
        "languages": ["en"],
        "copyright": False,
        "formats": {"text/plain; charset=us-ascii": "x"},
    }


def _text(i: int) -> str:
    return (
        f"Header\n*** START OF THE PROJECT GUTENBERG EBOOK {i} ***\n"
        + f"It rained on book {i}.\n" * 50
        + f"*** END OF THE PROJECT GUTENBERG EBOOK {i} ***\nFooter\n"
    )


def _mock_texts(ids: list[int]) -> respx.Route:
    page = {"count": len(ids), "next": None, "results": [_book(i) for i in ids]}
    route = respx.get(gutenberg.GUTENDEX).mock(return_value=httpx.Response(200, json=page))
    for i in ids:
        respx.get(f"{gutenberg.MIRROR}/cache/epub/{i}/pg{i}.txt").mock(return_value=httpx.Response(200, text=_text(i)))
    return route


@respx.mock
def test_a_text_load_writes_each_batch_and_stops_at_its_time(_env: Path, capsys, monkeypatch) -> None:
    ids = [11, 12, 13, 14, 15, 16, 17]
    catalogue = _mock_texts(ids)
    written: list[int] = []
    from src.modules.data.sources import runtime

    real = runtime.table_sink

    def counting(workspace, table):
        write = real(workspace, table)

        def w(rows):
            written.append(len(rows))
            write(rows)

        return w

    monkeypatch.setattr(runtime, "table_sink", counting)
    monkeypatch.setattr(gutenberg, "CALL_SECONDS", -1)  # the time is up after the first batch
    code, out = _run(["gutenberg", "text", "--ids", ",".join(map(str, ids)), "--table", "texts"], capsys)
    assert code == 0, out
    assert [r["id"] for r in out["items"]] == [11, 12, 13, 14, 15]
    assert out["note"].startswith("INCOMPLETE: 5 of 7 books loaded") and "16, 17" in out["note"]
    assert [r["id"] for r in _table(_env, "texts")] == [11, 12, 13, 14, 15]
    assert written[0] == 5  # the batch was in the table before the call ended

    # The same command again loads all of them; the catalogue answer of today is reused.
    monkeypatch.setattr(gutenberg, "CALL_SECONDS", 600)
    written.clear()
    code, out = _run(["gutenberg", "text", "--ids", ",".join(map(str, ids)), "--table", "texts"], capsys)
    assert code == 0 and "INCOMPLETE" not in out["note"]
    assert [r["id"] for r in _table(_env, "texts")] == ids
    assert written == [5, 7] and catalogue.call_count == 1


@respx.mock
async def test_fetch_data_writes_each_batch_into_its_table(_env: Path, monkeypatch) -> None:
    """The API backends' fetch_data with materialize: the batches reach data.db as they load."""
    from src.modules.data.discovery_tools import SeriesDataToolHandler

    ids = [21, 22, 23, 24, 25, 26]
    _mock_texts(ids)
    monkeypatch.setattr(gutenberg, "CALL_SECONDS", -1)
    out = json.loads(
        await SeriesDataToolHandler(_env).handle(
            "fetch_data",
            {
                "provider": "gutenberg",
                "method": "text",
                "params": {"ids": ",".join(map(str, ids))},
                "materialize": True,
                "table": "texts",
            },
        )
    )
    assert out.get("materialized_table") == "texts", out
    assert [r["id"] for r in _table(_env, "texts")] == [21, 22, 23, 24, 25]
    assert out["note"].startswith("INCOMPLETE: 5 of 6 books loaded")
