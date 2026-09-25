"""e2er login / publish --to / --dry-run / status / dossier push against a fake platform."""

from __future__ import annotations

import json
import shutil
import stat
from pathlib import Path

import httpx
import pytest

from src import cli_platform
from src.cli_publish import _rehash, publish
from src.cli_verify import _run_checks
from src.core import platform_client as pc
from src.core.dossier import dossier_id
from src.core.secret_scan import find_local_paths, find_secrets

ROOT = Path(__file__).resolve().parents[1]
SHOWCASE = ROOT / "examples" / "showcase"
URL = "https://platform.test"
ARGS = dict(owner="ada-lab", project="showcase", github="ada-lab", name="Ada Lovelace", commit="abc1234")


@pytest.fixture
def bundle(tmp_path: Path) -> Path:
    dst = tmp_path / "showcase"
    shutil.copytree(SHOWCASE, dst)
    return dst


@pytest.fixture(autouse=True)
def offline(monkeypatch, tmp_path):
    monkeypatch.setattr("src.cli_publish.shutil.which", lambda _: None)  # no tectonic in tests
    monkeypatch.setattr(pc, "_keyring", lambda: None)
    monkeypatch.setenv("E2ER_CREDENTIALS", str(tmp_path / "credentials.json"))
    monkeypatch.delenv("E2ER_TOKEN", raising=False)
    monkeypatch.delenv("E2ER_URL", raising=False)


class FakePlatform:
    """The endpoints the CLI calls, with the answers e2er-site gives."""

    def __init__(self):
        self.requests: list[tuple[str, str, dict]] = []
        self.polls = 0
        self.published: dict | None = None

    def __call__(self, req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content) if req.content else {}
        self.requests.append((req.method, req.url.path, body))
        p = req.url.path
        if p == "/api/auth/device/code":
            return httpx.Response(
                200,
                json={
                    "device_code": "dev-1",
                    "user_code": "ABCD-1234",
                    "verification_uri": "/device",
                    "interval": 5,
                    "expires_in": 1800,
                },
            )
        if p == "/api/auth/device/token":
            self.polls += 1
            if self.polls < 2:
                return httpx.Response(400, json={"error": "authorization_pending"})
            return httpx.Response(200, json={"access_token": "session-token", "token_type": "Bearer"})
        if p == "/api/v1/tokens":
            assert req.headers["authorization"] == "Bearer session-token"
            return httpx.Response(
                201,
                json={
                    "id": "t1",
                    "token": "e2er_" + "A" * 43,
                    "scopes": ["publish"],
                    "expires_at": "2026-12-24T00:00:00Z",
                },
            )
        if p == "/api/v1/me":
            return httpx.Response(
                200, json={"name": "Ada Lovelace", "email": "ada@example.org", "scopes": ["publish"], "handles": []}
            )
        if p == "/api/v1/studies" and req.method == "POST":
            self.published = body
            return httpx.Response(
                201,
                json={
                    "id": "ada-lab/showcase",
                    "owner_project": "ada-lab/showcase",
                    "version": 1,
                    "dossier_url": f"{URL}/d/x",
                    "study_url": f"{URL}/ada-lab/showcase",
                    "existing": False,
                },
            )
        if p == "/api/v1/studies/ada-lab/showcase":
            cid = self.published["manifest"]["content_id"] if self.published else None
            return httpx.Response(
                200,
                json={
                    "id": "ada-lab/showcase",
                    "title": "T",
                    "url": f"{URL}/ada-lab/showcase",
                    "latest": {"number": 1, "content_id": cid, "dossier_url": f"{URL}/d/x"},
                    "versions": [{}],
                    "checks": [{"check_id": "integrity", "status": "PASS", "run_by": "author"}],
                    "pending_confirmations": [],
                },
            )
        if p == "/api/v1/dossiers":
            return httpx.Response(201, json={"id": body["id"], "url": f"{URL}/d/{body['id'][7:23]}", "stored": True})
        if p == "/api/v1/tokens/current":
            return httpx.Response(200, json={"revoked": "t1"})
        return httpx.Response(404, json={"error": "no such endpoint"})


@pytest.fixture
def platform(monkeypatch) -> FakePlatform:
    fake = FakePlatform()
    monkeypatch.setattr(
        pc, "client_factory", lambda url: httpx.Client(base_url=url, transport=httpx.MockTransport(fake))
    )
    monkeypatch.setattr(pc.time, "sleep", lambda _s: None)
    return fake


def snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def test_scanner_finds_keys_tokens_and_env_lines():
    assert find_secrets({"a": "ok", "b": ["x sk-ant-api03-abcdefghijk y"]}) == [("$.b[0]", "Anthropic key")]
    assert find_secrets("OPENROUTER=sk-or-v1-0123456789abcdef")[0][1] == "OpenRouter key"
    assert find_secrets("WRDS_PASSWORD=Zq8#kLm2vX9pQr4TtY7uWbN3")[0][1] == "WRDS_PASSWORD= value"
    assert find_secrets("A readable sentence about DOIs and 20260911 dates.") == []
    assert find_local_paths({"p": "/Users/someone/data.csv"}) == ["$.p"]


def test_dry_run_changes_nothing_and_prints_the_request(bundle: Path, capsys):
    before = snapshot(bundle)
    code = publish(str(bundle), dry_run=True, **ARGS)
    out = capsys.readouterr()
    assert code == 0, out.out + out.err
    assert snapshot(bundle) == before  # not one byte changed, nothing written
    body = json.loads(out.out)
    assert body["dossier"]["id"] == dossier_id(body["dossier"]["doc"])
    assert "doc" not in body["manifest"]["dossier"] and body["manifest"]["id"] == "ada-lab/showcase"
    assert not find_local_paths(body) and not find_secrets(body)
    assert "nothing was written or sent" in out.err


def test_a_planted_key_blocks_the_publish(bundle: Path, platform: FakePlatform, monkeypatch, capsys):
    monkeypatch.setenv("E2ER_TOKEN", "e2er_" + "B" * 43)
    readme = bundle / "README.md"
    readme.write_text(
        "**Research question:** Did ETFs matter? sk-ant-api03-abcdefghijklmnopqrst\n\n"
        + readme.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    _rehash(bundle, ["README.md"])
    before = snapshot(bundle)
    assert publish(str(bundle), to_url=URL, **ARGS) == 1
    assert "Anthropic key" in capsys.readouterr().out
    assert platform.requests == [] and snapshot(bundle) == before


def test_login_stores_the_token_privately_and_whoami_uses_it(platform: FakePlatform, tmp_path: Path, capsys):
    assert cli_platform.login(URL, open_browser=False) == 0
    out = capsys.readouterr().out
    assert f"{URL}/device" in out and "ABCD-1234" in out
    cred = tmp_path / "credentials.json"
    assert json.loads(cred.read_text())[URL].startswith("e2er_")
    assert stat.S_IMODE(cred.stat().st_mode) == 0o600
    assert cli_platform.whoami(URL) == 0 and "ada@example.org" in capsys.readouterr().out
    assert cli_platform.logout(URL) == 0 and URL not in json.loads(cred.read_text())


def test_publish_to_the_platform_links_the_folder_and_it_still_verifies(
    bundle: Path, platform: FakePlatform, monkeypatch, capsys
):
    monkeypatch.setenv("E2ER_TOKEN", "e2er_" + "C" * 43)
    assert publish(str(bundle), to_url=URL, **ARGS) == 0, capsys.readouterr().out
    sent = platform.published
    assert sent["manifest"]["contributors"][0]["github"] == "ada-lab"
    assert sent["dossier"]["id"] == dossier_id(sent["dossier"]["doc"])
    link = json.loads((bundle / ".e2er" / "link.json").read_text())
    assert link["owner_project"] == "ada-lab/showcase" and link["platform_url"] == URL
    assert all(c.status == "PASS" for c in _run_checks(bundle, online=False))  # .e2er/ is not evidence
    assert cli_platform.status(str(bundle)) == 0
    assert "this folder is the published version" in capsys.readouterr().out


def test_dossier_push_registers_the_dossier_alone(bundle: Path, platform: FakePlatform, monkeypatch, capsys):
    assert publish(str(bundle), **{**ARGS, "out": str(bundle.parent / "entry")}) == 0
    monkeypatch.setenv("E2ER_TOKEN", "e2er_" + "D" * 43)
    assert cli_platform.dossier_push(str(bundle), URL) == 0
    method, path, body = platform.requests[-1]
    assert (method, path) == ("POST", "/api/v1/dossiers") and body["id"] == dossier_id(body["doc"])
    assert "Dossier registered" in capsys.readouterr().out
