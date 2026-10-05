# Referee Report — Literature Review

**Paper:** *No Cash Flows, New Owners: Spot Bitcoin ETFs and the Origins of Co-movement*
**Paper ID:** e432cf3f-9008-4202-8ee6-ff09a93948ec
**Reviewer role:** Literature Reviewer (full referee simulation, weighted toward coverage and positioning)
**Date:** 2026-09-11

---

DIMENSION SCORES:
- Contribution: 5.5/10
- Identification: 6.5/10
- Empirics: 6/10
- Writing: 8/10
- Literature: 3.5/10

Weighted: 0.25(5.5) + 0.25(6.5) + 0.20(6.0) + 0.15(8.0) + 0.15(3.5) = 5.925.

---

## Summary of the assessment

This is a carefully executed, unusually honest empirical paper wrapped in a literature section that is not yet at submission standard. The identification reasoning, the inference discipline under one treated unit, and the willingness to report the gold placebo, the BITO placebo, the sign flip under `ctrl_vix_move`, and a power verdict that falls *between* its own pre-committed bars are all above the norm for this literature. The prose is genuinely good.

The literature apparatus, by contrast, has three structural holes — a missing analogue strand, a missing theoretical citation for the paper's own model, and a complete absence of method citations — plus an uncited numerical benchmark on which the paper's headline claim rests. None of these are design failures. All are additive work. But together they are enough that the paper as it stands would be desk-rejected or returned by a JFE/RFS editor on reference grounds alone, and several of them change how the contribution should be framed.

---

## MAJOR CONCERNS

### 1. The commodity-financialization strand is entirely absent, and it is the paper's closest structural analogue — including a published result that anticipates the null

The paper does not mention commodities once. This is the single most damaging omission, for two reasons.

**First, the setting is the same setting.** "A new financial product made an asset class accessible to a new clientele; did co-movement with equities rise?" is the commodity-financialization question, asked about commodity index products in the mid-2000s. Tang and Xiong (2012, *Financial Analysts Journal* 68(6), 54–74) is the direct methodological ancestor of this paper's design: they compare *indexed* against *off-index* commodities, which is structurally identical to comparing an ETF-listed coin against never-listed coins. Basak and Pavlova (2016, *JF* 71(4), 1511–1556) supply a formal model in which benchmarked institutional demand raises index constituents' volatility and their correlation with each other and with the market *with no change in fundamentals* — i.e. the closest existing formal statement of the paper's own equation (1). Henderson, Pearson and Wang (2015, *RFS* 28(5), 1285–1311) isolate mechanically-driven hedging flow to identify the financial-investor channel, which is the inverse of the basis-versus-allocation decomposition the paper's Section 3 proposes and cannot estimate. A referee in this field will notice all three within a paragraph.

**Second, and more seriously, Cheng and Xiong (2014, *Annual Review of Financial Economics* 6, 419–441) already argue the paper's conclusion in the prior setting.** Their position is that the index-flow explanation for rising commodity–equity co-movement is overstated and that much of the observed increase reflects common macro shocks — global demand, the dollar, monetary policy — rather than the new clientele. That is, almost exactly, this paper's Section 8: "the common component is large and the Bitcoin-specific component is not distinguishable from zero."

This cuts both ways and the paper must decide which way it wants it. Left uncited, the finding reads as novel when a referee will recognise it as a replication of a published argument in a new asset class. Cited and confronted, the finding becomes *stronger*: the paper supplies an out-of-sample test of Cheng–Xiong in a setting where the fundamentals channel Cheng–Xiong could not rule out (commodities have real supply and demand) is unavailable by construction. That is a better contribution claim than the one currently in Section 1, and it costs a paragraph. **Make Cheng–Xiong the named prior in the introduction and the null's theoretical ally in the conclusion.**

Required additions (verify each DOI on save; the literature-scan handoff lists them as blocked by a save-budget cap):

| Reference | Role |
|---|---|
| Tang & Xiong (2012), *FAJ* 68(6) | Indexed-vs-off-index design ancestor |
| Basak & Pavlova (2016), *JF* 71(4) | Formal clientele model with no fundamentals change |
| Basak & Pavlova (2013), *AER* 103(5) | Institutional investors and equilibrium correlations |
| Henderson, Pearson & Wang (2015), *RFS* 28(5) | Mechanical-flow identification; inverse of the §3 flow decomposition |
| Cheng & Xiong (2014), *ARFE* 6 | **The counterweight; the named prior for the null** |
| Hong & Yogo (2012), *JFE* 105(3) | Futures-market interest and asset prices |
| Singleton (2014), *ManSci* 60(2) | Investor flows and commodity price dynamics |
| Büyükşahin & Robe (2014), *JIMF* 42 | Trader-type composition and cross-market correlation |

### 2. Section 4 builds a Merton (1987) participation-cost model and never cites Merton (1987)

Section 4 introduces a per-period participation cost $\kappa$, an allocator participation function $\lambda(\kappa)$ with $\lambda'<0$, and an equilibrium loading that is a participation-weighted average across clienteles, and describes this as being "in the spirit of the investor-recognition tradition." There is no citation attached to that phrase, and Merton (1987, *JF* 42(3), 483–510) does not appear anywhere in the paper. This is the workhorse citation for the entire framework. Its absence is, on its own, disqualifying at a top journal — a referee reading Section 4 will assume the authors do not know the source of their own model.

Related theoretical omissions in the same section: Koijen and Yogo (2019, *JPE* 127(4)) for the demand-system statement that who holds an asset determines its covariance structure; Bekaert and Harvey (1995, *JF* 50(2)) and Karolyi and Stulz (1996, *JF* 51(3)) for the segmentation-and-integration framing that Section 4's two-clientele structure is a special case of; and the inelastic-markets line of work (Gabaix and Koijen) for the modern demand-based statement of the same idea. Merton is mandatory; the other three are strongly advisable.

### 3. The paper cites no econometric methods literature at all, despite naming roughly a dozen procedures

Sections 5 through 7 name, in prose, with zero citations: Fisher-$z$, randomization inference, Conley–Taber intervals, the wild cluster bootstrap, the Bertrand–Duflo–Mullainathan collapse, the one-treated-cluster invalidity result, Bai–Perron multiple structural break tests, the Andrews sup-Wald test, DCC–GARCH, the Chow test, Newey–West, Rambachan–Roth (mentioned in the companion spec, silently dropped from the paper), and Callaway–Sant'Anna (referenced only obliquely via "the forbidden comparison that generates negative weights in staggered designs").

The paper's *second* stated contribution is that the inference procedure "is not a technicality in a one-treated-unit design but the difference between a null and three false positives." That contribution is uncitable as written, because the claim that cluster-robust inference fails with one treated cluster is not the authors' — it is Conley and Taber (2011) and MacKinnon and Webb's work on few and on one treated cluster. Attributing it correctly does not weaken the contribution; it converts an unsupported assertion into a demonstrated application.

Minimum required set: Merton (1987) as above, plus Conley & Taber (2011, *REStat* 93(1)); MacKinnon & Webb on few/one treated clusters (*Econometrics Journal* 2018; *JAE* 2017); Bertrand, Duflo & Mullainathan (2004, *QJE* 119(1)); Cameron, Gelbach & Miller (2008, *REStat* 90(3)); Engle (2002, *JBES* 20(3)); Bai & Perron (1998, *Econometrica* 66(1); 2003, *JAE* 18(1)); Andrews (1993, *Econometrica* 61(4)); Chow (1960, *Econometrica* 28(3)); Newey & West (1987, *Econometrica* 55(3)); Callaway & Sant'Anna (2021, *J. Econometrics* 225(2)); Sun & Abraham (2021, same issue); Borusyak, Jaravel & Spiess (2024, *REStud* 91(6)); Rambachan & Roth (2023, *REStud* 90(5)); Abadie, Diamond & Hainmueller (2010, *JASA* 105(490)); Scholes & Williams (1977) and Dimson (1979) for the non-synchronous-trading discussion in Section 4.4.

### 4. The headline claim rests on an uncited numerical benchmark

The paper's central sentence — "The design excludes an increase in equity correlation above about $0.086$, which rules out the upper half of the range the index-inclusion literature reports" — depends entirely on the assertion, made twice in the paper and twice in the companion specification, that the index-inclusion literature reports correlation changes of roughly 0.05 to 0.15 (and beta changes of 0.2 to 0.4). **No citation is attached to either range anywhere.**

This is not a stylistic lapse. The pre-committed MDE bar of 0.10 is calibrated *from* that range; the verdict that the realized MDE of 0.148 "falls between the bars" is a function of it; and the entire interpretation of the null as informative rather than uninformative follows from it. As written, the paper's most load-bearing number is unfalsifiable and looks reverse-engineered, whatever the authors' actual chronology.

The fix is a short benchmark table in Section 3 or Section 6.6 that reports, paper by paper, what magnitude each study found, on what horizon, in what units, and how each was converted to the paper's correlation metric: Vijh (1994, *RFS* 7(1)) on inclusion-induced beta changes; Barberis, Shleifer and Wurgler (2005, *JFE* 75(2)) on bivariate and multivariate beta shifts for S&P additions; Boyer (2011, *JF* 66(1)) on style-label reclassification; Greenwood (2008, *RFS* 21(3)) on Nikkei weight changes; Da and Shive (2018, *EFM* 24(1)) on the ETF-ownership co-movement gradient. Add Chang, Hong and Liskovich (2015, *RFS* 28(1)) on the Russell reconstitution discontinuity, which is the most nearly mechanical index-membership design in print and a better modern comparator than Boyer alone. Where the conversion between reported beta changes and correlation changes requires a volatility-ratio assumption, state the assumption. If the resulting benchmark range is wider or differently centred than 0.05–0.15, the power verdict must move with it.

### 5. The nearest competitor has not been read, and the paper asserts what it found

`khatib2026from` (Al khatib & Alshaib, 2026, *IREF*) is cited twice and characterised as documenting "a regime shift in crypto–equity integration around the spot ETF." The literature-scan handoff states plainly that the full text is paywalled, was not retrieved, and that every characterisation is inferred from title and outlet only — and flags that the title's framing ("from contagion to *stabilization*") may not be a co-movement-*increase* claim at all.

Two consequences. First, the paper asserts a specific finding of a paper it has not read, in a sentence that carries the weight of its first stated contribution. Second, and more consequentially, contribution #1 — "what has not been supplied is a comparison group of assets that experienced the same macro environment without the access change" — is conditional on that paper not using a cross-asset counterfactual, which is unverified. If they do, contribution #1 evaporates and the paper must lead with the inference argument or the power bound instead.

This is blocking. Obtain the article (interlibrary loan, author request, or the accepted manuscript), read it, and rewrite the two citing sentences to describe what it actually does. Answer three questions in the text: does it use a cross-asset counterfactual; does it decompose by session or intraday; does it use flow data and does it distinguish flow types.

### 6. Load-bearing institutional and empirical claims carry no citation and no source

Section 3 (Institutional background) contains zero citations, and Section 7 contains zero. Among the uncited claims that do real work:

- **"A substantial share of early institutional participation in these products was not allocation... Hedge funds ran the cash-and-carry basis trade."** This is an empirical claim about 13F composition. It is presented without evidence, without a source, and without a magnitude — and the paper's closing interpretive move ("the most economical explanation for that pair of facts is that a substantial share of those assets never represented directional exposure at all") depends on it entirely. Either cite the 13F evidence and quantify it, or demote the claim to an explicitly flagged conjecture that the paper cannot evaluate. As written, the conclusion's most quotable sentence rests on an assertion.
- **"by December 2023 market-implied odds were high."** This justifies the donut. It needs a source — prediction-market prices, Bloomberg Intelligence's published odds series, or an options-implied measure.
- **The SEC approval order and *Grayscale v. SEC*.** Cite the primary sources directly: SEC Release No. 34-99306 (January 10, 2024) and *Grayscale Investments, LLC v. SEC*, 82 F.4th 1239 (D.C. Cir. 2023). A background section built on a regulatory order and an appellate opinion must cite both.
- **The pre-2024 crypto–equity spillover benchmark.** Iyer (2022), *Cryptic Connections: Spillovers between Crypto and Equity Markets*, IMF Global Financial Stability Note 2022/001, is the standing institutional benchmark for what this paper's dependent variable did before the ETF, and it attributes the post-2020 rise in spillovers partly to institutional entry. Its absence means the paper's *hypothesis* may be pre-existing in a form the paper never acknowledges. Cite it and say explicitly what is new relative to it.

### 7. The bibliography will print wrong years, and one wrong journal

The literature-scan handoff documents that the resolver populated year fields from working-paper or online-first records. With `\bibliographystyle{chicago}`, these print. Confirmed corrections needed before compilation: `barberis2004comovement` → 2005; `bendavid2014do` → 2018; `da2017exchange` → 2018; `greenwood2007excess` → 2008; `liu2020risks` → 2021; `makarov2019trading` → 2020; `glosten2020etf` → 2021; `baltussen2018indexing` → 2019; `baur2017bitcoin` → 2018; `bouri2016on` → 2017. And `brown2020etf` carries `journal = "European Finance Review"`, which is the pre-2004 title — it is *Review of Finance* 25(4), 937–972 (2021). Every one of these is currently cited in the draft body, so every one will print incorrectly.

Separately: `corbet2018retracted` (DOI 10.1016/j.irfa.2018.09.003) is a **retracted** article sitting in `literature.bib`. It is not currently cited, which is correct — but it should be deleted from the file rather than left as a trap for a later revision pass.

Also resolve a discrepancy in the internal documents: `biais2023equilibrium` is listed as *JF* in one place and *RFS* in another. It is *Journal of Finance*.

---

## MINOR CONCERNS

1. **`tang2026the` is doing more work than its outlet can support.** Section 2 leans on it for the authorized-participant / US-session-liquidity conjecture. The literature scan characterises it as a narrative review in a non-finance, low-tier outlet with garbled passages and unverifiable secondary statistics. The mechanism it conjectures follows directly from Da and Shive (2018) and Ben-David, Franzoni and Moussawi (2018) applied to a spot creation-redemption wrapper; attribute it there and either drop `tang2026the` or reduce it to a single parenthetical noting that the conjecture is in circulation.

2. **`pucher2026falsenews` is cited to an unverified record.** The scan reports the article could not be retrieved and no DOI is on file. Verify the outlet, volume and page before the reference list is frozen.

3. **Canada's February 2021 spot Bitcoin ETF is never mentioned.** A US-adjacent spot product listed three years earlier in a smaller market is an obvious out-of-sample replication of this exact design, and a referee will ask why it was not attempted. Even a paragraph in the conclusion explaining why it was not feasible here would pre-empt the question.

4. **The BITO placebo is reported with no literature context.** The row is one of the paper's most interesting and most damaging results (a non-event generating a larger apparent effect than the event). The paper should state that it could locate no published work on the October 2021 futures listing's effect on Bitcoin's factor structure, rather than reporting the placebo as though the question had never been asked.

5. **The pre-registered decision rule is now unsatisfiable, and the paper does not say so.** The identification strategy committed to supporting H1 only if *both* the DiD returns $\hat\tau>0$ with RI $p<0.05$ *and* the session DDD shows US-hours concentration. The session DDD is not estimable on this data. The pre-committed rule therefore could not have returned a positive verdict whatever the data showed. Given how much credit the paper (rightly) claims for pre-commitment, this needs one honest sentence in Section 5.6.

6. **The paper omits a striking descriptive fact from its own data build that would help it.** The data summary reports that gold's raw pre/post correlation with SPY rose +0.0581 and silver's +0.0458, against Bitcoin's +0.0092 — the placebo assets moved five to six times as much as the treated unit. That fact appears only inside a figure. Put it in the text: it is the most legible single piece of evidence for the paper's central claim that 2024–25 raised alternative-asset equity correlation generally.

7. **"Six methodologically distinct estimators" overstates the independence of the evidence.** The BDM collapse returns a numerically identical point estimate to the headline (the paper says so itself), and the daily rolling panel is the same returns re-windowed. Three genuinely distinct routes — the Fisher-$z$ panel, the returns-level triple difference, and the DCC with its control-pair distribution — is a more defensible claim and loses nothing.

8. **A specified inference check appears not to have been run or reported.** The econometric specification commits to validating the generated-outcome standard errors against a two-step stationary block bootstrap and to reporting that the analytic and bootstrap adjustments agree. No such comparison appears in the paper. Either report it or state that it was dropped and why. Similarly, Rambachan–Roth is dropped with the randomization interval offered as a substitute; the substitution is disclosed in the spec but not in the paper.

9. **Related literature is thin for the claim being made.** Four paragraphs across four strands, for a paper positioning itself against the index-inclusion, ETF, financialization and crypto asset-pricing literatures simultaneously. With the additions above it will roughly double, which is the right length.

10. **Small numerical slip.** Section 6.2 computes the variance-share change as 0.0135 and describes it as "about one and a half percentage points." It is 1.35 points; say so.

---

## POSITIVE ASPECTS

1. **The "no cash flows" claim is narrowed correctly, and this was the paper's most attackable framing.** The introduction concedes explicitly that Bitcoin has fundamentals in the broader sense (hashrate, halvings, on-chain activity, regulatory repricing), concedes that a common real-rate factor is a discount-rate channel requiring no ownership change, and states that what the setting shuts off is the *cash-flow-news* channel specifically. It then positions the setting against `froot1999how`, `boyer2011stylerelated` and `greenwood2007excess` rather than claiming priority over them — "Bitcoin does not do something unprecedented; it does something the twin-share and reclassification designs achieve for a handful of securities, for an entire asset class." That is exactly the defensible version, and it is rare to see a paper give up its most quotable overclaim voluntarily.

2. **The `israeli2017is` / `glosten2020etf` reconciliation is the best use of literature in the paper.** Reading the apparent conflict as a shift in price informativeness from idiosyncratic toward systematic, and then observing that an asset with no earnings has nothing for that channel to work on, gives the null a specific, citable micro-foundation rather than a rationalisation. This should be developed further, not less.

3. **Sources are used as evidence rather than as decoration.** `liu2020risks` supports $\beta^c \approx 0$ as an empirical finding rather than an assumption; `biais2023equilibrium` carries the no-dividend claim theoretically rather than rhetorically; `hu2019cryptocurrencies` is cited *against* the paper's own result, as the evidence for the SUTVA attenuation the design concedes. Citing a paper because it cuts against your finding is the right instinct.

4. **`guliyev2025from` is handled with unusual care** — reported at its actual significance level (10%), and its weakness turned into a motivating puzzle for the basis-trade wedge rather than inflated into corroboration.

5. **The honesty is exemplary and should survive revision intact.** The gold placebo that rejects under the wrong column; the BITO placebo that is larger than the treatment effect; the sign flip under differential macro loading, reported with the explicit statement that a positive-effect paper could have been produced from the same data; the power verdict landing between two pre-set bars with neither bar retrofitted. Several of these would have been quietly omitted by most submissions.

6. **The writing is clear, specific and well-paced**, with claims stated at the precision the evidence supports and magnitude discipline enforced throughout ($\rho^2$ reported beside every correlation).

---

## Path to revision

The literature work is bounded and mechanical, and none of it requires re-estimation:

1. Save and integrate the eight financialization references and Merton (1987); rewrite Section 2 to add a financialization paragraph and Section 4 to anchor the model. Make Cheng–Xiong the named prior for the null in the introduction and conclusion. *(Highest value; changes the contribution framing.)*
2. Add the full econometric methods citation set. *(Mechanical; blocking.)*
3. Build the index-inclusion benchmark table and re-derive the 0.05–0.15 range from it, adjusting the power verdict if the range moves. *(Blocking for the headline claim.)*
4. Obtain and read `khatib2026from`; rewrite the two citing sentences and, if necessary, re-rank the three contributions.
5. Source or demote the basis-trade claim, the market-implied-odds claim; cite SEC Release 34-99306, *Grayscale v. SEC*, and Iyer (2022).
6. Fix the eleven year fields and the `brown2020etf` journal field; delete the retracted entry.

Items 1–4 are substantive and would move the Literature score into the 7s and the Contribution score up roughly a point. Items 5–6 are a day's work. The empirical core of the paper does not need to change.

OVERALL SCORE: 5.9/10
RECOMMENDATION: Major Revision
