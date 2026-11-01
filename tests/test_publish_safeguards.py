"""Publishing safeguards: publish asks first, nothing publishes from a test run, tokens for one study.

The real platform client, keychain lookup and Zenodo client are taken here at import, before conftest's
autouse fixture replaces them for every test, so the guards inside them are what these tests exercise.
Any request a guard would let through goes to a dead proxy (127.0.0.1:9) as well, so nothing can leave
the machine even if a guard failed.
"""

from __future__ import annotations

import http.server
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import httpx
import pytest

from src import cli_platform
from src.cli_publish import confirm_question, publish
from src.core import github_files as gf
from src.core import platform_client as pc
from src.core import test_guard
from src.core import zenodo as zen
from tests.run_db import make_run_db, paper_id_of
from tests.test_platform_cli import ARGS, SHOWCASE, URL, FakePlatform, snapshot

REAL_CLIENT = pc.client_factory
REAL_KEYRING = pc._keyring
REAL_ZENODO_CLIENT = zen.client_factory
ROOT = Path(__file__).resolve().parents[1]
DEAD_PROXY = "http://127.0.0.1:9"


@pytest.fixture(autouse=True)
def nowhere(monkeypatch, tmp_path):
    """No tectonic, no credentials, and a dead proxy for anything that would still try the network."""
    monkeypatch.setattr("src.cli_publish.shutil.which", lambda _: None)
    monkeypatch.setenv("E2ER_CREDENTIALS", str(tmp_path / "credentials.json"))
    monkeypatch.delenv("E2ER_URL", raising=False)
    for var in ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "https_proxy", "http_proxy", "all_proxy"):
        monkeypatch.setenv(var, DEAD_PROXY)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")


@pytest.fixture
def bundle(tmp_path: Path) -> Path:
    import shutil

    dst = tmp_path / "showcase"
    shutil.copytree(SHOWCASE, dst)
    make_run_db(tmp_path, paper_id_of(dst))
    return dst


@pytest.fixture
def platform(monkeypatch) -> FakePlatform:
    fake = FakePlatform()
    monkeypatch.setattr(
        pc, "client_factory", lambda url: httpx.Client(base_url=url, transport=httpx.MockTransport(fake))
    )
    monkeypatch.setattr(pc.time, "sleep", lambda _s: None)
    monkeypatch.setattr(pc, "load_token", lambda base: "e2er_" + "A" * 43)
    return fake


def _not_a_test_run(monkeypatch) -> None:
    for var in ("PYTEST_CURRENT_TEST", "E2ER_TEST", "CI"):
        monkeypatch.delenv(var, raising=False)


# ── 4. publish asks first ────────────────────────────────────────────────────


def test_the_question_names_the_title_the_platform_the_handle_and_the_github_folder():
    t = gf.Target("ada", "demos", "who")
    assert (
        confirm_question("Road deaths", platform="https://e2er.org", handle="ada", github=t)
        == "Publish 'Road deaths' to https://e2er.org as ada? Files to GitHub ada/demos/who."
    )
    assert confirm_question("T", platform="https://e2er.org", handle="ada") == "Publish 'T' to https://e2er.org as ada?"
    assert "Zenodo (zenodo.org)" in confirm_question("T", platform=None, handle="ada", zenodo="zenodo.org")


def test_without_a_terminal_and_without_yes_nothing_is_sent(bundle: Path, platform: FakePlatform, capsys):
    before = snapshot(bundle)
    assert publish(str(bundle), to_url=URL, **ARGS) == 1
    out = capsys.readouterr().out
    assert "only after you confirm it" in out and "--yes" in out and "Nothing was sent." in out
    assert platform.requests == [] and platform.published is None
    assert snapshot(bundle) == before


def test_answering_no_sends_nothing_and_changes_nothing(bundle: Path, platform: FakePlatform, monkeypatch, capsys):
    asked: list[str] = []
    monkeypatch.setattr("builtins.input", lambda q: asked.append(q) or "n")
    before = snapshot(bundle)
    assert publish(str(bundle), to_url=URL, interactive=True, data="private", code="private", **ARGS) == 1
    out = capsys.readouterr().out
    assert len(asked) == 1
    assert asked[0].startswith("Publish '") and asked[0].endswith(f"' to {URL} as ada-lab? [y/N]: ")
    assert "What goes where:" in out and f"{URL} (ada-lab/showcase)" in out
    assert "Not published: nothing was sent or pushed." in out
    assert platform.published is None
    assert not [r for r in platform.requests if r[0] != "GET"]
    assert snapshot(bundle) == before


@pytest.mark.parametrize("answer", ["y", "yes", " YES "])
def test_only_y_or_yes_publishes(bundle: Path, platform: FakePlatform, monkeypatch, answer):
    monkeypatch.setattr("builtins.input", lambda q: answer)
    assert publish(str(bundle), to_url=URL, interactive=True, data="private", code="private", **ARGS) == 0
    assert platform.published is not None


@pytest.mark.parametrize("answer", ["", "no", "ja", "Y es"])
def test_anything_else_does_not(bundle: Path, platform: FakePlatform, monkeypatch, answer):
    monkeypatch.setattr("builtins.input", lambda q: answer)
    assert publish(str(bundle), to_url=URL, interactive=True, data="private", code="private", **ARGS) == 1
    assert platform.published is None


def test_yes_publishes_without_a_terminal_and_says_so(bundle: Path, platform: FakePlatform, capsys):
    assert publish(str(bundle), to_url=URL, yes=True, **ARGS) == 0
    out = capsys.readouterr().out
    assert f"to {URL} as ada-lab? yes (--yes)" in out
    assert platform.published is not None


def test_a_dry_run_never_asks_and_never_sends(bundle: Path, platform: FakePlatform, monkeypatch, capsys):
    def no_question(q):
        raise AssertionError(f"a dry run asked: {q}")

    monkeypatch.setattr("builtins.input", no_question)
    before = snapshot(bundle)
    assert publish(str(bundle), to_url=URL, dry_run=True, interactive=True, data="private", code="private", **ARGS) == 0
    assert publish(str(bundle), to_url=URL, dry_run=True, **ARGS) == 0  # no terminal, no --yes: still a dry run
    assert platform.requests == [] and snapshot(bundle) == before
    assert "dry run: nothing was written or sent" in capsys.readouterr().err


def _run_main(monkeypatch, argv: list[str]) -> int:
    from src.__main__ import main

    monkeypatch.setattr(sys, "argv", ["e2er", *argv])
    with pytest.raises(SystemExit) as e:
        main()
    return int(e.value.code or 0)


def test_the_command_line_passes_yes(monkeypatch):
    seen: list[bool] = []
    monkeypatch.setattr("src.cli_publish.publish", lambda bundle, **kw: seen.append(kw["yes"]) or 0)
    base = ["publish", "b", "--owner", "a", "--project", "p", "--to", URL]
    for extra, want in (([], False), (["--yes"], True), (["-y"], True)):
        assert _run_main(monkeypatch, base + extra) == 0
        assert seen.pop() is want


def test_a_zenodo_deposit_without_a_terminal_needs_yes(bundle: Path, monkeypatch, capsys):
    def no_zenodo(base):
        raise AssertionError("Zenodo was contacted")

    monkeypatch.setattr(zen, "client_factory", no_zenodo)
    monkeypatch.setenv("ZENODO_TOKEN", "zen-test")
    assert publish(str(bundle), zenodo=True, data="public", code="public", **ARGS) == 1
    assert "only after you confirm it" in capsys.readouterr().out


# ── 5. no publishing from a test run ─────────────────────────────────────────


def test_what_counts_as_a_test_run(monkeypatch):
    assert test_guard.under_test()  # pytest sets PYTEST_CURRENT_TEST
    _not_a_test_run(monkeypatch)
    monkeypatch.setattr(test_guard, "_test_command", lambda: False)
    assert not test_guard.under_test()
    monkeypatch.setenv("CI", "true")
    assert not test_guard.under_test()  # CI alone is not a test run
    monkeypatch.setattr(test_guard, "_test_command", lambda: True)
    assert test_guard.why_test_run() == "CI=true and a test command is running"
    monkeypatch.delenv("CI")
    monkeypatch.setenv("E2ER_TEST", "1")
    assert test_guard.why_test_run() == "E2ER_TEST=1"


def test_a_test_run_reaches_only_local_servers_and_the_named_test_server(monkeypatch):
    for url in ("http://localhost:8799", "http://127.0.0.1:4321", "http://[::1]:80", "http://site.localhost"):
        assert test_guard.target_allowed(url), url
    for url in ("https://e2er.org", "https://preview.e2er.org", "https://zenodo.org", "https://platform.test"):
        assert not test_guard.target_allowed(url), url
    monkeypatch.setenv("E2ER_TEST_SERVER", "http://platform.test:8080/")
    assert test_guard.target_allowed("http://platform.test:8080")
    assert not test_guard.target_allowed("http://platform.test:8081")
    assert not test_guard.target_allowed("https://e2er.org")
    for prod in ("https://e2er.org", "https://preview.e2er.org"):
        monkeypatch.setenv("E2ER_TEST_SERVER", prod)
        with pytest.raises(test_guard.RefusedInTestError, match="never for e2er.org"):
            test_guard.check_target(prod)


def test_the_real_client_refuses_e2er_org_in_a_test_run():
    for url in ("https://e2er.org", "https://preview.e2er.org"):
        with pytest.raises(pc.PlatformError, match="running under a test runner .PYTEST_CURRENT_TEST is set."):
            REAL_CLIENT(url)


def test_the_real_client_reaches_a_local_server(monkeypatch):
    seen: list[str] = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - the http.server name
            seen.append(self.path)
            body = json.dumps({"name": "Local", "email": "l@example.org", "handles": []}).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        monkeypatch.setattr(pc, "client_factory", REAL_CLIENT)
        code, body = pc.request(f"http://127.0.0.1:{server.server_port}", "GET", "/api/v1/me", token="e2er_local")
    finally:
        server.shutdown()
    assert code == 200 and body["name"] == "Local" and seen == ["/api/v1/me"]


def test_a_test_run_never_touches_the_keychain(monkeypatch):
    calls: list[str] = []

    class Keychain:
        def get_password(self, *a):
            calls.append("get")
            return "e2er_from_the_keychain"

        def set_password(self, *a):
            calls.append("set")

        def delete_password(self, *a):
            calls.append("delete")

    monkeypatch.setitem(sys.modules, "keyring", Keychain())
    monkeypatch.setattr(pc, "_keyring", REAL_KEYRING)
    assert REAL_KEYRING() is None
    assert pc.load_token("https://e2er.org") is None
    pc.save_token("https://e2er.org", "e2er_new")  # into the test's own E2ER_CREDENTIALS file
    pc.forget_token("https://e2er.org")
    assert calls == []
    _not_a_test_run(monkeypatch)
    monkeypatch.setattr(test_guard, "_test_command", lambda: False)
    assert REAL_KEYRING() is not None  # outside a test run the keychain is used as before


def test_a_test_run_never_reads_or_writes_the_saved_credentials(monkeypatch, tmp_path):
    home = tmp_path / "home"
    saved = home / ".e2er" / "credentials.json"
    saved.parent.mkdir(parents=True)
    saved.write_text(json.dumps({"https://e2er.org": "e2er_saved"}), encoding="utf-8", newline="\n")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("E2ER_CREDENTIALS")
    assert pc.credentials_path() is None
    assert pc.load_token("https://e2er.org") is None
    with pytest.raises(pc.PlatformError, match="keeps no login"):
        pc.save_token("https://e2er.org", "e2er_other")
    pc.forget_token("https://e2er.org")
    assert json.loads(saved.read_text(encoding="utf-8")) == {"https://e2er.org": "e2er_saved"}
    monkeypatch.setenv("E2ER_TOKEN", "e2er_from_the_test")
    assert pc.load_token("https://e2er.org") == "e2er_from_the_test"  # what the test sets itself


def test_zenodo_reads_no_saved_token_and_is_not_reached_in_a_test_run(monkeypatch):
    monkeypatch.setitem(sys.modules, "keyring", type("K", (), {"get_password": lambda *a: "zen-keychain"})())
    assert zen.load_token() is None
    monkeypatch.setenv("ZENODO_TOKEN", "zen-env")
    assert zen.load_token() == "zen-env"
    with pytest.raises(zen.ZenodoError, match="test runner"):
        REAL_ZENODO_CLIENT("https://zenodo.org/api")


def test_a_test_run_does_not_use_gh(monkeypatch):
    monkeypatch.delenv("E2ER_TEST_GITHUB", raising=False)
    monkeypatch.setattr(gf.subprocess, "run", lambda *a, **k: pytest.fail(f"ran {a}"))
    for cmd in (["gh", "api", "user"], ["git", "push", "origin", "HEAD"]):
        with pytest.raises(gf.GitHubError, match="does not use gh or push to GitHub"):
            gf._run(cmd)


def test_publish_with_a_token_in_a_test_run_sends_nothing_to_e2er_org(bundle: Path, monkeypatch, capsys):
    """The incident of 2026-10-20, with the guard instead of conftest's fake: a token, e2er.org, --yes."""
    monkeypatch.setattr(pc, "client_factory", REAL_CLIENT)
    monkeypatch.setenv("E2ER_TOKEN", "e2er_" + "T" * 43)  # not a real token; the dead proxy catches a slip
    assert publish(str(bundle), to_url="https://e2er.org", yes=True, **ARGS) == 1
    out = capsys.readouterr().out
    assert "could not reach https://e2er.org" in out and "running under a test runner" in out
    assert "Nothing was sent." in out


def test_a_command_started_by_a_test_inherits_the_guard(tmp_path):
    """`e2er whoami` run by a test: PYTEST_CURRENT_TEST reaches it, so it neither reads a login nor asks e2er.org."""
    env = {
        **os.environ,
        "HOME": str(tmp_path),
        "USERPROFILE": str(tmp_path),
        "E2ER_TOKEN": "e2er_" + "S" * 43,
        "HTTPS_PROXY": DEAD_PROXY,
        "PYTHONPATH": str(ROOT),
    }
    env.pop("E2ER_CREDENTIALS", None)
    assert env.get("PYTEST_CURRENT_TEST")
    r = subprocess.run(
        [sys.executable, "-m", "src", "whoami", "--url", "https://e2er.org"],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        cwd=ROOT,
        timeout=120,
    )
    assert r.returncode != 0
    assert "running under a test runner (PYTEST_CURRENT_TEST is set)" in r.stdout + r.stderr


# ── 6. tokens for one study ──────────────────────────────────────────────────


class StudyTokenPlatform(FakePlatform):
    """The platform's answer to a study token request (e2er-site: POST /api/v1/tokens with study)."""

    def __init__(self, supports: bool = True):
        super().__init__()
        self.supports = supports

    def __call__(self, req: httpx.Request) -> httpx.Response:
        if req.url.path == "/api/v1/tokens" and req.method == "POST":
            body = json.loads(req.content)
            self.requests.append((req.method, req.url.path, body))
            made = {
                "id": "t2",
                "token": "e2er_" + "B" * 43,
                "scopes": ["publish"],
                "expires_at": "2027-01-18T00:00:00Z",
            }
            if self.supports:
                made["study"] = body.get("study")
            return httpx.Response(201, json=made)
        if req.url.path == "/api/v1/tokens/current" and req.method == "DELETE":
            self.requests.append((req.method, req.url.path, {"auth": req.headers.get("authorization")}))
            return httpx.Response(200, json={"revoked": "t2"})
        return super().__call__(req)


@pytest.fixture
def study_platform(monkeypatch) -> StudyTokenPlatform:
    fake = StudyTokenPlatform()
    monkeypatch.setattr(
        pc, "client_factory", lambda url: httpx.Client(base_url=url, transport=httpx.MockTransport(fake))
    )
    monkeypatch.setattr(pc.time, "sleep", lambda _s: None)
    return fake


def test_the_scope_names_one_study():
    assert pc.parse_study_scope("study:Ada/FX-carry") == "ada/fx-carry"
    assert pc.parse_study_scope("ada/fx", scope=False) == "ada/fx"
    for bad in ("ada/fx", "study:ada", "study:/fx", "publish", "study:ada/fx/x"):
        with pytest.raises(ValueError):
            pc.parse_study_scope(bad)


def test_login_with_a_study_scope_hands_over_a_token_for_that_study_and_keeps_the_personal_login(
    study_platform: StudyTokenPlatform, monkeypatch, tmp_path, capsys
):
    pc.save_token(URL, "e2er_personal")  # the personal login, in the test's credentials file
    assert cli_platform.login(URL, open_browser=False, scope="study:ada-lab/showcase") == 0
    out, err = capsys.readouterr()
    assert out == "e2er_" + "B" * 43 + "\n"  # only the token on standard output, for `| gh secret set`
    assert "can publish new versions of that study only" in err and "ada-lab/showcase" in err
    posted = [b for m, p, b in study_platform.requests if p == "/api/v1/tokens"]
    assert posted == [{"name": "e2er token for ada-lab/showcase", "study": "ada-lab/showcase"}]
    assert pc.load_token(URL) == "e2er_personal"


def test_a_platform_without_study_tokens_gets_its_token_ended(monkeypatch, capsys):
    fake = StudyTokenPlatform(supports=False)
    monkeypatch.setattr(
        pc, "client_factory", lambda url: httpx.Client(base_url=url, transport=httpx.MockTransport(fake))
    )
    monkeypatch.setattr(pc.time, "sleep", lambda _s: None)
    assert cli_platform.login(URL, open_browser=False, scope="study:ada-lab/showcase") == 1
    out, err = capsys.readouterr()
    assert out == "" and "does not make tokens limited to one study" in err
    assert ("DELETE", "/api/v1/tokens/current", {"auth": "Bearer e2er_" + "B" * 43}) in fake.requests


def test_token_create_uses_the_personal_login(study_platform: StudyTokenPlatform, capsys):
    assert cli_platform.token_create("ada-lab/showcase", url=URL) == 1  # not signed in
    assert "not signed in" in capsys.readouterr().err
    pc.save_token(URL, "e2er_personal")
    assert cli_platform.token_create("ada-lab/showcase", url=URL, name="CI of fx") == 0
    out, err = capsys.readouterr()
    assert out.strip() == "e2er_" + "B" * 43
    assert [b for m, p, b in study_platform.requests if p == "/api/v1/tokens"] == [
        {"name": "CI of fx", "study": "ada-lab/showcase"}
    ]
    assert pc.load_token(URL) == "e2er_personal"


def test_the_command_line_has_scope_and_token_create(monkeypatch):
    seen: list[tuple] = []
    monkeypatch.setattr(cli_platform, "login", lambda url, **kw: seen.append(("login", url, kw)) or 0)
    monkeypatch.setattr(cli_platform, "token_create", lambda study, **kw: seen.append(("token", study, kw)) or 0)
    assert _run_main(monkeypatch, ["login", "--scope", "study:a/b", "--no-browser"]) == 0
    assert _run_main(monkeypatch, ["token", "create", "--study", "a/b", "--url", URL]) == 0
    assert seen == [
        ("login", None, {"open_browser": False, "scope": "study:a/b"}),
        ("token", "a/b", {"url": URL, "name": None}),
    ]


def test_whoami_says_when_the_token_is_for_one_study(monkeypatch, capsys):
    def fake(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"name": "CI", "email": "a@example.org", "handles": ["ada-lab"], "study": "ada-lab/showcase"}
        )

    monkeypatch.setattr(
        pc, "client_factory", lambda url: httpx.Client(base_url=url, transport=httpx.MockTransport(fake))
    )
    monkeypatch.setenv("E2ER_TOKEN", "e2er_ci")
    assert cli_platform.whoami(URL) == 0
    assert "This token can only publish new versions of ada-lab/showcase." in capsys.readouterr().out


def test_logout_with_a_ci_token_ends_that_token_and_keeps_the_saved_login(
    study_platform: StudyTokenPlatform, monkeypatch, capsys
):
    pc.save_token(URL, "e2er_personal")
    monkeypatch.setenv("E2ER_TOKEN", "e2er_" + "B" * 43)
    assert cli_platform.logout(URL) == 0
    assert "Ended the token in E2ER_TOKEN" in capsys.readouterr().out
    assert ("DELETE", "/api/v1/tokens/current", {"auth": "Bearer e2er_" + "B" * 43}) in study_platform.requests
    monkeypatch.delenv("E2ER_TOKEN")
    assert pc.load_token(URL) == "e2er_personal"
