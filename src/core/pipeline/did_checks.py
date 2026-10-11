"""The checks of a difference-in-differences policy evaluation, before and after estimation.

A policy evaluation by difference-in-differences stands on its design: which
units were treated when, which units they are compared with, and an estimator
that suits the timing. Two checks hold a study of the ``policy-evaluation``
template to it.

``did_design`` (before estimation) reads ``did_design.json``, which the
identification strategist writes (schema: skills/files/econometrics/did-practice.md),
and the panel in ``data.db``. It fails when

  (a) the design names no outcome, panel or treatment timing that the data hold;
  (b) there is no comparison group: no never-treated unit for a design that
      compares with the never treated, no unit treated later for one that
      compares with the not yet treated;
  (c) the timing is staggered (units start treatment in two or more periods)
      and the estimator is two-way fixed effects, whose estimate is a weighted
      average of comparisons that can carry negative weights when effects
      differ across cohorts or over time (Goodman-Bacon 2021; de Chaisemartin
      and D'Haultfœuille 2020): the design must name a heterogeneity-robust
      estimator (Callaway and Sant'Anna 2021, Sun and Abraham 2021, ...). A
      staggered design with a robust estimator passes with a warning;
  (d) no cohort has ``min_pre_periods`` periods before treatment, so the
      pre-trends cannot be seen.

It writes what it found (cohorts, treated and comparison units, periods) to
``did_design_check.json``.

``did_results`` (after estimation, before drafting) reads
``estimation_results.json`` and fails when

  (e) the results carry no event-study path with at least ``min_pre_periods``
      pre-treatment periods besides the reference period;
  (f) no joint test of the pre-treatment coefficients is reported, or it
      rejects at ``pretrend_alpha`` and no sensitivity analysis for
      violations of parallel trends (Rambachan and Roth 2023) is reported;
  (g) neither a placebo test nor a sensitivity analysis is reported;
  (h) the headline estimate does not name the declared estimator, or uses
      two-way fixed effects on staggered timing.

The event-study plot is drawn from the results: when ``figure_spec.json``
holds no event-study figure, the check adds one built from the results'
path; an event-study figure whose numbers differ from the results fails the
check. It writes its findings to ``did_check.json``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .checks_common import Verdict, close, lst, names, num, obj, read_columns, read_json, to_float, write_json

DESIGN_FILE = "did_design.json"
DESIGN_CHECK_FILE = "did_design_check.json"
RESULTS_CHECK_FILE = "did_check.json"
EVENT_FIGURE = "fig_event_study.pdf"
#: Marks a figure this module drew, so a later run of the check draws it again from the results.
_DRAWN_BY = "drawn by e2er's did_results check"

#: Defaults, each overridable in the template (`[steps.settings]` of the gate).
DEFAULTS: dict[str, float] = {"min_pre_periods": 2, "pretrend_alpha": 0.05}

#: Estimators that stay valid when treatment effects differ across cohorts and over time,
#: by e2er's name, with the spellings a design may use.
ROBUST_ESTIMATORS: dict[str, tuple[str, ...]] = {
    "callaway_santanna": ("callawaysantanna", "cs", "csdid", "attgt", "callawaysantanna2021"),
    "sun_abraham": ("sunabraham", "sa", "interactionweighted", "iw", "sunabraham2021"),
    "de_chaisemartin_dhaultfoeuille": (
        "dechaisemartindhaultfoeuille",
        "dechaisemartindhaultfuille",
        "dcdh",
        "didmultiplegt",
        "didl",
    ),
    "borusyak_jaravel_spiess": ("borusyakjaravelspiess", "bjs", "imputation", "didimputation"),
    "gardner_two_stage": ("gardnertwostage", "did2s", "twostagedid", "gardner"),
    "stacked": ("stacked", "stackeddid", "stackedregression"),
    "wooldridge_etwfe": ("wooldridgeetwfe", "etwfe", "extendedtwfe", "wooldridge"),
}
#: Two-way fixed effects: fine for a single treatment date, not for staggered timing.
TWFE_SPELLINGS: tuple[str, ...] = ("twfe", "twowayfixedeffects", "twowayfe", "olstwfe", "twfeols", "did", "ols")
COMPARISON_GROUPS = ("never_treated", "not_yet_treated")
#: Words that mark a sensitivity analysis for violations of parallel trends.
_PT_SENSITIVITY = re.compile(r"rambachan|honest|relative[ _-]?magnitude|smoothness|breakdown", re.I)


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower().replace("œ", "oe"))


def estimator_name(value: Any) -> str | None:
    """e2er's name of an estimator (a robust one, or ``twfe``), None when unknown."""
    key = _norm(value)
    if not key:
        return None
    for name, spellings in ROBUST_ESTIMATORS.items():
        if key == _norm(name) or key in spellings:
            return name
    if key in TWFE_SPELLINGS:
        return "twfe"
    return None


def _period_key(values: list[Any]) -> tuple[dict[Any, float], bool]:
    """Each period's position on one axis: its value when every period is a number, else its rank."""
    distinct = sorted({v for v in values if v is not None and str(v).strip() != ""}, key=lambda v: str(v))
    nums = {v: to_float(v) for v in distinct}
    if distinct and all(x is not None for x in nums.values()):
        return {v: float(x) for v, x in nums.items() if x is not None}, True
    return {v: float(i) for i, v in enumerate(sorted(distinct, key=str))}, False


# ── before estimation ────────────────────────────────────────────────────────


def check_did_design(workspace: Path, *, min_pre_periods: int = int(DEFAULTS["min_pre_periods"])) -> Verdict:
    """Check ``did_design.json`` against the panel in data.db: rules (a) to (d)."""
    ws = Path(workspace)
    design, err = read_json(ws / DESIGN_FILE)
    if err:
        return Verdict(False, (f"(a) {err}: the identification strategist declares the design there",))
    if not isinstance(design, dict):
        return Verdict(False, (f"(a) {DESIGN_FILE} must be a JSON object",))

    reasons: list[str] = []
    notes: list[str] = []
    stats: dict[str, Any] = {}

    panel = obj(design.get("panel"))
    outcome = obj(design.get("outcome"))
    treatment = obj(design.get("treatment"))
    p_table, unit, time = panel.get("table"), panel.get("unit"), panel.get("time")
    o_table = outcome.get("table") or p_table
    o_col = outcome.get("column")
    t_table = treatment.get("table") or p_table
    t_unit = treatment.get("unit") or unit
    first = treatment.get("first_treated")
    if not (p_table and unit and time):
        reasons.append("(a) panel needs table, unit and time (the columns of the panel in data.db)")
    if not o_col:
        reasons.append("(a) outcome needs column (and table, when it is not the panel's)")
    if not first:
        reasons.append(
            "(a) treatment needs first_treated: the column with the first treated period of each unit "
            "(empty, 0 or null for a unit never treated)"
        )
    comparison = str(design.get("comparison_group") or "").strip().lower().replace("-", "_").replace(" ", "_")
    if comparison not in COMPARISON_GROUPS:
        reasons.append(f"(b) comparison_group must be one of {', '.join(COMPARISON_GROUPS)}")
    raw_est = design.get("estimator")
    est = estimator_name(raw_est)
    if est is None:
        reasons.append(
            f"(c) estimator {raw_est!r} is not one e2er knows; name one of " + ", ".join([*ROBUST_ESTIMATORS, "twfe"])
        )
    if reasons:
        return Verdict(False, tuple(reasons))

    rows, why = read_columns(ws, o_table, [unit, time, o_col])
    if rows is None:
        return Verdict(False, (f"(a) outcome: {why}",))
    trows, why = read_columns(ws, t_table, [t_unit, first])
    if trows is None:
        return Verdict(False, (f"(a) treatment timing: {why}",))

    observed = [(u, t, y) for u, t, y in rows if u is not None and t is not None]
    with_outcome = [(u, t) for u, t, y in observed if to_float(y) is not None]
    if not with_outcome:
        return Verdict(False, (f"(a) {o_table}.{o_col} holds no numeric outcome",))
    position, numeric_time = _period_key([t for _u, t in with_outcome])
    periods = sorted(set(position.values()))
    units = sorted({str(u) for u, _t in with_outcome})
    stats.update({"units": len(units), "periods": len(periods), "observations": len(with_outcome)})
    stats["first_period"], stats["last_period"] = _label(periods[0]), _label(periods[-1])

    # Each unit's first treated period, on the panel's time axis.
    timing: dict[str, float | None] = {}
    conflicting: list[str] = []
    off_axis: list[str] = []
    for u, g in trows:
        if u is None:
            continue
        key = str(u)
        gnum = None if g is None or str(g).strip() in ("", "0", "0.0", "nan", "None") else g
        if gnum is not None:
            if numeric_time:
                gnum = to_float(gnum)
                if gnum is None:
                    off_axis.append(key)
                    continue
            else:
                gnum = position.get(gnum)
                if gnum is None:
                    off_axis.append(key)
                    continue
        if key in timing and timing[key] != gnum:
            conflicting.append(key)
        timing[key] = gnum
    if conflicting:
        reasons.append(
            f"(a) {t_table}.{first} gives units more than one first treated period: {names(sorted(set(conflicting)))}"
        )
    if off_axis:
        reasons.append(f"(a) the first treated period of {names(off_axis)} is not a period of the panel's {time}")

    in_panel = set(units)
    not_in_panel = sorted(u for u in timing if u not in in_panel)
    if not_in_panel:
        notes.append(f"units in the treatment table without outcome data: {names(not_in_panel)}")
    cohorts: dict[float, list[str]] = {}
    never: list[str] = []
    always: list[str] = []
    after_end: list[str] = []
    for u in units:
        g = timing.get(u)
        if g is None:
            never.append(u)
        elif g <= periods[0]:
            always.append(u)
        elif g > periods[-1]:
            after_end.append(u)
        else:
            cohorts.setdefault(g, []).append(u)
    missing_timing = [u for u in units if u not in timing]
    if missing_timing:
        notes.append(
            f"{len(missing_timing)} panel unit(s) are not in the treatment table and count as never treated: "
            + names(missing_timing)
        )
    if always:
        notes.append(
            f"{len(always)} unit(s) are treated from the first period on, have no pre-treatment period and "
            f"drop out of the comparison: {names(always)}"
        )
    if after_end:
        notes.append(f"{len(after_end)} unit(s) are first treated after the panel ends and count as never treated")
        never += after_end
    stats.update(
        {
            "treated_units": sum(len(v) for v in cohorts.values()),
            "never_treated_units": len(never),
            "cohorts": len(cohorts),
        }
    )
    if not cohorts:
        reasons.append("(a) no unit is treated inside the panel: there is nothing to evaluate")

    # (b) the comparison group
    if comparison == "never_treated" and not never:
        reasons.append(
            "(b) the design compares with the never treated, but every unit is treated inside the panel; "
            "compare with the not yet treated or extend the panel"
        )
    if comparison == "not_yet_treated" and len(cohorts) < 2 and not never:
        reasons.append("(b) every treated unit starts in the same period, so no unit is treated later to compare with")

    # (c) staggered timing and the estimator
    staggered = len(cohorts) >= 2
    stats["staggered"] = staggered
    stats["estimator"] = est
    if staggered:
        shown = ", ".join(f"{_label(g)} ({len(us)})" for g, us in sorted(cohorts.items()))
        if est == "twfe":
            reasons.append(
                f"(c) treatment timing is staggered ({len(cohorts)} cohorts: {shown}). A two-way fixed-effects "
                "estimate then averages comparisons that use earlier-treated units as controls, with weights "
                "that can be negative when effects differ across cohorts or over time (Goodman-Bacon 2021; "
                "de Chaisemartin and D'Haultfoeuille 2020). Declare a heterogeneity-robust estimator: "
                "callaway_santanna, sun_abraham, de_chaisemartin_dhaultfoeuille, borusyak_jaravel_spiess, "
                "gardner_two_stage, stacked or wooldridge_etwfe"
            )
        else:
            notes.append(
                f"warning: treatment timing is staggered ({len(cohorts)} cohorts: {shown}); the estimator "
                f"{est} is robust to effects that differ across cohorts and over time; report effects by "
                "event time and the aggregation used"
            )

    # (d) pre-treatment periods
    pre = {g: sum(1 for p in periods if p < g) for g in cohorts}
    if cohorts:
        best = max(pre.values())
        stats["max_pre_periods"] = best
        if best < min_pre_periods:
            reasons.append(
                f"(d) no cohort has {min_pre_periods} periods before its treatment (at most {best}), so "
                "pre-treatment trends cannot be seen; extend the panel backwards"
            )
        short = sorted(_label(g) for g, n in pre.items() if n < min_pre_periods)
        if short and best >= min_pre_periods:
            notes.append(
                f"cohort(s) {', '.join(str(c) for c in short)} have fewer than {min_pre_periods} "
                "pre-treatment periods; their leads are missing from the event study"
            )

    found = {
        "design": DESIGN_FILE,
        "comparison_group": comparison,
        "estimator": est,
        "staggered": staggered,
        "units": len(units),
        "periods": [_label(p) for p in periods],
        "cohorts": {_label(g): sorted(us) for g, us in sorted(cohorts.items())},
        "never_treated": sorted(never),
        "always_treated": sorted(always),
        "pre_periods_by_cohort": {_label(g): n for g, n in sorted(pre.items())},
        "passed": not reasons,
        "reasons": reasons,
        "notes": notes,
    }
    write_json(ws / DESIGN_CHECK_FILE, found)
    return Verdict(not reasons, tuple(reasons), tuple(notes), stats)


def _p(p: float) -> str:
    return "p < 0.0001" if p < 0.0001 else f"p = {p:.4g}"


def _label(x: float) -> Any:
    return int(x) if float(x).is_integer() else x


# ── after estimation ─────────────────────────────────────────────────────────


def _event_path(results: dict[str, Any]) -> tuple[list[dict[str, Any]], float | None, list[str]]:
    """(periods with numeric estimates, reference period, problems) of the results' event study."""
    es = results.get("event_study")
    if not isinstance(es, dict):
        return [], None, ["(e) estimation_results.json has no 'event_study' block (the dynamic effects by event time)"]
    ref = num(es.get("reference_period"))
    raw = es.get("periods")
    if not isinstance(raw, list) or not raw:
        return [], ref, ["(e) event_study.periods must list the estimate of each event time"]
    out: list[dict[str, Any]] = []
    for i, p in enumerate(raw):
        rel, est = num((p or {}).get("relative_period")), num((p or {}).get("estimate"))
        if rel is None or est is None:
            return [], ref, [f"(e) event_study.periods[{i}] needs a numeric relative_period and estimate"]
        out.append(p)
    return sorted(out, key=lambda p: float(p["relative_period"])), ref, []


def _entries(value: Any) -> dict[str, dict[str, Any]]:
    if isinstance(value, dict):
        return {str(k): v for k, v in value.items() if isinstance(v, dict)}
    if isinstance(value, list):
        return {str(v.get("name") or i): v for i, v in enumerate(value) if isinstance(v, dict)}
    return {}


def _figure_from_path(path: list[dict[str, Any]], ref: float | None, results: dict[str, Any]) -> dict[str, Any]:
    es = results.get("event_study") or {}
    fig: dict[str, Any] = {
        "filename": EVENT_FIGURE,
        "figure_type": "event_study",
        "title": str(es.get("title") or "Effect by period relative to treatment"),
        "periods": [float(p["relative_period"]) for p in path],
        "estimates": [float(p["estimate"]) for p in path],
        "x_label": str(es.get("x_label") or "Periods relative to treatment"),
        "y_label": str(es.get("y_label") or "Estimated effect"),
        "treatment_period": -0.5,
        "source": f"estimation_results.json#event_study ({_DRAWN_BY})",
    }
    lo = [num(p.get("ci_lower")) for p in path]
    hi = [num(p.get("ci_upper")) for p in path]
    if all(x is not None for x in lo + hi):
        fig["ci_lower"], fig["ci_upper"] = lo, hi
    return fig


def check_did_results(
    workspace: Path,
    *,
    min_pre_periods: int = int(DEFAULTS["min_pre_periods"]),
    pretrend_alpha: float = DEFAULTS["pretrend_alpha"],
) -> Verdict:
    """Check the estimation results of a DiD study: rules (e) to (h); draw the event-study plot."""
    ws = Path(workspace)
    results, err = read_json(ws / "estimation_results.json")
    if err:
        return Verdict(False, (f"(e) {err}",))
    if not isinstance(results, dict) or not results:
        return Verdict(False, ("(e) estimation_results.json is empty",))
    design, _ = read_json(ws / DESIGN_FILE)
    design = design if isinstance(design, dict) else {}
    found, _ = read_json(ws / DESIGN_CHECK_FILE)
    found = found if isinstance(found, dict) else {}

    reasons: list[str] = []
    notes: list[str] = []
    stats: dict[str, Any] = {}

    # (e) the event-study path
    path, ref, problems = _event_path(results)
    reasons += problems
    if path:
        leads = [p for p in path if float(p["relative_period"]) < 0 and float(p["relative_period"]) != ref]
        lags = [p for p in path if float(p["relative_period"]) >= 0]
        stats.update({"pre_periods": len(leads), "post_periods": len(lags)})
        if len(leads) < min_pre_periods:
            reasons.append(
                f"(e) the event study has {len(leads)} pre-treatment period(s) besides the reference period; "
                f"at least {min_pre_periods} are needed to see pre-trends"
            )
        if not lags:
            reasons.append("(e) the event study has no period at or after treatment")

    # (f) the pre-trends test
    pt = results.get("pre_trends")
    sens = _entries(results.get("sensitivity"))
    pt_sens = [k for k, v in sens.items() if _PT_SENSITIVITY.search(f"{k} {v.get('method', '')}")]
    if not isinstance(pt, dict):
        reasons.append(
            "(f) estimation_results.json has no 'pre_trends' block: report the joint test that the "
            "pre-treatment coefficients are zero (test, statistic, df, p_value, n_pre_periods)"
        )
    else:
        p = num(pt.get("p_value"))
        if p is None or not 0 <= p <= 1:
            reasons.append("(f) pre_trends.p_value must be a number between 0 and 1")
        else:
            stats["pre_trends_p"] = round(p, 4)
            n_pre = num(pt.get("n_pre_periods"))
            if path and n_pre is not None:
                leads_n = sum(1 for q in path if float(q["relative_period"]) < 0 and float(q["relative_period"]) != ref)
                if int(n_pre) != leads_n:
                    reasons.append(
                        f"(f) pre_trends.n_pre_periods is {int(n_pre)}, but the event study has {leads_n} "
                        "pre-treatment periods besides the reference period"
                    )
            if p < pretrend_alpha:
                if pt_sens:
                    notes.append(
                        f"warning: the pre-treatment coefficients are jointly different from zero "
                        f"({_p(p)}, below {pretrend_alpha}); the conclusion must rest on the sensitivity analysis "
                        f"({', '.join(pt_sens)}), and the paper must say so"
                    )
                else:
                    reasons.append(
                        f"(f) the pre-treatment coefficients are jointly different from zero ({_p(p)}, below "
                        f"{pretrend_alpha}): parallel trends is contradicted by the study's own data. Change the "
                        "design (comparison group, sample, covariates) or report a sensitivity analysis for "
                        "violations of parallel trends (Rambachan and Roth 2023: relative magnitudes or "
                        "smoothness bounds) under 'sensitivity' and draw conclusions from it"
                    )
            elif p < 0.2:
                notes.append(
                    f"the pre-trends test does not reject at {pretrend_alpha} (p = {p:.4g}), which is not evidence "
                    "of parallel trends (Roth 2022); a sensitivity analysis is advisable"
                )

    # (g) placebo or sensitivity
    placebo = _entries(results.get("placebo"))
    stats["placebo"] = len(placebo)
    stats["sensitivity"] = len(sens)
    if not placebo and not sens:
        reasons.append(
            "(g) report a placebo test ('placebo': a fake treatment date or an outcome the policy cannot "
            "affect) or a sensitivity analysis ('sensitivity': e.g. bounds on violations of parallel trends, "
            "another comparison group, anticipation)"
        )
    for k, v in placebo.items():
        if num(v.get("estimate")) is None:
            reasons.append(f"(g) placebo.{k} needs a numeric estimate (and se or a confidence interval)")
            break

    # (h) the headline estimator
    main = obj(results.get("main")) or None
    declared = estimator_name(design.get("estimator"))
    if main is None:
        reasons.append("(h) estimation_results.json has no 'main' entry (the headline ATT)")
    else:
        reported = estimator_name(main.get("estimator"))
        if reported is None:
            reasons.append(
                "(h) main.estimator must name the estimator used (e.g. callaway_santanna); "
                f"it says {main.get('estimator')!r}"
            )
        elif declared and reported != declared:
            reasons.append(f"(h) main.estimator is {reported}, but did_design.json declares {declared}")
        staggered = bool(found.get("staggered"))
        if staggered and reported == "twfe":
            reasons.append("(h) the timing is staggered, but the headline estimate uses two-way fixed effects")
        stats["estimator"] = reported

    # The event-study plot, from the results.
    if path:
        figure_problem = _ensure_event_figure(ws, path, ref, results, notes)
        if figure_problem:
            reasons.append(figure_problem)

    write_json(
        ws / RESULTS_CHECK_FILE,
        {"passed": not reasons, "reasons": reasons, "notes": notes, "stats": stats, "pretrend_alpha": pretrend_alpha},
    )
    return Verdict(not reasons, tuple(reasons), tuple(notes), stats)


def _ensure_event_figure(
    ws: Path, path: list[dict[str, Any]], ref: float | None, results: dict[str, Any], notes: list[str]
) -> str | None:
    """Add the event-study figure built from the results, or check the one there; a problem or None."""
    spec_path = ws / "figure_spec.json"
    spec, err = read_json(spec_path)
    if spec is None and spec_path.is_file():
        return f"(e) {err}"
    spec = spec if isinstance(spec, dict) else {}
    figures = lst(spec.get("figures"))
    want = _figure_from_path(path, ref, results)
    # A figure this check drew earlier is drawn again from the results as they are now.
    ours = [f for f in figures if isinstance(f, dict) and _DRAWN_BY in str(f.get("source") or "")]
    if ours:
        spec["figures"] = [want if f is ours[0] else f for f in figures if f is ours[0] or f not in ours]
        write_json(spec_path, spec)
        return None
    existing = [f for f in figures if isinstance(f, dict) and f.get("figure_type") == "event_study"]
    if not existing:
        spec["figures"] = [*figures, want]
        write_json(spec_path, spec)
        notes.append(f"the event-study plot {EVENT_FIGURE} was added to figure_spec.json from the results")
        return None
    for f in existing:
        periods, estimates = f.get("periods"), f.get("estimates")
        if not isinstance(periods, list) or not isinstance(estimates, list) or len(periods) != len(estimates):
            return f"(e) the event-study figure {f.get('filename')} needs equal-length periods and estimates"
        shown = {to_float(p): to_float(e) for p, e in zip(periods, estimates, strict=True)}
        for p in path:
            got = shown.get(float(p["relative_period"]))
            if got is None or not close(got, float(p["estimate"]), rel=0.01, abs_=1e-6):
                return (
                    f"(e) the event-study figure {f.get('filename')} does not show the results' estimate for "
                    f"period {p['relative_period']} ({p['estimate']}); draw it from estimation_results.json"
                )
    return None
