# E2ER — turn a research question into a paper

[![Status](https://img.shields.io/badge/status-active%20development-blue)]()
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)]()
[![Tests](https://github.com/bhanneke/E2ER-project/actions/workflows/tests.yml/badge.svg)](https://github.com/bhanneke/E2ER-project/actions/workflows/tests.yml)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.20187238.svg)](https://doi.org/10.5281/zenodo.20187238)
[![PyPI](https://img.shields.io/pypi/v/e2er.svg)](https://pypi.org/project/e2er/)

E2ER is an open-source, end-to-end pipeline for empirical research. You bring
your own data and your own papers, pose a research question, and steer a
human-in-the-loop workflow that returns a LaTeX paper with citations, an
internal peer-review pass, and a runnable replication package — typically in
~25 minutes.

What makes it a research instrument rather than a draft generator is that
**every number, citation, and design choice is mechanically verifiable.**
Results-table cells are filled by a deterministic renderer from JSON sidecars
(never hand-typed); two gates check the draft before any reviewer runs; every
exported bundle carries a content-addressed provenance manifest; and
`e2er verify` re-establishes — offline, no API keys, in under a minute — that
a finished bundle is internally consistent and untampered. Generation is
nearly free; E2ER's aim is to make *verification* cheap too.

```bash
pip install e2er
e2er init --defaults                         # scaffold data/ + literature/, write .env
e2er run "<your research question>"          # → a paper in workspaces/<id>/
```

`e2er init --defaults` sets up non-interactively (or run `e2er init` for the
guided wizard). New here? The **[For reviewers](#for-reviewers)** tour goes
from a 2-minute browse to reproducing a result, and it opens with a no-key,
$0 step.

---

## Table of contents

- [The workflow](#the-workflow)
- [For reviewers](#for-reviewers)
- [Install](#install)
- [First run](#first-run)
- [Pick a backend](#pick-a-backend)
- [What you get](#what-you-get)
- [Methodologies](#methodologies)
- [Costs](#costs)
- [Check, tail, cancel, resume](#check-tail-cancel-resume)
- [Data sources](#data-sources)
- [Literature](#literature)
- [Going deeper](#going-deeper)
- [Examples](#examples)
- [Troubleshooting](#troubleshooting)
- [Development (contributing)](#development-contributing)
- [Citing · Related work · Contact](#citing)

---

## The workflow

E2ER is organized around four things a researcher actually does.

**1 · Bring your own data and your own papers.** Drop datasets in `data/`
(`.csv`, `.parquet`, `.xlsx`, …) and reference PDFs — or a Zotero library — in
`literature/`. `e2er init` scaffolds both; `e2er doctor` reports what it found
and which literature mode is active. Your PDFs never leave your machine:
exported bundles ship only the BibTeX corpus, never the source PDFs. See
[Data sources](#data-sources) and [Literature](#literature).

**2 · Sharpen the research question.** `e2er rq --draft "<rough question>"`
reads your data catalogue and local library and returns a precise, feasible
research question with candidate variables, identification options, and
feasibility notes. It only advises — it never starts a run. You decide, then:

**3 · Run a human-in-the-loop workflow.** `e2er run "<RQ>"` runs the pipeline.
Add `--review-at <stage>` to pause at chosen phases for inspection and
`e2er resume` to continue. Run the same question across models —
`e2er run-matrix "<RQ>" --backends claude_code,codex,gemini --repeats 3` — and
then `e2er compare matrix.json` diffs the machine-readable design choices each
model made (estimator, fixed effects, controls, clustering, the coefficient of
interest). This is coverage of the solution space, **not** selection: no run is
promoted, and any decision to carry one forward must be pre-committed.

**4 · Everything is verifiable.** Every run writes deterministic gate reports;
every export bundle carries a content-addressed `provenance.json` (SHA-256 of
every file plus the derivation graph). `e2er verify <bundle>` re-establishes
offline that the bundle is internally consistent and untampered. The governance
regime is a first-class knob — `e2er run --governance off|contracts|full`
selects which gates *block*; in `off`/`contracts` the deterministic gates still
run in **shadow** (compute + log, don't block), so what they would have caught
is measured rather than hidden.

| Command | What it does |
|---|---|
| `e2er init [--defaults]` | Scaffold `data/` + `literature/`, write `.env`, bundle skills |
| `e2er doctor` | Preflight: backend, DB, and your bring-your-own data + literature |
| `e2er rq --draft "…"` | Sharpen a draft RQ against your data + library (advisory) |
| `e2er run "…" [--governance …] [--review-at …]` | Run the pipeline for one RQ |
| `e2er run-matrix "…" --backends a,b,c` | Same RQ across k backends × n repeats |
| `e2er compare matrix.json` | Diff the design choices across the matrix |
| `e2er export <paper_id>` | Assemble a clean bundle (+ `provenance.json`) |
| `e2er verify <bundle> [--online]` | Offline re-check: hashes, numbers, spec, citations |

---

## For reviewers

A short tour, from a 2-minute browse to reproducing a governance result. It
opens with a step that needs no API keys and costs nothing.

**T0 — 2 minutes, in the browser.** Skim [What you get](#what-you-get) and the
[Examples](#examples): real artifacts from real runs, including the gate
reports — the rejected fabricated citations, a spec-contract violation coached
to compliance, a phase-gate halt. The claim to check is that the numbers,
citations, and design choices are all traceable to machine-readable sources.

**T1 — 10 minutes, no keys, $0.** `e2er verify <bundle>` re-establishes a
bundle's integrity **offline**: it re-hashes every file against
`provenance.json`, re-traces each results-table cell to its source JSON,
re-checks the identification contract, and confirms every `\cite` resolves in
the bibliography (`--online` re-queries the live registries). Recomputation is
authoritative, so an edited number or a deleted reference is caught. A curated,
ready-to-verify showcase bundle (`examples/showcase/`) ships from the next
tagged release; until then, verify any bundle you produce with `e2er export`.

**T2 — under an hour, $0 with a CLI subscription.** `e2er init --defaults` →
drop your own CSVs into `data/` and PDFs into `literature/` → `e2er doctor` →
`e2er run "<your RQ>"` on one of the flat-rate CLI backends. Pinned model,
public data, stated runtime.

**T3 — the governance experiment.** `e2er run --governance off|contracts|full`
reproduces a single study cell; under `off` the gates run in shadow, so you can
watch fabrication happen **and** see it measured. `scripts/experiment_driver.py`
runs the full RQ × regime × N grid and writes `results.csv` + `summary.md` with
the per-regime fabrication means — turning the governance switch into a measured
comparison of fabrication and variance across regimes.

The submission also ships a companion artifact — a catalogue of
automated-research systems (RISE) — that situates E2ER against the landscape.

---

## Install

**Prerequisites:** Python 3.11 or 3.12. That's it — SQLite is auto-created at `~/.e2er/papers.db`, so no database setup is needed for the default flow.

```bash
pip install e2er
e2er init                # guided setup: backend pick, prereq check, .env, skills
```

`e2er init` is the recommended path — it asks you a handful of questions, checks that your chosen LLM backend is installed, writes a working `.env` to the current directory, runs `install-skills`, and prints example research questions you can copy. Re-run it any time to reconfigure (`--force` overwrites without prompting).

If you'd rather do it by hand:

```bash
pip install e2er
e2er install-skills      # bundles the skill files used by the specialists
export LLM_BACKEND=claude_code   # or anthropic / openrouter / codex / gemini
```

To verify your install without spending any tokens:

```bash
e2er run --help          # CLI is wired
```

That's all you need to run a paper. The rest of this section covers optional setup.

**Optional — Postgres + pgvector** (for production, multi-user, or the literature KB):

```bash
export DATABASE_URL=postgresql://user:pass@host:5432/e2er
e2er migrate              # runs the schema migrations
```

**Optional — GitHub integration** (push each paper's LaTeX + replication package to its own repo):

```bash
export GITHUB_TOKEN=ghp_...     # token with `repo` scope
export GITHUB_USERNAME=your-user-or-org
```

---

## First run

```bash
export LLM_BACKEND=claude_code   # see "Pick a backend" below
e2er run "Does liquidity concentration in Uniswap v3 affect price discovery?" \
   --methodology empirical \
   --max-cost 5
```

What happens:

1. `e2er run` starts a local API server (uvicorn on `:8280`) if one isn't already running.
2. It submits the paper to `POST /api/papers` and gets back a `paper_id` + workspace path.
3. It tails the run to your terminal. Press `^C` at any time — the run keeps going in the background; re-attach via the dashboard.
4. When the pipeline finishes, you'll see a summary line with the paper's terminal status (`completed` / `rejected` / `paused`).

Open the dashboard at <http://127.0.0.1:8280> to see all papers, drill into per-specialist artifacts, watch the live cost meter, and download the audit bundle.

Files for a paper land in two places:

- `workspaces/<paper_id>/` on your filesystem — every artifact, every reviewer report, the replication package.
- A dedicated GitHub repo per paper (if you've set `GITHUB_TOKEN` + `GITHUB_USERNAME`), structured for direct Overleaf import.

---

## Pick a backend

E2ER is "bring your own LLM" — choose whichever you already have access to. The CLI backends use your existing subscription, so the marginal cost per paper is **$0**.

| Backend | Setting | Cost per paper | Install |
|---|---|---|---|
| **Claude Code CLI** (Anthropic Max) | `LLM_BACKEND=claude_code` | $0/token | `npm i -g @anthropic-ai/claude-code` |
| **Codex CLI** (ChatGPT Plus/Pro) | `LLM_BACKEND=codex` | $0/token | `npm i -g @openai/codex` |
| **Gemini CLI** (Google AI Pro/Ultra) | `LLM_BACKEND=gemini` | $0/token | `npm i -g @google/gemini-cli` |
| Anthropic SDK | `LLM_BACKEND=anthropic` | per-token | `export ANTHROPIC_API_KEY=...` |
| OpenRouter | `LLM_BACKEND=openrouter` | per-token | `export OPENROUTER_API_KEY=...` (200+ models) |

> **First-run guardrail:** the first paper at any (model, methodology, mode) combination is capped at **$1.00** until one has completed successfully — protects against a runaway tool-use loop on a model that hasn't been validated yet. Pass `--acknowledge-unproven` to lift the floor and use the full `--max-cost` you provided.

---

## What you get

Every paper produces this artifact set in `workspaces/<paper_id>/`:

| File | Description |
|---|---|
| `paper_plan.md` | Research design, propositions, identification strategy |
| `literature_review.md` | Related-work synthesis with citations |
| `identification_strategy.md` | Causal identification argument and threats |
| `econometric_spec.md` | Econometric specification with equations |
| `data_dictionary.json` | Pre-specified data footprint (fields, time filter, granularity) |
| `data_summary.md` | Data acquisition narrative |
| `summary_statistics.json` | Machine-readable descriptive stats — consumed by `verify_numbers` and the drafter |
| `estimation_results.json` | Machine-readable point estimates, SEs, t-stats, p-values |
| `figure_spec.json` | Numeric values for every figure |
| `paper_draft.tex` | Full LaTeX manuscript |
| `abstract.tex` | Standalone abstract |
| `self_attack_report.json` | Adversarial flaw-finding report with severity scores |
| `review_*.md` | Structured reviews from 6 specialist reviewers |
| `review_aggregation.json` | Mechanical aggregation verdict (`ACCEPT` / `MINOR_REVISION` / `MAJOR_REVISION` / `HARD_REJECT`) |
| `number_verification.json` | Anti-hallucination gate report — every table number checked against the JSON sidecars |
| `replication/estimation.py` | Main econometric estimation code |
| `replication/data_queries.sql` | All data queries used in the paper |
| `replication/audit_log.csv` | Complete data-access audit trail |

Run `e2er export <paper_id>` to assemble these into a clean, navigable bundle
(`paper/ code/ data/ results/ design/ reviews/ replication/`) with a
content-addressed **`provenance.json`** manifest — a SHA-256 inventory of every
file plus the derivation graph tying each table cell to its source JSON key and
each citation to its registry record. `e2er verify <bundle>` re-checks that
bundle offline (see [For reviewers](#for-reviewers)). The gate reports
themselves — `number_verification.json` (every table number vs. the JSON
sidecars) and `citation_integrity.json` (every `\cite` vs. OpenAlex / Semantic
Scholar / Crossref) — ship in the bundle too.

If `GITHUB_TOKEN` is set, all of the above are also pushed to a dedicated paper repo with an Overleaf-compatible layout.

---

## Methodologies

Pick one per paper via `--methodology`:

- **`empirical`** *(default)* — data-driven; runs identification, data, and econometrics specialists.
- **`theoretical`** — formal model + propositions; skips data and replication phases (and the data reviewer).
- **`mixed`** — formal model AND empirical test.

Most users want `empirical`. `theoretical` is for pure-model papers (no data, just propositions and proofs); the pipeline costs ~30% less because the data specialists and replication packager are skipped.

---

## Costs

| Mode | Model | Typical cost | Notes |
|---|---|---|---|
| `single_pass` | Haiku 4.5 | **~$0.50** | Fast draft. What `make smoke-paid` uses. |
| `single_pass` | Sonnet 4.6 | **$3 – $8** | Better depth, one pass through the pipeline. |
| `iterative` | Sonnet 4.6 | **$15 – $25** | Full loop: ceiling check → self-attack → polish → review → revision. Hard-capped at `--max-cost` (default $25). |
| any | Claude Code / Codex / Gemini CLI | **$0** | Flat-rate subscription absorbs the cost. The dollar meter is a synthetic estimate at Sonnet rates and still drives the budget gate. |

**Budget safety.** Every paper has a hard cap (`--max-cost`, default $25). The pipeline checks cumulative cost at every phase boundary; when the cap is reached the run transitions to `paused` (resumable — see below) rather than crashing.

---

## Check, tail, cancel, resume

After `e2er run` you have four lightweight CLI commands for managing the paper from the terminal:

```bash
e2er status <paper_id>                       # one-shot snapshot
e2er status <paper_id> --tail                # re-attach the live tailer
e2er cancel <paper_id>                       # stop a running paper (confirms first)
e2er cancel <paper_id> --yes                 # skip the confirmation
e2er resume <paper_id>                       # restart a paused / failed paper
e2er resume <paper_id> --max-cost 15         # raise the cap while resuming
e2er resume <paper_id> --max-cost 15 --tail  # raise cap + watch to terminal
```

`status` shows the current phase, cost meter, last error if any, and the workspace + dashboard URLs. `cancel` preserves the workspace + completed-phase artifacts so the run is resumable. `resume` works for budget-paused papers (use `--max-cost` to give it more budget), circuit-breaker pauses (POST with no extra cap; fix the underlying issue first), and zombie revision/in_progress rows left behind by a server restart. The resume-from-disk logic skips any phase that already produced its canonical artifact, so completed work isn't re-paid.

The dashboard's "Resume" button does the same thing through the UI.

---

## Data sources

**Bring your own data.** `e2er init` scaffolds a `data/` folder (pointed at by
`LOCAL_DATA_DIR`); drop `.csv` / `.tsv` / `.jsonl` / `.parquet` / `.xlsx` /
`.txt` files there and they are staged into each run's workspace, imported into
a per-paper SQLite warehouse, and queryable by the specialists.
`e2er doctor` reports the datasets it found.

On top of that, specialists **discover** built-in data sources in light of the
research question: they call `list_data_sources` to see what's available and
what each is for, then pull series data with a unified `fetch_data` tool (or
`query_allium` for on-chain data). To run literature-only papers, just leave the
data keys unset.

| Source | Coverage | Setup | In-loop tool |
|---|---|---|---|
| **yfinance** | Equities, ETFs, crypto, FX, indices | No key required (always on) | `fetch_data` |
| **FRED** | US + international macro time series | Free key (`FRED_API_KEY`, ~30s at <https://fred.stlouisfed.org>) | `fetch_data` |
| **Allium** | On-chain blockchain data (requires query credits) | Bring your own key (`ALLIUM_API_KEY`) | `query_allium` (guarded) |

### Allium guardrails (when enabled)

Every Allium query passes through 5 guardrails before execution:

1. No `SELECT *` — all fields must be listed explicitly.
2. All requested fields must be declared in the paper's `data_dictionary.json`.
3. A time-bound `WHERE` clause is required on every query.
4. Transaction-level granularity requires written justification.
5. Production queries require a prior approved feasibility run on the same table.

Two-phase workflow: **feasibility** queries (1000-row sample) are auto-approved; **production** queries are queued for researcher approval at `GET /api/papers/{id}/pending-queries`.

We gratefully acknowledge **[Allium](https://allium.so)** for supporting this research through data access and technical collaboration.

---

## Literature

**Bring your own papers.** `e2er init` scaffolds a `literature/` folder
(`LITERATURE_DIR`). Point it at a folder of reference PDFs, a Zotero library (a
folder with a `zotero.sqlite`), or a single `.bib` file — three modes, pick
whichever you have. `e2er doctor` reports which mode is active and how many
papers it found. Your PDFs stay on your machine; exported bundles carry only the
`.bib` corpus. Full text also resolves open-access by DOI at run time.

Two complementary paths in detail: **your own references**, and **open-access discovery + full text**.

### Your reference library

Bring references from any of these — all optional, merged and de-duplicated by (title, year):

```bash
export LITERATURE_BIBTEX_FILE=/path/to/refs.bib   # a single .bib file
export LOCAL_DATA_DIR=/path/to/corpus             # any *.bib in this folder (+ data files)
export ZOTERO_API_KEY=...                          # your live Zotero library
export ZOTERO_USER_ID=1234567                      # (or ZOTERO_GROUP_ID for a group library)
```

A compact reference list is injected into the prompts of the bibliography-relevant
specialists (`literature_scanner`, `paper_drafter`, `section_writer`, `abstract_writer`, `revisor`),
and any `.bib` is copied into the workspace so LaTeX compiles with `\bibliography{refs}`.

### Discovery and full text (open access)

The pipeline **does** reach the internet for literature, through guarded tools:

- **`search_papers`** / **`fetch_paper`** — search and fetch metadata via OpenAlex
  (free, no key), with arXiv and Semantic Scholar fallbacks.
- **`read_reference`** — download a paper's PDF and extract its text (via `pypdf`)
  so specialists can read what a paper actually says, not just its abstract. Takes a
  `pdf_url` (from a search result or a `[PDF]`-marked reference) or a `doi` (resolves
  an open-access PDF). Tightly budgeted to protect the token budget.

> **Zotero PDFs:** `read_reference` can fetch a Zotero attachment only if the file is
> in Zotero's cloud file storage (the Web API can't serve locally-stored / WebDAV /
> over-quota files). When it isn't, use open-access resolution by DOI instead.

---

## Going deeper

### How it works

![How E2ER works — phases, specialists, and JSON artifact contracts](docs/figures/pipeline.svg)

The figure shows the seven pipeline phases left-to-right
(`initial → iterative → self_attack → polish → review → revision → replication`),
the specialists in each phase, and — the key part — the **JSON artifact
contracts** flowing from the specialist that produces them
(`econometrics_specialist → estimation_results.json`,
`paper_drafter → table_spec.json`, …). Results-table numbers are filled by a
**deterministic renderer** from those JSON files (per `table_spec.json`), so they
can't be fabricated; the two assurance gates that run before any reviewer —
`verify_numbers` and `verify_citations` — then check the draft.

This figure is **generated from the source of truth**, not hand-drawn:
[`scripts/gen_pipeline_figure.py`](scripts/gen_pipeline_figure.py) reads the real
specialist roster and artifact contracts from
[`src/core/specialists/registry.py`](src/core/specialists/registry.py), so it can
never drift from the code — rename a specialist or a sidecar and the figure (and
its test) follow automatically. Regenerate with:

```bash
python scripts/gen_pipeline_figure.py   # writes docs/figures/pipeline.{dot,svg,pdf}
# needs Graphviz for SVG/PDF:  brew install graphviz   (the .dot is always written)
```

For a high-level mental model before diving into the code:

- **[Pipeline overview](docs/diagrams/pipeline_overview.md)** — full flow from idea to completion (mermaid diagram).
- **[Specialist DAG](docs/diagrams/specialist_dag.md)** — execution dependencies and parallel groups.
- **[Review aggregation](docs/diagrams/review_aggregation.md)** — the 3 mechanical rules that turn 6 reviewer scores into a verdict.
- **[Interactive architecture diagram](docs/architecture.html)** — open in a browser.

### Pipeline phases

```
[Researcher input: RQ + optional BibTeX + optional data]
          |
          v
    1. Study Design      idea_developer, literature_scanner, identification_strategist
    2. Data              data_architect → data_analyst → summary_statistics.json
    3. Estimation        econometrics_specialist → estimation_results.json
    4. Writing           paper_drafter, abstract_writer, latex_formatter
          |
          v  (iterative mode only)
    5. Ceiling Check     Strategist assesses whether further iteration adds value
    6. Self-Attack       Adversarial specialist finds critical flaws (severity 1-10)
    7. Polish            5 parallel specialists: formula, numerics, institutions, bibliography, equilibria
          |
          v
    8. verify_numbers    Programmatic gate: every table number must match a JSON sidecar
    9. Review            6 parallel reviewers (5 for theoretical): mechanism, technical,
                         identification, literature, data, writing
   10. Aggregation       3-rule mechanical verdict
   11. Revision          Revisor specialist addresses feedback (if MAJOR_REVISION)
   12. Replication       Packages all queries, code, and audit trail
   13. GitHub Push       LaTeX + replication package committed to paper repo
```

### Review aggregation rules

Applied in order; first match wins:

| Rule | Condition | Verdict |
|---|---|---|
| 1 | Mechanism reviewer score < 5 | `MECHANISM_FAIL` — fundamental revision required |
| 2 | Any reviewer score < 4 | `HARD_REJECT` — floor violation |
| 3 | Weighted average (technical ×1.5, identification ×1.5, data ×1.25) | `ACCEPT` / `MINOR_REVISION` / `MAJOR_REVISION` / `HARD_REJECT` |

---

## Examples

The repo ships with worked examples — real artifacts from real runs:

- [`examples/e2er_v3_haiku_smoke/`](examples/e2er_v3_haiku_smoke/) — single-pass v3 run on Haiku 4.5 (~$1.50, ~11 min), data module disabled. Pipeline plumbing only — not findings.
- [`examples/starter_theoretical/`](examples/starter_theoretical/) — minimal theoretical paper template you can copy as a starting point.
- [`examples/e2er_v1_nft_seasonality/`](examples/e2er_v1_nft_seasonality/) — full v1 paper (PDF + LaTeX + replication) testing whether the Halloween effect extends to NFT markets. Null result; 35.8M Ethereum NFT trades.
- [`examples/e2er_v1_bitcoin_institutionalization/`](examples/e2er_v1_bitcoin_institutionalization/) — full v1 paper on Bitcoin volatility convergence around the January 2024 ETF approval. GARCH + Markov-switching + DiD + Rambachan-Roth.

> These results have not been submitted to a journal and should not be cited as peer-reviewed findings.

<p align="center">
  <img src="examples/e2er_v1_nft_seasonality/figures/fig1_monthly_returns.png" alt="Monthly NFT Returns" width="600">
</p>
<p align="center"><em>Monthly return distribution by platform — pipeline-generated, from the NFT seasonality example</em></p>

---

## Troubleshooting

**`e2er: command not found`** — `pip install e2er` succeeded but the script directory isn't on your PATH. Try `python -m e2er run "..."` instead, or add your `~/.local/bin` (or venv `bin/`) to PATH.

**`pip install e2er` errors with `ImportError: cannot import name 'UTC' from 'datetime'`** — your local Python is < 3.11. E2ER requires 3.11+. Use `pyenv install 3.11` or `brew install python@3.12`.

**Paper stuck in `in_progress` forever** — check `workspaces/<paper_id>/.pipeline_state.json` for the last completed phase and `~/.e2er/uvicorn.log` for errors. Restart uvicorn and hit `/resume` — the runner reads state.json and skips completed phases.

**Paper paused with `BudgetExceededError`** — raise the cap and resume: `curl -X POST http://127.0.0.1:8280/api/papers/<id>/resume -d '{"max_cost_usd": 15}' -H "Content-Type: application/json"`.

**Paper rejected with `verify_numbers: N critical mismatches`** — the drafter cited table numbers that don't match the JSON sidecars. Open `number_verification.json` for the specific mismatches. Either revise the source artifacts (`summary_statistics.json` etc.) to match the draft, or revise the draft to match the sources, then resume.

**Allium API key error / out of credits** — leave `ALLIUM_API_KEY` unset to run without on-chain data; the pipeline runs literature-only (or with FRED/yfinance series, and manually uploaded data files). yfinance and FRED are unaffected by Allium. (Note: `data_module_enabled` is a computed property, not a settable env var — there's no `DATA_MODULE_ENABLED` toggle; presence of the key is what matters.)

**OpenRouter `402 Payment Required`** — your OpenRouter balance is zero. Top up at <https://openrouter.ai/credits>. The pipeline correctly bails rather than looping.

**`Authorization` header missing on JSON POSTs** — you set `API_AUTH_TOKEN` but didn't include `-H "Authorization: Bearer <token>"` on the request. The HTML dashboard form is exempt.

---

## Development (contributing)

For local development on the repo itself (rather than `pip install e2er`):

```bash
git clone https://github.com/bhanneke/E2ER-project.git
cd E2ER-project
pip install -e ".[dev]"
make smoke          # full mocked test suite — ~15s, no API key needed
```

If `make smoke` reports `680+ passed`, your install is good and the orchestration works end-to-end. Then:

```bash
make lint                      # ruff check + format check
make typecheck                 # mypy
python scripts/live_check.py   # live provider smoke (real APIs, no LLM/cost; skips unconfigured)
make smoke-paid                # ~$0.50 Haiku run end-to-end (requires ANTHROPIC_API_KEY)
```

**Docker path (postgres + dashboard in one command):**

```bash
./scripts/quickstart.sh    # prompts for ANTHROPIC_API_KEY, runs `docker compose up --build`
```

See [`AGENTS.md`](AGENTS.md) for the branch model, lane structure, and contribution conventions. See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the PR process, and [`skills/CONTRIBUTING_SKILLS.md`](skills/CONTRIBUTING_SKILLS.md) for the skill-file pattern (the lowest-friction way to contribute — markdown only, no code changes).

### Related projects

The automated research space is developing quickly. Two projects most relevant to E2ER:

- **[Project APE](https://ape.socialcatalystlab.org/)** (Social Catalyst Lab, University of Zurich) — AI agents identifying policy questions with credible causal identification strategies, running econometric analysis, and producing complete papers. ~1,000 papers generated; now in systematic evaluation against peer-reviewed journals. Closest in spirit to E2ER.
- **[ZeroPaper](https://github.com/alejandroll10/zeropaper)** (Institute for Automated Research) — ~30 specialised agents across 10 stages, focused on theory-first finance and macroeconomics. E2ER adopts four quality-control ideas from ZeroPaper (ceiling detection, self-attack, parallel polish, mechanical aggregation).

### Roadmap highlights

- **More data sources**: WRDS, OpenBB, Census, BLS, ECB, World Bank, Dune, Flipside — the data module is designed to be extended. See [`docs/iv_database.md`](docs/iv_database.md) for the natural-experiments catalogue.
- **Evaluation framework**: [`docs/evaluation_framework.md`](docs/evaluation_framework.md) — six scored dimensions (identification, execution, writing, literature, replication, novelty) plus automated metrics.
- **Testers wanted**: if you're working on an empirical question in IS, economics, finance, or adjacent fields and want to run the pipeline on your own data, contact <hanneke@wiwi.uni-frankfurt.de>.

---

## Citing

```bibtex
@software{hanneke2026e2er,
  author       = {Hanneke, Bj{\"o}rn},
  title        = {{E2ER: End-to-End Researcher, An Open-Source Pipeline
                   for Automated Empirical Research}},
  year         = {2026},
  version      = {0.8.0},
  url          = {https://github.com/bhanneke/E2ER-project},
  doi          = {10.5281/zenodo.20187238},
  license      = {MIT},
  institution  = {Goethe University Frankfurt},
}
```

Cite the concept DOI `10.5281/zenodo.20187238` to credit any version (resolves to the latest release), or [browse all versions on Zenodo](https://zenodo.org/records/20187238) to pin a specific snapshot. A companion paper describing the system architecture is in preparation.

---

## Contact

**Björn Hanneke** · [bjornhanneke.com](https://www.bjornhanneke.com) · <hanneke@wiwi.uni-frankfurt.de>

PhD Candidate, Goethe University Frankfurt — Chair of Information Systems and Information Management (Prof. Dr. Oliver Hinz).

[ORCID](https://orcid.org/0009-0000-7466-9581) · [Google Scholar](https://scholar.google.com/citations?user=N5fbuZIAAAAJ) · [LinkedIn](https://linkedin.com/in/bhanneke)

---

*MIT License: see [LICENSE](LICENSE).*
