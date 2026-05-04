# E2ER v3 CLAUDE.md

## Project overview

E2ER v3 is a standalone open-source pipeline for end-to-end empirical research.
It is separate from the private 100xOS ecosystem — no shared/ imports, no infra-net,
no CoS dependencies.

## Key architectural decisions

### Owns the tool-use loop
No Claude Code CLI subprocess. The pipeline runs `LLMBackend.tool_loop()` directly.
This lets `AlliumToolHandler` intercept every tool call and run guardrails BEFORE
any query reaches the Allium API.

### Two LLM backends
- `AnthropicBackend`: uses `anthropic.AsyncAnthropic`, supports prompt caching
- `OpenRouterBackend`: uses `openai.AsyncOpenAI` pointed at `https://openrouter.ai/api/v1`
Select via `LLM_BACKEND=anthropic|openrouter` in `.env`.

### Data module is optional
Set `DATA_MODULE_ENABLED=false` to run without Allium. Papers can be written from
literature alone, or with manually provided data files in the workspace.

### GitHub integration
- `.gitignore` is ALWAYS the first commit — prevents Overleaf artifacts from polluting git
- Use `GitHubClient.create_paper_repo()` — never create Overleaf first
- Overleaf should always import FROM GitHub, never the reverse

## Critical rules

1. **Never import from 100xOS/shared/** — this is a standalone project
2. **Never skip guardrail validation** — the 5 rules in `QueryValidator.validate_all()` must all run
3. **Never execute production Allium queries without approval** — check `data_approval_requests.status`
4. **Never commit to git without reading CONTRIBUTING.md first** (when it exists)
5. **SQL migrations are additive** — never modify existing files in `sql/`

## Development setup

```bash
pip install -e ".[pgvector,dev]"
cd docker && docker compose up -d db
python scripts/migrate.py
uvicorn src.api.app:app --reload --port 8280
```

## Running tests

```bash
pytest tests/ -v
ruff check src/ tests/
```

## File structure

```
src/
  config.py              — pydantic-settings, all BYOK config
  modules/
    llm/                 — LLM backends + tool-use loop
    data/                — Allium client + 5 guardrails + audit
    tracking/            — token usage + cost
    literature/          — paper search (OA, S2, arXiv) + KB
    github/              — repo creation + artifact push
    fetch/               — SSRF-safe HTTP client
  core/
    strategist/          — engine, runner, ceiling check, self-attack, review aggregation
    specialists/         — base runner, contracts, registry, dispatcher
    pipeline/            — DAG, state persistence
    artifacts/           — artifact registry
    renderer/            — LaTeX assembly + compilation
  db/client.py           — async psycopg3
  api/app.py             — FastAPI routes
  skills/                — skill file loader
skills/files/            — skill markdown files (injected into specialist prompts)
sql/                     — PostgreSQL migrations (run in order)
docker/                  — Dockerfile + docker-compose.yml
tests/                   — pytest tests (no network, no LLM calls)
docs/diagrams/           — Mermaid architecture diagrams
```
