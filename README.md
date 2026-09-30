# e2er — reusable research infrastructure

[![Status](https://img.shields.io/badge/status-active%20development-blue)]()
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)]()
[![Tests](https://github.com/bhanneke/E2ER-project/actions/workflows/tests.yml/badge.svg)](https://github.com/bhanneke/E2ER-project/actions/workflows/tests.yml)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.20187238.svg)](https://doi.org/10.5281/zenodo.20187238)
[![PyPI](https://img.shields.io/pypi/v/e2er.svg)](https://pypi.org/project/e2er/)

A workbench for building research processes: e2er organises **skills** and
**specialists** into **pipelines** that produce research outputs. Four layers,
each one composable:

```
skills        markdown — what a discipline knows       (58 files)
  ↓
specialists   a role: skills + an output it must write (26 roles)
  ↓
pipelines     an ordered process: steps that dispatch
              specialists or run checks                (a .toml file)
  ↓
gates         deterministic checks. The pipeline is
              yours; these are not.
```

Writing a new research process means writing a pipeline file — steps, which
specialists each runs, which checks fire and whether they halt or merely record.
Not forking the code.

The pipeline that ships takes a research question and your data and returns a
LaTeX paper with citations, an internal peer-review pass, and a runnable
replication package, typically in ~25 minutes. That is **one** pipeline, not the
point of the thing.

What makes it a research instrument rather than a draft generator is that
**every number, citation, and design choice is mechanically verifiable** — and
that a pipeline may add checks and enforce them harder, but never remove them.
Results-table cells are filled by a deterministic renderer from JSON sidecars
(never hand-typed); two gates check the draft before any reviewer runs; every
exported bundle carries a content-addressed provenance manifest; and
`e2er verify` re-establishes — offline, no API keys, in under a minute — that
a finished bundle is internally consistent and untampered. Generation is
nearly free; e2er's aim is to make *verification* cheap too.

```bash
uv tool install --python 3.12 e2er    # installs Python 3.12 and e2er (see Install)
e2er                                  # your browser opens
```

`e2er` alone opens a page in your browser where you choose your AI provider,
your literature (a .bib file, a Zotero export or a folder of PDFs) and your data
folder, start a study, review it at the points where it stops for you, verify it
and publish it. The terminal stays open while you work; nothing else happens
there. `e2er --no-browser` prints the address without opening it.

The terminal commands remain for power users:

```bash
e2er init --defaults                         # scaffold data/ + literature/, write .env
e2er run "<your research question>"          # → a paper in workspaces/<id>/
e2er run "<question>" --template <name>      # follow another template
```

A template fixes the steps a run takes, the checks it must pass and where it
stops for you. Four ship in `pipelines/`:

- `empirical` (default): question and data in, empirical paper out.
- `empirical-preregistered`: the empirical template with the researcher in it;
  a design review, a pre-registration frozen before any estimation, and a
  review of the draft.
- `event-study-finance`: abnormal-return event studies around announcements;
  checks the estimation window, overlapping events and the event dates before
  estimation.
- `replication`: computational reproduction of a published study from its
  Zenodo replication package, run in a Docker sandbox, with every reported
  number compared with the rerun.

When a run pauses for you (a design review, a pre-registration, a failed
check), `e2er review <paper_id>` shows the step and its files; approve, edit a
file, add an instruction, or send a step back with a remark.

`e2er init --defaults` sets up non-interactively (or run `e2er init` for the
guided wizard). New here? The **[For reviewers](#for-reviewers)** tour goes
from a 2-minute browse to reproducing a result, and it opens with a no-key,
$0 step.

### Bring your own data and literature

![Pointing e2er at a folder of data and a folder of references, then running e2er doctor](docs/demo/byod.gif)

Put your datasets in one folder and your references in another, name them in
`.env`, and `e2er doctor` tells you whether a run will actually work before you
start one. Every line in that recording is the program's own output — see
[docs/demo](docs/demo/) for how it is made and re-made.

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
- [Studies, versions and archiving](#studies-versions-and-archiving)
- [Data sources](#data-sources)
- [Literature](#literature)
- [Going deeper](#going-deeper)
- [Examples](#examples)
- [Troubleshooting](#troubleshooting)
- [Development (contributing)](#development-contributing)
- [Citing · Related work · Contact](#citing)

---

## The workflow

e2er is organized around four things a researcher actually does.

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
| `e2er run "…" [--template …] [--governance …] [--review-at …]` | Run the pipeline for one RQ, following a template (default `empirical`) |
| `e2er review <paper_id> [--approve] [--edit …] [--send-back …]` | Act on a paused run: approve, edit a file, add an instruction, send a step back |
| `e2er rerun <paper_id> --from STEP --remark "…"` | Send a finished study back to one of its steps; it and the later steps run again |
| `e2er run-matrix "…" --backends a,b,c` | Same RQ across k backends × n repeats |
| `e2er compare matrix.json` | Diff the design choices across the matrix |
| `e2er export <paper_id>` | Assemble a clean bundle (+ `provenance.json`) |
| `e2er verify <bundle> [--online]` | Offline re-check: hashes, numbers (and p from t), spec, citations; the pre-registration and a reproduction when the bundle has one |

**Going deeper.** [`docs/WORKFLOW.md`](docs/WORKFLOW.md) is the technical
account: the phase sequence, what each of the four gates actually checks, what
the governance regime changes, and — stated plainly rather than left to be
discovered — what the system does *not* establish.
[`docs/diagrams/workflow.md`](docs/diagrams/workflow.md) is the same thing as a
picture, including where a human decides and which gates block in which regime.

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
automated-research systems (RISE) — that situates e2er against the landscape.

---

## Install

The recommended way installs Python for you. e2er needs Python 3.11 or newer
and is tested on 3.11 and 3.12, so the commands pin 3.12.

**Mac and Linux**, in a terminal:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh     # installs uv, a Python installer
uv tool install --python 3.12 e2er                  # downloads Python 3.12 and e2er
uv tool update-shell                                # then open a new terminal window
e2er                                                # your browser opens
```

**Windows**, in PowerShell:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
uv tool install --python 3.12 e2er
uv tool update-shell        # then open a new PowerShell window
e2er
```

e2er's automated tests run on Linux (Ubuntu, Python 3.11 and 3.12), and it is
developed on macOS. Windows is not yet tested.

**Updating:** `uv tool upgrade e2er`.

**If you manage Python yourself** (Python 3.11 or newer), use a virtual
environment. On a Mac, for example:

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install e2er
e2er
```

### AI access

e2er needs one of these. The setup page shows which ones it finds.

- **A Claude subscription, through Claude Code.** Install Claude Code following
  [Anthropic's instructions](https://code.claude.com/docs/en/setup), then run
  `claude` once and sign in in the browser. Claude Code needs a Pro, Max, Team
  or Enterprise plan (or a Console account). Studies then run on your
  subscription with no extra bill.
- **An API key**, billed per use: [Anthropic](https://console.anthropic.com/settings/keys)
  or [OpenRouter](https://openrouter.ai/keys). Paste it on the setup page; every
  study has a spending limit.
- The **Codex CLI** (ChatGPT Plus/Pro, [install](https://github.com/openai/codex))
  and the **Gemini CLI** (Google AI Pro/Ultra, [install](https://github.com/google-gemini/gemini-cli))
  are supported the same way as Claude Code.

**Docker Desktop** ([get it](https://docs.docker.com/get-started/get-docker/)) is
needed only for the replication template, which runs published code inside it.

### Setting up in the terminal instead

SQLite is auto-created at `~/.e2er/papers.db`, so no database setup is needed.

```bash
e2er init                # guided setup: backend pick, prereq check, .env, skills
```

`e2er init` asks a handful of questions, checks that your chosen LLM backend is installed, writes a working `.env` to the current directory (readable by you only), runs `skills sync`, and prints example research questions you can copy. It accepts paths the way you paste or drag them: with quotes, with the terminal prompt in front, or a folder where a .bib is asked for. Re-run it any time to reconfigure (`--force` overwrites without prompting). The setup page in the browser writes the same `.env`.

If you'd rather do it by hand:

```bash
e2er skills sync         # makes the specialists' skill files visible to your CLI backend
export LLM_BACKEND=claude_code   # or anthropic / openrouter / codex / gemini
```

`e2er doctor` checks the setup without spending any tokens.

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

e2er is "bring your own LLM" — choose whichever you already have access to. The CLI backends use your existing subscription, so the marginal cost per paper is **$0**.

| Backend | Setting | Cost per paper | Install |
|---|---|---|---|
| **Claude Code CLI** (Claude subscription) | `LLM_BACKEND=claude_code` | $0/token | [Anthropic's instructions](https://code.claude.com/docs/en/setup) |
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
e2er cancel <paper_id>                       # stop a running paper, or end a paused one (confirms first)
e2er cancel <paper_id> --yes                 # skip the confirmation
e2er resume <paper_id>                       # restart a paused / failed paper
e2er resume <paper_id> --max-cost 15         # raise the cap while resuming
e2er resume <paper_id> --max-cost 15 --tail  # raise cap + watch to terminal
```

`status` shows the current phase, cost meter, last error if any, and the workspace + dashboard URLs. `cancel` preserves the workspace + completed-phase artifacts so the run is resumable. `resume` works for budget-paused papers (use `--max-cost` to give it more budget), circuit-breaker pauses (POST with no extra cap; fix the underlying issue first), and zombie revision/in_progress rows left behind by a server restart. The resume-from-disk logic skips any phase that already produced its canonical artifact, so completed work isn't re-paid.

The dashboard's "Resume" button does the same thing through the UI.

Two e2er servers can share one database (say a study server on 8280 and the everyday dashboard on 8300). Each run records which server process owns it, and a server that starts up pauses only the runs whose owner has stopped. A run that another live server owns shows as "Running in another e2er process" with its PID and port, and has no Resume or Cancel button here.

---

## Studies, versions and archiving

Running the same question again gives a new attempt, not a new study. The dashboard and `e2er list` show one row per study, where a study is every attempt with the same research question (ignoring spacing, case and trailing punctuation) and the same template. The attempts are numbered v1, v2, … by start time, and the study takes the title of its latest attempt. On a study's page, "Move to study…" puts an attempt into another study or splits it off into one of its own.

Archiving hides attempts from the lists. It never deletes a record, a file or a workspace, and it refuses attempts that are running or paused. A paused attempt you have given up on (stopped by the budget, or waiting at a researcher step) can be ended with "Cancel attempt" on its page or `e2er cancel <paper_id>`: it becomes cancelled, the cancellation is recorded as a researcher step in the dossier, its files stay, and it can then be archived. An attempt that another running e2er owns is refused.

```bash
e2er list                      # one entry per study
e2er list --attempts           # with each study's attempts
e2er list --archived           # including archived attempts
e2er archive <paper_id>        # one attempt (the first 8 characters of the id are enough)
e2er archive --study <key|id>  # every attempt of a study
e2er archive --failed          # shows the failed and cancelled attempts it would archive
e2er archive --failed --yes    # archives them
e2er unarchive <paper_id>      # brings one back (or --study <key|id>)
```

In the dashboard, "Archive failed and cancelled attempts" shows the count and the list before anything happens, and "Show archived (n)" brings archived attempts back into view with an Unarchive button.

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

### A corpus of what papers claim

A search tells you a paper exists. It does not tell you what the paper found, so
a drafter handed thirty BibTeX entries can only cite plausibly.

`e2er corpus` builds a local library of *claims* instead — each one stored with
the verbatim sentence it came from, checked against the paper's full text. A
claim whose quote cannot be located is discarded rather than flagged, which is
the numbers gate applied one level up: a table cell must trace to a sidecar key,
a claim must trace to a sentence.

```bash
e2er corpus add ~/papers/                   # every PDF in a folder
e2er corpus add "10.1257/aer.20201397"      # one paper by DOI
e2er corpus topics add "stablecoin runs"    # a standing interest
e2er corpus refresh                         # re-run topics, extract only what's new
e2er corpus search "null effects of listing"
```

A paper run also reads its own `literature/` folder — the PDFs staged from
`LITERATURE_DIR` or Zotero — into the corpus before drafting, so your own papers
need no separate command (`CORPUS_AUTOINGEST=false` to disable).

It lives at `~/.e2er/corpus.db` (`CORPUS_DB` to move it), outside any workspace,
and accumulates across projects — `refresh` skips what it already has before
downloading or calling a model, so running it on a schedule is cheap. When a
paper run starts, matching claims are written to `literature/corpus_evidence.md`
and reach the drafter, and the papers seed `literature.bib`. With no corpus,
nothing changes.

`e2er corpus stats` also reports how often the model supplied a quote that was
not in the paper — see [docs/CORPUS.md](docs/CORPUS.md) and the format spec in
[docs/STRUCTURED_REVIEWS.md](docs/STRUCTURED_REVIEWS.md).

---

## Going deeper

### How it works

![How e2er works — phases, specialists, and JSON artifact contracts](docs/figures/pipeline.svg)

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

**`pip install e2er` errors with `ImportError: cannot import name 'UTC' from 'datetime'`** — your local Python is < 3.11. e2er requires 3.11+. Use `pyenv install 3.11` or `brew install python@3.12`.

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

The automated research space is developing quickly. Two projects most relevant to e2er:

- **[Project APE](https://ape.socialcatalystlab.org/)** (Social Catalyst Lab, University of Zurich) — AI agents identifying policy questions with credible causal identification strategies, running econometric analysis, and producing complete papers. ~1,000 papers generated; now in systematic evaluation against peer-reviewed journals. Closest in spirit to e2er.
- **[ZeroPaper](https://github.com/alejandroll10/zeropaper)** (Institute for Automated Research) — ~30 specialised agents across 10 stages, focused on theory-first finance and macroeconomics. e2er adopts four quality-control ideas from ZeroPaper (ceiling detection, self-attack, parallel polish, mechanical aggregation).

### Roadmap highlights

- **More data sources**: WRDS, OpenBB, Census, BLS, ECB, World Bank, Dune, Flipside — the data module is designed to be extended. See [`docs/iv_database.md`](docs/iv_database.md) for the natural-experiments catalogue.
- **Evaluation framework**: [`docs/evaluation_framework.md`](docs/evaluation_framework.md) — six scored dimensions (identification, execution, writing, literature, replication, novelty) plus automated metrics.
- **Testers wanted**: if you're working on an empirical question in IS, economics, finance, or adjacent fields and want to run the pipeline on your own data, contact <hanneke@wiwi.uni-frankfurt.de>.

---

## Citing

```bibtex
@software{hanneke2026e2er,
  author       = {Hanneke, Bj{\"o}rn},
  title        = {{e2er: End-to-End Researcher, An Open-Source Pipeline
                   for Automated Empirical Research}},
  year         = {2026},
  version      = {0.12.1},
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
