"""Every dashboard page, read as a researcher reads it: no internal names, no raw errors.

Björn reads every page of the dashboard. Before 0.14.0 they showed the
code's own names (``number_check``, ``paper_drafter``, ``phase_start``,
``skills.installed``, ``BudgetExceededError``, ``ANTHROPIC_API_KEY``), study
ids, a raw JSON body for a wrong address, and four words for one thing
(attempt, version, run, paper). This test renders every page with a study at
every kind of stop (tests/dashboard_fixture.py) and reads the visible text:

* no internal id of a step, specialist, event, check or template;
* none of the words the dashboard no longer uses (artifact, audit bundle, …);
* no JSON error body;
* no full id (UUID).

Ids may appear inside a folded "Technical details" (``<details class="tech">``),
which is where they help with a bug report, and in links (not visible). Text
others wrote (a skill pack's description, class ``quoted``) is theirs.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

import pytest
from fastapi.testclient import TestClient

from src.api import local_session as ls
from src.core import labels
from src.db import client as _client
from tests.dashboard_fixture import Fixture, build, env_for

_REAL = (_client.execute, _client.fetch_one, _client.fetch_all)
TOKEN = "vocabulary-test-token-0123456789"
BASE = "http://127.0.0.1:8290"

#: Words the dashboard does not use any more, with the word it uses instead.
JARGON = {
    "artifact": "file",
    "artifacts": "files",
    "audit bundle": "download all files",
    "researcher step": "stopped for you",
    "workspace": "folder",
    "pipeline": "template",
    "backend": "AI provider",
    "sidecar": "also writes",
    "cost cap": "spending limit",
    "budget": "spending limit",
    "attempts of": "runs of",
    "single pass": "one pass",
    "gates": "checks",
}

_UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")
_JSON_ERROR = re.compile(r'\{\s*"detail"\s*:')


def _internal_ids() -> set[str]:
    # A file name (polish_formula.md) is a file name, not an id: an id followed by ".x" does not count.
    # Ids that are also plain words ("failed", "docker", "review") are left out: only the code's own names.
    coded = set(labels.SPECIALISTS) | set(labels.EVENTS) | set(labels.CHECKS) | {"backend.claude_code"}
    ids = {i for i in coded if "_" in i or "." in i}
    ids |= {s for s in labels.STEPS if "_" in s}
    ids |= {t for t in labels.TEMPLATES if "-" in t}
    ids |= {
        "BudgetExceededError",
        "RuntimeError",
        "ANTHROPIC_API_KEY",
        "OPENROUTER_API_KEY",
        "FRED_API_KEY",
        "ZENODO_TOKEN",
        "ZENODO_SANDBOX_TOKEN",
        "single_pass",
        "review_at",
        "send_back",
        "claude_code",
        "e2er v3",
    }
    return ids


class _Visible(HTMLParser):
    """The text a person sees: no scripts or styles, nothing inside <details class="tech">, plus
    the placeholders and tooltips."""

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0
        self._stack: list[bool] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        classes = (a.get("class") or "").split()
        # Technical details, and text others wrote (a skill pack's own description: class "quoted").
        hidden = tag in {"script", "style"} or (tag == "details" and "tech" in classes) or "quoted" in classes
        if tag not in {"br", "input", "img", "meta", "link", "hr"}:
            self._stack.append(hidden)
            if hidden:
                self._skip += 1
        if not self._skip:
            for k in ("placeholder", "title", "aria-label"):
                if a.get(k):
                    self.parts.append(str(a[k]))

    def handle_endtag(self, tag):
        if tag in {"br", "input", "img", "meta", "link", "hr"} or not self._stack:
            return
        if self._stack.pop():
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def visible_text(html: str) -> str:
    p = _Visible()
    p.feed(html)
    return " ".join(" ".join(p.parts).split())


def problems(html: str) -> list[str]:
    text = visible_text(html)
    found = []
    for ident in sorted(_internal_ids()):
        if m := re.search(rf"(?<![\w./-]){re.escape(ident)}(?![\w-]|\.\w)", text):
            found.append(f"internal id {ident!r} in “…{text[max(0, m.start() - 60) : m.end() + 40]}…”")
    low = text.lower()
    for word, instead in JARGON.items():
        if m := re.search(rf"(?<![\w-]){re.escape(word)}(?![\w-])", low):
            found.append(f"{word!r} (say {instead!r}) in “…{text[max(0, m.start() - 60) : m.end() + 40]}…”")
    if _JSON_ERROR.search(html):
        found.append("a raw JSON error body")
    if m := _UUID.search(text):
        found.append(f"a full id {m.group(0)} outside the technical details")
    return found


@pytest.fixture(scope="module")
def fx(tmp_path_factory) -> Fixture:
    folder = tmp_path_factory.mktemp("dash")
    mp = pytest.MonkeyPatch()
    for k, v in env_for(folder).items():
        mp.setenv(k, v)
    mp.setenv(ls.ENV_TOKEN, TOKEN)
    mp.setenv("HOME", str(folder / "home"))
    mp.chdir(folder / "study") if (folder / "study").is_dir() else None
    (folder / "home").mkdir(exist_ok=True)
    mp.setattr(_client, "execute", _REAL[0])
    mp.setattr(_client, "fetch_one", _REAL[1])
    mp.setattr(_client, "fetch_all", _REAL[2])
    fixture = build(folder)
    mp.chdir(fixture.study)
    yield fixture
    mp.undo()
    from src.config import get_settings

    get_settings.cache_clear()
    _client._backend = ""
    _client._sqlite_bootstrapped = False


@pytest.fixture
def client(fx, monkeypatch) -> TestClient:
    for k, v in env_for(fx.folder).items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv(ls.ENV_TOKEN, TOKEN)
    monkeypatch.setenv("HOME", str(fx.folder / "home"))
    monkeypatch.chdir(fx.study)
    monkeypatch.delenv("E2ER_SKIP_SETUP_REDIRECT", raising=False)
    monkeypatch.setattr(_client, "execute", _REAL[0])
    monkeypatch.setattr(_client, "fetch_one", _REAL[1])
    monkeypatch.setattr(_client, "fetch_all", _REAL[2])
    from src.config import get_settings

    get_settings.cache_clear()
    _client._backend = ""
    _client._sqlite_bootstrapped = False

    async def _checks():  # the doctor's network checks are not this test's business
        return {
            "checks": [
                {"name": "python", "status": "PASS", "detail": "Python 3.12"},
                {"name": "backend.claude_code", "status": "PASS", "detail": "`claude` found; signed in"},
                {"name": "skills.installed", "status": "PASS", "detail": "152 instruction files"},
                {"name": "data.fred.key", "status": "SKIP", "detail": "no FRED key"},
            ],
            "ready": True,
            "blockers": [],
            "n_pass": 3,
            "n_skip": 1,
            "n_fail": 0,
            "error": "",
        }

    monkeypatch.setattr("src.api.app._preflight", _checks)
    c = TestClient(_app(), base_url=BASE, client=("127.0.0.1", 50000))
    c.cookies.set("e2er_session_8290", TOKEN)
    return c


def _app():
    from src.api.app import app

    return app


def _pages(fx: Fixture) -> list[str]:
    pages = ["/", "/?archived=1", "/papers/new", "/setup", "/preflight", "/library", "/skills", "/workflow"]
    pages += [f"/studies/{k}" for k in dict.fromkeys(fx.keys.values()) if k]
    for name, pid in fx.ids.items():
        pages += [f"/papers/{pid}", f"/htmx/papers/{pid}/live", f"/papers/{pid}/review"]
    pages.append(f"/papers/{fx.ids['finished']}/finish")
    return pages


def test_every_page_reads_plainly(client, fx):
    bad: dict[str, list[str]] = {}
    for path in _pages(fx):
        r = client.get(path)
        assert r.status_code == 200, f"{path}: {r.status_code} {r.text[:300]}"
        if found := problems(r.text):
            bad[path] = found
    assert not bad, "\n".join(f"{p}: {', '.join(f)}" for p, f in bad.items())


@pytest.mark.parametrize(
    "path, status",
    [
        ("/papers/00000000-0000-4000-8000-000000000000", 404),
        ("/papers/not-an-id", 404),
        ("/no/such/page", 404),
        ("/studies/no-such-study", 404),
    ],
)
def test_an_error_is_a_page_with_the_way_back(client, path, status):
    r = client.get(path)
    assert r.status_code == status
    assert "text/html" in r.headers["content-type"]
    assert "Back to your studies" in r.text and not problems(r.text)


def test_a_tab_without_the_session_gets_a_page_that_says_what_to_do(fx, client):
    c = TestClient(_app(), base_url=BASE, client=("127.0.0.1", 50000))  # no cookie
    r = c.post("/papers", data={"research_question": "Q"})
    assert r.status_code == 403 and "text/html" in r.headers["content-type"]
    assert "not signed in" in r.text and "e2er" in r.text and not problems(r.text)


def test_the_api_keeps_answering_json(client):
    r = client.get("/api/papers/00000000-0000-4000-8000-000000000000")
    assert r.status_code == 404 and r.json()["detail"]


def test_a_live_panel_error_is_a_fragment_not_json(client):
    r = client.get("/htmx/papers/00000000-0000-4000-8000-000000000000/live", headers={"HX-Request": "true"})
    assert r.status_code == 404 and "<div" in r.text and not _JSON_ERROR.search(r.text)
    assert "<html" not in r.text.lower()


def test_the_check_finds_what_it_is_for():
    """The check itself: each kind of mess it must catch."""
    assert problems("<p>Researcher step: number_check</p>")
    assert problems("<p>paper_drafter: 3 attempts</p>")
    assert problems("<p>Download audit bundle</p>")
    assert problems('{"detail":"Paper not found"}')
    assert problems("<p>run 2f1c7a3e-1b2c-4d5e-8f90-123456789abc</p>")
    assert not problems(
        '<details class="tech"><summary>Technical details</summary>'
        "<p>number_check 2f1c7a3e-1b2c-4d5e-8f90-123456789abc</p></details>"
    )
    assert not problems('<a href="/papers/2f1c7a3e-1b2c-4d5e-8f90-123456789abc">Run 2</a>')


def test_every_label_has_a_plain_name():
    """No step of a built-in template falls back to its id with spaces."""
    from src.core.pipeline.spec import available, load_spec

    for name, path in available().items():
        spec = load_spec(path)
        assert labels.template(name, spec) != name
        for st in spec.steps:
            assert st.name in labels.STEPS, f"{name}: step {st.name} has no plain name"
            for sp in st.run:
                assert sp in labels.SPECIALISTS, f"{name}: specialist {sp} has no plain name"


def test_folders_are_named_after_the_date_and_title(fx):
    """New runs get readable folder names; the fixture's id-named ones (older runs) still open."""
    from src.home import find_workspace, new_workspace, paper_id_of

    root = fx.study / "workspaces"
    pid = "11111111-2222-4333-8444-555555555555"
    ws = new_workspace(root, "Do FOMC announcements move bank stocks?", pid)
    (ws / "manifest.json").write_text(f'{{"paper_id": "{pid}"}}')
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}-do-fomc-announcements-move-bank-stocks", ws.name)
    from src import home

    home._KNOWN.clear()
    assert find_workspace(pid, root) == ws and paper_id_of(ws) == pid
    assert find_workspace(fx.ids["finished"], root) == root / fx.ids["finished"]
    again = new_workspace(root, "Do FOMC announcements move bank stocks?", "x")
    assert again.name.endswith("-2")


def test_a_dashboard_with_studies_has_no_unlabelled_steps(client, fx):
    """The step list of every run names its steps (the live panel)."""
    for pid in fx.ids.values():
        text = visible_text(client.get(f"/htmx/papers/{pid}/live").text)
        assert "Design, data, estimation and draft" in text or "Fetch and verify" in text


def test_the_review_page_leads_with_the_decision(client, fx):
    html = client.get(f"/papers/{fx.ids['numbers']}/review").text
    decision = html.index('id="decision"')
    assert decision < html.index("Send a step back") < html.index("<h2>Files</h2>")
    assert html.index('id="approve"') < html.index("Send a step back")
    for col in ("Where in the paper", "In the table", "In the results", "Results file and entry"):
        assert f"<th>{col}</th>" in html
    # Files are folded and readable; editing opens on a click.
    assert '<details class="rv-file">' in html and "Edit this file" in html
    assert "You are editing the LaTeX source" in html


def test_a_stop_you_asked_for_lists_the_steps_outputs(client, fx):
    data = client.get(f"/api/papers/{fx.ids['asked_stop']}/review").json()
    names = [f["name"] for f in data["files"]]
    assert names == ["review_technical.md"], names
