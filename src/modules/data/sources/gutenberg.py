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
- Citation: the format of https://www.gutenberg.org/policy/permission.html
  ("Carroll, Lewis. (2006). Alice's Adventures in Wonderland. Urbana,
  Illinois: Project Gutenberg. Retrieved …, from www.gutenberg.org/ebooks/19033.").
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from .base import Arg, Context, Doctor, Fetched, FetchError, Operation, Polite, Source

GUTENDEX = "https://gutendex.com/books/"
MIRROR = "https://gutenberg.pglaf.org"
MAX_PAGES = 10
MAX_BOOKS = 20
TERMS_URL = "https://www.gutenberg.org/policy/license.html"
_START = re.compile(r"^\*\*\*\s*START OF (THE|THIS) PROJECT GUTENBERG EBOOK.*$", re.I | re.M)
_END = re.compile(r"^\*\*\*\s*END OF (THE|THIS) PROJECT GUTENBERG EBOOK.*$", re.I | re.M)
_PG = re.compile(r"project\s+gutenberg|gutenberg\.org|gutenberg-tm|pglaf", re.I)


def _book_row(b: dict[str, Any]) -> dict[str, Any]:
    authors = b.get("authors") or []
    return {
        "id": b.get("id"),
        "title": b.get("title"),
        "authors": "; ".join(a.get("name", "") for a in authors) or None,
        "author_birth_year": authors[0].get("birth_year") if authors else None,
        "author_death_year": authors[0].get("death_year") if authors else None,
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


async def fetch_books(ctx: Context, params: dict[str, Any]) -> Fetched:
    from .adapters import rest_json_pages

    q = _query(params)
    if not q:
        raise FetchError("give at least one of --search, --topic, --languages, --ids, --author-year-start/-end")
    limit = int(params.get("limit") or 100)
    if not 1 <= limit <= 32 * MAX_PAGES:
        raise FetchError(f"--limit {limit}: between 1 and {32 * MAX_PAGES}")
    books, urls = await rest_json_pages(ctx.http, GUTENDEX, q, items="results", paging="next", max_items=limit)
    rows = [_book_row(b) for b in books]
    what = ", ".join(f"{k}={v}" for k, v in q.items())
    return Fetched(
        rows=rows,
        series=f"Project Gutenberg books ({what})",
        query=urls[0],
        files=[],
        link="https://www.gutenberg.org/ebooks/",
        citation=COLLECTION_CITATION.format(date=_today_long()),
        record={"catalogue": "Gutendex", "pages": len(urls)},
        note="One row per book (catalogue data only). Load the texts with: text --ids <id,id,...>.",
    )


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
    books, urls = await rest_json_pages(ctx.http, GUTENDEX, {"ids": ",".join(ids)}, items="results", paging="next")
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
    rows, files, removed, citations = [], [], {}, []
    for i in ids:
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
    return Fetched(
        rows=rows,
        series=f"Project Gutenberg texts {', '.join(ids)} (header, footer and licence removed)",
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
        },
        note=(
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
            card="Books in the catalogue → one row per book (id, title, authors and years, languages, subjects, "
            "downloads). Params: search, topic, languages (list), author_year_start, author_year_end, ids (list), "
            "sort, limit.",
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
