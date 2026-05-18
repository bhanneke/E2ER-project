# Changelog

All notable changes to E2ER v3 are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

(Add new entries here under `### Lane A — Pipeline`, `### Lane B — Literature`,
`### Lane C — Data`, or `### Cross-lane` sub-headings per `AGENTS.md`.)

## v0.4.2 — 2026-05-18

Hot-fix over v0.4.1. The 0.4.1 wheel shipped only `.py` files + skill
markdown, but the runtime needs three other on-disk asset bundles: the
FastAPI static directory, the Jinja2 templates, and `sql/sqlite/schema.sql`
for the SQLite bootstrap. Without them, `e2er run` on a fresh
`pip install e2er` crashed at uvicorn startup with `RuntimeError:
Directory '.../src/api/static' does not exist`.

### Cross-lane

- **Ship runtime assets in the wheel**: `pyproject.toml` now declares
  `src.api` package-data (`static/*`, `templates/*`) and `sql` / `sql.sqlite`
  package-data (`*.sql`). Empty `sql/__init__.py` and `sql/sqlite/__init__.py`
  make `sql/` discoverable by `setuptools.packages.find`. Verified by
  fresh-venv install + `uvicorn src.api.app:app` boot, `GET /static/style.css`
  serving 5,182 bytes, and an end-to-end `e2er run` reaching terminal
  `failed` status (cost-cap test) with `~/.e2er/papers.db` and the
  workspace directory both created via the SQLite zero-config path.

## v0.4.1 — 2026-05-18

Lifecycle patch over v0.4.0. Three resume/shutdown bugs that surfaced
during the v0.4 SQLite live test.

### Lane A — Pipeline

- **Graceful shutdown** (closes #5): `@app.on_event("shutdown")` now
  cancels in-flight runner tasks and transitions papers to `paused`.
  Skips state.json-says-completed papers. Stops the "zombie row at
  designing/revision after every uvicorn restart" failure mode.
- **Resume writes terminal status** (closes #6): when resume runs on a
  paper whose state.json already has every stage complete, the runner
  now mirrors `state.last_status` back to the DB before returning.
  Previously the DB row stayed at `designing` (the entry value).
- **Resume accepts zombies** (closes #7): `/api/papers/{id}/resume` no
  longer requires status to be `paused`/`failed`. Any non-terminal
  status with no live runner task in `_RUNNING` is resumable. Combined
  with #5, this removes the manual-UPDATE workaround entirely.
- **SQLite translation extensions** (closes nothing — caught by live
  SQLite smoke after v0.4.0 shipped, fixed before tagging):
  `NOW()` → `CURRENT_TIMESTAMP`, plus `::int`/`::bigint`/`::numeric`/
  `::float` casts stripped alongside the existing type/json/interval
  casts. Without these, status UPDATEs silently failed and usage
  aggregations crashed SQLite with "unrecognized token: ':'".

### Tests

- `tests/pipeline/integration/test_graceful_shutdown.py` — 3 new.
- `tests/pipeline/integration/test_resume_terminal_status.py` — 1 new.
- `tests/pipeline/integration/test_resume_api.py` — 4 new + 1 rewritten.

Test count: 326 → 333.

## v0.4.0 — 2026-05-18

The **"actually usable by a stranger"** release. `pip install e2er`
followed by a one-command `e2er run "<RQ>"` now starts a local server,
submits the paper, and tails the run to terminal — zero database setup,
zero `.env` editing required to get to a first paper.

### Cross-lane — User journey

- **Zero-setup default**: `e2er serve` no longer requires Postgres. The
  DB client dispatches to SQLite at `~/.e2er/papers.db` by default; set
  `DATABASE_URL=postgresql://…` to opt into the production stack
  (pgvector + concurrent writes + literature KB).
- **`e2er run "<RQ>"`** subcommand: starts uvicorn in the background if
  needed, POSTs `/api/papers`, tails status to terminal, prints the
  paper's workspace + dashboard URL on completion. ^C is safe — the
  run keeps going.
- **README rewrite**: leads with the 5-minute quickstart + the BYO-CLI
  cost matrix. Architecture / artifact list moved below.
- **GitHub repo description + topics** filled in for discoverability.

### Lane C — Data

- **Raw-data persistence**: every data-pulling subcommand
  (`yfinance history`, `yfinance fundamentals`, `yfinance dividends`,
  `fred series`) gains a `--save-to <rel/path>.csv` flag. The wrapper
  writes the response rows to `workspace/data/<rel/path>` so the
  replication package is runnable offline. Skill files updated to
  mandate `--save-to` on every meaningful extraction. Closes #11.

### Internals

- **DB-client dispatch**: `src/db/client.py` now routes SQLite vs Postgres
  by URL scheme. Postgres ``%(name)s`` parameter style translates to
  SQLite ``:name`` on the fly; Postgres ``::type`` casts are stripped.
  Existing call sites need zero changes.
- **`sql/sqlite/schema.sql`** ships a SQLite-compatible schema with the
  core tables (papers, events, contributions, llm_usage, data_query_records,
  data_approval_requests). pgvector-dependent tables (literature_files,
  knowledge_chunks) are NOT created — KB feature degrades to "disabled"
  on SQLite, as designed.
- **`aiosqlite>=0.20.0`** added to dependencies.

### Tests

- New: `tests/data/contract/test_db_dispatch.py` — 9 tests pinning the
  parameter translation, cast stripping, and path resolution.

## v0.3.0 — 2026-05-16

The **stability sprint**. Five-phase overhaul focused on making v3
*actually* stable for users beyond the maintainer. Adopted patterns
from `Davidvandijcke/coarse` (branching model, slash commands, headless
CLI backends, OIDC PyPI publishing). Test count: 221 → 290.

### Cross-lane — Foundation & process

- **dev/main branch model**: `dev` is now the default integration branch;
  `main` is released-only and branch-protected (PR required, no force
  push, no deletion). All feature work goes through PRs into `dev`.
- **`AGENTS.md`** (new) codifies the three-lane split (Pipeline / Lit /
  Data), the public contracts each lane owns, hard rules (no live runs
  from `dev` without smoke-pass, cross-lane changes need explicit flag),
  and the tag-driven release procedure.
- **`.claude/hooks/session-brief.sh`** runs at SessionStart to dump
  branch, recent commits, CI status, and in-flight paper runs into
  every new Claude Code session.
- **`scripts/release_audit.py` + `make release-audit`**: hard-gates
  (version match between `pyproject.toml` and `src/__init__.py`, clean
  tree, CHANGELOG has entries, no `TODO(release)`, pytest passes) + soft
  gates (on-main, CI green). Required before tagging.
- **`.github/workflows/release.yml`** (new) tag-driven (`push:tags:v*`).
  Enforces tag↔pyproject↔__init__.py version triple-match, runs tests,
  builds wheel, creates GH release. Publishes to PyPI via OIDC trusted
  publishing — no API token secret.
- **Path-filtered per-lane CI** (`ci-pipeline.yml`, `ci-lit.yml`,
  `ci-data.yml`): each lane runs only its own tests; full `tests.yml`
  runs on every dev/main merge.
- **CHANGELOG per-lane organisation**: entries under `## Unreleased` use
  `### Lane A`, `### Lane B`, `### Lane C`, `### Cross-lane` sub-headings.

### Lane A — Pipeline (Phase 2-5)

- **Specialist circuit breaker** (`src/core/strategist/runner.py` +
  `state.py`): tracks consecutive failures per non-tolerant specialist.
  After 3 failures, the runner raises `CircuitBreakerError`, marks the
  paper `PAUSED` (new state), logs a `circuit_breaker_tripped` event,
  and returns cleanly. Tolerant specialists (reviewers, polish) are
  exempt — their failure is non-blocking. Fixes the run #14 failure
  mode where data_analyst was re-dispatched 3+ times when Allium was
  unrecoverable, burning 13 specialists before manual cancel.
- **Resume from last completed stage** (`POST /api/papers/{id}/resume`):
  re-enters the pipeline at the first phase whose canonical artifact is
  missing. Eligible from `paused` or `failed`. Avoids re-running phases
  that already succeeded after fixing a downstream issue.
- **Turn-budget signal in specialist prompts** (`src/core/specialists/base.py`):
  the system prompt opens with a "Turn Budget" section telling the
  model its max_turns and to write a first version of the canonical
  artifact within the first half. Fixes the run #16 failure where
  data_analyst saved write_file for the last turn and hit max_turns
  mid-pagination.
- **`SPECIALIST_SKILLS` consolidation**: previously two parallel dicts
  (`registry.py` and `loader.py`) that drifted whenever someone added a
  skill to one but not the other. Now one source of truth in
  `registry.SPECIALIST_SKILLS` with full paths (`data/cleaning`); loader
  resolves them.
- **Codex headless backend** (`LLM_BACKEND=codex`, src/modules/llm/codex.py)
  for ChatGPT Plus/Pro subscriptions. Shells out to `codex exec` — same
  pattern as the existing Claude Code backend. Adapted from coarse.
- **Gemini headless backend** (`LLM_BACKEND=gemini`, src/modules/llm/gemini.py)
  for Google AI Pro/Ultra. Probes `--approval-mode` vs legacy `--yolo`
  at startup. Adapted from coarse.
- **Skills bundled in the wheel** (`pyproject.toml` + `skills/__init__.py`):
  all 49 skill .md files ship in the e2er wheel. `e2er install-skills
  [--backend claude|codex|gemini|all] [--force]` copies them to the
  per-CLI skills dir (`~/.{backend}/skills/`).
- **Pre-run safety**: PR-time contract tests for specialist artifacts
  (every specialist in `SPECIALIST_ARTIFACTS` has registered skills,
  every skill path resolves to a real .md file, reviewer/polish lists
  stay aligned with registries) and integration smoke (theoretical
  pipeline end-to-end via MockLLMBackend, FastAPI POST surface,
  cascade-detection halt).
- **`POST /api/papers/{id}/resume`** (new endpoint, see above).
- **`GET /api/papers/{id}/failure-bundle`** (new): single-call
  diagnostic returning paper status + last_error (untruncated), every
  pipeline event with full payload, per-specialist drill-down
  (untruncated error_msg), workspace artifact listing (present vs
  missing), and the data_summary.md excerpt. Replaces the
  4-endpoint scavenger hunt diagnosis used to require.
- **Slash commands** (`.claude/commands/*.md`): `/pre-pr`,
  `/diagnose-run`, `/run-paper`, `/release-audit`.

### Lane B — Literature (Phase 2)

- **Provider contract tests** (`tests/lit/contract/test_provider_shapes.py`):
  first dedicated Lane B tests. For OpenAlex, Semantic Scholar, and
  arXiv, mock the documented response payloads and verify parsers
  handle standard shape, empty results, and network errors without
  crashing or raising into specialist code.

### Lane C — Data (Phase 2-3, 5)

- **Live OpenAPI contract tests** (`tests/data/contract/test_allium_developer_schema.py`):
  validates `AlliumDeveloperProvider` method kwargs against Allium's
  published OpenAPI specs (snapshots cached in
  `tests/data/fixtures/`). Catches required-param drift, list-vs-object
  body-shape mismatches, and silently-ignored unknown params. Run
  #14-#18's wrapper bugs would have been red CI checks instead of
  burning real specialist invocations.
- **Nightly schema-drift workflow** (`.github/workflows/schema-drift.yml`):
  re-fetches Allium's live OpenAPI at 03:30 UTC, diffs against the
  cached fixtures, opens a labelled issue with the unified-diff
  artifact if anything changed upstream.
- **Data-layer degradation breaker** (`src/modules/data/allium_developer.py`):
  tracks a sliding window of recent call outcomes. If >50% of the last
  6 calls errored, subsequent calls short-circuit with a structured
  "data layer degraded" envelope BEFORE hitting the network. Stops a
  specialist from draining its turn budget on dozens of 429 retries.
  Self-clears on the next successful call.
- **`GET /api/papers/{id}/data-queries`** (new): every Allium-style
  query the run submitted, with validation/approval status, executed
  timestamps, row counts, plus a rolled-up summary. Replaces the
  manual `cat audit_log.csv | grep` workflow.

### Fixed — Real bugs from the May 2026 NFT-marketplace live run

**Root cause (the hard lesson):** v3 made an architectural change v1/v2 didn't have — instead of delegating to the Claude Code CLI subprocess, it owns the tool-use loop directly via the Anthropic / OpenRouter SDKs (so `AlliumToolHandler` can intercept every tool call for guardrail validation). That introduced a class of bugs the unit-test suite never covered: the layer was never pressure-tested with realistic specialist output sizes. `MockLLMBackend` returns short canned outputs, so unit tests never saw the failure modes that hit on the first live run.

The May 2026 run lost ~$8 across two attempts before the diagnosis: `data_architect` writing `data_dictionary.json` as a single tool call exceeded `max_tokens_per_call=16384`, the model's output was truncated mid-write (`finish_reason=length`), the tool_loop correctly bailed (looping is futile — same wall every retry), the specialist was marked failed, and downstream specialists silently cascaded.

- `src/config.py`: `max_tokens_per_call` default bumped 16384 → 32768. Both Sonnet 4.6 and Haiku 4.5 support 64K out; 32K is a safe floor for the largest single tool argument any specialist emits.
- `src/core/specialists/base.py`: `_MAX_TURNS` 25 → 40. Independent issue from the same run — Sonnet specialists with Allium tools needed 29-38 turns to converge; 25 was tight enough that `idea_developer` hit the cap.
- `src/core/specialists/dispatcher.py`: cascade detection added to `execute_parallel`. After each batch, any non-tolerant specialist (anything not a reviewer / polish specialist) whose canonical artifact is missing now raises `RuntimeError` immediately — preventing downstream specialists from running on absent inputs and looping. Reviewer / polish specialists are still tolerant of partial failure (the aggregator handles gaps).
- `src/api/app.py`: invalid UUIDs on `/papers/{id}` and `/api/papers/{id}` now return 404 instead of 500. Previously a typo'd URL surfaced as `psycopg.InvalidTextRepresentation` → 500.

### Added — Stress tests for the tool-loop layer

`tests/test_tool_loop_stress.py` — five tests covering the failure modes mocked unit tests miss:
- 30 KB JSON tool argument forwarded to handler intact (the NFT-paper repro).
- 100 KB tool result threaded back into the message history verbatim.
- `finish_reason="length"` produces an actionable error referencing the setting to fix (so devs don't chase `max_turns` like I did).
- `max_tokens_per_call` default >= 32K (config-level floor).
- 25-turn message accumulation with correct token-usage summing.

Plus `tests/test_security_review_fixes.py` regression test for the cascade-detection behaviour above (`test_execute_parallel_raises_on_missing_canonical_artifact`).

### Added (P3 engineering hygiene)
- **mypy in CI.** `mypy src/` runs after `ruff` in `.github/workflows/tests.yml`.
  Config in `pyproject.toml` is pragmatic (catches real bugs without grinding
  on annotation completeness): `no_implicit_optional`, `strict_equality`,
  `warn_redundant_casts`. Per-module strictness can be ratcheted up later.
- **Pre-commit hooks.** `.pre-commit-config.yaml` runs ruff (with --fix),
  ruff-format, mypy, and standard hygiene hooks (trailing whitespace, large
  file check, merge-conflict markers, **detect-private-key**) on every commit.
  Install with `make hooks`.
- `Makefile` gains `typecheck` and `hooks` targets; help output updated.
- CONTRIBUTING.md gains a "Pre-commit hooks (recommended)" section and a
  "Local checks before pushing" cheat sheet.

### Fixed (real bugs surfaced by mypy)
- `src/modules/literature/bibtex.py` was calling `bibtexparser.load(f, parser=...)`
  which **does not exist** in bibtexparser v2 (project pins `>=2.0.0b7`).
  Any user with a `LITERATURE_BIBTEX_FILE` set would have hit
  `AttributeError: module has no attribute 'load'` at runtime. Migrated to
  `bibtexparser.parse_file()` and the v2 `Entry.fields_dict` API, with a
  glue layer keeping `_entry_to_metadata`'s dict interface unchanged.
- `src/modules/literature/arxiv.py`: `el.text` was accessed on an
  `Optional[Element]` without a None check — would raise `AttributeError`
  on author entries with missing `<atom:name>` tags.
- `src/modules/github/client.py`: `Github.get_user()` returns
  `NamedUser | AuthenticatedUser`; only `AuthenticatedUser` has `create_repo`.
  Cast added so type narrowing works without breaking tests that mock the
  user with MagicMock.
- `src/modules/github/push.py` and `src/api/app.py`: `GitHubClient(token, user)`
  was constructed with `Optional[str]` arguments that the constructor types
  as `str`. Added explicit None check (returns early when github is configured
  but token/username are missing) plus assert in push paths.
- `src/api/app.py`: `for e in events` shadowed the `except Exception as e`
  variable on the line above, which Python 3 deletes after the except block
  closes. Renamed to `exc` / `ev` to remove the deleted-variable read that
  mypy correctly flagged.
- `src/modules/llm/base.py` `tool_loop` typed `tool_handler: ToolHandler`,
  but engine.py was calling it with `tool_handler=None` for tool-less
  strategist decisions. Widened the abstract signature (and both concrete
  backends) to `ToolHandler | None`, with explicit None handling that
  surfaces a clear error if the model nonetheless requests a tool.
- `src/modules/data/tools.py`: `result` was reassigned from `ValidationResult`
  to `dict[str, Any]` in the same function, which mypy correctly flagged as
  a type confusion. Renamed the second binding to `query_result`.

### Added
- **Methodology selector** — papers now accept a `methodology` field at
  creation time: `empirical` (default, unchanged), `theoretical` (formal
  model only, no data/econometrics specialists), `mixed` (formal model +
  empirical test). Surfaced in the dashboard form and `POST /api/papers`.
- New `theory_specialist` (writes `model_spec.md`) ported from E2ER v2.
  Dispatched by the strategist when methodology is `theoretical` or
  `mixed`. Skill bundle: `base/economist`, `modeling/game-theory`,
  `modeling/asset-pricing`, `math/proof-strategies`,
  `reasoning/identification`.
- `sql/009_papers_methodology.sql` — adds `methodology` column to the
  `papers` table with a CHECK constraint.
- `tests/test_methodology.py` — 12 tests pinning the registry, prompt
  contract, manifest persistence, API validation, and specialist
  invocation.
- GitHub Actions CI: ruff lint + format + pytest on Python 3.11 and 3.12,
  triggered on push to `main` and all PRs.
- Branch protection on `main` requiring both pytest matrix jobs to pass
  before PR merges.
- `Makefile` with `make smoke` (free, ~10s, all 155 mocked tests) and
  `make smoke-paid` (~$0.50 Haiku end-to-end test).
- Issue templates (bug report, feature request) and PR template under
  `.github/`.
- `tests/test_pipeline_resilience.py` — 18 tests guarding against upstream
  result loss when downstream phases fail (crash injection per phase,
  resume-without-redo, artifact persistence, GitHub push idempotence,
  state-file atomicity, no-op replay).
- `SECURITY.md` and `CHANGELOG.md`.

### Changed
- `PipelineState.save()` now writes atomically (tmp + rename) and keeps a
  `.bak`. Previously a crash mid-write could corrupt the only state file
  and lose all upstream progress on resume.
- `PaperStatus` and `PipelineMode` now inherit from `StrEnum`, matching
  the pattern used in E2ER v2.
- Renamed `BudgetExceeded` → `BudgetExceededError` (PEP 8 exception
  naming).
- `src/api/app.py`: `TemplateResponse` calls migrated to the
  `(request, name, context)` signature for current Starlette.

### Fixed
- `tests/test_regressions.py`: removed hardcoded absolute path that
  would have failed on every CI runner.
- `src/modules/data/audit.py` and `tools.py`: missing top-level
  `from pathlib import Path` (worked at runtime only via `from __future__
  import annotations`).
- `src/modules/literature/bibtex.py`: removed unused `doi_index` dead
  code that hid an incomplete dedup intention.

## [3.0.0] — Initial public release

The first open-source release of E2ER. Differs from the private v1/v2
which were tied to internal infrastructure.

### Architecture
- Standalone package — no shared/ imports, no Docker network dependencies
  on private services.
- BYOK for all external services: `ANTHROPIC_API_KEY`, `OPENROUTER_API_KEY`,
  `ALLIUM_API_KEY`, `GITHUB_TOKEN`.
- Owns its tool-use loop in Python (no Claude Code CLI subprocess) so
  every tool call can be intercepted for guardrail validation.
- Two LLM backends: Anthropic API (with prompt caching) and OpenRouter
  (OpenAI-compatible). Switch via `LLM_BACKEND=anthropic|openrouter`.

### Pipeline
- Two modes: `single_pass` (fast draft) and `iterative` (full loop with
  ceiling detection, self-attack, polish stack).
- New phases vs v2: ceiling check, adversarial self-attack with severity
  scoring, parallel polish stack (formula, numerics, institutions,
  bibliography, equilibria), mechanical 3-rule review aggregation.
- Full pipeline state persistence and resume-from-crash support.

### Data module
- Allium integration with 5 hard guardrails (no `SELECT *`, fields must be
  in `data_dictionary.json`, time-bound `WHERE` required, transaction
  granularity requires justification, production queries require prior
  feasibility run).
- Two-phase workflow: feasibility (auto-approved sample) → production
  (researcher approval required).
- Full audit log persisted as `audit_log.csv` in the replication package.
- Module is optional: set `DATA_MODULE_ENABLED=false` for literature-only
  or manually-provided-data papers.

### GitHub integration
- Auto-creates a per-paper repo with `.gitignore` as the FIRST commit
  (so Overleaf import never pollutes git history with build artifacts).
- Pushes the LaTeX draft, replication package, and audit bundle.

### Cost tracking
- Per-call usage recorded in `llm_usage` table.
- Per-paper hard cost cap enforced at every phase boundary.
- Audit bundle export (`.tar.gz`) includes `usage.json` with full cost
  breakdown.

[Unreleased]: https://github.com/bhanneke/E2ER-project/compare/v3.0.0...HEAD
[3.0.0]: https://github.com/bhanneke/E2ER-project/releases/tag/v3.0.0
