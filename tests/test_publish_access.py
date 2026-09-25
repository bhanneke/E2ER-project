"""e2er publish: data and code public or private, and Zenodo DOIs in one step."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import httpx
import pytest

from src.cli_publish import publish, request_body
from src.core import zenodo as zen
from src.core.dossier import SCHEMA_AVAILABILITY, build_dossier, dossier_id

ROOT = Path(__file__).resolve().parents[1]
SHOWCASE = ROOT / "examples" / "showcase"
BASE = dict(owner="bhanneke", project="demo", github="bhanneke", orcid="0009-0000-7466-9581", name=None)
REPO = dict(repo="https://github.com/bhanneke/E2ER-project", commit="abc1234", path="examples/showcase")


@pytest.fixture
def bundle(tmp_path: Path) -> Path:
    dst = tmp_path / "showcase"
    shutil.copytree(SHOWCASE, dst, ignore=shutil.ignore_patterns(".e2er", "e2er.json"))
    return dst


def _manifest(bundle: Path) -> dict:
    return json.loads((bundle / "e2er.json").read_text())


def test_data_and_code_are_private_unless_stated(bundle: Path, tmp_path: Path):
    assert publish(str(bundle), **BASE, **REPO, out=str(tmp_path / "e")) == 0
    m = _manifest(bundle)
    assert m["availability"] == {"data": {"access": "private"}, "code": {"access": "private"}}
    # A private study's dossier omits availability, so its address is unchanged.
    doc = m["dossier"]["doc"]
    assert "availability" not in doc
    assert (
        dossier_id(build_dossier({k: v for k, v in m.items() if k != "availability"}, bundle=bundle))
        == m["dossier"]["id"]
    )


def test_public_code_points_at_the_repository_commit(bundle: Path, tmp_path: Path):
    assert publish(str(bundle), **BASE, **REPO, code="public", out=str(tmp_path / "e")) == 0
    m = _manifest(bundle)
    assert m["availability"]["code"] == {
        "access": "public",
        "url": "https://github.com/bhanneke/E2ER-project/tree/abc1234/examples/showcase",
    }
    assert m["dossier"]["doc"]["schema"] == SCHEMA_AVAILABILITY
    assert m["dossier"]["doc"]["availability"] == m["availability"]


def test_private_material_carries_no_address_and_no_contents(bundle: Path, tmp_path: Path, capsys):
    assert (
        publish(
            str(bundle), **BASE, **REPO, data="private", data_url="https://example.org/secret", out=str(tmp_path / "e")
        )
        == 0
    )
    assert "ignored" in capsys.readouterr().out
    body = request_body(_manifest(bundle) | {"dossier": _manifest(bundle)["dossier"]}, bundle)
    text = json.dumps(body)
    assert body["manifest"]["availability"]["data"] == {"access": "private"}
    assert "example.org/secret" not in text
    summary = (bundle / "data" / "data_summary.md").read_text()
    assert summary[:200] not in text  # fingerprints only, never file contents


class FakeZenodo:
    """Zenodo's deposit API, in memory."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self.meta: dict[int, dict] = {}
        self.next_id = 100

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.calls.append((req.method, req.url.host, req.url.path))
        assert req.headers["authorization"] == "Bearer tok"
        path = req.url.path
        if req.method == "POST" and path == "/api/deposit/depositions":
            self.next_id += 1
            i = self.next_id
            return httpx.Response(
                201,
                json={
                    "id": i,
                    "links": {"bucket": f"https://{req.url.host}/api/files/b{i}"},
                    "metadata": {"prereserve_doi": {"doi": f"10.5072/zenodo.{i}"}},
                },
            )
        if req.method == "PUT" and path.startswith("/api/deposit/depositions/"):
            self.meta[int(path.rsplit("/", 1)[1])] = json.loads(req.content)["metadata"]
            return httpx.Response(200, json={})
        if path.endswith("/actions/publish"):
            i = int(path.split("/")[4])
            return httpx.Response(
                202,
                json={"doi": f"10.5072/zenodo.{i}", "links": {"record_html": f"https://{req.url.host}/records/{i}"}},
            )
        return httpx.Response(200, json={})


@pytest.fixture
def fake(monkeypatch) -> FakeZenodo:
    f = FakeZenodo()
    monkeypatch.setattr(
        zen, "client_factory", lambda base: httpx.Client(base_url=base, transport=httpx.MockTransport(f))
    )
    monkeypatch.setenv("ZENODO_TOKEN", "tok")
    monkeypatch.setenv("ZENODO_SANDBOX_TOKEN", "tok")
    return f


def test_zenodo_deposits_public_data_and_code_and_records_the_dois(bundle: Path, tmp_path: Path, fake: FakeZenodo):
    code = publish(str(bundle), **BASE, **REPO, data="public", code="public", zenodo=True, out=str(tmp_path / "e"))
    assert code == 0
    m = _manifest(bundle)
    av = m["availability"]
    assert av["data"]["doi"] == "10.5072/zenodo.101" and av["code"]["doi"] == "10.5072/zenodo.102"
    assert m["dossier"]["doc"]["availability"]["data"]["doi"] == "10.5072/zenodo.101"  # the DOI is in the dossier
    uploads = [p for meth, _, p in fake.calls if meth == "PUT" and p.startswith("/api/files/")]
    assert "/api/files/b101/data_dictionary.json" in uploads and "/api/files/b102/demo-code.zip" in uploads
    data_meta = fake.meta[101]
    assert data_meta["upload_type"] == "dataset" and m["dossier"]["url"] in data_meta["description"]
    assert data_meta["creators"][0]["orcid"] == "0009-0000-7466-9581"
    assert {"identifier": m["dossier"]["url"], "relation": "isSupplementTo", "resource_type": "other"} in data_meta[
        "related_identifiers"
    ]
    assert sum(1 for meth, _, p in fake.calls if p.endswith("/actions/publish")) == 2


def test_zenodo_sandbox(bundle: Path, tmp_path: Path, fake: FakeZenodo):
    code = publish(
        str(bundle), **BASE, **REPO, code="public", zenodo=True, zenodo_sandbox=True, out=str(tmp_path / "e")
    )
    assert code == 0
    assert {host for _, host, _ in fake.calls} == {"sandbox.zenodo.org"}


def test_zenodo_without_a_token_writes_nothing(bundle: Path, tmp_path: Path, monkeypatch, capsys):
    monkeypatch.delenv("ZENODO_TOKEN", raising=False)
    monkeypatch.setattr(zen, "load_token", lambda sandbox=False: None)
    assert publish(str(bundle), **BASE, **REPO, code="public", zenodo=True, out=str(tmp_path / "e")) == 1
    assert "ZENODO_TOKEN" in capsys.readouterr().out
    assert not (bundle / "e2er.json").exists()


def test_zenodo_refuses_private_material(bundle: Path, tmp_path: Path, fake: FakeZenodo, capsys):
    assert publish(str(bundle), **BASE, **REPO, zenodo=True, out=str(tmp_path / "e")) == 1
    assert "nothing to deposit" in capsys.readouterr().out
    assert fake.calls == []
    # Mixed: only the public item is deposited; the private one is named and left alone.
    assert publish(str(bundle), **BASE, **REPO, code="public", zenodo=True, out=str(tmp_path / "e")) == 0
    out = capsys.readouterr().out
    assert "leaves the data alone: it is private" in out
    assert not any("data_dictionary" in p for _, _, p in fake.calls)


def test_dry_run_prints_the_deposit_plan_and_deposits_nothing(bundle: Path, fake: FakeZenodo, capsys):
    before = {p: p.read_bytes() for p in bundle.rglob("*") if p.is_file()}
    code = publish(str(bundle), **BASE, **REPO, data="public", code="public", zenodo=True, dry_run=True)
    assert code == 0
    err = capsys.readouterr().err
    assert "zenodo data: would deposit 2 file(s)" in err and "demo-code.zip" in err
    assert fake.calls == []
    assert {p: p.read_bytes() for p in bundle.rglob("*") if p.is_file()} == before


def test_in_a_terminal_the_researcher_is_asked(bundle: Path, tmp_path: Path, monkeypatch):
    answers = iter(["public", ""])  # data public; code: Enter keeps private
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))
    assert publish(str(bundle), **BASE, **REPO, out=str(tmp_path / "e")) == 0
    av = _manifest(bundle)["availability"]
    assert av["data"]["access"] == "public" and av["code"]["access"] == "private"
