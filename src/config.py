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
    # Default: SQLite at ~/.e2er/papers.db (zero-setup, single-user).
    # Production / multi-user: set DATABASE_URL=postgresql://… (enables
    # pgvector, concurrent writes, the literature KB).
    #
    # Legacy db_* fields preserved for back-compat with prior docker
    # compose envs. Set DATABASE_URL explicitly to override.
    database_url: str = ""  # empty → SQLite default
    db_password: str = "changeme"
    db_host: str = "db"
    db_port: int = 5432
    db_name: str = "e2er"
    db_user: str = "e2er"
    postgres_url: str | None = None  # legacy alias; overrides db_* if set

    @property
    def resolved_database_url(self) -> str:
        """The DB URL the client should actually use.

        Order of precedence (highest → lowest):
          1. ``database_url`` env var (most explicit)
          2. ``postgres_url`` env var (legacy alias)
          3. The composed ``postgresql://`` URL from db_* fields — ONLY
             if any db_* field was explicitly overridden (i.e., not the
             docker-only defaults). Otherwise falls through to SQLite.
          4. SQLite at ``~/.e2er/papers.db``.
        """
        if self.database_url:
            return self.database_url
        if self.postgres_url:
            return self.postgres_url
        # If the user has explicitly set ANY db_* field (i.e. they want
        # Postgres), compose the URL. Otherwise default to SQLite —
        # avoids tripping the "connect to docker DB called 'db'" failure
        # mode for fresh pip installs.
        defaults = (
            self.db_password == "changeme"
            and self.db_host == "db"
            and self.db_port == 5432
            and self.db_name == "e2er"
            and self.db_user == "e2er"
        )
        if not defaults:
            return f"postgresql://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"
        # Fall through to SQLite — empty string signals "use default".
        return ""

    # ── Data — Allium ─────────────────────────────────────────────────────────
    allium_api_key: str | None = None
    allium_api_base: str = "https://api.allium.so/api/v1"
    auto_approve_feasibility: bool = True
    max_queries_per_paper: int = 20
    max_rows_per_paper: int = 5_000_000

    # ── Data — FRED (Federal Reserve Economic Data) ───────────────────────────
    # Free key, ~30s to register at https://fredaccount.stlouisfed.org/apikey.
    # Without a key, FRED subcommands return a structured error envelope
    # pointing the user at the registration URL.
    fred_api_key: str | None = None

    @property
    def data_module_enabled(self) -> bool:
        return self.allium_api_key is not None

    # ── Local datasets + literature directory ────────────────────────────────
    # Single env var that holds the researcher's BYOD ("bring your own data")
    # corpus reusable across papers. Mixed content, extension-routed:
    #   *.csv / *.tsv / *.jsonl / *.parquet / *.xlsx / *.txt → data files,
    #     symlinked into `workspace/<paper_id>/data/` at paper creation so
    #     `_list_user_data` picks them up and specialists can `read_file`
    #     them through the standard sandbox.
    #   *.bib → additional BibTeX, parsed alongside LITERATURE_BIBTEX_FILE in
    #     `_load_reference_summary`.
    # When unset, both pathways are no-ops; everything that worked pre-v0.8
    # still works.
    local_data_dir: str | None = None
    # Walk subdirectories of LOCAL_DATA_DIR rather than only top-level files.
    # When True, file destinations under workspace/data/ preserve the
    # relative path from the corpus root (so a/raw/x.csv → workspace/data/a/raw/x.csv).
    local_data_dir_recursive: bool = False

    # ── Literature ────────────────────────────────────────────────────────────
    literature_bibtex_file: str | None = None
    semantic_scholar_api_key: str | None = None

    # Email used to identify this client to the OpenAlex / Crossref / Unpaywall
    # polite pools (all keyless, all ask for a contact in every request). Each
    # of those services prioritises requests from registered emails; the
    # default keeps us in the polite pool with a stable address.
    unpaywall_email: str = "research@e2er.app"

    # Zotero Web API (reference library). Set the key plus exactly one of
    # user_id / group_id. The library's bibliographic items are merged into
    # the reference summary alongside local .bib (see reference_libraries()).
    zotero_api_key: str | None = None
    zotero_user_id: str | None = None
    zotero_group_id: str | None = None

    @property
    def zotero_enabled(self) -> bool:
        return self.zotero_api_key is not None and (self.zotero_user_id is not None or self.zotero_group_id is not None)

    @property
    def literature_kb_enabled(self) -> bool:
        # The pgvector KB requires Postgres. Derive from the *resolved* URL so
        # the documented `DATABASE_URL=postgresql://…` path enables it — the
        # old check only looked at the legacy postgres_url/db_password fields
        # and left the KB silently off (keyword-only) for DATABASE_URL users.
        return self.resolved_database_url.startswith("postgres")

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
