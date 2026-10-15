"""Project Gutenberg: the catalogue (through Gutendex) and the plain text of books, from Project Gutenberg's own mirror.

- Catalogue: Gutendex (https://gutendex.com/, MIT-licensed, run by Gareth
  Johnson), a JSON API over Project Gutenberg's catalogue: search by words of
  title and author, topic (subjects and bookshelves), language, authors' years,
  copyright status; 32 books per page, paged by ``next`` links. Gutendex asks
  heavy users to run their own copy ("For long-term use, please run your own
  server"); a load reads at most ``MAX_PAGES`` pages, one per second.
- Texts: Project Gutenberg's website "is intended for human users only. Any
  perceived use of automated tools to access the Project Gutenberg website
  will result in a temporary or permanent block of your IP address"
  (https://www.gutenberg.org/policy/robot_access.html), and its terms of use say
  to download many books "from one of our mirrors, not from the main site"
  (https://www.gutenberg.org/policy/terms_of_use.html). ``text`` therefore reads
  ``/cache/epub/<id>/pg<id>.txt`` from gutenberg.pglaf.org, Project Gutenberg's
  own high-speed mirror (www.gutenberg.org/MIRRORS.ALL), at most ``MAX_BOOKS``
  books per load, two seconds apart (the pause the robot policy's own example
  uses), and keeps each file in the cache so a book is downloaded once a day.
- Terms: the licence (https://www.gutenberg.org/policy/license.html): the
  books "are not restricted by copyright in the United States"; an ebook is
  "the book text not restricted by U.S. copyright law and the non public domain
  Project Gutenberg trademark and license. If you strip the Project Gutenberg
  license and all references to Project Gutenberg from the text, you are left
  with a text unrestricted by U.S. intellectual property law." ``text`` stores
  the book text only: it cuts the header and footer at Project Gutenberg's
  ``*** START OF``/``*** END OF`` lines and drops any remaining line that names
  Project Gutenberg, and records what it removed and the SHA-256 of the file as
  downloaded. Books Gutendex marks as still under copyright are not loaded.
- Slow catalogue: Gutendex took 78 s per page in a 2026-10-13 demo (each
  100-320-row search about ten minutes). A search is kept for the day under
  the cache (``queries/``), and Gutendex gets ``GUTENDEX_TIMEOUT`` seconds; when
  it does not answer in time, the search reads Project Gutenberg's own
  catalogue file instead, ``pg_catalog.csv.gz`` from the feeds directory
  (``/cache/epub/feeds/``) of the mirror. Project Gutenberg's offline-catalogue
  page asks tools to "use one of these files as input to a database or other
  tools you may be developing" instead of crawling the website, and its robot
  policy says "The catalog data are granted to the public domain." The file
  (updated weekly by Project Gutenberg) is downloaded at most once a day; for
  an hour after a timeout, searches go to it directly.
- Citation: the format of https://www.gutenberg.org/policy/permission.html
  ("Carroll, Lewis. (2006). Alice's Adventures in Wonderland. Urbana,
  Illinois: Project Gutenberg. Retrieved …, from www.gutenberg.org/ebooks/19033.").
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .base import Arg, Context, Doctor, Fetched, FetchError, Operation, Polite, Source

GUTENDEX = "https://gutendex.com/books/"
MIRROR = "https://gutenberg.pglaf.org"
MAX_PAGES = 10
#: Seconds Gutendex gets to answer a search (all its pages) before the catalogue file is read instead.
GUTENDEX_TIMEOUT = 45.0
#: Project Gutenberg's catalogue file on its mirror (the feeds directory; https://www.gutenberg.org/ebooks/offline_catalogs.html).
CATALOGUE_CSV = "https://gutenberg.pglaf.org/cache/epub/feeds/pg_catalog.csv.gz"
#: After a Gutendex timeout, searches use the catalogue file for this long.
_SLOW_SECONDS = 3600
MAX_BOOKS = 20
#: Texts are downloaded in batches of this many; each batch is written into the table at once
#: (``Context.sink``), so a call that is stopped keeps the books it loaded.
TEXT_BATCH = 5
#: A text load starts no new batch after this many seconds: it returns the books it has and says
#: which are left. A specialist's whole call has 30 to 60 minutes (2026-10-14: one Gutenberg load
#: per call ran into the 1,800 s limit of Claude Code and failed the study).
CALL_SECONDS = 600
TERMS_URL = "https://www.gutenberg.org/policy/license.html"
_START = re.compile(r"^\*\*\*\s*START OF (THE|THIS) PROJECT GUTENBERG EBOOK.*$", re.I | re.M)
_END = re.compile(r"^\*\*\*\s*END OF (THE|THIS) PROJECT GUTENBERG EBOOK.*$", re.I | re.M)
_PG = re.compile(r"project\s+gutenberg|gutenberg\.org|gutenberg-tm|pglaf", re.I)


def _person(name: str | None, birth: Any, death: Any) -> str:
    """'Austen, Jane (1775-1817)'; the years left out when neither is known."""
    if birth is None and death is None:
        return name or ""
    return f"{name or ''} ({'' if birth is None else birth}-{'' if death is None else death})"


def _people(people: list[dict[str, Any]]) -> str | None:
    return "; ".join(_person(p.get("name"), p.get("birth_year"), p.get("death_year")) for p in people) or None


def _book_row(b: dict[str, Any]) -> dict[str, Any]:
    """One catalogue row. ``translators`` (names with their years) is what tells a translation from a
    book written in its language: the weather-words demo (2026-10-14) kept ten translated novels
    (Dumas, Verne, Flaubert, ...) because the table had no such column."""
    authors = b.get("authors") or []
    return {
        "id": b.get("id"),
        "title": b.get("title"),
        "authors": "; ".join(a.get("name", "") for a in authors) or None,
        "author_birth_year": authors[0].get("birth_year") if authors else None,
        "author_death_year": authors[0].get("death_year") if authors else None,
        "authors_years": _people(authors),
        "translators": _people(b.get("translators") or []),
        "languages": ",".join(b.get("languages") or []) or None,
        "subjects": "; ".join(b.get("subjects") or []) or None,
        "bookshelves": "; ".join(b.get("bookshelves") or []) or None,
        "copyright": b.get("copyright"),
        "media_type": b.get("media_type"),
        "download_count": b.get("download_count"),
        "has_plain_text": any(k.startswith("text/plain") for k in (b.get("formats") or {})),
    }


def _query(params: dict[str, Any]) -> dict[str, Any]:
    q: dict[str, Any] = {
        "search": params.get("search"),
        "topic": params.get("topic"),
        "languages": ",".join(params["languages"]) if params.get("languages") else None,
        "author_year_start": params.get("author_year_start"),
        "author_year_end": params.get("author_year_end"),
        "sort": params.get("sort"),
    }
    if params.get("ids"):
        ids = [str(i).strip() for i in params["ids"]]
        if not all(i.isdigit() for i in ids):
            raise FetchError(f"--ids {', '.join(ids)}: give Project Gutenberg book numbers, e.g. 1342,84")
        q["ids"] = ",".join(ids)
    if params.get("copyright") is not None:
        q["copyright"] = params["copyright"]
    return {k: v for k, v in q.items() if v not in (None, "")}


def _query_cache(q: dict[str, Any], limit: int) -> Path:
    import hashlib
    import json

    from .adapters import cache_dir

    key = hashlib.sha256(json.dumps({"q": q, "limit": limit}, sort_keys=True).encode()).hexdigest()[:24]
    return cache_dir("gutenberg") / "queries" / datetime.now(UTC).strftime("%Y-%m-%d") / f"{key}.json"


def _slow_marker() -> Path:
    from .adapters import cache_dir

    return cache_dir("gutenberg") / "gutendex-slow"


def _gutendex_recently_slow() -> bool:
    import time

    try:
        return time.time() - _slow_marker().stat().st_mtime < _SLOW_SECONDS
    except OSError:
        return False


async def _from_gutendex(ctx: Context, q: dict[str, Any], limit: int) -> tuple[list[dict[str, Any]], list[str]]:
    import asyncio

    from .adapters import rest_json_pages

    try:
        books, urls = await asyncio.wait_for(
            rest_json_pages(ctx.http, GUTENDEX, q, items="results", paging="next", max_items=limit),
            timeout=GUTENDEX_TIMEOUT,
        )
    except TimeoutError:
        raise _GutendexSlowError(f"Gutendex did not answer within {GUTENDEX_TIMEOUT:.0f} s") from None
    except FetchError as e:
        if "timeout" in str(e).lower():
            raise _GutendexSlowError(str(e)) from None
        raise
    return [_book_row(b) for b in books], urls


class _GutendexSlowError(Exception):
    """Gutendex did not answer in time."""


async def fetch_books(ctx: Context, params: dict[str, Any]) -> Fetched:
    import json

    q = _query(params)
    if not q:
        raise FetchError("give at least one of --search, --topic, --languages, --ids, --author-year-start/-end")
    limit = int(params.get("limit") or 100)
    if not 1 <= limit <= 32 * MAX_PAGES:
        raise FetchError(f"--limit {limit}: between 1 and {32 * MAX_PAGES}")
    what = ", ".join(f"{k}={v}" for k, v in q.items())
    cached = _query_cache(q, limit)
    if cached.is_file():
        try:
            kept = json.loads(cached.read_text(encoding="utf-8"))
            return _books_fetched(
                kept["rows"], what, kept["query"], kept["record"] | {"from_cache": True}, kept["note"]
            )
        except (OSError, ValueError, KeyError):
            pass
    note = "One row per book (catalogue data only). Load the texts with: text --ids <id,id,...>."
    rows: list[dict[str, Any]] | None = None
    record: dict[str, Any] = {}
    query = ""
    slow = ""
    if _gutendex_recently_slow():
        slow = "Gutendex did not answer in time within the last hour"
    else:
        try:
            rows, urls = await _from_gutendex(ctx, q, limit)
            record = {"catalogue": "Gutendex", "pages": len(urls)}
            query = urls[0]
        except _GutendexSlowError as e:
            slow = str(e)
            try:
                _slow_marker().parent.mkdir(parents=True, exist_ok=True)
                _slow_marker().touch()
            except OSError:
                pass
    if rows is None:
        rows, file_meta = await _from_catalogue_file(ctx, q, limit, slow)
        query = f"{CATALOGUE_CSV} (filtered: {what})"
        record = {"catalogue": "Project Gutenberg catalogue file", "file": file_meta, "why": slow}
        note = (
            f"{slow}, so the rows come from Project Gutenberg's own catalogue file (pg_catalog.csv, updated weekly). "
            "It has no download counts and no copyright status: rows are ordered by book number, `download_count` "
            "and `copyright` are empty, and `text` checks the copyright before loading a book. " + note
        )
    try:
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_text(json.dumps({"rows": rows, "query": query, "record": record, "note": note}), encoding="utf-8")
    except OSError:
        pass
    return _books_fetched(rows, what, query, record, note)


def _books_fetched(rows: list[dict[str, Any]], what: str, query: str, record: dict[str, Any], note: str) -> Fetched:
    return Fetched(
        rows=rows,
        series=f"Project Gutenberg books ({what})",
        query=query,
        files=[],
        link="https://www.gutenberg.org/ebooks/",
        citation=COLLECTION_CITATION.format(date=_today_long()),
        record=record,
        note=note,
    )


_YEARS = re.compile(r",\s*(?:(\d{1,4})\??\s*(BCE)?)?\s*-\s*(?:(\d{1,4})\??\s*(BCE)?)?\s*$")


_ROLE = re.compile(r"\s*\[([^\]]*)\]\s*$")


def _role(raw: str) -> str:
    """The role a catalogue file gives a person after the name ('[Translator]', '[Editor]'), lower case."""
    m = _ROLE.search(raw.strip())
    return m.group(1).strip().lower() if m else ""


def _author(raw: str) -> tuple[str, int | None, int | None]:
    """'Austen, Jane, 1775-1817' -> ('Austen, Jane', 1775, 1817); years missing or BCE are negative/None."""
    raw = _ROLE.sub("", raw.strip())  # "[Editor]", "[Translator]"
    m = _YEARS.search(raw)
    if not m:
        return raw, None, None

    def year(v: str | None, bce: str | None) -> int | None:
        return None if not v else (-int(v) if bce else int(v))

    return raw[: m.start()].strip(), year(m.group(1), m.group(2)), year(m.group(3), m.group(4))


def catalogue_rows(lines: Any, q: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    """The books of Project Gutenberg's catalogue CSV that match a Gutendex-style query, as ``_book_row`` rows.

    ``search``: every word in the title or an author's name; ``topic``: a
    phrase in the subjects or bookshelves; ``languages``: any of them;
    ``author_year_start``/``end``: an author alive at or after / at or before
    the year; ``ids``: those books. Sorted by book number (``descending`` reverses).
    """
    import csv

    words = [w.lower() for w in str(q.get("search") or "").split()]
    topic = str(q.get("topic") or "").lower()
    langs = {x.strip() for x in str(q.get("languages") or "").split(",") if x.strip()}
    ids = {x.strip() for x in str(q.get("ids") or "").split(",") if x.strip()}
    start = q.get("author_year_start")
    end = q.get("author_year_end")
    out: list[dict[str, Any]] = []
    for rec in csv.DictReader(lines):
        num = (rec.get("Text#") or "").strip()
        if ids and num not in ids:
            continue
        people = [a for a in (rec.get("Authors") or "").split(";") if a.strip()]
        # A translator is not an author: the file lists both, the translator marked "[Translator]".
        translators = [_author(a) for a in people if _role(a) == "translator"]
        authors = [_author(a) for a in people if _role(a) != "translator"]
        names = "; ".join(a[0] for a in authors)
        if words and not all(w in f"{rec.get('Title') or ''} {names}".lower() for w in words):
            continue
        if topic and topic not in f"{rec.get('Subjects') or ''} {rec.get('Bookshelves') or ''}".lower():
            continue
        book_langs = {x.strip() for x in (rec.get("Language") or "").replace(",", ";").split(";") if x.strip()}
        if langs and not (book_langs & langs):
            continue
        if start is not None and not any(d is not None and d >= int(start) for _n, _b, d in authors):
            continue
        if end is not None and not any(b is not None and b <= int(end) for _n, b, _d in authors):
            continue
        first = authors[0] if authors else (None, None, None)
        out.append(
            {
                "id": int(num) if num.isdigit() else num,
                "title": rec.get("Title"),
                "authors": names or None,
                "author_birth_year": first[1],
                "author_death_year": first[2],
                "authors_years": "; ".join(_person(*a) for a in authors) or None,
                "translators": "; ".join(_person(*t) for t in translators) or None,
                "languages": ",".join(sorted(book_langs)) or None,
                "subjects": rec.get("Subjects") or None,
                "bookshelves": rec.get("Bookshelves") or None,
                "copyright": None,
                "media_type": rec.get("Type"),
                "download_count": None,
                "has_plain_text": rec.get("Type") == "Text",
            }
        )
    out.sort(key=lambda r: r["id"] if isinstance(r["id"], int) else 0, reverse=q.get("sort") == "descending")
    return out[:limit]


async def _from_catalogue_file(
    ctx: Context, q: dict[str, Any], limit: int, why: str
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    import gzip
    import io

    from .adapters import download_file

    today = datetime.now(UTC).strftime("%Y-%m-%d")
    try:
        path, meta = await download_file(ctx.http, CATALOGUE_CSV, "gutenberg", version=f"catalogue-{today}")
    except FetchError as e:
        raise FetchError(
            f"{why}, and Project Gutenberg's catalogue file could not be read either ({e}). Try again later."
        ) from None
    with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
        rows = catalogue_rows(io.StringIO(fh.read()), q, limit)
    return rows, {"url": meta["url"], "sha256": meta["sha256"], "retrieved_at": meta["retrieved_at"]}


def _today_long() -> str:
    d = datetime.now(UTC)
    return f"{d.strftime('%B')} {d.day}, {d.year}"


def strip_gutenberg(raw: str) -> tuple[str, dict[str, Any]]:
    """The book text without Project Gutenberg's header, footer and licence, and what was removed."""
    text = raw.replace("\r\n", "\n").lstrip("﻿")
    start, end = _START.search(text), _END.search(text)
    info: dict[str, Any] = {"header_found": bool(start), "footer_found": bool(end)}
    body = text[start.end() if start else 0 : end.start() if end else len(text)]
    kept, dropped = [], 0
    for line in body.split("\n"):
        if _PG.search(line):
            dropped += 1
            continue
        kept.append(line)
    out = "\n".join(kept).strip("\n") + "\n"
    info["lines_naming_project_gutenberg_removed"] = dropped
    info["characters_removed"] = len(text) - len(out)
    return out, info


async def fetch_text(ctx: Context, params: dict[str, Any]) -> Fetched:
    from .adapters import download_file, rest_json_pages

    ids = [str(i).strip() for i in params["ids"] or []]
    if not ids or not all(i.isdigit() for i in ids):
        raise FetchError("--ids: give Project Gutenberg book numbers, e.g. 1342,84")
    if len(ids) > MAX_BOOKS:
        raise FetchError(f"{len(ids)} books: load at most {MAX_BOOKS} at a time (Project Gutenberg asks for restraint)")
    import asyncio
    import json
    import time

    started = time.monotonic()
    looked_up = _query_cache({"ids": ",".join(ids), "for": "text"}, 0)
    try:
        kept = json.loads(looked_up.read_text(encoding="utf-8"))
        books, urls = kept["books"], kept["urls"]
    except (OSError, ValueError, KeyError):
        try:
            books, urls = await asyncio.wait_for(
                rest_json_pages(ctx.http, GUTENDEX, {"ids": ",".join(ids)}, items="results", paging="next"),
                timeout=GUTENDEX_TIMEOUT,
            )
        except TimeoutError:
            raise FetchError(
                f"Gutendex, the catalogue e2er checks each book's copyright status with, did not answer within "
                f"{GUTENDEX_TIMEOUT:.0f} s. No text was loaded; try again later."
            ) from None
        try:  # the same books asked for again today (a call that stopped at its time limit) skip Gutendex
            looked_up.parent.mkdir(parents=True, exist_ok=True)
            looked_up.write_text(json.dumps({"books": books, "urls": urls}), encoding="utf-8")
        except OSError:
            pass
    by_id = {str(b.get("id")): b for b in books}
    missing = [i for i in ids if i not in by_id]
    if missing:
        raise FetchError(f"no Project Gutenberg book {', '.join(missing)} in the catalogue (Gutendex)")
    protected = [i for i in ids if by_id[i].get("copyright")]
    if protected:
        raise FetchError(
            f'book {", ".join(protected)} is still under copyright (Project Gutenberg: "If you want to distribute '
            'a copyrighted ebook you found on PG, you have to contact the author"); e2er does not load it'
        )
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    rows: list[dict[str, Any]] = []
    files: list[dict[str, Any]] = []
    removed: dict[str, Any] = {}
    citations: list[str] = []
    left: list[str] = []
    for n, i in enumerate(ids):
        if n and n % TEXT_BATCH == 0:
            if ctx.sink is not None:
                ctx.sink(rows)  # this batch is in the table now, whatever happens to the call
            if time.monotonic() - started > CALL_SECONDS:
                left = ids[n:]
                break
        url = f"{MIRROR}/cache/epub/{i}/pg{i}.txt"
        path, meta = await download_file(ctx.http, url, "gutenberg", version=today, name=f"pg{i}.txt")
        raw = path.read_bytes().decode("utf-8", errors="replace")
        text, info = strip_gutenberg(raw)
        if not info["header_found"] or not info["footer_found"]:
            raise FetchError(
                f"{url}: Project Gutenberg's START/END lines were not found, so the licence could not be cut "
                "from the text; e2er does not load it"
            )
        files.append(
            {"url": meta["url"], "sha256": meta["sha256"], "bytes": meta["bytes"], "retrieved_at": meta["retrieved_at"]}
        )
        removed[i] = info
        row = _book_row(by_id[i])
        row.update({"text": text, "characters": len(text), "words": len(text.split())})
        rows.append(row)
        citations.append(_cite(by_id[i]))
    if ctx.sink is not None:
        ctx.sink(rows)
    loaded = ids[: len(rows)]
    record: dict[str, Any] = {}
    note = ""
    if left:
        record["incomplete"] = {"loaded": loaded, "not_loaded": left}
        note = (
            f"INCOMPLETE: {len(loaded)} of {len(ids)} books loaded; one call stops after "
            f"{CALL_SECONDS // 60} minutes so that it never runs as long as a specialist's whole call. The "
            f"{len(loaded)} are in the table. Run the same command again: the books downloaded today are read "
            f"from the cache, and the rest ({', '.join(left)}) are loaded. "
        )
    return Fetched(
        rows=rows,
        series=f"Project Gutenberg texts {', '.join(loaded)} (header, footer and licence removed)",
        query=f"{MIRROR}/cache/epub/<id>/pg<id>.txt for {', '.join(ids)}; catalogue {urls[0]}",
        version=today,
        files=files,
        link=f"https://www.gutenberg.org/ebooks/{ids[0]}",
        citation=" ".join(citations),
        record={
            "mirror": MIRROR,
            "stripped": removed,
            "stripping": "Header and footer cut at the *** START OF / *** END OF lines; any other line naming "
            "Project Gutenberg dropped (licence: strip the license and all references).",
            **record,
        },
        note=note
        + (
            "One row per book: catalogue fields and `text`, the book text without Project Gutenberg's header, footer "
            "and licence (what was cut is in the load record). Files are the plain-text edition as of the load; "
            "Project Gutenberg corrects books and rebuilds these files, so a later load can differ."
        ),
    )


def _cite(b: dict[str, Any]) -> str:
    authors = b.get("authors") or []
    who = authors[0]["name"] if authors and authors[0].get("name") else "Anonymous"
    if len(authors) > 1:
        who += " et al."
    return (
        f"{who}. (n.d.). {b.get('title')}. Urbana, Illinois: Project Gutenberg. Retrieved {_today_long()}, "
        f"from www.gutenberg.org/ebooks/{b.get('id')}."
    )


COLLECTION_CITATION = "Project Gutenberg. (n.d.). Retrieved {date}, from https://www.gutenberg.org."
CITATION = "Project Gutenberg. (n.d.). Urbana, Illinois: Project Gutenberg. https://www.gutenberg.org."
CITE_KEY = "ProjectGutenberg"
BIBTEX = """@misc{ProjectGutenberg,
  author       = {{Project Gutenberg}},
  title        = {Project Gutenberg},
  address      = {Urbana, Illinois},
  url          = {https://www.gutenberg.org},
  note         = {Texts from the mirror gutenberg.pglaf.org; catalogue via Gutendex, https://gutendex.com}
}"""

SOURCE = Source(
    name="gutenberg",
    label="Project Gutenberg",
    dataset="Project Gutenberg ebooks (catalogue via Gutendex; texts from Project Gutenberg's mirror)",
    website="https://www.gutenberg.org",
    terms_url=TERMS_URL,
    terms_summary=(
        "The books are not restricted by copyright in the United States; e2er stores the text with Project "
        "Gutenberg's licence and all references to Project Gutenberg removed, which leaves \"a text unrestricted by "
        'U.S. intellectual property law". Check the copyright law of your country.'
    ),
    terms_plain=(
        "The books are not restricted by copyright in the United States; outside the U.S., check your country's law.",
        "e2er stores the book text only: Project Gutenberg's header, footer, licence and every line naming Project "
        "Gutenberg are removed, and the load records what was cut.",
        "Books still under copyright are not loaded.",
        "Texts come from Project Gutenberg's mirror, not its website, which allows no automated access.",
    ),
    licence=(
        f'Project Gutenberg licence ({TERMS_URL}): "These books are not restricted by copyright in the United '
        "States and anyone located in the United States — including Project Gutenberg and you — may read and "
        "distribute them. If you don't live in the United States you'll have to check the laws of the country you "
        'live in before downloading and distributing our ebooks." "If you strip the Project Gutenberg license '
        "and all references to Project Gutenberg from the text, you are left with a text unrestricted by U.S. "
        'intellectual property law." Permissions (https://www.gutenberg.org/policy/permission.html): "No '
        'permission is needed for non-commercial use." Catalogue (https://www.gutenberg.org/policy/'
        'robot_access.html): "The catalog data are granted to the public domain."'
    ),
    citation=CITATION,
    citation_by="source",
    bibtex=BIBTEX,
    cite_key=CITE_KEY,
    use=(
        "Books whose U.S. copyright has expired (about 75,000, most in English; novels, poetry, drama, history, "
        "philosophy, science): the catalogue (title, authors and their years, language, subjects, downloads) and "
        "the plain text of chosen books for text analysis. Find books with `books`, load texts with `text`."
    ),
    coverage="Public-domain (U.S.) books: catalogue and plain text, Project Gutenberg's licence removed.",
    help="Project Gutenberg: book catalogue (via Gutendex) and plain texts. No key.",
    operations=(
        Operation(
            "books",
            "Books in the catalogue, e.g. --search 'austen' --languages en, or --topic 'detective'.",
            args=(
                Arg("search", "Words of the title or the author's name."),
                Arg("topic", "A word of the subjects or bookshelves, e.g. children, detective."),
                Arg("languages", "Two-letter language codes, comma-separated, e.g. en,fr.", type="list"),
                Arg("author-year-start", "Authors alive at or after this year.", type=int),
                Arg("author-year-end", "Authors alive at or before this year.", type=int),
                Arg("ids", "Book numbers, comma-separated.", type="list"),
                Arg(
                    "sort",
                    "popular (default), ascending or descending (by number).",
                    choices=("popular", "ascending", "descending"),
                ),
                Arg("limit", f"Most books (default 100, at most {32 * MAX_PAGES}).", type=int),
            ),
            fetch=fetch_books,
            card="Books in the catalogue → one row per book (id, title, authors and years, translators, languages, "
            "subjects, bookshelves, downloads). Params: search, topic, languages (list), author_year_start, "
            "author_year_end, ids (list), sort, limit.",
        ),
        Operation(
            "text",
            f"The plain text of books, e.g. --ids 1342,84 (at most {MAX_BOOKS}).",
            args=(Arg("ids", "Book numbers, comma-separated, e.g. 1342,84.", type="list", required=True),),
            fetch=fetch_text,
            card=f"Plain texts of books (Project Gutenberg's licence removed) → one row per book with `text`. "
            f"Params: ids (list, required, at most {MAX_BOOKS}).",
        ),
    ),
    polite=Polite(min_interval=2.0, max_requests=MAX_PAGES + MAX_BOOKS + 5, timeout=120.0),
    aliases=("project_gutenberg", "gutendex", "pg"),
    skill="data/gutenberg",
    doctor=Doctor("data.gutenberg.books", operation="books", params={"ids": "1342"}),
)
