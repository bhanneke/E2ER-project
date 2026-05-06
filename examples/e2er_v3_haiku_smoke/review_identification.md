# Identification Review: Block Height vs. Elapsed Time on Ethereum

**Paper ID:** 1f256351-d253-47cf-9fcf-a745fc7fe08f  
**Title:** Temporal Dynamics of Ethereum: Block Height, Time, and Protocol Stability After the Merge  
**Stage:** Idea Development  
**Review Date:** 2025  

---

## SUMMARY ASSESSMENT

**Status: CONCERNS — Significant gaps between identification strategy and econometric implementation**

The research question is well-motivated and the phenomenon is genuine. However, the current identification strategy conflates **descriptive measurement of temporal regularity** with **causal inference about drivers of deviation**. The econometric specification in Stage 2 is purely descriptive (OLS relating block height to elapsed time). The causal claims in the Identification Strategy document (Sections 1–2) about network congestion, validator heterogeneity, and consensus dynamics cannot be tested with the proposed specification because the causal mechanisms are not instrumented or identified in the regression framework.

**Critical Issue:** The paper promises causal explanation ("because network congestion... create endogenous delays") but the econometric specification only measures whether block timing deviates from linearity. These are different questions. The current trajectory will produce a purely descriptive paper mislabeled as causal inference.

---

## DATA PIPELINE VERIFICATION

### Current State
The data pipeline is not yet described in detail because the project is at the "Idea" stage. However, the research plan mentions:
- **Data source:** Ethereum mainnet block data
- **Unit of observation:** Individual blocks (indexed by block height)
- **Temporal coverage:** Genesis (Jan 30, 2015) to present; with focus on post-Merge (Sept 15, 2022 onward)
- **Key variables:** Block height, block timestamp, transaction count, gas used, mempool state

### Critical Questions to Resolve BEFORE Data Construction

1. **Block Timestamp Definition**: Is the dependent variable `block.timestamp` (Ethereum's on-chain timestamp field set by the proposer) or actual wall-clock time of block propagation/finality? These differ by 10–30 seconds on average due to network propagation. The choice fundamentally changes interpretation.
   - **Concern:** If using on-chain `block.timestamp`, the analysis measures validator timekeeping behavior, not network dynamics.
   - **Concern:** If using propagation time, this requires off-chain monitoring data (e.g., Etherscan, Infura logs), which introduces latency and observation-point bias.

2. **Slot vs. Block Conflation**: Are "blocks" and "slots" used consistently? Under PoS, each slot should contain 0 or 1 block. Some slots are empty (no proposer, missed block, or slashing). The relationship between block height and elapsed time is mediated by slot-to-block assignment.
   - **Current specification:** Uses block height directly. This ignores missed slots.
   - **Better approach:** Use slot height as treatment variable, not block height.

3. **Sample Construction Criteria**:
   - Are all blocks included, or is there filtering by client type, proposer, mempool state?
   - How are uncle blocks (pre-Merge PoW) handled if extending analysis backward?
   - How are post-Merge blocks with zero transactions handled?
   - Are there explicit exclusion criteria (e.g., reorged blocks)?

4. **Temporal Granularity**: 
   - Should the unit be individual blocks (current implicit plan) or time windows (e.g., daily averages)?
   - If individual blocks: sample size is ~2.2 million post-Merge blocks (Sept 2022–present). This is computationally manageable but may have severe autocorrelation issues (see Section 3).
   - If time windows: this reduces sample size but allows for cleaner aggregation and reduces within-window dependence.

### Recommendation
Before proceeding to data construction, clarify:
- [ ] Exact definition of "elapsed time" (on-chain timestamp vs. wall-clock propagation time)
- [ ] Treatment unit (slot height vs. block height; implications for missed slots)
- [ ] Explicit sample construction rules (inclusion/exclusion criteria, deduplication)
- [ ] Temporal aggregation (block-level vs. window-level analysis)

---

## IDENTIFICATION STRATEGY ASSESSMENT

### 2.1 Stated Causal Claim (Section 1)

The paper claims:
> "Block height fails to map to elapsed time at predictable intervals ... **because** network congestion, validator heterogeneity, and consensus dynamics create endogenous delays..."

This is a **causal claim**: treatment (network conditions) → mechanism (validator delay) → outcome (deviation from 12-second regularity).

### 2.2 The Identification Problem

To identify a causal effect of network congestion on block delay, we need to separate:
1. **Exogenous variation** in congestion (truly independent of block delay)
2. **Reverse causality**: Does congestion cause delay, or does delay (queue buildup) cause congestion?
3. **Confounding**: Do unobserved chain state variables affect both congestion and delay?

**Current Econometric Specification (Section 3):** The proposed OLS regression has **no treatment variable**. It simply regresses block height on elapsed time. This is a description of the aggregate relationship, not identification of causal mechanisms.

### 2.3 What the OLS Specification Actually Does

$$\text{ElapsedTime}_i = \beta_0 + \beta_1 \cdot \text{BlockHeight}_i + \varepsilon_i$$

This regression asks: "On average, how many seconds elapse per block?"

- If $\beta_1 = 12$: average block time is 12 seconds (matches PoS design)
- If $\beta_1 \neq 12$: average block time deviates from design

**This is descriptive, not causal.** It answers "what is the temporal relationship?" but not "why is it deviating from protocol expectations?" or "what observable chain states predict deviation?"

### 2.4 The Mismatch Between Strategy and Specification

The Identification Strategy document (Section 1) proposes a causal mechanism:

$$\Delta_i = \text{delay in slot } i = f(S_i, C_i, V_i)$$

Where:
- $S_i$ = network congestion (mempool size, gas usage)
- $C_i$ = chain state (fork likelihood, reorg risk)
- $V_i$ = validator composition (heterogeneity)

**But the econometric specification does not estimate this function.** There is no regression of $\Delta_i$ on $(S_i, C_i, V_i)$.

Instead, we have a regression of total elapsed time on block height, which is equivalent to estimating the marginal block rate—a purely summary statistic.

### 2.5 Critical Identification Issues

#### Issue 1: Reverse Causality (Simultaneity)

If the true causal structure is:
- Block delay (Δ_i) causes mempool congestion (S_i) because delayed blocks = backed-up transactions
- Mempool congestion (S_i) causes block delay (Δ_i) because validators process slower

Then any regression of delay on congestion is biased by simultaneity bias. **Solution:** Use an instrumental variable for congestion (e.g., external transaction arrival rate) or use a lag structure (congestion at t-1 predicts delay at t).

**Current spec has no IV, so simultaneity is unaddressed.**

#### Issue 2: Unobserved Confounding

Chain state variables (validator distribution, client version mix, network topology changes) may affect both congestion and delay but are unobserved. Even adding observable controls (mempool size, gas used) will not eliminate this bias.

**Current spec has no sensitivity analysis for omitted variables.** The paper should conduct Oster (2019) or Rosenbaum bounds analysis post-estimation.

#### Issue 3: Autocorrelation and Dependence

Block times are highly autocorrelated: if block i is delayed, block i+1 is more likely delayed (validators are slower, network congestion persists). Standard OLS standard errors will be **severely downward biased**.

**Current spec does not address autocorrelation clustering.** Variance should be estimated using Newey-West (HAC) standard errors or by clustering at temporal windows (e.g., daily blocks).

#### Issue 4: Non-stationarity

If the underlying protocol parameters or validator composition change over time, the relationship between block height and elapsed time is non-stationary. A single slope $\beta_1$ estimated over 10+ years may mask structural breaks.

**Current spec uses a segmented/piecewise model (Section 1.2) that tests for a break at the Merge, which is good.** However, it ignores:
- Shanghai upgrade (April 2023): introduced EIP-4844, affecting block structure
- Dencun upgrade (March 2024): further changes to blob handling
- Ongoing validator composition shifts (Lido concentration)

**Recommendation:** Implement rolling-window OLS or state-space models to allow $\beta_1$ to vary over time.

---

## ECONOMETRIC SPECIFICATION REVIEW

### 3.1 Model 1: Linear Baseline (Section 1.1)

$$\text{ElapsedTime}_i = \beta_0 + \beta_1 \cdot \text{BlockHeight}_i + \varepsilon_i$$

**Strengths:**
- Simple, interpretable: $\beta_1$ is average seconds per block
- Correct interpretation of theoretical value: $\beta_1 \approx 12$ post-Merge

**Weaknesses:**
1. **No treatment variables**: This is a univariate regression of outcome on time index. It cannot identify causal mechanisms.
2. **Severe autocorrelation**: Consecutive blocks have nearly identical timestamps. OLS standard errors will be downward biased by a factor of 10–100.
   - **Fix:** Use Newey-West standard errors with lag order = 15–20 minutes of blocks (~75 blocks)
3. **Functional form assumption**: Assumes linearity. If block rate is accelerating or mean-reverting, this will misspecify the model.
   - **Check:** Plot $\text{ElapsedTime}_i$ vs. $\text{BlockHeight}_i$. If the plot shows curvature, add polynomial terms or use local regression (LOWESS).
4. **Selection of sample**: Uses all blocks since genesis (2015–present). But protocol parameters changed dramatically. Pre-Merge behavior is not comparable to post-Merge.
   - **Fix:** Implement Model 2 (segmented) or estimate separately on post-Merge data.

**Red Flag:** If $\beta_1 = 12.1$ (0.8% deviation from 12 seconds), with standard error 0.02, this is statistically significant but economically trivial. Ensure interpretations don't overstate precision.

### 3.2 Model 2: Segmented/Piecewise Linear (Section 1.2)

$$\text{ElapsedTime}_i = \beta_0 + \beta_1 \cdot \text{BlockHeight}_i + \beta_2 \cdot \text{PostMerge}_i + \beta_3 \cdot (\text{BlockHeight}_i \times \text{PostMerge}_i) + \varepsilon_i$$

**Strengths:**
- Tests for structural break at Merge: joint F-test on $[\beta_2, \beta_3]$
- Allows slope and intercept to differ pre/post-Merge
- Aligns with the paper's motivation (major protocol change)

**Weaknesses:**
1. **Single breakpoint**: Ignores Shanghai (April 2023) and Dencun (March 2024) upgrades. If $\beta_1$ changed post-Dencun, the segmented model will not detect this.
   - **Fix:** Include additional indicators for other protocol upgrades.
2. **No controls for confounders**: Even within pre- or post-Merge, the relationship may vary with network conditions. Adding controls (mempool size, gas used) may reveal that the "Merge effect" is confounded by changing network usage.
3. **Same autocorrelation issues as Model 1**: Standard errors will be biased downward.

**Test of Specification Alignment:** The paper (Section 2.1) states the null hypothesis is $H_0: \beta_2 = 0, \beta_3 = 0$ (no structural break). This is correct. However, if the result is significant (rejecting H0), the paper should clarify:
- What does a significant $\beta_2$ mean economically? (Jump in time at the exact block number? Or gradual transition?)
- Is the significance driven by $\beta_2$ or $\beta_3$? (Intercept change or slope change?)

### 3.3 Missing Specifications

The paper plan does not propose specifications for key research questions raised in the Research Question document:

**RQ2 (Time-Varying Effects):** How does block time regularity vary over time?
- **Missing spec:** Rolling-window OLS or state-space model with time-varying $\beta_1(t)$

**RQ3 (Conditional Heterogeneity):** What chain states predict greater deviation from 12-second regularity?
- **Missing spec:** Regression of block delay $\Delta_i$ on chain state variables (mempool size, gas used, validator diversity)
- Example: $\Delta_i = \alpha + \gamma_1 \cdot \text{MempoolSize}_{i-1} + \gamma_2 \cdot \text{GasUsed}_{i} + u_i$

**RQ4 (Validation/Robustness):** Do we see block time deviations during known network stress events?
- **Missing spec:** Event study around network incidents (e.g., flash crashes, MEV cascades, client bugs)

---

## RESULTS INTERPRETATION & REPORTING ISSUES

### 4.1 Interpretation Template (Pre-Analysis Plan)

The paper should pre-commit to interpretations before seeing results:

**If $\beta_1 = 12.0 \pm 0.05$ (95% CI: [11.95, 12.05]):**
- Interpretation: Block time matches protocol design within measurement error. ✓ Robust to Merge.

**If $\beta_1 = 12.5 \pm 0.1$ (95% CI: [12.3, 12.7]):**
- Interpretation: Block time is systematically 4.2% slower than design. Could indicate validator issues, network congestion, or measurement error. Conduct robustness checks.

**If $\beta_3 < 0$ in segmented model (post-Merge slope is lower than pre-Merge):**
- Interpretation: Block time accelerated post-Merge (shorter time per block). But is this protocol improvement or reduced network usage? Need conditional analysis.

### 4.2 Significance Testing Issues

1. **Multiple Comparisons:** If the paper tests many thresholds (Is $\beta_1 = 12$? Is it = 11.5? Is it = 12.5?), apply Bonferroni or Benjamini-Hochberg correction.

2. **Power Analysis:** At 2.2 million post-Merge blocks, the standard error on $\beta_1$ will be extremely small. A trivial 0.1-second difference becomes significant. Report practical significance (effect size) alongside statistical significance.

3. **Confidence Intervals:** Must account for autocorrelation. Standard OLS 95% CI will be too narrow by 2–3x.

### 4.3 Economic Significance

The paper should tie results back to stakeholders:
- **Dapp developers:** "If block times are X% slower than assumed, time-based rate limits (e.g., 'execute every 100 blocks = 20 min') will be off by Y%."
- **Validators:** "Block time variance suggests you should expect Z milliseconds of jitter in your slot assignment."
- **Researchers:** "Using block height as a time proxy introduces Z% systematic error in time-based event studies."

---

## IDENTIFICATION CONCERNS: SENSITIVITY ANALYSIS

### 5.1 Current State: None

The paper plan does not mention sensitivity analysis. Yet the main identifying assumption (that block height is a valid time proxy) is untested.

### 5.2 Required Sensitivity Analysis

**Framework:** Oster (2019) for selection on unobservables; Rosenbaum bounds for matching-based analyses.

#### Sensitivity Analysis 1: Omitted Variable Bias in Congestion-Delay Relationship

If the paper estimates the causal effect of mempool congestion on block delay (a secondary objective), conduct Oster delta sensitivity:

$$\Delta_i = \alpha + \gamma \cdot \text{MempoolSize}_{i-1} + \varepsilon_i$$

- Compute $\gamma$ with no controls (short regression)
- Compute $\gamma$ with protocol state controls (long regression)
- Calculate Oster delta: the coefficient movement divided by R-squared movement
- **Breakpoint:** At what delta does the effect flip sign or become zero?

**Interpretation:** "An unobserved confounder would need to explain 2.3x more variation than mempool size (our richest control) to eliminate the effect of congestion on block delay."

#### Sensitivity Analysis 2: Measurement Error in Block Timestamps

If using on-chain `block.timestamp` (proposer-set time), there is potential measurement error (proposers can set timestamps within a valid window). Conduct classical measurement error analysis:

- Regress observed delay on true delay (measured with Poisson model of slot production) with measurement error added
- How much does measurement error attenuate $\gamma$?
- What is the implied true effect if noise is proportional to block time?

**Output:** "The observed correlation between congestion and delay is attenuated by 15–20% due to timestamp error. The true effect may be X–Y units per unit congestion."

#### Sensitivity Analysis 3: Breakpoint for Block Time Regularity

Define a "breakpoint" as the level of unobserved confounding needed for the paper's conclusion to reverse.

- **Main finding:** $\beta_1 = 12.2$ (post-Merge block time is 1.7% slower than design)
- **Breakpoint question:** How much unobserved confounding in the Merge indicator ($\beta_3$) would be required for the post-Merge slowdown to disappear?
- **Answer:** If confounders explain an additional 25% of variation beyond observed controls, the slowdown would be halved.

### 5.3 Recommendation

Add a "Sensitivity Analysis" subsection to the econometric spec:
- [ ] Oster delta for any causal effects estimated
- [ ] Measurement error analysis for block timestamps
- [ ] Rosenbaum-style bounds if using propensity score matching on validator type
- [ ] E-value for any binary outcomes (e.g., "Did block X have zero transactions?")

---

## RED FLAGS DETECTED

### Red Flag 1: Causal Language Without Causal Specification

The Identification Strategy (Section 1) uses causal language ("because network congestion... create endogenous delays") but the econometric specification is purely descriptive. This is a **critical inconsistency**.

**Action:** Either:
- **Reframe as descriptive:** "We characterize the empirical relationship between block height and elapsed time" (accurate to the spec)
- **Implement causal spec:** Add treatment variables, instruments, and identification assumptions (to match the strategy)

### Red Flag 2: No Mention of Autocorrelation

Block-level data is heavily autocorrelated. Standard errors will be biased downward by orders of magnitude. The spec does not mention this.

**Action:**
- [ ] Compute Newey-West HAC standard errors with lag order ≥ 15 minutes
- [ ] Compare to naive OLS SE; report ratio (should be 2–3x larger)
- [ ] Plot autocorrelation function (ACF) of residuals to diagnose

### Red Flag 3: Sample Spans Incomparable Periods

Regressing all blocks from 2015–present assumes the relationship is stationary over 10 years. But:
- Pre-2017: very low transaction volume
- 2018–2020: recovery period
- 2020–2021: DeFi boom, high congestion
- 2021–2022: multiple upgrades, EIP-1559, staking growth
- Sept 2022: **The Merge** (major change)
- 2022–present: new validator ecosystem

**Action:**
- [ ] Fit Model 2 (segmented) with multiple breakpoints (not just Merge)
- [ ] Or: estimate post-Merge only (Sept 2022–present) as primary
- [ ] Report pre-Merge results as robustness check or historical context

### Red Flag 4: No Discussion of Data Quality

Block timestamps can be:
- Off-chain propagation time (noisy, observation-point dependent)
- On-chain block.timestamp (set by proposer, subject to strategically behavior)
- Consensus finality time (finalized timestamp, 12–100+ seconds after proposal)

The paper does not specify which.

**Action:**
- [ ] Define precisely which timestamp is the dependent variable
- [ ] Conduct robustness check: estimate model with multiple timestamp definitions
- [ ] Report which definition is used in main results

### Red Flag 5: No Pre-Analysis Plan

Given the exploratory nature of this project, pre-commit to:
- [ ] Main specification (which econometric model is primary?)
- [ ] Sample definition (time period, inclusion criteria)
- [ ] Primary outcome (seconds per block, block regularity, variance of delays?)
- [ ] Threshold for significance or practical importance

Without pre-commitment, there is risk of p-hacking or specification searching.

---

## STRENGTHS OF THE APPROACH

### Strength 1: Well-Motivated Phenomenon

The core observation is real and consequential: Ethereum block timing deviates from protocol design, especially post-Merge. This matters for researchers, developers, and validators. The motivation is clear.

### Strength 2: Natural Experiment Structure

The Merge (Sept 2022) is a clean, exogenous change in protocol parameters. Using it as a breakpoint (Model 2) is sound.

### Strength 3: Large, High-Quality Data

Ethereum block data is public, timestamped to the second, and highly available. 2.2 million post-Merge blocks provide substantial statistical power.

### Strength 4: Policy Relevance

Understanding whether Ethereum achieves its design goals (12-second block time, predictable finality) has direct implications for regulatory frameworks and institutional adoption.

---

## RECOMMENDATIONS

### Immediate (Before Data Collection)

1. **Clarify the research question:** Is this a descriptive study (what is block time?) or causal (why does it deviate?)?
   - If descriptive: drop causal language from Identification Strategy, reframe as empirical characterization
   - If causal: add treatment variables (mempool size, validator diversity), specify identification assumptions, add IV if needed

2. **Define the dependent variable precisely:**
   - [ ] On-chain block.timestamp or off-chain propagation time?
   - [ ] Wall-clock seconds or in units of slots?
   - [ ] Block delay (Δ_i) or cumulative elapsed time?

3. **Specify the sample:**
   - [ ] Post-Merge only (Sept 2022–present) or full history?
   - [ ] All blocks or a stratified sample?
   - [ ] Inclusion/exclusion criteria?

4. **Pre-commit to the main econometric model:**
   - [ ] Is Model 1 (linear baseline) or Model 2 (segmented) primary?
   - [ ] Are there additional breakpoints (Shanghai, Dencun, etc.)?
   - [ ] Will you estimate time-varying models or rolling windows?

### Before Estimation

5. **Data quality checks:**
   - [ ] Plot block timestamps over time. Are there gaps, jumps, or anomalies?
   - [ ] Compute descriptive statistics: mean block time, standard deviation, quantiles, by time period
   - [ ] Check for missing blocks or duplicates

6. **Resolve autocorrelation:**
   - [ ] Compute Newey-West HAC standard errors
   - [ ] Alternatively: aggregate to daily averages to reduce dependence
   - [ ] Report ACF of residuals

7. **Test for non-stationarity:**
   - [ ] Conduct Augmented Dickey-Fuller test on block timestamps
   - [ ] If non-stationary: difference the series or use first-differencing

### Before Reporting Results

8. **Conduct sensitivity analysis:**
   - [ ] Oster delta for any causal effects
   - [ ] E-values if binary outcomes
   - [ ] Measurement error bounds for timestamp noise

9. **Robustness checks:**
   - [ ] Estimate separately for different time periods (first 6 months post-Merge, later periods)
   - [ ] Use different timestamp definitions (on-chain vs. off-chain)
   - [ ] Exclude known anomaly periods (client bugs, network attacks)

10. **Visualization:**
    - [ ] Plot block time over time (time series)
    - [ ] Plot elapsed time vs. block height (scatter with fitted line)
    - [ ] Plot distribution of block time delays (histogram)
    - [ ] Plot sensitivity curves (effect on delta, confidence intervals as function of R_max)

---

## SUMMARY OF CONCERNS

| Concern | Severity | Status | Recommendation |
|---------|----------|--------|-----------------|
| Causal claims without causal identification | **HIGH** | Current | Reframe as descriptive OR add treatment variables + IV |
| No mention of autocorrelation in SE | **HIGH** | Current | Implement Newey-West HAC or temporal aggregation |
| Undefined dependent variable | **HIGH** | Current | Specify: on-chain timestamp vs. propagation time |
| No sensitivity analysis | **MEDIUM** | Current | Add Oster delta, E-values, measurement error bounds |
| Sample spans incomparable periods | **MEDIUM** | Current | Focus on post-Merge; segment by protocol upgrades |
| Multiple breakpoints not addressed | **MEDIUM** | Current | Extend Model 2 to include Shanghai, Dencun |
| No pre-analysis plan | **MEDIUM** | Current | Pre-commit to main spec, sample, and thresholds |
| Potential reverse causality in congestion-delay | **MEDIUM** | Conditional | Use lag structure or IV if testing causal mechanism |

---

## CONCLUSION

This project has a compelling research question and access to high-quality data. However, the identification strategy currently conflates descriptive measurement with causal inference. The econometric specification (OLS of elapsed time on block height) answers "what is the average block time?" but not "why does it deviate from design?" or "what observable factors predict deviations?"

**Path Forward:**

1. **If the goal is descriptive:** Accurately label the paper as an empirical characterization of block timing post-Merge. Report point estimates, confidence intervals (with proper SE), and time-varying analysis. This is valuable and defensible.

2. **If the goal is causal:** Specify the causal mechanism clearly. Add treatment variables (e.g., mempool size, validator diversity). Justify identification assumptions. Use IV if needed for reverse causality. Conduct sensitivity analysis.

**Critical next steps:**
- [ ] Clarify the research objective (descriptive vs. causal)
- [ ] Define the dependent variable and sample precisely
- [ ] Address autocorrelation in standard errors
- [ ] Add sensitivity analysis for omitted confounders
- [ ] Pre-commit to main specification before seeing data

With these revisions, the paper will have a sound identification strategy aligned with its econometric implementation.

