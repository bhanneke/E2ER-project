#!/usr/bin/env bash
# Fetch htmx into src/api/static/ for offline-friendly serving.
# Run once at install time (or in your Docker build) so the dashboard
# doesn't need a CDN at runtime.
#
# The download is checked against the SHA-256 below before it replaces anything:
# a changed file on the CDN (or on the way) never becomes the dashboard's script.
# The same file's SHA-384 is the `integrity` attribute in src/api/templates/base.html;
# tests/test_htmx_integrity.py keeps the three in step. To move to another version,
# update VERSION, SHA256 and the integrity attribute together (htmx's docs publish the SRI hash).
set -euo pipefail

VERSION="1.9.12"
SHA256="449317ade7881e949510db614991e195c3a099c4c791c24dacec55f9f4a2a452"
DEST="$(dirname "$0")/../src/api/static/htmx.min.js"
URL="https://unpkg.com/htmx.org@${VERSION}/dist/htmx.min.js"

mkdir -p "$(dirname "$DEST")"
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
echo "Fetching htmx ${VERSION} -> ${DEST}"
curl -fsSL "$URL" -o "$TMP"
if command -v sha256sum >/dev/null 2>&1; then
    GOT="$(sha256sum "$TMP" | cut -d' ' -f1)"
else
    GOT="$(shasum -a 256 "$TMP" | cut -d' ' -f1)"
fi
if [ "$GOT" != "$SHA256" ]; then
    echo "error: htmx ${VERSION} from ${URL} has SHA-256 ${GOT}, expected ${SHA256}; not installed." >&2
    exit 1
fi
mv "$TMP" "$DEST"
trap - EXIT
echo "Done. Size: $(wc -c < "$DEST") bytes, SHA-256 verified"
