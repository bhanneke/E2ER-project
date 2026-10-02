"""Three checks from the live demonstration studies (2026-09-29).

1. Every pre-registered hypothesis has a result, on the registered sample.
2. p-values follow from the test statistic.
3. A replication export can be verified offline.

Fixtures: ``tests/fixtures/fomc_event_study/`` holds the FOMC event study's
frozen pre-registration and two versions of its estimation_results.json (the
first, with no H2 entry and p = 0.32 at t = -2.00 with 20 events, and the one
written at 15:37). ``tests/fixtures/replication_demo/`` holds the replication
demo's plan, report, check and sandbox log from export -07 plus the five
output files the report compares against, copied from the sandbox run.
"""

from __future__ import annotations

import json
import math
import shutil
from pathlib import Path
from typing import Any

import pytest

from src.cli_verify import FAIL, PASS, SKIP, _run_checks, _verdict, verify
from src.core.pipeline.preregistration import (
    LOCK_FILE,
    MACHINE_HEADING,
    PREREG_FILE,
    assemble,
    check_results_against_preregistration,
    extract_hypotheses,
    freeze,
    headline_entry,
    parse_machine_block,
    preregistered,
    result_coverage,
)
from src.core.pipeline.reproduction import CHECK_FILE, check_reproduction, evaluate, label_for
from src.core.pipeline.statistics import betainc, check_statistics, p_from_t, t_sf, t_two_sided_p
from src.core.specialists.contract_check import (
    check_preregistered_results,
    check_specialist_artifacts,
    check_statistics_consistent,
)

FIXTURES = Path(__file__).parent / "fixtures"
FOMC = FIXTURES / "fomc_event_study"
REPL = FIXTURES / "replication_demo"


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _coef(estimate: float, se: float, t: float, p: float, **extra: Any) -> dict[str, Any]:
    return {"estimate": estimate, "se": se, "t_stat": t, "p_value": p, **extra}


# ══ 2. p-values follow from the test statistic ═══════════════════════════════


@pytest.mark.parametrize("t", [0.0, 0.3, 1.0, 2.0, 5.0, 40.0])
def test_t_with_one_and_two_df_matches_the_closed_forms(t: float):
    assert t_two_sided_p(t, 1) == pytest.approx(1 - 2 / math.pi * math.atan(abs(t)), abs=1e-12)
    assert t_two_sided_p(t, 2) == pytest.approx(1 - abs(t) / math.sqrt(2 + t * t), abs=1e-12)


@pytest.mark.parametrize(
    ("t", "df", "p"),
    [
        # Two-sided critical values from standard t tables.
        (12.706204736, 1, 0.05),
        (4.302652730, 2, 0.05),
        (2.570581836, 5, 0.05),
        (2.228138852, 10, 0.05),
        (2.093024054, 19, 0.05),
        (2.042272456, 30, 0.05),
        (1.979930405, 120, 0.05),
        (3.169272673, 10, 0.01),
        (2.749995652, 30, 0.01),
        (1.724718243, 20, 0.10),
        (1.959963985, None, 0.05),
        (2.575829304, math.inf, 0.01),
    ],
)
def test_t_matches_published_critical_values(t: float, df: float | None, p: float):
    assert t_two_sided_p(t, df) == pytest.approx(p, abs=1e-8)
    assert t_two_sided_p(-t, df) == pytest.approx(p, abs=1e-8)


def test_t_approaches_the_normal_and_the_one_sided_tails_add_up():
    assert t_two_sided_p(2.0, 1e6) == pytest.approx(math.erfc(2 / math.sqrt(2)), abs=1e-6)
    assert t_two_sided_p(2.0, 19) == pytest.approx(0.0600, abs=5e-5)  # the FOMC case
    assert t_sf(1.5, 7) + t_sf(-1.5, 7) == pytest.approx(1.0, abs=1e-12)
    assert p_from_t(2.0, 19, "greater") == pytest.approx(0.0300, abs=5e-5)
    assert p_from_t(2.0, 19, "less") == pytest.approx(0.9700, abs=5e-5)
    assert betainc(2.0, 3.0, 0.4) == pytest.approx(0.5248, abs=1e-12)  # I_0.4(2,3) = 0.5248 exactly
    assert betainc(1.0, 1.0, 0.37) == pytest.approx(0.37, abs=1e-14)


def test_the_fomc_studys_first_results_fail_and_name_each_coefficient():
    report = check_statistics([("estimation_results.json", _load(FOMC / "estimation_results_early.json"))])
    assert not report.ok and report.checked == 3
    hikes = next(p for p in report.problems if "main_hikes.mean_car" in p)
    # t = -2.00 with 20 events: two-sided p is 0.060, not the 0.32 reported.
    assert "p_value 0.32" in hikes and "19 df" in hikes and "0.0603" in hikes
    assert any("#main.mean_car" in p and "0.1191" in p for p in report.problems)


def test_the_fomc_studys_later_results_still_fail():
    """The 15:37 version states df, and its hand-written t_sf still gives p = 0.208 for t = -2.00."""
    report = check_statistics([("estimation_results.json", _load(FOMC / "estimation_results_1537.json"))])
    assert report.checked == 6 and len(report.problems) == 6
    assert any("h1_hikes_m1p1.mean_car: p_value 0.208" in p and "0.0603" in p for p in report.problems)


def test_consistent_statistics_pass():
    doc = {
        "main": {
            "n_observations": 20,
            "method": "one-sample t-test of the mean CAR",
            "coefficients": {"mean_car": _coef(-0.010588, 0.0053, -1.9978, 0.0603)},
        },
        "ols": {
            "n_observations": 500,
            "diagnostics": {"df_residual": 497},
            "coefficients": {"x": _coef(0.5, 0.25, 2.0, 0.046), "z": _coef(1.2, 0.4, 3.0, 0.0028)},
        },
    }
    report = check_statistics([("r.json", doc)])
    assert report.ok, report.problems
    assert report.checked == 3 and not report.df_unknown


def test_t_that_is_not_estimate_over_se_fails():
    doc = {"main": {"diagnostics": {"df": 50}, "coefficients": {"x": _coef(0.5, 0.25, 3.1, 0.003)}}}
    report = check_statistics([("r.json", doc)])
    assert len(report.problems) == 1 and "main.x: t_stat 3.1 is not estimate / se" in report.problems[0]


def test_rounded_inputs_are_allowed_for():
    # estimate and se rounded to 3 decimals; the t from the unrounded values.
    doc = {"main": {"diagnostics": {"df": 100}, "coefficients": {"x": _coef(0.012, 0.005, 2.47, 0.0152)}}}
    assert check_statistics([("r.json", doc)]).ok


def test_unknown_df_is_checked_against_a_band_and_flagged():
    ok = {"m": {"n_observations": 40, "coefficients": {"a": _coef(1.0, 0.5, 2.0, 0.05), "b": _coef(1, 1, 1, 0.32)}}}
    report = check_statistics([("r.json", ok)])
    assert report.ok and report.df_unknown == ["r.json#m.a", "r.json#m.b"]
    assert "df unknown for 2" in report.summary()
    bad = {"m": {"coefficients": {"a": _coef(1.0, 0.5, 2.0, 0.40)}}}
    problem = check_statistics([("r.json", bad)]).problems[0]
    assert "m.a" in problem and "df unknown" in problem


def test_clustered_standard_errors_accept_g_minus_one_to_the_normal():
    entry = {"n_observations": 540, "n_clusters": 10, "cluster_level": "coin", "diagnostics": {"df_residual": 476}}
    t9 = {**entry, "coefficients": {"d": _coef(-0.05, 0.04, -1.25, 0.2432)}}
    normal = {**entry, "coefficients": {"d": _coef(-0.05, 0.04, -1.25, 0.2113)}}
    assert check_statistics([("r.json", {"main": t9})]).ok
    assert check_statistics([("r.json", {"main": normal})]).ok
    wrong = {**entry, "coefficients": {"d": _coef(-0.05, 0.04, -1.25, 0.45)}}
    assert "clustered on 10 groups" in check_statistics([("r.json", {"main": wrong})]).problems[0]


def test_declared_rounding_widens_the_tolerance_and_other_methods_are_left_out():
    rounded = {
        "rounding": {"p_value": 1},
        "main": {"diagnostics": {"df": 19}, "coefficients": {"x": _coef(-1.0, 0.5, -2.0, 0.1)}},
    }
    assert check_statistics([("r.json", rounded)]).ok
    assert not check_statistics([("r.json", {**rounded, "rounding": {}})]).ok
    perm = {"main": {"coefficients": {"x": _coef(-1.0, 0.5, -2.0, 0.2, p_value_method="permutation")}}}
    report = check_statistics([("r.json", perm)])
    assert report.ok and report.checked == 0 and report.not_analytic == ["r.json#main.x"]


def test_a_declared_one_sided_test_is_checked_one_sided():
    coef = _coef(1.0, 0.5, 2.0, 0.03, alternative="greater")
    doc = {"main": {"diagnostics": {"df": 19}, "coefficients": {"x": coef}}}
    assert check_statistics([("r.json", doc)]).ok
    doc["main"]["coefficients"]["x"]["alternative"] = "two-sided"
    assert not check_statistics([("r.json", doc)]).ok


def test_the_estimation_check_names_the_inconsistent_coefficient(tmp_path: Path):
    shutil.copy(FOMC / "estimation_results_early.json", tmp_path / "estimation_results.json")
    c = check_statistics_consistent(tmp_path, "estimation_results.json")
    assert not c.ok and c.kind == "verification"
    assert "main_hikes.mean_car" in c.reason and "scipy.stats" in c.reason


def _econometrics_workspace(ws: Path, results: dict[str, Any]) -> None:
    (ws / "econometric_spec.md").write_text("A mean-CAR test of the FOMC events, " * 10)
    (ws / "estimation_results.json").write_text(json.dumps(results))


def test_the_estimation_gate_runs_the_statistics_rule(tmp_path: Path):
    _econometrics_workspace(tmp_path, _load(FOMC / "estimation_results_early.json"))
    failed = [c for c in check_specialist_artifacts(tmp_path, "econometrics_specialist") if not c.ok]
    assert any("statistics do not agree" in c.reason for c in failed)


def _verify_bundle(tmp_path: Path, results: dict[str, Any], *, prereg: bool = False) -> Path:
    from src.core.export.structured import export_paper

    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "manifest.json").write_text(json.dumps({"title": "Checks", "paper_id": "p1", "governance": "full"}))
    (ws / "estimation_results.json").write_text(json.dumps(results))
    if prereg:
        for name in ("paper_plan.md", "event_design.json", "identification_spec.json"):
            shutil.copy(FOMC / name, ws / name)
        assemble(ws)
        freeze(ws)
    return export_paper(ws, tmp_path / "out", date_str="20260929")


def test_verify_numbers_fails_on_an_inconsistent_p_value(tmp_path: Path):
    bundle = _verify_bundle(tmp_path, _load(FOMC / "estimation_results_early.json"))
    numbers = next(c for c in _run_checks(bundle, online=False) if c.name == "numbers")
    assert numbers.status == FAIL and "main_hikes.mean_car" in numbers.detail


def test_verify_numbers_reports_consistent_statistics_without_a_paper(tmp_path: Path):
    doc = {"main": {"diagnostics": {"df": 19}, "coefficients": {"x": _coef(-1.0, 0.5, -2.0, 0.06)}}}
    bundle = _verify_bundle(tmp_path, doc)
    numbers = next(c for c in _run_checks(bundle, online=False) if c.name == "numbers")
    assert numbers.status == SKIP and "1 coefficient(s) checked, 0 inconsistent" in numbers.detail


# ══ 1. every pre-registered hypothesis has a result ══════════════════════════


def test_the_hypotheses_are_read_from_the_plan():
    found = extract_hypotheses((FOMC / "paper_plan.md").read_text())
    assert [h["id"] for h in found] == ["H1", "H2"]
    assert found[0]["parts"] == ["H1a", "H1b"] and found[1]["statement"] == "Surprise Sensitivity Test"
    # A passing mention is not a declaration.
    assert extract_hypotheses("- H1 and H2 results excluding March 2020\n") == []
    assert [h["id"] for h in extract_hypotheses("**H3.** Volume rises.\n- **h4a (hikes)**: x\n")] == ["H3", "H4"]


def test_the_preregister_step_writes_the_machine_readable_list_and_freezes_it(tmp_path: Path):
    for name in ("paper_plan.md", "event_design.json", "identification_spec.json"):
        shutil.copy(FOMC / name, tmp_path / name)
    text = assemble(tmp_path).read_text()
    assert f"## {MACHINE_HEADING}" in text
    block = parse_machine_block(text)
    assert block is not None
    assert [h["id"] for h in block["hypotheses"]] == ["H1", "H2"]
    assert block["sample_size"] == {"n": 31, "unit": "events", "source": "event_design.json"}
    # The researcher corrects the list before approving: the lock takes the edited one.
    edited = text.replace('"id": "H2"', '"id": "H3"')
    (tmp_path / PREREG_FILE).write_text(edited)
    lock = freeze(tmp_path)
    assert [h["id"] for h in lock["hypotheses"]] == ["H1", "H3"]
    assert lock["sample_size"]["n"] == 31
    assert _load(tmp_path / LOCK_FILE)["hypotheses"] == lock["hypotheses"]


def test_a_lock_frozen_before_the_list_existed_falls_back_to_the_text():
    prereg = preregistered(FOMC, _load(FOMC / "preregistration.lock.json"))
    assert [h["id"] for h in prereg["hypotheses"]] == ["H1", "H2"]
    assert prereg["sample_size"]["n"] == 31 and "declared in the text" in prereg["source"]


def _prereg() -> dict[str, Any]:
    return preregistered(FOMC, _load(FOMC / "preregistration.lock.json"))


def test_the_fomc_studys_first_results_miss_both_hypotheses_and_one_event():
    results = _load(FOMC / "estimation_results_early.json")
    problems, _ = result_coverage([results], _prereg(), headline_entry(results, _prereg()))
    assert "without a result: H1, H2" in problems[0] and "3 result entries name no hypothesis" in problems[0]
    assert "fixes 31 events, the headline result uses 30" in problems[1]


def test_the_fomc_studys_later_results_miss_both_hypotheses():
    """The 15:37 version puts the null hypothesis's text in 'hypothesis' and has no H2 entry."""
    results = _load(FOMC / "estimation_results_1537.json")
    problems, _ = result_coverage([results], _prereg(), headline_entry(results, _prereg()))
    assert len(problems) == 1 and "without a result: H1, H2" in problems[0]
    assert "named but not pre-registered" in problems[0]


def _tagged(n: int = 31, h2: bool = True, **main: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "main": {"hypothesis": "H1", "n_observations": n, "coefficients": {"m": {"estimate": 1}}, **main},
        "main_hikes": {"hypothesis": "H1a", "n_observations": 20, "coefficients": {"m": {"estimate": 1}}},
    }
    if h2:
        doc["h2"] = {"hypothesis": ["H2"], "n_observations": n, "coefficients": {"b": {"estimate": 1}}}
    return doc


def test_tagged_results_on_the_registered_sample_pass():
    doc = _tagged()
    problems, notes = result_coverage([doc], _prereg(), headline_entry(doc, _prereg()))
    assert problems == [] and "every pre-registered hypothesis has a result (H1, H2)" in notes[0]


def test_a_missing_hypothesis_is_named():
    doc = _tagged(h2=False)
    problems, _ = result_coverage([doc], _prereg(), headline_entry(doc, _prereg()))
    assert problems == [
        "pre-registered hypothesis without a result: H2 (each result entry names the hypothesis it "
        "tests in a 'hypothesis' field)"
    ]


def test_a_part_counts_for_its_hypothesis():
    doc = {"a": {"hypothesis": "h1b", "coefficients": {}}, "b": {"hypothesis": "H2", "coefficients": {}}}
    assert result_coverage([doc], _prereg(), None)[0] == []


@pytest.mark.parametrize(
    ("exclusions", "problem"),
    [
        ([{"id": "fomc-2020-03-15", "reason": "emergency cut outside the scheduled calendar"}], None),
        ([{"ids": ["a", "b"], "reason": "no prices"}], "account for 2, not 1"),
        ([{"id": "fomc-2020-03-15"}], "without a reason"),
    ],
)
def test_a_smaller_sample_needs_declared_exclusions(exclusions: list[dict[str, Any]], problem: str | None):
    doc = {**_tagged(n=30), "exclusions": exclusions}
    problems, notes = result_coverage([doc], _prereg(), headline_entry(doc, _prereg()))
    if problem is None:
        assert problems == []
        assert "declared exclusions: fomc-2020-03-15: emergency cut outside the scheduled calendar" in notes
    else:
        assert any(problem in p for p in problems), problems


def test_more_observations_than_registered_fail():
    doc = _tagged(n=35)
    problems, _ = result_coverage([doc], _prereg(), headline_entry(doc, _prereg()))
    assert "35 observations, more than the 31 events registered" in problems[0]


def test_the_estimation_gate_runs_the_hypothesis_rule_when_a_preregistration_is_frozen(tmp_path: Path):
    assert check_preregistered_results(tmp_path, "estimation_results.json") is None  # nothing frozen
    _econometrics_workspace(tmp_path, _tagged(h2=False))
    for name in ("paper_plan.md", "event_design.json", "identification_spec.json"):
        shutil.copy(FOMC / name, tmp_path / name)
    assemble(tmp_path)
    freeze(tmp_path)
    found = check_results_against_preregistration(tmp_path)
    assert found is not None and "without a result: H2" in found[0][0]
    failed = [c for c in check_specialist_artifacts(tmp_path, "econometrics_specialist") if not c.ok]
    assert any("pre-registration: pre-registered hypothesis without a result: H2" in c.reason for c in failed)


def test_verify_reports_a_missing_hypothesis(tmp_path: Path):
    bundle = _verify_bundle(tmp_path, _tagged(h2=False), prereg=True)
    assert (bundle / "design" / "event_design.json").is_file()
    check = next(c for c in _run_checks(bundle, online=False) if c.name == "preregistration")
    assert check.status == FAIL and "without a result: H2" in check.detail


def test_verify_passes_a_study_that_follows_its_preregistration(tmp_path: Path):
    bundle = _verify_bundle(tmp_path, _tagged(), prereg=True)
    check = next(c for c in _run_checks(bundle, online=False) if c.name == "preregistration")
    assert check.status == PASS and "every pre-registered hypothesis has a result" in check.detail


# ══ 3. replication bundles verify offline ════════════════════════════════════


def _replication_workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    shutil.copytree(REPL, ws)
    logs = ws / "sandbox" / "logs"
    logs.mkdir(parents=True)
    (logs / "00-did_main.stdout.log").write_text("did_main finished\n")
    # A package file the run did not write: never exported as a result.
    shipped = ws / "sandbox" / "run" / "supplementary_elections_social_assistance" / "README.md"
    shipped.write_text("package readme\n")
    return ws


def _export(ws: Path, tmp_path: Path) -> Path:
    from src.core.export.structured import export_paper

    return export_paper(ws, tmp_path / "out", date_str="20260929")


def test_the_real_report_recomputes_to_12_2_3(tmp_path: Path):
    ws = _replication_workspace(tmp_path)
    log = _load(ws / "sandbox_log.json")
    doc = evaluate(_load(ws / "replication_plan.json"), _load(ws / "reproduction_report.json"), log, ws / "sandbox/run")
    assert doc["passed"], doc["reasons"]
    assert doc["stats"]["level_1"]["numbers"] == {"reproduced": 12, "reproduced_minor": 2, "not_reproduced": 3}
    assert doc["stats"]["level_1"]["results"] == {"reproduced": 6, "reproduced_minor": 2, "not_reproduced": 3}
    assert doc["summary"]["level_1"]["counts"] == "compared numbers"
    # The pipeline's check uses the same code and agrees.
    assert check_reproduction(ws).passed
    assert _load(ws / CHECK_FILE)["stats"]["level_1"]["numbers"]["reproduced"] == 12


def test_the_export_carries_the_run_outputs_and_logs(tmp_path: Path):
    bundle = _export(_replication_workspace(tmp_path), tmp_path)
    run = bundle / "sandbox" / "run" / "supplementary_elections_social_assistance"
    assert (run / "assistencia_social" / "output" / "data" / "resultados_did.csv").is_file()
    assert not (run / "README.md").exists()
    assert (bundle / "sandbox" / "logs" / "00-did_main.stdout.log").is_file()
    assert (bundle / "misc" / CHECK_FILE).is_file()
    files = _load(bundle / "provenance.json")["files"]
    assert "sandbox/logs/00-did_main.stdout.log" in files
    assert any(f.endswith("output/data/poder_mde.csv") for f in files)


def test_a_replication_bundle_is_verified(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    ws = _replication_workspace(tmp_path)
    # As in a run: the reproduction check (which writes the report's summary section) precedes the export.
    assert check_reproduction(ws).passed
    bundle = _export(ws, tmp_path)
    checks = {c.name: c for c in _run_checks(bundle, online=False)}
    assert checks["integrity"].status == PASS
    rep = checks["reproduction"]
    assert rep.status == PASS, rep.detail
    assert "17 compared number(s)" in rep.detail
    assert "level 1: 12 reproduced, 2 reproduced minor, 3 not reproduced" in rep.detail
    assert "summary counts agree" in rep.detail
    banner, code = _verdict(list(checks.values()))
    assert code == 0 and "verified" in banner and "reproduction" in banner
    assert verify(str(bundle), online=False) == 0


def test_an_edited_output_file_fails_the_reproduction_check(tmp_path: Path):
    bundle = _export(_replication_workspace(tmp_path), tmp_path)
    csv = next(bundle.rglob("resultados_did.csv"))
    csv.write_text(csv.read_text().replace("-0.00135097481805838", "-0.00235097481805838"))
    checks = {c.name: c for c in _run_checks(bundle, online=False)}
    assert checks["integrity"].status == FAIL
    assert checks["reproduction"].status == FAIL and "l1_tac_att_twfe_sem" in checks["reproduction"].detail


def test_a_summary_that_disagrees_with_the_numbers_fails(tmp_path: Path):
    ws = _replication_workspace(tmp_path)
    report = _load(ws / "reproduction_report.json")
    report["summary"]["level_1"]["reproduced"] = 13
    (ws / "reproduction_report.json").write_text(json.dumps(report))
    r = check_reproduction(ws)
    assert not r.passed and any("summary.level_1" in x for x in r.reasons)


def test_a_wrong_label_on_a_number_fails(tmp_path: Path):
    ws = _replication_workspace(tmp_path)
    report = _load(ws / "reproduction_report.json")
    comp = report["results"][0]["comparisons"][0]
    comp["label"] = "reproduced_minor"
    (ws / "reproduction_report.json").write_text(json.dumps(report))
    r = check_reproduction(ws)
    assert not r.passed and any("labelled 'reproduced_minor'" in x for x in r.reasons)


def test_an_older_replication_bundle_without_outputs_is_not_verified(tmp_path: Path):
    bundle = _export(_replication_workspace(tmp_path), tmp_path)
    shutil.rmtree(bundle / "sandbox")
    prov = _load(bundle / "provenance.json")
    prov["files"] = {k: v for k, v in prov["files"].items() if not k.startswith("sandbox/")}
    (bundle / "provenance.json").write_text(json.dumps(prov))
    check = next(c for c in _run_checks(bundle, online=False) if c.name == "reproduction")
    assert check.status == FAIL and "were not exported" in check.detail


def test_paper_bundles_have_no_reproduction_check(tmp_path: Path):
    bundle = _verify_bundle(tmp_path, {"main": {"coefficients": {"x": {"estimate": 1.0}}}})
    assert "reproduction" not in {c.name for c in _run_checks(bundle, online=False)}
    assert not (bundle / "sandbox").exists()


@pytest.mark.parametrize(
    ("value", "published", "dp", "label"),
    [
        (-0.01214, -0.012, 3, "reproduced"),
        (-0.0131, -0.012, 3, "reproduced_minor"),
        (-0.015, -0.012, 3, "not_reproduced"),
        (0.001, -0.0005, 4, "not_reproduced"),  # sign change
    ],
)
def test_label_for_uses_the_thresholds_of_the_check(value: float, published: float, dp: int, label: str):
    assert label_for(value, published, dp, 0.10)["label"] == label
