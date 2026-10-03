# Econometric Specification: Bank Stock Response to FOMC Target-Rate Announcements

## Research Question

How do US bank stocks (KBE) respond to FOMC target-rate announcements, and is the response magnitude related to the same-day change in Treasury yields?

---

## Event Study Design

### Sample and Events

**Event population**: All FOMC target-rate announcements from December 2015 through December 2025.

**Source**: `fomc_announcement_dates` table (31 events total).

**Event day (t=0)**: The `announcement_date` from the table. When an announcement falls on a non-trading day (e.g., Sunday March 15, 2020), t=0 is moved to the next trading day (March 16, 2020). This adjustment is already applied in the source table under `dfedtaru_change_date`.

**Classification by direction** (from `direction` column):
- **Rate increases (hikes)**: 20 events
- **Rate decreases (cuts)**: 11 events

Trading-day dates are verified against the SPY price calendar (`spy_prices` table).

### Event Windows (Relative to t=0)

Two windows are examined:

1. **Window 1: [t=-1, t=+1]** (3-day window)
   - Captures pre-announcement drift, same-day announcement reaction, and overnight adjustment
   - Primary specification for hypothesis tests

2. **Window 2: [t=0, t=+5]** (6-day window)
   - Captures same-day reaction and one full week of subsequent price discovery
   - Secondary specification to assess persistence

### Estimation Window

For each event i, estimate the market model over the interval **[t=-250, t=-12]** trading days relative to t=0.

**Rationale**:
- Window of 238 trading days (approximately 1 year) provides stable parameter estimates while minimizing structural break risk.
- 12-day gap before event window prevents contamination from pre-announcement leakage or overlap with other events' windows.
- The first event (December 16, 2015) requires data back to approximately March 2015; the first FOMC event must have at least 250 trading days of prior data.

**Exclusion rule**: If an earlier event's event window [t=-1, t=+5] overlaps with the estimation window [t=-250, t=-12] of a later event, the earlier event is excluded from that later event's estimation sample. This preserves the market model's estimation under the assumption of no event contamination.

---

## Abnormal Return Model

### Market Model

For each event i and trading day τ relative to t=0, the (log) return on the KBE ETF is modeled as:

$$R_{i,\tau}^{\text{KBE}} = \alpha_i + \beta_i \cdot R_{i,\tau}^{\text{SPY}} + \varepsilon_{i,\tau}$$

**Parameters**:
- $\alpha_i$: intercept (Jensen's alpha)
- $\beta_i$: market beta (KBE's sensitivity to SPY returns)
- $\varepsilon_{i,\tau}$: idiosyncratic error

**Estimation**: OLS regression over the estimation window [t=-250, t=-12] for each event i.

**Requirements**:
- Minimum of 100 non-missing observations in the estimation window (to ensure stable parameter estimates).
- Both KBE and SPY closing prices are available.

### Abnormal Return

For trading day τ within an event window, the abnormal return is:

$$AR_{i,\tau} = R_{i,\tau}^{\text{KBE}} - \left( \hat{\alpha}_i + \hat{\beta}_i \cdot R_{i,\tau}^{\text{SPY}} \right)$$

The fitted value $\hat{\alpha}_i + \hat{\beta}_i \cdot R_{i,\tau}^{\text{SPY}}$ is the expected return absent the event.

### Cumulative Abnormal Return

Over event window [τ₁, τ₂], the cumulative abnormal return is:

$$\text{CAR}_{i}[\tau_1, \tau_2] = \sum_{\tau = \tau_1}^{\tau_2} AR_{i,\tau}$$

Two CARs are computed for each event:
- $\text{CAR}_{i}[-1, +1]$: 3-day CAR
- $\text{CAR}_{i}[0, +5]$: 6-day CAR

---

## Hypothesis 1: Mean Abnormal Return Test

**Null hypothesis**: The mean cumulative abnormal return equals zero.

**Design**: The null hypothesis is tested separately for rate hikes and rate cuts (two-sided tests).

### Sub-hypothesis H1a: Rate Hikes

$$H0: \mathbb{E}[\text{CAR}_{i}[-1, +1] | \text{hike}] = 0$$

**Sample**: n = 20 rate hikes

**Test statistic**:

$$t_{\text{H1a}} = \frac{\bar{\text{CAR}}_{\text{hikes}}[-1, +1]}{SE(\bar{\text{CAR}}_{\text{hikes}})}$$

**Standard error** (cross-sectional):

$$SE(\bar{\text{CAR}}_{\text{hikes}}) = \frac{S_{\text{CAR,hikes}}}{\sqrt{n_{\text{hikes}}}}$$

$$S_{\text{CAR,hikes}} = \sqrt{\frac{1}{n_{\text{hikes}}-1} \sum_{i \in \text{hikes}} \left( \text{CAR}_i - \bar{\text{CAR}}_{\text{hikes}} \right)^2}$$

**Degrees of freedom**: df = n_hikes – 1 = 19

**Distribution under H₀**: t-distribution with 19 degrees of freedom.

**Inference**: Two-sided test at the 5% significance level. Reject H₀ if $|t_{\text{H1a}}| > t_{0.025, 19} \approx 2.093$.

**P-value**: Computed as $2 \times P(t_{19} \geq |t_{\text{H1a}}|)$ via scipy.stats.t.sf or statsmodels.

### Sub-hypothesis H1b: Rate Cuts

$$H0: \mathbb{E}[\text{CAR}_{i}[-1, +1] | \text{cut}] = 0$$

**Sample**: n = 11 rate cuts

**Test statistic**:

$$t_{\text{H1b}} = \frac{\bar{\text{CAR}}_{\text{cuts}}[-1, +1]}{SE(\bar{\text{CAR}}_{\text{cuts}})}$$

**Degrees of freedom**: df = n_cuts – 1 = 10

**Distribution under H₀**: t-distribution with 10 degrees of freedom.

**Inference**: Two-sided test at the 5% significance level. Reject H₀ if $|t_{\text{H1b}}| > t_{0.025, 10} \approx 2.228$.

**P-value**: Computed as $2 \times P(t_{10} \geq |t_{\text{H1b}}|)$ via scipy.stats.t.sf or statsmodels.

### Secondary Event Window [0, +5]

The same tests (H1a and H1b) are also performed over the secondary event window [0, +5] to assess the persistence of announcement effects. Results are reported separately for this window.

**Interpretation**:
- If $t_{\text{H1a}}$ is significantly negative, this suggests that rate hikes compress bank valuations (consistent with net interest margin compression).
- If $t_{\text{H1b}}$ is significantly positive, this suggests that rate cuts expand bank valuations (consistent with net interest margin expansion).
- A non-significant test does not imply no effect; it indicates the effect is not distinguishable from zero at the 5% level given the cross-sectional variation.

---

## Hypothesis 2: Surprise Sensitivity Test

**Null hypothesis**: Abnormal returns are not correlated with the surprise component of the FOMC announcement (measured by the same-day change in the 2-year Treasury yield).

**Surprise measure**: The change in the 2-year Treasury yield on the announcement date t=0.

$$\Delta \text{DGS2}_{i} = [\text{DGS2}(t=0) - \text{DGS2}(t=-1)] \times 100$$

where DGS2 is the constant maturity 2-year Treasury yield from the Federal Reserve Economic Data (FRED).

**Units**: Basis points. (FRED reports DGS2 in percent per annum; multiply by 100 to convert to bps.)

### Regression Specification

$$\text{CAR}_{i}[-1, +1] = \alpha + \beta \cdot \Delta \text{DGS2}_{i} + \varepsilon_i$$

**Parameters**:
- $\alpha$: intercept
- $\beta$: sensitivity of KBE abnormal returns (in %) to Treasury yield surprise (in bps)

**Interpretation**:
- $\beta$ measures the percentage-point change in KBE abnormal returns for each 1 basis point increase in the 2-year yield.
- Example: If β = 0.5 and ΔDG S2 = 10 bps, predicted CAR = 0.5 × 10 = 5%.
- Positive $\beta$: bank stocks appreciate when yields rise (suggests yield-driven expectations outweigh margin compression).
- Negative $\beta$: bank stocks depreciate when yields rise (suggests margin compression concerns dominate).

### Estimation and Inference

**Primary analysis** (H2: all 31 events, pooled):
- Estimator: OLS.
- Standard errors: Heteroskedasticity-consistent (HC1), *not clustered*.
- Sample size: 31 events.
- Degrees of freedom: df = 31 – 2 = 29.
- **This is the pre-registered primary test.**

**Test statistic**:

$$t_{\beta, \text{H2}} = \frac{\hat{\beta}}{SE_{\text{HC1}}(\hat{\beta})}$$

**Inference**: Two-sided test at the 5% significance level. Reject $H_0: \beta = 0$ if $|t_{\beta, \text{H2}}| > t_{0.025, 29} \approx 2.045$.

**P-value**: Computed as $2 \times P(t_{29} \geq |t_{\beta, \text{H2}}|)$ via scipy.stats.t.sf or statsmodels.

**Reporting**:
- Point estimate $\hat{\beta}$, HC1 standard error, t-statistic, two-sided p-value, 95% confidence interval, R², and N.

### Secondary analysis (stratified by direction):

Separately estimate the regression for rate hikes and rate cuts to examine heterogeneity in the yield-surprise response:

**H2 (Hikes): Separate regression for rate hikes (n=20)**
$$t_{\beta, \text{hikes}} = \frac{\hat{\beta}_{\text{hikes}}}{SE_{\text{HC1}}(\hat{\beta}_{\text{hikes}})}$$

- Degrees of freedom: df = 20 – 2 = 18

**H2 (Cuts): Separate regression for rate cuts (n=11)**
$$t_{\beta, \text{cuts}} = \frac{\hat{\beta}_{\text{cuts}}}{SE_{\text{HC1}}(\hat{\beta}_{\text{cuts}})}$$

- Degrees of freedom: df = 11 – 2 = 9

**Interpretation**:
- Hikes and cuts may show opposite-signed slopes if the yield move has asymmetric effects on bank valuations (e.g., margin expansion on cuts but compression on hikes, or vice versa).
- **These are secondary/exploratory; the primary test is pooled over all 31 events.**

---

## Robustness Checks

### Robustness 1: Alternative Benchmark (XLF)

Repeat all H1 and H2 analyses with the Financial Select Sector SPDR (XLF), a sector-level benchmark, in place of SPY.

**Rationale**: XLF is a broad portfolio of financial stocks, which may better capture systematic risk in the financial sector. Bank-specific abnormal returns relative to the sector (XLF) may differ from returns relative to the broad market (SPY).

**Data source**: `xlf_prices` table.

**Specification**:
- Market model: $R_{i,\tau}^{\text{KBE}} = \alpha_i + \beta_i \cdot R_{i,\tau}^{\text{XLF}} + \varepsilon_{i,\tau}$
- Re-run H1 tests (mean CAR tests for pooled, hikes, cuts) using XLF-based abnormal returns
- Re-run H2 tests (surprise sensitivity regression) using XLF-based abnormal returns

### Robustness 2: Excluding March 2020 Emergency Cuts

The COVID-19 pandemic triggered emergency FOMC rate cuts in March 2020, which may represent a regime shift.

**Procedure**:
- Identify all FOMC events in March 2020 from the `fomc_announcement_dates` table (fomc-2020-03-03 and fomc-2020-03-16)
- Drop these two events; re-run H1 and H2 tests with reduced sample (N = 29 events; 18 hikes, 11 cuts)

**Rationale**: Emergency cuts during a liquidity crisis may have different market dynamics than regular policy adjustments.

### Robustness 3: Excluding March 2023 Hike

The March 2023 FOMC rate hike occurred during regional banking stress (SVB failure).

**Procedure**:
- Identify the March 16, 2023 FOMC hike from the `fomc_announcement_dates` table
- Drop this event; re-run H1 and H2 tests with reduced sample (N = 30 events)

**Rationale**: Heightened financial stability concerns may confound the monetary policy response.

---

## Diagnostic Checks and Assumptions

### Assumption 1: Event Independence (No Spillovers)

**Assumption**: The announcement effect on one event does not carry over to affect abnormal returns in another event (no violations of Stable Unit Treatment Value Assumption, SUTVA).

**Check**: Verify that the 12-day gap between the event window [t=-1, t=+1] (3 days) and the next event's estimation window start is sufficient. For 31 events spanning 10 years, with an average of ~9 events per year (0.75/month), the 12-day buffer is adequate except in rare cases of back-to-back FOMC meetings.

**Action if violated**: Drop the second event in a pair if windows overlap.

### Assumption 2: Market Model Stability (No Structural Breaks)

**Assumption**: The parameters ($\alpha_i$, $\beta_i$) estimated over [-250, -12] remain valid during the event window.

**Check**: 
- Verify that major macroeconomic or market shocks (e.g., equity market crashes, major financial crises) did not occur between the estimation window and event window.
- Report the estimation-window dates for each event.

**Diagnostic**: Compute the first-stage R² for the market model. Expect R² > 0.85 for a broad market index like SPY (typical range: 0.8–0.95).

### Assumption 3: Normality and Homoskedasticity of Idiosyncratic Returns

**Assumption**: The residuals $\varepsilon_{i,\tau}$ are approximately normally distributed with constant variance.

**Justification for robustness**: We use HC1 standard errors in H2 (Hypothesis 2) to guard against heteroskedasticity violations. We do not assume normality for significance testing of mean CARs (cross-sectional t-test), which is robust under the Central Limit Theorem with N=31 events.

**Diagnostic**: Report the distribution of residuals (skewness, kurtosis) from a sample of market-model regressions.

### Assumption 4: Correct Identification of Event Day

**Assumption**: The announcement date in `fomc_announcement_dates` is the date on which the market learns of the policy decision, and t=0 correctly identifies the first trading day on or after the announcement.

**Check**: 
- Verify that all announcement dates are correctly mapped to trading days.
- Spot-check a few events (e.g., March 15–16, 2020) against FOMC press release dates and trading calendars.

---

---

## Estimation Details and Reporting

### Market Model Estimation (Per Event)

For each event i:

1. Identify the estimation window [t=-250, t=-12] in trading days.
2. Extract daily closing prices for KBE and SPY over this window.
3. Compute log-returns: $R_t = \ln(\text{Price}_t) - \ln(\text{Price}_{t-1})$.
4. Regress KBE returns on SPY returns (with constant) via OLS.
5. Retain the regression output: $\hat{\alpha}_i$, $\hat{\beta}_i$, residual standard error $S_i$, R², observations count.
6. Check for sufficient data (≥100 observations).

### Abnormal Return Computation (Per Event, Per Window)

1. Extract daily returns over the event window.
2. Compute expected returns using the estimated market model.
3. Compute abnormal returns as actual minus expected.
4. Sum abnormal returns to obtain CAR.

### Hypothesis 1 Testing

1. **Pooled test**: Compute $\bar{\text{CAR}}[-1, +1]$, $S_{\text{CAR}}$, and $t$-statistic across all 31 events.
2. **Stratified tests**: Repeat for hikes (n=20) and cuts (n=11).
3. Report: mean CAR, standard deviation, standard error, t-statistic, p-value, 95% confidence interval.

### Hypothesis 2 Testing

1. **Merge data**: Match each event to its announcement date; fetch the DGS2 values for t=-1 and t=0.
2. **Compute surprises**: $\Delta \text{DGS2}_i = \text{DGS2}(t=0) - \text{DGS2}(t=-1)$ in basis points.
3. **OLS regression**: $\text{CAR}[-1, +1]$ on $\Delta \text{DGS2}$ with constant, using HC1 standard errors.
4. **Report**: Coefficient $\hat{\beta}$, HC1 SE, t-statistic, p-value, 95% CI, R², adjusted R², sample size.
5. **Stratified regressions**: Repeat separately for hikes and cuts.

### Diagnostic Reporting

For each specification, report:
- Number of events (N).
- Date range of events.
- Average estimation-window R² and range.
- Average market beta and range.
- Pre-event mean CAR (t=-10 to t=-2) to check for anticipation bias.

---

## Output Format

### Main Results Table

| Specification | N | Mean CAR [-1,+1] (%) | SD | SE | t-stat | p-value | 95% CI |
|---|---|---|---|---|---|---|---|
| All Events | 31 | [α̂] | [SD] | [SE] | [t] | [p] | [CI] |
| Rate Hikes | 20 | [α̂] | [SD] | [SE] | [t] | [p] | [CI] |
| Rate Cuts | 11 | [α̂] | [SD] | [SE] | [t] | [p] | [CI] |

### Surprise Sensitivity Regression (H2)

| Specification | N | Constant | Coeff. on ΔDG S2 | SE | t-stat | p-value | 95% CI | R² |
|---|---|---|---|---|---|---|---|---|
| Pooled | 31 | [ĉ] | [β̂] | [SE] | [t] | [p] | [CI] | [R²] |
| Hikes | 20 | [ĉ] | [β̂] | [SE] | [t] | [p] | [CI] | [R²] |
| Cuts | 11 | [ĉ] | [β̂] | [SE] | [t] | [p] | [CI] | [R²] |

---

## References

MacKinlay, A. C. (1997). "Event studies in economics and finance." *Journal of Economic Literature*, 35(1), 13–39.

Campbell, J. Y., Lo, A. W., & MacKinlay, A. C. (1997). *The Econometrics of Financial Markets*. Princeton University Press.

Boehmer, E., Musumeci, J., & Poulsen, A. B. (1991). "Event-study methodology under conditions of event-induced variance." *Journal of Financial Economics*, 30(2), 253–272.

Kothari, S. P., & Warner, J. B. (2007). "Econometrics of event studies." In B. E. Eckbo (Ed.), *Handbook of Corporate Finance: Empirical Corporate Finance* (Vol. 1, pp. 3–36). Elsevier.

Fama, E. F., & MacBeth, J. D. (1973). "Risk, return, and equilibrium: Empirical tests." *Journal of Political Economy*, 81(3), 607–636.

White, H. (1980). "A heteroskedasticity-consistent covariance matrix estimator and a direct test for heteroskedasticity." *Econometrica*, 48(4), 817–838.

---

## Implementation Notes

### P-value Computation

All p-values are computed using `scipy.stats.t.sf()` (survival function), which correctly implements:
- Two-sided p-value: 2 × P(T > |t_obs|) where T ~ t(df)
- Degrees of freedom: reported in each result entry for each hypothesis

### Execution Status

- **H1 (Mean CAR tests)**: ✓ **Complete**. Estimated on all 31 events, both windows [-1,+1] and [0,+5], stratified by rate direction (hikes and cuts). Results available in `estimation_results.json` with hypothesis_id, n_events, df, and all statistics. P-values computed using scipy.stats.t-distribution with degrees of freedom as reported.

- **H2 (Surprise Sensitivity)**: ✓ **Complete**. The 2-year Treasury yield series (FRED DGS2) was loaded by the researcher into the `dgs2` table (2870 rows, 2750 non-null values). H2 estimated as pre-registered:
  - **Primary**: Pooled regression over all 31 events (N=31, df=29) with OLS and HC1 standard errors via statsmodels. Results: β = -0.0165 (SE 0.0440, t = -0.3761, p = 0.7069, R² = 0.0034).
  - **Secondary**: Separately for hikes (N=20, df=18, β = 0.0030, p = 0.9494) and cuts (N=11, df=9, β = -0.0868, p = 0.4599).
  - All H2 tests are non-significant at α = 0.05, suggesting that abnormal returns in KBE do not respond significantly to same-day 2-year Treasury yield changes after accounting for market movements.

### Output Files

- `run_estimation.py`: Python script that executes the estimation against `data.db`. Attempts to load DGS2 from FRED if empty; reports current blocker if FRED API key unavailable.
- `estimation_results.json`: JSON sidecar containing all point estimates, standard errors, t-statistics, p-values (two-sided), confidence intervals, and degrees of freedom for each hypothesis. H1 complete; H2 entries included but null pending data.
