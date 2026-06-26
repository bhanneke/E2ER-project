"""Local Zotero (zotero.sqlite) reader — against a tiny synthetic fixture DB.

Hermetic: no network, no real Zotero install. Verifies item mapping, author
ordering + institutional names, attachment path resolution, deleted/attachment/
note exclusion, read-only safety, and never-raise on a malformed DB.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from src.modules.literature.local_zotero import detect_zotero, read_zotero_sqlite


def _make_zotero(dirp: Path) -> Path:
    dirp.mkdir(parents=True, exist_ok=True)
    db = dirp / "zotero.sqlite"
    c = sqlite3.connect(db)
    c.executescript(
        """
        CREATE TABLE items(itemID INT PRIMARY KEY, key TEXT, itemTypeID INT);
        CREATE TABLE itemTypes(itemTypeID INT, typeName TEXT);
        CREATE TABLE fields(fieldID INT, fieldName TEXT);
        CREATE TABLE itemDataValues(valueID INT, value TEXT);
        CREATE TABLE itemData(itemID INT, fieldID INT, valueID INT);
        CREATE TABLE creators(creatorID INT, firstName TEXT, lastName TEXT, fieldMode INT);
        CREATE TABLE creatorTypes(creatorTypeID INT, creatorType TEXT);
        CREATE TABLE itemCreators(itemID INT, creatorID INT, creatorTypeID INT, orderIndex INT);
        CREATE TABLE itemAttachments(itemID INT, parentItemID INT, contentType TEXT, path TEXT, linkMode INT);
        CREATE TABLE deletedItems(itemID INT);
        """
    )
    c.executemany("INSERT INTO itemTypes VALUES(?,?)", [(1, "journalArticle"), (2, "attachment"), (3, "note")])
    c.executemany("INSERT INTO items VALUES(?,?,?)", [(10, "ABCD1234", 1), (11, "ATTACHKEY", 2), (12, "DELE0000", 1)])
    c.executemany(
        "INSERT INTO fields VALUES(?,?)",
        [(1, "title"), (2, "date"), (3, "DOI"), (4, "publicationTitle"), (5, "abstractNote")],
    )
    c.executemany(
        "INSERT INTO itemDataValues VALUES(?,?)",
        [
            (100, "Concentrated Liquidity and Price Discovery"),
            (101, "2024-03-01"),
            (102, "10.1234/abc"),
            (103, "Journal of Finance"),
            (104, "We study AMMs."),
            (200, "A Deleted Paper"),
        ],
    )
    c.executemany(
        "INSERT INTO itemData VALUES(?,?,?)",
        [(10, 1, 100), (10, 2, 101), (10, 3, 102), (10, 4, 103), (10, 5, 104), (12, 1, 200)],
    )
    c.executemany(
        "INSERT INTO creators VALUES(?,?,?,?)",
        [(50, "Alice", "Smith", 0), (51, "", "Federal Reserve", 1)],
    )
    c.executemany("INSERT INTO creatorTypes VALUES(?,?)", [(1, "author")])
    c.executemany("INSERT INTO itemCreators VALUES(?,?,?,?)", [(10, 50, 1, 0), (10, 51, 1, 1)])
    stor = dirp / "storage" / "ATTACHKEY"
    stor.mkdir(parents=True)
    (stor / "smith2024.pdf").write_bytes(b"%PDF-1.4 fake")
    c.execute(
        "INSERT INTO itemAttachments VALUES(?,?,?,?,?)",
        (11, 10, "application/pdf", "storage:smith2024.pdf", 0),
    )
    c.execute("INSERT INTO deletedItems VALUES(12)")
    c.commit()
    c.close()
    return dirp


def test_detect_zotero(tmp_path: Path):
    zdir = _make_zotero(tmp_path / "lib")
    assert detect_zotero(zdir) == zdir / "zotero.sqlite"
    assert detect_zotero(tmp_path / "not_zotero") is None


def test_reader_maps_one_article_excludes_rest(tmp_path: Path):
    zdir = _make_zotero(tmp_path / "lib")
    papers = read_zotero_sqlite(zdir)
    assert len(papers) == 1  # attachment, note, and deleted item all excluded
    p = papers[0]
    assert p.title == "Concentrated Liquidity and Price Discovery"
    assert p.authors == ["Alice Smith", "Federal Reserve"]  # ordered; institutional name
    assert p.year == 2024
    assert p.doi == "10.1234/abc"
    assert p.journal == "Journal of Finance"
    assert p.source == "zotero_local"
    assert p.raw["source_pdf"].endswith("storage/ATTACHKEY/smith2024.pdf")


def test_read_only_never_mutates(tmp_path: Path):
    zdir = _make_zotero(tmp_path / "lib")
    db = zdir / "zotero.sqlite"
    before = db.read_bytes()
    read_zotero_sqlite(zdir)
    assert db.read_bytes() == before


def test_malformed_db_degrades_to_empty(tmp_path: Path):
    zdir = tmp_path / "lib"
    zdir.mkdir()
    (zdir / "zotero.sqlite").write_bytes(b"not a database")
    assert read_zotero_sqlite(zdir) == []


def test_missing_dir_is_empty(tmp_path: Path):
    assert read_zotero_sqlite(tmp_path / "nope") == []
