# Peer Review: Bank Stock Response to Federal Reserve Target-Rate Announcements
## Event Study of FOMC Decisions, 2015–2025

**Reviewer:** Literature Reviewer (Academic Journal Simulation)  
**Date:** 2026-09-29  
**Review Type:** Comprehensive Peer Review (Referee Simulation)

---

## EXECUTIVE SUMMARY

This paper presents an event study of 31 FOMC target-rate announcements (December 2015 – December 2025), examining cumulative abnormal returns in the KBE banking sector ETF. The pre-registered analysis employs a market model with event-specific parameter estimation and tests two hypotheses: (H1) mean abnormal returns differ from zero by announcement direction, and (H2) abnormal return magnitudes correlate with Treasury yield surprise. The paper finds null results for H1 in the narrow [−1, +1] event window (hikes: −1.06%, p=0.0603; cuts: −0.08%, p=0.9295) and also for H2 (pooled coefficient −0.0208, p=0.6368). A secondary [0, +5] window shows a significant pooled CAR of −1.47% (p=0.022).

The paper is methodologically sound but offers limited novelty. The contribution is primarily empirical documentation across a 10-year period rather than new theoretical or methodological insight. The identification strategy, while transparent, does not credibly support causal claims, and the empirical analysis does not probe heterogeneity or investigate why null results emerge.

---

## DIMENSION SCORES

### Contribution: 5/10

**Strengths:**
- Comprehensive 10-year retrospective covering multiple distinct policy regimes (gradual 2015–2018 normalization, 2019 reversal, 2020 pandemic emergency cuts, 2022–2023 rapid tightening, 2024–2025 easing)
- Systematic documentation of announcement-day effects across the broadest sample accessible with open data
- Pre-registered design reduces p-hacking concerns and increases credibility
- Examines both rate hikes and cuts, detecting asymmetries (hikes closer to significance at p=0.0603)

**Weaknesses:**
- Event-study analysis of FOMC effects on sector returns is not novel; this application is incremental
- Main findings are null results (non-significant in pre-registered [−1, +1] window), which, while informative, do not advance theory or method
- No new conceptual insight into *why* effects are null (market efficiency, offsetting channels, statistical power?) or *when* they would emerge
- Missing cross-sectional analysis of bank heterogeneity (size, duration risk, capital ratios) despite literature emphasizing these as key predictors of policy transmission—this is the gap the contribution should fill but does not
- No investigation of whether the null H1 results are robust to the robustness checks mentioned in pre-registration (excluding March 2020 emergency cuts, March 2023 financial stress hike, XLF benchmark)—these checks are referenced as pre-registered but not reported
- Null result in H2 (R² = 0.53%) is particularly weak: yield surprise explains almost none of the variation in abnormal returns, but the paper does not investigate why

**Assessment:** The paper documents empirical patterns over a long window but does not generate novel insights. Applying standard event-study methodology to the 2015–2025 period with aggregate data is a straightforward extension of existing work. The null findings themselves, while non-obvious a priori, do not challenge or advance the theoretical understanding of monetary policy transmission to bank valuations.

---

### Identification: 5/10

**Strengths:**
- FOMC meeting dates are known and exogenous in timing; they follow a published calendar not determined by current market conditions or bank performance
- Clear separation of estimation windows from event windows (−250 to −12 trading days) to avoid contamination
- Good institutional documentation: FOMC announcements typically avoid overlap with major employment/CPI releases; equity market is open when announcements occur (2:00 PM ET)
- Market model specification is standard and appropriate for isolating abnormal returns
- Explicit recognition of multiple transmission channels (NIM compression, credit risk, duration risk, risk premia), indicating awareness of confounding mechanisms

**Weaknesses:**
- **Endogeneity not addressed:** Fed policy decisions are endogenous to economic conditions. A rate hike occurring during a growth slowdown will be confounded with the economic shock itself. The 2022–2023 tightening cycle, which prompted the fastest rate increases since 1980, occurred amid inflation concerns; abnormal returns cannot be attributed solely to the rate change. Similarly, the March 2020 emergency cuts coincided with an acute equity market crash driven by pandemic-induced systemic risk—not by the policy move alone. The paper acknowledges multiple transmission channels but does not control for them.
- **Policy surprise not isolated:** The paper uses same-day Treasury yield change (ΔDG S2) as a proxy for policy surprise in H2, but this conflates expected and unexpected components. A rise in the 2-year yield on announcement day reflects both the Fed's announced action and market expectations about the Fed's future path—both of which may be partially anticipated. Fed Funds futures data (if available) would provide a cleaner measure of surprise; the absence of this leaves H2 open to measurement error.
- **No causal claim justified:** The paper frames the analysis as examining "how bank stocks respond" to Fed announcements, implying causality, but the design is purely correlational. An event-study design documents co-movement but does not isolate causal effects.
- **Confounding events during 2020 and 2023:** The March 15–16, 2020 announcement, excluded from some robustness checks, occurred during the largest single-day equity market decline in history; the March 22, 2023 hike occurred amid bank-specific stress (SVB failure March 10). In both cases, the abnormal returns reflect financial system dynamics, not Fed policy effects in isolation.
- **Pre-announcement drift not tested:** Lucca & Moench (2015) document strong mean returns (48 bps) in the 24 hours before FOMC announcements. The paper includes t=−1 in its event window but does not control for or test drift separately. The announcement effect may be partially attributable to prior-day drift.

**Assessment:** The identification strategy is limited to documenting correlation between FOMC dates and bank returns. The paper does not credibly support a causal claim. Endogeneity (Fed responds to economic conditions), measurement error (yield change vs. surprise), and omitted mechanisms (confounding events, pre-announcement drift) are not adequately addressed.

---

### Empirics: 6/10

**Strengths:**
- Large sample of 31 events spanning a full decade across multiple policy regimes
- All data from open-access sources (Yahoo Finance, FRED), ensuring reproducibility
- Event-specific market model estimation (Equation 1) with event-specific parameters (α̂ᵢ, β̂ᵢ) is the appropriate approach
- Non-overlapping event windows by design (12-day gap between end of prior event window and start of next event's estimation window)
- Correct statistical inference: cross-sectional t-tests with n−1 degrees of freedom (df=19 for hikes, df=10 for cuts)
- Heteroskedasticity-consistent standard errors (HC1) in H2 regression, appropriate for cross-sectional data
- Large market model estimation windows (238 trading days) provide stable parameter estimates
- Clear data documentation: prices available from 2014-01-02 onward, ensuring first event (2015-12-16) has full estimation window
- Transparency about data sourcing and pre-registration procedures

**Weaknesses:**
- **Use of aggregate ETF rather than firm-level data:** KBE is a sector ETF; abnormal returns are computed for the entire sector, which averages over idiosyncratic variation across individual banks. The literature (Kashyap & Stein 2000; Cetorelli & Goldberg 2012) documents that responses vary substantially by bank size, capital, and funding structure. Using an aggregate measure masks heterogeneity and reduces power to detect effects.
- **Statistical power not calculated or reported:** With 20–31 events and cross-sectional standard deviations of approximately 2.5–3.0%, the power to detect an economically meaningful effect (e.g., 50 bps per 1% rate move) is moderate at best. This limitation should be stated explicitly; null results may reflect weak power rather than true zero effects.
- **H2 sample small and fit weak:** The regression of CAR on ΔDG S2 uses only 31 events; the R² is 0.53%, indicating that yield surprise explains essentially none of the cross-sectional variation in abnormal returns. The pooled coefficient is −0.0208 (p=0.6368). This null result is striking but not investigated. Why does yield surprise not predict abnormal returns? Is the yield-surprise measure a poor proxy for Fed policy surprise? Is the announcement effect small relative to idiosyncratic noise? Is the transmission channel from rate expectations to bank valuations weaker than expected?
- **Robustness checks not reported in main paper:** The pre-registration specifies robustness checks (excluding March 2020 emergency cuts, March 2023 hike, using XLF as benchmark). These are mentioned in the methodology but results are not systematically reported. Readers cannot assess whether null findings hold across specifications. The researcher's note indicates that "leftover files tables/robustness_march2020.tex, robustness_march2023.tex and xlf.tex are not part of the paper," suggesting they exist but were excluded; this undermines the pre-registration commitment.
- **No bank-level heterogeneity analysis:** Despite the literature review extensively discussing size, capital, and duration as key predictors, the empirical analysis does not stratify by bank characteristics. A cross-sectional regression of CAR on bank balance-sheet variables would directly test whether heterogeneity predicts returns, addressing a central prediction of prior work.
- **No investigation of specific events:** The paper mentions March 2020 (pandemic shock), March 2023 (SVB crisis), and the 2022–2023 rapid tightening as potentially anomalous but does not investigate whether these periods drive the null results. Subsample analysis by regime (normal times vs. financial stress) would clarify whether effects emerge selectively.
- **Null pre-announcement drift analysis:** The paper mentions Lucca & Moench (2015) but does not test for pre-announcement drift in its own sample. Including t=−1 in the event window without controlling for systematic pre-announcement appreciation or depreciation may bias H1 estimates.

**Assessment:** Empirical execution is competent; the event-study design is implemented correctly. However, the empirical analysis is limited in scope. Use of aggregate data rather than firm-level returns reduces power. The null H2 result is striking but not probed. Pre-registered robustness checks are not reported. Heterogeneity analysis, despite being central to the motivation, is absent. Statistical power is not reported.

---

### Writing: 7/10

**Strengths:**
- Clear structure with well-defined sections: Introduction (motivation), Literature Review (comprehensive foundation), Institutional Context (transmission channels), Data and Methodology (replicable specification), Results (transparent null findings), Discussion (interpretation and implications)
- Good pedagogical exposition of event-study methodology (Equations 1–3 for market model, abnormal returns, and CAR are clearly stated)
- Transparent about null findings; does not overstate weak evidence (e.g., acknowledges p=0.0603 for hikes is not significant at 5% level)
- Embedded data references (src: estimation_results.json) link reported numbers to source data, enhancing verifiability
- Good institutional context section explaining FOMC timing, rate transmission mechanisms, and why announcement-day effects are relevant for bank valuations
- Appropriate tone: professional, measured, honest about limitations

**Weaknesses:**
- **Disclaimer format unusual:** The prominent disclaimer at the top stating this is "machine-generated using Claude AI" is unusual for a traditional journal submission. While transparency is good, the phrasing "abnormal returns were computed by the data analyst… blind (the results were not reviewed before pre-registration)" reads awkwardly and may distract reviewers. A brief note in acknowledgments or methods might be clearer.
- **Mechanical presentation of null results:** The results section reports findings but does not deeply interpret them. For example, H2 shows R² = 0.53%, but the paper does not explore what this means (measurement error? weak transmission? noise dominating signal?).
- **Discussion section lacks incisiveness:** Four interpretations of null H1 results are offered (market efficiency, offsetting channels, low statistical power, longer lags), but the paper does not adjudicate between them or provide evidence for any. A more critical discussion (e.g., testing for pre-event drift, comparing power to detect 50 bps effects, stratifying by event type) would strengthen the paper.
- **Missing economic magnitude contextualization:** The paper reports −1.06% CAR for rate hikes but does not contextualize this against, say, the bank sector's duration (what is the expected sensitivity of bank equity to a 100 bps rate move?). Economic significance is unclear.
- **Redundancy between sections:** The introduction motivates the question, the literature review covers transmission mechanisms, and the institutional context section repeats much of this. Some consolidation would improve conciseness.
- **No "punchline" conclusion:** The paper ends with implications for practitioners and policymakers, but readers are left uncertain whether the main finding is that announcements do not matter, or whether the effect is present but small, or whether the methodology/data are insufficient to detect it.

**Assessment:** Writing is generally clear and professional, with good structure and methodology exposition. However, the interpretation of results is shallow, the disclaimer is awkwardly phrased, and the critical engagement with the findings is limited. Writing would benefit from deeper investigation of the null results and clearer takeaways.

---

### Literature: 6/10

**Strengths:**
- Comprehensive literature section (Section 2 in paper, plus detailed literature_review.md document) demonstrating awareness of prior work
- Cites foundational event-study methodology (MacKinlay 1997; Campbell, Lo, & MacKinlay 1997) and applies it correctly
- References key works on Fed policy and asset prices (Bernanke & Kuttner 2005, Kuttner 2001, Lucca & Moench 2015)
- Discusses bank-specific transmission channels with appropriate citations (Kashyap & Stein 2000, Driscoll 2004, Gambacorta 2005)
- Acknowledges heterogeneity by bank size, capital, and business model
- Situates work within debate on monetary policy transmission to equities
- Discusses offsetting mechanisms (NIM vs. credit risk vs. duration vs. risk premia) that could explain null results

**Weaknesses:**
- **Heterogeneity-empirics gap:** The literature review extensively discusses bank size, capital ratios, and duration risk as predictors of policy response (citing Kashyap & Stein 2000, Cetorelli & Goldberg 2012, Driscoll 2004). Yet the empirical analysis uses aggregate KBE data and does not examine heterogeneity. This gap between literature foundation and empirical execution is a major weakness; the heterogeneity discussion should either be removed or the empirical analysis should test it.
- **Limited engagement with recent work on 2023 bank stress:** The literature cites Landier, Noel, & Thesmar (2015) on interest-rate risk and bank valuations, but does not deeply integrate findings about duration risk in accumulated long-term bond portfolios. The 2023 regional bank crisis (SVB failure March 10, 2023) directly reflected duration losses not adequately priced into equities earlier; this should be central to interpreting the March 2023 event but is mentioned only briefly.
- **Post-2008 regulatory context underutilized:** Thakor (2018) on how capital regulation changes transmission is cited but not integrated into the empirical analysis. The 2015–2025 period is post-Dodd-Frank steady state; how do leverage ratios and liquidity coverage ratios alter bank responses compared to pre-2008? This is not explored.
- **Forward guidance vs. target rate not distinguished:** Hanson & Stein (2015) on Fed communication and forward guidance is cited in references but not integrated into the analysis. FOMC announcements often include forward guidance (e.g., signaling future rate path) separate from the target-rate decision itself. The empirical design does not separate these; a more refined analysis would examine whether guidance surprises predict returns independently of rate surprises.
- **Fed Funds futures not used:** Kuttner (2001) develops identification using Fed Funds futures to extract policy surprises. The paper acknowledges this but does not implement it, leaving H2's yield-surprise measure as a coarse proxy.
- **Generic treatment of references:** Many citations are standard references (MacKinlay 1997 for event studies, Bernanke & Kuttner 2005 for Fed effects) without deep critical synthesis. The literature is woven into the paper but not critiqued or synthesized into a novel perspective.

**Assessment:** Literature is adequately covered but somewhat generic. The major weakness is the gap between the heterogeneity discussion in the literature review and its complete absence from the empirical analysis. Recent work on duration risk and regulatory constraints is cited but underutilized. The paper reads as competently grounded in prior work but does not synthesize new insights or identify a clear research gap that the paper fills.

---

## WEIGHTED OVERALL SCORE

| Dimension | Score | Weight | Contribution |
|-----------|-------|--------|---------------|
| Contribution | 5/10 | 25% | 1.25 |
| Identification | 5/10 | 25% | 1.25 |
| Empirics | 6/10 | 20% | 1.20 |
| Writing | 7/10 | 15% | 1.05 |
| Literature | 6/10 | 15% | 0.90 |
| **OVERALL** | — | — | **5.65/10** |

---

## MAJOR CONCERNS

1. **Limited Conceptual Contribution with Null Main Results**
   - The paper applies standard event-study methodology to a straightforward research question (do bank stocks react to Fed announcements?), documenting that the answer is "not significantly in the [−1, +1] window." Null results are informative but do not advance theory. The paper would require deeper investigation into *why* effects are null (market efficiency? offsetting mechanisms? weak measurement? low statistical power?) to constitute a meaningful contribution. Without this, the paper is primarily an empirical documentation of a decade of data rather than a conceptual advance.

2. **Endogeneity and Causal Claims**
   - The paper frames results as describing "how bank stocks respond" to Fed policy, implying causality, but the identification strategy does not support causal inference. Fed rate decisions are endogenous to economic conditions (Fed tightens when growth is strong, cuts when facing recession). A rate increase during a downturn is confounded with economic shock. The paper acknowledges transmission channels but does not address this core endogeneity. Fed Funds futures data, if available, could isolate surprise-component of policy; this is not employed.

3. **Absence of Cross-Sectional Analysis Despite Theoretical Prominence**
   - The literature review extensively documents that bank size, capital ratios, duration risk, and funding structure predict heterogeneous responses to Fed policy (Kashyap & Stein 2000, Driscoll 2004, Cetorelli & Goldberg 2012). Yet the empirical analysis uses an aggregate sector ETF (KBE) and does not examine any cross-sectional heterogeneity. This is a critical omission. A regression of individual bank abnormal returns on balance-sheet characteristics (or stratification of results by bank size) would directly test the central prediction of prior work and would differentiate the paper's contribution.

4. **H2 Null Result Not Investigated**
   - The regression of CAR on same-day Treasury yield change yields R² = 0.53% and a pooled coefficient of −0.0208 (p=0.6368). This near-zero fit is striking: yield surprise explains essentially none of the variation in abnormal returns. Yet the paper does not investigate why. Possible explanations: (a) ΔDG S2 is a poor proxy for policy surprise (contaminated by market expectations); (b) the announcement-day effect is small relative to idiosyncratic noise; (c) the transmission channel from rate expectations to bank valuations is weaker than predicted. The paper does not test any of these. Appendix analysis or simulation would strengthen the paper.

5. **Pre-Registered Robustness Checks Not Reported**
   - The pre-registration explicitly specifies robustness checks: (i) exclude March 2020 emergency cuts, (ii) exclude March 2023 hike, (iii) use XLF as benchmark instead of SPY. The researcher's note indicates these were prepared but not included in the paper ("leftover files… not part of the paper and contradict the pre-registration"). This undermines the credibility of the pre-registration commitment. Readers cannot assess whether the null findings hold across specifications. These checks should be included in an appendix or main results.

---

## MINOR CONCERNS

1. **Statistical Power Not Reported**
   - With 20–31 events and cross-sectional SD ≈ 2.5%, power to detect an economically meaningful effect (e.g., 50 bps per 1% rate move) is moderate. The paper does not calculate or report power. A power analysis would clarify whether null results reflect true zero effects or insufficient sample size.

2. **Aggregation Decision Not Justified**
   - The use of KBE (sector ETF) rather than individual bank stock returns is practical (avoids large data requirements) but reduces power (idiosyncratic noise) and prevents heterogeneity analysis. This trade-off should be explicitly discussed and justified.

3. **Pre-Announcement Drift Not Tested**
   - Lucca & Moench (2015) documents strong mean returns (48 bps) in 24 hours before FOMC announcements. The paper mentions this but does not test for drift in its sample. Including t=−1 in the event window without controlling for drift may bias H1 estimates. A separate test of pre-event abnormal returns (t=−10 to −2) would clarify.

4. **Disclaimer Phrasing Unusual**
   - The prominent disclaimer that this is "machine-generated using Claude AI" and the note that abnormal returns were computed "blind" before pre-registration is transparent but reads awkwardly. A brief sentence in the methods or acknowledgments might be clearer.

5. **Measurement of Policy Surprise Weak in H2**
   - Using same-day Treasury yield change (ΔDG S2) as a proxy for policy surprise conflates expected and unexpected components. A cleaner approach would use Fed Funds futures data (prior-day implied path vs. actual announcement). The absence of this leaves H2 open to measurement error and may explain the weak fit.

6. **Economic Significance Not Contextualized**
   - A −1.06% CAR for rate hikes is reported but not compared to, e.g., the bank sector's estimated duration. What is the expected sensitivity of bank equity to a 100 bps rate move? How does the observed effect compare to this benchmark?

---

## POSITIVE ASPECTS

1. **Methodologically Sound Event-Study Design**
   - The market model specification (Equation 1) is correctly implemented with event-specific parameter estimation. Event windows are properly separated from estimation windows (12-day gap). Market model parameters are estimated over 238 trading days, providing stable estimates. Cross-sectional inference is correct (t-test with n−1 df). HC1 standard errors are used in regression.

2. **Comprehensive 10-Year Sample Across Policy Regimes**
   - Sample covers 31 events spanning multiple distinct policy cycles: 2015–2018 gradual normalization, 2019 reversal, 2020 pandemic emergency measures, 2022–2023 rapid tightening (fastest since 1980s), and 2024–2025 easing. This breadth is a strength and allows testing across diverse conditions.

3. **Pre-Registration Reduces p-Hacking**
   - The paper specifies hypotheses, estimation window, and event windows in advance, computing abnormal returns blind before pre-registration freeze. This reduces concerns about selective reporting or data-mining.

4. **Transparent Data and Code**
   - All data are from open-access sources (Yahoo Finance, FRED). Methodology is detailed and replicable. Embedded data references link numbers to source estimates. This transparency is exemplary for empirical work.

5. **Honest Reporting of Null Results**
   - The paper does not oversell weak evidence. It clearly states that H1 is not significant at the 5% level for hikes (p=0.0603) and cuts (p=0.9295), and H2 is non-significant (p=0.6368). There is no p-hacking or selective emphasis.

6. **Good Institutional Context and Motivation**
   - The paper explains FOMC timing, transmission channels, and institutional details clearly, making the research question and design accessible to readers unfamiliar with Fed operations.

---

## RECOMMENDATIONS FOR REVISION

If the authors were to revise this paper for resubmission, the following changes would strengthen it significantly:

1. **Add bank-level heterogeneity analysis.** Obtain data on individual bank stock returns stratified by size (market cap quartile or asset size) and balance-sheet characteristics (duration risk, capital ratio, deposit franchise). Regress CAR on these characteristics. This is central to the literature motivation and absent from the empirical work.

2. **Report pre-registered robustness checks.** Include a table or appendix section showing H1 and H2 results (i) excluding March 2020, (ii) excluding March 2023, and (iii) using XLF as benchmark. Assess whether null results hold across specifications.

3. **Investigate H2 null result.** Add analysis explaining why yield surprise predicts almost none of the variation in abnormal returns. Consider: (a) measurement error in ΔDG S2 as proxy for surprise, (b) event-by-event comparison of yield moves vs. abnormal returns to identify outliers, (c) subsample analysis by rate direction or regime to check for heterogeneous relationships.

4. **Calculate and report statistical power.** Using the observed cross-sectional SD and sample sizes, compute power to detect effect sizes of 50, 100, and 150 bps. Clarify whether null results reflect true zero effects or weak power.

5. **Deepen the discussion of null results.** Move beyond listing four possible interpretations to testing them (pre-event drift, market efficiency indicators, regime-dependent effects, asset-level measurement error). This would transform a purely empirical documentation into a more analytical contribution.

6. **Clarify the causal claim.** Either reframe the paper explicitly as correlational (documenting co-movement without claiming causality), or use policy-surprise identification (Fed Funds futures) to isolate exogenous variation in expectations.

---

## SUMMARY FOR DECISION

This paper presents a competently executed event study on a straightforward research question: do bank stocks react to FOMC announcements? The answer, over the 2015–2025 period, is "not significantly in the tight [−1, +1] window." The methodology is sound, the data transparent, and the pre-registration credible. However, the contribution is limited. The paper does not advance theory, does not probe the null results to explain them, does not examine heterogeneity central to its literature foundation, and does not address endogeneity in policy causation. The empirical analysis uses aggregate data when cross-sectional analysis of bank characteristics would be far more informative. The H2 regression (yield surprise predicting CAR) fails dramatically (R² = 0.53%), but this striking null is not investigated.

The paper would be strengthened substantially by (i) bank-level heterogeneity analysis, (ii) deep investigation of why H2 fails, (iii) reporting of pre-registered robustness checks, and (iv) a more critical discussion of what null results tell us about market efficiency, policy transmission, or data limitations. In its current form, it is primarily a thorough documentation of a decade of announcement-day data, not a scholarly contribution to understanding monetary policy transmission or bank valuations.

---

DIMENSION SCORES:
- Contribution: 5/10
- Identification: 5/10
- Empirics: 6/10
- Writing: 7/10
- Literature: 6/10

OVERALL SCORE: 5.65/10
RECOMMENDATION: Major Revision
