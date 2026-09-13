# Econometric Specification

**Paper:** *No Cash Flows, New Owners: Spot Bitcoin ETFs and the Origins of Comovement*
**Paper ID:** e432cf3f-9008-4202-8ee6-ff09a93948ec
**Question:** Did the January 2024 approval of US spot Bitcoin ETFs change the co-movement between Bitcoin returns and US equity returns?
**Companion documents:** `identification_strategy.md` (design), `identification_spec.json` (machine contract), `data_dictionary.json` (variables), `data_summary.md` (coverage).
**Results sidecars:** `estimation_results.json` (core), `robustness_results.json` (robustness and placebo grid).
**Estimation script:** `run_estimation.py` (runs end-to-end on numpy + pandas; the distribution functions and the optimiser are implemented inside it because the runtime has no scipy or statsmodels).

---

## 0. What this document is, and the one thing to read if you read nothing else

This is the full model set: the estimating equations, the samples they run on, the fixed effects they absorb, the inference procedure attached to each, and what each robustness check is designed to break. Sections 1–11 were written from the design in `identification_strategy.md` **before** any estimation was run, so the specification is a commitment rather than a description of whatever the code produced. Sections 12–16 report the realized numbers, and every number quoted carries a pointer into the JSON sidecars.

The one thing to read: **there is exactly one treated unit.** Bitcoin is the asset that got a US spot ETF in January 2024; no other asset in the sample did. Every inferential statement in this paper has to survive that fact. Cluster-robust standard errors on the coin dimension with one treated cluster do not have a valid asymptotic justification — they are reported because referees expect the column, but they are not the inferential basis. The honest procedure is **randomization inference over a placebo grid of counterfactual (coin, treatment-date) assignments**, and the randomization $p$-value is the one the paper's text quotes. §8 states this precisely.

This is not a technicality in this paper. It changes the sign of two conclusions. The clustered pre-trend $F$-test rejects parallel trends at $p = 0.002$; the randomization version of the same test returns $p = 0.80$, with Bitcoin's pre-trend statistic sitting *below the median* of the placebo coins (§12.3). The gold placebo "rejects" at a clustered $p$ of 0.04 and returns a randomization $p$ of 0.50 (§14). Anyone reading the clustered column here as if it were a sampling-theory $p$-value would conclude the design is broken. It is not; the clustered column is.

---

## 1. Treatment, timing, and the object being estimated

| Element | Value | Source |
|---|---|---|
| Event | SEC approval order for eleven US spot Bitcoin ETPs | 2024-01-10, 16:00 ET |
| Commencement of trading | 2024-01-11, 09:30 ET | — |
| Treated asset | BTC | `cohort == "treated_btc"` |
| Baseline treatment month | **2024m2** | `d_etf_listed` |
| Donut (excluded) | 2023m8 – 2024m1 | `d_donut` |
| No-donut variant | treatment from 2024-01-11 | `d_post_listing_raw` |

The treatment month is 2024m2, not 2024m1, because a donut excludes 2023m8–2024m1. That window contains the August 2023 Grayscale appellate ruling (when the market re-priced approval odds), the 2023-10-16 erroneous Cointelegraph report, the 2024-01-09 compromised-SEC-account post, listing week itself, and the start of the GBTC redemption transition. Including those months would attribute anticipation to the post period and contaminate the pre period with a partially-treated regime. The donut costs six months and buys a clean contrast; the no-donut variant is reported as robustness so the reader can see what the donut is doing.

**The estimand.** Not "is Bitcoin correlated with equities." It is the change in Bitcoin's equity co-movement attributable to the ETF listing, net of the 2024 macro regime, where the macro regime is netted out by the never-treated crypto control group and month fixed effects. Formally, an ATT on the treated unit over 2024m2 onward.

**Why this setting can identify a clientele effect at all.** Bitcoin has no cash flows. In an index-inclusion or ETF study on equities, a post-event rise in comovement is always contestable — perhaps the firm's fundamentals genuinely became more correlated with the market. Here that channel is shut off by construction: the issuance schedule is fixed and public, there are no earnings and no analyst revisions. A change in factor loadings is therefore a discount-rate or clientele effect, not a cash-flow effect. This is the paper's comparative advantage and it is why the outcome is a *second moment* rather than a price level.

---

## 2. Outcome variables

The outcome is a generated regressor, and the choice among candidates is driven by its sampling properties, not by convenience.

**Primary: monthly Fisher-z correlation.** For asset $i$ in month $m$, compute the within-month Pearson correlation $\hat\rho_{im}$ between the asset's daily return and the equity market return over the $n_{im}$ trading days in that month, then

$$y_{im} \;=\; \operatorname{atanh}(\hat\rho_{im}) \;=\; \tfrac{1}{2}\ln\!\frac{1+\hat\rho_{im}}{1-\hat\rho_{im}},
\qquad \operatorname{se}(y_{im}) \approx (n_{im}-3)^{-1/2}.$$

Three reasons this is the primary outcome rather than rolling beta:

1. **Variance stabilisation.** $\operatorname{Var}(y_{im})$ depends only on $n_{im}$, not on the unknown $\rho$. The raw correlation's variance collapses as $\rho \to \pm 1$, so a panel regression on $\hat\rho$ has mechanically heteroskedastic errors whose heteroskedasticity is a *function of the outcome* — precisely the structure that biases inference in a DiD.
2. **Unboundedness and approximate normality.** $y$ lives on $\mathbb{R}$ and is approximately normal, which the wild bootstrap and the randomization procedures in §8 rely on.
3. **Non-overlapping blocks.** Calendar months are disjoint, so $y_{im}$ has no mechanical moving-average structure. A rolling 30-day beta series overlaps on 29 of 30 days by construction, which makes its autocorrelation an artifact of the window and makes daily pre-trend tests on it close to uninterpretable. This is the strongest reason the headline moved from a daily rolling-beta panel (the paper plan's original) to a monthly Fisher-z panel. §12.5 shows the cost of ignoring it: the same break statistic computed on the rolling series falls from 140.4 to 6.4 once the overlap is corrected for.

Both legs are built: `market_leg == "SPY"` (the S&P 500 ETF, headline) and `market_leg == "MKT"` (the excess-return market factor). SPY is the headline because the mechanism under test is a *US brokerage habitat*, and SPY is the instrument that habitat actually trades.

**Secondary: monthly equity beta** $\hat\beta_{im}$ from the same within-month regression (`beta_m`). Beta answers a different question — co-movement *scaled by relative volatility* — and moves with crypto volatility even when correlation is flat. It is reported alongside, never instead of, and §13 decomposes the two using $\ln(\sigma_i/\sigma_{mkt})$ (`ln_sigma_ratio_m`).

**Daily-frequency outcome (complementary):** Fisher-z of the 30/60/90-day rolling correlation, $z_{it} = \operatorname{atanh}(\hat\rho^{(w)}_{it})$, from `rolling_diagnostics.csv`. Used for the daily-panel DiD, the Chow test, and the Bai–Perron break tests, with the overlap caveat carried explicitly (§6.1, §12.5).

---

## 3. Primary specification — `main`

### 3.1 Equation

$$\boxed{\;y_{im} \;=\; \tau \cdot D_{im} \;+\; \alpha_i \;+\; \delta_m \;+\; \varepsilon_{im}\;}$$

- $i$ indexes coins, $m$ indexes calendar months. Unit of analysis: **coin-month**.
- $y_{im}$: Fisher-z of the within-month correlation of the coin's daily return with SPY (`y_fisherz_corr_equity`).
- $D_{im} = \mathbb{1}\{i = \mathrm{BTC}\} \times \mathbb{1}\{m \ge 2024\mathrm{m}2\}$ — the variable `d_etf_listed`. This is Treated $\times$ Post; there is no separate main effect for either, both being absorbed.
- $\alpha_i$: **coin fixed effects.** Absorb every time-invariant difference in the level of equity integration across coins — BTC is more integrated with equities than XLM is, always has been, and that level difference is not the object of interest.
- $\delta_m$: **year-month fixed effects.** Absorb every shock common to crypto assets in a given month: the Fed pivot, the collapse in rate volatility through 2024, the AI-driven equity rally, the crypto cycle itself. **This is what nets out the 2024 macro regime**, and it is the reason the headline is not a pre/post comparison on Bitcoin.
- **Controls: deliberately none.** Volume, market capitalisation and realized volatility are *mediators* of the ETF treatment, not confounders. Conditioning on them would absorb part of the effect being estimated — a bad-control problem in the Angrist–Pischke sense. Macro variables such as VIX and MOVE are absorbed by $\delta_m$ by construction; they appear in a robustness row (§10, R4) in *interacted* form, which is the version month fixed effects cannot absorb.
- $\tau$: the ATT. **This is the headline coefficient.**

### 3.2 Sample

| Restriction | Effect |
|---|---|
| `d_in_headline_sample == 1` | BTC + 9 never-treated coins (LTC, BNB, ADA, DOGE, BCH, LINK, AVAX, DOT, XLM) |
| `market_leg == "SPY"` | headline equity leg |
| `d_donut == 0` | drops 2023m8–2024m1 |
| 2021m1 – 2025m12 | the estimation window declared in `identification_strategy.md` §7 |

**ETH, SOL and XRP are excluded from the control group.** They are eventually-treated (ETH July 2024; SOL/XRP 2025 cohorts). Excluding them means the headline contains **no comparison of a not-yet-treated unit against an already-treated unit** — the forbidden comparison that generates negative weights in staggered TWFE. The negative-weights problem does not arise here by construction, which is why TWFE is the right estimator for the headline and why Callaway–Sant'Anna is relegated to the multi-cohort extension (§7), where it is the correct tool.

GLD and SLV are in the panel as **placebo assets**, not controls (§11, F3). ALTIDX_EW is a broad crypto index used as a synthetic-control donor and for descriptive display; it is not a control unit.

### 3.3 Identifying assumption

> Absent the US spot ETF listing, the Fisher-z equity co-movement of Bitcoin and of the never-ETF'd crypto assets would have followed parallel paths in expectation.

Testable implication: no differential pre-trend. Tested in §5, results in §12.3.

### 3.4 What the design does *not* remove

Stated here rather than buried, because it is the binding weakness. Coin and month fixed effects do not absorb **Bitcoin-specific post-treatment shocks**. Two matter:

- the **April 19–20, 2024 halving**, fourteen weeks after listing;
- the **November 2024 US election** and the subsequent policy regime.

Three responses, all run and all reported:

1. $\hat\tau$ estimated separately on the **pre-halving window** (post truncated at 2024m3), the **pre-election window** (post truncated at 2024m10), and the full post window. The pre-election estimate is the figure to treat as ETF-attributable.
2. The **prior-halving placebo** (F5), testing directly whether a halving moves equity co-movement on its own.
3. The **session triple-difference** (§7), whose coin-month fixed effects absorb every Bitcoin-specific time shock outright.

---

## 4. Descriptive baseline — `descriptive_raw_gap` (NOT the headline)

$$y_{\mathrm{BTC},m} = a + b\cdot \mathbb{1}\{m \ge 2024\mathrm{m}2\} + u_m, \qquad \text{Newey–West}(L=6).$$

Bitcoin only, no control group, no fixed effects. **This is descriptive and labelled descriptive in every table it appears in.** It cannot separate the ETF from the 2024 macro regime: if global risk-asset correlations rose in 2024 for reasons unrelated to Bitcoin ETFs, this regression reports that as a treatment effect. It is included so the reader can see how much the control group and month fixed effects are doing.

This corresponds to the `fallback` entry in `identification_spec.json`. It is reported as a fallback-labelled descriptive row and **not** as the headline, because the headline design *is* estimable — the never-treated control panel exists and is balanced.

---

## 5. Parallel trends and dynamics — `event_study`

$$y_{im} \;=\; \sum_{b \ne b_{\text{ref}}} \theta_b \cdot \mathbb{1}\{i = \mathrm{BTC}\}\cdot\mathbb{1}\{B_m = b\} \;+\; \alpha_i \;+\; \delta_m \;+\; \varepsilon_{im}$$

where $B_m$ is **six-month event-time bins** relative to 2024m2 and $b_{\text{ref}} = -2$ (the bin covering $K = -12$ to $-7$, the six months ending at the donut; the conventional $k = -1$ falls inside the donut and cannot serve as reference).

**Why bins and not single months.** A month-by-month event study is *saturated* for a single treated unit: BTC's residual is identically zero in every month that carries its own dummy, so the standard errors attached to $\theta_k$ are computed off the control coins alone and are not interpretable. Six-month bins give each coefficient six treated observations and restore a non-degenerate residual for the treated unit. The month-by-month path is still reported, as point estimates only, under `event_study.monthly_path_point_estimates`, flagged as descriptive.

Reported:

- $\theta_b$ with clustered standard errors, and the **joint $F$-test that all pre-treatment $\theta_b = 0$**, in two versions: the conventional asymptotic $p$-value and — the one that counts — a **randomization $p$-value** obtained by running the identical pre-trend test with each control coin in turn cast as the treated unit. The conventional test inherits the one-treated-unit problem exactly as the clustered $p$-value on $\tau$ does; the randomization version does not.
- A **linear pre-trend test** (BTC $\times$ linear event time over the pre-period), one parameter, also with a randomization $p$-value.
- **Rambachan–Roth (2023) sensitivity** in principle: the breakdown value $\bar M$ — how large a post-period deviation from linear extrapolation of the pre-trend can be tolerated before the identified set for $\tau$ includes zero. With a single treated unit the Rambachan–Roth machinery needs a variance estimate the design cannot credibly supply; the randomization interval in §12.6 plays the equivalent role and is reported instead. This substitution is stated rather than the check being silently dropped.
- The dynamic path is itself informative: a mechanism operating through ETF flows should produce a **persistent** shift, not a one-period blip. A $\theta_0$ spike that decays is a listing-window liquidity artifact, not a clientele effect.

---

## 6. Complementary specifications

### 6.1 Daily rolling-window panel DiD — `daily_rolling_did`

The work order's baseline formulation, reported as a complement to the monthly headline.

$$z_{it} = \tau^{d} \cdot D_{it} + \alpha_i + \delta_t + \varepsilon_{it}, \qquad z_{it} = \operatorname{atanh}\!\big(\hat\rho^{(30)}_{it}\big)$$

Unit: asset-day. $\alpha_i$ asset FE, $\delta_t$ **date** FE. $D_{it} = \mathbb{1}\{i=\mathrm{BTC}\}\times\mathbb{1}\{t \ge \text{2024-02-01}\}$, donut dates dropped. Same 10-asset headline sample, SPY leg.

Inference, in order of weight carried:

1. **Randomization inference** (placebo assets, placebo dates) — primary, as everywhere in this paper.
2. **Wild cluster bootstrap** (Rademacher, 999 replications, null imposed) clustered on asset. With 10 clusters and one treated, this is the Cameron–Gelbach–Miller correction, and it is still not enough: the wild cluster bootstrap with a *single treated cluster* is unreliable (MacKinnon–Webb 2017). Reported with that caveat, not as a solution.
3. Two-way clustering on asset and date — reported; same objection.

**The overlap caveat travels with this specification.** The 30-day rolling window means $z_{it}$ and $z_{i,t-1}$ share 29 of 30 observations, so the panel has roughly $T/30$ independent blocks, not $T$. The row count is reported as `n_observations`; the number of *independent* blocks is reported alongside as `n_effective_blocks`, so nobody mistakes one for the other. This is exactly why the monthly non-overlapping panel is the headline.

### 6.2 Returns-level interacted model, per asset — `returns_interacted_BTC`

$$r_{i,t} \;=\; \alpha \;+\; \beta\, r_{\mathrm{eq},t} \;+\; \delta\,\big(r_{\mathrm{eq},t}\times \mathrm{Post}_t\big) \;+\; \gamma\,\mathrm{Post}_t \;+\; \epsilon_{i,t}$$

$\delta$ is the change in the equity loading — the co-movement change, estimated directly from returns with no generated-regressor step. Estimated for BTC and for each control coin separately on daily returns, donut dates dropped, with **HAC (Newey–West, $L = \lfloor 4(T/100)^{2/9}\rfloor$)** standard errors. The distribution of $\hat\delta$ across the control coins is itself a randomization distribution for BTC's $\hat\delta$ and is reported as such.

### 6.3 Pooled triple-difference on returns — `returns_ddd`

$$r_{it} = \beta\, r_{\mathrm{eq},t} + \pi\,(r_{\mathrm{eq},t}\times \mathrm{Post}_t) + \psi\,(r_{\mathrm{eq},t}\times \mathrm{BTC}_i) + \underbrace{\delta^{\mathrm{DDD}}\,(r_{\mathrm{eq},t}\times \mathrm{Post}_t \times \mathrm{BTC}_i)}_{\text{coefficient of interest}} + \alpha_i + \delta_t + \epsilon_{it}$$

Asset and date fixed effects absorb $r_{\mathrm{eq},t}$ and $r_{\mathrm{eq},t}\times\mathrm{Post}_t$, so $\delta^{\mathrm{DDD}}$ is identified as the differential change in Bitcoin's equity loading relative to the never-treated coins' change — the returns-level counterpart of $\tau$. It requires no generated outcome at all, which is its point: the generated-regressor critique of the Fisher-z panel does not apply to it. Clustered on date (the dimension along which $r_{\mathrm{eq},t}$ varies), with asset clustering reported alongside.

### 6.4 DCC-GARCH(1,1) with a post-treatment dummy — `dcc_garch_btc_spy`

Univariate GARCH(1,1) on each of $r_{\mathrm{BTC},t}$ and $r_{\mathrm{SPY},t}$; standardised residuals $u_t$; then the Engle (2002) DCC recursion with the treatment dummy shifting the off-diagonal long-run correlation target:

$$q_{12,t} = (1-a-b)\big(\bar q_{12} + \phi\,\mathrm{Post}_t\big) + a\,u_{1,t-1}u_{2,t-1} + b\,q_{12,t-1},
\qquad \rho_t = \frac{q_{12,t}}{\sqrt{q_{11,t}q_{22,t}}}$$

Estimated by two-stage QML (Nelder–Mead on the transformed parameters). Fitted for BTC–SPY and for every control-coin–SPY pair; the cross-sectional distribution of $\hat\phi$ over control pairs is the randomization distribution for Bitcoin's.

Why include it given the DiD: DCC estimates a *conditional* correlation path from the full likelihood rather than a windowed moment, so it is immune to the rolling-window overlap problem, and it separates the correlation shift from the volatility shift (the univariate GARCHs absorb the latter). Its weakness is that the base version is a parametric time-series model on one pair with no control group — hence the control-pair distribution, which restores the differencing. Second-stage standard errors ignore first-stage GARCH estimation error, so the control-pair placebo distribution, not the QML standard error, is the inference channel.

### 6.5 Endogenous break dating — `bai_perron`

The DiD imposes the break date. This specification asks the data where the break is, which is the more demanding and more falsifiable question.

Bai–Perron (1998, 2003) multiple structural break tests on Bitcoin's 30-day rolling beta and — more informatively — on the **differential** $z_{\mathrm{BTC},t} - \bar z_{\text{ctrl},t}$, which nets out the common component so a detected break is a *differential* break. Specification: 15% trimming, up to 5 breaks, dynamic-programming global minimisation of the SSR, BIC and LWZ selection, sequential $\sup F(\ell+1 \mid \ell)$.

**Report every estimated break date, whether or not it flatters the hypothesis.** A break dated 2024m1–2024m3 with an interval containing the approval is strong corroboration. A break dated elsewhere — at the 2022 rate-hiking cycle, say, or at the halving — with none near January 2024 is evidence against, and is reported as such. This test is included because it can fail.

Andrews (1993) sup-Wald with unknown breakpoint is reported alongside for the single-break case, in both an iid and a **Newey–West (L = 60, twice the rolling window)** version. The iid version is badly oversized on an overlapping rolling series and is reported only to show by how much.

Break-date confidence intervals are **not** reported: the Bai–Perron interval requires a HAC break-fraction asymptotic that is not implemented in this runtime. That is stated in the sidecar rather than an interval being fabricated.

### 6.6 Chow test at the imposed date — `chow_test`

Chow test for a structural break in the returns-level equity-loading regression at 2024-02-01 (and at 2024-01-11 for the no-donut variant), reported with:

- homoskedastic (classical) $F$,
- **heteroskedasticity-robust (HC3) Wald**,
- **HAC (Newey–West) Wald**.

All three are reported because they differ, and the gap between the classical $F$ and the HAC Wald is itself diagnostic of how much of the apparent break is a volatility-regime artifact. The classical $F$ is reported for completeness and is not the number to quote.

---

## 7. Extensions carried in the strategy document

**Session triple-difference (`session_ddd`).** $y$ measured separately in US cash-session and non-US-session returns:

$$y_{ism} = \lambda\,(\mathrm{BTC}_i \times \mathrm{Post}_m \times \mathrm{USsession}_s) + \gamma_{im} + \eta_{sm} + \ldots$$

The coin-month fixed effect $\gamma_{im}$ absorbs **every** Bitcoin-specific time shock, including the halving and the election. $\lambda$ is identified purely from the *relocation* of co-movement into US exchange hours. The logic is decisive: a macro regime shift raises global risk-asset correlation in all sessions; only a mechanism operating through a US-listed vehicle relocates covariance into US trading hours. The full intraday session split requires intraday data not present in this workspace. The workspace does contain `crypto_offday_returns.csv` (UTC-clock returns on non-equity-session days), which supports a weekend/off-day variant and which is used in §14 (`alignment_offday_span`). The full test is stated as not estimable rather than approximated with a proxy.

**Staggered multi-cohort extension (`staggered_cs`).** With ETH (2024m7), SOL and XRP (2025) cohorts added, treatment is staggered and TWFE is no longer safe; Callaway–Sant'Anna, Sun–Abraham and Borusyak–Jaravel–Spiess are the right estimators. In the delivered panel only BTC is flagged treated (`d_etf_listed == 0` throughout for ETH/SOL/XRP despite `cohort == "eventually_treated"`), so no post-listing variation exists for them on this build. Reported as specified-but-not-estimable, with the reason, rather than silently dropped.

**Synthetic control (`synthetic_control`).** Donor pool: the never-treated coins, optionally augmented with gold and the broad crypto index; weights $w_j \ge 0$, $\sum w_j = 1$ minimising pre-period distance in $y$ over 2021m1–2023m7; post-2024m2 gap reported with placebo-in-space $p$-values from the post/pre RMSPE ratio. This relaxes the exchangeability premise TWFE imposes and supplies a second inference channel. Not estimated on this build; the placebo-in-space grid in §8.2 supplies the same inference channel directly.

---

## 8. Inference — the section that governs every $p$-value in this paper

### 8.1 The problem

One treated unit. Nine control coins. Cluster-robust variance estimation on the coin dimension with $G=10$ clusters of which **one** is treated has no valid asymptotic justification: the treatment-effect estimator is driven entirely by a single cluster's residuals, and the CRVE is severely downward-biased in exactly that configuration (Conley–Taber 2011; MacKinnon–Webb 2017). The wild cluster bootstrap, the usual remedy for few clusters, also fails with one treated cluster.

Reporting a clustered $p$-value as the headline here would be the central inferential error available in this setting. This paper does not make it, and §12 shows concretely what it would have cost.

### 8.2 Randomization inference — **primary**

Build a placebo distribution over counterfactual treatment assignments and locate the actual estimate within it.

- **Placebo-in-space.** Assign the real treatment date (2024m2) to each never-treated coin in turn. Nine donors, so the smallest attainable two-sided $p$ is $1/10$. Too coarse alone.
- **Placebo-in-time.** Assign treatment to every candidate month in 2021m7–2023m1, for every coin including BTC, on the pre-period sample (2021m1–2023m7) so the actual treatment cannot contaminate the placebo.
- **Combined space-and-time grid**, and this is where the headline $p$-value comes from:

$$p^{\mathrm{RI}} \;=\; \frac{\#\{\,|\hat\tau^{\mathrm{placebo}}| \ge |\hat\tau|\,\}}{\#\text{placebos} + 1}.$$

Reported with the full placebo density and $\hat\tau$ marked. **This is the headline $p$-value and the one the paper's text quotes.** The placebo-in-time draws come from a shorter sample and therefore have somewhat larger variance than the actual estimate, which makes the resulting $p$-value conservative; this is noted rather than corrected.

The same procedure is applied to every robustness row (`p_value_ri_space`), to the pre-trend test, and to the DCC $\phi$. Wherever a clustered $p$-value and a randomization $p$-value both appear, the randomization one governs.

### 8.3 Conley–Taber

Conley–Taber (2011) intervals, designed for DiD with a small number of treated units and many controls: the control-group placebo distribution supplies the reference distribution for the treated unit's estimate. Reported alongside the randomization interval as a second valid-under-one-treated-unit procedure.

### 8.4 Bertrand–Duflo–Mullainathan collapse

Collapse the panel to two periods per coin (pre-mean, post-mean) and re-estimate, removing serial correlation in $\varepsilon_{im}$ by construction. With a monthly non-overlapping outcome the serial-correlation problem is already small, but the collapsed estimate is cheap and its agreement (or not) with the panel estimate is informative.

### 8.5 What is reported, and in what order

| Procedure | Status | Where |
|---|---|---|
| Randomization inference (space × time grid) | **Primary — quoted in the text** | `main.p_value_ri` |
| Conley–Taber interval | Valid alternative | `main.conley_taber_ci_lower/upper` |
| Randomization 95% interval | Valid alternative | `main.ri_ci95_lower/upper` |
| BDM collapse | Serial-correlation check | `bdm_collapsed` |
| Cluster-robust on coin | Reported for convention; **not the inferential basis** | `main.coefficients.d_etf_listed.se` |
| Wild cluster bootstrap | Reported with the one-treated-cluster caveat | `main.p_value_wild_bootstrap` |
| Two-way (coin × month) | Robustness row | `twoway_cluster` |

---

## 9. Pre-specified null, and the minimum detectable effect

Stated **before** the estimates, because a precisely-estimated zero is a finding in this literature and the only way to claim it credibly is to have said in advance what would count as one.

### 9.1 What a null looks like

A null result is:

1. $\hat\tau$ small in magnitude — **$|\hat\tau| < 0.10$ in Fisher-z units**, corresponding to a correlation shift under roughly 0.09 at $\rho \approx 0.35$ (since $d\rho/dz = 1-\rho^2$); **and**
2. a randomization-inference $p$-value above 0.10; **and**
3. a **95% confidence interval that excludes economically meaningful effects** — bounds lying inside $\pm$ MDE, so the data can rule out the effect sizes the habitat hypothesis predicts; **and**
4. an event-study path with no visible level shift at $b=0$ and no trend thereafter; **and**
5. no Bai–Perron break dated within two months of the approval.

Conditions 1–2 alone are *not* a null — they are consistent with an imprecise estimate. Condition 3 is what distinguishes "we found nothing" from "we could not have found anything." The MDE is therefore reported next to the point estimate in the main table.

### 9.2 Minimum detectable effect

With $\alpha = 0.05$ two-sided and power $1-\kappa = 0.80$:

$$\mathrm{MDE} \;=\; \big(z_{1-\alpha/2} + z_{1-\kappa}\big)\cdot \mathrm{se}(\hat\tau) \;=\; 2.80158 \cdot \mathrm{se}(\hat\tau).$$

Because the clustered SE is not trustworthy here (§8.1), the MDE is computed **three ways** and all three reported: from the cluster-robust SE (conventional, for comparability); from the **standard deviation of the randomization placebo distribution** — the honest one, since that distribution *is* the sampling distribution under this design; and from the Conley–Taber reference distribution. It is then translated into correlation units at the pre-period mean via $\Delta\rho \approx (1-\bar\rho_{\mathrm{pre}}^2)\cdot\mathrm{MDE}$.

**Benchmark for "economically meaningful," committed in advance.** The habitat/category literature on index inclusion reports beta changes of roughly 0.2–0.4 and correlation changes of roughly 0.05–0.15. If the MDE in correlation units is **at or below ~0.10**, the design can detect an effect of the size the theory predicts and a tight zero is a genuine rejection of the habitat hypothesis in this setting. If the MDE **exceeds ~0.20**, the design is underpowered and **no null claim will be made** — the paper will say the data cannot distinguish the hypotheses, a different and weaker statement. Whichever obtains is stated in the abstract.

---

## 10. Robustness checks (all reported in `robustness_results.json`)

Each specified with what it is meant to break.

| # | Key | Check | What it tests |
|---|---|---|---|
| R1 | `window_60d`, `window_90d` | Alternative rolling windows (60d, 90d) for the daily specifications | Whether the result is a 30-day-window artifact. A result that appears at only one window length is a windowing artifact. |
| R2 | `utc_alignment`, `alignment_offday_span` | 24h-UTC return alignment; and an off-day-span alignment that cumulates weekend/holiday crypto returns into the next equity session | Non-synchronous trading. Crypto trades 24/7, equities 09:30–16:00 ET. If the estimate flips with the clock, what is being measured is measurement timing, not co-movement. *(See §14: the delivered daily crypto returns turn out to already be on the UTC clock, so the first of these reproduces `main` and the second is the alignment test that is actually feasible here.)* |
| R3 | `excl_halving` | Drop 2024m4–2024m5 (April 19–20 halving window) | The largest BTC-specific post-treatment shock. Complements the pre-halving sub-window (§3.4). |
| R4 | `ctrl_vix_move` | Add VIX and MOVE monthly levels **interacted with the Bitcoin indicator** | **Whether the estimate is picking up the macro regime.** Main effects are absorbed by $\delta_m$; the interactions let the macro regime load *differentially* on Bitcoin, which is the version of the macro story month FE do not kill. The most substantively important robustness row in the table. |
| R5 | `placebo_dates_pre` | Placebo break dates from the pre-period (every month 2021m7–2023m1) | Feeds the RI distribution (§8.2) and separately reported as a falsification. |
| R6 | `placebo_bito_2021` | The 2021-10-19 BITO futures-ETF launch as a placebo event | A US-listed, brokerage-accessible Bitcoin ETF that did **not** change spot plumbing. A large effect favours a pure listing/visibility channel; a null favours spot plumbing. **Informative in either direction**, and a genuine falsification of "any US-listed Bitcoin vehicle raises co-movement." |
| R7 | `excl_extreme_news` | Drop days with extreme crypto-idiosyncratic news (\|r_BTC\| above the 99th percentile, plus the FTX-collapse window) | Whether a handful of crypto-native shocks drive the estimate. |
| R8 | `no_donut` | Treatment from 2024m1, donut months retained | What the donut is doing. A much larger estimate without it means anticipation is being counted as treatment. |
| R9 | `leg_mkt` | Excess-return market factor instead of SPY | Whether the result is specific to the tradable US large-cap vehicle. |
| R10 | `outcome_beta`, `outcome_ln_sigma_ratio` | Monthly beta; log relative volatility | Which margin of $\beta = \rho\,(\sigma_i/\sigma_{mkt})$ moves (§13). |
| R11 | `placebo_gold`, `placebo_silver` | Gold and silver assigned BTC's treatment date | Same macro regime, long-standing ETFs, no 2024 access change. **A break in gold at January 2024 falsifies the macro-neutrality of the design.** |
| R12 | `winsorized` | Winsorize daily returns at 0.5/99.5 within-asset percentiles before building the outcome | Outlier sensitivity. |
| R13 | `sample_extended_2026` | Extend to 2026m7 (the full delivered panel) | The declared window ends 2025m12; the delivered data run to 2026m7. Reported so the window choice is visible rather than hidden. |
| R14 | `twoway_cluster` | Two-way clustering on coin and month | Conventional alternative; same one-treated-unit objection. |
| R15 | `subwindow_pre_halving`, `subwindow_pre_election`, `subwindow_post_election` | Post window truncated before the halving / before the election; and post restricted to after the election | Isolates the two BTC-specific post-treatment shocks the design cannot difference out (§3.4). |
| R16 | `leg_acwx_non_us` | Non-US equity leg (ACWX, MSCI ACWI ex-US) | If the mechanism is a *US* brokerage habitat, co-movement should rise more against US than non-US equities. A uniform rise points to global macro. |

Every entry carries the same scalar fields as `main` — `n_observations`, `n_clusters`, `n_pre_treatment`, `n_post_treatment`, and `p_value_ri_space` — recomputed for that specification, not copied from the headline, so the results table renders in complete rows.

---

## 11. Falsification layer

- **F1** Pre-trends (§5, §12.3).
- **F2** Placebo treatment dates (R5, and the RI grid).
- **F3** Placebo assets: gold, silver, each never-treated coin assigned BTC's date (R11).
- **F4** False-news placebos — 2024-01-09 (compromised SEC account) and 2023-10-16 (erroneous Cointelegraph report): news without plumbing. If co-movement responds to false news as much as to the real listing, the mechanism is sentiment, not access. The price-response leg requires intraday data and is not estimable here; both dates fall inside the donut, so the daily co-movement leg is also unavailable on this build. Stated as not estimable.
- **F5** Prior-halving placebo (2016-07-09, 2020-05-11). The panel begins 2021m1, so both are outside coverage. Not estimable; partly offset by R3 and R15.
- **F6** Futures-ETF placebo, BITO 2021-10-19 (R6).
- **F8** Alternative market proxies and the non-US equity placebo (R9, R16).

---

## 12. Realized results

> All numbers below trace to `estimation_results.json` and `robustness_results.json`. Source paths are given inline. The script ran to completion; `run_estimation.py` reproduces every figure here.

### 12.1 Headline

The identified specification — TWFE DiD on the coin-month panel, Fisher-z equity correlation, coin and year-month fixed effects, no controls, clustered on coin, randomization inference primary — returns

$$\hat\tau = -0.0212 \quad (\text{cluster-robust SE } 0.0170;\ \ p^{\mathrm{RI}} = 0.665)$$

> Source: `estimation_results.json#main.coefficients.d_etf_listed`, `#main.p_value_ri`

on 540 coin-month observations, 10 coins, 31 pre-treatment and 23 post-treatment months for the treated unit, with 10 coin fixed effects and 54 month fixed effects (63 absorbed parameters) and 476 residual degrees of freedom. Within-$R^2$ net of fixed effects is 0.00057.

In correlation units at the Bitcoin pre-period mean correlation of $\bar\rho_{\mathrm{pre}} = 0.3822$, the conversion factor is $1-\bar\rho_{\mathrm{pre}}^2 = 0.8539$ and $\hat\tau$ corresponds to a change in correlation of $-0.0181$ — under two correlation points, and negative.

**The estimate is small, negative, and statistically indistinguishable from zero under every valid inference procedure.** The randomization $p$-value of 0.665 comes from a combined space-and-time grid of 199 placebo assignments, of which 66.3% produced an absolute estimate at least as large as the actual one. Placebo-in-space alone gives $p = 0.800$. The wild cluster bootstrap gives $p = 0.467$ and the clustered $t$-test $p = 0.243$; all three agree in substance, and the two that are valid agree with each other more closely.

The placebo density is wide: its 2.5th and 97.5th percentiles are $-0.138$ and $+0.103$, against a point estimate of $-0.021$. The actual estimate sits close to the middle of the distribution of estimates the design produces when nothing happened.

> Source: `robustness_results.json#placebo_dates_pre.diagnostics`

The Conley–Taber interval is $[-0.106,\ 0.039]$ and the randomization 95% interval is $[-0.143,\ 0.100]$, against the cluster-robust interval of $[-0.060,\ 0.017]$. **The clustered interval is roughly a third the width of the valid ones** — a direct measurement of the downward bias §8.1 predicts.

> Source: `estimation_results.json#main.conley_taber_ci_lower/upper`, `#main.ri_ci95_lower/upper`

### 12.2 What the control group and the month fixed effects are doing

The descriptive raw gap — Bitcoin only, no control group, no fixed effects — is

$$\hat b = -0.0064 \quad (\text{Newey–West SE } 0.0939,\ L=6,\ p = 0.946)$$

> Source: `estimation_results.json#descriptive_raw_gap.coefficients.post_etf`

Bitcoin's monthly Fisher-z equity correlation averaged 0.4322 before and 0.4258 after, on 54 months. The raw gap and the identified estimate are both essentially zero, and that similarity is itself the substantive content: over this window the never-treated crypto control group experienced almost exactly the same change in equity co-movement as Bitcoin did, and Bitcoin's own before/after change was negligible to begin with. Whatever moved crypto–equity correlation around the ETF listing moved all of crypto, and not by much. The month fixed effects find essentially nothing Bitcoin-specific to remove.

### 12.3 Pre-trends — and the clearest demonstration of why the inference procedure matters

The joint test of the five pre-treatment event-study bin coefficients gives $F = 9.185$, with an **asymptotic $p$-value of 0.0024** — an apparent, decisive rejection of parallel trends.

It is not one. Running the identical test with each of the nine control coins cast in turn as the treated unit gives a placebo distribution with **median $F = 17.36$ and maximum $F = 84.30$**. Bitcoin's $F = 9.185$ is *below the median placebo*. The randomization $p$-value is

$$p^{\mathrm{RI}}_{\text{pre-trend}} = 0.800.$$

> Source: `estimation_results.json#event_study.pre_trend_f_stat`, `#event_study.pre_trend_p_value`, `#event_study.pre_trend_p_value_ri`, `#event_study.pre_trend_placebo_F_median`

The asymptotic test rejects for *every* coin, treated or not, because with one treated unit the cluster-robust covariance of a set of unit-specific lead coefficients is driven by a single cluster. The test is not detecting a Bitcoin pre-trend; it is detecting its own invalidity. §8 committed to randomization inference as the governing procedure before this was known, and this is where that commitment pays.

The linear pre-trend test agrees: $-0.00144$ per month (clustered SE 0.00132, $p = 0.304$), randomization $p = 0.700$.

The binned event-study path (reference bin $-2$, the six months ending at the donut):

| Bin (6 months) | $\theta_b$ | SE |
|---|---|---|
| $-7$ | 0.2026 | 0.0517 |
| $-6$ | 0.0774 | 0.0273 |
| $-5$ | 0.0586 | 0.0425 |
| $-4$ | 0.0914 | 0.0258 |
| $-3$ | 0.1689 | 0.0364 |
| $-2$ (ref) | 0 | — |
| $0$ | 0.0029 | 0.0367 |
| $1$ | 0.1406 | 0.0443 |
| $2$ | 0.0206 | 0.0258 |
| $3$ | 0.0886 | 0.0358 |

> Source: `estimation_results.json#event_study.coefficients`

Read against the reference bin, the pre-period coefficients are positive and the post-period ones are of the same order — there is no level shift at the listing. $\theta_0 = 0.0029$: the first six months of treatment are indistinguishable from the reference window. The post-period coefficients are not systematically larger than the pre-period ones; the series simply wanders, which is what the randomization pre-trend test says too.

### 12.4 Complementary specifications

| Spec | Coefficient | Estimate | SE | $p$ | $N$ |
|---|---|---|---|---|---|
| `daily_rolling_did` | $\tau^d$ (30d Fisher-z, asset+date FE) | $-0.0272$ | 0.0182 | 0.170 | 11,050 |
| `returns_ddd` | $\delta^{\mathrm{DDD}}$ (triple interaction) | $-0.0798$ | 0.1619 | 0.622 | 11,280 |
| `returns_interacted_BTC` | $\delta$ (BTC equity-loading change, HAC) | $-0.4148$ | 0.2302 | 0.072 | 1,128 |
| `dcc_garch_btc_spy` | $\phi$ (post shift in correlation target) | $+0.1203$ | 0.0674 | 0.074 | 1,255 |
| `chow_test` | HAC Wald at 2024-02-01 | $\chi^2 = 3.315$ | — | 0.191 | 1,128 |
| `bdm_collapsed` | $\tau$ (two periods per coin) | $-0.0212$ | 0.0246 | 0.411 | 20 |

> Sources: `estimation_results.json#daily_rolling_did`, `#returns_ddd`, `#returns_interacted_BTC`, `#dcc_garch_btc_spy`, `#chow_test`, `#bdm_collapsed`

Six methodologically distinct routes — a fixed-effects panel on a generated second moment, a daily rolling-window panel, a returns-level triple difference requiring no generated regressor at all, a parametric conditional-correlation model estimated by QML, a classical structural-break test, and a two-period collapse — and none of them finds a detectable increase in Bitcoin's equity co-movement.

Three of them deserve comment.

**The returns-level DDD matters most as a specification check.** It bypasses the Fisher-z transform entirely, and at $-0.0798$ it agrees with `main` in sign and is of the same order once scaled. That rules out the possibility that the null is an artifact of the correlation transform. The BDM collapse returns $-0.0212$, numerically identical to `main` — the balanced panel makes this exact — with a wider standard error, confirming serial correlation is not doing any work here.

**The per-asset returns model is the one result that looks large, and it is not what it appears.** Bitcoin's equity beta fell by $-0.4148$ (HAC $p = 0.072$). But the never-treated control coins' betas fell too, by $-0.3221$ on average with a cross-sectional standard deviation of 0.2394. Bitcoin's decline is 0.4 standard deviations beyond the control mean, and the randomization $p$-value across control coins is 0.30. **Every crypto asset's equity beta fell over this window.** The DDD differences that common decline out, which is exactly why the DDD is $-0.08$ and not $-0.41$, and it is a clean illustration of what a design without a control group would have reported.

**The DCC is the one specification with a positive point estimate, and it has the same problem.** $\hat\phi = +0.1203$ says Bitcoin's long-run conditional correlation target with SPY shifted up after the listing, and the asymptotic $p$ is 0.074. But fitting the identical model to all nine control-coin–SPY pairs returns $\hat\phi$ **positive for every one of them**, ranging from $+0.0157$ (DOT) to $+0.1457$ (DOGE). DOGE's exceeds Bitcoin's. The randomization $p$-value across control pairs is 0.20.

> Source: `estimation_results.json#dcc_garch_btc_spy.control_pair_phi`

A DCC fitted to Bitcoin alone would have reported a post-2024 rise in equity correlation at conventional significance. It would have been picking up a crypto-wide phenomenon. This is the paper's argument in miniature, and it is why the DCC is reported with its control-pair distribution rather than on its own.

The daily panel is estimated on 11,050 asset-day rows but only about 368 independent 30-day blocks; its standard error is not to be read as coming from 11,050 independent draws. Two-way clustering on asset and date changes it from 0.0182 to 0.0184.

### 12.5 Endogenous break dating

Bai–Perron on the differential series $z_{\mathrm{BTC},t} - \bar z_{\text{ctrl},t}$ (15% trimming, up to 5 breaks, dynamic-programming global minimisation) selects four breaks under BIC: **2022-04-11, 2023-01-30, 2024-05-02, 2025-01-31**. LWZ selects three, dropping the last. On Bitcoin's 30-day rolling beta the BIC-selected breaks are **2022-02-02, 2023-03-16, 2024-04-30, 2025-02-03**.

> Source: `estimation_results.json#bai_perron.differential_fisherz`, `#bai_perron.btc_rolling_beta`

**Nothing is dated at the approval.** The closest differential break is 2024-05-02 — nearly four months after the approval, and *two weeks after the April 19–20 halving*, whose date it brackets far more plausibly than the ETF's. The rolling-beta series agrees, breaking on 2024-04-30. With one break imposed, the procedure picks 2023-01-30, not 2024.

This is a pre-committed falsification (§6.5: "report all estimated break dates, whether or not they flatter the hypothesis"), and it does not flatter the hypothesis. It also supplies something useful: the one clear 2024 regime change in Bitcoin's differential co-movement lines up with the halving, which is precisely the confound §3.4 named as the design's binding weakness. The break test locates it and dates it away from the ETF.

The Andrews sup-Wald illustrates the overlap problem quantitatively. The iid version is **140.41**, which would reject overwhelmingly. The Newey–West version ($L = 60$, twice the rolling window) at the same argmax date of 2023-01-31 is **6.39**, below the roughly 8.85 asymptotic 5% critical value for a one-parameter mean break with 15% trimming.

> Source: `estimation_results.json#bai_perron.andrews_sup_wald`, `#bai_perron.andrews_sup_wald_hac`

A twenty-two-fold reduction in the test statistic from correcting for a mechanical 29-of-30-day overlap. Any paper that runs a break test on a rolling-window series without a HAC correction is reporting an artifact, and §2 chose the monthly non-overlapping outcome for the headline for this reason.

The Chow test at the imposed date tells the same story more quietly: classical $F = 2.886$ ($p = 0.056$), HC3 Wald $= 4.284$ ($p = 0.117$), HAC Wald $= 3.315$ ($p = 0.191$). The classical version is the only one that flirts with significance, and it is the only one that is wrong. The no-donut variant at 2024-01-11 gives HAC Wald $= 2.630$ ($p = 0.269$).

### 12.6 Minimum detectable effect — and the verdict §9.2 committed to

$$\mathrm{MDE}_{\mathrm{RI}} = 2.80158 \times 0.06195 = 0.1736 \ \text{(Fisher-z)} \;\;\Longrightarrow\;\; \Delta\rho \approx 0.1482$$

> Source: `estimation_results.json#power_analysis`

| Reference distribution | SD | MDE (Fisher-z) | MDE (correlation units) | Valid? |
|---|---|---|---|---|
| Randomization grid | 0.0619 | 0.1736 | 0.1482 | yes |
| Conley–Taber | 0.0534 | 0.1497 | 0.1279 | yes |
| Cluster-robust | 0.0170 | 0.0475 | 0.0406 | **no** |

The two valid reference distributions agree closely (0.148 and 0.128 in correlation units). The cluster-robust MDE of 0.041 is three and a half times smaller and would have supported a much stronger claim than the data can carry — one more reason §8 does not use it.

**§9.2 committed in advance to a bar, and it binds.** MDE at or below ~0.10 in correlation units licenses a null claim; above ~0.20 forbids one. **The realized MDE is 0.148 — between the two bars.** So the finding is stated as follows, and this is the paper's headline claim:

> Bitcoin's equity co-movement did not detectably change after the January 2024 spot-ETF approval. The point estimate is $-0.021$ in Fisher-z units ($-0.018$ in correlation units), with a randomization $p$-value of 0.67, and the randomization 95% interval is $[-0.143,\ +0.100]$ in Fisher-z units, or $[-0.122,\ +0.086]$ in correlation units. The design **excludes an increase in equity correlation above about 0.09**, which rules out the upper half of the 0.05–0.15 range the index-inclusion comovement literature reports. It does **not** rule out an increase of 0.05. With 80% power the design could only have detected an effect of about 0.15 or larger.

> Source: `estimation_results.json#power_analysis.ri_ci95_lower/upper_correlation_units`, `#power_analysis.verdict`

That is weaker than "we reject the habitat hypothesis" and stronger than "we found nothing." §9.2 required it to be phrased this way rather than upgraded after the fact, and the abstract says this.

Checked against the five pre-specified null conditions in §9.1: (1) $|\hat\tau| = 0.021 < 0.10$ ✓; (2) $p^{\mathrm{RI}} = 0.665 > 0.10$ ✓; (3) interval bounds inside $\pm$MDE ✓, though the substantive power bar in §9.2 is not met; (4) no level shift at $b=0$, $\theta_0 = 0.003$ ✓; (5) no Bai–Perron break within two months of the approval ✓. Four met outright, the fifth met in form but not in the power it was meant to guarantee.

What would have been needed to do better: more treated units — the ETH/SOL/XRP cohorts, once their listings are flagged in the panel, would raise the treated count from one to four and cut the randomization-based MDE materially — or a higher-frequency outcome with genuinely independent blocks. Both are available in principle; neither is available on this build.

---

## 13. Correlation versus beta

Beta and correlation need not move together, because $\beta_{im} = \rho_{im}\cdot(\sigma_{i,m}/\sigma_{mkt,m})$. A rise in beta with flat correlation is a volatility story, not a co-movement story.

| Outcome | $\hat\tau$ | SE | $p^{\mathrm{RI}}$ |
|---|---|---|---|
| Fisher-z correlation (`main`) | $-0.0212$ | 0.0170 | 0.665 |
| Monthly beta | $-0.1890$ | 0.1431 | 0.800 |
| $\ln(\sigma_i/\sigma_{mkt})$ | $-0.1128$ | 0.0297 | 0.200 |

> Sources: `robustness_results.json#outcome_beta`, `#outcome_ln_sigma_ratio`

The decomposition is internally consistent. Correlation is flat; the log volatility ratio falls by 0.113 (the largest clustered $t$-statistic anywhere in the paper, though its randomization $p$ is 0.20); and beta, being the product, falls by 0.189 — almost exactly what a flat correlation times a 0.11 log-point decline in relative volatility implies at a pre-period beta near 1.6.

Substantively: Bitcoin's volatility relative to the equity market fell after the listing, which is the direction a broader, less levered, more institutional investor base would predict, while its *correlation* with equities did not move. That is an interesting composite finding — the clientele appears to have changed the asset's volatility, not its factor loading — and it is the one result in the paper that a habitat story can partially claim. It should be reported as suggestive: the randomization $p$-value of 0.20 is the minimum-but-one attainable with nine donors, and the paper should not lean on it harder than that.

There is no version of these results in which co-movement rose and the correlation measure failed to see it.

---

## 14. Robustness — realized

All twenty-two rows in `robustness_results.json`. Randomization $p$-values are on nine placebo assignments, so the minimum attainable is 0.10.

| Key | $\hat\tau$ | SE | $p_{\text{clustered}}$ | $p^{\mathrm{RI}}$ | $N$ |
|---|---|---|---|---|---|
| `utc_alignment` | $-0.0212$ | 0.0170 | 0.243 | 0.80 | 540 |
| `alignment_offday_span` | $-0.0212$ | 0.0187 | 0.286 | 0.80 | 540 |
| `excl_halving` | $-0.0217$ | 0.0169 | 0.231 | 0.80 | 520 |
| `ctrl_vix_move` | $+0.0195$ | 0.0201 | 0.357 | 0.80 | 540 |
| `placebo_bito_2021` | $+0.0412$ | 0.0165 | **0.034** | 0.40 | 310 |
| `excl_extreme_news` | $-0.0353$ | 0.0165 | 0.061 | 0.60 | 540 |
| `no_donut` | $-0.0092$ | 0.0159 | 0.577 | 1.00 | 600 |
| `leg_mkt` | $-0.0239$ | 0.0174 | 0.204 | 0.80 | 540 |
| `leg_acwx_non_us` | $-0.0496$ | 0.0145 | **0.008** | 0.30 | 540 |
| `outcome_beta` | $-0.1890$ | 0.1431 | 0.219 | 0.80 | 540 |
| `outcome_ln_sigma_ratio` | $-0.1128$ | 0.0297 | **0.004** | 0.20 | 540 |
| `placebo_gold` | $-0.0400$ | 0.0170 | **0.043** | 0.50 | 540 |
| `placebo_silver` | $-0.0340$ | 0.0170 | 0.076 | 0.70 | 540 |
| `winsorized` | $-0.0184$ | 0.0173 | 0.313 | 1.00 | 540 |
| `sample_extended_2026` | $-0.0088$ | 0.0157 | 0.589 | 0.90 | 610 |
| `twoway_cluster` | $-0.0212$ | 0.0229 | 0.379 | 0.80 | 540 |
| `subwindow_pre_halving` | $-0.2613$ | 0.0316 | **0.000** | 0.10 | 330 |
| `subwindow_pre_election` | $-0.0439$ | 0.0193 | **0.049** | 0.60 | 400 |
| `subwindow_post_election` | $-0.0066$ | 0.0189 | 0.736 | 1.00 | 450 |
| `window_60d` (daily) | $-0.0183$ | 0.0208 | 0.401 | — | 10,810 |
| `window_90d` (daily) | $-0.0169$ | 0.0210 | 0.443 | — | 10,570 |

The point estimate is negative in nineteen of twenty rows and never exceeds 0.05 in absolute value except in the two sub-window rows and the two alternative outcomes. Six rows deserve comment.

**`ctrl_vix_move` (R4) is the substantively important one, and it does not behave the way §10 anticipated.** Letting the macro regime load *differentially* on Bitcoin flips the treatment coefficient from $-0.0212$ to $+0.0195$. The reason is visible in the interaction itself: `vix_x_btc` $= +0.0100$ (SE 0.0018, clustered $p = 0.0003$) — Bitcoin's equity co-movement loads strongly and positively on the VIX level, far more than the control coins' does. `move_x_btc` is $-0.00034$ (SE 0.00029, $p = 0.276$) and does nothing.

> Source: `robustness_results.json#ctrl_vix_move.coefficients`

So Bitcoin's equity co-movement *is* a differential function of the macro volatility regime, and once that is controlled for the treatment estimate moves by roughly two-thirds of a randomization standard deviation, from slightly negative to slightly positive. Both remain far inside the randomization distribution ($p^{\mathrm{RI}} = 0.80$), so neither is distinguishable from zero, and the sign flip is not a finding. But it *is* a statement about precision: the headline estimate is not robust in sign to a defensible alternative specification, and a paper claiming a positive ETF effect of this magnitude could have been produced from this data by choosing R4 as the headline. The null is robust; the sign is not, and the paper should say so rather than present $-0.021$ as though the negative sign meant something.

**`placebo_gold` and `placebo_silver` (R11) pass, but only under the right inference.** Gold assigned Bitcoin's treatment date gives $-0.0400$ with a **clustered $p$ of 0.043**. Under the conventional column, gold breaks at January 2024 — which §11 committed to treating as falsifying the design's macro-neutrality. Under randomization inference the same estimate has $p = 0.50$: it is a completely ordinary draw from the placebo distribution. Silver behaves the same way ($-0.0340$, clustered $p = 0.076$, $p^{\mathrm{RI}} = 0.70$). The design's macro-neutrality survives, and it survives *because* the inference procedure was chosen in §8 before this row was run. Had the paper used clustered $p$-values, its own pre-registered falsification test would have killed it on a false positive.

**`placebo_bito_2021` (R6) produces a larger estimate than the real event.** The 2021 futures-ETF launch gives $+0.0412$ — twice the magnitude of the actual spot approval and of the opposite sign — with a clustered $p$ of 0.034 and a randomization $p$ of 0.40. §10 pre-committed to reading a null here as favouring the spot-plumbing channel over a pure listing/visibility channel. That reading is not available: the placebo estimate is not null, it is bigger than the treatment estimate. What the row actually establishes is a bound on how much this design can distinguish: a non-event in the same panel generates a larger apparent effect than the event under study. The channel inference is not drawn from it, and the row is reported for what it is — a demonstration that estimates of this size are noise.

**`subwindow_pre_halving` (R15) is the largest coefficient in the paper and the most likely to be over-read.** With the post window truncated at 2024m3, $\hat\tau = -0.2613$ (clustered SE 0.0316, clustered $p < 0.001$, $p^{\mathrm{RI}} = 0.10$ — the most extreme of the ten assignments). It rests on **two** post-treatment months for Bitcoin: 2024m2, where the Fisher-z correlation was $-0.093$, and 2024m3. Bitcoin's equity correlation in the two months immediately after listing was unusually low, more extreme than any control coin's over the same months. Two observations do not establish a treatment effect, the randomization $p$ is at the floor imposed by having nine donors rather than genuinely small, and the direction is opposite to the habitat prediction. It is reported because §3.4 pre-committed to reporting it, with $n_{\text{post}} = 2$ printed next to it. The pre-election sub-window ($-0.0439$, $p^{\mathrm{RI}} = 0.60$, nine post months) is the figure §3.4 designated as ETF-attributable, and it is a null.

**`leg_acwx_non_us` (R16) points the wrong way for the habitat story.** Against non-US equities, Bitcoin's differential co-movement change is $-0.0496$ — more negative than against SPY ($-0.0212$). §10 specified that a US brokerage habitat should raise co-movement *more* against US equities than against non-US equities. The ordering is in the predicted direction (US less negative than non-US) but both are negative and the randomization $p$ is 0.30. The most that can be said is that the data do not contradict the ordering; they do not support it either.

**`utc_alignment` (R2) turned out not to be a test, and the substitute is.** The delivered `daily_returns.csv` crypto series are already on the UTC clock, so rebuilding UTC returns from the raw price files reproduces `main` exactly (`reproduces_main_exactly: true`, identical estimate and identical SE). The equity-close (16:00–16:00 ET) clock is not constructible from the delivered data. The feasible alignment test is `alignment_offday_span`, which cumulates weekend and holiday crypto returns into the next equity session so each crypto return spans the same calendar interval as the equity return it is correlated against. That adjustment is material at the series level — it changes Bitcoin's monthly correlation by 0.053 on average across 310 adjusted sessions — but it changes the DiD estimate by less than $2\times10^{-6}$ while raising the standard error from 0.0170 to 0.0187. The reason is that the weekend effect is common across crypto assets and is absorbed by the month fixed effects, which is the correct behaviour and a small piece of evidence that the fixed effects are doing what they are supposed to.

> Source: `robustness_results.json#utc_alignment.reproduces_main_exactly`, `#alignment_offday_span`

The `no_donut` row gives $-0.0092$ against the donut's $-0.0212$, so the donut is doing very little — consistent with the absence of a treatment effect to anticipate. The `sample_extended_2026` row ($-0.0088$, 610 observations) shows the extra seven months of data move the estimate toward zero.

A diagnostic row, `sanity_rebuild_check`, records that Bitcoin's delivered monthly Fisher-z outcome and the same object rebuilt inside `run_estimation.py` from `daily_returns.csv` correlate at 1.000 across 60 months, which is what licenses the four rows built on rebuilt outcomes (`utc_alignment`, `alignment_offday_span`, `excl_extreme_news`, `winsorized`, `leg_acwx_non_us`) to be compared against `main`.

---

## 15. Summary of what was and was not estimated

**Estimated and reported:** the primary TWFE DiD with randomization inference, Conley–Taber intervals and a wild cluster bootstrap; the descriptive raw gap; the binned event study with randomization-based pre-trend tests; the daily rolling-window panel DiD at 30, 60 and 90 days; the returns-level per-asset interacted model with its control-coin placebo distribution; the pooled returns-level triple difference; the DCC-GARCH(1,1) with a post dummy in the correlation target, for BTC–SPY and all nine control pairs; Bai–Perron multiple break tests on the level and differential series with sequential $\sup F$, BIC and LWZ; Andrews sup-Wald in iid and HAC versions; the Chow test with classical, HC3 and HAC variants; the BDM collapse; the power/MDE analysis; and all twenty-two robustness and placebo rows in §14.

**Specified but not estimable on this build, with reasons stated rather than substituted:**

- **The full session DDD (§7).** Requires intraday or session-split returns. The workspace has daily and off-day UTC returns but no intraday split. The off-day variant is the estimable fragment (`alignment_offday_span`); the full test is not, and no proxy is offered. This matters more than the other gaps, because the session DDD is the design `identification_strategy.md` ranks highest on internal validity and the only one that absorbs the halving and the election outright — and §12.5 shows the halving is where the one real 2024 break in this series actually sits.
- **The staggered multi-cohort extension (§7).** The delivered panel flags only BTC as treated; ETH, SOL and XRP carry `cohort == "eventually_treated"` but `d_etf_listed == 0` throughout, so no post-listing variation exists for them here. Callaway–Sant'Anna is specified and would be the correct estimator; it is not estimable on this build. This is also the single change that would most improve the paper's power (§12.6).
- **The prior-halving placebo, F5 (§11).** The panel begins 2021m1; the 2016 and 2020 halvings are outside coverage. Since the April 2024 halving is the design's binding residual confound and §12.5 dates the only clear 2024 break to within two weeks of it, the inability to run this placebo is a real limitation and is stated as one. It is partly offset by `excl_halving` and the pre-halving sub-window, neither of which is as good a test.
- **False-news placebos, F4 (§11).** Both candidate dates (2024-01-09, 2023-10-16) fall inside the donut, and the intraday price-response leg requires data not present. Not estimable.
- **Rambachan–Roth breakdown values (§5).** The procedure requires a variance estimate the one-treated-unit design cannot credibly supply. The randomization interval in §12.6 is reported in its place, and the substitution is flagged rather than the check being dropped silently.
- **Synthetic control (§7).** Not estimated; the placebo-in-space grid supplies the same inference channel directly.

**On the primary specification's status.** The design declared in `identification_spec.json` — coin and year-month fixed effects, no controls, clustered on coin, coin-month unit, Fisher-z outcome — was estimable exactly as declared, and that is what `main` reports. The `fallback` entry (Bitcoin-only time series with a post dummy) was **not** invoked as the headline: it appears as `descriptive_raw_gap`, labelled descriptive, exactly as §4 requires.

---

## 16. What the numbers add up to

This paper asked whether changing who holds an asset changes its factor structure when fundamentals are mechanically constant. On this data the answer is that no change is detectable, and the interesting part is how many ways that answer arrives.

Six estimators disagree about almost everything except the conclusion. The DCC finds a positive shift in Bitcoin's correlation target; the per-asset returns model finds a large negative shift in its beta; the panel DiD finds nothing. All three dissolve into the same result the moment a control group is applied, because **every crypto asset's equity beta fell and every crypto pair's DCC correlation target rose over this window**. The common component is large and the Bitcoin-specific component is not distinguishable from zero. A paper that ran any one of these specifications on Bitcoin alone would have reported a significant result, and it would have been reporting 2024.

The inference procedure does comparable work. Three separate conventional tests reject at conventional levels — the pre-trend $F$ at $p = 0.002$, the gold placebo at $p = 0.043$, the iid Andrews sup-Wald at 140 against a critical value near 9 — and all three are artifacts: of one treated cluster, of one treated cluster again, and of a 29-of-30-day window overlap. The randomization and HAC versions of the same three tests return 0.80, 0.50, and 6.39. §8 fixed the inference procedure before any of this was known, which is the only reason those three numbers are corrections rather than results.

Two honest limitations qualify the conclusion. The estimate is not robust in *sign* to allowing the macro volatility regime to load differentially on Bitcoin (§14, R4) — it is robustly null, not robustly negative. And the design's minimum detectable effect, 0.148 in correlation units, sits between the two bars §9.2 set in advance, so the paper can rule out an increase above roughly 0.09 but cannot rule out one of 0.05. The single change that would move that number is more treated units, which the ETH, SOL and XRP cohorts will supply once their listings are flagged in the panel.
