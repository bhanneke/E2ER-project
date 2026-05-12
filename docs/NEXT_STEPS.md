# Next steps for E2ER v3

End-of-session document — May 12, 2026. Captures (1) where we are after
extensive live validation, (2) the one remaining blocker (Allium endpoint
URL), and (3) lessons from the multi-run session.

---

## Where we are now

| Capability | Status |
|------------|--------|
| Mocked unit / regression / stress tests | ✓ **221 passing** |
| CI on Python 3.11 + 3.12 (ruff, mypy, pytest) | ✓ green, branch-protected |
| Three LLM backends: Anthropic, OpenRouter, **Claude Code CLI** | ✓ all wired through `LLMBackend` |
| First-run cost guardrail ($1 cap on unproven tuples) | ✓ shipped + `acknowledge` truly overrides cap |
| Pipeline resilience (atomic state save, no-redo on resume) | ✓ shipped |
| Theory specialist + per-paper methodology selector | ✓ shipped |
| Security: 0 secrets in git, prompt sanitizer, API auth, scrubbed CORS, locked-down Bash | ✓ shipped |
| **CLI backend end-to-end on theoretical methodology** | ✓ **VALIDATED $0 real cost (run #6 / #7 / #8)** |
| **CLI backend end-to-end on empirical methodology** | ✓ pipeline ran; data layer blocked on URL config (see below) |
| **Allium gatekeeper bash wrapper** | ✓ **VALIDATED end-to-end (run #11)** — 3 queries through, all 5 guardrails fired, all logged to `data_query_records` + `audit_log.csv` |
| **Disk-first review aggregation (6 of 6 reviewers parsed)** | ✓ **VALIDATED** (run #11 aggregation has 6/6 in `Breakdown:`) |
| **Allium discovery primitives** (list/describe/distinct-values) | ✓ shipped; needs working URL to validate end-to-end |
| **Allium SQL endpoint URL** (which surface for this tier) | ✗ **UNRESOLVED** — see #1 below |
| Real empirical paper with actual Allium data | ✗ blocked by the URL question |

The pipeline orchestrates correctly end-to-end. Theoretical papers
complete at $0 with all artifacts. Empirical papers complete at $0 with
all artifacts EXCEPT real data rows — the data integrity guardrail
correctly refuses to fabricate numbers when the Allium endpoint returns
0 rows, and the technical_reviewer correctly flags the resulting thin
empirics with a HARD_REJECT verdict.

---

## #1 priority: confirm the right Allium SQL endpoint URL

### The state

`ALLIUM_API_BASE` is set in `.env` to `https://api.allium.so/api/v1` and
`AlliumProvider.execute_raw` POSTs to `{base}/explorer/query/run`.

Run #11 evidence:
- That URL returns **HTTP 404 Not Found** for any SQL.
- v1/v2 used `https://mcp.allium.so/api/v1/queries`. Probing that today
  also 404s.
- `mcp.allium.so/` root replies with a JSON-RPC error requiring
  `text/event-stream` (MCP-over-SSE protocol, not REST).

Allium has multiple API surfaces (Data Service, Explorer, MCP) and
different tiers expose different endpoints. Three sources of ground truth
the next session should consult:

1. **The Allium dashboard's API docs page** (logged in with your
   account). It will show the *exact* curl command for your tier.
2. **Allium support / chat** — fastest path to "which URL for SQL
   under <plan_name>".
3. **The `Allium-MCP` GitHub repo** if Allium has one — would document
   the SSE-MCP path.

Once you have the right base URL:

```bash
# In .env:
ALLIUM_API_BASE=https://<the-actual-host>/<the-actual-path>
```

Restart the app. Then verify with the discovery primitives:

```bash
# Should return >0 tables now
e2er-allium-query list-tables

# Should return real columns + types
e2er-allium-query describe-table --schema ethereum --table nft_trades

# Should return actual marketplace literals + counts
e2er-allium-query distinct-values --schema ethereum --table nft_trades --column marketplace
```

If `distinct-values` shows `'OpenSea'` (or whatever Allium actually
stores), submit the empirical paper again and the pipeline should
produce a complete empirical run with real data.

### Why this is "user task" not "code task"

The discovery code is portable — it issues standard SQL against whatever
URL is configured. No code change makes the wrong URL into the right
URL. The Allium subscription determines which surface is accessible,
and that's not derivable from inside the repo.

---

## #2 priority: features from `docs/PORTING_PLAN.md`

Five items inspired by Imbad0202/academic-research-skills, all still
unstarted. In execution order:

1. **Compliance front-matter** (~2 hrs) — CRediT, AI-disclosure, ethics
   declaration in the generated LaTeX. Pulls from existing
   `contributions` + `data_query_records` tables.
2. **Devil's-Advocate concession threshold** (~3 hrs) — score the
   revisor's response to each self-attack finding; block status
   advance below threshold. Pattern from Imbad0202's stage 4.5.
3. **Reference integrity gate** (~1 day) — independent OpenAlex/S2
   verification of every citation in `references.bib`; hard-blocks
   finalization on failure. Their public 31%-reference-error
   post-mortem is the precedent.
4. **Mid-pipeline entry modes** (~1 day) — `revision-coach`,
   `citation-check`, `outline-only`, `disclosure-only`. 5× addressable
   use case for ~1 day's work.
5. **Showcase artifacts** under `examples/showcase/` (~0.5 day + 1
   run) — fully generated papers with reviews, integrity reports,
   replication packages. Now possible at $0 on Max plan.

All five are developable at $0 under the CLI backend. The original
porting plan with full design sketches is at `docs/PORTING_PLAN.md`.

---

## #3 — lower-priority opens

- **The actual Allium endpoint** (#1 above) — depends on subscription
  details.
- **Empirical-with-Allium starter template** in `examples/` — has been
  blocked by the URL issue but is otherwise just a template + README.
- **`mixed` methodology starter** — we have `examples/starter_theoretical/`;
  parallel templates for `empirical` + `mixed` would round out coverage.
- **Cassette-based tests** — record one successful CLI run's output,
  replay as a regression fixture. Catches regressions of *known-working*
  behaviour at $0. Lower priority now that the CLI backend itself is
  $0 to test against.
- **PyPI release** — deferred at user request. Repo remains
  pip-installable from git.
- **`mypy --strict` ratchet** — current config catches real bugs but
  not annotation completeness.
- **GitHub Actions Node 20 → 24** — non-blocking deprecation warning.
  Auto-migrates June 2026.

---

## Lessons from the May 12 session

Eight live runs, six concrete bugs, all caught and fixed at $0 actual
cost (Max plan + CLI backend). Each is a separate-cause class:

### 1. CLI tool names differ from SDK tool names

The system prompt referenced `write_file` / `read_file`; Claude Code CLI
exposes `Write` / `Read` / `Edit` / `Glob`. The model in CLI mode read
"use `write_file`" → found no such tool → produced text without writing
a file. **Fix:** `_translate_tool_names_for_cli` rewrites prompts when
the backend is `claude_code`. Belt-and-braces: instruction at *both* the
skill level AND the work-order level.

### 2. CLI subprocess CWD must be the paper's workspace

The CLI's `Write` tool resolves relative paths against cwd. Default cwd
was the project root, so `Write("paper_plan.md")` landed in the repo
root instead of the paper's workspace. **Fix:**
`ClaudeCodeBackend._invoke_cli` now passes `cwd={workspace_root}/{paper_id}`
per invocation. `_find_output_file` has a recursive recovery path that
moves nested artifacts (`workspace/<specialist>/<file>`) to canonical
location with a warning.

### 3. CLI summary JSON has no `messages` array

Claude Code 2.x `--output-format json` returns top-level metadata
(`num_turns`, `usage`, `result`) but **no per-message content list**.
Our parser counted tool_use blocks in a nonexistent field, so
`tools_called=0` always. **Fix:** approximate via `num_turns - 1`. The
metric is informational; the cascade detection uses file-existence, not
tool count.

### 4. The skills loader has its own `_SPECIALIST_SKILLS` dict

Two dicts named the same thing exist: one in
`src/skills/loader.py` (what actually loads), one in
`src/core/specialists/registry.py` (what I'd been editing for weeks).
The loader dict didn't include the `allium-cli` skill I'd added to
registry. **Fix:** added `allium-cli` to the loader's data_analyst +
data_architect entries. **TODO** (low priority): unify the two dicts.

### 5. Bare `Bash` in the allowlist defeated the gatekeeper

`_DEFAULT_ALLOWED_TOOLS` had both `Bash` (unrestricted) and
`Bash(e2er-allium-query:*)` (pattern). The bare `Bash` made the
pattern restriction meaningless — model could run any shell command.
**Fix:** dropped bare `Bash`; only the gatekeeper pattern remains.
Regression test pins the no-bare-Bash invariant.

### 6. The bash wrapper needed Python interpreter discovery

`scripts/e2er-allium-query` used `exec python -m src.modules.data.cli`,
but `python` wasn't on the Claude Code subprocess's PATH. Falling back
to `python3` resolved to the system 3.9 which crashed on PEP 604 union
types at import. **Fix:** the runner injects `E2ER_PYTHON=sys.executable`
into the subprocess env; the wrapper prefers that, then probes
`python3.12 → python3.11 → python3 → python` in order.

### 7. Review aggregator parsed chat summary, not file on disk

Under the CLI backend, `c.output` is the CLI's final assistant message
("I've written the review") — *not* the file content. Some reviewers
echoed the score; some didn't. Aggregation was non-deterministic across
runs. **Fix:** `_run_revision_phase` now reads each reviewer's file from
disk and parses that. Chat summary is a fallback only when the file is
missing entirely. Regression test sets up a disk-vs-chat disagreement
and asserts disk wins.

### 8. First-run cap acknowledgement only bypassed the rejection

`acknowledge_unproven_tuple=true` let the request through (no 400) but
the cap was still clamped to `$1` via
`min(requested_cap, _UNPROVEN_TUPLE_CAP)`. Caused `BudgetExceededError`
mid-pipeline when the user explicitly requested `$25`. **Fix:** ack now
actually raises the cap to the requested value. Regression test pins
that the persisted cap matches the request.

---

## Quick start for the next session

```bash
# 0. Pick up from main
git pull origin main
make lint && make typecheck && make smoke   # all should pass (221 tests)

# 1. Figure out the right Allium URL (#1 above).
#    Check your Allium dashboard or contact support.
#    Then update .env: ALLIUM_API_BASE=<correct-url>

# 2. Restart the app + verify discovery works
lsof -i :8280 | grep LISTEN | awk '{print $2}' | xargs -r kill -9
/tmp/e2er_venv2/bin/python -m uvicorn src.api.app:app --host 127.0.0.1 --port 8280 &
e2er-allium-query list-tables                          # should return >0 tables
e2er-allium-query describe-table --schema ethereum --table nft_trades

# 3. Submit an empirical paper end-to-end
curl -X POST http://localhost:8280/api/papers -d '{
  "title": "...",
  "research_question": "...",
  "mode": "single_pass",
  "methodology": "empirical",
  "max_cost_usd": 25.0,
  "acknowledge_unproven_tuple": true
}'

# 4. If the run succeeds with REAL data rows, ship it as a showcase
#    paper in examples/showcase/ (item #2.5 of the porting plan).

# 5. Then pick from the porting plan in execution order:
#    compliance → concession-threshold → integrity-gate → entry-modes
#    All five developable at $0 under the CLI backend.
```

## Today's commit chain

```
9c40b88  Allium discovery: describe-table, distinct-values, INFORMATION_SCHEMA list-tables
7093a38  Allium gatekeeper actually works under CLI backend end-to-end
a74e959  Review aggregation: read scores from disk, not from CLI chat summary
51d30a1  Reviewer prompts: enforce parser closing-format at dispatch, not just skill
a1fa5b1  Review aggregator parser: handle the 4 reviewer-output formats Sonnet emits
```

Test count: 192 → **221** across the session. CI green throughout.

---

## Architecture invariants to preserve

A few things that should NOT be casually changed because their absence
would re-introduce bugs we shipped fixes for today:

1. **Bare `Bash` must not be in `_DEFAULT_ALLOWED_TOOLS`** — pinned by
   `test_allowed_tools_do_not_include_bare_bash`. Adding it back opens
   the arbitrary-command surface.
2. **Reviewer work-order prompts must contain the `OVERALL SCORE:`
   closing-format mandate** — pinned by
   `test_reviewer_user_prompt_contains_mandatory_closing_format`.
3. **`_run_revision_phase` must read review files from disk first** —
   pinned by `test_runner_aggregation_prefers_disk_over_chat_summary`.
   Reverting to chat-summary-first re-introduces the partial-aggregation
   bug.
4. **`max_tokens_per_call` must be >=32K** — pinned by
   `test_max_tokens_per_call_default_is_at_least_32k`. The original
   $25-burning bug.
5. **The two skills dicts** (loader.py, registry.py) **must stay in
   sync** until they're unified. No regression test for this yet;
   manual diligence required. TODO: write a test that asserts
   `loader._SPECIALIST_SKILLS.keys() == registry.SPECIALIST_SKILLS.keys()`
   and bail if a skill name appears in one but not the other.
