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

# Inside the container uvicorn binds 0.0.0.0 so the port mapping reaches it; docker-compose.yml
# publishes it on the host's 127.0.0.1 only. Bound to every interface, the API needs a bearer
# token: refuse to start without API_AUTH_TOKEN (every API request then sends
# `Authorization: Bearer <token>`). E2ER_ALLOWED_HOSTS names extra Host headers to accept.
if [ -z "${API_AUTH_TOKEN:-}" ]; then
    echo "[entrypoint] API_AUTH_TOKEN is not set. Set it in .env (for example: openssl rand -hex 32) and start again." >&2
    exit 1
fi

echo "[entrypoint] starting uvicorn on 0.0.0.0:8280 (published on 127.0.0.1:8280 by docker-compose.yml)"
exec uvicorn src.api.app:app --host 0.0.0.0 --port 8280 --workers 1
