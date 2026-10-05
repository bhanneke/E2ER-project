# Identification Review

**Paper:** *No Cash Flows, New Owners: Spot Bitcoin ETFs and the Origins of Co-movement*
**Paper ID:** e432cf3f-9008-4202-8ee6-ff09a93948ec
**Reviewer role:** Identification Reviewer
**Scope:** the credibility of the causal claim — estimand, identifying assumptions, threats, inference validity, falsification, power, and the correspondence between what the design establishes and what the paper claims.

---

## 1. Summary assessment

**Verdict: Major Revision.**

This is a careful paper with an unusually honest inferential core and a materially weaker identification core than the writing implies. The two should be graded separately.

The inference work is the best thing in the paper and is, in places, exemplary. The authors correctly identify that a one-treated-unit design has no valid cluster-robust asymptotics, fix randomization inference as the governing procedure *before* estimation, and then demonstrate — with three separate examples — that the conventional column would have produced three false positives. The pre-trend $F$-test placebo exercise (Bitcoin's $F = 9.185$ lies below the median placebo $F = 17.36$) and the iid-versus-HAC sup-Wald comparison ($140.41 \to 6.39$) are genuine public-goods results that deserve to be cited by other people working in this setting. Reporting a minimum detectable effect against a pre-registered bar, landing between the bars, and declining to upgrade the claim is the kind of discipline this literature almost never shows.

The identification core is thinner than the paper presents it as being, in five specific ways.

1. **A first-order confound is measured, reported, and then misclassified as a robustness curiosity.** Bitcoin's differential loading on the equity-volatility regime is estimated at $+0.0100$ per VIX point with a clustered SE of $0.0018$. The VIX regime fell sharply between the pre- and post-periods. This is not a specification quibble; it is a violation of parallel trends with a directly measurable magnitude, and the arithmetic below shows it accounts for essentially the entire headline point estimate (§4).
2. **The paper's randomization-inference defence of parallel trends is misread.** A valid test failing to reject establishes that Bitcoin's pre-trend is *typical of the panel*, not that it is *absent*. The paper's own linear pre-trend estimate, extrapolated across the gap between the pre- and post-period centroids, is larger in magnitude than the headline coefficient (§5).
3. **The "no cash flows" identification argument does no identification work in the design as executed** — the control coins have no cash flows either, so the property is differenced out (§8).
4. **Five pre-specified, feasible checks are missing without adequate justification**: synthetic control, leave-one-coin-out, the clean-control subsample, the three-regime anticipation specification, and Romano–Wolf adjustment (§9).
5. **The abstract makes a break-dating claim the evidence cannot support**, because break-date confidence intervals were declined — and the paper's own identification document said in terms that a break point without an interval "has reported nothing" (§7.3).

None of this overturns the null. I think the null is probably right, and the paper's power self-assessment survives my own independent arithmetic (§6). But the paper's *only* substantive positive claim — that it excludes correlation increases above roughly $0.086$ — rests on an interval computed under exact parallel trends, with an undocumented construction, and a linearized units conversion that is off by about 5%. That claim needs to be rebuilt before it can carry the abstract.

---

## 2. The estimand and what the design actually identifies

The paper defines $\tau$ as the post-listing change in Bitcoin's equity co-movement relative to the no-ETF counterfactual, an ATT on a second moment over a medium-run horizon. That is the right target and it is stated with appropriate care. Three refinements are needed.

**(a) It is an intent-to-treat on access availability.** The paper says this in the identification document but the draft never restates it. The treatment is "a US spot ETF exists and trades," not "allocators hold Bitcoin." Given that a substantial share of the resulting AUM was market-neutral basis-trade positioning — the paper's own §3 argument — the wedge between the ITT and the allocation-weighted effect is potentially large. This belongs in the results section, not only in the framework.

**(b) The design identifies the *Bitcoin-specific* component only, and the paper should say so where the reader will see it.** With coin and calendar-month fixed effects, any ETF effect that propagated uniformly to the control coins is absorbed by $\delta_m$ and is invisible by construction. This is conceded in the SUTVA paragraph but is then contradicted in interpretation: §"What the control group is doing" reports that the raw Bitcoin-only gap ($-0.0064$) and the identified estimate ($-0.0212$) are both near zero and reads this as "the month fixed effects find essentially nothing Bitcoin-specific to remove."

The near-identity of the raw gap and the DiD estimate is *equally consistent with complete spillover contamination*, which the paper's own citation to Hu, Parlour and Rajan says is the empirically likely case for cryptoassets. Under complete contamination, the DiD has zero power against a crypto-wide integration effect operating through the Bitcoin wrapper — which is a live mechanism, since the paper's own framework says the ETF restored a spot creation/redemption channel that transmits US-session liquidity into the crypto spot market generally. The paper should present the raw-gap/DiD agreement as *uninformative between* "nothing happened" and "everything happened to everyone," and then say which parts of its interpretation survive each reading.

**(c) The SUTVA direction is reported selectively.** The identification document enumerated both bias directions: contamination attenuates toward zero, but *diversion* of US allocator demand away from altcoins would lower control-coin co-movement and bias $\hat\tau$ **upward**. The draft retains only the attenuation direction and presents it as cutting against the paper's own finding. Retaining only the convenient direction is exactly the move the identification document warned against ("The plan should not claim only the convenient direction"). Restore both, and adjudicate between them with the evidence you already have: control-coin co-movement *rose* in absolute terms post-2024 ($+0.0105$), which is more consistent with contamination than with diversion. That is a one-sentence fix and it makes the paper stronger, not weaker.

---

## 3. Parallel trends as an assumption about a nonlinear function of moments

The identifying assumption is stated on the Fisher-$z$ scale. It cannot hold simultaneously on the $\rho$, $z(\rho)$, $\beta$, and covariance scales, because these are nonlinear transforms of each other and the paper's own decomposition shows that a *different* moment moved differentially: $\ln(\sigma_i/\sigma_{mkt})$ falls by $-0.1128$ with the largest clustered $t$-statistic in the paper.

This is Roth and Sant'Anna (2023) territory and the paper does not engage with it. Parallel trends is functional-form-insensitive only under a strong condition on the distribution of potential outcomes; absent that condition, the choice of $z(\rho)$ over $\rho$ over $\beta$ over $\mathrm{Cov}$ is an identifying assumption, not a measurement convention. The paper's three stated reasons for Fisher-$z$ (variance stabilisation, unboundedness, disjoint blocks) are all *statistical* arguments about the estimator, not arguments about which scale the counterfactual is parallel on.

**Required:** a paragraph in §5 acknowledging that the scale choice is part of the identifying assumption; a statement of which scale the economic mechanism predicts parallel counterfactual paths on (the clientele model in eq. 1 is written in $\beta$, not in $z(\rho)$, which is worth noticing); and either the Roth–Sant'Anna condition or an explicit concession that the null is scale-conditional. The fact that the null obtains on all three scales ($z$: $-0.021$, $p^{RI}=0.665$; $\beta$: $-0.189$, $p^{RI}=0.80$) is the natural defence and should be promoted from a table row to the identification section.

---

## 4. The differential macro-volatility loading is a first-order confound, not a robustness row

This is my central identification concern, and I think the paper is roughly forty percent of the way to seeing it.

The `ctrl_vix_move` row moves $\hat\tau$ from $-0.0212$ to $+0.0195$ — a shift of $+0.0407$ in Fisher-$z$ units. The paper reports this, calls it "the substantively important row," notes the sign flip, and concludes "the null is robust; the sign is not." That is honest but it stops one step short of the diagnosis, and the diagnosis matters.

**The arithmetic.** The reported interaction coefficients are $\texttt{vix\_x\_btc} = +0.0100$ (clustered SE $0.0018$) and $\texttt{move\_x\_btc} = -0.00034$. The shift in $\hat\tau$ induced by adding these interactions is, to first order, the product of each differential loading and the pre-to-post change in the corresponding macro level. Solving $0.0407 \approx 0.0100 \cdot \Delta\overline{\mathrm{VIX}} \times(-1) + (-0.00034)\cdot\Delta\overline{\mathrm{MOVE}}\times(-1)$ against plausible regime changes (VIX falling roughly 3–4 points and MOVE falling roughly 30 points between 2021–2023 and 2024–2025) reproduces the observed shift almost exactly. I cannot run the regression, so I present this as a reviewer's decomposition the authors must verify — but it is internally consistent with every number the paper reports, including the sample VIX mean of 19.25 with SD 5.12.

**What this means.** The headline negative sign is, on this reading, a *composition effect*: Bitcoin's equity co-movement is a differentially steep function of the equity-volatility regime, the volatility regime fell across the treatment date, and coin and calendar-month fixed effects cannot absorb a *differential* loading on a common factor. This is precisely the version of the macro-confounding story the paper says month fixed effects cannot kill — and the paper has measured its magnitude.

**Why it is more than a sign issue.** The specification-induced movement in $\hat\tau$ is $0.0407$ in Fisher-$z$, roughly $0.035$ in correlation units. The paper's only substantive positive claim is that it excludes correlation increases above $0.086$. **The confound moves the estimate by about forty percent of the exclusion bound the paper uses to make that claim.** An identified-set statement that is sensitive at that magnitude to a measured, sign-flipping confound is not yet an exclusion statement; it is a point estimate plus noise plus an unresolved regime-loading adjustment.

**The bad-control problem the paper walks into.** §6.2 of the specification correctly forbids conditioning on mediators. But if the ETF changed *who* holds Bitcoin toward investors whose marginal utility tracks equity wealth, then a heightened differential loading on the equity-volatility regime is the mechanism's own signature — i.e. $\texttt{vix\_x\_btc}$ is partly an *outcome* of treatment. The `ctrl_vix_move` specification imposes a single, time-invariant $\texttt{vix\_x\_btc}$ across pre and post, which is innocuous only if the loading did not change. The paper's own bad-control rule therefore condemns its most substantively important robustness row, and the paper does not notice.

**The fix, and it is cheap.** Estimate

$$y_{im} = \tau D_{im} + \phi_1(\mathrm{VIX}_m \times \mathrm{BTC}_i) + \phi_2(\mathrm{VIX}_m \times \mathrm{BTC}_i \times \mathrm{Post}_m) + \alpha_i + \delta_m + \varepsilon_{im},$$

with the analogous MOVE terms. $\phi_1$ is the *pre-period* differential loading, which is a confounder and should be adjusted for; $\phi_2$ is the *change* in the loading, which is a treatment effect and should be left in $\tau$ or reported as a second outcome. This separates the confound from the mechanism and it runs on the delivered panel today. Report $\hat\tau$ from this specification alongside the current two, with its randomization $p$-value. I would expect this to become the headline specification, or at minimum to be the row the abstract's interval is computed from.

**Why this also implicates the sample-window choice.** The pre-period was chosen to start in 2021m1 to avoid the March 2020 correlation spike. It therefore contains the 2022 joint drawdown, a sustained high-VIX episode in which — per $\texttt{vix\_x\_btc}$ — Bitcoin's differential equity co-movement was mechanically elevated. The paper notes in passing that the correlation series "reach[es] levels in 2022 that it does not exceed after the listing" and does not connect that observation to the VIX interaction. They are the same fact. The window choice and the macro-loading confound are one issue, and the paper should present them as one.

---

## 5. The randomization defence of parallel trends does not establish parallel trends

The paper's pre-trend section is its best piece of methodological writing and its most consequential interpretive error.

The demonstration is correct: the conventional joint $F$ rejects for every coin, treated or not, because with one treated unit the cluster-robust covariance of a vector of unit-specific lead coefficients is driven by a single cluster. Bitcoin's $F = 9.185$ against a placebo median of $17.36$ gives $p^{RI} = 0.80$. The conclusion "the test is detecting its own invalidity" is right.

But the paper then slides from *the test is uninformative* to *there is no pre-trend*, and the draft's language ("Read against the reference bin, the estimated path shows no level shift... The series wanders") invites the reader to make that slide. Two things are true simultaneously:

- Bitcoin's pre-trend is not unusual relative to the control coins. ✓ (What the RI test shows.)
- Every coin in this panel, including Bitcoin, appears to have a differential pre-trend relative to the others, and the resulting bias in $\hat\tau$ is not removed by the observation that Bitcoin is typical.

**The magnitude, using the paper's own number.** The linear pre-trend is $-0.00144$ per month. The pre-period runs 2021m1–2023m7 (centroid ≈ 2022m4); the post-period runs 2024m2–2025m12 (centroid ≈ 2025m1). The gap between centroids is about 33 months. A DiD compares period *means*, so the relevant extrapolation is across the centroid gap:

$$-0.00144 \times 33 \approx -0.0475 \quad\text{in Fisher-}z.$$

Anchoring instead at the last clean pre-month (2023m7) and the post centroid gives $-0.00144 \times 18 \approx -0.0259$. **Either anchor produces an extrapolated pre-trend contribution larger in magnitude than the entire headline estimate of $-0.0212$.** Under a linear-extrapolation counterfactual, the trend-adjusted treatment effect is small and *positive*.

This supports the null and strengthens the paper's "robustly null, not robustly negative" framing with an argument independent of the VIX specification. It should be reported, not because it changes the verdict but because the paper currently derives "robustly null, not robustly negative" from a single robustness row, and this is a second, more standard derivation of the same conclusion.

**Where it does bite.** The paper's exclusion claim is computed under *exact* parallel trends. Adding pre-trend uncertainty (SE $0.00132$/month $\times$ 33 months $\approx 0.044$ in $z$) in quadrature to the randomization half-width of roughly $0.121$ widens the upper bound from about $+0.100$ to about $+0.108$ in $z$, i.e. from roughly $0.082$ to roughly $0.088$ in correlation units (exact conversion; see §6.3). The claim "rules out the upper half of the $0.05$–$0.15$ range" survives, but with visibly less margin than the draft implies, and it has not been tested against the *relative-magnitudes* bounds, which are the standard and which would widen it further.

**Required.** The specification document declines Rambachan–Roth on the grounds that the design "cannot credibly supply" a variance estimate. That is too quick. You already construct a placebo distribution of the full event-study coefficient vector by casting each control coin as treated — that is a placebo covariance matrix, and it is the natural input. It will be rank-deficient with nine donors against ten bins, so either coarsen to four or five bins, or use the relative-magnitudes ($\bar{M}$) formulation with a diagonal approximation and say so. At minimum, report **the breakdown value $\bar{M}$ for the exclusion claim specifically** — how large a post-period deviation from extrapolated pre-trends the design tolerates before the identified set covers $+0.10$ in correlation units. That single number is what the paper's contribution actually rests on, and it is currently absent.

**Secondary point on the event study.** The reference bin $-2$ is the lowest point in the estimated series and sits roughly $0.17$ below bin $-3$. Normalising to a volatile single bin makes every other coefficient positive and does a great deal of visual work. Report the event study normalised to the *pre-period mean* rather than to a single bin, and show sensitivity to the reference choice. The $-3 \to -2$ drop of $0.169$ in six months is also, on its own, the strongest argument against linear extrapolation and for the relative-magnitudes version of the sensitivity analysis.

---

## 6. Inference: what is exemplary, and what is undocumented

### 6.1 The randomization grid

Three issues with the grid as constructed.

**(a) Heterogeneous placebo variances.** The 190 time placebos are drawn from a shorter pre-period sample with candidate dates in 2021m7–2023m1, so individual placebo assignments have very different pre/post window lengths and therefore very different sampling variances. The resulting reference distribution is a *mixture* and the $p$-value is not exactly valid under any single sharp null. The paper notes this makes $p$ conservative; that is the right sign but not the right characterisation. The standard fix is **studentisation** — divide each placebo estimate by its own placebo standard error before ranking (Canay–Romano–Shaikh) — or restrict the grid to assignments matched on pre- and post-window length. Report the studentised $p$-value alongside the raw one. This matters because the same mixture inflates the placebo SD of $0.0619$ that the MDE is computed from, and the MDE is what the paper's null claim is adjudicated against.

**(b) Effective number of independent draws.** The 199 assignments are 19 candidate months $\times$ 10 coins plus 9 space placebos. Adjacent candidate months share most of their data and the ten coins within a candidate month are cross-sectionally dependent. The effective number of independent placebo draws is far below 199, so quoting $p^{RI} = 0.665$ to three digits asserts a precision the design does not have. Report the space-only $p$ (floor $0.10$) as the honest granularity benchmark, which you already do, and state the combined $p$ with an explicit caveat on granularity.

**(c) Exchangeability of donors.** RI is valid under exchangeability of the assignment, and Bitcoin is by construction not exchangeable with LTC or XLM in size, liquidity, or institutional standing. You have the evidence to defend this and do not present it: the reported SD of the Fisher-$z$ outcome is $0.2982$ for Bitcoin and $0.2952$ for the control group — essentially identical, and $n_{days,m}$ (and hence the first-stage sampling variance) is common across coins by construction. **Report the per-donor dispersion of the placebo estimates.** If it is flat across donors, that is a direct and persuasive defence of the RI procedure; if it varies with coin size, studentisation is mandatory rather than optional.

### 6.2 Construction of the randomization interval is undocumented and the distinction matters

The reported RI 95% interval is $[-0.1426, +0.1002]$ against placebo percentiles of $[-0.1384, +0.1025]$ and $\hat\tau = -0.0212$. The reported interval is neither the raw placebo percentiles nor those percentiles shifted by $\hat\tau$ ($[-0.1596, +0.0813]$), so I cannot tell whether it comes from test inversion, from a slightly different grid, or from something else.

This is not pedantry. The raw placebo percentiles are a *prediction interval for the estimate under the sharp null*; they become a confidence interval for $\tau$ only under location-invariance of the placebo distribution. The paper then reads the upper bound as an exclusion bound for $\tau$ ("excludes an increase above about $0.086$"), which requires the confidence-interval reading. **State the construction explicitly, and if it is test inversion, say over what grid of $\tau_0$.** If it is the raw percentile reading, the exclusion statement needs to be re-derived from the shifted interval, which would give an upper bound of $+0.0813$ in $z$ rather than $+0.1002$ — a 19% change in the paper's headline positive claim.

### 6.3 The units conversion is linearised where it should be exact

The conversion from Fisher-$z$ to correlation units uses the delta-method factor $1-\bar\rho_{pre}^2 = 0.8539$ at $\bar\rho_{pre} = 0.3822$. The exact conversion is $\tanh(z_{pre} + \tau) - \tanh(z_{pre})$ with $z_{pre} = \operatorname{atanh}(0.3822) = 0.4025$. My calculations:

| Quantity | Paper (linearised) | Exact |
|---|---:|---:|
| RI CI upper, correlation units | $+0.086$ | $+0.082$ |
| RI CI lower, correlation units | $-0.122$ | $-0.128$ |
| MDE (RI), correlation units | $0.148$ | $0.137$ |
| MDE (Conley–Taber), correlation units | $0.128$ | $0.120$ |

The errors are small but they are all in numbers the abstract quotes to three digits, and two of them are the numbers adjudicated against the pre-registered bars. The exact MDE of $0.137$ is closer to the $0.10$ bar than the reported $0.148$, and the exact upper exclusion bound of $0.082$ is further below $0.10$ than the reported $0.086$ — both movements favour the paper. Use the exact conversion, or state that the linearisation is used and quote one fewer digit. The conclusions are unchanged: $0.137$ and $0.120$ still fall between the bars of $0.10$ and $0.20$, so **the pre-registered verdict is robust to both the conversion method and the choice between the RI and Conley–Taber reference distributions.** Say that explicitly; it is a strength you are not claiming.

### 6.4 Conley–Taber versus randomization

The CT interval is $[-0.1065, +0.0386]$, width $0.145$; the RI interval is width $0.243$ — a 68% difference between two procedures the paper describes as equally valid. The discrepancy is consistent with the time-placebo mixture (§6.1a) inflating the RI reference distribution. The paper reports both and selects the wider for the MDE headline, which is the conservative choice and which pushes the verdict past the $0.10$ bar. A referee will ask which to believe. Reconcile them — I expect studentisation or window-matching will close most of the gap — and state that the pre-registered verdict holds either way.

---

## 7. Falsification layer

### 7.1 The gold placebo: an unreconciled internal inconsistency

This is the one place where I think the paper may have a factual problem rather than a presentational one.

The robustness table reports `placebo_gold` $= -0.0400$ with a clustered $p$ of $0.043$ and $p^{RI} = 0.50$, and the paper concludes that macro-neutrality survives. But the data summary's raw contrast (§7.3) reports gold's mean monthly correlation with SPY rising from $0.1536$ to $0.2116$, a change of $+0.0581$, against the control coins' $+0.0105$. On the Fisher-$z$ scale that is a raw differential of roughly $+0.048$ — **the opposite sign, and of large magnitude, relative to the estimated placebo coefficient of $-0.0400$.**

The gap is roughly $0.088$ in Fisher-$z$ units. Some of it is attributable to the different post-window endpoints (the raw contrast runs to 2026m7, the estimation window to 2025m12), and the `sample_extended_2026` row shows seven extra months moving Bitcoin's estimate by $+0.012$ — so window differences plausibly explain part but not obviously all of it. The paper's own data document flagged sign reversals between raw contrasts and regression estimates as a build-level red flag requiring explanation rather than assertion. **This one is unexplained and it sits on the pre-registered falsification test.**

Two things are needed. First, reconcile the numbers: report the gold raw contrast on the *estimation* window and show it against the regression coefficient. Second, and independently of the reconciliation, **the paper must confront the descriptive fact in its own appendix — that gold's equity correlation rose six times more than Bitcoin's over the same window.** The pre-registration was unconditional: a gold break falsifies the design's macro-neutrality. I do not think the honest reading is that the design is falsified — a large *differential* gold move with a flat crypto complex arguably shows the crypto-only control group is doing its job, since the month fixed effects are crypto-specific and gold's regime is not shared — but that argument has to be made in the paper rather than left for a referee to construct, and it has to be made in a way that does not look like retrofitting a pre-registered failure into a pass.

### 7.2 The BITO placebo

The paper's handling is correct and admirably unflattering: the futures-ETF placebo returns $+0.0412$ with a clustered $p$ of $0.034$, twice the magnitude of the real estimate and of opposite sign, and the paper declines to draw the channel inference it had pre-committed to. Two additions. First, the BITO row runs on a truncated sample ($n = 310$) with fewer post-months and hence a larger sampling variance, so comparing its magnitude directly to the headline is not apples-to-apples; report its own placebo SD. Second, taken together with the placebo SD of $0.0619$, the BITO row supports rather than undercuts the paper's power conclusion: the design's resolution is roughly $\pm 0.05$ in correlation units, which is the bottom edge of the index-inclusion range. That is the constructive reading and it should replace the slightly defensive framing currently in the draft.

### 7.3 Break dating: the abstract claims more than the evidence supports

The abstract states that "an endogenous break-dating procedure ... locates no break at the approval." The specification document declines to report break-date confidence intervals ("the Bai–Perron interval requires a HAC break-fraction asymptotic that is not implemented in this runtime"). The paper's own identification document was explicit on this point: *"Report the 90% confidence interval for the break date, not just the point estimate. The relevant test is whether 2024-01-11 lies inside it. ... a paper that reports only 'the break is estimated at 2024-02' has reported nothing."*

A point break date at 2024-05-02 with no interval cannot establish that January 2024 is excluded. Break-date point estimates are notoriously imprecise, and the underlying series is a 30-day rolling window, which mechanically lags the true break by up to a month — so a genuine break in early April would plausibly print as early May. The paper's attribution of the May break to the April halving is admissible but it is not the only admissible reading: ETF asset accumulation peaked in February–March 2024, and a phase-in effect would also date to late April on a 30-day window.

**Required.** Either (i) implement a bootstrap confidence interval for the break date — a block bootstrap over the differential series is entirely feasible and is a resource constraint, not a methodological impossibility — or (ii) remove the claim from the abstract and restate it as "the sequential procedure selects no break date within the window we pre-specified," with the pre-specified window stated. As written, this is a pre-commitment that was made, found inconvenient to satisfy, and then relied on anyway.

### 7.4 Pre-commitment compliance

Three items to audit and disclose:

- The identification document designated the **pre-election sub-window** ($-0.0439$, $p^{RI}=0.60$) as "the ETF-attributable figure," and committed that "if the two differ materially the text leads with the smaller, more conservative attribution." The abstract and headline quote $-0.0212$. The two differ by a factor of two. I do not think this is favourable selection — the pre-election estimate is *more* negative and would, if anything, strengthen the "no increase" claim — but the commitment should either be honoured or the deviation stated in the text.
- The **conjunctive decision rule** (positive DiD *and* US-session concentration) cannot be evaluated because the session DDD is not estimable. The paper should state plainly that its pre-registered rule for adjudicating H1 was un-runnable, so neither hypothesis was adjudicated as pre-specified, and that the MDE-bar rule is the only rule that could be applied.
- The **three-regime specification** (pre / anticipation / post, with the anticipation coefficient interpretable) was pre-specified alongside the no-donut variant and is not reported. This matters substantively: the no-donut estimate ($-0.0092$) is *closer to zero* than the donut estimate, meaning the anticipation months carried a higher Bitcoin differential than the rest of the post-period. That is consistent with a positive-then-decaying anticipation response, and the three-regime specification is the thing that would tell you. The paper instead reads "the donut is doing very little" as "there was nothing to anticipate," which is one of at least two readings.

---

## 8. Framing versus identification: the cash-flow argument does no work here

The paper's most distinctive rhetorical asset is the claim that Bitcoin's lack of cash flows shuts off the fundamentals channel that confounds the index-inclusion literature. The literature review already forced a useful narrowing (cash-flow *news* specifically; the discount-rate channel conceded; Froot–Dabora's twin shares acknowledged as an existing near-fundamentals-invariant design), and the draft executes that narrowing well.

But there is a structural problem the narrowing does not address. **In a cross-coin difference-in-differences, the absence of cash flows is a property shared by the treated unit and every control unit, and is therefore differenced out.** The identification in this paper is done entirely by the never-listed control group and the calendar-month fixed effects. Nothing in the estimating equation, the assumption, or the falsification layer is made more credible by Bitcoin having no earnings.

The cash-flow argument *would* be identifying in a single-asset before/after design — which the paper explicitly demotes to `descriptive_raw_gap` and labels as such. It is also load-bearing for the *interpretation* of a positive finding, which the paper does not have. As executed, the argument's only live function is the pre-committed reading of the null (§"What a null would mean"), where it does genuine work: a null in an asset with no earnings localises habitat effects in the shared-cash-flow-news channel that Glosten, Nallareddy and Zou document. That is a real contribution and it should be where the framing lands.

**Recommendation.** Move the cash-flow argument out of the identification claim and into the interpretation claim. The introduction currently sells it as what makes the *design* credible; it should sell it as what makes the *null informative*. This is not a demotion — it is the only version of the argument that survives a referee who notices that DOGE has no cash flows either.

---

## 9. Pre-specified analyses that are feasible and missing

The paper's §15 is a model of transparency about what could not be estimated (session DDD, staggered cohorts, prior-halving placebo, false-news placebo), and every one of those explanations is convincing. The following five were pre-specified, are estimable on the delivered panel, and are neither reported nor explained.

| Check | Where specified | Why it matters here | Cost |
|---|---|---|---|
| **Synthetic control for Bitcoin's co-movement path** | Identification strategy, ranked **1b**, "reported beside the primary" | Addresses **exchangeability** — the single most contestable premise of the design. Weighting donors to match Bitcoin's pre-period path would absorb much of the differential VIX loading in §4, precisely because that loading is expressed in the pre-period path. | Low |
| **Leave-one-coin-out (F7)** | Identification strategy §9; data dictionary calls a leave-BNB-out row "mandatory" | With nine donors and a null, the cheapest possible test of whether one control drives the result. BNB carries exchange-specific regulatory news inside the pre-period; DOGE carries a large 2021 idiosyncratic episode. | Trivial |
| **Clean-control subsample** | Identification strategy §5.1; data dictionary flags AVAX, DOT, XLM | The direct empirical response to the SUTVA concern the paper concedes. | Trivial |
| **Three-regime (pre / anticipation / post)** | Identification strategy §7 | Resolves the no-donut reading (§7.4 above). | Trivial |
| **Romano–Wolf stepdown across the secondary outcome family** | Identification strategy §8 | The paper highlights $\ln(\sigma_i/\sigma_{mkt})$ with a clustered $p$ of $0.004$ out of a family of roughly 22 rows and 3 outcomes. | Low |

The synthetic-control omission needs a specific correction. The specification document justifies it as "the placebo-in-space grid supplies the same inference channel directly." That conflates two different objects: placebo-in-space is an *inference* device; synthetic control is a *counterfactual-construction* device that relaxes the equal-weighting of donors that TWFE imposes. They are not substitutes, and the identification document ranked SC at 1b precisely because it addresses exchangeability. With ten coins, 31 pre-months, and a balanced panel, it is straightforward. **Reinstate it.**

A sixth item, less serious: the specification contemplates $1/\mathrm{se}^2$ GLS weights as a robustness row and does not report one. Given that $n_{days,m}$ ranges only 19–23, the weights vary by about 25% in variance and this is genuinely second-order; a sentence suffices.

---

## 10. Power: the paper's self-assessment survives independent arithmetic

I checked the power claim independently, because it carries the paper's headline verdict, and I want to record that it holds up.

**The noise floor is measurement error, and it is nearly the whole story.** The Fisher-$z$ sampling variance is $1/(n_{im}-3)$; with a mean of $20.87$ sessions per cell this is $1/17.87 = 0.0560$, i.e. $\mathrm{sd} = 0.237$ per cell. The reported total SD of the outcome in the estimation sample is $0.2957$, i.e. variance $0.0874$. **First-stage sampling error therefore accounts for roughly 64% of the outcome's variance**, leaving a true cross-month dispersion of only about $0.177$ in Fisher-$z$. This single fact explains the within-$R^2$ of $0.00057$ and should be reported — it is a far better justification for the design's imprecision than anything currently in §"Power."

Propagating that measurement error alone through the 2×2 DiD, with 31 treated pre-months, 23 treated post-months, and nine averaged controls:

$$\mathrm{SE}(\hat\tau)\big|_{\text{first stage only}} \approx \sqrt{0.0560\left(\tfrac{1}{23}+\tfrac{1}{31}\right)\left(1+\tfrac{1}{9}\right)} \approx 0.069.$$

The empirical randomization SD is $0.0619$. These agree to within about 10%. **The design's entire noise floor is the sampling error in estimating a monthly correlation from twenty-one daily observations; there is essentially no room left for genuine economic dispersion in the differential.** Three consequences worth stating in the paper:

1. The clustered SE of $0.0170$ is roughly a quarter of the analytically predicted noise floor. This is independent arithmetic confirming the paper's central inferential claim, and it is more persuasive than the comparison of interval widths currently used.
2. The randomization SD is not obviously inflated by the time-placebo mixture after all — it is slightly *below* the analytic prediction. That is reassuring for §6.1(a), though studentisation should still be reported.
3. **The only routes to better power are more daily observations per block or more treated units.** Aggregating to quarterly blocks does *not* help: the noise variance falls roughly threefold but the number of treated post-periods falls threefold too, and the true-dispersion component is persistent, so the net effect on $\mathrm{Var}(\hat\tau)$ is adverse. I mention this because it is the obvious first thing a reader will propose. The paper's own conclusion — intraday data or a multi-cohort design — is the right one.

**One caution on the proposed multi-cohort fix.** The conclusion asserts that "a staggered multi-cohort design across four treated assets would cut the randomization-based minimum detectable effect materially." That is true for the *average* effect across cohorts, not for Bitcoin's. The Bitcoin ETF complex is roughly two orders of magnitude larger than the SOL or XRP complexes, and the paper's own framework makes the effect a function of participation $\lambda(\kappa)$, hence of dose. Pooling heterogeneous doses lowers the MDE for a quantity that may be much closer to zero than Bitcoin's. State the homogeneity assumption the proposed extension requires.

---

## 11. Strengths worth preserving in revision

I want these on the record, because the revision list above is long and the paper's virtues are real.

- **Fixing the inference procedure before estimation, and then demonstrating that it changed three conclusions.** The pre-trend $F$, the gold placebo, and the iid sup-Wald are three separate demonstrations that the conventional column manufactures false positives in this configuration. This is the paper's most durable contribution and it should stay in the introduction.
- **Excluding eventually-treated coins from the control group**, which forecloses the forbidden-comparison/negative-weights problem by construction rather than by estimator choice. The justification for TWFE over Callaway–Sant'Anna here is correct.
- **The $140.41 \to 6.39$ sup-Wald demonstration.** A twenty-two-fold reduction from correcting a 29-of-30-day overlap is a result other researchers in this literature need to see.
- **The DCC and per-asset returns models reported with their control-group distributions.** "Every crypto asset's beta fell; every crypto pair's DCC target rose" is the paper's argument in miniature and it is beautifully executed.
- **Reporting `subwindow_pre_halving` with $n_{post}=2$ printed beside it** rather than quietly dropping the largest coefficient in the paper.
- **The no-controls decision**, correctly reasoned from the mediator/bad-control logic rather than from convenience.
- **Reporting an MDE against a pre-registered bar, landing between the bars, and declining to upgrade.** Rare and correct.

---

## 12. Ranked recommendations

**Must fix before this is an identification paper:**

1. **Resolve the macro-volatility-loading confound.** Estimate the $\mathrm{VIX}\times\mathrm{BTC}\times\mathrm{Post}$ specification (§4), separating the pre-period loading (confounder, adjust) from the change in loading (mechanism, do not adjust). Report the resulting $\hat\tau$ and interval, and state which specification the abstract's exclusion bound comes from.
2. **Bound the pre-trend.** Implement Rambachan–Roth using the placebo covariance you already construct, or a defensible coarsened version, and report the breakdown value $\bar{M}$ for the exclusion claim specifically. At minimum, report the linear-extrapolation-adjusted estimate (§5).
3. **Document the randomization interval's construction** and re-derive the exclusion bound under the correct reading (§6.2). Use exact rather than linearised Fisher-$z$ conversions throughout (§6.3).
4. **Fix or withdraw the break-dating claim in the abstract.** Bootstrap break-date intervals, or restate the claim as what it is (§7.3).
5. **Reconcile the gold placebo** against the raw contrast in your own data appendix, and confront the descriptive fact that gold's equity correlation rose six times more than Bitcoin's over the same window (§7.1).

**Should fix:**

6. Reinstate the **synthetic control** (§9) — it is the direct answer to exchangeability and it interacts helpfully with recommendation 1.
7. Run **leave-one-coin-out**, the **clean-control subsample**, and the **three-regime anticipation specification** (§9). All are trivial and all are pre-specified.
8. Report **studentised randomization $p$-values** and **per-donor placebo dispersion** (§6.1).
9. Restate the SUTVA discussion with **both** bias directions and adjudicate with the control-coin level evidence you already have (§2c).
10. Move the **cash-flow framing** from the identification claim to the interpretation claim (§8).
11. Add the **noise-floor decomposition** (§10) to the power section — it is a much better account of the design's imprecision than the current one.
12. Address **functional-form dependence of parallel trends** (§3); the fact that the null holds on $z$, $\rho$ and $\beta$ is your defence and you should state it as one.
13. Report **Romano–Wolf** across the secondary outcome family, or explain the omission (§9).
14. Normalise the event study to the **pre-period mean** rather than a single volatile reference bin (§5).

**Presentation:**

15. "Six methodologically distinct estimators agree" overstates independence — all six use the same daily return series and the same single treated unit. Concordance among dependent estimators on one treated unit's data is weaker evidence than the phrasing implies.
16. The abstract's "survives ... a grid of placebo assets" is a stretch when two placebo rows return conventionally significant coefficients ($p = 0.034$, $p = 0.043$) that are explained away by the inference procedure. The explanation is correct; the abstract's summary of it is not.
17. The clock argument in §"Variable construction" — that the UTC clock is not the one a US-hours relocation would mechanically favour — is looser than stated. The UTC crypto day contains the full US cash session of day $t$, so a relocation into US hours raises measured correlation on this clock too, just by less than on the ET clock. Since the finding is null, this cuts in your favour: a mechanical upward force was present and did not produce an increase. Say that instead.

---

## 13. What would change my assessment

Upward, to a clear accept-with-minor-revisions on identification grounds: recommendations 1–5 implemented, with the exclusion bound surviving both the $\mathrm{VIX}\times\mathrm{Post}$ adjustment and an honest-DiD relative-magnitudes bound; the synthetic control agreeing with TWFE; break-date intervals containing or excluding January 2024 on a stated rule.

Downward: if the $\mathrm{VIX}\times\mathrm{BTC}\times\mathrm{Post}$ specification moves $\hat\tau$ by more than about one randomization SD again, or if the synthetic control produces a materially different gap path, the design cannot separate the ETF from the macro-regime loading at the resolution the paper needs, and the correct paper is a shorter one whose claim is "this design cannot resolve effects of the size the theory predicts, and here is what it would take" — which the paper half-writes already and which would still be publishable in a good field journal.

The null itself I expect to survive all of this. My concern is not that the answer is wrong; it is that the apparatus currently supporting the paper's one positive claim — the exclusion bound — is not yet strong enough to carry it.

OVERALL SCORE: 6/10
RECOMMENDATION: Major Revision
