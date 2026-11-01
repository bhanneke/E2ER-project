"""A run id in a dashboard URL is a UUID or nothing (the reviewer's 2026-10-23 traversal repro).

``/api/papers/%2E%2E/artifacts/.env`` served the studies folder's ``.env`` (API keys) because the
id became a folder name: ``<workspaces>/..``.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from src.api.app import app

BAD_IDS = ["%2E%2E", "..", "%2e%2e%2f%2e%2e", "abc", "x" * 50]


@pytest.fixture
def studies(tmp_path: Path):
    """A studies folder with a .env beside the workspaces, as on a real computer."""
    (tmp_path / "workspaces").mkdir()
    (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=sk-ant-FAKE-NOT-A-KEY\n", encoding="utf-8", newline="\n")
    with patch("src.config.get_settings") as s, patch("src.api.app.get_settings", s):
        s.return_value.workspace_root = str(tmp_path / "workspaces")
        s.return_value.api_auth_token = None
        yield tmp_path


@pytest.mark.parametrize("bad", BAD_IDS)
@pytest.mark.parametrize(
    "path",
    [
        "/api/papers/{id}/artifacts",
        "/api/papers/{id}/artifacts/.env",
        "/api/papers/{id}/artifacts/workspaces/../.env",
        "/api/papers/{id}/failure-bundle",
        "/api/papers/{id}/audit-bundle",
        "/api/papers/{id}/data-queries",
        "/api/papers/{id}/events",
        "/api/papers/{id}/usage",
        "/api/papers/{id}/pending-queries",
        "/papers/{id}/finish",
        "/htmx/papers/{id}/inputs",
    ],
)
def test_a_path_id_that_is_not_a_uuid_is_refused(studies, path, bad):
    c = TestClient(app, base_url="http://127.0.0.1:8280")
    r = c.get(path.format(id=bad), follow_redirects=False)
    assert r.status_code in (404, 400), (path, bad, r.status_code)
    assert "sk-ant-FAKE" not in r.text


def test_every_route_with_a_paper_id_declares_the_check():
    """A new route that takes ``paper_id`` without the check fails here, not in a review."""
    from src.api.guards import validate_uuid

    missing = []
    for route in app.routes:
        if not isinstance(route, APIRoute) or "{paper_id}" not in route.path:
            continue
        calls = [d.call for d in route.dependant.dependencies]
        if validate_uuid not in calls:
            missing.append(route.path)
    assert not missing, missing


def test_hidden_files_of_a_workspace_are_not_served(studies):
    pid = str(uuid.uuid4())
    ws = studies / "workspaces" / pid
    (ws / ".e2er").mkdir(parents=True)
    (ws / ".e2er" / "secret.json").write_text("{}", encoding="utf-8", newline="\n")
    (ws / "paper.md").write_text("# ok", encoding="utf-8", newline="\n")
    c = TestClient(app, base_url="http://127.0.0.1:8280")
    assert c.get(f"/api/papers/{pid}/artifacts/paper.md").status_code == 200
    assert c.get(f"/api/papers/{pid}/artifacts/.e2er/secret.json").status_code == 400


def test_find_workspace_refuses_an_id_that_is_a_path(tmp_path):
    from src.home import find_workspace

    for bad in ["..", "../x", "/etc", "a/b", ""]:
        with pytest.raises(ValueError):
            find_workspace(bad, tmp_path)
    pid = str(uuid.uuid4())
    assert find_workspace(pid, tmp_path) == tmp_path / pid
