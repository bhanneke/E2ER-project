#!/usr/bin/env bash
# Install a built wheel into a fresh virtualenv outside the checkout and check
# that a study can start from it: `e2er --help`, the four templates and the
# skill files resolve, and `e2er verify` passes on a copy of examples/showcase.
#
#   scripts/check_wheel.sh dist/e2er-*.whl
#
# Used by the `package` job in .github/workflows/tests.yml. Fails on a wheel
# without pipelines/ (0.11.0).
set -euo pipefail

WHEEL="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PYTHON:-python3}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

"$PY" -m venv "$WORK/venv"
"$WORK/venv/bin/pip" install --quiet --upgrade pip
"$WORK/venv/bin/pip" install --quiet "$WHEEL"

# Outside the checkout, with an empty HOME: no ./pipelines, no ~/.e2er.
mkdir -p "$WORK/home" "$WORK/run"
cp "$REPO/scripts/check_installed_package.py" "$WORK/run/"
cp -R "$REPO/examples/showcase" "$WORK/run/showcase"
cd "$WORK/run"
export HOME="$WORK/home"
unset PYTHONPATH || true

echo "== e2er --help"
"$WORK/venv/bin/e2er" --help >/dev/null
echo "ok  e2er --help"

echo "== templates and skills"
"$WORK/venv/bin/python" check_installed_package.py "$REPO"

echo "== e2er verify showcase"
"$WORK/venv/bin/e2er" verify showcase
