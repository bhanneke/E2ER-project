# Changelog

All notable changes to E2ER v3 are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
