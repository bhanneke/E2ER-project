# PEER REVIEW: "Temporal Dynamics of Ethereum: Block Height, Time, and Protocol Stability After the Merge"

**Paper ID:** 1f256351-d253-47cf-9fcf-a745fc7fe08f  
**Stage:** Idea Development / Early Draft  
**Reviewed:** January 2025  
**Review Type:** Referee simulation for top-tier IS/Finance journal

---

## DIMENSION SCORES

| Dimension | Score | Notes |
|-----------|-------|-------|
| **Contribution** | 6/10 | Novel empirical phenomenon, but limited theoretical insight; narrow audience |
| **Identification** | 5/10 | Mechanism proposed but not causally identified; observational confounding unaddressed |
| **Empirics** | 5/10 | Econometric specs outlined but missing critical robustness; data quality/availability unclear |
| **Writing** | 7/10 | Clear framing and motivation; well-structured outline; logic flows |
| **Literature** | 6/10 | Adequate coverage of Ethereum specs; gaps in blockchain measurement literature and causal inference |

---

## OVERALL SCORE: 5.9/10

**RECOMMENDATION: MAJOR REVISION** (Reject in current form; possible acceptance with substantial reframing)

---

## MAJOR CONCERNS

### 1. **No Causal Identification of Proposed Mechanism — Critical Threat to Validity**

**Specific Issue:**  
The identification strategy claims block delays are driven by network congestion (S_i), chain state (C_i), and validator heterogeneity (V_i), but provides no credible source of causal variation to separate these from confounding. The proposed specification:

$$\text{DelayTime}_i = f(S_i, C_i, V_i) + \varepsilon_i$$

**Why This Fails:**
- All three mechanisms (congestion, chain state, validator mix) are endogenous to the blockchain itself. A validator who skips a slot causes congestion in the next slot, which causes delays, which affects validator selection — circular causality.
- No instrumental variable, natural experiment, or quasi-random assignment is proposed to break this loop.
- Reverse causality: delays may cause apparent congestion (users defer transactions waiting for slots to normalize) rather than congestion causing delays.
- Omitted variable bias: protocol software bugs, client diversity crashes, or timestamp synchronization errors would show up as delays but are not in the model.

**Path to Revision:**
- Explicitly scope the contribution as **descriptive empirics only**: document the empirical relationship without causal claims. Reframe as "What is the distribution of inter-block times post-Merge?" rather than "What causes deviation?"
- OR adopt a quasi-experimental design: exploit exogenous events (e.g., major client software upgrades, network latency shocks from external infrastructure failures, staking provider outages) as instruments.
- OR partner with protocol developers to access validator-level telemetry (which validators skipped, why, CPU/network diagnostics) to make the identification credible.

---

### 2. **Critical Data Availability and Measurement Gaps — Paper Feasibility Unknown**

**Specific Issue:**  
The paper plan references data needs but does not confirm data availability or quality:

- **Wall-clock time source:** Are timestamps from block headers (reported by proposer, unverified) or from distributed observer clocks? Block timestamps can be manipulated within bounds (±12 seconds) by proposers. No discussion of measurement error.
- **Network congestion proxy (S_i):** Proposed to use mempool size, gas usage, pending transactions. But post-Merge, should this be measured at proposer's perspective (biased) or network average? How to handle layer-2 and MEV-Boost bundling?
- **Validator heterogeneity (V_i):** Are validator-client distributions publicly available? The paper does not specify source. Will this be etherscan data, Beaconcha.in, or proprietary node telemetry?
- **Chain state (C_i):** How to measure reorg risk in real-time? Retrospective measurement of historical reorg frequency is feasible but retrospective, not forward-causal.

**Path to Revision:**
- Produce a **data appendix before analysis**: document source, collection method, missing data rates, and measurement error bounds for each variable.
- Conduct a **feasibility pilot**: sample 1 week of post-Merge data (Sep 22-29, 2022), construct variables, document obstacles. Publish this as online appendix or pre-analysis plan (OSF registry).
- Consider downscoping to **publicly available data only** (block headers, Beaconcha.in attestations, Etherscan): this is reproducible but lower-resolution.

---

### 3. **Insufficient Literature Review — Key Streams Missed**

**Specific Gaps:**

a) **Blockchain measurement literature:** Papers on Ethereum throughput dynamics, transaction latency, and mempool behavior are undersummarized:
   - No mention of how prior work (e.g., Akaki 2022 on Ethereum MEV; Weinberg et al. 2019 on transaction confirmation) handles time measurement.
   - No discussion of censorship/reorg risk literature (Daian et al. 2019 "Flash Boys 2.0"; Schiavone & Seuken on MEV-Boost impact on consensus).
   - Missing: Buterin et al. 2019 "Casper the Friendly Finality Gadget" — the protocol document is cited but not analyzed for implications of finality delay.

b) **Causal inference in observational systems:** The paper claims a causal mechanism but does not engage with:
   - Pearl's causal hierarchy (association vs. intervention vs. counterfactual); no DAG (directed acyclic graph) provided.
   - Synthetic control or matching methods for quasi-experimental designs (standard in finance/IS for endogenous systems).
   - Granger causality or vector autoregression (VAR) literature on feedback systems.

c) **Econometric specification:** Missing references:
   - Time-series properties: is the relationship cointegrated? If block height and elapsed time are I(1) unit roots, OLS is biased (Granger & Newbold 1974). Augmented Dickey-Fuller (ADF) or Johansen cointegration tests must precede regression.
   - Autocorrelation in block delays: if delays are serially correlated (likely under consensus dynamics), OLS standard errors are biased downward (Newey-West correction needed).
   - Heteroskedasticity by network regime: pre- vs. post-Merge; high vs. low traffic periods. No discussion of Breush-Pagan testing or clustered standard errors.

d) **Missing contemporary work:**
   - Recent Ethereum research on slot efficiency post-Merge (e.g., Lashkari et al. 2023 on validator performance).
   - MEV-Boost rollout effects (November 2023 onwards) on block production timing — this is a structural break not discussed.
   - Shapella upgrade (April 2023) effects on staking participation and validator composition.

**Path to Revision:**
- Expand literature section to 4–5 pages (not 2–3). Organize into: (1) Ethereum consensus architecture; (2) Prior blockchain measurement work; (3) Consensus dynamics and time measurement in distributed systems; (4) Causal inference in observational blockchain data.
- Create a citation matrix: for each proposed variable (delay, congestion, validator type), cite 2–3 prior papers that use similar measurement.
- Explicitly position relative to at least one concurrent working paper on post-Merge Ethereum dynamics (e.g., search ArXiv/SSRN for "Ethereum slot" or "validator performance" 2023–2024).

---

### 4. **Econometric Specification Incomplete — Multiple Sources of Bias**

**Specific Issues:**

a) **Model 1 (Linear OLS):** Proposes $\text{ElapsedTime}_i = \beta_0 + \beta_1 \cdot \text{BlockHeight}_i + \varepsilon_i$

- **Problem:** This assumes the relationship is constant over 10 years of data (Jan 2015 to now). Ethereum is not a stationary system. The relationship almost certainly changes with:
  - Hashpower fluctuations (pre-Merge)
  - Difficulty bomb delays
  - Shanghai upgrade (PoS reorg improvements)
  - Network growth and node count
- **Remedy:** Include epoch fixed effects or control for calendar time. Alternatively, estimate on post-Merge data only (Sep 2022 to present ≈ 2 years) and acknowledge pre-Merge period separately.

b) **Model 2 (Segmented regression):** Includes a structural break at Merge.

- **Problem:** Only tests one break point. But Ethereum has had ~15 protocol upgrades since genesis. Shouldum test for breaks at Shanghai (April 2023), Dencun (March 2024)? How sensitive is the result to the break-point choice?
- **Remedy:** Run Quandt-Andrews test (unknown break date) or Bai-Perron (multiple breaks) to identify where empirical relationships actually change, not where theory says they should change.

c) **Model 3 (Conditional delays):** Proposes to regress delay on congestion/chain state.

- **Problem:** No specification provided for which variables enter, functional form, lags, or interaction terms. Will the model include lagged delay (autoregression)? If not, is this a specification error (omitted dynamics)?
- **Remedy:** Pre-specify the full model equation. Justify lag order via Akaike/Bayesian IC. Report Durbin-Watson statistic and autocorrelation function (ACF) plots.

d) **Robustness checks:** None proposed.

- **Critical gaps:**
  - Subsample stability: are results robust to early vs. late post-Merge periods (Sep 2022–Mar 2023 vs. Apr 2023–present)?
  - Outlier sensitivity: validators sometimes have downtime or high reorg rates (Lido node outages). Are results robust to dropping top 1% of delays?
  - Measurement robustness: if timestamps are measured with ±2 second error, how does this bias estimates?
- **Remedy:** Add section "Robustness and Sensitivity Analysis" with 4–5 core checks.

---

### 5. **Contribution Scope Overstated — Limited Novelty and Audience**

**Specific Issue:**  
The paper positions itself as addressing protocol robustness, research methodology, and mechanism design. But the core finding—"block times deviate from nominal 12 seconds"—is:

- **Not novel to practitioners:** Ethereum node operators and stakers already know block times are variable. This is visible on Beaconcha.in in real-time.
- **Not surprising theoretically:** Consensus protocols with asynchronous networks always exhibit timing variance. This is known since Lamport & Shostak 1982.
- **Of limited applied impact:** The paper does not propose a fix, mechanism change, or recommend validator behavior change. It is purely descriptive.

**Scope Issues:**
- The identified audience (protocol researchers, dapp developers, stakers, policy makers) spans multiple communities with different needs. A single paper cannot address all adequately. The contribution is either:
  - **Too broad** (if trying to speak to all audiences) → lacks depth for any single audience.
  - **Too narrow** (if focusing on one audience, e.g., empirical researchers using block height as a time proxy) → niche contribution.

**Path to Revision:**
- **Sharpen the contribution:** Choose ONE primary audience and ONE high-impact finding. For example:
  - *For dapp researchers:* Show that time-based aggregations (e.g., "last 1000 blocks ≈ 3.33 hours") introduce systematic bias in time-series analysis. Quantify this bias and propose a correction method.
  - *For protocol researchers:* Characterize which validators/clients are responsible for slot skipping and propose monitoring/alerting heuristics.
  - *For stakers:* Analyze whether block delays are correlated with MEV and estimate the implied economic inefficiency.
- Reframe as a focused empirical brief (5–8 pages) with a single clear policy implication, not a comprehensive phenomenon review.

---

### 6. **Missing Pre-Analysis Plan and Potential p-Hacking Risk**

**Specific Issue:**  
The paper is at "idea stage" but proposes 3+ models and multiple secondary outcomes (delay distribution, congestion correlation, validator attribution). With this flexibility, there is risk of:

- Testing multiple specifications and reporting only those with low p-values.
- Deciding sample composition (e.g., which validators to include, which time periods) after seeing data.
- Post-hoc variable transformations (e.g., logging, winsorizing) to achieve "better fit."

This is common in observational blockchain research and undermines statistical credibility.

**Path to Revision:**
- Before any analysis, register a pre-analysis plan (PAP) on OSF (Open Science Framework) or AsPredicted. Specify:
  - Exact sample: e.g., "All blocks from Sep 15, 2022 (post-Merge) to 2024-12-31."
  - Primary outcome: e.g., "β₁ estimate in Model 1; test H0: β₁ = 1/12."
  - Secondary outcomes: e.g., "Conditional delay distribution under high vs. low congestion."
  - Exclusion criteria: e.g., "Drop blocks with timestamp >120 seconds from prior block (reorg/restart)."
  - Robustness checks: e.g., "Subsample by client type, validator size, MEV-Boost membership."
- Publish the PAP before running regressions. Report deviations from PAP (and justify) in final paper.

---

## MINOR CONCERNS

### 1. **Methodological Ambiguity in Defining "Block Time" vs. "Slot Time"**

The literature review conflates "block time" (actual time between consecutive blocks on the canonical chain) with "slot time" (the protocol-designated 12-second duration per slot). Under Ethereum PoS:

- **Expected:** 1 block per slot → 12 seconds per block.
- **Observed:** Some slots have 0 blocks (skipped slots), some have 1+ blocks (reorgs, forks). The relationship between slot count and wall-clock time is perfect (# slots = elapsed time / 12), but block count is not.

**Recommendation:** Clearly distinguish:
- **Slot interval:** Always exactly 12 seconds (not a random variable; deterministic).
- **Block interval:** Variable; depends on proposer behavior, reorg resolution.
- **Block production rate:** The slope β₁ in the OLS model; estimated as empirical blocks per unit time.

Define which is the outcome variable in each model. The current paper is ambiguous.

---

### 2. **Insufficient Motivation for Non-Linear Specifications (Models 4, 5)**

The econometric specification section proposes polynomial and cubic spline models but does not justify why non-linearity is expected. Block production is a renewal process; why would the relationship between cumulative count and elapsed time be non-linear in the residuals rather than white noise?

**Recommendation:** 
- Provide theoretical or empirical justification: e.g., "Network effects predict that delay increases convexly with congestion because of queuing dynamics" (cite queueing theory).
- Plot scatter (block height vs. elapsed time) and visually assess linearity before model choice.
- Use specification tests (Ramsey RESET test) to compare linear vs. nonlinear fit.

---

### 3. **Validator Attribution (Section 3.2 of Identification Strategy) Unresolved**

The identification strategy proposes to "attribute delays to individual validators or client type," but this requires:
- Identifying which validator produced each block (Beaconcha.in provides some data, but with latency and attribution uncertainty).
- Linking validators to client type (Prysm vs. Lighthouse vs. Nimbus) — this is not always public.
- Handling anonymized staking pools (Lido, Rocket Pool) where individual validator identity is obscured.

**Current Status:** Unspecified.

**Recommendation:**
- Conduct a data availability assessment: for what % of post-Merge blocks can validator identity be reliably assigned? Document sources and confidence intervals.
- Scope attribution claims conservatively: e.g., "Among labeled validators in Lido, we estimate X% of delays correlate with client type" rather than claiming universe coverage.

---

### 4. **Statistical Power and Sample Size Not Discussed**

The dataset (all Ethereum blocks since genesis, ~19–20 million blocks) is very large. With such large N, even tiny effects (β ≈ 0.001 seconds per block) will be statistically significant at p < 0.001. Conversely, practical significance is unclear.

**Recommendation:**
- Specify the effect size of interest: e.g., "We aim to detect delays > 0.5 seconds per block with 95% power."
- Pre-specify what counts as a "meaningful" result vs. "statistically significant but economically trivial."
- Report 95% confidence intervals alongside p-values. If the CI is [12.00, 12.01] seconds per block, this is practically null even if p < 0.001.

---

### 5. **Temporal Aggregation and the "Levels vs. Differences" Choice**

The paper uses levels (elapsed time, block height) in the OLS model. But if both are trending unit roots, the regression is spurious (Granger & Newbold 1974) and β₁ has a non-standard distribution.

**Current Status:** No unit root tests, cointegration analysis, or justification of specification choice.

**Recommendation:**
- Before regression, run ADF test on both elapsed time and block height (indexed over the post-Merge sample). If both are I(1), test for cointegration (Engle-Granger or Johansen). If cointegrated, report cointegrating vector; if not cointegrated, use differences or express results as a long-run elasticity.
- Alternatively, if the focus is on deviations from protocol norm, define $\text{Deviation}_i = \text{ObservedTime}_i - 12i$ (expected time per protocol) and regress deviation on covariates. This ensures the outcome is stationary and theoretically grounded.

---

### 6. **Causality Language Too Strong in Current Draft**

The identification strategy states: *"network conditions → validator delay → observable deviation"* and treats this as causal. But the paper has no experimental design, instrumental variables, or temporal sequencing to establish causality.

**Recommendation:**
- Use associational language until identification is solid: "network congestion is *correlated with* block delays" not "causes."
- If causal claims are desired, explicitly propose an identification strategy (IV, DiD, RDD, etc.) that is credible given the data and context.

---

## POSITIVE ASPECTS

### 1. **Clear Problem Motivation and Practical Relevance**

The paper articulates why block timing matters (protocol robustness, empirical methodology, mechanism design) with concrete examples. This is well-written and would engage readers. The observation that researchers often treat block height as a deterministic time proxy is correct and underexplored.

---

### 2. **Appropriate Scope and Data Environment**

Post-Merge Ethereum is a good phenomenon to study: the protocol is publicly specified (12-second slots), data is transparent and verifiable, and the event (Sep 2022 Merge) provides a natural comparison point. This is superior to studying private blockchains or proprietary systems.

---

### 3. **Well-Structured Research Design Framework**

The paper provides clear sections on phenomenon, objectives, identification strategy, and econometric models. This organization is logical and would support a strong paper if the underlying analyses are credible. The use of piecewise regression for structural breaks is appropriate.

---

### 4. **Legitimate Secondary Analyses**

Proposed secondary objectives (conditional delay distributions, validator heterogeneity, mempool dynamics) are sensible if the primary analyses hold. These would provide actionable insights for protocol monitoring.

---

### 5. **Acknowledges Measurement Challenges**

The identification strategy and econometric section hint at measurement issues (timestamp reliability, congestion measurement). This awareness is a good foundation for robustness.

---

## SUMMARY OF REVISIONS REQUIRED FOR ACCEPTANCE

| Priority | Issue | Action |
|----------|-------|--------|
| **Critical** | Causal identification unresolved | Reframe as descriptive OR propose credible quasi-experimental design (IV, matching, RDD). Cannot identify causal mechanism from observational data alone. |
| **Critical** | Data availability unconfirmed | Produce data appendix with sources, measurement error, missing-data rates before analysis begins. Run feasibility pilot. |
| **Critical** | Literature review incomplete | Add 2–3 pages on blockchain measurement, consensus dynamics, causal inference in observational systems. |
| **High** | Econometric specification incomplete | Add unit root tests, autoregression diagnostics, heteroskedasticity tests, Durbin-Watson stats. Specify all Models 3–5 fully. |
| **High** | Contribution scope unclear | Narrow to single audience + one high-impact finding. Consider reframing as applied brief for dapp developers or protocol monitors. |
| **High** | Pre-analysis plan missing | Register on OSF before analysis to mitigate p-hacking risk. |
| **Medium** | Block time vs. slot time ambiguity | Define precisely in methods section. Clarify which is outcome variable in each model. |
| **Medium** | Validator attribution feasibility | Document data availability for validator identity and client type. Qualify claims accordingly. |
| **Medium** | No robustness checks proposed | Add subsample stability, outlier sensitivity, measurement error robustness. Report 95% CIs, not just p-values. |
| **Low** | Causality language | Shift to associational framing ("correlated") unless causal identification is established. |

---

## RECOMMENDATION FOR NEXT STEPS

**Current Status:** Reject in present form.

**Path Forward:**

1. **If pursuing causal claims:** Collaborate with Ethereum developers (Protocol Research group at EF) to access validator-level telemetry and design a quasi-experimental evaluation. This substantially raises the bar but makes the contribution defensible.

2. **If pursuing descriptive contribution:** Downscope to a focused empirical brief (8 pages):
   - Document block time distribution post-Merge (histogram, quantiles, ACF).
   - Show that time-based aggregations are biased; quantify correction factor.
   - Propose a simple monitoring heuristic for infrastructure operators.
   - This is publishable in a blockchain/systems venue even if not top-tier finance.

3. **In either case:**
   - Expand literature review significantly.
   - Conduct data availability pilot and register pre-analysis plan.
   - Add econometric diagnostics (unit root, autocorrelation, heteroskedasticity tests).
   - Narrow the scope to a single, high-impact finding rather than addressing all stakeholders.

---

## FINAL REMARKS

This paper addresses a legitimate empirical phenomenon (block timing irregularity on Ethereum) with clear practical motivation. The research design framework is sound, and the writing is lucid. However, the paper is not ready for review in its current form due to:

- **Unresolved causal identification** (core methodological flaw)
- **Incomplete literature review** (missing key streams and citations)
- **Underspecified econometric models** (missing diagnostic tests)
- **Unclear scope and audience** (too broad; lacks focus)

With substantial revision—particularly addressing the causal identification strategy or reframing as descriptive—this could become a solid empirical contribution for a blockchain/systems audience or a specialized finance journal. It is not suitable for a top-tier general-interest management or IS journal without causal identification.

**Estimated revision effort:** 6–8 weeks for a junior researcher with Ethereum familiarity; 10–12 weeks for those new to blockchain systems.

