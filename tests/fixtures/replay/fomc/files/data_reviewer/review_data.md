# Data Review: Bank Stock Response to FOMC Target-Rate Announcements
## How do US bank stocks respond to changes in the Federal Reserve's target rate? An event study of FOMC target-rate changes, 2015–2025

**Reviewer:** Data Quality Assessment Specialist  
**Review Date:** 2026-09-29  
**Paper ID:** @@PAPER_ID@@

---

## EXECUTIVE SUMMARY

This data review assesses the data sources, construction, and quality for an event study of 31 FOMC target-rate announcements (2015–2025) examining abnormal returns in US bank stocks (KBE) relative to the S&P 500 (SPY). 

**Overall Assessment:** Data quality is **good**. Sources are reliable (FRED, Yahoo Finance), sample construction is transparent, and the event-level analysis is properly specified. However, the analysis has **three material issues**: (1) pre-registered robustness checks are not reported in the paper; (2) some methodological choices lack transparent documentation in the results; (3) a data-loading process failure required researcher intervention to complete the analysis.

**Recommendation:** MINOR REVISION with specific documentation improvements.

---

## 1. SOURCE DOCUMENTATION

### Strengths
- ✓ **FOMC announcement dates:** Clearly identified source (researcher-assembled table from Federal Reserve Board historical announcements, Dec 2015 – Dec 2025). The table includes announcement dates, rate-change magnitudes, and classification (hike/cut).
- ✓ **KBE, SPY, XLF prices:** Source clearly stated (Yahoo Finance). Ticker symbols unambiguous. Daily frequency explicitly documented.
- ✓ **Interest rate data:** FRED series identified by official ID (DGS2 for 2-year Treasury yield, DFEDTARU for Fed Funds target). Persistent identifiers with access via FRED API.
- ✓ **Data vintage:** Time period clearly specified (daily data from 2014-01-02 to 2025-12-31, with event sample 2015-12-16 to 2025-12-10).
- ✓ **Access conditions:** All data are from public sources (open-access APIs). No proprietary data or restricted-access datasets.
- ✓ **Unit of observation:** Event-level analysis (31 FOMC announcements) with daily sub-unit (trading days).

### Issues
- ⚠ **Data loading process failure:** The DGS2 table (2-year Treasury yield) was loaded by the researcher after the data analyst's attempt failed three times. Root cause: FRED API key had a leading space. The researcher ran: `e2er-data fred series --series-id DGS2 --start 2015-01-01 --end 2025-12-31 --paper-id [id] --table dgs2`. The paper's data section should explicitly state this, but it only mentions "loaded...by the researcher after the initial data analyst load failed." While the issue is resolved and transparent, it suggests process gaps in automated data pipelines.
- ⚠ **Paper does not specify:** The definition of "day 0 change" in DGS2 (computed against "previous trading day with a value") is documented in code instructions but not stated explicitly in the Methods section.

---

## 2. SAMPLE CONSTRUCTION

### Strengths
- ✓ **Sample transparency:** The 31 FOMC events are enumerated by announcement date (2015-12-16 to 2025-12-10). Classification by direction is explicit: 20 rate hikes, 11 rate cuts (totaling 31; no holds included in sample). This is stated clearly in the paper.
- ✓ **Event date definition:** Day t=0 is defined as the FOMC announcement date or, if the announcement falls on a weekend/non-trading day (e.g., Sunday 2020-03-15), the next trading day (2020-03-16). This handling is proper and stated in the methods.
- ✓ **Event window specification:** Two windows clearly defined:
  - **Primary:** [t=-1, t=+1] (3 trading days centered on announcement)
  - **Secondary:** [t=0, t=+5] (6 trading days post-announcement)
- ✓ **Estimation window:** Specified as [t=-250, t=-12] trading days before each event. This is 238 trading days (~1 year) with a 12-day gap before the event window. The gap ensures no contamination from pre-announcement leakage or overlapping event windows from prior events.
- ✓ **Event independence:** The 12-day buffer and event-specific market model estimation are designed to prevent spillover between events. No events are dropped due to overlapping windows (implicit check not reported, but plausible given 31 events over 10 years).
- ✓ **Sample size:** 31 events is reasonable for an event study at the aggregate level. Power is not explicitly analyzed, but the sample is large enough to detect economically meaningful effects given typical cross-sectional variation in stock returns.

### Issues
- ⚠ **No explicit confirmation of non-overlapping windows:** The paper does not verify that no two events' [t=-1, t=+1] windows overlap with [t=-250, t=-12] estimation windows for any other event. With 31 events over 10 years (~3 per year), this is unlikely to be a problem, but should be confirmed.
- ⚠ **Aggregate measure hides heterogeneity:** KBE is a value-weighted basket of bank stocks, not individual bank returns. Heterogeneous responses across bank sizes, business models, and geographies are masked. The paper acknowledges this and plans robustness checks with XLF, but these are not reported (see Section 10 below).
- ⚠ **No exclusion justification:** The paper excludes rate-hold announcements (if any exist in the sample) but does not explicitly state that only hikes and cuts are analyzed. This is a minor clarity issue.

---

## 3. MISSING VALUES

### Data Availability
- **KBE prices:** 3,017 observations (2014-01-02 to 2025-12-30), no missing values in trading-day records.
- **SPY prices:** 3,017 observations, no missing values.
- **XLF prices:** 3,017 observations, no missing values.
- **DGS2 (2-year Treasury yield):** 2,870 rows in database; 2,750 with non-null values (2015-01-01 to 2025-12-31). Missing values correspond to market holidays (FRED reports no yield on non-trading days). This is correct and expected.
- **DFEDTARU (Fed Funds target):** 2,765 rows, fully populated.

### Strengths
- ✓ **Extent of missing data reported:** Data summary clearly states "2,750 non-null values" for DGS2 out of 2,870 rows.
- ✓ **Pattern of missingness documented:** Missing DGS2 values correspond to non-trading days (weekends, holidays), which is expected and properly handled.
- ✓ **Treatment strategy:** For H2 regression, the day-0 DGS2 change (Δdgs2₀) is computed against the "previous trading day with a value." This is correct and avoids artificial gaps.
- ✓ **No spurious missing-value recoding:** No evidence that missing values are miscoded as -9, 0, or 999.

### Minor Issue
- ⚠ **Not stated in paper:** The paper should explicitly document how DGS2 changes are computed when day -1 is a non-trading day (i.e., which prior trading day is the denominator). This is correct in implementation but absent from the Results section.

---

## 4. VARIABLE DEFINITIONS

### Market Model Specification
The paper defines the abnormal return model clearly:

$$R_{i,\tau}^{\text{KBE}} = \alpha_i + \beta_i \cdot R_{i,\tau}^{\text{SPY}} + \varepsilon_{i,\tau}$$

- ✓ **OLS regression:** Estimated separately for each event i over estimation window [t=-250, t=-12].
- ✓ **Log returns:** Computed as ln(close_t) - ln(close_{t-1}), appropriate for multi-day cumulative returns.
- ✓ **Abnormal return definition:** AR_{i,τ} = R_KBE,τ - (α̂_i + β̂_i · R_SPY,τ). Clear and standard.
- ✓ **CAR definition:** Sum of daily abnormal returns over event window. Specified for two windows: [t=-1, t=+1] and [t=0, t=+5].

### Explanatory Variables (H2 Regression)
- **ΔDGS2₀:** Change in 2-year Treasury yield on announcement day (t=0), measured in basis points (FRED reports percent; converted to bps by multiplying by 100). This is explicit in econometric specification but not emphasized in the Results section.

### Strengths
- ✓ **Outcome variable:** Cumulative abnormal return (CAR) is unambiguously defined.
- ✓ **Constructed variables:** Step-by-step construction documented (market model → abnormal return → CAR).
- ✓ **Timing:** Clear specification of t=0 and time windows.
- ✓ **Units:** CAR reported in percentages, yields in basis points.

### Issues
- ⚠ **Transformation documentation:** The conversion of FRED DGS2 (reported in %) to basis points is not stated in the main paper; it appears only in econometric specification notes.
- ⚠ **No discussion of log returns vs. simple returns:** The paper uses log returns but does not justify or discuss sensitivity to this choice for a 3-day CAR window.
- ⚠ **Market beta stability:** The market model assumes constant α_i and β_i over the event window. No discussion of time-varying beta or structural breaks.

---

## 5. OUTLIERS

### Assessment
- ⚠ **No explicit outlier analysis:** The paper does not report distributions (histograms, box plots) of CARs or abnormal returns.
- ⚠ **No leverage diagnostics:** Cook's distance, DFBETAS, or leave-one-out analysis are not reported.

### Observed Values
From the abstract and results tables:
- **H1 (Hikes):** Mean CAR = -1.06% (SD ≈ 2.1% implied from SE 0.53% and n=20)
- **H1 (Cuts):** Mean CAR = -0.08% (SD ≈ 2.7% implied from SE 0.86% and n=11)
- **Range implied:** CARs appear to fall within [-4%, +3%] plausibly (no extreme values reported)

### Concerns
- ⚠ **Vulnerability to single events:** With only 31 events and CARs showing substantial variation (SD ~2-3%), a single outlier (e.g., March 2020 emergency cuts) could dominate results. The paper excludes March 2020 and March 2023 in robustness checks, but these checks are **not reported** (see Section 10).
- ⚠ **No explicit test:** The paper does not report results with/without specific high-leverage events.

### Positive Note
- ✓ **Plausible magnitude:** CARs in the [-2%, +2%] range are economically reasonable for a 3-day event window around a policy announcement, consistent with prior literature (Bernanke & Kuttner 2005).

---

## 6. MEASUREMENT QUALITY

### Strengths
- ✓ **Reliable data sources:** Yahoo Finance (widely used, high quality) and FRED (official Federal Reserve, no measurement error in official rates).
- ✓ **High-frequency data:** Daily prices and yields reduce measurement error compared to lower-frequency data.
- ✓ **No proxy variables:** The paper uses observed prices and yields, not constructed proxies.
- ✓ **Measurement transparency:** The construction of abnormal returns from the market model is standard and well-documented.

### Potential Limitations (Acknowledged)
- ⚠ **KBE is an aggregate:** The KBE ETF returns reflect a value-weighted basket of bank stocks. Measurement error from aggregation masks heterogeneous responses. The paper acknowledges this strategy (using an ETF vs. individual banks or banking indices like FDIC or Federal Reserve data) but does not discuss the implications.
- ⚠ **No individual bank balance-sheet data:** The paper does not match bank-specific characteristics (capital ratios, duration, deposit composition) to abnormal returns. This limits interpretation of which banks drive the results.
- ⚠ **Trading volume and liquidity:** No discussion of whether KBE is actively traded or whether any estimation days had low volume/wide spreads that could introduce measurement noise.

---

## 7. TIME AND CURRENCY

### Strengths
- ✓ **Inflation adjustment:** Not needed for a short-term event study (3-6 day windows).
- ✓ **Currency:** All values in USD (implicit, standard for US data).
- ✓ **Date format:** Unambiguous (YYYY-MM-DD format used throughout).
- ✓ **Time period consistency:** All data span 2015–2025 or earlier (2014-01-02 start for estimation window).
- ✓ **Basis point conversion:** FRED DGS2 converted from percent to basis points (multiply by 100). This is correct.

### Minor Issue
- ⚠ **Seasonal adjustment:** Not applicable (FOMC announcements are not seasonal, and the event window is short).

---

## 8. PANEL DATA & 9. CROSS-SECTIONAL CHECKS

**Not applicable** to this analysis:
- This is an event study (aggregated across events), not a panel dataset with units and periods.
- FOMC announcements are a time series of events, not a sample survey.

---

## 10. DATA INTEGRITY & REPLICATION

### Critical Issue: Pre-Registered Robustness Checks Not Reported

The paper states in Section 4 that three robustness specifications are planned:
1. **Alternative Benchmark (XLF):** Repeat H1 and H2 tests using XLF as market proxy.
2. **Excluding March 2020 Emergency Cuts:** Re-run H1 and H2 on remaining 29 events (20 hikes, 9 cuts).
3. **Excluding March 2023 Hike:** Re-run H1 and H2 on remaining 30 events (19 hikes, 11 cuts).

**Status:** These checks are listed in Section 4 of the paper as "planned" but **results are not reported in the paper**. The known-issues note states:

> "The pre-registered robustness checks (without the March 2020 cuts, without the March 2023 hike, XLF as benchmark) are not reported in the paper. Leftover files tables/robustness_march2020.tex, robustness_march2023.tex and xlf.tex are not part of the paper and contradict the pre-registration (three March 2020 cuts instead of two; sample sizes that do not add up)."

**Severity:** HIGH. The pre-registration document explicitly lists these checks as primary robustness tests. Omitting them from the published paper violates pre-registration discipline and limits the reader's ability to assess sensitivity to key choices.

**Data integrity concerns from this omission:**
- The robustness files contain contradictory sample sizes ("three March 2020 cuts instead of two"), raising questions about data handling.
- No defense is offered for why these checks are omitted (e.g., data issues, computational problems).
- Readers cannot assess whether main results are robust to excluding crisis periods.

### Other Replication Issues

- ✓ **Raw data preserved:** All data sourced from public APIs (FRED, Yahoo Finance), so raw data is recoverable.
- ✓ **Specification documented:** Market model, event windows, and H1/H2 specifications are clearly stated.
- ⚠ **Code not provided:** No Python/R scripts or reproducible notebooks are attached. The paper references "process_event_study.py" in the known-issues section ("set aside unread"), but this is not available for replication verification.
- ⚠ **Summary statistics check:** Main results (Table 1) show mean CARs and standard errors. These match the abstract and are internally consistent. However, without code, it is impossible to verify calculations independently.

---

## 11. RED FLAGS FROM THE CHECKLIST

Applying the data review checklist's red-flag patterns:

| Red Flag | Status | Details |
|----------|--------|---------|
| Vague sample descriptions | ✓ PASS | Clear description: 31 FOMC announcements, 20 hikes, 11 cuts, 2015–2025 |
| No summary statistics table | ✓ PASS | Table 1 provided with mean CAR, SE, t-stat, p-values |
| Round numbers in sample sizes | ✓ PASS | 31 events, 20 hikes, 11 cuts are realistic splits (no suspiciously round numbers like 30 or 25 hikes) |
| Missing data not discussed | ✓ PASS | DGS2 missingness (120 out of 2,870 rows) is documented and explained (market holidays) |
| No balance/baseline table | ✓ PASS | Not applicable to event study; sample composition table provided |
| Outcome & treatment from different time periods | ✓ PASS | DAY 0 = announcement date; outcome measured around day 0; treatment (rate decision) announced on day 0. No temporal misalignment. |
| Implausible summary statistics | ✓ PASS | Mean CAR -1.06% (hikes) and -0.08% (cuts) are economically plausible |

---

## 12. DETAILED FINDINGS

### Hypothesis 1: Mean CAR Test
- **Specification:** Two-sided t-test of H₀: E[CAR] = 0, stratified by rate direction (hikes, cuts).
- **Results as reported:**
  - Rate hikes (n=20): CAR = -1.06%, SE = 0.53%, t = -1.998, p = 0.0603 (not significant at 5%)
  - Rate cuts (n=11): CAR = -0.08%, SE = 0.86%, t = -0.091, p = 0.9295 (not significant at 5%)
- **Data quality assessment:**
  - ✓ Degrees of freedom correctly applied (19 for hikes, 10 for cuts)
  - ✓ P-values computed from t-distribution (verified by abstract)
  - ✓ Confidence intervals reported
  - ⚠ **Issue:** Secondary H1 window [0, +5] shows pooled CAR = -1.47% (p = 0.022), which IS significant. This is mentioned in the abstract but not clearly integrated into the narrative. The paper should clarify that the primary (pre-registered) window [-1, +1] shows null results, but a longer window shows a marginally significant negative effect.

### Hypothesis 2: Surprise Sensitivity Regression
- **Specification:** CAR = α + β·ΔDGS2 + ε, where ΔDGS2 is day-0 change in 2-year yield (basis points).
- **Results as reported:**
  - Pooled (n=31): β = -0.0208, p = 0.6368 (not significant)
  - Hikes (n=20): β = -0.0008, p = 0.9865 (not significant)
  - Cuts (n=11): β = -0.0944, p = 0.4587 (not significant)
- **Data quality assessment:**
  - ✓ Coefficients estimated with HC1 standard errors (robust to heteroskedasticity)
  - ✓ All three specifications (pooled, by direction) are reported
  - ✓ P-values appropriately computed from t-distribution with n-2 degrees of freedom
  - ⚠ **Issue:** R² for pooled regression is 0.0053 (0.53%), meaning yield surprise explains essentially 0% of variation in abnormal returns. This is correctly interpreted as a null result, but the interpretation deserves emphasis: either market has already priced announcement, or offsetting economic channels dominate.

---

## 13. ASSESSMENT OF KNOWN ISSUES

The paper's known-issues note documents four concerns:

1. **Robustness checks not reported** — HIGH SEVERITY
   - Pre-registered checks (exclude March 2020, exclude March 2023, XLF benchmark) are listed in paper but results are not shown.
   - Leftover files contain contradictory sample sizes.
   - **Impact:** Readers cannot assess robustness; pre-registration violated in reporting.

2. **Abstract terminology on pre-registration** — LOW SEVERITY
   - The abstract calls the [0, +5] window "not pre-registered" but the window was actually pre-registered (only the pooled estimate was post-hoc).
   - This is a minor clarification issue, not a data quality problem.

3. **DGS2 loaded by researcher** — MODERATE SEVERITY (now resolved)
   - The data analyst's DGS2 load failed three times due to a leading space in the FRED API key.
   - Researcher manually ran: `e2er-data fred series --series-id DGS2 --start 2015-01-01 --end 2025-12-31 --paper-id [id] --table dgs2`.
   - Result: dgs2 table now has 2,870 rows with 2,750 non-null values (correct).
   - **Impact:** Data integrity is now assured, but the process failure indicates gaps in the automated pipeline. This should be documented in the paper's data availability statement.

4. **H2 estimates changed across reruns** — RESOLVED
   - The definition of "day-0 change" was clarified: compute against the "previous trading day with a value" (not just calendar-previous day).
   - Final estimates in estimation_results.json use this corrected definition.
   - **Impact:** No data quality issue, but version control of intermediate results is important for reproducibility.

---

## 14. PROCESS & TRANSPARENCY

### Strengths
- ✓ **Pre-registration disclosed:** The paper explicitly states analysis was pre-registered and results were computed blind (8 minutes after design approval, before pre-registration freeze).
- ✓ **Demonstration disclaimer:** Clear statement that this is a demonstration of end-to-end pipeline (machine-generated under researcher supervision).
- ✓ **Data sources public:** All data from FRED and Yahoo Finance (open access, no proprietary restrictions).

### Weaknesses
- ⚠ **Pre-registered robustness checks omitted:** Results are missing despite being listed in Methods.
- ⚠ **Process failure not fully disclosed:** The DGS2 loading failure is mentioned in known-issues but not highlighted in the paper's data availability section.
- ⚠ **Code not provided:** Reproducibility limited by absence of analysis scripts.

---

## 15. OVERALL DATA QUALITY SCORE

| Dimension | Assessment | Score |
|-----------|------------|-------|
| Source documentation | Excellent (open data, FRED/Yahoo) | 9/10 |
| Sample construction | Good (31 events, clear windows) | 8/10 |
| Missing data handling | Good (documented, appropriate strategy) | 8/10 |
| Variable definitions | Good (clear, standard approach) | 8/10 |
| Outliers & leverage | Needs improvement (no explicit analysis) | 5/10 |
| Measurement quality | Good (reliable sources, high-frequency) | 8/10 |
| Time & currency | Excellent (clear, consistent) | 9/10 |
| Data integrity & replication | Fair (pre-registered checks not reported, code unavailable) | 6/10 |
| Transparency | Good (disclosure of pre-registration, process issues noted) | 7/10 |

**Weighted Average:** 7.3/10

---

## 16. SUMMARY OF MAJOR FINDINGS

### Critical Issue
**Pre-registered robustness checks are not reported in the paper despite being listed in Methods Section 4.** Files (tables/robustness_march2020.tex, robustness_march2023.tex, xlf.tex) exist but contain inconsistencies (e.g., "three March 2020 cuts instead of two") and are excluded from the paper. This violates pre-registration discipline and limits assessment of robustness.

### Moderate Issues
1. **Data loading failure:** FRED DGS2 table was empty (2,765 rows, 0 values) due to analyst error. Researcher manually reloaded the data. While resolved, this indicates process fragility.
2. **Outlier analysis absent:** No systematic analysis of leverage, influence, or sensitivity to individual events (especially March 2020, March 2023).
3. **Measurement aggregation:** KBE (value-weighted ETF) masks heterogeneous responses across bank sizes. Implications not discussed.

### Minor Issues
1. **Methodological transparency:** The conversion of DGS2 from percent to basis points is not stated in main Methods.
2. **H2 null result interpretation:** R² = 0.53% correctly indicates yield surprise explains negligible variation, but this deserves emphasis.
3. **Code availability:** No Python/R scripts provided for verification.

### Positive Aspects
- ✓ Open-access data sources (FRED, Yahoo Finance)
- ✓ Clear event definition and window specification
- ✓ Proper handling of non-trading days and missing data
- ✓ Transparent pre-registration with blind analysis
- ✓ Appropriate statistical framework (market model, cross-sectional t-test)
- ✓ Explicit stratification by rate direction

---

## 17. RECOMMENDATIONS

### Tier 1: Must Fix Before Publication
1. **Report pre-registered robustness checks** (or provide explicit justification for omission and explain the inconsistencies in auxiliary files).
   - Include results excluding March 2020 and March 2023.
   - Include results using XLF as alternative benchmark.
   - If data issues preclude completion, document them.

2. **Clarify DGS2 computation in Methods:**
   - State explicitly: "Day-0 change is computed as DGS2(day 0) − DGS2(previous trading day with a value)."
   - Explain why this matters (handles weekends/holidays).

### Tier 2: Should Improve
3. **Add outlier analysis:** Report distribution of CARs (mean, median, SD, range). Optionally, conduct cook's distance for leverage diagnostics on H2 regression.

4. **Discuss measurement aggregation:** KBE is an ETF; acknowledge that individual bank responses are masked. Discuss whether XLF results (when reported in robustness) show similar patterns.

5. **Document data loading issue:** Add a sentence to the data section stating: "The 2-year Treasury yield (DGS2) was loaded from FRED by the researcher after an initial analyst attempt failed due to an API key formatting error. The final dataset contains 2,870 observations (2,750 non-null, excluding market holidays)."

6. **Add power analysis or discuss:**
   - Why sample of 31 events is adequate for detecting economically meaningful effects.
   - Typical effect sizes in prior literature and implied power.

### Tier 3: Nice-to-Have
7. **Provide analysis code:** Release Python/R scripts for full reproducibility.

8. **Comment on H1 [0, +5] window:** The secondary window shows -1.47% CAR (p=0.022), significant at 5%. Discuss whether this suggests cumulative effects over a week and warrant further investigation.

---

## CONCLUSION

**Data quality is fundamentally sound.** The sources are reliable (FRED, Yahoo Finance), the sample construction is transparent (31 FOMC events over 2015–2025), and variables are clearly defined. However, **three material reporting issues reduce confidence:**

1. **Pre-registered robustness checks are listed but not reported**, with auxiliary files containing inconsistencies.
2. **A data-loading process failure** required manual intervention, though it has been resolved and is partially disclosed.
3. **Limited outlier and sensitivity analysis** leaves vulnerability to high-leverage events.

These are **not data quality issues per se**, but rather **reporting and process transparency issues** that weaken the credibility of the analysis despite the underlying data being solid.

**The core event study—31 FOMC announcements, KBE/SPY returns, market model, H1 and H2 hypotheses—is properly specified and the data are correctly handled.** The main findings (null results for H1 in the pre-registered 3-day window, null sensitivity to yield surprise in H2) appear robust to the data quality concerns identified.

---

OVERALL SCORE: 7/10
RECOMMENDATION: Minor Revision
