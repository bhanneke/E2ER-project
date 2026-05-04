# E2ER v3 — End-to-End Researcher

[![Status](https://img.shields.io/badge/status-active%20development-blue)]()
[![License](https://img.shields.io/badge/license-MIT-green)]()
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)]()
[![Tests](https://img.shields.io/badge/tests-passing-brightgreen)]()

**E2ER** is an open-source pipeline for producing peer-review-quality empirical research papers in information systems, economics, and finance. The researcher provides a research question and data access; the pipeline handles the rest — study design, data acquisition, econometric estimation, writing, review, and replication packaging.

> **Scope**: E2ER is optimised for empirical papers. It works best with structured data, a clear identification strategy, and established econometric methods. It is not designed for purely theoretical work.

---

## What the system produces

For each paper, E2ER produces:

| Artifact | Description |
|----------|-------------|
| `paper_plan.md` | Research design, propositions, identification strategy |
| `literature_review.md` | Related work synthesis with citations |
| `identification_strategy.md` | Causal identification argument and threats |
| `econometric_spec.md` | Econometric specification with equations |
| `data_dictionary.json` | Pre-specified minimal data footprint (fields, time filter, granularity) |
| `paper_draft.tex` | Full LaTeX manuscript |
| `abstract.tex` | Standalone abstract |
| `self_attack_report.json` | Adversarial flaw-finding report with severity scores |
| `review_*.md` | Structured reviews from 6 specialist reviewers |
| `review_aggregation.json` | Mechanical aggregation verdict and scores |
| `replication/estimation.py` | Main econometric estimation code |
| `replication/data_queries.sql` | All data queries used in the paper |
| `replication/audit_log.csv` | Complete data access audit trail |

All artifacts are committed to a dedicated GitHub repository for the paper, structured for direct import into Overleaf.

---

## Pipeline stages

```
[Researcher input: RQ + optional BibTeX + optional data]
          │
          ▼
    1. Study Design      idea_developer, literature_scanner, identification_strategist
    2. Data              data_architect → Allium queries → human approval → data_analyst
    3. Estimation        econometrics_specialist
    4. Writing           section_writer, abstract_writer, latex_formatter
          │
          ▼  (iterative mode only)
    5. Ceiling Check     Strategist assesses whether further iteration adds value
    6. Self-Attack       Adversarial specialist finds critical flaws (severity 1–10)
    7. Polish            5 parallel specialists: formula · numerics · institutions · bibliography · equilibria
          │
          ▼
    8. Review            6 parallel reviewers: mechanism · technical · identification ·
                         literature · data · writing
    9. Aggregation       3-rule mechanical verdict (see below)
   10. Revision          if MAJOR_REVISION verdict: revisor specialist addresses feedback
   11. Replication       packages all queries, code, and audit trail
   12. GitHub Push       LaTeX + replication package committed to paper repo
```

---

## Review aggregation

Reviews are aggregated by three deterministic rules applied in order:

| Rule | Condition | Verdict |
|------|-----------|---------|
| 1 | Mechanism reviewer score < 5 | `MECHANISM_FAIL` — fundamental revision required |
| 2 | Any reviewer score < 4 | `HARD_REJECT` — floor violation |
| 3 | Weighted average (technical × 1.5, identification × 1.5, data × 1.25) | `ACCEPT` / `MINOR_REVISION` / `MAJOR_REVISION` / `HARD_REJECT` |

---

## Data access — Allium

The data module uses [Allium](https://allium.so) for indexed blockchain data. Set `ALLIUM_API_KEY` in `.env` to enable it. The pipeline also runs without data (literature-only or with manually provided files).

Every query passes through 5 guardrails before execution:

1. No `SELECT *` — all fields must be listed explicitly
2. All requested fields must be declared in the paper's `data_dictionary.json`
3. A time-bound `WHERE` clause is required on every query
4. Transaction-level granularity requires written justification
5. Production queries require a prior approved feasibility run on the same table

**Two-phase workflow:**
- **Feasibility** (1000-row sample) — auto-approved, executes immediately
- **Production** (full dataset) — queued for researcher approval at `GET /api/papers/{id}/pending-queries`

We gratefully acknowledge **[Allium](https://allium.so)** for supporting this research through data access and technical collaboration.

---

## Quick start

### 1. Install

```bash
git clone https://github.com/bhanneke/E2ER-project.git
cd E2ER-project
pip install -e ".[pgvector]"
```

### 2. Configure

```bash
cp .env.example .env
# Required: set ANTHROPIC_API_KEY or OPENROUTER_API_KEY
# Optional: ALLIUM_API_KEY (data module), GITHUB_TOKEN (repo push)
```

### 3. Start PostgreSQL

```bash
cd docker && docker compose up -d db
```

### 4. Initialise the database

```bash
python scripts/migrate.py
# Runs sql/001 through sql/006 in order:
# papers, llm_usage, data_queries + approvals, literature, contributions, events
```

### 5. Start the API

```bash
uvicorn src.api.app:app --reload --port 8280
```

### 6. Create a paper

```bash
curl -X POST http://localhost:8280/api/papers \
  -H "Content-Type: application/json" \
  -d '{
    "title": "DeFi Liquidity Provision and Market Quality",
    "research_question": "How does concentrated liquidity in Uniswap v3 affect price discovery?",
    "datasets": ["uniswap_v3_swaps"],
    "mode": "iterative"
  }'
```

### 7. Approve pending data queries

```bash
curl http://localhost:8280/api/papers/{paper_id}/pending-queries
curl -X POST http://localhost:8280/api/queries/{query_id}/approve \
  -d '{"approved": true}'
```

---

## Supported LLM providers

| Provider | Setting | Notes |
|----------|---------|-------|
| Anthropic | `LLM_BACKEND=anthropic` | Supports prompt caching — recommended |
| OpenRouter | `LLM_BACKEND=openrouter` | 200+ models via OpenAI-compatible format |

---

## Architecture diagrams

Mermaid diagrams in [`docs/diagrams/`](docs/diagrams/):

| Diagram | Description |
|---------|-------------|
| [`pipeline_overview.md`](docs/diagrams/pipeline_overview.md) | Full pipeline from idea to completion |
| [`specialist_dag.md`](docs/diagrams/specialist_dag.md) | Specialist execution dependencies and parallel groups |
| [`data_module.md`](docs/diagrams/data_module.md) | Allium query flow through guardrails and approval |
| [`llm_tool_loop.md`](docs/diagrams/llm_tool_loop.md) | LLM API loop and tool call interception |
| [`system_architecture.md`](docs/diagrams/system_architecture.md) | Component overview |
| [`review_aggregation.md`](docs/diagrams/review_aggregation.md) | 3-rule mechanical review aggregation |

---

## Example outputs

The following papers were produced by earlier versions of the E2ER pipeline. In each case the researcher selected the research question and participated in the review stage; all other steps (literature search, data acquisition, estimation, writing) were handled autonomously by the pipeline.

> Results have not been submitted to a journal and should not be cited as peer-reviewed findings.

### NFT Market Seasonality

Tests whether the Halloween effect (systematically higher winter returns) extends to NFT markets. The pipeline acquired 35.8 million Ethereum-based NFT trades across eight platforms, specified econometric models, and ran robustness checks (bootstrap inference, permutation tests, jackknife analysis).

**Key result (null finding):** No statistically significant Halloween effect. Two-thirds of the raw seasonal differential in USD returns reflects ETH price seasonality rather than NFT-specific patterns.

### Institutionalisation of Bitcoin

Examines whether Bitcoin's volatility converged toward traditional asset levels following the January 2024 spot ETF approval. The pipeline estimated GARCH and Markov-switching regime models, ran a difference-in-differences design around the ETF date, and executed robustness checks (Mann-Kendall trend tests, Rambachan-Roth sensitivity, leave-one-out analysis).

**Key result (null finding):** Bitcoin's GARCH volatility fell from 89% to 50% after ETF approval, reaching a low-volatility regime at 32% (within commodity range). But Bitcoin sustains this regime for only 6 days on average vs. 82 days for equities — convergence is gradual, not structural.

*Full paper PDFs and replication packages will be added to this repository as a separate release.*

---

## Version history

### v1 — Linear Pipeline

A sequential pipeline of 14 specialised agents processing a research question through 16 fixed stages. Each agent handles one task (literature search, data acquisition, theory development, estimation, drafting, review) and passes artifacts forward. Quality gates between stages enforce minimum standards before downstream agents proceed.

```
idea → research design → [literature | data | theory] → merge → estimation
     → analysis → draft → [consistency | review | technical | visual] → revision
```

24 workers, 118 skill files, 40+ skills across 9 domains. Fixed stage ordering; no editorial intelligence at runtime. Produced 133 paper drafts across 157 runs.

### v2 — Strategist-Controlled Architecture

A central Strategist agent (acting as first author) orchestrates 12 specialist agents (co-authors) through a work-order pattern. The Strategist operates in two modes: Mode 1 (lean orchestration, structured JSON decisions at pipeline checkpoints) and Mode 2 (full editorial control with access to the complete paper).

Key advances over v1:
- Strategist makes tactical decisions at checkpoints rather than following a fixed sequence
- Tiered context management (Tier 0: paper identity; Tier 1: decision-specific; Tier 2: full artifacts)
- Data pipeline isolation — only the Data specialist queries databases; all others work from exports
- Human review gates at research design and post-draft stages

### v3 — Open-Source Release (this repo)

A ground-up redesign for open-source use. Retains the Strategist architecture from v2 and adds four extensions adapted from [ZeroPaper](https://github.com/alejandroll10/zeropaper):

- **Ceiling detection** — Strategist assesses diminishing returns after each iteration and decides: continue, pivot (max once), or proceed to review
- **Self-attack phase** — an adversarial specialist scores the draft's flaws by severity (1–10) before external review
- **Parallel polish stack** — five specialists run concurrently targeting specific weaknesses: formula errors, numeric consistency, institutional context, bibliography, equilibrium conditions
- **Mechanical review aggregation** — three deterministic rules replace subjective editorial judgement

Additional v3 changes: BYOK (Anthropic and OpenRouter), built-in Allium data guardrails, token/cost tracking per specialist call, and GitHub integration with Overleaf-compatible repo structure.

---

## Running tests

```bash
pytest tests/ -v
```

20 tests covering guardrails, review aggregation, and cost tracking — no network or LLM calls required.

---

## Contributing

- **Research questions** — open an issue with a research question you think could be tested on on-chain data
- **Data providers** — the data module is designed to be extended; Allium is the first example
- **Skill files** — add domain expertise as markdown in `skills/files/`; loaded automatically into specialist prompts
- **Architectural ideas** — discussion on pipeline design, LLM tool-use patterns, and causal inference tooling is welcome

---

## Contact

**Björn Hanneke** · [bjornhanneke.com](https://www.bjornhanneke.com) · hanneke@wiwi.uni-frankfurt.de

PhD Candidate, Goethe University Frankfurt
Chair of Information Systems and Information Management (Prof. Dr. Oliver Hinz)

[ORCID](https://orcid.org/0009-0000-7466-9581) · [Google Scholar](https://scholar.google.com/citations?user=N5fbuZIAAAAJ) · [LinkedIn](https://linkedin.com/in/bhanneke)

---

*MIT License — see [LICENSE](LICENSE).*
