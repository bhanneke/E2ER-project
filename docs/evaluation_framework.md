# E2ER Quality Evaluation Framework

This document defines how pipeline output quality is measured across runs. It serves two purposes:
(1) internal quality tracking as the pipeline develops, and (2) the empirical evaluation basis for the companion system paper.

---

## 1. Evaluation dimensions

Each completed paper is scored on six dimensions, each 1–10. Scores are produced by two sources: **automated** (pipeline-internal) and **human** (researcher review).

| # | Dimension | What it measures |
|---|-----------|-----------------|
| 1 | **Identification validity** | Is the causal identification strategy credible? Does the paper correctly handle threats (OVB, reverse causality, SUTVA)? |
| 2 | **Empirical execution** | Is the data appropriate? Is the econometric specification correct? Are inference procedures (clustering, bootstrap) appropriate? |
| 3 | **Writing quality** | Is the paper well-structured, precise, and free of vague or redundant language? |
| 4 | **Literature grounding** | Are claims supported by citations? Does the paper correctly position itself in the literature? |
| 5 | **Replication integrity** | Can the key results be reproduced from the replication package? Are all data queries, estimation code, and parameters documented? |
| 6 | **Novelty** | Does the paper make a contribution that is not obvious from the prior literature? |

**Scoring guide:**

| Score | Interpretation |
|-------|---------------|
| 9–10 | Publication-ready at a top-3 venue |
| 7–8 | Strong paper; publishable with minor revision at a good venue |
| 5–6 | Competent but requires major revision |
| 3–4 | Fundamental problems; needs redesign |
| 1–2 | Output not usable |

---

## 2. Automated pipeline metrics

These are recorded automatically for every run and stored in the `pipeline_runs` evaluation log.

| Metric | Source | Notes |
|--------|--------|-------|
| `review_weighted_avg` | `review_aggregation.json` | Weighted average from 6 internal reviewers |
| `review_verdict` | `review_aggregation.json` | ACCEPT / MINOR_REVISION / MAJOR_REVISION / HARD_REJECT / MECHANISM_FAIL |
| `mechanism_score` | `review_mechanism.md` | Mechanism reviewer score (hard gate at < 5) |
| `self_attack_max_severity` | `self_attack_report.json` | Max severity finding from adversarial phase (1–10) |
| `self_attack_critical_count` | `self_attack_report.json` | Number of findings with severity ≥ 7 |
| `revision_rounds` | pipeline state | How many revision cycles were triggered |
| `stages_completed` | pipeline state | Fraction of planned stages that completed without error |
| `total_tokens` | `llm_usage` table | Total tokens across all specialist calls |
| `total_cost_usd` | `llm_usage` table | Total USD cost of the run |
| `runtime_minutes` | pipeline state | Wall-clock time from start to completion |
| `specialist_failure_count` | contributions log | Number of specialist calls that returned an error |

---

## 3. Human evaluation rubric

For each paper submitted for human evaluation, a researcher completes the following:

```
Paper ID: _______________
Evaluator: _______________
Date: _______________
Domain: _______________
Pipeline version: _______________

DIMENSION SCORES (1–10):
  Identification validity:    ___
  Empirical execution:        ___
  Writing quality:            ___
  Literature grounding:       ___
  Replication integrity:      ___
  Novelty:                    ___

OVERALL SCORE: ___ / 10

WOULD THIS PAPER BE DESK-REJECTED at a top-5 IS/econ journal?
  [ ] Yes — fundamental flaw  [ ] Possibly  [ ] No

MOST CRITICAL WEAKNESS (one sentence):
_______________________________________________

STRONGEST ELEMENT (one sentence):
_______________________________________________

NOTES:
_______________________________________________
```

---

## 4. Comparison protocol

To benchmark pipeline versions and domains against each other, use the following protocol:

1. **Same RQ, different versions** — run the same research question through v1, v2, and v3; score each output on all 6 dimensions; compute improvement deltas
2. **Same version, different domains** — run v3 on RQs from 3+ domains; score each; identify where the pipeline performs well vs. poorly
3. **Pipeline vs. baseline** — compare a pipeline draft against a human-written draft on the same RQ (blind scoring by a third-party researcher)

All comparison runs should be logged in `docs/evaluation_log.csv` (see template below).

---

## 5. Evaluation log format

`docs/evaluation_log.csv` tracks all evaluated runs:

```
run_id, paper_id, pipeline_version, domain, rq_summary,
score_identification, score_empirical, score_writing, score_literature, score_replication, score_novelty,
human_overall, review_weighted_avg, review_verdict,
self_attack_max_severity, revision_rounds, total_cost_usd, runtime_minutes,
evaluator, evaluation_date, notes
```

---

## 6. Target benchmarks (v3)

These are the quality targets for v3 to be considered ready for the companion paper submission:

| Metric | Target |
|--------|--------|
| Human overall score (mean across runs) | ≥ 6.5 / 10 |
| Fraction reaching ACCEPT or MINOR_REVISION verdict | ≥ 60% |
| Fraction desk-rejected by human evaluator | ≤ 20% |
| Replication integrity score (mean) | ≥ 7.0 / 10 |
| Mechanism score (mean) | ≥ 6.0 / 10 |
| Stage completion rate | ≥ 90% |

Targets are provisional and will be updated as baseline data from early runs accumulates.

---

## 7. Open questions for the companion paper

- How does automated review score correlation with human evaluation score vary by domain?
- What is the marginal value of the self-attack and polish stages (v3 additions) measured in score improvement vs. token cost?
- Which pipeline stage produces the most variance in output quality?
- Does ceiling detection correctly identify when further iteration adds value?
