"""The method checks of the policy-evaluation and spatial-analysis templates, and the map renderer.

Unit level, on the replay fixtures' data (tests/fixtures/replay/did and
spatial, synthetic) and small hand-made cases. The end-to-end runs are in
test_policy_evaluation_replay.py and test_spatial_analysis_replay.py.
"""

from __future__ import annotations

import csv
import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from src.core.pipeline.did_checks import check_did_design, check_did_results, estimator_name
from src.core.pipeline.spatial_checks import check_spatial_design, check_spatial_results, crs_code, morans_i
from src.core.pipeline.spec import find_spec
from src.core.renderer.figures import render_figures

FIX = Path(__file__).resolve().parent / "fixtures" / "replay"
DID, SPATIAL = FIX / "did" / "files", FIX / "spatial" / "files"


@pytest.fixture
def did_ws(tmp_path: Path) -> Path:
    for src in (
        DID / "data_analyst" / "data.db",
        DID / "data_analyst" / "figure_spec.json",
        DID / "identification_strategist" / "did_design.json",
        DID / "econometrics_specialist" / "estimation_results.json",
    ):
        shutil.copy(src, tmp_path / src.name)
    return tmp_path


def _edit(path: Path, **changes: object) -> None:
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc.update(changes)
    path.write_text(json.dumps(doc), encoding="utf-8")


# ── difference-in-differences ───────────────────────────────────────────────


def test_estimator_names_and_spellings():
    assert estimator_name("Callaway-Sant'Anna") == "callaway_santanna"
    assert estimator_name("csdid") == "callaway_santanna"
    assert estimator_name("did_multiplegt") == "de_chaisemartin_dhaultfoeuille"
    assert estimator_name("TWFE") == "twfe" and estimator_name("OLS") == "twfe"
    assert estimator_name("synthetic control") is None


def test_the_design_check_records_the_cohorts_and_warns_on_staggered_timing(did_ws: Path):
    v = check_did_design(did_ws)
    assert v.passed, v.reasons
    assert v.stats["cohorts"] == 2 and v.stats["staggered"] and v.stats["never_treated_units"] == 12
    assert any(n.startswith("warning: treatment timing is staggered") for n in v.notes)
    found = json.loads((did_ws / "did_design_check.json").read_text(encoding="utf-8"))
    assert found["pre_periods_by_cohort"] == {"2006": 6, "2010": 10}


def test_two_way_fixed_effects_on_staggered_timing_is_refused(did_ws: Path):
    _edit(did_ws / "did_design.json", estimator="twfe")
    v = check_did_design(did_ws)
    assert not v.passed and "staggered" in v.reasons[0] and "Goodman-Bacon" in v.reasons[0]


def test_two_way_fixed_effects_with_one_treatment_date_passes(did_ws: Path):
    con = sqlite3.connect(did_ws / "data.db")
    con.execute("UPDATE adoption SET first_year = 2006 WHERE first_year = 2010")
    con.commit()
    con.close()
    _edit(did_ws / "did_design.json", estimator="twfe")
    v = check_did_design(did_ws)
    assert v.passed and v.stats["staggered"] is False, v.reasons


def test_no_comparison_group_and_too_few_pre_periods_are_refused(did_ws: Path):
    con = sqlite3.connect(did_ws / "data.db")
    con.execute("UPDATE adoption SET first_year = 2001 WHERE first_year IS NULL")
    con.commit()
    con.close()
    v = check_did_design(did_ws)
    assert not v.passed and any(r.startswith("(b)") for r in v.reasons)
    v = check_did_design(did_ws, min_pre_periods=11)
    assert any(r.startswith("(d)") for r in v.reasons)


def test_a_missing_outcome_column_names_the_table_columns(did_ws: Path):
    _edit(did_ws / "did_design.json", outcome={"table": "panel", "column": "gdp"})
    v = check_did_design(did_ws)
    assert not v.passed and "has no column gdp" in v.reasons[0] and "outcome" in v.reasons[0]


def test_the_results_check_draws_the_event_study_plot_from_the_results(did_ws: Path):
    check_did_design(did_ws)
    v = check_did_results(did_ws)
    assert v.passed, v.reasons
    figs = json.loads((did_ws / "figure_spec.json").read_text(encoding="utf-8"))["figures"]
    es = [f for f in figs if f["figure_type"] == "event_study"]
    assert len(es) == 1 and es[0]["periods"][0] == -5.0
    # Run again on changed results: the figure it drew is drawn again, not kept stale.
    res = json.loads((did_ws / "estimation_results.json").read_text(encoding="utf-8"))
    res["event_study"]["periods"][0]["estimate"] = 0.5
    (did_ws / "estimation_results.json").write_text(json.dumps(res), encoding="utf-8")
    assert check_did_results(did_ws).passed
    figs = json.loads((did_ws / "figure_spec.json").read_text(encoding="utf-8"))["figures"]
    assert [f for f in figs if f["figure_type"] == "event_study"][0]["estimates"][0] == 0.5


def test_a_figure_of_its_own_that_shows_other_numbers_fails(did_ws: Path):
    spec = json.loads((did_ws / "figure_spec.json").read_text(encoding="utf-8"))
    spec["figures"].append(
        {"filename": "fig_es.pdf", "figure_type": "event_study", "periods": [-2, 0], "estimates": [0.0, -9.0]}
    )
    (did_ws / "figure_spec.json").write_text(json.dumps(spec), encoding="utf-8")
    v = check_did_results(did_ws)
    assert not v.passed and any("does not show the results' estimate" in r for r in v.reasons)


def test_rejected_pre_trends_pass_only_with_a_rambachan_roth_sensitivity(did_ws: Path):
    res = json.loads((did_ws / "estimation_results.json").read_text(encoding="utf-8"))
    res["pre_trends"]["p_value"] = 0.01
    (did_ws / "estimation_results.json").write_text(json.dumps(res), encoding="utf-8")
    v = check_did_results(did_ws)
    assert v.passed and any("sensitivity analysis" in n for n in v.notes)
    res["sensitivity"].pop("honest_did_rm")
    (did_ws / "estimation_results.json").write_text(json.dumps(res), encoding="utf-8")
    v = check_did_results(did_ws)
    assert not v.passed and any("jointly different from zero" in r for r in v.reasons)


def test_no_placebo_no_sensitivity_no_pre_trends_and_a_wrong_estimator_fail(did_ws: Path):
    res = json.loads((did_ws / "estimation_results.json").read_text(encoding="utf-8"))
    for k in ("placebo", "sensitivity", "pre_trends"):
        res.pop(k)
    res["main"]["estimator"] = "sun_abraham"
    (did_ws / "estimation_results.json").write_text(json.dumps(res), encoding="utf-8")
    reasons = " ".join(check_did_results(did_ws).reasons)
    assert "(f) estimation_results.json has no 'pre_trends'" in reasons
    assert "(g) report a placebo test" in reasons
    assert "main.estimator is sun_abraham, but did_design.json declares callaway_santanna" in reasons


def test_too_few_leads_fail(did_ws: Path):
    res = json.loads((did_ws / "estimation_results.json").read_text(encoding="utf-8"))
    res["event_study"]["periods"] = [p for p in res["event_study"]["periods"] if p["relative_period"] >= -2]
    res["pre_trends"]["n_pre_periods"] = 1
    (did_ws / "estimation_results.json").write_text(json.dumps(res), encoding="utf-8")
    v = check_did_results(did_ws)
    assert any("1 pre-treatment period(s)" in r for r in v.reasons)


# ── spatial ─────────────────────────────────────────────────────────────────


@pytest.fixture
def sp_ws(tmp_path: Path) -> Path:
    for src in (
        SPATIAL / "data_analyst" / "data.db",
        SPATIAL / "data_analyst" / "figure_spec.json",
        SPATIAL / "data_architect" / "spatial_design.json",
        *(SPATIAL / "econometrics_specialist").glob("*.csv"),
        SPATIAL / "econometrics_specialist" / "estimation_results.json",
    ):
        shutil.copy(src, tmp_path / src.name)
    return tmp_path


def test_crs_codes():
    assert crs_code("EPSG:4326") == "4326" and crs_code("urn:ogc:def:crs:EPSG::3035") == "3035"
    assert crs_code("WGS84") == "4326" and crs_code("lat/lon") is None


def test_morans_i_of_a_checkerboard_is_minus_one():
    values = {"a": 1.0, "b": 0.0, "c": 1.0, "d": 0.0}
    links = [("a", "b", 1.0), ("b", "a", 0.5), ("b", "c", 0.5), ("c", "b", 0.5), ("c", "d", 0.5), ("d", "c", 1.0)]
    assert morans_i(values, links) == pytest.approx(-1.0)


def test_the_design_check_matches_units_to_geometry(sp_ws: Path):
    v = check_spatial_design(sp_ws)
    assert v.passed, v.reasons
    assert v.stats["data_units"] == 31 and v.stats["without"] == 1


def test_an_unlisted_unit_without_geometry_a_missing_crs_and_undocumented_weights_fail(sp_ws: Path):
    _edit(sp_ws / "spatial_design.json", units_without_geometry=[], crs="", weights={"type": "knn"})
    reasons = " ".join(check_spatial_design(sp_ws).reasons)
    assert "(c) 1 unit(s) of regional.geo have no geometry" in reasons and "RZZ" in reasons
    assert "(b) crs must state" in reasons
    assert "weights of type knn need a numeric 'k'" in reasons and "row_standardised" in reasons


def test_units_without_geometry_may_be_listed_by_a_pattern(sp_ws: Path):
    _edit(sp_ws / "spatial_design.json", units_without_geometry=[{"id": "R?Z", "reason": "extra-regio codes"}])
    v = check_spatial_design(sp_ws)
    assert v.passed, v.reasons
    found = json.loads((sp_ws / "spatial_design_check.json").read_text(encoding="utf-8"))
    assert found["reasons"] == {"RZZ": "extra-regio codes"}
    _edit(
        sp_ws / "spatial_design.json", units_without_geometry=[{"id": "CH, NO and other non-EU codes", "reason": "x"}]
    )
    assert not check_spatial_design(sp_ws).passed  # a sentence is not a pattern


def test_a_projected_crs_on_longitudes_and_latitudes_fails(sp_ws: Path):
    _edit(sp_ws / "spatial_design.json", crs="EPSG:3035")
    assert any("projected" in r for r in check_spatial_design(sp_ws).reasons)


def test_boundaries_without_source_terms_fail(sp_ws: Path):
    design = json.loads((sp_ws / "spatial_design.json").read_text(encoding="utf-8"))
    design["boundaries"].pop("licence")
    (sp_ws / "spatial_design.json").write_text(json.dumps(design), encoding="utf-8")
    assert any("need licence" in r for r in check_spatial_design(sp_ws).reasons)
    design["boundaries"]["source"] = "gisco"
    (sp_ws / "spatial_design.json").write_text(json.dumps(design), encoding="utf-8")
    assert any("records no load from it" in r for r in check_spatial_design(sp_ws).reasons)


def test_the_results_check_recomputes_morans_i_and_builds_the_maps(sp_ws: Path):
    v = check_spatial_results(sp_ws)
    assert v.passed, v.reasons
    figs = {f["filename"]: f for f in json.loads((sp_ws / "figure_spec.json").read_text(encoding="utf-8"))["figures"]}
    assert set(figs) == {"fig_map_rate.pdf", "fig_map_lisa.pdf"}
    report = render_figures(sp_ws)
    assert set(report.rendered) == {"fig_map_rate.pdf", "fig_map_lisa.pdf"}, report


def test_a_reported_i_that_the_weights_do_not_give_and_a_normal_p_value_fail(sp_ws: Path):
    res = json.loads((sp_ws / "estimation_results.json").read_text(encoding="utf-8"))
    res["spatial_statistics"]["moran_rate_queen"]["estimate"] = 0.75
    for s in res["spatial_statistics"].values():
        s["p_value_method"] = "normal"
    (sp_ws / "estimation_results.json").write_text(json.dumps(res), encoding="utf-8")
    reasons = " ".join(check_spatial_results(sp_ws).reasons)
    assert "(g) spatial_statistics.moran_rate_queen: the reported Moran's I 0.75 does not follow" in reasons
    assert "(f) no Moran's I has permutation inference" in reasons


def test_weights_that_are_not_row_standardised_or_name_strangers_fail(sp_ws: Path):
    path = sp_ws / "spatial_weights.csv"
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    rows[0]["weight"] = "0.9"
    rows.append({"from": "R01", "to": "X99", "weight": "0.1"})
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["from", "to", "weight"])
        w.writeheader()
        w.writerows(rows)
    reasons = " ".join(check_spatial_results(sp_ws).reasons)
    assert "names units spatial_units.csv has not: X99" in reasons
    assert "rows do not sum to 1" in reasons


def test_too_few_permutations_and_an_impossible_p_value_fail(sp_ws: Path):
    res = json.loads((sp_ws / "estimation_results.json").read_text(encoding="utf-8"))
    res["spatial_statistics"]["moran_rate_queen"]["n_permutations"] = 49
    res["spatial_statistics"]["moran_rate_knn4"]["p_value"] = 0.0001
    (sp_ws / "estimation_results.json").write_text(json.dumps(res), encoding="utf-8")
    reasons = " ".join(check_spatial_results(sp_ws).reasons)
    assert "n_permutations must be at least 99" in reasons and "below 1 / (permutations + 1)" in reasons


# ── maps ─────────────────────────────────────────────────────────────────────


def test_a_map_reads_its_boundaries_and_values_and_names_units_without_geometry(sp_ws: Path):
    spec = {
        "figures": [
            {
                "filename": "fig_m.pdf",
                "figure_type": "map",
                "boundaries": {"table": "regions", "id_column": "id", "geometry_column": "geometry"},
                "data": {"table": "regional", "id_column": "geo", "value_column": "rate"},
                "classification": "equal_interval",
                "classes": 4,
                "projection": "equal_earth",
                "attribution": "Synthetic test geometry",
            },
            {
                "filename": "fig_pts.pdf",
                "figure_type": "map",
                "map_type": "points",
                "values": None,
                "data": {"file": "pts.csv", "lon_column": "lon", "lat_column": "lat", "value_column": "v"},
            },
            {"filename": "fig_bad.pdf", "figure_type": "map", "data": {"file": "nope.csv", "value_column": "x"}},
        ]
    }
    (sp_ws / "pts.csv").write_text("lon,lat,v\n1.5,45.5,1\n9.2,52.1,3\n", encoding="utf-8")
    (sp_ws / "figure_spec.json").write_text(json.dumps(spec), encoding="utf-8")
    report = render_figures(sp_ws)
    assert set(report.rendered) == {"fig_m.pdf", "fig_pts.pdf"}, report
    assert any("RZZ" in n for n in report.notes)  # the data unit without geometry
    assert any(s.startswith("fig_bad.pdf: a choropleth or categories map needs 'boundaries'") for s in report.skipped)


def test_the_shipped_templates_load_with_their_checks_and_panels():
    did, sp = find_spec("policy-evaluation"), find_spec("spatial-analysis")
    assert did.results == "regression" and did.causal
    assert [s.check for s in did.steps if s.kind == "gate"] == ["did_design", "did_results", "estimation"]
    assert sp.results == "spatial" and not sp.causal and sp.base_skill == "base/researcher"
    assert [s.check for s in sp.steps if s.kind == "gate"] == ["spatial_design", "spatial_results", "estimation"]
    assert {c["relation"] for c in did.credit} == {"cites"} and len(did.credit) == 8
    assert any("10.1111/j.1538-4632.1995.tb00338.x" in c["url"] for c in sp.credit)


def test_credits_json_carries_the_templates_method_sources():
    import tomllib

    parts = json.loads((Path(__file__).resolve().parents[1] / "credits.json").read_text(encoding="utf-8"))["parts"]
    for name in ("policy-evaluation", "spatial-analysis"):
        path = Path(__file__).resolve().parents[1] / "pipelines" / f"{name}.toml"
        assert parts[f"template:{name}"] == tomllib.loads(path.read_text(encoding="utf-8"))["credit"]


def test_an_extent_in_degrees_frames_a_map_drawn_in_etrs89_laea(tmp_path: Path):
    """The spatial live run of 2026-10-11 drew NUTS 2024 boundaries in EPSG:3035 with an extent in degrees;
    the extent was ignored and the overseas regions shrank Europe to a corner of the map."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from src.core.renderer.maps import _etrs89_laea, render_map

    def square(lon: float, lat: float) -> dict:
        pts = [_etrs89_laea(lon + dx, lat + dy) for dx, dy in ((0, 0), (1, 0), (1, 1), (0, 1), (0, 0))]
        return {"type": "Polygon", "coordinates": [[list(p) for p in pts]]}

    feats = [
        {"type": "Feature", "properties": {"id": "DE1"}, "geometry": square(9, 49)},
        {"type": "Feature", "properties": {"id": "FRY4"}, "geometry": square(55, -21)},  # La Réunion
    ]
    (tmp_path / "b.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}), "utf-8")
    spec = {
        "figure_type": "map",
        "boundaries": {"file": "b.geojson", "id_property": "id"},
        "values": {"DE1": 1.0, "FRY4": 2.0},
        "crs": "EPSG:3035",
        "extent": [-12, 34, 35, 72],
    }
    fig, notes = render_map(plt, spec, tmp_path)
    x0, x1 = fig.axes[0].get_xlim()
    assert "projection: none" in notes
    assert x1 - x0 < 300_000  # framed on the one region inside the extent, not on La Réunion as well
    plt.close(fig)
