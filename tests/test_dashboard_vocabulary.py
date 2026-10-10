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
    "mismatch": "difference",
    "mismatches": "differences",
}

_UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")
_JSON_ERROR = re.compile(r'\{\s*"detail"\s*:')
#: Raw error text and instructions for scripts: never outside "Technical details".
_RAW = re.compile(
    r"ConnectionError|ConnectError|curl: \(\d+\)|Traceback \(most recent|\[Errno|POST /api/|`e2er resume`|"
    r"\b[A-Z]\w*Error\(|Paused for human review|Circuit breaker:"
)


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
        *labels.SETTINGS,
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
    if m := _RAW.search(text):
        found.append(f"raw error text {m.group(0)!r} in “…{text[max(0, m.start() - 60) : m.end() + 40]}…”")
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
                # `e2er doctor`'s own text, as the terminal prints it: the page says it plainly.
                {"name": "python", "status": "PASS", "detail": "Python 3.12.4"},
                {
                    "name": "backend.claude_code",
                    "status": "PASS",
                    "detail": "CLI at /usr/local/bin/claude ($0 on the subscription); signed in",
                },
                {"name": "skills.installed", "status": "PASS", "detail": "152 skill files under src/skills/files/"},
                {"name": "db", "status": "PASS", "detail": "SQLite default (auto-created at /h/.e2er/papers.db)"},
                {
                    "name": "byod.literature",
                    "status": "SKIP",
                    "detail": "no LITERATURE_BIBTEX_FILE / LITERATURE_DIR / LOCAL_DATA_DIR — OpenAlex-only",
                },
                {
                    "name": "byod.local_data_dir",
                    "status": "SKIP",
                    "detail": "LOCAL_DATA_DIR not set (no bring-your-own datasets)",
                },
                {"name": "data.fred.key", "status": "SKIP", "detail": "FRED_API_KEY not set"},
                {"name": "data.allium.list_tables", "status": "SKIP", "detail": "ALLIUM_API_KEY not set"},
                {"name": "lit.zotero.library", "status": "SKIP", "detail": "ZOTERO_API_KEY + user/group id not set"},
                # A computer that cannot reach a service: the raw error only under Technical details.
                {
                    "name": "data.yfinance.history",
                    "status": "FAIL",
                    "detail": "ConnectionError: Failed to perform, curl: (7) Failed to connect to "
                    "query2.finance.yahoo.com:443 over proxy 127.0.0.1 after 0 ms",
                },
                {
                    "name": "data.fred.observations",
                    "status": "FAIL",
                    "detail": "transport error: All connection attempts failed",
                },
                {"name": "lit.search_papers", "status": "FAIL", "detail": "0 papers via arxiv"},
                {"name": "data.list_data_sources", "status": "FAIL", "detail": "RuntimeError('catalog broken')"},
            ],
            "ready": True,
            "n_pass": 4,
            "n_skip": 5,
            "n_fail": 4,
            "blockers": [],
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
        pages += [f"/papers/{pid}", f"/htmx/papers/{pid}/live", f"/papers/{pid}/review", f"/htmx/papers/{pid}/inputs"]
    pages.append(f"/papers/{fx.ids['finished']}/finish")
    # Choosing data and papers (0.15.0): the papers list New study loads, the Library's progress line.
    pages += ["/htmx/new/papers", "/htmx/library/adding"]
    return pages


def test_new_study_lists_the_data_files_and_the_papers(client, fx):
    page = client.get("/papers/new").text
    assert "fomc_announcement_dates.csv" in page and "bank_tickers.csv" in page and "Add files" in page
    papers = client.get("/htmx/new/papers").text
    assert "What Explains the Stock Market" in papers and 'name="paper_choice"' in papers


def test_the_run_and_finish_pages_say_what_the_study_used(client, fx):
    pid = fx.ids["finished"]
    panel = client.get(f"/htmx/papers/{pid}/inputs").text
    assert "fomc_announcement_dates.csv" in panel and "added for this study" in panel
    assert "Your papers (1)" in panel and "Found on the web (1)" in panel
    assert "your data file (fomc_announcement_dates.csv)" in panel
    finish = client.get(f"/papers/{pid}/finish").text
    assert "What the study used" in finish and "from your papers" in finish and "found on the web" in finish


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


@pytest.mark.parametrize(
    "name, detail, plain",
    [
        (
            "backend",
            "no AI access is set up in this folder (no LLM_BACKEND here or in .env). run `e2er`",
            "No AI provider",
        ),
        ("backend.anthropic", "ANTHROPIC_API_KEY not set — `e2er run` will fail", "No API key saved"),
        ("backend.codex", "CLI at /Applications/ChatGPT.app/codex, but not signed in", "Found, but not signed in"),
        (
            "backend.claude_code",
            "`claude` CLI not found on PATH or at CLAUDE_CODE_PATH — install it (https://x), or see https://y",
            "`claude` is not installed",
        ),
        ("byod.literature", "LITERATURE_BIBTEX_FILE=/x/refs.bib not found", "The .bib file /x/refs.bib was not found"),
        (
            "byod.literature",
            "literature dir /x/pdfs is not a directory",
            "The literature folder /x/pdfs does not exist",
        ),
        ("byod.local_data_dir", "LOCAL_DATA_DIR=/x/data is not a directory", "The data folder /x/data does not exist"),
        ("data.fred.key", "FRED_API_KEY has the format of a FRED key (…abcd)", "The FRED key has the right format"),
        ("data.fred.observations", "not requested: the key has the wrong format (data.fred.key)", "Not asked"),
        ("workspace.writable", "/tmp/my studies is outside the claude_code config tree", "Studies are written to"),
        (
            "db",
            "Postgres unreachable: x — if you didn't intend Postgres, unset DATABASE_URL / POSTGRES_URL to use the "
            "SQLite default",
            "remove the database address",
        ),
    ],
)
def test_preflight_says_the_doctor_text_plainly(name, detail, plain):
    text = labels.check_detail(name, detail)
    assert plain in text
    assert not problems(f"<p>{text}</p>"), text


def test_the_finish_page_of_a_published_study_says_so_and_offers_to_remove_older_copies(client, fx):
    """Published, nothing changed since: the page names the version with its links, Publish waits with a reason,
    and the two older copies can go (never the published folder)."""
    html = client.get(f"/papers/{fx.ids['finished']}/finish").text
    text = re.sub(r"\s+([,.])", r"\1", visible_text(html))  # the parser joins the link and the text with spaces
    assert "Published as kim-dash/fomc-bank-stocks, version 2." in text
    assert (
        'href="https://e2er.org/kim-dash/fomc-bank-stocks"' in html
        and 'href="https://e2er.org/d/bbbbbbbbbbbbbbbb"' in html
    )
    assert re.search(r'<button[^>]*id="do-publish"[^>]*disabled[^>]*>Publish</button>', html)
    assert "Nothing changed since this folder was published." in text
    assert "2 older copies of this folder" in text and "Remove older copies" in text
    # A new version goes to the same place: owner and project as published.
    assert (
        'name="owner" id="pub-owner" value="kim-dash"' in html and 'id="pub-project" value="fomc-bank-stocks"' in html
    )
    assert not problems(html)


def test_skills_without_the_internet_says_so_plainly(client, monkeypatch):
    from src.modules import skills_catalogue as sc

    def offline():
        raise sc.CatalogueError(
            "could not download the RISE catalogue from https://github.com/bhanneke/RISE ([Errno 61] Connection "
            "refused). Check the internet connection, or clone the repository."
        )

    monkeypatch.setattr(sc, "read_catalogue", offline)
    html = client.get("/skills").text
    assert "The skills catalogue (RISE, on GitHub) could not be reached." in visible_text(html)
    assert not problems(html)


def test_the_iterative_mode_shows_its_rounds_in_plain_words(client, fx):
    """Each round with its specialists, the ceiling check after it, the change of approach and the self-critique."""
    html = client.get(f"/htmx/papers/{fx.ids['iterative']}/live").text
    text = visible_text(html).replace(" :", ":")
    assert "Round 1: Estimation, Paper draft" in text
    assert "Ceiling check: another round" in text
    assert "Round 2: Sections and table layout" in text
    assert "Ceiling check: a change of approach" in text and "Change of approach: Abstract" in text
    assert "2 rounds, then a change of approach" in text
    assert "Self-critique: 2 findings, 1 serious; 1 correction made in the draft" in text
    assert "Polish: 2 notes; 1 change made in the draft" in text
    # The strategist's own words are shown as its words, not checked as e2er's.
    assert "section:discussion" in html and not problems(html)
    log = text[text.find("What happened") :]
    assert "Round of improvement" in log and "Ceiling check" in log and "Change of approach" in log
