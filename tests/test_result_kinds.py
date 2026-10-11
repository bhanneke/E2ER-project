"""The discipline-neutral core (0.16.0): result contracts per kind, template-declared panels, skills.

A template names the kind of results it reports (``results``), whether it makes
a causal claim (``causal``), its persona (``base_skill``), its domain data
skills (``data_skills``) and its review panel with weights. Templates that say
none of this behave exactly as before; these tests hold both halves.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest

from src.core.pipeline import components
from src.core.pipeline.result_kinds import KINDS, RESULT_KINDS, active_kind, check_results, file_kind
from src.core.pipeline.spec import PipelineError, available, find_spec, load_spec, spec_from_dict
from src.core.specialists.contract_check import check_specialist_artifacts
from src.core.specialists.registry import (
    POLISH_SPECIALISTS,
    REVIEWER_SPECIALISTS,
    SPECIALIST_SKILLS,
)
from src.core.strategist.review_aggregator import ReviewScore, aggregate_reviews

ROOT = Path(__file__).resolve().parent.parent
SKILLS = ROOT / "skills" / "files"
EXO = ROOT / "tests" / "fixtures" / "replay" / "exoplanet"
DESCRIPTIVE = load_spec(ROOT / "pipelines" / "descriptive-study.toml")


def _schema_example(kind: str) -> dict:
    """The first JSON example of the kind's schema skill: the documentation is checked by the contract."""
    text = (SKILLS / "data" / f"{kind}-results-schema.md").read_text(encoding="utf-8")
    block = re.search(r"```json\n(.*?)```", text, re.DOTALL)
    assert block, kind
    return json.loads(block.group(1))


@pytest.fixture
def template():
    """Make a template the active one for the length of a test."""
    tokens = []

    def use(spec):
        tokens.append(components.activate(spec))
        return spec

    yield use
    for t in reversed(tokens):
        components.deactivate(t)


# ── each kind's contract ────────────────────────────────────────────────────


@pytest.mark.parametrize("kind", [k for k in RESULT_KINDS if k != "regression"])
def test_the_schema_skill_example_of_each_kind_meets_its_contract(kind: str):
    assert check_results(kind, _schema_example(kind)) == []


@pytest.mark.parametrize("kind", [k for k in RESULT_KINDS if k != "regression"])
def test_a_results_file_names_its_kind(kind: str):
    doc = _schema_example(kind)
    doc.pop("result_kind")
    assert any('"result_kind": "' + kind + '"' in p for p in check_results(kind, doc))
    assert check_results(kind, []) == ["the results file must be a JSON object"]


def test_the_regression_contract_is_not_this_module_s():
    """Regression keeps its own checks (coefficients, identified spec, t and p) in contract_check."""
    assert KINDS["regression"].check is None and check_results("regression", {}) == []
    assert KINDS["regression"].causal_by_default and not KINDS["descriptive"].causal_by_default


def _broken(kind: str, mutate) -> list[str]:
    doc = copy.deepcopy(_schema_example(kind))
    mutate(doc)
    return check_results(kind, doc)


def test_descriptive_contract_catches_missing_blocks_and_contradicting_numbers():
    assert any("sample.n_observations" in p for p in _broken("descriptive", lambda d: d.pop("sample")))
    assert any("'statistics'" in p for p in _broken("descriptive", lambda d: d.update(statistics={})))
    assert any("'distributions'" in p for p in _broken("descriptive", lambda d: d.pop("distributions")))
    assert any("'figures'" in p for p in _broken("descriptive", lambda d: d.update(figures=[])))

    def median_above_p75(d):
        d["statistics"]["radius_earth"]["median"] = 9.0

    assert any("median (9.0) is above p75" in p for p in _broken("descriptive", median_above_p75))

    def n_above_sample(d):
        d["statistics"]["radius_earth"]["n"] = 61

    assert any("exceeds sample.n_observations" in p for p in _broken("descriptive", n_above_sample))

    def counts_not_n(d):
        d["distributions"]["radius"]["n"] = 60  # the example shows two of its bins

    assert any("add up to 25, not to its n = 60" in p for p in _broken("descriptive", counts_not_n))

    def overlapping(d):
        d["distributions"]["radius"]["bins"][1]["lower"] = 0.8

    assert any("overlap" in p for p in _broken("descriptive", overlapping))

    def negative_sd(d):
        d["statistics"]["radius_earth"]["sd"] = -1

    assert any("sd is negative" in p for p in _broken("descriptive", negative_sd))


def test_timeseries_contract_catches_forecasts_outside_their_interval_and_impossible_errors():
    def outside(d):
        d["forecasts"]["arima_2025"]["points"][0]["forecast"] = 9.9

    assert any("lies outside" in p for p in _broken("timeseries", outside))

    def mae_above_rmse(d):
        d["out_of_sample"]["arima_test"]["mae"] = 2.0

    assert any("exceeds rmse" in p for p in _broken("timeseries", mae_above_rmse))

    def unknown_model(d):
        d["forecasts"]["arima_2025"]["model"] = "prophet"

    assert any("must name an entry of 'models'" in p for p in _broken("timeseries", unknown_model))

    def bad_level(d):
        d["forecasts"]["arima_2025"]["interval_level"] = 95

    assert any("interval_level" in p for p in _broken("timeseries", bad_level))
    assert any("'out_of_sample'" in p for p in _broken("timeseries", lambda d: d.pop("out_of_sample")))

    def horizon(d):
        d["forecasts"]["arima_2025"]["horizon"] = 12

    assert any("horizon 12 but 2 point(s)" in p for p in _broken("timeseries", horizon))


def test_spatial_contract_checks_morans_expectation_and_p_from_z():
    def expected(d):
        d["spatial_statistics"]["moran_unemployment"]["expected"] = -0.05

    assert any("-1/(n_units - 1)" in p for p in _broken("spatial", expected))

    def p_from_z(d):
        d["spatial_statistics"]["moran_unemployment"].update(z=1.0, p_value=0.05)

    assert any("does not follow from z" in p for p in _broken("spatial", p_from_z))

    def permutation(d):
        d["spatial_statistics"]["moran_unemployment"].update(z=1.0, p_value=0.05, p_value_method="permutation")

    assert _broken("spatial", permutation) == []
    assert any("'maps'" in p for p in _broken("spatial", lambda d: d.update(maps=[])))
    assert any(
        "weights" in p
        for p in _broken("spatial", lambda d: d["spatial_statistics"]["moran_unemployment"].pop("weights"))
    )


def test_text_contract_checks_frequencies_per_token():
    def per_10k(d):
        d["term_frequencies"]["all"]["terms"][1]["per_10k"] = 12.5

    assert any("per_10k 12.5" in p for p in _broken("text", per_10k))

    def types_above_tokens(d):
        d["corpus"]["n_types"] = d["corpus"]["n_tokens"] + 1

    assert any("n_types" in p for p in _broken("text", types_above_tokens))

    def too_many(d):
        d["term_frequencies"]["1850s"]["terms"][0]["count"] = 2_000_000

    assert any("more than its 1200000 tokens" in p for p in _broken("text", too_many))
    assert any("'models'" in p for p in _broken("text", lambda d: d.pop("models")))


def test_figures_named_by_the_results_must_be_in_figure_spec(tmp_path: Path):
    doc = _schema_example("descriptive")
    assert any("no readable figure_spec.json" in p for p in check_results("descriptive", doc, tmp_path))
    (tmp_path / "figure_spec.json").write_text(json.dumps({"figures": [{"filename": "fig_radius_period.pdf"}]}))
    assert check_results("descriptive", doc, tmp_path) == [
        "'figures' names fig_radius_hist.pdf, which figure_spec.json does not declare"
    ]


# ── the kind of a study ─────────────────────────────────────────────────────


def test_the_kind_comes_from_the_running_template_else_the_results_file(tmp_path: Path, template):
    assert active_kind(tmp_path) == "regression"
    (tmp_path / "estimation_results.json").write_text(json.dumps({"result_kind": "text", "corpus": {}}))
    assert file_kind(tmp_path) == "text" and active_kind(tmp_path) == "text"
    template(DESCRIPTIVE)
    assert active_kind(tmp_path) == "descriptive"


# ── the estimation contract dispatches on the kind ──────────────────────────


def _exoplanet_workspace(ws: Path) -> Path:
    files = EXO / "files"
    for rel in (
        "econometrics_specialist/estimation_results.json",
        "econometrics_specialist/econometric_spec.md",
        "econometrics_specialist/run_estimation.py",
        "data_analyst/figure_spec.json",
    ):
        (ws / Path(rel).name).write_bytes((files / rel).read_bytes())
    return ws


def test_a_descriptive_template_holds_the_analysis_to_its_contract_not_to_a_regression(tmp_path: Path, template):
    ws = _exoplanet_workspace(tmp_path)
    template(DESCRIPTIVE)
    checks = check_specialist_artifacts(ws, "econometrics_specialist")
    assert all(c.ok for c in checks), [c for c in checks if not c.ok]
    assert not any("regression" in c.reason for c in checks)

    results = json.loads((ws / "estimation_results.json").read_text())
    results["statistics"]["radius_earth"]["min"] = 99.0
    (ws / "estimation_results.json").write_text(json.dumps(results))
    failed = [c for c in check_specialist_artifacts(ws, "econometrics_specialist") if not c.ok]
    assert len(failed) == 1 and failed[0].kind == "verification"
    assert failed[0].reason.startswith("descriptive results contract: statistics.radius_earth: min (99.0) is above")
    assert "data/descriptive-results-schema" in failed[0].reason


def test_without_a_template_the_same_file_must_still_be_a_regression(tmp_path: Path):
    """Unchanged behaviour: no template, no result_kind -> the regression contract."""
    ws = _exoplanet_workspace(tmp_path)
    results = json.loads((ws / "estimation_results.json").read_text())
    results.pop("result_kind")
    (ws / "estimation_results.json").write_text(json.dumps(results))
    failed = [c for c in check_specialist_artifacts(ws, "econometrics_specialist") if not c.ok]
    assert [c.reason[:25] for c in failed] == ["no estimated regression: "]


def test_a_non_causal_regression_template_does_not_hold_main_to_an_identification(tmp_path: Path, template):
    spec = json.dumps({"primary": {"fixed_effects": ["unit"], "cluster_level": "unit"}})
    (tmp_path / "identification_spec.json").write_text(spec)
    (tmp_path / "econometric_spec.md").write_text("x" * 200)
    (tmp_path / "run_estimation.py").write_text("import json\n" + "# analysis\n" * 20)
    (tmp_path / "estimation_results.json").write_text(
        json.dumps({"assoc": {"coefficients": {"x": {"estimate": 1.0, "se": 0.5}}, "n_observations": 50}})
    )
    causal = [c for c in check_specialist_artifacts(tmp_path, "econometrics_specialist") if not c.ok]
    assert any("identified-spec contract" in c.reason for c in causal)
    raw = _template_dict(results="regression", causal=False)
    template(spec_from_dict(raw))
    loose = [c for c in check_specialist_artifacts(tmp_path, "econometrics_specialist") if not c.ok]
    assert not any("identified-spec contract" in c.reason for c in loose)


def test_identification_spec_is_required_only_in_a_causal_template(tmp_path: Path, template):
    (tmp_path / "identification_strategy.md").write_text("design " * 40)
    missing = [c for c in check_specialist_artifacts(tmp_path, "identification_strategist") if not c.ok]
    assert [c.artifact for c in missing] == ["identification_spec.json"]
    template(DESCRIPTIVE)
    assert all(c.ok for c in check_specialist_artifacts(tmp_path, "identification_strategist"))
    assert "identification_spec.json" not in components.sidecars_for("identification_strategist")


# ── the template file ───────────────────────────────────────────────────────


def _template_dict(**top) -> dict:
    return {
        "name": "t",
        **top,
        "steps": [
            {"kind": "strategist", "name": "initial"},
            {"kind": "aggregate", "name": "review", "run": ["data_reviewer", "methods_reviewer", "writing_reviewer"]},
        ],
    }


#: Shipped templates built on the discipline-neutral core: they change e2er's defaults on purpose.
NEUTRAL_TEMPLATES = {"descriptive-study", "time-series-forecasting"}


def test_every_shipped_template_keeps_e2er_s_defaults():
    for name in available(ROOT):
        if name in NEUTRAL_TEMPLATES:
            continue
        spec = find_spec(name, project=ROOT)
        assert spec.results == "regression" and spec.causal and spec.is_default_core(), name
        assert spec.base_skill == "base/economist" and spec.data_skills is None and spec.review_weights == {}
        if any(s.kind == "aggregate" for s in spec.steps):
            assert spec.panel() == REVIEWER_SPECIALISTS, name
        if spec.step("polish") is not None:
            assert spec.polish() == POLISH_SPECIALISTS, name


def test_shipped_templates_give_every_specialist_the_registry_s_skills():
    """The skills a run of an existing template reads are the registry's plus its own `[skills]`, as before."""
    for name in available(ROOT):
        if name in NEUTRAL_TEMPLATES:
            continue
        spec = find_spec(name, project=ROOT)
        for specialist, skills in SPECIALIST_SKILLS.items():
            want = list(dict.fromkeys([*skills, *spec.skills.get(specialist, ())]))
            assert components.skills_for(specialist, spec) == want, (name, specialist)


def test_the_descriptive_template_changes_the_persona_data_and_analysis_skills():
    s = components.skills_for
    assert "base/researcher" in s("idea_developer", DESCRIPTIVE)
    assert not any("economist" in x for sp in SPECIALIST_SKILLS for x in s(sp, DESCRIPTIVE))
    for sp in ("data_architect", "data_analyst"):
        assert not {"data/blockchain", "data/crypto-defi", "data/allium-cli"} & set(s(sp, DESCRIPTIVE))
        assert "data/fred" in s(sp, DESCRIPTIVE)  # general connectors stay
    analysis = s("econometrics_specialist", DESCRIPTIVE)
    assert "data/descriptive-results-schema" in analysis and "econometrics/did" not in analysis
    assert analysis[-1] == "methods/descriptive-analysis"  # the template's own [skills] come last
    assert "causal-inference/identification-spec-schema" not in s("identification_strategist", DESCRIPTIVE)
    assert DESCRIPTIVE.panel() == [
        "literature_reviewer",
        "writing_reviewer",
        "data_reviewer",
        "methods_reviewer",
        "plausibility_reviewer",
    ]
    assert DESCRIPTIVE.polish() == ["polish_numerics", "polish_bibliography"]


@pytest.mark.parametrize(
    ("top", "message"),
    [
        ({"results": "anova"}, "results must be one of"),
        ({"causal": "no"}, "causal must be true or false"),
        ({"base_skill": "base/astronomer"}, "base_skill: no skill"),
        ({"data_skills": ["data/nasa"]}, "data_skills: no skill"),
        ({"review_weights": {"mechanism_reviewer": 2}}, "not a reviewer of this template's panel"),
        ({"review_weights": {"data_reviewer": 0}}, "must be a positive number"),
    ],
)
def test_template_core_keys_are_checked_at_load(top: dict, message: str):
    with pytest.raises(PipelineError, match=message):
        spec_from_dict(_template_dict(**top))


def test_an_aggregate_step_runs_reviewers_only():
    raw = _template_dict()
    raw["steps"][1]["run"] = ["data_reviewer", "paper_drafter"]
    with pytest.raises(PipelineError, match="paper_drafter is not a reviewer"):
        spec_from_dict(raw)


def test_a_causal_claim_follows_the_kind_unless_stated():
    assert spec_from_dict(_template_dict()).causal
    assert not spec_from_dict(_template_dict(results="timeseries")).causal
    assert spec_from_dict(_template_dict(results="spatial", causal=True)).causal


def test_a_core_key_written_under_a_step_is_named_as_misplaced():
    raw = _template_dict()
    raw["steps"][1]["results"] = "descriptive"
    with pytest.raises(PipelineError, match="top-level setting"):
        spec_from_dict(raw)


# ── the panel's score ───────────────────────────────────────────────────────


def test_a_panel_without_a_mechanism_reviewer_is_scored_with_its_own_weights():
    panel = ["data_reviewer", "methods_reviewer", "writing_reviewer"]
    scores = [ReviewScore(r, s, "minor_revision") for r, s in zip(panel, (8.0, 6.0, 9.0), strict=True)]
    result = aggregate_reviews(scores, panel=panel, weights={"writing_reviewer": 2.0})
    assert result.rule_triggered == "Rule 3: weighted average"  # no "mechanism review missing"
    assert result.weighted_avg == pytest.approx((8 * 1.25 + 6 * 1.5 + 9 * 2.0) / (1.25 + 1.5 + 2.0))
    # The default panel still requires the mechanism review.
    assert aggregate_reviews([ReviewScore("data_reviewer", 9.0, "accept")]).rule_triggered == (
        "Rule 1: mechanism review missing"
    )


# ── what specialists are told ───────────────────────────────────────────────


def test_the_template_block_is_empty_for_e2er_s_defaults_and_names_the_contract_otherwise(template):
    from src.core.strategist.context import template_context

    assert template_context() == ""
    template(find_spec("empirical", project=ROOT))
    assert template_context() == ""
    template(DESCRIPTIVE)
    text = template_context()
    assert "descriptive statistics and distributions" in text and "do not dispatch identification_strategist" in text


def test_the_analysis_specialist_is_told_its_kind_of_results(template):
    from src.core.specialists.base import _build_system_prompt

    regression = _build_system_prompt("econometrics_specialist", "")
    assert "Headline estimate MUST be the IDENTIFIED specification" in regression
    template(DESCRIPTIVE)
    descriptive = _build_system_prompt("econometrics_specialist", "")
    assert "You are the Analysis specialist" in descriptive
    assert '"result_kind": "descriptive"' in descriptive and "IDENTIFIED specification" not in descriptive


def test_the_number_check_reads_the_files_of_the_kind(tmp_path: Path, template):
    from src.core.pipeline.verify_numbers import _SOURCE_JSON_FILES, source_files

    assert source_files(tmp_path) == _SOURCE_JSON_FILES
    template(DESCRIPTIVE)
    assert "field_map_results.json" not in source_files(tmp_path)
    assert "estimation_results.json" in source_files(tmp_path)
