# E2ER v3 — End-to-End Researcher

**E2ER** is an open-source pipeline for generating peer-review-quality empirical research papers in information systems, economics, and finance.

> **Disclaimer:** This pipeline is designed for empirical research. It works best with structured data, clear identification strategies, and established econometric methods. It is not intended for purely theoretical papers. Generated manuscripts require researcher review before submission.

## What it does

Given a research question and access to data, E2ER v3:

1. Develops the paper plan and literature review
2. Designs the identification strategy
3. Queries and validates data (with human-in-the-loop approval)
4. Runs econometric specifications
5. Drafts the full paper in LaTeX
6. Self-attacks the draft adversarially to find flaws
7. Runs a parallel polish stack for targeted improvements
8. Conducts formal peer review simulation
9. Aggregates review scores via a mechanical 3-rule system
10. Pushes results to a GitHub repository (Overleaf-compatible)

## Architecture

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

## Key design principles

- **BYOK** — Bring Your Own Keys. Supports Anthropic API and OpenRouter (200+ models)
- **Owns the tool-use loop** — no CLI subprocess; pipeline intercepts every tool call for guardrails
- **Human-in-the-loop data approval** — all production Allium queries require researcher sign-off
- **Cost transparent** — every LLM call tracked with token counts and USD cost
- **Replication-ready** — all data queries, SQL, and estimation code saved as artifacts
- **Overleaf-compatible** — GitHub repos created with `.gitignore` as the first commit

## Modules

| Module | Description |
|--------|-------------|
| `src/modules/llm/` | LLM backends (Anthropic, OpenRouter), tool-use loop |
| `src/modules/data/` | Allium HTTP API client, 5 guardrails, audit log |
| `src/modules/tracking/` | Token usage and cost tracking |
| `src/modules/literature/` | Paper search (OpenAlex, Semantic Scholar, arXiv), BibTeX |
| `src/modules/github/` | GitHub repo creation, artifact push |
| `src/core/strategist/` | Strategist engine, ceiling detection, self-attack, review aggregation |
| `src/core/specialists/` | Specialist runner (owns tool-use loop), dispatcher |
| `src/core/pipeline/` | DAG definition, state persistence |
| `src/skills/` | Skill files injected into specialist prompts |
| `src/api/` | FastAPI REST API |

## Quick start

### 1. Install

```bash
pip install -e ".[pgvector]"
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env: add your ANTHROPIC_API_KEY or OPENROUTER_API_KEY
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
    "research_question": "How does concentrated liquidity provision in Uniswap v3 affect price discovery?",
    "datasets": ["uniswap_v3_swaps", "uniswap_v3_positions"],
    "mode": "iterative"
  }'
```

## Data module — Allium

The data module uses [Allium](https://allium.so) for blockchain data access.
Set `ALLIUM_API_KEY` in `.env` to enable it.

**5 guardrails enforced on every query:**
1. No `SELECT *` — must list explicit fields
2. Fields must be in the paper's `data_dictionary.json`
3. Time-bound `WHERE` clause required
4. Transaction-level granularity requires justification
5. Production queries require a prior approved feasibility run

**Two-phase workflow:**
- **Feasibility** queries (1000-row sample) are auto-approved and run immediately
- **Production** queries are queued for researcher approval at `GET /api/papers/{id}/pending-queries`

## Supported LLM providers

| Provider | Setting | Notes |
|----------|---------|-------|
| Anthropic | `LLM_BACKEND=anthropic` | Supports prompt caching |
| OpenRouter | `LLM_BACKEND=openrouter` | 200+ models, no caching |

## Attribution

E2ER v3 was developed by [Björn Hanneke](https://wiwi.uni-frankfurt.de) as part of research into
automated empirical research pipelines.

We gratefully acknowledge **[Allium](https://allium.so)** for supporting this project through
blockchain data access and technical collaboration.

## License

MIT License — see [LICENSE](LICENSE).

---

*This pipeline produces research assistance, not finished papers. Human researcher review,
validation, and editorial judgment are required before any manuscript is submitted.*
