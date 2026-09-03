"""The literature CLI bridge (`e2er-lit`) and the citable-key prompt block.

Why these exist: `ClaudeCodeBackend.tool_loop` ignores the `tools` argument, so
LITERATURE_TOOLS are unreachable on every CLI backend. In the 2026-09-01
repeats cell no run wrote a bibliography at all and both reviewed drafts cited
real papers from memory that nothing backed. These tests pin the two halves of
the fix: the bridge that lets a specialist record references, and the prompt
block that tells it which keys exist without relying on a tool call.

No network: the search path is exercised live elsewhere; here we cover the
offline surface (list, budgets, parsing).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.core.specialists.base import _workspace_bib_for_prompt
from src.modules.literature.cli import _bib_keys, _load_budget, _save_budget, build_parser

REPO_ROOT = Path(__file__).resolve().parent.parent
WRAPPER = REPO_ROOT / "scripts" / "e2er-lit"

BIB = """@article{lycsa2020impact,
  title = {Impact of macroeconomic news on the volatility of bitcoin},
  author = {Lyocsa, S.},
  year = {2020},
  doi = {10.1016/j.jedc.2020.103980},
}

@article{alexander2020price,
  title = {Price discovery in Bitcoin: The impact of unregulated markets},
  author = {Alexander, C.},
  year = {2020},
}
"""


# ── bib parsing ──────────────────────────────────────────────────────────────


def test_bib_keys_reads_entries(tmp_path: Path):
    (tmp_path / "literature.bib").write_text(BIB, encoding="utf-8")
    assert _bib_keys(tmp_path) == ["alexander2020price", "lycsa2020impact"]


def test_bib_keys_absent_file_is_empty(tmp_path: Path):
    assert _bib_keys(tmp_path) == []


# ── budgets survive across processes ─────────────────────────────────────────


def test_budget_roundtrips_per_specialist(tmp_path: Path):
    _save_budget(tmp_path, "literature_scanner", {"search": 3, "fetch": 1, "save": 0, "read": 0})
    _save_budget(tmp_path, "paper_drafter", {"search": 1, "fetch": 0, "save": 0, "read": 0})

    assert _load_budget(tmp_path, "literature_scanner")["search"] == 3
    assert _load_budget(tmp_path, "paper_drafter")["search"] == 1
    assert _load_budget(tmp_path, "never_ran") == {}


def test_budget_survives_a_corrupt_file(tmp_path: Path):
    """One bash call is one process, so a half-written counter file must not
    take down the next invocation."""
    (tmp_path / ".lit_budget.json").write_text("{not json", encoding="utf-8")
    assert _load_budget(tmp_path, "literature_scanner") == {}
    _save_budget(tmp_path, "literature_scanner", {"search": 1})
    assert _load_budget(tmp_path, "literature_scanner")["search"] == 1


# ── the citable-key prompt block ─────────────────────────────────────────────


def _with_workspace_root(tmp_path: Path):
    return patch("src.config.get_settings", return_value=SimpleNamespace(workspace_root=str(tmp_path)))


def test_prompt_block_lists_the_citable_keys(tmp_path: Path):
    ws = tmp_path / "paper-1"
    ws.mkdir()
    (ws / "literature.bib").write_text(BIB, encoding="utf-8")

    with _with_workspace_root(tmp_path):
        out = _workspace_bib_for_prompt("paper_drafter", "paper-1")

    assert "lycsa2020impact" in out
    assert "alexander2020price" in out
    assert "2 in literature.bib" in out
    assert "2020" in out
    assert "Price discovery in Bitcoin" in out


def test_prompt_block_forbids_citing_from_memory(tmp_path: Path):
    ws = tmp_path / "paper-1"
    ws.mkdir()
    (ws / "literature.bib").write_text(BIB, encoding="utf-8")

    with _with_workspace_root(tmp_path):
        out = _workspace_bib_for_prompt("paper_drafter", "paper-1")

    assert "Do not cite" in out and "memory" in out
    assert "missing_in_bib" in out
    assert "e2er-lit search" in out


def test_prompt_block_empty_when_no_bibliography(tmp_path: Path):
    (tmp_path / "paper-1").mkdir()
    with _with_workspace_root(tmp_path):
        assert _workspace_bib_for_prompt("paper_drafter", "paper-1") == ""


def test_prompt_block_only_for_bib_specialists(tmp_path: Path):
    ws = tmp_path / "paper-1"
    ws.mkdir()
    (ws / "literature.bib").write_text(BIB, encoding="utf-8")

    with _with_workspace_root(tmp_path):
        assert _workspace_bib_for_prompt("econometrics_specialist", "paper-1") == ""
        assert _workspace_bib_for_prompt("data_analyst", "paper-1") != "x"  # not a bib specialist
        assert _workspace_bib_for_prompt("data_analyst", "paper-1") == ""


def test_prompt_block_truncates_a_large_bibliography(tmp_path: Path):
    ws = tmp_path / "paper-1"
    ws.mkdir()
    many = "\n\n".join(f"@article{{key{i},\n  title = {{T{i}}},\n  year = {{2020}},\n}}" for i in range(50))
    (ws / "literature.bib").write_text(many, encoding="utf-8")

    with _with_workspace_root(tmp_path):
        out = _workspace_bib_for_prompt("paper_drafter", "paper-1", limit=10)

    assert "50 in literature.bib" in out
    assert "and 40 more" in out


# ── the parser ───────────────────────────────────────────────────────────────


def test_search_saves_by_default():
    args = build_parser().parse_args(["search", "some query"])
    assert args.save is True
    assert args.query == "some query"


def test_no_save_flag_disables_recording():
    args = build_parser().parse_args(["search", "q", "--no-save"])
    assert args.save is False


def test_subcommand_is_required():
    with pytest.raises(SystemExit):
        build_parser().parse_args([])


# ── the real wrapper ─────────────────────────────────────────────────────────


@pytest.mark.skipif(not WRAPPER.exists(), reason="wrapper not present")
def test_wrapper_list_reports_an_empty_bibliography(tmp_path: Path):
    env = dict(os.environ, E2ER_PYTHON=sys.executable, E2ER_SPECIALIST="literature_scanner")
    proc = subprocess.run([str(WRAPPER), "list"], cwd=tmp_path, capture_output=True, text=True, timeout=120, env=env)
    assert proc.returncode == 0, proc.stderr
    assert "nothing is citable yet" in proc.stdout


@pytest.mark.skipif(not WRAPPER.exists(), reason="wrapper not present")
def test_wrapper_list_reads_the_directory_it_was_called_from(tmp_path: Path):
    """cwd is the workspace; the wrapper must resolve the project root from its
    own path, not from cwd."""
    (tmp_path / "literature.bib").write_text(BIB, encoding="utf-8")
    env = dict(os.environ, E2ER_PYTHON=sys.executable, E2ER_SPECIALIST="paper_drafter")
    proc = subprocess.run([str(WRAPPER), "list"], cwd=tmp_path, capture_output=True, text=True, timeout=120, env=env)
    assert proc.returncode == 0, proc.stderr
    assert "lycsa2020impact" in proc.stdout
    assert "ONLY citable keys" in proc.stdout


@pytest.mark.skipif(not WRAPPER.exists(), reason="wrapper not present")
def test_wrapper_save_requires_an_argument(tmp_path: Path):
    env = dict(os.environ, E2ER_PYTHON=sys.executable, E2ER_SPECIALIST="literature_scanner")
    proc = subprocess.run([str(WRAPPER), "save"], cwd=tmp_path, capture_output=True, text=True, timeout=120, env=env)
    assert proc.returncode == 2
    assert "--doi or --entry" in proc.stderr


def test_budget_file_is_not_mistaken_for_a_bib(tmp_path: Path):
    """.lit_budget.json lives beside literature.bib; it must never be parsed
    as one."""
    _save_budget(tmp_path, "literature_scanner", {"search": 1})
    assert json.loads((tmp_path / ".lit_budget.json").read_text())
    assert _bib_keys(tmp_path) == []
