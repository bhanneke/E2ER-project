"""Say what is happening, and say whether the machine can run at all.

Two gaps a person without a terminal falls into.

For sixty-five minutes the live panel showed a status word, a cost bar and an
event list — not enough to distinguish a working pipeline from a hung one. I
watched "designing" for half an hour during the showcase run and resorted to
reading uvicorn.log. A researcher has no log, and after twenty silent minutes
the reasonable conclusion is that the tool is broken.

And `e2er doctor` is excellent and invisible: someone who never opens a terminal
learns their CLI backend is not logged in only when their first paper dies
several minutes in, for a reason nothing on screen explains.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from src.api.app import _progress, app


def _ev(kind: str, *, minutes_ago: int, specialist: str = "", stage: str = "") -> dict:
    return {
        "event_type": kind,
        "specialist": specialist or None,
        "stage": stage or None,
        "created_at": datetime.now(UTC) - timedelta(minutes=minutes_ago),
    }


def test_a_running_specialist_is_named_with_its_elapsed_time():
    """The question during a long run is "is anything happening", and the
    answer is a name and a number."""
    events = [  # newest first, as the query returns them
        _ev("specialist_start", minutes_ago=7, specialist="idea_developer"),
        _ev("phase_start", minutes_ago=8, stage="initial"),
    ]
    p = _progress(events, {"status": "designing"})

    assert [a["name"] for a in p["active"]] == ["idea_developer"]
    assert p["active"][0]["minutes"] == 7
    assert p["elapsed_min"] == 8


def test_a_finished_specialist_stops_being_reported_as_running():
    events = [
        _ev("specialist_end", minutes_ago=1, specialist="idea_developer"),
        _ev("specialist_start", minutes_ago=6, specialist="idea_developer"),
    ]
    assert _progress(events, {"status": "designing"})["active"] == []


def test_a_failed_specialist_also_stops_being_reported_as_running():
    """Otherwise a crashed specialist spins forever in the UI."""
    events = [
        _ev("specialist_failed", minutes_ago=1, specialist="data_analyst"),
        _ev("specialist_start", minutes_ago=9, specialist="data_analyst"),
    ]
    assert _progress(events, {"status": "designing"})["active"] == []


def test_phases_are_marked_done_running_and_pending():
    events = [
        _ev("phase_start", minutes_ago=2, stage="review"),
        _ev("phase_end", minutes_ago=3, stage="initial"),
        _ev("phase_start", minutes_ago=20, stage="initial"),
    ]
    states = {p["name"]: p["state"] for p in _progress(events, {"status": "review"})["phases"]}

    assert states["initial"] == "done"
    assert states["review"] == "running"
    assert states["revision"] == "pending"


def test_a_finished_run_shows_no_pending_work():
    """A completed paper listing phases it will never run reads as unfinished."""
    events = [
        _ev("phase_end", minutes_ago=1, stage="review"),
        _ev("phase_start", minutes_ago=5, stage="review"),
    ]
    p = _progress(events, {"status": "completed"})

    assert p["terminal"] is True
    assert all(ph["state"] != "pending" for ph in p["phases"])


def test_no_events_does_not_crash():
    p = _progress([], {"status": "idea"})
    assert p["active"] == []
    assert p["elapsed_min"] is None


def test_unparseable_timestamps_are_survivable():
    """SQLite hands back strings, Postgres hands back datetimes, and a bad row
    must not take the page down."""
    events = [{"event_type": "specialist_start", "specialist": "x", "stage": None, "created_at": "not-a-date"}]
    p = _progress(events, {"status": "designing"})
    assert [a["name"] for a in p["active"]] == ["x"]
    assert p["active"][0]["minutes"] is None


# ── preflight in the browser ─────────────────────────────────────────────────


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


def test_preflight_page_renders(client: TestClient):
    r = client.get("/preflight")
    assert r.status_code == 200
    assert "Preflight" in r.text


def test_the_banner_states_readiness(client: TestClient):
    """It loads with the new-paper form, so the answer arrives before the ask."""
    r = client.get("/htmx/preflight-banner")
    assert r.status_code == 200
    assert ("Ready" in r.text) or ("not ready" in r.text.lower())


def test_the_new_paper_form_asks_for_the_banner(client: TestClient):
    r = client.get("/papers/new")
    assert "/htmx/preflight-banner" in r.text


def test_the_fast_mode_is_the_default(client: TestClient):
    """iterative adds self-attack and polish and runs far longer; defaulting a
    newcomer's first paper to it is how you lose them."""
    r = client.get("/papers/new")
    assert 'value="single_pass" selected' in r.text
