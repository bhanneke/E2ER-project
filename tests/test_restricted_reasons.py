"""Each source whose terms keep its data with it states its own reason; GitHub data need an open-access paper.

Björn, 2026-10-11 (from the template live runs): the generic sentence "its
terms do not allow passing the data on" is too strong for Gaia (CC BY-NC 3.0
IGO) and GISCO (non-commercial use). Each restricted source definition now
gives its own one-line reason, and the publish note, the finish page, the
confirmation, the README and the skill stub use it.

GitHub's Acceptable Use Policies (section 7) allow research use of public
non-personal information only if the resulting publications are open access,
so a study that used the `github` source is published with its paper public.
"""

# ruff: noqa: F811 — the fixtures imported from test_publish_data_terms are test parameters here
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.api import finish
from src.cli_publish import publish
from src.core import data_terms
from src.core.availability import reader_notes
from src.modules.data.sources import all_sources
from src.modules.data.sources.docs import readme_block, skill_stub
from tests.test_publish_access import BASE, REPO
from tests.test_publish_data_terms import _add, _manifest, _snapshot, plain_bundle  # noqa: F401

GENERIC = "do not allow passing the data on"

REASONS = {
    "yfinance": "allow personal use only",
    "gmd": "do not allow passing the data on outside the study's replication package",
    "gaia": "allow non-commercial use only, with credit to ESA/Gaia/DPAC (CC BY-NC 3.0 IGO)",
    "gisco": "allow non-commercial use only, with the notice '© EuroGeographics for the administrative boundaries' "
    "on every map",
    "who_gho": "allow use for public health purposes only, and no changes without WHO's written permission",
    "github": "grant no licence to redistribute the repository metadata",
}


def test_every_restricted_source_states_its_own_reason():
    restricted = {s.name: s for s in all_sources() if not s.redistribution}
    assert set(REASONS) <= set(restricted)
    for name, reason in REASONS.items():
        assert restricted[name].restricted.reason == reason, name
        t = data_terms.known()[name]
        # One reason for the publish note, the finish page and the confirmation.
        assert t.reason == t.limit == t.limit_finish == reason, name
    for name in ("gaia", "gisco", "github", "who_gho", "yfinance"):
        assert GENERIC not in data_terms.known()[name].reason


@pytest.mark.parametrize("name", ["gaia", "gisco"])
def test_non_commercial_sources_are_not_said_to_forbid_passing_the_data_on(name: str):
    t = data_terms.known()[name]
    notes = reader_notes(
        {"data": {"access": "private"}, "code": {"access": "public"}}, {"status": "public"}, [(t.the_short, t.limit)]
    )
    (note,) = [n for n in notes if n.startswith("The data come from")]
    assert "non-commercial use only" in note and "passing" not in note


def test_the_confirmation_and_the_refusal_carry_the_reason():
    use = data_terms.Use(data_terms.known()["gaia"], [], [])
    assert data_terms.terms_text(use).splitlines()[0] == (
        f"The study uses data from ESA Gaia Data Release 3 (Gaia). Its terms {REASONS['gaia']}:"
    )
    assert f"needs your confirmation of the Gaia terms ({REASONS['gaia']}):" in data_terms.refusal([use])


def test_the_readme_and_a_skill_stub_name_each_reason():
    sources = all_sources()
    block = readme_block(sources)
    for name, reason in REASONS.items():
        label = next(s.label for s in sources if s.name == name)
        assert f"- {label}: its terms {reason}." in block
    gaia = next(s for s in sources if s.name == "gaia")
    assert f"- The terms {REASONS['gaia']}: publishing asks" in skill_stub(gaia)
    readme = (Path(__file__).resolve().parent.parent / "README.md").read_text(encoding="utf-8")
    assert block in readme  # scripts/gen_sources.py has written it


# ── GitHub data: the paper must be open access ───────────────────────────────

CSV = "data/repos.csv"


def _add_github(b: Path) -> None:
    load = {
        "connector": "github",
        "operation": "search",
        "saved_to": CSV,
        "rows": 2,
        "retrieved_at": "2026-10-11T08:00:00Z",
    }
    _add(b, CSV, b"full_name,stars\nowner/a,1\nowner/b,2\n")
    path = b / "data" / "data_sources.json"
    sources = json.loads(path.read_text()) if path.is_file() else {"loads": []}
    sources["loads"].append(load)
    _add(b, "data/data_sources.json", (json.dumps(sources, indent=2) + "\n").encode())


@pytest.fixture
def bundle(plain_bundle: Path) -> Path:
    """The showcase study with one GitHub load saved as data/repos.csv."""
    _add_github(plain_bundle)
    return plain_bundle


def test_github_data_with_a_private_paper_are_refused_and_say_why(bundle: Path, tmp_path: Path, capsys):
    before = _snapshot(bundle)
    for extra in ({}, {"dry_run": True}, {"offline": True}, {"paper": "private"}):
        assert publish(str(bundle), **BASE, **REPO, out=str(tmp_path / "e"), **extra, yes=True) == 1
        out = capsys.readouterr().out
        assert "error: the study uses GitHub repository metadata. GitHub's Acceptable Use Policies" in out
        assert "Acceptable Use Policies (section 7" in out and "open access" in out
        assert "--paper public --paper-url <address of the PDF>" in out
        assert "Nothing was written or sent." in out
        assert _snapshot(bundle) == before


def test_github_data_with_a_public_paper_publish(bundle: Path, tmp_path: Path, capsys):
    rc = publish(
        str(bundle),
        **BASE,
        **REPO,
        paper="public",
        paper_url="https://example.org/paper.pdf",
        out=str(tmp_path / "e"),
        yes=True,
    )
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "uses GitHub repository metadata (GitHub) data (kept private)" in out
    assert f"whose terms {REASONS['github']}" in out
    assert _manifest(bundle)["access"] == {"status": "public", "pdf": "https://example.org/paper.pdf"}


def test_the_finish_page_states_the_open_access_rule(bundle: Path):
    (gh,) = finish._terms(bundle)
    assert gh["connector"] == "github" and "open access" in gh["open_access_why"]
    assert gh["reason"] == REASONS["github"]
    assert gh["reader_note"].endswith(f"its terms {REASONS['github']}.")
    others = [t for t in data_terms.known().values() if t.connector != "github"]
    assert all(not t.open_access_why for t in others)
