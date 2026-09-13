# Referee Report — Mechanism Review

**Paper:** *No Cash Flows, New Owners: Spot Bitcoin ETFs and the Origins of Co-movement*
**Paper ID:** e432cf3f-9008-4202-8ee6-ff09a93948ec
**Reviewer role:** Mechanism reviewer (referee simulation; market-microstructure emphasis)
**Reviewed:** full draft, identification strategy, econometric specification, literature review, data dictionary, data summary, paper plan

---

## Summary of the submission

The paper uses the January 10–11, 2024 approval and listing of eleven US spot Bitcoin ETPs as an access shock to Bitcoin's investor base and asks whether Bitcoin's co-movement with US equities changed as a result. The design is a two-way fixed-effects difference-in-differences on a coin-month panel of Fisher-*z* equity correlations, Bitcoin treated from 2024m2, nine never-listed coins as controls, with a six-month donut and randomization inference as the governing procedure because there is exactly one treated unit. The estimate is $-0.0212$ in Fisher-*z* units ($-0.0181$ in correlation units), RI $p = 0.665$, RI 95% interval $[-0.122, +0.086]$ in correlation units, with a minimum detectable effect of $0.148$ that falls between the two pre-committed bars. The paper reports six estimators, an endogenous break-dating procedure that dates the only clear 2024 differential break to two weeks after the April halving, and a twenty-two-row robustness and placebo grid.

The execution is candid and in several respects exemplary. My central objection is that this is a reduced-form bounded null with **no mechanism evidence of any kind**, and that several mechanism margins are estimable on the delivered daily data and were not attempted.

---

## DIMENSION SCORES

- Contribution: 5/10
- Identification: 6/10
- Empirics: 6/10
- Writing: 8/10
- Literature: 3/10

**Weighted computation:** $0.25(5) + 0.25(6) + 0.20(6) + 0.15(8) + 0.15(3) = 1.25 + 1.50 + 1.20 + 1.20 + 0.45 = 5.60$

---

## MAJOR CONCERNS

### 1. No mechanism test survives, and the conclusion's mechanism claim is therefore unsupported by anything in the paper

This is the finding that governs my recommendation, and I want to state it precisely rather than as a general complaint about scope.

The conceptual framework in §4 generates three predictions. **P1** is a magnitude prediction on $\Delta\beta$. **P2** is the flow decomposition: the loading should respond to allocation flow and not to market-neutral basis flow. **P3** is the session prediction: allocator trading is confined to exchange hours, so the induced covariance concentrates in the US cash session. The identification strategy ranks the session triple-difference as the paper's highest-internal-validity design and the only one that absorbs the halving and the election outright, and it ranks the flow decomposition as the paper's novel measurement contribution.

Neither P2 nor P3 is tested. The paper is candid about why (no intraday crypto history before late 2024, no fund-level creations and redemptions), and I do not penalize a design for data that cannot be obtained. But the consequence for the *interpretation* has not been absorbed. §8 concludes that "habitat co-movement operates through a shared interpretation of shared cash-flow news — the channel through which ETFs are known to raise systematic price informativeness in equities — and that an asset with no earnings has nothing for that channel to work on." Nothing in the paper bears on that claim. A reduced-form null on $\Delta\rho$ is consistent with at least four distinct structures:

- (a) the clientele did not change (no ETF-driven shift in $\omega(\lambda)$);
- (b) the clientele changed but their SDF is not equity-linked at the margin (the paper's own H2, orthogonal-demand sub-channel);
- (c) the clientele changed, $\beta^a$ transmission occurred, and it was offset by displacement of the correlated retail noise trader (the paper's own H2b, which predicts a *decline*);
- (d) the assets that arrived were overwhelmingly market-neutral cash-and-carry positions, so $\omega(\lambda)$ barely moved despite enormous AUM (the paper's own H3).

The paper enumerates all four in §3 and then, in §8, picks a fifth reading — the cash-flow-news localization — that is not one of its own hypotheses and that no reported estimate discriminates. The honest closing position is that the design bounds the magnitude and says *nothing* about the channel, and the conclusion should say that in those words. Alternatively, supply a mechanism margin. Several are available on the data already on disk:

**(1a) The weekend / off-day margin (F14) is pre-registered, cheap, and not run.** The build wrote `data/crypto_offday_returns.csv` with 8,411 crypto coin-days on sessions the NYSE was closed. The pre-analysis states F14's logic clearly: if the ETF's marginal holder now sets the price, Bitcoin's weekend share of volume and of realized variance should fall post-2024, and weekend returns should become less informative for Monday pricing. The data dictionary specifies `w_weekend_vol_share` and `w_weekend_volume_share` as derived variables. Every control coin also trades weekends and did not receive an ETF, so this is a DiD with the same ten units, the same month fixed effects, and the same nine-donor randomization distribution. It is the one piece of the session logic that survives without hourly data, the data summary says so explicitly, and the paper uses the off-day file only for an alignment robustness row. **This is my single highest-value ask.** Run it, and report the weekend variance-share DiD and the weekend-return-to-Monday-return predictability DiD beside the headline.

**(1b) The lead–lag / Dimson margin is specified, apparently built, and never reported.** `rho_3d_m` and `beta_dimson_m` appear in the data dictionary (dv_12, dv_13) as constructed on 63-session blocks, and F9 pre-commits to the Dimson/Scholes–Williams summed-lag construction as the resynchronization check. Neither variable appears in any table. This is a reporting gap, not a data gap. It matters twice over: F9 was pre-committed, and the summed lead–contemporaneous–lag beta is the only daily-frequency shadow of the session hypothesis available here. If Bitcoin's contemporaneous loading fell while its summed Dimson loading did not, that is a re-timing result and a mechanism finding. If both are flat, the null is stronger than currently reported. Either way the reader is entitled to the number.

**(1c) A liquidity margin is free and is the first-order microstructure prediction of an access shock, and it is absent.** The build has daily OHLCV for Bitcoin and all nine controls over the full window. Two standard estimators require nothing more. Amihud (2002) illiquidity, $\text{ILLIQ}_{im} = n_{im}^{-1}\sum |r_{id}|/\text{DVOL}_{id}$, needs only daily returns and dollar volume. Corwin–Schultz (2012) recovers an effective spread from daily high–low ranges. Both slot into the identical coin-month panel, the identical fixed effects, and the identical randomization grid. If a US-listed spot vehicle with an authorized-participant creation and redemption mechanism operating in spot Bitcoin did anything to the underlying, the sharpest prediction is a change in price impact and effective spread — not a change in a second moment against a different asset class. The paper's own institutional section argues exactly this when it describes the GBTC discount collapsing to parity "at the moment redemptions became possible." It then never measures the liquidity margin that the restored arbitrage mechanism most directly implies. A null on $\Delta\rho$ alongside a *detected* decline in ILLIQ or in the Corwin–Schultz spread would transform the paper: it would establish that the wrapper changed the asset's microstructure without changing its factor structure, which is a genuine and reportable dissociation and precisely the "localization" claim §8 wants to make but cannot currently support. I regard this as the most valuable addition available and it requires no new data.

**(1d) A Kyle-$\lambda$ price-impact margin is also within reach at daily frequency.** Regressing daily $|\Delta P|$ or $\Delta P$ on signed or unsigned dollar volume per coin-month gives a crude but usable price-impact coefficient with the same panel structure. Coarser than the tick-level object, but the DiD differences out the coarseness common across coins.

### 2. The paper's own model is about $\beta$; $\beta$ fell; the paper reports "no change"

Equation (1) states $\beta = \omega(\lambda)\beta^a + (1-\omega(\lambda))\beta^c$ and concludes $\partial\beta/\partial\kappa < 0$. The estimand implied by the framework is the equity *loading*. The paper then makes $\rho$ the headline outcome on grounds that are entirely statistical — Fisher-*z* has a known, coin-invariant sampling variance and non-overlapping blocks, whereas the monthly $\hat\beta$'s sampling variance scales with $\sigma_i/\sigma_{mkt}$ and would make the DiD residual variance a function of treatment status. That argument is correct and I accept it as an *estimation* choice. It is not an economic argument, and the paper never supplies one.

The problem is that the two objects diverge here, and they diverge in a direction the paper does not reconcile. Table `outcome_beta` reports $\hat\tau^\beta = -0.1890$; `outcome_ln_sigma_ratio` reports $-0.1128$ with the largest clustered $t$-statistic in the paper. So on the framework's own object the estimate moved, negatively, and the paper's summary sentence is "no detectable change." §7.6 resolves this arithmetically — $\beta = \rho\cdot(\sigma_i/\sigma_{mkt})$ and the volatility leg is doing the work — but arithmetic is not the issue. The issue is that equation (1) predicts $\beta$, and the paper needs either to (i) rewrite the framework so that participation weights move $\rho$ rather than $\beta$, which requires an assumption about how $\omega(\lambda)$ interacts with idiosyncratic variance and is not innocuous, or (ii) own that its own model's object declined and say what that means.

Reading (ii) is more interesting than the paper allows. H2's noise-reduction sub-channel — stated in §4 and then abandoned — predicts precisely a decline: a deep, institutionally arbitraged product displaces the marginal retail noise trader who was reaching both speculative equities and crypto through the same brokerage applications and the same sentiment cycle, which reduces the sentiment-driven component of co-movement *and* reduces idiosyncratic volatility. The delivered results are $\Delta\rho \approx 0$, $\Delta\ln(\sigma_i/\sigma_{mkt}) < 0$, $\Delta\beta < 0$ — a pattern H2b predicts and no other hypothesis in the paper predicts. The paper has a result consistent with one of its own pre-registered hypotheses and declines to engage it, which is over-correction in the opposite direction from the usual failure. Engage it, note that the RI $p$ of 0.20 will not support a claim, and let the reader see that the paper's framework has something to say about its own findings.

### 3. The volatility-ratio result has an obvious mechanical explanation that is not ruled out

The volatility-ratio decline is the paper's one positive finding and it is currently under-defended in two specific ways.

First, **size**. Realized volatility falls with market capitalization essentially universally across assets. Bitcoin's market capitalization grew substantially relative to the nine control coins over 2021–2026. A differential volatility decline for the largest coin in a panel of ten is therefore the null prediction of a size–volatility relation, not evidence of a broader investor base. The test is a paragraph: plot the pre-to-post change in $\ln(\sigma_i/\sigma_{mkt})$ against the change in $\ln$ market cap across the ten coins and report whether Bitcoin sits on or off the fitted line. If Bitcoin is on the line, the clientele reading of this result is gone and the paper should say so. (The data dictionary notes historical market caps are not served by any configured source; the change in the *price* index relative to the panel is a usable proxy and the paper already has it, since supply schedules are public and near-deterministic for these assets over the window.)

Second, **the RI $p$ is a rank, and the rank is uninformative without its identity**. With nine donors the attainable values are $\{0.1, 0.2, \ldots\}$; $p = 0.20$ means exactly one control coin produced a larger absolute estimate. Which one? If it is DOGE — the coin the data documentation flags as carrying a large idiosyncratic 2021 episode that inflates its pre-period idiosyncratic variance — then Bitcoin's rank is being set by a comparison the paper has already told us is contaminated, and the reader should know. Print the nine donor estimates.

### 4. The donut's justification contradicts the paper's own treatment concept, and it is not doing "very little"

The introduction makes a good argument: this is an access shock, not a news shock, and "second moments cannot be pre-traded the way a level can, which is the reason this paper measures factor loadings rather than announcement returns." I find that argument persuasive. But it undercuts the donut, which §5.1 justifies as excluding *anticipation*. If second moments cannot be pre-traded, there is nothing in the second moment to anticipate, and the donut discards six months of otherwise clean pre-period for a reason the paper's own framework denies.

The paper then asserts the donut "is doing very little — consistent with the absence of a treatment effect to anticipate." It is doing more than that: $-0.0092$ without the donut against $-0.0212$ with it. The donut more than doubles the point estimate. Both are far inside the randomization distribution, so neither is a finding, but "very little" is the wrong description of a specification choice that moves the headline coefficient by 130%.

There *is* a defensible access-based justification for the donut and the paper does not use it: the GBTC conversion and the start of the redemption transition are a genuine plumbing change spanning 2023m8–2024m1, and the treated unit's price series is mechanically entangled with a closed-end discount collapsing to parity. Argue from that, drop the anticipation argument or confine it to the news-event leg, and state plainly that the donut choice moves the coefficient by a factor of two within a distribution that is 0.06 wide.

### 5. SUTVA is claimed one-directionally, and the prescribed test was dropped

§5.3 states: "contamination of the control group biases the difference-in-differences toward zero. Our estimate is therefore a lower bound." The identification strategy document flags both directions and is explicit that the sign is ambiguous: "if spot-ETF access *diverted* US allocator demand away from altcoins, control-coin co-movement would fall and $\hat\tau$ would be biased **upward**. The plan should not claim only the convenient direction."

The delivered draft claims only the convenient direction. The prescribed empirical responses — a clean-control subsample restricted to coins least exposed to US-brokerage-adjacent ownership, and reporting whether control-coin co-movement rose or fell in absolute terms post-2024 — are both absent. The data dictionary already flags `in_clean_control_subsample` for AVAX, DOT and XLM. The data summary already reports that control-coin correlation rose by $+0.0105$ in absolute terms, which is the second of the two prescribed diagnostics and belongs in the paper. Run the three-coin clean-control row, report the control-group level movement, and either establish the lower-bound claim or withdraw it.

### 6. The BITO placebo is the paper's most damaging result for the mechanism and is processed too quickly

A non-event in the same panel — the October 2021 futures-ETF launch — returns $+0.0412$ with clustered $p = 0.034$: twice the magnitude of the spot-approval estimate and opposite in sign. The paper reads this as "a demonstration that estimates of this size are noise," draws no channel inference, and moves on.

That reading is simultaneously too generous to the design and too dismissive of the row. Too generous: if a placebo generates a larger apparent differential than the treatment, one live possibility is that the pre-period contains a genuine Bitcoin-specific regime (BITO launched at the October–November 2021 cycle peak, as the literature review notes) that the randomization distribution is not capturing because the placebo-in-time grid is drawn from 2021m7–2023m1 and therefore *includes* that regime in its own reference distribution. Report the BITO estimate with the cycle-peak months excluded, and report its RI 95% interval beside the treatment's so the reader can see whether they overlap. Too dismissive: the futures wrapper supplied US brokerage access without spot creation and redemption. A positive futures-launch estimate and a zero spot-launch estimate is, on its face, a listing-and-visibility channel with no spot-plumbing channel — which is a substantive claim about mechanism, is the one channel inference this paper is positioned to make, and is waved away in two sentences.

### 7. Promised multiplicity discipline is not implemented, and the sign-count sentence overstates

The econometric specification commits to Romano–Wolf stepdown adjusted $p$-values across the secondary outcome family (beta, volatility ratio, Dimson correlation, DCC correlation, factor loadings). No Romano–Wolf $p$-value appears anywhere in the draft or the reported results. With three outcomes, six estimators, four sub-windows and twenty-two robustness rows, the promise mattered.

Relatedly, §6 of the robustness discussion leans on "the point estimate is negative in nineteen of twenty rows." Those twenty rows share a common outcome, a common panel and overlapping samples; they are close to perfectly dependent, and the count carries almost no independent information about sign. Either state that explicitly or remove the sentence — as written it reads as corroboration and is not.

---

## MINOR CONCERNS

1. **The UTC-clock conservatism claim is asserted, not shown.** "The UTC clock is not the clock that such a relocation would mechanically favour" is plausible but not obvious: the mismatch is $+3$/$4$ hours on one side and $-20$/$21$ hours on the other, and the induced change in measured daily correlation from relocating covariance into 09:30–16:00 ET depends on where within the 24-hour cycle covariance previously sat. A short simulation — impose a known relocation, compute the induced change in UTC-clock daily $\hat\rho$ — settles it in a paragraph and is worth considerably more than the assertion.

2. **The Fisher-*z* homoskedasticity claim overstates.** $\text{Var}(y_{im}) \approx 1/(n_{im}-3)$ is common across coins *within* a month but varies across months ($n$ runs 19–23). The paper and the econometric specification both say "the same for every coin and every month." Month fixed effects do not absorb heteroskedasticity. The direction is benign and the point is small, but the text should be corrected.

3. **Conley–Taber and RI intervals are treated as agreeing when they differ by 40% in width.** $[-0.1065, 0.0386]$ versus $[-0.1426, 0.1002]$; MDEs of $0.128$ versus $0.148$. They agree in substance. The abstract quotes $0.148$, which is the conservative choice and the right one — say that it is the conservative choice rather than implying the two procedures coincide.

4. **Two different criteria are conflated in the power paragraph.** "The design excludes an increase above about $0.086$" is an interval statement; "with 80% power the design could only have detected $0.148$" is a power statement. Readers will merge them. One clarifying sentence.

5. **The randomization placebo density figure is promised and missing.** The inference section commits to plotting "the full placebo density with the true estimate marked." Given a design whose entire inferential content is the placebo distribution, this is the single most persuasive exhibit available, and the delivered figure set contains only descriptive rolling-correlation and ETF-turnover panels. Add it.

6. **`khatib2026from` was never read.** The positioning rests on a title and an outlet; the 403 is documented in the literature review. The title's "from contagion to *stabilization*" may not be a co-movement-*increase* claim at all, in which case the draft's framing — "a regime change in crypto–equity integration around the spot ETF has been documented; what has not been supplied is a comparison group" — misstates what is already in print, and possibly understates the contribution. This must be resolved before the positioning paragraph is final.

7. **The sub-window with two post-treatment months is reported honestly but is still over-displayed.** $-0.2613$ with $n_{post} = 2$ is the largest coefficient in the paper and will be quoted by someone. The paper prints the post-count beside it and says two observations do not establish an effect, which is the right handling. Consider moving it to an appendix table with the count in the row label.

8. **Cross-venue price validation is absent and the paper says so.** Single-source Yahoo crypto quotes with an undocumented aggregation methodology and silent revisions. Correctly flagged; nothing more can be done here. But `qa_11` (a ten-day spot check against an independent reference) is described in the data dictionary as a warning-level check and does not appear to have been run. Run it — it costs nothing and closes a referee line.

---

## LITERATURE (the weakest dimension, and the easiest to fix)

The literature review document is unusually good and the draft does not use most of it. Three gaps are referee-visible on a first read:

- **The financialization strand is entirely absent from the draft.** Tang–Xiong (2012), Basak–Pavlova (2013, 2016), Henderson–Pearson–Wang (2015), Cheng–Xiong (2014). This is the paper's closest structural analogue — a new financial product made an asset class accessible to a new clientele and equity co-movement rose — and the draft's §2 does not mention it. Cheng–Xiong is specifically the named antagonist: the argument that observed commodity co-movement increases reflect common macro shocks rather than index flows is *this paper's own finding*, arrived at independently, and the paper does not cite the prior statement of it. Henderson–Pearson–Wang is the template for the flow decomposition the paper proposes and cannot run. Omitting this strand is not a stylistic choice; it means the paper cannot claim to build on the literature its design descends from.

- **Merton (1987) is absent while the framework is a Merton (1987) application.** §4 introduces a per-period participation cost $\kappa$, a participation function $\lambda(\kappa)$, and an investor-recognition mechanism, and cites no source for any of it. This is the most damaging single omission.

- **Every econometric method is used by name and cited by none.** Fisher-*z*; Engle (2002) DCC; Bai–Perron (1998, 2003); Andrews (1993) sup-Wald; Conley–Taber (2011); MacKinnon–Webb on the one-treated-cluster wild bootstrap; Bertrand–Duflo–Mullainathan; Rambachan–Roth; Callaway–Sant'Anna, Sun–Abraham, Borusyak–Jaravel–Spiess in the extension discussion; Scholes–Williams and Dimson if the F9 check is restored. The draft names all of these in prose and cites none of them in the bibliography. A referee will notice on page one of Section 5.

The literature review attributes these gaps to an exhausted save budget and unavailable search, which is a pipeline constraint rather than a scholarly failure. It is nonetheless a property of the submitted manuscript, and the manuscript cannot be evaluated on the intentions of an upstream document.

One substantive positioning point the draft gets right and should keep: the narrowing of the zero-cash-flow claim. The literature review is correct that Froot–Dabora's twin shares hold cash flows *exactly* constant and that "no prior study can claim this" would be false. The draft's formulation — Bitcoin "does something the twin-share and reclassification designs achieve for a handful of securities, and it does it for an entire asset class around a single large and well-dated treatment" — is defensible and well put. Keep it.

---

## POSITIVE ASPECTS

1. **The inference treatment is genuinely exemplary and is the paper's most transportable contribution.** One treated unit, randomization inference fixed as primary *before* estimation, and then a concrete demonstration that three conventional tests would have delivered three false positives: the pre-trend $F = 9.185$ with asymptotic $p = 0.0024$ that sits *below the median placebo* ($F = 17.36$) when each control coin is cast as treated; the gold placebo at clustered $p = 0.043$ and RI $p = 0.50$, which under the paper's own pre-registration would have killed the design on a false positive; and the iid Andrews sup-Wald of $140.41$ collapsing to $6.39$ under a HAC correction at twice the rolling window. That last figure alone — a twenty-two-fold reduction from correcting a mechanical 29-of-30-day overlap — is worth publishing as a standalone warning to a literature that runs break tests on rolling-window series routinely.

2. **The control-group demonstration is clean, generalizable, and correct.** The DCC $\hat\phi$ is positive for all ten pairs, DOGE's exceeding Bitcoin's; every crypto asset's returns-level equity beta fell, so Bitcoin's $-0.4148$ becomes $-0.0798$ once the common decline is differenced out. "A study running any one of these specifications on Bitcoin alone would have reported a significant result, and it would have been reporting 2024" is the right sentence and it is well supported.

3. **The pre-committed power bar with a verdict that lands between the bars, honestly reported rather than upgraded after the fact.** This is rare and it should be protected in revision. The abstract's phrasing — excludes the upper half of the index-inclusion range, cannot rule out half that magnitude — is exactly the claim the data license.

4. **Honest reporting of results that do not flatter the hypothesis:** the sign flip under the macro interaction; the BITO placebo failing its pre-committed reading; the Bai–Perron break landing at the halving rather than the approval; the pre-halving sub-window resting on two months and printed with its count.

5. **Measurement discipline on the ETF series.** Turnover is labelled turnover and never flow, with the reasoning stated ("a day of heavy two-sided trading with no net creation produces a large value"). The GBTC discount is labelled a proxy with its anchoring and its fee drag disclosed. The eleven-versus-ten fund coverage is stated rather than implied. This is the standard the rest of the literature does not meet and it should be preserved verbatim.

6. **Magnitude discipline.** $\rho^2$ reported beside every correlation, the mean variance share of $0.184$ carried into the conclusion, and the explicit refusal to write "Bitcoin became a risk asset" off a correlation of $0.4$.

7. **Writing.** The introduction's structure — phenomenon, tension, design, result, then the three qualifications stated up front rather than deferred to a robustness section — is the right architecture and it is executed with unusual clarity. The prose is precise and the paper is easy to audit, which is itself a scholarly virtue.

---

## PATH TO REVISION

The paper is well built and honestly reported, and its problem is not error but incompleteness of exactly the kind a revision can fix. In priority order:

1. Run the weekend/off-day mechanism DiD (F14). The data are on disk and the test is pre-registered.
2. Add a liquidity margin — Amihud illiquidity and Corwin–Schultz spreads on the identical coin-month panel with the identical RI grid. Free data, first-order microstructure prediction, and the one result that could convert a bounded null into a dissociation finding.
3. Report `rho_3d_m` and `beta_dimson_m`. They are specified, F9 was pre-committed, and their absence is a reporting gap.
4. Reconcile $\beta$ and $\rho$ against equation (1), and engage H2b, which the delivered pattern of results actually fits.
5. Test the size explanation for the volatility-ratio decline and print the nine donor estimates.
6. Run the clean-control subsample; state the SUTVA bias direction as ambiguous.
7. Re-argue the donut from GBTC plumbing rather than anticipation, and report honestly that it doubles the coefficient.
8. Add the financialization strand, Merton (1987), and the econometric method citations; read `khatib2026from`.
9. Add the randomization placebo density figure.
10. Deliver the promised Romano–Wolf adjustment or withdraw the promise.

With items 1–3 alone the paper would have mechanism content rather than mechanism conjecture, and my assessment would change materially. Without them it remains a carefully executed and inferentially exemplary reduced-form null on a question whose channel it cannot address.

OVERALL SCORE: 5.6/10
RECOMMENDATION: Major Revision
