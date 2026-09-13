"""The /workflow page must describe the install it is running in.

The dashboard had only a papers list and a new-paper form, so the specialist
roster and skill wiring were invisible from the UI — the only way to learn that
11 shipped skills are loaded by nothing was to read the registry.

The first version of this page looked in the wrong directory and cheerfully
reported "0 skill files installed, 47 referenced but absent". It rendered,
returned 200, and was entirely wrong — which is why these tests assert the
numbers rather than the status code.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api.app import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


def test_workflow_page_renders(client: TestClient):
    r = client.get("/workflow")
    assert r.status_code == 200
    assert "Workflow" in r.text


def test_it_finds_the_skill_files(client: TestClient):
    """The count that was silently zero.

    The loader searches two directories; this page reuses that list, so a
    packaging change that moves the files breaks both together rather than
    leaving the page confidently empty.
    """
    from src.api.app import _workflow_inventory

    inv = _workflow_inventory()
    assert inv["counts"]["on_disk"] > 0, "no skill files found — wrong directory?"
    assert inv["counts"]["referenced"] > 0
    assert not inv["missing"], f"specialists reference absent skills: {inv['missing']}"


def test_every_specialist_is_listed(client: TestClient):
    from src.api.app import _workflow_inventory
    from src.core.specialists.registry import SPECIALIST_SKILLS

    inv = _workflow_inventory()
    listed = {s["name"] for s in inv["specialists"]}
    assert set(SPECIALIST_SKILLS) <= listed


def test_unused_skills_are_surfaced(client: TestClient):
    """Skills nothing loads are the reason the page exists — they must be named,
    not merely counted."""
    from src.api.app import _workflow_inventory

    inv = _workflow_inventory()
    assert len(inv["unused"]) == inv["counts"]["unused"]
    if inv["unused"]:
        r = client.get("/workflow")
        assert inv["unused"][0] in r.text


def test_nav_links_to_it(client: TestClient):
    """A page nobody can reach from the UI is the same as no page."""
    r = client.get("/")
    assert "/workflow" in r.text
