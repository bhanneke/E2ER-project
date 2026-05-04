-- E2ER v3: append-only pipeline events log
CREATE TABLE pipeline_events (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    paper_id    UUID REFERENCES papers(id) ON DELETE CASCADE,
    event_type  TEXT NOT NULL,
    stage       TEXT,
    specialist  TEXT,
    payload     JSONB,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_events_paper ON pipeline_events(paper_id, created_at);

-- Trigger to update papers.updated_at on any change
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER papers_updated_at
    BEFORE UPDATE ON papers
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();
