"""Every researcher action of the command line is in the dashboard too.

Björn, 2026-10-04: "those things should be possible on the local host ui, too!"
The dashboard offers, beside the researcher steps (review.html):

* on the new-study page: the stops after a step (`e2er run --review-at`);
* on the study page: run again from a step with a remark (`e2er rerun`), also
  after a failure or a stop; resume a failed or stopped study (`e2er resume`);
  resume with a higher spending limit (`e2er resume --max-cost`); deposit the
  frozen pre-registration (`e2er preregister deposit --zenodo`); data queries
  waiting for approval;
* on the finish page: where public data and code live, the Zenodo deposit,
  name, ORCID iD and licence, and the confirmation of a data source's terms
  (`e2er publish --accept-data-terms gmd`).
"""

# ruff: noqa: F811 — the fixtures imported from test_browser_setup are test parameters here
from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src.api.app import app

from .test_browser_setup import BASE, TOKEN, live_db, session  # noqa: F401 — fixtures

PID = str(uuid.uuid4())


def _row(live_db: Path, status: str, *, pipeline: str = "replication", error: str | None = None, **extra: Any) -> Path:
    from src.db.client import execute

    ws = live_db / "workspaces" / PID
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "manifest.json").write_text(json.dumps({"paper_id": PID, "title": "T", **extra.get("manifest", {})}))
    asyncio.run(
        execute(
            "INSERT INTO papers (id, title, research_question, status, workspace, mode, methodology, pipeline, "
            "last_error, max_cost_usd) VALUES (%(id)s, 'T', 'Q?', %(st)s, %(ws)s, 'single_pass', 'empirical', "
            "%(pl)s, %(err)s, 0.5)",
            {"id": PID, "st": status, "ws": str(ws), "pl": pipeline, "err": error},
        )
    )
    return ws


def _client() -> TestClient:
    c = TestClient(app, base_url=BASE, client=("127.0.0.1", 5))
    c.cookies.set("e2er_session_8290", TOKEN)
    return c


# ── new study: the stops after a step ───────────────────────────────────────


def test_the_new_study_form_offers_the_stops_after_a_step_and_passes_them(monkeypatch):
    from src.api import app as app_module

    html = TestClient(app).get("/papers/new").text
    for stage in ("initial", "estimation_gate", "review", "replication"):
        assert f'name="review_at" value="{stage}"' in html
    seen: dict[str, Any] = {}

    async def _create(req, bg):
        seen["req"] = req
        return app_module.PaperResponse(paper_id=PID, title=req.title, status="idea", workspace="/tmp/x")

    monkeypatch.setattr(app_module, "create_paper", _create)
    r = TestClient(app).post(
        "/papers",
        data={
            "research_question": "Does X affect Y?",
            "review_at": ["review", "estimation_gate"],
            "demonstration": "1",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text
    assert seen["req"].review_stages == ["review", "estimation_gate"]
    assert seen["req"].purpose == "demonstration"


# ── the study page ──────────────────────────────────────────────────────────


def test_the_study_page_offers_a_rerun_from_the_templates_steps(live_db):
    _row(live_db, "completed", manifest={"purpose": "demonstration"})
    html = _client().get(f"/papers/{PID}").text
    assert 'id="rerun-box"' in html and 'id="rerun-box" class="card" hidden' not in html
    for step in ("fetch", "plan", "sandbox_run", "compare", "reproduction_gate"):
        assert f'<option value="{step}">' in html
    for researcher_step in ("review_plan", "review_report"):
        assert f'<option value="{researcher_step}">' not in html
    assert "Run again from this step" in html and 'id="rerun-remark"' in html
    assert "Demonstration or test run" in html


def test_a_failed_study_can_be_resumed_and_run_again_from_the_page(live_db):
    _row(live_db, "failed", error="RuntimeError: step 'compare': reproduction_comparer failed")
    live = _client().get(f"/htmx/papers/{PID}/live").text
    assert f'hx-post="/api/papers/{PID}/resume"' in live
    assert 'data-rerun="1"' in live and 'data-budget="0"' in live


def test_a_budget_pause_offers_a_higher_limit_and_no_plain_resume(live_db):
    _row(live_db, "paused", error="BudgetExceededError: spent $0.52, cap $0.50")
    c = _client()
    live = c.get(f"/htmx/papers/{PID}/live").text
    assert 'data-budget="1"' in live and 'id="resume"' not in live
    page = c.get(f"/papers/{PID}").text
    assert 'id="budget-cap"' in page and "Resume with this limit" in page


def test_data_queries_waiting_for_approval_show_in_the_live_panel(live_db, monkeypatch):
    _row(live_db, "in_progress")

    async def _queries(pid):
        return [{"id": "q1", "query_sql": "SELECT 1", "estimated_rows": 10}]

    monkeypatch.setattr("src.api.app._pending_queries_or_none", _queries)
    live = _client().get(f"/htmx/papers/{PID}/live").text
    assert 'data-query="q1" data-approve="1"' in live and 'data-query="q1" data-approve="0"' in live


def test_the_frozen_preregistration_is_deposited_from_the_page(live_db, session, monkeypatch):
    ws = _row(live_db, "completed", pipeline="empirical-preregistered")
    (ws / "preregistration.lock.json").write_text(
        json.dumps({"file": "preregistration.md", "sha256": "a" * 64, "frozen_at": "2026-10-04T10:00:00Z"})
    )
    c = _client()
    assert 'id="prereg-deposit"' in c.get(f"/papers/{PID}").text
    monkeypatch.delenv("ZENODO_TOKEN", raising=False)
    r = c.post(f"/api/papers/{PID}/preregistration/deposit", json={})
    assert r.status_code == 422 and "ZENODO_TOKEN" in r.json()["detail"]
    monkeypatch.setenv("ZENODO_TOKEN", "tok")
    calls: list[Any] = []

    def _deposit(folder, token, *, base_url):
        calls.append((folder, token, base_url))
        return {"service": "zenodo", "doi": "10.5281/zenodo.1", "url": "https://zenodo.org/records/1"}

    monkeypatch.setattr("src.core.pipeline.preregistration.deposit_zenodo", _deposit)
    r = c.post(f"/api/papers/{PID}/preregistration/deposit", json={})
    assert r.status_code == 200 and r.json()["doi"] == "10.5281/zenodo.1"
    assert calls[0][0] == ws and calls[0][1] == "tok" and "sandbox" not in calls[0][2]


# ── researcher steps: the wording per kind ──────────────────────────────────


@pytest.mark.parametrize(
    ("kind", "button", "text"),
    [
        ("gate", "Continue: run the check again", "the check runs again when the run continues"),
        ("deviation", "Approve the deviation and continue", "The pre-registered plan changed"),
        ("contract", "Keep the output as it is and continue", "failed its check in every attempt"),
        ("numbers", "Continue with these mismatches", "differ from the results files"),
        ("preregister", "Approve and freeze", "freezes it with its fingerprint"),
    ],
)
def test_each_stop_says_what_continuing_means(monkeypatch, kind: str, button: str, text: str):
    async def _review(pid):
        return {
            "pending": {"stage": "estimation_gate", "kind": kind, "reasons": ["why"]},
            "files": [],
            "sendable": ["identification_strategist"],
            "actions": [],
        }

    monkeypatch.setattr("src.api.app.get_review", _review)
    html = TestClient(app).get(f"/papers/{PID}/review").text
    assert button in html and text in html
    assert 'id="send-back"' in html and 'id="send-instr"' in html


# ── finish: availability, terms, identity ───────────────────────────────────


def _gmd_export(live_db: Path) -> Path:
    from src.core.export.structured import export_paper
    from src.db.client import execute

    ws = _row(live_db, "completed", pipeline="empirical")
    for kind in ("specialist_start", "specialist_end"):  # a recorded run, as publish needs
        asyncio.run(
            execute(
                "INSERT INTO pipeline_events (paper_id, event_type, stage, specialist, payload) "
                "VALUES (%(p)s, %(t)s, 'initial', 'paper_drafter', '{}')",
                {"p": PID, "t": kind},
            )
        )
    (ws / "paper_draft.tex").write_text("\\section{A}\nText.\n")
    (ws / "data_sources.json").write_text(
        json.dumps({"loads": [{"connector": "gmd", "version": "2025_09", "saved_to": "data/gmd.csv"}]})
    )
    return export_paper(ws, live_db / "exports", date_str="20261004")


def test_the_finish_page_asks_to_confirm_the_gmd_terms(live_db, session):
    _gmd_export(live_db)
    html = _client().get(f"/papers/{PID}/finish").text
    assert "The study uses data from the Global Macro Database" in html
    assert 'class="confirm-terms" value="gmd"' in html
    assert 'id="pub-data-url"' in html and 'id="pub-zenodo"' in html and 'id="pub-orcid"' in html
    # What readers on e2er.org see for what stays private; for GMD data the source, and no nudge.
    assert 'name="paper" value="public"' in html and 'id="pub-paper-url"' in html
    assert "Private: readers on e2er.org see a button to ask you for the paper." in html
    assert "readers on e2er.org see a link to the GMD instead of a request button" in html
    assert "Private: readers on e2er.org see a button to ask you for the data." not in html


def test_the_finish_page_passes_every_publish_choice(live_db, session, monkeypatch):
    _gmd_export(live_db)
    seen: dict[str, Any] = {}

    def _publish(bundle, **kw):
        seen.update(kw, bundle=bundle)
        print("{}")
        return 0

    monkeypatch.setattr("src.cli_publish.publish", _publish)
    r = _client().post(
        f"/api/papers/{PID}/publish",
        json={
            "owner": "kim",
            "project": "gmd-study",
            "data": "public",
            "code": "public",
            "data_url": "https://doi.org/10.1/x",
            "code_url": " ",
            "paper": "public",
            "paper_url": " https://example.org/kim/paper.pdf ",
            "zenodo": True,
            "accept_data_terms": ["gmd"],
            "name": "Kim Dash",
            "orcid": "0000-0002-1825-0097",
            "license_id": "CC-BY-4.0",
            "roles": ["Conceptualization", " "],
            "repo": "https://github.com/kim/gmd-study",
            "commit": "0123456789abcdef0123456789abcdef01234567",
            "path": "study",
            "derived_from": ["ana/base-study"],
            "demonstration": True,
        },
    )
    assert r.status_code == 200, r.text
    assert seen["accept_data_terms"] == ["gmd"] and seen["zenodo"] is True
    assert seen["data_url"] == "https://doi.org/10.1/x" and seen["code_url"] is None
    assert seen["paper"] == "public" and seen["paper_url"] == "https://example.org/kim/paper.pdf"
    assert seen["name"] == "Kim Dash" and seen["orcid"] == "0000-0002-1825-0097" and seen["license_id"] == "CC-BY-4.0"
    assert seen["demonstration"] is True and seen["data"] == "public"
    assert seen["roles"] == ["Conceptualization"] and seen["derived_from"] == ["ana/base-study"]
    assert (
        seen["repo"] == "https://github.com/kim/gmd-study"
        and seen["commit"].startswith("0123")
        and seen["path"] == "study"
    )


def test_publishing_public_gmd_data_without_the_confirmation_is_refused(live_db, session):
    _gmd_export(live_db)
    r = _client().post(
        f"/api/papers/{PID}/publish",
        json={"owner": "kim", "project": "gmd-study", "data": "public", "code": "private", "dry_run": True},
    )
    assert r.status_code == 200 and r.json()["ok"] is False
    assert "needs your confirmation of the GMD terms" in r.json()["output"]


def test_the_finish_page_says_yahoo_allows_personal_use_only(live_db, session):
    from src.core.export.structured import export_paper

    _gmd_export(live_db)
    ws = live_db / "workspaces" / PID
    (ws / "data_sources.json").write_text(
        json.dumps({"loads": [{"connector": "yfinance", "saved_to": "data/btc.csv"}]})
    )
    export_paper(ws, live_db / "exports", date_str="20261005")
    html = _client().get(f"/papers/{PID}/finish").text
    assert "The study uses data from Yahoo Finance. Its terms:" in html
    assert 'class="confirm-terms" value="yfinance"' in html
    assert "Publish the Yahoo Finance data with the study although Yahoo&#39;s terms allow personal use only" in html
    assert (
        "If the data stay private, readers on e2er.org see a link to Yahoo Finance instead of a request button: "
        "its terms allow personal use only."
    ) in html
    assert '<p class="small">Citation:' not in html and "Global Macro Database" not in html
    assert "Private: readers on e2er.org see a button to ask you for the data." not in html
