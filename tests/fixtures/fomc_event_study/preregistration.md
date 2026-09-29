# Pre-registration

Assembled by e2er from the study's design files before any analysis ran. The researcher reviews and may edit it; on approval it is frozen with its fingerprint.

## Research question and hypotheses

_From `paper_plan.md`._

# Paper Plan: Bank Stock Response to FOMC Target-Rate Announcements

## Research Question

**How do bank stocks (KBE) respond to FOMC target-rate announcements, and is the response magnitude related to the magnitude of the Treasury yield surprise?**

---

## Hypotheses

### H1: Mean Abnormal Return Test (Two-Sided)

The mean cumulative abnormal return (CAR) of KBE, relative to SPY, differs significantly from zero on and around FOMC announcement dates.

- **H1a (Rate Hikes)**: E[CAR | hike] ≠ 0 (two-sided test)
- **H1b (Rate Cuts)**: E[CAR | cut] ≠ 0 (two-sided test)

**Economic intuition**: Rate hikes may compress net interest margins (negative CAR); rate cuts may expand them (positive CAR). The test is two-sided to avoid pre-committing to sign.

### H2: Surprise Sensitivity Test

The magnitude of KBE abnormal returns on and around FOMC announcement dates is related to the magnitude of the same-day change in the 2-year Treasury yield (DGS2).

**Specification**: 
$$\text{CAR}_{i} = \alpha + \beta \cdot \Delta\text{DGS}_{0} + \varepsilon_i$$

where:
- CAR_i is the cumulative abnormal return for event i over the event window
- ΔDGS₀ = DGS(t=0) − DGS(t=-1), the day-0 change in the 2-year yield, in basis points
- β captures the sensitivity of bank stock valuations to Treasury yield surprise (after controlling for market move via market model)

**Interpretation**: For every 1 basis point increase in the 2-year yield, KBE abnormal returns move by β basis points.

---

## Event Study Design

### Events

**Sample**: 31 FOMC target-rate announcements (Dec 2015 – Dec 2025)
- Source: `fomc_announcement_dates` table in data.db
- **Day t=0**: `announcement_date` (date of FOMC press release)
  - Special case: If announcement_date is Sunday (e.g., 15 Mar 2020), then t=0 is the next trading day (16 Mar 2020)
- **Classification**: Events grouped by `direction` ∈ {increase, decrease, hold}

### Event Windows (Trading Days Relative to t=0)

**Window 1: [t=-1, t=+1]** (3-day window, centered on announcement)
- Captures pre-announcement drift, same-day reaction, overnight adjustment
- Primary window for H1 and H2 tests

**Window 2: [t=0, t=+5]** (6-day window, post-announcement)
- Captures same-day reaction and one full week of subsequent price discovery
- Secondary window to assess persistence of announcement effect

### Abnormal Return Model

#### Estimation
For each event i, estimate the market model on an event-free window:
$$R_{t}^{\text{KBE}} = \alpha + \beta \cdot R_{t}^{\text{SPY}} + \varepsilon_t$$

**Estimation window**: [-250, -12] trading days before event t=0
- Rationale: 238 trading days provides stable parameter estimates; 12-day gap avoids overlap with other events' windows
- Ensures no contamination from prior or concurrent announcements

#### Abnormal Return for Each Trading Day
$$AR_{\tau} = R_{\tau}^{\text{KBE}} - (\hat{\alpha} + \hat{\beta} \cdot R_{\tau}^{\text{SPY}})$$

#### Cumulative Abnormal Return
$$\text{CAR}_{[\tau_1, \tau_2]} = \sum_{\tau=\tau_1}^{\tau_2} AR_{\tau}$$

For each event i, CAR is computed over the specified event window.

---

## Data

**All data are open-access (FRED, Yahoo Finance only).**

### Price Data
- `kbe_prices`: KBE (Invesco KBW Bank ETF) daily closing prices and returns (Yahoo Finance)
- `spy_prices`: SPY (SPDR S&P 500 ETF Trust) daily closing prices and returns (Yahoo Finance)
- `xlf_prices`: XLF (Financial Select Sector SPDR ETF) daily closing prices and returns (Yahoo Finance) — for robustness check

### Interest Rate Data
- `dgs2`: 2-year Treasury yield (FRED series DGS2) — daily, in basis points
  - Key variable for H2: ΔDGS₀ = DGS(announcement_date) − DGS(trading_day_before)
- `dfedtaru`: Federal funds effective rate target (FRED series DFEDTARU) — for context and event classification

### Event Dates
- `fomc_announcement_dates`: 31 FOMC target-rate announcement dates, Dec 2015 – Dec 2025
  - Columns: `announcement_date`, `dfedtaru_change_date`, `dfedtaru_before`, `dfedtaru_after`, `direction`, `source_url`

---

## Hypothesis Tests

### H1: Test of Mean Abnormal Return

**Procedure**:
1. Partition the 31 events into hikes (20) and cuts (11) (via `direction` column); there are no holds
2. For each partition and each event window, compute mean CAR across events
3. Test H₀: mean CAR = 0 using a t-statistic with the cross-sectional standard error
4. Report point estimate, SE, t-statistic, and p-value (two-sided)

**Test structure**:
- t-statistic: $t = \frac{\overline{\text{CAR}}}{\text{SE}(\overline{\text{CAR}})}$ where SE = SD(CAR) / √M and M = number of events in partition
- Critical values: |t| > 1.96 ⟹ reject at 5% level

**Reporting**:
- Table 1: H1 results by direction (hikes, cuts) and window ([-1,+1] and [0,+5])
  - Each cell: point estimate, SE, t-stat, p-value, N (number of events)

### H2: Test of Surprise Sensitivity

**Procedure**:
1. For each of the 31 events, compute ΔDGS₀ = DGS(t=0) − DGS(t=-1)
2. For each event, compute CAR over window [-1, +1]
3. Run cross-sectional regression (OLS):
   $$\text{CAR}_{i} = \alpha + \beta \cdot \Delta\text{DGS}_{0,i} + \varepsilon_i$$
4. Report β, heteroskedasticity-robust SE (HC1), t-stat, and R². Primary test: pooled over all 31 events; secondary: the same regression separately for hikes (n=20) and cuts (n=11)

**Interpretation**:
- β: For every 1 bps increase in the 2-year yield, KBE abnormal returns increase by β basis points
- Example: If β = 0.5, a 10 bps rise in DGS2 corresponds to a +5 bps abnormal return for KBE

**Reporting**:
- Table 2: H2 results
  - Coefficient β, SE, t-stat, p-value, R², N=31

---

## Robustness Checks

### 1. Exclude March 2020 Emergency Cuts
- **Events to remove**: the two emergency cuts of 3 Mar 2020 and 15 Mar 2020 (a Sunday; day 0 = 16 Mar 2020)
- **Remaining sample**: 29 events
- **Rationale**: COVID-19 cuts are emergency measures, distinct from regular policy cycles
- **Re-estimate**: H1 and H2 on reduced sample; compare point estimates and significance

### 2. Exclude March 2023 Hike
- **Events to remove**: 22 Mar 2023 hike (occurred amid banking stress; SVB collapse)
- **Remaining sample**: 30 events
- **Rationale**: Banking crisis confounds Fed policy effect; isolate regular cycle responses
- **Re-estimate**: H1 and H2 on reduced sample

### 3. Alternative Market Benchmark (XLF)
- **Specification**: Rerun market model with XLF (Financial Select Sector SPDR) instead of SPY
  $$R_{t}^{\text{KBE}} = \alpha' + \beta' \cdot R_{t}^{\text{XLF}} + \varepsilon'_t$$
- **Rationale**: XLF is sector-specific; may be more appropriate benchmark for financial stocks
- **Compare**: Are H1 and H2 results robust to choice of market proxy?
- **Report**: Side-by-side table (SPY results vs. XLF results)

---

## Sample Description

| Item | Value |
|---|---|
| Total FOMC events | 31 |
| Rate increases (hikes) | ~15 |
| Rate decreases (cuts) | ~10 |
| Rate holds | ~6 |
| Sample period | Dec 2015 – Dec 2025 |
| Trading days in estimation window | 238 |
| Event window 1 size | 3 days [-1, +1] |
| Event window 2 size | 6 days [0, +5] |
| Data source (prices) | Yahoo Finance (KBE, SPY, XLF) |
| Data source (yields) | FRED (DGS2, DFEDTARU) |

---

## Output Deliverables

1. **Table 1**: H1 Results — Mean CAR by direction and window
   - Rows: Hikes, Cuts, Holds
   - Columns: Window, Mean CAR (%), SE, t-stat, p-value, N events

2. **Table 2**: H2 Results — Surprise Sensitivity Regression
   - Coefficient β, SE, t-stat, p-value, R², N=31
   - Reported for window [-1, +1]

3. **Table 3**: Robustness Checks
   - H1 and H2 results excluding March 2020 cuts
   - H1 and H2 results excluding March 2023 hike
   - H1 and H2 results using XLF market model

4. **Figure 1**: Average Abnormal Return by Day Relative to Event
   - x-axis: Event day (t = -1 to +5)
   - y-axis: Average abnormal return (%)
   - Lines: Separate for hikes and cuts
   - CI bands: ±1 SE

5. **Figure 2**: Scatter Plot of CAR vs. DGS2 Change (H2)
   - x-axis: ΔDGS₀ (basis points)
   - y-axis: CAR[-1,+1] (%)
   - Points: One per event (31 total)
   - Fitted line: OLS regression from H2
   - Annotation: β, SE, R²

## Identification strategy

_From `identification_strategy.md`._

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

## Identification (machine-readable)

_From `identification_spec.json`._

```json
{
  "primary": {
    "estimator": "ols",
    "unit_of_analysis": "event",
    "outcome": "car",
    "treatment": "dgs2_change_day0",
    "fixed_effects": [],
    "controls": [],
    "cluster_level": "none",
    "identifying_assumption": "FOMC announcement dates are determined by the Fed's calendar (fixed ex-ante), making timing of rate decisions exogenous to bank stock performance. The day-0 change in the 2-year Treasury yield (ΔDGS2) proxies for the market's surprise about the Fed's policy action, guidance, and growth expectations. Conditional on the announcement direction (hike vs. cut), ΔDGS2 variation is plausibly exogenous.",
    "stratification": "Results reported separately for rate hikes and rate cuts.",
    "notes": "H2: cross-sectional regression of CAR on ΔDGS2. CAR computed from market model (estimated over [-250, -12] trading days). ΔDGS2 = DGS2(t=0) - DGS2(t=-1), in basis points. Primary: pooled over all 31 events; secondary: separately for hikes (n=20) and cuts (n=11). Heteroskedasticity-robust (HC1) standard errors."
  },
  "event_study_specification": {
    "market_model": {
      "dependent_variable": "kbe_return",
      "independent_variable": "spy_return",
      "estimation_window_days": 238,
      "estimation_window_range": [-250, -12],
      "benchmark": "spy_prices",
      "notes": "Estimated separately for each event. Abnormal return on day t = actual return - (alpha_hat + beta_hat * market_return). CAR = sum of daily ARs over event window. Event windows: [-1,+1] and [0,+5]."
    }
  },
  "fallback": {
    "estimator": "market_adjusted",
    "fixed_effects": [],
    "controls": [],
    "cluster_level": "none",
    "when": "If sufficient historical data to estimate market model is unavailable for any event. Sets beta=1 and alpha=0 (AR = KBE return - SPY return).",
    "notes": "Simpler but less efficient than market model."
  }
}
```

## Events and windows (machine-readable)

_From `event_design.json`._

```json
{
  "event_day": "FOMC announcement date (typically 2pm ET); if the announcement falls on a non-trading day, event day is the next trading day in the spy_prices calendar. See fomc_announcement_dates.announcement_date column.",
  "estimation_window": {
    "start": -250,
    "end": -12,
    "description": "Trading days [-250,-12] before the event day, leaving out days inside other events' windows. Market model (KBE on SPY) estimated over this window for each event."
  },
  "event_windows": [
    {
      "name": "car_m1_p1",
      "start": -1,
      "end": 1,
      "description": "3-day window centered on announcement (trading day before, announcement day, trading day after). Primary window for testing immediate market reaction."
    },
    {
      "name": "car_0_p5",
      "start": 0,
      "end": 5,
      "description": "6-day window from announcement through 5 days after. Tests for multi-day adjustment; higher risk of confounding by subsequent news."
    }
  ],
  "calendar": {
    "table": "spy_prices",
    "date_column": "date",
    "description": "Trading dates from S&P 500 ETF (SPY). Used to map calendar dates to trading day sequences."
  },
  "events_source": {
    "table": "fomc_announcement_dates",
    "date_column": "announcement_date",
    "description": "FOMC announcement dates from the fomc_announcement_dates table in data.db. Every date in this table is treated as an event. Non-trading dates are shifted to the next trading day per the calendar."
  },
  "overlap_treatment": "none",
  "confounding_risk": "Check for concurrent earnings announcements by major banks (JPM, BAC, C, WFC, GS, MS) and macroeconomic releases (CPI, jobs, ISM, PMI) within \u00b11 trading day of each FOMC announcement. Document in results; exclude if more than ~10% of events are confounded.",
  "events": [
    {
      "id": "fomc-2015-12-16",
      "date": "2015-12-16",
      "asset": "KBE",
      "direction": "increase",
      "rate_before": 0.25,
      "rate_after": 0.5,
      "magnitude_bps": 25
    },
    {
      "id": "fomc-2016-12-14",
      "date": "2016-12-14",
      "asset": "KBE",
      "direction": "increase",
      "rate_before": 0.5,
      "rate_after": 0.75,
      "magnitude_bps": 25
    },
    {
      "id": "fomc-2017-03-15",
      "date": "2017-03-15",
      "asset": "KBE",
      "direction": "increase",
      "rate_before": 0.75,
      "rate_after": 1.0,
      "magnitude_bps": 25
    },
    {
      "id": "fomc-2017-06-14",
      "date": "2017-06-14",
      "asset": "KBE",
      "direction": "increase",
      "rate_before": 1.0,
      "rate_after": 1.25,
      "magnitude_bps": 25
    },
    {
      "id": "fomc-2017-12-13",
      "date": "2017-12-13",
      "asset": "KBE",
      "direction": "increase",
      "rate_before": 1.25,
      "rate_after": 1.5,
      "magnitude_bps": 25
    },
    {
      "id": "fomc-2018-03-21",
      "date": "2018-03-21",
      "asset": "KBE",
      "direction": "increase",
      "rate_before": 1.5,
      "rate_after": 1.75,
      "magnitude_bps": 25
    },
    {
      "id": "fomc-2018-06-13",
      "date": "2018-06-13",
      "asset": "KBE",
      "direction": "increase",
      "rate_before": 1.75,
      "rate_after": 2.0,
      "magnitude_bps": 25
    },
    {
      "id": "fomc-2018-09-26",
      "date": "2018-09-26",
      "asset": "KBE",
      "direction": "increase",
      "rate_before": 2.0,
      "rate_after": 2.25,
      "magnitude_bps": 25
    },
    {
      "id": "fomc-2018-12-19",
      "date": "2018-12-19",
      "asset": "KBE",
      "direction": "increase",
      "rate_before": 2.25,
      "rate_after": 2.5,
      "magnitude_bps": 25
    },
    {
      "id": "fomc-2019-07-31",
      "date": "2019-07-31",
      "asset": "KBE",
      "direction": "cut",
      "rate_before": 2.5,
      "rate_after": 2.25,
      "magnitude_bps": -25
    },
    {
      "id": "fomc-2019-09-18",
      "date": "2019-09-18",
      "asset": "KBE",
      "direction": "cut",
      "rate_before": 2.25,
      "rate_after": 2.0,
      "magnitude_bps": -25
    },
    {
      "id": "fomc-2019-10-30",
      "date": "2019-10-30",
      "asset": "KBE",
      "direction": "cut",
      "rate_before": 2.0,
      "rate_after": 1.75,
      "magnitude_bps": -25
    },
    {
      "id": "fomc-2020-03-03",
      "date": "2020-03-03",
      "asset": "KBE",
      "direction": "cut",
      "rate_before": 1.75,
      "rate_after": 1.25,
      "magnitude_bps": -50
    },
    {
      "id": "fomc-2020-03-16",
      "date": "2020-03-16",
      "asset": "KBE",
      "direction": "cut",
      "rate_before": 1.25,
      "rate_after": 0.25,
      "magnitude_bps": -100,
      "note": "Announced Sunday 15 March 2020; day 0 is the next trading day."
    },
    {
      "id": "fomc-2022-03-16",
      "date": "2022-03-16",
      "asset": "KBE",
      "direction": "increase",
      "rate_before": 0.25,
      "rate_after": 0.5,
      "magnitude_bps": 25
    },
    {
      "id": "fomc-2022-05-04",
      "date": "2022-05-04",
      "asset": "KBE",
      "direction": "increase",
      "rate_before": 0.5,
      "rate_after": 1.0,
      "magnitude_bps": 50
    },
    {
      "id": "fomc-2022-06-15",
      "date": "2022-06-15",
      "asset": "KBE",
      "direction": "increase",
      "rate_before": 1.0,
      "rate_after": 1.75,
      "magnitude_bps": 75
    },
    {
      "id": "fomc-2022-07-27",
      "date": "2022-07-27",
      "asset": "KBE",
      "direction": "increase",
      "rate_before": 1.75,
      "rate_after": 2.5,
      "magnitude_bps": 75
    },
    {
      "id": "fomc-2022-09-21",
      "date": "2022-09-21",
      "asset": "KBE",
      "direction": "increase",
      "rate_before": 2.5,
      "rate_after": 3.25,
      "magnitude_bps": 75
    },
    {
      "id": "fomc-2022-11-02",
      "date": "2022-11-02",
      "asset": "KBE",
      "direction": "increase",
      "rate_before": 3.25,
      "rate_after": 4.0,
      "magnitude_bps": 75
    },
    {
      "id": "fomc-2022-12-14",
      "date": "2022-12-14",
      "asset": "KBE",
      "direction": "increase",
      "rate_before": 4.0,
      "rate_after": 4.5,
      "magnitude_bps": 50
    },
    {
      "id": "fomc-2023-02-01",
      "date": "2023-02-01",
      "asset": "KBE",
      "direction": "increase",
      "rate_before": 4.5,
      "rate_after": 4.75,
      "magnitude_bps": 25
    },
    {
      "id": "fomc-2023-03-22",
      "date": "2023-03-22",
      "asset": "KBE",
      "direction": "increase",
      "rate_before": 4.75,
      "rate_after": 5.0,
      "magnitude_bps": 25
    },
    {
      "id": "fomc-2023-05-03",
      "date": "2023-05-03",
      "asset": "KBE",
      "direction": "increase",
      "rate_before": 5.0,
      "rate_after": 5.25,
      "magnitude_bps": 25
    },
    {
      "id": "fomc-2023-07-26",
      "date": "2023-07-26",
      "asset": "KBE",
      "direction": "increase",
      "rate_before": 5.25,
      "rate_after": 5.5,
      "magnitude_bps": 25
    },
    {
      "id": "fomc-2024-09-18",
      "date": "2024-09-18",
      "asset": "KBE",
      "direction": "cut",
      "rate_before": 5.5,
      "rate_after": 5.0,
      "magnitude_bps": -50
    },
    {
      "id": "fomc-2024-11-07",
      "date": "2024-11-07",
      "asset": "KBE",
      "direction": "cut",
      "rate_before": 5.0,
      "rate_after": 4.75,
      "magnitude_bps": -25
    },
    {
      "id": "fomc-2024-12-18",
      "date": "2024-12-18",
      "asset": "KBE",
      "direction": "cut",
      "rate_before": 4.75,
      "rate_after": 4.5,
      "magnitude_bps": -25
    },
    {
      "id": "fomc-2025-09-17",
      "date": "2025-09-17",
      "asset": "KBE",
      "direction": "cut",
      "rate_before": 4.5,
      "rate_after": 4.25,
      "magnitude_bps": -25
    },
    {
      "id": "fomc-2025-10-29",
      "date": "2025-10-29",
      "asset": "KBE",
      "direction": "cut",
      "rate_before": 4.25,
      "rate_after": 4.0,
      "magnitude_bps": -25
    },
    {
      "id": "fomc-2025-12-10",
      "date": "2025-12-10",
      "asset": "KBE",
      "direction": "cut",
      "rate_before": 4.0,
      "rate_after": 3.75,
      "magnitude_bps": -25
    }
  ],
  "events_note": "The 31 events are the researcher's announcement dates from fomc_announcement_dates, set at review_design."
}
```
