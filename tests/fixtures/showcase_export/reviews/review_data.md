# Data Review

**Paper:** *No Cash Flows, New Owners: Spot Bitcoin ETFs and the Origins of Co-movement*
**Paper ID:** e432cf3f-9008-4202-8ee6-ff09a93948ec
**Reviewer role:** Data Reviewer (sources, sample construction, missingness, variable definitions, outliers, measurement, integrity/replication)
**Date:** 2026-09-11

---

## 0. Scope and method

This review evaluates the paper on the data dimension only: provenance, sample construction, missing-value handling, variable definition, outlier treatment, measurement quality, and replication integrity. Identification and econometric inference are reviewed elsewhere; where a data problem has an inferential consequence I state the consequence but do not re-litigate the design.

Where possible I verified claims against the delivered artifacts in the workspace rather than taking the prose at face value. Verification commands and their results are quoted inline. The checks I ran:

| Check | Result |
|---|---|
| `wc -l data/coin_month_panel.csv` | 2,145 lines = **2,144 cells** — matches `data_summary` §8 |
| `wc -l data/daily_returns.csv` | 1,422 lines = **1,421 sessions** — matches the paper's `n_nyse_sessions` |
| `wc -l data/crypto_offday_returns.csv` | 8,412 lines = **8,411 off-day coin-days** — matches `sample_flow` step 5 (18,473 = 13 × 1,421) |
| `grep -c ',SPY,' data/coin_month_panel.csv` | **1,072** — matches `sample_flow[6]` |
| `grep -cE '^(BTC\|LTC\|BNB\|ADA\|DOGE\|BCH\|LINK\|AVAX\|DOT\|XLM),[0-9-]+,SPY,'` | **670** = 10 × 67 — matches `sample_flow[8]` |
| Column list of `coin_month_panel.csv` | `rho_3d_m`, `beta_dimson_m`, `rho_dcc_m` **absent** (see D2) |
| Column list of `crypto_offday_returns.csv` | `date_utc,asset_id,r_utc` only — `offday_type`, `w_weekend_vol_share` **absent** (see D2) |
| `grep -rE '(rho_3d\|dimson\|weekend\|winsor\|n_cal_days)' data/` | **No files found** (see D2) |
| Row 2 of `daily_returns.csv` | `lvl_TNX = 0.917` on 2021-01-04 → `^TNX` already in percent; **`qa_05` genuinely passes** |
| `ls data/` | 40 frozen extract files present; offline replication claim is supported on the price side |

The headline arithmetic all reconciles: 13 coins × 1,421 sessions = 18,473 coin-days exactly; 16 series × 67 months = 1,072 coin-months; 10 coins × 67 = 670; 10 × 61 = 610; 10 × 54 = 540. The panel is exactly balanced and the counts in the draft are internally consistent with the sidecars. That is worth saying plainly before the criticism starts.

---

## 1. What the paper does well

This is, on the data-transparency dimension, well above the median empirical finance paper, and several of its choices are ones I would hold up as examples.

- **The sample flow is in the paper, with counts and drop reasons at every step.** Most papers give a single N. This one walks 27,430 raw bars down to 540 estimation cells in the prose, with the source key for each figure. Verified against `summary_statistics.json#sample_flow`.
- **Missing-value policy is explicit, correct, and justified.** No imputation, no forward-filling, no zero-coding, with the reason stated: "forward-filling a continuously traded asset would manufacture zero returns and mechanically deflate both its variance and its correlation with anything." That is exactly the right reasoning for a correlation outcome.
- **ρ² is printed beside every ρ, and the panel mean (0.184) is used to discipline the prose.** The sentence "a paper that wrote 'Bitcoin became a risk asset' off a correlation of 0.4 would be overstating by a wide margin" is the single best magnitude-discipline decision in the draft.
- **Turnover is not called flow.** The variable is named `etf_turnover_usd`, the distinction is stated three separate times, and the dose–response design that would need real flows is declared not estimable rather than run on a proxy. Given how routinely this literature substitutes dollar volume for creations, this deserves explicit credit.
- **The GBTC discount is labelled a proxy**, with the reason (no BTC-per-share disclosure) and the contaminant (sponsor-fee drag) both named.
- **Coverage is stated, not implied:** "every aggregate we report covers ten of eleven funds rather than the full complex."
- **Eventually-treated coins are excluded from the control group by construction**, so the forbidden comparison cannot arise rather than being corrected after the fact.
- **Control-coin caveats are stated with the direction of the bias, including when unfavourable** (BNB's pre-period regulatory news; DOGE's 2021 episode, retained because it biases against the paper's own hypothesis).
- **Extracts are frozen on disk** (verified: 40 files) and a `sanity_rebuild_check` rebuilds the outcome from raw returns.
- **The clock deviation from the pre-registered baseline is disclosed in the data section**, not buried in an appendix.

The problems below are real, and one of them is potentially first-order, but they sit on top of a careful build.

---

## 2. Major findings

### D1 — CRITICAL. The "never-listed" status of the nine control coins is asserted for a post-period running to August 2026 and is never verified, and the bias it would induce runs in exactly the direction of the paper's result.

The paper's control group is defined by a negative: LTC, BNB, ADA, DOGE, BCH, LINK, AVAX, DOT and XLM are used "because none of them received a US spot exchange-traded product during the sample." Nothing in the data record establishes this.

- `data_dictionary.json#asset_reference` carries `etf_listing_date: null` and `in_headline_control_group: true` for all nine, with no `verification_status` field — unlike SOL and XRP, which carry explicit `UNVERIFIED` notes.
- The dictionary explicitly flags one of them: *"Monitor: LTC has been a recurring spot-ETF filing candidate. If an LTC spot ETF lists inside the sample it must move to eventually_treated and leave the headline control group. **Re-check at estimation time.**"*
- No re-check is reported in `data_summary.md`, `econometric_spec.md`, or the draft.
- The paper itself writes that "spot products for Ether listed in July 2024 and for other large assets during 2025," and the dictionary leaves SOL and XRP dates null precisely because 2025 listings could not be pinned down from primary sources. The same epistemic situation applies to the nine controls and is not acknowledged.

The exposure is not hypothetical. The delivered panel runs to 2026m7 and the `sample_extended_2026` robustness row estimates on it. That is a 30-month post-window extending eighteen months past the point where the dictionary's own author stopped being able to verify listing dates.

**Direction of bias.** A control coin that received a US spot ETP at any point in the post-window is a treated unit sitting inside the comparison group. The two-way fixed-effects estimator then differences Bitcoin against a partially-treated control mean, which attenuates $\hat\tau$ toward zero. The paper already concedes that within-crypto spillover biases toward zero and argues from that concession that "a null result is weaker evidence against H1 than it would be under clean controls." An unverified control group compounds the one bias the headline cannot afford, and it does so through a mechanism far larger than spillover: a directly treated control unit, not a second-order contamination.

**Required.** Verify, from each fund's Form 8-A and the exchange listing notice, that none of the nine control coins had a US-listed spot ETP trading at any point through the end of the estimation window. State the verification date and the primary source in the data section, in the same sentence that defines the control group. If any coin was listed, move it to `eventually_treated`, re-estimate, and report both. If verification is impossible for 2025–2026, truncate the headline window to the last month for which the never-treated status can be established and say so. The headline's 2025m12 cutoff mitigates but does not eliminate the exposure, and the `sample_extended_2026` row is the most exposed row in the paper.

---

### D2 — MAJOR. Four pre-specified checks were declared as deliverable panel columns, never built, and in two cases the paper describes them as infeasible when they are computable from the delivered daily returns.

Verified by direct search over the whole data directory:

```
grep -rE '(rho_3d|dimson|weekend|winsor|n_cal_days)' data/   →  No files found
```

`coin_month_panel.csv` columns are exactly: `asset_id, year_month, market_leg, n_days_m, rho_m, y_fisherz_corr_equity, se_fisherz, beta_m, rho2_m, ln_sigma_ratio_m, rcov_m, sd_i_m, sd_mkt_m, cohort, d_donut, d_etf_listed, d_post_listing_raw, d_post_etf, d_anticipation, d_in_headline_sample, event_k`. The dictionary's T10 specification also lists `rho_3d_m`, `beta_dimson_m` and `rho_dcc_m`. None exists. `crypto_offday_returns.csv` contains only `date_utc, asset_id, r_utc`; the dictionary's T12 also specifies `offday_type`, `w_weekend_vol_share` and `w_weekend_volume_share`. None exists.

The four dropped items:

**(a) F9, the timing-invariance test — the pre-registered remedy for the paper's own largest measurement threat.** `identification_strategy.md` §2 calls resynchronization "the single most underrated threat in this literature" and specifies the remedy precisely: "Dimson/Scholes–Williams summed lead–contemporaneous–lag correlations, which are invariant to a shift in *when* within the day information is impounded." The dictionary operationalises it as `rho_3d_m` (dv_12) and `beta_dimson_m` (dv_13), both on 63-session blocks. **Both require only daily returns.** `daily_returns.csv` contains 1,421 sessions of every series needed. The paper instead writes: "one of the two checks we specified turned out not to be a test… The feasible alignment test is the off-day-span variant." That is incorrect as to F9. The off-day-span variant is not the Dimson check and does not test the same thing: it fixes the calendar span of each return, it does not test invariance to *intraday relocation of price discovery*, which is the mechanism the paper's own H1 predicts.

This matters more than a missing robustness row. The paper's data section argues at length about which way the UTC-clock mismatch cuts, and concludes that "a null finding is not explained by it either." That is an argument, not evidence, and the pre-analysis specified the evidence. Worse, the argument is not airtight: the US cash session of day *t* lies fully inside both the equity window [16:00 ET *t*−1, 16:00 ET *t*] and the UTC crypto window [≈19:00 ET *t*−1, ≈19:00 ET *t*], so a relocation of Bitcoin's covariance into US cash hours is captured by the UTC clock about as well as by the ET clock. The claim that "the UTC clock is not the clock that such a relocation would mechanically favour" needs either a demonstration or the Dimson check that was promised.

**(b) F14, the weekend margin.** `data_summary.md` §6 calls this "the one piece of D2's logic that survives without hourly data" and dv_17 defines it from daily UTC returns alone. The off-day file was built for exactly this purpose — 8,411 rows, verified present — and then never used. F14 is an independent corroboration from a direction the DiD does not use: if the ETF's marginal holder now sets the price, Bitcoin's weekend share of variance and volume should fall post-2024. It costs a dozen lines of code against a file already on disk.

**(c) F7, leave-one-coin-out.** Listed in `identification_strategy.md` §9 as a numbered commitment ("Numbered as a commitment. Each is a *reportable outcome*, not a filter"). It does not appear in `econometric_spec.md` §11's falsification list, in the robustness table, or in the paper. It is not declared not-estimable; it is simply absent. With nine controls whose pre/post correlation changes span −0.034 (DOT) to +0.075 (AVAX), and with the paper's own claim that "the comparison group does almost all of the work," this is the first check a referee will ask for. The dictionary additionally states "a leave-BNB-out row is **mandatory** in F7."

**(d) The pre-specified GLS weighting.** `data_dictionary.json#data_plan.handoff_to_econometrics.weights` specifies "`1/se_fisherz²` as a robustness row (it is a legitimate GLS weight here precisely because `se_fisherz` is known)." `se_fisherz` is in the delivered panel. The row is not reported. Since `n_days_m` ranges 19–23, the weights are mild and the row would almost certainly change nothing — which is precisely why omitting it costs nothing to fix and something to leave out.

**Why this is a major finding rather than a list of nice-to-haves.** The paper stakes a substantial part of its claim to credibility on pre-commitment: "we pre-committed to reporting every estimated break date whether or not it flatters the hypothesis"; "we committed in advance to licensing a null claim only if…"; "we report it because we committed to reporting it." Four pre-specified checks that were declared as deliverable data columns, never constructed, and in two cases described in the paper as infeasible when they are not, is inconsistent with that posture. The fix is cheap — all four run on files already in `data/` — and until they are run the paper should not claim the alignment threat has been addressed.

---

### D3 — MAJOR. The DCC–GARCH, the only specification in the paper with a positive point estimate, appears to be estimated on a sample that retains the donut.

The returns-level sample sizes are mutually consistent except one:

| Specification | N | Implied days |
|---|---:|---:|
| `returns_interacted_BTC` | 1,128 | 1,128 |
| `chow_test` | 1,128 | 1,128 |
| `returns_ddd` | 11,280 | 1,128 × 10 |
| `daily_rolling_did` | 11,050 | 1,105 × 10 (30-day warm-up) |
| **`dcc_garch_btc_spy`** | **1,255** | **1,128 + 127** |

127 is the number of NYSE sessions in the donut window 2023m8–2024m1. The DCC is the one returns-level model whose N is consistent with the donut being retained, and it is the one model that reports $\hat\phi = +0.1203$ with an asymptotic $p$ of 0.074 — the only positive estimate in the paper, and the one the discussion section leans on as the specification that "would have reported a post-2024 rise in equity correlation at conventional significance."

If the donut days are retained and `Post` is coded 0 over them, the anticipation regime — the six months the donut exists to quarantine, containing the Grayscale ruling, the October 2023 false report, the January 9 compromised-account post, listing week, and the GBTC transition — is loaded into the DCC's pre-period. Any anticipation-driven rise in conditional correlation is then attributed to the post-period shift. That is a directional contamination of the one estimate that goes the paper's hypothesised way.

**Required.** State the DCC estimation sample explicitly in the text and in `estimation_results.json`. Report how `Post` is coded on donut days. Re-estimate the DCC with donut days excluded (or with a separate anticipation dummy in the correlation target) and report both, for Bitcoin and for all nine control pairs. If the 1,255 figure has a different explanation, say what it is — as reported, it is the only sample-size discrepancy in the results and it sits under the paper's most quotable positive number.

---

### D4 — MAJOR. The raw contrast presented as "the identifying contrast" is computed on a different window from the headline regression, and three different post-period end-dates appear in the same paper.

The data section states: Bitcoin's mean monthly correlation "rose by 0.0092 between the clean pre-period and the post-period," controls "rose by 0.0105 over exactly the same months," and "the difference between those two numbers, **which is the identifying contrast**, is −0.0014." These come from `summary_statistics.json#raw_contrast`, which `data_summary.md` §7.3 computes over post = **2024m2–2026m7 (30 months)**.

The headline regression runs on post = **2024m2–2025m12 (23 months)**, N = 540, per `estimation_results.json#main.n_post_treatment = 23`.

So the exhibit the paper offers as the model-free version of its headline is computed on a 30% longer post-window than the headline. It is not the identifying contrast of the reported regression. It is a *different* estimand on a *different* sample, and it happens to be the window where the regression estimate shrinks (`sample_extended_2026` = −0.0088 vs the headline −0.0212).

Compounding this, Figure 3's caption states the post-period as **2024m2–2026m8** — a third window, and one month longer than the delivered panel, which ends 2026m7 because of the Ken French publication lag. The data section separately describes "the end of the delivered panel in 2026m7." A reader cannot reconstruct which months are in which exhibit.

**Required.** Recompute the raw contrast on the headline window (2021m1–2023m7 vs 2024m2–2025m12) and report that number as the identifying contrast; report the full-panel version separately and label it as such. Fix the Figure 3 caption to 2026m7. State once, in the data section, that the estimation panel ends one month before the price panel and why.

---

### D5 — MAJOR. The allocator conclusion translates a within-month correlation into a portfolio correlation input, against an explicit warning in the data record, and for Bitcoin the two objects move in opposite directions.

`data_summary.md` §7.3 reports, for Bitcoin over the same windows:

| Aggregation | Pre | Post | Change |
|---|---:|---:|---:|
| Mean **within-month** ρ | 0.3822 | 0.3914 | **+0.0092** |
| **Pooled-daily** ρ | 0.4105 | 0.3923 | **−0.0182** |
| **Pooled-daily** β | 1.4028 | 1.0822 | **−0.3207** |

The gap is the low-frequency co-movement — chiefly the joint 2022 drawdown — that non-overlapping monthly blocks strip out by construction. The data team states the implication in terms: *"**The estimation outcome is the within-month correlation and therefore deliberately excludes low-frequency co-movement.** The paper must not describe it as 'the correlation between Bitcoin and equities' without that qualifier."*

The discussion section does exactly that: "The case for a small crypto sleeve in a diversified portfolio rests on a correlation input, and our estimate says that input should not have been revised on account of the wrapper… An allocator who revised the correlation assumption upward by a tenth on the strength of the listing was acting on a magnitude this design would have detected and did not find."

An allocator's correlation input is the full-sample correlation of the return series they hold, which includes the low-frequency component. It is not the average of within-month correlations. The paper's estimate is silent about the object the allocator uses, and on the raw evidence that object moved the other way.

The abstract and conclusion inherit the same slippage ("Bitcoin's equity co-movement did not detectably change"). The design point — that a within-month outcome is the right estimation object because it has no mechanical MA structure and a known sampling variance — is correct and well argued. It just does not license the allocation sentence.

**Required.** Add the qualifier wherever the estimate is given a portfolio interpretation. Report the pooled-daily contrast alongside the monthly one in the raw-contrast table so the reader can see the two objects side by side. Either drop the allocator paragraph or re-derive it on a full-sample correlation.

---

### D6 — MAJOR/MODERATE. Gold's own equity correlation rose six times as much as Bitcoin's; this is the pre-registered falsification criterion and it is not reported.

`data_summary.md` §7.3, over identical windows: gold's mean monthly ρ with SPY rose **0.1536 → 0.2116 (+0.0581)**; silver **+0.0458**; Bitcoin **+0.0092**.

The pre-analysis condition was stated unambiguously and repeated in the paper: *"A break in gold at January 2024 would be direct evidence that the crypto result is a macro artifact"* (`identification_strategy.md` §4); *"our pre-analysis committed to reading a gold break as falsifying the design's macro-neutrality"* (draft, §Robustness).

The paper evaluates this condition with a *different object*: a DiD of gold against the nine crypto controls with coin and calendar-month fixed effects (−0.0400, RI *p* = 0.50), and concludes "the design's macro-neutrality survives." But that estimator asks whether gold's change differs from crypto's change. The month fixed effects absorb the common move. It is not a test of whether gold broke; by construction it cannot be.

On the criterion as stated, gold moved, and it moved by six times Bitcoin's amount. `data_summary.md` says so directly: *"Gold did break, in the same direction and by more."* That finding does not appear in the draft.

I do not think this sinks the paper — the honest reading is close to what `data_summary` offers, that the whole alternative-asset complex saw its equity correlation rise over 2024–2026 and that this is the strongest argument for using a cross-sectional difference rather than a Bitcoin time-series break. But the paper cannot claim to have satisfied a pre-registered falsification criterion by silently replacing the criterion with an estimator that absorbs the thing being tested.

**Required.** Report gold's and silver's raw pre/post changes in the raw-contrast table. Address the pre-registered criterion on its own terms — did gold's own equity correlation break at January 2024? Then report the crypto-control DiD as the additional, differently-specified test it is, and explain what each one can and cannot rule out.

---

## 3. Moderate findings

### D7 — Zero missingness is reported as a strength; the two QA checks designed to distinguish completeness from vendor-side imputation have no reported status.

Coverage is literally 100%: 13 coins × 1,421 sessions = 18,473 coin-days, verified exactly. The paper reports this as reassurance ("No coin-day cell in the final panel is missing").

For a single-vendor, undocumented, cross-venue aggregate, 100% coverage over 5.7 years across AVAX, DOT and XLM is not by itself evidence of completeness. It is equally consistent with vendor-side carry-forward on venues that were quiet. The dictionary anticipated exactly this and specified two checks:

- **`qa_11`** — "Cross-source price sanity: BTC close from yfinance versus at least one independent reference on ten randomly chosen days, agreeing within 0.5 percent… This is the residue of the cross-venue validation `paper_plan.md` §6 asked for."
- **`qa_12`** — "No forward-fill anywhere in the price tables. Assert that no two consecutive rows of any crypto price series are bit-identical."

Neither appears in `data_summary.md` §7.4's list of checks that passed (qa_05, qa_06, qa_07, qa_08, qa_10) nor in its list of checks that could not be run (qa_02, qa_04). They are unaccounted for. `qa_01` and `qa_03` are likewise not in either list, though qa_03 is implicitly covered by exception E1.

This bears directly on the outcome. Stale or carried-forward prints compress within-month return variance, which mechanically deflates the within-month correlation — the dependent variable. If staleness is more prevalent in the smaller controls than in Bitcoin, it enters the DiD as a differential measurement error.

**Required.** Run and report `qa_11` and `qa_12`. Report, per coin, the count of exactly-zero daily log returns and the maximum run of bit-identical consecutive closes, in the data appendix. Report the status of every QA check in the dictionary, including the ones that passed trivially.

### D8 — The largest pre-treatment event-study coefficient rests on a single month, and the table does not say so.

With treatment at 2024m2, six-month bins, and reference bin −2 = *k* ∈ [−12, −7], bin −7 covers *k* ∈ [−42, −37]. The panel begins 2021m1, which is *k* = −37. **Bin −7 therefore contains exactly one treated-unit month.** It carries the largest pre-period coefficient in the table, $\theta_{-7} = 0.2026$ (SE 0.0517), roughly seventy times $\theta_0 = 0.0029$, and it enters the joint pre-trend *F*.

The stated rationale for binning is that "a month-by-month specification is saturated for a single treated unit: Bitcoin's residual is identically zero in any month carrying its own dummy." Bin −7 has precisely that problem. The bin arithmetic confirms it: bins −6 through −3 and the reference bin account for 5 × 6 = 30 months, plus bin −7 = 1, which is the full 31-month clean pre-period.

**Required.** Print the number of treated-unit months behind each bin in the event-study table. Report the pre-trend *F* with bin −7 folded into bin −6, so the reader can see whether the rejection (and the randomization comparison) depends on a one-observation bin.

### D9 — The `alignment_offday_span` result is internally implausible as reported and needs a diagnostic.

The paper states the off-day adjustment "is material at the level of the monthly correlation series" — `econometric_spec.md` §14 quantifies it as moving Bitcoin's monthly correlation by **0.053 on average across 310 adjusted sessions** — and then that it "changes the difference-in-differences estimate by **less than 2×10⁻⁶**, to −0.0212."

Agreement to five significant figures on a coefficient of −0.0212 after perturbing every cell of the outcome by ~0.05 requires the perturbation to be almost exactly additively separable into coin and month effects. The explanation offered ("the weekend effect is common across crypto assets and is absorbed by the month fixed effects") is plausible and, if true, is a nice piece of evidence that the fixed effects behave. But it is asserted, and the reported magnitude of the agreement is far tighter than "approximately absorbed" would produce.

**Required.** Report the mean and SD of the change in `y_fisherz_corr_equity` across the whole panel (not just Bitcoin), and the $R^2$ from regressing that change on coin and month dummies. If the $R^2$ is not effectively 1, the row is not doing what the text says and the 2×10⁻⁶ figure needs re-checking. This is a five-minute diagnostic that converts an implausible-looking number into a supporting piece of evidence.

### D10 — The beta outcome contains values that are not economically interpretable, and neither secondary outcome receives any outlier treatment.

`data_summary.md` §7.2 reports, for the headline sample, `beta_m` ranging from **−8.35 to +10.84** with SD 1.81 on a mean of 1.69, and `ln_sigma_ratio_m` with mean 1.55 (crypto daily vol ≈ 4.7× the market's). Each `beta_m` cell is an OLS slope on ~21 observations with a regressor of small within-month variance; monthly betas of ±10 are estimation noise, not economic quantities.

`outcome_beta` (−0.1890) and `outcome_ln_sigma_ratio` (−0.1128) are estimated on these cells at full weight, with no trimming, no winsorizing, and no influence diagnostics. `outcome_ln_sigma_ratio` carries "the largest clustered *t*-statistic anywhere in this paper" and supplies the paper's one substantive positive claim ("Bitcoin's volatility relative to the equity market fell after the listing"). That claim deserves an influence check before it is offered even as suggestive.

The paper's outlier policy is confined to *returns* (the `winsorized` row, at 0.5/99.5 on daily returns). There is no outlier policy for the *outcome*.

**Required.** Report p1/p5/p95/p99 for `beta_m`, `ln_sigma_ratio_m` and `y_fisherz_corr_equity` in the summary-statistics table (the checklist standard is min/p1/p5/p95/p99/max, not mean/SD). Report the beta and volatility-ratio DiDs with outcome cells trimmed at the 1st/99th percentiles. Report Cook's distance or leave-one-cell-out for the `ln_sigma_ratio` regression — with 540 cells and one treated unit, a handful of Bitcoin months could be driving it.

### D11 — The β = ρ · σ-ratio reconciliation is asserted rather than shown, and it only works at the wrong scale.

The paper says the beta effect is "close to what a flat correlation combined with a decline of 0.1128 log points in relative volatility implies at a pre-period beta near the panel mean," and `econometric_spec.md` §13 pins this to "a pre-period beta near 1.6."

The panel-mean beta is 1.6926. Bitcoin's own pre-period mean beta is **1.2327** (`data_summary` §7.3). The reconciliation:

- At the panel mean: 1.6926 × (e^{−0.1128} − 1) = **−0.181**, against the reported −0.1890. Close.
- At Bitcoin's own level: 1.2327 × (e^{−0.1128} − 1) = **−0.132**, i.e. about 70% of −0.1890, leaving a residual of roughly −0.057 unexplained by the volatility margin.

All three coefficients are differential effects on the treated unit. The decomposition is therefore a statement about Bitcoin and should be evaluated at Bitcoin's pre-period beta, not at the panel mean of ten coins whose betas range over an order of magnitude. Done correctly, the σ-ratio channel accounts for most but not all of the beta decline, and the residual is of the same order as the correlation coefficient the paper calls flat.

**Required.** Show the arithmetic explicitly, at Bitcoin's own pre-period level, and report the residual rather than absorbing it into "almost exactly." If the residual is genuinely small, showing it strengthens the claim; if it is not, the phrase "internally consistent" needs softening.

### D12 — The minimum detectable effect, which determines the paper's licensed claim, is computed from a placebo SD that mixes two different sample lengths.

$\mathrm{MDE}_{\mathrm{RI}} = 2.80158 \times 0.06195$, where 0.06195 is the SD of a grid of 199 placebo estimates: **9 placebo-in-space draws** on the 54-month headline sample, and **190 placebo-in-time draws** on the 31-month pre-period sample (`econometric_spec.md` §8.2: "on the pre-period sample (2021m1–2023m7) so the actual treatment cannot contaminate the placebo").

Shorter samples yield larger standard errors. The 190 time draws — 95% of the grid — therefore have systematically larger dispersion than the estimator whose sampling distribution the grid is supposed to represent. The spec acknowledges the consequence for the *p*-value ("this makes the resulting *p*-value conservative; this is noted rather than corrected") but does not carry the acknowledgement over to the MDE, where the same inflation directly widens the reported detectable effect. The Conley–Taber MDE (0.128), computed from full-sample control residuals, is 16% smaller — consistent with exactly this inflation.

This is not a minor calibration point. The paper's entire interpretive posture rests on where the MDE lands relative to two pre-registered bars: "A minimum detectable effect at or below 0.10 in correlation units would license a null claim… The realized value of 0.148 falls between them." A length-matched MDE plausibly lands closer to the Conley–Taber figure, and the gap between 0.128 and 0.10 is not large.

**Required.** Report the SD of the space-only and time-only placebo draws separately. Report an MDE computed from a placebo grid of matched sample length (e.g. placebo-in-time draws using 54-month windows, or a re-scaling by √(T_placebo/T_actual)). State whether the licensing verdict is robust to the correction. If a length-matched MDE falls at or below 0.10, the pre-registered null claim becomes available and the abstract's central hedge changes.

---

## 4. Minor findings and corrections

**M1. The GBTC fee-drag figure is wrong for the period it describes.** Figure 1's caption: "the pre-2024 path also absorbs cumulative sponsor-fee drag of roughly 1.5 percent per year." Per `data_dictionary.json#T06`, the sponsor fee was **2.00% p.a. before the 2024-01-11 conversion and 1.50% after**. The pre-2024 path — the whole region the proxy is quoted over — carries 2.00%. Over 2021–2023 that is ~6pp of cumulative drag, not ~4.5pp, a 1.5pp error in a level the text quotes to two decimal places.

**M2. False precision on an anchored proxy.** The paper says "the level is anchored rather than measured" and then quotes −47.13%, −27.35%, −1.51% and −0.99%. Round to whole percentage points, or attach the error bound the dictionary requires ("if the modelled version is used it must be labelled `gbtc_bps_modeled` and its error bound stated").

**M3. "GBTC, whose redemption-driven volume dominates the aggregate in 2024" is contradicted by the paper's own numbers.** $2,213.7bn − $1,874.0bn = $339.7bn, i.e. GBTC is **15.3%** of cumulative turnover. Either restrict the claim to a named sub-window and give the number for that window, or drop "dominates."

**M4. The sample-flow table is not a nested chain.** Row 5 (18,473 coin-days) covers 13 crypto assets; row 7 (1,072 coin-months) covers 16 series, silently adding GLD, SLV and the altcoin index. Verified: 16 × 67 = 1,072 and 13 × 1,421 = 18,473. A flow table must be monotone over a single population. Add an explicit row where the placebo and benchmark series enter, or present them in a separate panel.

**M5. Three sample end-dates appear.** "August 31, 2026" (data section), 2026m7 (estimation panel and the `sample_extended_2026` description), 2026m8 (Figure 3 caption). Fix the caption; state once which object ends when and why.

**M6. The min-15-sessions rule dropped zero cells** (min `n_days_m` = 19, verified in `data_summary` §7.2 and consistent with 1,072 → 1,072 in the flow). The paper presents it as an active restriction. Say it was non-binding — a filter reported as binding sends the reader looking for observations that were never lost.

**M7. The equity leg is a second undisclosed deviation from the pre-registered contract.** `identification_spec.json` declares the outcome against "the US equity market excess return," and `identification_strategy.md` §6.1 names "the CRSP value-weighted excess return (SPY as the fallback / robustness proxy)." The delivered headline uses SPY, and the paper inverts the framing: "The market factor we use as *the alternative equity leg* is the CRSP value-weighted excess return." The `leg_mkt` row (−0.0239) shows it does not matter for the estimate — which is the right thing to say, but it should be said as a disclosed deviation, in the same paragraph as the clock deviation, rather than as a description of the design.

**M8. Minor definitional points not stated.** (i) Within-month correlations are computed on raw returns while `beta_m` uses excess returns; say so once. (ii) Verified from `daily_returns.csv`: `mktrf` and `rf` are stored to 4 decimals (1bp/day granularity, e.g. `mktrf = −0.0141`, `rf = 0.0` in January 2021) while every other return carries full double precision. The implied rounding noise is ~0.3% of the market return SD and is immaterial for correlation, but the two equity legs are not precision-comparable and one line should note it. (iii) Positively: `lvl_TNX = 0.917` on 2021-01-04 confirms `^TNX` was already in percent, so `qa_05` genuinely passes and the 10× scale trap was correctly avoided.

**M9. Survivorship in the control group is not mentioned.** All nine controls have continuous coverage from 2021-01-04 to the panel end and none exits. Coins that failed inside the sample are absent by construction, and the dictionary flags yfinance's survivorship behaviour ("delisted tickers disappear"). Second-order for a correlation outcome, but it is a one-sentence acknowledgement.

**M10. The USD-vs-USDT denomination question is listed in `data_summary` §6 as a cleaning decision "to document in the paper" and is not documented.** Yahoo's aggregate may include USDT-quoted venues; during stablecoin stress episodes this is a real source of measurement error in the crypto leg.

**M11. `sanity_rebuild_check` reports a correlation of 1.000 between delivered and rebuilt Bitcoin monthly Fisher-z across 60 months.** A correlation of 1.000 is invariant to a location or scale shift. Report the maximum absolute difference instead, or alongside. It licenses five robustness rows, so the check should be the tight version.

**M12. The altcoin index in Figure 2 contains eventually-treated assets.** `ALTIDX_EW` is frozen as of 2020-12-31 (good practice, correctly motivated against look-ahead) but includes ETH, SOL and XRP. The caption should say so, since the figure is used to argue that the control complex moved with Bitcoin.

**M13. The Ken French extract is not frozen on disk.** `ls data/` shows 40 frozen price/ETF files but no factor file; `mktrf` and `rf` survive only as columns inside `daily_returns.csv`. Estimation is reproducible offline from that file, so the claim is not false, but the raw factor download is not archived and the retrieval date is not recorded in an artifact. One line in the replication appendix, plus saving the ZIP, closes it.

**M14. The DEFI/Hashdex ticker has been reused.** `data/etf_DEFI.csv` is 1,805 bytes — 16 bars from July–August 2026 on trivial volume, per `data_summary` E2 — i.e. the ticker now resolves to an unrelated instrument. The paper says the fund "is not [retrievable]," which is right in effect. Add the clause that the ticker has been reassigned, so a replicator who pulls `DEFI` and gets data does not silently contaminate the aggregate.

---

## 5. What I checked and found clean

Stating these explicitly, because a review that lists only problems misrepresents the build.

- Every count in the draft reconciles with the sidecars and with the files on disk: 27,430 → 26,884 → 18,473 → 1,072 → 670 → 610 → 540, with 13 × 1,421 = 18,473 and 10 × 54 = 540 exact.
- The panel is exactly balanced in both the 610-cell and 540-cell versions; no entry, exit, or gap.
- `qa_05` (the `^TNX` 10× scale trap), `qa_06` (|ρ| < 0.999), `qa_07` (session threshold), `qa_08` (no pre-listing zero-padding) and `qa_10` (no eventually-treated unit in the headline sample) are reported as passing and are consistent with the delivered files.
- The off-day file is genuinely separate (8,411 rows) rather than deleted, exactly as specified — the data is there for F14 even though F14 was not run.
- The turnover/flow distinction is maintained consistently across the draft, the variable names, and the figure captions. No table calls turnover a flow.
- The three not-estimable designs (session DDD, flow dose–response, false-news placebo) are declared rather than proxied, with the reason given in each case. The refusal to substitute SPY for the E-mini in the session test — because "SPY does not trade during the Asian session where the identifying contrast lives" — is exactly right and would have been an easy corner to cut.
- The clock deviation from the pre-registered baseline is disclosed in the data section.

---

## 6. Priority list for revision

**Blocking (must be resolved before the data section can be accepted):**

1. **D1** — Verify the never-treated status of all nine control coins from primary sources through the end of the estimation window; state the verification date and source; re-estimate if any coin was listed.
2. **D2** — Build and report F9 (Dimson / 3-session invariance), F14 (weekend margin), F7 (leave-one-coin-out) and the GLS-weighted row. All four run on files already in `data/`. Correct the statement that the alignment check reduces to the off-day-span variant.
3. **D3** — Resolve the DCC sample discrepancy (1,255 vs 1,128) and report the donut-excluded DCC.
4. **D4** — Recompute the raw contrast on the headline window; fix the three conflicting end-dates.
5. **D5** — Add the within-month qualifier wherever the estimate is given an allocation interpretation; report the pooled-daily contrast alongside.
6. **D6** — Report gold's and silver's raw pre/post changes and address the pre-registered falsification criterion on its own terms.

**Should be fixed:** D7 (run and report qa_11, qa_12, plus zero-return and stale-run counts), D8 (bin −7 is one month), D9 (alignment separability diagnostic), D10 (outcome-tail statistics and influence diagnostics for the beta and volatility-ratio rows), D11 (decomposition at Bitcoin's own beta), D12 (length-matched MDE).

**Editorial:** M1–M14, of which M1 (fee rate), M3 ("dominates"), M5 (end-dates) and M7 (equity-leg deviation) are factual corrections rather than presentational preferences.

---

## 7. Assessment

The data construction underlying this paper is careful, well documented, and in several respects exemplary — the sample flow, the missing-value policy, the ρ² discipline, the turnover/flow distinction, and the refusal to proxy three infeasible designs are all better than field standard. The build reconciles to the last observation against the files on disk.

Against that, there are six findings I regard as blocking. One (D1) is potentially first-order: the control group's defining property is asserted rather than verified over a post-window running eighteen months past the point at which the data architect stopped being able to verify listing dates, and the bias it would induce points in exactly the direction of the paper's null. Four pre-specified checks were declared as deliverable panel columns, never built, and in two cases described in the paper as infeasible when they are computable from a file already on disk — which is difficult to square with a paper that makes pre-commitment a central plank of its credibility. The one specification with a positive point estimate appears to run on a donut-inclusive sample that no other returns-level model uses. The model-free exhibit offered as "the identifying contrast" is computed on a different window from the headline. And the paper's practical conclusion translates a within-month object into a portfolio input that moved the other way, against an explicit warning in its own data record.

None of these is fabrication or carelessness with the underlying numbers. All but D1 are fixable in a day with data already in the workspace, and D1 needs an afternoon of primary-source verification. But as the data section stands, a referee who ran the checks I ran would find enough unaccounted-for gaps to send it back.

OVERALL SCORE: 6/10
RECOMMENDATION: Major Revision
