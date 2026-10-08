"""Retrieve a boundary from OpenAlex: the papers a search, a journal set and a year range select.

Keyless requests to OpenAlex draw on a daily budget shared by every machine
behind the same public address. So retrieval here is careful with requests:

- one request first reads how many papers the boundary holds (``per-page=1``);
  a boundary above ``max_papers`` is refused before anything else is fetched;
- pages are read with cursor paging, ``per-page`` 100 (a page with abstracts and
  reference lists stays far below the 2 MB response cap of e2er's HTTP client);
- every command has a request ceiling (``max_requests``) and stops at it;
- each page is cached in the study's workspace by the address it was read
  from, so a rerun with the same boundary sends no request;
- requests carry the contact address of e2er's settings (``UNPAYWALL_EMAIL``,
  OpenAlex's polite pool), and ``OPENALEX_API_KEY`` when it is set, as a bearer
  token (it never appears in an address, a log or the cache).

OpenAlex data are CC0. A boundary file records the filter, the time of
retrieval, the counts and the number of requests sent.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ...logging_config import get_logger
from .network import short_id

logger = get_logger(__name__)

API = "https://api.openalex.org"
PER_PAGE = 100
#: Fields read for each work. Abstracts are kept for the lanes step (titles and abstracts).
SELECT = (
    "id,doi,title,publication_year,publication_date,type,primary_location,authorships,"
    "referenced_works,referenced_works_count,cited_by_count,abstract_inverted_index,keywords"
)
#: Where a search may look.
SEARCH_FIELDS = {
    "title_abstract": "title_and_abstract.search",
    "title": "title.search",
    "all": "default.search",
}
DEFAULT_TYPES = ("article", "review")


class BoundaryError(ValueError):
    """A boundary that cannot be retrieved as written (or would cost too many requests)."""


Fetch = Callable[[str, dict[str, str]], str]


class HTTPError(RuntimeError):
    """A response OpenAlex answered with an error status (the body kept for the reason)."""

    def __init__(self, status: int, body: str) -> None:
        super().__init__(f"HTTP {status}: {body[:300]}")
        self.status = status
        self.body = body


def _default_fetch(url: str, headers: dict[str, str]) -> str:
    import httpx

    with httpx.Client(timeout=60.0, follow_redirects=True) as client:
        resp = client.get(url, headers=headers)
    if resp.status_code >= 400:
        raise HTTPError(resp.status_code, resp.text)
    return resp.text


@dataclass
class Budget:
    """Requests sent by one command, against its ceiling."""

    limit: int
    sent: int = 0
    cached: int = 0

    def spend(self) -> None:
        if self.sent >= self.limit:
            raise BoundaryError(
                f"the request ceiling of {self.limit} OpenAlex requests is reached; narrow the boundary "
                "or raise --max-requests"
            )
        self.sent += 1


@dataclass
class Client:
    """A small OpenAlex client: polite pool, optional key, cache, request ceiling, pacing."""

    cache_dir: Path | None = None
    budget: Budget = field(default_factory=lambda: Budget(limit=300))
    mailto: str = ""
    api_key: str = ""
    fetch: Fetch = _default_fetch
    pause_s: float = 0.12
    retries: int = 3

    @classmethod
    def from_settings(cls, cache_dir: Path | None, max_requests: int = 300, **kw: Any) -> Client:
        try:
            from ...config import get_settings

            s = get_settings()
            mailto = getattr(s, "unpaywall_email", "") or ""
            key = getattr(s, "openalex_api_key", None) or ""
        except Exception:  # noqa: BLE001 — settings are optional for this client
            mailto, key = "", ""
        return cls(cache_dir=cache_dir, budget=Budget(limit=max_requests), mailto=mailto, api_key=key, **kw)

    def _url(self, path: str, params: dict[str, Any]) -> str:
        q = {k: v for k, v in params.items() if v not in (None, "")}
        if self.mailto:
            q["mailto"] = self.mailto
        return f"{API}/{path}?{urllib.parse.urlencode(q, safe=':,|*')}"

    def get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        url = self._url(path, params)
        cache = None
        if self.cache_dir is not None:
            cache = self.cache_dir / (hashlib.sha256(url.encode()).hexdigest()[:32] + ".json")
            if cache.is_file():
                try:
                    self.budget.cached += 1
                    return json.loads(cache.read_text(encoding="utf-8"))
                except ValueError:
                    pass
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        last: Exception | None = None
        for attempt in range(self.retries):
            self.budget.spend()
            try:
                text = self.fetch(url, headers)
                data = json.loads(text)
                break
            except Exception as e:  # noqa: BLE001 — retried, then reported
                last = e
                if isinstance(e, HTTPError) and e.status == 400:
                    raise BoundaryError(f"OpenAlex did not accept the request: {e.body[:500]}") from e
                if isinstance(e, HTTPError) and "budget" in e.body.lower():
                    raise BoundaryError(
                        "OpenAlex refused the request: the daily budget for requests without a key is spent "
                        "(it is shared by every machine on this network). Set OPENALEX_API_KEY (free) or retry "
                        "after midnight UTC."
                    ) from e
                time.sleep(self.pause_s * (2**attempt) * 5)
        else:
            raise BoundaryError(f"OpenAlex request failed after {self.retries} attempts: {last}")
        if self.pause_s:
            time.sleep(self.pause_s)
        if cache is not None:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(data), encoding="utf-8")
        return data


# ── the boundary ────────────────────────────────────────────────────────────


def normalise_boundary(raw: dict[str, Any]) -> dict[str, Any]:
    """A boundary as the retrieval reads it, checked; raises BoundaryError on a mistake."""
    if not isinstance(raw, dict):
        raise BoundaryError("a boundary must be a JSON object")
    name = str(raw.get("name") or "").strip()
    if not name or not all(c.isalnum() or c in "-_" for c in name):
        raise BoundaryError(f"boundary name {name!r} must be letters, digits, - or _")
    query = str(raw.get("query") or "").strip()
    if "," in query:
        raise BoundaryError(f"boundary {name}: the query may not contain commas; join terms with OR or AND")
    sources = [short_id(s).upper() for s in raw.get("sources") or []]
    if not query and not sources:
        raise BoundaryError(f"boundary {name}: needs a query, a set of sources, or both")
    for s in sources:
        if not (s.startswith("S") and s[1:].isdigit()):
            raise BoundaryError(f"boundary {name}: {s!r} is not an OpenAlex source id (S followed by digits)")
    search_in = str(raw.get("search_in") or "title_abstract")
    if search_in not in SEARCH_FIELDS:
        raise BoundaryError(f"boundary {name}: search_in must be one of {', '.join(SEARCH_FIELDS)}")
    from_year, to_year = raw.get("from_year"), raw.get("to_year")
    for label, y in (("from_year", from_year), ("to_year", to_year)):
        if y is not None and (isinstance(y, bool) or not isinstance(y, int) or not 1500 <= y <= 2100):
            raise BoundaryError(f"boundary {name}: {label} must be a year")
    if from_year and to_year and from_year > to_year:
        raise BoundaryError(f"boundary {name}: from_year is after to_year")
    raw_types = raw.get("types")
    types = [str(t) for t in (raw_types if raw_types is not None else DEFAULT_TYPES)]
    exclude = sorted({short_id(x) for x in raw.get("exclude") or []})
    return {
        "name": name,
        "query": query,
        "search_in": search_in,
        "sources": sorted(set(sources)),
        "from_year": from_year,
        "to_year": to_year,
        "types": types,
        "exclude": exclude,
        "note": str(raw.get("note") or ""),
    }


def openalex_filter(b: dict[str, Any]) -> str:
    """The OpenAlex ``filter`` parameter of a normalised boundary."""
    parts: list[str] = []
    if b["query"]:
        parts.append(f"{SEARCH_FIELDS[b['search_in']]}:{b['query']}")
    if b["sources"]:
        parts.append("primary_location.source.id:" + "|".join(b["sources"]))
    if b["from_year"] and b["to_year"]:
        parts.append(f"publication_year:{b['from_year']}-{b['to_year']}")
    elif b["from_year"]:
        parts.append(f"publication_year:>{b['from_year'] - 1}")
    elif b["to_year"]:
        parts.append(f"publication_year:<{b['to_year'] + 1}")
    if b["types"]:
        parts.append("type:" + "|".join(b["types"]))
    parts.append("is_paratext:false")
    return ",".join(parts)


def boundary_hash(b: dict[str, Any]) -> str:
    """Identifies what a boundary selects (name and note excluded)."""
    core = {k: v for k, v in b.items() if k not in ("name", "note")}
    return hashlib.sha256(json.dumps(core, sort_keys=True).encode()).hexdigest()[:16]


def abstract_text(inverted: dict[str, list[int]] | None) -> str:
    if not inverted:
        return ""
    pos = sorted((p, w) for w, ps in inverted.items() for p in ps)
    return " ".join(w for _, w in pos)


def parse_work(w: dict[str, Any]) -> dict[str, Any]:
    """The fields of one OpenAlex work the field map uses."""
    loc = w.get("primary_location") or {}
    src = loc.get("source") or {}
    doi = str(w.get("doi") or "")
    if doi.startswith("https://doi.org/"):
        doi = doi[len("https://doi.org/") :]
    authors = [(a.get("author") or {}).get("display_name") or "" for a in w.get("authorships") or []]
    return {
        "id": short_id(w.get("id") or ""),
        "doi": doi,
        "title": w.get("title") or "",
        "year": w.get("publication_year"),
        "date": w.get("publication_date") or "",
        "type": w.get("type") or "",
        "journal": src.get("display_name") or "",
        "source_id": short_id(src.get("id") or ""),
        "authors": [a for a in authors if a],
        "references": sorted({short_id(r) for r in w.get("referenced_works") or []}),
        "reference_count": int(w.get("referenced_works_count") or 0),
        "cited_by_count": int(w.get("cited_by_count") or 0),
        "abstract": abstract_text(w.get("abstract_inverted_index")),
        "keywords": [k.get("display_name") for k in w.get("keywords") or [] if k.get("display_name")],
    }


def count(client: Client, b: dict[str, Any]) -> int:
    """How many works the boundary selects (one request)."""
    data = client.get("works", {"filter": openalex_filter(b), "per-page": 1, "select": "id"})
    return int((data.get("meta") or {}).get("count") or 0)


def retrieve(client: Client, b: dict[str, Any], *, max_papers: int = 5000) -> dict[str, Any]:
    """Every work of the boundary, with the filter, counts and requests used."""
    flt = openalex_filter(b)
    reported = count(client, b)
    if reported > max_papers:
        raise BoundaryError(
            f"boundary {b['name']} selects {reported} papers, above the limit of {max_papers}; narrow the "
            "query, the journals or the years (a main path analysis is usually run on 300 to 2,000 papers)"
        )
    works: list[dict[str, Any]] = []
    cursor = "*"
    while cursor:
        data = client.get("works", {"filter": flt, "per-page": PER_PAGE, "cursor": cursor, "select": SELECT})
        page = data.get("results") or []
        works.extend(parse_work(w) for w in page)
        nxt = (data.get("meta") or {}).get("next_cursor")
        cursor = nxt if page and nxt else ""
    seen: set[str] = set()
    unique = []
    for w in works:
        if w["id"] and w["id"] not in seen:
            seen.add(w["id"])
            unique.append(w)
    unique.sort(key=lambda w: (w["year"] or 9999, w["date"], w["id"]))
    return {
        "boundary": b,
        "filter": flt,
        "hash": boundary_hash(b),
        "count_reported": reported,
        "papers_retrieved": len(unique),
        "papers": unique,
    }


def find_sources(client: Client, name: str, limit: int = 8) -> list[dict[str, Any]]:
    """Journals (OpenAlex sources) matching a name, for writing a journal set (one request)."""
    data = client.get(
        "sources",
        {
            "search": name.replace("?", " ").replace("*", " "),
            "per-page": limit,
            "select": "id,display_name,issn_l,type,works_count,host_organization_name",
        },
    )
    return [
        {
            "id": short_id(s.get("id") or ""),
            "name": s.get("display_name"),
            "issn_l": s.get("issn_l"),
            "type": s.get("type"),
            "works": s.get("works_count"),
            "publisher": s.get("host_organization_name"),
        }
        for s in data.get("results") or []
    ]
