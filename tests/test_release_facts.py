"""scripts/release_facts.py: release-facts.json from the code, and the Zenodo version DOI filled in later."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load():
    name = "e2er_release_facts"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / "release_facts.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


rf = _load()


def test_the_format_is_fixed():
    """e2er.org reads this file; the keys and their order are the contract in docs/RELEASING.md."""
    doc = rf.facts(ROOT, tests=4213)
    assert list(doc) == ["version", "date", "tag_url", "concept_doi", "doi", "counts"]
    assert list(doc["counts"]) == ["templates", "specialists", "skills", "data_sources", "tests"]
    assert doc["concept_doi"] == "10.5281/zenodo.20187238" and doc["doi"] is None
    assert doc["tag_url"] == f"https://github.com/bhanneke/E2ER-project/releases/tag/v{doc['version']}"
    assert rf.validate(doc) == []
    docs = (ROOT / "docs" / "RELEASING.md").read_text()
    for key in [*doc, *doc["counts"]]:
        assert f'"{key}"' in docs


def test_the_counts_come_from_the_code():
    from src.core.specialists.data_sources import _connectors
    from src.core.specialists.registry import SPECIALIST_ARTIFACTS, SPECIALIST_SKILLS

    counts = rf.facts(ROOT, tests=1)["counts"]
    assert counts["templates"] == len(list((ROOT / "pipelines").glob("*.toml"))) > 0
    assert counts["skills"] == len(list((ROOT / "skills" / "files").rglob("*.md"))) > 0
    assert counts["specialists"] == len(set(SPECIALIST_ARTIFACTS) | set(SPECIALIST_SKILLS)) > 0
    assert counts["data_sources"] == len(_connectors()) > 0
    # The same number docs/SPECIALISTS.md states (it is generated from the registry too).
    assert f"**{counts['specialists']}** specialists" in (ROOT / "docs" / "SPECIALISTS.md").read_text()


def test_the_counts_agree_with_an_independent_count():
    """The test above repeats the script's own formulas, so a wrong formula passed it. These counts
    come another way: what git tracks, the source modules' own definitions, the README's generated
    table (written when the sources changed, not now)."""
    import re
    import subprocess

    counts = rf.facts(ROOT, tests=1)["counts"]

    def tracked(*specs: str) -> list[str]:
        out = subprocess.run(["git", "ls-files", "--", *specs], cwd=ROOT, capture_output=True, text=True)
        if out.returncode != 0:
            pytest.skip("not a git checkout")
        return [line for line in out.stdout.splitlines() if line]

    templates = tracked("pipelines/*.toml")
    assert counts["templates"] == len(templates), templates
    assert counts["skills"] == len([f for f in tracked("skills/files") if f.endswith(".md")])
    sources = (ROOT / "src/modules/data/sources").glob("*.py")
    defined = [p for p in sources if re.search(r"(?m)^SOURCE = Source\(", p.read_text())]
    assert counts["data_sources"] == len(defined) + 1  # + Allium, which is no kit source
    readme = (ROOT / "README.md").read_text()
    block = readme.split("<!-- sources:start -->", 1)[1].split("<!-- sources:end -->", 1)[0]
    rows = [line for line in block.splitlines() if line.startswith("| ") and not line.startswith("| Source |")]
    assert counts["data_sources"] == len(rows)
    assert f"on {counts['data_sources']} sources" in block


def test_version_and_date_are_the_release_script_s():
    doc = rf.facts(ROOT, tests=1)
    from src import __version__

    assert doc["version"] == __version__
    assert f'date-released: "{doc["date"]}"' in (ROOT / "CITATION.cff").read_text()


@pytest.mark.parametrize(
    ("line", "n"),
    [
        ("4213 tests collected in 9.12s", 4213),
        ("4200/4213 tests collected (13 deselected) in 9.12s", 4200),
        ("1 test collected in 0.01s", 1),
        ("no tests collected in 0.01s", 0),
    ],
)
def test_parse_collected(line: str, n: int):
    assert rf.parse_collected(f"tests/test_a.py::test_x\n\n{line}\n") == n


def test_parse_collected_without_a_count_fails():
    with pytest.raises(ValueError):
        rf.parse_collected("ERROR collecting tests/test_a.py\n")


def test_write_refuses_a_changed_format(tmp_path: Path):
    doc = rf.facts(ROOT, tests=1)
    bad = dict(doc, extra=1)
    with pytest.raises(ValueError, match="fixed format"):
        rf.write(bad, tmp_path / "f.json")
    with pytest.raises(ValueError):
        rf.write(dict(doc, counts={**doc["counts"], "tests": "many"}), tmp_path / "f.json")
    rf.write(doc, tmp_path / "f.json")
    assert json.loads((tmp_path / "f.json").read_text()) == doc


# ── the Zenodo version DOI (Zenodo's public records API, faked) ──────────────


def _record(recid: int, version: str) -> dict:
    return {
        "id": recid,
        "doi": f"10.5281/zenodo.{recid}",
        "conceptrecid": "20187238",
        "conceptdoi": "10.5281/zenodo.20187238",
        "metadata": {"version": version},
    }


class FakeZenodo:
    def __init__(self, latest: dict | None, listed: list[dict]) -> None:
        self.latest, self.listed, self.urls = latest, listed, []

    def __call__(self, url: str):
        self.urls.append(url)
        assert url.startswith("https://zenodo.org/api/records")
        if url.endswith("/records/20187238/versions/latest"):
            if self.latest is None:
                raise OSError("404")
            return self.latest
        return {"hits": {"hits": self.listed}}


def test_finds_the_version_named_like_the_tag():
    fake = FakeZenodo(_record(23535112, "v0.17.3"), [])
    assert rf.find_version_doi("0.17.3", fake) == "10.5281/zenodo.23535112"


def test_a_later_latest_version_is_not_taken():
    fake = FakeZenodo(_record(2, "v0.18.0"), [_record(2, "v0.18.0"), _record(1, "v0.17.3")])
    assert rf.find_version_doi("0.17.3", fake) == "10.5281/zenodo.1"
    assert rf.find_version_doi("0.16.1", fake) is None  # Zenodo made none for it: no DOI


def test_another_concept_or_the_concept_doi_is_never_taken():
    other = dict(_record(5, "v0.17.3"), conceptrecid="999")
    concept = dict(_record(20187238, "v0.17.3"))
    assert rf.find_version_doi("0.17.3", FakeZenodo(None, [other, concept])) is None


def test_waits_until_zenodo_has_it_then_fills_the_file(tmp_path: Path):
    path = tmp_path / "release-facts.json"
    doc = rf.facts(ROOT, tests=1)
    rf.write(doc, path)
    calls = {"n": 0}

    def fetch(url: str):
        calls["n"] += 1
        if calls["n"] < 5:  # two polls of two requests each find nothing
            return {"hits": {"hits": []}} if "versions" not in url else {}
        return _record(77, f"v{doc['version']}")

    now = [0.0]
    slept: list[float] = []

    def sleep(s: float) -> None:
        slept.append(s)
        now[0] += s

    got = rf.fill_doi(path, wait=1800, every=30, fetch=fetch, sleep=sleep, clock=lambda: now[0])
    assert got == "10.5281/zenodo.77" and slept == [30, 30]
    out = json.loads(path.read_text())
    assert out["doi"] == "10.5281/zenodo.77" and rf.validate(out) == []


def test_gives_up_after_the_wait_and_leaves_doi_null(tmp_path: Path):
    path = tmp_path / "release-facts.json"
    rf.write(rf.facts(ROOT, tests=1), path)
    now = [0.0]

    def sleep(s: float) -> None:
        now[0] += s

    got = rf.fill_doi(path, wait=120, every=30, fetch=FakeZenodo(None, []), sleep=sleep, clock=lambda: now[0])
    assert got is None and now[0] <= 120
    assert json.loads(path.read_text())["doi"] is None


def test_the_release_workflow_writes_and_attaches_the_file():
    wf = (ROOT / ".github" / "workflows" / "release.yml").read_text()
    assert "scripts/release_facts.py" in wf and "release-facts.json" in wf
    assert "release_facts.py zenodo-doi" in wf
    assert "scripts/release.py --check" in wf  # the version check is the release script's
