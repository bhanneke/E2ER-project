"""M1: ``e2er doctor`` — preflight checks + output formatting."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.doctor import (
    FAIL,
    PASS,
    SKIP,
    Check,
    backend_check,
    byod_literature_check,
    byod_local_data_check,
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


# ── BYOD corpus checks (pure-local, no network) ─────────────────────────────


def _byod_settings(**kw):
    """Settings stub for the BYOD checks. resolved_literature_dirs is a
    method on the real Settings, so mirror it as a callable here."""
    base = dict(
        local_data_dir=None,
        local_data_dir_recursive=False,
        literature_bibtex_file=None,
        literature_dir=None,
    )
    base.update(kw)
    ldir = base.get("literature_dir")
    ldata = base.get("local_data_dir")
    ns = SimpleNamespace(**base)
    ns.resolved_literature_dirs = lambda: ldir or ldata
    return ns


async def test_byod_local_data_unset_skips():
    c = await byod_local_data_check(_byod_settings())
    assert c.status == SKIP


async def test_byod_local_data_missing_dir_fails(tmp_path):
    c = await byod_local_data_check(_byod_settings(local_data_dir=str(tmp_path / "nope")))
    assert c.status == FAIL and "not a directory" in c.detail


async def test_byod_local_data_empty_dir_skips(tmp_path):
    c = await byod_local_data_check(_byod_settings(local_data_dir=str(tmp_path)))
    assert c.status == SKIP


async def test_byod_local_data_counts_files(tmp_path):
    (tmp_path / "a.csv").write_text("x\n")
    (tmp_path / "b.csv").write_text("x\n")
    (tmp_path / "c.parquet").write_bytes(b"\x00")
    (tmp_path / "ignore.md").write_text("x\n")
    c = await byod_local_data_check(_byod_settings(local_data_dir=str(tmp_path)))
    assert c.status == PASS
    assert "2 csv" in c.detail and "1 parquet" in c.detail


async def test_byod_local_data_recursive(tmp_path):
    sub = tmp_path / "raw"
    sub.mkdir()
    (sub / "deep.csv").write_text("x\n")
    top = await byod_local_data_check(_byod_settings(local_data_dir=str(tmp_path)))
    assert top.status == SKIP  # top-level scan misses the nested file
    rec = await byod_local_data_check(_byod_settings(local_data_dir=str(tmp_path), local_data_dir_recursive=True))
    assert rec.status == PASS and "1 csv" in rec.detail


async def test_byod_literature_nothing_skips():
    c = await byod_literature_check(_byod_settings())
    assert c.status == SKIP


async def test_byod_literature_bibtex_counts_entries(tmp_path):
    bib = tmp_path / "refs.bib"
    bib.write_text("@article{a, title={A}}\n@book{b, title={B}}\n")
    c = await byod_literature_check(_byod_settings(literature_bibtex_file=str(bib)))
    assert c.status == PASS and "2 entries" in c.detail


async def test_byod_literature_missing_bibtex_fails(tmp_path):
    c = await byod_literature_check(_byod_settings(literature_bibtex_file=str(tmp_path / "gone.bib")))
    assert c.status == FAIL


async def test_byod_literature_pdf_folder(tmp_path):
    (tmp_path / "p1.pdf").write_bytes(b"%PDF")
    (tmp_path / "p2.pdf").write_bytes(b"%PDF")
    c = await byod_literature_check(_byod_settings(literature_dir=str(tmp_path)))
    assert c.status == PASS and "2 PDFs" in c.detail


async def test_byod_literature_ignores_an_empty_fallback_dir(tmp_path):
    """resolved_literature_dirs() falls back to LOCAL_DATA_DIR, so a user who
    configured only a .bib would otherwise see their data folder reported as a
    miss appended to a passing check."""
    bib = tmp_path / "refs.bib"
    bib.write_text("@article{a, title={A}}\n")
    data = tmp_path / "data"
    data.mkdir()
    (data / "prices.csv").write_text("x\n")

    c = await byod_literature_check(_byod_settings(literature_bibtex_file=str(bib), literature_dir=str(data)))

    assert c.status == PASS
    assert c.detail == "bibtex (1 entries)"
    assert "no PDFs" not in c.detail


async def test_byod_literature_zotero_detected(tmp_path):
    (tmp_path / "zotero.sqlite").write_bytes(b"\x00")
    c = await byod_literature_check(_byod_settings(literature_dir=str(tmp_path)))
    assert c.status == PASS and "Zotero" in c.detail


# ── CLI integration: `e2er doctor` (via the __main__ argparse) ──────────────


def test_cli_doctor_subcommand_registered():
    """argparse must accept `doctor` (and `doctor --json`) without crashing."""
    import subprocess
    import sys

    # Subcommand must be listed in the top-level help.
    r = subprocess.run([sys.executable, "-m", "src", "--help"], capture_output=True, text=True, timeout=15)
    assert r.returncode == 0
    assert "doctor" in r.stdout


# ── workspace writability under a CLI backend ────────────────────────────────


def _ws_settings(**kw):
    base = {"llm_backend": "claude_code", "workspace_root": "/tmp/e2er-ws"}
    base.update(kw)
    return SimpleNamespace(**base)


def test_workspace_inside_the_cli_config_tree_is_a_failure(tmp_path, monkeypatch):
    """~/.claude is the Claude Code CLI's own tree and it refuses writes there.

    The pipeline process can write to it perfectly well, so nothing looks wrong
    until every specialist fails its contract with "file not written" — the same
    message a model that ignored its contract produces. It cost a 53-minute run
    to diagnose once.
    """
    from src.doctor import workspace_writable_check

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    root = tmp_path / ".claude" / "jobs" / "abc" / "tmp" / "project" / "workspaces"
    root.mkdir(parents=True)

    check = workspace_writable_check(_ws_settings(workspace_root=str(root)))

    assert check.status == FAIL
    assert "refuses writes" in check.detail


def test_workspace_outside_the_config_tree_passes(tmp_path, monkeypatch):
    from src.doctor import workspace_writable_check

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    root = tmp_path / "research" / "workspaces"
    root.mkdir(parents=True)

    check = workspace_writable_check(_ws_settings(workspace_root=str(root)))
    assert check.status == PASS


def test_sdk_backends_have_no_cli_permission_rules(tmp_path, monkeypatch):
    """The restriction belongs to the CLI subprocess, not the filesystem, so an
    in-process backend is unaffected even under ~/.claude."""
    from src.doctor import workspace_writable_check

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    root = tmp_path / ".claude" / "workspaces"
    root.mkdir(parents=True)

    check = workspace_writable_check(_ws_settings(llm_backend="anthropic", workspace_root=str(root)))
    assert check.status == PASS


def test_an_unwritable_workspace_blocks_the_run():
    """A run cannot succeed without a writable workspace, so it is a blocker
    rather than a warning."""
    from src.doctor import _BLOCKERS_PREFIXES

    assert any("workspace" in prefix for prefix in _BLOCKERS_PREFIXES)
