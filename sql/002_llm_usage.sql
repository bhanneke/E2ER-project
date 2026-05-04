-- E2ER v3: LLM token usage tracking
CREATE TABLE llm_usage (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    paper_id        UUID REFERENCES papers(id) ON DELETE CASCADE,
    specialist      TEXT NOT NULL,
    backend         TEXT NOT NULL,
    model           TEXT NOT NULL,
    input_tokens    INTEGER NOT NULL DEFAULT 0,
    output_tokens   INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens INTEGER NOT NULL DEFAULT 0,
    cache_write_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd        NUMERIC(10, 6),
    work_order_id   UUID,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_llm_usage_paper ON llm_usage(paper_id);
CREATE INDEX idx_llm_usage_model ON llm_usage(model, created_at);
