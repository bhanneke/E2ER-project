-- E2ER v3: core papers table
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE papers (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    title       TEXT NOT NULL,
    research_question TEXT,
    status      TEXT NOT NULL DEFAULT 'idea',
    mode        TEXT NOT NULL DEFAULT 'iterative',
    workspace   TEXT,
    github_repo TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_papers_status ON papers(status);
