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
1. Partition the 31 events into hikes, cuts, and holds (via `direction` column)
2. For each partition and each event window, compute mean CAR across events
3. Test H₀: mean CAR = 0 using t-statistic with Patell or cross-sectional standard error
4. Report point estimate, SE, t-statistic, and p-value (two-sided)

**Test structure**:
- t-statistic: $t = \frac{\overline{\text{CAR}}}{\text{SE}(\overline{\text{CAR}})}$ where SE = SD(CAR) / √M and M = number of events in partition
- Critical values: |t| > 1.96 ⟹ reject at 5% level

**Reporting**:
- Table 1: H1 results by direction (hikes, cuts, holds) and window ([-1,+1] and [0,+5])
  - Each cell: point estimate, SE, t-stat, p-value, N (number of events)

### H2: Test of Surprise Sensitivity

**Procedure**:
1. For each of the 31 events, compute ΔDGS₀ = DGS(t=0) − DGS(t=-1)
2. For each event, compute CAR over window [-1, +1]
3. Run cross-sectional regression (OLS):
   $$\text{CAR}_{i} = \alpha + \beta \cdot \Delta\text{DGS}_{0,i} + \varepsilon_i$$
4. Report β, SE (Newey-West lag=1), t-stat, and R²

**Interpretation**:
- β: For every 1 bps increase in the 2-year yield, KBE abnormal returns increase by β basis points
- Example: If β = 0.5, a 10 bps rise in DGS2 corresponds to a +5 bps abnormal return for KBE

**Reporting**:
- Table 2: H2 results
  - Coefficient β, SE, t-stat, p-value, R², N=31

---

## Robustness Checks

### 1. Exclude March 2020 Emergency Cuts
- **Events to remove**: Announcements on/around 3, 15, and 16 Mar 2020 (3 rapid cuts during COVID-19 crisis)
- **Remaining sample**: ~28 events
- **Rationale**: COVID-19 cuts are emergency measures, distinct from regular policy cycles
- **Re-estimate**: H1 and H2 on reduced sample; compare point estimates and significance

### 2. Exclude March 2023 Hike
- **Events to remove**: 22 Mar 2023 hike (occurred amid banking stress; SVB collapse)
- **Remaining sample**: ~30 events
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
