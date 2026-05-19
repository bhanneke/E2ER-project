"""Pin the v0.4.5 fix for the nested-workspace-path bug.

Live test eea5379b on v0.4.4 wrote SPY data to
`workspaces/<id>/workspaces/<id>/data/yfinance_SPY_2020_2026.csv`
because:

1. claude_code spawns the data_analyst subprocess with
   `cwd = Path("workspaces") / paper_id` — a relative path, resolved
   against the parent process's cwd at subprocess.exec time.
2. Inside that subprocess, `_resolve_workspace(paper_id)` returned
   `Path(get_settings().workspace_root) / paper_id` — the same relative
   string. The OS resolved it again against the (already-workspace)
   subprocess cwd, producing the nested directory.

The fix: `_resolve_workspace` prefers `$E2ER_WORKSPACE_ROOT` (absolute,
injected by claude_code.py) over the relative settings default. These
tests pin the env-var precedence and the no-nesting outcome.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.modules.data.cli import _resolve_workspace


def test_resolve_workspace_uses_env_var_when_set(tmp_path: Path, monkeypatch) -> None:
    paper_id = "00000000-0000-0000-0000-000000000001"
    abs_root = tmp_path / "abs_workspaces"
    abs_root.mkdir()
    monkeypatch.setenv("E2ER_WORKSPACE_ROOT", str(abs_root))

    resolved = _resolve_workspace(paper_id)

    assert resolved == abs_root / paper_id
    assert resolved.is_absolute(), f"expected absolute path, got {resolved!r}"


def test_resolve_workspace_falls_back_to_settings(monkeypatch) -> None:
    """Without the env var, fall through to settings.workspace_root."""
    monkeypatch.delenv("E2ER_WORKSPACE_ROOT", raising=False)
    paper_id = "00000000-0000-0000-0000-000000000002"

    resolved = _resolve_workspace(paper_id)

    # Default settings value is the relative string "workspaces".
    assert resolved.parts[-1] == paper_id
    assert resolved.parts[-2] == "workspaces"


def test_resolve_workspace_no_nesting_when_cwd_is_workspace(tmp_path: Path, monkeypatch) -> None:
    """The regression case: subprocess cwd is the paper's workspace dir.

    Pre-v0.4.5, `_resolve_workspace` returned a relative path that the OS
    re-resolved against this cwd → `workspaces/<id>/workspaces/<id>`.
    With the env-var fix the resolution is absolute and stable.
    """
    paper_id = "eafef6b4-9d97-4426-9efa-0f9c5a89b410"
    abs_root = tmp_path / "wsroot"
    workspace = abs_root / paper_id
    workspace.mkdir(parents=True)

    monkeypatch.setenv("E2ER_WORKSPACE_ROOT", str(abs_root))
    monkeypatch.chdir(workspace)  # mimic the subprocess cwd

    resolved = _resolve_workspace(paper_id)

    # Must equal the original workspace dir, not workspace/workspaces/<id>.
    assert resolved == workspace
    assert (resolved / "data").parent == workspace, f"resolved workspace nests under itself: {resolved!r}"


@pytest.mark.parametrize(
    "save_to",
    ["spy.csv", "subdir/spy.csv"],
)
def test_save_to_target_is_absolute(tmp_path: Path, monkeypatch, save_to: str) -> None:
    """End-to-end check of the path the `--save-to` code computes for a
    bare/relative filename. With the env-var set, the target lives directly
    under <abs_root>/<paper_id>/data/, never under a nested workspaces/<id>/."""
    paper_id = "00000000-0000-0000-0000-000000000003"
    abs_root = tmp_path / "wsroot"
    abs_root.mkdir()
    monkeypatch.setenv("E2ER_WORKSPACE_ROOT", str(abs_root))

    workspace = _resolve_workspace(paper_id)
    target = workspace / "data" / save_to

    expected = abs_root / paper_id / "data" / save_to
    assert target == expected, f"got {target!r}, expected {expected!r}"
    assert "workspaces/00000000-0000-0000-0000-000000000003/workspaces" not in str(target), (
        "regression: nested workspaces/<id>/workspaces/<id> path detected"
    )
