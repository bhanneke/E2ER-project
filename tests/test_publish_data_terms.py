"""e2er publish and data under a source's own terms (the Global Macro Database).

The GMD data may be published with the study only after the researcher confirms
the GMD terms (--accept-data-terms gmd, or yes at the prompt); the description
and the dossier name the terms and the citation in every case.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import httpx
import jsonschema
import pytest

from src.cli_publish import publish
from src.core import platform_client as pc
from src.core import zenodo as zen
from src.modules.data import gmd_provider as gmd
from tests.run_db import make_run_db, paper_id_of
from tests.test_publish_access import BASE, REPO, SHOWCASE, FakeZenodo

SCHEMA = json.loads((Path(__file__).parent.parent / "docs/schemas/research-object.schema.json").read_text())
CSV = "data/gmd_panel.csv"


def _add(b: Path, rel: str, content: bytes) -> None:
    """Put a file into the bundle as if export had written it (listed in provenance.json)."""
    p = b / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)
    prov_path = b / "provenance.json"
    prov = json.loads(prov_path.read_text(encoding="utf-8"))
    prov["files"][rel] = {"sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)}
    prov_path.write_text(json.dumps(prov, indent=2) + "\n", encoding="utf-8")


@pytest.fixture
def fake(monkeypatch) -> FakeZenodo:
    f = FakeZenodo()
    monkeypatch.setattr(
        zen, "client_factory", lambda base: httpx.Client(base_url=base, transport=httpx.MockTransport(f))
    )
    monkeypatch.setenv("ZENODO_TOKEN", "tok")
    return f


@pytest.fixture
def plain_bundle(tmp_path: Path) -> Path:
    dst = tmp_path / "showcase"
    shutil.copytree(SHOWCASE, dst, ignore=shutil.ignore_patterns(".e2er", "e2er.json"))
    make_run_db(tmp_path, paper_id_of(dst))
    return dst


@pytest.fixture
def bundle(plain_bundle: Path) -> Path:
    """The showcase study with one GMD load saved as data/gmd_panel.csv, as `e2er-data gmd` records it."""
    load = {
        "connector": "gmd",
        "dataset": gmd.DATASET,
        "version": "2026_09",
        "files": [{"url": f"{gmd.BASES[0]}/distribute/GMD_2026_09.csv", "sha256": "a" * 64, "bytes": 10}],
        "variables": ["rGDP"],
        "rows": 2,
        "licence": gmd.LICENCE,
        "terms": gmd.TERMS_URL,
        "citation": gmd.CITATION,
        "cite_key": gmd.CITE_KEY,
        "saved_to": CSV,
    }
    _add(plain_bundle, CSV, b"ISO3,year,rGDP\nDEU,2020,1.0\nFRA,2020,2.0\n")
    sources = {"loads": [load]}
    _add(plain_bundle, "data/data_sources.json", (json.dumps(sources, indent=2) + "\n").encode())
    refs = plain_bundle / "paper" / "refs.bib"
    _add(plain_bundle, "paper/refs.bib", refs.read_bytes() + b"\n" + gmd.BIBTEX.encode() + b"\n")
    return plain_bundle


def _manifest(b: Path) -> dict:
    return json.loads((b / "e2er.json").read_text())


def _snapshot(b: Path) -> dict[str, bytes]:
    return {p.relative_to(b).as_posix(): p.read_bytes() for p in b.rglob("*") if p.is_file()}


def _states_terms(m: dict) -> None:
    entry = next(d for d in m["data"] if d["path"] == CSV)
    assert entry["source"] == "Global Macro Database (GMD), release 2026_09"
    assert gmd.TERMS_URL in entry["terms"] and entry["terms"].startswith("Holds data from the Global Macro")
    assert entry["citation"] == gmd.CITATION
    others = [d for d in m["data"] if d["path"] != CSV]
    assert others and all("terms" not in d for d in others)
    (load,) = m["dossier"]["doc"]["data_sources"]
    assert load["licence"] == gmd.LICENCE and load["citation"] == gmd.CITATION and load["terms"] == gmd.TERMS_URL


def test_private_gmd_data_publish_without_confirmation_and_state_the_terms(bundle: Path, tmp_path: Path, capsys):
    assert publish(str(bundle), **BASE, **REPO, data="private", out=str(tmp_path / "e")) == 0
    out = capsys.readouterr().out
    assert "uses Global Macro Database (GMD), release 2026_09 data (kept private)" in out
    assert "warning" not in out  # the paper cites the GMD
    # No nudge to publish data the GMD's terms keep: readers on e2er.org are sent to the source.
    assert "note: The data come from the Global Macro Database (GMD), whose terms do not allow passing them on" in out
    assert "--data public (with --data-url" not in out
    m = _manifest(bundle)
    assert m["availability"]["data"] == {"access": "private"}
    _states_terms(m)


def test_public_gmd_data_without_confirmation_are_refused_and_nothing_is_written(
    bundle: Path, tmp_path: Path, capsys, fake: FakeZenodo
):
    before = _snapshot(bundle)
    for extra in ({}, {"zenodo": True}, {"dry_run": True}, {"offline": True}):
        assert publish(str(bundle), **BASE, **REPO, data="public", out=str(tmp_path / "e"), **extra) == 1
        out = capsys.readouterr().out
        assert "error: the study uses Global Macro Database (GMD), release 2026_09 data" in out
        assert "To confirm, add --accept-data-terms gmd; to keep the data here, use --data private." in out
        assert _snapshot(bundle) == before
    assert fake.calls == []
    assert not (tmp_path / "e").exists()


def test_public_gmd_data_are_refused_before_anything_is_sent(bundle: Path, monkeypatch, capsys):
    sent: list = []
    monkeypatch.setattr(pc, "request", lambda *a, **k: sent.append(a) or (201, {}))
    monkeypatch.setattr(pc, "load_token", lambda base: "tok")
    before = _snapshot(bundle)
    assert publish(str(bundle), **BASE, **REPO, data="public", to_url="https://e2er.example") == 1
    assert "--accept-data-terms gmd" in capsys.readouterr().out
    assert sent == [] and _snapshot(bundle) == before


def test_confirmed_public_gmd_data_publish_and_state_the_terms(bundle: Path, tmp_path: Path, capsys):
    rc = publish(str(bundle), **BASE, **REPO, data="public", accept_data_terms=["gmd"], out=str(tmp_path / "e"))
    assert rc == 0
    assert "(published with the study)" in capsys.readouterr().out
    m = _manifest(bundle)
    assert m["availability"]["data"]["access"] == "public"
    _states_terms(m)


def test_unknown_terms_name_is_refused(bundle: Path, tmp_path: Path, capsys):
    rc = publish(str(bundle), **BASE, **REPO, data="public", accept_data_terms=["gdm"], out=str(tmp_path / "e"))
    assert rc == 1
    out = capsys.readouterr().out
    assert "--accept-data-terms gdm: e2er knows the terms of " in out and " only" in out
    assert "gmd" in out and "yfinance" in out
    assert not (bundle / "e2er.json").exists()


def test_a_zenodo_deposit_of_gmd_data_states_the_terms_under_a_non_commercial_licence(
    bundle: Path, tmp_path: Path, fake: FakeZenodo
):
    rc = publish(
        str(bundle),
        **BASE,
        **REPO,
        data="public",
        code="public",
        license_id="CC-BY-4.0",
        zenodo=True,
        accept_data_terms=["gmd"],
        out=str(tmp_path / "e"),
    )
    assert rc == 0
    data_meta, code_meta = fake.meta[101], fake.meta[102]
    assert data_meta["license"] == "other-nc"  # never the study's CC-BY-4.0
    assert "labelled as GMD data" in data_meta["description"] and "Do not re-host" in data_meta["description"]
    assert gmd.TERMS_URL in data_meta["description"] and gmd.CITATION in data_meta["description"]
    assert "Global Macro Database" in data_meta["keywords"]
    assert code_meta["license"] == "cc-by-4.0" and "GMD" not in code_meta["description"]


def test_the_dry_run_plan_names_the_gmd_licence(bundle: Path, fake: FakeZenodo, capsys):
    rc = publish(str(bundle), **BASE, **REPO, data="public", zenodo=True, dry_run=True, accept_data_terms=["gmd"])
    assert rc == 0
    err = capsys.readouterr().err
    assert "licence: other-nc" in err and "terms and citation of the Global Macro Database" in err
    assert fake.calls == []


@pytest.mark.parametrize(("answer", "rc"), [("y", 0), ("", 1), ("n", 1)])
def test_in_a_terminal_the_researcher_confirms_the_gmd_terms(
    bundle: Path, tmp_path: Path, monkeypatch, capsys, answer: str, rc: int
):
    asked: list[str] = []
    answers = iter(["public", "", answer])  # data public; code private; the GMD terms

    def ask(prompt: str) -> str:
        asked.append(prompt)
        return next(answers)

    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", ask)
    assert publish(str(bundle), **BASE, **REPO, out=str(tmp_path / "e")) == rc
    out = capsys.readouterr().out
    assert asked[-1] == "Publish the GMD data with the study under these terms? [y/N]: "
    assert "The data may not be republished anywhere else." in out and gmd.TERMS_URL in out
    assert (bundle / "e2er.json").exists() == (rc == 0)


def test_a_study_without_gmd_data_is_unaffected(plain_bundle: Path, tmp_path: Path, monkeypatch):
    asked: list[str] = []
    answers = iter(["public", ""])
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda p: asked.append(p) or next(answers))
    assert publish(str(plain_bundle), **BASE, **REPO, out=str(tmp_path / "e")) == 0
    assert len(asked) == 2
    m = _manifest(plain_bundle)
    assert all(set(d) == {"path", "sha256", "bytes"} for d in m["data"])
    assert "data_sources" not in m["dossier"]["doc"]


def test_a_missing_gmd_citation_is_named(bundle: Path, tmp_path: Path, capsys):
    refs = bundle / "paper" / "refs.bib"
    text = refs.read_text(encoding="utf-8").replace(gmd.BIBTEX, "")
    _add(bundle, "paper/refs.bib", text.encode())
    assert publish(str(bundle), **BASE, **REPO, data="private", out=str(tmp_path / "e")) == 0
    assert "warning: paper/refs.bib has no entry GMD2025" in capsys.readouterr().out


def test_a_gmd_publish_matches_the_sites_format(bundle: Path, monkeypatch):
    sent: list[dict] = []

    def server(base, method, path, token=None, body=None):
        sent.append(body)
        oid = body["manifest"]["id"]
        return 201, {"id": oid, "owner_project": oid, "version": 1, "study_url": "u", "dossier_url": "d"}

    monkeypatch.setattr(pc, "request", server)
    monkeypatch.setattr(pc, "load_token", lambda base: "tok")
    rc = publish(str(bundle), **BASE, **REPO, data="public", accept_data_terms=["gmd"], to_url="https://e2er.example")
    assert rc == 0 and len(sent) == 1
    manifest, d = sent[0]["manifest"], sent[0]["dossier"]
    jsonschema.Draft202012Validator(SCHEMA).validate(
        {**manifest, "dossier": {"id": d["id"], "url": manifest["dossier"]["url"], "doc": d["doc"]}}
    )
    entry = next(x for x in manifest["data"] if x["path"] == CSV)
    assert gmd.TERMS_URL in entry["terms"]
    assert d["doc"]["data_sources"][0]["licence"] == gmd.LICENCE
