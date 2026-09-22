"""Installing skill packs from the RISE catalogue.

RISE indexes packs published by other projects, each with its own repository and
licence. E2ER installs them; it does not vendor them. Roughly half the
catalogue's 358 skills are CC BY-NC, unlicensed, or private to their curator, so
copying them into an MIT package on PyPI would be republishing work that is not
ours to republish.

Most of what is tested here is tolerance of a catalogue that is slightly wrong,
because the first real install proved it is: every `details_url` assumes the
`main` branch, and one entry disagrees with its siblings about the case of
SKILL.md.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.modules.skills_catalogue import (
    CatalogueError,
    SkillPack,
    _candidate_urls,
    find_pack,
    install_pack,
    installed_packs,
    read_catalogue,
    remove_pack,
)

PACK_YML = """
pack:
  slug: demo
  name: 'Demo Pack'
  source_url: 'https://github.com/someone/demo'
  maintainers:
    - 'A. Person'
  license: 'MIT'
  total_skills: 2
  compatibility:
    - claude-code
skills:
  - slug: alpha
    name: 'Alpha'
    category: audit
    field: economics
    description: 'Does alpha things.'
    source_path: 'skills/alpha/SKILL.md'
    details_url: 'https://github.com/someone/demo/blob/main/skills/alpha/SKILL.md'
  - slug: beta
    name: 'Beta'
    category: infra
    field: economics
    description: 'Does beta things.'
    source_path: 'skills/beta/SKILL.md'
    details_url: 'https://github.com/someone/demo/blob/main/skills/beta/SKILL.md'
"""


@pytest.fixture
def catalogue(tmp_path: Path) -> Path:
    (tmp_path / "skills").mkdir()
    (tmp_path / "skills" / "demo.yml").write_text(PACK_YML)
    return tmp_path


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def test_a_pack_is_read_with_its_licence_and_authors(catalogue):
    packs = read_catalogue(catalogue)

    assert len(packs) == 1
    pack = packs[0]
    assert pack.slug == "demo"
    assert pack.license == "MIT"
    assert pack.maintainers == ("A. Person",)
    assert [s.slug for s in pack.skills] == ["alpha", "beta"]


def test_a_malformed_pack_does_not_hide_the_others(catalogue):
    (catalogue / "skills" / "broken.yml").write_text("pack: [[[ not yaml")

    assert [p.slug for p in read_catalogue(catalogue)] == ["demo"]


def test_a_missing_catalogue_says_where_to_get_one(tmp_path):
    with pytest.raises(CatalogueError, match="RISE"):
        read_catalogue(tmp_path / "nowhere")


def test_an_unknown_pack_is_reported(catalogue):
    with pytest.raises(CatalogueError, match="no pack named"):
        find_pack("nonesuch", catalogue)


# ---------------------------------------------------------------------------
# Licence awareness — the reason this installs rather than copies
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("licence", "bundleable"),
    [
        ("MIT", True),
        ("Apache-2.0", True),
        ("BSD-3-Clause", True),
        ("CC BY-NC 4.0", False),
        ("none declared", False),
        ("private (curator-owned)", False),
        ("Other (see repo)", False),
        ("", False),
    ],
)
def test_bundleability_is_judged_from_the_licence(licence, bundleable):
    """Not used to block an install — installing a public file on your own
    machine is not redistribution. It answers "could E2ER ship this?", which is
    the question that made this an installer."""
    assert SkillPack(slug="x", license=licence).redistributable is bundleable


# ---------------------------------------------------------------------------
# Surviving a catalogue that is slightly wrong
# ---------------------------------------------------------------------------


def test_a_blob_url_becomes_a_raw_url():
    urls = _candidate_urls("https://github.com/o/r/blob/main/skills/a/SKILL.md")

    assert urls[0] == "https://raw.githubusercontent.com/o/r/main/skills/a/SKILL.md"


def test_the_other_default_branch_is_tried():
    """Found on the first real install: the catalogue writes /blob/main/ for
    every pack, and theorist-toolbox is on master, so all eleven skills 404'd."""
    urls = _candidate_urls("https://github.com/o/r/blob/main/skills/a/SKILL.md")

    assert any("/master/" in u for u in urls)


def test_both_spellings_of_skill_md_are_tried():
    """One catalogue entry says skill.md where its ten siblings say SKILL.md,
    and raw.githubusercontent is case-sensitive."""
    lower = _candidate_urls("https://github.com/o/r/blob/main/skills/a/skill.md")
    upper = _candidate_urls("https://github.com/o/r/blob/main/skills/a/SKILL.md")

    assert any(u.endswith("SKILL.md") for u in lower)
    assert any(u.endswith("skill.md") for u in upper)


def test_a_non_github_url_is_left_alone():
    url = "https://example.org/skills/a.md"
    assert _candidate_urls(url) == [url]


# ---------------------------------------------------------------------------
# Installing
# ---------------------------------------------------------------------------


async def test_installing_writes_the_skills_and_their_provenance(catalogue, tmp_path, monkeypatch):
    async def _fetch(url, headers=None, max_bytes=None):
        return b"# a skill\n\nbody"

    monkeypatch.setattr("src.modules.fetch.http.fetch_bytes", _fetch)
    dest = tmp_path / "installed"

    report = await install_pack(find_pack("demo", catalogue), dest=dest)

    assert report["installed"] == 2
    assert (dest / "demo" / "alpha.md").read_text() == "# a skill\n\nbody"

    # Six months later, someone has to be able to ask whose file this is.
    manifest = json.loads((dest / "demo" / "pack.json").read_text())
    assert manifest["pack"]["license"] == "MIT"
    assert manifest["pack"]["source_url"] == "https://github.com/someone/demo"
    assert manifest["pack"]["maintainers"] == ["A. Person"]


async def test_one_unreachable_skill_does_not_stop_the_pack(catalogue, tmp_path, monkeypatch):
    async def _fetch(url, headers=None, max_bytes=None):
        if "beta" in url:
            raise RuntimeError("404 Not Found")
        return b"ok"

    monkeypatch.setattr("src.modules.fetch.http.fetch_bytes", _fetch)
    dest = tmp_path / "installed"

    report = await install_pack(find_pack("demo", catalogue), dest=dest)

    assert report["installed"] == 1
    assert report["failed"] == 1
    assert (dest / "demo" / "alpha.md").is_file()


async def test_failures_are_recorded_not_just_counted(catalogue, tmp_path, monkeypatch):
    async def _fetch(url, headers=None, max_bytes=None):
        raise RuntimeError("410 Gone")

    monkeypatch.setattr("src.modules.fetch.http.fetch_bytes", _fetch)
    dest = tmp_path / "installed"

    await install_pack(find_pack("demo", catalogue), dest=dest)
    manifest = json.loads((dest / "demo" / "pack.json").read_text())

    assert len(manifest["failed"]) == 2
    assert "410" in manifest["failed"][0]["error"]


async def test_installed_then_removed(catalogue, tmp_path, monkeypatch):
    async def _fetch(url, headers=None, max_bytes=None):
        return b"ok"

    monkeypatch.setattr("src.modules.fetch.http.fetch_bytes", _fetch)
    dest = tmp_path / "installed"

    await install_pack(find_pack("demo", catalogue), dest=dest)

    listed = installed_packs(dest)
    assert [p["slug"] for p in listed] == ["demo"]
    assert listed[0]["files"] == 2
    assert listed[0]["license"] == "MIT"

    assert remove_pack("demo", dest) is True
    assert installed_packs(dest) == []
    assert remove_pack("demo", dest) is False


def test_nothing_installed_is_not_an_error(tmp_path):
    assert installed_packs(tmp_path / "absent") == []


def test_the_loader_searches_installed_packs():
    """Installing is pointless if a specialist cannot then load the skill."""
    from src.skills.loader import _SKILLS_DIRS

    assert any(".e2er" in str(d) and d.name == "skills" for d in _SKILLS_DIRS)


def test_a_bundled_skill_wins_over_an_installed_one():
    """An installed pack should extend the library, not silently replace part
    of it — so the packaged directories are searched first."""
    from src.skills.loader import _SKILLS_DIRS

    installed_at = next(i for i, d in enumerate(_SKILLS_DIRS) if ".e2er" in str(d))
    assert installed_at == len(_SKILLS_DIRS) - 1
