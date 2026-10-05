# Identification Strategy

**Paper:** *No Cash Flows, New Owners: Spot Bitcoin ETFs and the Origins of Comovement*
**Paper ID:** e432cf3f-9008-4202-8ee6-ff09a93948ec · **Stage:** idea → identification
**Question:** Did the January 2024 approval of US spot Bitcoin ETFs change the co-movement between Bitcoin returns and US equity returns?

---

## 1. The causal claim and the estimand

**Claim.** The SEC's January 10, 2024 approval order and the January 11, 2024 commencement of trading in eleven US spot Bitcoin ETPs lowered the participation cost for US brokerage-channel investors, shifting the identity of Bitcoin's marginal holder toward investors whose stochastic discount factor prices US equities, and thereby *raised Bitcoin's co-movement with US equities*. Because Bitcoin has no cash flows, no earnings, and a fixed public issuance schedule, no change in fundamental covariance is available as an alternative explanation: any change in factor loadings is a discount-rate or clientele effect.

**Estimand.** Let $\rho_{it}$ denote the co-movement of asset $i$ with the US equity market over an interval ending at $t$, and let $D_i(t)=1$ if asset $i$ has a US-listed spot ETF trading at $t$. The target is

$$\tau \;=\; \mathbb{E}\big[\, \rho_{\mathrm{BTC},t}(1) - \rho_{\mathrm{BTC},t}(0) \;\big|\; t \in \text{post} \,\big],$$

the average post-listing change in Bitcoin's equity co-movement *relative to what it would have been had the ETF not been approved*, over a medium-run (roughly two-year) horizon. Three properties of this estimand should be stated in the paper and not softened later:

- It is an **intent-to-treat on access availability**, not a treatment effect of any investor's portfolio decision. The treatment is "a US spot ETF exists and trades," not "allocators hold Bitcoin."
- It is a **medium-run** object. Two post-years cannot speak to the steady state.
- It is defined on **co-movement**, a second moment. This is why almost every design that works for first moments (announcement returns, event-study CARs) does *not* directly deliver it, and why the design problem is harder than a standard event study.

---

## 2. The central threat, stated precisely

The naive estimator is a single-asset, single-date pre/post contrast, $\widehat{\Delta} = \hat\rho^{\,\text{post}}_{\mathrm{BTC}} - \hat\rho^{\,\text{pre}}_{\mathrm{BTC}}$. Its expectation decomposes into four terms, only the first of which is the object of interest:

$$\mathbb{E}[\widehat\Delta] \;=\; \underbrace{\tau}_{\text{ETF}} \;+\; \underbrace{\Delta^{\text{macro}}}_{\text{common regime}} \;+\; \underbrace{\Delta^{\text{BTC}}}_{\text{BTC-specific, non-ETF}} \;+\; \underbrace{\Delta^{\text{meas}}}_{\text{measurement}}$$

**$\Delta^{\text{macro}}$ — the 2024 regime.** Four concurrent shifts each plausibly raise the equity co-movement of *every* long-duration, high-beta, non-cash-flow asset, with no reference to ETFs:

1. *Fed pivot expectations.* From late 2023 the market priced an easing cycle. When a single common factor — the expected path of policy rates — becomes the dominant driver of both equity and crypto discount rates, cross-asset correlation rises mechanically.
2. *Falling rate volatility.* The decline in MOVE from its 2022–23 highs compresses the idiosyncratic, rates-driven component of risk-asset returns, which *raises* the share of variance attributable to the common risk-appetite factor and therefore raises measured correlations even with an unchanged covariance structure in levels.
3. *The AI-driven equity rally.* The market factor itself changed composition: US market variance concentrated in a handful of megacap technology names. Bitcoin's loading on "the market" is not a fixed object when the market's own factor structure moves.
4. *The crypto cycle.* 2024–25 is a bull phase. Correlation between risk assets is well documented to be state-dependent.

**$\Delta^{\text{BTC}}$ — BTC-specific, non-ETF shocks.** This is the term that a crypto-control DiD does **not** remove, and it must be confronted rather than assumed away:

- The **April 19–20, 2024 halving** — a Bitcoin-only supply event, 14 weeks after listing.
- The **November 5, 2024 US election** and the ensuing repricing of crypto policy (strategic-reserve proposals, personnel changes). This was disproportionately a *Bitcoin* story, not a uniform crypto story.
- Bitcoin-specific narrative shocks (e.g. the March 2023 regional-banking episode, in the pre-period, during which Bitcoin *decoupled upward* from equities — a pre-period event that mechanically lowers $\hat\rho^{\text{pre}}$ and inflates $\widehat\Delta$).

**$\Delta^{\text{meas}}$ — measurement that can manufacture the result.** Two are first-order and one of them is, in our judgment, the most underrated threat in this literature:

- *Resynchronization.* Bitcoin trades 24/7; US equities close at 16:00 ET. If the ETF shifted Bitcoin price discovery into US cash hours — which is precisely what the paper's own mechanism predicts — then daily correlation measured on a 16:00 ET clock rises **mechanically**, because more of the shared information is now impounded inside the same daily bucket, *even if the true 24-hour covariance is unchanged*. A naive reading would report this as the headline effect. The paper must separate "co-movement rose" from "co-movement got re-timed." The remedy is a Dimson/Scholes–Williams summed-lag correlation, which is invariant to the timing shift (§9, F9).
- *Beta versus correlation.* $\beta = \rho\,\sigma_i/\sigma_m$, and Bitcoin's realized volatility fell over the sample. A $\beta$-based outcome therefore mixes the object of interest with a volatility-ratio trend. This is one of two reasons the workhorse outcome is the **correlation**, not the beta (§3).

**Why no design fully solves this alone.** There is exactly one treated asset and one treatment date. Every design below is an attempt to construct a counterfactual for $\rho_{\mathrm{BTC},t}(0)$, and each one removes a different subset of the nuisance terms. The strategy is therefore explicitly a **ladder**: each successive design differences out one more term at the cost of a narrower estimand.

| Design | Removes $\Delta^{\text{macro}}$ | Removes $\Delta^{\text{BTC}}$ | Removes $\Delta^{\text{meas}}$ | Estimand |
|---|---|---|---|---|
| Naive pre/post | ✗ | ✗ | ✗ | — |
| (a) Endogenous break test | ✗ (dates it only) | ✗ | partly | break location, not magnitude |
| (b) DiD on crypto controls | ✓ | ✗ | ✓ if applied symmetrically | total $\tau$ |
| (c) DDD with gold | ✓ (under strong separability) | ✗ | ✗ | total $\tau$, weakly |
| **(c′) DDD with trading sessions** | ✓ | **✓** | ✓ | US-hours *relocation* component of $\tau$ |
| (d) High-frequency around announcement | ✓ | ✓ | n/a | announcement surprise, not $\tau$ |
| (e) Placebos | — | — | — | falsification only |

---

## 3. Outcome construction is part of identification

Two construction choices do more work here than the choice of estimator, and both are settled before estimation.

**(i) The return clock.** Baseline daily returns for all crypto assets are computed on a **16:00 ET → 16:00 ET** clock, aligning the crypto day with the US equity close. The 00:00 UTC clock is reported as robustness. This is a plausible source of disagreement across the existing literature and is flagged as such.

**(ii) Fisher-z correlation, not beta, as the workhorse outcome.** For coin $i$ and calendar month $m$, using the $n_m \approx 21$ days on which both crypto and US equities trade:

$$\hat\rho_{im} \;=\; \widehat{\mathrm{corr}}\big(r_{i,t},\, r_{m,t}^{\text{mkt}}\big)_{t \in m}, \qquad
y_{im} \;=\; \operatorname{artanh}(\hat\rho_{im}) \;=\; \tfrac{1}{2}\ln\!\frac{1+\hat\rho_{im}}{1-\hat\rho_{im}}.$$

Three reasons this dominates a rolling-$\hat\beta$ outcome as the **headline**:

1. **The generated-outcome problem becomes tractable.** $\operatorname{Var}(y_{im}) \approx 1/(n_m-3)$: known, and — critically — *the same for every coin and every month*. The estimation error in the dependent variable is therefore classical, homoskedastic, and mean-zero, so it inflates standard errors but does not bias $\hat\tau$, and the inflation is analytically removable. The sampling variance of $\hat\beta_{im}$, by contrast, depends on $\sigma_i/\sigma_m$ and differs by an order of magnitude between Bitcoin and a small-cap altcoin, which would make the DiD residual variance itself a function of treatment status.
2. **It isolates the object of interest.** $\Delta\hat\beta$ confounds $\Delta\rho$ with $\Delta\ln(\sigma_i/\sigma_m)$. Both are reported (§9, F10), but the causal claim is about co-movement.
3. **Fisher-z is unbounded and approximately normal**, which the randomization and bootstrap inference below rely on.

**(iii) Non-overlapping monthly blocks, not daily rolling windows, for the panel.** A 60-day backward-looking rolling correlation induces a mechanical MA(59) structure: adjacent daily observations share 59/60 of their data. This has two consequences that are routinely mishandled. First, the estimated treatment effect **phases in linearly over the window length** rather than jumping — so a daily event-study coefficient plot shows a ramp regardless of the true dynamics. Second, daily "pre-trend tests" on such a series are close to uninterpretable, because the pre-period coefficients nearest the event are contaminated by post-period returns. The panel is therefore built on **non-overlapping 21-day (calendar-month) blocks**, one observation per coin-month. This also makes the effective sample size honest: roughly 60 months × 12 coins, not 15,000 quasi-independent daily observations. The 60-day rolling series is retained for figures (F1, F3) and as a robustness row, never as the headline.

**Secondary outcomes** (same panel, same specification): $\hat\beta_{im}$; $\ln(\hat\sigma_{i,m}/\hat\sigma_{m}^{\text{mkt}})$; $\hat\rho^2_{im}$ (the variance share, reported alongside every correlation to enforce magnitude discipline); Dimson-summed correlation; DCC-GARCH conditional correlation averaged within month.

---

## 4. Candidate designs: evaluation and ranking

### Ranking

| Rank | Design | Role | Verdict |
|---|---|---|---|
| **1** | **(b) DiD-in-correlation on never-ETF'd crypto controls** | **Primary / workhorse** | Only design that delivers the *magnitude* of $\tau$ while netting out the 2024 macro regime. Assumption is stated, partly testable, and bounded (Rambachan–Roth). |
| **1b** | Synthetic control for BTC's co-movement | Companion, reported beside the primary | Relaxes the exchangeability premise that TWFE imposes; placebo-in-space gives a second inference channel. |
| **2** | **(c′) Session DDD** (coin × session × time, with coin-month FE) | Strongest attribution test | *Highest internal validity in the paper.* Coin-month fixed effects absorb the halving and the election outright. Narrower estimand: the US-hours relocation component. |
| **3** | **(a) Endogenous break test** (Bai–Perron / Andrews sup-Wald) | **Validation and commitment device** | Cannot identify $\tau$ — no counterfactual — but can *falsify* the story by dating the break elsewhere. Value is asymmetric and pre-committed. |
| **4** | **(d) High-frequency identification** | Mechanism + placebo | Identifies the announcement surprise, not a second moment. The Jan-9 false post is its most valuable product, as a news-vs-plumbing placebo. |
| **5** | **(e) Placebo dates and assets** | Inference and falsification layer | Not a design. Indispensable: with one treated unit, the placebo distribution *is* the inference. |
| **6** | (c) Triple-difference with gold as the third difference | Demoted | The assumption required is stronger and less testable than the one it replaces. Gold is a far better **placebo asset** than a control group (see below). |

### (a) Structural break / time-varying parameter — validation, not identification

Bai–Perron multiple-break estimation and the Andrews sup-Wald test on the BTC-on-market regression, with the break date **not supplied to the estimator**, answer the question "when did the co-movement process change?" They cannot answer "why," because the single BTC series contains no counterfactual: a macro regime shift dated January 2024 and an ETF effect dated January 2024 are observationally identical in one time series.

Its value is genuinely asymmetric and therefore worth pre-committing to:

- If the data-selected break and its confidence interval **exclude** January 2024 — landing instead on, say, November 2024 (election) or October 2023 (the Fed-pivot turn and the *Grayscale* aftermath) — the ETF attribution is in serious trouble and this must be the headline of the break table, not a footnote.
- If the break **includes** January 2024, that is corroborative but far from sufficient, because the macro regime turned at roughly the same time.

Two refinements raise its value:

- Report the **90% confidence interval for the break date**, not just the point estimate. The relevant test is whether 2024-01-11 lies inside it. Point break dates in these tests are notoriously imprecise; a paper that reports only "the break is estimated at 2024-02" has reported nothing.
- Run the break tests on the **BTC-minus-control-coin differential** $y_{\mathrm{BTC},m} - \bar{y}_{\text{controls},m}$ as well as on the BTC series alone. Breaks in the differential cannot be generated by common macro regime shifts. This is the version that carries evidentiary weight.

Estimation window for break tests extends back to **2018-01-01**, so that earlier candidate breaks (2020 COVID, the 2021 futures-ETF launch, the 2022 rate cycle) can compete on equal terms. Trimming 15%, up to 5 breaks, Bai–Perron sequential $\sup F(\ell+1|\ell)$ and BIC/LWZ selection both reported.

Kalman-filtered TVP beta and DCC-GARCH are reported as *descriptive* devices (F3) and as alternative outcome constructions, not as identification. A DCC-GARCH correlation that rises in January 2024 is exactly as confounded as a rolling correlation that rises in January 2024.

### (b) DiD on never-ETF'd crypto controls — the workhorse

**Treated:** BTC, listed 2024-01-11. **Never-treated controls (headline):** ADA, LTC, DOGE, BCH, LINK, AVAX, DOT, XLM. **Eventually-treated (excluded from the headline control group, used in the staggered extension):** ETH (2024-07-23), SOL, XRP (2025 cohorts — *dates to be verified from primary sources*).

**Parallel trends, stated as an assumption about a second moment.** Absent the ETF listing, the Fisher-z equity co-movement of Bitcoin and of the never-treated coins would have followed parallel paths in expectation:

$$\mathbb{E}\big[\,y_{\mathrm{BTC},m}(0) - y_{\mathrm{BTC},m'}(0)\,\big] \;=\; \mathbb{E}\big[\,y_{jm}(0) - y_{jm'}(0)\,\big] \quad \forall\, j \in \text{controls},\; m \in \text{post},\; m' \in \text{pre}.$$

Note carefully what this does and does not say. It is **not** an assumption that Bitcoin and Dogecoin have the same equity correlation — coin fixed effects absorb any level difference in integration. It is an assumption that the *changes* are common. That is a much weaker and much more plausible requirement, and it is why the outcome is the co-movement itself rather than anything in levels.

**Plausibility.** The case for it: all of these assets are non-cash-flow, high-volatility, 24/7-traded, globally-held speculative claims whose discount rates respond to the same risk-appetite and rate-path factors; the macro shocks enumerated in §2 have no obvious reason to load differentially on Bitcoin versus Solana or Litecoin; and the pre-period is long enough (2021m1–2023m7, 31 months) to test the common-trend premise directly. The case against it, and the honest statement of it:

- **BTC-specific post-treatment shocks are not differenced out.** The April 2024 halving and the November 2024 election are Bitcoin events. This is the design's binding weakness. Three responses, all required: (i) report $\hat\tau$ separately for the **pre-halving window 2024m2–2024m3**, the **pre-election window 2024m2–2024m10**, and the full post window, and treat the pre-election estimate as the ETF-attributable figure; (ii) run the **prior-halving placebo** (§9, F5); (iii) rely on the session DDD, whose coin-month fixed effects absorb both shocks outright.
- **SUTVA.** Bitcoin's ETF plausibly raised other coins' equity co-movement through within-crypto integration, biasing $\hat\tau$ toward zero — so the estimate is a lower bound. But the spillover could also run the other way: if spot-ETF access *diverted* US allocator demand away from altcoins, control-coin co-movement would fall and $\hat\tau$ would be biased **upward**. The plan should not claim only the convenient direction. The empirical response is a "clean control" subsample (coins with the least US-brokerage-adjacent ownership and no US-listed derivative), plus reporting whether control-coin co-movement rose or fell in absolute terms post-2024.
- **Exchangeability.** Bitcoin is unique in size, institutional standing, and narrative. TWFE with coin FE handles fixed differences but not differential *sensitivity* to common shocks. The synthetic-control companion (rank 1b) addresses this directly by reweighting controls to match Bitcoin's pre-period co-movement path.

### (c) Triple-difference with gold — demoted, and why

The proposal is to add an asset-class dimension, using gold (ETF since 2004, no 2024 access change) to absorb macro regime shifts. We recommend **against** this as a primary design, for a reason of substance rather than taste.

A DDD requires that the macro regime's effect on equity co-movement be **additively separable and equal in magnitude across asset classes**. Gold's co-movement with equities responds to the 2024 macro regime through an entirely different structural channel from Bitcoin's: real rates and the dollar operate on gold through a safe-haven/opportunity-cost mechanism whose sign relative to equities is frequently the *opposite* of the risk-asset mechanism operating on crypto. Subtracting gold's change in co-movement from crypto's does not net out the regime; it adds a second, differently-signed regime exposure with an unknown loading. The structure is also not a clean $2\times2\times2$: gold is an always-treated unit, not a member of an untreated asset class, so there is no "gold without an ETF" cell.

Gold's correct role is as a **placebo asset**: an asset that experienced the same macro regime, has a long-standing ETF, and had no 2024 access change, and which should therefore exhibit no break in equity co-movement at January 2024. A break in gold at January 2024 would be direct evidence that the crypto result is a macro artifact. That is a sharp, falsifiable use, and it is where gold belongs.

### (c′) The third difference that does work: trading sessions

If a third difference is wanted — and it should be — take it along the **intraday session** dimension rather than the asset-class dimension. Partition the 24-hour day into Asia (00:00–07:00 ET), Europe (07:00–09:30 ET), **US cash (09:30–16:00 ET)**, and US post-close (16:00–24:00 ET), and compute session-level realized correlations against the S&P 500 E-mini future, which trades nearly around the clock and therefore makes the covariance well defined in every session.

The logic is decisive: **a macro regime shift raises global risk-asset correlation in all sessions; only a mechanism operating through a US-listed vehicle relocates covariance into US exchange hours.** Formally, with coin-month fixed effects in the specification, *every* Bitcoin-specific time shock — the halving, the election, any narrative shock — is absorbed. This is the one design in the paper that removes $\Delta^{\text{BTC}}$.

Its cost is a narrower estimand: it identifies the US-hours *relocation* component of the effect, not the total. It is therefore the strongest attribution test but not the headline magnitude, which is why (b) remains the workhorse. Note also the resynchronization caveat from §2 applies with opposite force here: relocation is not a nuisance in this design, it *is* the prediction — but the paper must then be careful not to also report the daily-clock correlation increase as independent evidence, since the two are partly the same fact.

### (d) High-frequency identification around the announcement

Three events, tight windows, intraday data:

- **E1** 2023-08-29, *Grayscale v. SEC* DC Circuit ruling (anticipation onset).
- **E2** 2024-01-09 ~16:11 ET, the compromised SEC X account announcing approval, retracted within roughly 15 minutes. **News without plumbing.**
- **E2′** 2023-10-16, the erroneous Cointelegraph report that BlackRock's ETF had been approved, retracted within roughly 30 minutes. A second, *cleaner* false-news event — cleaner than E2 because it is three months away from the real approval, so its effects cannot be contaminated by the actual listing.
- **E3/E4** 2024-01-10 ~16:00 ET (approval order) and 2024-01-11 09:30 ET (trading begins). **Plumbing.**

**What HFI can and cannot do.** It cannot deliver $\tau$: co-movement is a second moment and cannot be estimated from a 30-minute window around a single event. What it delivers is (i) precise *dating* and confirmation that the event carried real information, (ii) the **news-versus-plumbing decomposition** — E2/E2′ carry nearly identical news content to E3/E4 but changed no access, so if the co-movement change is a sentiment or narrative effect, the false-news events should move it too, and (iii) a bound on anticipation.

**Power caveat, stated up front.** Approval was heavily anticipated; by early January 2024 market-implied odds were very high. The *surprise* component of E3 is therefore small, and a null intraday response at E3 is uninformative about $\tau$. Ironically the false-news events may carry the larger surprise, which is precisely what makes them good placebos and poor treatments. The paper should not oversell the sharpness of E3.

### (e) Placebo break dates and placebo assets

Not a design but the inference backbone. With one treated unit, the placebo distribution *is* the sampling distribution (§8). Enumerated in §9.

---

## 5. Recommended design

**Primary (headline, and the specification declared in `identification_spec.json`):** two-way fixed-effects difference-in-differences in Fisher-z equity correlation on a coin-month panel of Bitcoin plus never-ETF'd crypto controls.

**Companion, reported beside the primary:** synthetic control for Bitcoin's co-movement path, with placebo-in-space inference.

**Validation:** endogenous break tests on the BTC series and on the BTC-minus-control differential, with break-date confidence intervals, pre-committed to being reported in full.

**Attribution / mechanism:** the session DDD (c′), which is the single most persuasive exhibit and the only one immune to Bitcoin-specific time shocks.

**Placebo layer:** false-news events, gold, prior halvings, the 2021 futures ETF, pre-period placebo dates.

A deliberate deviation from §9 of the paper plan, flagged for the econometrics specialist: the plan's primary was Callaway–Sant'Anna on a daily panel of $\hat\beta$ with two-way clustering. We move the headline to **TWFE on a monthly panel of Fisher-z correlation, clustered on coin, with randomization inference**. Reasons: (i) the generated-outcome variance argument in §3 favours Fisher-z decisively; (ii) non-overlapping blocks eliminate the mechanical MA structure that makes daily pre-trend tests uninterpretable; (iii) by excluding eventually-treated coins from the headline control group, the specification contains **no forbidden comparisons of already-treated units**, so the negative-weights problem that motivates Callaway–Sant'Anna does not arise by construction. CS, Sun–Abraham, and Borusyak–Jaravel–Spiess are reported as the staggered multi-cohort extension (BTC/ETH/SOL/XRP cohorts), where they are the right tools.

---

## 6. Estimating equations

### 6.1 First stage — outcome construction

For coin $i \in \mathcal{I}$ and month $m$, over the $n_m$ days on which both crypto and US equity markets trade (US market holidays excluded from the daily panel; retained separately for the weekend/holiday test):

$$\hat\rho_{im} = \frac{\sum_{t\in m}(r_{it}-\bar r_i)(r^{\text{mkt}}_t - \bar r^{\text{mkt}})}{\sqrt{\sum_{t\in m}(r_{it}-\bar r_i)^2}\sqrt{\sum_{t\in m}(r^{\text{mkt}}_t-\bar r^{\text{mkt}})^2}}, \qquad y_{im}=\operatorname{artanh}(\hat\rho_{im}),$$

with $r_{it}$ the 16:00 ET → 16:00 ET log return on coin $i$ and $r^{\text{mkt}}_t$ the CRSP value-weighted excess return (SPY as the fallback / robustness proxy).

### 6.2 Primary specification

$$\boxed{\;y_{im} \;=\; \alpha_i \;+\; \delta_m \;+\; \tau\,\mathrm{ETF}_{im} \;+\; \varepsilon_{im}\;}$$

- $\alpha_i$: **coin** fixed effects (absorb fixed differences in the level of equity integration across coins).
- $\delta_m$: **year-month** fixed effects (absorb every shock common to all crypto assets in month $m$: the Fed pivot, rate-vol compression, the AI rally, the crypto cycle).
- $\mathrm{ETF}_{im} = \mathbf{1}\{i = \mathrm{BTC}\} \times \mathbf{1}\{m \ge 2024\text{m}2\}$ in the headline sample; in the staggered extension, $\mathbf{1}\{m \ge T_i\}$ with cohort-specific listing months.
- **Controls: none.** This is a deliberate declaration, not an omission. The candidate controls — log dollar volume, market capitalisation, realized volatility — are all **mediators**, not confounders: the ETF changed Bitcoin's liquidity and volatility, so conditioning on them would absorb part of the treatment effect (bad control). They belong in a mechanism decomposition, reported separately, not in the primary equation.
- Errors clustered on **coin**; see §8, because the cluster count and the single treated unit make the CRVE $p$-value the *least* important number in the table.

### 6.3 Event study (the identification diagnostic)

$$y_{im} \;=\; \alpha_i \;+\; \delta_m \;+\; \sum_{k=-K,\,k\neq-1}^{K} \theta_k\,\mathbf{1}\{m - T_i = k\} \;+\; \varepsilon_{im},$$

in **event-month** bins, $K = 24$ leads and lags (binned at the endpoints), reference period $k=-1$. Joint $F$-test of $\theta_{-24},\dots,\theta_{-2}=0$ is the pre-trend test. Rambachan–Roth honest-DiD bounds report the **breakdown value** $\bar M$: how large a post-period deviation from the linear extrapolation of pre-trends the result can tolerate before losing significance. This number, not the pre-trend $p$-value, is what should be quoted in the text — a failure to reject a pre-trend with 31 monthly observations is weak evidence.

### 6.4 Session DDD (attribution)

For coin $i$, session $s \in \{\text{Asia},\text{Europe},\text{US cash},\text{US post}\}$, month $m$, with $\tilde y_{ism}$ the Fisher-z realized correlation between coin $i$'s session-$s$ return and the E-mini S&P session-$s$ return:

$$\tilde y_{ism} \;=\; \underbrace{\alpha_{is}}_{\text{coin}\times\text{session}} \;+\; \underbrace{\delta_{sm}}_{\text{session}\times\text{month}} \;+\; \underbrace{\gamma_{im}}_{\textbf{coin}\times\textbf{month}} \;+\; \lambda\,\big(\mathrm{ETF}_{im} \times \mathbf{1}\{s = \text{US cash}\}\big) \;+\; \nu_{ism}.$$

$\gamma_{im}$ is the crucial term: it absorbs *every* Bitcoin-specific time shock, including the halving and the election, leaving $\lambda$ identified purely from the differential relocation of co-movement into US cash hours. Companion specification adds a separate indicator for the 15:45–16:00 ET NAV-strike window.

### 6.5 Synthetic control (companion)

Weights $w_j \ge 0$, $\sum_j w_j = 1$ over never-treated coins (optionally augmented with gold and a broad crypto index) chosen to minimise pre-period distance in $y$ over 2021m1–2023m7. Report the gap $y_{\mathrm{BTC},m} - \sum_j w_j y_{jm}$ post-2024m2, with placebo-in-space $p$-values from the ratio of post- to pre-period RMSPE across all donor units.

### 6.6 Break tests (validation)

Bai–Perron on $\{y_{\mathrm{BTC},m}\}$ and on the differential $\{y_{\mathrm{BTC},m} - \bar y_{\text{ctrl},m}\}$, 2018m1–2025m12, 15% trimming, up to 5 breaks, sequential $\sup F(\ell+1|\ell)$ plus BIC and LWZ; Andrews (1993) sup-Wald with unknown breakpoint. **Report all estimated break dates and their 90% confidence intervals, whether or not they flatter the hypothesis.**

---

## 7. Sample and required windows

| Window | Dates | Role |
|---|---|---|
| Full panel | 2021m1 – 2025m12 | Estimation sample (monthly, ~12 coins) |
| Extended | 2018m1 – 2025m12 | Break tests only, so earlier breaks can compete |
| **Clean pre** | 2021m1 – 2023m7 | Ends before the 2023-08-29 *Grayscale* ruling |
| **Donut (excluded)** | 2023m8 – 2024m1 | Anticipation + false-news events + listing week + GBTC-outflow transition |
| **Clean post** | 2024m2 – 2025m12 | Post-treatment |
| Pre-halving sub-window | 2024m2 – 2024m3 | Excludes the 2024-04-19/20 halving entirely |
| **Pre-election sub-window** | 2024m2 – 2024m10 | **The ETF-attributable estimate**; excludes the 2024-11-05 election |
| Post-election sub-window | 2024m11 – 2025m12 | Reported separately, interpreted as ETF + policy regime |

Starting in 2021 avoids the March 2020 COVID correlation spike dominating the pre-period; the 2018-start version is reported in robustness. The donut is the baseline; the no-donut version and an explicit three-regime specification (pre / anticipation / post), in which the anticipation coefficient is itself interpretable, are both reported.

**Pre-committed:** the headline $\hat\tau$ is the full clean-post estimate; the **pre-election sub-window estimate is reported adjacent to it in the same table**, and if the two differ materially the text leads with the smaller, more conservative attribution.

---

## 8. Inference

The binding problem is not serial correlation alone — it is **one treated unit**. At the January 2024 date there is exactly one treated cluster. Standard cluster-robust inference is not merely conservative here; it is invalid. Four rows, reported together, with the first as primary:

**1. Randomization inference (primary).** Build the placebo distribution over a grid of counterfactual (coin, treatment-month) assignments:
- *Placebo-in-space*: assign the 2024m2 treatment date to each never-treated coin in turn (8 draws — too coarse alone: the minimum attainable one-sided $p$ is $1/9$).
- *Placebo-in-time*: assign the treatment to every candidate month in 2021m7–2023m7 for every coin including BTC.
- The **combined space-and-time grid** yields several hundred placebo estimates. Report $p^{\text{RI}} = \#\{|\hat\tau^{\text{placebo}}| \ge |\hat\tau|\}/(\#\text{placebos}+1)$ and plot the full placebo density with the true estimate marked. This is the headline $p$-value.

**2. Conley–Taber (2011).** The purpose-built procedure for few-treated-many-control DiD: use the empirical distribution of the *control-group* DiD residuals to construct a confidence interval for $\tau$. More principled than a bootstrap with one treated cluster, and it is the right second row.

**3. Wild cluster bootstrap-t, restricted (null-imposed), Rademacher weights** (Webb 6-point weights in the leave-one-coin-out robustness runs where $G<12$), 9,999 replications, Cameron–Gelbach–Miller. **Reported but not relied upon**: MacKinnon–Webb show that with a single treated cluster the restricted wild bootstrap under-rejects severely. Stating this explicitly is better than quietly reporting a $p$-value that a referee will know is uninformative.

**4. Bertrand–Duflo–Mullainathan collapse.** Average $y_{im}$ to one pre and one post observation per coin and run the DiD on the $2 \times 12$ collapsed panel. The most conservative row; immune to any within-coin serial correlation structure.

**Serial correlation, additionally.** Driscoll–Kraay standard errors (bandwidth $\approx 4$ months) and Newey–West on the collapsed time series are reported as supplementary rows, since the monthly outcome remains persistent even without window overlap.

**Generated-outcome adjustment.** Because $y_{im}$ is estimated, the primary standard errors are additionally validated by a **two-step block bootstrap**: resample daily returns by stationary bootstrap (mean block length 21 days), rebuild $\hat\rho_{im}$ and $y_{im}$, re-estimate $\tau$; 999 replications. Under the Fisher-z construction the first-stage noise is classical and homoskedastic with known variance $1/(n_m-3)$, so the analytic and bootstrap adjustments should agree — and the paper should report that they do, as a check that the construction behaves as claimed.

**Multiple testing.** Romano–Wolf stepdown adjusted $p$-values across the secondary outcome family (beta, volatility ratio, Dimson correlation, DCC correlation, factor loadings). The primary specification is pre-specified in §5 and is not adjusted.

---

## 9. Falsification tests the paper must report

Numbered as a commitment. Each is a *reportable outcome*, not a filter on what gets published.

**F1 — Pre-trend event study.** Monthly leads over 2021m1–2023m7, joint $F$-test, plus Rambachan–Roth breakdown value $\bar M$. Reported as the key identification figure regardless of outcome.

**F2 — Placebo treatment dates.** Every candidate pre-period month, for BTC and every control coin; the full RI density plotted with $\hat\tau$ marked (§8).

**F3 — Placebo assets.** (i) **Gold** (spot XAU and GLD): long-standing ETF, same macro regime, no 2024 access change → no January 2024 break. (ii) Silver, as a second precious metal. (iii) Each never-treated coin assigned BTC's treatment date. A break in gold at January 2024 falsifies the macro-neutrality of the design.

**F4 — False-news placebos (news without plumbing).** Event studies at 2024-01-09 (compromised SEC X post) and 2023-10-16 (erroneous Cointelegraph report). Report the intraday price response *and*, where feasible, the change in short-horizon realized co-movement. If co-movement responds to false news as much as to the real listing, the mechanism is sentiment, not access.

**F5 — Prior-halving placebo.** Re-run the primary DiD with treatment set to the 2016-07-09 and 2020-05-11 halvings, using contemporaneously available control coins. This directly tests whether a Bitcoin halving — the main BTC-specific shock the design cannot difference out — moves equity co-movement on its own. Caveat to state: the 2020 halving is contaminated by the COVID aftermath and the 2016 window has few usable controls; report both with the limitation attached.

**F6 — Futures-ETF placebo.** 2021-10-19, the launch of BITO. A US-listed, brokerage-accessible Bitcoin ETF that did *not* change spot plumbing (no spot creation/redemption, roll costs, futures-based). A large effect here would favour a pure listing/visibility channel; a null would favour the spot-plumbing channel. Informative in either direction, and it is a genuine falsification of "any US-listed Bitcoin vehicle raises co-movement."

**F7 — Leave-one-coin-out.** Drop each control coin in turn; report the full distribution of $\hat\tau$. Separately, drop ETH (most exposed to both spillover and its own later treatment) and report.

**F8 — Alternative market proxies and a non-US equity placebo.** CRSP VW, SPY, NASDAQ-100, Russell 2000, and **MSCI World ex-US**. If the mechanism is a *US* brokerage habitat, co-movement should rise more against US equities than against non-US equities once the global factor is netted out. A uniform rise against all equity indices points to global macro.

**F9 — Return-clock and resynchronization test.** Re-estimate on the 00:00 UTC clock, and — the substantive test — on **Dimson/Scholes–Williams summed lead–contemporaneous–lag correlations**, which are invariant to a shift in *when* within the day information is impounded. If the effect survives the Dimson construction, it is not pure resynchronization. If it does not, the paper must say so: the finding would then be that the ETF re-timed price discovery without changing 24-hour covariance, which is itself a real and reportable result.

**F10 — $\rho$ versus $\sigma$-ratio decomposition.** Report $\Delta y$ (Fisher-z correlation), $\Delta \ln(\sigma_{\mathrm{BTC}}/\sigma_{\text{mkt}})$, and $\Delta\hat\beta$ side by side, plus $\hat\rho^2$ (the equity-driven share of Bitcoin return variance) next to every correlation. The paper does not write "Bitcoin became a risk asset" on the strength of a correlation of 0.4, which is a 16% variance share.

**F11 — Endogenous break dates, reported in full.** All Bai–Perron breaks with 90% confidence intervals, on the BTC series and on the BTC-minus-control differential, 2018–2025. Pre-committed: if the differential's break CI excludes January 2024, that is the headline of the break table.

**F12 — Window, estimator, and sample grid.** Block length (21 / 42 / 63 / 126 days); rolling-window version; DCC-GARCH and ADCC conditional correlation as alternative outcomes; Kalman TVP; donut on/off; winsorization at 0.5/99.5 on/off; 2018 start; large-cap-only control set; clean-control subsample; TWFE vs. Callaway–Sant'Anna vs. Sun–Abraham vs. Borusyak–Jaravel–Spiess in the staggered extension.

**F13 — Session DDD as falsification.** $\Delta\mathrm{Cov}^{\text{US}} - \Delta\mathrm{Cov}^{\text{Asia}} > 0$ is a required finding for the mechanism. If the increase is spread evenly across sessions, the paper reports that the mechanism is global macro rather than the ETF, per the pre-analysis decision rule.

**F14 — Weekend margin.** Bitcoin trades weekends; the ETF does not. If the ETF's marginal holder sets the price, Bitcoin's weekend share of volume and volatility should fall post-2024, and weekend returns should become less informative for Monday pricing. An independent corroboration from a direction the DiD does not use.

---

## 10. Pre-commitments and what would make us wrong

**Decision rule (from the paper plan §9, retained).** H1 (integration) is supported only if **both** (i) the primary DiD $\hat\tau > 0$ with RI $p < 0.05$, and (ii) the session DDD shows the increase concentrated in US cash hours. Either alone is insufficient: the DiD alone cannot rule out a Bitcoin-specific shock coinciding with the event, and the session result alone cannot rule out a shift in the global news cycle.

**What would make us wrong:**
- The break in the **BTC-minus-control differential** dates to November 2024 → the election-and-policy story dominates.
- The session decomposition shows an even spread across Asian and US hours → the mechanism is global macro.
- **Gold shows a January 2024 break** → the macro regime, not the ETF, is moving cross-asset co-movement.
- The effect disappears under the **Dimson-summed** construction → the finding is re-timing of price discovery, not a change in co-movement.
- The **prior-halving placebo** is significant → the design cannot separate the ETF from the halving and the pre-halving sub-window becomes the only credible estimate.

**Null interpretation is fixed in advance.** If $\hat\tau \approx 0$, the paper's contribution is the reverse insight: shared ownership and a shared trading venue were *not sufficient* to generate habitat co-movement in an asset with no cash flows — evidence against the pure category view and in favour of information-diffusion mechanisms. This is committed to now.

**Minimum credibility bar met:** difference-in-differences with an explicit parallel-trends test, bounded sensitivity to its violation (Rambachan–Roth), a valid inference procedure for one treated unit (randomization inference, Conley–Taber), and a design (the session DDD) that removes the residual confound the DiD cannot.

---

## 11. Threat register

| Threat | Severity | Where handled |
|---|---|---|
| 2024 macro regime (Fed pivot, rate-vol, AI rally, crypto cycle) | High | Month FE in (b); session DDD; gold placebo (F3) |
| **April 2024 halving** (BTC-specific, post-treatment) | **High** | Pre-halving sub-window; prior-halving placebo (F5); coin-month FE in (c′) |
| **November 2024 election** (BTC-specific, post-treatment) | **High** | Pre-election sub-window as the attributable estimate; coin-month FE in (c′) |
| Anticipation / treatment leakage from the 2023 *Grayscale* ruling | High | Donut 2023m8–2024m1; three-regime specification; E1 event study |
| **Resynchronization masquerading as co-movement** | High | Dimson/Scholes–Williams summed correlation (F9) |
| One treated unit → invalid CRVE inference | High | RI primary; Conley–Taber; BDM collapse (§8) |
| Cross-coin spillovers (SUTVA), sign ambiguous | Medium-high | Clean-control subsample; report control-coin levels; state both bias directions |
| Bitcoin not exchangeable with control coins | Medium-high | Synthetic control companion; outcome in changes, coin FE |
| Generated outcome ($\hat\rho$ as LHS) | Medium | Fisher-z (known, coin-invariant variance); two-step block bootstrap |
| Rolling-window overlap → uninterpretable pre-trends | Medium | Non-overlapping monthly blocks as the panel |
| Beta/correlation conflation via falling $\sigma_{\mathrm{BTC}}$ | Medium | Correlation as headline outcome; F10 decomposition |
| Short post-period (two years) | Medium | Framed as medium-run; results reported by post-year |
| Multiple hypothesis testing across designs | Low-medium | Pre-specified primary; Romano–Wolf on the secondary family |

---

## 12. Contract with the econometrics specialist

`identification_spec.json` declares the headline specification. It must be echoed exactly by the `main` entry of `estimation_results.json`:

- **Unit of analysis:** `coin-month`. One observation per coin per calendar month.
- **Outcome variable, named exactly `fisher_z_corr_equity`:** $\operatorname{artanh}$ of the within-month realized correlation between the coin's 16:00 ET daily log returns and the US equity market excess return.
- **Treatment variable, named exactly `etf_listed`:** indicator for coin $i$ having a US-listed spot ETF trading in month $m$. In the headline sample this equals $\mathbf{1}\{\text{BTC}\}\times\mathbf{1}\{m\ge 2024\text{m}2\}$.
- **Fixed effects, named exactly `coin` and `year_month`.** The time fixed effect is the calendar *year*-month (e.g. `2024-02`), **not** calendar month-of-year. The panel columns must carry these names.
- **Controls: `[]`.** Empty by design, per §6.2 — the candidate controls are mediators. Do not add covariates to the headline equation.
- **Cluster level: `coin`.** This supersedes the paper plan's "two-way by coin and day" for the headline row; two-way clustering is a robustness row. The clustered $p$-value is reported but the **randomization-inference $p$-value is the one the text quotes** (§8).
- **Headline sample:** BTC plus never-treated coins only. Eventually-treated coins (ETH, SOL, XRP) are excluded from the headline control group and appear only in the staggered extension.
- **Fallback**, if the control-coin panel cannot be built: a single-series regime-interaction regression on Bitcoin alone, with the break date validated by sup-Wald and HAC errors. This is descriptive, not identified, and must be labelled as such in any table that reports it.
