-- E2ER v3: SQLite-compatible schema.
--
-- Mirror of the Postgres migrations under sql/00X_*.sql, with PG-specific
-- features replaced:
--   - UUID         → TEXT (UUIDs as strings, generated app-side via uuid.uuid4())
--   - TIMESTAMPTZ  → TEXT (ISO 8601 strings, set via datetime('now'))
--   - JSONB        → TEXT (JSON serialised app-side)
--   - NUMERIC      → REAL
--   - BOOLEAN      → INTEGER (0/1)
--   - DEFAULT NOW()/uuid_generate_v4() → triggers + app-side defaults
--   - CHECK constraints stay (SQLite supports them)
--   - FK constraints stay; SQLite needs PRAGMA foreign_keys=ON (set at connect)
--
-- pgvector-dependent literature/KB tables are SKIPPED. Users who need the
-- KB feature must run Postgres.

PRAGMA foreign_keys = ON;

-- ── papers ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS papers (
    id                TEXT PRIMARY KEY,
    title             TEXT NOT NULL,
    research_question TEXT,
    status            TEXT NOT NULL DEFAULT 'idea',
    mode              TEXT NOT NULL DEFAULT 'iterative',
    workspace         TEXT,
    github_repo       TEXT,
    last_error        TEXT,
    max_cost_usd      REAL DEFAULT 25.0,
    methodology       TEXT NOT NULL DEFAULT 'empirical'
                      CHECK (methodology IN ('empirical', 'theoretical', 'mixed')),
    model             TEXT,
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_papers_status ON papers(status);
CREATE INDEX IF NOT EXISTS idx_papers_methodology ON papers(methodology);
CREATE INDEX IF NOT EXISTS idx_papers_proven_tuple ON papers (model, methodology, mode, status);

-- Trigger to mimic Postgres's update_updated_at on UPDATE.
CREATE TRIGGER IF NOT EXISTS papers_updated_at
    AFTER UPDATE ON papers
    FOR EACH ROW
    WHEN NEW.updated_at = OLD.updated_at
    BEGIN
        UPDATE papers SET updated_at = datetime('now') WHERE id = NEW.id;
    END;

-- ── llm_usage ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS llm_usage (
    id                 TEXT PRIMARY KEY,
    paper_id           TEXT REFERENCES papers(id) ON DELETE CASCADE,
    specialist         TEXT NOT NULL,
    backend            TEXT NOT NULL,
    model              TEXT NOT NULL,
    input_tokens       INTEGER NOT NULL DEFAULT 0,
    output_tokens      INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens  INTEGER NOT NULL DEFAULT 0,
    cache_write_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd           REAL,
    work_order_id      TEXT,
    created_at         TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_llm_usage_paper ON llm_usage(paper_id);
CREATE INDEX IF NOT EXISTS idx_llm_usage_model ON llm_usage(model, created_at);

-- ── data_query_records ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS data_query_records (
    id                TEXT PRIMARY KEY,
    paper_id          TEXT REFERENCES papers(id) ON DELETE CASCADE,
    specialist        TEXT NOT NULL,
    query_sql         TEXT NOT NULL,
    query_type        TEXT NOT NULL CHECK (query_type IN ('feasibility', 'production')),
    fields_requested  TEXT,  -- JSON
    aggregation_level TEXT,
    estimated_rows    INTEGER,
    actual_rows       INTEGER,
    validation_status TEXT NOT NULL DEFAULT 'pending'
                      CHECK (validation_status IN ('pending', 'approved', 'rejected')),
    approved_by       TEXT,
    approved_at       TEXT,
    executed_at       TEXT,
    created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS data_approval_requests (
    id              TEXT PRIMARY KEY,
    query_record_id TEXT REFERENCES data_query_records(id) ON DELETE CASCADE,
    paper_id        TEXT REFERENCES papers(id) ON DELETE CASCADE,
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'approved', 'rejected')),
    note            TEXT,
    reviewed_at     TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_dqr_paper ON data_query_records(paper_id);
CREATE INDEX IF NOT EXISTS idx_dar_status ON data_approval_requests(status);
CREATE INDEX IF NOT EXISTS idx_dar_query ON data_approval_requests(query_record_id);

-- ── contributions ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS contributions (
    id           TEXT PRIMARY KEY,
    paper_id     TEXT REFERENCES papers(id) ON DELETE CASCADE,
    specialist   TEXT NOT NULL,
    stage        TEXT,
    output_file  TEXT,
    success      INTEGER NOT NULL DEFAULT 1,  -- BOOLEAN as 0/1
    error_msg    TEXT,
    usage_tokens INTEGER DEFAULT 0,
    cost_usd     REAL,
    duration_sec REAL,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_contributions_paper ON contributions(paper_id);

-- ── pipeline_events ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS pipeline_events (
    id          TEXT PRIMARY KEY,
    paper_id    TEXT REFERENCES papers(id) ON DELETE CASCADE,
    event_type  TEXT NOT NULL,
    stage       TEXT,
    specialist  TEXT,
    payload     TEXT,  -- JSON
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_events_paper ON pipeline_events(paper_id, created_at);

-- ── literature_items (SQLite local library) ──────────────────────────────
-- The Postgres schema's literature_items carries a pgvector `embedding` and a
-- UNIQUE(doi) for the KB. On SQLite we persist the researcher's BYOD library
-- (discovered from LITERATURE_DIR / a Zotero folder) so search_papers can serve
-- it offline. DOI is NOT unique here — a BYOD library legitimately holds
-- DOI-less items; dedup is enforced app-side per (paper_id, doi|title+year).
CREATE TABLE IF NOT EXISTS literature_items (
    id          TEXT PRIMARY KEY,
    paper_id    TEXT REFERENCES papers(id) ON DELETE CASCADE,
    title       TEXT NOT NULL,
    authors     TEXT,            -- JSON array string
    year        INTEGER,
    doi         TEXT,
    abstract    TEXT,
    journal     TEXT,
    url         TEXT,
    pdf_url     TEXT,
    pdf_path    TEXT,            -- workspace-relative path to a staged PDF
    source      TEXT,
    citations   INTEGER DEFAULT 0,
    raw         TEXT,            -- JSON string
    embedding   BLOB,            -- optional float32 vector (NULL unless enabled)
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_lit_paper ON literature_items(paper_id);
CREATE INDEX IF NOT EXISTS idx_lit_doi ON literature_items(doi);

CREATE TRIGGER IF NOT EXISTS literature_items_updated_at
    AFTER UPDATE ON literature_items
    FOR EACH ROW
    WHEN NEW.updated_at = OLD.updated_at
    BEGIN
        UPDATE literature_items SET updated_at = datetime('now') WHERE id = NEW.id;
    END;
