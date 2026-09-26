"""The RISE catalogue, reachable without a terminal.

358 skills published by a dozen research projects, previously reachable only by
knowing that `e2er skills` exists. A catalogue nobody can browse is a catalogue
nobody uses.

The licence column is the load-bearing part. E2ER installs packs from their own
repositories rather than shipping copies, because roughly half the catalogue is
CC BY-NC, unlicensed, or private to its curator. The page has to show whose work
it is without implying that the awkwardly-licensed half is off limits — fetching
a public file onto your own machine is not redistribution.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.app import app

MIT_PACK = """
pack:
  slug: demo
  name: 'Demo Pack'
  source_url: 'https://github.com/someone/demo'
  maintainers: ['A. Person']
  license: 'MIT'
skills:
  - slug: alpha
    name: 'Alpha'
    source_path: 'skills/alpha/SKILL.md'
    details_url: 'https://github.com/someone/demo/blob/main/skills/alpha/SKILL.md'
  - slug: beta
    name: 'Beta'
    source_path: 'skills/beta/SKILL.md'
    details_url: 'https://github.com/someone/demo/blob/main/skills/beta/SKILL.md'
"""

NC_PACK = """
pack:
  slug: curated
  name: 'Curated Methods'
  source_url: 'https://github.com/someone/curated'
  maintainers: ['B. Curator']
  license: 'CC BY-NC 4.0'
skills:
  - slug: gamma
    name: 'Gamma'
    source_path: 'skills/gamma/SKILL.md'
    details_url: 'https://github.com/someone/curated/blob/main/skills/gamma/SKILL.md'
"""


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def isolated(tmp_path: Path, monkeypatch) -> Path:
    """Never read the developer's own ~/.e2er/skills."""
    root = tmp_path / "installed"
    monkeypatch.setattr("src.modules.skills_catalogue.install_root", lambda: root)
    return root


@pytest.fixture
def catalogue(tmp_path: Path, monkeypatch, isolated: Path) -> Path:
    rise = tmp_path / "RISE"
    (rise / "skills").mkdir(parents=True)
    (rise / "skills" / "demo.yml").write_text(MIT_PACK)
    (rise / "skills" / "curated.yml").write_text(NC_PACK)
    monkeypatch.setattr("src.modules.skills_catalogue.catalogue_path", lambda explicit=None: rise)
    return rise


@pytest.fixture
def no_catalogue(tmp_path: Path, monkeypatch, isolated: Path) -> Path:
    absent = tmp_path / "nowhere"
    monkeypatch.setattr("src.modules.skills_catalogue.catalogue_path", lambda explicit=None: absent)
    return absent


# ---------------------------------------------------------------------------
# No catalogue
# ---------------------------------------------------------------------------


def test_no_catalogue_says_how_to_get_one(client, no_catalogue):
    r = client.get("/skills")

    assert r.status_code == 200
    assert "RISE" in r.text
    assert "RISE_PATH" in r.text, "tell them the setting that fixes it"


def test_no_catalogue_is_not_a_crash(client, no_catalogue):
    """A missing optional checkout must not take the dashboard down."""
    assert "Traceback" not in client.get("/skills").text


# ---------------------------------------------------------------------------
# A real catalogue
# ---------------------------------------------------------------------------


def test_the_catalogue_lists_its_packs(client, catalogue):
    r = client.get("/skills")

    assert r.status_code == 200
    assert "Demo Pack" in r.text
    assert "Curated Methods" in r.text


def test_each_pack_shows_whose_work_it_is(client, catalogue):
    """Attribution is the reason this is an installer and not a copy."""
    r = client.get("/skills")

    assert "A. Person" in r.text
    assert "MIT" in r.text
    assert "CC BY-NC 4.0" in r.text


def test_counts_are_of_skills_not_just_packs(client, catalogue):
    r = client.get("/skills")

    assert "skills available" in r.text
    assert ">3<" in r.text, "two packs, three skills between them"


def test_a_pack_e2er_could_not_bundle_can_still_be_installed(client, catalogue):
    """The distinction the whole design rests on.

    CC BY-NC means E2ER cannot ship the pack inside an MIT package on PyPI. It
    does not mean the user cannot fetch it onto their own machine. If the page
    ever hides the button for these, half the catalogue becomes unreachable for
    no reason.
    """
    body = client.get("/skills").text
    row = body[body.index("Curated Methods") :]
    row = row[: row.index("</tr>")]

    assert 'value="curated"' in row, "the non-redistributable pack must still have an install control"


def test_an_installed_pack_is_shown_as_installed(client, catalogue, isolated):
    (isolated / "demo").mkdir(parents=True)
    (isolated / "demo" / "alpha.md").write_text("# Alpha")
    (isolated / "demo" / "pack.json").write_text('{"pack": {"license": "MIT"}}')

    body = client.get("/skills").text
    row = body[body.index("Demo Pack") :]
    row = row[: row.index("</tr>")]

    assert "installed" in row
    assert 'value="demo"' not in row, "no install button for something already installed"


def test_skills_are_reachable_from_every_page(client, catalogue):
    assert "/skills" in client.get("/").text


# ---------------------------------------------------------------------------
# Installing
# ---------------------------------------------------------------------------


def test_installing_reports_what_happened(client, catalogue, monkeypatch):
    async def fake_install(pack, **kw):
        return {"installed": 2, "failed": 0, "dest": "/tmp/demo"}

    monkeypatch.setattr("src.modules.skills_catalogue.install_pack", fake_install)

    r = client.post("/skills/install", data={"pack": "demo"}, follow_redirects=True)

    assert r.status_code == 200
    assert "2 installed" in r.text


def test_a_pack_that_does_not_exist_does_not_500(client, catalogue):
    r = client.post("/skills/install", data={"pack": "no-such-pack"}, follow_redirects=True)

    assert r.status_code == 200
    assert "Could not install" in r.text


def test_a_network_failure_lands_on_the_page_not_a_stack_trace(client, catalogue, monkeypatch):
    """Installing reaches the network, which fails; the dashboard must not."""

    async def boom(pack, **kw):
        raise OSError("connection reset")

    monkeypatch.setattr("src.modules.skills_catalogue.install_pack", boom)

    r = client.post("/skills/install", data={"pack": "demo"}, follow_redirects=True)

    assert r.status_code == 200
    assert "connection reset" in r.text


def test_the_message_survives_a_url_round_trip(client, catalogue, monkeypatch):
    """The report is carried to the next page in a query string.

    Starlette percent-encodes spaces on its own, so those are not the hazard.
    `&` and `#` are on its safe list: unencoded, they end the parameter early
    and the user is shown a message truncated at the interesting part. Error
    text is exactly where an ampersand turns up — a URL with query parameters,
    or a maintainer list.
    """

    async def boom(pack, **kw):
        raise OSError("GET https://host/a?x=1&y=2#frag failed")

    monkeypatch.setattr("src.modules.skills_catalogue.install_pack", boom)

    r = client.post("/skills/install", data={"pack": "demo"}, follow_redirects=True)

    assert r.status_code == 200
    assert "y=2" in r.text, "the message was truncated at the ampersand"
    assert "frag failed" in r.text, "and at the fragment marker"
