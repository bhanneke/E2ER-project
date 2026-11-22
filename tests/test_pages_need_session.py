"""The dashboard's pages need the session, not only its API (review of 2026-11-21, finding 12)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api.app import app

from .conftest import TEST_SESSION_TOKEN


def _anon() -> TestClient:
    return TestClient(app, headers={"x-e2er-token": ""})


@pytest.mark.parametrize("path", ["/", "/setup", "/library", "/skills", "/workflow", "/new"])
def test_a_page_without_the_session_sends_the_browser_to_start_e2er(path):
    r = _anon().get(path, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/signed-out"
    page = _anon().get(path)
    assert page.status_code == 401 and "Start e2er" in page.text and "<code>e2er</code>" in page.text


def test_a_form_post_without_the_session_is_refused_with_the_page():
    r = _anon().post("/papers", data={"research_question": "Q"})
    assert r.status_code == 403 and "not signed in" in r.text


def test_the_launch_address_and_the_open_paths_still_answer():
    c = _anon()
    r = c.get(f"/?t={TEST_SESSION_TOKEN}", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"
    assert "e2er_session" in r.headers.get("set-cookie", "")
    assert c.get("/health").status_code == 200
    assert c.get("/signed-out").status_code == 401
    assert c.get("/static/e2er.js").status_code == 200
    assert _anon().get("/?t=wrong", follow_redirects=False).headers["location"] == "/signed-out"


def test_with_the_session_a_page_renders():
    r = TestClient(app).get("/workflow")
    assert r.status_code == 200
