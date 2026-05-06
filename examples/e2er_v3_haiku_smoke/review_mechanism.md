# PEER REVIEW: Block Height vs. Elapsed Time on Ethereum Post-Merge

**Paper ID:** 1f256351-d253-47cf-9fcf-a745fc7fe08f  
**Title:** Temporal Dynamics of Ethereum: Block Height, Time, and Protocol Stability After the Merge  
**Status:** Idea Stage  
**Review Date:** 2025

---

## DIMENSION SCORES

- **Contribution:** 5/10
- **Identification:** 6/10
- **Empirics:** 5/10
- **Writing:** 7/10
- **Literature:** 6/10

---

## OVERALL SCORE: 5.5/10

## RECOMMENDATION: **Reject**

**Rationale:** The paper addresses a phenomenon with modest relevance but conflates three distinct empirical questions (trend estimation, variance characterization, and causal mechanism identification) without clarity on which is primary. The identification strategy conflates descriptive estimation of temporal deviations with causal inference about network conditions, lacks appropriate controls, and proposes specifications that cannot distinguish between protocol design artifacts and genuine economic mechanisms. While writing is competent and the phenomenon is real, the conceptual foundation is insufficient for acceptance at a top venue.

---

## MAJOR CONCERNS

### 1. Fundamental Conceptual Confusion: Descriptive vs. Causal Claims

**The core problem:** The paper simultaneously pursues three incompatible research objectives:

- (A) **Descriptive:** Characterize the empirical time-to-height relationship and estimate deviations from the 12-second protocol design post-Merge.
- (B) **Variance decomposition:** Attribute variance in block intervals to validator heterogeneity, network congestion, consensus dynamics, etc.
- (C) **Causal mechanism:** Estimate the causal effect of network congestion (or client version, or validator performance) on block delays.

**Why this matters:** The identification strategy section claims causal ambitions (e.g., "network conditions → validator delay → observable deviation") but the econometric specifications are purely descriptive regressions of height on time. A regression of elapsed time on block height cannot identify causal effects of network congestion on block delays—it only estimates the average slope.

**Example of the confusion:** Section 2.2 of the Identification Strategy defines "conditional relationships" but then the Econometric Spec only proposes pooled OLS with time dummies, which do not address:
- Endogeneity (congestion may reverse-cause block delays, or both respond to unobserved demand shocks)
- Simultaneous causation (validators may slow inclusion speed to manage mempool; block delays may be chosen, not imposed)
- Selection bias (blocks produced during congestion may be non-randomly selected by proposers)

**Actionable fix:** Choose one of (A), (B), or (C) as the primary research question. If descriptive: report smoothed fits, variance decompositions (e.g., via ARCH/GARCH or wavelets), and temporal patterns without causal language. If causal: specify the identification threat, propose a strategy (instrumental variables, quasi-experimental design, natural experiment), and justify credibility. Do not mix.

---

### 2. Identification Strategy Does Not Address the Core Threat: Endogeneity of Block Delays

**The threat:** Block delays (Δ_i in the causal model) are endogenous—they may be:

1. **Reverse causation:** Validators observe congestion and *deliberately* delay block proposals to optimize MEV or gas inclusion. This is not exogenous network stress, but an optimal response.
2. **Simultaneity:** Unobserved demand shocks (e.g., attack, liquidation cascade, token launch) cause both network congestion and validator behavior changes, confounding the effect.
3. **Measurement error:** Block timestamps are set by proposers and attesters, not wall-clock time. Clock skew across validators introduces systematic measurement error that correlates with network conditions (high-demand periods coincide with client lag).

**Current response:** The Identification Strategy invokes "observable chain state variables" (S_i: mempool size, gas usage) but then proposes to condition on these in a simple regression—which does not resolve endogeneity. Conditional on congestion, a positive correlation between block delay and mempool size could reflect:
- True causal effect (congestion → delay)
- Reverse causation (delays → backlog → higher mempool size)
- Confounding (both driven by demand spike)

The paper provides no exclusion restriction, no temporal ordering proof, no natural experiment, and no IV strategy.

**Actionable fix:** Either:
- **Adopt a descriptive framing:** Abandon causal language. Report unconditional moments (mean block time, variance, autocorrelation, distribution) post-Merge by time period. Use spectral analysis to isolate periodicity (e.g., if 12-second rhythm is stable, show power spectrum peaks at 12s; if skipped slots, show 24s, 36s peaks).
- **Propose a quasi-experimental design:** Identify a plausibly exogenous shock to validator participation or network latency (e.g., Dencun upgrade affecting gas, or temporary client bug causing mass operator restart). Compare block timing before/after via diff-in-diff.
- **Use an instrumental variable:** If block delays are proxied well by aggregate network latency (e.g., via BGP routing data or DNS resolution time across geographies), use as IV for endogenous validator congestion. But this requires external data not mentioned in the plan.

---

### 3. Econometric Specifications Conflate Design Artifacts with Behavioral Phenomena

**The core issue:** The specification in Econometric Spec Section 1.2 proposes a piecewise linear model with a break at the Merge. This will fit the data, but the estimated slope change (β_3) **is not interpretable as evidence of a mechanism**—it reflects:

- (a) The mechanical shift from PoW (15.3s target) to PoS (12s target) by protocol design
- (b) One-time effects of Merge execution (validator participation ramp-up, network stabilization)
- (c) Actual temporal irregularities (skipped slots, validator delays)

**Why the problem is acute:** If β_3 is negative (post-Merge blocks get faster), this is *expected* by design and tells us nothing about network stress or validator behavior. The paper cannot distinguish design from mechanism without a much more granular specification.

**Example:** Suppose post-Merge block time averages 12.8 seconds instead of 12.0. The piecewise linear model estimates this as a level shift or slope shift. But this 0.8s overage is due to:
- Skipped slots? (If 8% of slots are empty, average observed time = 12s × 1/0.92 ≈ 13.04s) ✓
- Validator latency? (Blocks produced 0.8s after slot start on average)
- Attestation aggregation delays in the next slot?
- A combination?

The linear model cannot decompose these.

**Actionable fix:** Stratify the analysis:
- **Sub-question 1:** Characterize the distribution of block intervals post-Merge. Report mean, median, quantiles, skewness. Are intervals Poisson (12s ± noise) or clustered (many 12s, some 24s, some 36s)? This reveals slot skipping.
- **Sub-question 2:** For blocks that ARE produced in their assigned slot, how much do they deviate from the slot start timestamp? This isolates validator latency from slot skipping.
- **Sub-question 3:** Correlate deviations with observable state (mempool size, pending transactions, client version count). This informs whether delays are stress-driven or structural.
- Do NOT attempt to interpret a single aggregate slope as evidence of mechanism.

---

### 4. Data Availability and Specificity Are Underspecified

**Missing details that are essential for evaluation:**

- **Data source:** Will you use chain.link's public Ethereum API, or download full archive node data? API latency and reorg handling are critical if blocks are queried post-production (reorg risk biases time estimates).
- **Sample definition:** From what date post-Merge? The Merge was Sept 15, 2022. Do you analyze all subsequent blocks, or subsample (weekly, monthly)? This affects stationarity and seasonality control.
- **Timestamp definition:** Ethereum block headers contain a *block.timestamp* field set by the proposer (not accurate to seconds; it's an integer). This is NOT wall-clock time. Wall-clock time requires external data (e.g., block propagation time from a network monitor). The paper uses "wall-clock elapsed time" but has not specified how to construct this.
- **Measurement error:** How large is timestamp jitter? If validators' clocks are skewed by 1-2 seconds, the 12-second regularity is unobservable. Is this addressed?
- **Client version data:** The plan mentions validator client heterogeneity (Section 2.3). How will you obtain client version for each validator per epoch? This requires Beaconcha.in or similar; it's not in the chain itself. Feasibility?

**Actionable fix:** In the Methods section (to be written), specify:
- Exact data sources and access method
- Date range, sample size (number of blocks, time period)
- How wall-clock time is constructed (chain timestamps only? external time sync layer? both?)
- Handling of reorgs and timestamp outliers (e.g., blocks with timestamp < parent timestamp)
- Summary statistics of timestamp jitter and missing data

---

### 5. Identification Strategy Conflates Temporal Deviation with Causal Mechanisms; No Falsifiable Predictions

**The causal model in Identification Strategy Section 1 is stated as:**

$$t_i = i \times 12 + \Delta_i(S_i, C_i, V_i)$$

Where Δ_i (delay) is *caused by* network congestion (S_i), chain state (C_i), and validator composition (V_i).

**Critical gap:** The paper does not specify *how* each of these variables affects Δ_i, or what the predictions are. For instance:

- **S_i (congestion):** Does higher mempool size increase or decrease block delay? Theory is ambiguous:
  - *Increase delay:* Larger mempool requires more time to construct blocks (block building computational overhead).
  - *Decrease delay:* Validators producing blocks faster to extract MEV or meet time-optimal inclusion.
  - *Non-monotonic:* Delays peak at intermediate congestion; at very high congestion, validators use preset block templates.
  
  The paper does not articulate a directional hypothesis.

- **C_i (chain state):** "Reorg risk" and "fork likelihood" are vague. Post-Merge, Ethereum uses Gasper consensus with 2-epoch finality; reorgs deeper than one epoch are cryptographically impossible. Does the paper mean 1-slot reorg risk? How is this measured?

- **V_i (validator composition):** Does validator heterogeneity *increase* or *decrease* block time regularity? If validators have heterogeneous internet latency, we expect slower blocks to delay subsequent ones (latency autocorrelation). But if heterogeneity leads to robust decentralization, maybe delays are *lower* in expectation. No model.

**Why this matters:** Without directed predictions, the paper cannot be falsified. If the regression shows a positive correlation between congestion and block delay, it's consistent with the theory. If it shows negative correlation, it's also consistent (reverse causation, or simultaneity, or V_i dominates S_i). This is the hallmark of unfalsifiable science.

**Actionable fix:** State a directed causal model. Example:
- *Hypothesis 1:* Block delays (Δ_i) increase monotonically with mempool size (S_i), because validators incur computational overhead in transaction selection. *Prediction:* Coefficient on S_i is positive and significant. *Mechanism:* Block builder latency.
- *Hypothesis 2:* Validator geographical diversity (measured as latency dispersion across attesters) increases slot-skipping but does NOT increase delays conditional on slots producing blocks. *Prediction:* Coefficient on V_i (diversity) on block delay is zero; coefficient on V_i on slot-skip rate is positive.
- Then test these hypotheses. If H1 is rejected, revise the theory.

---

### 6. Missing Robustness Checks and Alternative Explanations

**Design artifacts the paper has not accounted for:**

1. **Gasper finality and reorg effects:** Post-Merge, validators may delay block proposals if prior slot is under dispute or reorg risk is high. This is a *protocol safety feature*, not pathology. The paper does not separate delays due to protocol design from delays due to network stress.

2. **Dencun upgrade (March 2024):** Proto-danksharding changed gas economics and block structure. If the sample includes pre- and post-Dencun blocks, there may be a regime shift. The paper does not mention this.

3. **Validator exit/entry flux:** After Shanghai upgrade (April 2023), staking became liquid via liquid staking derivatives. This may have changed validator participation and network heterogeneity. Timing?

4. **MEV-Boost adoption:** Most validators use MEV-Boost, which introduces asynchronous relay communication and adds 0.5-2s to block production. If adoption changed over time, this is a confound. Not mentioned.

5. **Client software version distribution:** Ethereum has multiple consensus clients (Prysm, Lighthouse, Lodestar, Nimbus). Client bugs or performance differences are plausible causes of delays. But analyzing this requires external data (e.g., from Beaconcha.in's client monitor) not mentioned.

**Actionable fix:** In Results, report:
- Sensitivity to sample period (pre/post major upgrades)
- Stratified analysis by validator client type (if data available)
- Separate analysis for validator-inclusion-list transactions vs. MEV-Boost blocks
- Falsification test: regress block delays on future network variables (if correlation exists, suggests reverse causation or measurement error)

---

## MINOR CONCERNS

### 1. Literature Review Lacks Recent Blockchain Empirics

The lit review cites Ethereum Foundation 2022 and Buterin et al. 2020 (protocol papers), which are appropriate for background. But it misses recent empirical work on:

- **Post-Merge block timing:** Papers analyzing actual PoS block intervals post-Merge exist on arXiv and Ethereum research forums. The review is incomplete.
- **MEV and block delays:** Flashbots and Protocol Labs have published analyses of block proposer latency correlated with MEV extraction. Not cited.
- **Blockchain empirics methods:** Recent papers (e.g., Bahng et al. 2024 on liquidity on Ethereum) use methods for high-frequency blockchain data that could be adapted here (e.g., realized volatility of block intervals as a liquidity/stress metric).

**Minor fix:** Add 5-8 citations to recent blockchain empirics papers. Avoid purely technical Ethereum documentation; cite empirical analysis.

---

### 2. Causal Model Notation is Ambiguous

The delay function is written as Δ_i(S_i, C_i, V_i), suggesting functional form and causality. But:

- Are these contemporaneous effects (same-slot causes) or lagged (prior-slot causes)?
- Is the function linear, non-linear, or threshold-based?
- Are S_i, C_i, V_i measured in absolute units (e.g., mempool size in MB) or percentiles?

**Minor fix:** Specify the functional form, measurement units, and lags explicitly. Example: Δ_i = α + β₁ S_{i-1} + β₂ C_i + β₃ V_i + ε_i, where S_{i-1} = mempool size (MB) in slot i−1.

---

### 3. Sample Size and Statistical Power Not Discussed

Post-Merge (Sept 2022 to present ~2 years) at 12-second slots = ~5.25M blocks. This is large enough for OLS inference, but the paper does not discuss:

- Effective degrees of freedom (given autocorrelation in delays)
- Power to detect effect sizes of interest (e.g., 0.1s change in delay per 100MB mempool)
- Clustering strategy for standard errors (by epoch? validator client? geography?)

**Minor fix:** Pre-specify sample size, expected effect size, and power calculation. Report robust standard errors with clustering strategy justified.

---

### 4. Writing is Clear but Lacks Precision in Definitions

Examples:

- "Protocol stress" is used informally to mean "deviation from 12-second regularity." Is stress a latent variable? Observable? Measurable? Define formally.
- "Validator heterogeneity" could mean: client version distribution, geographic dispersion, stake size distribution, or internet latency distribution. Specify.
- "Systematic deviation" is used to mean both (a) non-zero mean deviation and (b) autocorrelated deviation. These are distinct.

**Minor fix:** Add a Definitions section or formally define each construct before use in Identification Strategy.

---

### 5. Ethical and Data Privacy Considerations Omitted

The paper proposes to analyze validator client versions and infer validator-level latency. This may enable:

- Doxing of validator operators (identifying physical location from latency patterns)
- Targeted attacks on slower validators
- Privacy violations if validator identity is linked to client data

**Minor fix:** Add a brief discussion of privacy safeguards (e.g., anonymization, aggregation levels, disclosure risks).

---

## POSITIVE ASPECTS

### 1. Phenomenon is Real and Relevant

Block timing irregularities post-Merge are observable and of genuine interest to protocol developers, stakers, and empirical researchers. If properly specified, this work could provide value.

---

### 2. Research Question is Timely

Ethereum's post-Merge performance is actively debated. An empirical characterization of block timing (absent causal claims that cannot be supported) would inform this debate constructively.

---

### 3. Writing and Organization are Competent

The draft is well-structured, clearly written, and easy to follow. Figures are planned (though not shown here). This is above-average technical writing for an idea-stage paper.

---

### 4. Identification Strategy Attempts to Be Explicit About Causal Claims

Rather than slipping in causal language without justification, the paper explicitly articulates a causal model (Δ_i as a function of S_i, C_i, V_i). This is good practice, even though the model is not fully developed.

---

### 5. Econometric Specifications Show Awareness of Structural Breaks

The piecewise linear specification (Section 1.2 of Econometric Spec) is appropriate for testing the Merge as a break point. The impulse response and time-series GARCH models show methodological sophistication.

---

## SYNTHESIS AND PATH FORWARD

### What This Paper Could Become

**Option A (Descriptive empirics — publishable):** Reframe as a detailed characterization of Ethereum post-Merge block timing. Report:
- Distribution of block intervals (mean, variance, quantiles, ACF, spectral analysis)
- Evidence on slot skipping (proportion, clustering)
- Temporal patterns (intraday, weekly, epochal)
- Comparison to PoW pre-Merge baseline
- No causal claims about network conditions; no endogeneity concerns

Target venue: *Blockchain and Cryptocurrency Economics* or *Journal of Financial Market Microstructure* (if written carefully).

**Option B (Causal mechanism with quasi-experiment — publishable):** Identify a plausibly exogenous shock to validator behavior (e.g., Dencun upgrade, staking derivative adoption, client version bug fix) that arguably changes S_i or V_i without directly changing Δ_i, and use diff-in-diff to estimate causal effects. Requires additional data (external shock timing) and setup.

Target venue: *Management Science*, *MIS Quarterly* (if method is rigorous).

**Option C (Current path — not publishable):** Continue with vague causal claims, linear regressions on endogenous conditioning variables, and unfalsifiable theory. This paper will be desk-rejected from top venues for conflating description with causation.

---

## DETAILED SCORING RATIONALE

### Contribution (5/10)

**Why not higher:** The phenomenon is real, but the paper's intellectual contribution is modest. Characterizing block time post-Merge is useful, but:
- Not novel: Ethereum researchers and stakers already know blocks take ~12s, sometimes longer, due to network conditions and protocol dynamics.
- Not surprising: Deviations from ideal 12s are expected given validator heterogeneity and network realities.
- Not generalizable: Findings are specific to Ethereum and do not advance understanding of consensus mechanisms broadly or blockchain scalability.

**Why it's a 5 and not 3:** The phenomenon *could* yield insights if framed as descriptive empirics or if a valid causal design is implemented. The foundation exists; execution is lacking.

### Identification (6/10)

**Why not higher:** The identification strategy articulates a causal model but provides no strategy to estimate it credibly. The threat of endogeneity is severe and unaddressed.

**Why it's a 6 and not 4:** The paper is aware that causality is claimed and attempts to be explicit about it. No false pretense. But credibility is low without addressing confounding.

### Empirics (5/10)

**Why not higher:** Specifications are sensible (piecewise linear, ARCH/GARCH models are appropriate for time-series data), but:
- Data pipeline is not yet designed (source, cleaning, validation)
- Measurement strategy is unclear (wall-clock time construction)
- No robustness or falsification checks proposed
- No power analysis or effect size specification

**Why it's a 5 and not 3:** The specifications proposed are methodologically sound for a descriptive empirical analysis. Concerns are about application, not principle.

### Writing (7/10)

**Why not higher:** The writing is clear and organized, but:
- Some concepts are defined informally (protocol stress, heterogeneity)
- Notation is sometimes ambiguous (Δ_i function form)
- Lit review is incomplete (missing recent blockchain empirics)

**Why it's a 7:** The organization, clarity, and technical competence are above average for an idea-stage paper. A strong 7; needs minor tightening.

### Literature (6/10)

**Why not higher:** Coverage of Ethereum protocol documentation is solid, but:
- Missing recent blockchain empirics literature (post-2022)
- Missing related work on MEV, client diversity, and validator heterogeneity
- Missing econometric methods literature on time-series analysis of high-frequency data (realized volatility, etc.)

**Why it's a 6:** Lit review is adequate for background but insufficient for positioning novel contributions within the state of the art.

---

## FINAL RECOMMENDATION

**Reject.** The paper conflates descriptive temporal characterization with causal mechanism identification, proposes specifications that cannot identify causal effects, and does not address endogeneity. Before resubmission, the authors must:

1. **Choose a research question:** Descriptive characterization of block timing post-Merge, OR causal effect of network conditions on delays (with a valid identification strategy).
2. **Develop a credible identification strategy** if pursuing causality: propose instrumental variables, natural experiments, or quasi-experimental design.
3. **Expand the empirical pipeline:** specify data sources, measurement strategy, robustness checks, and falsification tests.
4. **Update literature review** to include recent blockchain empirics and consensus mechanism analysis.

If revised to focus on descriptive empirics (Option A above), this work could be acceptable with methodological rigor. If revised with a quasi-experimental design (Option B), it could be strong. In its current form, it is not ready for submission to a top-tier journal.

---

## DETAILED COMMENTS FOR REVISION

### For Descriptive Reframing:

- Title: Change to "Characterizing Block Timing Irregularities on Ethereum Post-Merge: Empirical Patterns and Protocol Implications"
- Remove all causal language (causation, mechanism, explanation)
- Add Section 3: Descriptive Statistics
  - Mean, median, std dev, quantiles of block intervals
  - Histogram and Q-Q plots
  - ACF and spectral density of intervals (evidence of slot skipping?)
  - Intraday, weekly, and epochal patterns (U-shaped intraday patterns like equities markets?)
- Add Section 4: Variance Decomposition
  - Break down block interval variance into:
    - Variance from slot skipping (deterministic, protocol design)
    - Variance from proposer latency (stochastic, network-dependent)
    - Variance from client software differences (if data available)
  - Use Bayesian hierarchical model or multilevel regression if possible

### For Causal Reframing:

- Title: Change to "Network Stress and Block Delays: Evidence from Ethereum's Merge to Proof-of-Stake"
- Specify causal graph (DAG): S_i → Δ_i ← Z (unobserved confounder)
- Propose IV strategy or quasi-experiment
  - IV option: Use past network latency (BGP data, geolocation) as instrument for current congestion
  - Quasi-experiment option: Exploit Dencun rollout (staggered, by rollup first adoption) as exogenous change to gas dynamics
- Estimate reduced-form and structural models
- Conduct falsification (e.g., future variables should not predict current delays)

---

END OF REVIEW
