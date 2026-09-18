-- E2ER v3: papers.review_stages — human-in-the-loop checkpoints.
--
-- A JSON array of pipeline stage names (from PIPELINE_STAGES) after which the
-- run pauses for the researcher to inspect / edit the workspace before
-- continuing. NULL / "[]" means unattended (the current behaviour).
--
-- Stored as text (JSON) rather than a child table: it is a small, per-paper
-- config list read only at run start + resume.

ALTER TABLE papers
    ADD COLUMN review_stages TEXT;
