# Next steps for E2ER v3

End-of-session document — May 8, 2026. Captures (1) what's open, (2) the
concrete design for the highest-priority piece (Allium guardrails under
the CLI backend), and (3) lessons from this session.

---

## Where we are now

| Capability | Status |
|------------|--------|
| Mocked unit / regression / stress tests | ✓ 195 passing |
| CI on Python 3.11 + 3.12 (ruff, mypy, pytest) | ✓ green, branch-protected |
| Three LLM backends: Anthropic, OpenRouter, **Claude Code CLI** | ✓ all wired through `LLMBackend` |
| First-run cost guardrail ($1 cap on unproven tuples) | ✓ shipped |
| Pipeline resilience (atomic state save, no-redo on resume) | ✓ shipped |
| Theory specialist + per-paper methodology selector | ✓ shipped |
| Security: 0 secrets in git, prompt sanitizer, API auth, scrubbed CORS | ✓ shipped |
| Allium guardrails under SDK backends (anthropic/openrouter) | ✓ working |
| **Allium guardrails under CLI backend** | ✗ **needs wrapper script (this doc)** |
| First end-to-end live run with Sonnet | ✗ failed twice (now diagnosed) |

The pipeline currently has one open architectural gap: Allium data access
under the new CLI backend. Everything else is shipped.

---

## #1 priority: Allium guardrails for the CLI backend

### Why this matters

The CLI backend (`LLM_BACKEND=claude_code`) gives users a $0-per-token
path under their Max plan — the actual answer to the May 8 token-burn.
But it currently has no `query_allium` tool: the CLI runs its own internal
tool loop, so the in-process `AlliumToolHandler` (which validates the 5
guardrails) can't intercept anything.

Until this is fixed, CLI users have to run with `DATA_MODULE_ENABLED=false`
(literature-only / BYOD papers). That's a meaningful gap.

### The design (your idea, written out)

> "Agent creates SQL; submits this SQL to another agent which has rights
> to only take that and put to Allium, and report results back."

That's exactly the bash-wrapper pattern. Concrete shape:

```
specialist (Claude Code CLI)
        │
        │ Bash(e2er-allium-query <subcommand> ...)
        ▼
scripts/e2er-allium-query  (bash one-liner → python -m src.modules.data.cli)
        │
        │ runs the SAME 5 guardrails (validate_all)
        │  • no SELECT *
        │  • fields must be in data_dictionary.json
        │  • time-bound WHERE required
        │  • granularity justification (transaction-level)
        │  • feasibility-first (production query needs prior approved feasibility)
        ▼
src.modules.data.allium.AlliumProvider  (existing client)
        │
        ▼
   Allium API
        │
        ▼
   results JSON → stdout → CLI subprocess sees them
```

The specialist *only* gets the bash wrapper allowlisted; raw Allium API
access is denied. The wrapper is the gatekeeper.

### Subcommands the wrapper exposes

```bash
# 1) Feasibility query (auto-approved sample, 1000-row LIMIT enforced)
e2er-allium-query feasibility \
  --paper-id <uuid> \
  --sql "SELECT block_number, ts FROM ethereum.blocks WHERE ts >= '2024-01-01'" \
  --fields block_number,ts \
  --aggregation daily \
  --rationale "verify data availability for the analysis window"

# 2) Production query (requires prior feasibility, then human approval)
e2er-allium-query production \
  --paper-id <uuid> \
  --sql "..." --fields ... --aggregation transaction \
  --rationale "..."

# 3) Poll for human approval status of a production query
e2er-allium-query check-approval --query-id <uuid>

# 4) List available tables (no guardrail — read-only schema info)
e2er-allium-query list-tables

# All return JSON to stdout. Errors go to stderr + non-zero exit code.
```

These mirror the four methods on `AlliumToolHandler` 1:1.

### Implementation steps (estimated half-day)

1. **`src/modules/data/cli.py`** (new, ~150 lines) — `python -m src.modules.data.cli` entry point.
   - Uses `argparse` with subcommands matching the four methods above.
   - Imports the existing `AlliumToolHandler` and calls its methods directly.
   - Serialises results as JSON to stdout; errors as JSON to stderr.
   - **Reuses** `validate_all`, `log_query`, `mark_approved`, `create_approval_request`, `get_approval_status_with_note`, `AlliumProvider` — no new logic, just a different entry point.

2. **`scripts/e2er-allium-query`** (new, ~10 lines) — bash wrapper.
   - Resolves the project's Python and runs `python -m src.modules.data.cli "$@"`.
   - One-liner; handles `--help` by passing through.
   - Marked executable (`chmod +x`).

3. **`src/modules/llm/claude_code.py`** — extend `_DEFAULT_ALLOWED_TOOLS` to optionally include `Bash(e2er-allium-query:*)` when `DATA_MODULE_ENABLED=true`. The CLI invocation also needs to ensure the script is on `PATH` (or pass an absolute path).

4. **Specialist prompt update** — `data_analyst` and `data_architect` need a sentence in their skill or system prompt: "To query Allium, invoke the bash command `e2er-allium-query <subcommand>`. You do not have any other Allium access." This ensures the model knows the tool exists and the path. Existing skill files in `skills/files/data/` are the right home.

5. **Tests** (`tests/test_allium_cli.py`):
   - Each subcommand with a passing query → JSON output with results.
   - Each subcommand with a failing guardrail → non-zero exit + rejection JSON.
   - Production query without prior feasibility → rejected (the 5th guardrail).
   - All offline; mock `AlliumProvider.execute_raw` and the DB calls.

6. **README** — update the LLM-providers table to drop the "DATA_MODULE_ENABLED=false" caveat for the CLI backend once this lands.

### Why this works (and is faithful to v3's safety model)

- **Same guardrails, same code path**: the wrapper imports `validate_all`
  from `src/modules/data/guardrails.py`. The 5 rules are not duplicated.
- **Same audit trail**: queries logged to the same `data_query_records`
  table via `log_query`. The replication package's `audit_log.csv` still
  captures everything.
- **Same approval flow**: production queries still go through
  `data_approval_requests` and the dashboard's pending-queries endpoint.
  The only change is *who* invokes the validator: the in-process
  `AlliumToolHandler` (SDK backends) vs the bash wrapper (CLI backend).
- **No raw Allium access for the specialist**: `--allowedTools=Bash(e2er-allium-query:*)`
  permits *only* this command; other bash invocations and direct HTTP are
  blocked by Claude Code's tool restriction layer.

### Risk to flag

The bash subprocess vs. Python in-process split means the wrapper has to
re-establish the DB connection on every call. For a paper with 20+
queries, that's 20+ connection setups. Use `psycopg.AsyncConnectionPool`
in `src/modules/data/cli.py` with persistent state? No — each `python -m`
invocation is a fresh process. The simpler path: a single `psycopg.connect`
per invocation. ~50ms overhead per query. Tolerable.

If it's a problem later, the answer is an MCP server (a long-running
process that the CLI talks to via stdio), but **start with the bash
wrapper** — simpler, fewer moving parts, ~half a day to ship.

---

## #2 priority: validate that *anything* end-to-end works

The May 8 run failed twice (different bugs each time). Even after fixing
`max_tokens_per_call`, we never confirmed an end-to-end paper completes.
The fastest way to validate, *now that the CLI backend exists*:

```bash
# In .env:
LLM_BACKEND=claude_code
DATA_MODULE_ENABLED=false   # until the Allium wrapper above ships

# Then submit:
curl -X POST http://localhost:8280/api/papers \
  -H "Content-Type: application/json" \
  -d '{
    "title": "...",
    "research_question": "...",
    "mode": "single_pass",
    "methodology": "theoretical",
    "max_cost_usd": 0.50
  }'
```

Cost: $0 under your Max plan. If this completes end-to-end, the pipeline
is genuinely working — and we have a "proven tuple" so the first-run
guardrail unlocks higher caps for subsequent runs.

If it fails, the failure mode is now diagnostic rather than expensive:
the CLI's `last_error` will tell us what broke without spending tokens.

---

## #3-#N: lower-priority opens

- **`mixed` and `empirical` starter templates** — we have
  `examples/starter_theoretical/`; the other two methodologies should have
  parallel templates so users can copy/run.
- **Cassette-based tests** — record one successful CLI run's output, replay
  it as a test fixture. This catches regressions of *known-working*
  behaviour at $0. Lower priority than Allium-CLI; the CLI backend already
  makes live tests cheap.
- **PyPI release** — deferred at user's request. Repo remains
  pip-installable from git.
- **`mypy --strict` ratchet** — current config catches real bugs but not
  annotation completeness. Could tighten file-by-file via per-module
  overrides.
- **Per-specialist `_MAX_TURNS`** — currently one global value.
  `data_architect` and `econometrics_specialist` plausibly need more turns
  than `abstract_writer`. Low priority once cost is $0.
- **GitHub Actions Node 20 → 24** — non-blocking deprecation warning.
  Auto-migrates June 2026.

---

## Lessons from this session

Honest record so the next session doesn't repeat the same loop.

### 1. Mocked tests don't predict live-run failures

The May 8 NFT-marketplace run lost $8 to a bug (`max_tokens_per_call=16384`)
that existed in the codebase from day one. The unit-test suite never
caught it because `MockLLMBackend` returns short canned outputs — the
failure mode (a specialist writing a 30 KB JSON tool argument) literally
cannot occur with mocked LLMs.

**Implication**: tests are necessary but not sufficient. Live validation
is the only way to find the unknowns. The proper response is to make live
validation *cheap* (the CLI backend), not to add more mocked tests.

### 2. Read the error messages

The first run's log clearly said `"max_tokens=16384 too low — model output
truncated. Increase max_tokens_per_call in settings."` The second run was
launched without addressing that line. Three rounds of "fix and retry"
followed — chasing `max_turns`, cascade detection, UUID validation — all
real but none the actual root cause. **The error message named the fix.**

### 3. Compare to the working version

v1 and v2 ran papers at $0/token via Claude Code CLI. v3 made an
architectural change (own the tool loop) without inheriting the
production-tested settings — `max_tokens_per_call` was a brand-new value
chosen for chat completions, not for tool-arg-as-file-write workloads.

**Implication**: when v3 adds a layer that v1/v2 didn't have, that layer
needs its own first-principles pressure test. Don't assume defaults
imported from a different paradigm transfer cleanly.

### 4. Tests don't change the cost equation; the architecture does

We could write a thousand stress tests and the next live run on a new
combination would still spend tokens. The actual fix is structural:
- **First-run guardrail**: caps damage at $1 (shipped)
- **CLI backend**: zero-cost path under Max plan (shipped)
- **Cassette replay**: $0 regression coverage of known-working behaviour
  (deferred)

These are real defenses. Tests are documentation of what we know.

---

## Quick start for the next session

```bash
# 1. Pick up from main
git pull origin main

# 2. Verify nothing has broken
make lint && make typecheck && make smoke      # all should pass

# 3. Start with Allium-via-CLI (priority #1)
#    - Read this file's "implementation steps"
#    - Build src/modules/data/cli.py
#    - Build scripts/e2er-allium-query
#    - Tests in tests/test_allium_cli.py
#    - Update prompts in skills/files/data/

# 4. Validate the CLI backend end-to-end
#    - Set LLM_BACKEND=claude_code, DATA_MODULE_ENABLED=false in .env
#    - Submit one theoretical paper at $0.50 cap
#    - If it completes: declare CLI backend production-ready
#    - If it fails: read the log, fix, retry (cost: $0)

# 5. Then validate Allium-via-CLI
#    - Set DATA_MODULE_ENABLED=true
#    - Submit one empirical paper at $0.50 cap
#    - Verify Allium queries route through e2er-allium-query
#    - Verify guardrails trigger on bad queries
```
