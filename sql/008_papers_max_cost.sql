-- Per-paper cost cap. Pipeline aborts when cumulative llm_usage.cost_usd >= max_cost_usd.
ALTER TABLE papers ADD COLUMN IF NOT EXISTS max_cost_usd NUMERIC(10, 4) DEFAULT 25.0;
