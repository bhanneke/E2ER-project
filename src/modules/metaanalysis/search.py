"""The search: every query of the protocol run on OpenAlex (and Crossref when named), recorded and deduplicated.

Requests go through the field map's OpenAlex client (polite pool, optional
``OPENALEX_API_KEY``, a request ceiling, pages cached in the workspace by their
address), so a rerun with the same protocol sends no request and the records
are the same. Keyless OpenAlex requests share one daily budget per network:
the search reads the size of each query first (one request) and refuses one
above ``max_records`` before any page is read.

Crossref has no Boolean search. When the protocol names it, the search reads
the first ``max_crossref`` records Crossref ranks as most relevant to the
query, and ``search_log.json`` says so: such a search is not exhaustive.

Files written to the workspace:

- ``records.json`` / ``records.csv``: one record per work after deduplication
  (by DOI, then by title and year), with the searches that found it;
- ``search_log.json``: per search and database the query as sent, the count
  the database reported, the records read, when, and the requests used;
- ``search_counts.md``: the same for the researcher's stop;
- ``data_sources.json``: one load per search (OpenAlex CC0, Crossref metadata).
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import urllib.parse
from pathlib import Path
from typing import Any

from ..fieldmap.network import short_id
from ..fieldmap.openalex import BoundaryError, Client, abstract_text
from ..fieldmap.openalex import _default_fetch as _http_get_text

RECORDS_FILE = "records.json"
RECORDS_CSV = "records.csv"
SEARCH_LOG = "search_log.json"
COUNTS_MD = "search_counts.md"
DIR = "metaanalysis"
PER_PAGE = 100
CROSSREF_API = "https://api.crossref.org/works"
SELECT = (
    "id,doi,title,publication_year,publication_date,type,primary_location,authorships,"
    "abstract_inverted_index,open_access,best_oa_location,biblio,language"
)

OPENALEX_SOURCE = {
    "connector": "openalex",
    "dataset": "OpenAlex",
    "terms_summary": "OpenAlex data are released under CC0: no restriction on use; OpenAlex asks to be cited.",
    "licence": "CC0 1.0 Universal (https://creativecommons.org/publicdomain/zero/1.0/)",
    "terms": "https://creativecommons.org/publicdomain/zero/1.0/",
    "citation": (
        "Priem, J., Piwowar, H., and Orr, R. (2022). OpenAlex: A fully-open index of scholarly works, authors, "
        "venues, institutions, and concepts. arXiv:2205.01833."
    ),
    "citation_by": "source",
    "link": "https://openalex.org",
}
CROSSREF_SOURCE = {
    "connector": "crossref",
    "dataset": "Crossref REST API",
    "terms_summary": "Crossref metadata are free to use; abstracts belong to their publishers.",
    "licence": "Crossref metadata: no known copyright restrictions (https://www.crossref.org/documentation/retrieve-metadata/rest-api/)",
    "terms": "https://www.crossref.org/documentation/retrieve-metadata/rest-api/",
    "citation": "Crossref REST API, https://api.crossref.org",
    "citation_by": "source",
    "link": "https://www.crossref.org",
}


def fetch_text(url: str, headers: dict[str, str]) -> str:
    """One GET, its body as text (raises on an error status). The replay level replaces this."""
    return _http_get_text(url, headers)


def client(ws: Path, max_requests: int) -> Client:
    return Client.from_settings(
        Path(ws) / DIR / "cache", max_requests=max_requests, fetch=lambda u, h: fetch_text(u, h)
    )


# ── OpenAlex ────────────────────────────────────────────────────────────────

_SEARCH_FIELDS = {"title_abstract": "title_and_abstract.search", "title": "title.search", "all": "default.search"}


def openalex_filter(search: dict[str, Any]) -> str:
    parts = [f"{_SEARCH_FIELDS[search.get('search_in', 'title_abstract')]}:{search['query'].strip()}"]
    fy, ty = search.get("from_year"), search.get("to_year")
    if fy and ty:
        parts.append(f"publication_year:{fy}-{ty}")
    elif fy:
        parts.append(f"publication_year:>{fy - 1}")
    elif ty:
        parts.append(f"publication_year:<{ty + 1}")
    types = search.get("types") or ["article"]
    parts.append("type:" + "|".join(str(t) for t in types))
    if search.get("open_access_only"):
        parts.append("open_access.is_oa:true")
    if search.get("language"):
        parts.append(f"language:{search['language']}")
    parts.append("is_paratext:false")
    return ",".join(parts)


def _doi(raw: Any) -> str:
    d = str(raw or "").strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if d.lower().startswith(prefix):
            d = d[len(prefix) :]
    return d.lower()


def parse_openalex(w: dict[str, Any]) -> dict[str, Any]:
    loc = w.get("primary_location") or {}
    src = loc.get("source") or {}
    oa = w.get("open_access") or {}
    best = w.get("best_oa_location") or {}
    biblio = w.get("biblio") or {}
    authors = [(a.get("author") or {}).get("display_name") or "" for a in w.get("authorships") or []]
    return {
        "id": short_id(w.get("id") or ""),
        "openalex_id": short_id(w.get("id") or ""),
        "doi": _doi(w.get("doi")),
        "title": w.get("title") or "",
        "year": w.get("publication_year"),
        "date": w.get("publication_date") or "",
        "type": w.get("type") or "",
        "journal": src.get("display_name") or "",
        "volume": biblio.get("volume") or "",
        "issue": biblio.get("issue") or "",
        "pages": "-".join(x for x in (biblio.get("first_page"), biblio.get("last_page")) if x),
        "authors": [a for a in authors if a],
        "abstract": abstract_text(w.get("abstract_inverted_index")),
        "language": w.get("language") or "",
        "is_oa": bool(oa.get("is_oa")),
        "oa_status": oa.get("oa_status") or "",
        "oa_url": oa.get("oa_url") or "",
        "oa_pdf_url": best.get("pdf_url") or "",
        "oa_landing_url": best.get("landing_page_url") or "",
        "oa_licence": best.get("license") or "",
    }


def run_openalex(cl: Client, search: dict[str, Any], *, max_records: int) -> dict[str, Any]:
    flt = openalex_filter(search)
    head = cl.get("works", {"filter": flt, "per-page": 1, "select": "id"})
    reported = int((head.get("meta") or {}).get("count") or 0)
    if reported > max_records:
        raise BoundaryError(
            f"search {search['name']} finds {reported} records on OpenAlex, above the limit of {max_records}; "
            "narrow the query or the years, or raise the search step's max_records"
        )
    works: list[dict[str, Any]] = []
    cursor = "*"
    while cursor and reported:
        data = cl.get("works", {"filter": flt, "per-page": PER_PAGE, "cursor": cursor, "select": SELECT})
        page = data.get("results") or []
        works.extend(parse_openalex(w) for w in page)
        nxt = (data.get("meta") or {}).get("next_cursor")
        cursor = nxt if page and nxt else ""
    return {"database": "openalex", "query": flt, "count_reported": reported, "records": works}


# ── Crossref ────────────────────────────────────────────────────────────────

_TAGS = re.compile(r"<[^>]+>")


def parse_crossref(item: dict[str, Any]) -> dict[str, Any]:
    doi = _doi(item.get("DOI"))
    parts = ((item.get("issued") or {}).get("date-parts") or [[None]])[0]
    year = parts[0] if parts else None
    authors = [" ".join(x for x in (a.get("given"), a.get("family")) if x) for a in item.get("author") or []]
    return {
        "id": "C" + hashlib.sha1(doi.encode()).hexdigest()[:10],
        "openalex_id": "",
        "doi": doi,
        "title": " ".join(item.get("title") or []),
        "year": year,
        "date": "",
        "type": item.get("type") or "",
        "journal": " ".join(item.get("container-title") or []),
        "volume": item.get("volume") or "",
        "issue": item.get("issue") or "",
        "pages": item.get("page") or "",
        "authors": [a for a in authors if a],
        "abstract": _TAGS.sub(" ", item.get("abstract") or "").strip(),
        "language": item.get("language") or "",
        "is_oa": False,
        "oa_status": "",
        "oa_url": "",
        "oa_pdf_url": "",
        "oa_landing_url": "",
        "oa_licence": "",
    }


def crossref_url(search: dict[str, Any], rows: int, mailto: str) -> str:
    flt = ["type:journal-article"]
    if search.get("from_year"):
        flt.append(f"from-pub-date:{search['from_year']}")
    if search.get("to_year"):
        flt.append(f"until-pub-date:{search['to_year']}")
    q = {
        "query.bibliographic": search["query"].replace('"', " "),
        "filter": ",".join(flt),
        "rows": rows,
        "select": "DOI,title,abstract,issued,container-title,author,type,volume,issue,page,language",
    }
    if mailto:
        q["mailto"] = mailto
    return f"{CROSSREF_API}?{urllib.parse.urlencode(q, safe=':,')}"


def run_crossref(cl: Client, ws: Path, search: dict[str, Any], *, rows: int) -> dict[str, Any]:
    url = crossref_url(search, rows, cl.mailto)
    cache = Path(ws) / DIR / "cache" / (hashlib.sha256(url.encode()).hexdigest()[:32] + ".json")
    if cache.is_file():
        data = json.loads(cache.read_text(encoding="utf-8"))
        cl.budget.cached += 1
    else:
        cl.budget.spend()
        data = json.loads(fetch_text(url, {}))
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(data), encoding="utf-8", newline="\n")
    msg = data.get("message") or {}
    items = [parse_crossref(i) for i in msg.get("items") or [] if i.get("DOI")]
    return {
        "database": "crossref",
        "query": url.split("?", 1)[1],
        "count_reported": int(msg.get("total-results") or 0),
        "records": items,
        "note": f"the first {rows} records Crossref ranks as most relevant; Crossref has no Boolean search",
    }


# ── dedup and files ─────────────────────────────────────────────────────────


def _title_key(r: dict[str, Any]) -> str:
    t = re.sub(r"[^a-z0-9]+", "", (r.get("title") or "").lower())
    return f"{t}|{r.get('year') or ''}"


def deduplicate(found: list[tuple[str, dict[str, Any]]]) -> tuple[list[dict[str, Any]], int]:
    """(unique records with the searches that found each, duplicates removed)."""
    by_key: dict[str, dict[str, Any]] = {}
    alias: dict[str, str] = {}
    dups = 0
    for where, rec in found:
        keys = [k for k in (f"doi:{rec['doi']}" if rec.get("doi") else "", f"title:{_title_key(rec)}") if k]
        hit = next((alias[k] for k in keys if k in alias), None)
        if hit is None:
            entry = {**rec, "found_by": [where]}
            by_key[entry["id"]] = entry
            for k in keys:
                alias[k] = entry["id"]
            continue
        dups += 1
        entry = by_key[hit]
        if where not in entry["found_by"]:
            entry["found_by"].append(where)
        for field in ("doi", "abstract", "oa_pdf_url", "oa_url", "journal"):
            if not entry.get(field) and rec.get(field):
                entry[field] = rec[field]
        for k in keys:
            alias.setdefault(k, hit)
    records = sorted(by_key.values(), key=lambda r: (r.get("year") or 0, r["id"]))
    return records, dups


def records_csv(records: list[dict[str, Any]]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "doi", "year", "title", "journal", "authors", "is_oa", "found_by", "has_abstract"])
    for r in records:
        w.writerow(
            [
                r["id"],
                r.get("doi", ""),
                r.get("year") or "",
                r.get("title", ""),
                r.get("journal", ""),
                "; ".join(r.get("authors", [])[:3]) + (" et al." if len(r.get("authors", [])) > 3 else ""),
                "yes" if r.get("is_oa") else "no",
                "; ".join(r.get("found_by", [])),
                "yes" if r.get("abstract") else "no",
            ]
        )
    return buf.getvalue()


def counts_md(log: dict[str, Any]) -> str:
    lines = [
        "# Search counts",
        "",
        "| Search | Database | Reported | Read | Query as sent |",
        "|---|---|---:|---:|---|",
    ]
    for s in log["searches"]:
        lines.append(
            f"| {s['name']} | {s['database']} | {s['count_reported']} | {s['records_read']} | `{s['query']}` |"
        )
    lines += [
        "",
        f"Records identified: {log['identified']}; duplicates removed: {log['duplicates_removed']}; "
        f"records to screen: {log['records']} ({log['with_abstract']} with an abstract, "
        f"{log['open_access']} open access).",
        f"Requests sent: {log['requests_sent']}; pages read from the cache: {log['pages_from_cache']}.",
    ]
    lines += [f"\nNote: {n}" for n in log.get("notes", [])]
    return "\n".join(lines) + "\n"
