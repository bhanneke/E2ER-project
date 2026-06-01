# Changelog

All notable changes to E2ER v3 are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### v0.9 M1 — `e2er doctor` user-facing preflight

- **New `e2er doctor` command.** Answers "am I ready to spend a paper run?"
  before the user does — checks the LLM backend (CLI on PATH for `$0`
  backends, API key set for SDK backends), bundled skill files, DB (SQLite
  default or Postgres reachable), and probes every configured data +
  literature provider with a one-line "what this paper would have access
  to." Verdict: ✅ Ready / ⚠️ Partial (paper runs work, some providers
  unavailable) / ❌ Blocked (backend, DB, or skills missing — exact fix
  surfaced). `--json` for scripting. Closes M1 of the v0.9 plan.
- **Fast, quiet DB probe.** The Postgres reachability check uses a direct
  `psycopg.AsyncConnection.connect(connect_timeout=5)` instead of going
  through the runtime connection pool — preflight now fails in ~5s instead
  of hanging 30s with retry spam when `DATABASE_URL` points at a Postgres
  that isn't running. Error message includes the actionable hint: unset
  `DATABASE_URL` / `POSTGRES_URL` to fall back to the zero-config SQLite
  default.
- **`scripts/live_check.py` refactored to a thin shim** over the new
  `src.doctor.run_provider_checks` engine. Dev harness and user-facing
  command now share the same probe code (DRY); live-check stays for nightly
  CI and for catching provider drift before users do.

## v0.8.1 — 2026-05-30

## v0.8.1 — 2026-05-30

Stability + corpus extensions. Bug fixes from a full code review —
**safety** (Allium guardrails no longer bypassed without a
`data_dictionary.json`; SQLite Allium-approval workflow works; SSRF
hostname resolution), **Lane-A robustness** (strategist JSON guards,
mechanism-gate, resume-status, single-order cascade), **Lane B/C wins**
(storage citations; OpenAlex/S2 null crash; `e2er run --acknowledge-
unproven`; FileToolHandler sandbox; OpenRouter `content=""`). Plus
user-driven additions: structured GitHub issue templates for data-source
and literature-provider requests, and `LOCAL_DATA_DIR` extensions
(comma-separated roots, recursive walk, PDFs staged into
`workspace/literature/` with `read_reference(path=…)`).

### Cross-lane

- **Structured GitHub issue templates** for the most common asks:
  `data_source_request` (provider, auth, coverage, example RQ) and
  `literature_provider_request` (capability, gap, auth). Both routed by
  `lane-*` / `provider-request` labels. Generic feature requests still go
  via `feature_request.md`.

### Lane A — Pipeline

- **Fix: malformed strategist JSON no longer crashes the paper.**
  `ceiling_check` and `run_self_attack` did a bare `json.loads` on LLM
  output — truncated/invalid JSON raised and failed the whole run. They now
  use the tolerant `extract_json` and skip malformed `WorkOrder`/finding
  items instead of raising.
- **Fix: a missing mechanism-reviewer score can no longer be silently
  accepted.** The Rule-1 mechanism gate no-op'd when the mechanism score was
  absent, letting a paper ACCEPT on the other reviewers' average. A missing
  (but expected) mechanism score now forces `MAJOR_REVISION`.
- **Fix: resume tolerates a bad/legacy persisted status.** `PaperStatus(
  state.last_status)` could raise `ValueError` and wedge a completed paper
  into FAILED on resume; it's now coerced with a safe fallback.
- **Fix: tier-0 context builder handles explicit-null manifest fields**
  (`datasets: null` / `research_question: null`) instead of `TypeError`.

### Lane B — Literature

- **Fix: `store_paper` persists citation counts.** `citations` was in the
  `ON CONFLICT DO UPDATE` clause but missing from the INSERT column list, so
  inserts dropped the count and conflict-updates zeroed it. Added to the
  insert.
- **`LOCAL_DATA_DIR` extensions.** Accepts a **comma-separated list** of
  roots, an opt-in **`LOCAL_DATA_DIR_RECURSIVE=true`** to walk
  subdirectories (paths under `workspace/data/` are preserved), and now
  also **stages `*.pdf` into `workspace/literature/`**. The bib-relevant
  specialists' reference summary lists those local PDFs so they can be
  read via the new `read_reference(path=...)`. New
  `src/modules/local_corpus.py` consolidates parsing/walking;
  `LocalBibLibrary` uses it for `.bib` discovery across multiple roots.
- **`read_reference`** accepts a new **`path`** argument (workspace-
  relative) for the staged local PDFs — no download, no auth, sandboxed
  under the workspace root.

### Lane C — Data

- **Fix (safety): guardrails no longer fully bypassed without a data
  dictionary.** `_query_allium` only ran `validate_all` when a
  `data_dictionary.json` was present, so a production query with no
  dictionary ran with ZERO validation. Now the structural rules (no
  `SELECT *`, time-bound) and feasibility-first/approval gate always fire;
  only the field-whitelist (Rule 2) is dictionary-gated (skipped with a
  warning).
- **Fix: audit inserts generate app-side UUIDs.** `log_query` /
  `create_approval_request` relied on a DB id default; SQLite has none, so
  `id` was NULL and the approval-request join silently never surfaced
  pending production queries on the default SQLite DB. Now both generate a
  `uuid4()` client-side — the Allium approval workflow works on SQLite.

### Cross-lane

- **Fix: cost-estimate labeling for the codex/gemini backends.** `app.py`
  checked `codex_cli`/`gemini_cli`, but the real backend literals are
  `codex`/`gemini`, so synthetic cost figures were mislabeled as real.
- **Fix: `literature_kb_enabled` honors `DATABASE_URL`.** It keyed off
  legacy `postgres_url`/`db_password`, leaving the pgvector KB silently off
  for the documented `DATABASE_URL=postgresql://…` path. Now derived from
  the resolved DB URL.
- **Fix (security): SSRF guard resolves hostnames.** `_check_url` only
  blocked literal private IPs; a hostname (e.g. `metadata.google.internal`
  → 169.254.x, or `localhost`) slipped past. It now resolves the host and
  blocks if any resolved address is private/loopback/link-local.
- **Fix: `e2er run --acknowledge-unproven` flag.** The CLI hardcoded
  `acknowledge_unproven_tuple=True`, silently disabling the $1 first-run
  floor (and the README documented a flag that didn't exist). The flag now
  exists (default off → floor enforced for metered backends); the $0
  flat-rate CLI backends (claude_code/codex/gemini) auto-acknowledge.
- **Fix: single-order dispatch gets the cascade guard.** The missing-
  canonical-artifact check ran only in `execute_parallel`; a lone specialist
  could "succeed" without its artifact and starve downstream work. Extracted
  `assert_artifacts_written`, now applied to both paths.
- **Fix: `FileToolHandler` sandbox uses path containment, not a string
  prefix** (a sibling workspace with a prefix name could escape).
- **Fix: OpenRouter tool-only turns send `content=""`** instead of `null`
  (some OpenAI-compatible servers reject `null` content + tool_calls).

## v0.8.0 — 2026-05-28

Pluggable data & literature providers. Specialists now **discover** data
sources in light of the research question — FRED and yfinance reach the
tool loop via `list_data_sources` + a unified `fetch_data`, and Allium sits
behind a `Warehouse` capability (its 5 guardrails unchanged). They also
pull the researcher's own reference library (local `.bib`, `LOCAL_DATA_DIR`,
and **Zotero** via the Web API) and read **full-text PDFs** (`read_reference`).
Both lanes are now registry-pluggable, so new providers are drop-in.

### Cross-lane

- **`scripts/live_check.py` — live smoke harness.** Exercises the real
  data/literature provider paths (yfinance, FRED, Allium connectivity,
  OpenAlex search, `read_reference` on an OA PDF, Zotero library) against
  live services, auto-skipping providers without credentials. No LLM calls
  (free). Complements `make smoke` (offline/mocked) and `make smoke-paid`
  (full LLM run). Run: `python scripts/live_check.py`.

### Lane C — Data

- **Allium folded behind a `Warehouse` capability (M3b of
  `docs/MODULARIZATION_PLAN.md`).** Allium is now a first-class registered
  provider: `AlliumWarehouse` owns its `card()`, `tools()` (→ `ALLIUM_TOOLS`)
  and `handler()` (→ `DeferredAlliumToolHandler`); `_run_pipeline` assembles
  it by iterating `warehouses(settings)` instead of hardcoding, and the
  catalog builds its card from the warehouse. Pure refactor — same condition
  (Allium key present), same tools, **the 5 `QueryValidator` guardrails and
  approval flow are untouched**, and `has_allium`/`data_module_enabled` are
  unchanged. Completes the Lane-C registry (series + warehouse).
- **Series data in the agent loop + RQ-aware discovery (M3a of
  `docs/MODULARIZATION_PLAN.md`).** FRED and yfinance are no longer
  CLI-only — specialists reach them in the tool loop. New `SeriesFetcher`
  capability + data registry (`providers.py`, `registry.py`) mirror the
  Lane-B pattern. Two new tools: `list_data_sources` (serves the registry
  catalog so the agent picks the right source for the research question)
  and a unified `fetch_data(provider, method, params)`. Allium is unchanged
  — it keeps its guarded `query_allium` tool and is advertised in the
  catalog (the 5 guardrails are untouched). Series tools are always on
  (yfinance needs no key); budgeted (`_MAX_FETCHES=20`). M3b will fold
  Allium behind a `Warehouse` capability into the same registry.

### Lane B — Literature

- **Fix: literature search crashed on OpenAlex/S2 explicit nulls.** A live
  search returned 0 papers because `openalex._parse` raised
  `'NoneType' object has no attribute 'get'` on a result whose
  `primary_location.source` (or `open_access` / `authorships`) was an
  explicit `null` — `.get(k, default)` doesn't apply the default for a
  present-but-null value. Both parsers now guard with `or {}` / `or []`.
  Regression tests added (the mocked payloads previously only used
  well-formed fields, so the bug only surfaced live).
- **Full-text `read_reference` tool (M2.5 of `docs/MODULARIZATION_PLAN.md`).**
  Specialists can now read a reference's PDF in full to deepen the lit
  review, not just its abstract. New `read_reference` literature tool takes
  a `pdf_url` (surfaced in search/fetch results and on `[PDF]`-marked
  reference-list entries, incl. Zotero attachments) or a `doi` (resolves an
  open-access PDF). Downloads (auth'd for Zotero hrefs, `/file/view` →
  `/file`), extracts text via **pypdf** (`pdf.py`), and returns it
  truncated to ~20K chars. Tightly budgeted (`_MAX_READS=6` + per-read char
  cap) given the prior 522K-token literature blowup. `fetch_bytes` gained a
  `max_bytes` override (PDFs exceed the 2 MB default). New `pypdf` dep. New
  `ZoteroLibrary` `ReferenceLibrary` reads the researcher's Zotero library
  via the Web API's native JSON (`zotero.py`), maps items to
  `PaperMetadata`, and captures each item's primary PDF attachment href
  (for the planned on-demand `read_reference` tool, M2.5). Config:
  `ZOTERO_API_KEY` + one of `ZOTERO_USER_ID` / `ZOTERO_GROUP_ID`; merged
  into the reference summary after local `.bib`, deduped by (title, year).
  Unset → no-op. Sync `fetch_text_sync` helper added for the (sync)
  reference-library path. Degrades to `[]` on any Zotero error — can't
  break paper creation.
- **Provider interface + registry (M1 of `docs/MODULARIZATION_PLAN.md`).**
  Formalized the de-facto interface the source modules already shared into
  capability sub-types — `SearchSource` (web discovery; OpenAlex, arXiv,
  Semantic Scholar) and `ReferenceLibrary` (the researcher's own corpus;
  `LocalBibLibrary` over `LITERATURE_BIBTEX_FILE` + `LOCAL_DATA_DIR`) — in
  new `providers.py` / `registry.py`. `LiteratureToolHandler` and
  `_load_reference_summary` now iterate the registry instead of hardcoding
  provider names. Pure refactor: the search (OpenAlex→arXiv) and DOI-fetch
  (OpenAlex→S2) fallback chains are reproduced exactly; +13 tests, no
  behaviour change. This is the seam Zotero (M2) and Citavi (M4) plug into.

## v0.7.3 — 2026-05-26

Fix the patch_revisor section-target resolution bug surfaced by
the v0.7.2 live re-validation on paper `7f4f2363`. The drafter
got a paper all the way through to the revision phase (v0.7.0's
verify_numbers parser fix worked), but the patch_revisor emitted
edits targeting canonical section names (`section:results`,
`section:mechanism`) that didn't exist in the actual draft. The
merger reported "target region not found" with no hint and the
paper REJECTED on parser bugs, not real hallucinations — for the
second release in a row.

### Lane A — Pipeline

- **Merger emits "did you mean..." suggestions on section/table
  not-found.** When `apply_edit` can't resolve a `section:` or
  `table:` target, the error message now appends the list of
  available section titles or labelled tables in the document.
  Example before/after:
  - Before: `target region 'section:results' not found in document`
  - After: `target region 'section:results' not found in document (available sections: 'Introduction', 'Identification Strategy', 'Empirical Strategy', 'Discussion')`
  Two new public helpers: `list_section_titles(text)` and
  `list_table_labels(text)`. Suggestions are suppressed when the
  list is empty (avoids the misleading
  `(available sections: )` suffix on minimal LaTeX skeletons).
  Universal targets (`paper:full` / `abstract` / `references`)
  don't get suggestions.
- **`writing/scoped-revision.md` skill update.** New section
  ("Before you compose any edits — list the draft's actual
  targets") instructs the patch_revisor to grep the draft for
  `\section{...}` and `\label{tab:...}` lines before composing
  patches. Explains the case-insensitive substring matching the
  merger uses, the common failure mode (canonical-name vs
  actual-heading mismatch), and the `paper:full` fallback for
  findings that don't have a dedicated section.

### Test counts

- Mocked suite: 598 passed (was 590 in v0.7.2; +8 here).
- 8 new tests in `tests/pipeline/test_patch_merger.py`:
  - 4 for `list_section_titles` and `list_table_labels` helpers.
  - 4 for the extended error: section suggestions, table
    suggestions, no suggestion for non-section/table targets, no
    misleading suffix when the list is empty.

## v0.7.2 — 2026-05-26

Closes the v0.7.1-noted follow-up: a CLI command to resume
paused / failed / zombie papers. Completes the status / cancel /
resume trio so the operator never has to drop down to curl.

### Cross-lane

- **`e2er resume <paper_id>`** — restart a paused or failed
  paper from the terminal. Optional `--max-cost N` raises the
  cap atomically with the resume (sent through to the v0.5+
  `ResumeRequest` body). Surfaces the paper's title + previous
  status + cap delta + `last_error` before issuing the POST, so
  the operator knows what they're restarting. Unlike `status`
  and `cancel`, this command DOES auto-start uvicorn — the user
  is asking the paper to start running again, so the server
  needs to be up.
  - 200 → prints the new transient status (`resuming`) +
    dashboard URL, optionally tails to terminal via `--tail`
  - 400 → surfaces the validation detail (e.g. non-positive
    cap) directly so the user can fix and retry
  - 409 → "already running" with a hint to `e2er cancel` first
  - 404 → "paper not found"
- **9 new regression tests** in `tests/test_cli_status.py`
  covering: no-cap-change happy path, cap-raise happy path,
  completed-paper short-circuit, 400 / 409 / 503 / 404 error
  paths, `--tail` integration, the API-unreachable branch.

### Test counts

- Mocked suite: 590 passed (was 581 in v0.7.1; +9 here).

## v0.7.1 — 2026-05-26

Two new lightweight CLI commands surfaced by the v0.7.0
fresh-install UX test: when `e2er run`'s tailer times out (or
the user ^C's it), there was no scripted way to re-attach,
inspect the current state, or cancel a runaway paper without
opening the dashboard.

### Cross-lane

- **`e2er status <paper_id>`** — one-shot snapshot of a paper:
  status, mode/methodology, cost meter (with the
  `cost_is_estimate` marker on CLI backends), specialist call
  count, token total, workspace path, dashboard URL. Shows
  `last_error` verbatim when present so the user can diagnose
  REJECTED / PAUSED / FAILED without parsing the events log.
  With `--tail`, re-uses the same polling loop `e2er run` uses
  so the user can re-attach after ^C. Short-circuits on already-
  terminal status (no wasted polls). Hits the local API by
  default; respects `E2ER_API_URL` for remote inspection.
- **`e2er cancel <paper_id>`** — POSTs the `/cancel` endpoint
  with a confirmation prompt (skippable via `--yes`). Surfaces
  the title + current status + spend-so-far before the user
  confirms so they don't cancel by accident. Terminal-status
  short-circuit. Treats post-cancel 404 as success (the paper
  finished while we were asking; that's what the user wanted).
  Brief post-cancel poll so the user sees the CANCELLED
  transition land before the shell returns.
- **Cost output now formats with two decimals.** Pre-fix
  `e2er status` showed `$8.462921999999999`; now `$8.46`. Float
  noise was reaching the user-facing string when the API
  returned high-precision cost totals.
- **`_poll_status` now treats `rejected` as terminal.** Pre-fix
  the `e2er run` tailer kept polling forever on REJECTED papers
  (a v0.5+ status it didn't know about). Observed during fresh-
  install testing on paper 2ca473aa.

### Test counts

- Mocked suite: 581 passed (was 554 in v0.7.0; +27 cli_status).
- 27 new tests in `tests/test_cli_status.py` covering
  formatters, exit codes, the unreachable-API branch, the
  confirmation prompt, and the post-cancel-404 race handling.

### Known follow-up (v0.7.2 candidate)

- `e2er resume <paper_id>` — natural complement to `cancel`.
  PAUSED papers can be resumed via `curl POST /resume` today;
  a CLI command would close the same UX gap that `status` and
  `cancel` close. Out of scope for v0.7.1.

## v0.7.0 — 2026-05-24

Better onboarding + a verify_numbers parser fix, bundled.
Surfaced by direct user feedback ("pip install e2er and then
what?") and by the v0.6.1 live run on paper `f79b7cd9` that hit
two false-positive critical mismatches caused by parser bugs.

### Cross-lane

- **New `e2er init` command — guided first-paper setup wizard.**
  Closes the post-`pip install e2er` onboarding gap. Walks the
  user through 4 steps (LLM backend pick + prereq check, data
  module on/off, optional BibTeX path, optional Postgres
  `DATABASE_URL`), an optional GitHub-integration prompt, then
  writes `./.env` (with confirm-overwrite), runs `e2er
  install-skills`, and prints three concrete example research
  questions to copy. Hand-rolled stdin wizard — no new
  dependencies (no `click` / `prompt_toolkit`). TTY-detected so
  non-interactive invocations exit with a helpful one-line guide
  instead of blocking on `input()`. Secrets discipline: GitHub
  PATs and API keys collected during the wizard are written to
  `.env` as comments, never as live env vars. 24 new unit tests
  in `tests/test_cli_init.py`. README quickstart updated to lead
  with `e2er init`.

### Lane A — Pipeline

- **Fix two `verify_numbers` false-positives**: ISO date strings
  in column headers (`2021-03-01`) were being parsed as the bare
  year `2021`, false-positive-mismatching against unrelated
  source values; and LaTeX brace-protected thousands separators
  (`1{,}573.89` — the form that survives math mode) were being
  split into two bogus numbers (`1` and `573.89`). Both surfaced
  on the v0.6.1 live-validation paper `f79b7cd9`, which was
  REJECTED entirely on parser bugs rather than real
  hallucinations. New `_normalize_cell(cell)` helper runs
  before `_NUMBER_RE` on each tabular cell: normalizes `{,}` →
  `,` so the existing thousands branch picks the value up
  intact, then strips ISO / slash / US date patterns so years
  inside dates don't leak as numeric claims. Bare years outside
  date context (e.g. `Sample size & 2021`) still extract — the
  fix is targeted at dates, not all four-digit numbers. 5 new
  regression tests in `tests/pipeline/test_verify_numbers.py`.

### Test counts

- Mocked suite: 554 passed (was 525 in v0.6.1; +24 wizard +5
  verify_numbers fix).

## v0.6.1 — 2026-05-23

Hot-fix on v0.6.0 closing the known follow-up surfaced by the
v0.6.0 live run on paper `3bc58e8d`.

### Lane A — Pipeline

- **Iterative-phase guard extended to drop the legacy `revisor`**
  on iterations 2+, alongside `paper_drafter`. Both specialists
  rewrite `paper_draft.tex` from scratch every time they run, so
  the same drift argument that motivated step 6's
  `paper_drafter` guard applies to `revisor`. v0.6.0's live run
  showed the strategist dispatching `revisor` during iterative
  phase even though `paper_drafter` was correctly skipped — the
  guard only filtered one. v0.6.1 closes the same door for both.
- **Strategist system prompt updated** to name `revisor`
  explicitly alongside `paper_drafter` in the iterative-phase
  rule, and to point at `patch_revisor` (dispatched automatically
  by the runner's revision phase) as the legitimate path for
  scoped revisions. Removes the v0.6.0 ambiguity where the prompt
  said "use `revisor` only when upstream artifacts are updated"
  but the runner now expects no `revisor` calls in iterative
  phase at all.
- **`test_section_writer_not_dropped_on_iteration_2` renamed** to
  `test_legitimate_specialists_not_dropped_on_iteration_2` and
  updated to reflect the v0.6.1 contract (was asserting `revisor`
  survives the guard, now asserts only the legitimate specialists
  do).
- **4 new regression tests** in `test_iterative_phase_guard.py`
  pinning the extended-guard contract.

Full mocked suite: 525 passed (was 521 in v0.6.0; +4 here).

## v0.6.0 — 2026-05-23

**Targeted-revision discipline.** Closes the three drift sources
identified in `docs/V0.6_PLAN.md`: full-rewrite `revisor` on
MAJOR_REVISION, parallel-`revisor` write race in self-attack, and
unconstrained `paper_drafter` re-dispatch in the iterative phase.
Validated end-to-end on paper `3bc58e8d` (2026-05-22, 38 min,
$12.36 est., Sonnet via Claude Code CLI).

### Lane A — Pipeline

- **New `patch_revisor` specialist + deterministic merger.**
  Replaces the pre-v0.6 `revisor` in every dispatch site. Writes
  structured edits to `paper_draft.tex.edits.json`; the merger
  (`src/core/strategist/patch_merger.py`) validates each edit's
  `target` against the work order's `Finding` list, applies
  in-scope edits to `paper_draft.tex`, and emits
  `paper_draft.tex.applied.diff` as a unified-diff audit
  artifact. One edit type supported in v0.6: `replace_text`
  with `find` / `replace` / `find_must_be_unique`. Target
  schema: `section:<name>` / `table:<label>` / `references` /
  `abstract` / `paper:full`. Edits whose target isn't in the
  findings are rejected before any text is touched.
- **Structured `Finding` dataclass + three collectors.** New
  `src/core/strategist/findings.py` introduces the
  `Finding(source, source_detail, target, severity, problem,
  suggested_fix)` frozen dataclass that every revision source
  emits: `collect_self_attack_findings`,
  `collect_verify_numbers_findings`, `collect_review_findings`.
  `combine_findings` sorts severity-desc with source priority
  (verify_numbers > self_attack > review on ties — numerical
  mismatches are the most mechanical to fix).
- **MAJOR_REVISION wired through `patch_revisor`.** Replaces the
  pre-v0.6 free-text-rationale path. Combines review findings +
  (when present) verify_numbers findings, serialises them as a
  JSON block in the work order's `focus`, dispatches
  `patch_revisor`, calls `merge_patch_file`. fully_applied →
  COMPLETED; missing patch file or failed edits → REJECTED with
  the first 3 failures named in `last_error`. Edge case:
  MAJOR_REVISION with no actionable findings short-circuits to
  COMPLETED without dispatching (avoids wasted spend).
- **Self-attack critical findings wired through `patch_revisor`.**
  Eliminates the pre-v0.6 parallel-revisor write race. Top-3
  critical findings are batched into ONE patch_revisor call.
  Patch failures at this phase are advisory (logged, do NOT
  REJECT) — the downstream review phase catches what remains.
- **`verify_numbers` auto-patch loop (proactive gate).** Pre-v0.6
  the gate was defensive: critical mismatch → REJECTED. v0.6
  closes the detect → patch → re-detect loop: critical mismatch →
  dispatch `patch_revisor` with the mismatch findings → re-run
  `verify_numbers` on the patched draft → REJECTED only if the
  second pass still has criticals. Bounded by
  `_VERIFY_NUMBERS_AUTO_PATCH_BUDGET = 1` (single attempt) so a
  drafter that consistently disagrees with the source JSON
  doesn't loop. The persisted `number_verification.json`
  reflects the post-patch state.
- **Iterative-phase guard against `paper_drafter` re-dispatch.**
  Two-layer defence:
  - Soft: strategist's system prompt instructs it to use
    `section_writer` (scoped to a `section:<name>` focus) on
    iterations 2+, never `paper_drafter`. Validated on the live
    run — strategist used `section_writer` 3× in iter 2.
  - Hard: `_dispatch` drops `paper_drafter` work orders when
    `self._iteration >= 2`, logging a warning. Catches the
    strategist if it ignores the soft instruction. iteration 0
    (initial) and iteration 1 (first iterative) still allow
    `paper_drafter` legitimately.
- **`patch_revisor` loads three skills.** `writing/scoped-revision`
  (new — defines the patch-file shape with worked examples for
  verify_numbers and self_attack findings),
  `writing/cite-numbers-by-source` (v0.5 — same discipline as
  the drafter), `writing/personal-style`, `reasoning/anti-slop`.
- **Five architecture invariants pinned.** Each step has a
  primary regression test; `tests/pipeline/integration/test_v0_6_invariants.py`
  documents all five in one place and adds cross-step
  assertions (legacy `revisor` never dispatched by v0.6 runner
  paths; both source types reach `patch_revisor`'s focus when
  review + verify_numbers both have findings; merger
  scope-enforcement holds across dispatch sites).

### Test counts

- Mocked suite: 521 passed (was 422 in v0.5.0; +99 in v0.6).
- New test modules: `test_findings.py`, `test_patch_merger.py`,
  `test_patch_revision_wiring.py`, `test_self_attack_patch_wiring.py`,
  `test_verify_numbers_auto_patch.py`, `test_iterative_phase_guard.py`,
  `test_v0_6_invariants.py`.

### Known follow-ups (deferred to v0.6.1)

- The legacy `revisor` specialist is no longer dispatched by v0.6
  runner code paths, but the strategist may still freely dispatch
  it from `_run_iterative_phase`. Surfaced by the 2026-05-22 live
  run (one revisor call in iterative phase). Candidate fix:
  extend the iterative-phase guard to also drop `revisor` on
  iterations 2+, OR update the strategist prompt to discourage
  it explicitly.

## v0.5.0 — 2026-05-21

**Anti-hallucination & methodology-aware pipeline.** Full design
record at `docs/V0.5_PLAN.md`. Motivated by v0.4.5 live tests on
papers `a6182f08`, `cbe8048f`, `eea5379b`, and validated end-to-end
against fresh live runs on 2026-05-20 (`234a11ea`, `fd6bf64d`) and
2026-05-21 (`525fa03c`) — see `docs/V0.5_LIVE_VALIDATION.md`.

### Lane A — Pipeline

- **Programmatic anti-hallucination gate before review** (new file
  `src/core/pipeline/verify_numbers.py`, 357 lines). Scans every number
  in `\begin{tabular}` blocks of `paper_draft.tex` and matches each
  against the flat numeric values from `summary_statistics.json`,
  `estimation_results.json`, `robustness_results.json`, and
  `figure_spec.json`. Tolerance 0.5% relative; integers ≥10 must be
  exact; signs must match. Critical mismatches (relative error >10%
  vs the closest source value) → status `REJECTED` and reviewers
  never spawn. Persists `number_verification.json` at workspace root
  on every run. Live-test paper `a6182f08`'s "log realized variance
  falls by 0.41 ($t=-3.9$)" hallucination was caught by
  `technical_reviewer` only after 6 reviewers had run; this gate
  catches it deterministically, at $0, before any reviewer spends a
  token. Graceful skip when no source JSON files are present (warn +
  pass), so papers from before the analyst contract was tightened
  don't regress.
- **Methodology-aware phase routing.** `PipelineRunner.__init__` now
  accepts `methodology: str = "empirical"`, propagated from
  `papers.methodology` through `_run_pipeline` and `resume_paper` in
  the API. For `methodology == "theoretical"`,
  `_reviewers_for_methodology()` drops `data_reviewer` from the
  6-reviewer panel and `_run_replication_phase()` early-returns.
  Live-test paper `cbe8048f` burned ~$0.34 on a `data_reviewer` stub
  over an empty contract plus ~$0.43 on a replication packager with
  no replication artifacts — both wasted, both gone in v0.5.
- **New status `PaperStatus.REJECTED`, distinct from `FAILED`.**
  `FAILED` is reserved for crashes; `REJECTED` means the pipeline
  ran successfully and the quality gate (verify_numbers,
  HARD_REJECT, MECHANISM_FAIL) returned a negative verdict.
  Resumable: transitions back to IDEA / IN_PROGRESS / REVIEW /
  REVISION / CANCELLED. `_run_revision_phase`'s HARD_REJECT and
  MECHANISM_FAIL branches updated to emit REJECTED instead of
  FAILED. New IN_PROGRESS → REJECTED transition for the
  verify_numbers gate path.
- **`BudgetExceededError` → `PAUSED`, resumable.** New `except
  BudgetExceededError` branch in `PipelineRunner.run()`, alongside
  the existing `CircuitBreakerError` handler. Persists state, logs a
  `paused_budget` event with `{spent, cap}`, returns a structured
  `{status: "paused", reason: "budget_exhausted", ...}` payload.
  The operator raises `--max-cost` and POSTs
  `/api/papers/{id}/resume`; existing resume-from-disk logic picks
  up at the first incomplete phase. Previously a budget exhaustion
  was indistinguishable from a crash.
- **`PAUSED` and `REJECTED` rows now persist `last_error`** on the
  `papers` table. Pre-v0.5, only FAILED and CANCELLED rows carried
  the error/reason; PAUSED and REJECTED dropped it at the SQL layer,
  leaving the dashboard with `last_error=NULL` and no way to render
  the budget breakdown, circuit-breaker specialist, or review-gate
  rationale. `_update_status` now treats PAUSED and REJECTED the
  same way as FAILED and CANCELLED for error preservation.
  Discovered while writing the v0.5 budget-pause regression test.
- **`POST /api/papers/{id}/resume` accepts `max_cost_usd` in the
  request body.** Pre-v0.5 the endpoint silently ignored the body and
  read the cap from the DB row, so raising the cap on a budget-paused
  paper required a manual `UPDATE papers SET max_cost_usd = ...`
  beforehand (the workaround surfaced during the 2026-05-20 live
  validation). The endpoint now accepts an optional `ResumeRequest`
  body; a positive `max_cost_usd` is validated and persisted on the
  row atomically with the status reset, then passed to the runner.
  Zero or negative values 400. Calls without a body preserve the
  pre-v0.5 behaviour (use the existing row value).
- **`paper_drafter`, `section_writer`, `abstract_writer`, and
  `revisor` load a new `writing/cite-numbers-by-source` skill** that
  teaches the cite-by-JSON-key discipline: every numeric value in
  the paper must trace to a value in `summary_statistics.json`,
  `estimation_results.json`, `robustness_results.json`, or
  `figure_spec.json`. HTML-comment markers (`<!-- src: file#key -->`)
  let `verify_numbers` mismatches name the exact source path the
  drafter should have used. Reduces hallucination rate in the first
  place; complements the post-hoc gate. Includes the "empty sidecar
  → no quantitative claims" rule so the design-without-estimates
  pathway is explicit.
- **Test-mock fix:** `MockLLMBackend._detect_specialist` now matches
  on the canonical `You are the <Name> specialist` role line in the
  system prompt rather than searching for any specialist name
  substring. The old heuristic silently misrouted calls whenever a
  skill referenced another specialist by name (e.g. the new
  `writing/cite-numbers-by-source` mentions "econometrics
  specialist" → paper_drafter calls were routed to the econometrics
  output → paper_draft.tex was never produced). Now matches one
  occurrence per prompt with no skill-content interference.
- **Machine-readable JSON sidecar contract for verify_numbers.**
  Pre-v0.5 every specialist was told to write EXACTLY ONE file, so
  even when a skill described a JSON sidecar (e.g. `data/figure-spec`),
  the system prompt overrode it and the JSON never appeared. The
  2026-05-20 live runs confirmed this empirically: both papers wrote
  `number_verification.json` with `skipped_reason="no source JSON
  files found"` — the gate was effectively a no-op. v0.5 adds a
  `SPECIALIST_SIDECAR_ARTIFACTS` registry, a `sidecar_artifacts` field
  on `WorkOrder` (auto-populated by `_inject_context`), and a
  multi-file "Required Output" prompt block that lists every required
  file with its role + JSON validity rules. `data_analyst` now emits
  `summary_statistics.json` and `figure_spec.json`;
  `econometrics_specialist` now emits `estimation_results.json`
  (with optional `robustness_results.json`). Two new schema skill
  files (`data/summary-statistics-schema`,
  `econometrics/estimation-results-schema`) teach the JSON shapes and
  the "write `{}` instead of omitting when data was unavailable"
  rule that distinguishes "honest empty" from "missing" for the gate.

## v0.4.5 — 2026-05-19

Bug pack rolling up findings from the v0.4.4 live test (paper eea5379b)
that completed end-to-end on a fresh `pip install e2er`. The pipeline
itself works; these are correctness + clarity fixes around it.

### Lane C — Data

- **Fix nested workspace path on `--save-to`** (Lane C, replication
  correctness). The data_analyst subprocess runs with cwd at the paper's
  workspace dir; `_resolve_workspace` then resolved the relative default
  `workspace_root="workspaces"` against THAT cwd, so the CSV landed at
  `workspaces/<id>/workspaces/<id>/data/`. The model worked around this
  by emitting a `_candidate_csv_paths` fallback in estimation.py — a
  prompt-engineered band-aid for a pipeline bug. Fix: `_resolve_workspace`
  now prefers `$E2ER_WORKSPACE_ROOT` (claude_code injects the absolute
  path) over the relative settings default.
- **Inject absolute workspace_root into the claude_code subprocess env**
  (`E2ER_WORKSPACE_ROOT`) and use an absolute path as the subprocess cwd.
  Without both, the relative `workspaces` string can re-resolve at any
  nested call site.

### Lane A — Pipeline

- **Accept `pipeline_mode` as an alias for `mode`** in `CreatePaperRequest`.
  `e2er run --mode single_pass` reached the API as `pipeline_mode`,
  which Pydantic silently dropped → server fell back to the default
  `"iterative"` → first-run log line falsely reported the wrong mode.
  Also fix `src/cli_run.py` to send the canonical `mode` field.
- **Reword the first-run cap log line.** "override=True" read like the
  server overrode the user's cap; it actually meant the user acknowledged
  the unproven (model, methodology, mode) tuple so the $1 floor was
  lifted to their requested cap. New format spells it out:
  `cap=$20.00 (user_ack_unproven=True, first_run_floor=$1.00)`.

### Cross-lane

- **Label CLI-backend costs as estimates.** Anyone running on
  `claude_code` / `codex_cli` / `gemini_cli` sees Sonnet-rate synthetic
  dollars even though the Max plan absorbs the actual cost. Startup log
  now warns once when a flat-rate backend is selected; the `/api/papers/<id>`
  usage payload carries a `cost_is_estimate` flag so dashboards can
  render the number with the right hedge.
- **`e2er migrate` works on pip-installed wheels.** Old code pointed at
  `scripts/migrate.py` which is excluded from the wheel. Moved to
  `src/db/migrate.py` (importable, ships in the wheel), reads SQL files
  via `importlib.resources("sql")` with a dev-checkout fallback.
- **Drop the stale `_SCRIPTS_DIR` PATH entry on pip installs.** Guarded
  with `.exists()` so the resolved PATH doesn't carry a non-existent
  `site-packages/scripts/` directory that confused `which`-style probes
  inside the claude_code sandbox.

## v0.4.4 — 2026-05-19

Hot-fix over v0.4.3. The PATH-propagation logic added in v0.4.3 used
`Path(sys.executable).resolve().parent` to find the venv bin/ where pip
puts the `e2er-data` entry-point shim. On macOS framework venvs this is
wrong — `bin/python` in the venv is a symlink to the underlying
`Python.framework/Versions/3.12/Resources/Python.app/Contents/MacOS/Python`,
and `.resolve()` follows it, so `.parent` lands in
`.../Python.framework/Versions/3.12/bin/` — which does *not* contain the
venv's entry-point shims. Live test on run `3f921299` confirmed
`e2er-data` was still `command not found` even though the shim existed
at `/tmp/<venv>/bin/e2er-data`.

### Lane C — Data

- **Use `sysconfig.get_path("scripts")`** instead of `Path(sys.executable).resolve().parent`.
  `sysconfig.get_path("scripts")` is the canonical Python API for the
  current-install entry-point dir and returns the venv's own `bin/` on
  Linux, macOS framework venvs, and Windows alike. Verified: on the same
  venv where `.resolve().parent` returned the framework Python's bin,
  `sysconfig.get_path("scripts")` returns the venv's bin and the
  `e2er-data` shim exists there.

## v0.4.3 — 2026-05-19

Hot-fix over v0.4.2. The 0.4.2 wheel boots and the pipeline runs end-to-end,
but the `data_analyst` specialist hits `command not found: e2er-data` and
no data is ever fetched — so papers reach `paper_draft.tex` without any
real data behind them. Trace from run `62526787-da0b-4ebd-8cf9-cf4f3e682a04`
on the v0.4.2 PyPI wheel showed `which e2er-data` → not found inside the
claude_code subprocess, with PATH containing the venv's `site-packages/scripts/`
but not `bin/`. The skill files (`data/yfinance.md`, `data/fred.md`,
`data/allium*.md`) all instruct the model to invoke `e2er-data ...`.

### Lane C — Data

- **Register `e2er-data` as an entry point** in `pyproject.toml [project.scripts]`
  pointing at `src.modules.data.cli:main`. pip now installs a `e2er-data` shim
  next to `e2er` in the venv's `bin/`, so the bash wrapper from the dev
  checkout is no longer required on pip-installed systems.
- **Prepend the venv `bin/` to the subprocess PATH** in `claude_code.py`
  (after the dev `scripts/` dir, before the inherited PATH). Without this
  the entry-point shim is unreachable from the claude_code subprocess
  even after the shim is installed.

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
