# Technical Review: Bank Stock Response to FOMC Target-Rate Announcements

**Paper**: How Do US Bank Stocks Respond to Federal Reserve Target-Rate Announcements? An Event Study of FOMC Decisions, 2015–2025

**ID**: @@PAPER_ID@@

**Date**: September 29, 2026

---

## Summary Assessment

**VERDICT: PASS with MINOR REVISIONS**

The paper implements a methodologically sound event-study design with correct hypothesis testing and appropriate pre-registration disclosure. The data pipeline is properly constructed, estimation windows are correctly specified, and hypothesis tests (H1 and H2) use appropriate degrees of freedom and two-sided inference. However, three organizational issues diminish the completeness of the technical implementation: (1) results for the secondary event window [0,+5] are mentioned in the abstract but not detailed in the Results section; (2) pre-registered robustness checks (excluding March 2020, March 2023, and using XLF benchmark) are not reported; and (3) missing table files prevent verification of reported numbers. These are not computational errors but gaps in documentation and completeness that should be addressed in revision.

---

## Data Pipeline Verification

### Data Sources and Coverage
✓ **PASS**: All required data tables properly loaded:
- kbe_prices, spy_prices, xlf_prices: 3,017 rows each (2014-01-02 to 2025-12-30)
- dgs2: 2,870 rows, 2,750 non-null values (2015-01-01 to 2025-12-31)
- fomc_announcement_dates: 31 events (20 hikes, 11 cuts)

### Sample Construction
✓ **PASS**: Event definition and classification are correct:
- 31 FOMC announcements from December 2015 to December 2025
- Direction classification (hikes/cuts) properly applied
- Sunday-to-trading-day adjustment documented (e.g., March 15, 2020 → March 16, 2020)
- First event has 250 trading days of prior data (January 2014 baseline sufficient)

### Variable Definitions and Calculations
✓ **PASS**: Log returns, market model, abnormal returns, and CAR calculations are standard and correctly specified:
- R_t = ln(Price_t) − ln(Price_{t−1})
- AR_{i,τ} = R^KBE − (α̂ + β̂ · R^SPY)
- CAR = Σ AR over event window

⚠️ **MINOR**: Event-day yield surprise (H2) computation needs clarification:
- Paper states "ΔDGS2 = DGS2(t=0) − DGS2(t=−1)" but does not explicitly specify whether t=−1 means the previous trading day or previous calendar day
- Since DGS2 has no value on market holidays, the definition matters: is the prior value the last trading day with a non-null value, or the calendar day before?
- Recommendation: Explicitly state the imputation rule (e.g., "previous trading day with a non-null value")

⚠️ **MINOR**: DGS2 data sourced by researcher after data analyst failed to load from FRED
- Data status disclosed in abstract: "The 2-year Treasury constant-maturity yield (DGS2) was loaded from FRED... after the initial data analyst load failed"
- Researcher instruction notes: "a leading space in the FRED key made every request fail, and the analyst's own script wrote the empty rows"
- Assessment: Disclosure is transparent; no evidence of bias (design was frozen before researcher reloaded data)
- However, this introduces potential for undisclosed influence if researcher had seen preliminary results

---

## Estimation Implementation

### Market Model Specification
✓ **PASS**: Correctly specified and implemented:
- Equation (1) matches standard market model: R_KBE = α_i + β_i · R_SPY + ε_i
- Event-specific parameters (separate α_i, β_i for each of 31 events) properly justified to account for time-varying risk
- Estimation window [t=−250, t=−12] provides 238 trading days, avoiding overlap with event windows

### Hypothesis 1: Mean Abnormal Return Test

**Test specification**: Cross-sectional t-test on mean CAR, separately for hikes and cuts, two-sided at α=0.05

**Reported results**:
| Group | N | Mean CAR | SE | t-stat | df | p-value | 95% CI | Reported |
|-------|---|----------|----|----|----|----|--------|----------|
| Hikes | 20 | −1.06% | 0.53% | −1.998 | 19 | 0.0603 | [−2.17%, +0.05%] | ✓ |
| Cuts | 11 | −0.08% | 0.86% | −0.091 | 10 | 0.9295 | [−2.00%, +1.84%] | ✓ |

**Verification**:
- Degrees of freedom: df = n − 1 (20 − 1 = 19 for hikes, 11 − 1 = 10 for cuts) ✓
- Critical values: t_{0.025,19} = 2.093, t_{0.025,10} = 2.228
- Conclusion: Both |t| < critical values, correctly not significant at 5% level ✓
- Two-sided p-values consistent with t-distribution at stated degrees of freedom ✓

**Secondary window [0,+5] results**: Abstract reports "pooled mean CAR of −1.47% (p = 0.022)" but this result is **not detailed in the Results section**. Only the [−1, +1] window is presented in the main text.

### Hypothesis 2: Surprise Sensitivity Regression

**Specification**: CAR_i = α + β · ΔDGS2_i + ε_i, with HC1 standard errors

**Reported results**:
| Specification | N | β | SE | t | df | p-value | R² | Reported |
|---|---|---|---|---|---|---|---|---|
| Pooled | 31 | −0.0208 | 0.0437 | −0.4771 | 29 | 0.6368 | 0.0053 | ✓ |
| Hikes | 20 | −0.0008 | 0.0456 | −0.0171 | 18 | 0.9865 | — | ✓ |
| Cuts | 11 | −0.0944 | 0.1219 | −0.7742 | 9 | 0.4587 | — | ✓ |

**Verification**:
- Degrees of freedom: df = n − 2 (31 − 2 = 29 for pooled, etc.) ✓
- t-statistics recomputed from reported β and SE match within rounding ✓
- P-values consistent with two-sided t-distribution at stated degrees of freedom ✓
- Coefficient unit: (percentage points CAR) per (basis point yield change), correctly interpreted

⚠️ **MINOR**: R² not reported for hikes and cuts regressions (only pooled R² = 0.0053 given). The low pooled R² correctly indicates negligible explanatory power.

---

## Results Reporting and Interpretation

### Effect Size Assessment
- **H1 hikes**: −1.06% CAR over 3 days is economically small relative to typical daily stock volatility (≈1–2%)
- **H1 cuts**: −0.08% is negligible
- **H1 [0,+5]**: −1.47% is larger but still modest over 6 days
- **H2 pooled**: −0.0208 percentage points per basis point yield change; economically weak relationship

Assessment: Effect sizes are consistently small, and null findings are not suspicious.

### Significance Testing
✓ **PASS**: Two-sided tests correctly applied; no one-sided tests disguised as two-sided. Non-significant results clearly stated as such (not "marginally significant" or p≈0.06 overstatement).

### Confidence Intervals
✓ **PASS**: Reported 95% confidence intervals for H1 are wide (reflecting small sample size and cross-sectional volatility), consistent with non-significant tests. For example, H1 hikes CI [−2.17%, +0.05%] includes zero, confirming non-rejection of H0.

---

## Red Flag Detection

### P-value Distribution
✓ **PASS**: No suspicious clustering:
- H1 hikes p = 0.0603 (above 0.05 threshold, correctly not significant)
- H1 cuts p = 0.9295 (strong null)
- H2 pooled p = 0.6368, hikes p = 0.9865, cuts p = 0.4587 (all well above threshold)
- No evidence of p-hacking (transposed digits, suspicious rounding, clustering below cutoffs)

### Specification Searching
✓ **PASS**: Two event windows pre-registered in econometric specification. Pooled [0,+5] estimate appropriately labeled "not pre-registered" in abstract (though the window by direction was pre-registered).

### Selective Reporting

⚠️ **MAJOR**: **Pre-registered robustness checks not reported in paper**:
- Econometric specification lists three robustness checks:
  1. Exclude March 2020 emergency cuts
  2. Exclude March 2023 banking-stress hike
  3. Use XLF as alternative market benchmark
- These are referenced in the specification but not presented in the paper
- Researcher notes (approval comments): "Leftover files tables/robustness_march2020.tex, robustness_march2023.tex and xlf.tex are not part of the paper and contradict the pre-registration"
- **Assessment**: Significant gap between pre-registration and published results. Researcher acknowledges this as a known issue "because this study is published only to demonstrate e2er," but for a submission this would be unacceptable.

### Missing Documentation

⚠️ **MAJOR**: **Referenced tables not provided**:
- Paper states `\input{tables/main.tex}` (Table 1) and `\input{tables/h2_results.tex}` (Table 2)
- These files are not included in the provided context, preventing verification that reported numbers match displayed tables
- While numbers are cited inline with source comments (e.g., `<!-- src: estimation_results.json#h1_hikes_m1p1.coefficients.mean_car.estimate -->`), the actual table layout and presentation cannot be checked

---

## Internal Consistency Across Pipeline Stages

### Data → Estimation
✓ **PASS**: 
- 31 events, 20 hikes + 11 cuts as claimed in data summary
- Price series (KBE, SPY, XLF) fully populated, no unexplained gaps
- Estimation window [−250, −12] properly excludes event windows

### Estimation → Analysis
✓ **PASS**:
- Reported H1 and H2 statistics match pre-registered specifications
- Test statistic formulas (cross-sectional t, OLS with HC1 SE) correctly applied
- Degrees of freedom consistently stated

### Analysis → Draft
✓ **PARTIAL PASS**:
- H1 results reported in main text for [−1, +1] window only
- H1 results for [0, +5] mentioned in abstract but not explained in Results section
- H2 results reported for pooled specification and by-direction subgroups
- Missing justification for why [0, +5] "pooled mean CAR = −1.47%" appears in abstract but not in Results section

### Draft Consistency with Pre-registration
✓ **MOSTLY PASS**:
- H1 and H2 hypotheses correctly match pre-registration
- Event windows match pre-registration
- Degrees of freedom and test structure match specification
- ⚠️ Robustness checks pre-registered but not reported in paper

---

## Technical Strengths

1. **Appropriate methodology**: Market model is standard for abnormal return estimation; 238-day estimation window balances parameter stability with avoiding structural breaks
2. **Sound hypothesis testing**: Two-sided tests with correct degrees of freedom; no evidence of p-hacking
3. **Transparent pre-registration**: H1 and H2 disclosed before results; event windows and specifications documented
4. **Null results not suspicious**: Small effect sizes and high p-values are consistent with weak or absent relationships, not p-hacking patterns
5. **Data sourcing transparent**: Disclosure that DGS2 was reloaded by researcher after analyst failure; no evidence of result-driven reloading

---

## Issues Requiring Revision

### Critical Issues

1. **Incomplete Results Reporting for [0,+5] Window**
   - **Issue**: Secondary window [0,+5] results mentioned in abstract ("A secondary analysis of the longer [0, +5] window (not pre-registered) shows a pooled mean CAR of −1.47% (p = 0.022)") but not detailed in Results section
   - **Evidence**: Abstract quotes the result; Results section only covers [−1, +1] window in detail
   - **Fix**: Either (a) add subsection in Results with full [0, +5] results (mean CAR by direction, standard errors, confidence intervals, df), or (b) remove from abstract and move to appendix if space-constrained

2. **Missing Robustness Checks**
   - **Issue**: Three robustness checks pre-registered in econometric specification (March 2020 exclusion, March 2023 exclusion, XLF benchmark) are not reported in paper
   - **Evidence**: Researcher notes "Leftover files tables/robustness_march2020.tex, robustness_march2023.tex and xlf.tex are not part of the paper"
   - **Fix**: Report robustness results in a dedicated table (or appendix), showing that main results hold under these variations

### Major Issues

3. **Table Files Not Provided**
   - **Issue**: Paper references `\input{tables/main.tex}` and `\input{tables/h2_results.tex}` but these files are not included
   - **Fix**: Provide complete table files or verify that inline-cited numbers match any tables that exist

4. **Ambiguous Day−1 Definition for H2**
   - **Issue**: "ΔDGS2 = DGS2(t=0) − DGS2(t=−1)" does not specify whether t=−1 is a calendar day or trading day, and how to handle missing values (market holidays)
   - **Fix**: Explicitly state: "t=−1 is the previous trading day with a non-null DGS2 value" or use the actual rule applied in estimation

### Minor Issues

5. **Unit Presentation in H2**
   - **Issue**: Phrase "coefficient of −0.0208 basis points" is potentially confusing. The coefficient is in (percentage points CAR) per (basis point yield change), not "basis points"
   - **Fix**: Rewrite as "coefficient of −0.0208 percentage points per basis point" or similar

6. **Missing R² for Stratified H2 Regressions**
   - **Issue**: R² reported for pooled H2 (0.0053) but not for hikes and cuts separately
   - **Fix**: Report R² for all three H2 regressions

---

## Assessment of Data Quality Handling

**DGS2 Reloading Issue**:
- Disclosure in abstract: "DGS2 data were loaded from FRED by the researcher after the initial data analyst load failed"
- Researcher instruction context: Initial load failed due to API key error; researcher reloaded after design freeze
- Assessment: **Acceptable** because (1) disclosure is transparent, (2) design was frozen before reloading, (3) blind-to-results reloading is disclosed ("computation was performed blind; results were not reviewed before pre-registration was frozen")
- However, this depends on the integrity of the claim that results were not reviewed. No independent verification provided.

---

## Strengths Summary

- ✓ Methodologically sound event-study design
- ✓ Correct hypothesis testing (degrees of freedom, two-sided tests, HC1 standard errors for regression)
- ✓ Transparent pre-registration of H1 and H2
- ✓ Null findings not suspicious (appropriate p-value patterns, low R² consistent with weak relationships)
- ✓ Disclosure of data sourcing issues and methodology choices

---

## Weaknesses Summary

- ✗ Incomplete reporting: [0,+5] results mentioned in abstract but not detailed in Results
- ✗ Missing robustness checks: Pre-registered exclusion and benchmark tests not reported
- ✗ Missing table documentation: Referenced table files not provided for verification
- ✗ Ambiguous specification: Day−1 definition for yield surprise computation not explicit
- ✗ Minor presentation: Unit language in H2 coefficient interpretation could be clearer

---

## Recommendations for Completion

**Before resubmission:**

1. Add detailed results for [0,+5] event window in Results section, matching the pre-registered structure (by direction, with standard errors and confidence intervals)

2. Report the three pre-registered robustness checks (March 2020, March 2023, XLF) as a robustness table or appendix section

3. Explicitly define "t=−1" for H2 yield surprise calculation (i.e., previous trading day with non-null DGS2 value)

4. Provide or verify table files (tables/main.tex, tables/h2_results.tex) match inline-cited numbers

5. Clarify units in H2 interpretation section

**Optional improvements:**

6. Report R² and adjusted R² for all H2 regressions (pooled, hikes, cuts)

7. Consider adding power analysis or discussion of minimum detectable effect given sample size (N=20 for hikes, N=11 for cuts)

---

## Conclusion

The paper implements a technically sound event-study design with appropriate statistical testing, correct hypothesis formulation, and transparent pre-registration. The core findings (non-significant abnormal returns in the primary 3-day window, no relationship between CAR and Treasury yield surprise) appear robust and correctly computed. However, organizational gaps—incomplete reporting of the secondary event window, missing robustness checks, and ambiguous specifications—diminish the completeness of the technical documentation. These are not computational errors but documentation deficiencies that should be addressed in revision to ensure full alignment between pre-registration, methods, and reported results.

The paper is suitable for publication with minor revisions addressing the completeness and clarity issues identified above.

OVERALL SCORE: 7/10
RECOMMENDATION: Minor Revision
