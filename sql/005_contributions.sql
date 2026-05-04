-- E2ER v3: specialist contributions log
CREATE TABLE contributions (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    paper_id        UUID REFERENCES papers(id) ON DELETE CASCADE,
    specialist      TEXT NOT NULL,
    stage           TEXT,
    output_file     TEXT,
    success         BOOLEAN NOT NULL DEFAULT TRUE,
    error_msg       TEXT,
    usage_tokens    INTEGER DEFAULT 0,
    cost_usd        NUMERIC(10, 6),
    duration_sec    NUMERIC(8, 2),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_contributions_paper ON contributions(paper_id);
