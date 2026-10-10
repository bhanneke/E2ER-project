"""The `field-map` template: its steps on a workspace, the runner, the specialists' wiring, and the credit.

No network and no model: OpenAlex is the fake from test_fieldmap.py, and
specialists are replaced by functions that write their files.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from src.core.pipeline import fieldmap_checks as fc
from src.core.pipeline.spec import SCHEMA_PATH, PipelineError, find_spec, spec_from_dict
from src.core.pipeline.state import PipelineState
from src.core.specialists.contracts import Contribution
from src.core.strategist.state import GateHaltError
from src.modules.fieldmap import credit as fm_credit
from src.modules.fieldmap import workflow as wf
from src.modules.fieldmap.openalex import Client

from .test_fieldmap import WORKS, FakeOpenAlex, _work

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "pipelines" / "field-map.toml"
SKILL = ROOT / "skills" / "files" / "synthesis" / "main-path-analysis.md"
PID = "22345678-1234-1234-1234-123456789abc"
ARTICLE_URL = "https://www.linkedin.com/pulse/map-research-field-claude-main-path-analysis-step-michal-hron-jm2ge/"
ARTICLE_TITLE = "Map a research field with Claude: main path analysis, step by step"

# Two alternative boundaries: one journal (S9: works 2-6), one ending in 2005 (works 1-5).
SETS = {
    "S9": [w for w in WORKS if w["id"].endswith(("W2", "W3", "W4", "W5", "W6"))],
    "publication_year:<2006": WORKS[:5],
    "main path": WORKS,
}

BOUNDARY = {
    "main": {"query": '"main path"', "note": "the method's name"},
    "alternatives": [
        {"name": "journal", "query": '"main path"', "sources": ["S9"]},
        {"name": "to-2005", "query": '"main path"', "to_year": 2005},
    ],
}


@pytest.fixture
def fake(monkeypatch) -> FakeOpenAlex:
    f = FakeOpenAlex(SETS)

    def _from_settings(cache_dir, max_requests=300, **kw):
        return Client(cache_dir=cache_dir, fetch=f, pause_s=0, mailto="research@example.org")

    monkeypatch.setattr(Client, "from_settings", classmethod(lambda cls, *a, **k: _from_settings(*a, **k)))
    return f


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    w = tmp_path / "ws"
    w.mkdir()
    (w / "field_boundary.json").write_text(json.dumps(BOUNDARY))
    return w


def _lanes(ws: Path) -> None:
    ids = wf.mapped_ids(ws)
    half = len(ids) // 2
    (ws / "field_lanes.json").write_text(
        json.dumps(
            {
                "lanes": [
                    {"id": "early", "question": "Where did it start?", "papers": ids[:half]},
                    {"id": "late", "question": "Where did it go?", "papers": ids[half:]},
                ]
            }
        )
    )


def _computed(ws: Path) -> None:
    assert fc.field_retrieve(ws).passed
    assert fc.field_network(ws, min_papers=1).passed
    assert fc.field_main_path(ws, key_routes=2).passed
    assert fc.field_robustness(ws).passed


# ── the steps on a workspace ────────────────────────────────────────────────


def test_retrieval_writes_every_boundary_records_the_loads_and_reuses_them(ws: Path, fake: FakeOpenAlex):
    v = fc.field_retrieve(ws)
    assert v.passed and v.stats["boundaries"] == 3 and v.stats["main_papers"] == 7
    counts = json.loads((ws / "field_boundary_counts.json").read_text())
    assert [(b["name"], b["papers"]) for b in counts["boundaries"]] == [("main", 7), ("journal", 5), ("to-2005", 5)]
    assert "| main | 7 |" in (ws / "field_boundary_counts.md").read_text()
    loads = json.loads((ws / "data_sources.json").read_text())["loads"]
    assert len(loads) == 3 and {ld["connector"] for ld in loads} == {"openalex"}
    assert all("CC0" in ld["licence"] and "Priem" in ld["citation"] and ld["citation_by"] == "source" for ld in loads)
    sent = len(fake.calls)
    assert fc.field_retrieve(ws).passed and len(fake.calls) == sent  # unchanged boundaries: no request
    # An edited boundary is retrieved again; the others are not.
    b = json.loads((ws / "field_boundary.json").read_text())
    b["alternatives"][1]["to_year"] = 2004
    (ws / "field_boundary.json").write_text(json.dumps(b))
    fake.sets = {"publication_year:<2005": WORKS[:4], **fake.sets}
    assert fc.field_retrieve(ws).passed and len(fake.calls) == sent + 3  # count + two pages of 3


def test_a_boundary_file_with_mistakes_fails_retrieval_with_reasons(ws: Path, fake: FakeOpenAlex):
    (ws / "field_boundary.json").write_text(json.dumps({"main": {"query": "a, b"}, "alternatives": []}))
    v = fc.field_retrieve(ws)
    assert not v.passed and "commas" in v.reasons[0] and "2 to 6" in v.reasons[0]
    assert fake.calls == []


def test_the_network_check_stops_on_a_thin_network(ws: Path, fake: FakeOpenAlex):
    fc.field_retrieve(ws)
    v = fc.field_network(ws)  # min_papers 100 by default
    assert not v.passed and "fewer than 100" in v.reasons[0]
    v = fc.field_network(ws, min_papers=1, max_isolated_share=0.1)
    # W7 has no internal link: 1 of 7 = 14% > 10%.
    assert not v.passed and "14% of the papers have no internal citation link" in v.reasons[0]
    rep = json.loads((ws / "completeness_report.json").read_text())
    assert rep["passed"] is False and rep["papers_without_internal_links"] == 1
    assert fc.field_network(ws, min_papers=1).passed
    assert "Papers without internal links: 1" in (ws / "completeness_report.md").read_text()


def test_main_path_robustness_map_and_results(ws: Path, fake: FakeOpenAlex):
    _computed(ws)
    mp = json.loads((ws / "main_path.json").read_text())
    # W1>W2>W3>W5>W6 or via W4: computed and checked in test_fieldmap; here the files hold it.
    assert mp["global_main_path"]["papers"][0] == "W1" and mp["global_main_path"]["papers"][-1] == "W6"
    rob = json.loads((ws / "robustness.json").read_text())
    assert rob["boundary_count"] == 3 and rob["key_routes_k"] == 2
    assert not fc.field_map(ws).passed  # no lanes yet
    _lanes(ws)
    v = fc.field_map(ws)
    assert v.passed, v.reasons
    for f in (
        "figures/field_map.png",
        "figures/field_map.pdf",
        "figures/field_map.svg",
        "reading_list.csv",
        "reading_list.json",
        "exports/field_network.net",
        "exports/field_network.gexf",
        "exports/vosviewer_map.txt",
        "exports/vosviewer_network.txt",
        "exports/edges.csv",
        "tables/field_map_summary.tex",
        "tables/main_path_list.tex",
        "field_map_results.json",
    ):
        assert (ws / f).is_file() and (ws / f).stat().st_size > 0, f
    res = json.loads((ws / "field_map_results.json").read_text())
    assert res["boundary"]["papers"] == 7 and res["network"]["papers_without_internal_links"] == 1
    assert res["main_path"]["length"] == len(mp["global_main_path"]["papers"])
    assert res["robustness"]["boundary_count"] == 3 and res["lanes"]["count"] == 2
    bib = (ws / "literature.bib").read_text()
    assert all(f"{{{k}," in bib for k in fm_credit.METHOD_REFERENCES)
    assert fc.field_map(ws).passed and (ws / "literature.bib").read_text() == bib  # added once


@pytest.mark.parametrize(
    ("lanes", "match"),
    [
        ({"lanes": [{"question": "Only one?", "papers": ["W1"]}]}, "2 to 8"),
        (
            {"lanes": [{"question": "No question mark", "papers": ["W1"]}, {"question": "B?", "papers": ["W2"]}]},
            "ending with",
        ),
        (
            {"lanes": [{"question": "A?", "papers": ["W1", "W77"]}, {"question": "B?", "papers": ["W2"]}]},
            "W77 is not on the main path",
        ),
        ({"lanes": [{"question": "A?", "papers": ["W1"]}, {"question": "B?", "papers": ["W1"]}]}, "in two lanes"),
    ],
)
def test_lanes_that_break_the_contract_are_named(ws: Path, fake: FakeOpenAlex, lanes, match):
    _computed(ws)
    (ws / "field_lanes.json").write_text(json.dumps(lanes))
    assert any(match in p for p in wf.lanes_problems(ws)), wf.lanes_problems(ws)


def test_the_specialist_contracts_read_the_judgement_files(ws: Path, fake: FakeOpenAlex):
    from src.core.specialists.contract_check import check_specialist_artifacts

    (ws / "field_boundary.md").write_text("# Boundary\n" + "Why each term is in. " * 20)
    assert all(c.ok for c in check_specialist_artifacts(ws, "field_boundary_designer"))
    (ws / "field_boundary.json").write_text(json.dumps({"main": {"query": "x"}}))
    bad = [c for c in check_specialist_artifacts(ws, "field_boundary_designer") if not c.ok]
    assert bad and "alternatives" in bad[0].reason


def test_the_number_check_traces_the_summary_table(ws: Path, fake: FakeOpenAlex):
    _computed(ws)
    _lanes(ws)
    fc.field_map(ws)
    (ws / "paper_draft.tex").write_text(
        "\\title{A field}\n\\begin{abstract}x\\end{abstract}\n\\section{Map}\n\\input{tables/field_map_summary.tex}\n"
    )
    v = fc.draft_numbers(ws)
    # Eight rows; a zero count is not read as a table value.
    assert v.passed and v.stats["table_values"] >= 7 and v.stats["matched"] == v.stats["table_values"]
    (ws / "paper_draft.tex").write_text("\\section{Map} No table.\n")
    v = fc.draft_numbers(ws)
    assert not v.passed and "tables/field_map_summary.tex" in v.reasons[0]


def test_the_number_check_stops_a_value_the_results_do_not_hold(tmp_path: Path):
    (tmp_path / "field_map_results.json").write_text(json.dumps({"network": {"internal_links": 1637}}))
    (tmp_path / "paper_draft.tex").write_text(
        "\\begin{tabular}{lr}\n\\hline\n & Count \\\\\n\\hline\n"
        "Internal citation links & 1200 \\\\\n\\hline\n\\end{tabular}\n"
    )
    v = fc.draft_numbers(tmp_path)
    assert not v.passed and "1200 vs 1637" in v.reasons[0]


# ── the template and the runner ─────────────────────────────────────────────


def test_the_template_loads_in_the_order_of_a_field_map():
    spec = find_spec("field-map")
    assert spec.sequence_for("single_pass") == [
        "design_boundary",
        "retrieve_boundary",
        "review_boundary",
        "citation_network",
        "main_path",
        "robustness",
        "propose_lanes",
        "review_lanes",
        "draw_map",
        "write_review",
        "number_check",
        "citation_check",
        "review_draft",
    ]
    assert spec.sequence_for("iterative") == spec.sequence_for("single_pass")
    assert spec.checks() == [
        "citations",
        "contracts",
        "field_main_path",
        "field_map",
        "field_network",
        "field_retrieve",
        "field_robustness",
        "numbers",
    ]
    kinds = {s.kind for s in spec.steps}
    # Nothing is estimated: no strategist (which dispatches the econometrics specialist), no estimation gate,
    # no review panel.
    assert "strategist" not in kinds and "aggregate" not in kinds and "estimation" not in spec.checks()
    assert [s.name for s in spec.steps if s.kind == "researcher"] == ["review_boundary", "review_lanes", "review_draft"]
    assert spec.step("retrieve_boundary").resumable is False
    assert spec.step("main_path").settings == {"key_routes": 10}
    assert "e2er contributors" in TEMPLATE.read_text()


def test_the_template_validates_against_the_published_schema():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validators.validator_for(schema)(schema).validate(tomllib.loads(TEMPLATE.read_text(encoding="utf-8")))


@pytest.mark.parametrize(
    ("data", "match"),
    [
        (
            {"credit": [{"creator": "X", "role": "r", "relation": "based_on", "title": "T", "url": "https://x"}]},
            "no accessed",
        ),
        (
            {
                "credit": [
                    {
                        "creator": "X",
                        "role": "r",
                        "relation": "inspired",
                        "title": "T",
                        "url": "https://x",
                        "accessed": "2026-10-08",
                    }
                ]
            },
            "relation must be",
        ),
        (
            {
                "credit": [
                    {
                        "creator": "X",
                        "role": "r",
                        "relation": "cites",
                        "title": "T",
                        "url": "http://x",
                        "accessed": "2026-10-08",
                    }
                ]
            },
            "https",
        ),
        (
            {"steps": [{"kind": "gate", "name": "g", "check": "field_network", "settings": {"max_isolated_share": 2}}]},
            "share",
        ),
        ({"steps": [{"kind": "gate", "name": "g", "check": "field_main_path", "settings": {"k": 2}}]}, "no setting"),
    ],
)
def test_bad_credit_or_settings_fail_at_load(data, match):
    base = {"name": "t", "steps": [{"kind": "gate", "name": "g", "check": "field_map"}]}
    with pytest.raises(PipelineError, match=match):
        spec_from_dict({**base, **data})


def test_the_computation_steps_block_in_every_regime_and_the_network_check_can_be_shadowed():
    from src.core.governance import enforces

    for regime in ("off", "contracts", "full"):
        for check in ("field_retrieve", "field_main_path", "field_robustness", "field_map"):
            assert enforces(regime, check)
    assert enforces("full", "field_network") and not enforces("off", "field_network")


def _runner(ws: Path, governance: str = "full"):
    from src.core.strategist.runner import PipelineRunner

    r = PipelineRunner.__new__(PipelineRunner)
    r._paper_id = PID
    r._workspace = ws
    r._mode = "single_pass"
    r._spec = find_spec("field-map")
    r._triggers = []
    r._state = PipelineState(paper_id=PID, mode="single_pass")
    r._in_initial = False
    r._contributions = []
    r._governance = governance
    r._failure_counts = {}
    r._last_specialist_errors = {}
    r._backend = r._model = r._backend_name = None
    r._extra_tools, r._extra_handlers = [], []
    r._review_stages = set()
    return r


@pytest.fixture
def events(monkeypatch):
    log: list[tuple[str, str | None, dict]] = []

    async def _log_event(paper_id, kind, *, stage=None, payload=None, **kw):
        log.append((kind, stage, payload or {}))

    monkeypatch.setattr("src.db.events.log_event", _log_event)
    return log


async def test_the_network_check_halts_with_its_reasons_or_is_shadowed(ws: Path, fake, events):
    fc.field_retrieve(ws)
    r = _runner(ws)
    with pytest.raises(GateHaltError) as halt:
        await r._run_check_step(r._spec.step("citation_network"), r._state)
    assert halt.value.stage == "citation_network" and "fewer than 100" in halt.value.reasons[0]
    assert r._state.metadata["review"]["files"] == [
        "field_boundary.json",
        "completeness_report.md",
        "completeness_report.json",
    ]
    off = _runner(ws, governance="off")
    await off._run_check_step(off._spec.step("citation_network"), off._state)  # recorded, not blocking
    assert [(k, s, p["passed"]) for k, s, p in events] == [
        ("gate_enforced", "field_network", False),
        ("gate_shadow", "field_network", False),
    ]


async def test_retrieval_failure_blocks_even_with_governance_off(ws: Path, fake, events):
    (ws / "field_boundary.json").unlink()
    r = _runner(ws, governance="off")
    with pytest.raises(GateHaltError):
        await r._run_check_step(r._spec.step("retrieve_boundary"), r._state)
    assert events[0][:2] == ("gate_enforced", "field_retrieve")


async def test_the_run_stops_at_the_boundary_review_with_the_counts(ws: Path, fake, events, monkeypatch):
    (ws / "field_boundary.json").unlink()
    sent: list[Any] = []

    async def _exec(orders, *a, **k):
        sent.extend(orders)
        (ws / "field_boundary.json").write_text(json.dumps(BOUNDARY))
        (ws / "field_boundary.md").write_text("# Boundary\n" + "x" * 200)
        return [Contribution(paper_id=PID, specialist=o.specialist, output="", success=True) for o in orders]

    async def _noop(*a, **k):
        return None

    monkeypatch.setattr("src.core.strategist.runner.execute_with_dependencies", _exec)
    monkeypatch.setattr("src.modules.tracking.usage.check_budget", _noop)
    r = _runner(ws)
    r._update_status = _noop
    r._best_effort_finalize = _noop
    r._max_cost_usd = 5.0
    r._pivot_count = r._iteration = 0
    r._deep_revision_count = 0
    r._in_memory_spent = lambda: 0.0
    monkeypatch.setattr("src.core.pipeline.state.PipelineState.load", classmethod(lambda cls, *a: r._state))
    monkeypatch.setattr("src.core.pipeline.state.PipelineState.save", lambda self, ws: None)
    out = await r.run()
    assert out["status"] == "paused" and out["stage"] == "review_boundary"
    assert [o.specialist for o in sent] == ["field_boundary_designer"]
    assert "e2er-fieldmap count" in sent[0].focus and "older names" in sent[0].focus
    assert r._state.metadata["review"]["files"] == [
        "field_boundary.json",
        "field_boundary.md",
        "field_boundary_counts.md",
    ]
    assert (ws / "field_boundary_counts.md").is_file() and not (ws / "completeness_report.json").exists()
    assert ("gate_enforced", "field_retrieve", True) in [(k, s, p.get("passed")) for k, s, p in events]


def test_the_specialists_are_registered_with_the_skill_and_the_command():
    from src.core.specialists.registry import (
        SPECIALIST_ARTIFACTS,
        SPECIALIST_DEFAULT_FOCUS,
        SPECIALIST_NEEDS,
        SPECIALIST_SIDECAR_ARTIFACTS,
        SPECIALIST_SKILLS,
    )
    from src.modules.llm.claude_code import allowed_tools_for

    for name in ("field_boundary_designer", "field_lane_mapper", "field_review_writer"):
        assert name in SPECIALIST_ARTIFACTS and name in SPECIALIST_DEFAULT_FOCUS
        assert "synthesis/main-path-analysis" in SPECIALIST_SKILLS[name]
        assert "Bash(e2er-fieldmap:*)" in allowed_tools_for(name)
    assert "Bash(e2er-fieldmap:*)" not in allowed_tools_for("econometrics_specialist")
    assert SPECIALIST_SIDECAR_ARTIFACTS["field_lane_mapper"] == ["field_lanes.json"]
    assert SPECIALIST_NEEDS["field_review_writer"] == ("field_lane_mapper",)
    focus = SPECIALIST_DEFAULT_FOCUS["field_review_writer"]
    for key in fm_credit.METHOD_REFERENCES:
        assert key in focus
    assert "field_map_results.json" in focus and "\\input{tables/field_map_summary.tex}" in focus


def test_the_command_is_installed_and_wrapped():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert pyproject["project"]["scripts"]["e2er-fieldmap"] == "src.modules.fieldmap.cli:main"
    assert "src.modules.fieldmap.cli" in (ROOT / "scripts" / "e2er-fieldmap").read_text()


def test_the_command_runs_the_same_steps(ws: Path, fake: FakeOpenAlex, capsys):
    from src.modules.fieldmap.cli import main

    assert main(["--workspace", str(ws), "boundary"]) == 0
    assert main(["--workspace", str(ws), "network"]) == 1  # 7 papers < 100
    assert "fewer than 100" in capsys.readouterr().out
    assert main(["--workspace", str(ws), "network", "--min-papers", "1"]) == 0
    assert main(["--workspace", str(ws), "mainpath", "--key-routes", "2"]) == 0
    assert main(["--workspace", str(ws), "robustness"]) == 0
    capsys.readouterr()
    assert main(["--workspace", str(ws), "papers", "--abstracts"]) == 0
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert rows and all("abstract" in r for r in rows)
    assert main(["--workspace", str(ws), "export"]) == 0  # no lanes needed
    assert (ws / "figures" / "field_map.png").is_file()


def test_a_work_without_metadata_still_parses():
    from src.modules.fieldmap.openalex import parse_work

    w = _work(9, [], 2009)
    w.update({"primary_location": None, "authorships": None, "doi": None, "abstract_inverted_index": None})
    p = parse_work(w)
    assert p["journal"] == "" and p["authors"] == [] and p["doi"] == "" and p["abstract"] == ""


# ── credit ──────────────────────────────────────────────────────────────────


def _toml_credit() -> list[dict[str, Any]]:
    return tomllib.loads(TEMPLATE.read_text(encoding="utf-8"))["credit"]


def test_the_template_credits_the_article_it_is_based_on():
    based = [c for c in _toml_credit() if c["relation"] == "based_on"]
    assert len(based) == 1
    c = based[0]
    assert c["creator"] == "Michal Hron" and c["role"] == "conceptualization" and c["kind"] == "article"
    assert c["title"] == ARTICLE_TITLE and c["publisher"] == "LinkedIn Pulse"
    assert c["url"] == ARTICLE_URL and c["published"] == "2026-10-08" and c["accessed"] == "2026-10-08"
    assert c["found_via"] == "shared by Björn Hanneke"
    assert "independent and uses OpenAlex" in c["statement"] and c["adopted"] and c["own"]
    # The module's copy says the same.
    for key in ("creator", "role", "relation", "title", "publisher", "published", "url", "accessed", "found_via"):
        assert fm_credit.WORKFLOW_SOURCE[key] == c[key], key
    assert fm_credit.STATEMENT == c["statement"] and fm_credit.ADOPTED == c["adopted"] and fm_credit.OWN == c["own"]
    # No wording that suggests endorsement.
    text = json.dumps(_toml_credit()).lower()
    assert "endorse" not in text and "approved by" not in text and "in collaboration" not in text


def test_the_methods_are_cited_with_verified_dois_everywhere():
    dois = {v["doi"] for v in fm_credit.METHOD_REFERENCES.values()}
    assert dois == {"10.1016/0378-8733(89)90017-8", "10.48550/arXiv.cs/0309023", "10.1002/asi.21692"}
    cited = {c["url"].removeprefix("https://doi.org/") for c in _toml_credit() if c["relation"] == "cites"}
    assert cited == dois
    skill = SKILL.read_text(encoding="utf-8")
    for doi in dois:
        assert doi in skill
    assert {c.get("cite_key") for c in _toml_credit() if c["relation"] == "cites"} == set(fm_credit.METHOD_REFERENCES)


def test_the_catalogue_file_carries_the_same_credit():
    doc = json.loads((ROOT / "credits.json").read_text(encoding="utf-8"))
    assert doc["parts"]["template:field-map"] == _toml_credit()
    assert doc["parts"]["skill:e2er/synthesis/main-path-analysis"][0]["url"] == ARTICLE_URL
    for entries in doc["parts"].values():
        for c in entries:
            assert c["url"].startswith("https://") and re.match(r"^\d{4}-\d{2}-\d{2}$", c["accessed"])


def test_the_credit_shows_in_the_skill_readme_and_changelog():
    skill = SKILL.read_text(encoding="utf-8")
    assert ARTICLE_URL in skill and ARTICLE_TITLE in skill and "independent and uses OpenAlex" in skill
    assert "shared by Björn Hanneke" in skill and "github.com/michalhron/scopus-plus-mcp" in skill
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "field-map" in readme and ARTICLE_URL in readme and "Hron" in readme
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    # The entry moves from [Unreleased] to a release heading when e2er is released, so check the whole file.
    assert "field-map" in changelog and "Hron" in changelog and ARTICLE_URL in changelog
    assert ARTICLE_URL in TEMPLATE.read_text(encoding="utf-8")


def test_the_study_bundle_carries_the_field_map(ws: Path, fake: FakeOpenAlex, tmp_path: Path):
    from src.core.export.structured import export_paper

    _computed(ws)
    _lanes(ws)
    assert fc.field_map(ws).passed
    (ws / "manifest.json").write_text(json.dumps({"title": "A field map"}))
    out = export_paper(ws, tmp_path / "out", date_str="2026-10-08", slug="study")
    for rel in (
        "results/field_map_results.json",
        "results/main_path.md",
        "results/robustness.json",
        "results/completeness_report.json",
        "results/reading_list.csv",
        "results/exports/field_network.gexf",
        "results/exports/field_network.net",
        "results/figures/field_map.png",
        "paper/tables/field_map_summary.tex",
        "design/field_boundary.json",
        "design/field_lanes.json",
        "data/fieldmap/main.json",
        "data/data_sources.json",
    ):
        assert (out / rel).is_file(), rel
    assert not list(out.rglob("cache"))


def test_the_completeness_stops_agree_everywhere_and_match_the_calibration():
    """50% without internal links and 40% without references (calibrated on five boundaries, 2026-10-10)."""
    import inspect

    from src.core.pipeline import fieldmap_checks
    from src.core.pipeline.spec import find_spec
    from src.modules.fieldmap import cli, workflow

    want = {"max_isolated_share": 0.5, "max_missing_refs_share": 0.4, "min_papers": 100}
    for fn in (workflow.network_step, fieldmap_checks.field_network):
        params = inspect.signature(fn).parameters
        assert {k: params[k].default for k in want} == want, fn
    assert dict(find_spec("field-map").step("citation_network").settings) == want
    source = inspect.getsource(cli.main)
    assert '"--max-isolated-share", type=float, default=0.5)' in source
    assert '"--max-missing-refs-share", type=float, default=0.4)' in source
