# Identification Strategy: Bank Stock Response to FOMC Rate Announcements

## Causal Claim

The Federal Reserve's target rate changes affect US bank equity returns because banks' profitability depends on the net interest margin, which is directly affected by the level and structure of interest rates. The timing of FOMC announcements is determined by a fixed calendar and is exogenous to individual bank performance, creating a natural experiment in which to isolate the causal effect of rate policy on bank valuations.

---

## H1: Mean Abnormal Return Test

**Hypothesis**: Bank stock cumulative abnormal returns (CAR) differ significantly from zero on and around FOMC announcement dates.

**Design**:
- **Event**: 31 FOMC target-rate announcements, 2015–2025, stratified by direction (hikes, cuts).
- **Event day τ=0**: The FOMC announcement date, or the next trading day if the announcement falls on a weekend.
- **Abnormal return model**: Market model, estimated over [-250, -12] trading days before each announcement.
  - R_KBE,t = α + β·R_SPY,t + ε_t
  - Abnormal return: AR_t = R_KBE,t − (α̂ + β̂·R_SPY,t)
  - Cumulative abnormal return (CAR): sum of daily ARs over the event window.

- **Event windows**: 
  - Primary: [-1, +1] (3 trading days centered on announcement)
  - Secondary: [0, +5] (6 trading days post-announcement)

- **Test**: Two-sided t-test of H0: E[CAR | direction] = 0, reported separately for hikes and cuts.
  - Test statistics: parametric (BMP test) and non-parametric (sign test, rank test).

**Interpretation**: A significant CAR indicates that the announcement surprises the market about bank valuations. Economic theory suggests rate hikes may compress net interest margins (negative CAR); rate cuts may expand them (positive CAR).

---

## H2: Surprise Sensitivity Test

**Hypothesis**: The magnitude of bank stock abnormal returns is related to the magnitude of the 2-year Treasury yield surprise on announcement day.

**Design**:
- **Unit of analysis**: FOMC announcement event (N=31 total; N=17 hikes, N=10 cuts, N=4 holds).
- **Dependent variable**: CAR_i over the event window.
- **Explanatory variable**: ΔDGS2_{0,i} = DGS2(t=0) − DGS2(t=−1), the day-0 change in the 2-year Treasury yield, in basis points.

- **Specification** (estimated separately for hikes and cuts):
  
  CAR_i = α + β · ΔDGS2_{0,i} + ε_i

- **Standard errors**: Heteroskedasticity-robust (White).

**Interpretation**:
- β measures the sensitivity of bank valuations to the Treasury yield surprise.
- For every 1 basis point increase in the 2-year yield on day 0, KBE abnormal returns increase by β basis points.
- A significant negative β for hikes would indicate that larger-than-expected yield increases predict more negative bank returns, consistent with larger-than-expected Fed tightening or growth concerns.

**Why ΔDGS2 is the surprise measure**:
- The 2-year Treasury yield is highly sensitive to Fed policy expectations and moves sharply on announcement days.
- Variation in ΔDGS2, conditional on the Fed's announced action (hike vs. cut), captures the market's surprise about guidance, growth expectations, and yield curve implications.
- In the absence of real-time Fed funds futures data, the same-day Treasury yield move is a real-time, market-based measure of surprise.

---

## Identifying Assumptions

### Assumption 1: Exogenous Event Timing

FOMC meeting dates are determined by a published calendar, not by current market conditions or bank-specific shocks. The Federal Reserve's schedule is set years in advance.

**Testable implication**: Bank stock returns should be mean-zero in windows before the announcement (no anticipatory drift beyond normal trading). We test for pre-announcement abnormal returns in period [-30, -2] and report separately.

### Assumption 2: Exclusion Restriction

The Fed's rate decision affects bank equity returns only through the effect on interest rates and the yield curve, not through alternative channels.

**Potential violations**:
- **Policy signaling**: The Fed's statement may signal views on future growth or inflation, affecting equity risk premia independent of interest rates.
- **Credit cycle signaling**: Rate tightening coupled with financial stability concerns sends credit-risk signals beyond rate mechanics.

**Mitigation**: 
- We stratify by rate direction. Under the hypothesis that hikes hurt banks through margin compression and cuts help them, we expect opposite-signed β across hike and cut subsamples. Consistency with economic theory supports the rate-mechanism interpretation.
- For any announcement coupled with explicit financial stability warnings, we note it and re-estimate excluding such dates in a robustness check.

### Assumption 3: No Contemporaneous Confounding

The FOMC rate decision is not confounded by other major announcements (earnings, macro data) on the same trading day.

**Plausibility**: High. FOMC announcements are scheduled to avoid overlap with major economic releases. Bank earnings are not synchronized with FOMC dates.

**Testable**: We document any concurrent announcements and report results with and without confounded dates.

---

## Threats and Mitigation

### Threat 1: Yield Curve Non-Parallel Shifts

The Fed's rate move may affect short and long rates differently, causing yield curve flattening/steepening. Bank returns could reflect the curve shape change, not just the level effect.

**Mitigation**: In H2, ΔDGS2 captures the 2-year level change. If results are robust when we include controls for longer-term rate changes or curve slope, the evidence supports a rate-level interpretation rather than a pure yield-curve story.

### Threat 2: Risk Sentiment and Safe-Haven Flows

A Fed rate increase might signal economic overheating, causing a broad equity sell-off through rising risk premia, not through rate mechanics on bank NIMs.

**Mitigation**: Bank stocks' CAR should be larger in magnitude than the broader market (SPY) if the effect is rate-specific. We compare KBE CAR to SPY CAR as a robustness check.

### Threat 3: Multiple Events with Overlapping Windows

If two FOMC announcements occur within a short period, their event windows overlap, making it impossible to isolate the effect of each announcement.

**Mitigation**: We use an estimation window [-250, -12] that explicitly excludes the 12-day pre-event period to avoid contamination. We report whether any events have overlapping event windows [−1, +1] and exclude overlapping windows if necessary.

---

## Robustness Checks

1. **Event window sensitivity**: Verify results hold over alternative windows ([-2, +2], [0, +1], [0, +3]).

2. **Estimation window sensitivity**: Re-estimate market model over [-200, -12], [-150, -12] to check robustness to window length.

3. **Benchmark choice**: Replicate using market-adjusted model (AR = R_KBE − R_SPY, fixing β=1) as a simpler alternative.

4. **Alternative surprise measure**: If Fed futures data becomes available, compare ΔDGS2-based results to futures-based surprise measures.

5. **Subsample analysis**:
   - Exclude March 2020 emergency cuts (extreme market stress, non-typical policy).
   - Exclude March 2023 hike (overlaps with SVB crisis; conflates policy and systemic risk).

6. **Alternative asset**: Replicate using XLF (financial sector ETF) in place of KBE.

---

## Data and Estimation

- **Data**: kbe_prices, spy_prices, xlf_prices (Yahoo Finance); dgs2, dfedtaru (FRED); fomc_announcement_dates (provided).
- **Sample period**: 2015–2025 (31 FOMC announcements).
- **Market model estimation**: OLS, 238 trading days per event.
- **Regression (H2)**: OLS, heteroskedasticity-robust standard errors, separately for hikes and cuts.

