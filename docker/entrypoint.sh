#!/usr/bin/env bash
# Docker entrypoint: vendor htmx if missing, run migrations, start uvicorn.
# Migrations and htmx vendoring are both idempotent so this is safe to run
# on every container start.
set -e

cd /app

# Fetch htmx if it isn't bundled yet (e.g. first build or stale image layer).
if [ ! -s src/api/static/htmx.min.js ]; then
    echo "[entrypoint] vendoring htmx..."
    bash scripts/vendor_htmx.sh || echo "[entrypoint] htmx fetch failed; falling back to CDN at runtime"
fi

# Apply any new migrations. The script is idempotent: SQL files use
# CREATE TABLE IF NOT EXISTS / ADD COLUMN IF NOT EXISTS, and migrate.py
# logs but does not abort on individual statement errors.
echo "[entrypoint] running migrations..."
python scripts/migrate.py || echo "[entrypoint] migrations finished with errors (likely already applied)"

echo "[entrypoint] starting uvicorn on 0.0.0.0:8280"
exec uvicorn src.api.app:app --host 0.0.0.0 --port 8280 --workers 1
