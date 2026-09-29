-- e2er 0.12.1: studies and archiving.
--
-- A study is the group of attempts (rows in papers) that share a normalised
-- research question and a template. study_key is derived from those two and
-- filled by the application (src/db/studies.py), which also backfills rows
-- that predate this migration; the normalisation (case-folding, trailing
-- punctuation) lives in Python so SQLite and Postgres agree on it.
-- study_override holds the researcher's choice when an attempt is moved to
-- another study or split off; the effective study is
-- COALESCE(study_override, study_key).
--
-- archived_at hides an attempt from the default lists. Archiving never
-- deletes a row, a file or a workspace.
--
-- Idempotent: safe to run again.

ALTER TABLE papers ADD COLUMN IF NOT EXISTS study_key TEXT;
ALTER TABLE papers ADD COLUMN IF NOT EXISTS study_override TEXT;
ALTER TABLE papers ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_papers_study ON papers (study_key);
CREATE INDEX IF NOT EXISTS idx_papers_archived ON papers (archived_at);
