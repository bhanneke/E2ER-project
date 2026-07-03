"""--save-to must never write through or over an existing path in workspace/data.

BYOD staging SYMLINKS the researcher's original files into workspace/data/, and
``to_csv()`` writes through a symlink — so a --save-to name colliding with a
staged file would truncate the original OUTSIDE the workspace. Regression tests
for the auto-suffix + resolved-containment protection in ``_maybe_save_csv``.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from src.modules.data.cli import _maybe_save_csv


def _args(pid: str, save_to: str) -> argparse.Namespace:
    return argparse.Namespace(paper_id=pid, specialist="data_analyst", save_to=save_to)


def _setup(tmp_path: Path, monkeypatch) -> Path:
    ws = tmp_path / "paper1"
    (ws / "data").mkdir(parents=True)
    monkeypatch.setenv("E2ER_WORKSPACE_ROOT", str(tmp_path))
    return ws


def test_save_to_never_writes_through_staged_symlink(tmp_path: Path, monkeypatch):
    ws = _setup(tmp_path, monkeypatch)
    original = tmp_path / "original_trades.csv"
    original.write_text("id;price\n1;100\n", encoding="utf-8")
    (ws / "data" / "trades.csv").symlink_to(original)

    result: dict = {"items": [{"a": 1}, {"a": 2}]}
    _maybe_save_csv(result, _args("paper1", "trades.csv"))

    assert original.read_text(encoding="utf-8") == "id;price\n1;100\n", "original clobbered!"
    assert "save_error" not in result
    assert "save_renamed" in result
    saved = ws / result["saved_to"]
    assert saved.name == "trades_1.csv"
    assert saved.is_file() and not saved.is_symlink()
    assert result["saved_rows"] == 2


def test_save_to_existing_file_is_not_overwritten(tmp_path: Path, monkeypatch):
    ws = _setup(tmp_path, monkeypatch)
    (ws / "data" / "out.csv").write_text("keep me", encoding="utf-8")

    result: dict = {"items": [{"a": 1}]}
    _maybe_save_csv(result, _args("paper1", "out.csv"))

    assert (ws / "data" / "out.csv").read_text(encoding="utf-8") == "keep me"
    assert (ws / result["saved_to"]).name == "out_1.csv"


def test_save_to_fresh_name_saves_normally(tmp_path: Path, monkeypatch):
    ws = _setup(tmp_path, monkeypatch)

    result: dict = {"items": [{"a": 1}]}
    _maybe_save_csv(result, _args("paper1", "fresh.csv"))

    assert "save_error" not in result and "save_renamed" not in result
    assert result["saved_to"] == "data/fresh.csv"
    assert (ws / "data" / "fresh.csv").is_file()


def test_save_to_suffix_skips_taken_names(tmp_path: Path, monkeypatch):
    ws = _setup(tmp_path, monkeypatch)
    (ws / "data" / "x.csv").write_text("0", encoding="utf-8")
    (ws / "data" / "x_1.csv").write_text("1", encoding="utf-8")

    result: dict = {"items": [{"a": 1}]}
    _maybe_save_csv(result, _args("paper1", "x.csv"))

    assert (ws / result["saved_to"]).name == "x_2.csv"
    assert (ws / "data" / "x.csv").read_text(encoding="utf-8") == "0"
    assert (ws / "data" / "x_1.csv").read_text(encoding="utf-8") == "1"


def test_save_to_symlinked_dir_escaping_workspace_is_rejected(tmp_path: Path, monkeypatch):
    ws = _setup(tmp_path, monkeypatch)
    outside = tmp_path / "outside"
    outside.mkdir()
    (ws / "data" / "sub").symlink_to(outside, target_is_directory=True)

    result: dict = {"items": [{"a": 1}]}
    _maybe_save_csv(result, _args("paper1", "sub/leak.csv"))

    assert "save_error" in result
    assert not (outside / "leak.csv").exists()
