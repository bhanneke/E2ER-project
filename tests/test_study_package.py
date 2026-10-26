# ruff: noqa: F811 — the fixtures imported from tests/test_publish_github.py are arguments here
"""The study package that goes with a published study (src/core/study_package.py).

`e2er publish --github` puts the package the files were opened from on a release of the study's
repository (``<project>-v<N>``, never forced, never overwritten), and the request and e2er.json record
``package``; `--zenodo` adds it to the code deposit; `e2er verify <file> --against` compares a package
with the record; `e2er fetch` downloads it and checks size and SHA-256.

GitHub is the fake of tests/test_publish_github.py (bare repositories, a fake gh with releases), e2er.org
a fake ``pc.request``; downloads go to an httpx.MockTransport. Nothing reaches the network.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx
import pytest

from src.cli_fetch import fetch, resolve
from src.cli_publish import publish
from src.cli_verify import verify
from src.core import platform_client as pc
from src.core import study_package as sp
from src.core.export import package as pkg
from tests.test_publish_data_terms import plain_bundle  # noqa: F401 — fixture
from tests.test_publish_github import ID, _git, _tree, github, who_study  # noqa: F401 — fixtures

ARGS = dict(**ID, github_repo="ada/demos", github_path="who")


def _releases(github: Path) -> Path:
    return github / "ada" / "demos.releases"


def _registered(github: Path) -> list[dict]:
    p = github / "registered.jsonl"
    return [json.loads(line) for line in p.read_text().splitlines()] if p.is_file() else []


# ── publish --github: the package as the file of a release ───────────────────


def test_the_package_becomes_the_file_of_a_release_at_the_pushed_commit(
    who_study: Path,
    github: Path,
    tmp_path: Path,
    capsys,
):
    assert publish(str(who_study), **ARGS, out=str(tmp_path / "e"), yes=True) == 0
    out = capsys.readouterr().out
    rel = _releases(github) / "demo-v1"
    asset = rel / "assets" / "demo-v1.e2er"
    assert asset.is_file(), out
    meta = json.loads((rel / "release.json").read_text())
    assert meta["latest"] is False, "a study's release never becomes the repository's latest"
    bare = github / "ada" / "demos.git"
    commit = _git("--git-dir", str(bare), "rev-parse", "main")
    assert _git("--git-dir", str(bare), "rev-parse", "refs/tags/demo-v1") == commit
    (body,) = _registered(github)
    m = json.loads((who_study / "e2er.json").read_text())
    want = {
        "url": "https://github.com/ada/demos/releases/download/demo-v1/demo-v1.e2er",
        "sha256": hashlib.sha256(asset.read_bytes()).hexdigest(),
        "bytes": asset.stat().st_size,
        "host": "github",
        "fingerprint": pkg.read_manifest(asset)["fingerprint"],
    }
    assert body["manifest"]["package"] == want and m["package"] == want
    # The folder in the repository is exactly that package, opened (its e2er.json carries no package).
    names = {c["path"] for c in pkg.read_manifest(asset)["contents"]} | {"e2er-package.json"}
    assert {p.removeprefix("who/") for p in _tree(bare)} == names
    inner = json.loads(_git("--git-dir", str(bare), "show", "main:who/e2er.json"))
    assert "package" not in inner and inner["dossier"]["id"] == m["dossier"]["id"]
    assert "Uploaded the study package demo-v1.e2er" in out
    assert json.loads((who_study / ".e2er" / "package.json").read_text())["tag"] == "demo-v1"


def test_publishing_the_same_files_again_reuses_the_release_and_a_new_version_gets_its_own(
    who_study: Path,
    github: Path,
    tmp_path: Path,
    capsys,
):
    assert publish(str(who_study), **ARGS, out=str(tmp_path / "e1"), yes=True) == 0
    first = (_releases(github) / "demo-v1" / "assets" / "demo-v1.e2er").read_bytes()
    capsys.readouterr()
    assert publish(str(who_study), **ARGS, out=str(tmp_path / "e2"), yes=True) == 0
    out = capsys.readouterr().out
    assert "Already on GitHub: the study package demo-v1.e2er" in out
    assert (_releases(github) / "demo-v1" / "assets" / "demo-v1.e2er").read_bytes() == first
    assert publish(str(who_study), **ARGS, license_id="MIT", out=str(tmp_path / "e3"), yes=True) == 0
    assert (_releases(github) / "demo-v2" / "assets" / "demo-v2.e2er").is_file()
    regs = _registered(github)
    assert [r["manifest"]["package"]["url"].rsplit("/", 1)[-1] for r in regs] == [
        "demo-v1.e2er",
        "demo-v1.e2er",
        "demo-v2.e2er",
    ]


def test_a_tag_at_another_commit_is_never_moved_and_nothing_is_registered(
    who_study: Path,
    github: Path,
    tmp_path: Path,
    capsys,
):
    from tests.test_publish_github import _seed

    bare = _seed(github, "ada/demos", {"README.md": "demos\n"})
    _git("--git-dir", str(bare), "tag", "demo-v1", "main")
    assert publish(str(who_study), **ARGS, out=str(tmp_path / "e"), yes=True) == 1
    out = capsys.readouterr().out
    assert "already has the tag demo-v1 at another commit" in out and "e2er never moves a tag" in out
    assert _registered(github) == [], "nothing is registered without the package"
    assert not (who_study / "e2er.json").exists() or "package" not in json.loads((who_study / "e2er.json").read_text())


def test_an_asset_with_other_bytes_is_never_overwritten(
    who_study: Path,
    github: Path,
    tmp_path: Path,
    capsys,
):
    assert publish(str(who_study), **ARGS, out=str(tmp_path / "e1"), yes=True) == 0
    asset = _releases(github) / "demo-v1" / "assets" / "demo-v1.e2er"
    asset.write_bytes(b"someone else's bytes")
    capsys.readouterr()
    assert publish(str(who_study), **ARGS, out=str(tmp_path / "e2"), yes=True) == 1
    out = capsys.readouterr().out
    assert "already has a file demo-v1.e2er with other bytes" in out and "never overwrites" in out
    assert asset.read_bytes() == b"someone else's bytes"
    assert len(_registered(github)) == 1


def test_a_failed_upload_registers_nothing_and_the_same_command_finishes_it(
    who_study: Path,
    github: Path,
    tmp_path: Path,
    monkeypatch,
    capsys,
):
    monkeypatch.setenv("FAKE_GH_RELEASE_FAILS", "1")
    assert publish(str(who_study), **ARGS, out=str(tmp_path / "e1"), yes=True) == 1
    out = capsys.readouterr().out
    assert "could not create the release demo-v1" in out and "nothing was registered" in out
    assert _registered(github) == []
    monkeypatch.delenv("FAKE_GH_RELEASE_FAILS")
    bare = github / "ada" / "demos.git"
    before = _git("--git-dir", str(bare), "rev-parse", "main")
    assert publish(str(who_study), **ARGS, out=str(tmp_path / "e2"), yes=True) == 0
    assert _git("--git-dir", str(bare), "rev-parse", "main") == before, "no new commit"
    assert len(_registered(github)) == 1 and (_releases(github) / "demo-v1" / "assets" / "demo-v1.e2er").is_file()


def test_a_dry_run_shows_the_package_it_would_record_and_makes_no_release(
    who_study: Path,
    github: Path,
    capsys,
):
    assert publish(str(who_study), **ARGS, dry_run=True, yes=True) == 0
    captured = capsys.readouterr()
    body = json.loads(captured.out)
    rec = body["manifest"]["package"]
    assert rec["url"] == "https://github.com/ada/demos/releases/download/demo-v1/demo-v1.e2er"
    assert sp.record_problems(rec) == []
    assert "would upload demo-v1.e2er" in captured.err
    assert not _releases(github).exists()


# ── verify --against: the package against the record ─────────────────────────


def _published(who_study: Path, github: Path, tmp_path: Path) -> tuple[Path, dict]:
    assert publish(str(who_study), **ARGS, out=str(tmp_path / "e"), yes=True) == 0
    asset = _releases(github) / "demo-v1" / "assets" / "demo-v1.e2er"
    (body,) = _registered(github)
    m = body["manifest"]
    record = {
        "versions": [
            {
                "number": 1,
                "content_id": m["content_id"],
                "dossier_id": body["dossier"]["id"],
                "package": m["package"],
            }
        ],
        "latest": {"number": 1},
    }
    return asset, record


def _checks(capsys) -> dict[str, dict]:
    report = json.loads(capsys.readouterr().out)
    return {c["name"]: c for c in report["checks"]}


def test_verify_against_the_study_record_compares_the_package_fingerprint(
    who_study: Path,
    github: Path,
    tmp_path: Path,
    capsys,
):
    asset, record = _published(who_study, github, tmp_path)
    saved = tmp_path / "study.json"
    saved.write_text(json.dumps(record))
    capsys.readouterr()
    verify(str(asset), json_output=True, against_file=str(saved))
    checks = _checks(capsys)
    assert checks["published"]["status"] == "PASS"
    assert checks["package published"]["status"] == "PASS"
    assert "byte for byte" in checks["package published"]["detail"]

    record["versions"][0]["package"] = {**record["versions"][0]["package"], "fingerprint": "sha256:" + "1" * 64}
    saved.write_text(json.dumps(record))
    assert verify(str(asset), json_output=True, against_file=str(saved)) == 1
    checks = _checks(capsys)
    assert (
        checks["package published"]["status"] == "FAIL" and "its files differ" in checks["package published"]["detail"]
    )

    record["versions"][0]["package"] = None
    saved.write_text(json.dumps(record))
    verify(str(asset), json_output=True, against_file=str(saved))
    assert _checks(capsys)["package published"]["status"] == "SKIP"


def test_verify_against_a_dossier_reads_the_dossiers_package_record(
    who_study: Path,
    github: Path,
    tmp_path: Path,
    monkeypatch,
    capsys,
):
    asset, record = _published(who_study, github, tmp_path)
    (body,) = _registered(github)
    did = body["dossier"]["id"]
    short = did.removeprefix("sha256:")[:16]
    seen: list[str] = []

    def answer(req: httpx.Request) -> httpx.Response:
        seen.append(req.url.path)
        assert req.method == "GET"
        if req.url.path == f"/api/v1/dossiers/{short}":
            return httpx.Response(200, json=body["dossier"]["doc"])
        if req.url.path == f"/api/v1/dossiers/{short}/package":
            return httpx.Response(200, json={"package": body["manifest"]["package"], "study": "ada/demo", "version": 1})
        return httpx.Response(404, json={"error": "no"})

    monkeypatch.setattr(
        pc, "client_factory", lambda url: httpx.Client(base_url=url, transport=httpx.MockTransport(answer))
    )
    capsys.readouterr()
    verify(str(asset), json_output=True, against=f"https://e2er.example/d/{short}")
    checks = _checks(capsys)
    assert checks["published"]["status"] == "PASS" and checks["package published"]["status"] == "PASS"
    assert seen == [f"/api/v1/dossiers/{short}", f"/api/v1/dossiers/{short}/package"]


def test_a_folder_verified_against_gets_no_package_check(
    who_study: Path,
    github: Path,
    tmp_path: Path,
    capsys,
):
    asset, record = _published(who_study, github, tmp_path)
    saved = tmp_path / "study.json"
    saved.write_text(json.dumps(record))
    folder = pkg.open_package(asset, tmp_path / "opened").root
    capsys.readouterr()
    verify(str(folder), json_output=True, against_file=str(saved))
    assert "package published" not in _checks(capsys)


# ── e2er fetch ───────────────────────────────────────────────────────────────


@pytest.fixture
def hosted(tmp_path: Path, monkeypatch):
    """A package kept on a fake GitHub (a release address that redirects to its storage) and e2er.org's record."""
    data = b"PK\x03\x04 a study package"
    rec = {
        "url": "https://github.com/ada/demos/releases/download/demo-v1/demo-v1.e2er",
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
        "host": "github",
        "fingerprint": "sha256:" + "a" * 64,
    }
    state = {
        "data": data,
        "study": {"versions": [{"number": 1, "content_id": "sha256:c", "package": rec}], "latest": {"number": 1}},
    }

    def site(req: httpx.Request) -> httpx.Response:
        assert req.method == "GET"
        if req.url.path == "/api/v1/studies/ada/demo":
            return httpx.Response(200, json=state["study"])
        if req.url.path == "/api/v1/dossiers/0123456789abcdef/package":
            return httpx.Response(200, json={"package": rec, "study": "ada/demo", "version": 1})
        return httpx.Response(404, json={"error": "not found"})

    def storage(req: httpx.Request) -> httpx.Response:
        if req.url.host == "github.com":
            return httpx.Response(302, headers={"location": "https://release-assets.example/x/demo-v1.e2er?sig=1"})
        return httpx.Response(200, content=state["data"])

    monkeypatch.setattr(
        pc, "client_factory", lambda url: httpx.Client(base_url=url, transport=httpx.MockTransport(site))
    )
    monkeypatch.setattr(sp, "download_client", lambda: httpx.Client(transport=httpx.MockTransport(storage)))
    hops: list[str] = []
    monkeypatch.setattr(sp, "_check_hop", lambda url: hops.append(url))
    monkeypatch.chdir(tmp_path)
    state["hops"] = hops
    return state


def test_fetch_downloads_the_recorded_package_checks_it_and_prints_the_commands(hosted, tmp_path: Path, capsys):
    assert fetch("https://e2er.example/ada/demo") == 0
    out = capsys.readouterr().out
    got = tmp_path / "demo-v1.e2er"
    assert got.read_bytes() == hosted["data"]
    assert hosted["hops"] == [
        "https://github.com/ada/demos/releases/download/demo-v1/demo-v1.e2er",
        "https://release-assets.example/x/demo-v1.e2er?sig=1",
    ], "every hop is checked"
    for line in (
        "e2er inspect demo-v1.e2er",
        "e2er verify demo-v1.e2er --against https://e2er.example/ada/demo",
        "e2er reproduce demo-v1.e2er",
        "Docker container",
        "Nothing was opened or run",
    ):
        assert line in out


def test_fetch_from_a_dossier_address(hosted, tmp_path: Path, capsys):
    (tmp_path / "dl").mkdir()
    assert fetch("https://e2er.example/d/0123456789abcdef", str(tmp_path / "dl")) == 0
    out = capsys.readouterr().out
    assert (tmp_path / "dl" / "demo-v1.e2er").is_file()
    assert "--against https://e2er.example/d/0123456789abcdef" in out


def test_fetch_keeps_nothing_when_the_file_is_not_the_recorded_one(hosted, tmp_path: Path, capsys):
    hosted["data"] = b"PK\x03\x04 a study packagE"  # the same size, other bytes
    assert fetch("https://e2er.example/ada/demo") == 1
    assert "SHA-256 is not the one e2er.org records" in capsys.readouterr().out
    assert not list(tmp_path.glob("*demo-v1*"))
    hosted["data"] = b"PK\x03\x04 a longer study package than recorded"
    assert fetch("https://e2er.example/ada/demo") == 1
    assert "larger than the recorded" in capsys.readouterr().out
    assert not list(tmp_path.glob("*demo-v1*"))


def test_fetch_says_when_nothing_is_recorded(hosted, capsys):
    hosted["study"]["versions"][0]["package"] = None
    assert fetch("https://e2er.example/ada/demo") == 1
    assert "records no study package for version 1 of ada/demo" in capsys.readouterr().out
    assert fetch("https://e2er.example/ada/demo", version=3) == 1
    assert "has no version 3" in capsys.readouterr().out
    assert fetch("https://e2er.example/r/abcdef") == 1
    assert "anonymous version" in capsys.readouterr().out


def test_a_download_is_https_only_and_never_overwrites(tmp_path: Path):
    with pytest.raises(sp.PackageHostError, match="not https"):
        sp._check_hop("http://github.com/x")
    (tmp_path / "a.e2er").write_bytes(b"mine")
    with pytest.raises(sp.PackageHostError, match="exists already"):
        sp.download("https://x.example/a.e2er", tmp_path / "a.e2er", expect_bytes=4, expect_sha256="0" * 64)
    assert (tmp_path / "a.e2er").read_bytes() == b"mine"


def test_resolve_reads_api_addresses_too(hosted):
    rec, what, against = resolve("https://e2er.example/api/v1/studies/ada/demo")
    assert rec["host"] == "github" and what == "ada/demo, version 1" and against == "https://e2er.example/ada/demo"


# ── the names and the record ─────────────────────────────────────────────────


def test_release_names_never_look_like_e2ers_own_releases():
    assert sp.tag_for("vaccines", 2) == "vaccines-v2" and sp.asset_name("demo", 1) == "demo-v1.e2er"
    assert sp.file_name({"url": "https://github.com/a/b/releases/download/t/..%2Fx.e2er"}) == "study.e2er"
    assert sp.record_problems({"url": "http://x", "sha256": "z", "bytes": 0, "host": "s3", "fingerprint": "x"}) == [
        "its address is not an https address",
        "its SHA-256 is not 64 hexadecimal characters",
        "its size is not a positive whole number of bytes",
        "its host is not one of github, zenodo",
        "its fingerprint is not sha256:<64 hexadecimal characters>",
    ]


def test_the_version_number_comes_from_the_platform():
    def server(versions, code=200):
        return lambda base, method, path, token=None, body=None: (
            code,
            {"versions": versions, "latest": versions[-1] if versions else None},
        )

    assert sp.version_for("https://e2er.example", "ada/demo", "sha256:c", request=server([], 404)) == 1
    two = [{"number": 1, "content_id": "sha256:a"}, {"number": 2, "content_id": "sha256:c"}]
    assert sp.version_for("https://e2er.example", "ada/demo", "sha256:c", request=server(two)) == 2
    assert sp.version_for("https://e2er.example", "ada/demo", "sha256:new", request=server(two)) == 3
    with pytest.raises(sp.PackageHostError):
        sp.version_for("https://e2er.example", "ada/demo", None, request=server(two, 500))


# ── publish --zenodo: the package in the code deposit ────────────────────────


@pytest.fixture
def zenodo_bundle(tmp_path: Path, monkeypatch):
    import shutil

    from src.core import zenodo as zen
    from tests.run_db import make_run_db, paper_id_of
    from tests.test_publish_access import SHOWCASE
    from tests.test_publish_zenodo_versions import Zenodo

    dst = tmp_path / "showcase"
    shutil.copytree(SHOWCASE, dst, ignore=shutil.ignore_patterns(".e2er", "e2er.json"))
    make_run_db(tmp_path, paper_id_of(dst))
    z = Zenodo()
    monkeypatch.setattr(
        zen, "client_factory", lambda base: httpx.Client(base_url=base, transport=httpx.MockTransport(z))
    )
    monkeypatch.setenv("ZENODO_TOKEN", "tok")
    monkeypatch.setattr(pkg, "uv_lock", lambda r, p, a: (None, "offline in the tests"))
    return dst, z


def test_with_a_public_paper_the_package_goes_into_the_code_deposit(zenodo_bundle, tmp_path: Path, capsys):
    from src.cli_publish import _zenodo_records
    from tests.test_publish_access import BASE, REPO

    b, z = zenodo_bundle
    rc = publish(
        str(b),
        **BASE,
        **REPO,
        data="public",
        code="public",
        paper="public",
        zenodo=True,
        yes=True,
        out=str(tmp_path / "e"),
    )
    out = capsys.readouterr().out
    assert rc == 0, out
    code = next(iter(_zenodo_records(b).values()))["deposits"]["code"]
    files = z.deps[code["id"]]["files"]
    assert set(files) == {"demo-code.zip", "demo-v1.e2er"}
    m = json.loads((b / "e2er.json").read_text())
    assert m["package"] == {
        "url": f"https://zenodo.org/records/{code['id']}/files/demo-v1.e2er",
        "sha256": hashlib.sha256(files["demo-v1.e2er"]).hexdigest(),
        "bytes": len(files["demo-v1.e2er"]),
        "host": "zenodo",
        "fingerprint": m["package"]["fingerprint"],
    }
    assert code["package"]["sha256"] == m["package"]["sha256"]
    # The checksums that decide whether the code changed are the code's own, without the package.
    assert set(code["files"]) == {"demo-code.zip"}
    # The package's own e2er.json names no package: it cannot name itself.
    p = tmp_path / "demo-v1.e2er"
    p.write_bytes(files["demo-v1.e2er"])
    assert pkg.read_manifest(p)["fingerprint"] == m["package"]["fingerprint"]
    assert "package" not in json.loads(pkg.read_member(p, "e2er.json") or b"{}")


def test_with_a_private_paper_no_package_goes_to_zenodo(zenodo_bundle, tmp_path: Path, capsys):
    from src.cli_publish import _zenodo_records
    from tests.test_publish_access import BASE, REPO

    b, z = zenodo_bundle
    rc = publish(str(b), **BASE, **REPO, data="public", code="public", zenodo=True, yes=True, out=str(tmp_path / "e"))
    out = capsys.readouterr().out
    assert rc == 0, out
    code = next(iter(_zenodo_records(b).values()))["deposits"]["code"]
    assert set(z.deps[code["id"]]["files"]) == {"demo-code.zip"}
    assert "package" not in json.loads((b / "e2er.json").read_text())
    assert "the paper is private and the package holds it" in out


# ── the backfill: a pushed folder is its package, opened ─────────────────────


def test_a_pushed_folder_repacks_into_the_package_it_was_opened_from(who_study: Path, github: Path, tmp_path: Path):
    from tests.test_publish_github import _clone

    assert publish(str(who_study), **ARGS, out=str(tmp_path / "e"), yes=True) == 0
    asset = _releases(github) / "demo-v1" / "assets" / "demo-v1.e2er"
    clone = _clone(github / "ada" / "demos.git", tmp_path / "clone")
    (clone / "who" / "NOTES.txt").write_text("not the study's\n")
    packed = pkg.repack(clone / "who", tmp_path / "again.e2er")
    assert packed.path.read_bytes() == asset.read_bytes(), "byte for byte the package the release carries"
    assert packed.notes == ["NOTES.txt is in the folder but not in the package's list; it was not taken"]
    (clone / "who" / "paper" / "paper.tex").write_text("changed\n")
    with pytest.raises(pkg.PackageError, match="paper/paper.tex: not the file the list names"):
        pkg.repack(clone / "who", tmp_path / "changed.e2er")
    assert not (tmp_path / "changed.e2er").exists()
