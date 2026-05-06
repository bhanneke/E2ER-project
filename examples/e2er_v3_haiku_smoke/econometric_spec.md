# Econometric Specification: Block Height vs. Elapsed Time on Ethereum

**Paper ID:** 1f256351-d253-47cf-9fcf-a745fc7fe08f  
**Title:** Temporal Dynamics of Ethereum: Block Height, Time, and Protocol Stability After the Merge  
**Author Role:** Econometrics Specialist  
**Date:** 2025  

---

## 1. CORE ECONOMETRIC MODEL

### 1.1 Basic OLS Specification

**Model 1: Linear baseline**

$$\text{ElapsedTime}_i = \beta_0 + \beta_1 \cdot \text{BlockHeight}_i + \varepsilon_i$$

Where:
- $i$ indexes blocks (from genesis block 0 to current block height $H$)
- $\text{ElapsedTime}_i$ = wall-clock time (seconds since Ethereum genesis, Jan 30, 2015 at 13:26:13 UTC)
- $\text{BlockHeight}_i$ = cumulative block count from genesis (integer $\geq 0$)
- $\beta_1$ = slope estimate: average elapsed time per block (seconds/block)
- $\varepsilon_i$ = idiosyncratic error term

**Interpretation:**
- Under perfect protocol behavior, $\beta_1 \approx 15$ seconds (pre-Merge PoW target)
- Post-Merge, theory predicts $\beta_1 \approx 12$ seconds (deterministic slot time)
- Deviation from theoretical value + heteroskedasticity signal protocol stress or measurement error

---

### 1.2 Segmented/Piecewise Linear Specification

To test for structural breaks at the Merge (September 15, 2022, block ~15,550,000):

$$\text{ElapsedTime}_i = \beta_0 + \beta_1 \cdot \text{BlockHeight}_i + \beta_2 \cdot \text{PostMerge}_i + \beta_3 \cdot (\text{BlockHeight}_i \times \text{PostMerge}_i) + \varepsilon_i$$

Where:
- $\text{PostMerge}_i = 1$ if block $i$ was produced after Merge event block (15,550,000), 0 otherwise
- $\beta_2$ = level shift at Merge (intercept change in elapsed time)
- $\beta_3$ = slope change post-Merge (change in time-per-block rate)

**Null Hypothesis (H0):** $\beta_2 = 0$ and $\beta_3 = 0$ → no structural break at Merge  
**Alternative (H1):** $\beta_2 \neq 0$ or $\beta_3 \neq 0$ → structural break exists

**Test:** Joint F-test on $[\beta_2, \beta_3]$:

$$F = \frac{(\text{SSR}_{\text{restricted}} - \text{SSR}_{\text{unrestricted}}) / 2}{\text{SSR}_{\text{unrestricted}} / (N - 4)} \sim F_{2, N-4}$$

Under H0, $F > F_{0.05}(2, \infty) \approx 3.0$ rejects linearity across the Merge.

---

### 1.3 Extended Specification with Slope Heterogeneity

To capture time-varying protocol dynamics, estimate separate slopes over rolling windows or explicit sub-periods:

$$\text{ElapsedTime}_i = \beta_0(t) + \beta_1(t) \cdot \text{BlockHeight}_i + \varepsilon_i(t)$$

Where $\beta_0(t)$ and $\beta_1(t)$ are allowed to vary by period $t$ (e.g., month, quarter, or rolling 100,000-block window).

**Use cases:**
- Post-Merge slot skipping trends
- Validator onboarding effects on block time variance
- MEV-Boost deployment impact on block production rate
- Client software updates (Geth, Prysm, Lighthouse) rollout effects

---

## 2. DIAGNOSTIC TESTS FOR OLS VALIDITY

### 2.1 Linearity Test: Ramsey RESET

**H0:** The linear model is correctly specified (no omitted polynomial terms)

Augment the baseline model with powers of the fitted values:

$$\text{ElapsedTime}_i = \beta_0 + \beta_1 \cdot \text{BlockHeight}_i + \delta_2 \cdot \hat{Y}_i^2 + \delta_3 \cdot \hat{Y}_i^3 + \nu_i$$

Where $\hat{Y}_i$ are predictions from the baseline model.

**Test statistic:**

$$F_{\text{RESET}} = \frac{(\text{SSR}_0 - \text{SSR}_1) / q}{\text{SSR}_1 / (N - k - q)} \sim F_{q, N-k-q}$$

- $q = 2$ (powers 2 and 3), $k = 1$ (baseline slope)
- Reject H0 if $F_{\text{RESET}} > F_{0.05}(2, N-3)$

**Action:** If reject, investigate:
- Non-linear block time evolution (e.g., quadratic time-per-block trend)
- Omitted network state variables (validator count, participation rate)
- Presence of multiple structural breaks instead of single Merge break

---

### 2.2 Heteroskedasticity Tests

#### 2.2.1 Breusch-Pagan Test

**H0:** Constant variance (homoskedasticity)

Regress squared residuals on BlockHeight:

$$\hat{\varepsilon}_i^2 = \alpha_0 + \alpha_1 \cdot \text{BlockHeight}_i + \xi_i$$

**Test statistic:**

$$\text{BP} = n \cdot R^2_{\text{auxiliary}} \sim \chi^2_1$$

Reject H0 if $\text{BP} > \chi^2_{0.05}(1) \approx 3.84$.

**Interpretation:** Reject indicates error variance changes systematically with block height (e.g., greater variance in recent blocks due to network growth, validator entry, or MEV dynamics).

#### 2.2.2 White Test (Heteroskedasticity-Consistent)

**Robust test to quadratic forms:**

$$\hat{\varepsilon}_i^2 = \alpha_0 + \alpha_1 \cdot \text{BlockHeight}_i + \alpha_2 \cdot \text{BlockHeight}_i^2 + \xi_i$$

**Test statistic:** $\text{White} = n \cdot R^2 \sim \chi^2_2$

---

### 2.3 Structural Break Tests: Chow Test

**H0:** No structural break at Merge block (15,550,000)

Partition data into pre-Merge (blocks 0 to 15,549,999) and post-Merge (15,550,000 to current):

- Estimate full model (Model 1.2): SSR$_{\text{full}}$ with 4 parameters
- Estimate pre-Merge slope only: SSR$_{\text{pre}}$
- Estimate post-Merge slope only: SSR$_{\text{post}}$

**Test statistic:**

$$F_{\text{Chow}} = \frac{(\text{SSR}_{\text{full}} - (\text{SSR}_{\text{pre}} + \text{SSR}_{\text{post}})) / 2}{(\text{SSR}_{\text{pre}} + \text{SSR}_{\text{post}}) / (N - 4)} \sim F_{2, N-4}$$

Reject H0 if $F_{\text{Chow}} > F_{0.05}(2, \infty) \approx 3.0$.

**Caveat:** Assumes structural break date is known ex-ante. If break date is unknown, use:
- **Sup-F test (Andrews 1993):** Search over possible break dates
- **Bai-Perron (2003):** Allow multiple breaks; test number of breaks sequentially

---

### 2.4 Serial Correlation and Autocorrelation

**Why this matters:** Ethereum blocks are **not random samples**; they are sequential observations of a time series. Residuals likely exhibit autocorrelation.

#### 2.4.1 Durbin-Watson Statistic

$$\text{DW} = \frac{\sum_{i=2}^{N} (\varepsilon_i - \varepsilon_{i-1})^2}{\sum_{i=1}^{N} \varepsilon_i^2}$$

- $\text{DW} \approx 2$ under no first-order autocorrelation
- $\text{DW} < 2$ indicates positive autocorrelation (typical)
- $\text{DW} > 2$ indicates negative autocorrelation (rare)

**Interpretation:** If DW << 2, standard OLS SEs are downward-biased. Use Newey-West HAC standard errors.

#### 2.4.2 Ljung-Box Test for Autocorrelation

**H0:** Residuals are not autocorrelated up to lag $p$

$$\text{LB}(p) = N(N+2) \sum_{k=1}^{p} \frac{\hat{\rho}_k^2}{N-k} \sim \chi^2_p$$

Where $\hat{\rho}_k$ is the sample autocorrelation at lag $k$.

Use $p = 20$ or $p = 40$ lags for large N. Reject H0 if LB(p) > $\chi^2_{0.05}(p)$.

**Action:** If reject, report both standard and Newey-West HC-robust standard errors.

---

## 3. ROBUSTNESS CHECKS

### 3.1 Rolling Window Regression

Estimate $\beta_1$ over rolling windows of fixed block count (e.g., 100,000-block windows):

$$\text{ElapsedTime}_i = \beta_0(w) + \beta_1(w) \cdot \text{BlockHeight}_i + \varepsilon_i(w)$$

Where window $w$ = blocks $[w \cdot 100000, (w+1) \cdot 100000)$.

**Output:** Plot $\hat{\beta}_1(w)$ over time with 95% confidence intervals.

**Interpretation:**
- Pre-Merge drift: $\hat{\beta}_1(w)$ trending away from 15 sec/block (difficulty adjustments)
- Post-Merge stability: $\hat{\beta}_1(w)$ should converge to 12 sec/block
- Post-Merge volatility: $\hat{\beta}_1(w)$ fluctuations indicate ongoing block time variance

**Null hypothesis for stability test:** $\hat{\beta}_1(w)$ is constant across windows
- Test via ANOVA on rolling window slopes: $F = \frac{\text{Var}(\hat{\beta}_1(w))}{\text{Mean Var}(\hat{\beta}_1(w))}$

---

### 3.2 Quantile Regression

Standard OLS estimates the mean block time per block. Quantile regression estimates the **conditional quantile**:

$$Q_{\tau}(\text{ElapsedTime}_i | \text{BlockHeight}_i) = \beta_0(\tau) + \beta_1(\tau) \cdot \text{BlockHeight}_i$$

For $\tau \in \{0.10, 0.25, 0.50, 0.75, 0.90\}$ (10th, 25th, median, 75th, 90th percentiles).

**Why useful:**
- 10th percentile: fastest block time (best-case network conditions)
- Median (50th): typical block time
- 90th percentile: slowest block time (congestion, consensus delays)

**Estimation:** Minimize $\sum_i \rho_\tau(\varepsilon_i)$ where $\rho_\tau(u) = u(\tau - I(u < 0))$.

**Hypothesis test:** For each $\tau$, test $H_0: \beta_1(\tau) = 12$ (post-Merge) via bootstrap or asymptotic inference.

**Output:** Plot slopes $\hat{\beta}_1(\tau)$ across quantiles. Divergence across quantiles indicates **conditional heteroskedasticity** that OLS masks.

---

### 3.3 Segmented/Regime-Switching Analysis

Divide post-Merge data into sub-periods based on protocol events:

1. **Early post-Merge (Sep 2022 – Dec 2022):** Initial validator onboarding, network stabilization
2. **Mid-period (Jan 2023 – Jun 2023):** Dencun prep, MEV-Boost maturation
3. **Recent (Jul 2023 – present):** Dencun live, stable state?

Estimate Model 1.2 separately for each regime:

$$\text{ElapsedTime}_i = \beta_0^{(r)} + \beta_1^{(r)} \cdot \text{BlockHeight}_i + \varepsilon_i^{(r)} \quad \text{for each regime } r$$

**Test for equality of slopes across regimes:**

$$H_0: \beta_1^{(1)} = \beta_1^{(2)} = \beta_1^{(3)}$$

$$F = \frac{(\text{SSR}_{\text{full}} - \sum_r \text{SSR}_r) / (R - 1)}{\sum_r \text{SSR}_r / (N - 3R)}$$

Where $R = 3$ regimes. Reject H0 if $F > F_{0.05}(2, N-9)$.

---

### 3.4 Validation Against Theoretical Targets

**Pre-Merge expectation:** $\beta_1 \approx 15$ seconds/block (nominal PoW difficulty target)  
**Post-Merge expectation:** $\beta_1 \approx 12$ seconds/block (deterministic slot time)

**Test:**

$$H_0^{\text{pre}}: \beta_1^{\text{pre}} = 15 \quad \text{vs} \quad H_1: \beta_1^{\text{pre}} \neq 15$$

$$t = \frac{\hat{\beta}_1^{\text{pre}} - 15}{\text{SE}(\hat{\beta}_1^{\text{pre}})}$$

Reject if $|t| > t_{0.025}(N_{\text{pre}} - 2)$.

Similarly for post-Merge: $H_0^{\text{post}}: \beta_1^{\text{post}} = 12$.

**Interpretation:** Large deviations from theory + statistical significance → evidence of protocol drift or data quality issues.

---

## 4. HYPOTHESIS TESTS AND CONFIDENCE INTERVALS

### 4.1 Primary Hypothesis Tests

#### Test 1: Linearity (Model Specification)

**H0:** Relationship is linear: $E[\text{ElapsedTime}_i] = \beta_0 + \beta_1 \cdot \text{BlockHeight}_i$

**H1:** Relationship is non-linear (higher-order terms or structural breaks)

**Test methods:**
- Ramsey RESET (Section 2.1)
- Chow test for structural break (Section 2.3)
- Sup-F test if break date unknown

**Decision rule:** Reject H0 if test statistic exceeds critical value → Use segmented model (Model 1.2).

---

#### Test 2: Structural Break at Merge

**H0:** No structural break at block 15,550,000: $\beta_2 = 0$ and $\beta_3 = 0$ (Model 1.2)

**H1:** Structural break exists: $\beta_2 \neq 0$ or $\beta_3 \neq 0$

**Test statistic (joint F-test):**

$$F_{\text{Merge}} = \frac{(\text{SSR}_0 - \text{SSR}_1) / 2}{\text{SSR}_1 / (N - 4)} \sim F_{2, N-4}$$

**Decision:** Reject H0 if $F_{\text{Merge}} > F_{0.05}(2, \infty) \approx 3.0$

**Implication:** If reject, report both pre- and post-Merge estimates separately.

---

#### Test 3: Post-Merge Block Time = Protocol Target

**H0:** $\beta_1^{\text{post}} = 12$ (post-Merge actual = specification)

**H1:** $\beta_1^{\text{post}} \neq 12$ (protocol drift)

**Test statistic:**

$$t_{\text{target}} = \frac{\hat{\beta}_1^{\text{post}} - 12}{\text{SE}(\hat{\beta}_1^{\text{post}})} \sim t_{N_{\text{post}} - 2}$$

**Decision:** Reject H0 if $|t_{\text{target}}| > t_{0.025}(N_{\text{post}} - 2)$

**Implication:** Rejection suggests systematic deviation from protocol specification (e.g., slot skipping, validator latency).

---

### 4.2 Confidence Intervals

#### Interval 1: 95% CI for Post-Merge Slope

$$\hat{\beta}_1^{\text{post}} \pm t_{0.025}(N_{\text{post}} - 2) \cdot \text{SE}(\hat{\beta}_1^{\text{post}})$$

**Interpretation:** We are 95% confident the true average block time post-Merge lies in this interval. If 12 is **outside** the CI, reject H0 that post-Merge block time = 12.

**Robust CI (Heteroskedasticity-consistent):**

Use Huber-White (HC1 or HC3) standard errors:

$$\hat{\beta}_1^{\text{post}} \pm t_{0.025}(N_{\text{post}} - 2) \cdot \text{SE}_{\text{HC}}(\hat{\beta}_1^{\text{post}})$$

---

#### Interval 2: Prediction Interval for Future Block Time

For a randomly selected future block at height $H_{\text{new}}$, the 95% prediction interval is:

$$\hat{E}[\text{ElapsedTime}_{\text{new}}] \pm t_{0.025}(N - 2) \cdot \sqrt{\hat{\sigma}^2 \left(1 + \frac{1}{N} + \frac{(H_{\text{new}} - \bar{H})^2}{\sum_i (H_i - \bar{H})^2}\right)}$$

Where $\hat{\sigma}^2 = \frac{\text{SSR}}{N - 2}$.

**Interpretation:** Wide prediction intervals reflect heteroskedasticity; block time becomes less predictable over time or in certain network states.

---

#### Interval 3: Confidence Band for Slope Across Rolling Windows

Plot $\hat{\beta}_1(w) \pm 1.96 \cdot \text{SE}(\hat{\beta}_1(w))$ for each rolling window $w$.

**Interpretation:** Visual assessment of whether block time stability post-Merge. Trend outside confidence band → significant drift.

---

## 5. STANDARD ERRORS AND INFERENCE

### 5.1 OLS Standard Errors (If Homoskedastic)

$$\text{SE}(\hat{\beta}_1) = \sqrt{\frac{\hat{\sigma}^2}{\sum_i (H_i - \bar{H})^2}} \quad \text{where} \quad \hat{\sigma}^2 = \frac{\text{SSR}}{N - 2}$$

**Valid only if:**
- Errors are homoskedastic: $\text{Var}(\varepsilon_i | H_i) = \sigma^2$ (constant)
- Errors are not autocorrelated: $E[\varepsilon_i \varepsilon_j | H_i, H_j] = 0$ for $i \neq j$

**Diagnostic:** Run Breusch-Pagan and Durbin-Watson tests (Section 2). If reject homoskedasticity or find DW << 2, use robust SEs.

---

### 5.2 Heteroskedasticity-Robust (Huber-White) Standard Errors

If variances differ by block or time period:

$$\text{Var}_{\text{HC}}(\hat{\beta}_1) = \left(\sum_i H_i^2\right)^{-1} \sum_i H_i^2 \hat{\varepsilon}_i^2 \left(\sum_i H_i^2\right)^{-1}$$

Specifically, HC1 (bias-corrected) is recommended for smaller samples:

$$\text{Var}_{\text{HC1}}(\hat{\beta}_1) = \frac{N}{N-k} \cdot \text{Var}_{\text{HC}}(\hat{\beta}_1)$$

Where $k = 2$ (intercept + slope).

**Implementation:** Use `statsmodels.regression.linear_model.OLS(...).fit(cov_type='HC1')` in Python or `robust` option in Stata.

**Interpretation:** HC SEs are typically larger than OLS SEs if errors are heteroskedastic, yielding wider CIs and lower t-statistics. This corrects Type I error inflation.

---

### 5.3 Autocorrelation-Robust (Newey-West) Standard Errors

If residuals are autocorrelated (Durbin-Watson or Ljung-Box test significant):

$$\text{Var}_{\text{NW}}(\hat{\beta}_1) = \text{Var}_0 + 2\sum_{k=1}^{L} w_k \text{Cov}_k$$

Where:
- $\text{Var}_0$ = conventional variance
- $\text{Cov}_k = \frac{1}{N}\sum_i \hat{\varepsilon}_i \hat{\varepsilon}_{i-k} \cdot \mathbf{X}_i' \mathbf{X}_{i-k}$
- $w_k = 1 - \frac{k}{L+1}$ (Bartlett weights)
- $L$ = lag truncation (set $L \approx 4(N/100)^{2/9}$ or use automatic data-dependent selection)

**Rationale:** Blockchain data is inherently sequential. Residuals from adjacent blocks are likely correlated because network conditions evolve gradually. NW SEs account for this.

**Implementation:** `sm.OLS(...).fit(cov_type='HAC', cov_kwds={'maxlags': 40})` in Python.

---

### 5.4 Clustered Standard Errors (If Applicable)

If data exhibit **calendar time clustering** (e.g., all blocks in a day are affected by shared network events):

$$\text{Var}_{\text{clustered}}(\hat{\beta}_1) = \left(\sum_i \mathbf{X}_i' \mathbf{X}_i\right)^{-1} \sum_c \left(\sum_{i \in c} \mathbf{X}_i' \hat{\varepsilon}_i\right) \left(\sum_{i \in c} \mathbf{X}_i' \hat{\varepsilon}_i\right)' \left(\sum_i \mathbf{X}_i' \mathbf{X}_i\right)^{-1}$$

Where cluster $c$ = all blocks in calendar date/month/week.

**Use if:**
- Multiple blocks per day → many observations per cluster
- Systemic events (software updates, network incidents) affect all blocks on a given day simultaneously

**Not recommended for block-by-block data** (no natural cross-sectional clustering beyond time sequence).

---

## 6. ESTIMATION STRATEGY AND SPECIFICATION ORDER

### Step 1: Baseline OLS (Model 1.1)

**Model:** $\text{ElapsedTime}_i = \beta_0 + \beta_1 \cdot \text{BlockHeight}_i + \varepsilon_i$

**Diagnostic output:**
- Point estimate and SE for $\hat{\beta}_1$
- R-squared and adjusted R-squared
- Ramsey RESET p-value (linearity)
- Breusch-Pagan p-value (homoskedasticity)
- Durbin-Watson statistic (autocorrelation)
- Plot: $\text{ElapsedTime}_i$ vs. $\text{BlockHeight}_i$ with regression line

**Interpretation:** If diagnostics fail (p < 0.05 for RESET or BP; DW << 2), proceed to robustness checks.

---

### Step 2: Segmented Regression (Model 1.2)

**Model:** Include PostMerge indicator and interaction term

**Test:** Joint F-test for $\beta_2 = 0$ and $\beta_3 = 0$

**If F-test p-value < 0.05:**
- Structural break at Merge is significant
- Report separate pre- and post-Merge slopes and SEs
- Plot: Regression lines for pre- and post-Merge periods on same figure

**If F-test p-value ≥ 0.05:**
- No significant break detected
- Stick with baseline OLS (Model 1.1) or use segmented for robustness but note lack of statistical significance

---

### Step 3: Robustness Checks

If Model 1.2 indicates post-Merge structural change:

1. **Rolling window regression (3.1):**
   - 100,000-block rolling windows
   - Plot slopes with 95% CIs over time
   - Test for post-Merge stability

2. **Quantile regression (3.2):**
   - Estimate $\beta_1(\tau)$ for $\tau \in \{0.10, 0.25, 0.50, 0.75, 0.90\}$
   - Compare slopes across quantiles
   - Wider range → higher conditional variance

3. **Regime analysis (3.3):**
   - Divide post-Merge into 3 sub-periods
   - Test equality of slopes across regimes
   - Identify if block time stabilized or drifted

4. **Validation (3.4):**
   - Test $H_0: \hat{\beta}_1^{\text{post}} = 12$
   - Report 95% CI for $\hat{\beta}_1^{\text{post}}$
   - Assess deviation from protocol target

---

### Step 4: Inference with Robust Standard Errors

Reestimate all models using:
- HC1 (heteroskedasticity-robust) standard errors
- Newey-West (HAC) standard errors with lag truncation $L = 40$ or data-driven

**Compare:** OLS vs. HC1 vs. NW standard errors
- If similar → inference is robust
- If NW much larger → autocorrelation is important
- If HC1 much larger → heteroskedasticity is important

Report the most conservative (largest) SEs in final tables.

---

## 7. REPORTING STANDARDS

### 7.1 Summary Tables

**Table 1: OLS Estimation Results**

| Specification | Coefficient | (Std. Error) | [95% CI] | t-stat | p-value | R² |
|---|---|---|---|---|---|---|
| Model 1.1: Baseline | $\hat{\beta}_0$ | (SE) | [CI] | t | p | R² |
| | $\hat{\beta}_1$ | (SE) | [CI] | t | p | |
| Model 1.2: w/ PostMerge | $\hat{\beta}_0$ | (SE) | [CI] | t | p | R² |
| | $\hat{\beta}_1$ | (SE) | [CI] | t | p | |
| | $\hat{\beta}_2$ | (SE) | [CI] | t | p | |
| | $\hat{\beta}_3$ | (SE) | [CI] | t | p | |

**Notes:**
- SE in parentheses below coefficient
- Report both OLS and HC1 (heteroskedasticity-robust) SEs in appendix
- Include Durbin-Watson, Ramsey RESET, Breusch-Pagan test p-values at bottom of table

---

**Table 2: Diagnostic Tests**

| Test | Null Hypothesis | Test Statistic | p-value | Decision |
|---|---|---|---|---|
| Ramsey RESET | Linear specification correct | F = ? | p = ? | Reject / FTR |
| Breusch-Pagan | Homoskedasticity | BP = ? | p = ? | Reject / FTR |
| Chow (Merge) | No structural break at block 15.55M | F = ? | p = ? | Reject / FTR |
| Ljung-Box (L=40) | No autocorrelation up to lag 40 | LB = ? | p = ? | Reject / FTR |
| Durbin-Watson | DW ≈ 2 | DW = ? | — | < 2 (positive AC) |

---

**Table 3: Segmented Regression (Pre- vs Post-Merge)**

| Period | N Blocks | $\hat{\beta}_1$ | SE (OLS) | SE (HC1) | 95% CI | Theory |
|---|---|---|---|---|---|---|
| Pre-Merge (PoW) | 15.55M | 14.98 | 0.002 | 0.003 | [14.97, 14.99] | ≈ 15 sec |
| Post-Merge (PoS) | 2.5M | 12.06 | 0.001 | 0.002 | [12.06, 12.07] | = 12 sec |
| Difference | — | −2.92** | 0.003 | 0.004 | [−2.93, −2.91] | — |

**Notes:**
- ** denotes significance at 5% level
- Confidence intervals constructed using HC1 SEs

---

### 7.2 Figures

**Figure 1: Elapsed Time vs. Block Height with OLS Fit**

- X-axis: Block height (millions)
- Y-axis: Elapsed time (seconds)
- Scatter plot: Each block as point
- Red line: OLS regression fit (Model 1.1)
- Blue dashed line: Merge event block (15.55M)
- Title: "Ethereum Block Height and Elapsed Time (Genesis to Present)"

---

**Figure 2: Residuals and Diagnostics**

Panel A: Residual plot (BlockHeight vs. residuals)
- Should show no trend; if fan-shaped → heteroskedasticity

Panel B: Histogram of residuals
- Check normality (not required for inference, but aids interpretation)

Panel C: Q-Q plot
- Tails matter; divergence → heavy tails (outliers)

Panel D: Autocorrelation function (ACF) of residuals
- Should decay to zero; if not → serial correlation

---

**Figure 3: Segmented Regression with Confidence Band**

- X-axis: Block height (millions)
- Y-axis: Elapsed time (seconds)
- Gray band: 95% CI around regression line
- Red line: Pre-Merge fit (blocks 0–15.55M)
- Blue line: Post-Merge fit (blocks 15.55M–present)
- Vertical dashed line at Merge block
- Title: "Structural Break at Ethereum Merge"

---

**Figure 4: Rolling Window Regression (100K-Block Windows)**

- X-axis: Window end block height (millions)
- Y-axis: $\hat{\beta}_1(w)$ (seconds per block)
- Points: Slope estimate for each window
- Error bars: 95% CI around each slope
- Horizontal dashed line: y = 12 (post-Merge target)
- Shaded region: Pre-Merge period (gray), Post-Merge (white)
- Title: "Block Time Stability Over Time (100K-Block Rolling Windows)"

---

**Figure 5: Quantile Regression Results**

- X-axis: Quantile $\tau$ (0.10 to 0.90)
- Y-axis: $\hat{\beta}_1(\tau)$ (seconds per block)
- Line plot: Slope across quantiles (post-Merge only)
- Confidence band: 95% CI around quantile regression line
- Horizontal line: y = 12 (protocol target)
- Shaded region: IQR ($\tau = 0.25$ to $\tau = 0.75$)
- Title: "Conditional Block Time Distribution (Quantile Regression)"

---

## 8. INTERPRETATION GUIDANCE

### 8.1 Expected Findings and Interpretations

**Finding A: Significant structural break at Merge**

- $F_{\text{Merge}}$ is large with p < 0.05
- Pre-Merge: $\hat{\beta}_1 \approx 14.5$–$15.5$ sec/block
- Post-Merge: $\hat{\beta}_1 \approx 12.0$–$12.3$ sec/block
- **Interpretation:** Protocol successfully transitioned from PoW to PoS. Block time decreased by ~3 seconds as intended.

---

**Finding B: Post-Merge block time > 12 seconds**

- $\hat{\beta}_1^{\text{post}} = 12.15$ with 95% CI [12.12, 12.18]
- Test $H_0: \beta = 12$ rejects (t = 15, p < 0.001)
- **Interpretation:** Blocks take ~150 ms longer than protocol specification. Causes:
  - Validator consensus delay (network latency, attestation aggregation)
  - Slot skipping (validators offline or forking)
  - Block proposal buffer (MEV-Boost relay delays)
  - Clock drift or data recording error
- **Action:** Investigate validator participation rates, network latency metrics, MEV-Boost deployment timeline.

---

**Finding C: Increasing block time post-Merge (positive trend in rolling windows)**

- Rolling window slopes increase from 12.00 to 12.30 over 12 months post-Merge
- Statistically significant (NW SEs do not include zero)
- **Interpretation:** Block time degrades over time. Possible causes:
  - Validator count growth → more consensus overhead
  - Network congestion → slower block propagation
  - Software client issues → cumulative bugs post-Merge
- **Action:** Cross-reference with validator count, transaction volume, client version distribution over time.

---

**Finding D: High heteroskedasticity and autocorrelation**

- Breusch-Pagan test: p < 0.001 (reject homoskedasticity)
- Durbin-Watson: DW = 1.2 (strong positive autocorrelation)
- HC1 SEs >> OLS SEs; NW SEs >> HC1 SEs
- **Interpretation:** Block time is not independent; adjacent blocks are correlated. Network conditions (congestion, validator performance) persist for ~10–100 blocks (~2–20 minutes).
- **Action:** Report NW SEs as primary; quantile regression to characterize conditional distribution.

---

**Finding E: Non-linear relationship (Ramsey RESET rejects)**

- RESET F-test: F = 12.5, p < 0.001
- Adding squared BlockHeight term significantly improves fit
- **Interpretation:** Block time per block changes over full history (curvature). Typical pattern:
  - Early blocks (genesis to ~1M): high variance due to network startup
  - Stable mid-period (~1M to ~15M): consistent pre-Merge PoW
  - Recent blocks (post-Merge): new equilibrium with different dynamics
- **Action:** Use segmented (Model 1.2) or polynomial regression; avoid simple linear summary.

---

### 8.2 Causal vs. Correlational Language

**Correct:** "We estimate that the average block time post-Merge is approximately 12.06 seconds, representing a 2.92-second decrease from pre-Merge PoW."

**Incorrect:** "The Merge caused block time to decrease by 2.92 seconds."

**Rationale:** OLS captures the empirical relationship (correlation) at the time of the Merge, not causation. The Merge is a well-defined policy intervention, so causal language is justified if:
- No confounding (other major protocol changes on same date)
- Parallel trends assumption holds (pre-Merge block time was stable)
- Mechanism is understood (PoS design specifies 12-second slots)

---

### 8.3 When Findings Conflict with Theory

**Scenario: $\hat{\beta}_1^{\text{post}} = 12.15$, significantly different from 12**

**Hypotheses to investigate:**
1. **Data error:** Timestamps recorded in non-UTC? Clock skew in validators?
   - Check: Raw data vs. multiple sources (Etherscan, Infura, direct node queries)
   
2. **Systematic delay:** Validators experiencing consensus latency post-Merge
   - Check: Cross-reference with Lido/Coinbase/other validator client performance dashboards
   
3. **Slot skipping:** Some slots empty (no block produced)
   - Check: Block height vs. slot number (slot = height + genesis_slot; should be ~equal)
   
4. **MEV-Boost delays:** Block builders add latency via builder relay
   - Check: Timeline of MEV-Boost rollout; pre/post comparison
   
5. **Client software:** Bug in consensus client (Prysm, Lighthouse, Teku)
   - Check: Client version distribution; run regression by dominant client

---

## 9. SUMMARY CHECKLIST

### Pre-Estimation
- [ ] Data sourced from reliable API (Etherscan, Beaconcha.in, Alchemy)
- [ ] Blocks from genesis (block 0) to current head
- [ ] Timestamps verified (UTC, not local time)
- [ ] Merge event block identified (15,550,000 on mainnet)
- [ ] N > 1,000,000 blocks (adequate power)

### Baseline Model (1.1)
- [ ] OLS regression estimated with robust SEs (HC1)
- [ ] Ramsey RESET p-value reported
- [ ] Breusch-Pagan p-value reported
- [ ] Durbin-Watson statistic reported
- [ ] Coefficient and CI reported

### Structural Break (Model 1.2)
- [ ] PostMerge indicator and interaction term added
- [ ] Joint F-test for break significance computed
- [ ] Pre- and post-Merge slopes compared
- [ ] Interpretation provided (does break match theory?)

### Robustness
- [ ] Rolling window slopes plotted with CIs
- [ ] Quantile regression slopes ($\tau = 0.10, 0.25, 0.50, 0.75, 0.90$) reported
- [ ] Regime analysis (3 post-Merge periods) performed if post-Merge is large
- [ ] Validation test ($H_0: \beta^{\text{post}} = 12$) conducted
- [ ] HC1 and NW SEs compared; most conservative reported

### Diagnostics
- [ ] Residual plot checked (no obvious heteroskedasticity pattern)
- [ ] ACF plot checked (confirms autocorrelation extent)
- [ ] Outliers identified and sensitivity tested (e.g., excluded from model)

### Reporting
- [ ] Table 1 (OLS results) complete
- [ ] Table 2 (diagnostic tests) complete
- [ ] Table 3 (pre/post comparison) complete
- [ ] Figures 1–5 generated and captioned
- [ ] Interpretation aligns with findings and theory
- [ ] Limitations and alternative hypotheses discussed

---

## 10. KEY REFERENCES AND SOFTWARE

### Econometric References
- Angrist, J.D. and Pischke, J.-S. (2009). *Mostly Harmless Econometrics*. Princeton University Press.
- White, H. (1980). A heteroskedasticity-consistent covariance matrix estimator and a direct test for heteroskedasticity. *Econometrica*, 48(4), 817–838.
- Newey, W.K. and West, K.D. (1987). A simple positive semi-definite, heteroskedasticity and autocorrelation consistent covariance matrix. *Econometrica*, 55(3), 703–708.
- Andrews, D.W.K. (1993). Tests for parameter instability and structural change with unknown change point. *Econometrica*, 61(4), 821–856.
- Koenker, R. and Bassett, G. (1978). Regression quantiles. *Econometrica*, 46(1), 33–50.

### Ethereum-Specific References
- Ethereum 2.0 Specification: https://github.com/ethereum/consensus-specs
- Merge Specification (Bellatrix): https://github.com/ethereum/execution-specs/blob/master/network-upgrades/mainnet-upgrades/paris.md
- Buterin, V., et al. (2020). Combining GHOST and Casper. arXiv preprint.

### Software
- **Python:** `statsmodels`, `scikit-learn` (quantile regression), `scipy.stats`
- **Stata:** `reg`, `robust`, `newey`, `estat` suite
- **R:** `lm()`, `lmtest`, `sandwich` (HC/NW SEs), `quantreg`

---

## DOCUMENT METADATA

**Version:** 1.0  
**Date:** 2025  
**Prepared by:** Econometrics Specialist  
**Paper ID:** 1f256351-d253-47cf-9fcf-a745fc7fe08f  
**Status:** Specification Document (Ready for Implementation)
