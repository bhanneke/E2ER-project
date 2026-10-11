"""The checks of the descriptive and time-series templates, case by case (no server, no model).

data_quality and figure_data: src/core/pipeline/data_quality.py.
forecast_design and forecast_evaluation: src/core/pipeline/forecast_checks.py.
The templates themselves: pipelines/descriptive-study.toml, pipelines/time-series-forecasting.toml.
"""

from __future__ import annotations

import copy
import json
import shutil
import sqlite3
import tomllib
from pathlib import Path

import pytest

from src.core.pipeline.data_quality import check_data_quality, check_figure_data
from src.core.pipeline.forecast_checks import (
    FREEZE_FILE,
    check_forecast_design,
    check_forecast_evaluation,
)
from src.core.pipeline.spec import PipelineError, find_spec, load_spec, spec_from_dict

ROOT = Path(__file__).resolve().parents[1]
EXO = ROOT / "tests" / "fixtures" / "replay" / "exoplanet" / "files"
CLIMATE = ROOT / "tests" / "fixtures" / "replay" / "climate" / "files"


def _write(path: Path, doc: object) -> None:
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")


# ── the data check ──────────────────────────────────────────────────────────


@pytest.fixture
def exo(tmp_path: Path) -> Path:
    for f in ("data_architect/data_dictionary.json", "data_analyst/data.db", "data_analyst/figure_spec.json"):
        shutil.copy(EXO / f, tmp_path)
    shutil.copy(EXO / "econometrics_specialist" / "estimation_results.json", tmp_path)
    return tmp_path


def _dictionary(ws: Path) -> dict:
    return json.loads((ws / "data_dictionary.json").read_text(encoding="utf-8"))


def test_clean_data_pass_and_the_report_lists_every_column(exo: Path):
    r = check_data_quality(exo)
    assert r.passed, r.reasons
    report = json.loads((exo / "data_quality.json").read_text(encoding="utf-8"))
    assert set(report["tables"]["exoplanets"]["columns"]) == {
        "planet",
        "period_days",
        "radius_earth",
        "discovery_method",
        "discovery_year",
    }
    assert report["tables"]["exoplanets"]["coverage"]["found"] == [2009, 2024]


def test_a_numeric_column_without_a_unit_stops_the_run(exo: Path):
    d = _dictionary(exo)
    del d["tables"][0]["columns"][2]["unit"]
    _write(exo / "data_dictionary.json", d)
    r = check_data_quality(exo)
    assert not r.passed and "radius_earth have no unit" in r.reasons[0]


def test_duplicate_rows_stop_the_run(exo: Path):
    con = sqlite3.connect(exo / "data.db")
    con.execute("INSERT INTO exoplanets SELECT * FROM exoplanets LIMIT 3")
    con.commit()
    con.close()
    r = check_data_quality(exo)
    assert not r.passed and any("3 of 63 rows repeat on the key (planet)" in x for x in r.reasons)


def test_missing_values_need_a_reason_above_the_threshold(exo: Path):
    con = sqlite3.connect(exo / "data.db")
    con.execute("UPDATE exoplanets SET radius_earth = NULL WHERE rowid <= 6")
    con.commit()
    con.close()
    r = check_data_quality(exo)
    assert not r.passed and any("radius_earth (6 of 60, 10%)" in x for x in r.reasons)
    d = _dictionary(exo)
    d["tables"][0]["columns"][2]["missing"] = "not measured for six planets; statistics use the 54 with a radius"
    _write(exo / "data_dictionary.json", d)
    r = check_data_quality(exo)
    assert r.passed and "radius_earth: 10% missing" in r.notes[0]
    # A looser threshold in the template's settings lets the gap pass without a note.
    d["tables"][0]["columns"][2].pop("missing")
    _write(exo / "data_dictionary.json", d)
    assert check_data_quality(exo, max_missing_share=0.2).passed


def test_coverage_the_data_do_not_span_stops_the_run(exo: Path):
    d = _dictionary(exo)
    d["tables"][0]["coverage"] = {"column": "discovery_year", "from": 1995, "to": 2025}
    _write(exo / "data_dictionary.json", d)
    r = check_data_quality(exo)
    assert any("starts at 2009" in x for x in r.reasons) and any("ends at 2024" in x for x in r.reasons)


def test_a_declared_table_that_was_not_loaded_stops_the_run(exo: Path):
    d = _dictionary(exo)
    d["tables"].append({"name": "hosts", "source": "file", "columns": []})
    _write(exo / "data_dictionary.json", d)
    r = check_data_quality(exo)
    assert not r.passed and "table hosts is declared but not in data.db" in r.reasons


# ── the figure check ────────────────────────────────────────────────────────


def _figures(ws: Path) -> dict:
    return json.loads((ws / "figure_spec.json").read_text(encoding="utf-8"))


def test_figures_from_their_data_pass(exo: Path):
    r = check_figure_data(exo)
    assert r.passed, r.reasons
    assert r.stats == {"figures": 2, "parts": 2}


def test_a_figure_value_that_is_not_the_data_stops_the_run(exo: Path):
    spec = _figures(exo)
    spec["figures"][0]["y"][5] = spec["figures"][0]["y"][5] + 0.5
    _write(exo / "figure_spec.json", spec)
    r = check_figure_data(exo)
    assert not r.passed and "not the data of exoplanets" in r.reasons[0]


def test_a_histogram_that_shows_other_counts_stops_the_run(exo: Path):
    spec = _figures(exo)
    spec["figures"][1]["bins"][3]["count"] += 1
    _write(exo / "figure_spec.json", spec)
    r = check_figure_data(exo)
    assert not r.passed and "distributions.radius.bins" in r.reasons[0]


def test_a_figure_without_a_source_stops_the_run(exo: Path):
    spec = _figures(exo)
    del spec["figures"][0]["source"]
    _write(exo / "figure_spec.json", spec)
    r = check_figure_data(exo)
    assert r.reasons == ("fig_radius_period.pdf names no 'source' (a data.db table and columns, or a results path)",)


def test_a_source_condition_is_limited_to_the_tables_columns(exo: Path):
    spec = _figures(exo)
    spec["figures"][0]["source"]["where"] = "radius_earth > 0; DROP TABLE exoplanets"
    _write(exo / "figure_spec.json", spec)
    assert "simple condition" in check_figure_data(exo).reasons[0]
    spec["figures"][0]["source"]["where"] = "discovery_method = 'Transit'"
    _write(exo / "figure_spec.json", spec)
    # Only the transit planets: the figure (all 60) is no longer those rows.
    assert "the figure has 60 points, the data 47" in check_figure_data(exo).reasons[0]


def test_values_are_compared_at_the_precision_the_figure_states(exo: Path):
    spec = _figures(exo)
    spec["figures"][0]["x"] = [round(v, 1) for v in spec["figures"][0]["x"]]
    _write(exo / "figure_spec.json", spec)
    assert check_figure_data(exo).passed


# ── the forecast setup and its freeze ───────────────────────────────────────


@pytest.fixture
def ts(tmp_path: Path) -> Path:
    shutil.copy(CLIMATE / "data_analyst" / "data.db", tmp_path)
    shutil.copy(CLIMATE / "forecast_designer" / "forecast_design.json", tmp_path)
    return tmp_path


def _design(ws: Path) -> dict:
    return json.loads((ws / "forecast_design.json").read_text(encoding="utf-8"))


def _results(ws: Path) -> None:
    shutil.copy(CLIMATE / "econometrics_specialist" / "estimation_results.json", ws)


def test_the_setup_is_frozen_with_its_hold_out(ts: Path):
    r = check_forecast_design(ts)
    assert r.passed, r.reasons
    freeze = json.loads((ts / FREEZE_FILE).read_text(encoding="utf-8"))
    assert freeze["periods"][0] == "2021-01" and len(freeze["periods"]) == 36 and freeze["n_train"] == 240
    assert check_forecast_design(ts).notes[0].startswith("frozen at ")


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        (lambda d: d["holdout"].update(start="2020-01", end="2022-12", n_periods=36), "must be the last periods"),
        (lambda d: d["holdout"].update(n_periods=24), "holdout.n_periods is 24, but 2021-01 to 2023-12 are 36"),
        (lambda d: d["holdout"].update(start="2002-01", n_periods=264), "only 12 periods are left to fit on"),
        (lambda d: d.update(baselines=[]), "baselines must list at least one simple benchmark"),
        (lambda d: d["baselines"].append({"model": "arima", "method": "ARIMA"}), "is not naive, seasonal naive"),
        (lambda d: d.update(diagnostics=d["diagnostics"][:1]), "at least one trend test"),
        (lambda d: d.update(interval_level=95), "interval_level must be a share"),
        (lambda d: d["series"].update(table="t2m"), "table t2m is not in data.db"),
    ],
)
def test_a_setup_the_check_refuses(ts: Path, change, reason: str):
    d = _design(ts)
    change(d)
    _write(ts / "forecast_design.json", d)
    r = check_forecast_design(ts)
    assert not r.passed and any(reason in x for x in r.reasons), r.reasons
    assert not (ts / FREEZE_FILE).exists()


def test_a_setup_written_after_a_model_was_fitted_is_refused(ts: Path):
    _results(ts)
    r = check_forecast_design(ts)
    assert not r.passed and "was not frozen before a model was fitted" in r.reasons[0]


def test_a_change_before_fitting_is_frozen_again_and_one_after_is_refused(ts: Path):
    assert check_forecast_design(ts).passed
    d = _design(ts)
    d["horizon"] = 6
    _write(ts / "forecast_design.json", d)
    r = check_forecast_design(ts)
    assert r.passed and "frozen again" in r.notes[0]
    assert len(json.loads((ts / FREEZE_FILE).read_text(encoding="utf-8"))["changes"]) == 1
    _results(ts)
    d["horizon"] = 12
    _write(ts / "forecast_design.json", d)
    r = check_forecast_design(ts)
    assert not r.passed and "changed after the hold-out was frozen" in r.reasons[0]


# ── the evaluation on the hold-out ──────────────────────────────────────────


@pytest.fixture
def evaluated(ts: Path) -> Path:
    assert check_forecast_design(ts).passed
    _results(ts)
    return ts


def _edit_results(ws: Path, fn) -> None:
    doc = json.loads((ws / "estimation_results.json").read_text(encoding="utf-8"))
    fn(doc)
    _write(ws / "estimation_results.json", doc)


def test_the_recorded_study_passes_and_its_errors_are_recomputed(evaluated: Path):
    r = check_forecast_evaluation(evaluated)
    assert r.passed, r.reasons
    check = json.loads((evaluated / "forecast_check.json").read_text(encoding="utf-8"))
    assert check["best_baseline_rmse"] == pytest.approx(2.1344, abs=1e-4)
    assert check["out_of_sample"]["trend_season_test"]["interval_coverage"] == pytest.approx(34 / 36)


@pytest.mark.parametrize(
    ("edit", "reason"),
    [
        (lambda d: d["models"]["trend_season"].update(train_end="2022-06"), "leakage: models.trend_season was fitted"),
        (
            lambda d: d["diagnostics"]["kpss_level"].update(sample_end="2023-12"),
            "inside the hold-out (training ends 2020-12)",
        ),
        (lambda d: d["diagnostics"].pop("mann_kendall_annual"), "diagnostics.mann_kendall_annual"),
        (
            lambda d: d["out_of_sample"]["trend_season_test"].update(rmse=1.5),
            "the predictions and the hold-out values give 1.78",
        ),
        (lambda d: d["out_of_sample"]["naive_test"].pop("predictions"), "must list its 'predictions'"),
        (lambda d: d["out_of_sample"]["naive_test"]["predictions"].pop(), "do not cover each hold-out period"),
        (lambda d: d["out_of_sample"].pop("seasonal_naive_test"), "seasonal_naive have no out-of-sample evaluation"),
        (lambda d: d["out_of_sample"]["naive_test"].update(test_start="2020-01"), "the frozen hold-out is 2021-01"),
        (lambda d: d["forecasts"]["trend_season_2024"]["points"].pop(), "the declared horizon is 12"),
        (lambda d: d.update(forecasts={}), "no forecast beyond the data"),
        (lambda d: d["out_of_sample"]["trend_season_test"].update(coverage=0.99), "the intervals cover 0.944"),
    ],
)
def test_results_the_forecast_check_refuses(evaluated: Path, edit, reason: str):
    _edit_results(evaluated, edit)
    r = check_forecast_evaluation(evaluated)
    assert not r.passed and any(reason in x for x in r.reasons), r.reasons


def test_a_changed_setup_or_hold_out_after_the_freeze_is_refused(evaluated: Path):
    d = _design(evaluated)
    d["interval_level"] = 0.9
    _write(evaluated / "forecast_design.json", d)
    assert any("changed after the hold-out was frozen" in x for x in check_forecast_evaluation(evaluated).reasons)
    shutil.copy(CLIMATE / "forecast_designer" / "forecast_design.json", evaluated)
    con = sqlite3.connect(evaluated / "data.db")
    con.execute("UPDATE t2m_frankfurt SET T2M = T2M + 0.1 WHERE date = '2022-07'")
    con.commit()
    con.close()
    assert (
        "the hold-out values in data.db changed after they were frozen" in check_forecast_evaluation(evaluated).reasons
    )


def test_without_a_freeze_there_is_no_evaluation(ts: Path):
    _results(ts)
    r = check_forecast_evaluation(ts)
    assert not r.passed and "never frozen before fitting" in r.reasons[0]


# ── the templates ───────────────────────────────────────────────────────────


def test_the_descriptive_template():
    spec = find_spec("descriptive-study")
    assert (spec.results, spec.causal, spec.base_skill, spec.data_skills) == (
        "descriptive",
        False,
        "base/researcher",
        (),
    )
    gate = spec.step("data_quality_gate")
    assert gate.check == "data_quality" and gate.after == ("data_architect", "data_analyst") and gate.on_fail == "retry"
    assert gate.settings == {"max_missing_share": 0.05}
    assert [s.name for s in spec.steps if s.kind == "researcher"] == ["review_design", "review_draft"]
    names = [s.name for s in spec.steps]
    assert names.index("estimation_gate") < names.index("figure_gate") < names.index("review_draft")
    assert spec.polish() == ["polish_numerics", "polish_bibliography"]
    assert "identification_reviewer" not in spec.panel() and "methods_reviewer" in spec.panel()
    assert spec.skills["econometrics_specialist"] == ("methods/descriptive-analysis",)


def test_the_time_series_template():
    spec = find_spec("time-series-forecasting")
    assert (spec.results, spec.causal, spec.base_skill) == ("timeseries", False, "base/researcher")
    gate = spec.step("forecast_design_gate")
    assert gate.check == "forecast_design" and set(gate.after) == {"data_analyst", "forecast_designer"}
    assert spec.optional_steps() == ["preregister"]
    names = [s.name for s in spec.steps]
    assert names.index("estimation_gate") < names.index("forecast_gate") < names.index("figure_gate")
    assert names.index("figure_gate") < names.index("review_draft")
    assert spec.polish() == ["polish_formula", "polish_numerics", "polish_bibliography"]
    assert "technical_reviewer" in spec.panel() and "mechanism_reviewer" not in spec.panel()
    # The pre-registration runs only when the researcher chose it.
    assert spec.chosen([]).step("preregister") is None
    assert spec.chosen(["preregister"]).step("preregister") is not None


def test_only_researcher_steps_can_be_optional():
    with pytest.raises(PipelineError, match="only researcher and preregister steps can be optional"):
        spec_from_dict({"name": "x", "steps": [{"kind": "strategist", "name": "initial", "optional": True}]})
    with pytest.raises(PipelineError, match="optional must be true or false"):
        spec_from_dict({"name": "x", "steps": [{"kind": "researcher", "name": "r", "optional": "yes"}]})


def test_optional_steps_are_choices_on_new_study():
    from src.api.app import _review_at_choices

    assert "preregister" in _review_at_choices(find_spec("time-series-forecasting"))
    assert "preregister" not in _review_at_choices(find_spec("empirical-preregistered"))


@pytest.mark.parametrize("name", ["descriptive-study", "time-series-forecasting"])
def test_the_method_sources_are_credited_in_the_template_and_the_catalogue(name: str):
    raw = tomllib.loads((ROOT / "pipelines" / f"{name}.toml").read_text(encoding="utf-8"))
    credit = raw["credit"]
    assert credit and all(c["relation"] == "cites" and c["url"].startswith("https://") for c in credit)
    doc = json.loads((ROOT / "credits.json").read_text(encoding="utf-8"))
    assert doc["parts"][f"template:{name}"] == credit
    assert load_spec(ROOT / "pipelines" / f"{name}.toml").credit == tuple(credit)


def test_the_forecast_designer_is_a_registered_specialist():
    from src.core.labels import SPECIALISTS, STEPS, TEMPLATES
    from src.core.specialists.registry import (
        SPECIALIST_ARTIFACTS,
        SPECIALIST_NEEDS,
        SPECIALIST_SIDECAR_ARTIFACTS,
        SPECIALIST_SKILLS,
    )

    assert SPECIALIST_ARTIFACTS["forecast_designer"] == "forecast_design.md"
    assert SPECIALIST_SIDECAR_ARTIFACTS["forecast_designer"] == ["forecast_design.json"]
    assert "methods/time-series-forecasting" in SPECIALIST_SKILLS["forecast_designer"]
    assert "forecast_designer" in SPECIALIST_NEEDS["econometrics_specialist"]
    assert SPECIALISTS["forecast_designer"] and TEMPLATES["time-series-forecasting"] and TEMPLATES["descriptive-study"]
    for step in ("data_quality_gate", "figure_gate", "forecast_design_gate", "forecast_gate"):
        assert step in STEPS


def test_the_strategist_is_told_to_dispatch_the_forecast_designer():
    from src.core.pipeline.components import activate, deactivate
    from src.core.strategist.context import template_context

    token = activate(copy.copy(find_spec("time-series-forecasting")))
    try:
        text = template_context()
    finally:
        deactivate(token)
    assert "Dispatch data_analyst, forecast_designer before econometrics_specialist" in text
