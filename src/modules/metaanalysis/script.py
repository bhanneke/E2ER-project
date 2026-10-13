"""The study's ``run_estimation.py``: e2er's meta-analysis code, written into the workspace and run there.

The synthesis step writes the script from two parts: the source of
``stats.py`` (numpy and scipy only) and ``MAIN`` below, which reads the
checked extraction (``meta_studies.csv``), the protocol's synthesis settings
(``review_protocol.json``) and the flow counts (``prisma_counts.json``) and
writes ``estimation_results.json``. The script imports nothing from e2er, so
``e2er reproduce`` reruns it as it is.
"""

from __future__ import annotations

import inspect
import re

from . import stats

SCRIPT = "run_estimation.py"

HEADER = '''"""Random-effects meta-analysis of the studies in meta_studies.csv (written by e2er).

Reads meta_studies.csv (the extracted effects, each number traced to its
source by e2er's extraction check), review_protocol.json (effect measure and
synthesis settings) and prisma_counts.json (the flow of records); writes
estimation_results.json (result_kind "metaanalysis"). numpy and scipy only.
"""

from __future__ import annotations
'''

MAIN = """

# ── the study ───────────────────────────────────────────────────────────────

import csv
import json


def _row_effect(row):
    keys = ("value", "se", "ci_lower", "ci_upper", "n", "n1", "n2", "mean1", "sd1", "mean2", "sd2", "ci_level")
    return {k: float(row[k]) for k in keys if (row.get(k) or "").strip()}


def _n(row):
    if (row.get("n") or "").strip():
        return int(float(row["n"]))
    if (row.get("n1") or "").strip() and (row.get("n2") or "").strip():
        return int(float(row["n1"])) + int(float(row["n2"]))
    return None


def main():
    with open("review_protocol.json", encoding="utf-8") as f:
        protocol = json.load(f)
    with open("prisma_counts.json", encoding="utf-8") as f:
        prisma = json.load(f)
    with open("meta_studies.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    measure = protocol["effect_measure"]
    syn = protocol.get("synthesis") or {}
    method = syn.get("tau2_method", "REML")
    level = float(syn.get("ci_level", 0.95))
    min_studies = int(syn.get("min_studies", 3))

    ids, labels, y, v, studies = [], [], [], [], []
    zc = _zcrit(level)
    for row in rows:
        yi, vi, how = effect_on_scale(_row_effect(row), measure)
        se = math.sqrt(vi)
        ids.append(row["id"])
        labels.append(row["label"])
        y.append(yi)
        v.append(vi)
        studies.append(
            {
                "id": row["id"],
                "label": row["label"],
                "year": int(row["year"]) if (row.get("year") or "").strip() else None,
                "yi": yi,
                "vi": vi,
                "se": se,
                "ci_lower": yi - zc * se,
                "ci_upper": yi + zc * se,
                "n": _n(row),
                "estimate_reported_scale": back_transform(measure, yi),
                "ci_lower_reported_scale": back_transform(measure, yi - zc * se),
                "ci_upper_reported_scale": back_transform(measure, yi + zc * se),
                "computed": how,
                "risk_of_bias": row.get("rob_overall") or "",
            }
        )
    k = len(studies)
    results = {
        "result_kind": "metaanalysis",
        "question": protocol.get("question", ""),
        "outcome": (protocol.get("outcome") or {}).get("name", ""),
        "effect_measure": measure,
        "analysis_scale": analysis_scale(measure),
        "effect_direction": protocol.get("effect_direction", ""),
        "model": {"type": "random effects", "tau2_method": method, "ci_level": level, "min_studies": min_studies},
        "k": k,
        "studies": studies,
        "prisma": prisma,
        "figures": ["fig_prisma.pdf"],
    }
    if k < min_studies:
        results["narrative_only"] = True
        results["narrative_reason"] = (
            f"{k} {'study reports' if k == 1 else 'studies report'} an effect that can be pooled; the protocol "
            f"requires at least {min_studies} for a meta-analysis, so the studies are described, not pooled"
        )
        results["pooled"] = None
    else:
        r = pool(y, v, method=method, level=level)
        for s, w in zip(studies, r["weights_percent"]):
            s["weight_percent"] = w
        results["narrative_only"] = False
        results["pooled"] = {
            "estimate": r["estimate"],
            "se": r["se"],
            "z": r["z"],
            "p_value": r["p_value"],
            "ci_lower": r["ci_lower"],
            "ci_upper": r["ci_upper"],
            "estimate_reported_scale": back_transform(measure, r["estimate"]),
            "ci_lower_reported_scale": back_transform(measure, r["ci_lower"]),
            "ci_upper_reported_scale": back_transform(measure, r["ci_upper"]),
        }
        results["heterogeneity"] = {
            "tau2": r["tau2"],
            "tau": r["tau"],
            "tau2_method": method,
            "tau2_converged": r["tau2_converged"],
            "i2": r["i2"],
            "h2": r["h2"],
            "q": r["q"],
            "q_df": r["q_df"],
            "q_p_value": r["q_p_value"],
        }
        pi = r["prediction_interval"]
        if pi is not None:
            pi = dict(pi)
            pi["lower_reported_scale"] = back_transform(measure, pi["lower"])
            pi["upper_reported_scale"] = back_transform(measure, pi["upper"])
        results["prediction_interval"] = pi
        results["fixed_effect"] = r["fixed_effect"]
        e = egger(y, v)
        if "skipped" not in e:
            e["low_power"] = k < 10
        tf = trim_and_fill(y, v, method=method, level=level)
        results["small_study_effects"] = {"egger": e, "trim_and_fill": tf}
        results["leave_one_out"] = leave_one_out(y, v, ids, method=method, level=level)
        results["figures"] = ["fig_forest.pdf", "fig_funnel.pdf", "fig_prisma.pdf"]
    with open("estimation_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    main()
"""


def stats_source() -> str:
    """stats.py without its module docstring and future import (the script has its own)."""
    src = inspect.getsource(stats)
    src = re.sub(r'^""".*?"""\n', "", src, count=1, flags=re.S)
    src = src.replace("from __future__ import annotations\n", "", 1)
    return "\n# ── e2er's meta-analysis code (src/modules/metaanalysis/stats.py) ──────────\n" + src.lstrip("\n")


def build() -> str:
    return HEADER + stats_source() + MAIN
