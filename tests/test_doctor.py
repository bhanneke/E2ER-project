"""M1: ``e2er doctor`` — preflight checks + output formatting."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.doctor import (
    FAIL,
    PASS,
    Check,
    backend_check,
    db_check,
    main_doctor,
    render_human,
    skills_check,
)

# ── backend_check ────────────────────────────────────────────────────────────


async def test_backend_anthropic_no_key_fails():
    s = SimpleNamespace(llm_backend="anthropic", anthropic_api_key=None)
    c = await backend_check(s)
    assert c.status == FAIL and "ANTHROPIC_API_KEY" in c.detail


async def test_backend_anthropic_with_key_passes():
    s = SimpleNamespace(llm_backend="anthropic", anthropic_api_key="sk-ant-x")
    c = await backend_check(s)
    assert c.status == PASS


async def test_backend_openrouter_with_key_passes():
    s = SimpleNamespace(llm_backend="openrouter", openrouter_api_key="sk-or-x")
    c = await backend_check(s)
    assert c.status == PASS


async def test_backend_claude_code_not_installed_fails():
    s = SimpleNamespace(llm_backend="claude_code")
    with patch("src.doctor.shutil.which", return_value=None):
        c = await backend_check(s)
    assert c.status == FAIL and "not on PATH" in c.detail


async def test_backend_claude_code_installed_passes():
    s = SimpleNamespace(llm_backend="claude_code")
    with patch("src.doctor.shutil.which", return_value="/usr/local/bin/claude"):
        c = await backend_check(s)
    assert c.status == PASS and "/usr/local/bin/claude" in c.detail


# ── skills_check + db_check ──────────────────────────────────────────────────


async def test_skills_check_passes():
    c = await skills_check(SimpleNamespace())
    assert c.status == PASS


async def test_db_check_sqlite_default():
    s = SimpleNamespace(resolved_database_url="")
    c = await db_check(s)
    assert c.status == PASS and "SQLite" in c.detail


# ── render_human verdict logic ───────────────────────────────────────────────


def test_render_human_all_pass_says_ready():
    checks = [Check("backend.anthropic", PASS, "key"), Check("data.yfinance.history", PASS, "ok")]
    out = render_human(checks)
    assert "Ready" in out and "0 failed" in out


def test_render_human_blocker_fail_says_blocked():
    # A backend FAIL is a blocker — the user can't run a paper.
    checks = [
        Check("backend.claude_code", FAIL, "not on PATH"),
        Check("data.yfinance.history", PASS, "ok"),
    ]
    out = render_human(checks)
    assert "Blocked" in out


def test_render_human_only_provider_fail_says_partial():
    # Provider failures degrade gracefully — paper runs still work without them.
    checks = [
        Check("backend.anthropic", PASS, "key"),
        Check("db", PASS, "sqlite"),
        Check("data.allium.list_tables", FAIL, "credits"),
    ]
    out = render_human(checks)
    assert "Partial" in out


# ── main_doctor exit codes + output mode ─────────────────────────────────────


def test_main_doctor_returns_zero_when_no_failures(capsys):
    fake = [Check("x", PASS, "ok")]
    with (
        patch("src.doctor.run_doctor", new=AsyncMock(return_value=fake)),
        patch("src.config.get_settings", return_value=SimpleNamespace()),
    ):
        rc = main_doctor(json_output=False)
    assert rc == 0
    assert "Ready" in capsys.readouterr().out


def test_main_doctor_returns_one_when_any_failure(capsys):
    fake = [Check("x", FAIL, "broken")]
    with (
        patch("src.doctor.run_doctor", new=AsyncMock(return_value=fake)),
        patch("src.config.get_settings", return_value=SimpleNamespace()),
    ):
        rc = main_doctor(json_output=False)
    assert rc == 1


def test_main_doctor_json_mode_emits_json(capsys):
    fake = [Check("x", PASS, "ok")]
    with (
        patch("src.doctor.run_doctor", new=AsyncMock(return_value=fake)),
        patch("src.config.get_settings", return_value=SimpleNamespace()),
    ):
        main_doctor(json_output=True)
    import json as _j

    payload = _j.loads(capsys.readouterr().out)
    assert payload["checks"][0]["name"] == "x"


# ── CLI integration: `e2er doctor` (via the __main__ argparse) ──────────────


def test_cli_doctor_subcommand_registered():
    """argparse must accept `doctor` (and `doctor --json`) without crashing."""
    import subprocess
    import sys

    # Subcommand must be listed in the top-level help.
    r = subprocess.run([sys.executable, "-m", "src", "--help"], capture_output=True, text=True, timeout=15)
    assert r.returncode == 0
    assert "doctor" in r.stdout
