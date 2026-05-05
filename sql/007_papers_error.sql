-- Add last_error column to papers for surfacing pipeline failures
ALTER TABLE papers ADD COLUMN IF NOT EXISTS last_error TEXT;
