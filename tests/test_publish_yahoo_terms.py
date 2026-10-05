"""e2er publish and Yahoo Finance data (`e2er-data yfinance`), whose terms allow personal use only.

Björn, 2026-10-05: Yahoo Finance data get the GMD's treatment. Readers on
e2er.org see a link to the source instead of a request button, and there is no
nudge to publish the data. Publishing them with the study needs a confirmation
that says Yahoo allows personal use only; a Zenodo deposit of the data is
refused, because no Zenodo licence fits "personal use only". Yahoo publishes no
citation format, so no BibTeX key is asked for.
"""

# ruff: noqa: F811 — the fixtures imported from test_publish_data_terms are test parameters here
from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from src.cli_publish import publish
from src.core import data_terms
from src.core import platform_client as pc
from src.core.availability import reader_notes
from src.modules.data.load_record import YFINANCE, yfinance_load
from tests.test_publish_access import BASE, REPO, FakeZenodo
from tests.test_publish_data_terms import CSV as GMD_CSV
from tests.test_publish_data_terms import SCHEMA, _add, _manifest, _snapshot, fake, plain_bundle  # noqa: F401
from tests.test_publish_data_terms import bundle as gmd_bundle  # noqa: F401

CSV = "data/btc_prices.csv"
NOTE = (
    "note: The data come from Yahoo Finance, whose terms allow personal use only, "
    "so readers on e2er.org see a link to the source instead of a request button."
)


def _add_yahoo(b: Path) -> None:
    load = {**yfinance_load("BTC-USD", "2026-10-05T08:00:00Z"), "saved_to": CSV, "rows": 2}
    _add(b, CSV, b"Date,Close\n2026-10-01,1.0\n2026-10-02,2.0\n")
    path = b / "data" / "data_sources.json"
    sources = json.loads(path.read_text()) if path.is_file() else {"loads": []}
    sources["loads"].append(load)
    _add(b, "data/data_sources.json", (json.dumps(sources, indent=2) + "\n").encode())


@pytest.fixture
def bundle(plain_bundle: Path) -> Path:
    """The showcase study with one Yahoo Finance load saved as data/btc_prices.csv."""
    _add_yahoo(plain_bundle)
    return plain_bundle


def _states_terms(m: dict) -> None:
    entry = next(d for d in m["data"] if d["path"] == CSV)
    assert entry["source"] == "Yahoo Finance"
    assert entry["terms"] == f"Holds data from Yahoo Finance, used under its terms. {YFINANCE.licence}"
    assert "personal use only" in entry["terms"]
    assert "citation" not in entry  # Yahoo publishes no citation format
    (load,) = m["dossier"]["doc"]["data_sources"]
    assert load["connector"] == "yfinance" and load["terms"] == YFINANCE.terms_url


def test_yahoo_is_a_source_with_terms_taken_from_the_load_record():
    t = data_terms.known()["yfinance"]
    assert t.terms_url == YFINANCE.terms_url and t.licence == YFINANCE.licence
    assert " ".join(t.plain) == YFINANCE.terms_summary
    assert t.zenodo_licence is None and t.cite_key is None and t.citation == ""


def test_private_yahoo_data_publish_with_a_link_to_the_source_and_no_nudge(bundle: Path, tmp_path: Path, capsys):
    refs = bundle / "paper" / "refs.bib"
    assert "yahoo" not in refs.read_text(encoding="utf-8").lower()
    assert publish(str(bundle), **BASE, **REPO, data="private", out=str(tmp_path / "e")) == 0
    out = capsys.readouterr().out
    assert "note: the study uses Yahoo Finance data (kept private); the description states its terms\n" in out
    assert NOTE in out
    assert "--data public (with --data-url" not in out
    assert "warning: paper/refs.bib" not in out  # no cite key to demand
    m = _manifest(bundle)
    assert m["availability"]["data"] == {"access": "private"}
    _states_terms(m)


def test_public_yahoo_data_without_confirmation_are_refused_and_say_personal_use_only(
    bundle: Path,
    tmp_path: Path,
    capsys,
    fake: FakeZenodo,
):
    before = _snapshot(bundle)
    for extra in ({}, {"dry_run": True}, {"offline": True}):
        assert publish(str(bundle), **BASE, **REPO, data="public", out=str(tmp_path / "e"), **extra) == 1
        out = capsys.readouterr().out
        assert (
            "error: the study uses Yahoo Finance data. Publishing them with the study (--data public) "
            f"needs your confirmation of the Yahoo Finance terms: {YFINANCE.terms_url}\n"
            "  Yahoo's terms allow personal use only.\n"
        ) in out
        assert "To confirm, add --accept-data-terms yfinance; to keep the data here, use --data private." in out
        assert _snapshot(bundle) == before
    assert fake.calls == []


def test_confirmed_public_yahoo_data_publish(bundle: Path, tmp_path: Path, capsys):
    rc = publish(str(bundle), **BASE, **REPO, data="public", accept_data_terms=["yfinance"], out=str(tmp_path / "e"))
    assert rc == 0
    out = capsys.readouterr().out
    assert "uses Yahoo Finance data (published with the study)" in out
    assert "whose terms allow personal use only" not in out  # the data are public: no reader note
    m = _manifest(bundle)
    assert m["availability"]["data"]["access"] == "public"
    _states_terms(m)


@pytest.mark.parametrize("extra", [{"zenodo": True}, {"zenodo": True, "dry_run": True}])
def test_a_zenodo_deposit_of_yahoo_data_is_refused_before_anything_is_sent(
    bundle: Path,
    tmp_path: Path,
    capsys,
    fake: FakeZenodo,
    extra: dict,
):
    before = _snapshot(bundle)
    rc = publish(
        str(bundle),
        **BASE,
        **REPO,
        data="public",
        code="public",
        accept_data_terms=["yfinance"],
        out=str(tmp_path / "e"),
        **extra,
    )
    assert rc == 1
    out = capsys.readouterr().out
    assert (
        "error: e2er does not deposit Yahoo Finance data on Zenodo: Yahoo's terms allow personal use only, "
        "and a Zenodo deposit republishes the data for anyone to reuse.\n"
        "  Nothing was written or sent.\n"
        "  To deposit the code alone, use --data private; to publish the data with the study, "
        "give --data-url and leave out --zenodo."
    ) in out
    assert fake.calls == [] and _snapshot(bundle) == before


def test_the_code_alone_goes_to_zenodo_when_the_yahoo_data_stay_private(
    bundle: Path,
    tmp_path: Path,
    fake: FakeZenodo,
):
    rc = publish(str(bundle), **BASE, **REPO, data="private", code="public", zenodo=True, out=str(tmp_path / "e"))
    assert rc == 0
    (meta,) = fake.meta.values()
    assert meta["upload_type"] == "software" and "Yahoo" not in meta["description"]


@pytest.mark.parametrize(("answer", "rc"), [("y", 0), ("", 1)])
def test_in_a_terminal_the_researcher_confirms_knowing_yahoo_allows_personal_use_only(
    bundle: Path, tmp_path: Path, monkeypatch, capsys, answer: str, rc: int
):
    asked: list[str] = []
    answers = iter(["public", "", answer])

    def ask(prompt: str) -> str:
        asked.append(prompt)
        return next(answers)

    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", ask)
    assert publish(str(bundle), **BASE, **REPO, out=str(tmp_path / "e")) == rc
    out = capsys.readouterr().out
    assert asked[-1] == (
        "Publish the Yahoo Finance data with the study although Yahoo's terms allow personal use only? [y/N]: "
    )
    assert "The study uses data from Yahoo Finance. Its terms:" in out
    assert "  - Yahoo's terms of use apply.\n" in out
    assert "intended for personal use only" in out and YFINANCE.terms_url in out
    assert "Citation:" not in out
    assert (bundle / "e2er.json").exists() == (rc == 0)


def test_gmd_and_yahoo_data_name_both_sources(gmd_bundle: Path, tmp_path: Path, capsys):
    _add_yahoo(gmd_bundle)
    assert publish(str(gmd_bundle), **BASE, **REPO, data="public", out=str(tmp_path / "e")) == 1
    out = capsys.readouterr().out
    assert "--accept-data-terms gmd, yfinance;" in out
    assert publish(str(gmd_bundle), **BASE, **REPO, data="private", out=str(tmp_path / "e")) == 0
    out = capsys.readouterr().out
    assert (
        "note: The data come from the Global Macro Database (GMD), whose terms do not allow passing them on "
        "outside the study's replication package, and Yahoo Finance, whose terms allow personal use only, "
        "so readers on e2er.org see links to the sources instead of a request button."
    ) in out
    m = _manifest(gmd_bundle)
    assert next(d for d in m["data"] if d["path"] == GMD_CSV)["source"].startswith("Global Macro Database (GMD)")
    assert next(d for d in m["data"] if d["path"] == CSV)["source"] == "Yahoo Finance"


def test_reader_notes_take_each_source_s_own_terms():
    av = {"data": {"access": "private"}, "code": {"access": "public"}}
    (note,) = reader_notes(
        av, {"status": "public", "pdf": "https://x/p.pdf"}, [("Yahoo Finance", "allow personal use only")]
    )
    assert note == NOTE.removeprefix("note: ")


def test_a_yahoo_table_in_the_data_dictionary_counts(tmp_path: Path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "data.db").write_bytes(b"x")
    (tmp_path / "data" / "data_dictionary.json").write_text(json.dumps({"tables": [{"source": "yfinance"}]}))
    (use,) = data_terms.uses(tmp_path)
    assert use.terms.connector == "yfinance" and use.files == ["data/data.db"] and use.label == "Yahoo Finance"


def test_a_yahoo_publish_matches_the_sites_format(bundle: Path, monkeypatch):
    sent: list[dict] = []

    def server(base, method, path, token=None, body=None):
        sent.append(body)
        oid = body["manifest"]["id"]
        return 201, {"id": oid, "owner_project": oid, "version": 1, "study_url": "u", "dossier_url": "d"}

    monkeypatch.setattr(pc, "request", server)
    monkeypatch.setattr(pc, "load_token", lambda base: "tok")
    assert publish(str(bundle), **BASE, **REPO, data="private", to_url="https://e2er.example") == 0
    manifest, d = sent[0]["manifest"], sent[0]["dossier"]
    jsonschema.Draft202012Validator(SCHEMA).validate(
        {**manifest, "dossier": {"id": d["id"], "url": manifest["dossier"]["url"], "doc": d["doc"]}}
    )


def test_a_file_holding_gmd_and_yahoo_data_names_both(tmp_path: Path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "data.db").write_bytes(b"x")
    tables = {"tables": [{"source": "gmd", "version": "2025_09"}, {"source": "yfinance"}]}
    (tmp_path / "data" / "data_dictionary.json").write_text(json.dumps(tables))
    manifest = {"data": [{"path": "data/data.db", "sha256": "0" * 64, "bytes": 1}]}
    data_terms.annotate(manifest, data_terms.uses(tmp_path))
    (entry,) = manifest["data"]
    assert entry["source"] == "Global Macro Database (GMD), release 2025_09; Yahoo Finance"
    assert entry["terms"].startswith("Holds data from the Global Macro Database (GMD), release 2025_09, used under")
    assert " Holds data from Yahoo Finance, used under its terms. Yahoo terms of service" in entry["terms"]
    assert entry["citation"] == data_terms.known()["gmd"].citation
