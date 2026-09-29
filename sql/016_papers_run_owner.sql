-- e2er 0.12.1: which server process owns a running paper.
--
-- Two e2er servers can share one database. At start-up each server pauses the
-- papers a stopped server left "running"; before this migration it paused
-- every such paper, including one another live server was still running.
-- run_owner records the owner when a run starts or resumes (JSON: host, pid,
-- process start time, port, a per-process instance id); heartbeat_at is
-- refreshed while the run is alive. Start-up recovery pauses a paper only
-- when its owner is gone.
--
-- Bookkeeping columns (study, archive, owner, heartbeat) do not move
-- updated_at, which the dashboard sorts by: archiving a study or a heartbeat
-- is not activity on the paper. The trigger below replaces the one from 006
-- for the papers table only; update_updated_at() stays for other tables.
--
-- Idempotent: safe to run again.

ALTER TABLE papers ADD COLUMN IF NOT EXISTS run_owner TEXT;
ALTER TABLE papers ADD COLUMN IF NOT EXISTS heartbeat_at TIMESTAMPTZ;

CREATE OR REPLACE FUNCTION papers_touch_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.study_key IS DISTINCT FROM OLD.study_key
       OR NEW.study_override IS DISTINCT FROM OLD.study_override
       OR NEW.archived_at IS DISTINCT FROM OLD.archived_at
       OR NEW.run_owner IS DISTINCT FROM OLD.run_owner
       OR NEW.heartbeat_at IS DISTINCT FROM OLD.heartbeat_at THEN
        RETURN NEW;
    END IF;
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS papers_updated_at ON papers;
CREATE TRIGGER papers_updated_at
    BEFORE UPDATE ON papers
    FOR EACH ROW EXECUTE FUNCTION papers_touch_updated_at();
