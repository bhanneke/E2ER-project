.PHONY: install test lint format smoke smoke-paid clean help

# Use the same Python that resolves `python3` so Makefile works regardless of
# whether `pytest` / `ruff` happen to be on the user's PATH.
PY := python3

help:
	@echo "E2ER make targets:"
	@echo "  install     Install package + dev dependencies (pip install -e '.[dev]')"
	@echo "  smoke       Run the full mocked test suite — no API key needed (~15s, free)"
	@echo "  smoke-paid  Run the live Haiku end-to-end test (~\$$0.50, needs ANTHROPIC_API_KEY)"
	@echo "  test        Same as smoke (full mocked suite)"
	@echo "  lint        Run ruff check + format --check"
	@echo "  format      Auto-format with ruff"
	@echo "  clean       Remove caches and build artifacts"

install:
	$(PY) -m pip install -e ".[dev]"

# Free smoke test — proves install + pipeline orchestration without spending tokens.
# Run this first after cloning to confirm the pipeline works end-to-end.
smoke:
	$(PY) -m pytest tests/ -v --tb=short -m "not e2e"

# Real-LLM end-to-end test on Haiku 4.5. Costs ~$0.50. Requires ANTHROPIC_API_KEY.
smoke-paid:
	@if [ -z "$$ANTHROPIC_API_KEY" ]; then \
		echo "ANTHROPIC_API_KEY not set; export it before running smoke-paid." >&2; \
		exit 1; \
	fi
	$(PY) -m pytest tests/e2e/test_haiku_smoke.py -v -m e2e

test: smoke

lint:
	$(PY) -m ruff check src/ tests/
	$(PY) -m ruff format --check src/ tests/

format:
	$(PY) -m ruff format src/ tests/
	$(PY) -m ruff check --fix src/ tests/

clean:
	rm -rf .pytest_cache .ruff_cache .mypy_cache build dist *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} +
