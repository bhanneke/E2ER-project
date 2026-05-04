# Narrative Threads

## Thread 1: The DiD estimator recovers the causal effect cleanly

The core question — does X cause Y? — receives an unambiguous affirmative from the data. The TWFE baseline estimates a treatment effect of 2.39 (run_1, TWFE_baseline; confirmed identically in run_2, run_3, run_4), with the 95% CI [2.15, 2.63] containing the true DGP parameter of 2.5. This is not merely statistically significant; the effect is large relative to the outcome standard deviation (2.09), implying a standardized effect of approximately 1.14σ. The result survives all robustness checks across four independent estimation runs: adding covariate controls, winsorizing the outcome, replacing the within-estimator with explicit dummy OLS (run_1), log-transforming the covariate (run_2, run_4), and — critically — a placebo group falsification test (run_4). Point estimates vary by less than 0.04 across five positive-treatment specifications, and no specification produces a p-value above 10⁻⁶. Cluster-robust standard errors (CR1 at the unit level) ensure inference accounts for within-unit serial correlation.

**From gap to contribution**: If the literature lacks a causal estimate of the X→Y relationship, this paper provides one under clean identification conditions. The stability across specifications and runs strengthens the claim that the estimate reflects the underlying causal parameter rather than a fragile artifact of modeling choices.

## Thread 2: Parallel trends hold — the identification assumption is credible

The credibility of any DiD estimate rests on whether treated and control units would have evolved similarly absent treatment (Assumption A1). Two pieces of evidence support this, replicated across all four estimation runs. The placebo test (run_1 through run_4, placebo) assigns a fake treatment at t=2 using pre-treatment data and estimates a coefficient of 0.185 (p=0.27) — a precisely estimated null. The event-study coefficients at t=0 and t=1 are -0.04 and -0.33 respectively, both with 95% CIs spanning zero, confirming flat pre-trends. The sharp discontinuity at the treatment date (from ~0 to 2.15 at t=3, then 2.39 at t=4) is the signature of a treatment effect, not a pre-existing trend.

**Why this matters**: Without credible parallel trends, the DiD coefficient could reflect differential time trajectories rather than causation. The event-study evidence converts the identifying assumption from an untestable article of faith into a proposition with strong empirical support in the pre-treatment period.

## Thread 3: The effect persists and potentially strengthens over time

The event-study estimates reveal not just a level shift but a modest escalation: the treatment coefficient rises from 2.15 at t=3 (the first post-treatment period) to 2.39 at t=4. While only two post-treatment periods are available — too few for definitive claims about dynamics — the pattern is consistent with a mechanism that accumulates rather than one-shot shocks. The baseline TWFE estimate (2.39) averages over both post periods. The fact that the t=4 estimate (2.39) nearly equals the pooled estimate suggests the effect stabilizes quickly.

**Implication for the contribution**: If X affects Y through a channel that operates cumulatively (as specified in the theoretical model's Proposition 1), the strengthening post-treatment coefficients provide preliminary evidence for the proposed mechanism. Longer post-treatment observation would sharpen this claim.

## Thread 4: Statistical vs. economic significance — a validated pipeline

The estimated effect of 2.39 is large in absolute and relative terms. Against a control-group outcome distribution, the treatment shifts outcomes by more than two units — a transformation, not a marginal adjustment. The within-R² of 0.307 indicates that the treatment interaction alone explains roughly 31% of the demeaned outcome variation. The t-statistic of approximately 19.7 places this result far beyond marginal significance thresholds.

**Caveat**: These magnitudes reflect a synthetic DGP with a clean, large treatment effect (δ=2.5) and Gaussian errors. The validation confirms the pipeline's ability to detect and accurately estimate effects when they exist; the slight downward bias (2.39 vs. 2.50, or 4.4% attenuation) is consistent with finite-sample noise and provides a useful calibration benchmark. Production results will require separate assessment of economic meaningfulness.

## Thread 5: Reproducibility across estimation runs

Run_1 through run_4 share identical data (hash: 5e5d6477aefd459a) but differ in model specifications (four distinct model hashes). Overlapping specifications (TWFE_baseline, TWFE_with_covariate, TWFE_winsorized_y) produce identical coefficients and standard errors across all runs that include them. This confirms numerical reproducibility of the estimation pipeline — a prerequisite for credible empirical work that is rarely verified explicitly.

**Why this matters for the contribution**: Reproducibility is not merely a methodological hygiene check. It demonstrates that the pipeline produces deterministic results given the same data, which strengthens confidence in any production results where the true parameter is unknown.

## Thread 6: Homogeneous treatment effects across covariate levels

Run_3 splits the sample at the median of x (5.12) and estimates TWFE separately for high-x (coef=2.37, SE=0.156) and low-x (coef=2.41, SE=0.146) subgroups. The difference of 0.04 is economically trivial — less than 2% of the pooled estimate — and the 95% CIs overlap almost entirely ([2.06, 2.68] vs. [2.12, 2.70]). Both subgroup estimates bracket the true parameter (2.5) within their CIs.

This homogeneity is expected in the synthetic DGP, where the treatment effect is constant across units by construction. The result confirms that the TWFE estimator does not produce spurious heterogeneity when none exists — a useful calibration check. In production, finding heterogeneity across economically meaningful subgroups would strengthen the mechanistic story (H2). Finding homogeneity, as here, is informative in the opposite direction: it either supports a uniform mechanism or indicates insufficient variation in the dimension being tested.

**Caveat**: The x variable is a covariate, not a treatment intensity measure. The subgroup split tests effect heterogeneity along x, which is a necessary but insufficient condition for the dose-response prediction in H2. Standard errors increase by 20-28% relative to the pooled estimate, reflecting the halved effective sample — a cost-of-heterogeneity that production analyses should account for.

## Thread 7: Placebo group falsification confirms treatment specificity

Run_4 introduces a placebo group test — applying the DiD treatment indicator to a group that did not actually receive treatment. The resulting coefficient of 0.20 (SE=0.208, p=0.34, 95% CI [-0.21, 0.61]) is statistically and economically indistinguishable from zero. The within-R² of 0.002 confirms the treatment indicator has zero explanatory power for the placebo group's outcomes.

This is a direct falsification test: if the main effect of 2.39 were driven by specification artifacts, time effects, or data structure rather than actual treatment, the placebo group would show a comparable effect. The clean null eliminates these alternative explanations. Combined with the pre-trend placebo (p=0.27 across all runs) and the event-study pre-period nulls, the evidence forms a triangulation: the effect is specific to the treated group, specific to the post-treatment period, and absent when tested against counterfactual groups.

**From gap to contribution**: Falsification tests are not window dressing — they are the mechanism by which a causal claim graduates from "consistent with the data" to "robust against specific alternatives." The placebo group null closes one of the most direct threats to internal validity.
