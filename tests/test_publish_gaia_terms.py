"""e2er publish and Gaia data (CC BY-NC 3.0 IGO): the terms are stated and confirmed, never assumed.

Gaia's licence allows non-commercial use with credit. A study that loaded Gaia
rows publishes them only after the researcher confirms the terms
(--accept-data-terms gaia); the description names the licence on every file
holding Gaia rows; a Zenodo deposit of the data takes a non-commercial
licence, never the study's own.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.cli_publish import publish
from src.modules.data.sources import gaia
from tests.test_publish_access import BASE, REPO, FakeZenodo
from tests.test_publish_data_terms import _add, fake, plain_bundle  # noqa: F401 — fixtures

CSV = "data/pleiades.csv"


@pytest.fixture
def bundle(plain_bundle: Path) -> Path:  # noqa: F811
    """The showcase study with one Gaia cone saved as data/pleiades.csv, as `e2er-data gaia` records it."""
    load = {
        "connector": "gaia",
        "dataset": gaia.SOURCE.dataset,
        "version": "DR3",
        "series": "Gaia DR3 sources within 0.5 deg of RA 56.75, Dec 24.12, G < 11.0",
        "files": [{"url": f"{gaia.SERVICE}/sync?QUERY=x", "sha256": "b" * 64}],
        "licence": gaia.SOURCE.licence,
        "terms": gaia.SOURCE.terms_url,
        "terms_summary": gaia.SOURCE.terms_summary,
        "citation": gaia.CITATION,
        "cite_key": gaia.CITE_KEY,
        "request": {"command": "cone", "ra": 56.75, "dec": 24.12, "radius": 0.5, "max_mag": 11.0},
        "saved_to": CSV,
    }
    _add(plain_bundle, CSV, b"source_id,parallax\n1,7.3\n2,7.4\n")
    _add(plain_bundle, "data/data_sources.json", (json.dumps({"loads": [load]}, indent=2) + "\n").encode())
    refs = plain_bundle / "paper" / "refs.bib"
    _add(plain_bundle, "paper/refs.bib", refs.read_bytes() + b"\n" + gaia.BIBTEX.encode() + b"\n")
    return plain_bundle


def _manifest(b: Path) -> dict:
    return json.loads((b / "e2er.json").read_text())


def test_public_gaia_data_without_confirmation_are_refused(bundle: Path, tmp_path: Path, capsys):
    assert publish(str(bundle), **BASE, **REPO, data="public", out=str(tmp_path / "e")) == 1
    out = capsys.readouterr().out
    assert "ESA Gaia Data Release 3 (Gaia), release DR3" in out
    assert "--accept-data-terms gaia" in out
    assert not (bundle / "e2er.json").exists()


def test_confirmed_public_gaia_data_publish_and_state_the_licence(bundle: Path, tmp_path: Path, capsys):
    rc = publish(str(bundle), **BASE, **REPO, data="public", accept_data_terms=["gaia"], out=str(tmp_path / "e"))
    assert rc == 0, capsys.readouterr().out
    m = _manifest(bundle)
    entry = next(d for d in m["data"] if d["path"] == CSV)
    assert gaia.SOURCE.terms_url in entry["terms"] and entry["citation"] == gaia.CITATION
    (load,) = m["dossier"]["doc"]["data_sources"]
    assert "CC BY-NC 3.0 IGO" in load["licence"]


def test_a_zenodo_deposit_of_gaia_data_takes_a_non_commercial_licence(
    bundle: Path,
    tmp_path: Path,
    fake: FakeZenodo,  # noqa: F811
):
    rc = publish(
        str(bundle),
        **BASE,
        **REPO,
        data="public",
        code="public",
        license_id="CC-BY-4.0",
        zenodo=True,
        accept_data_terms=["gaia"],
        out=str(tmp_path / "e"),
    )
    assert rc == 0
    data_meta, code_meta = fake.meta[101], fake.meta[102]
    assert data_meta["license"] == "other-nc"  # never the study's CC-BY-4.0
    assert gaia.SOURCE.terms_url in data_meta["description"]
    assert code_meta["license"] == "cc-by-4.0"
