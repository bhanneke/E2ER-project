# Technical Review: Block Height vs. Elapsed Time on Ethereum

**Paper ID:** 1f256351-d253-47cf-9fcf-a745fc7fe08f  
**Title:** Temporal Dynamics of Ethereum: Block Height, Time, and Protocol Stability After the Merge  
**Review Date:** 2025  
**Stage:** Idea Development (Pre-analysis)

---

## Summary Assessment

**CONCERNS** — The paper exhibits strong conceptual motivation and clear research framing, but **critical gaps exist in the identification strategy and data construction that must be resolved before empirical work begins**. The causal mechanism is underspecified relative to what the data will actually capture. Three major implementation risks must be addressed: (1) distinguishing measurement error from true protocol deviation, (2) handling endogeneity between block production delays and network state variables, and (3) specifying how blocks are indexed and deduplicated across reorganizations.

---

## Data Pipeline

### Status: **UNREADY — Missing Critical Specifications**

#### Issues Identified:

**1. Data Source & Extraction Not Documented**
- The paper does not specify how block height and elapsed time will be obtained.
- Ethereum data can be sourced from: full node archives (Geth, Erigon), public APIs (Infura, Alchemy, Etherscan), or reorg-aware indexers (The Graph).
- **Risk:** Different sources may handle chain reorganizations (reorgs) differently, producing different mappings of block height to timestamp.
- **Missing:** Which source? How will reorgs be handled?

**2. The "Block Height" Variable Is Ambiguous**
- Ethereum has no single block height index; blocks are identified by `(number, hash)` pair.
- Block reorganizations are common (especially post-Merge). A block at height `h` produced at time `t` may be replaced by a different block at `(h, hash')`.
- **Critical question:** Will the analysis use:
  - **Canonical chain only** (live head, subject to future reorgs)? This creates a moving target — results change as reorgs occur.
  - **Finalized chain** (>95% reorg risk eliminated after ~2 weeks)? This delays analysis but provides stability.
  - **Manually rebased after finality** (retrospective correction)? This requires explicit reorg handling logic.
- **Current state:** The plan does not specify. This is a fatal gap.

**3. Time Reference Ambiguity**
- Blocks carry multiple time fields:
  - **Block timestamp** (header.timestamp): set by proposer, can be manipulated within limits
  - **Arrival time** (consensus client): when the block was first seen by a node
  - **Finalization time**: when state was finalized
  - **Wall-clock time**: query timestamp (differs by timezone and client clock drift)
- **Current plan assumes:** Wall-clock elapsed time from genesis (Jan 30, 2015).
- **Risk:** This conflates block proposal order with elapsed seconds. A block produced late (e.g., 20 seconds into its 12-second slot) will map to a different `elapsed_time` than a block produced on-time.
- **Missing:** Which timestamp field should be used? Should block.timestamp be preferred or arrival time?

**4. Sample Construction: No Exclusion Criteria Specified**
- Should blocks from the failed Shanghai upgrade attempt (April 2023) be excluded?
- Should blocks from Dencun (March 2024) mainnet fork be treated as breaks?
- How to handle the post-Merge slot skipping: should skipped slots (no block produced) be imputed as missing, or simply omitted?
- **Current state:** Silent. This will affect sample size and interpretation.

**5. Deduplication & Reorganization Logic Not Specified**
- Post-Merge reorgs are common (depth 1-5 blocks).
- If using non-finalized chain: a block at height `h` observed today may not exist in tomorrow's canonical chain.
- **Missing logic:**
  - If a block is orphaned post-hoc, is it dropped from analysis?
  - If yes, at what point do we consider a block "safe" (not subject to reorg)?
  - If no, how is time measured for blocks that were replaced?

#### Red Flags:

- **Implicit inner joins:** If cross-referencing block height to timestamp via a blockchain API that returns only finalized blocks, there is an implicit filter that drops unfinalized blocks. This is not documented.
- **Sample drift:** If analysis is conducted today vs. 6 weeks later, the dataset will have changed due to finality progression. Reproducibility requires specifying the exact snapshot date.

---

## Estimation Implementation

### Status: **PARTIAL — Specification is Sound, but Critical Assumptions Underspecified**

#### Alignment to Econometric Specification:

The econometric specification (Model 1 and Model 2) is clearly written and internally consistent:

- **Model 1 (Linear baseline):** `ElapsedTime_i = β₀ + β₁·BlockHeight_i + ε_i`
  - Dependent variable: elapsed time (seconds since genesis)
  - Independent variable: block height (count)
  - This is well-specified and the code implementation should be straightforward.

- **Model 2 (Piecewise linear with Merge break):** Adds intercept and slope change indicators.
  - The specification correctly identifies the Merge block (~15,550,000).
  - Joint F-test approach is standard.

**Alignment check: PASS** — If data is prepared as specified, the estimation code should directly implement these models via OLS.

#### Issues Identified:

**1. Standard Errors & Clustering: Not Addressed**
- The econometric spec does not mention clustering or robust inference.
- **Critical question:** Should standard errors be clustered at any level?
  - Blocks are not naturally clustered (one observation = one block).
  - But: if modeling blocks as nested within validators, or within time windows (e.g., epochs of 32 blocks), clustering by validator or epoch might be appropriate.
  - Alternatively: if there are persistent deviations from linearity (e.g., systematic delays in certain epochs), OLS errors will be heteroskedastic.
- **Current state:** Specification assumes i.i.d. errors. This is likely violated post-Merge due to:
  - **Slot-level clustering:** Validators assigned to nearby slots may exhibit correlated delay patterns.
  - **Time-of-day effects:** Periods of high network congestion may cluster blocks temporally.
- **Recommendation:** Use heteroskedasticity-robust standard errors (HC2 or HC3) as a baseline. Report cluster-robust SEs (by validator or epoch) in robustness tables.

**2. Functional Form: Why Level-Level? Not Justified**
- The paper models `ElapsedTime ~ BlockHeight` in levels (not logs).
- This is theoretically sound (block height is a counting process) but the specification section does not justify this choice.
- **Alternative:** Could use `log(ElapsedTime)` to model exponential vs. linear growth. Should be discussed.
- **Weaker issue, but:** Specification should acknowledge and justify the functional form choice.

**3. Fixed Effects: None Included**
- The baseline model includes no fixed effects beyond the intercept.
- **Question:** Should there be validator-level or epoch-level fixed effects?
  - If validating that **different validators produce different block delays**, yes, include `i_validator` FE.
  - If the goal is just to estimate overall block rate, fixed effects are unnecessary.
- **Current specification is silent.** This should be explicit: "We do not include FE because blocks are the unit of observation and we are interested in the population average block rate."

**4. Interaction Terms in Model 2: Correct but Needs Care**
- The Merge × BlockHeight interaction correctly captures slope change post-Merge.
- **Identification concern:** The Merge is a single event at a known date/block. There is no endogeneity (the Merge was not chosen *because* of block timing).
- **However:** The break is in event time (calendar), not block time. The code must correctly identify which blocks fall post-Merge.
  - If block #15,550,000 is the Merge block, blocks 15,550,001+ should be flagged as PostMerge=1.
  - The exact boundary is critical: off-by-one errors will bias estimates.

**5. Sample Restrictions: Not Documented**
- Does the analysis use all blocks from genesis through some end date, or a subset?
- If subset: why? (E.g., "exclude first 100 blocks due to initialization anomalies"?)
- **Missing from spec:** Any discussion of outliers. Are there blocks with extreme time gaps (reorg corrections, client bugs) that should be excluded?

---

## Results Reporting & Interpretation

### Status: **UNREADY — No results available yet; but interpretation framework is problematic**

#### Interpretation Issues (Prospective):

**1. Coefficient Interpretation: Semantically Correct, but Economically Problematic**
- Model 1 predicts: β₁ ≈ 12 (seconds per block, post-Merge)
- The interpretation "a one-unit increase in block height is associated with a 12-second increase in elapsed time" is correct.
- **However:** This is a tautology if the data are perfectly synchronous.
- **The interesting quantity is not β₁ itself, but deviation from 12:**
  - If β₁ = 12.3, this means blocks are arriving *slower than spec* (12.3 sec instead of 12 sec).
  - This is economically meaningful: "Protocol drift of +2.5% from design."
  - **Recommendation:** Report effect size as **(β₁ - 12) / 12 × 100%** — percent deviation from spec.

**2. Interpreting Model 2 (Merge Breakpoint): Correct but Needs Precision**
- β₃ (slope change) will show whether post-Merge block time improved (β₃ < 0, shorter blocks) or worsened (β₃ > 0).
- **Correct interpretation:** β₃ represents the change in average seconds per block, pre- vs. post-Merge.
- **Pitfall to avoid:** Confusing β₃ with "time savings" or "efficiency gains." β₃ is purely descriptive of the block rate change.

**3. R-squared Interpretation: Will Be Suspiciously High**
- In Model 1, if blocks are produced nearly deterministically, R² will be very high (>0.99).
- **Why this is a problem:**
  - High R² does not imply the model is correct — it reflects that block height is a nearly perfect linear clock.
  - This makes the residuals the focus of interest: what is the ~1% variation?
  - **Recommendation:** Report and interpret **σ(residuals)** as the typical deviation from 12-second regularity, not R².

#### Red Flags in Interpretation (Prospective):

**1. Confounding: Measurement Error vs. True Deviation**
- The identified relationship between block height and time conflates two mechanisms:
  1. **True protocol delay:** Validators legitimately delay block production.
  2. **Timestamp manipulation:** Proposers can set block.timestamp within a validity window (usually ±1 second from parent), creating artificial time gaps.
  3. **Measurement error:** If using external clock time instead of block.timestamp, node clock drift introduces noise.
- **Current identification strategy does not separate these.**
- **Recommendation:** Conduct robustness using different time sources (block.timestamp vs. arrival time) and compare.

**2. Endogeneity Not Addressed**
- The identification strategy claims: "Network congestion → validator delay → observable deviation"
- **But:** The econometric spec treats block height as exogenous.
- **Issue:** If congestion causes delays, which increases block height (more blocks in same wall time), then congestion is partly in the error term, creating measurement error in the RHS variable.
- **This is not a causal identification problem per se** (block height doesn't cause time; time causes block height), but it means OLS estimates will not isolate the causal effect of network conditions.
- **Better approach:** Use block.timestamp directly and model deviations from the 12-second grid as the dependent variable, then correlate with network state measures (gas used, mempool size) as controls.

**3. Post-Merge Validity: Needs Pre-Merge Benchmark**
- The paper claims deviations post-Merge, but without a clear pre-Merge baseline, readers cannot evaluate whether the post-Merge relationship is *better* or *worse*.
- **Recommendation:** Include pre-Merge period in analysis (even though paper focuses on post-Merge) to show the before/after contrast.

---

## Red Flag Detection

### Critical Red Flags:

1. **Chain Reorganization Handling Not Specified**
   - The paper does not address how reorgs will be handled. This is a showstopper for blockchain data.
   - Different choices (canonical vs. finalized vs. rebase) produce materially different results.
   - **Status:** Must be resolved before data collection.

2. **Ambiguity in "Elapsed Time" Definition**
   - Is this wall-clock time (query-dependent) or block.timestamp (proposer-set)?
   - These diverge post-Merge when validators delay blocks but backdate timestamps.
   - **Status:** Must be specified before estimation.

3. **Causal Mechanism Underspecified**
   - The identification strategy claims delays are "endogenous" to network conditions, but does not model how.
   - The econometric spec is purely descriptive (block height vs. time), not causal.
   - **Misalignment:** If the paper claims to identify *why* blocks are delayed, the econometric model must include conditioning variables. Currently it does not.
   - **Status:** Specification must be extended to include network state controls, or claims must be downscoped to "descriptive relationship."

### Major Red Flags:

4. **No Discussion of Outliers or Data Cleaning**
   - Are there blocks with extreme time gaps (>60 seconds)? These indicate reorgs or client failures.
   - The spec does not mention winsorization, trimming, or outlier treatment.
   - **Risk:** If 1-2 blocks have extreme gaps (e.g., 10-minute reorg), they will heavily influence regression slope.
   - **Recommendation:** Report histogram of block inter-arrival times and flag/document any cleaning applied.

5. **Reproducibility Concern: Dataset Snapshot Not Specified**
   - Ethereum data changes as finality progresses. Running this analysis now vs. 3 months later produces different results.
   - The plan does not specify: will the analysis use the *current* chain state, or a historically fixed snapshot?
   - **Implication:** Results may not be reproducible by other researchers unless data source and snapshot date are documented.

6. **Multiple Comparisons / Specification Search Risk**
   - The plan includes multiple secondary analyses (seasonal, validator-level, MEV interactions).
   - If many specifications are tested, p-hacking risk is present.
   - **Recommendation:** Pre-register primary vs. exploratory analyses to avoid this.

### Minor Red Flags:

7. **Robustness Checks Not Pre-Specified**
   - The identification strategy mentions robustness to "alternative definitions of congestion," but does not pre-specify which alternative measures will be tested.
   - **Concern:** This allows flexibility in reporting, which could bias results toward significant findings.
   - **Recommendation:** Pre-specify 3-5 robustness checks ex-ante.

8. **Model 2 Breakpoint: Merge Date Not Verified**
   - The spec lists Merge block as ~15,550,000, but does not cite this or verify it matches actual chain data.
   - **Minor risk:** If incorrect, the Merge indicator will misclassify blocks.
   - **Recommendation:** Cross-check block # with Etherscan or Ethereum specification.

---

## Internal Consistency Across Pipeline Stages

### Data → Estimation Alignment: **AT RISK**
- The data construction stage is not yet documented, so alignment cannot be verified.
- **Critical check once data is ready:** Verify that estimation code reads variables exactly as data stage produced them (same name, same scale, same sample size).

### Estimation → Analysis Alignment: **UNSPECIFIED**
- The plan does not describe the analysis stage (e.g., are there secondary models, heterogeneity analysis, robustness checks?).
- **Required:** Specify how results from Model 1 & 2 will be analyzed (e.g., test for seasonality, validator effects) before writing analysis code.

### RSD (Identification Strategy) → Estimation Alignment: **PARTIAL MISMATCH**
- **Identification strategy claims:** Causal relationship between network conditions (S, C, V) and block delays (Δ).
- **Econometric spec does:** Linear regression of time on block height only.
- **Gap:** The spec does not include S, C, or V as controls. This means the econometric model does not implement the causal claim.
- **Resolution needed:** Either (1) extend Model 1/2 to include network state controls, or (2) reframe the identification strategy as purely descriptive.

---

## Strengths

**1. Clear and Motivated Research Question**
- The paper identifies a genuine phenomenon (block time deviation post-Merge) that matters for protocol robustness and empirical research.
- Motivation is compelling and well-articulated.

**2. Correct Identification of the Merge as a Natural Experiment**
- The September 2022 Merge is a clean structural break at a known date.
- The piecewise linear specification (Model 2) is appropriate and well-motivated.

**3. Econometric Specification is Internally Consistent**
- The baseline (Model 1) and Merge break (Model 2) models are correctly specified (barring the issues flagged above).
- The joint F-test approach for the breakpoint is standard and appropriate.

**4. Good Awareness of Domain Context**
- The literature review correctly covers PoS consensus mechanics, Casper FFG, and post-Merge dynamics.
- Cites relevant protocol documentation (Ethereum specification, Buterin et al., 2020).

**5. Appropriate Secondary Research Questions**
- The plan's discussion of heterogeneity by validator, MEV-Boost configuration, and network conditions shows thoughtful scope expansion.

---

## Recommendations

### CRITICAL (Must resolve before data collection):

**1. Specify Chain Reorganization Handling**
   - **Action:** Document explicitly which blocks will be included in analysis:
     - Option A: Canonical chain (subject to future reorgs) → requires snapshot date
     - Option B: Finalized chain only (safe from reorg after ~2 weeks) → delays analysis but ensures stability
     - Option C: Reorg-aware indexing (e.g., The Graph subgraph that rebases) → most robust, requires specifying reorg depth tolerance
   - **Owner:** Data engineering stage
   - **Output:** Data documentation specifying reorg handling logic

**2. Define Time Reference Variable**
   - **Action:** Choose between block.timestamp (set by proposer) or arrival_time (from consensus client).
   - **Justification:** Write 1-2 sentences explaining why one is preferred (e.g., "We use block.timestamp because it is the on-chain consensus value; arrival_time is node-specific and not reproducible.")
   - **Owner:** Identification strategy document
   - **Output:** Revised identification strategy, Section on Time Measurement

**3. Specify Sample Construction and Exclusion Criteria**
   - **Action:** Document:
     - Start date (genesis or a later date?)
     - End date (current or fixed historical snapshot?)
     - Any blocks/epochs excluded (why? see: Shanghai fork, Dencun fork, etc.)
     - Treatment of skipped slots (drop or impute?)
   - **Owner:** Data documentation
   - **Output:** Sample construction document (section: "Exclusion Criteria and Filtering Logic")

**4. Align Identification Strategy to Econometric Specification**
   - **Action:** Choose one of two paths:
     - **Path A (Descriptive):** Revise identification strategy to state "we document the empirical relationship between block height and time, without claiming causality." Keep econometric spec as is (Model 1 & 2).
     - **Path B (Causal):** Extend econometric spec to include network state controls (mempool size, gas usage, validator composition); revise identification strategy to specify how these controls proxy for congestion/delay mechanisms.
   - **Owner:** Identification strategist + econometrician
   - **Output:** Revised identification strategy OR revised econometric specification

### MAJOR (Should resolve before analysis):

**5. Handle Outliers and Extreme Values**
   - **Action:** 
     - Compute histogram of block inter-arrival times (time from block i to block i+1).
     - Flag any blocks with inter-arrival > 60 seconds (likely reorg artifacts).
     - Document: will these be excluded, downweighted, or included?
   - **Owner:** Data quality / exploratory analysis
   - **Output:** Data cleaning document (section: "Outlier Treatment")

**6. Pre-Specify Primary vs. Exploratory Analyses**
   - **Action:** Clearly separate:
     - **Primary:** Model 1 (baseline block rate) + Model 2 (Merge breakpoint) — these are preregistered.
     - **Exploratory:** Validator heterogeneity, MEV effects, seasonality — these are post-hoc.
   - **Justification:** Prevents p-hacking; allows proper multiple-testing inference if primary analysis is refined.
   - **Owner:** Identification strategy document
   - **Output:** Section added to identification strategy: "Primary vs. Exploratory Analyses"

**7. Specify Standard Error Calculation**
   - **Action:** 
     - Report results with both OLS standard errors AND heteroskedasticity-robust SEs (HC2 or HC3).
     - If clustering is justified (e.g., by validator or epoch), report cluster-robust SEs in robustness tables.
   - **Owner:** Econometric specification document
   - **Output:** Section added: "Inference and Standard Errors"

### MINOR (Nice to address):

**8. Add Pre-Merge Period for Contrast**
   - **Action:** Include a small Pre-Merge subsample (e.g., last 3 months of PoW) to show before/after improvement.
   - **Benefit:** Strengthens narrative that post-Merge block time improved (or not).
   - **Owner:** Analysis stage

**9. Verify Merge Block Number**
   - **Action:** Cross-check block #15,550,000 (or whatever is used) against Etherscan/spec.
   - **Owner:** Data engineering

**10. Robustness Checks: Pre-Specify 3-5 Key Robustness Tests**
   - **Action:** Document upfront:
     - Use block.timestamp vs. arrival_time (time measurement robustness)
     - Exclude extreme outliers (>60 sec gaps) vs. include all (outlier robustness)
     - Sub-period analysis (different market conditions, network upgrades)
   - **Owner:** Econometrician

---

## Summary Table: Issue Severity & Resolution Pathway

| Issue | Severity | Category | Resolution Owner | Timeline |
|-------|----------|----------|------------------|----------|
| Reorg handling not specified | CRITICAL | Data pipeline | Data engineer | Before data collection |
| Time reference variable ambiguous | CRITICAL | Data pipeline | Identification strategist | Before data collection |
| Sample construction undocumented | CRITICAL | Data pipeline | Data engineer | Before data collection |
| RSD-to-spec misalignment (causal claim vs. descriptive model) | CRITICAL | Specification | Econometrician + ID strategist | Before estimation |
| Outlier treatment not addressed | MAJOR | Data quality | Data engineer | Before analysis |
| Standard errors not specified | MAJOR | Inference | Econometrician | Before estimation |
| Primary vs. exploratory not separated | MAJOR | Specification | ID strategist | Before analysis |
| Pre-Merge period not included | MINOR | Analysis design | Analyst | During analysis |
| Merge block # not verified | MINOR | Data quality | Data engineer | Before data collection |
| Robustness checks not pre-specified | MINOR | Specification | Econometrician | Before analysis |

---

## Final Assessment

**Overall Verdict: PROCEED WITH CAUTION**

The paper has a strong conceptual foundation and clear research question. The econometric specification is technically sound. However, **the data construction and identification strategy contain critical gaps that must be resolved before empirical work can begin.**

**Must-fix before proceeding:**
1. Specify how blockchain reorganizations will be handled.
2. Define the time reference variable (block.timestamp vs. arrival time).
3. Document sample construction logic (exclusions, filtering, deduplication).
4. Align the causal identification strategy to the econometric specification (currently misaligned).

**Timeline Recommendation:**
- Current stage (Idea): Complete → Add critical specifications (1-2 weeks)
- Data collection stage: Can begin once critical specs are finalized → (1-2 weeks)
- Estimation & analysis: ~2 weeks after data is validated
- Draft writing: ~2-3 weeks

**Blocking Issues for Submission:** None identified in design, but implementation must address the four critical gaps above before results can be considered robust.

---

## Questions for Author

1. **Chain reorg handling:** Will the analysis use the current live chain, finalized chain, or a historically fixed snapshot? Why?
2. **Time measurement:** Will elapsed time be measured via block.timestamp (on-chain) or query-time wall-clock? How will validator timestamp manipulation be handled?
3. **Causal mechanism:** Is this paper descriptive (documenting the empirical relationship) or causal (identifying why delays occur)? The identification strategy suggests causal, but the econometric spec is purely descriptive.
4. **Reproducibility:** Will you provide a fixed snapshot date/block range so other researchers can reproduce the exact dataset? How will future analysis updates be handled?
5. **Data quality:** Have you examined the histogram of block inter-arrival times? Are there obvious outliers or reorg artifacts that require cleaning?

---

**End of Technical Review**
