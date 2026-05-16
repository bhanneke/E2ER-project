"""E2ER v3 — Unified configuration (all BYOK settings)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── LLM ───────────────────────────────────────────────────────────────────
    llm_backend: Literal["anthropic", "openrouter", "claude_code", "codex", "gemini"] = "anthropic"
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-4-5"
    openrouter_api_key: str | None = None
    openrouter_model: str = "anthropic/claude-sonnet-4-5"
    enable_prompt_caching: bool = True

    # ── Database ──────────────────────────────────────────────────────────────
    db_password: str = "changeme"
    db_host: str = "db"
    db_port: int = 5432
    db_name: str = "e2er"
    db_user: str = "e2er"
    postgres_url: str | None = None  # overrides individual settings if set

    @property
    def database_url(self) -> str:
        if self.postgres_url:
            return self.postgres_url
        return f"postgresql://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"

    # ── Data — Allium ─────────────────────────────────────────────────────────
    allium_api_key: str | None = None
    allium_api_base: str = "https://api.allium.so/api/v1"
    auto_approve_feasibility: bool = True
    max_queries_per_paper: int = 20
    max_rows_per_paper: int = 5_000_000

    @property
    def data_module_enabled(self) -> bool:
        return self.allium_api_key is not None

    # ── Literature ────────────────────────────────────────────────────────────
    literature_bibtex_file: str | None = None
    semantic_scholar_api_key: str | None = None

    @property
    def literature_kb_enabled(self) -> bool:
        return self.postgres_url is not None or self.db_password != "changeme"

    # ── GitHub ────────────────────────────────────────────────────────────────
    github_token: str | None = None
    github_username: str | None = None
    github_org: str | None = None
    github_paper_prefix: str = "E2ER"
    github_private_repos: bool = True

    @property
    def github_enabled(self) -> bool:
        return self.github_token is not None and self.github_username is not None

    # ── Pipeline ──────────────────────────────────────────────────────────────
    max_concurrent_specialists: int = 3
    specialist_timeout: int = 3600
    max_review_rounds: int = 3
    weak_accept_threshold: float = 7.0
    max_revision_iterations: int = 3
    default_max_cost_usd: float = 25.0  # fallback per-paper cost cap
    # Per-API-call output cap. Must be large enough for ONE specialist's
    # `write_file` tool argument (the JSON / LaTeX / markdown content).
    # 16384 was too low: data_architect / paper_drafter writing
    # data_dictionary.json or full paper drafts hit finish_reason="length"
    # mid-write, the tool_loop correctly bails (looping is futile — same
    # wall every time), and the specialist is marked failed. Both Anthropic
    # Claude Sonnet 4.6 and Haiku 4.5 support 64K output tokens; use
    # 32K as a balanced default that leaves headroom without burning extra
    # latency on calls that don't need it.
    max_tokens_per_call: int = 32768

    # ── Server ────────────────────────────────────────────────────────────────
    host: str = "0.0.0.0"
    port: int = 8280
    log_level: str = "INFO"
    artifacts_dir: str = "artifacts"
    repos_dir: str = "repos"
    workspace_root: str = "workspaces"

    # ── Claude Code CLI backend (free under Max plan) ─────────────────────────
    # Set LLM_BACKEND=claude_code to delegate every specialist call to the
    # `claude` CLI subprocess instead of paying API tokens. Requires Claude
    # Code installed (`npm i -g @anthropic-ai/claude-code`) AND a Max plan.
    # See src/modules/llm/claude_code.py for trade-offs (Allium guardrails
    # need a wrapper script, prompt tool-name conventions differ).
    claude_code_path: str = "claude"
    claude_code_timeout: int = 1800  # 30 min hard cap per specialist invocation
    claude_code_max_turns: int = 60  # Default agentic-turn cap inside the CLI
    claude_code_cwd: str = ""  # Empty → use os.getcwd() at invocation time

    # ── Codex CLI backend (free under ChatGPT Plus/Pro plan) ──────────────────
    # Set LLM_BACKEND=codex to delegate to the `codex exec` subprocess.
    # Requires Codex installed (`npm install -g @openai/codex`) + `codex login`.
    # Alpha: interface is stable but live validation pending.
    codex_path: str = "codex"
    codex_timeout: int = 1800
    codex_model: str = ""  # Empty → CLI's default
    codex_reasoning_effort: str = ""  # low | medium | high; empty → CLI default
    codex_cwd: str = ""

    # ── Gemini CLI backend (free under Google AI Pro/Ultra plan) ──────────────
    # Set LLM_BACKEND=gemini to delegate to the `gemini` subprocess. Requires
    # Gemini CLI installed (`npm install -g @google/gemini-cli`) + `gemini auth`.
    # Alpha: interface is stable but live validation pending.
    gemini_path: str = "gemini"
    gemini_timeout: int = 1800
    gemini_model: str = ""  # Empty → CLI's default
    gemini_cwd: str = ""

    # ── API security ──────────────────────────────────────────────────────────
    # When set, all mutating endpoints (POST/DELETE) require
    # `Authorization: Bearer <token>`. When unset (default), the API is open
    # — fine for localhost dev, NOT fine for any deploy beyond your machine.
    api_auth_token: str | None = None
    # Comma-separated origins for CORS. Default is the dashboard on localhost.
    # Set to '*' explicitly to allow any origin (only do this for non-secret deploys).
    cors_origins: str = "http://localhost:8280,http://127.0.0.1:8280"

    @property
    def default_model(self) -> str:
        if self.llm_backend == "openrouter":
            return self.openrouter_model
        return self.anthropic_model

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",  # tolerate extra env vars (e.g. POSTGRES_PASSWORD for docker)
    }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
