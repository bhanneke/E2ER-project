# E2ER v3 CLAUDE.md

## Project overview

E2ER v3 is a standalone open-source pipeline for end-to-end empirical research.
It is separate from the private 100xOS ecosystem — no shared/ imports, no infra-net,
no CoS dependencies.

## Key architectural decisions

### Five LLM backends behind one `tool_loop` contract
`LLM_BACKEND` selects the backend (`src/modules/llm/registry.py`):
- `anthropic` — `anthropic.AsyncAnthropic`, prompt caching (SDK; owns the loop)
- `openrouter` — `openai.AsyncOpenAI` → openrouter.ai (SDK; owns the loop)
- `claude_code` — shells out to the `claude` CLI ($0 under a Max plan)
- `codex` — shells out to the `codex` CLI ($0 under ChatGPT Plus/Pro)
- `gemini` — shells out to the `gemini` CLI ($0 under Google AI Pro/Ultra)

The SDK backends run `LLMBackend.tool_loop()` in-process, so `AlliumToolHandler`
intercepts every tool call and runs guardrails BEFORE any query reaches Allium.
The CLI backends delegate the loop to the headless CLI and enforce the SAME
Allium guardrails through the `e2er-data` / `e2er-allium-query` wrapper.

### Data is discovered, not hardcoded
Specialists call `list_data_sources` (what's available for the research question)
then `fetch_data` (FRED/yfinance — yfinance is keyless and always on; FRED needs
`FRED_API_KEY`) or the guarded `query_allium` (needs `ALLIUM_API_KEY` + query
credits). There is **no `DATA_MODULE_ENABLED` toggle** — `data_module_enabled` is a
computed property (`allium_api_key is not None`). To run without on-chain data,
leave `ALLIUM_API_KEY` unset; papers can also run from literature alone or from
files in the workspace `data/` dir (+ `LOCAL_DATA_DIR`).

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
pip install -e ".[dev]"            # add the pgvector extra for the Postgres KB
e2er init                          # guided setup: backend, .env, skills
e2er run "your research question"  # or: uvicorn src.api.app:app --reload --port 8280
```

The DB defaults to **zero-config SQLite** at `~/.e2er/papers.db` (auto-created);
set `DATABASE_URL=postgresql://…` for Postgres + pgvector, then run
`python scripts/migrate.py` (migrations are Postgres-only; SQLite is auto-initialized).

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
    llm/                 — 5 LLM backends + tool-use loop + registry
    data/                — providers (Allium warehouse + FRED/yfinance) + registry + discovery/fetch tools + 5 guardrails + audit
    tracking/            — token usage + cost
    literature/          — providers (OpenAlex/arXiv/S2 search + Zotero/local-.bib libraries) + registry + read_reference (PDF) + KB
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
