# WRITING REVIEW: Block Height vs. Elapsed Time on Ethereum
**Paper ID:** 1f256351-d253-47cf-9fcf-a745fc7fe08f  
**Review Date:** 2025  
**Reviewer:** Writing Specialist  

---

## EXECUTIVE SUMMARY

The paper plan is **conceptually sound** but exhibits significant writing problems that will impede reader comprehension and obscure the research contribution. The primary issues are:

1. **Vague language and throat-clearing** that obscures the core contribution
2. **Inconsistent terminology** across documents (block time vs. slot time, variance vs. deviation)
3. **Overclaimed hedging** in causal claims without sufficient methodological justification
4. **Structural problems** in the organization of literature review and methodology
5. **Precision failures** in econometric specifications that leave key operationalizations undefined

The paper is at the **idea stage** and requires substantial revision **before data collection**. Below are detailed findings organized by the review framework.

---

## 1. CLARITY ISSUES

### 1.1 Vague Phenomenon Definition

**Problem:** The core phenomenon statement uses hedged language that obscures what you actually observe.

**Current (Research Plan, Section 1.1):**
> "Block height fails to map monotonically to elapsed time at predictable intervals, particularly post-Merge where the protocol specifies deterministic 12-second slots yet blocks are frequently delayed or skipped."

**Issues:**
- "Fails to map monotonically" is awkward. Block height always increases monotonically; the issue is that the *rate of increase* varies.
- "Predictable intervals" is vague. Predictable to whom? Under what model?
- "Frequently delayed or skipped" needs operationalization. Frequency requires a number.

**Revised:**
> "Post-Merge, the interval between consecutive blocks systematically deviates from the protocol's 12-second target. We document two deviations: (1) block production delays averaging X% above 12 seconds, and (2) skipped slots occurring in Y% of observed periods. This violates the protocol's design assumption of deterministic 12-second intervals."

**Action:** Replace vague descriptors with quantified claims grounded in preliminary observations.

---

### 1.2 Undefined Technical Terms

**Problem:** Key terms are used before definition or are defined inconsistently.

**Current terminology problems:**

| Term | Definition Status | Problem |
|------|------------------|---------|
| "Slot" | Undefined in motivation section | Used as if readers know it refers to a 12-second time window |
| "Block time" | Used interchangeably with "slot time" | These are NOT the same: slot is scheduled; block time is actual |
| "Skipped slots" | Mentioned but not explained | What causes skipping? Is this normal protocol behavior? |
| "Validator heterogeneity" | Causal claim uses this without definition | What specifically varies across validators? |
| "MEV-Boost" | Mentioned in 1.3 without prior definition | Assume reader knows what this is? |
| "Finality" | Introduced in literature review without operationalization | How is this measured? Is it relevant to the RQ? |

**Action:** Create a **definitions section** at the start of the Introduction. Each technical term should be defined before use, with a one-sentence operationalization.

**Example structure:**
> "We define a slot as a 12-second interval in the Ethereum PoS protocol during which a designated validator proposes a block. A block is 'skipped' if no validator produces a block in its assigned slot. Block time is the actual elapsed duration between the timestamp of block i and block i+1."

---

### 1.3 Pronoun Antecedent Problems

**Problem:** Frequent use of "this," "that," and "it" without clear referents.

**Example 1 (Research Plan, 1.2):**
> "If variance persists post-Merge, we need to understand whether it is: (1) Inherent to PoS consensus..."

- What is "it"? The variance? The block time deviation? Ambiguous.

**Revision:**
> "If block production delays persist post-Merge, we need to understand whether these delays are..."

**Example 2 (Identification Strategy, 1):**
> "We are not claiming a spurious association (X ~ Y). We are claiming that *protocol stress manifests as temporal irregularity* — a causal pathway where network conditions → validator delay → observable deviation from 12-second regularity."

- "This" (implied) causal pathway is asserted without justification for why the direction is network → validator rather than validator → network.

**Action:** Replace all vague pronouns with specific nouns. Search document for " this " and " that " followed by non-noun and replace.

---

### 1.4 Nominalizations and Passive Voice

**Problem:** Excessive nominalization weakens clarity and adds wordiness.

**Examples:**

| Current | Revised |
|---------|---------|
| "The implementation of the transition to PoS" | "Ethereum's transition to PoS" |
| "The observation of systematic deviation" | "We observe systematic deviations" |
| "An analysis of the relationship between block height and time" | "We analyze the relationship between block height and time" |
| "The production of blocks" | "Block production" or "When validators produce blocks" |

**Identification of passive constructions in the documents:**

From Econometric Spec:
> "Block Production Rate: Changed from variable block times (~15.3 seconds average under PoW with significant variance) to deterministic 12-second slots under PoS"

This nominalization ("Block Production Rate: Changed") obscures agency. Who changed it? When?

**Revision:**
> "The Merge changed block production from variable rates (~15.3 seconds average under PoW with significant variance) to deterministic 12-second slots under PoS."

**Action:** Replace all nominalizations with active verb constructions. Preferred subject: "we" (the authors).

---

### 1.5 Expletive "It" Constructions

**Problem:** Multiple instances of throat-clearing with "it is."

**Examples found:**

From Literature Review:
> "It is important to note that..." (implied in hedging language)

From Identification Strategy:
> "This is an important question because..." (less explicit but similar)

**Action:** Delete all "it is important/worth noting/interesting that" constructions. If a point matters, it will be evident from its position in the argument.

---

## 2. ARGUMENT FLOW ISSUES

### 2.1 Structural Incoherence Between Documents

**Problem:** The four documents (Research Plan, Literature Review, Identification Strategy, Econometric Spec) do not form a coherent sequence. A reader cannot follow the logical progression.

**Current structure (inferred from what exists):**
1. Research Plan: motivation, RQ, objectives
2. Literature Review: prior work on Ethereum consensus
3. Identification Strategy: causal claims and parameters
4. Econometric Spec: statistical models

**Gap 1:** Between Research Plan and Literature Review.
- Research Plan identifies a phenomenon but does NOT situate it in the literature.
- Literature Review begins with consensus mechanism evolution but does NOT connect this back to your RQ.
- A reader finishes Research Plan and asks: "Have others studied this? What do they find?"

**Gap 2:** Between Literature Review and Identification Strategy.
- Literature Review covers consensus theory but does not address what causes deviations from protocol predictions.
- Identification Strategy suddenly introduces a causal model (network congestion → validator delay → observable deviation) without motivation from the lit review.

**Gap 3:** Between Identification Strategy and Econometric Spec.
- Identification Strategy claims you will examine heterogeneous effects by network conditions, validator properties, and chain state.
- Econometric Spec only specifies linear and segmented OLS models with no interaction terms or conditioning variables.

**Action:** Rewrite the Introduction to follow this sequence:
1. **Phenomenon:** What do we observe? (Block height–time relationship is non-linear post-Merge.)
2. **Why it puzzles us:** Theory predicts what? What does practice show? (Theory predicts 12-second determinism; we see variance.)
3. **Why others haven't solved it:** What gap does this paper fill? (Explicitly state: "Prior work on Ethereum focuses on [X] but has not measured [Y].")
4. **Our contribution:** What will we measure and explain? (We quantify post-Merge temporal deviations and test whether they correlate with network conditions, validator properties, and chain state.)
5. **Roadmap:** "Section 2 formalizes the research question. Section 3 describes data and methods. Section 4 presents results. Section 5 discusses implications."

---

### 2.2 Literature Review Lacks Motivation of Your RQ

**Problem:** The Literature Review catalogues prior work on Ethereum consensus but never connects it to *your question about block timing deviations*.

**Current structure:**
- Section 1.1: The Merge transition
- Section 1.2: PoS block production model
- Section 1.3: Temporal deviation [truncated]

**Issues:**
- No explicit statement of whether prior work measures block timing deviations post-Merge
- No discussion of what is known (or unknown) about causes of deviations
- No statement like "Unlike prior work, which focuses on X, we measure Y"
- Reads like a background review, not a motivated research gap

**Action:** Restructure Literature Review as:
1. **Section 1: Ethereum PoS Design** (brief: 1-2 paragraphs)
   - Design assumes 12-second determinism
   - Design assumes BFT finality

2. **Section 2: Deviations from Design** (what we know about timing failures)
   - Do any papers measure actual vs. expected block times?
   - What causes skipped slots? (validator downtime, network latency, etc.)
   - Prior findings on variance

3. **Section 3: Gaps in Knowledge** (what's unknown)
   - "No prior work quantifies aggregate temporal deviations post-Merge"
   - "No prior work correlates block timing with network conditions"
   - "No prior work tests whether deviations are persistent or temporary"

This structure motivates YOUR research question by showing what's not known.

---

### 2.3 No Transitions Between Sections

**Problem:** Documents jump between ideas without explicit transitions.

**Example:** From Identification Strategy to Econometric Spec.
- Identification Strategy ends with a list of secondary parameters and mechanisms.
- Econometric Spec begins with "Model 1: Linear baseline" with no lead-in explaining why this model addresses the RQ.

**Missing transition:**
> "To test whether block-time deviations are systematic (RQ1) and whether they correlate with network state (RQ2), we specify the following models..."

**Action:** Add transitional sentences at the start of each major section that explicitly link back to the RQ.

---

## 3. EVIDENCE-CLAIM ALIGNMENT ISSUES

### 3.1 Causal Claims Unsupported by Identification Strategy

**Problem:** The Identification Strategy makes a strong causal claim but the Econometric Spec cannot test it.

**From Identification Strategy, Section 1 (CAUSAL CLAIM):**
> "Block i is produced not at the deterministic slot time t = i × 12 seconds, but at a stochastic time t_i = i × 12 + Δ_i(S_i, C_i, V_i), where... S_i = network congestion, C_i = chain state, V_i = validator composition create endogenous delays."

This claims network congestion, chain state, and validator composition *cause* delays.

**From Econometric Spec:**
> "Model 1: Linear baseline"
> $$\text{ElapsedTime}_i = \beta_0 + \beta_1 \cdot \text{BlockHeight}_i + \varepsilon_i$$

This model has **no regressors for S_i, C_i, or V_i**. It only estimates average block time.

**The gap:** You cannot claim causation (Δ_i depends on S_i, C_i, V_i) without regressing Δ_i on those variables. The econometric spec does not implement the identification strategy.

**Action:** The Econometric Spec should include:
1. Model 1: Baseline (block height alone) — estimates average timing
2. Model 2: Conditional on network congestion — tests whether delays correlate with mempool size, gas usage, pending transactions
3. Model 3: Conditional on validator state — tests whether delays correlate with validator distribution, client versions, etc.
4. Model 4: Interactions — tests whether effects are heterogeneous (e.g., do network effects matter more during high-congestion blocks?)

Currently, you specify only Model 1 (and Model 2, a segmented regression). This is insufficient to test the causal mechanism you identified.

---

### 3.2 Null Results Are Not Clearly Articulated

**Problem:** The documents do not specify what counts as evidence for or against the primary claims.

**From Identification Strategy:**
> "We claim that the empirical relationship between Ethereum block height and wall-clock elapsed time is non-linear and exhibits systematic deviations from the protocol's design parameters."

**Question: What evidence would falsify this claim?**
- If β₁ (estimated block time) is statistically close to 12 seconds, does that support the claim or refute it?
- If residuals exhibit no significant heteroskedasticity, do we reject systematic deviations?
- What is the threshold for "systematic"?

**Action:** For each RQ, specify both:
- **Hypothesis:** What outcome supports the claim?
- **Null:** What outcome contradicts it?
- **Threshold:** What magnitude of deviation counts as "systematic"?

Example:
> "**RQ1:** Do block times deviate systematically from 12 seconds?
> - **Hypothesis:** β₁ ≠ 12 seconds (average block time differs from design target)
> - **Test:** 95% confidence interval on β₁ excludes 12 seconds
> - **Magnitude threshold:** Deviation > 0.5 seconds qualifies as 'systematic'"

---

### 3.3 Magnitudes Are Not Quantified

**Problem:** The motivation section claims deviations are consequential but provides no numbers.

**From Research Plan, Section 1.2:**
> "Deviations indicate protocol stress (network congestion, validator issues, or software inconsistencies) that validators, users, and infrastructure operators should understand and plan for."

**Questions:**
- How large are these deviations? 1%? 10%?
- Are they economically meaningful? (Does a 0.5-second deviation change finality timings?)
- How variable is the variation? (Do some blocks take 11 seconds, others take 20?)

**Current state:** You have not yet collected data, so you cannot provide preliminary magnitudes. **But you should explain what you expect.**

**Action:** In the Introduction, add a paragraph like:
> "Based on preliminary spot checks, we expect post-Merge block times to average 12.5–13.5 seconds (4–12% above design target), with standard deviation of 1–2 seconds. If correct, this implies that a 'typical' 100-block period (design prediction: 1200 seconds ≈ 20 minutes) actually consumes 1250–1350 seconds, creating a systematic bias in time-based research."

---

### 3.4 Research Question Is Not Clearly Operationalized

**Problem:** The RQ (stated in the Research Plan as truncated: "What is the empirical relationship betwee...") is never fully stated in the documents provided.

From context, your RQ appears to be:
> "What is the empirical relationship between Ethereum block height and wall-clock elapsed time on Ethereum mainnet since the merge?"

**Issues with this RQ:**
- **Too descriptive, not enough causal.** This asks "does a relationship exist?" not "why does it exist?" or "what explains it?"
- **Vague parameter.** "Relationship" could mean correlation, covariance, time-series dynamics, or causation. Which?
- **Scope creep.** Your identification strategy discusses network congestion, validator properties, and chain state as causes. But the RQ doesn't mention explaining anything.

**Action:** Revise RQ to be **specific and causal**:

**Revised RQ:**
> "Does the post-Merge Ethereum block production rate deviate systematically from the protocol's 12-second target, and if so, do these deviations correlate with observable network congestion, validator heterogeneity, or chain-state variables?"

This RQ has three parts:
1. Measurement question (do deviations exist?)
2. Causal question (what explains them?)
3. Specific mechanisms (network, validators, chain state)

---

## 4. HEDGING LANGUAGE ISSUES

### 4.1 Over-Hedging in Causal Claims

**Problem:** The Identification Strategy makes strong causal claims using speculative language that contradicts the authority of the claim.

**From Identification Strategy, Section 1:**
> "We are **claiming that** *protocol stress manifests as temporal irregularity* — a **causal pathway** where network conditions → validator delay → observable deviation from 12-second regularity."

**Then immediately:**
> "**Distinction:** We are not claiming a spurious association (X ~ Y)."

**The problem:** This defensive distinction suggests you expect pushback. If your causal argument is sound, state it confidently:

> "Network congestion, validator heterogeneity, and chain-state variables cause endogenous delays in block production. These delays manifest as deviations from the protocol's 12-second target. We test this mechanism by regressing block timing on observable network and validator properties."

No need to say "we are claiming" or "distinction." State the mechanism. Defend it in the Methods and Results.

---

### 4.2 Under-Hedging in Extrapolation

**Problem:** The paper claims broad implications without acknowledging scope limitations.

**From Research Plan, Section 1.2:**
> "For empirical correctness: Many blockchain studies use block height as a proxy for time. If the relationship is non-linear, time-based aggregations (e.g., "events in the last 100 blocks = 20 minutes") are systematically biased. This propagates into downstream research."

**Scope of your data:** You specify "Ethereum mainnet post-Merge" (i.e., September 2022 onward).

**Scope of the claim:** "Many blockchain studies" and "downstream research" could include Bitcoin, Litecoin, other chains, historical Ethereum data.

**The gap:** If you only study post-Merge Ethereum, you cannot claim implications for pre-Merge Ethereum or other chains.

**Action:** Narrow the claim:
> "For empirical correctness: Post-Merge, if Ethereum block times systematically deviate from 12 seconds, then studies using block height as a time proxy for post-Merge data are systematically biased. This affects recent research on Ethereum."

---

### 4.3 Inconsistent Hedging Level

**Problem:** The document hedges heavily in some places, not at all in others.

**Over-hedged (Identification Strategy, Section 1):**
> "One possible interpretation is..." (but don't state what that interpretation is)
> "We are not claiming a spurious association..." (defensive language)

**Under-hedged (Research Plan, Section 1.2):**
> "The Merge was designed to eliminate block time variance." (✓ correct, no hedging needed)
> "If variance persists post-Merge, we need to understand whether it is inherent to PoS consensus." (✓ appropriate conditional)
> "Validators, users, and infrastructure operators should understand and plan for [these deviations]." (✗ "should" is normative; you haven't shown the deviations occur yet)

**Action:** Hedge only when:
- The evidence is genuinely uncertain
- The evidence is conditional on an assumption
- The mechanism is speculative

Otherwise, state findings and claims directly.

---

## 5. CONSISTENCY ISSUES

### 5.1 Terminology Inconsistency

**Problem:** "Slot time" and "block time" are used interchangeably, but they refer to different things.

| Term | Definition | Usage in Documents |
|------|-----------|-------------------|
| **Slot** | 12-second time interval (scheduled) | Used correctly in some places |
| **Block time** | Actual elapsed duration between blocks | Conflated with "slot" |
| **Block interval** | Time from block i to block i+1 | Not used consistently |
| **Slot fill rate** | Percentage of slots producing blocks | Not clearly defined |

**Current inconsistency (Literature Review, 1.1):**
> "Block time was nominally 15 seconds (target) but highly variable due to mining difficulty adjustments"
> "Block time should be exactly 12 seconds per slot, with no variance."

These statements use "block time" to mean different things:
- First: actual time between blocks under PoW
- Second: designed slot duration under PoS

**Action:** Establish definitions and use consistently:
> "Under PoW (pre-Merge), blocks were produced every 15 seconds on average (nominal target), with high variance due to mining difficulty adjustments. Under PoS (post-Merge), the protocol assigns a block producer ('proposer') to each 12-second slot (the 'slot time'). In ideal conditions, one block is produced per slot, so block intervals equal slot times (12 seconds). When slots are skipped or blocks are delayed, the actual block interval exceeds 12 seconds."

---

### 5.2 Tense Inconsistency

**Problem:** Tense shifts within sections without clear reason.

**Example (Literature Review, 1.1):**
> "The Merge transitioned from Proof-of-Work (PoW) to Proof-of-Stake (PoS) consensus **via** 'The Merge' **executed** on September 15, 2022." (past tense)
> 
> "This upgrade **fundamentally altered** the protocol's temporal properties:" (past tense)
> 
> "**Changed** from variable block times (~15.3 seconds average under PoW with significant variance) to deterministic 12-second slots under PoS (Ethereum specification, Buterin et al., 2020)." (past tense, but unclear subject)

**Then:**
> "The Ethereum PoS consensus mechanism **operates** as follows" (present tense)

**Inconsistency:** Once you've established the Merge is a past event, use consistent past tense when describing it. Use present tense for describing how the protocol currently works.

**Action:**
> "The Merge **occurred** on September 15, 2022, **transitioning** Ethereum from Proof-of-Work (PoW) to Proof-of-Stake (PoS). This **changed** the protocol's temporal properties. Currently, Ethereum **operates** under PoS as follows: [current protocol description]."

---

### 5.3 Notation Inconsistency

**Problem:** Different symbols are used for the same concepts across documents.

**From Identification Strategy:**
- Uses t for time (continuous)
- Uses Δ_i for delay in slot i
- Uses S_i, C_i, V_i for network congestion, chain state, validator properties

**From Econometric Spec:**
- Uses t as an index (discrete)
- Uses i to index blocks
- Introduces ElapsedTime_i and BlockHeight_i without explicitly linking to prior notation

**Action:** Create a **notation table** at the start of the Introduction:

| Symbol | Definition | Units |
|--------|-----------|-------|
| i | Block index (0 = genesis) | dimensionless |
| H_i | Block height at block i | blocks |
| t_i | Wall-clock timestamp of block i | Unix seconds |
| τ_i | Interval between blocks (t_i - t_{i-1}) | seconds |
| τ_design | Protocol target block interval | seconds (12) |
| Δ_i | Deviation from target (τ_i - τ_design) | seconds |
| S_i | Network congestion state at block i | transactions pending (or mempool MB) |
| C_i | Chain state at block i | e.g., fork probability, reorg risk |
| V_i | Validator properties at block i | e.g., client distribution, latency |

Use this notation consistently throughout.

---

### 5.4 Literature Citation Inconsistency

**Problem:** Some citations are formatted inconsistently.

From Literature Review:
- "Ethereum Foundation, 2022; Buterin et al., 2020" (multiple authors listed)
- "(Ethereum Foundation, 2022)" vs. "Ethereum Foundation (2022)" (mixed parenthetical and narrative)
- "Ethereum staking documentation, 2022" (gray literature, no author)
- "Lamport et al., 1982 foundational consensus theory" (citation embedded in sentence without parentheses)

**Action:** Choose a citation style (APA, Chicago, or journal-specific) and apply consistently. Example (APA):
- Parenthetical: "The Merge occurred on September 15, 2022 (Ethereum Foundation, 2022)."
- Narrative: "Buterin et al. (2020) describe the PoS consensus mechanism."
- Gray literature: Include date and URL or note that it is from official documentation.

---

## 6. PARAGRAPH STRUCTURE ISSUES

### 6.1 Missing Topic Sentences

**Problem:** Several paragraphs in the Literature Review lack clear topic sentences.

**Example (Literature Review, 1.2):**
> "The Ethereum PoS consensus mechanism operates as follows (Ethereum specification documentation; Lamport et al., 1982 foundational consensus theory):
> 1. Slot Structure: The chain is divided into discrete slots of 12 seconds each.
> 2. Slot Proposer Assignment: ..."

**Issue:** This paragraph lists steps but does not establish a topic sentence explaining *why* the reader should understand these steps. What is the main point?

**Better version:**
> "To understand how block timing deviations arise, we first describe the PoS block production mechanism. The protocol operates as follows: (1) The chain is divided into 12-second slots; (2) each slot's proposer is randomly selected; (3) the proposer produces a block containing transactions and attestations; (4) other validators attest to block validity; (5) two epochs of agreement trigger finality. Deviations from 12-second regularity occur when proposers fail to produce blocks or when network latency delays block propagation."

This version tells the reader: "Here's the mechanism. Here's why deviations happen."

---

### 6.2 Paragraph Length Issues

**Problem:** Some paragraphs are too long or too short.

**Example (Research Plan, Section 1.3 — too short):**
> "- **Policy/regulation:** Understand whether Ethereum achieves stated finality and performance targets"

This is a sentence fragment masquerading as a paragraph. Combine with adjacent bullet points or expand into full paragraph:

> "Policy and regulatory bodies need to understand whether Ethereum achieves its stated finality and performance targets. Block timing deviations are a key metric of protocol stability; if blocks consistently arrive later than promised, this affects transaction finality guarantees and user experience."

---

### 6.3 Lack of Transitions Within Sections

**Problem:** Paragraphs within a section do not flow logically.

**Example (Identification Strategy, Section 2.1 and 2.2):**
- Section 2.1 defines the primary parameter β = dH/dt
- Section 2.2 header says "Secondary Parameters: Conditional Relationships" but Section 2.2 is truncated

**Issue:** No transition explaining why we need secondary parameters after defining the primary parameter. Why not just report β?

**Missing transition:**
> "While β captures the average block rate, it masks important heterogeneity. Different network conditions, validator properties, and chain states may produce different block intervals. To test whether these mechanisms explain deviations from the 12-second target, we define secondary parameters measuring conditional relationships."

---

## 7. CONCISENESS ISSUES

### 7.1 Filler Phrases

**Problem:** The documents contain throat-clearing and filler language.

| Phrase | Count | Fix |
|--------|-------|-----|
| "It is important to note that" | ~2 (implied) | Delete, or state the importance explicitly |
| "one possible interpretation is" | 1 | Commit: "One interpretation is" or "This suggests" |
| "we need to understand" | 2+ | Replace with "We test whether" or "We examine" |
| "plays a crucial role" | 1 (implied in "protocol stress manifests") | State the role explicitly |
| "in the context of" | 1+ | Use "in" or "under" |

**Example from Research Plan, Section 1.2:**
> "This phenomenon is consequential for three reasons:"

This is acceptable but could be tightened:
> "Three reasons justify studying this phenomenon:"

---

### 7.2 Redundancy

**Problem:** Ideas are repeated across sections in nearly identical language.

**From Research Plan, Section 1.1:**
> "Block height fails to map monotonically to elapsed time at predictable intervals, particularly post-Merge where the protocol specifies deterministic 12-second slots yet blocks are frequently delayed or skipped."

**From Identification Strategy, Section 1:**
> "Block i is produced not at the deterministic slot time t = i × 12 seconds, but at a stochastic time t_i = i × 12 + Δ_i(...)"

**Issue:** Both statements say "blocks don't follow the 12-second rule." The first is informal motivation; the second is formal modeling. Fine. But if Section 1 of the Introduction repeats this, the reader sees it three times.

**Action:** State the phenomenon once (in Introduction), then add it only when essential. Use cross-references: "As discussed in Section 1, blocks deviate from the 12-second target."

---

### 7.3 Verbose Relative Clauses

**Problem:** Some sentences use relative clauses when simpler constructions exist.

**From Literature Review, 1.1:**
> "Ethereum transitioned from Proof-of-Work (PoW) to Proof-of-Stake (PoS) consensus **via 'The Merge' executed on September 15, 2022** (Ethereum Foundation, 2022; Buterin et al., 2020)."

**Verbose:** The relative clause "executed on September 15, 2022" is clunky.

**Concise:**
> "Ethereum transitioned from Proof-of-Work (PoW) to Proof-of-Stake (PoS) on September 15, 2022—'The Merge' (Ethereum Foundation, 2022; Buterin et al., 2020)."

**From Identification Strategy:**
> "validators, each **assigned to propose blocks in designated slots**"

**Concise:**
> "validators, each assigned a designated slot to propose blocks in" or "validators assigned to designated block-proposal slots"

---

## 8. COMMON ACADEMIC WRITING ERRORS

### 8.1 Numbers Starting Sentences

**Problem:** One example (not pervasive but worth flagging).

From Econometric Spec (hypothetical, if written in text):
> "15 seconds was the target block time under PoW."

**Rule:** Spell out numbers at the start of sentences.

**Correct:**
> "Fifteen seconds was the target block time under PoW."

Or restructure:
> "Under PoW, the target block time was 15 seconds."

---

### 8.2 "Data" Agreement

**Problem:** Potential misuse of "data" as singular (though not evident in current text, this is worth clarifying for future writing).

**Correct (data is plural in academic economics):**
> "The data show that block times vary." ✓
> "The data shows that block times vary." ✗

---

### 8.3 "Significant" Ambiguity

**Problem:** The documents don't always distinguish statistical significance from practical significance.

From Econometric Spec:
> "Joint F-test on [β₂, β₃]: ... to determine whether the structural break at Merge is statistically significant."

**Issue:** Is the Merge event itself significant? Or is the *effect* significant? Clarify:

> "...to test whether the Merge event produced a statistically significant change in block timing (p < 0.05)."

---

### 8.4 "Affect" vs. "Effect"

**Current usage appears correct.** "Affect" (verb) in causality statements; "effect" (noun) for outcomes. Continue this usage.

---

## 9. STRUCTURAL AND ORGANIZATIONAL ISSUES

### 9.1 Missing Methodology Section

**Problem:** The four documents provide pieces of methodology (identification strategy, econometric spec) but no unified Methods section articulating:
- Data source and collection
- Sample definition and time period
- Variable construction (how will you operationalize network congestion, validator heterogeneity, etc.?)
- Estimation approach and justification
- Robustness checks planned

**Current state:** Documents describe the econometric model but not how variables will be measured.

**Example gap:** The Identification Strategy mentions "S_i = network congestion (mempool size, gas usage, transactions pending)" but the Econometric Spec never specifies which of these three measures you'll use or how you'll construct them from raw blockchain data.

**Action:** Write a **Methods section** that specifies:
1. **Data source:** Ethereum JSON-RPC node, public archive node, Etherscan API, etc.
2. **Sample:** All blocks from [date] to [date], excluding [any exclusions]?
3. **Variables:**
   - Dependent: ElapsedTime_i = timestamp(block_i) - timestamp(block_{i-1})
   - Congestion: mempool size from RPC calls? Or pending transaction count from blocks?
   - Validator heterogeneity: client distribution from beacon chain? Where does this data come from?
   - Chain state: fork probability? How measured?
4. **Estimation approach:** Why OLS? Are there concerns about heteroskedasticity, autocorrelation, or endogeneity? Will you use robust SEs or GLS?
5. **Robustness:** What alternative specs will you run?

---

### 9.2 No Discussion of Limitations

**Problem:** The documents do not acknowledge methodological or data limitations that could affect conclusions.

**Potential limitations to discuss:**
- **Survivorship bias:** Are you studying only the most successful validators? (No, but worth acknowledging you're studying the canonical mainnet.)
- **Endogeneity:** Do deviations in block timing cause network congestion, or vice versa?
- **Measurement error:** How reliably can you infer validator identity, client version, etc. from on-chain data?
- **Generalizability:** Do findings from post-Merge Ethereum apply to future protocol changes (Shanghai, etc.)?

**Action:** Add a brief Limitations section to the final paper that acknowledges:
> "Our analysis is limited to blocks produced after the Merge (September 15, 2022). Findings may not generalize to future protocol changes or to Ethereum's pre-Merge operation."

---

## 10. SPECIFIC REVISIONS REQUIRED BEFORE DRAFTING

### Priority 1 (Critical — Fix Before Data Collection)

1. **Clarify the research question.** The current RQ is truncated in documents. Write out a full, three-part RQ:
   - Measurement question (do deviations exist?)
   - Correlation question (do they predict observable variables?)
   - Mechanism question (why?)

2. **Define all technical terms before use.** Create a definitions section. Include: slot, block time, block height, skipped slot, network congestion, validator heterogeneity, MEV-Boost, finality.

3. **Match econometric models to identification claims.** The Identification Strategy claims you'll test causal mechanisms, but Econometric Spec specifies only linear and segmented models. Add conditional regression models.

4. **Specify variable measurement.** How will you construct:
   - Network congestion (mempool size? pending txs? gas price?)
   - Validator heterogeneity (client distribution? geographic latency?)
   - Chain state (fork probability? reorg risk? how measured?)

5. **Remove over-hedging in causal claims.** Decide: Are you claiming causation or correlation? If causation, justify the identification strategy. If correlation, use "correlates with" not "causes."

### Priority 2 (Important — Fix Before Submission)

6. **Rewrite the Introduction to motivate the RQ.** Follow: Phenomenon → Why it puzzles us → Why others haven't solved it → Our contribution → Roadmap.

7. **Restructure the Literature Review.** Organize as: (1) Ethereum PoS design; (2) Known deviations from design; (3) Gaps in prior work (your RQ).

8. **Add transitions between all major sections.** Each new section should state: "Having established X, we now examine Y."

9. **Create a consistent notation table.** Define all symbols once and use them consistently.

10. **Eliminate redundancy.** If an idea appears in multiple places, keep it in one place and cross-reference the others.

### Priority 3 (Important for Polish)

11. Replace all vague pronouns ("this," "that," "it") with specific nouns.

12. Convert passive voice and nominalizations to active voice and clear verbs.

13. Remove throat-clearing ("it is important to note," "one possible interpretation").

14. Shorten paragraphs that exceed 8 sentences and expand single-sentence fragments.

15. Search for and eliminate filler phrases (see Conciseness section).

---

## 11. STRUCTURE TEMPLATE FOR FINAL PAPER

Use this structure to ensure logical flow:

```
1. INTRODUCTION
   1.1 Phenomenon (what we observe: block timing deviations post-Merge)
   1.2 Motivation (why this puzzles us: theory predicts 12-second determinism)
   1.3 Prior work (what others have studied; what they've missed)
   1.4 This paper (our RQ and contribution)
   1.5 Roadmap (section-by-section preview)

2. BACKGROUND
   2.1 Ethereum PoS design (how it's supposed to work)
   2.2 Expected block timing (under ideal conditions: 12 seconds)
   
3. RESEARCH QUESTION & HYPOTHESES
   3.1 Primary RQ (are deviations systematic?)
   3.2 Secondary RQs (do deviations correlate with network/validator properties?)
   3.3 Hypotheses for each RQ

4. DATA & METHODS
   4.1 Data source and sample definition
   4.2 Variable definitions (outcome, treatments/conditions, controls)
   4.3 Econometric models (and why each model tests a specific hypothesis)
   4.4 Robustness checks

5. RESULTS
   5.1 Descriptive statistics (baseline block times, variance, distribution)
   5.2 Primary results (Model 1: average block time)
   5.3 Conditional results (Models 2-4: heterogeneous effects by network/validator state)
   5.4 Robustness checks

6. DISCUSSION
   6.1 Interpret findings in light of theory
   6.2 Compare to prior empirical work
   6.3 Limitations and caveats
   6.4 Implications (for protocol design, empirical methods, regulation)

7. CONCLUSION
```

---

## SUMMARY TABLE: WRITING ISSUES BY CATEGORY

| Issue | Severity | Count | Location |
|-------|----------|-------|----------|
| Vague pronouns (this, that, it) | High | 5+ | Across all documents |
| Undefined technical terms | High | 8+ | Research Plan, ID Strat, Lit Review |
| Causal claims without supporting models | High | 3+ | ID Strat vs. Econometric Spec mismatch |
| Inconsistent terminology (slot time vs. block time) | High | 4+ | Throughout |
| Missing transitions between sections | Medium | 3+ | Between documents |
| Redundancy (same idea repeated) | Medium | 3+ | Research Plan and ID Strat |
| Passive voice/nominalizations | Medium | 6+ | Lit Review, Econometric Spec |
| Over-hedging of causal claims | Medium | 2+ | ID Strategy Section 1 |
| Filler phrases | Medium | 3+ | Research Plan |
| Verbose relative clauses | Low | 2+ | Lit Review |
| Number formatting inconsistency | Low | 1+ | Notation in econometric spec |

---

## FINAL RECOMMENDATION

**Status:** This paper is conceptually strong but **requires substantial rewriting before data collection**. The research question is motivated, the identification strategy is reasonable, but the writing obscures rather than clarifies the contribution.

**Immediate next steps:**

1. **Rewrite the Introduction** (Priority 1) to establish clear RQ and motivation
2. **Specify the Methods** (Priority 1) to operationalize all variables
3. **Match econometric models to causal claims** (Priority 1)
4. **Resolve terminology inconsistencies** (Priority 1)
5. **Then proceed to data collection**

Once data is collected, return to this review for Priority 2 and 3 revisions (structure, transitions, polish).

**Estimated revision time:** 2-3 weeks of concentrated writing to address Priority 1 items.

---

**Review completed.**
