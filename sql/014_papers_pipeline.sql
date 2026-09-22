-- E2ER v3: papers.pipeline — which pipeline file produced this paper.
--
-- Deliberately NOT a CHECK constraint, unlike papers.methodology above it.
-- Pipelines are files on disk that users add — project-local, ~/.e2er/pipelines,
-- or builtin — so the set of legal values is open by design. A CHECK would mean
-- that writing a new pipeline required a database migration, which would defeat
-- the point of pipelines being files.
--
-- It has to be stored rather than re-chosen at run time because resume reads
-- this row: a paper that started under one pipeline must resume under the same
-- one, or the second half of the run would follow a different DAG than the
-- first half produced state for.

ALTER TABLE papers
    ADD COLUMN pipeline TEXT NOT NULL DEFAULT 'empirical';
