# Contributing to E2ER

Thanks for your interest. This document covers the most common contribution paths. For specific topics there are deeper guides:

- **Adding skill files** (most common) → [`skills/CONTRIBUTING_SKILLS.md`](skills/CONTRIBUTING_SKILLS.md)
- **Adding natural experiments / IVs** → [`docs/iv_database.md`](docs/iv_database.md)

---

## Quick start (development setup)

```bash
git clone https://github.com/bhanneke/E2ER-project.git
cd E2ER-project
pip install -e ".[pgvector,dev]"
docker compose -f docker/docker-compose.yml up -d db
python scripts/migrate.py
bash scripts/vendor_htmx.sh
pytest tests/
```

The default `pytest` invocation skips real-LLM tests (`-m 'not e2e'`). To run the haiku smoke test against the real Anthropic API:

```bash
ANTHROPIC_API_KEY=sk-ant-... pytest tests/e2e/test_haiku_smoke.py -v -m e2e
```

---

## What you can contribute

### 1. Skill files (no code changes)

Most domain expertise lives in `skills/files/**/*.md`. These are markdown documents injected into specialist system prompts at runtime. No Python changes are needed.

See [`skills/CONTRIBUTING_SKILLS.md`](skills/CONTRIBUTING_SKILLS.md) for the file format, naming rules, and how skills are routed to specialists.

### 2. Specialists

Specialists live in `src/core/specialists/` and follow the contract in `src/core/specialists/contracts.py` (`WorkOrder` in, `Contribution` out). To add a new one:

1. Add the specialist name to `src/core/specialists/registry.py`.
2. Wire its expected output filename into `SPECIALIST_ARTIFACTS` so the runner can find it on resume.
3. Map its skill bundle in `src/skills/loader.py` (`_SPECIALIST_SKILLS`).
4. Add a deterministic mock entry in `tests/conftest.py` (`_SPECIALIST_OUTPUTS`) so the existing pipeline tests cover it.

The Strategist's prompt at `src/core/strategist/engine.py` lists the available specialists — update that prompt if you want the Strategist to be aware of yours.

### 3. Data sources

The data module is designed to be pluggable. The Allium implementation in `src/modules/data/` is one example. To add a new provider:

1. Add tools (`*_TOOLS: list[dict]`) and a handler (subclass `ToolHandler`) under `src/modules/<provider>/tools.py`.
2. Wire the tools and handler into `_run_pipeline` in `src/api/app.py`, gated on a feature flag (e.g. `WRDS_ENABLED`).
3. Document the provider in the README's "Data sources for integration" table.
4. If the provider needs guardrails (mandatory time bounds, approval flow, etc.) put them in the handler's `handle()` method — never trust raw LLM output.

The literature module at `src/modules/literature/tools.py` is a more recent, smaller example to copy.

### 4. LLM backends

Two backends ship today: `AnthropicBackend` and `OpenRouterBackend` in `src/modules/llm/`. They both implement the `LLMBackend` interface (`tool_loop` method). To add a third:

1. Implement `tool_loop(system, messages, tools, tool_handler, max_turns)` returning a `ToolLoopResult`.
2. Register it in `src/modules/llm/registry.py`.
3. Add the corresponding env var to `Settings` in `src/config.py` and to `.env.example`.

Per the Anthropic/OpenRouter precedent, configure the SDK client with `max_retries=5`.

### 5. Bug reports / feedback

If a paper run produces something obviously broken, please open an issue with:

- The research question that triggered it
- The model + backend used
- The relevant `last_error` (or full audit bundle if you can share it)
- What you expected vs. what happened

Edge cases and failure modes are particularly valuable for the evaluation framework.

---

## Code style

- **Python 3.11+**. Type hints throughout.
- **Lint**: `ruff check src/ tests/` and `ruff format src/ tests/`.
- **Type-check**: `mypy src/` (strict mode is enabled).
- **No `print` in library code** — use `from .logging_config import get_logger`.
- **Tests are mock-only by default**: no network calls, no real LLM, no DB. Real-LLM tests live under `tests/e2e/` and are gated on `@pytest.mark.e2e`.
- **Per the project rules**: SQL migrations are additive — never modify existing `sql/*.sql` files. Add a new one with the next number.

---

## PR process

1. Open an issue first for non-trivial changes so we can scope it before you write code.
2. Branch from `main`, keep PRs small and focused.
3. CI runs `pytest tests/` — must be green before merge.
4. PR description should call out user-facing changes and any new env vars.

---

## Contact

Open an issue or email **hanneke@wiwi.uni-frankfurt.de** for direct questions.
