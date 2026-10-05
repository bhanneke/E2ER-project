"""e2er in the browser: `e2er` alone opens a dashboard for setup, a new study, its review and publishing.

What these tests hold in place:

* The path helper. Björn's first `e2er init` failed twice at the literature
  prompt: he gave a folder where a .bib was asked for, then a path copied with
  the terminal prompt glyph in front ("❯ /Users/…"), which read as "Not found".
* The folder browser. It lists folders on this computer, so it must need the
  session token, answer only on 127.0.0.1 with a local Host header and no
  foreign Origin, stay inside the home folder, and not follow links out of it.
* Setup writes the same .env `e2er init` writes, owner-only (mode 600), keys
  included and never shown back in full.
* Template cards come from pipelines/*.toml; a study starts from the form and
  runs (on the mock backend) to its first pause; the finish page verifies.
* The two bugs from the 0.11.0 recording: `e2er review` without a terminal,
  and `e2er status` naming the wrong template.
"""

from __future__ import annotations

import json
import os
import stat
import time
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api import local_session as ls
from src.api.app import app
from src.paths import clean_path_input, inspect_data, inspect_literature, resolve_bib_answer

BASE = "http://127.0.0.1:8290"
TOKEN = "test-session-token-0123456789"


# ── fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def home(tmp_path: Path, monkeypatch) -> Path:
    """A private home folder with a literature library whose name has spaces."""
    h = tmp_path / "home"
    lib = h / "Documents" / "Zotero Export"
    (lib / "files" / "12").mkdir(parents=True)
    (lib / "My Library.bib").write_text("@article{a, title={A}}\n@book{b, title={B}}\n@comment{x}\n")
    (lib / "files" / "12" / "Smith 2020.pdf").write_bytes(b"%PDF-1.4")
    (h / "Documents" / ".hidden").mkdir()
    (h / "Documents" / ".secret.bib").write_text("@article{s,}")
    (h / "Data").mkdir()
    (h / "Data" / "prices.csv").write_text("a,b\n1,2\n")
    (h / "Data" / "notes.docx").write_text("x")
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.delenv("E2ER_BROWSE_ROOTS", raising=False)
    return h


@pytest.fixture
def session(monkeypatch):
    monkeypatch.setenv(ls.ENV_TOKEN, TOKEN)


def _client(*, cookie: bool = True, client_ip: str = "127.0.0.1", base: str = BASE) -> TestClient:
    c = TestClient(app, base_url=base, client=(client_ip, 50000))
    if cookie:
        c.cookies.set("e2er_session_8290", TOKEN)
    return c


# ── the path helper ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("/Users/b/My Library.bib", "/Users/b/My Library.bib"),
        ("  /Users/b/refs.bib  \n", "/Users/b/refs.bib"),
        ("❯ /Users/b/refs.bib", "/Users/b/refs.bib"),  # Björn's second attempt
        ("❯/Users/b/refs.bib", "/Users/b/refs.bib"),
        ("› /Users/b/refs.bib", "/Users/b/refs.bib"),
        ("$ /Users/b/refs.bib", "/Users/b/refs.bib"),
        ("% /Users/b/refs.bib", "/Users/b/refs.bib"),
        ("> /Users/b/refs.bib", "/Users/b/refs.bib"),
        ("# /Users/b/refs.bib", "/Users/b/refs.bib"),
        ("$ ❯ /Users/b/refs.bib", "/Users/b/refs.bib"),
        ("'/Users/b/My Library.bib'", "/Users/b/My Library.bib"),
        ('"/Users/b/My Library.bib"', "/Users/b/My Library.bib"),
        ("❯ '/Users/b/My Library.bib' ", "/Users/b/My Library.bib"),
        ("/Users/b/My\\ Library.bib", "/Users/b/My Library.bib"),  # drag-and-drop into Terminal
        ("/Users/b/Zotero\\ Export\\ \\(2026\\)/", "/Users/b/Zotero Export (2026)/"),
        ("file:///Users/b/My%20Library.bib", "/Users/b/My Library.bib"),
        ("$HOME/refs.bib", "$HOME/refs.bib"),  # a variable, not a prompt
        ("#notes/refs.bib", "#notes/refs.bib"),  # a name, not a prompt
        ("", ""),
        ("   ", ""),
    ],
)
def test_clean_path_input(raw, expected):
    assert clean_path_input(raw) == expected


def test_clean_path_input_expands_home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert clean_path_input("❯ ~/refs.bib") == str(tmp_path / "refs.bib")
    assert clean_path_input("'~/My Library.bib'") == str(tmp_path / "My Library.bib")


def test_bjoerns_folder_answer_is_offered_the_bib_inside(home):
    """He pasted the folder; it wanted a .bib. Now it offers the one inside."""
    folder = home / "Documents" / "Zotero Export"
    ans = resolve_bib_answer(str(folder))
    assert ans.ask == "That is a folder. It contains My Library.bib — use it?"
    assert ans.candidate == str(folder / "My Library.bib")
    assert ans.literature is not None and ans.literature.kind == "zotero_export"


def test_bjoerns_glyph_answer_resolves(home):
    """His second answer came with "❯ " in front and said "Not found"."""
    bib = home / "Documents" / "Zotero Export" / "My Library.bib"
    ans = resolve_bib_answer(f"❯ {bib}")
    assert ans.bib == str(bib) and not ans.error


def test_a_missing_path_says_what_was_expected_and_what_was_read(home):
    ans = resolve_bib_answer("❯ /nowhere/refs.bib")
    assert "Expected a .bib file or a folder" in ans.error
    assert "/nowhere/refs.bib" in ans.error


def test_a_file_that_is_not_bib_is_named(home):
    (home / "paper.pdf").write_bytes(b"%PDF")
    ans = resolve_bib_answer(str(home / "paper.pdf"))
    assert ".pdf file" in ans.error


def test_literature_kinds(home, tmp_path):
    zot = inspect_literature(home / "Documents" / "Zotero Export")
    assert (zot.kind, zot.n_references, zot.n_pdfs) == ("zotero_export", 2, 1)
    assert zot.settings() == {
        "LITERATURE_BIBTEX_FILE": str(home / "Documents" / "Zotero Export" / "My Library.bib"),
        "LITERATURE_DIR": str(home / "Documents" / "Zotero Export"),
    }

    pdfs = tmp_path / "pdfs"
    pdfs.mkdir()
    (pdfs / "a.pdf").write_bytes(b"%PDF")
    (pdfs / "sub").mkdir()
    (pdfs / "sub" / "b.pdf").write_bytes(b"%PDF")
    lit = inspect_literature(pdfs)
    assert (lit.kind, lit.n_pdfs) == ("pdf_folder", 2)
    assert lit.settings() == {"LITERATURE_DIR": str(pdfs)}

    many = tmp_path / "many"
    many.mkdir()
    (many / "a.bib").write_text("@a{x,}")
    (many / "b.bib").write_text("@a{y,}")
    assert inspect_literature(many).kind == "many_bibs"
    assert not inspect_literature(many).usable

    empty = tmp_path / "empty"
    empty.mkdir()
    assert inspect_literature(empty).kind == "empty"

    zlib = tmp_path / "Zotero"
    (zlib / "storage" / "K1").mkdir(parents=True)
    (zlib / "zotero.sqlite").write_bytes(b"")
    (zlib / "storage" / "K1" / "x.pdf").write_bytes(b"%PDF")
    assert inspect_literature(zlib).kind == "zotero_library"


def test_data_folder_lists_data_files_only(home):
    d = inspect_data(home / "Data")
    assert d.ok and d.files == ["prices.csv"]


def test_init_prompt_accepts_the_folder_after_confirmation(home, monkeypatch, capsys):
    """The terminal wizard uses the same helper: folder in, bib offered, yes taken."""
    from src import cli_init

    answers = iter([f"❯ {home / 'Documents' / 'Zotero Export'}", ""])
    prompts: list[str] = []

    def fake_input(prompt=""):
        prompts.append(prompt)
        return next(answers)

    monkeypatch.setattr("builtins.input", fake_input)
    settings = cli_init.ask_literature()
    assert "That is a folder. It contains My Library.bib — use it? [Y/n]" in prompts[1]
    assert settings["LITERATURE_BIBTEX_FILE"].endswith("My Library.bib")


def test_path_flags_are_cleaned(monkeypatch, tmp_path):
    """`e2er verify ❯ '/path with space'` reaches verify as a clean path."""
    import sys

    from src import __main__ as cli

    seen = {}
    monkeypatch.setattr("src.cli_verify.verify", lambda bundle, **kw: seen.setdefault("bundle", bundle) and 0)
    monkeypatch.setattr(sys, "argv", ["e2er", "verify", f"'{tmp_path}/My Study'"])
    with pytest.raises(SystemExit):
        cli.main()
    assert seen["bundle"] == f"{tmp_path}/My Study"


# ── the folder browser: who may use it ─────────────────────────────────────


def test_browse_needs_the_session_token(home, session):
    r = _client(cookie=False).get("/api/local/browse")
    assert r.status_code == 403
    assert "link e2er opened" in r.json()["detail"]


def test_browse_with_the_token_lists_home(home, session):
    r = _client().get("/api/local/browse", params={"kind": "literature"})
    assert r.status_code == 200
    d = r.json()
    assert d["path"] == os.path.realpath(home)
    assert {x["name"] for x in d["dirs"]} == {"Documents", "Data"}


def test_the_token_header_works_for_scripts(home, session):
    c = _client(cookie=False)
    assert c.get("/api/local/browse", headers={"X-E2ER-Token": TOKEN}).status_code == 200
    assert c.get("/api/local/browse", headers={"X-E2ER-Token": "wrong"}).status_code == 403


def test_only_loopback_clients(home, session):
    assert _client(client_ip="192.168.1.20").get("/api/local/browse").status_code == 403


@pytest.mark.parametrize("host", ["evil.example:8290", "192.168.1.20:8290", "e2er.org"])
def test_only_a_local_host_header(home, session, host):
    """A site that points its own name at 127.0.0.1 (DNS rebinding) sends its own Host."""
    assert _client().get("/api/local/browse", headers={"host": host}).status_code == 403


@pytest.mark.parametrize("host", ["127.0.0.1:8290", "localhost:8290", "[::1]:8290"])
def test_local_host_headers_pass(home, session, host):
    assert _client().get("/api/local/browse", headers={"host": host}).status_code == 200


def test_other_origins_are_refused_and_never_get_cors(home, session):
    c = _client()
    r = c.get("/api/local/browse", headers={"origin": "https://evil.example"})
    assert r.status_code == 403
    assert "access-control-allow-origin" not in {k.lower() for k in r.headers}
    assert c.get("/api/local/browse", headers={"sec-fetch-site": "cross-site"}).status_code == 403
    assert c.get("/api/local/browse", headers={"origin": BASE}).status_code == 200


def test_no_listing_outside_home(home, session, tmp_path):
    c = _client()
    outside = tmp_path / "outside"
    outside.mkdir()
    for p in ["/", "/etc", str(outside), str(home / ".." / ".."), f"{home}/../outside"]:
        assert c.get("/api/local/browse", params={"path": p}).status_code == 403, p
    assert c.get("/api/local/inspect", params={"path": str(outside)}).status_code == 403


def test_extra_roots_only_when_named(home, session, tmp_path, monkeypatch):
    extra = tmp_path / "Volumes"
    extra.mkdir()
    assert _client().get("/api/local/browse", params={"path": str(extra)}).status_code == 403
    monkeypatch.setenv("E2ER_BROWSE_ROOTS", str(extra))
    assert _client().get("/api/local/browse", params={"path": str(extra)}).status_code == 200


def test_symlinks_out_of_home_are_not_followed(home, session, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "stolen.bib").write_text("@a{x,}")
    (home / "Documents" / "escape").symlink_to(outside)
    (home / "Documents" / "escape.bib").symlink_to(outside / "stolen.bib")
    (home / "Documents" / "inside").symlink_to(home / "Data")
    c = _client()
    names = {x["name"] for x in c.get("/api/local/browse", params={"path": str(home / "Documents")}).json()["dirs"]}
    files = {x["name"] for x in c.get("/api/local/browse", params={"path": str(home / "Documents")}).json()["files"]}
    assert "escape" not in names and "escape.bib" not in files
    assert "inside" in names, "a link that stays inside home is fine"
    assert c.get("/api/local/browse", params={"path": str(home / "Documents" / "escape")}).status_code == 403


def test_hidden_files_are_not_listed(home, session):
    d = _client().get("/api/local/browse", params={"path": str(home / "Documents")}).json()
    assert ".hidden" not in {x["name"] for x in d["dirs"]}
    assert ".secret.bib" not in {x["name"] for x in d["files"]}


def test_paths_with_spaces_and_kinds(home, session):
    c = _client()
    lib = home / "Documents" / "Zotero Export"
    lit = c.get("/api/local/browse", params={"path": str(lib), "kind": "literature"}).json()
    assert [f["name"] for f in lit["files"]] == ["My Library.bib"]
    data = c.get("/api/local/browse", params={"path": str(home / "Data"), "kind": "data"}).json()
    assert [f["name"] for f in data["files"]] == ["prices.csv"]
    found = c.get("/api/local/inspect", params={"path": str(lib), "kind": "literature"}).json()
    assert (found["kind"], found["n_references"], found["n_pdfs"]) == ("zotero_export", 2, 1)


def test_the_launch_url_sets_a_strict_cookie_and_drops_the_token(home, session):
    c = _client(cookie=False)
    r = c.get(f"/setup?t={TOKEN}", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/setup"
    cookie = r.headers["set-cookie"].lower()
    assert "e2er_session_8290=" in cookie and "httponly" in cookie and "samesite=strict" in cookie
    assert c.get("/api/local/browse").status_code == 200


def test_a_wrong_launch_token_sets_nothing(home, session):
    c = _client(cookie=False)
    r = c.get("/setup?t=guess", follow_redirects=False)
    assert "set-cookie" not in r.headers
    assert c.get("/api/local/browse").status_code == 403


def test_the_session_file_is_owner_only(home):
    p = ls.write_session_file(8290, "abc")
    assert stat.S_IMODE(p.stat().st_mode) == 0o600
    assert ls.read_session_token(8290) == "abc"
    ls.remove_session_file(8290)
    assert not p.exists()


# ── setup writes .env ───────────────────────────────────────────────────────


@pytest.fixture
def project(home, tmp_path, monkeypatch) -> Path:
    from src.config import get_settings

    proj = home / "research"
    proj.mkdir()
    monkeypatch.chdir(proj)
    for k in ("LLM_BACKEND", "FRED_API_KEY", "ANTHROPIC_API_KEY", "CLAUDE_CODE_MODEL", "LITERATURE_DIR"):
        monkeypatch.delenv(k, raising=False)
    get_settings.cache_clear()
    yield proj
    get_settings.cache_clear()


def test_first_visit_goes_to_setup(project, session, monkeypatch):
    monkeypatch.delenv("E2ER_SKIP_SETUP_REDIRECT", raising=False)
    r = _client().get("/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/setup"


def test_setup_page_offers_backends_docker_and_instructions(project, session, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)  # nothing installed
    html = _client().get("/setup").text
    assert "Set up e2er" in html
    assert "e2er needs one of these" in html
    assert "https://code.claude.com/docs/en/setup" in html
    assert "https://console.anthropic.com/settings/keys" in html and "https://openrouter.ai/keys" in html
    assert "Only the replication template needs Docker" in html
    assert "Haiku — cheapest" in html


def test_setup_writes_env_mode_600_and_masks_keys(project, session):
    c = _client()
    lib = project.parent / "Documents" / "Zotero Export"
    r = c.post(
        "/api/setup/save",
        json={
            "backend": "claude_code",
            "model": "haiku",
            "literature": f"❯ {lib}",
            "data_dir": str(project.parent / "Data"),
            "keys": {"FRED_API_KEY": "fredkey-1234567890abcd"},
            "create_folders": True,
        },
        headers={"origin": BASE},
    )
    assert r.status_code == 200, r.text
    env = project / ".env"
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
    text = env.read_text()
    assert "LLM_BACKEND=claude_code" in text and "CLAUDE_CODE_MODEL=haiku" in text
    assert f"LITERATURE_BIBTEX_FILE='{lib / 'My Library.bib'}'" in text
    assert "FRED_API_KEY=fredkey-1234567890abcd" in text
    assert (project / "data").is_dir() and (project / "literature").is_dir()

    from src.config import Settings

    s = Settings()
    assert s.literature_bibtex_file == str(lib / "My Library.bib")
    assert s.literature_dir == str(lib)
    assert s.local_data_dir == str(project.parent / "Data")
    assert s.fred_api_key == "fredkey-1234567890abcd"

    page = c.get("/setup").text
    assert "fredkey-1234567890abcd" not in page, "a stored key is never shown in full"
    assert "…abcd" in page


def test_setup_keeps_stored_keys_and_unmanaged_settings(project, session):
    (project / ".env").write_text("LLM_BACKEND=anthropic\nANTHROPIC_API_KEY=sk-ant-old-9999\nGOVERNANCE=contracts\n")
    r = _client().post("/api/setup/save", json={"backend": "anthropic", "model": "claude-haiku-4-5"})
    assert r.status_code == 200
    text = (project / ".env").read_text()
    assert "ANTHROPIC_API_KEY=sk-ant-old-9999" in text
    assert "GOVERNANCE=contracts" in text
    assert "ANTHROPIC_MODEL=claude-haiku-4-5" in text


def test_setup_refuses_unusable_literature_and_unknown_backend(project, session, tmp_path):
    c = _client()
    empty = project.parent / "empty"
    empty.mkdir()
    r = c.post("/api/setup/save", json={"backend": "claude_code", "literature": str(empty)})
    assert r.status_code == 422 and "no .bib file and no PDFs" in r.json()["detail"]
    assert c.post("/api/setup/save", json={"backend": "gpt"}).status_code == 422
    assert not (project / ".env").exists()


def test_setup_save_needs_the_session(project, session):
    r = _client(cookie=False).post("/api/setup/save", json={"backend": "claude_code"})
    assert r.status_code == 403
    r = _client().post("/api/setup/save", json={"backend": "claude_code"}, headers={"origin": "https://evil.example"})
    assert r.status_code == 403
    assert not (project / ".env").exists()


def test_init_writes_env_owner_only(tmp_path):
    from src.cli_init import _write_env

    p = tmp_path / ".env"
    _write_env(p, "LLM_BACKEND=claude_code\n", force=True)
    assert stat.S_IMODE(p.stat().st_mode) == 0o600


# ── doctor ──────────────────────────────────────────────────────────────────


def test_doctor_points_to_install_instructions(monkeypatch):
    import asyncio
    import sys

    from src import doctor

    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)

    class S:
        llm_backend = "claude_code"

    check = asyncio.run(doctor.backend_check(S()))
    assert check.status == "FAIL" and "https://code.claude.com/docs/en/setup" in check.detail
    monkeypatch.setattr(sys, "version_info", (3, 10, 4))
    py = doctor.python_check()
    assert py.status == "FAIL" and doctor.INSTALL_URL in py.detail
    dk = doctor.docker_check()
    assert dk.status == "SKIP" and "only the replication template" in dk.detail


def test_cli_sign_in_is_read_from_files(tmp_path, monkeypatch):
    from src.doctor import cli_signed_in

    for k in ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "OPENAI_API_KEY", "CODEX_HOME"):
        monkeypatch.delenv(k, raising=False)
    (tmp_path / ".claude.json").write_text(json.dumps({"projects": {}}))
    assert cli_signed_in("claude_code", tmp_path)[0] is False
    (tmp_path / ".claude.json").write_text(json.dumps({"oauthAccount": {"emailAddress": "x"}}))
    assert cli_signed_in("claude_code", tmp_path)[0] is True
    assert cli_signed_in("codex", tmp_path)[0] is False


# ── new study: template cards, starting one ─────────────────────────────────


def test_template_cards_come_from_the_pipeline_files():
    import tomllib

    html = TestClient(app).get("/papers/new").text
    root = Path(__file__).resolve().parents[1] / "pipelines"
    for name in ("empirical", "empirical-preregistered", "event-study-finance", "replication"):
        spec = tomllib.loads((root / f"{name}.toml").read_text())
        assert f'value="{name}"' in html
        assert spec["description"].replace("'", "&#39;") in html
    assert "Stops for you at:</b> Design review, Pre-registration, Draft review" in html
    assert "Stops for you at:</b> Plan review, Report review" in html
    assert "Runs through without stopping" in html
    assert 'name="demonstration"' in html


def test_the_templates_ship_in_the_package():
    """0.11.0's wheel had no pipelines/, so a fresh install could not start any study."""
    import tomllib

    data = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text())
    st = data["tool"]["setuptools"]
    assert "pipelines" in st["packages"]["find"]["include"]
    assert st["package-data"]["pipelines"] == ["*.toml"]
    assert (Path(__file__).resolve().parents[1] / "pipelines" / "__init__.py").is_file()


@pytest.fixture
def live_db(tmp_path, monkeypatch):
    """A real SQLite database and workspace root in tmp, and the mock AI backend."""
    import src.db.client as dbc
    from src.config import get_settings

    from .conftest import MockLLMBackend

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'papers.db'}")
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path / "workspaces"))
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "exports"))
    monkeypatch.setenv("LLM_BACKEND", "claude_code")
    monkeypatch.setattr(dbc, "_backend", "", raising=False)
    monkeypatch.setattr(dbc, "_sqlite_bootstrapped", False)

    # conftest replaces the DB helpers with no-ops for every test; this one
    # wants the real SQLite database.
    async def _fetch_one(sql, params=None):
        rows = await dbc._sqlite_fetch_all(sql, params)
        return rows[0] if rows else None

    monkeypatch.setattr(dbc, "execute", dbc._sqlite_execute)
    monkeypatch.setattr(dbc, "fetch_all", dbc._sqlite_fetch_all)
    monkeypatch.setattr(dbc, "fetch_one", _fetch_one)
    monkeypatch.setattr(
        "src.modules.llm.registry.get_backend", lambda settings, name=None, model=None: MockLLMBackend()
    )

    async def _nothing(*a, **kw):
        return None

    # No network: the literature steps would ask OpenAlex.
    monkeypatch.setattr("src.api.app._acquire_literature", _nothing)
    monkeypatch.setattr("src.api.app._ingest_literature_corpus", _nothing)
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


def test_a_study_starts_from_the_form_and_stops_at_its_first_review(live_db):
    with TestClient(app) as c:
        r = c.post(
            "/papers",
            data={
                "research_question": "Does X affect Y? We use a panel.",
                "pipeline": "empirical-preregistered",
                "demonstration": "1",
            },
            follow_redirects=False,
        )
        assert r.status_code == 303, r.text
        pid = r.headers["location"].rsplit("/", 1)[1]
        uuid.UUID(pid)
        deadline = time.time() + 60
        while time.time() < deadline:
            status = c.get(f"/api/papers/{pid}").json()["status"]
            if status in {"paused", "failed", "completed"}:
                break
            time.sleep(0.3)
        paper = c.get(f"/api/papers/{pid}").json()
        assert paper["status"] == "paused", paper.get("last_error")
        assert paper["pipeline"] == "empirical-preregistered"
        assert paper["title"] == "Does X affect Y"  # the first sentence, as `e2er run` names it
        manifest = json.loads((live_db / "workspaces" / pid / "manifest.json").read_text())
        assert manifest["purpose"] == "demonstration"

        # The review is offered once the run task has wound down, not the moment
        # the status turns to paused (approving before that is refused).
        deadline = time.time() + 30
        live = ""
        while time.time() < deadline:
            live = c.get(f"/htmx/papers/{pid}/live").text
            if "The study is waiting for you" in live:
                break
            time.sleep(0.2)
        assert "The study is waiting for you" in live
        assert f'href="/papers/{pid}/review"' in live
        # The mock strategist never dispatches data_architect, so the design
        # review (which waits for it) never fires; the draft review is the first stop.
        assert "Draft review" in live and "waiting for you" in live
        assert "Design, data, estimation and draft" in live
        assert "idea_developer" in live  # specialists done

        review = c.get(f"/papers/{pid}/review").text
        assert "Researcher step: review_draft" in review


def test_a_refused_start_is_shown_on_the_form(live_db):
    with TestClient(app) as c:
        r = c.post("/papers", data={"research_question": "Q?", "pipeline": "no-such-template"})
        assert r.status_code == 422
        assert "unknown pipeline" in r.text and "New study" in r.text
        assert "Q?" in r.text, "what was typed is kept"


# ── finish: verify ──────────────────────────────────────────────────────────


def test_the_finish_page_verifies_the_export(live_db, session, monkeypatch):
    from src.core.export.structured import export_paper

    from .test_cli_verify import TABLE_TEX

    pid = str(uuid.uuid4())
    ws = live_db / "workspaces" / pid
    ws.mkdir(parents=True)
    (ws / "manifest.json").write_text(json.dumps({"title": "Verify Me", "paper_id": pid, "governance": "full"}))
    (ws / "paper_draft.tex").write_text(TABLE_TEX)
    (ws / "literature.bib").write_text("@article{smith2021, title={X}, doi={10.1/x}, year={2021}}\n")
    (ws / "estimation_results.json").write_text(json.dumps({"main": {"coefficients": {"treat": {"estimate": 12.5}}}}))
    (ws / "identification_spec.json").write_text(
        json.dumps({"primary": {"estimator": "ols", "outcome": "y", "treatment": "treat"}})
    )
    bundle = export_paper(ws, live_db / "exports", date_str="20260929")

    import asyncio

    from src.db.client import execute

    asyncio.run(
        execute(
            "INSERT INTO papers (id, title, research_question, status, workspace, mode, methodology, pipeline) "
            "VALUES (%(id)s, 'Verify Me', 'Q?', 'completed', %(ws)s, 'single_pass', 'empirical', 'empirical')",
            {"id": pid, "ws": str(ws)},
        )
    )
    c = TestClient(app, base_url=BASE, client=("127.0.0.1", 5))
    page = c.get(f"/papers/{pid}/finish").text
    assert str(bundle) in page and "Publish to e2er.org" in page

    assert c.post(f"/api/papers/{pid}/verify").status_code == 403, "needs the session"
    c.cookies.set("e2er_session_8290", TOKEN)
    d = c.post(f"/api/papers/{pid}/verify").json()
    assert [x["name"] for x in d["checks"]][:6] == ["integrity", "anchor", "numbers", "tables", "spec", "citations"]
    assert d["verified"] is True, d
    assert d["bundle"] == str(bundle)

    live = c.get(f"/htmx/papers/{pid}/live").text
    assert f'href="/papers/{pid}/finish"' in live


# ── the two bugs from the 0.11.0 recording ─────────────────────────────────


def test_review_without_a_terminal_exits_cleanly(monkeypatch, capsys):
    """It crashed with EOFError; now it says which flags or which page to use."""
    import io

    from src import cli_review

    class Resp:
        status_code = 200

        def json(self):
            return {"pending": {"stage": "review_design", "kind": "researcher"}, "files": [], "sendable": []}

    class Http:
        def get(self, url):
            return Resp()

    monkeypatch.setattr(cli_review, "_client", lambda: Http())
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    code = cli_review.review("0e0e0e0e-0000-0000-0000-000000000000")
    err = capsys.readouterr().err
    assert code == 2
    assert "--approve" in err and "/papers/0e0e0e0e-0000-0000-0000-000000000000/review" in err


def test_review_eof_in_a_terminal_is_not_a_traceback(monkeypatch, capsys):
    from src import cli_review

    class Resp:
        status_code = 200

        def json(self):
            return {"pending": {"stage": "review_design", "kind": "researcher"}, "files": [], "sendable": []}

    class Http:
        def get(self, url):
            return Resp()

    def eof(prompt=""):
        raise EOFError

    monkeypatch.setattr(cli_review, "_client", lambda: Http())
    monkeypatch.setattr(cli_review, "_interactive", lambda: True)
    monkeypatch.setattr("builtins.input", eof)
    assert cli_review.review("p") == 2


def test_status_shows_the_actual_template():
    from src.cli_status import _format_status_summary

    out = _format_status_summary(
        {"status": "paused", "mode": "single_pass", "methodology": "empirical", "pipeline": "event-study-finance"}
    )
    assert "Template:   event-study-finance" in out
    assert "single_pass / empirical" not in out


# ── bare `e2er` ─────────────────────────────────────────────────────────────


def test_bare_e2er_serves_and_prints_the_launch_url(monkeypatch, capsys, home):
    import sys

    from src import __main__ as cli

    ran = {}
    monkeypatch.setattr(cli, "_already_serving", lambda h, p: False)
    monkeypatch.setattr("uvicorn.run", lambda *a, **kw: ran.update(kw))
    opened = []
    monkeypatch.setattr(cli, "_open_browser", lambda url, delay=1.2: opened.append(url))
    monkeypatch.setattr(cli, "_interactive", lambda: True)
    monkeypatch.setenv(ls.ENV_TOKEN, "")  # restored after the test; empty means "make one"
    monkeypatch.setattr(sys, "argv", ["e2er", "--port", "8291"])
    with pytest.raises(SystemExit) as e:
        cli.main()
    assert e.value.code == 0
    out = capsys.readouterr().out
    token = os.environ[ls.ENV_TOKEN]
    assert f"http://127.0.0.1:8291/?t={token}" in out
    assert opened == [f"http://127.0.0.1:8291/?t={token}"]
    assert ran["port"] == 8291 and ran["host"] == "127.0.0.1"


def test_no_browser_and_non_interactive_do_not_open(monkeypatch, capsys, home):
    import sys

    from src import __main__ as cli

    monkeypatch.setattr(cli, "_already_serving", lambda h, p: False)
    monkeypatch.setattr("uvicorn.run", lambda *a, **kw: None)
    opened = []
    monkeypatch.setattr(cli, "_open_browser", lambda url, delay=1.2: opened.append(url))
    monkeypatch.setattr(cli, "_interactive", lambda: True)
    monkeypatch.setenv(ls.ENV_TOKEN, "")
    monkeypatch.setattr(sys, "argv", ["e2er", "--no-browser", "--port", "8292"])
    with pytest.raises(SystemExit):
        cli.main()
    monkeypatch.setattr(cli, "_interactive", lambda: False)
    monkeypatch.setattr(sys, "argv", ["e2er", "--port", "8292"])
    with pytest.raises(SystemExit):
        cli.main()
    assert opened == []
    assert "http://127.0.0.1:8292/?t=" in capsys.readouterr().out


def test_a_running_e2er_is_opened_with_its_own_token(monkeypatch, capsys, home):
    from src import __main__ as cli

    ls.write_session_file(8293, "running-token")
    monkeypatch.setattr(cli, "_already_serving", lambda h, p: True)
    monkeypatch.setattr(cli, "_interactive", lambda: True)
    opened = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url))
    assert cli._serve(host="127.0.0.1", port=8293, reload=False, no_browser=False) == 0
    assert opened == ["http://127.0.0.1:8293/?t=running-token"]


def test_the_review_is_offered_only_once_the_run_task_has_stopped():
    """Status turns to paused a moment before the task winds down; approving then got a 409."""
    import asyncio

    from src.api import app as appmod

    class Task:
        def __init__(self, done):
            self._done = done

        def done(self):
            return self._done

    paper = {"id": "p-1", "status": "paused", "workspace": "/nonexistent", "mode": "single_pass"}
    appmod._RUNNING["p-1"] = Task(False)  # type: ignore[assignment]
    try:
        assert appmod._awaiting_review(paper) is None
    finally:
        appmod._RUNNING.pop("p-1", None)
    assert asyncio.iscoroutinefunction(appmod.post_review)
