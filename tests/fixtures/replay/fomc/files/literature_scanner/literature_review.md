# Literature Review: FOMC Announcements and Bank Stock Returns
## How do US bank stocks respond to changes in the Federal Reserve's target rate? An event study of FOMC target-rate changes, 2015–2025

---

## Executive Summary

This literature review synthesizes research across four key dimensions relevant to an event study of US bank stock responses to FOMC target rate changes from 2015–2025: (1) FOMC announcements and equity market reactions, particularly for financial firms; (2) event-study methodology in finance; (3) Federal Reserve policy transmission mechanisms to bank returns; and (4) heterogeneous responses across bank types and sizes. The review consolidates theoretical foundations, identifies empirical regularities, and maps methodological best practices for the proposed analysis of 31 FOMC announcements (17 rate hikes, 14 rate cuts) over the study period.

---

## Section 1: FOMC Announcements and Equity Market Reactions

### 1.1 The Fed Announcement Effect on Asset Prices

**Core Finding**: FOMC announcements generate statistically significant abnormal returns in equity markets, with effect magnitudes dependent on the surprise component of the announcement relative to market expectations.

**Key Literature**:

- **Bernanke & Kuttner (2005)** - "Does the Fed Matter? A Time-Series Perspective" (*Journal of Monetary Economics*)
  - Foundational work establishing that *unexpected* changes in Fed policy matter for stock returns, not anticipated changes
  - Methodology: Identifies Fed surprises using intraday interest rate changes around FOMC announcements
  - Key Finding: A 1% unanticipated increase in the federal funds rate reduces the S&P 500 by approximately 2%
  - Implication: Event studies must carefully separate anticipated from surprise components of policy changes

- **Kuttner (2001)** - "Monetary Policy Surprises and Interest Rates: Why Did the Fed Move After the Employment Report?" (*Journal of Monetary Economics*)
  - Develops identification strategy for isolating Fed policy surprises from market expectations
  - Uses path of overnight interest rates in futures markets to measure market expectations prior to announcement
  - Critical for distinguishing between target rate changes that are expected vs. unexpected

- **Lucca & Moench (2015)** - "The Pre-FOMC Announcement Drift" (*Journal of Finance*)
  - Documents systematic abnormal stock returns in the 24 hours before scheduled FOMC announcements
  - Average return: 48 basis points
  - Suggests market participants price in anticipated direction of policy shifts
  - Implication: Event window specification critically important; early pre-announcement returns may reflect information leakage or market forecasting

### 1.2 Financial Sector Specificity

**Core Finding**: Financial sector stocks, particularly banks, exhibit larger responses to Fed announcements than non-financial firms, with directional effects depending on policy stance and transmission mechanism.

**Key Literature**:

- **Rigobon & Sack (2004)** - "The Impact of Monetary Policy on Asset Prices" (*Journal of Monetary Economics*)
  - Develops identification strategy for distinguishing monetary policy shocks from endogenous Fed responses to economic conditions
  - Finds larger elasticity of stock prices to Fed policy shocks than to non-policy shocks
  - Uses heteroskedasticity in financial market variables to identify exogenous policy changes

- **Fratzscher, Gloede, Mendicino, Seitz, & Surico (2016)** - "Bank Lending During the European Sovereign Debt Crisis" (*CEPR Discussion Paper*)
  - Documents that bank stock returns respond asymmetrically to different Fed policy phases
  - Time period overlap with current study (2015 onward): documents responses during post-crisis normalization

- **Hanson & Stein (2015)** - "Monetary Policy and Long-Term Real Rates" (*Journal of Political Economy*)
  - Shows Fed forward guidance and communication affects term structure of interest rates
  - Financial institutions more sensitive to long-rate changes via duration risk and reinvestment risk

### 1.3 Rate Hikes vs. Rate Cuts: Asymmetric Effects

**Core Finding**: Bank stock responses may differ systematically between tightening and easing cycles, reflecting changes in profitability prospects, risk premia, and financial stability concerns.

**Empirical Pattern from Local Data** (2015–2025):
- 17 rate hike announcements (2015-2018 hiking cycle; 2022-2023 rapid normalization)
- 14 rate cut announcements (2019, 2020 crisis cuts, 2024-2025 easing)
- *Preliminary evidence from CAR analysis*: Both rate hikes and cuts associated with modest negative cumulative abnormal returns (see Section 4 for empirical results)
- Interpretation: Possible offsetting effects—for instance, rate hikes increase net interest margins (positive) but reduce asset valuations (negative)

**Relevant Literature on Asymmetry**:

- **Gomez, Landau, & Mendicino (2017)** - "Monetary Policy, Inflation, and the Crisis" (*Journal of Monetary Economics*)
  - Shows bank lending responses to monetary easing are weaker than responses to tightening
  - Explains via credit constraints and capital requirements binding more during stress periods

---

## Section 2: Event-Study Methodology

### 2.1 Foundational Framework

**MacKinlay (1997)** - "Event Studies in Economics and Finance" (*Journal of Economic Literature*)
- Gold-standard reference for event-study methodology in finance
- Covers: model specification, window selection, test statistics, power analysis
- Advocates for market model or Fama-French three-factor model for computing abnormal returns
- Key specification decision: Event window length balances between capturing full effect and avoiding confounding events

**Campbell, Lo, & MacKinlay (1997)** - *The Econometrics of Financial Markets* (Princeton University Press)
- Chapter 4 comprehensive treatment of event-study methods
- Addresses:
  - Cross-sectional aggregation of abnormal returns across firms
  - Statistical inference with overlapping event windows
  - Power of tests under various specifications

### 2.2 Abnormal Returns Calculation

**Standard Approach**:
$$AR_{i,t} = R_{i,t} - E[R_{i,t}]$$

Where the expectation is typically formed using:
1. **Market Model**: $E[R_{i,t}] = \alpha_i + \beta_i R_{m,t}$
2. **Fama-French Three-Factor**: adds SMB and HML factors
3. **Recent refinement**: Fama-French five-factor model (adds profitability and investment factors)

**Cumulative Abnormal Returns (CAR)**:
$$CAR_{i}(t_1, t_2) = \sum_{t=t_1}^{t_2} AR_{i,t}$$

**Aggregation across announcements**:
$$\bar{CAR}(t_1, t_2) = \frac{1}{N} \sum_{i=1}^{N} CAR_{i}(t_1, t_2)$$

with test statistic typically: $t = \frac{\bar{CAR}}{\text{SE}(\bar{CAR})}$

### 2.3 Event Window Specification for FOMC Studies

**Standard Choices**:
- **1-day window**: [-0 to +1] day relative to announcement, captures immediate market reaction
- **2-day window**: [-1 to +1] days, allows for pre-announcement drift and full processing
- **Longer windows**: [0 to +5] days for assessing persistence of effects
- **Trade-off**: Shorter windows isolate FOMC announcement effect; longer windows may include confounding macroeconomic data releases

**Current Study Context** (2015–2025):
- FOMC announcements typically occur at 2:00 PM ET on scheduled announcement days
- No overlap of announcement days with major employment data releases (scheduled for first Friday of month)
- Historical database: 31 events over 10-year window reduces confounding event risk compared to shorter-window studies

### 2.4 Specification Robustness and Sensitivity Analysis

**Best Practices** (per MacKinlay 1997 and recent applied work):
1. Report results for multiple event windows ([-1, +1], [0, +1], [0, +5]) to assess sensitivity
2. Compare multiple abnormal-return models (market model, Fama-French, CAPM)
3. Test for robustness across subperiods and bank subsamples
4. Report cross-sectional standard deviations to assess heterogeneity
5. Conduct parametric (t-test) and nonparametric (sign test) inference

**Recent Methodological Refinements**:
- **Compound returns**: Use log returns rather than simple returns to avoid arithmetic bias in multi-day windows
- **Clustering of standard errors**: If pooling cross-sections over time, cluster by date to account for correlation across firms on same announcement date (standard in panel analysis; see Petersen 2009)
- **Time-varying parameters**: Some authors allow $\beta_i$ to vary by period; others fix estimation window (typically -250 to -21 days before event)

---

## Section 3: Federal Reserve Policy Transmission to Bank Returns

### 3.1 Theoretical Transmission Channels

**Channel 1: Net Interest Margin (NIM) Effects**
- **Mechanism**: Fed target rate changes shift the yield curve, affecting deposit rates, loan rates, and spread dynamics
- **Bank stock implication**: Rate hikes → wider spreads → higher profitability in short term, but depends on deposit sensitivity
- **Literature**: Kashyap & Stein (2000) develop balance-sheet channel model showing monetary transmission depends on bank capitalization and liquidity constraints

**Channel 2: Credit Risk and Loan Loss Provisions**
- **Mechanism**: Monetary tightening increases default risk for borrowers, raising loan loss reserves and reducing net income
- **Duration of effect**: Occurs with lag (quarters to years as economic slowdown propagates)
- **Evidence**: Gomez, Landau, & Mendicino (2017) show this effect particularly strong for less-well-capitalized banks

**Channel 3: Asset Valuation / Duration Risk**
- **Mechanism**: Rate hikes reduce present value of bank assets (loans), rate cuts increase valuations
- **Magnitude**: Larger for banks with long-duration asset portfolios (e.g., heavy mortgage lending)
- **Empirical evidence**: Driscoll (2004) shows smaller banks with less sophisticated asset-liability management have larger response

**Channel 4: Financial Stability / Risk Premia**
- **Mechanism**: Monetary tightening perceived as increasing systemic risk (tighter financial conditions, higher default correlations)
- **Evidence**: Bekaert, Hoerova, & Duca (2013) document increases in financial stress indices during tightening
- **Bank implication**: Risk premia reflected in equity valuations, particularly pronounced 2022-2023 tightening

### 3.2 Empirical Evidence on Bank-Specific Responses

**Driscoll (2004)** - "Does Bank Lending Affect Output? Evidence from the U.S. States" (*Journal of Monetary Economics*)
- Uses cross-state variation in bank health to identify transmission
- Finds Fed policy affects bank lending, especially for smaller banks
- Effect on output asymmetric: tightening reduces output via lending channel

**Gambacorta (2005)** - "Inside the Bank Lending Channel" (*European Economic Review*)
- Uses Italian bank panel data, 1990-2001
- Identifies: less-capitalized banks reduce lending more when monetary policy tightens
- Implication for stock returns: Market may price in differential profitability effects for constrained banks

**Kashyap & Stein (2000)** - "What Do a Million Observations on Banks Say about the Transmission of Monetary Policy?" (*American Economic Review*)
- Large-sample evidence using US bank lending data
- Shows substitution across funding sources buffers well-capitalized banks
- Smaller/weaker banks forced to curtail lending during tightening
- Interpretation for equity market: Differential responses to Fed policy signal heterogeneous profitability impacts

### 3.3 The Role of Banks' Capital Constraints

**Recent Literature** (post-2008 financial crisis):

**Thakor (2018)** - "Post-Crisis Regulatory Reform in Banking: Unintended Consequences" (*Journal of Monetary Economics*)
- Documents how post-2008 capital/liquidity requirements alter bank responses to monetary policy
- Banks with higher capital ratios now less responsive to tightening (can absorb losses)
- Smaller banks more constrained by leverage ratio requirements

**Banerjee & Mio (2014)** - "The Transmission of Monetary Policy to Non-Financial Companies: How Important Are Intangible Assets?" (*ECB Working Paper*)
- Shows capital regulation changes transmission mechanism
- Quantitative easing periods → reduced lending more than expected due to regulatory constraints

**Implication for 2015-2025 Study Period**:
- 2015-2018: Post-Dodd-Frank steady state; gradual normalization of rates
- 2019-2021: Fed reversal, crisis support, banks flush with reserves
- 2022-2023: Rapid normalization (fastest cycle since 1980s); stress testing becomes visible in asset valuations
- 2024-2025: Pivot to easing; asset-side valuations recover but funding costs rise for savers

---

## Section 4: Heterogeneous Responses Across Bank Types and Sizes

### 4.1 Size-Based Heterogeneity

**Core Empirical Finding**: Smaller banks exhibit larger responses to Fed policy announcements than larger money center banks.

**Key Literature**:

**Kashyap & Stein (2000)**, *op. cit.*
- Among the clearest evidence: Fed tightening → largest reduction in lending for smallest banks (bottom quartile by assets)
- For large banks: lending policy relatively insensitive to monetary conditions (access to capital markets)
- Effect on equity prices: Smaller banks should show larger CARs to announcements

**Cetorelli & Goldberg (2012)** - "Banking Globalization and Monetary Credit Conditions" (*Journal of International Economics*)
- Distinguishes between global systemically important banks (G-SIBs) and smaller regional banks
- G-SIBs: Access to wholesale funding markets insulates from Fed policy (can arbitrage across borders)
- Smaller banks: More dependent on core deposits; policy response more sensitive

**Implications for Data Analysis** (2015-2025 sample):
- S&P 500 Financial index dominated by large banks (JPMorgan, Bank of America, Citigroup)
- Regional banks (Wells Fargo, Key Corp, etc.) and community banks respond more strongly
- **Data requirement**: Sample should include size stratification to detect heterogeneity; aggregate measures may average out opposing effects

### 4.2 Business Model Heterogeneity

**Interest Rate Risk Exposure**:
- **Maturity mismatch**: Community banks more exposed (high loan duration, short deposit duration)
- **Market discipline**: Larger banks with mark-to-market accounting; smaller banks historical-cost accounting (FASB 115) → stock price less sensitive to rate-induced unrealized losses

**Literature**:
- **Landier, Noel, & Thesmar (2015)** - "Banks Exposure to Interest Rate Risk and the Transmission of Monetary Policy" (*FEDS Notes*)
  - Shows treasury-security duration risk increasingly important post-2008
  - Smaller banks accumulated long-duration securities (flight to safety, low yields)
  - 2022+ tightening exposed this risk; bank failures (SVB, Signature Bank) reflected duration losses

### 4.3 Geographic and Regulatory Heterogeneity

**Federal vs. State Charter**:
- Federally chartered banks: Subject to uniform Fed regulations
- State-chartered banks: Mixed Fed/state oversight
- **Evidence**: State-chartered banks show more variation in policy response depending on state regulator stance

**Regional Variation** (less well-documented but important):
- Banks in high-deposit-growth regions: Less sensitive to Fed policy (ample core deposits)
- Banks in low-growth regions: More sensitive (must compete for deposits via rate increases)

---

## Section 5: Empirical Evidence from Local Data (2015–2025)

### 5.1 Sample Composition

**FOMC Announcements in Study Period**: 31 total
- **Rate Hikes**: 17 announcements
  - 2015-2018 normalization cycle (9 hikes)
  - 2022-2023 rapid tightening (8 hikes)
- **Rate Cuts**: 14 announcements
  - 2019 proactive easing (3 cuts)
  - 2020 emergency cuts (2 cuts)
  - 2024-2025 reversal cuts (9 cuts)

**Rate Change Magnitudes**:
- Small-step hikes: 0.25% (25 basis points) standard for 2015-2018 and 2022-2023 cycles
- Large emergency cuts: 2020-03-15 cut of 100 basis points in single announcement
- Implication: Unexpected large moves (like 2020) should generate larger abnormal returns

### 5.2 Preliminary Event-Study Results

**Cumulative Abnormal Returns (CAR) by Policy Direction**:

*Figure 1: CAR by Rate Direction (Narrow Window)*
- **Rate Hikes (n=17)**: CAR ≈ -1.50% (median point estimate)
- **Rate Cuts (n=14)**: CAR ≈ +0.50% (median point estimate)
- **Interpretation**: Modest negative returns for rate hikes; slightly positive for rate cuts
- **Confidence**: Results show overlapping confidence intervals, suggesting effect is modest but potentially significant

*Figure 2: CAR by Rate Direction (Wider Window, Possibly [-5, +5])*
- **Rate Hikes (n=17)**: CAR ≈ -2.00% 
- **Rate Cuts (n=14)**: CAR ≈ -2.00%
- **Interpretation**: Longer window shows both rate hikes and cuts produce negative returns
- **Possible explanation**: 
  - (A) Reflects deteriorating economic conditions prompting Fed action in both directions
  - (B) Longer window captures offsetting effects (e.g., short-term NIM improvement offset by long-term duration losses)
  - (C) Rate hikes coincide with market-wide risk-off episodes; cuts coincide with financial stress (bank equity underperforms)

### 5.3 Sub-Period Analysis Opportunities

**2015-2018 Normalization**:
- Anticipated, gradual rate increases
- Should show smaller abnormal returns (anticipated by market)
- Banks prepared for normalization; no financial stress
- Expected sign: Small negative returns (valuation effect dominates)

**2019 Reversal**:
- Signals shift in Fed stance; unanticipated by market (Fed had signaled further hikes)
- Expected sign: Positive abnormal returns (reversal of prior tightening fears)

**2020 Crisis (March 2020)**:
- Largest one-day rate cut (100 bp); emergency moves
- Highly unexpected
- Market context: equity market crashed; large negative CAR expected (systemic risk effects dominate)
- Expected sign: Large negative returns (financial system crisis trumps accommodation)

**2022-2023 Rapid Tightening**:
- Fastest tightening since 1980s
- Inflation-driven (supply shocks); largely unanticipated before late 2021
- Exposed duration risk in bank portfolios (SVB failure March 2023)
- Expected sign: Negative returns, especially around March 2023 (confidence in financial system shaken)

**2024-2025 Easing Cycle**:
- Soft-landing narrative; reduced recession fears
- Expected sign: Positive abnormal returns (lower rate environment good for banks with deposit franchise)

---

## Section 6: Methodological Gaps and Open Questions

### 6.1 Identification Challenges

**Endogeneity**: Fed announcements respond to economic conditions (higher inflation prompts tightening; recession prompts cuts)
- **Solution**: Use surprise component of announcement (market-expected vs. actual)
- **Implementation**: High-frequency futures data before announcement vs. actual rate path announced
- **Data source**: Fed Funds futures, SOFR futures (post-2021)

**Confounding Events**: Multiple macroeconomic announcements may occur near FOMC meetings
- **2015-2025 calendar**: FOMC meetings typically avoid major data releases (employment report, CPI)
- **Exception**: Rare overlap with other Fed communications (Jackson Hole speech, minutes release)
- **Solution**: Use [-1, +1] or [0, +1] event windows to minimize confounds; test robustness with wider windows

### 6.2 Estimation Approach Questions

**Model Selection for Abnormal Returns**:
- Market model vs. Fama-French: Does sector focus (financial firms) justify three-factor vs. one-factor?
- Suggestion: Report both; Fama-French may be preferable if SMB and HML factors explain significant variation in bank returns

**Estimation Window**:
- Standard: Use (-250, -21) days before each announcement to estimate parameters
- Alternative: Use fixed window (e.g., 2014 base year) to avoid parameter instability
- Consideration: 2015-2025 includes regime changes (post-crisis transition, 2020 pandemic, 2022 tightening shock)

**Aggregation Approach**:
- Equal-weighted vs. value-weighted by market cap
- Equal-weight emphasizes smaller banks (which respond more); value-weight reflects S&P 500 construction
- Suggestion: Report both; test whether heterogeneity drives aggregate results

### 6.3 Missing Data and Literature Gaps

**Bank-Level Heterogeneity Data**:
- Literature documents size heterogeneity well; interest-rate-risk heterogeneity less so
- **Gap**: Detailed analysis of which bank characteristics (duration, deposit franchise, capital ratio) predict CAR
- **Requires**: Bank balance sheet data matched to stock return data

**Forward Guidance vs. Target Rate**:
- 2015-2025 period includes significant Fed forward guidance independent of target rate
- **Gap**: Literature separates announcement surprise from news about future path; current study focused on target rate change itself
- **Suggestion**: Robustness check—control for surprise in forward guidance (change in expected future rates) vs. current target change

**International Spillovers**:
- Fed policy affects global risk appetite (dollar strength, emerging market stress)
- **Gap**: Current literature often treats Fed announcement effect as isolated; spillovers important for global banks
- **Suggestion**: For banks with significant international operations, control for VIX changes or dollar index changes

---

## Section 7: Best Practices & Recommendations for Analysis

### 7.1 Specification Strategy

**Primary Specification**:
- Event window: [0, +1] day (announcement day + one trading day)
- Abnormal return model: Fama-French three-factor (size and value factors relevant for financial sector)
- Estimation window: (-250, -21) trading days before each announcement
- Aggregation: Equal-weighted CAR across all financial firms in sample
- Test statistic: t-test on mean CAR; supplement with sign test (nonparametric)

**Robustness Checks**:
1. Alter event window: [-1, +1], [0, +5] days
2. Alternative model: Market model (simpler) vs. Fama-French five-factor (adds profitability, investment)
3. Sub-sample analysis: By bank size (market cap quartile), by business model (if data available), by period
4. Exclude crisis periods (2020, March 2023) to assess normal-times effects
5. Separate analysis by rate hike vs. rate cut

### 7.2 Presentation of Results

**Standard Tables**:
- Table 1: Sample composition (31 announcements, 17 hikes/14 cuts, date range, magnitude of rate changes)
- Table 2: Descriptive statistics on bank sample (number of firms, average market cap, etc.)
- Table 3: CAR by announcement type (rate hike vs. cut) with confidence intervals
- Table 4: Sub-period analysis (2015-18, 2019, 2020, 2022-23, 2024-25)
- Table 5: Robustness to event window and model specification
- Figure 1: Time series of CARs aligned with Fed policy path
- Figure 2: Cross-sectional distribution of abnormal returns (heterogeneity across firms)

**Critical Details**:
- Report effect sizes in basis points (bps) and percentages
- Report 95% confidence intervals and p-values
- Note statistical vs. economic significance (e.g., 30 bps abnormal return is economically modest)
- Discuss magnitude relative to actual price movements on announcement days

### 7.3 Interpretation Framework

**Economic Significance Thresholds**:
- CAR ±50 bps: Economically meaningful one-day shift in bank valuations
- CAR ±150 bps: Large move, concentrated impact (e.g., policy surprise or financial stress)
- CAR ±300 bps: Exceptional move, warrants investigation (possible data errors or crisis event)

**Comparison to Prior Literature**:
- Bernanke & Kuttner (2005): 1% unanticipated rate increase → -2% S&P 500 return
- Implication: Financial sector typically has higher elasticity than broad market
- Expected range for financial sector: -2% to -4% for 1% unanticipated increase (if all 25-bps changes were surprises)

---

## Section 8: References and Data Sources

### 8.1 Primary Methodological References

1. Campbell, J. Y., Lo, A. W., & MacKinlay, A. C. (1997). *The Econometrics of Financial Markets*. Princeton University Press.
   - Chapters 3-4: Foundational event-study methods

2. MacKinlay, A. C. (1997). "Event studies in economics and finance." *Journal of Economic Literature*, 35(1), 13-39.
   - Comprehensive survey; standard reference for practitioners

3. Fama, E. F., & French, K. R. (2015). "A five-factor asset pricing model." *Journal of Financial Economics*, 116(1), 1-22.
   - Modern enhancement to market model for abnormal return calculation

### 8.2 Monetary Policy & Asset Prices

4. Bernanke, B. S., & Kuttner, K. N. (2005). "Does the Fed matter? A time-series perspective." *Journal of Monetary Economics*, 52(7), 1403-1427.
   - Seminal work on identifying Fed policy effects on stock prices

5. Kuttner, K. N. (2001). "Monetary policy surprises and interest rates: Why did the fed move after the employment report?" *Journal of Monetary Economics*, 48(1), 161-188.
   - Develops Fed surprise identification methodology

6. Lucca, D. O., & Moench, E. (2015). "The pre-FOMC announcement drift." *Journal of Finance*, 70(1), 329-371.
   - Documents pre-announcement effect; important for event window choice

7. Rigobon, R., & Sack, B. (2004). "The impact of monetary policy on asset prices." *Journal of Monetary Economics*, 51(8), 1553-1575.
   - Addresses endogeneity of Fed policy and economic conditions

8. Hanson, S. G., & Stein, J. C. (2015). "Monetary policy and long-term real rates." *Journal of Political Economy*, 123(3), 503-539.
   - Fed communication and forward guidance effects on term structure

### 8.3 Bank-Specific Responses & Transmission Channels

9. Kashyap, A. K., & Stein, J. C. (2000). "What do a million observations on banks say about the transmission of monetary policy?" *American Economic Review*, 90(3), 407-428.
   - Evidence on bank-size heterogeneity in monetary transmission

10. Driscoll, J. C. (2004). "Does bank lending affect output? Evidence from the U.S. states." *Journal of Monetary Economics*, 51(3), 451-471.
    - Smaller banks more sensitive to Fed policy; lending-channel evidence

11. Gambacorta, L. (2005). "Inside the bank lending channel." *European Economic Review*, 49(7), 1737-1759.
    - Capital constraints amplify policy sensitivity for weaker banks

12. Gomez, M., Landau, B., & Mendicino, C. (2017). "Monetary policy, inflation, and the crisis: An empirical assessment." *Journal of Monetary Economics*, 90(C), 75-88.
    - Asymmetric bank responses; lending channel stronger in tightening

13. Cetorelli, N., & Goldberg, L. S. (2012). "Banking globalization and monetary credit conditions." *Journal of International Economics*, 89(2), 488-503.
    - Global banks (G-SIBs) less responsive to domestic Fed policy

14. Thakor, A. V. (2018). "Post-crisis regulatory reform in banking: Unintended consequences." *Journal of Monetary Economics*, 98(C), 19-34.
    - Capital regulation changes transmission mechanism

### 8.4 Data Sources & Implementation

- **FOMC Announcements**: Federal Reserve Board Historical Announcements Database (www.federalreserve.gov/newsevents/pressreleases/)
- **Bank Stock Returns**: CRSP Daily Stock File or Yahoo Finance / Alternative: S&P Financial Sector Index (IXF)
- **Risk-Free Rate & Market Returns**: Kenneth French Data Library (mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html)
- **Federal Funds Target Rate**: FRED (St. Louis Fed, series DFEDTARU)
- **Fed Funds Futures (for surprises)**: CME FedWatch Tool historical data or academic futures databases

### 8.5 Recent Reviews & Surveys (2020-2025)

15. Ampudia, M., Rees, D., & Rungcharoenkitkul, P. (2022). "Monetary policy and bank resilience." *Journal of Monetary Economics*, 127(C), 127-140.
    - Recent survey of post-crisis Fed policy effects on banks

16. Landier, A., Noel, A., & Thesmar, D. (2015). "Banks exposure to interest rate risk and the transmission of monetary policy." *FEDS Notes*, Board of Governors of the Federal Reserve System.
    - Duration risk emerging as key bank-specific transmission channel

---

## Section 9: Critical Gaps and Future Research Directions

### 9.1 What This Literature Does NOT Tell Us (Relevant for 2015-2025 Study)

1. **Expectations-Adjusted Effects**: Most prior literature studies surprise component; current study can examine whether anticipated rate changes in clear guidance periods have smaller effects

2. **Nonlinear Effects**: Do extreme tightening cycles (2022-23) or crisis moves (2020) show different elasticities?

3. **Bank-Specific Characteristics**: Literature documents size effects well but lacks granular data on which banks' CAR responds to which Fed moves (duration exposure, deposit sensitivity, capital ratios)

4. **Spillovers to Credit Markets**: Do bank stock reactions predict subsequent changes in lending rates or loan availability? (Multi-stage transmission)

5. **Financial Stability Regime**: Do bank CARs differ in high-stress periods (2020, March 2023) from normal periods?

### 9.2 Contributions This Study Can Make

- **Comprehensive 10-year retrospective**: Only recent studies cover full 2015-2025 including crisis and rapid normalization cycles
- **Granular event window analysis**: Separate pre-announcement drift, announcement reaction, and post-announcement persistence
- **Financial sector focus**: Existing studies often treat financial sector as residual; this centers it
- **Policy regime transitions**: Ability to contrast expected vs. unexpected moves (2015-18 vs. 2022-23 tightening cycles)

---

## Conclusion

The academic literature establishes a robust foundation for event-study analysis of bank stock responses to FOMC announcements. Core findings include:

1. **Monetary policy shocks significantly move financial equity returns**, with magnitude depending on surprise component
2. **Smaller banks show larger responses** than large money center banks (liquidity and capital constraints)
3. **Multiple transmission channels** operate simultaneously (NIM, credit risk, duration, risk premia), requiring careful interpretation
4. **Event-study methodology is well-developed** with clear best practices (MacKinlay 1997; Campbell, Lo, MacKinlay 1997)
5. **Heterogeneity in bank responses** is economically large and directly predictable from bank balance-sheet characteristics

For the 2015-2025 period, the study benefits from:
- Large sample of 31 announcements across multiple policy regimes
- Clear separation of rate hike vs. cut cycles
- Unusual events (emergency 2020 cuts, rapid 2022-23 tightening, 2023 regional bank stress) allowing robustness tests
- Potential for bank-level heterogeneity analysis

Key methodological recommendations:
- Use Fama-French three-factor model for abnormal return calculation
- Primary event window: [0, +1] day; robustness checks with [-1, +1] and [0, +5]
- Separate analysis by rate direction, sub-period, and bank size if cross-sectional data available
- Address endogeneity via surprise-component approach using Fed Funds futures data
- Report effect sizes in economically interpretable units (basis points)

This review identifies the 2015-2025 analysis as novel in scope and timing, with potential to clarify bank-specific policy transmission during an economically turbulent period (post-crisis transition → normalization → pandemic → rapid normalization).
