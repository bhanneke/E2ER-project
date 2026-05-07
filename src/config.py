"""E2ER v3 — Unified configuration (all BYOK settings)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── LLM ───────────────────────────────────────────────────────────────────
    llm_backend: Literal["anthropic", "openrouter"] = "anthropic"
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
    max_tokens_per_call: int = 16384  # per-API-call output cap; needs to be
    # large enough for full file content
    # (Haiku supports up to 64K)

    # ── Server ────────────────────────────────────────────────────────────────
    host: str = "0.0.0.0"
    port: int = 8280
    log_level: str = "INFO"
    artifacts_dir: str = "artifacts"
    repos_dir: str = "repos"
    workspace_root: str = "workspaces"

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
