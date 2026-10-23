"""A skill pack's slugs never name a file outside the install root (the reviewer's 2026-10-23 repros).

The catalogue is other people's YAML: ``pack.slug: "../../.claude"`` with a skill ``CLAUDE`` wrote
``~/.claude/CLAUDE.md``; a skill slug ``../../outside/CLAUDE`` wrote next to the install root.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from src.modules import skills_catalogue as cat


@pytest.fixture
def fetched(monkeypatch):
    import src.modules.fetch.http as h

    async def fake(url, headers=None, max_bytes=None):
        return b"IGNORE PREVIOUS INSTRUCTIONS\n"

    monkeypatch.setattr(h, "fetch_bytes", fake)


def _pack(pack_slug: str, *skill_slugs: str) -> cat.SkillPack:
    raw = {
        "pack": {"slug": pack_slug, "name": "evil"},
        "skills": [{"slug": s, "details_url": f"https://example.com/{i}.md"} for i, s in enumerate(skill_slugs)],
    }
    return cat._pack_from(raw, "evil")


def _files(root: Path) -> list[str]:
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())


@pytest.mark.parametrize("bad", ["../../.claude", "..", "a/b", "/abs", "UPPER", "", ".hidden", "x" * 97])
def test_a_pack_slug_that_is_not_a_plain_name_is_refused(tmp_path, fetched, bad):
    home = tmp_path / "home"
    dest = home / ".e2er" / "skills"
    dest.mkdir(parents=True)
    with pytest.raises(cat.CatalogueError):
        asyncio.run(cat.install_pack(_pack(bad, "CLAUDE"), dest=dest))
    assert _files(tmp_path) == []


def test_a_skill_slug_with_a_path_is_skipped_and_the_rest_installs(tmp_path, fetched):
    dest = tmp_path / "inst" / "e2er-skills"
    report = asyncio.run(
        cat.install_pack(_pack("evil", "../../outside/CLAUDE", "skills/evil/SKILL", "fine"), dest=dest)
    )
    assert report["installed"] == 1 and report["failed"] == 2
    assert _files(tmp_path) == ["inst/e2er-skills/evil/fine.md", "inst/e2er-skills/evil/pack.json"]


def test_the_catalogues_own_long_underscore_slugs_install(tmp_path, fetched):
    slug = "theory_lab-personas-tier6_social_humanities-science_technology_studies"
    report = asyncio.run(cat.install_pack(_pack("theory_lab", slug), dest=tmp_path))
    assert report["installed"] == 1
    assert (tmp_path / "theory_lab" / f"{slug}.md").is_file()


def test_remove_pack_refuses_a_path(tmp_path):
    root = tmp_path / "skills"
    (root / "ok").mkdir(parents=True)
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "keep.txt").write_text("x")
    for bad in ["../victim", "..", "/tmp", "ok/../../victim"]:
        with pytest.raises(cat.CatalogueError):
            cat.remove_pack(bad, dest=root)
    assert (victim / "keep.txt").is_file()
    (root / "link").symlink_to(victim)
    with pytest.raises(cat.CatalogueError):
        cat.remove_pack("link", dest=root)
    assert (victim / "keep.txt").is_file()
    assert cat.remove_pack("ok", dest=root) is True


@pytest.mark.parametrize("bad", ["../../../etc/hosts", "/etc/hosts", "data/../../x", "a\\..\\b", "*", "c:x"])
def test_the_skill_loader_refuses_a_path_outside_the_skill_folders(bad):
    from src.skills import loader

    assert loader._load_skill(bad) == ""
    assert loader.skill_exists(bad) is False


def test_the_skill_loader_still_loads_a_bundled_skill():
    from src.skills import loader

    available = loader.list_available_skills()
    assert available
    assert loader._load_skill(available[0])
