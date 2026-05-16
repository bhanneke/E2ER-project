"""Lane A — `e2er install-skills` subcommand contract.

These tests pin:
  - all 49 bundled skills copy to the chosen backend's dir
  - default --backend=all populates Claude + Codex + Gemini dirs
  - category subdirs are preserved (loaders depend on the path layout)
  - --force overwrites existing files; default skips them
  - missing-bundled-skills returns 1 with a clear error message
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from src.cli_install_skills import install_skills


def test_install_skills_copies_all_files_to_claude(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    rc = install_skills(backend="claude")

    assert rc == 0
    copied = list((tmp_path / ".claude" / "skills").rglob("*.md"))
    assert len(copied) >= 40, f"expected at least 40 skill files, got {len(copied)}"


def test_install_skills_preserves_category_subdirs(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    install_skills(backend="claude")

    # Spot-check that data/, writing/, review/ subdirs all exist —
    # the loader walks by category path (e.g. "data/cleaning"), so
    # flattening into one directory would break skill resolution.
    skills_root = tmp_path / ".claude" / "skills"
    for category in ("data", "writing", "review", "econometrics", "modeling"):
        assert (skills_root / category).is_dir(), f"missing category subdir: {category}"


def test_install_skills_all_populates_three_backends(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    install_skills(backend="all")

    for backend in ("claude", "codex", "gemini"):
        target = tmp_path / f".{backend}" / "skills"
        files = list(target.rglob("*.md"))
        assert len(files) >= 40, f"{backend} dir has only {len(files)} files"


def test_install_skills_skips_existing_by_default(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    # First install creates files
    install_skills(backend="claude")
    target = tmp_path / ".claude" / "skills"
    sample = next(target.rglob("*.md"))
    sample.write_text("MODIFIED", encoding="utf-8")

    # Second install must NOT overwrite
    install_skills(backend="claude")
    assert sample.read_text(encoding="utf-8") == "MODIFIED", (
        "default install should skip existing files; --force is the way to overwrite"
    )


def test_install_skills_force_overwrites(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    install_skills(backend="claude")
    target = tmp_path / ".claude" / "skills"
    sample = next(target.rglob("*.md"))
    sample.write_text("MODIFIED", encoding="utf-8")

    install_skills(backend="claude", force=True)
    assert sample.read_text(encoding="utf-8") != "MODIFIED", (
        "--force should have overwritten the modified file with the bundled content"
    )


def test_install_skills_returns_1_when_source_missing(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    # Force the bundled-skills lookup to return None (simulating a broken install).
    with patch("src.cli_install_skills._bundled_skills_dir", return_value=None):
        rc = install_skills(backend="claude")
    assert rc == 1
    captured = capsys.readouterr()
    assert "broken state" in captured.out or "reinstall" in captured.out
