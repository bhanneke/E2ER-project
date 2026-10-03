"""What `e2er publish` sends to e2er.org matches the format the site enforces.

docs/schemas/research-object.schema.json is a copy of e2er.org's
src/data/registry/schema/research-object.schema.json (additionalProperties: false).
On 2026-10-02 publish added an `amendments` field the site did not know, and every
publish was refused; this test sends a real publish to a fake server and validates the
request against the copy.
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from src.cli_publish import publish
from src.core import platform_client as pc
from tests.run_db import make_run_db, paper_id_of
from tests.test_publish_integrity import ARGS, bundle  # noqa: F401  (fixture)

SCHEMA = json.loads((Path(__file__).parent.parent / "docs/schemas/research-object.schema.json").read_text())


def test_the_published_description_matches_the_sites_format(bundle: Path, tmp_path: Path, monkeypatch):  # noqa: F811
    make_run_db(tmp_path / "study", paper_id_of(bundle), researcher_actions=2)
    sent: list[dict] = []

    def server(base, method, path, token=None, body=None):
        sent.append(body)
        oid = body["manifest"]["id"]
        return 201, {
            "id": oid,
            "owner_project": oid,
            "version": 1,
            "study_url": f"{base}/{oid}",
            "dossier_url": f"{base}/d/x",
        }

    monkeypatch.setattr(pc, "request", server)
    monkeypatch.setattr(pc, "load_token", lambda base: "tok")
    rc = publish(str(bundle), **ARGS, demonstration=True, to_url="https://e2er.example", site="https://e2er.example")
    assert rc == 0 and len(sent) == 1
    manifest = sent[0]["manifest"]
    d = sent[0]["dossier"]
    # As the site validates it (src/lib/api/publish.ts checkBody): the dossier sent alongside, inserted.
    jsonschema.Draft202012Validator(SCHEMA).validate(
        {**manifest, "dossier": {"id": d["id"], "url": manifest["dossier"]["url"], "doc": d["doc"]}}
    )
    prov = json.loads((bundle / "provenance.json").read_text())
    assert "amendments" not in manifest and isinstance(prov.get("amendments", []), list)


def test_publishing_to_another_platform_names_its_dossier_address(
    bundle: Path,  # noqa: F811
    tmp_path: Path,
    monkeypatch,
    capsys,
):
    """`--to https://e2er.example`: the dossier address in e2er.json, the request, the output and the paper is there."""
    make_run_db(tmp_path / "study", paper_id_of(bundle))
    sent: list[dict] = []

    def server(base, method, path, token=None, body=None):
        sent.append(body)
        oid = body["manifest"]["id"]
        return 201, {"id": oid, "owner_project": oid, "version": 1, "study_url": f"{base}/{oid}", "dossier_url": "x"}

    monkeypatch.setattr(pc, "request", server)
    monkeypatch.setattr(pc, "load_token", lambda base: "tok")
    monkeypatch.delenv("E2ER_URL", raising=False)
    assert publish(str(bundle), **ARGS, to_url="https://e2er.example", site="https://e2er.example") == 0
    url = sent[0]["manifest"]["dossier"]["url"]
    assert url.startswith("https://e2er.example/d/")
    assert json.loads((bundle / "e2er.json").read_text())["dossier"]["url"] == url
    assert f"\\url{{{url}}}" in (bundle / "paper" / "paper.tex").read_text()
    out = capsys.readouterr().out
    assert "https://e2er.org/d/" not in out and url in out
