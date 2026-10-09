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

# The commands specialists run by name must exist in an installed e2er and be on
# the PATH the backends give a specialist (before 0.15.0 only e2er-data and
# e2er-fieldmap were installed; e2er-run, e2er-lit, e2er-check-tables and
# e2er-allium-query existed only in a source checkout).
echo "== the specialists' commands"
"$WORK/venv/bin/python" - <<'PY'
import shutil, sys
from src.modules.llm.cli_support import subprocess_path
path = subprocess_path("/usr/bin:/bin")
missing = [c for c in ("e2er-data", "e2er-fieldmap", "e2er-run", "e2er-lit", "e2er-check-tables", "e2er-allium-query")
           if not shutil.which(c, path=path)]
if missing:
    sys.exit(f"not on a specialist's PATH ({path}): {', '.join(missing)}")
print("ok  all six on a specialist's PATH")
PY
mkdir -p "$WORK/ws"
printf 'print("ran")\n' > "$WORK/ws/tiny.py"
( cd "$WORK/ws" && "$WORK/venv/bin/e2er-run" tiny.py | grep -q ran )
grep -q '"script": "tiny.py"' "$WORK/ws/.e2er-script-runs.jsonl"
echo "ok  e2er-run runs a script and records it"
( cd "$WORK/ws" && "$WORK/venv/bin/e2er-run" ../tiny.py 2>/dev/null ) && { echo "e2er-run ran a path outside the workspace"; exit 1; } || true
"$WORK/venv/bin/e2er-lit" --help >/dev/null
echo "ok  e2er-lit --help"
"$WORK/venv/bin/e2er-allium-query" --help >/dev/null
echo "ok  e2er-allium-query --help"
# Exit 2: nothing to check; the answer says why.
CT="$(cd "$WORK/ws" && "$WORK/venv/bin/e2er-check-tables" 2>&1 || true)"
echo "$CT" | grep -q "no table_spec.json"
echo "ok  e2er-check-tables answers in a workspace without table_spec.json"
