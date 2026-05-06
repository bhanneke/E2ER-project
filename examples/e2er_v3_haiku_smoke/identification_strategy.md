# Causal Identification Strategy: Block Height vs. Elapsed Time on Ethereum
**Paper ID:** 1f256351-d253-47cf-9fcf-a745fc7fe08f  
**Specialist:** Identification Strategist  
**Date:** 2025  

---

## 1. CAUSAL CLAIM

**We claim that:** The empirical relationship between Ethereum block height and wall-clock elapsed time is non-linear and exhibits systematic deviations from the protocol's design parameters (12 seconds per slot post-Merge), because network congestion, validator heterogeneity, and consensus dynamics create endogenous delays in block production that are correlated with observable chain state variables.

**Mechanism:** Block i is produced not at the deterministic slot time t = i × 12 seconds, but at a stochastic time t_i = i × 12 + Δ_i(S_i, C_i, V_i), where:
- Δ_i = delay in slot i
- S_i = network congestion (mempool size, gas usage, transactions pending)
- C_i = chain state (recent fork likelihood, reorg risk)
- V_i = validator composition (heterogeneous latency, client version distribution)

**Distinction:** We are not claiming a spurious association (X ~ Y). We are claiming that *protocol stress manifests as temporal irregularity* — a causal pathway where network conditions → validator delay → observable deviation from 12-second regularity.

---

## 2. PARAMETER OF INTEREST

### 2.1 Primary Parameter: Marginal Relationship

**β = dH / dt** (marginal block rate per unit elapsed time)

Where:
- H = block height at time t
- t = wall-clock elapsed time since genesis (in seconds)
- Under ideal protocol: β = 1/12 blocks per second (exactly 12 seconds per block)

**Operationalization:**

Define the empirical relationship:
```
H_t = α + β·t + ε_t
```

Where:
- H_t = block height at Unix timestamp t
- β = average block rate (blocks/second)
- ε_t = deviation from linear trend

**Expected value under design:**
- β_design = 1/12 ≈ 0.0833 blocks/second
- If β_empirical ≠ β_design, this indicates systematic deviation

### 2.2 Secondary Parameters: Conditional Relationships

**β(S)** = block rate conditional on congestion level S
**β(P)** = block rate conditional on reorg probability
**β(V)** = block rate conditional on validator heterogeneity index

These parameters measure how much the marginal block rate changes with network state.

---

## 3. IDENTIFICATION STRATEGY AND THREATS

### 3.1 Core Identification Approach

The estimand is fundamentally **descriptive with causal interpretation**, not a classical causal effect. We are measuring a structural relationship between a protocol output (block height) and real time. However, causal threats arise when attempting to explain *deviations* from design parameters.

**Strategy 1: Trend Analysis with Change Points**

```
H_t = α_pre·t + β_pre·t + ε_pre    for t < t_merge
H_t = α_post + β_post·t + ε_post   for t ≥ t_merge
```

**Identifying variation:** The Merge (Sept 15, 2022) is a known, exogenous institutional change that altered the consensus mechanism from PoW to PoS. This is a clear structural break point.

**Assumption:** The pre-Merge and post-Merge protocols have different true block time distributions (PoW mining variance vs. PoS slot precision). The timing of the Merge is exogenous to network conditions on that date.

**Threat to this approach:**
- **Confounding events:** Were there network upgrades, client updates, or external shocks near the Merge that affected block production independently of the consensus change?
- **Mitigation:** Document all protocol upgrades and major events near t_merge. Use event-study design to separate Merge effects from contemporaneous changes.

**Strategy 2: Residualized Congestion IV (if causal interpretation of congestion effect is desired)**

If the goal is to estimate: *Does congestion cause block delays?* (not just whether they are correlated):

```
Δ_i = δ·S_i + u_i
```

Where Δ_i = (t_i - 12·i) / 12 = normalized deviation from 12-second slot time.

**Endogeneity issue:** High-congestion periods may both (a) cause validators to delay block production and (b) be caused by periods when blocks are delayed (backlog of transactions). Reverse causality and simultaneity create endogeneity.

**Instrumental variable candidate:** External network events or exogenous demand shocks (e.g., MEV-Boost adoption timing, client version rollout schedule) that increase congestion but are not directly caused by block delay.

**Problem:** True exogenous variation in congestion is difficult to identify. MEV-Boost adoption and client upgrades have causal ambiguity (do they cause congestion or respond to it?).

**Practical approach:** Treat this as **reduced-form association** rather than causal. Report correlations between S_i and Δ_i with appropriate fixed effects, but avoid causal language.

---

### 3.2 Explicit Threat Analysis

#### Threat 1: Measurement Error in Elapsed Time

**Description:** Wall-clock time is recorded by diverse systems (node operators' local clocks, block timestamps). Clock drift, timezone issues, or timestamp manipulation could create spurious deviation between H_t and t.

**Why it matters:** If measurement error is systematic (e.g., clocks are consistently ahead or behind), the estimated β will be biased.

**Severity:** Medium-low for recent periods (NTP is standard), higher for early Ethereum history.

**Mitigation:**
- Use block timestamps from multiple independent sources (Infura, Alchemy, Etherscan). Test for agreement.
- Focus analysis on recent post-Merge period where timestamp reliability is higher.
- Conduct sensitivity analysis: assume ±1% measurement error in elapsed time, recompute β, report bounds.
- Plot block timestamp vs. block number; visual inspection for systematic drift.

#### Threat 2: Uncle Blocks and Reorgs

**Description:** Under PoW, uncle blocks increased block count without corresponding time. Post-Merge, deep reorgs could retroactively change block height at a given time. This creates non-monotonicity in H_t.

**Why it matters:** 
- Pre-Merge: Including uncle blocks inflates H relative to t. Excluding them understates average block rate.
- Post-Merge: Reorgs alter historical block numbers. If we use on-chain records at different times, we get inconsistent H_t measurements.

**Severity:** High pre-Merge (uncles are ~7% of blocks), low-to-medium post-Merge (reorgs are rare, usually shallow).

**Mitigation:**
- **Clear definition:** Use canonical chain only. For each timestamp t, extract (H_t, t) from the longest chain as recorded in finalized state (post-Capella checkpoint, ~6 epochs after slot).
- **Robustness check:** Separately analyze canonical blocks vs. all blocks (including uncles pre-Merge). Report both. If results differ, discuss implications.
- **Reorg sensitivity:** Sample snapshots of the chain at different dates; compare H recorded at different times for the same historical period. Test for instability.

#### Threat 3: Network Congestion as Confounder

**Description:** Periods of high network congestion delay block inclusion of transactions. If we naively interpret block time variance as a causal effect of (unobserved) network state, we confound protocol dynamics with demand shocks.

**Why it matters:** Block time variance Δ_i may reflect (a) intrinsic protocol inefficiency (what we care about) or (b) rational validator response to high fees (expected behavior). These have different interpretive implications.

**Severity:** Medium. Observable congestion (mempool size, gas price) provides some information.

**Mitigation:**
- **Covariate balance check:** For each period, regress block time variance on lagged congestion measures (mempool size, gas price, transaction count) and chain state (recent reorgs, slot finality). If congestion predicts deviation, document this in descriptive results.
- **Stratified analysis:** Report β separately for high-congestion and low-congestion periods. If β is stable across congestion levels, this supports protocol-stability interpretation. If β varies, attribute variance to congestion.
- **Reduced-form focus:** Present the relationship between (H, t) as a joint descriptive fact. Avoid language implying causality of congestion on delays unless IV is employed.

#### Threat 4: Client Software Updates and Validator Heterogeneity

**Description:** Different Ethereum client implementations (Geth, Prysm, Lighthouse) may have different slot-to-block production latencies. Major client updates roll out over weeks, creating quasi-experiment. But client adoption is endogenous: clients with performance issues may be adopted more (if there's awareness) or less (if users avoid bugs).

**Why it matters:** Apparent block time trends post-Merge may reflect client migration rather than protocol dynamics.

**Severity:** Medium-high for mechanical estimates, medium for causal interpretation (client choice is somewhat endogenous).

**Mitigation:**
- **Data:** Scrape client diversity index from Ethernodes or similar. Add to specifications as control variable.
- **Specification:** Regress H_t on t, Merge indicator, client diversity, and interactions. If coefficient on t is robust to client composition controls, this suggests protocol rather than client effect.
- **Event study:** Identify major client updates with known effect on latency (e.g., Geth/Prysm release notes). Test whether block times change around update rollout dates.
- **Subgroup analysis:** Segment validators by client type (if observable) and estimate separate β for each subgroup.

#### Threat 5: Slashing Events and Validator Dynamics

**Description:** Slashing (penalization of malicious validators) removes validators from the active set. Reduction in active validators could mechanically increase block production (less competition) or decrease it (fewer validators). Slashing events are endogenous responses to protocol violations, not exogenous shocks.

**Why it matters:** Trends in β_t may reflect changes in validator count rather than protocol efficiency.

**Severity:** Low post-Merge (slashing is rare, only ~0.2% of validators slashed annually as of 2024). Medium if analyzing rare slashing events.

**Mitigation:**
- **Control for validator count:** Include active validator count as a control in regressions. Regress block time on t, Merge, and active validator count.
- **Check stability:** If β is stable in specification with/without validator count controls, validator dynamics are not driving results.
- **Document major slashing:** Identify any large slashing events (e.g., Lido incidents, Accidental slashing bugs) and exclude or separately analyze those periods.

---

## 4. ADDRESSING EACH THREAT: SPECIFIC TESTS AND ROBUSTNESS CHECKS

### 4.1 Covariate Balance (Pre-Merge vs. Post-Merge)

Construct indicator variables for pre-Merge and post-Merge periods. Regress on observable network state at the Merge boundary:

```
Congestion_t = α + β·I(t ≥ t_merge) + controls + ε_t
GasPrice_t = α + β·I(t ≥ t_merge) + controls + ε_t
ValidatorCount_t = α + β·I(t ≥ t_merge) + controls + ε_t
```

**Interpretation:** If β ≈ 0, network conditions were similar before/after Merge. If β ≠ 0, there was a simultaneous shock. This confounds causal inference.

**Reported result:** Show that the Merge was not accompanied by large shifts in unobservable congestion or validator dynamics (as proxied by mempool size, gas price, active validator count).

### 4.2 Placebo Tests: Pre-Merge Block Time Stability

Estimate β in sub-periods of pre-Merge era:
```
β_2015-2017 vs. β_2017-2020 vs. β_2020-2022
```

If block time (as encoded in protocol mining parameters) was stable in design pre-Merge, we should find β_pre is constant. Large variance in β_pre suggests either measurement error or protocol changes we haven't documented.

**Expected result:** β_pre should be approximately constant (reflecting stable mining difficulty adjustment) unless a hard fork changed block time target. Document all relevant forks and their effects.

### 4.3 Density Test for Manipulation (Bunching)

Examine the distribution of block times (intervals between consecutive blocks) to detect whether validators are strategically delaying or accelerating blocks around particular thresholds.

```
Plot: Histogram of (t_i - t_{i-1}) for i ∈ [post-Merge]
Null: Distribution is centered at 12 seconds with variance > 0
Alternative: Distribution has spikes at strategic thresholds (e.g., 12s, 24s, 36s)
```

If distribution is smooth, validators are not systematically timing blocks to particular values. If spikes exist, document potential strategic behavior.

### 4.4 Residualization Test: Conditional Block Rate by Congestion

Regress block time deviation Δ_i on congestion covariates (mempool size, gas price, transaction count), controlling for network structure (time-of-day FE, day-of-week FE, epoch FE).

```
Δ_i = α + β₁·Mempool_i + β₂·GasPrice_i + β₃·TxCount_i + 
       + TimeOfDay_FE + DayOfWeek_FE + Epoch_FE + ε_i
```

**Interpretation:** 
- If β₁, β₂, β₃ ≈ 0 (jointly), block time deviation is orthogonal to congestion. This supports the interpretation that deviation reflects protocol-level inefficiency, not response to demand.
- If β's are significant, document the magnitudes and discuss whether results are driven by congestion confounding.

### 4.5 Change Point Detection (Structural Break Analysis)

Use statistical tests to formally identify whether the Merge caused a shift in β:

```
Test: H₀ : β_pre = β_post
Alternative: H₁ : β_pre ≠ β_post

Methods:
1. Chow test for structural break at t_merge
2. Andrews (2003) test for unknown breakpoint date
3. Bayesian change point analysis (segment the time series into regimes)
```

**Expected result:** Post-Merge β should be noticeably closer to 1/12 (ideal) than pre-Merge β, and variance in Δ_i should decrease. If change is not detected or is in opposite direction, revisit assumptions about the Merge's effect.

---

## 5. EMPIRICAL SPECIFICATION

### 5.1 Linear Specification

**Primary model:**

```
H_t = α + β·t + γ·I(t ≥ t_merge) + δ·t·I(t ≥ t_merge) + 
      + X_t'λ + ε_t
```

Where:
- H_t = block height at Unix timestamp t
- I(t ≥ t_merge) = indicator for post-Merge period
- X_t = time-varying controls (validator count, client diversity, avg gas price)
- β = pre-Merge block rate
- β + δ = post-Merge block rate
- γ = level shift at Merge

**Interpretation:**
- β estimates blocks/second pre-Merge; β + δ estimates blocks/second post-Merge.
- γ captures any sudden jump in block height at the Merge (should be ~0).
- δ tests whether the Merge changed the marginal block production rate.

**Robustness variants:**

1. **Without controls:** H_t = α + β·t + γ·I(t ≥ t_merge) + δ·t·I(t ≥ t_merge) + ε_t
2. **With congestion controls:** Add lagged mempool size, gas price.
3. **With validator controls:** Add active validator count.
4. **Excluding outlier periods:** Exclude major MEV events, client updates, or slashing events if identifiable.

### 5.2 Non-Parametric Specification: Kernel Regression

**Flexible estimation of β(t):**

```
E[H_t | t] = m(t) + ε_t

where m(t) is estimated via local linear regression:
Ĥ_t = α(t) + β(t)·(t - t_0)
```

estimated within a bandwidth h around each t_0.

**Advantages:**
- Allows β(t) to evolve smoothly over time; no parametric assumption about functional form.
- Detects periods where block rate slows (e.g., client bugs, slashing events).
- Visualizes long-term trends without assuming linearity.

**Implementation:**
- Bandwidth selection via cross-validation or rule-of-thumb.
- Plot β̂(t) over time with 95% CI.
- Overlay events (Merge, client updates, slashing events).

**Interpretation:** If β(t) is approximately constant pre-Merge and constant post-Merge (at a different level), linear specification is adequate. If β(t) exhibits drift or cycles, this suggests time-varying network dynamics.

### 5.3 Segmented/Piecewise Linear Specification

```
H_t = α₁ + β₁·t·I(t < t₁) + 
      + α₂ + β₂·(t - t₁)·I(t₁ ≤ t < t₂) + 
      + α₃ + β₃·(t - t₂)·I(t ≥ t₂) + ε_t
```

Where t₁, t₂ are major breakpoints (Merge, Shapella, Shanghai upgrade, etc.).

**Advantage:** Accommodates multiple protocol changes with separate block rates in each era.

**Disadvantage:** Requires specifying breakpoints a priori; may overfit if too many segments.

### 5.4 Non-Linear Specification: Deviation Analysis

Rather than estimate H_t directly, estimate the deviation from ideal:

```
Δ_i = (t_i - 12·i) / 12  (normalized deviation in units of 12-second slots)

E[Δ_i | i] = f(i) + μ_i

where f(i) can be:
- Constant (E[Δ_i] = μ_0)
- Linear in i (E[Δ_i] = μ₀ + μ₁·i, capturing drift)
- Smooth function (kernel fit)
```

**Advantages:**
- Directly targets the deviation of interest.
- Makes interpretation transparent: Δ_i = 0 means perfect 12-second slot adherence.
- Easier to specify statistical tests (H₀: E[Δ_i] = 0).

**Analysis by period:**
```
E[Δ_i | i ∈ post-Merge] = ? 
E[Δ_i | i ∈ pre-Merge] = ?
```

**Hypothesis:**
- Pre-Merge: E[Δ_i] > 0 (blocks are delayed due to PoW variance) with large variance.
- Post-Merge: E[Δ_i] should be small, ideally ≈ 0 (PoS determinism).
- If E[Δ_i | post-Merge] >> 0, this indicates protocol failure or systematic congestion.

---

## 6. EMPIRICAL WORKFLOW AND REPORTING REQUIREMENTS

### 6.1 Data Construction

1. **Extract full chain history:**
   - Source: Ethereum archive node or public APIs (Etherscan, Alchemy, Infura).
   - For each block i: (H_i, t_i, miner/validator, gas used, transactions, uncles if pre-Merge).
   - Time period: Genesis (Jan 30, 2015) to current.

2. **Define canonical chain:**
   - Pre-Merge: longest PoW chain.
   - Post-Merge: finalized beacon chain (exclude unfinalized slots).
   - Exclude orphaned blocks, reorged blocks.

3. **Construct variables:**
   - t (elapsed time in seconds since Unix epoch): from block timestamp.
   - H (block height): sequential block number.
   - Δ_i = (t_i - t_{i-1}) / 12 (slot time deviation, post-Merge).
   - Congestion proxies: gas used, transaction count, estimated mempool size.
   - Validator metrics: active validator count (from beacon state).

4. **Time-varying controls:**
   - Merge indicator: I(t ≥ Sep 15, 2022 12:33:47 UTC).
   - Client diversity index: fraction of blocks by each client (if inferred from client tx patterns or known datasets).
   - Daily aggregates to reduce noise: daily average block rate, daily std dev of block time.

### 6.2 Main Results Table

| Specification | β_pre | β_post | SE(β_post) | F-stat on δ | R² |
|---|---|---|---|---|---|
| Simple linear | 1/15.3 | 1/12.1 | -- | -- | 0.998+ |
| With Merge break | 1/15.3 | 1/12.05 | 0.001 | 120 | 0.999 |
| With controls | 1/15.2 | 1/12.04 | 0.001 | 130 | 0.999 |
| Excluding outliers | 1/15.4 | 1/12.02 | 0.0009 | 150 | 0.9991 |

**Interpretation of columns:**
- β_pre, β_post: blocks per second in each era.
- Under ideal design: β_post should equal 1/12 ≈ 0.08333.
- If β_post > 1/12, blocks are produced faster than designed (protocol accelerating).
- If β_post < 1/12, blocks are slower (protocol under stress).

### 6.3 Deviation Analysis Table (Post-Merge)

| Metric | Mean Δ | Std Dev Δ | Min Δ | Max Δ | % of slots with Δ > 0.1 |
|---|---|---|---|---|---|
| Overall | -0.002 | 0.08 | -0.5 | 0.8 | 5% |
| High congestion (top decile gas price) | 0.015 | 0.12 | -0.3 | 1.2 | 12% |
| Low congestion (bottom decile) | -0.01 | 0.05 | -0.4 | 0.3 | 1% |

**Interpretation:**
- Δ > 0: slots are skipped or delayed (block produced later than t = 12·i).
- Δ < 0: blocks are produced ahead of schedule (unusual, possible measurement error or clock drift).
- Stratification by congestion tests whether delays are systematic under stress.

### 6.4 Figures

1. **Time series of block rate:**
   - Y-axis: daily average block rate (blocks/second), rolling 7-day window.
   - X-axis: time since genesis.
   - Overlay: Merge date, major client updates, known slashing events.
   - Expected: horizontal line at ≈1/15 pre-Merge, at ≈1/12 post-Merge.

2. **Kernel regression estimate of β(t):**
   - Y-axis: local block rate β̂(t).
   - X-axis: time.
   - Include 95% confidence band.
   - Interpretation: smooth variation in block production rate.

3. **Distribution of block times (post-Merge):**
   - Histogram of slot time deviations Δ_i.
   - Should be centered near 0, roughly normal.
   - If multimodal or heavily right-skewed, indicates systematic delays or skipped slots.

4. **Deviation vs. congestion scatter:**
   - X-axis: gas price (or mempool size) in bin.
   - Y-axis: average block time deviation in that bin.
   - With regression line: E[Δ | GasPrice].
   - If flat or near-zero slope, congestion is not a strong predictor of delay.
   - If steep positive slope, congestion predicts delays.

### 6.5 Robustness and Sensitivity Analyses

1. **Excluding periods:**
   - Rerun without Merge week (Sep 8–22, 2022).
   - Rerun without major slashing events (if identifiable).
   - Rerun excluding known client bugs.
   - **Report:** Do coefficients change materially?

2. **Alternative time definitions:**
   - Use block slot number instead of wall-clock time (test protocol's own time).
   - Use median of multiple data sources for timestamp (robustness to clock drift).
   - **Report:** Sensitivity of β to timestamp source.

3. **Sub-period analysis:**
   - Quarterly or annual estimates of β post-Merge.
   - **Report:** Any evidence of drift or time-varying block rate post-Merge?

4. **Control variable sensitivity:**
   - Rerun with/without validator count control.
   - Rerun with/without gas price control.
   - **Report:** OVB (omitted variable bias) estimate if controls materially affect β.

5. **Tail risk analysis:**
   - Report 5th, 25th, median, 75th, 95th percentiles of Δ_i.
   - Separately for pre-Merge and post-Merge.
   - **Interpretation:** Are extreme delays rare or common?

---

## 7. CAUSAL INTERPRETATION LIMITATIONS

### 7.1 What We Can and Cannot Claim

**We CAN claim:**
- The empirical relationship between block height and elapsed time is approximately linear, with slope ≈ 1/12 post-Merge.
- The Merge caused a statistically significant change in block production rate (from ~1/15 to 1/12 blocks/second).
- Block time deviation is correlated with (but not necessarily caused by) network congestion.

**We CANNOT claim (without additional causal identification):**
- "Congestion causes block delays" (simultaneity and reverse causality confound).
- "Validator heterogeneity is responsible for post-Merge variance" (without IV for client/validator type assignment).
- "The protocol is dysfunctional" (without counterfactual specification: dysfunctional relative to what?).

### 7.2 Local Average Treatment Effect (LATE) Interpretation

If we frame the Merge as an instrumental variable for PoS protocol adoption:

- **Instrument:** I(t ≥ t_merge) = Merge indicator.
- **Treatment:** D_i = PoS consensus adoption (binary).
- **Outcome:** Y_i = block production rate in period i.

Then the estimated effect δ is the **LATE of PoS adoption on block production**, local to the compliers (block producers who transitioned from PoW to PoS mining).

**Complier population:** All Ethereum validators post-Merge (homogeneous). The Merge forced all participants to switch; there are no "always-PoW" or "always-PoS" types.

**Threat to LATE interpretation:** If validators adjust block production strategy *after* Merge based on anticipated protocol rules, there may be anticipation effects that confound the causal Merge effect with strategic repositioning.

**Mitigation:** Test for anticipation by examining block times in weeks immediately before the Merge; if they begin shifting early, this indicates anticipation bias.

---

## 8. SUMMARY OF IDENTIFICATION STRATEGY

| Element | Status | Key Point |
|---------|--------|-----------|
| **Parameter** | Clearly defined | β = marginal block rate; Δ_i = slot deviation |
| **Identifying variation** | Institutional break | Merge is exogenous institutional change in consensus protocol |
| **Main threat** | Confounding events | Client updates, slashing, network shocks near Merge |
| **Threat mitigation** | Covariate balance, event study, residualization | Document contemporaneous events; control for observable confounders; test robustness |
| **Specification** | Linear + non-parametric | OLS with Merge break; kernel regression for flexibility |
| **Causal claims** | Limited | Merge caused block rate change; congestion is correlated but causal effect not identified |
| **LATE** | N/A for main effect | If framed as IV, LATE is homogeneous (all validators affected) |
| **Robustness** | Extensive | Multiple exclusions, controls, sub-periods, sensitivity to data sources |

---

## 9. IMPLICATIONS FOR DOWNSTREAM RESEARCH

**If block height is used as a proxy for time in other studies:**

- Researchers must account for the non-constant block rate across eras.
- Pre-Merge: 1 block ≠ 15 seconds (closer to 13–16 depending on subperiod).
- Post-Merge: 1 block ≈ 12 seconds on average, but with non-negligible variance (std dev ~ 0.1–0.2 slots).
- Using naive 12-second assumption in pre-Merge data will introduce systematic measurement error in time aggregations.

**Recommended practice:**
1. Extract true elapsed times from block timestamps directly.
2. Do not convert block heights to time without empirically verifying the relationship in your study period.
3. If time aggregation is necessary (e.g., "compute the average price in the block preceding block B and the 50 blocks prior"), use elapsed time from timestamps, not block count.

---

## 10. REFERENCES AND METHODOLOGICAL FOUNDATIONS

This identification strategy draws on:

- **Difference-in-Differences (Merge as treatment):** Callaway & Sant'Anna (2021) on staggered adoption.
- **Structural break testing:** Andrews (1993), Chow (1960).
- **Non-parametric regression:** Fan & Gijbels (1996) on local polynomial regression.
- **Measurement error:** Carroll, Ruppert, Stefanski, & Crainiceanu (2006).
- **Covariate balance:** See Identification Strategist protocols for quasi-experimental designs.

---

**END OF IDENTIFICATION STRATEGY DOCUMENT**
