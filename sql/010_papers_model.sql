-- E2ER v3: papers.model — which LLM model was used.
--
-- Needed by the first-run cost guardrail: a (model, methodology, mode) tuple
-- must have at least one paper with status='completed' before users can request
-- a cap > $1 without explicit acknowledgement. Without storing the model on
-- the paper row, we couldn't tell whether a prior completion validated the
-- same tuple the user is now requesting.
--
-- Additive migration; nullable so existing rows backfill cleanly.

ALTER TABLE papers
    ADD COLUMN model TEXT;

CREATE INDEX idx_papers_proven_tuple ON papers (model, methodology, mode, status);
