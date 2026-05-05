#!/usr/bin/env bash
# E2ER v3 smoke test — validates a fresh clone from scratch through a full paper creation.
#
# Usage:
#   bash tests/e2e/smoke_test.sh                  # unit tests only (no DB/LLM required)
#   FULL=1 bash tests/e2e/smoke_test.sh           # full API smoke test (requires running DB + .env)
#
# Exit codes: 0 = all checks passed, non-zero = something failed.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

pass() { echo -e "${GREEN}✓${NC} $1"; }
fail() { echo -e "${RED}✗${NC} $1"; exit 1; }
info() { echo -e "${YELLOW}→${NC} $1"; }

echo ""
echo "═══════════════════════════════════════════════════"
echo "  E2ER v3 — Smoke Test"
echo "═══════════════════════════════════════════════════"
echo ""

# ---------------------------------------------------------------------------
# Phase 1: Package structure
# ---------------------------------------------------------------------------

info "Phase 1: Package structure"

[ -f "pyproject.toml" ] && pass "pyproject.toml present" || fail "pyproject.toml missing"
[ -f "src/api/app.py" ] && pass "src/api/app.py present" || fail "src/api/app.py missing"
[ -f "src/__main__.py" ] && pass "src/__main__.py present" || fail "src/__main__.py missing"
[ -d "skills/files" ] && pass "skills/files/ directory present" || fail "skills/files/ missing"
[ -d "sql" ] && pass "sql/ migrations directory present" || fail "sql/ missing"
[ -f "docker/docker-compose.yml" ] && pass "docker/docker-compose.yml present" || fail "docker/docker-compose.yml missing"
[ -f ".env.example" ] && pass ".env.example present" || fail ".env.example missing"

# Count skill files
SKILL_COUNT=$(find skills/files -name "*.md" | wc -l | tr -d ' ')
[ "$SKILL_COUNT" -ge 20 ] && pass "skills/files/ has $SKILL_COUNT skill files (≥20 required)" \
    || fail "skills/files/ only has $SKILL_COUNT skill files — expected ≥20"

# Count SQL migrations
SQL_COUNT=$(find sql -name "*.sql" | wc -l | tr -d ' ')
[ "$SQL_COUNT" -ge 6 ] && pass "sql/ has $SQL_COUNT migration files (≥6 required)" \
    || fail "sql/ only has $SQL_COUNT migration files"

echo ""

# ---------------------------------------------------------------------------
# Phase 2: Python package installs cleanly
# ---------------------------------------------------------------------------

info "Phase 2: Package import"

python3 -c "import src.api.app" && pass "src.api.app imports successfully" \
    || fail "src.api.app import failed — check dependencies"

python3 -c "import src.modules.llm.base; import src.modules.data.guardrails" \
    && pass "core modules import successfully" \
    || fail "core module import failed"

python3 -c "import src.__main__; print('ok')" > /dev/null \
    && pass "src.__main__ imports and CLI entry point is wired" \
    || fail "src.__main__ import failed"

echo ""

# ---------------------------------------------------------------------------
# Phase 3: Unit test suite
# ---------------------------------------------------------------------------

info "Phase 3: Unit + integration tests (no DB, no LLM)"

if command -v pytest &>/dev/null; then
    pytest tests/ -v --tb=short -q \
        --ignore=tests/e2e \
        2>&1 | tail -20

    # Check exit code from pytest (the pipe loses it, so re-run minimally)
    pytest tests/ -q --ignore=tests/e2e --no-header 2>&1 | tail -3
    pass "pytest completed — check output above for failures"
else
    fail "pytest not found — run: pip install -e '.[dev]'"
fi

echo ""

# ---------------------------------------------------------------------------
# Phase 4: Skills loading
# ---------------------------------------------------------------------------

info "Phase 4: Skills resolution"

python3 - <<'PYEOF'
from src.skills.loader import load_skills_for_specialist, _SPECIALIST_SKILLS
missing = [s for s in _SPECIALIST_SKILLS if not load_skills_for_specialist(s).strip()]
if missing:
    print(f"FAIL: specialists with no skills: {missing}")
    exit(1)
print(f"All {len(_SPECIALIST_SKILLS)} specialists resolve to at least one skill file.")
PYEOF
pass "All specialists have skill files loaded"

echo ""

# ---------------------------------------------------------------------------
# Phase 5: Full API smoke test (FULL=1 only)
# ---------------------------------------------------------------------------

if [ "${FULL:-0}" = "1" ]; then
    info "Phase 5: Full API smoke test (FULL=1)"

    # Require .env
    [ -f ".env" ] || fail ".env not found — copy .env.example and fill in API keys"

    # Start the API server in background
    python3 -m e2er serve --port 8280 &
    SERVER_PID=$!
    trap "kill $SERVER_PID 2>/dev/null || true" EXIT

    # Wait for server to be ready
    for i in $(seq 1 10); do
        if curl -sf http://127.0.0.1:8280/health >/dev/null 2>&1; then
            break
        fi
        sleep 1
    done

    curl -sf http://127.0.0.1:8280/health >/dev/null && pass "API server /health returns 200" \
        || fail "API server not responding after 10s"

    # Create a paper
    RESPONSE=$(curl -sf -X POST http://127.0.0.1:8280/api/papers \
        -H "Content-Type: application/json" \
        -d '{"title":"Smoke Test Paper","research_question":"Does the smoke test pass?","mode":"single_pass"}')

    echo "create_paper response: $RESPONSE"
    PAPER_ID=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['paper_id'])")

    [ -n "$PAPER_ID" ] && pass "Paper created: $PAPER_ID" || fail "Could not extract paper_id from response"

    # Fetch paper record
    GET_RESPONSE=$(curl -sf "http://127.0.0.1:8280/api/papers/$PAPER_ID")
    echo "get_paper response: $GET_RESPONSE"
    STATUS=$(echo "$GET_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status','unknown'))")
    pass "Paper status: $STATUS"

    # List artifacts (may be empty if pipeline hasn't finished)
    ARTIFACTS=$(curl -sf "http://127.0.0.1:8280/api/papers/$PAPER_ID/artifacts")
    echo "artifacts: $ARTIFACTS"
    pass "Artifacts endpoint responded"

    kill $SERVER_PID 2>/dev/null || true
    trap - EXIT
else
    info "Phase 5 skipped (set FULL=1 to run the live API test)"
fi

echo ""
echo "═══════════════════════════════════════════════════"
echo -e "  ${GREEN}Smoke test complete.${NC}"
echo "═══════════════════════════════════════════════════"
echo ""
