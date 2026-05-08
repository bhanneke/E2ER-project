#!/usr/bin/env bash
# E2ER quickstart: copy .env, prompt for API key if missing, build + run.
# Run from the repo root: ./scripts/quickstart.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# 0. Pre-flight checks — fail fast with actionable hints.
if ! command -v docker >/dev/null 2>&1; then
    echo "✗ docker not found on PATH." >&2
    echo "  Install Docker Desktop (https://www.docker.com/products/docker-desktop) and retry." >&2
    echo "  To run without Docker, see the Manual install section in README.md." >&2
    exit 1
fi
if ! docker info >/dev/null 2>&1; then
    echo "✗ docker daemon is not running." >&2
    echo "  Start Docker Desktop (or 'sudo systemctl start docker' on Linux) and retry." >&2
    exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
    echo "✗ docker compose subcommand not available." >&2
    echo "  Install Docker Compose v2 (https://docs.docker.com/compose/install/) and retry." >&2
    exit 1
fi

# 1. .env file
if [ ! -f .env ]; then
    echo "→ creating .env from .env.example"
    cp .env.example .env
fi

# 2. Make sure we have an Anthropic API key (or OpenRouter, but Anthropic is the default)
needs_key=false
if ! grep -E '^ANTHROPIC_API_KEY=sk-' .env >/dev/null 2>&1; then
    if ! grep -E '^OPENROUTER_API_KEY=sk-' .env >/dev/null 2>&1; then
        needs_key=true
    fi
fi
if [ "$needs_key" = true ]; then
    echo "→ no API key configured in .env"
    read -r -p "  Enter your Anthropic API key (sk-ant-...): " key
    if [ -z "$key" ]; then
        echo "  no key entered; edit .env manually and re-run." >&2
        exit 1
    fi
    # macOS sed needs '' after -i; this works on both BSD and GNU sed.
    if sed --version >/dev/null 2>&1; then
        sed -i "s|^ANTHROPIC_API_KEY=.*|ANTHROPIC_API_KEY=$key|" .env
    else
        sed -i '' "s|^ANTHROPIC_API_KEY=.*|ANTHROPIC_API_KEY=$key|" .env
    fi
    echo "  ✓ ANTHROPIC_API_KEY written"
fi

# 3. Build + start
echo "→ docker compose up -d --build"
if ! docker compose -f docker/docker-compose.yml up -d --build; then
    echo "✗ docker compose build/up failed." >&2
    echo "  Common causes:" >&2
    echo "    • Out of disk space — 'docker system prune' may help." >&2
    echo "    • Port 8280 or 5432 already in use — 'lsof -i :8280' / change PORT in .env." >&2
    echo "    • Old container collision — 'docker compose -f docker/docker-compose.yml down' and retry." >&2
    exit 1
fi

# 4. Wait for the app health endpoint to come up.
echo -n "→ waiting for http://localhost:8280/health "
for i in $(seq 1 60); do
    if curl -fsS http://localhost:8280/health >/dev/null 2>&1; then
        echo "✓"
        break
    fi
    echo -n "."
    sleep 2
    if [ "$i" = "60" ]; then
        echo
        echo "  timed out — check logs with: docker compose -f docker/docker-compose.yml logs app" >&2
        exit 1
    fi
done

echo
echo "E2ER is running:"
echo "  Dashboard:  http://localhost:8280/"
echo "  API health: http://localhost:8280/health"
echo "  Logs:       docker compose -f docker/docker-compose.yml logs -f app"
echo

# 5. Open the browser (best-effort).
if command -v open >/dev/null 2>&1; then
    open http://localhost:8280/ || true
elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open http://localhost:8280/ || true
fi
