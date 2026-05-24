"""`e2er init` — guided first-paper setup wizard.

Most of the wizard is interactive (driven by `input()`), so the
unit tests here focus on the deterministic surface: env-block
generation, prerequisite checks, the non-TTY exit path, and the
file-overwrite gate. Interactive behaviour is smoke-tested by
running the wizard manually before release.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from src.cli_init import (
    _BACKEND_CHOICES,
    _EXAMPLE_RQS,
    _check_backend_prereqs,
    _env_block,
    _write_env,
    init,
)

# ---------------------------------------------------------------------------
# Backend choice list — pin the order so the wizard's "default = claude_code"
# behaviour stays stable across edits.
# ---------------------------------------------------------------------------


class TestBackendChoices:
    def test_claude_code_is_first(self):
        """The first option is the default in `_ask_choice`. claude_code
        is the recommended backend (Max plan, $0/token) — it must remain
        index 0, otherwise new users get steered to a paid backend."""
        assert _BACKEND_CHOICES[0][0] == "claude_code"

    def test_all_known_backends_covered(self):
        """Wizard must cover every backend the runtime accepts."""
        backend_keys = {key for key, _ in _BACKEND_CHOICES}
        assert backend_keys == {
            "claude_code",
            "anthropic",
            "openrouter",
            "codex_cli",
            "gemini_cli",
        }

    def test_descriptions_mention_cost(self):
        """Each backend description must clue the user in on cost so
        they can choose without reading external docs."""
        for key, desc in _BACKEND_CHOICES:
            desc_lower = desc.lower()
            assert "token" in desc_lower or "free" in desc_lower or "$" in desc, (
                f"{key} description gives no cost signal: {desc!r}"
            )


# ---------------------------------------------------------------------------
# Prerequisite checks
# ---------------------------------------------------------------------------


class TestBackendPrereqs:
    def test_anthropic_ready_when_key_set(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        ready, notes = _check_backend_prereqs("anthropic")
        assert ready is True
        assert any("ANTHROPIC_API_KEY set" in n for n in notes)

    def test_anthropic_not_ready_when_key_missing(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        ready, notes = _check_backend_prereqs("anthropic")
        assert ready is False
        # User-facing string names the missing env var
        assert any("ANTHROPIC_API_KEY" in n for n in notes)
        # And the URL to get one
        assert any("console.anthropic.com" in n for n in notes)

    def test_openrouter_not_ready_when_key_missing(self, monkeypatch):
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        ready, notes = _check_backend_prereqs("openrouter")
        assert ready is False
        assert any("openrouter.ai" in n for n in notes)

    def test_claude_code_checks_for_claude_cli(self, monkeypatch):
        """When the `claude` binary is on PATH, claude_code is ready;
        when it isn't, the wizard surfaces the npm install command."""
        with patch("src.cli_init.shutil.which", return_value="/usr/local/bin/claude"):
            ready, notes = _check_backend_prereqs("claude_code")
        assert ready is True
        assert any("claude CLI found" in n for n in notes)

        with patch("src.cli_init.shutil.which", return_value=None):
            ready, notes = _check_backend_prereqs("claude_code")
        assert ready is False
        # The fix-it instruction is included
        assert any("npm i -g @anthropic-ai/claude-code" in n for n in notes)

    def test_codex_cli_checks_for_codex_binary(self):
        with patch("src.cli_init.shutil.which", return_value="/usr/local/bin/codex"):
            ready, _ = _check_backend_prereqs("codex_cli")
        assert ready is True
        with patch("src.cli_init.shutil.which", return_value=None):
            ready, notes = _check_backend_prereqs("codex_cli")
        assert ready is False
        assert any("npm i -g @openai/codex" in n for n in notes)

    def test_gemini_cli_checks_for_gemini_binary(self):
        with patch("src.cli_init.shutil.which", return_value=None):
            ready, notes = _check_backend_prereqs("gemini_cli")
        assert ready is False
        assert any("npm i -g @google/gemini-cli" in n for n in notes)


# ---------------------------------------------------------------------------
# .env body generation
# ---------------------------------------------------------------------------


class TestEnvBlock:
    def test_writes_chosen_backend(self):
        body = _env_block(
            backend="claude_code",
            use_data=False,
            bibtex_path="",
            database_url="",
            github_token_pat="",
            github_owner="",
        )
        assert "LLM_BACKEND=claude_code" in body

    def test_data_module_flag(self):
        on = _env_block("anthropic", True, "", "", "", "")
        off = _env_block("anthropic", False, "", "", "", "")
        assert "DATA_MODULE_ENABLED=true" in on
        assert "DATA_MODULE_ENABLED=false" in off

    def test_bibtex_path_only_when_set(self):
        with_bib = _env_block("anthropic", False, "/path/to/refs.bib", "", "", "")
        without_bib = _env_block("anthropic", False, "", "", "", "")
        assert "LITERATURE_BIBTEX_FILE=/path/to/refs.bib" in with_bib
        assert "LITERATURE_BIBTEX_FILE" not in without_bib

    def test_database_url_branches(self):
        sqlite = _env_block("anthropic", False, "", "", "", "")
        postgres = _env_block("anthropic", False, "", "postgresql://u:p@h/d", "", "")
        # SQLite path: DATABASE_URL is commented-out as a hint
        assert "SQLite default" in sqlite
        assert "# DATABASE_URL=postgresql" in sqlite
        # Postgres path: DATABASE_URL is uncommented and set
        assert "DATABASE_URL=postgresql://u:p@h/d" in postgres

    def test_anthropic_backend_includes_api_key_hint(self):
        body = _env_block("anthropic", False, "", "", "", "")
        # Hint comment for the API key — must NOT actually write the
        # key into .env (committed convention is shell env only).
        assert "# ANTHROPIC_API_KEY=" in body

    def test_openrouter_backend_includes_api_key_hint(self):
        body = _env_block("openrouter", False, "", "", "", "")
        assert "# OPENROUTER_API_KEY=" in body

    def test_data_module_includes_allium_key_hint(self):
        body = _env_block("anthropic", True, "", "", "", "")
        assert "# ALLIUM_API_KEY" in body

    def test_no_secrets_written_to_env(self):
        """Defensive: even when the user pasted a GitHub PAT during the
        wizard, the function must write it as a COMMENT, never as a
        live env line. Same for API keys (the function doesn't accept
        them — but pin the contract)."""
        body = _env_block(
            backend="anthropic",
            use_data=True,
            bibtex_path="",
            database_url="",
            github_token_pat="ghp_TESTTESTTEST",
            github_owner="user",
        )
        # The PAT appears commented out
        assert "# GITHUB_TOKEN=ghp_TESTTESTTEST" in body
        # No uncommented GITHUB_TOKEN= line
        for line in body.splitlines():
            stripped = line.lstrip()
            if stripped.startswith("GITHUB_TOKEN="):
                pytest.fail(f"GITHUB_TOKEN written as live env var, not a comment: {line!r}")


# ---------------------------------------------------------------------------
# Overwrite gate
# ---------------------------------------------------------------------------


class TestWriteEnvOverwrite:
    def test_creates_new_file(self, tmp_path: Path):
        env_path = tmp_path / ".env"
        ok = _write_env(env_path, "LLM_BACKEND=claude_code\n", force=False)
        assert ok is True
        assert env_path.read_text() == "LLM_BACKEND=claude_code\n"

    def test_force_overwrites_existing(self, tmp_path: Path):
        env_path = tmp_path / ".env"
        env_path.write_text("OLD=1\n")
        ok = _write_env(env_path, "NEW=2\n", force=True)
        assert ok is True
        assert env_path.read_text() == "NEW=2\n"

    def test_existing_file_without_force_prompts_user(self, tmp_path: Path):
        """Without --force, an existing .env triggers a confirmation
        prompt. When the user declines (answers 'n'), the file is left
        intact."""
        env_path = tmp_path / ".env"
        env_path.write_text("OLD=1\n")
        # Simulate the user typing 'n' at the overwrite prompt
        with patch("builtins.input", side_effect=["n"]):
            ok = _write_env(env_path, "NEW=2\n", force=False)
        assert ok is False
        assert env_path.read_text() == "OLD=1\n"

    def test_existing_file_overwritten_on_y(self, tmp_path: Path):
        env_path = tmp_path / ".env"
        env_path.write_text("OLD=1\n")
        with patch("builtins.input", side_effect=["y"]):
            ok = _write_env(env_path, "NEW=2\n", force=False)
        assert ok is True
        assert env_path.read_text() == "NEW=2\n"


# ---------------------------------------------------------------------------
# Non-TTY exit path
# ---------------------------------------------------------------------------


class TestNonTTYPath:
    def test_init_exits_with_helpful_message_when_stdin_not_a_tty(self, capsys):
        """`input()` in a non-interactive context (CI, piped, script)
        would block forever or raise — the wizard detects this and
        bails with exit code 2 and a one-line guide to the
        non-interactive setup steps."""
        with patch("src.cli_init._is_tty", return_value=False):
            code = init(force=False)
        assert code == 2
        captured = capsys.readouterr()
        assert "not a terminal" in captured.out
        # Should mention the manual fallback path
        assert "LLM_BACKEND" in captured.out
        assert "install-skills" in captured.out


# ---------------------------------------------------------------------------
# Example RQs
# ---------------------------------------------------------------------------


class TestExampleRQs:
    def test_at_least_three_examples(self):
        """The print-next-steps block lists numbered example RQs. Three
        is the minimum that demonstrates the range — empirical with
        crypto, empirical with macro, empirical with microstructure."""
        assert len(_EXAMPLE_RQS) >= 3

    def test_each_example_is_a_specific_question(self):
        """Every example must be a real, copy-pasteable RQ — not a
        placeholder like 'Does X affect Y?'."""
        for rq in _EXAMPLE_RQS:
            assert len(rq) > 50, f"Example RQ is too short to be a real question: {rq!r}"
            # No placeholder tokens
            for placeholder in ("<", ">", "TODO", "PLACEHOLDER"):
                assert placeholder not in rq, f"Example RQ contains placeholder {placeholder!r}: {rq!r}"
