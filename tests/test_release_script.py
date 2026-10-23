"""scripts/release.py: one command makes every version edit of a release, or refuses and writes nothing."""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FILES = ("pyproject.toml", "src/__init__.py", "CITATION.cff", "README.md", "CHANGELOG.md")


def _load():
    name = "e2er_release_script"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / "release.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


rel = _load()


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout


@pytest.fixture
def repo(tmp_path: Path, monkeypatch) -> Path:
    """A git repository with copies of the repository's own versioned files, committed."""
    cfg = tmp_path / "gitconfig"
    cfg.write_text("[user]\n\tname = Test\n\temail = test@example.org\n[commit]\n\tgpgsign = false\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(cfg))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    root = tmp_path / "repo"
    for f in FILES:
        (root / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / f, root / f)
    # Right after a release the repository's Unreleased section is empty, and a release of the copy
    # would be refused: give the copy an entry then, so the tests do not depend on the CHANGELOG's state.
    log = root / "CHANGELOG.md"
    text = log.read_text()
    body = rel.unreleased_body(text)
    if not body.strip():
        log.write_text(text.replace("## [Unreleased]" + body, "## [Unreleased]\n\n### Added\n- A test entry.\n\n", 1))
    _git(root, "init", "-q")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "init")
    return root


def _bump(version: str) -> str:
    a, b, _ = rel.parse_version(version)
    return f"{a}.{b + 1}.0"


def test_the_repository_names_one_version_everywhere():
    """What release.yml's version check runs; fails when a place was edited by hand."""
    assert rel.check(ROOT) == []


def test_a_release_edits_every_place(repo: Path):
    current = rel.current_version(repo)
    new = _bump(current)
    unreleased = rel.unreleased_body((repo / "CHANGELOG.md").read_text())
    files = rel.release(repo, new, "2027-01-05")
    assert sorted(files) == sorted(FILES)

    assert f'version = "{new}"' in (repo / "pyproject.toml").read_text()
    assert f'__version__ = "{new}"' in (repo / "src/__init__.py").read_text()
    cff = (repo / "CITATION.cff").read_text()
    assert f'\nversion: "{new}"' in cff and 'date-released: "2027-01-05"' in cff
    assert f'  version: "{new}"' in cff and "  year: 2027" in cff
    readme = (repo / "README.md").read_text()
    assert f"version      = {{{new}}}" in readme and "year         = {2027}" in readme

    log = (repo / "CHANGELOG.md").read_text()
    assert f"## [Unreleased]\n\n## [{new}] — 2027-01-05\n" in log
    assert rel.unreleased_body(log).strip() == ""  # a new, empty Unreleased
    assert unreleased.strip() in log.split(f"## [{new}] — 2027-01-05\n", 1)[1]  # the entries moved under it
    assert f"[Unreleased]: {rel.REPO_URL}/compare/v{new}...HEAD" in log
    assert f"[{new}]: {rel.REPO_URL}/releases/tag/v{new}" in log

    assert rel.check(repo, f"v{new}") == []
    assert rel.check(repo, f"v{current}")  # the old tag no longer matches


def test_nothing_else_changes(repo: Path):
    """Only the version places change: every other line of every file is as it was."""
    before = {f: (repo / f).read_text().splitlines() for f in FILES}
    new = _bump(rel.current_version(repo))
    rel.release(repo, new, "2027-01-05")
    for f in ("pyproject.toml", "src/__init__.py", "CITATION.cff", "README.md"):
        after = (repo / f).read_text().splitlines()
        assert len(after) == len(before[f])
        changed = [(a, b) for a, b in zip(before[f], after, strict=True) if a != b]
        assert changed and all(new in b or "2027" in b for _, b in changed), (f, changed)


def test_commit(repo: Path):
    new = _bump(rel.current_version(repo))
    rel.release(repo, new, "2027-01-05", commit=True)
    assert _git(repo, "status", "--porcelain") == ""
    assert _git(repo, "log", "-1", "--format=%s") == f"Release {new}\n"


def test_refuses_a_dirty_tree(repo: Path):
    (repo / "README.md").write_text((repo / "README.md").read_text() + "\nedited\n")
    before = (repo / "pyproject.toml").read_text()
    with pytest.raises(rel.ReleaseError, match="uncommitted"):
        rel.release(repo, _bump(rel.current_version(repo)), "2027-01-05")
    assert (repo / "pyproject.toml").read_text() == before


@pytest.mark.parametrize("version", ["same", "0.0.1", "1.2", "v9.9.9", "9.9.9rc1"])
def test_refuses_a_version_that_is_not_greater_or_not_x_y_z(repo: Path, version: str):
    current = rel.current_version(repo)
    before = {f: (repo / f).read_text() for f in FILES}
    with pytest.raises(rel.ReleaseError):
        rel.release(repo, current if version == "same" else version, "2027-01-05")
    assert {f: (repo / f).read_text() for f in FILES} == before


def test_refuses_an_empty_unreleased_section(repo: Path):
    log = repo / "CHANGELOG.md"
    text = log.read_text()
    body = rel.unreleased_body(text)
    log.write_text(text.replace(body, "\n", 1))
    _git(repo, "commit", "-qam", "empty")
    with pytest.raises(rel.ReleaseError, match="empty"):
        rel.release(repo, _bump(rel.current_version(repo)), "2027-01-05")


def test_refuses_a_place_it_cannot_find(repo: Path):
    readme = repo / "README.md"
    readme.write_text(readme.read_text().replace("@software{hanneke2026e2er,", "@software{renamed,"))
    _git(repo, "commit", "-qam", "renamed")
    before = (repo / "pyproject.toml").read_text()
    with pytest.raises(rel.ReleaseError, match="README.md"):
        rel.release(repo, _bump(rel.current_version(repo)), "2027-01-05")
    assert (repo / "pyproject.toml").read_text() == before


def test_check_names_a_place_edited_by_hand(repo: Path):
    init = repo / "src/__init__.py"
    init.write_text(init.read_text().replace(rel.current_version(repo), "9.9.9"))
    assert any("src/__init__.py" in p for p in rel.check(repo))


def test_dry_run_writes_nothing(repo: Path, capsys):
    before = {f: (repo / f).read_text() for f in FILES}
    assert rel.main([_bump(rel.current_version(repo)), "--dry-run", "--date", "2027-01-05", "--root", str(repo)]) == 0
    assert "would change" in capsys.readouterr().out
    assert {f: (repo / f).read_text() for f in FILES} == before


def test_cli_check_and_refusal(repo: Path, capsys):
    current = rel.current_version(repo)
    assert rel.main(["--check", "--tag", f"v{current}", "--root", str(repo)]) == 0
    assert rel.main(["--check", "--tag", "v99.0.0", "--root", str(repo)]) == 1
    assert rel.main([current, "--root", str(repo)]) == 1
    assert "not greater" in capsys.readouterr().out


def test_warns_about_a_version_that_is_neither_history_nor_the_release(repo: Path):
    current = rel.current_version(repo)
    a, b, c = rel.parse_version(current)
    patch = f"{a}.{b}.{c + 1}"
    (repo / "docs").mkdir()
    (repo / "docs" / "x.md").write_text(f"This comes in {patch}.\nUp to {current} it did not.\nfixest 0.12.1\n")
    assert rel.future_mentions(repo, current, patch) == []  # releasing that version: fine
    warned = rel.future_mentions(repo, current, f"{a}.{b + 1}.0")
    assert warned == [f"docs/x.md:1: This comes in {patch}."]
