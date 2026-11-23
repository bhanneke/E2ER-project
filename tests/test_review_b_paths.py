"""Windows drive-relative, UNC and colon paths in a recipe; every target inside the run folder (review B, 10)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.core import reproduce as rp


@pytest.mark.parametrize(
    "path",
    [
        "D:x",
        "D:results/x.json",
        "C:\\\\x",
        "\\\\\\\\host\\\\share\\\\x",
        "\\\\x",
        "a\\\\..\\\\..\\\\x",
        "a:stream",
        "x\0y",
    ],
)
def test_windows_paths_are_not_inside_the_folder(path: str) -> None:
    assert not rp._safe_rel(path)


@pytest.mark.parametrize("path", ["results/x.json", "data/a b.csv", "code/über.py"])
def test_plain_relative_paths_are(path: str) -> None:
    assert rp._safe_rel(path)


@pytest.mark.skipif(os.name == "nt", reason="symlinks need privileges on Windows")
def test_lay_out_does_not_delete_through_a_linked_folder(tmp_path: Path) -> None:
    folder, run_dir, outside = tmp_path / "study", tmp_path / "run", tmp_path / "outside"
    (folder / "results").mkdir(parents=True)
    outside.mkdir()
    (outside / "x.json").write_text("{}")
    (folder / "out").symlink_to(outside, target_is_directory=True)  # copied as a link
    recipe = {"compare": [{"published": "results/x.json", "produced": "out/x.json"}]}
    with pytest.raises(rp.RecipeError):
        rp.lay_out(folder, run_dir, recipe)
    assert (outside / "x.json").is_file()


@pytest.mark.skipif(os.name == "nt", reason="symlinks need privileges on Windows")
def test_lay_out_does_not_write_through_a_linked_folder(tmp_path: Path) -> None:
    folder, run_dir, outside = tmp_path / "study", tmp_path / "run", tmp_path / "outside"
    (folder / "data").mkdir(parents=True)
    (folder / "data" / "a.csv").write_text("a\n1\n")
    outside.mkdir()
    run_dir.mkdir()
    (run_dir / "data").symlink_to(outside, target_is_directory=True)
    with pytest.raises(rp.RecipeError):
        rp.lay_out(folder, run_dir, {"files": {"data/a.csv": "data/a.csv"}})
    assert not (outside / "a.csv").exists()


def test_lay_out_refuses_a_drive_relative_target(tmp_path: Path) -> None:
    folder, run_dir = tmp_path / "study", tmp_path / "run"
    folder.mkdir()
    (folder / "a.csv").write_text("a\n")
    with pytest.raises(rp.RecipeError):
        rp.lay_out(folder, run_dir, {"files": {"D:a.csv": "a.csv"}})
    with pytest.raises(rp.RecipeError):
        rp.lay_out(folder, run_dir, {"compare": [{"published": "a.csv", "produced": "D:a.csv"}]})
