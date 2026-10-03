# Mechanism Review: Bank Stock Response to FOMC Target-Rate Announcements

## Summary
This paper conducts an event study of 31 FOMC target-rate announcements (2015–2025) to examine abnormal returns in the KBE banking sector ETF. Using a market model with a 238-trading-day estimation window, the authors test whether mean cumulative abnormal returns (CAR) differ from zero in a 3-day window centered on announcements (H1) and whether abnormal returns correlate with same-day Treasury yield surprises (H2). Main findings: no significant announcement-day effect for rate hikes (−1.06%, p=0.0603) or cuts (−0.08%, p=0.9295) in the pre-registered window; no significant relationship between abnormal returns and yield surprise (β=−0.0208, p=0.6368, R²=0.0053). A secondary analysis of the [0,+5] window yields a significant pooled mean CAR of −1.47% (p=0.022). The paper is transparent about methodology and limitations, with appropriate disclosure of machine-generated analysis.

---

## DIMENSION SCORES

**Contribution: 5/10**

*Rationale:* The paper provides systematic event-study evidence spanning a full decade of FOMC decisions, which has longitudinal value. However, the contribution is limited by: (1) null results in the pre-registered window—documenting that bank stocks do not move significantly around FOMC announcements is neither surprising nor novel given prior literature on efficient markets and offsetting economic forces; (2) the secondary significant finding (−1.47% CAR in [0,+5] window) is exploratory and not pre-registered, raising concerns about post-hoc window selection; (3) no new mechanism or insight into monetary policy transmission beyond what existing literature establishes (net interest margin effects, credit risk channels, duration effects). The paper's value is primarily as a methodological demonstration rather than a substantive contribution to understanding Fed-bank stock dynamics.

**Identification: 5.5/10**

*Rationale:* Strengths: (1) FOMC announcements occur on a published, exogenous calendar; (2) market model specification is standard and appropriate; (3) 238-trading-day estimation window is reasonable and non-overlapping across events. Weaknesses: (1) **Critical:** Treasury yield change (DGS2) is used as a proxy for Fed policy surprise, but this is problematic. Treasury yields respond to multiple factors (inflation expectations, real growth revision, risk-premia shifts) beyond Fed action. Without high-frequency Fed Funds futures data, the paper cannot cleanly separate announcement surprise from market expectations. Literature (Bernanke & Kuttner 2005; Kuttner 2001) emphasizes the importance of measuring surprise correctly; this design falls short. (2) Yield curve non-parallel shifts are plausible but not addressed—a 2-year yield increase could reflect steepening rather than policy tightening. (3) Systemic confounds in crisis periods (March 2020, March 2023) acknowledged but inadequately mitigated; excluding these in robustness checks (noted as incomplete) would strengthen claims. (4) Exclusion restriction—that Fed policy affects bank returns only via interest rates—is plausible but not tested; risk-sentiment and financial-stability channels could operate independently.

**Empirics: 6/10**

*Rationale:* Strengths: (1) Data are from public sources (FRED, Yahoo Finance), fully documented and reproducible; (2) all 31 events used as pre-registered; (3) statistical inference is correct—t-tests with proper degrees of freedom (n−1), cross-sectional standard errors, two-sided p-values; (4) H2 uses heteroskedasticity-consistent (HC1) standard errors appropriately for 31 observations; (5) market model R² adequately high (typical range 0.8–0.95 for broad market benchmark). Weaknesses: (1) **Sample size and power:** With n=20 hikes and n=11 cuts, and cross-sectional SD ≈2.5–3%, power to detect small but economically meaningful effects (e.g., −50 bps mean CAR) is limited. No post-hoc power analysis reported. (2) **H2 explanatory power is vanishingly small** (R²=0.0053): Treasury yield surprise explains less than 1% of variation in abnormal returns. The paper does not explore why—this could indicate: (a) poor surprise measurement (likely); (b) genuine absence of relationship; or (c) other unmeasured factors dominating. Failing to investigate this is a missed opportunity. (3) **Robustness checks incomplete:** Pre-registered checks (excluding March 2020 emergency cuts, excluding March 2023 hike, using XLF benchmark) are noted in known issues as not fully reported. Cannot assess robustness to alternative specifications. (4) **Pre-announcement drift:** Not examined. Literature (Lucca & Moench 2015) documents 48 bps drift in 24 hours before announcement; if banks exhibit similar drift, CAR over [−1, +1] may confound drift with announcement effect. (5) **Multicollinearity risk:** On announcement days, prices may move in anticipation of yield changes, creating endogeneity in H2. No discussion of this.

**Writing: 7/10**

*Rationale:* Strengths: (1) Abstract and introduction clearly motivate the research question; (2) institutional context section well-explains Fed transmission channels; (3) methods section is precise and reproducible; (4) results section appropriately reports null findings without overselling—e.g., "not significantly different from zero" and "fail to reject H₀" used correctly; (5) discussion thoughtfully interprets null results through three lenses (market efficiency, offsetting forces, statistical noise); (6) transparent disclosure statement about machine-generated analysis under researcher supervision is exemplary. Weaknesses: (1) Some redundancy—mean CARs and corresponding statistics reported multiple times across abstract, results, and conclusion; (2) tables referenced (tables/main.tex, tables/h2_results.tex) are not fully displayed in provided text—impossible to verify all numbers; (3) some in-line result annotations (e.g., HTML/JSON source comments) suggest document is auto-generated from structured data, reducing clarity of lineage; (4) discussion could more explicitly address why secondary [0,+5] result is exploratory and deserves future investigation.

**Literature: 7/10**

*Rationale:* Strengths: (1) comprehensive separate literature review covering foundational works (MacKinlay 1997; Campbell, Lo, MacKinlay 1997) and recent advances; (2) good coverage of monetary policy transmission channels (net interest margin, credit risk, duration, risk premia, financial stability); (3) bank heterogeneity literature well-represented (size effects, capitalization constraints post-2008); (4) historical context of 2015–2025 period (normalization, pandemic, rapid tightening) appropriately positioned. Weaknesses: (1) limited integration of literature review into main paper—discussion of transmission mechanisms mostly delegated to separate document; (2) could better engage with literature on forward guidance and communication channels; (3) no discussion of recent work on "Fed put" and risk-premia expectations (e.g., Cieslak et al. on monetary policy surprises and asset prices); (4) financial stability channel cited but underexplored given March 2023 banking stress overlap.

---

## MAJOR CONCERNS

1. **Surprise Measurement is Fundamentally Flawed**
   - The paper proxies Fed policy surprise with same-day DGS2 change in basis points, but Treasury yields are endogenous to many factors beyond Fed policy.
   - Proper identification requires ex-ante market expectations (e.g., Fed Funds futures traded before announcement) compared to actual policy.
   - Without this, H2 regression conflates Fed policy effect with yield-curve-shift effects.
   - Literature standard (Bernanke & Kuttner 2005; Kuttner 2001) uses intraday futures data; this paper does not.
   - **Actionable path:** Obtain Fed Funds futures contract prices from CME FedWatch database or academic sources; recompute ΔDGS2 as post-announcement minus pre-announcement yield move.

2. **H2 Explanatory Power is Essentially Zero**
   - R²=0.0053 means DGS2 surprise explains <1% of variation in abnormal returns.
   - Paper states this result is "not significant" but does not explain the absence of predictive power.
   - Possible interpretations: (a) surprise is mismeasured (likely, given endogeneity); (b) announcement-day returns are dominated by noise unrelated to yield changes; (c) bank stock reactions operate through channels unrelated to same-day yield moves (e.g., forward guidance about future rate path, financial stability signaling).
   - Paper does not explore or test these alternatives.
   - **Actionable path:** Investigate why yield surprise has no power. Test alternative surprise measures (e.g., change in 5-year rate, change in yield-curve slope). Examine whether pre-announcement expectations (from Fed Funds futures or economist surveys) predict abnormal returns better.

3. **Incomplete Robustness Checks**
   - Pre-registered robustness checks (excluding March 2020 emergency cuts, excluding March 2023 hike, using XLF benchmark) are noted in known issues as not fully reported in the paper.
   - Robustness tables are mentioned to exist but are not integrated into main text.
   - Cannot assess whether results are robust to: (a) excluding crisis/emergency periods; (b) using sector-level rather than market-level benchmark; (c) alternative samples.
   - **Actionable path:** Include all pre-registered robustness checks in main paper or supplementary appendix. Report any changes to point estimates and statistical significance. Discuss reasons for any sensitivity.

4. **Secondary [0,+5] Result Not Pre-Registered; Risk of Post-Hoc Window Selection**
   - Pooled mean CAR of −1.47% (p=0.022) over [0,+5] is significant and interesting.
   - But this window was not pre-registered; only the [-1,+1] window was.
   - Paper acknowledges this ("not pre-registered") but still emphasizes the finding in results and abstract.
   - Risk: If [0,+5] window was chosen post-hoc to capture a significant result, this is p-hacking.
   - The paper does not report this result stratified by rate direction in main text (though H1b in results mentions it separately).
   - **Actionable path:** Either pre-register the [0,+5] window and report it as confirmatory, or explicitly label it as exploratory and discuss in a separate section with appropriate caveats about inference.

5. **Sample Size and Statistical Power Limitations**
   - With n=20 hikes and n=11 cuts, and cross-sectional SD ≈2.5–3%, power to detect economically meaningful effects is limited.
   - Mean CAR for hikes of −1.06% with t-stat of −1.998 is marginally non-significant at 5% (p=0.0603).
   - No post-hoc power analysis or calculation of minimum detectable effect size.
   - **Actionable path:** Report post-hoc power analysis. Compute the effect size this sample can detect at 80% power. Discuss whether null result reflects true absence of effect or lack of statistical power.

---

## MINOR CONCERNS

1. **Confounding Events in Crisis Periods**
   - March 2020 emergency cuts coincide with market-wide crash (VIX spiking, equity indices down >10% that day). Difficult to isolate Fed effect from systemic risk.
   - March 2023 hike coincides with banking stress (SVB failure on March 10; FOMC met March 22). Risk-sentiment effects may dominate.
   - Pre-registered robustness excluding these should be reported to show whether effect is robust.

2. **Market Model May Be Too Simple**
   - Bank stocks (particularly smaller banks) exhibit exposure to size (SMB) and value (HML) factors.
   - Using Fama-French three-factor model might reduce residual variance and improve precision.
   - Paper does not explore this alternative.

3. **Unbalanced Sample by Rate Direction**
   - 20 hikes vs. 11 cuts: 65/35 split.
   - Sub-period composition: 2015–2018 (mostly hikes, post-crisis normalization), 2020 (emergency cuts, pandemic), 2022–2023 (rapid hikes, tightening cycle), 2024–2025 (renewed cuts, easing cycle).
   - No sub-period analysis to isolate whether effects differ across regimes.
   - Suggests heterogeneity that aggregate analysis masks.

4. **Pre-Announcement Drift Not Examined**
   - Literature (Lucca & Moench 2015) documents 48 bps drift in 24 hours before scheduled FOMC announcements.
   - If banks show similar drift, this contaminates the CAR interpretation in [−1, +1] window.
   - Could test whether drift is present (regress returns on "days until announcement" over [−30, −1]).

5. **Treasury Yield Endogeneity in H2**
   - DGS2 rises partly because markets expect tighter policy.
   - But banks' equity prices may also rise in anticipation of policy, creating reverse causality or simultaneity.
   - Proper identification requires instrumenting yield surprise with something exogenous (e.g., Fed Funds futures surprise from the intraday move).

6. **Interpretation of "Null" Results**
   - Paper offers three interpretations: market efficiency, offsetting forces, noise.
   - No direct test of these. For example:
     - Market efficiency could be tested by examining whether abnormal returns predict future macro variables.
     - Offsetting forces could be tested by examining heterogeneity across bank types (high-NIM exposure vs. low-NIM exposure).
     - Noise/power hypothesis could be tested via post-hoc power calculation.
   - More granular analysis would strengthen the discussion.

---

## POSITIVE ASPECTS

1. **Transparent and Ethical Disclosure**
   - Clear statement that analysis is machine-generated under researcher supervision.
   - Explicit note that abnormal returns were computed on 29 Sep 2026 at 01:23 UTC (eight minutes after design approval, before pre-registration frozen).
   - Computation performed blind (results not reviewed before pre-registration).
   - This level of transparency and ethical practice is exemplary and rare.

2. **Event Identification is Clean and Exogenous**
   - 31 FOMC announcements identified via published calendar.
   - Announcement dates are exogenous to bank performance (Fed does not choose dates based on bank health).
   - Timing is appropriate for causal inference via event study.

3. **Null Results Reported Plainly**
   - Paper does not oversell or spin null findings.
   - Uses appropriate language: "not significantly different from zero," "fail to reject H₀."
   - Acknowledges alternative interpretations of null results (efficiency, offsetting forces, noise).
   - This is a gold standard in reporting.

4. **Standard and Sound Methodology**
   - Market model is workhorse in event-study literature.
   - Specification choices (238-trading-day window, [-250, -12] estimation window, non-overlapping events) are reasonable and well-justified.
   - Cross-sectional inference is appropriate for N=31 events.
   - Statistical inference (t-tests, HC1 standard errors) is correct.

5. **Data Reproducibility and Openness**
   - All data from public sources (FRED, Yahoo Finance).
   - No proprietary or restricted data.
   - Fully reproducible by independent researchers.
   - Data loading and handling documented (e.g., FRED yield series reloaded by researcher after initial failure).

6. **Comprehensive Contextual Literature Review**
   - Separate literature review spans monetary policy transmission, event-study methods, Fed communication, bank heterogeneity.
   - Covers both foundational (MacKinlay 1997) and recent work.
   - Appropriate citations and balanced discussion of multiple transmission channels.

7. **Discussion of Limitations is Thorough**
   - Paper explicitly acknowledges statistical power constraints, confounding events, and alternative interpretations.
   - Acknowledges that longer event windows may be required to capture full effect.
   - Suggests future research directions (longer windows, bank-level heterogeneity, dynamic effects).

---

## OVERALL SCORE: 5.9/10

**Scoring Breakdown:**
- Contribution (25%): 5/10 → 1.25
- Identification (25%): 5.5/10 → 1.375
- Empirics (20%): 6/10 → 1.20
- Writing (15%): 7/10 → 1.05
- Literature (15%): 7/10 → 1.05
- **Weighted Total: 5.9/10**

**Interpretation of Score:**
This paper demonstrates competent event-study methodology with transparent reporting and ethical disclosure. However, it suffers from fundamental identification problems (surprise measurement), incomplete robustness, and null results that limit scientific contribution. The work is above the "reject" threshold because methodology is sound, data reproducible, and null results properly reported. However, it falls short of "minor revision" because the surprise measurement issue is substantive, robustness checks are incomplete, and the exploratory secondary finding raises p-hacking concerns. The paper would benefit from major revisions addressing the surprise measurement, completing robustness checks, and deeper investigation of why H2 yields no explanatory power.

## RECOMMENDATION: Major Revision

**Required revisions for acceptability:**

1. **Surprise Measurement** (Critical)
   - Obtain Fed Funds futures data (CME, academic databases).
   - Recompute surprise as post-announcement minus pre-announcement futures rate.
   - Re-estimate H2 with properly measured surprise.

2. **Complete Robustness Checks** (Critical)
   - Integrate all pre-registered robustness analyses (March 2020 exclusion, March 2023 exclusion, XLF benchmark) into main paper.
   - Report whether results are robust to these specifications.

3. **Investigate Low H2 Explanatory Power** (Major)
   - Test alternative surprise measures (5-year yield, yield-curve slope, Fed Funds futures).
   - Examine whether announcement-day effects operate through channels other than same-day yields.
   - Consider sub-period or heterogeneity analysis.

4. **Secondary Window Analysis** (Major)
   - Either pre-register the [0,+5] window and present results as confirmatory, or relabel as exploratory.
   - Discuss why longer window shows effect while narrow window does not (and what mechanisms this implies).
   - Stratify by rate direction for [0,+5] window in main results table.

5. **Statistical Power Analysis** (Minor)
   - Compute post-hoc power and minimum detectable effect sizes.
   - Discuss whether null results reflect true absence of effect or sample size limitations.

6. **Robustness to Model Specification** (Minor)
   - Report results using Fama-French three-factor model as an alternative to market model.
   - Discuss whether factor model reduces unexplained variance.

---

OVERALL SCORE: 5.9/10
RECOMMENDATION: Major Revision
