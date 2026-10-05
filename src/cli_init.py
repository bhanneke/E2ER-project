"""``e2er init`` — interactive setup wizard for new users.

Closes the post-`pip install e2er` gap. Without this command, the
new-user path is:

  1. pip install e2er
  2. Read the README to discover LLM_BACKEND, ANTHROPIC_API_KEY,
     DATABASE_URL, LITERATURE_BIBTEX_FILE, the first-run-cap
     acknowledgment, the backend-specific install (claude CLI,
     codex CLI, etc.)
  3. Manually create a `.env`, run `e2er skills sync`, then
     compose an `e2er run` command.

`e2er init` walks the user through the same decisions interactively
with sensible defaults, checks backend prerequisites, writes the
`.env`, runs `skills sync`, and prints concrete example
research questions to copy.

Hand-rolled stdin wizard — no new dependencies. TTY-detected so
non-interactive invocations exit with a helpful message rather
than blocking on `input()`.
"""

from __future__ import annotations

import os
import re
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


def ask_literature() -> dict[str, str]:
    """Ask for the researcher's literature until it resolves, or they leave it blank.

    Forgiving about how the path arrives (prompt glyph, quotes, drag-and-drop
    escapes, ~) and about what it is: a folder holding one .bib, a Zotero
    export or a folder of PDFs is offered for confirmation. Returns the .env
    settings for it ({} when skipped).
    """
    from .paths import resolve_bib_answer

    while True:
        raw = _ask("  Path to your .bib file or literature folder (blank to skip)", default="")
        if not raw.strip():
            return {}
        ans = resolve_bib_answer(raw)
        if ans.bib and ans.literature is not None:
            print(f"  ✓ Using {ans.bib} ({ans.literature.n_references} references)")
            return ans.literature.settings()
        if ans.ask and ans.literature is not None:
            if _ask_yes_no(f"  {ans.ask}", default=True):
                lit = ans.literature
                print(f"  ✓ Using {lit.path}" + (f" ({lit.summary()})" if lit.summary() else ""))
                return lit.settings()
            continue
        print(f"  ✗ {ans.error} Leave blank to skip.")


# ---------------------------------------------------------------------------
# Backend prerequisite checks
# ---------------------------------------------------------------------------


# Keys MUST match the config `llm_backend` Literal
# (anthropic|openrouter|claude_code|codex|gemini) — they are written
# verbatim as LLM_BACKEND into the generated .env. An earlier version
# used `codex_cli`/`gemini_cli` here, which produced a .env that fails
# Settings validation the moment it is loaded.
_BACKEND_CHOICES: list[tuple[str, str]] = [
    ("claude_code", "Anthropic Max plan ($0/token — recommended)"),
    ("anthropic", "Anthropic SDK (per-token API)"),
    ("openrouter", "OpenRouter (per-token, 200+ models)"),
    ("codex", "ChatGPT Plus/Pro ($0/token)"),
    ("gemini", "Google AI Pro/Ultra ($0/token)"),
]

_BACKEND_CLI_BINARY: dict[str, str] = {
    "claude_code": "claude",
    "codex": "codex",
    "gemini": "gemini",
}

_BACKEND_CLI_INSTALL: dict[str, str] = {
    "claude_code": "npm i -g @anthropic-ai/claude-code",
    "codex": "npm i -g @openai/codex",
    "gemini": "npm i -g @google/gemini-cli",
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


_DATA_DIR_README = """\
# Bring your own data

Drop datasets here (`.csv`, `.tsv`, `.jsonl`, `.parquet`, `.xlsx`, `.txt`).
At paper creation they are staged into the run's workspace and imported into
a per-paper `data.db` that specialists query with read-only SQL. Nothing here
is uploaded anywhere. `.bib` files here are also read as extra references.

Point the pipeline at a different folder by setting `LOCAL_DATA_DIR` in `.env`.
"""

_LIT_DIR_README = """\
# Bring your own papers

Drop your reference PDFs here, or point `LITERATURE_DIR` in `.env` at an
existing folder of PDFs or a Zotero library (a folder containing
`zotero.sqlite`). These are discovered and indexed for grounded citation and
retrieval at paper creation.

Your PDFs never leave this machine: exported paper bundles ship only the
BibTeX corpus (`refs.bib`), never the source PDFs. Full text can also resolve
open-access by DOI at run time, or you can supply a single BibTeX file via
`LITERATURE_BIBTEX_FILE`.
"""


def _scaffold_project_dirs(root: Path) -> tuple[Path, Path]:
    """Create ./data and ./literature with explanatory READMEs. Idempotent —
    never clobbers files the user has already added. Returns the two paths."""
    data_dir = root / "data"
    lit_dir = root / "literature"
    for d, readme in ((data_dir, _DATA_DIR_README), (lit_dir, _LIT_DIR_README)):
        d.mkdir(parents=True, exist_ok=True)
        readme_path = d / "README.md"
        if not readme_path.exists():
            readme_path.write_text(readme, encoding="utf-8")
    return data_dir, lit_dir


def _version() -> str:
    from . import __version__

    return __version__


#: The skills folder each CLI backend reads, as `install_skills` names it.
_SKILL_TARGETS = {"claude_code": "claude", "codex": "codex", "gemini": "gemini"}


def _copy_skills_for(backend: str, *, ask: bool) -> None:
    """Copy e2er's skill files into the chosen CLI backend's skills folder, and say so.

    Only the chosen backend: the other CLIs' folders are not e2er's to fill. The
    API backends read the skills from the package and need no copy. With
    ``ask``, the person confirms first.
    """
    target = _SKILL_TARGETS.get(backend)
    if target is None:
        print(f"  · no skill files copied: the {backend} backend reads them from the e2er package")
        return
    from .cli_install_skills import _backend_skills_dirs

    folder = _backend_skills_dirs(target)[0]
    if ask and not _ask_yes_no(
        f"Copy e2er's skill files into {folder}? The {backend} CLI reads them from there (existing files are kept)",
        default=True,
    ):
        print(f"  · skill files not copied; `e2er skills sync --backend {target}` copies them later")
        return
    print(f"Copying e2er's skill files into {folder} (the folder the {backend} CLI reads; existing files kept)...")
    try:
        from .cli_install_skills import install_skills as _install

        _install(backend=target, force=False)
    except Exception as e:  # noqa: BLE001 — best-effort; setup still succeeded
        print(f"  ! copying the skill files failed: {e} (run `e2er skills sync --backend {target}` later)")


def _env_block(
    backend: str,
    use_data: bool,
    bibtex_path: str,
    database_url: str,
    github_token_pat: str,
    github_owner: str,
    local_data_dir: str = "",
    literature_dir: str = "",
    *,
    model: tuple[str, str] | None = None,
    keys: dict[str, str] | None = None,
    purpose: str = "",
    written_by: str = "`e2er init`",
) -> str:
    """Assemble the `.env` body with comments so the user can edit later.

    `model` is a (setting, value) pair such as ("CLAUDE_CODE_MODEL", "haiku");
    `keys` are API keys the researcher typed into the setup page. The file is
    written owner-only (see `write_env_file`), so keys may live in it.
    """
    keys = {k: v for k, v in (keys or {}).items() if v}
    lines = [
        f"# e2er configuration (e2er {_version()}) — written by {written_by}",
        "# Re-run `e2er init` (or open Settings in the dashboard) to change it, or edit by hand.",
        "",
        "# ── LLM backend ──────────────────────────────────────────────────",
        f"LLM_BACKEND={backend}",
    ]
    if model and model[1]:
        lines.append(f"{model[0]}={model[1]}")
    if backend == "anthropic" and "ANTHROPIC_API_KEY" not in keys:
        lines.append("# ANTHROPIC_API_KEY=sk-ant-...   (set in shell env, not here)")
    elif backend == "openrouter" and "OPENROUTER_API_KEY" not in keys:
        lines.append("# OPENROUTER_API_KEY=sk-or-v1-... (set in shell env, not here)")
    lines.append("")

    if keys:
        lines.append("# ── Keys (this file is readable by you only) ─────────────────────")
        lines.extend(f"{k}={_env_quote(v)}" for k, v in keys.items())
        lines.append("")

    if purpose:
        lines.extend(
            ["# ── Purpose of the studies made here ─────────────────────────────", f"E2ER_PURPOSE={purpose}", ""]
        )

    if local_data_dir or literature_dir:
        lines.append("# ── Bring your own data + papers ─────────────────────────────────")
        if local_data_dir:
            lines.append(f"LOCAL_DATA_DIR={_env_quote(local_data_dir)}")
        if literature_dir:
            lines.append(f"LITERATURE_DIR={_env_quote(literature_dir)}")
        lines.append("")

    # The Allium data module enables itself whenever ALLIUM_API_KEY is
    # present (config.data_module_enabled is derived from the key) — there
    # is no DATA_MODULE_ENABLED setting, so we only leave a pointer here.
    lines.append("# ── Data module (Allium blockchain warehouse) ────────────────────")
    if use_data:
        lines.append("# Set ALLIUM_API_KEY in your shell env to enable it:")
        lines.append("#   export ALLIUM_API_KEY=...")
    else:
        lines.append("# Literature-only run. To add Allium blockchain data later, set")
        lines.append("#   export ALLIUM_API_KEY=...   (yfinance + FRED need no key)")
    lines.append("")

    if bibtex_path:
        lines.extend(
            [
                "# ── Literature (BibTeX) ──────────────────────────────────────────",
                f"LITERATURE_BIBTEX_FILE={_env_quote(bibtex_path)}",
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

    if github_owner:
        # config uses GITHUB_USERNAME (+ optional GITHUB_ORG), and
        # github_enabled requires GITHUB_USERNAME plus GITHUB_TOKEN. The
        # earlier GITHUB_OWNER key was silently ignored.
        lines.extend(
            [
                "# ── GitHub (per-paper repo + Overleaf-ready push) ────────────────",
                f"GITHUB_USERNAME={github_owner}",
                "# If pushing to an organization instead of your user account,",
                f"#   GITHUB_ORG={github_owner}",
                "# Set the token in your shell env (never commit it):",
                f"#   export GITHUB_TOKEN={github_token_pat or '<personal-access-token-with-repo-scope>'}",
                "",
            ]
        )

    return "\n".join(lines) + "\n"


def _env_quote(value: str) -> str:
    """A value as python-dotenv reads it back: quoted when it holds spaces, quotes, # or =."""
    if value and not re.search(r"[\s'\"#=\\$]", value):
        return value
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def write_env_file(env_path: Path, content: str) -> None:
    """Write the settings file readable and writable by its owner only (mode 600).

    It may hold API keys. Created with that mode rather than chmod-ed after,
    so there is no moment in which another user could read it.
    """
    env_path = Path(env_path)
    tmp = env_path.with_name(env_path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(content)
    os.chmod(tmp, 0o600)
    os.replace(tmp, env_path)
    os.chmod(env_path, 0o600)


def _write_env(env_path: Path, content: str, force: bool) -> bool:
    """Write `.env` with confirm-overwrite semantics. Returns True iff written."""
    if env_path.exists() and not force:
        print(f"\n  ! {env_path} already exists.")
        if not _ask_yes_no("    Overwrite?", default=False):
            print("    Keeping the existing file. Edit it by hand if needed.")
            return False
    write_env_file(env_path, content)
    print(f"  ✓ Wrote {env_path}")
    return True


# ---------------------------------------------------------------------------
# Wizard
# ---------------------------------------------------------------------------


def _init_defaults() -> int:
    """Non-interactive setup (`e2er init --defaults`). Scaffolds data/ +
    literature/, writes a claude_code .env, copies the skill files for Claude Code. Safe in CI /
    non-TTY — never calls input()."""
    root = Path.cwd()
    print("e2er init --defaults — non-interactive setup")
    data_dir, lit_dir = _scaffold_project_dirs(root)
    print(f"  ✓ scaffolded {data_dir}/ and {lit_dir}/ (drop your data + PDFs there)")
    content = _env_block(
        backend="claude_code",
        use_data=False,
        bibtex_path="",
        database_url="",
        github_token_pat="",
        github_owner="",
        local_data_dir="./data",
        literature_dir="./literature",
    )
    _write_env(root / ".env", content, force=True)
    _copy_skills_for("claude_code", ask=False)
    print('  ✓ ready — verify with `e2er doctor`, then `e2er run "<your RQ>"`')
    return 0


def init(force: bool = False, defaults: bool = False) -> int:
    """Entry point for `e2er init`. Returns shell exit code."""
    if defaults:
        return _init_defaults()
    if not _is_tty():
        print(
            "e2er init: stdin is not a terminal. Re-run with `e2er init --defaults` "
            "for non-interactive setup, or set LLM_BACKEND in your shell + "
            '`e2er skills sync` + `e2er run "<your RQ>" --methodology empirical`.'
        )
        return 2

    print()
    print("┌──────────────────────────────────────────────────────────────────┐")
    print("│  e2er init — first-paper setup wizard                            │")
    print("│  ~1 minute. Writes .env, copies skills, prints next steps.       │")
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
        "  e2er can run literature-only (no external data), or use Allium\n"
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
        "  Your own references: a .bib file (e.g. exported from Zotero or\n"
        "  Mendeley), a Zotero export folder, or a folder of PDFs. You can\n"
        "  drag the file or folder into this window."
    )
    bibtex = ""
    literature_dir = "./literature"
    if _ask_yes_no("Configure your literature now?", default=False):
        chosen = ask_literature()
        if chosen:
            bibtex = chosen.get("LITERATURE_BIBTEX_FILE", "")
            literature_dir = chosen.get("LITERATURE_DIR", literature_dir)
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

    # Scaffold the bring-your-own-data + papers folders so `e2er doctor`
    # and the pipeline have somewhere to look (idempotent; never clobbers).
    _scaffold_project_dirs(Path.cwd())
    print("  ✓ data/ and literature/ ready (drop your datasets + PDFs there)")

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
        local_data_dir="./data",
        literature_dir=literature_dir,
    )
    _write_env(env_path, content, force=force)

    # Skill files: only into the chosen CLI backend's folder, after asking.
    print()
    _copy_skills_for(backend, ask=True)

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
