"""``e2er init`` — interactive setup wizard for new users.

Closes the post-`pip install e2er` gap. Without this command, the
new-user path is:

  1. pip install e2er
  2. Read the README to discover LLM_BACKEND, ANTHROPIC_API_KEY,
     DATABASE_URL, LITERATURE_BIBTEX_FILE, the first-run-cap
     acknowledgment, the backend-specific install (claude CLI,
     codex CLI, etc.)
  3. Manually create a `.env`, run `e2er install-skills`, then
     compose an `e2er run` command.

`e2er init` walks the user through the same decisions interactively
with sensible defaults, checks backend prerequisites, writes the
`.env`, runs `install-skills`, and prints concrete example
research questions to copy.

Hand-rolled stdin wizard — no new dependencies. TTY-detected so
non-interactive invocations exit with a helpful message rather
than blocking on `input()`.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Small prompt helpers
# ---------------------------------------------------------------------------


def _is_tty() -> bool:
    """Return True iff stdin is a real terminal — required for `input()`.

    Avoids blocking when this command is invoked from a script, CI, or
    piped input. The non-TTY path prints next steps and exits.
    """
    return sys.stdin.isatty() and sys.stdout.isatty()


def _ask(prompt: str, default: str = "") -> str:
    """Read a line with a default shown in brackets. Returns the user
    input or `default` if they hit Enter."""
    hint = f" [{default}]" if default else ""
    raw = input(f"{prompt}{hint}: ").strip()
    return raw or default


def _ask_choice(prompt: str, choices: list[tuple[str, str]], default_index: int = 0) -> str:
    """Numbered-choice prompt. Returns the selected key.

    `choices` is a list of (key, description) tuples. The user enters
    a number; defaults to `default_index + 1` if they hit Enter.
    """
    print(prompt)
    for i, (key, desc) in enumerate(choices, 1):
        marker = " (default)" if i - 1 == default_index else ""
        print(f"  {i}) {key:<14}  {desc}{marker}")
    while True:
        raw = input(f"> [1-{len(choices)}, default {default_index + 1}]: ").strip()
        if not raw:
            return choices[default_index][0]
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(choices):
                return choices[idx][0]
        except ValueError:
            pass
        print(f"  Please enter a number between 1 and {len(choices)}.")


def _ask_yes_no(prompt: str, default: bool = False) -> bool:
    hint = " [Y/n]" if default else " [y/N]"
    while True:
        raw = input(f"{prompt}{hint}: ").strip().lower()
        if not raw:
            return default
        if raw in {"y", "yes"}:
            return True
        if raw in {"n", "no"}:
            return False
        print("  Please answer y or n.")


# ---------------------------------------------------------------------------
# Backend prerequisite checks
# ---------------------------------------------------------------------------


_BACKEND_CHOICES: list[tuple[str, str]] = [
    ("claude_code", "Anthropic Max plan ($0/token — recommended)"),
    ("anthropic", "Anthropic SDK (per-token API)"),
    ("openrouter", "OpenRouter (per-token, 200+ models)"),
    ("codex_cli", "ChatGPT Plus/Pro ($0/token)"),
    ("gemini_cli", "Google AI Pro/Ultra ($0/token)"),
]

_BACKEND_CLI_BINARY: dict[str, str] = {
    "claude_code": "claude",
    "codex_cli": "codex",
    "gemini_cli": "gemini",
}

_BACKEND_CLI_INSTALL: dict[str, str] = {
    "claude_code": "npm i -g @anthropic-ai/claude-code",
    "codex_cli": "npm i -g @openai/codex",
    "gemini_cli": "npm i -g @google/gemini-cli",
}


def _check_backend_prereqs(backend: str) -> tuple[bool, list[str]]:
    """Return (ready_to_use, notes).

    Notes are user-facing strings printed during the wizard so the
    user knows what (if anything) they still need to do.
    """
    notes: list[str] = []
    ready = True

    if backend in _BACKEND_CLI_BINARY:
        binary = _BACKEND_CLI_BINARY[backend]
        if shutil.which(binary):
            notes.append(f"  ✓ {binary} CLI found")
        else:
            ready = False
            install_cmd = _BACKEND_CLI_INSTALL[backend]
            notes.append(f"  ✗ {binary} CLI not on PATH")
            notes.append(f"     install: {install_cmd}")

    if backend == "anthropic":
        if os.environ.get("ANTHROPIC_API_KEY"):
            notes.append("  ✓ ANTHROPIC_API_KEY set in env")
        else:
            ready = False
            notes.append("  ✗ ANTHROPIC_API_KEY not set")
            notes.append("     get one: https://console.anthropic.com/")
    elif backend == "openrouter":
        if os.environ.get("OPENROUTER_API_KEY"):
            notes.append("  ✓ OPENROUTER_API_KEY set in env")
        else:
            ready = False
            notes.append("  ✗ OPENROUTER_API_KEY not set")
            notes.append("     get one: https://openrouter.ai/keys")

    return ready, notes


# ---------------------------------------------------------------------------
# `.env` writing
# ---------------------------------------------------------------------------


_EXAMPLE_RQS: list[str] = [
    "Does the introduction of concentrated liquidity (Uniswap v3) reduce "
    "impermanent loss for liquidity providers relative to constant-product "
    "(Uniswap v2) pools, conditional on similar trading volume?",
    "Has the January 2024 spot-Bitcoin-ETF approval reduced the persistence "
    "of Bitcoin's high-volatility regime relative to the pre-approval window?",
    "Do automated market makers exhibit higher pricing efficiency than "
    "centralized exchanges during the first hour after a major token "
    "listing, measured by cross-venue mid-price spread variance?",
]


def _env_block(
    backend: str,
    use_data: bool,
    bibtex_path: str,
    database_url: str,
    github_token_pat: str,
    github_owner: str,
) -> str:
    """Assemble the `.env` body with comments so the user can edit later."""
    lines = [
        "# E2ER v3 configuration — written by `e2er init`",
        "# Re-run `e2er init` to overwrite, or edit by hand.",
        "",
        "# ── LLM backend ──────────────────────────────────────────────────",
        f"LLM_BACKEND={backend}",
    ]
    if backend == "anthropic":
        lines.append("# ANTHROPIC_API_KEY=sk-ant-...   (set in shell env, not here)")
    elif backend == "openrouter":
        lines.append("# OPENROUTER_API_KEY=sk-or-v1-... (set in shell env, not here)")
    lines.append("")

    lines.extend(
        [
            "# ── Data module ──────────────────────────────────────────────────",
            f"DATA_MODULE_ENABLED={'true' if use_data else 'false'}",
        ]
    )
    if use_data:
        lines.append("# ALLIUM_API_KEY=...           (set in shell env, not here)")
    lines.append("")

    if bibtex_path:
        lines.extend(
            [
                "# ── Literature (BibTeX) ──────────────────────────────────────────",
                f"LITERATURE_BIBTEX_FILE={bibtex_path}",
                "",
            ]
        )

    if database_url:
        lines.extend(
            [
                "# ── Database (Postgres) ──────────────────────────────────────────",
                f"DATABASE_URL={database_url}",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "# ── Database (SQLite default — auto-created at ~/.e2er/papers.db) ─",
                "# DATABASE_URL=postgresql://...   (uncomment to switch to Postgres)",
                "",
            ]
        )

    if github_token_pat and github_owner:
        lines.extend(
            [
                "# ── GitHub (per-paper repo + Overleaf-ready push) ────────────────",
                f"# GITHUB_TOKEN={github_token_pat}",
                f"GITHUB_OWNER={github_owner}",
                "# Move GITHUB_TOKEN to your shell env (not committed):",
                f"#   export GITHUB_TOKEN={github_token_pat}",
                "",
            ]
        )

    return "\n".join(lines) + "\n"


def _write_env(env_path: Path, content: str, force: bool) -> bool:
    """Write `.env` with confirm-overwrite semantics. Returns True iff written."""
    if env_path.exists() and not force:
        print(f"\n  ! {env_path} already exists.")
        if not _ask_yes_no("    Overwrite?", default=False):
            print("    Keeping the existing file. Edit it by hand if needed.")
            return False
    env_path.write_text(content, encoding="utf-8")
    print(f"  ✓ Wrote {env_path}")
    return True


# ---------------------------------------------------------------------------
# Wizard
# ---------------------------------------------------------------------------


def init(force: bool = False) -> int:
    """Entry point for `e2er init`. Returns shell exit code."""
    if not _is_tty():
        print(
            "e2er init: stdin is not a terminal. Run interactively, or "
            "set LLM_BACKEND in your shell + `e2er install-skills` + "
            '`e2er run "<your RQ>" --methodology empirical`.'
        )
        return 2

    print()
    print("┌──────────────────────────────────────────────────────────────────┐")
    print("│  e2er init — first-paper setup wizard                            │")
    print("│  ~1 minute. Writes .env, bundles skills, prints next steps.      │")
    print("└──────────────────────────────────────────────────────────────────┘")
    print()

    # 1. LLM backend
    print("Step 1/4 — Pick an LLM backend.")
    backend = _ask_choice(
        "Which backend will you use?",
        _BACKEND_CHOICES,
        default_index=0,
    )
    print()
    print(f"Checking prerequisites for {backend}...")
    ready, notes = _check_backend_prereqs(backend)
    for line in notes:
        print(line)
    if not ready:
        print()
        print("  ⚠ Backend is not ready yet — the wizard will still write")
        print("    your config, but `e2er run` will fail until you finish")
        print("    the install / set the API key.")
    print()

    # 2. Data module
    print("Step 2/4 — Data sources.")
    print(
        "  E2ER can run literature-only (no external data), or use Allium\n"
        "  for blockchain data. yfinance + FRED are always available and\n"
        "  don't need keys."
    )
    use_data = _ask_yes_no("Enable the Allium data module?", default=False)
    if use_data:
        print(
            "  → Set ALLIUM_API_KEY in your shell env before running.\n"
            "    Free tier exists; production tables need a paid plan."
        )
    print()

    # 3. Literature
    print("Step 3/4 — Literature (optional).")
    print(
        "  E2ER does not auto-fetch papers. Supply your own BibTeX file\n"
        "  (e.g. exported from Zotero / Mendeley) for grounded citations."
    )
    bibtex = ""
    if _ask_yes_no("Configure a BibTeX file now?", default=False):
        while True:
            path = _ask("  Path to .bib file", default="")
            if not path:
                break
            expanded = Path(path).expanduser()
            if expanded.is_file():
                bibtex = str(expanded.resolve())
                print(f"  ✓ Using {bibtex}")
                break
            print(f"  ✗ Not found: {expanded}. Leave blank to skip.")
    print()

    # 4. Database (advanced — most users skip)
    print("Step 4/4 — Database (advanced).")
    print(
        "  SQLite (default) is created automatically at ~/.e2er/papers.db.\n"
        "  Postgres is only needed for multi-user / pgvector literature KB."
    )
    database_url = ""
    if _ask_yes_no("Configure a Postgres DATABASE_URL?", default=False):
        database_url = _ask("  DATABASE_URL", default="postgresql://e2er:e2er_dev@127.0.0.1:5432/e2er")
    print()

    # GitHub integration is optional and not in the main 4-step flow
    # — added at the end so it's there if the user wants it, but no
    # prompt-spam if they don't.
    github_token_pat = ""
    github_owner = ""
    if _ask_yes_no(
        "Set up GitHub integration (auto-push each paper to its own repo)?",
        default=False,
    ):
        github_owner = _ask("  Your GitHub username or org", default="")
        github_token_pat = _ask(
            "  Personal access token (with `repo` scope) — paste here OR leave blank to set via shell env",
            default="",
        )
    print()

    # Write .env
    print("Writing config...")
    env_path = Path.cwd() / ".env"
    content = _env_block(
        backend=backend,
        use_data=use_data,
        bibtex_path=bibtex,
        database_url=database_url,
        github_token_pat=github_token_pat,
        github_owner=github_owner,
    )
    _write_env(env_path, content, force=force)

    # Install skills (always — costs nothing and is required for CLI backends)
    print()
    print("Bundling skill files for headless CLI backends...")
    try:
        from .cli_install_skills import install_skills as _install

        _install(backend="all", force=False)
    except Exception as e:
        print(f"  ! install-skills failed: {e}")
        print("    Run `e2er install-skills` manually after install.")

    # Postgres migrate hint (don't auto-run; the user may need to start the DB first)
    if database_url:
        print()
        print("Postgres is configured. After your DB is up, run:\n  e2er migrate")

    # Next steps + example RQs
    print()
    print("┌──────────────────────────────────────────────────────────────────┐")
    print("│  Setup complete. Try your first paper:                           │")
    print("└──────────────────────────────────────────────────────────────────┘")
    print()
    print('  e2er run "<your research question>" \\')
    print("    --methodology empirical \\")
    print("    --mode single_pass \\")
    print("    --max-cost 5")
    print()
    print("Or copy one of these example research questions:")
    for i, rq in enumerate(_EXAMPLE_RQS, 1):
        # Wrap long lines at ~70 chars for readability
        words = rq.split()
        lines: list[str] = []
        current = ""
        for w in words:
            if len(current) + len(w) + 1 > 70:
                lines.append(current)
                current = w
            else:
                current = f"{current} {w}".strip()
        if current:
            lines.append(current)
        print(f"\n  {i}) {lines[0]}")
        for line in lines[1:]:
            print(f"     {line}")

    print()
    print("Dashboard (after first `e2er run`): http://127.0.0.1:8280")
    print("Docs: https://github.com/bhanneke/E2ER-project#readme")
    print()
    print(
        "Tip: `e2er run` already acknowledges the first-run guardrail for you.\n"
        "If you POST directly to /api/papers, include\n"
        '  "acknowledge_unproven_tuple": true\n'
        "in the body to lift the $1 first-run cap on unproven tuples.\n"
    )
    return 0
