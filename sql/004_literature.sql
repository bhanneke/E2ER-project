-- E2ER v3: literature items and optional pgvector embeddings
CREATE TABLE literature_items (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    paper_id    UUID REFERENCES papers(id) ON DELETE CASCADE,
    title       TEXT NOT NULL,
    authors     JSONB,
    year        INTEGER,
    doi         TEXT UNIQUE,
    abstract    TEXT,
    journal     TEXT,
    url         TEXT,
    pdf_url     TEXT,
    source      TEXT,
    citations   INTEGER DEFAULT 0,
    raw         JSONB,
    embedding   vector(384),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_lit_paper ON literature_items(paper_id);
CREATE INDEX idx_lit_doi ON literature_items(doi) WHERE doi IS NOT NULL;
-- Vector index created separately once data is loaded (for HNSW performance)
-- CREATE INDEX idx_lit_embedding ON literature_items USING hnsw (embedding vector_cosine_ops);
