# Technical Review

**Paper:** *No Cash Flows, New Owners: Spot Bitcoin ETFs and the Origins of Co-movement*
**Paper ID:** e432cf3f-9008-4202-8ee6-ff09a93948ec
**Reviewer role:** Technical / methodological reviewer (data-to-results pipeline coherence)
**Materials reviewed:** full draft, `identification_strategy.md`, `econometric_specification.md`, `literature_review.md`, `data_dictionary.json`, `data_summary.md`, and the numeric values quoted from `summary_statistics.json`, `estimation_results.json`, `robustness_results.json` via the draft's `% src:` provenance comments.

**Scope note.** This is not a referee report on contribution or positioning. It asks one question: *does the implementation do what the paper says it does?* I traced the sample flow end to end, reconstructed roughly thirty reported statistics from their stated inputs, checked every t-statistic against its coefficient and standard error, and reconciled the pre-analysis documents against what the draft actually reports.

---

## Summary Assessment

**CONCERNS.**

The arithmetic layer of this paper is unusually clean. I recomputed the sample flow at every one of the eleven filter steps and it reconciles exactly; I re-derived twenty-one p-values from their coefficients and standard errors and all of them match at the reported precision under a t(G−1) reference with G = 10; the event-study coefficients, weighted by their bin month-counts, reproduce the headline τ̂ = −0.0212 to four decimal places; and the full-panel raw Fisher-z difference-in-differences (−0.0088 in `summary_statistics.json`) is numerically identical to the `sample_extended_2026` regression estimate, which is exactly what a balanced one-treated-unit TWFE panel should deliver. That is a better internal-consistency record than most submitted empirical papers achieve.

The concerns are of three kinds, and they are concentrated where the paper makes its headline claims rather than in the plumbing.

*First, the inference apparatus the paper sells as "valid under one treated unit" quietly reverts to normal approximations at the two points where the headline claims are generated.* The reported "randomization 95% interval" is τ̂ ± 1.96 × SD(placebo) — I verified this reconstructs [−0.1426, +0.1002] exactly — not an inversion of the placebo distribution. The placebo distribution is visibly asymmetric (2.5th percentile −0.1384, 97.5th +0.1025), and inverting it properly gives roughly [−0.124, +0.117], whose upper bound in correlation units is ≈ 0.100 rather than the 0.086 the abstract advertises. The minimum detectable effect is likewise 2.80158 × SD(placebo), a z-formula applied to a 199-draw permutation distribution. Since the paper's central verdict is a comparison of a power number against a pre-registered bar, this labeling matters.

*Second, the combined randomization grid is not an exchangeable reference distribution*, and the treated unit is left in the donor pool for every placebo. The 190 placebo-in-time draws come from a 31-month pre-period with treated-period lengths ranging from roughly 6 to 25 months, while the actual estimate uses 54 months with 23 post-treatment months. Pooling estimates with heterogeneous sampling variance into one reference distribution is a heuristic, not a randomization test, and the direction of the resulting size distortion is not signed by the "shorter sample, larger variance" argument the econometric specification offers.

*Third, a material fraction of the pre-committed falsification battery is absent from the draft without acknowledgement.* The paper's rhetorical core is pre-commitment discipline — "we pre-committed to reporting every estimated break date whether or not it flattered the hypothesis," "we report it because we committed to reporting it." Against that standard, at least ten pre-registered checks are missing, and only six of them are disclosed anywhere in the pipeline. Break-date confidence intervals in particular were pre-committed with an explicit warning that point break dates without intervals "report nothing" — and the draft then uses point break dates to make an attribution claim while never mentioning that the intervals were promised and not delivered.

None of this overturns the null. If anything, most of the fixes I recommend would leave the null intact and in several cases strengthen it. But three headline numbers — the 0.086 exclusion bound, the 0.148 MDE that determines the pre-registered verdict, and the gold-placebo pass — do not currently rest on what the paper says they rest on.

---

## Data Pipeline

### Sample construction reconciles exactly

I reconstructed the eleven-step flow from `summary_statistics.json#sample_flow` against the draft's prose and against the panel dimensions. Every step reconciles:

| Step | Reported N | Reconstruction | Status |
|---|---:|---|---|
| Raw crypto bars | 27,430 | — | ✓ quoted correctly in draft |
| Post-differencing | 26,884 | 26,897 − 13 series | ✓ |
| NYSE sessions only | 18,473 | 26,884 − 8,411 off-days | ✓ |
| Coin-months | 1,072 | 16 series × 67 months | ✓ |
| Headline cohorts | 670 | 10 coins × 67 months | ✓ |
| Donut dropped | 610 | 10 × 61 | ✓ |
| Headline estimation | 540 | 10 × 54 (2021m1–2025m12 less donut) | ✓ |
| Pre / post split | 31 / 23 | 2021m1–2023m7 / 2024m2–2025m12 | ✓ (sums to 54) |
| Absorbed FE params | 63 | 10 + 54 − 1 | ✓ |
| Residual df | 476 | 540 − 63 − 1 | ✓ |

Every robustness row's N also reconciles against its stated sample restriction: `excl_halving` 520 = 540 − 20; `no_donut` 600 = 60 × 10; `subwindow_pre_halving` 330 = 33 × 10 with n_post = 2; `subwindow_pre_election` 400 = 40 × 10; `subwindow_post_election` 450 = 45 × 10; `placebo_bito_2021` 310 = 31 × 10; `sample_extended_2026` 610. This is a well-built panel and the filter chain is documented to a standard that most papers do not meet.

### Missing values, exclusions, and the one unreported QA check

Missingness handling is exemplary in policy (drop, never impute, never zero; no forward-fill; gaps void cells; raw values stored with a winsorization flag rather than pre-winsorized) and the reported outcome is zero missing across 18,473 coin-days. The minimum-session rule (`n_days_m ≥ 15`) never binds — the realized minimum is 19.

**Finding D1 (minor, verify).** Zero missing observations across 18,473 coin-days from a single aggregated vendor that the paper itself describes as having "no published methodology" and revising history silently is a mild anomaly rather than a clean bill of health. The data dictionary specifies `qa_12` precisely for this — "no forward-fill anywhere; assert that no two consecutive rows of any crypto price series are bit-identical." `data_summary.md` §7.4 lists the QA checks that passed (qa_05, qa_06, qa_07, qa_08, qa_10) and the ones that could not run (qa_02, qa_04). **`qa_12` appears in neither list.** Given that a vendor-side fill is the single most plausible way to get a perfectly complete panel, and that a filled bar manufactures a zero return which mechanically deflates both the variance and the correlation of that cell, the status of `qa_12` needs to be reported. Same for `qa_11` (cross-source price sanity), which is acknowledged as reduced to a spot check but whose result is never given.

### Clock convention: disclosed, but the pre-committed invariance test was not run

The design declared the 16:00 ET clock as baseline; the delivered outcome is on the 00:00 UTC clock because hourly crypto history is capped at the trailing 730 days. The draft discloses this fully and reasons carefully about which way the non-synchronicity cuts. That is the right handling of the constraint.

**Finding D2 (major).** The identification strategy's F9 designated the **Dimson / Scholes–Williams summed-lag correlation and the 3-session-return correlation as "the substantive test"** for resynchronization, and pre-committed a specific reading of each outcome ("If it does not survive, the paper must say so: the finding would then be that the ETF re-timed price discovery without changing 24-hour covariance, which is itself a real and reportable result"). The data dictionary builds both variables (`rho_3d_m`, `beta_dimson_m`, `dv_12`/`dv_13`) on 63-session blocks. **Neither appears in the econometric specification's falsification list, in `robustness_results.json`, or anywhere in the draft.** The inputs exist in the panel. This is a pre-committed test with constructed inputs that was silently dropped, and it is the one that speaks directly to the clock deviation the paper spends a full subsection defending. It should be run.

### The off-day alignment row is internally anomalous

**Finding D3 (major, verify in code).** `alignment_offday_span` reports that the off-day adjustment "changes Bitcoin's monthly correlation by 0.053 on average across 310 adjusted sessions" (econometric spec §14) yet moves the DiD point estimate by **less than 2 × 10⁻⁶** while raising the clustered standard error from 0.0170 to 0.0187 — a 10% increase.

Those two facts are hard to hold together. Under coin-plus-month fixed effects, if the rebuilt outcome differs from the original by a term that is exactly common across coins within each month, then the within-transformed data are unchanged, τ̂ is unchanged *and the residuals and hence the standard error are also unchanged*. If instead there is any idiosyncratic component, the residuals change — which is what a 10% SE move implies — and τ̂ should generically move at the 10⁻³ scale, not 10⁻⁶. An SE that moves while the point estimate is invariant to six decimal places is not a configuration the fixed-effects algebra produces naturally.

The draft's explanation ("the weekend effect is common across crypto assets and is absorbed by the month fixed effects") would predict *both* quantities to be unchanged, and it is offered as "a small piece of evidence that the fixed effects are doing what they are supposed to." I would not lean on that sentence until the code path has been checked: the most likely mechanical explanations are that the regression reads the original outcome column while only the standard-error input (e.g., an `n_days_m`-dependent weight or cluster definition) was rebuilt, or that the SE difference comes from a df/clustering change rather than from the data. Either way this row is currently not evidence of anything.

### Variable definitions vs. the declared contract

`identification_spec.json` specifies the outcome as the Fisher-z of the correlation between the coin's 16:00 ET return and the **US equity market excess return**, with columns named exactly `fisher_z_corr_equity`, `etf_listed`, `coin`, `year_month`. The delivered panel uses the UTC clock (disclosed), **SPY total returns** rather than the excess-return market factor for the headline leg (the excess-return leg is relegated to `leg_mkt`), and the names `y_fisherz_corr_equity`, `d_etf_listed`, `asset_id`, `year_month`. The naming drift is cosmetic; the total-vs-excess substitution is immaterial for a correlation and material only at the third decimal for beta. Both are worth a sentence in the data appendix rather than silence, given that the spec said "named exactly."

**Finding D4 (minor).** The GBTC figure caption attributes "cumulative sponsor-fee drag of roughly 1.5 percent per year" to the **pre-2024** path. The data dictionary records the sponsor fee as **2.00% p.a. before the 2024-01-11 conversion and 1.50% after**. The caption applies the post-conversion rate to the pre-conversion window. Over the 2021–2023 stretch this is a ~1.5 percentage-point level error in an already-anchored proxy — small next to a 47% discount, but it is a stated number that contradicts its own source.

**Finding D5 (minor).** The draft says GBTC's "redemption-driven volume dominates the aggregate in 2024." The only figures reported are cumulative: \$2,213.7bn total and \$1,874.0bn ex-GBTC, i.e. GBTC is **15%** of cumulative turnover. "Dominates" may be true within 2024 alone, but no 2024-only figure is reported, so as written the claim is unsupported by the paper's own numbers. Either report the 2024 share or soften the word.

---

## Estimation Implementation

### Specification match: the headline equation is implemented as written

Equation (did) — `y_im = τ·D_im + α_i + δ_m + ε_im`, D = 1{BTC} × 1{m ≥ 2024m2}, no controls, clustered on coin — matches `estimation_results.json#main` in every checkable dimension: unit, outcome, treatment definition, fixed-effect counts, sample filters, cluster count. Controls are genuinely absent from the headline and the mediator argument for excluding them is correct (volume, market cap, realized volatility are post-treatment). The month fixed effects are not collinear with the treatment. No forbidden comparisons arise because eventually-treated coins are excluded by construction, which is the right reason to use TWFE rather than Callaway–Sant'Anna here.

**Verified:** every reported p-value is consistent with a t(9) reference distribution. τ̂/SE = 0.0212/0.0170 = 1.247 → p = 0.243 ✓ (reported 0.243). CI = τ̂ ± 2.262 × SE = [−0.0597, +0.0173] ✓ (reported [−0.0595, +0.0172]). The same check passes for `outcome_ln_sigma_ratio` (t = 3.798 → 0.0042), `placebo_gold` (t = 2.353 → 0.0430), `placebo_silver` (t = 2.00 → 0.0767), `leg_acwx_non_us` (t = 3.42 → 0.0076), `placebo_bito_2021` (t = 2.497 → 0.0339), `subwindow_pre_election` (t = 2.275 → 0.0490), `excl_extreme_news` (t = 2.139 → 0.0611), `no_donut` (t = 0.579 → 0.577), `bdm_collapsed` (t = 0.862 → 0.411), the linear pre-trend (t = 1.091 → 0.304), and `ctrl_vix_move.vix_x_btc` (t = 5.56 → 0.0003). Large-cluster specifications correctly switch to a normal reference: `returns_ddd` (t = 0.493 → 0.622), `returns_interacted_BTC` (t = 1.802 → 0.072), `dcc` (t = 1.785 → 0.074). The Chow tests reconcile as χ²(2): 4.284 → 0.117, 3.315 → 0.191, 2.630 → 0.269, and the classical F(2,·) 2.886 → 0.056. **This layer is correct.**

### Finding E1 (major): the "randomization 95% interval" is a normal approximation

`main.ri_ci95 = [−0.1426, +0.1002]`. This is exactly τ̂ ± 1.96 × 0.06195, where 0.06195 is `placebo_dates_pre.diagnostics.placebo_sd`. It is a Wald interval built on the placebo standard deviation, not an inversion of the placebo distribution, and it is symmetric by construction.

The placebo distribution is not symmetric: its reported quantiles are q₀.₀₂₅ = −0.1384 and q₀.₉₇₅ = +0.1025. The standard randomization interval, [τ̂ − q₀.₉₇₅, τ̂ − q₀.₀₂₅], is [−0.1237, +0.1172]. In correlation units (× 0.8539) that is [−0.106, **+0.100**], against the reported [−0.122, **+0.086**].

This is not a rounding issue — it changes the abstract. The paper's headline exclusion claim is "the design excludes an increase in equity correlation above about 0.086, which rules out the upper half of the range the index-inclusion literature reports." Under the interval the paper's own procedure implies, the bound is ≈ 0.100, which sits exactly at the pre-registered 0.10 bar and rules out somewhat less of the literature's range. The substantive conclusion survives, but the number in the abstract does not, and the interval is currently described in Table `tab:inference` and in §Inference as one of the procedures that is "valid under one treated unit" — which is precisely what a normal approximation to an asymmetric 199-draw permutation distribution is not. Either relabel it ("normal approximation to the placebo distribution") or replace it with the inversion interval and propagate the new bound to the abstract, the introduction, and §Power.

### Finding E2 (major): the MDE is a z-formula applied to a permutation distribution, and the pre-registered verdict turns on it

`MDE_RI = 2.80158 × 0.06195 = 0.1736` in Fisher-z, × 0.8539 = **0.1482** in correlation units. I verified the arithmetic; the issue is the construction. Three points:

1. **It assumes normality of the placebo distribution**, which the reported quantiles contradict, at the one place where the paper renders its pre-registered verdict ("at or below 0.10 licenses a null claim; above 0.20 forbids one; the realized value falls between").
2. **It pools two heterogeneous placebo families.** The SD of 0.0619 mixes 9 space placebos (same window, same pre/post split as the actual estimate) with 190 time placebos estimated on a 31-month pre-period with treated-period lengths from ~6 to ~25 months. The econometric specification argues the pooled variance is conservative because the time placebos come from a shorter sample. That argument signs the bias only if *every* time placebo has larger variance than the actual estimator, which is not established — placebos with balanced pre/post splits inside a 31-month window need not. **Report the space-only placebo SD and its implied MDE separately.** If the space-only SD is materially below 0.0619, the MDE may fall closer to (or below) the 0.10 bar, and the paper's central verdict flips from "between the bars" to "null claim licensed."
3. **A permutation-based power calculation should be simulated, not derived from a z-formula.** Add a constant τ₀ to the treated unit's post-period outcome, re-run the whole RI procedure, and find the τ₀ at which the RI test rejects 80% of the time. That is the MDE of the test actually being used. The Conley–Taber figure (0.128) is a useful cross-check and is also above 0.10, so the verdict may well survive — but as implemented, the paper's most consequential number is produced by the approximation its own §Inference section argues against.

### Finding E3 (major): the endpoint event-study bin contains one treated month

The draft justifies six-month bins on an explicit ground: "a month-by-month specification is saturated for a single treated unit: Bitcoin's residual is identically zero in any month carrying its own dummy... Six-month bins give each coefficient six treated observations."

With k = 0 at 2024m2 and the donut spanning k ∈ [−6, −1], the pre-period runs k = −37 (2021m1) to k = −7 (2023m7), i.e. 31 months. The bins recovered from the reference definition (bin −2 = k ∈ [−12, −7]) are: −2 (6 months), −3 (6), −4 (6), −5 (6), −6 (6), and **−7 (one month: 2021m1)**.

I confirmed this by reconstruction rather than by assumption. Weighting the reported bin coefficients by these month-counts gives a pre-period mean of (1 × 0.2026 + 6 × [0.0774 + 0.0586 + 0.0914 + 0.1689 + 0])/31 = 0.0832 and a post-period mean of (6 × 0.00285 + 6 × 0.1406 + 6 × 0.0206 + 5 × 0.0886)/23 = 0.0621, whose difference is **−0.0211** — the headline τ̂ = −0.0212 to four decimals. Assigning bin −7 six months instead of one gives −0.0377, which does not reconcile. So bin −7 has exactly one treated observation.

Consequences: (i) the stated rationale for binning fails for exactly one bin; (ii) that bin carries the **largest pre-period coefficient in the table (0.2026, SE 0.0517, t = 3.9)**; (iii) it enters the five-degree-of-freedom pre-trend F = 9.185 that the paper then spends a page arguing is an artifact of invalid inference. Part of that F may instead be an artifact of a one-observation endpoint bin. Fold k = −37 into bin −6 (a seven-month bin) or drop it, and report whether F and its randomization p-value move. If they do not, the paper's argument gets stronger; if they do, the paper needs to know.

As a related presentational point, the event-study coefficients are all measured against bin −2 and are therefore not directly comparable to τ̂, which is a contrast against the *whole* pre-period. A reader who sees post-period coefficients averaging +0.062 against a reference of zero may wonder how the headline is negative. One sentence and the weighted-mean arithmetic above would settle it — and it is a genuinely reassuring check worth showing.

### Finding E4 (moderate): the treated unit stays in the donor pool for every placebo

Placebo-in-space assigns treatment to control coin *j* while **Bitcoin remains in the control group**, and Bitcoin is genuinely treated over the post-period. The same holds for the nine placebo pre-trend F-statistics that produce the median of 17.36. The Abadie-style convention is to remove the treated unit from the donor pool when constructing placebos, precisely because a genuinely-treated contaminant inflates the placebo spread and biases the placebo estimates.

Here the estimated effect is near zero, so the contamination is second-order for the point estimate — but it is not second-order for the *spread*, and the spread is what produces the MDE, the interval, and the "below the median placebo" pre-trend argument. Re-run the placebo-in-space grid with BTC excluded from the donor pool and report whether the placebo SD (0.0619), the pre-trend placebo median (17.36), and the RI p-values move.

### Finding E5 (moderate): the DCC sample appears to include the donut, unlike every other specification

Observation counts, per asset: `returns_interacted_BTC` = 1,128; `returns_ddd` = 11,280/10 = 1,128; `chow_test` = 1,128; `daily_rolling_did` = 11,050/10 = 1,105 (1,128 less the rolling burn-in). The full 2021m1–2025m12 window is ≈ 1,254 NYSE sessions, and 1,254 − 126 donut sessions = **1,128** — an exact match, confirming that the donut is dropped in all of those.

`dcc_garch_btc_spy` reports **N = 1,255**, i.e. the full window *with* the donut retained. If so, and if `Post_t` switches at 2024-02-01, then the DCC's pre-period includes the entire anticipation window that the paper's own design argues "would attribute anticipation to the post-period and contaminate the pre-period with a partially treated regime." The DCC is the only specification in the paper with a positive point estimate. Either the donut exclusion should be applied to the DCC as well, or the deviation should be stated and a donut-excluded DCC reported alongside.

### Finding E6 (major): the DCC parameterization makes φ weakly identified, and no first-stage diagnostics are reported

Equation (dcc) puts the post dummy inside the intercept of the Q recursion:

> q₁₂,t = (1 − a − b)(q̄₁₂ + φ·Post_t) + a·u₁,t−₁u₂,t−₁ + b·q₁₂,t−₁

φ enters multiplied by **(1 − a − b)**. DCC fits on daily financial data routinely deliver a + b in the 0.97–0.995 range, i.e. (1 − a − b) between 0.005 and 0.03. In that region the level shift induced by φ is a *fraction of a percent* of φ's nominal value, φ's scale is arbitrary, and the parameter is close to unidentified — a reported φ = 0.1203 could correspond to a correlation-target shift of anywhere between ~0.0006 and ~0.004, or to a genuine shift of 0.12, depending entirely on the fitted persistence. The paper reports φ and its standard error and nothing else.

This also undermines the cross-pair comparison that the paper leans on most heavily. The reported spread in φ̂ across control pairs (+0.0157 for DOT to +0.1457 for DOGE) may reflect cross-pair variation in (1 − â − b̂) rather than variation in correlation shifts, in which case the statement "every crypto pair's conditional correlation target rose" is not established by the spread of φ.

Required: report â, b̂, â + b̂, the log-likelihood, convergence status, and starting-value sensitivity for BTC–SPY and for all nine control pairs, and — more usefully — report the **implied change in fitted ρ̄_t** (mean fitted conditional correlation post minus pre) rather than the raw φ, which is what "shifted up" should mean. The optimizer is a hand-rolled Nelder–Mead in a runtime without scipy, with inequality constraints on a and b; convergence diagnostics are not optional in that setting.

**Related, moderate:** all ten φ̂ are positive. The paper reads this as a crypto-wide phenomenon. An untested alternative is that the specification mechanically produces φ̂ > 0 when the second half of the sample has a different volatility regime (crypto volatility fell over the post-period, as the paper's own `ln_sigma_ratio` result shows). The cheap discriminating test is a **DCC placebo-in-time**: assign the post dummy to a pre-period date and refit all ten pairs. If φ̂ is positive for all ten there too, the cross-sectional uniformity carries no information about 2024.

### Finding E7 (moderate): the HAC "sup-Wald" is not a sup, and is compared to a sup critical value

The iid Andrews statistic is 140.41 and the Newey–West statistic is 6.39, described as "at the same argmax date," compared against "an approximate five percent critical value near 8.85 for a one-parameter mean break with fifteen percent trimming." The 8.85 figure is the correct Andrews (1993) 5% critical value for p = 1, π₀ = 0.15.

But a statistic evaluated at a date chosen to maximize a *different* (iid) objective is not a sup-Wald over the HAC objective, and the sup critical value is the wrong reference for it. The correct pointwise reference for a one-parameter break at a fixed date is χ²(1), whose 5% critical value is **3.84** — and 6.39 exceeds it. Whether the paper's conclusion ("below that critical value") survives therefore depends on which reference is appropriate, and that depends on a procedural detail the draft does not state. The clean fix is to maximize the HAC Wald over the trimmed date grid and report that sup against 8.85. The paper draws a strong general claim from this number ("Any study that runs a break test on a rolling-window series without a HAC correction is reporting an artifact") and should make the comparison airtight.

### Finding E8 (major): break-date confidence intervals were pre-committed, not delivered, and the draft does not say so

`identification_strategy.md` §6.6 and F11 pre-commit to reporting "all estimated break dates **and their 90% confidence intervals**," with an explicit warning: "The relevant test is whether 2024-01-11 lies inside it. Point break dates in these tests are notoriously imprecise; a paper that reports only 'the break is estimated at 2024-02' has reported nothing."

The econometric specification discloses the omission honestly (§6.5: "Break-date confidence intervals are **not** reported: the Bai–Perron interval requires a HAC break-fraction asymptotic that is not implemented in this runtime"). **The draft does not mention it at all.** It reports four point break dates, observes that "nothing is dated at the approval," argues that 2024-05-02 "brackets [the halving] far more plausibly than it does the ETF's," and frames the whole exercise as a pre-committed falsification that was honored. That is the exact inference the pre-analysis said was worthless without intervals.

The break-date interval on a 30-day rolling series with a 22-fold HAC correction to the test statistic is going to be wide, plausibly wide enough to contain January 2024 and the halving simultaneously. Report it, or state plainly that it could not be computed and that the point dates therefore support no attribution. Note also that a genuine break at the 2024-01-11 listing would surface in a 30-day *trailing* rolling series as a ramp completing around 2024-02-22, with the estimated break typically located mid-ramp in late January — so "no break near the approval" is a meaningful statement only once the ramp geometry and the interval are both accounted for.

### Finding E9 (moderate): the raw contrast and the headline estimate are computed on different windows and different transforms, then compared

The draft's §Summary statistics states: Bitcoin's mean monthly correlation rose by **+0.0092**, the controls' by **+0.0105**, "the difference between those two numbers, which is the identifying contrast, is **−0.0014**." Three sentences later the reader encounters the headline effect of **−0.0181 in correlation units**. Thirteen times larger.

Both numbers are correct as computed, but they are not the same object:
- The raw contrast uses **post = 2024m2–2026m7** (30 months); the headline uses **post = 2024m2–2025m12** (23 months).
- The raw contrast is a difference of mean **ρ**; the headline is a difference of mean **Fisher-z**, converted by a linearization.

`summary_statistics.json` reports the raw **Fisher-z** DiD on the same full window as **−0.0088**, which is identical to the `sample_extended_2026` regression coefficient (as it must be in a balanced one-treated-unit panel — a genuine and welcome verification). So the window accounts for roughly half the gap and the transform for the other half: the raw ρ-space DiD (−0.0014) and the raw z-space DiD (−0.0088) differ by 0.0075 in correlation units, which is about 40% of the headline effect. That difference is pure transform curvature, not signal.

Two consequences. (i) The draft should report the raw contrast **on the estimation window** and label the transform explicitly, so that "the identifying contrast" and the headline are the same object. (ii) The linearization Δρ ≈ (1 − ρ̄²_pre)·τ̂ is applied at the pre-period mean, which ignores Jensen curvature over a distribution with within-coin SD(ρ) ≈ 0.25; the average derivative E[1 − ρ²] is smaller than 1 − ρ̄² (panel-wide: 0.816 vs 0.877). Since **every** economically-interpreted number in the paper is this one multiplication (−0.0181, the ±[0.122, 0.086] interval, the 0.148 MDE, the comparison against the 0.10 bar), the conversion deserves a direct validation rather than a formula: add a constant δ to Bitcoin's post-period Fisher-z values, invert, and read off the induced change in mean ρ. Report the empirical conversion factor. If it differs materially from 0.8539, the pre-registered verdict may change.

### Finding E10 (moderate): the beta/correlation decomposition is reconciled against the wrong baseline

The draft states that the beta effect (−0.1890) "is close to what a flat correlation combined with a decline of 0.1128 log points in relative volatility implies **at a pre-period beta near the panel mean**." The panel mean beta is 1.6926, and 1.6926 × (e^(−0.1128) − 1) = −0.181 ≈ −0.189 ✓.

But the effect is a **treated-unit** effect, so the correct baseline is Bitcoin's own pre-period beta, which `summary_statistics.json#raw_contrast` reports as **1.2327**. That gives 1.2327 × (−0.1067) = **−0.132**, roughly 30% below the estimated −0.189. The decomposition is therefore *not* as tight as the paper claims, and the residual (−0.057) is unexplained. Either use BTC's own pre-period beta and report the gap honestly, or explain why the panel mean is the right scaling factor for a Bitcoin-specific effect. (The econometric specification makes the same substitution, quoting "a pre-period beta near 1.6.")

### Finding E11 (minor): equation (ri) does not reproduce the reported p-value

The draft writes p^RI = #{|τ̂^placebo| ≥ |τ̂|} / (#placebos + 1). With 199 placebos and `share_abs_ge_actual = 0.663` (i.e. 132 exceedances), that formula gives 132/200 = 0.660. The reported p is **0.665** = (132 + 1)/200. The implemented estimator adds one to the numerator as well — which is the correct, conservative convention — but the displayed equation governing the paper's headline p-value does not match the implementation. Fix the equation.

Relatedly, "a coarsest attainable two-sided p-value of 0.10" is confusing phrasing; the grid's *resolution* is 0.10 and the *smallest attainable* value is 0.10.

---

## Results Reporting

### Effect-size interpretation

The units are handled correctly throughout: the Fisher-z coefficient is converted to correlation units by the delta-method factor 1 − ρ̄²_pre = 0.8539 (arithmetic verified: 0.0212 × 0.8539 = 0.0181), the variance-share translation checks out (0.3822² − 0.3641² = 0.0135, reported as "about one and a half percentage points" — 1.35 pp, which rounds to 1.4 and is stretched slightly by "one and a half"), and the σ-ratio discipline (3.18× for BTC, verified from the reported daily SDs) is applied consistently. Reporting ρ² beside every correlation is the right call and is followed.

The one substantive interpretation issue is Finding E9 above: the conversion factor is used everywhere but validated nowhere.

### Significance and inference

Every stars-vs-standard-error check passes (see the verification list under "Specification match"). The clustered column is consistently subordinated to the randomization column, and the two places where they disagree (gold, and the pre-trend F) are both flagged in the text. The paper deserves credit for this: the disagreement between valid and conventional inference is treated as the finding rather than buried.

**Finding R1 (minor).** "The clustered interval is roughly a third the width of the valid ones." Computed: clustered width 0.0767; Conley–Taber width 0.1451; RI width 0.2428. The clustered interval is 32% of the RI width but **53%** of the Conley–Taber width. "A third the width of the valid ones" (plural) is accurate for one of the two. Say "a third the width of the randomization interval and about half the Conley–Taber interval."

**Finding R2 (minor).** "The design is unbiased under the null, and its noise level is five times the actual estimate," resting on a placebo mean of 0.00011. Under TWFE with coin and month fixed effects on a balanced panel, the average of the DiD estimator over *all* (coin, date) assignments is essentially zero by construction, because the within-transformed residuals sum to zero along both dimensions. A placebo mean of ~0 is therefore close to mechanical and is not evidence of unbiasedness. The noise-level statement is fine and useful; the unbiasedness claim should go.

**Finding R3 (minor).** "Across the twenty robustness rows the point estimate is negative in nineteen and never exceeds 0.05 in absolute value except in the two sub-window rows and the two alternative outcomes." Two counting errors. (i) The robustness table has **21** rows, of which 19 are negative (`ctrl_vix_move` +0.0195 and `placebo_bito_2021` +0.0412 are the positives) — so "nineteen of twenty" mis-tallies, and the econometric spec separately refers to "all twenty-two rows." Fix the count once and propagate. (ii) Only **one** sub-window row exceeds 0.05 in absolute value: `subwindow_pre_halving` (−0.2613). `subwindow_pre_election` is −0.0439 and `subwindow_post_election` is −0.0066, both under 0.05. The sentence should read "except one sub-window row and the two alternative outcomes."

**Finding R4 (minor).** Post-period window inconsistency inside the draft: the caption of `fig_prepost_correlation_change` gives the post-period as "2024m2--2026m8," but the delivered panel ends **2026m7** (610 = 10 × 61 months confirms this, and §Robustness itself says "the end of the delivered panel in 2026m7"). One month off in a figure caption.

### Robustness assessment: are the checks addressing the actual threats?

Mostly yes, and several are genuinely well-chosen. `ctrl_vix_move` is the right implementation of the macro-confounding threat (main effects absorbed by δ_m; the *interaction* is the version fixed effects cannot kill), and the paper's handling of the resulting sign flip — "the null is robust; the sign is not" — is the correct and honest reading. The sub-window battery isolates exactly the two confounds the design cannot difference out. `leg_acwx_non_us` is the right operationalization of the US-habitat prediction. `excl_extreme_news` addresses the crypto-native-shock alternative directly. None of these reads as cosmetic.

Three exceptions.

**Finding R5 (major): the gold placebo's sign contradicts the raw data, and the raw gold movement is not reported.**

`data_summary.md` §7.3 reports that **gold's correlation with SPY rose from 0.1536 to 0.2116 (+0.0581)** and silver's from 0.2582 to 0.3040 (+0.0458) between the same clean-pre and post windows — against Bitcoin's +0.0092 and the control coins' +0.0105. The data analyst flagged this explicitly: "Gold did break, in the same direction and by more... the whole alternative-asset complex saw its equity correlation rise over 2024–2026."

**None of this appears in the draft.** The draft reports only the gold *regression* coefficient (−0.0400, clustered p = 0.0425, RI p = 0.50) and concludes "The design's macro-neutrality survives."

Two problems. (i) **A sign contradiction that needs reconciling.** If gold rose by +0.058 and the crypto controls by +0.0105, a gold-vs-crypto DiD on the full window should be strongly *positive* (≈ +0.037 in Fisher-z), yet the regression on the truncated window reports **−0.0400**. That is a 0.077 swing from removing seven months, against a swing of 0.012 for the identical window change applied to Bitcoin (−0.0088 → −0.0212). The two numbers may both be right, but the paper cannot report one and not the other without explaining the reversal. Report gold's raw Δρ and Δz **on the estimation window** alongside the DiD coefficient.

(ii) **The pre-registered falsification was stated in terms of a break, not in terms of a break under one inference procedure.** `identification_strategy.md` §10 lists "Gold shows a January 2024 break → the macro regime, not the ETF, is moving cross-asset co-movement" among "what would make us wrong." The draft resolves this by switching inference procedures and reporting the RI p of 0.50 — which is defensible, since the procedure ordering was genuinely fixed in advance. But the *level* fact that gold's equity correlation rose six times as much as Bitcoin's over the same window is inference-free, is documented in the pipeline's own data artifacts, and is exactly the kind of fact a reader needs in order to judge the macro-neutrality claim for themselves. Its absence from a paper that is otherwise scrupulous about self-incriminating evidence is the most serious reporting gap I found.

**Finding R6 (moderate): the estimate's sensitivity to the last seven months is larger than the estimate.** The headline window (ending 2025m12) is pre-declared, so the choice is legitimate. But the consequences are not stated. Bitcoin's post-period mean Fisher-z is 0.4258 on the headline window and 0.4464 on the full delivered panel — meaning the seven months of 2026 averaged roughly 0.51 and, by themselves, flip the descriptive raw gap from −0.0064 to +0.0142. The headline coefficient is −0.0212 on the declared window and −0.0088 on all available data: **the pre-declared truncation more than doubles the point estimate.** The draft reports the extended-window row but frames it only as "moves the estimate toward zero." One sentence acknowledging that the window choice is worth more than the effect — and that this is itself evidence the effect is noise — would be both honest and, in this paper, supportive of the conclusion.

**Finding R7 (minor): "six methodologically distinct estimators" overstates independence.** The six are: the monthly panel, the BDM collapse, the daily rolling panel, the returns-level DDD, the DCC, and the Chow test. But the BDM collapse is reported as "numerically identical to the headline because the panel is balanced" — it is the same estimator with a different variance estimate, not a distinct route. The Chow test is a test statistic, not an estimator of τ. The monthly panel and the daily rolling panel share an outcome construction and a sample. The genuinely distinct routes are three: the Fisher-z panel, the returns-level DDD, and the DCC. That is still a respectable robustness story; it does not need inflating.

Relatedly, the claim that the DDD (−0.0798) "agrees with the panel estimate in sign and is of the same order once scaled" asserts a scaling that is never performed. The panel's implied beta change is `outcome_beta` = −0.1890, so the two differ by a factor of 2.4. Show the mapping (Δβ implied by Δρ at BTC's pre-period volatility ratio) rather than asserting agreement.

---

## Red Flags

**No evidence of p-hacking or specification searching.** The distribution of reported p-values does not cluster below thresholds; if anything it clusters *above* them, which is the expected pattern for an honestly-reported null. The headline p is 0.665. The specifications that do reject under the clustered column are reported prominently *as failures of the inference procedure*, which is the opposite of selective reporting. The `subwindow_pre_halving` row (−0.2613, clustered p < 0.001) — the largest and most flattering-looking coefficient in the paper for a "the ETF did something" story — is reported with n_post = 2 printed beside it and explicitly disowned. The `ctrl_vix_move` sign flip is surfaced in the abstract. This is unusually good practice and should be said plainly.

**No magic numbers of concern.** Every threshold in the pipeline is documented and justified: the 15-session minimum (never binds), the 0.5/99.5 winsorization (reported both ways), the 15% Bai–Perron trimming (standard), the HAC lag L = 60 (twice the rolling window, stated), the |ρ| < 0.999 guard (flag, not clip). The donut boundaries are tied to named events.

**No suspiciously clean results.** Within-R² is 0.00057; coefficients are small and mixed in sign across the robustness grid; nothing is perfectly monotone.

**The one real red flag is selective *omission*, not selective reporting.** Set against a paper whose central rhetorical claim is pre-commitment discipline, the following pre-registered items are absent from the draft. I mark whether the omission is disclosed anywhere in the pipeline:

| Pre-committed item | Source | Disclosed in econ spec? | In draft? |
|---|---|---|---|
| Break-date 90% confidence intervals | ident. §6.6, F11 | yes | **no mention** |
| Dimson / 3-session timing-invariance test (F9) | ident. §9, dv_12/dv_13 | **no** | **no mention** |
| Leave-one-coin-out grid (F7); leave-BNB-out mandated | ident. §9, data dict | **no** | **no mention** |
| Weekend-margin test (F14) | ident. §9, dv_17 | **no** | **no mention** |
| Two-step block bootstrap for the generated outcome | ident. §8 | **no** | **no mention** |
| Romano–Wolf stepdown on the secondary outcome family | ident. §8 | **no** | **no mention** |
| Driscoll–Kraay / Newey–West supplementary rows | ident. §8 | **no** | **no mention** |
| GLS row weighted by 1/se_fisherz² | data dict handoff | **no** | **no mention** |
| Three-regime (pre/anticipation/post) specification | ident. §7 | **no** | **no mention** |
| Clean-control SUTVA subsample | ident. §4, data dict | **no** | **no mention** |
| Synthetic control (ranked co-primary, "1b") | ident. §4, §5 | yes | **no mention** |
| Rambachan–Roth breakdown value M̄ | ident. §6.3 | yes (substituted) | **no mention** |

The draft's own section "What we specified and could not estimate" lists exactly three items (session DDD, flow dose-response, false-news placebo). Twelve more are missing, of which nine are undisclosed anywhere.

Several of these are cheap to run and would materially strengthen the paper. F9 in particular has its inputs already constructed in the panel and speaks directly to the clock deviation the paper defends at length. F7 is a leave-one-out loop over nine coins and the data dictionary explicitly mandates the BNB variant. Romano–Wolf matters because `outcome_ln_sigma_ratio` — the paper's "largest clustered t-statistic anywhere" — is precisely the secondary-family result that a multiple-testing correction was pre-committed to discipline.

**Finding X1 (moderate): the pre-registered decision rule cannot be evaluated as written.** `identification_strategy.md` §10 states that H1 "is supported only if **both** (i) the primary DiD τ̂ > 0 with RI p < 0.05, **and** (ii) the session DDD shows the increase concentrated in US cash hours." The session DDD is not estimable. The paper should say that its pre-registered decision rule is only half-evaluable, rather than presenting the null verdict as though the full rule had been applied.

**Finding X2 (moderate): the "between the bars" reading is not itself pre-committed.** The pre-analysis (econ spec §9.2) specified what to do if the MDE is ≤ 0.10 and what to do if it exceeds 0.20. It did **not** specify the intermediate case. The draft's reading — "bounding the ETF-attributable component rather than a rejection" — is a reasonable and commendably modest resolution, but it is a decision made after seeing the realized MDE, and the draft presents it as pre-committed ("it is the statement our pre-analysis required us to make rather than one we upgraded after seeing the estimate"). That sentence is not accurate. Reword to: the pre-analysis specified bars at 0.10 and 0.20 and was silent on the interval between them; here is the reading we adopt and why.

**Finding X3 (minor): the generated-outcome homoskedasticity argument is stronger than the data support.** The paper's central justification for Fisher-z over beta is that Var(y_im) ≈ 1/(n_im − 3) is "known, and — critically — the same for every coin and every month," so the measurement error is classical and cannot be a function of treatment status. Two qualifications. (i) n_im ranges 19–23, so the variance ranges 1/16 to 1/20 — a 25% spread, not constant (minor). (ii) More importantly, 1/(n − 3) is the *bivariate-normal* variance of atanh(ρ̂). Daily crypto and equity returns are heavy-tailed and the true sampling variance depends on fourth moments, which differ systematically across coins (DOGE vs. BTC) and across regimes (crypto volatility fell over the post-period, as the paper's own `ln_sigma_ratio` result establishes). That is exactly the configuration — measurement-error variance correlated with unit and with treatment status — that the argument claims Fisher-z rules out. The identification strategy pre-committed to a **two-step stationary block bootstrap** to check this ("the paper should report that they do, as a check that the construction behaves as claimed"); it was not run. Run it, or soften the claim.

---

## Strengths

These are specific, and several are better than standard practice.

1. **The sample flow is fully auditable and reconciles at every step.** Eleven filters, each with a count, each reproducible from the panel dimensions. Missing values are dropped rather than imputed, never coded zero, never forward-filled in policy, and the retained off-day returns are carried in a separate file rather than discarded. I could not find a single unexplained observation.

2. **The inference is internally consistent to three or four decimals across the entire results set.** Twenty-one p-values recomputed from coefficient/SE pairs, all matching, with the correct t(9) reference for clustered rows and the correct normal reference for large-cluster rows, and the Chow statistics correctly on a χ²(2) scale. This level of arithmetic discipline is rare.

3. **The event study aggregates exactly to the headline.** Month-weighted bin coefficients give −0.0211 against a reported τ̂ of −0.0212. This is a real verification of the pipeline, not a coincidence, and the paper should report it — it is more convincing than any of the six "distinct estimators."

4. **The raw Fisher-z DiD on the full panel equals the `sample_extended_2026` regression coefficient (−0.0088).** In a balanced one-treated-unit TWFE panel that identity must hold, and it does. It confirms the fixed-effects implementation is doing what the equation says.

5. **The inference-procedure ordering was genuinely fixed in advance and the payoff is demonstrated, not asserted.** Three conventional tests reject (pre-trend F, gold, iid sup-Wald) and all three are shown to be artifacts. The paper is right that this is not a technicality, and right to lead with it.

6. **Self-incriminating results are reported rather than buried.** The `ctrl_vix_move` sign flip is in the abstract. The `placebo_bito_2021` row is reported as evidence that the design's resolution is poor. `subwindow_pre_halving` is reported with n_post = 2 printed beside it and explicitly disowned. The Bai–Perron breaks are reported as not flattering the hypothesis.

7. **Mediators are correctly excluded from the headline and correctly identified as mediators.** The no-controls decision is a genuine design choice with a stated rationale, not an omission.

8. **The forbidden-comparison problem is eliminated by construction** rather than patched with a heterogeneity-robust estimator, and the paper explains why TWFE is therefore the right estimator here and Callaway–Sant'Anna is not.

9. **Magnitude discipline is enforced throughout.** ρ² beside every correlation; the σ-ratio carried separately from ρ; no beta quoted without its correlation; the explicit refusal to write "Bitcoin became a risk asset" off a correlation of 0.4.

---

## Recommendations

Ordered by how much they affect the headline claims. Pipeline stage in brackets.

**Must fix before the paper can stand as written**

1. **[estimation] Replace the "randomization 95% interval" with an inversion of the placebo distribution, or relabel it.** Currently τ̂ ± 1.96·SD(placebo). Inverting gives ≈ [−0.124, +0.117] in Fisher-z, i.e. an upper bound of ≈ 0.100 rather than 0.086 in correlation units. Propagate the corrected bound to the abstract, the introduction, and §Power. (Finding E1)

2. **[estimation] Recompute the MDE by simulation under the actual RI procedure**, and report the space-only placebo SD and its implied MDE separately from the pooled figure. The pre-registered verdict ("between the bars") turns on whether the MDE is above or below 0.10; that determination currently rests on a normal approximation to a pooled, non-exchangeable placebo distribution. (Finding E2)

3. **[estimation] Fix the endpoint event-study bin.** Bin −7 contains one treated month (2021m1), carries the largest pre-period coefficient (0.2026, t = 3.9), and enters the pre-trend F. Merge it into bin −6 or drop it, and report whether F = 9.185 and its RI p-value move. (Finding E3)

4. **[data → draft] Report gold's and silver's raw pre/post correlation changes on the estimation window, and reconcile the sign reversal.** The pipeline's own data artifacts show gold's equity correlation rose +0.0581 against Bitcoin's +0.0092, and the regression on the truncated window reports −0.0400. Both facts belong in the paper. (Finding R5)

5. **[estimation → draft] Report Bai–Perron break-date confidence intervals, or state explicitly in the draft that they could not be computed and that the point dates therefore support no attribution claim.** The pre-analysis said in terms that point dates without intervals "report nothing." (Finding E8)

6. **[estimation] Report full DCC first-stage diagnostics (â, b̂, â+b̂, log-likelihood, convergence, starting-value sensitivity) for all ten pairs, and report the implied change in fitted ρ̄ rather than the raw φ.** φ enters multiplied by (1 − a − b) and is near-unidentified at typical daily persistence. Add a DCC placebo-in-time to test whether uniformly positive φ̂ is informative about 2024. (Finding E6)

7. **[draft] Complete the "what we specified and could not estimate" section.** It currently lists three of the fifteen pre-committed items that are absent. Nine of the omissions are disclosed nowhere in the pipeline. (Red Flags table)

**Should fix**

8. **[estimation] Run the cheap missing pre-committed checks.** In rough order of value: F9 (Dimson / 3-session timing-invariance — inputs already built, and it is the direct test of the clock deviation the paper defends at length); F7 (leave-one-coin-out, with the BNB variant the data dictionary mandates); the two-step block bootstrap validating the Fisher-z variance approximation against heavy tails; Romano–Wolf on the secondary outcome family; the three-regime anticipation specification; F14 (weekend margin, constructible from the off-day file already on disk).

9. **[estimation] Re-run all placebos with Bitcoin excluded from the donor pool**, and report whether the placebo SD, the pre-trend placebo median, and the RI p-values move. (Finding E4)

10. **[estimation] Debug the `alignment_offday_span` row.** A 10% SE change with a point-estimate change below 2 × 10⁻⁶ is not a configuration the fixed-effects algebra produces; check whether the regression is reading the rebuilt outcome column. Until resolved, drop the claim that this row is "evidence that the fixed effects are doing what they are supposed to." (Finding D3)

11. **[estimation] Apply the donut exclusion to the DCC**, or state the deviation and report a donut-excluded DCC alongside. The observation count (1,255 vs. 1,128 everywhere else) indicates the DCC's pre-period includes the anticipation window. (Finding E5)

12. **[estimation] Validate the Fisher-z → correlation conversion empirically** by shifting Bitcoin's post-period z values by a constant, inverting, and reading off the induced change in mean ρ. Every economically-interpreted number in the paper is this one multiplication. (Finding E9)

13. **[estimation] Maximize the HAC Wald over the trimmed date grid** rather than evaluating it at the iid argmax, so that the 8.85 sup critical value is the right reference. (Finding E7)

14. **[draft] Report the raw contrast on the estimation window and in the same transform as the headline**, so that "the identifying contrast" and the headline estimate are comparable. (Finding E9)

15. **[draft] Fix the beta decomposition baseline** — use Bitcoin's pre-period beta (1.2327), not the panel mean (1.6926), and report the residual honestly. (Finding E10)

**Minor / editorial**

16. **[draft]** Correct equation (ri) to include the +1 in the numerator, matching the implementation. (E11)
17. **[draft]** Fix the robustness-row count (21, not 20/22) and the "two sub-window rows" claim (only one exceeds 0.05). (R3)
18. **[draft]** Fix the figure caption post-period (2026m7, not 2026m8). (R4)
19. **[draft]** Fix the GBTC pre-conversion sponsor fee (2.00%, not 1.50%). (D4)
20. **[draft]** Qualify or support "GBTC's redemption-driven volume dominates the aggregate" — cumulative share is 15%. (D5)
21. **[draft]** Correct "a third the width of the valid ones" — a third of the RI interval, half the Conley–Taber. (R1)
22. **[draft]** Drop "the design is unbiased under the null"; a near-zero placebo mean is close to mechanical here. (R2)
23. **[draft]** Retire "six methodologically distinct estimators" in favour of the three genuinely distinct routes, and perform the DDD-to-panel scaling rather than asserting agreement. (R7)
24. **[draft]** Add one sentence noting that the headline window choice more than doubles the point estimate relative to all available data, and that this is itself evidence the estimate is noise. (R6)
25. **[draft]** Reword the pre-commitment claim around the MDE verdict: the pre-analysis set bars at 0.10 and 0.20 and was silent on the interval between. (X2)
26. **[draft]** Note that the pre-registered decision rule required both the DiD and the session DDD, and only the first half is evaluable. (X1)
27. **[data]** Report the status of `qa_12` (no forward-fill) and `qa_11` (cross-source sanity). (D1)
28. **[data]** Note the outcome-column naming drift from `identification_spec.json` and the SPY-total vs. MKT-excess substitution for the headline leg. (D4 discussion)

---

## Closing note

This is a carefully built pipeline with a genuinely honest disposition, and the arithmetic behind it is more reliable than the arithmetic behind most papers I review. The corrections above do not, as far as I can tell, threaten the null. What they threaten is the paper's claim to have earned that null by a procedure more rigorous than the conventional one — because at three of the points where that claim is cashed out (the exclusion bound, the MDE, and the gold placebo), the implementation is either a normal approximation in randomization clothing or an omission of an inconvenient fact the pipeline itself documented. Those are fixable in a revision, and the paper is worth the revision.

OVERALL SCORE: 6.5/10
RECOMMENDATION: Major Revision
