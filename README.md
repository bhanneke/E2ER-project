# E2ER v3 — End-to-End Researcher

[![Status](https://img.shields.io/badge/status-active%20development-blue)]()
[![License](https://img.shields.io/badge/license-MIT-green)]()
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)]()
[![Tests](https://img.shields.io/badge/tests-passing-brightgreen)]()

**E2ER** is an open-source pipeline for generating peer-review-quality empirical research papers in information systems, economics, and finance. Given a research question and access to data, the system autonomously designs the study, acquires and validates data, runs econometric estimation, writes the paper in LaTeX, self-attacks its own draft, runs parallel peer review, and pushes everything to a GitHub repository compatible with Overleaf.

> **Disclaimer**: Papers produced by this pipeline have not been peer-reviewed or independently validated. Methodological errors, incorrect interpretations, and factual inaccuracies may be present. Do not cite pipeline outputs as established research findings without independent verification. E2ER is optimised for empirical research — it works best with structured data, clear identification strategies, and established econometric methods.

This is v3 of the E2ER project, the first open-source release. It grew out of two years of internal pipeline development that produced 133 paper drafts across 157 runs, documented below.

---

## What it does

```
Research Question
       │
       ▼
  [Strategist] ──── decides ────► [Specialists] (parallel or sequential)
       │                              │
       │◄────── contributions ────────┘
       │
  [Ceiling Check] → [Self-Attack] → [Polish Stack] → [Review] → [Aggregation]
       │
  [GitHub Push] → paper repo (LaTeX + replication package)
```

1. **Design** — develops the paper plan, literature review, and identification strategy
2. **Data** — queries Allium blockchain data through 5 guardrails + human approval
3. **Analysis** — econometric specification and estimation
4. **Writing** — full LaTeX paper draft by specialist agents
5. **Self-attack** — adversarial agent finds critical flaws before external review
6. **Polish** — parallel specialists target formula errors, numerics, institutions, bibliography, equilibria
7. **Review** — 6 reviewers in parallel with mechanical 3-rule aggregation
8. **Replication** — SQL queries, estimation code, and audit log packaged for reproducibility
9. **GitHub** — LaTeX + replication package pushed to a paper repo (Overleaf-compatible)

---

## Project background

Rigorous empirical research is slow, expensive, and difficult to scale. A single causal study on blockchain economics requires identifying a natural experiment, acquiring on-chain data, specifying an econometric model, running estimation with robustness checks, and producing a paper with replication materials. Each step requires domain expertise that is scarce and unevenly distributed.

E2ER automates this pipeline. It has been developed and tested at the Chair of Information Systems, Goethe University Frankfurt, as part of ongoing PhD research. The system has been tested on Ethereum-specific data (NFT transactions, DeFi protocol data, token distributions) and general empirical economics questions.

### Internal pipeline statistics (v1, through April 2026)

| Metric | Count |
|--------|-------|
| Total pipeline runs | 157 |
| Completed paper drafts | 133 |
| Peer review simulations | 133 |
| Technical methodology reviews | 133 |
| Consistency checks | 133 |
| Completed revisions | 133 |
| Second-iteration drafts | 30 |
| Total stage executions | 2,253 |

---

## Example outputs

> All papers below were produced entirely by earlier versions of the E2ER pipeline without human intervention. No human selected the research question, wrote any text, ran any estimation, or reviewed the output. They are provided to demonstrate what the pipeline produces autonomously.

### Example 1 — NFT Market Seasonality

**Input**: One-sentence idea about calendar anomalies in NFT markets.

**What the pipeline produced**: A 30+ page paper testing whether the Halloween effect extends to NFT markets. The pipeline autonomously identified the research gap, formulated five testable propositions, acquired 35.8 million Ethereum-based NFT trades across eight platforms, specified econometric models, ran estimation with robustness checks (bootstrap inference, permutation tests, jackknife analysis), generated all figures, and produced a complete LaTeX manuscript with bibliography.

**Key result** (null finding): No statistically significant Halloween effect. Two-thirds of the raw seasonal differential in USD returns reflects ETH price seasonality rather than NFT-specific patterns. Day-of-week effects are significant, suggesting shorter-horizon calendar patterns dominate seasonal ones.

[Full paper PDF](examples/e2er_v1_nft_seasonality/paper.pdf) · [LaTeX source](examples/e2er_v1_nft_seasonality/main.tex) · [Replication package](examples/e2er_v1_nft_seasonality/replication/)

<p align="center">
  <img src="examples/e2er_v1_nft_seasonality/figures/fig1_monthly_returns.png" alt="Monthly NFT Returns" width="680">
</p>
<p align="center"><em>Monthly return distribution — AI-generated, not peer-reviewed</em></p>

### Example 2 — Institutionalisation of Bitcoin

**Input**: One-sentence idea about Bitcoin volatility convergence toward traditional assets.

**What the pipeline produced**: A paper examining whether Bitcoin's volatility has converged toward traditional asset levels following the January 2024 spot ETF approval. The pipeline acquired daily data on Bitcoin and seven traditional benchmarks (2020–2026), estimated GARCH and Markov-switching regime models, ran a difference-in-differences design around the ETF date, and executed full robustness checks (Mann-Kendall trend tests, Rambachan-Roth sensitivity, leave-one-out analysis).

**Key result** (null finding): Bitcoin's unconditional GARCH volatility fell from 89% to 50% after ETF approval, and Markov-switching models identify a low-volatility regime at 32% (within commodity range). However, Bitcoin sustains this calm regime for only six days on average vs. 82 days for equities. No discrete structural break at the ETF date; convergence is gradual.

[Full paper PDF](examples/e2er_v1_bitcoin_institutionalization/paper.pdf) · [LaTeX source](examples/e2er_v1_bitcoin_institutionalization/main.tex) · [Replication package](examples/e2er_v1_bitcoin_institutionalization/replication/)

<p align="center">
  <img src="examples/e2er_v1_bitcoin_institutionalization/figures/figure_2_event_study.pdf" alt="Event Study: ETF Approval" width="680">
</p>
<p align="center"><em>Event study around ETF approval date — AI-generated, not peer-reviewed</em></p>

---

## Architecture

### Key design decisions

**Owns the tool-use loop** — no CLI subprocess. The pipeline runs the Anthropic/OpenRouter API directly and intercepts every tool call. This is what makes guardrails enforceable: the `AlliumToolHandler` validates all 5 rules before any query reaches the data provider.

**BYOK** — Bring Your Own Keys. Supports Anthropic API (with prompt caching) and OpenRouter (200+ models via OpenAI-compatible format).

**Human-in-the-loop data approval** — all production Allium queries require researcher sign-off via the REST API before execution. Feasibility queries (1000-row samples) are auto-approved.

**Mechanical review aggregation** — three deterministic rules replace subjective editorial judgement:
- Rule 1: mechanism reviewer score < 5 → `MECHANISM_FAIL` (hard gate)
- Rule 2: any reviewer score < 4 → `HARD_REJECT`
- Rule 3: weighted average (technical reviewer 1.5×, identification reviewer 1.5×)

**Replication-ready by default** — all SQL queries, estimation code, and the full data access audit trail are saved as artifacts and pushed to the paper's GitHub repository.

**Overleaf-compatible** — paper repos are created with `.gitignore` as the first commit (preventing LaTeX artifacts from polluting git history). Overleaf should always import *from* GitHub, never the other direction.

### Architecture diagrams

Detailed Mermaid diagrams in [`docs/diagrams/`](docs/diagrams/):

| Diagram | Description |
|---------|-------------|
| [`pipeline_overview.md`](docs/diagrams/pipeline_overview.md) | Full pipeline from idea to completion |
| [`specialist_dag.md`](docs/diagrams/specialist_dag.md) | Specialist execution dependencies and parallel groups |
| [`data_module.md`](docs/diagrams/data_module.md) | Allium query flow through 5 guardrails + approval |
| [`llm_tool_loop.md`](docs/diagrams/llm_tool_loop.md) | Owned tool-use loop (no CLI subprocess) |
| [`system_architecture.md`](docs/diagrams/system_architecture.md) | Component overview |
| [`review_aggregation.md`](docs/diagrams/review_aggregation.md) | 3-rule mechanical review aggregation |

---

## Modules

| Module | Description |
|--------|-------------|
| `src/modules/llm/` | Anthropic + OpenRouter backends, tool-use loop, file tools |
| `src/modules/data/` | Allium HTTP client, 5 guardrails, audit log, approval workflow |
| `src/modules/tracking/` | Token usage and USD cost tracking per specialist call |
| `src/modules/literature/` | Paper search (OpenAlex, Semantic Scholar, arXiv), BibTeX, pgvector KB |
| `src/modules/github/` | Repo creation, `.gitignore`-first workflow, artifact push |
| `src/modules/fetch/` | SSRF-safe HTTP client |
| `src/core/strategist/` | Strategist engine, ceiling detection, self-attack, review aggregation |
| `src/core/specialists/` | Specialist runner, parallel dispatcher, work order contracts |
| `src/core/pipeline/` | DAG (single-pass + iterative), state persistence |
| `src/skills/` | Skill markdown files injected into specialist prompts |
| `src/api/` | FastAPI REST API (papers, data approval, usage) |

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
# Edit .env — at minimum set ANTHROPIC_API_KEY or OPENROUTER_API_KEY
```

### 3. Start the database

```bash
cd docker && docker compose up -d db
```

### 4. Run migrations

```bash
python scripts/migrate.py
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
# List queries awaiting approval
curl http://localhost:8280/api/papers/{paper_id}/pending-queries

# Approve
curl -X POST http://localhost:8280/api/queries/{query_id}/approve \
  -H "Content-Type: application/json" \
  -d '{"approved": true}'
```

---

## Data module — Allium

The data module uses [Allium](https://allium.so) for indexed blockchain data.
Set `ALLIUM_API_KEY` in `.env` to enable it (optional — the pipeline runs without data too).

**5 guardrails enforced on every query:**
1. No `SELECT *` — explicit field list required
2. All fields must be declared in the paper's `data_dictionary.json`
3. Time-bound `WHERE` clause required on every query
4. Transaction-level granularity requires written justification
5. Production queries require a prior approved feasibility run on the same table

**Two-phase workflow:**
- **Feasibility** (1000-row sample) — auto-approved, runs immediately
- **Production** (full dataset) — queued for researcher approval via `GET /api/papers/{id}/pending-queries`

We gratefully acknowledge **[Allium](https://allium.so)** for supporting this research through data access and technical collaboration.

---

## Supported LLM providers

| Provider | Setting | Notes |
|----------|---------|-------|
| Anthropic | `LLM_BACKEND=anthropic` | Supports prompt caching — recommended |
| OpenRouter | `LLM_BACKEND=openrouter` | 200+ models, OpenAI-compatible format |

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
- **Skill files** — add domain expertise as markdown files in `skills/files/`; they are automatically loaded into specialist prompts
- **Architectural ideas** — if you work on automated research pipelines, LLM tool-use, or causal inference tooling, discussion on design choices is welcome

---

## Version history

### v1 — Linear Pipeline (2024)

A sequential pipeline of 14 specialised agents processing a research question through 16 fixed stages. Each agent handles one task (literature search, data acquisition, theory development, estimation, drafting, review) and passes artifacts forward. Quality gates between stages enforce minimum standards before downstream agents proceed.

```
idea → research design → [literature | data | theory] → merge → estimation
     → analysis → draft → [consistency | review | technical | visual] → revision
```

24 workers, 118 skill files, 40+ skills across 9 domains. Fixed stage ordering; no editorial intelligence at runtime. Produced 133 paper drafts across 157 runs.

### v2 — Strategist-Controlled Architecture (2025)

A central Strategist agent (acting as first author) orchestrates 12 specialist agents (co-authors) through a work-order pattern. The Strategist operates in two modes: Mode 1 (lean orchestration, structured JSON decisions at pipeline checkpoints) and Mode 2 (full editorial control with access to the complete paper).

Key advances over v1:
- Strategist makes tactical decisions at checkpoints rather than following a fixed sequence
- Tiered context management (Tier 0: paper identity; Tier 1: decision-specific; Tier 2: full artifacts)
- Data pipeline isolation — only the Data specialist queries databases; all others work from exports
- Human review gates at research design and post-draft stages
- Ran on private 100xOS infrastructure (Claude Code CLI subprocess pattern)

### v3 — Open-Source Release (2026, this repo)

A ground-up redesign for open-source use. Retains the Strategist architecture from v2 and adds four major extensions inspired by the ZeroPaper architecture:

- **Owns the tool-use loop** — replaced Claude Code CLI subprocess with direct Anthropic/OpenRouter API calls; enables intercepting every tool call for guardrails
- **Ceiling detection** — Strategist assesses diminishing returns after each iteration and decides: continue, pivot (max once), or proceed to review
- **Self-attack phase** — an adversarial specialist reads the draft and returns severity-scored findings (1–10) before external review
- **Parallel polish stack** — five specialists run concurrently targeting specific pathologies (formula errors, numeric consistency, institutional context, bibliography, equilibrium conditions)
- **Mechanical review aggregation** — three deterministic rules replace subjective editorial judgement
- **BYOK** — Anthropic API and OpenRouter supported; no dependency on private infrastructure
- **Allium data module** — blockchain data access with 5 guardrails and human-in-the-loop approval built in from the start

---

## Contact

**Björn Hanneke** · [www.bjornhanneke.com](https://www.bjornhanneke.com) · hanneke@wiwi.uni-frankfurt.de

PhD Candidate, Goethe University Frankfurt
Chair of Information Systems and Information Management (Prof. Dr. Oliver Hinz)

[ORCID](https://orcid.org/0009-0000-7466-9581) · [Google Scholar](https://scholar.google.com/citations?user=N5fbuZIAAAAJ) · [LinkedIn](https://linkedin.com/in/bhanneke)

---

## License

MIT — see [LICENSE](LICENSE).

*This pipeline produces research assistance outputs. Human researcher review, validation, and editorial judgement are required before any manuscript is submitted for publication.*
