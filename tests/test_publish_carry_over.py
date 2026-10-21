"""`e2er publish` of a new version whose run database is gone: the earlier version's dossier, carried over.

On 2026-10-19 the run databases of five published demos were gone (macOS
cleared /tmp). Publishing them again with their files on GitHub would have
built dossiers without steps. Now publish fetches the dossier of the version
the folder published from e2er.org (a fake platform here), checks it against
.e2er/link.json and e2er.json, and carries it over with its steps unchanged,
the new availability and an amendment that says so. Anything that does not
match is refused, and nothing in the folder changes.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import jsonschema
import pytest

from src.cli_publish import publish
from src.core import carry_over as co
from src.core import platform_client as pc
from src.core.dossier import dossier_id, short_id
from tests.test_publish_data_terms import plain_bundle  # noqa: F401 — fixture
from tests.test_publish_github import ID, _git, github, who_study  # noqa: F401 — fixtures

SCHEMA = json.loads((Path(__file__).parent.parent / "docs/schemas/research-object.schema.json").read_text())
SITE = "https://e2er.example"


class FakePlatform:
    """POST /api/v1/studies stores a version; GET serves the study and its dossiers, as e2er.org does."""

    def __init__(self) -> None:
        self.versions: list[dict] = []
        self.dossiers: dict[str, dict] = {}
        self.sent: list[dict] = []
        self.tamper = False

    def __call__(self, base, method, path, token=None, body=None):
        if method == "GET" and path == "/api/v1/me":
            return 200, {"name": "Ada", "handles": ["ada"]}
        if method == "POST" and path == "/api/v1/studies":
            self.sent.append(body)
            oid = body["manifest"]["id"]
            self.dossiers[short_id(body["dossier"]["id"])] = copy.deepcopy(body["dossier"]["doc"])
            self.versions.append(
                {
                    "number": len(self.versions) + 1,
                    "content_id": body["manifest"]["content_id"],
                    "dossier_id": body["dossier"]["id"],
                }
            )
            n = len(self.versions)
            return 201, {
                "id": oid,
                "owner_project": oid,
                "version": n,
                "study_url": f"{base}/{oid}",
                "dossier_url": f"{base}/d/{short_id(body['dossier']['id'])}",
            }
        if method == "GET" and path.startswith("/api/v1/studies/"):
            if not self.versions:
                return 404, {"error": "not found"}
            return 200, {
                "id": path.removeprefix("/api/v1/studies/"),
                "latest": self.versions[-1],
                "versions": self.versions,
            }
        if method == "GET" and path.startswith("/api/v1/dossiers/"):
            doc = self.dossiers.get(path.rsplit("/", 1)[-1])
            if doc is None:
                return 404, {"error": "not found"}
            doc = copy.deepcopy(doc)
            if self.tamper:
                doc["workflow"] = doc["workflow"][:1]
            return 200, doc
        raise AssertionError(f"unexpected request {method} {path}")


@pytest.fixture
def platform(monkeypatch) -> FakePlatform:
    fake = FakePlatform()
    monkeypatch.setattr(pc, "request", fake)
    monkeypatch.setattr(pc, "load_token", lambda base: "tok")
    monkeypatch.delenv("E2ER_URL", raising=False)
    return fake


def _published_without_db(study: Path, tmp_path: Path, platform: FakePlatform) -> dict:
    """Version 1 published from the run database; then the database is gone. Returns version 1's dossier."""
    assert publish(str(study), **ID, demonstration=True, to_url=SITE, site=SITE, yes=True) == 0
    (tmp_path / "e2er.db").unlink()
    first = platform.sent[0]["dossier"]["doc"]
    assert first["workflow"], "version 1 lists the run's steps"
    return first


def _snapshot(b: Path) -> dict[str, bytes]:
    return {p.relative_to(b).as_posix(): p.read_bytes() for p in b.rglob("*") if p.is_file()}


def test_a_new_version_on_github_carries_over_the_dossier_with_its_steps(
    who_study: Path,  # noqa: F811
    github: Path,  # noqa: F811
    tmp_path: Path,
    platform: FakePlatform,
    capsys,
):
    first = _published_without_db(who_study, tmp_path, platform)
    v1_manifest = json.loads((who_study / "e2er.json").read_text())
    capsys.readouterr()
    rc = publish(
        str(who_study),
        **ID,
        demonstration=True,
        github_repo="ada/demos",
        github_path="who",
        to_url=SITE,
        site=SITE,
        yes=True,
    )
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "the run database is not available" in out and "carried over from version 1" in out
    body = platform.sent[-1]
    doc = body["dossier"]["doc"]
    assert body["dossier"]["id"] == dossier_id(doc)
    # The steps, segments, events and components are version 1's, unchanged; none is added.
    for key in ("workflow", "e2er", "run", "components", "data", "schema"):
        assert doc[key] == first[key], key
    # The new availability: the files on GitHub.
    assert doc["availability"]["code"]["access"] == "public"
    assert doc["availability"]["code"]["url"] == "https://github.com/ada/demos"
    assert doc["purpose"] == "demonstration"
    (carried,) = [a for a in doc["amendments"] if a.get("kind") == co.KIND]
    assert carried["path"] == "e2er.json" and carried["from_version"] == 1
    assert carried["from_dossier"] == platform.versions[0]["dossier_id"]
    assert carried["reason"].startswith(
        "published again with files on GitHub; run database not available, dossier carried over from version 1"
    )
    # e2er.json describes the run as version 1 did (recorded agents), and matches the site's format.
    m = json.loads((who_study / "e2er.json").read_text())
    assert m["ai"] == v1_manifest["ai"] and m["ai"]["agents_source"] == "recorded"
    assert m["components"] == v1_manifest["components"]
    d = body["dossier"]
    jsonschema.Draft202012Validator(SCHEMA).validate(
        {**body["manifest"], "dossier": {"id": d["id"], "url": body["manifest"]["dossier"]["url"], "doc": d["doc"]}}
    )
    # The repository holds the carried-over dossier; the paper's footnote names it.
    bare = github / "ada" / "demos.git"
    pushed = json.loads(_git("--git-dir", str(bare), "show", "main:who/e2er.json"))
    assert pushed["dossier"]["doc"]["workflow"] == first["workflow"]
    assert short_id(d["id"]) in (who_study / "paper" / "paper.tex").read_text()
    link = json.loads((who_study / ".e2er" / "link.json").read_text())
    assert link["version"] == 2 and link["dossier_id"] == d["id"]


def test_dry_run_shows_the_carry_over_and_changes_nothing(
    who_study: Path,  # noqa: F811
    github: Path,  # noqa: F811
    tmp_path: Path,
    platform: FakePlatform,
    capsys,
):
    first = _published_without_db(who_study, tmp_path, platform)
    before = _snapshot(who_study)
    capsys.readouterr()
    rc = publish(
        str(who_study), **ID, demonstration=True, github_repo="ada/demos", github_path="who", dry_run=True, yes=True
    )
    got = capsys.readouterr()
    assert rc == 0, got.out + got.err
    assert "WARNING: the run database is not available" in got.err and "carried over" in got.err
    body = json.loads(got.out)
    assert body["dossier"]["doc"]["workflow"] == first["workflow"]
    assert any(a.get("kind") == co.KIND for a in body["dossier"]["doc"]["amendments"])
    assert _snapshot(who_study) == before
    assert len(platform.sent) == 1, "a dry run sends nothing"


def test_a_newer_version_published_elsewhere_is_never_carried_over(
    who_study: Path,  # noqa: F811
    tmp_path: Path,
    platform: FakePlatform,
    capsys,
):
    _published_without_db(who_study, tmp_path, platform)
    platform.versions.append({"number": 2, "content_id": "sha256:" + "1" * 64, "dossier_id": "sha256:" + "2" * 64})
    before = _snapshot(who_study)
    capsys.readouterr()
    assert publish(str(who_study), **ID, demonstration=True, to_url=SITE, site=SITE, yes=True) == 1
    out = capsys.readouterr().out
    assert "cannot be carried over" in out and "published from elsewhere" in out
    assert _snapshot(who_study) == before


def test_a_dossier_that_does_not_hash_to_its_id_is_refused(
    who_study: Path,  # noqa: F811
    tmp_path: Path,
    platform: FakePlatform,
    capsys,
):
    _published_without_db(who_study, tmp_path, platform)
    platform.tamper = True
    before = _snapshot(who_study)
    capsys.readouterr()
    assert publish(str(who_study), **ID, demonstration=True, to_url=SITE, site=SITE, yes=True) == 1
    out = capsys.readouterr().out
    assert "hashes to" in out and "not carried over" in out
    assert _snapshot(who_study) == before and len(platform.sent) == 1


def test_another_project_never_takes_the_folders_dossier(
    who_study: Path,  # noqa: F811
    tmp_path: Path,
    platform: FakePlatform,
    capsys,
):
    _published_without_db(who_study, tmp_path, platform)
    capsys.readouterr()
    args = {**ID, "project": "other"}
    assert publish(str(who_study), **args, demonstration=True, to_url=SITE, site=SITE, yes=True) == 1
    assert "another study's dossier is never carried over" in capsys.readouterr().out


def test_an_unreachable_platform_refuses_and_says_why(
    who_study: Path,  # noqa: F811
    tmp_path: Path,
    platform: FakePlatform,
    monkeypatch,
    capsys,
):
    _published_without_db(who_study, tmp_path, platform)

    def down(*a, **k):
        raise OSError("connection refused")

    monkeypatch.setattr(pc, "request", down)
    capsys.readouterr()
    assert publish(str(who_study), **ID, demonstration=True, to_url=SITE, site=SITE, yes=True) == 1
    out = capsys.readouterr().out
    assert "could not reach" in out and "no run database with paper" in out


def test_no_db_still_builds_the_dossier_without_steps(
    who_study: Path,  # noqa: F811
    tmp_path: Path,
    platform: FakePlatform,
    capsys,
):
    """--no-db is the researcher's explicit choice: no fetch, a dossier that says its steps are not recorded."""
    _published_without_db(who_study, tmp_path, platform)
    capsys.readouterr()
    assert publish(str(who_study), **ID, demonstration=True, no_db=True, to_url=SITE, site=SITE, yes=True) == 0
    doc = platform.sent[-1]["dossier"]["doc"]
    assert doc["workflow"] == [] and doc["run"]["workflow_recorded"] is False
    assert not any(a.get("kind") == co.KIND for a in doc.get("amendments") or [])


def test_data_that_differ_from_the_earlier_dossier_are_named():
    prev = co.Previous(
        version=1,
        dossier_id="sha256:" + "a" * 64,
        doc={"data": [{"path": "data/a.csv", "sha256": "1" * 64}, {"path": "data/b.csv", "sha256": "2" * 64}]},
        manifest={},
        manifest_sha256="3" * 64,
        platform_url=SITE,
    )
    now = [{"path": "data/a.csv", "sha256": "1" * 64}, {"path": "data/b.csv", "sha256": "9" * 64}]
    assert co.data_mismatch(prev, now) == ["data/b.csv"]
    assert co.data_mismatch(prev, now[:1] + [{"path": "data/b.csv", "sha256": "2" * 64}]) == []
