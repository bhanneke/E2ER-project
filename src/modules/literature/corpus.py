"""A local, growing library of structured reviews.

The pipeline's literature stage is per-paper and disposable: it searches, cites
thirty results, and throws the work away. Run it twice on neighbouring questions
and it does the same work twice, no better the second time. This is the opposite
— one SQLite file, outside any workspace, that accumulates across projects and
gets more useful as it grows.

What makes it worth keeping rather than re-running is that everything in it has
been checked. ``add_review`` refuses a claim whose evidence did not verify, so
the invariant holds at the door rather than by convention: if a claim is in this
database, its quote was found in the paper it is attributed to.

Search is over *claims*, not titles. "who found null effects for ETF listings"
should return the sentence, the paper and the section — which is the question a
researcher actually has, and the one a bibliography cannot answer.

Not to be confused with ``src/modules/local_corpus.py``, which is about folders
of BYOD files. This is the corpus of what papers say.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ...logging_config import get_logger
from .review import (
    SCHEMA_VERSION,
    StructuredReview,
    normalize,
    review_from_dict,
)

logger = get_logger(__name__)

#: Bumped when the tables change shape. Stored in `corpus_meta` so a future
#: version can tell an old file from a corrupt one.
CORPUS_SCHEMA = 1

DEFAULT_CORPUS_FILENAME = "corpus.db"


class CorpusError(RuntimeError):
    """Raised when something would violate the corpus's one guarantee."""


# ── paths ────────────────────────────────────────────────────────────────────


def corpus_path(explicit: str | Path | None = None) -> Path:
    """Where the corpus lives.

    Deliberately outside any workspace and shared across papers: a library that
    resets per project is not a library. ``CORPUS_DB`` overrides, which is what
    the tests use and what lets someone keep a corpus on an external drive.
    """
    if explicit:
        return Path(explicit).expanduser()

    try:
        from ...config import get_settings

        configured = get_settings().corpus_db
    except Exception:  # config is optional for a bare library call
        configured = None

    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".e2er" / DEFAULT_CORPUS_FILENAME


# ── schema ───────────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS corpus_meta (
    k TEXT PRIMARY KEY,
    v TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS corpus_papers (
    key           TEXT PRIMARY KEY,
    doi           TEXT,
    title         TEXT NOT NULL DEFAULT '',
    authors_json  TEXT NOT NULL DEFAULT '[]',
    year          INTEGER,
    source        TEXT NOT NULL DEFAULT '',
    access_license TEXT NOT NULL DEFAULT '',
    added_at      TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_papers_doi  ON corpus_papers(doi);
CREATE INDEX IF NOT EXISTS idx_papers_year ON corpus_papers(year);

CREATE TABLE IF NOT EXISTS corpus_reviews (
    key             TEXT PRIMARY KEY REFERENCES corpus_papers(key) ON DELETE CASCADE,
    schema_version  TEXT NOT NULL,
    extracted_at    TEXT NOT NULL DEFAULT '',
    extractor_model TEXT NOT NULL DEFAULT '',
    source_sha256   TEXT NOT NULL DEFAULT '',
    source_chars    INTEGER NOT NULL DEFAULT 0,
    review_json     TEXT NOT NULL,
    extraction_json TEXT NOT NULL DEFAULT '',
    n_claims        INTEGER NOT NULL DEFAULT 0
);

-- Denormalised on purpose: search hits claims, not papers, so the claim is the
-- row. A join per hit to reassemble a sentence would be the common path.
CREATE TABLE IF NOT EXISTS corpus_claims (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    key        TEXT NOT NULL REFERENCES corpus_papers(key) ON DELETE CASCADE,
    field      TEXT NOT NULL,
    text       TEXT NOT NULL,
    quote      TEXT NOT NULL,
    locator    TEXT NOT NULL DEFAULT '',
    char_start INTEGER NOT NULL DEFAULT -1
);
CREATE INDEX IF NOT EXISTS idx_claims_key   ON corpus_claims(key);
CREATE INDEX IF NOT EXISTS idx_claims_field ON corpus_claims(field);

CREATE TABLE IF NOT EXISTS corpus_topics (
    query      TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    last_run_at TEXT NOT NULL DEFAULT '',
    n_found    INTEGER NOT NULL DEFAULT 0,
    n_added    INTEGER NOT NULL DEFAULT 0
);
"""

_FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS claims_fts USING fts5(
    text, quote, claim_id UNINDEXED, key UNINDEXED
);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _has_fts5(conn: sqlite3.Connection) -> bool:
    """Is FTS5 compiled into this SQLite build?

    Present in CPython's bundled SQLite and in every mainstream build, but not
    guaranteed — some distro and minimal builds omit it. Search degrades to LIKE
    rather than the corpus refusing to open.
    """
    try:
        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS _fts_probe USING fts5(x)")
        conn.execute("DROP TABLE IF EXISTS _fts_probe")
        return True
    except sqlite3.Error:
        return False


def init_schema(conn: sqlite3.Connection) -> bool:
    """Create the tables if absent. Returns whether FTS5 search is available."""
    conn.executescript(_SCHEMA)
    fts = _has_fts5(conn)
    if fts:
        conn.executescript(_FTS_SCHEMA)
    conn.execute(
        "INSERT INTO corpus_meta (k, v) VALUES ('corpus_schema', ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v",
        (str(CORPUS_SCHEMA),),
    )
    conn.commit()
    return fts


@contextmanager
def connect(path: str | Path | None = None) -> Iterator[sqlite3.Connection]:
    """Open (creating if needed) the corpus. Always closes."""
    db = corpus_path(path)
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        init_schema(conn)
        yield conn
    finally:
        conn.close()


# ── identity ─────────────────────────────────────────────────────────────────


def normalize_doi(doi: str) -> str:
    """Bare, lowercased DOI. The only cross-corpus identifier that works."""
    d = (doi or "").strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if d.startswith(prefix):
            d = d[len(prefix) :]
    return d.strip()


def paper_key(review: StructuredReview) -> str:
    """A stable, deduplicating identity for a paper.

    DOI when there is one, because that is what two corpora can agree on. Then
    the hash of the source text, which catches the same PDF arriving twice
    without metadata. Title and year only as a last resort — they collide
    across preprint and published versions, which is a merge someone has to
    make deliberately rather than one the database should make silently.
    """
    import hashlib

    doi = normalize_doi(review.doi)
    if doi:
        return f"doi:{doi}"
    if review.source_sha256:
        return f"text:{review.source_sha256[:32]}"
    seed = normalize(f"{review.title}|{review.year or ''}").lower()
    return "title:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32]


# ── writing ──────────────────────────────────────────────────────────────────


@dataclass
class AddOutcome:
    key: str
    added: bool = False
    replaced: bool = False
    claims: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _unverified(review: StructuredReview) -> list[str]:
    return [f"{fname}: {claim.text[:80]}" for fname, claim in review.claims() if not claim.verified]


def add_review(
    conn: sqlite3.Connection,
    review: StructuredReview,
    *,
    extraction: dict[str, Any] | None = None,
    replace: bool = True,
) -> AddOutcome:
    """Store a verified review, replacing any earlier one for the same paper.

    Refuses a review containing an unverified claim. The extractor already drops
    those, so reaching this is a programming error rather than a bad paper — and
    the whole value of the corpus is that no such check is needed on the way
    out.
    """
    bad = _unverified(review)
    if bad:
        raise CorpusError(
            f"refusing to store {len(bad)} unverified claim(s): {bad[:3]}. "
            "Run verify_review() and drop_unverified() first."
        )

    key = paper_key(review)
    existing = conn.execute("SELECT key FROM corpus_papers WHERE key = ?", (key,)).fetchone()
    if existing and not replace:
        return AddOutcome(key=key, added=False, replaced=False)

    now = _now()
    doi = normalize_doi(review.doi)

    if existing:
        conn.execute(
            "UPDATE corpus_papers SET doi=?, title=?, authors_json=?, year=?, source=?, "
            "access_license=?, updated_at=? WHERE key=?",
            (
                doi,
                review.title,
                json.dumps(review.authors),
                review.year,
                review.source,
                review.access_license,
                now,
                key,
            ),
        )
    else:
        conn.execute(
            "INSERT INTO corpus_papers (key, doi, title, authors_json, year, source, access_license, "
            "added_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                key,
                doi,
                review.title,
                json.dumps(review.authors),
                review.year,
                review.source,
                review.access_license,
                now,
                now,
            ),
        )

    claims = review.claims()
    conn.execute(
        "INSERT INTO corpus_reviews (key, schema_version, extracted_at, extractor_model, source_sha256, "
        "source_chars, review_json, extraction_json, n_claims) VALUES (?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET schema_version=excluded.schema_version, "
        "extracted_at=excluded.extracted_at, extractor_model=excluded.extractor_model, "
        "source_sha256=excluded.source_sha256, source_chars=excluded.source_chars, "
        "review_json=excluded.review_json, extraction_json=excluded.extraction_json, "
        "n_claims=excluded.n_claims",
        (
            key,
            review.schema_version or SCHEMA_VERSION,
            review.extracted_at,
            review.extractor_model,
            review.source_sha256,
            review.source_chars,
            review.to_json(),
            json.dumps(extraction) if extraction else "",
            len(claims),
        ),
    )

    # Replace the claim rows wholesale: a re-extraction supersedes the old one,
    # and merging claim-by-claim would leave claims from a superseded reading of
    # the paper sitting alongside the current one.
    _delete_claims(conn, key)
    for fname, claim in claims:
        cur = conn.execute(
            "INSERT INTO corpus_claims (key, field, text, quote, locator, char_start) VALUES (?,?,?,?,?,?)",
            (key, fname, claim.text, claim.evidence.quote, claim.evidence.locator, claim.evidence.char_start),
        )
        if _fts_enabled(conn):
            conn.execute(
                "INSERT INTO claims_fts (text, quote, claim_id, key) VALUES (?,?,?,?)",
                (claim.text, claim.evidence.quote, cur.lastrowid, key),
            )

    conn.commit()
    return AddOutcome(key=key, added=not existing, replaced=bool(existing), claims=len(claims))


def _fts_enabled(conn: sqlite3.Connection) -> bool:
    row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='claims_fts'").fetchone()
    return row is not None


def _delete_claims(conn: sqlite3.Connection, key: str) -> None:
    if _fts_enabled(conn):
        conn.execute("DELETE FROM claims_fts WHERE key = ?", (key,))
    conn.execute("DELETE FROM corpus_claims WHERE key = ?", (key,))


def remove_paper(conn: sqlite3.Connection, key: str) -> bool:
    """Delete a paper and everything attached to it."""
    _delete_claims(conn, key)
    cur = conn.execute("DELETE FROM corpus_papers WHERE key = ?", (key,))
    conn.execute("DELETE FROM corpus_reviews WHERE key = ?", (key,))
    conn.commit()
    return cur.rowcount > 0


# ── reading ──────────────────────────────────────────────────────────────────


@dataclass
class PaperRow:
    key: str
    doi: str
    title: str
    authors: list[str]
    year: int | None
    source: str
    n_claims: int
    extractor_model: str = ""
    added_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ClaimHit:
    """A claim, with enough around it to be read without another query."""

    field: str
    text: str
    quote: str
    locator: str
    key: str
    title: str
    year: int | None
    doi: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def cite(self) -> str:
        who = self.title[:60] or self.key
        return f"{who} ({self.year})" if self.year else who


def has_paper(conn: sqlite3.Connection, key: str) -> bool:
    return conn.execute("SELECT 1 FROM corpus_papers WHERE key = ?", (key,)).fetchone() is not None


def has_doi(conn: sqlite3.Connection, doi: str) -> bool:
    """Is this DOI already covered? The question `refresh` asks before extracting."""
    d = normalize_doi(doi)
    if not d:
        return False
    return conn.execute("SELECT 1 FROM corpus_papers WHERE doi = ?", (d,)).fetchone() is not None


def get_review(conn: sqlite3.Connection, key: str) -> StructuredReview | None:
    row = conn.execute("SELECT review_json FROM corpus_reviews WHERE key = ?", (key,)).fetchone()
    if row is None:
        return None
    return review_from_dict(json.loads(row["review_json"]))


def get_extraction(conn: sqlite3.Connection, key: str) -> dict[str, Any] | None:
    """The extraction record, including what was rejected. Used by `stats`."""
    row = conn.execute("SELECT extraction_json FROM corpus_reviews WHERE key = ?", (key,)).fetchone()
    if row is None or not row["extraction_json"]:
        return None
    try:
        parsed: dict[str, Any] = json.loads(row["extraction_json"])
        return parsed
    except (ValueError, TypeError):
        return None


def _paper_row(row: sqlite3.Row) -> PaperRow:
    return PaperRow(
        key=row["key"],
        doi=row["doi"] or "",
        title=row["title"],
        authors=json.loads(row["authors_json"] or "[]"),
        year=row["year"],
        source=row["source"] or "",
        n_claims=row["n_claims"] or 0,
        extractor_model=(row["extractor_model"] if "extractor_model" in row.keys() else "") or "",
        added_at=row["added_at"] or "",
    )


def get_papers(conn: sqlite3.Connection, keys: list[str]) -> dict[str, PaperRow]:
    """Look up several papers by key at once, for turning search hits into citations."""
    if not keys:
        return {}
    placeholders = ",".join("?" for _ in keys)
    rows = conn.execute(
        "SELECT p.*, r.n_claims, r.extractor_model FROM corpus_papers p "
        f"LEFT JOIN corpus_reviews r ON r.key = p.key WHERE p.key IN ({placeholders})",
        keys,
    ).fetchall()
    return {r["key"]: _paper_row(r) for r in rows}


def list_papers(conn: sqlite3.Connection, *, limit: int = 50, offset: int = 0) -> list[PaperRow]:
    rows = conn.execute(
        "SELECT p.*, r.n_claims, r.extractor_model FROM corpus_papers p "
        "LEFT JOIN corpus_reviews r ON r.key = p.key "
        "ORDER BY p.added_at DESC, p.title LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    return [_paper_row(r) for r in rows]


# ── search ───────────────────────────────────────────────────────────────────

_TOKEN = re.compile(r"[A-Za-z0-9]+")


def fts_query(text: str) -> str:
    """Turn what a person typed into a legal FTS5 MATCH expression.

    Raw user text is not a valid MATCH expression: `null effects (ETF)` is a
    syntax error, and so is anything containing a bare hyphen, quote or
    parenthesis. Passing it through would turn an ordinary search term into a
    crash, so each alphanumeric run becomes a quoted phrase.

    Joined with OR rather than AND, then ranked by bm25. A natural-language
    question ANDed together matches nothing — every word would have to appear in
    the same claim — whereas OR with relevance ranking puts the claim that
    matches most of the question first, which is what a person typing a question
    means.
    """
    tokens = _TOKEN.findall(text or "")
    return " OR ".join(f'"{t}"' for t in tokens)


def search_claims(
    conn: sqlite3.Connection,
    query: str,
    *,
    limit: int = 20,
    fields: list[str] | None = None,
) -> list[ClaimHit]:
    """Full-text search over claims, most relevant first."""
    tokens = _TOKEN.findall(query or "")
    if not tokens:
        return []

    where_field = ""
    params: list[Any] = []
    if fields:
        where_field = f" AND c.field IN ({','.join('?' for _ in fields)})"
        params.extend(fields)

    if _fts_enabled(conn):
        sql = (
            "SELECT c.field, c.text, c.quote, c.locator, c.key, p.title, p.year, p.doi "
            "FROM claims_fts f "
            "JOIN corpus_claims c ON c.id = f.claim_id "
            "JOIN corpus_papers p ON p.key = c.key "
            "WHERE claims_fts MATCH ?" + where_field + " ORDER BY bm25(claims_fts) LIMIT ?"
        )
        try:
            rows = conn.execute(sql, [fts_query(query), *params, limit]).fetchall()
            return [_hit(r) for r in rows]
        except sqlite3.OperationalError as e:
            # Never let a search term become a crash; fall through to LIKE.
            logger.warning("corpus: FTS query failed (%s); falling back to LIKE", e)

    return _search_like(conn, tokens, limit=limit, where_field=where_field, field_params=params)


def _search_like(
    conn: sqlite3.Connection,
    tokens: list[str],
    *,
    limit: int,
    where_field: str,
    field_params: list[Any],
) -> list[ClaimHit]:
    """Ranked LIKE fallback for SQLite builds without FTS5.

    Slower and cruder, but a corpus that cannot be searched on an unusual build
    is a corpus that cannot be trusted to be there.
    """
    like_clauses = " OR ".join("(c.text LIKE ? OR c.quote LIKE ?)" for _ in tokens)
    score = " + ".join("(c.text LIKE ? OR c.quote LIKE ?)" for _ in tokens)
    patterns: list[Any] = []
    for t in tokens:
        patterns.extend([f"%{t}%", f"%{t}%"])

    sql = (
        f"SELECT c.field, c.text, c.quote, c.locator, c.key, p.title, p.year, p.doi, ({score}) AS score "
        "FROM corpus_claims c JOIN corpus_papers p ON p.key = c.key "
        f"WHERE ({like_clauses}){where_field} ORDER BY score DESC LIMIT ?"
    )
    rows = conn.execute(sql, [*patterns, *patterns, *field_params, limit]).fetchall()
    return [_hit(r) for r in rows]


def _hit(row: sqlite3.Row) -> ClaimHit:
    return ClaimHit(
        field=row["field"],
        text=row["text"],
        quote=row["quote"],
        locator=row["locator"] or "",
        key=row["key"],
        title=row["title"] or "",
        year=row["year"],
        doi=row["doi"] or "",
    )


def claims_for_papers(
    conn: sqlite3.Connection,
    keys: list[str],
    *,
    fields: list[str] | None = None,
) -> list[ClaimHit]:
    """Every claim for the given papers — what the pipeline reads."""
    if not keys:
        return []
    placeholders = ",".join("?" for _ in keys)
    sql = (
        "SELECT c.field, c.text, c.quote, c.locator, c.key, p.title, p.year, p.doi "
        "FROM corpus_claims c JOIN corpus_papers p ON p.key = c.key "
        f"WHERE c.key IN ({placeholders})"
    )
    params: list[Any] = list(keys)
    if fields:
        sql += f" AND c.field IN ({','.join('?' for _ in fields)})"
        params.extend(fields)
    sql += " ORDER BY p.year DESC, p.title, c.field"
    return [_hit(r) for r in conn.execute(sql, params).fetchall()]


# ── topics ───────────────────────────────────────────────────────────────────


@dataclass
class TopicRow:
    query: str
    created_at: str
    last_run_at: str
    n_found: int
    n_added: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def add_topic(conn: sqlite3.Connection, query: str) -> bool:
    """Register a standing interest. Returns False if already registered."""
    q = (query or "").strip()
    if not q:
        raise CorpusError("a topic needs a query")
    try:
        conn.execute("INSERT INTO corpus_topics (query, created_at) VALUES (?, ?)", (q, _now()))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def remove_topic(conn: sqlite3.Connection, query: str) -> bool:
    cur = conn.execute("DELETE FROM corpus_topics WHERE query = ?", ((query or "").strip(),))
    conn.commit()
    return cur.rowcount > 0


def list_topics(conn: sqlite3.Connection) -> list[TopicRow]:
    rows = conn.execute("SELECT * FROM corpus_topics ORDER BY created_at").fetchall()
    return [
        TopicRow(
            query=r["query"],
            created_at=r["created_at"],
            last_run_at=r["last_run_at"] or "",
            n_found=r["n_found"] or 0,
            n_added=r["n_added"] or 0,
        )
        for r in rows
    ]


def record_topic_run(conn: sqlite3.Connection, query: str, *, found: int, added: int) -> None:
    """Record that a topic was refreshed. Counts are cumulative."""
    conn.execute(
        "UPDATE corpus_topics SET last_run_at = ?, n_found = n_found + ?, n_added = n_added + ? WHERE query = ?",
        (_now(), found, added, (query or "").strip()),
    )
    conn.commit()


# ── statistics ───────────────────────────────────────────────────────────────


@dataclass
class CorpusStats:
    """What is in here, and what it cost to get it right.

    The second half is the part that is not bookkeeping. Every extraction
    records what the model proposed on its first pass and what survived, so the
    corpus carries a running measurement of how often a model fabricates a quote
    when it has been told the quote will be checked.
    """

    papers: int = 0
    reviews: int = 0
    claims: int = 0
    claims_by_field: dict[str, int] = field(default_factory=dict)
    papers_by_year: dict[str, int] = field(default_factory=dict)
    models: dict[str, int] = field(default_factory=dict)
    topics: int = 0

    first_pass_proposed: int = 0
    first_pass_rejected: int = 0
    rejections_by_field: dict[str, int] = field(default_factory=dict)
    rejections_by_reason: dict[str, int] = field(default_factory=dict)
    extractions_measured: int = 0

    @property
    def first_pass_rejection_rate(self) -> float | None:
        """Share of first-pass claims whose quote was not in the paper.

        ``None`` when nothing has been measured — which is not the same as zero,
        and a corpus imported from elsewhere will legitimately report it.
        """
        if not self.first_pass_proposed:
            return None
        return self.first_pass_rejected / self.first_pass_proposed

    def rejection_rate_by_field(self) -> dict[str, float]:
        """Where fabrication concentrates, as a share of that field's proposals."""
        out: dict[str, float] = {}
        for fname, rejected in self.rejections_by_field.items():
            kept = self.claims_by_field.get(fname, 0)
            proposed = kept + rejected
            if proposed:
                out[fname] = rejected / proposed
        return dict(sorted(out.items(), key=lambda kv: kv[1], reverse=True))

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["first_pass_rejection_rate"] = self.first_pass_rejection_rate
        d["rejection_rate_by_field"] = self.rejection_rate_by_field()
        return d


def stats(conn: sqlite3.Connection) -> CorpusStats:
    out = CorpusStats()
    out.papers = conn.execute("SELECT COUNT(*) AS n FROM corpus_papers").fetchone()["n"]
    out.reviews = conn.execute("SELECT COUNT(*) AS n FROM corpus_reviews").fetchone()["n"]
    out.claims = conn.execute("SELECT COUNT(*) AS n FROM corpus_claims").fetchone()["n"]
    out.topics = conn.execute("SELECT COUNT(*) AS n FROM corpus_topics").fetchone()["n"]

    for r in conn.execute("SELECT field, COUNT(*) AS n FROM corpus_claims GROUP BY field ORDER BY n DESC"):
        out.claims_by_field[r["field"]] = r["n"]
    for r in conn.execute(
        "SELECT COALESCE(CAST(year AS TEXT), 'unknown') AS y, COUNT(*) AS n "
        "FROM corpus_papers GROUP BY y ORDER BY y DESC"
    ):
        out.papers_by_year[r["y"]] = r["n"]
    for r in conn.execute(
        "SELECT COALESCE(NULLIF(extractor_model, ''), 'unknown') AS m, COUNT(*) AS n "
        "FROM corpus_reviews GROUP BY m ORDER BY n DESC"
    ):
        out.models[r["m"]] = r["n"]

    for r in conn.execute("SELECT extraction_json FROM corpus_reviews WHERE extraction_json != ''"):
        try:
            rec = json.loads(r["extraction_json"])
        except (ValueError, TypeError):
            continue
        attempts = rec.get("attempts") or []
        if not attempts:
            continue
        first = attempts[0]
        out.extractions_measured += 1
        out.first_pass_proposed += int(first.get("proposed") or 0)
        out.first_pass_rejected += int(first.get("rejected") or 0)
        for rej in first.get("rejections") or []:
            fname = str(rej.get("field") or "unknown")
            out.rejections_by_field[fname] = out.rejections_by_field.get(fname, 0) + 1
            reason = _reason_bucket(str(rej.get("reason") or ""))
            out.rejections_by_reason[reason] = out.rejections_by_reason.get(reason, 0) + 1

    return out


def _reason_bucket(reason: str) -> str:
    """Group rejection reasons; the char count in "too short" would fragment them."""
    if "too short" in reason:
        return "quote too short"
    if "no quote" in reason:
        return "no quote given"
    if "does not appear" in reason:
        return "quote not in source"
    return reason or "unknown"


# ── export ───────────────────────────────────────────────────────────────────


def export_corpus(conn: sqlite3.Connection, dest: Path) -> int:
    """Write every review as JSON, one file per paper, plus an index.

    The portable form. A corpus locked inside a SQLite file this project happens
    to write is not infrastructure anyone else can use; these files validate
    against the published schema and can be read by anything.
    """
    dest = Path(dest).expanduser()
    (dest / "reviews").mkdir(parents=True, exist_ok=True)

    index: list[dict[str, Any]] = []
    written = 0
    for paper in list_papers(conn, limit=1_000_000):
        review = get_review(conn, paper.key)
        if review is None:
            continue
        record = review.to_dict()
        extraction = get_extraction(conn, paper.key)
        if extraction and extraction.get("verification"):
            record["verification"] = extraction["verification"]

        name = re.sub(r"[^A-Za-z0-9._-]", "_", paper.key) + ".json"
        (dest / "reviews" / name).write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
        index.append(
            {"key": paper.key, "doi": paper.doi, "title": paper.title, "year": paper.year, "file": f"reviews/{name}"}
        )
        written += 1

    (dest / "index.json").write_text(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "corpus_schema": CORPUS_SCHEMA,
                "exported_at": _now(),
                "papers": written,
                "index": index,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return written
