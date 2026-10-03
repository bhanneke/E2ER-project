# Data Summary: Bank Stock Response to FOMC Target-Rate Announcements

## Research Context

This dataset supports an event-study analysis of how US bank stocks (proxied by the KBE sector ETF) respond to Federal Reserve target-rate announcements from December 2015 through December 2025. The data span extends from January 2014 to ensure the first event (2015-12-16) has a full 250-trading-day estimation window for the market model. The study examines whether announcement-day price reactions differ by announcement type (rate increase vs. cut) and whether abnormal returns correlate with the magnitude of same-day Treasury yield surprise.

---

## Data Sources & Tables

### Primary Data Sources

| Table | Source | Rows | Coverage | Role |
|-------|--------|------|----------|------|
| `fomc_announcement_dates` | Local warehouse (researcher-supplied) | 31 | 2015-12-16 to 2025-12-10 | Event dates; announcement details |
| `kbe_prices` | Yahoo Finance | 3,017 | 2014-01-02 to 2025-12-30 | Bank sector ETF daily OHLCV |
| `spy_prices` | Yahoo Finance | 3,017 | 2014-01-02 to 2025-12-30 | Market baseline (S&P 500) daily OHLCV |
| `xlf_prices` | Yahoo Finance | 3,017 | 2014-01-02 to 2025-12-30 | Robustness check (financials sector) daily OHLCV |
| `dgs2` | FRED | 2,870 | 2015-01-01 to 2025-12-31 | 2-year Treasury constant-maturity yield; 2,750 non-null values |
| `dfedtaru` | FRED | 2,765 | 2015-01-02 to 2025-12-30 | Federal Funds Target Rate Upper Bound; daily |

### Events Table: `fomc_announcement_dates`

**Sample construction:**
- Raw: 31 FOMC target-rate announcements, Dec 2015 – Dec 2025
- Direction: classified as `increase` (20 events) or `cut` (11 events)
- Key variable: `announcement_date` (date of FOMC press release)
  - Special handling: If announcement_date falls on a Sunday (e.g., 2020-03-15), t=0 is the next trading day (2020-03-16)
- Each event associated with:
  - `dfedtaru_before`: Fed Funds rate before announcement (basis points)
  - `dfedtaru_after`: Fed Funds rate after announcement (basis points)
  - `direction`: {'increase', 'cut'}

---

## Variable Definitions

### Price & Return Variables

**Daily Close-to-Close Returns** (3 series):
- `r_kbe_t`: KBE daily return = ln(close_t) − ln(close_{t−1})
- `r_spy_t`: SPY daily return (market baseline)
- `r_xlf_t`: XLF daily return (financials robustness)

**Treasury Yield:**
- `dgs2_t`: 2-year Treasury yield (basis points, from FRED)
- `Δdgs2_0`: announcement-day change in 2-year yield = DGS2(t=0) − DGS2(t=−1)

**Abnormal & Cumulative Abnormal Returns:**
- Estimated market model for each event i over estimation window [t=−250, t=−12]:
  $$R_{\text{KBE},t} = \alpha_i + \beta_i \cdot R_{\text{SPY},t} + \varepsilon_{i,t}$$
  
- Abnormal return on trading day τ in event i's window:
  $$AR_{i,\tau} = R_{\text{KBE},\tau} − (\hat{\alpha}_i + \hat{\beta}_i \cdot R_{\text{SPY},\tau})$$
  
- Cumulative abnormal return (CAR) over window [τ₁, τ₂]:
  $$\text{CAR}_{i, [τ₁,τ₂]} = \sum_{\tau=τ₁}^{τ₂} AR_{i,\tau}$$

### Event-Study Windows (Trading Days Relative to t=0)

| Window | Days | Purpose |
|--------|------|---------|
| Estimation | [−250, −12] | Market model parameter estimation; 238 trading days; gap of 12 days ensures no event contamination |
| H1 Window | [−1, +1] | Hypothesis 1 (mean CAR test): 3-day window centered on announcement |
| H2 Window | [0, +5] | Hypothesis 2 sensitivity: 6-day post-announcement window |

---

## Sample Construction & Missingness

### Event Sample
- **Total events:** 31 FOMC announcements (no filters applied)
- **By direction:** 
  - Rate increases: 20 events
  - Rate cuts: 11 events
  
### Trading Day Requirements
- **Market model estimation:** minimum 238 trading days available in [−250, −12] window
  - Typically satisfied: 2015–2025 is post-2008, no major market closures
  - Action if violated: exclude event and report
  
- **Price data:** KBE, SPY daily closes available for all event-study dates
  - Yahoo Finance coverage: daily from 2014 onward (sufficient)
  
- **Yield data:** DGS2 daily observations for all event study dates
  - FRED coverage: daily from 1962 onward (sufficient)

### Handling of Missing Values
- **Missing daily prices:** If a date is not a trading day (weekend, US holiday), skip it (common in finance)
- **Missing yields:** If DGS2 value is `null` for announcement day, impute with prior trading day close (forward-fill one day max)
  - Expected: rare (<0.5% of events)

---

## Analysis Dataset Structure (Post-Cleaning)

### Level of Observation
- **Unit of analysis:** Event i = 1, 2, ..., 31
- **Sub-unit:** Trading day τ relative to event i (e.g., τ ∈ {−250, ..., −12, −1, 0, +1, ..., +5})

### Key Derived Variables (Event-Level)
- `event_id`: unique event identifier (1–31)
- `announcement_date`: calendar date of FOMC press release
- `trading_day_0`: adjustment if announcement_date is Sunday
- `direction`: {'increase', 'decrease', 'hold'}
- `dfedtaru_change`: absolute change in Fed Funds target, basis points
- `dgs2_change_day0`: ΔDG S2 on announcement day, basis points
- `car_minus1_plus1`: CAR over [−1, +1] window
- `car_0_plus5`: CAR over [0, +5] window
- `alpha_i`, `beta_i`: market model parameters for event i

### Data Quality Checks
1. ✓ All 31 events have non-null announcement_date and direction
2. ✓ Price series (KBE, SPY, XLF) have no missing daily closes; fully populated (3,017 obs each)
3. ✓ **DGS2 observations: 2,870 rows, 2,750 non-null values** (loaded from FRED by researcher after initial data analyst load failed)
4. ✓ DFEDTARU fully populated (2,765 obs, all non-null)
5. ✓ Market model parameter estimation window has ≥238 observations per event (price data available from 2014-01-02)
6. ✓ No duplicate events (announcement_date is unique key)

---

## Planned Analysis

### Event Sample
- **Total events**: 31 FOMC target-rate announcements, December 2015 – December 2025
- **By direction**: To be summarized after loading
  - Rate increases (expected ~8–10 events)
  - Rate decreases (expected ~15–18 events)
  - Rate holds (expected 0–2 events)

### Confirmation Checks
Once data is loaded into data.db:
1. All price series (KBE, SPY, XLF) have no missing daily closes from 2014-01-02 to 2025-12-31
2. Yield series (DGS2, DFEDTARU) have valid daily observations over the same period
3. Each of 31 events has ≥238 trading-day observations in estimation window [−250, −12]
4. Special date handling confirmed: if FOMC announcement is Sunday, next trading day is t=0

---

## Estimation & Robustness

### Primary Specification
- Market model: KBE returns regressed on SPY returns
- Event window: [−1, +1] and [0, +5]
- Hypotheses: H1 (mean CAR ≠ 0 by direction), H2 (CAR vs. ΔDG S2)

### Robustness Checks
1. **Exclude March 2020 emergency cuts** (pandemic policy response)
2. **Exclude March 2023 hike** (bank distress period, SVB collapse)
3. **Alternative baseline:** Use XLF instead of SPY

---

## Data Provenance & Citation

All price and yield data obtained from public APIs with no cost or licensing restrictions:
- **Yahoo Finance** (via `yfinance` Python library): KBE, SPY, XLF daily OHLCV
- **FRED** (Federal Reserve Economic Data): DGS2 (requires API key — currently placeholder with null values), DFEDTARU (derived from FOMC data)
- **Local warehouse:** FOMC announcement dates and details (researcher-supplied)

All data acquired and processed on 2026-09-29.

### Data Status Notes

**Data Status**: All required tables are loaded and ready for analysis.

- **dgs2 table**: 2-year Treasury constant-maturity yield from FRED. 2,870 observations (2,750 non-null values covering trading days and excluding market holidays), 2015-01-01 to 2025-12-31. Loaded from FRED by the researcher after the initial data analyst load failed. Used for H2 regression (CAR vs. same-day yield surprise).
- **dfedtaru table**: Federal Funds Target Rate Upper Bound from FRED, 2015-01-02 to 2025-12-30. Fully populated (2,765 non-null values, range 25.0–550.0 basis points). Used for policy state tracking.
- **Price data (kbe_prices, spy_prices, xlf_prices)**: Fully populated (3,017 obs each), 2014-01-02 to 2025-12-30.
