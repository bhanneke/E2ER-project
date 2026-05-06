#!/usr/bin/env bash
# Fetch htmx into src/api/static/ for offline-friendly serving.
# Run once at install time (or in your Docker build) so the dashboard
# doesn't need a CDN at runtime.
set -euo pipefail

VERSION="1.9.12"
DEST="$(dirname "$0")/../src/api/static/htmx.min.js"
URL="https://unpkg.com/htmx.org@${VERSION}/dist/htmx.min.js"

mkdir -p "$(dirname "$DEST")"
echo "Fetching htmx ${VERSION} -> ${DEST}"
curl -fsSL "$URL" -o "$DEST"
echo "Done. Size: $(wc -c < "$DEST") bytes"
