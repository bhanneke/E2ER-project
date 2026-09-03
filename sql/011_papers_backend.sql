-- E2ER v3: papers.backend — which LLM backend produced this paper.
--
-- The backend (anthropic | openrouter | claude_code | codex | gemini) was
-- previously a process-global config value, so two papers on one server
-- could not differ. Per-paper backend selection powers multi-model runs
-- (the same RQ + data across k backends, compared afterwards) and the
-- governance experiment. Storing it on the row makes each paper's regime
-- disclosable and lets the experiment harvester group by backend.
--
-- Additive, nullable so existing rows backfill cleanly (NULL = the server
-- default backend that was active at run time).

ALTER TABLE papers
    ADD COLUMN backend TEXT;
