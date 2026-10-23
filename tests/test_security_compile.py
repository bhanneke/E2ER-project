"""The paper's LaTeX is AI-written: the compiler reads no latexmkrc, escapes to no shell and reads
no file outside the workspace (security review 2026-10-23)."""

from __future__ import annotations

from src.core.renderer import compiler


def test_latexmk_reads_no_rc_file_and_runs_no_shell():
    cmd = compiler._build_cmd("latexmk", "paper.tex")
    assert cmd[:2] == ["latexmk", "-norc"] and "-no-shell-escape" in cmd
    assert "-no-shell-escape" in compiler._build_cmd("pdflatex", "paper.tex")
    assert "--untrusted" in compiler._build_cmd("tectonic", "paper.tex")


def test_tex_may_open_files_below_the_workspace_only_and_gets_no_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-FAKE")
    monkeypatch.setenv("SSH_AUTH_SOCK", "/tmp/agent")
    env = compiler.compile_env()
    assert env["openin_any"] == "p" and env["openout_any"] == "p"
    assert "ANTHROPIC_API_KEY" not in env and "SSH_AUTH_SOCK" not in env
