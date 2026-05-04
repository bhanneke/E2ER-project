-- E2ER v3: Allium data query records and approval workflow
CREATE TABLE data_query_records (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    paper_id            UUID REFERENCES papers(id) ON DELETE CASCADE,
    specialist          TEXT NOT NULL,
    query_sql           TEXT NOT NULL,
    query_type          TEXT NOT NULL CHECK (query_type IN ('feasibility', 'production')),
    fields_requested    JSONB,
    aggregation_level   TEXT,
    estimated_rows      INTEGER,
    actual_rows         INTEGER,
    validation_status   TEXT NOT NULL DEFAULT 'pending'
                        CHECK (validation_status IN ('pending', 'approved', 'rejected')),
    approved_by         TEXT,
    approved_at         TIMESTAMPTZ,
    executed_at         TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE data_approval_requests (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    query_record_id     UUID REFERENCES data_query_records(id) ON DELETE CASCADE,
    paper_id            UUID REFERENCES papers(id) ON DELETE CASCADE,
    status              TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'approved', 'rejected')),
    note                TEXT,
    reviewed_at         TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_dqr_paper ON data_query_records(paper_id);
CREATE INDEX idx_dar_status ON data_approval_requests(status);
CREATE INDEX idx_dar_query ON data_approval_requests(query_record_id);
