"""e2er publish --zenodo against a fake of Zenodo's deposit API: the calls, and a new version of a study.

The fake answers as Zenodo's REST API documents it (https://developers.zenodo.org/): a deposition
has ``id``, ``links.bucket`` and ``metadata.prereserve_doi.doi``; files go to ``PUT <bucket>/<name>``;
``POST .../actions/newversion`` answers with the published deposition, whose ``links.latest_draft``
is the new draft, and the draft starts with the files of the version before.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import httpx
import pytest

from src.cli_publish import ZENODO_RECORD, publish
from src.core import zenodo as zen
from tests.run_db import make_run_db, paper_id_of
from tests.test_publish_access import BASE, REPO, SHOWCASE

PUBLIC = dict(data="public", code="public", zenodo=True, yes=True)


class Zenodo:
    """Zenodo's deposit API, in memory: depositions, buckets, versions."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.deps: dict[int, dict] = {}
        self.next_id = 500

    def _new(self, host: str, files: dict[str, bytes] | None = None, concept: int | None = None) -> dict:
        self.next_id += 1
        i = self.next_id
        dep = {
            "id": i,
            "state": "unsubmitted",
            "concept": concept or i,
            "links": {"bucket": f"https://{host}/api/files/bucket-{i}"},
            "metadata": {"prereserve_doi": {"doi": f"10.5072/zenodo.{i}", "recid": i}},
            "files": dict(files or {}),
        }
        self.deps[i] = dep
        return dep

    def _view(self, dep: dict) -> dict:
        return {k: v for k, v in dep.items() if k != "files"}

    def __call__(self, req: httpx.Request) -> httpx.Response:
        path, host = req.url.path, req.url.host
        self.calls.append((req.method, path))
        assert req.headers["authorization"] == "Bearer tok"
        parts = path.strip("/").split("/")
        if req.method == "POST" and path == "/api/deposit/depositions":
            assert json.loads(req.content or b"{}") in ({}, {"metadata": {"prereserve_doi": True}})
            return httpx.Response(201, json=self._view(self._new(host)))
        if parts[:2] == ["api", "files"]:  # PUT <bucket>/<name>
            i = int(parts[2].removeprefix("bucket-"))
            assert self.deps[i]["state"] == "unsubmitted", "upload to a published deposit"
            self.deps[i]["files"][parts[3]] = req.content
            return httpx.Response(201, json={"key": parts[3]})
        if parts[:3] == ["api", "deposit", "depositions"]:
            i = int(parts[3])
            dep = self.deps[i]
            rest = parts[4:]
            if req.method == "GET" and not rest:
                return httpx.Response(200, json=self._view(dep))
            if req.method == "PUT" and not rest:
                assert dep["state"] == "unsubmitted"
                dep["metadata"] = {
                    **json.loads(req.content)["metadata"],
                    "prereserve_doi": dep["metadata"]["prereserve_doi"],
                }
                return httpx.Response(200, json=self._view(dep))
            if rest == ["files"] and req.method == "GET":
                return httpx.Response(
                    200,
                    json=[
                        {
                            "id": f"f-{i}-{n}",
                            "filename": n,
                            "checksum": hashlib.md5(b).hexdigest(),
                            "links": {"self": f"https://{host}/api/deposit/depositions/{i}/files/f-{i}-{n}"},
                        }
                        for n, b in dep["files"].items()
                    ],
                )
            if rest[:1] == ["files"] and req.method == "DELETE":
                name = rest[1].removeprefix(f"f-{i}-")
                assert dep["state"] == "unsubmitted"
                del dep["files"][name]
                return httpx.Response(204)
            if rest == ["actions", "publish"]:
                assert dep["files"], "Zenodo refuses to publish a deposit without files"
                dep["state"] = "done"
                return httpx.Response(
                    202,
                    json={
                        **self._view(dep),
                        "doi": dep["metadata"]["prereserve_doi"]["doi"],
                        "links": {**dep["links"], "record_html": f"https://{host}/records/{i}"},
                    },
                )
            if rest == ["actions", "newversion"]:
                assert dep["state"] == "done"
                draft = self._new(host, dep["files"], concept=dep["concept"])
                return httpx.Response(
                    201,
                    json={
                        **self._view(dep),
                        "links": {
                            **dep["links"],
                            "latest_draft": f"https://{host}/api/deposit/depositions/{draft['id']}",
                        },
                    },
                )
        return httpx.Response(404, json={"message": f"no such route {req.method} {path}"})


@pytest.fixture
def bundle(tmp_path: Path) -> Path:
    dst = tmp_path / "showcase"
    shutil.copytree(SHOWCASE, dst, ignore=shutil.ignore_patterns(".e2er", "e2er.json"))
    make_run_db(tmp_path, paper_id_of(dst))
    return dst


@pytest.fixture
def zenodo(monkeypatch) -> Zenodo:
    z = Zenodo()
    monkeypatch.setattr(
        zen, "client_factory", lambda base: httpx.Client(base_url=base, transport=httpx.MockTransport(z))
    )
    monkeypatch.setenv("ZENODO_TOKEN", "tok")
    monkeypatch.setenv("ZENODO_SANDBOX_TOKEN", "tok")
    return z


def _record(b: Path) -> dict:
    return json.loads((b / ZENODO_RECORD).read_text())


def test_first_publish_creates_uploads_describes_and_publishes(bundle: Path, tmp_path: Path, zenodo: Zenodo):
    assert publish(str(bundle), **BASE, **REPO, **PUBLIC, out=str(tmp_path / "e")) == 0
    rec = _record(bundle)["deposits"]
    assert {i: r["state"] for i, r in rec.items()} == {"data": "published", "code": "published"}
    for item in ("data", "code"):
        dep = zenodo.deps[rec[item]["id"]]
        assert dep["state"] == "done" and rec[item]["files"] == {
            n: hashlib.md5(b).hexdigest() for n, b in dep["files"].items()
        }
        meta = dep["metadata"]
        assert meta["title"].endswith(f"({item})") and meta["upload_type"] in ("dataset", "software")
        assert meta["publication_date"] and meta["creators"] and meta["license"]
    m = json.loads((bundle / "e2er.json").read_text())
    assert m["availability"]["code"]["doi"] == rec["code"]["doi"]


def test_publishing_again_unchanged_deposits_nothing_new(bundle: Path, tmp_path: Path, zenodo: Zenodo):
    assert publish(str(bundle), **BASE, **REPO, **PUBLIC, out=str(tmp_path / "e")) == 0
    first = _record(bundle)
    n = len(zenodo.calls)
    assert publish(str(bundle), **BASE, **REPO, **PUBLIC, out=str(tmp_path / "e")) == 0
    assert _record(bundle) == first
    assert zenodo.calls[n:] == []  # the checksums are recorded: Zenodo is not even asked


def test_changed_files_become_a_new_version_of_the_same_record(bundle: Path, tmp_path: Path, zenodo: Zenodo, capsys):
    assert publish(str(bundle), **BASE, **REPO, **PUBLIC, out=str(tmp_path / "e")) == 0
    first = _record(bundle)
    old = first["deposits"]["code"]
    # The study's code changed since the deposit (e.g. an amendment): pretend the deposit holds other bytes.
    zenodo.deps[old["id"]]["files"] = {"demo-code.zip": b"the earlier code"}
    first["deposits"]["code"]["files"] = {"demo-code.zip": hashlib.md5(b"the earlier code").hexdigest()}
    (bundle / ZENODO_RECORD).write_text(json.dumps(first))
    capsys.readouterr()

    assert publish(str(bundle), **BASE, **REPO, **PUBLIC, out=str(tmp_path / "e")) == 0
    out = capsys.readouterr().out
    rec = _record(bundle)["deposits"]
    new = rec["code"]
    assert new["id"] != old["id"] and new["doi"] != old["doi"] and new["state"] == "published"
    assert new["earlier"] == [{"id": old["id"], "doi": old["doi"]}]
    assert zenodo.deps[new["id"]]["concept"] == zenodo.deps[old["id"]]["concept"]  # one record, two versions
    # The new version holds exactly the study's files: the earlier version's were removed from the draft.
    assert set(zenodo.deps[new["id"]]["files"]) == {"demo-code.zip"}
    assert zenodo.deps[new["id"]]["files"]["demo-code.zip"] != b"the earlier code"
    assert zenodo.deps[old["id"]]["files"] == {"demo-code.zip": b"the earlier code"}  # the old version stays
    assert rec["data"] == first["deposits"]["data"]  # unchanged data keep their DOI
    m = json.loads((bundle / "e2er.json").read_text())
    assert (
        m["availability"]["code"]["doi"] == new["doi"]
        and m["dossier"]["doc"]["availability"]["code"]["doi"] == new["doi"]
    )
    assert f"new version {new['doi']}" in out


def test_a_record_without_checksums_asks_zenodo(bundle: Path, tmp_path: Path, zenodo: Zenodo):
    """Deposits made before e2er recorded checksums: Zenodo's own checksums decide."""
    assert publish(str(bundle), **BASE, **REPO, **PUBLIC, out=str(tmp_path / "e")) == 0
    record = _record(bundle)
    for r in record["deposits"].values():
        del r["files"]
    (bundle / ZENODO_RECORD).write_text(json.dumps(record))
    n = len(zenodo.calls)
    assert publish(str(bundle), **BASE, **REPO, **PUBLIC, out=str(tmp_path / "e")) == 0
    later = zenodo.calls[n:]
    assert all(m == "GET" and p.endswith("/files") for m, p in later) and len(later) == 2
    assert {k: v["id"] for k, v in _record(bundle)["deposits"].items()} == {
        k: v["id"] for k, v in record["deposits"].items()
    }


def test_a_failed_publish_keeps_the_draft_and_a_retry_reuses_it(
    bundle: Path, tmp_path: Path, zenodo: Zenodo, monkeypatch
):
    real = zen.Zenodo.publish

    def fail(self, dep):
        raise zen.ZenodoError("Zenodo refused to publish (500): try later")

    monkeypatch.setattr(zen.Zenodo, "publish", fail)
    assert publish(str(bundle), **BASE, **REPO, **PUBLIC, out=str(tmp_path / "e")) == 1
    assert not (bundle / "e2er.json").exists()
    drafts = {k: v["id"] for k, v in _record(bundle)["deposits"].items()}
    monkeypatch.setattr(zen.Zenodo, "publish", real)
    assert publish(str(bundle), **BASE, **REPO, **PUBLIC, out=str(tmp_path / "e")) == 0
    assert {k: v["id"] for k, v in _record(bundle)["deposits"].items()} == drafts
    for i in drafts.values():  # the retry removed the first attempt's files before uploading again
        assert len(zenodo.deps[i]["files"]) == len(set(zenodo.deps[i]["files"]))


def test_the_sandbox_is_another_address_and_token(bundle: Path, tmp_path: Path, zenodo: Zenodo, monkeypatch):
    seen: list[str] = []
    real = zen.client_factory

    def factory(base: str):
        seen.append(base)
        return real(base)

    monkeypatch.setattr(zen, "client_factory", factory)
    monkeypatch.delenv("ZENODO_TOKEN")
    assert publish(str(bundle), **BASE, **REPO, **PUBLIC, zenodo_sandbox=True, out=str(tmp_path / "e")) == 0
    assert seen == ["https://sandbox.zenodo.org"]
    assert _record(bundle)["sandbox"] is True
    assert json.loads((bundle / "e2er.json").read_text())["availability"]["code"]["zenodo"].startswith(
        "https://sandbox.zenodo.org/records/"
    )


# ── the client on its own ────────────────────────────────────────────────────


def _client(handler) -> zen.Zenodo:
    return zen.Zenodo(
        "tok",
        base="https://zenodo.org",
        client=httpx.Client(base_url="https://zenodo.org", transport=httpx.MockTransport(handler)),
    )


def test_a_file_name_is_quoted_in_the_bucket_address():
    urls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        urls.append(str(req.url))
        return httpx.Response(201, json={})

    z = _client(handler)
    z.upload(zen.Deposit(id=1, bucket="https://zenodo.org/api/files/abc", doi=None), "a b#1.csv", b"x")
    assert urls == ["https://zenodo.org/api/files/abc/a%20b%231.csv"]


def test_a_new_version_without_a_reserved_doi_is_refused():
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/actions/newversion"):
            return httpx.Response(
                201, json={"id": 1, "links": {"latest_draft": "https://zenodo.org/api/deposit/depositions/2"}}
            )
        return httpx.Response(
            200, json={"id": 2, "links": {"bucket": "https://zenodo.org/api/files/b2"}, "metadata": {}}
        )

    with pytest.raises(zen.ZenodoError, match="no DOI"):
        _client(handler).new_version(1)


def test_zenodo_s_refusal_is_reported_in_plain_words():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"message": "Validation error.", "errors": [{"field": "metadata.creators"}]})

    with pytest.raises(zen.ZenodoError, match=r"refused to create a deposit \(400\): Validation error"):
        _client(handler).create()


def test_many_data_files_go_as_one_zip(tmp_path: Path):
    from src.cli_publish import _deposit_plan

    b = tmp_path / "s"
    (b / "data").mkdir(parents=True)
    files = {}
    for k in range(zen.MAX_FILES + 1):
        (b / "data" / f"t{k}.csv").write_text(f"{k}\n")
        files[f"data/t{k}.csv"] = "x"
    (b / "provenance.json").write_text(json.dumps({"files": files}))
    plan = _deposit_plan(b, {"data": {"access": "public"}, "code": {"access": "private"}}, "p")
    assert [n for n, _ in plan["data"]["files"]] == ["p-data.zip"]
