# E2ER — turn a research question into a paper

[![Status](https://img.shields.io/badge/status-active%20development-blue)]()
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)]()
[![Tests](https://github.com/bhanneke/E2ER-project/actions/workflows/tests.yml/badge.svg)](https://github.com/bhanneke/E2ER-project/actions/workflows/tests.yml)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.20187238.svg)](https://doi.org/10.5281/zenodo.20187238)
[![PyPI](https://img.shields.io/pypi/v/e2er.svg)](https://pypi.org/project/e2er/)

Hand E2ER a research question; get back a LaTeX paper with citations, an
internal peer-review pass, and a runnable replication package — typically
in ~25 minutes.

```bash
pip install e2er
e2er install-skills
export LLM_BACKEND=claude_code
e2er run "Does X affect Y?" --methodology empirical --max-cost 5
```

That's everything you need to run your first paper. See **[First run](#first-run)** below for what happens next.

---

## Table of contents

- [Install](#install)
- [First run](#first-run)
- [Pick a backend](#pick-a-backend)
- [What you get](#what-you-get)
- [Methodologies](#methodologies)
- [Costs](#costs)
- [Resume a paused paper](#resume-a-paused-paper)
- [Data sources](#data-sources)
- [Literature: bring your own BibTeX](#literature-bring-your-own-bibtex)
- [Going deeper](#going-deeper)
- [Examples](#examples)
- [Troubleshooting](#troubleshooting)
- [Development (contributing)](#development-contributing)
- [Citing · Related work · Contact](#citing)

---

## Install

**Prerequisites:** Python 3.11 or 3.12. That's it — SQLite is auto-created at `~/.e2er/papers.db`, so no database setup is needed for the default flow.

```bash
pip install e2er
e2er install-skills      # bundles the skill files used by the specialists
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
export GITHUB_OWNER=your-user-or-org
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
- A dedicated GitHub repo per paper (if you've set `GITHUB_TOKEN` + `GITHUB_OWNER`), structured for direct Overleaf import.

---

## Pick a backend

E2ER is "bring your own LLM" — choose whichever you already have access to. The CLI backends use your existing subscription, so the marginal cost per paper is **$0**.

| Backend | Setting | Cost per paper | Install |
|---|---|---|---|
| **Claude Code CLI** (Anthropic Max) | `LLM_BACKEND=claude_code` | $0/token | `npm i -g @anthropic-ai/claude-code` |
| **Codex CLI** (ChatGPT Plus/Pro) | `LLM_BACKEND=codex_cli` | $0/token | `npm i -g @openai/codex` |
| **Gemini CLI** (Google AI Pro/Ultra) | `LLM_BACKEND=gemini_cli` | $0/token | `npm i -g @google/gemini-cli` |
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

## Resume a paused paper

Papers pause for two reasons, both recoverable:

- **Budget exhausted** — the per-paper cap was reached.
- **Circuit breaker** — a non-tolerant specialist failed `_MAX_SPECIALIST_ATTEMPTS` times in a row (typically a data-layer outage).

For budget pauses, raise the cap atomically with the resume:

```bash
curl -X POST http://127.0.0.1:8280/api/papers/<paper_id>/resume \
  -H "Content-Type: application/json" \
  -d '{"max_cost_usd": 15}'
```

For circuit-breaker pauses, fix the underlying problem (e.g. restore data-source access) first, then POST with no body to retry. The runner's resume-from-disk logic skips any phase that already produced its canonical artifact, so you don't re-pay for completed work.

The dashboard's "Resume" button does the same thing through the UI.

---

## Data sources

The data module is **optional**. Set `DATA_MODULE_ENABLED=false` to run literature-only papers, or supply your own data files in the workspace's `data/` directory.

Currently wired in:

| Source | Coverage | Setup |
|---|---|---|
| **yfinance** | Equities, ETFs, crypto, FX, indices | No key required |
| **FRED** | US + international macro time series | Free key (~30s registration at <https://fred.stlouisfed.org>) |
| **Allium** | On-chain blockchain data | Bring your own key (`ALLIUM_API_KEY`) |

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

## Literature: bring your own BibTeX

E2ER does **not** automatically retrieve papers from the internet. Supply a `.bib` file of your own curated references:

```bash
export LITERATURE_BIBTEX_FILE=/path/to/refs.bib
```

When set, the pipeline:

1. Parses all entries at startup (requires `bibtexparser` — included in `pip install e2er`).
2. Injects a compact reference list into the prompts of `literature_scanner`, `paper_drafter`, `section_writer`, `abstract_writer`, and `revisor`.
3. Copies the `.bib` file into the workspace so LaTeX can compile with `\bibliography{refs}`.

A typical workflow: export your references from Zotero / Mendeley as `refs.bib`, set the env var, and the drafter uses `\cite{}` commands aligned with your BibTeX keys.

> **Planned:** open-access paper fetching via OpenAlex, Semantic Scholar, and arXiv is implemented in `src/modules/literature/` but not yet wired into the pipeline. Contributions welcome.

---

## Going deeper

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

**Allium API key error / data module crashes** — set `DATA_MODULE_ENABLED=false` in your environment. The pipeline runs literature-only (or with manually uploaded data files) without Allium.

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

If `make smoke` reports `420+ passed`, your install is good and the orchestration works end-to-end. Then:

```bash
make lint           # ruff check + format check
make typecheck      # mypy
make smoke-paid     # ~$0.50 Haiku run end-to-end (requires ANTHROPIC_API_KEY)
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
  version      = {0.5.0},
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
