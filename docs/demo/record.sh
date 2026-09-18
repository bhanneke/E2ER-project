#!/usr/bin/env bash
# Record the demo GIFs.
#
#   docs/demo/record.sh            # every session that can be recorded honestly
#   docs/demo/record.sh byod       # just one
#
# Requires: brew install asciinema agg
#
# Every command in every session runs for real, and everything on screen after
# the prompt is the program's own output. Nothing is simulated and no take is
# stitched together from several runs. The only theatre is the typing delay in
# the session scripts, so a reader can follow the line being entered.
#
# The one staging: `e2er` resolves to the working-tree build rather than to a
# site-packages install. That runs the real code and prints its real output; it
# only saves reinstalling between takes.
#
# quickstart opens with `pip install e2er`, which cannot be recorded honestly
# until the published wheel is the thing the rest of the session demonstrates.
# The published 0.8.1 predates doctor/verify/rq/compare/run-matrix, so this
# script refuses to record it until PyPI has caught up.
#
# (vhs was the obvious tool here and does not work on this machine: it reports
# "Creating ….gif" and writes nothing, with Chrome, ttyd and ffmpeg 7 all
# present and working. asciinema + agg needs no browser.)
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO"

for tool in asciinema agg; do
  command -v "$tool" >/dev/null || { echo "$tool not found: brew install asciinema agg" >&2; exit 1; }
done

PY="$REPO/.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"

export E2ER_DEMO_DIR="${E2ER_DEMO_DIR:-/tmp/e2er-demo}"
export E2ER_DEMO_HOME="${E2ER_DEMO_HOME:-/tmp/e2er-demo-home}"

WINDOW="${E2ER_DEMO_WINDOW:-112x38}"
FONT_SIZE="${E2ER_DEMO_FONT:-18}"
THEME="${E2ER_DEMO_THEME:-dracula}"

echo "==> building the demo project"
"$PY" docs/demo/make_demo_project.py "$E2ER_DEMO_DIR"
rm -rf "$E2ER_DEMO_HOME"
mkdir -p "$E2ER_DEMO_HOME"

SHIM="$(mktemp -d)"
cat > "$SHIM/e2er" <<EOF
#!/bin/sh
exec "$PY" -m src "\$@"
EOF
chmod +x "$SHIM/e2er"
export PATH="$SHIM:$PATH"
export PYTHONPATH="$REPO"
trap 'rm -rf "$SHIM"' EXIT

published_is_current() {
  "$PY" - <<'PYEOF'
import json, sys, urllib.request
try:
    with urllib.request.urlopen("https://pypi.org/pypi/e2er/json", timeout=15) as r:
        v = json.load(r)["info"]["version"]
except Exception:
    sys.exit(1)
major, minor, *_ = (v.split(".") + ["0", "0"])[:3]
sys.exit(0 if (int(major), int(minor)) >= (0, 9) else 1)
PYEOF
}

for name in ${@:-byod quickstart}; do
  if [ "$name" = "quickstart" ] && ! published_is_current; then
    echo "==> SKIPPING quickstart: PyPI has no 0.9.0+ yet, so 'pip install e2er'"
    echo "    would not produce the CLI the rest of the session uses. Cut the"
    echo "    release first, then re-run this script."
    continue
  fi

  cast="$(mktemp -t "e2er-$name").cast"
  echo "==> recording $name"
  asciinema rec --overwrite --window-size "$WINDOW" \
    -c "bash docs/demo/${name}_session.sh" "$cast" >/dev/null

  echo "==> rendering docs/demo/$name.gif"
  agg --font-size "$FONT_SIZE" --theme "$THEME" \
    --idle-time-limit 2 --last-frame-duration 4 \
    "$cast" "docs/demo/$name.gif"
  rm -f "$cast"
done

echo "==> done"
ls -la docs/demo/*.gif 2>/dev/null || true
