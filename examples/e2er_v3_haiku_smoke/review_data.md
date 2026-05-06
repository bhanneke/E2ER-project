# Data Review Report: Block Height vs. Elapsed Time on Ethereum
**Paper ID:** 1f256351-d253-47cf-9fcf-a745fc7fe08f  
**Title:** Temporal Dynamics of Ethereum: Block Height, Time, and Protocol Stability After the Merge  
**Current Stage:** Idea Development  
**Review Date:** 2025  

---

## EXECUTIVE SUMMARY

This paper proposes an empirical investigation of block production timing on Ethereum post-Merge, with a well-motivated research question and sophisticated identification strategy. However, the **data collection and validation plan is underdeveloped and poses significant credibility risks**. The work order specifies "Data Available" but provides no documentation of: (1) where data will be sourced, (2) how data quality will be assured, (3) what sample restrictions will apply, or (4) how potential measurement errors will be handled.

**Critical finding:** At idea stage, the paper lacks essential data documentation required for empirical credibility. The sections below detail specific gaps and remediation steps.

---

## 1. SOURCE DOCUMENTATION — CRITICAL GAPS

### 1.1 Missing: Data Source Specification

**Current state:** No explicit data source is named.

**What must be documented:**
- [ ] **Primary source identifier:** Will data come from:
  - Geth full node RPC endpoint (if so, which deployment: Infura, Alchemy, self-hosted)?
  - Etherscan API (requires API key, rate limits)?
  - Polygon Labs chain data repository?
  - Direct node archive data export (raw LevelDB)?
  - Third-party aggregator (e.g., Glassnode, The Block)?
  
  **Action required:** Specify the exact data provider and URL/endpoint before data collection begins.

- [ ] **Persistent identifier or citation:** 
  - If using Geth: specify version (e.g., geth v1.13.2)
  - If using Etherscan: document API contract and rate limits
  - If using a research dataset: provide DOI or arXiv link
  
  **Current problem:** Ethereum data is "live" and changes with every new block. A reader cannot reproduce results months later using "the Ethereum mainnet" alone. You must snapshot the data or freeze a block range.

- [ ] **Data vintage and versioning:**
  - Specify end block height or timestamp for the analysis sample (e.g., "all blocks from genesis to block 19,234,567 as of 2025-01-15")
  - Document whether the data includes reorg-affected blocks or canonical chain only
  - If using RPC, specify whether data reflects post-finality consensus or includes speculative blocks
  
  **Current problem:** Ethereum undergoes consensus reorgs. A block at height H produced on 2025-01-15 might have been removed by 2025-01-16 if a reorganization occurred. Must clarify which chain state version is authoritative.

### 1.2 Missing: Access and Reproducibility Plan

- [ ] **Public availability:** Can other researchers obtain identical data?
  - If using a full node RPC: provide instructions for setting up a node or accessing a public endpoint
  - If using restricted-access data: document how another researcher applies for access
  - If using your own archive node: commit to depositing the dataset in a public repository (e.g., Zenodo, Open Science Framework) with a DOI
  
  **Red flag:** "The data is proprietary" or "I extracted it from my node" without a reproducibility plan makes replication impossible.

- [ ] **Query/extraction code:** Document exactly how blocks and timestamps were extracted:
  - If RPC: provide the specific JSON-RPC calls (e.g., `eth_getBlockByNumber` parameters, batch size, retry logic)
  - If direct export: provide the extraction script or SQL query
  - Document handling of RPC failures, timeouts, or inconsistencies
  
  **Why this matters:** Ethereum data extraction is error-prone. Different endpoints may return slightly different data due to inconsistent indexing. Specify which implementation is canonical.

### 1.3 Missing: Geographic and Temporal Scope

**Current state:** Understood to be Ethereum mainnet, post-Merge (September 15, 2022 onward).

**Must clarify:**
- [ ] **Start block and timestamp:** 
  - Begin at Merge block (15,537,394) or immediately after?
  - Or include pre-Merge PoW data for comparison (if so, specify cutoff point)
  
  **Recommendation:** Use Merge block ± N blocks to quantify structural break. If N=0, you lose pre-Merge context for testing H0: no break.

- [ ] **End block and timestamp:** 
  - Specify a fixed block height (e.g., 19,000,000) to allow reproducibility
  - If using "current data," restate this requirement: "Data downloaded on DATE; future analysis must freeze at this checkpoint"
  
  **Current problem:** A reader running the code 6 months later would get different results if you say "use all blocks to present." Must freeze the analysis set.

- [ ] **Blocks included or excluded:**
  - Are all blocks included, or are there gaps (orphaned blocks, reorg artifacts)?
  - Does analysis include slots with no block proposed (skipped slots)?
  - If skipped slots are included, how are they coded: as missing data, or as deterministic 12-second increments with no block?

---

## 2. SAMPLE CONSTRUCTION — SPECIFICATION INCOMPLETE

### 2.1 Missing: Explicit Inclusion/Exclusion Criteria

**Current state:** Econometric spec mentions "blocks from genesis to current block height" but provides no explicit sampling rules.

**Must specify:**
- [ ] **Inclusion rules:**
  - Every block on the canonical chain? (If so, which definition: post-finality consensus? Longest chain as of snapshot date?)
  - All 32 slots per epoch? (Note: not all slots produce blocks; some are skipped)
  - Only blocks with transaction data? Or include empty blocks?
  
  **Recommendation:** Include all blocks on canonical chain, including skipped slots coded as missing block time. This preserves the slot regularity assumption.

- [ ] **Exclusion rules:**
  - Drop any blocks with anomalous timestamps (e.g., timestamps before previous block's timestamp)?
  - Drop genesis block (block 0)? It has an artificial timestamp (1438269988 Unix seconds). Include or exclude?
  - Drop any blocks where elapsed time < 0 (reorg indicator)? How will you detect reorgs in your snapshot?

### 2.2 Missing: Sample Flow Diagram

**Current state:** No sample accounting.

**Required table:**

| Step | N (blocks) | Notes |
|------|-----------|-------|
| Raw blocks downloaded | ? | All blocks from source, genesis to freeze date |
| Drop if timestamp < previous block | ? | Detect reorg artifacts |
| Drop if block height not monotonic | ? | Data integrity check |
| Drop orphaned/side-chain blocks | ? | Consensus layer filtering |
| **Analysis sample** | **?** | Blocks used in regression |

**Why this matters:** If you exclude even 100 blocks, readers need to know. If you discover during analysis that 1,000 blocks have anomalous timing, this affects credibility.

### 2.3 Missing: Reorg Handling

**Critical issue:** Ethereum undergoes reorganizations. The "canonical chain" you observe on day 1 may differ from day 2 if a reorg occurred.

**Must specify:**
- [ ] **Finality definition:** Are you analyzing:
  - The longest chain as of extraction date (max 0 reorg risk post-Merge, but RPC may return speculative data)?
  - Finalized blocks only (post-Casper FFG, no reorg risk but 2+ epochs = 25+ minutes lag)?
  - All blocks, then drop those later reorg'd out?

  **Recommendation for this paper:** Use **finalized blocks only**. Post-Merge, Casper FFG finalizes blocks 2 epochs (~25 minutes) after proposal. If your analysis includes only finalized blocks, reorg risk is eliminated and results are reproducible.

- [ ] **Reorg detection:** If you extract data on day 1 and day 2:
  - Will block timestamps at height H differ if a reorg occurred?
  - Document the test: compare `eth_getBlockByNumber(H)` on day 1 vs. day 2; if timestamps differ, a reorg occurred.

---

## 3. MISSING VALUES — NOT YET ADDRESSED

### 3.1 Critical: Skipped Slots vs. Missing Blocks

**The core ambiguity:** Under Ethereum PoS, not every slot produces a block. When a validator fails to produce, that slot is empty. The protocol still advances time regularly (slot 12 seconds), but no block is created.

**Must decide:**
- [ ] **How to represent skipped slots:**
  - **Option A:** Exclude skipped slots from analysis (only analyze blocks that exist)
    - *Pro:* Simpler; block-to-block analysis is clean
    - *Con:* Ignores time between blocks (not accounting for 12-second gaps)
  - **Option B:** Include skipped slots as rows with missing block data
    - *Pro:* Preserves the 12-second timing structure; makes protocol regularities visible
    - *Con:* Requires careful imputation or indicator variables in regression
  - **Option C:** Expand data to slot-level, not block-level
    - *Pro:* Direct test of 12-second hypothesis; slot N should have timestamp = genesis + 12*N
    - *Con:* Dataset ~5% larger; requires re-aggregating regression to slot-time level

  **Recommendation:** Use **Option C (slot-level analysis)**. Skipped slots are the core phenomenon! Excluding them hides delays. Instead, regress:
  
  $$\text{ElapsedTime}_s = \beta_0 + \beta_1 \cdot \text{SlotNumber}_s + \varepsilon_s$$
  
  Where ε_s includes both "slot had no block" (deterministic delay) and "block appeared late within slot" (stochastic delay).

### 3.2 Missing: Missing Data Documentation

**Current state:** No mention of how missing blocks, timestamps, or other fields will be handled.

**Must specify:**
- [ ] **Data completeness audit:**
  - What fraction of blocks have valid timestamps? (Should be ~100% for canonical chain)
  - Any NULL or zero timestamps? (Would indicate corrupt data)
  - Any blocks with timestamp < genesis time? (Would indicate data error)
  
  **Action:** Run diagnostic before analysis:
  ```
  SELECT 
    COUNT(*) as total_blocks,
    COUNT(DISTINCT block_height) as unique_heights,
    COUNT(CASE WHEN timestamp IS NULL THEN 1 END) as missing_timestamps,
    COUNT(CASE WHEN timestamp < genesis_time THEN 1 END) as pre_genesis_timestamps,
    MIN(timestamp) as earliest_timestamp,
    MAX(timestamp) as latest_timestamp
  FROM blocks;
  ```

- [ ] **Treatment of edge cases:**
  - Genesis block (block 0): artificially old timestamp (1438269988 = July 30, 2015). Include or exclude?
  - Merge block (15537394, timestamp ~1663224479 = Sep 15, 2022): is its timestamp accurate, or does it have artifacts?
  - Current practice: Document, then show robustness to inclusion/exclusion.

---

## 4. VARIABLE DEFINITIONS — UNDERSPECIFIED

### 4.1 Critical: "Elapsed Time" Definition

**Current state:** Mentioned as "wall-clock elapsed time since genesis" but not formally defined.

**Must specify precisely:**
- [ ] **Measurement basis:**
  - Unix timestamp (seconds since epoch 1970-01-01 00:00:00 UTC)?
  - Or seconds since Ethereum genesis (1438269988 Unix seconds)?
  
  **Recommendation:** Use seconds since genesis to avoid large numbers:
  $$\text{ElapsedTime}_i = \text{Timestamp}_i - 1438269988$$

- [ ] **Precision:**
  - Are timestamps recorded to nearest second, or millisecond/nanosecond?
  - If sub-second, how is rounding handled?
  - Specification: "Timestamp is the Unix timestamp of block i's seal, rounded to nearest second by the protocol"

- [ ] **Timezone:**
  - All Unix timestamps are UTC; confirm this is what Ethereum uses (it does)

### 4.2 Critical: "Block Height" Definition

**Current state:** Mentioned but not formally defined.

**Must specify:**
- [ ] **Indexing:**
  - Block 0 is genesis?
  - Or block 1?
  - This affects interpretation of slopes (seconds per block)
  
  **Standard in Ethereum:** Block 0 is genesis. Confirm this in your data dictionary.

- [ ] **Handling of reorgs:**
  - If height H existed, was removed in reorg, then replaced by different block at H:
    - Which version do you analyze? (The original, or the replacement?)
    - Does your dataset include both? (It shouldn't, if using canonical chain)

### 4.3 Missing: "Network Congestion" Variable Definitions

**Identification strategy mentions** S_i (mempool size, gas usage, etc.) as drivers of block delays, but:

- [ ] **Which specific variables will you measure?**
  - Gas used in block i? (Easy: on-chain, objective)
  - Mempool size at block i? (Hard: RPC nodes can't query "mempool size" reliably; must infer from pending transactions)
  - Transaction count? (Easy: on-chain)
  - Other proxies?

- [ ] **Measurement timing:**
  - Gas used *at block production time* (exact time block was sealed)?
  - Or gas used *in the block* (transactions included)?
  - Are these the same? (Yes, once block is produced, its contents are fixed)

- [ ] **Aggregation level:**
  - Per-block or per-epoch?
  - Will you aggregate to match regression granularity?

**Current problem:** The identification strategy is ambitious, but the variables are not yet operationalized. Define these before data collection.

---

## 5. OUTLIERS — NO HANDLING STRATEGY SPECIFIED

### 5.1 Missing: Outlier Detection Plan

**Current state:** Econometric spec includes robust regression as alternative, but no outlier analysis is described.

**Must plan:**
- [ ] **What would be an outlier?**
  - Blocks appearing >30 seconds apart? (>2.5× normal 12-second slot)
  - Blocks appearing in reverse chronological order? (timestamp[i] < timestamp[i-1])
  - Huge gaps (e.g., 5 blocks with no intermediate blocks in <1 second, then 5-minute gap)
  
  **Action:** Compute distribution of inter-block times:
  ```
  inter_block_time_i = elapsed_time[i] - elapsed_time[i-1]
  ```
  Histogram of this. What are 1st, 5th, 50th, 95th, 99th percentiles?
  
  **Expectation post-Merge:**
  - Mean ≈ 12 seconds (one block per slot)
  - But some variation: some slots skipped (blocks > 12 apart)
  - Distribution should be right-skewed (occasional very long gaps from multi-slot skips)

- [ ] **Outlier treatment:**
  - Winsorize? At which percentile? (e.g., 99th percentile = longest 1% of inter-block gaps)
  - Trim? Drop blocks with inter-block time > 10 minutes?
  - Robust regression? (Recommended: Huber M-estimation or median regression)
  
  **Recommendation:** Do not trim. Instead:
  1. Report raw results (OLS on all blocks)
  2. Report robust regression results (downweight extreme observations)
  3. Show both summary statistics for inter-block times and regression results

### 5.2 Missing: Leverage and Influence Analysis

**The Merge is a structural break**, likely a high-leverage point:

- [ ] **Identify high-influence observations:**
  - Are the first/last blocks pre-Merge anomalous?
  - Is there an Merge-day surge in block delays (temporary protocol adjustment)?
  - Compute Cook's distance for key blocks; report which blocks are most influential
  
  **Action:** After fitting model, compute:
  ```
  cook_d = (residual[i]^2 / (p * MSE)) * (leverage[i] / (1 - leverage[i]))
  ```
  Flag observations where cook_d > 4/N (rule of thumb).

---

## 6. MEASUREMENT QUALITY — CRITICAL ASSUMPTION NOT DISCUSSED

### 6.1 Missing: Data Accuracy Analysis

**Current state:** No discussion of measurement error in timestamps or block heights.

**Must address:**
- [ ] **RPC endpoint accuracy:**
  - Ethereum RPC returns block timestamps as reported by validators
  - Are validators required to report accurate Unix timestamps?
  - What's the tolerance? (Protocol allows validators to propose blocks with timestamps up to ~12 seconds in the future; ~1 second in past)
  
  **Implication:** Block timestamps have **±1 to ±12 second error** by protocol design. This affects your ability to detect sub-slot timing deviations.

- [ ] **Timestamp synchronization:**
  - Different validators may have clock skew
  - A block proposed by validator V1 has its timestamp set by V1's clock
  - If V1's clock is 1 second fast, the block timestamp will appear 1 second earlier than wall-clock time
  
  **Implication:** Systematic deviations may reflect validator clock heterogeneity, not protocol delays!

- [ ] **Recommended mitigation:**
  - Use multiple RPC endpoints and cross-check timestamps (are they identical?)
  - If divergent, document the differences
  - Consider using "block arrival time" (when the block was first observed on the network) instead of "block production time" (timestamp field). These differ by network latency (~milliseconds to seconds, depending on observer location).

**Critical assumption:** Current plan assumes timestamps in blocks are ground truth. This may not hold.

---

## 7. TIME AND CURRENCY — NOT APPLICABLE

This paper is not about monetary values, so no inflation adjustment or exchange rate conversion needed. ✓

However:

- [ ] **Unix timestamp standard:** Confirm all timestamps use Unix convention (seconds since 1970-01-01 00:00:00 UTC). Ethereum does use this. ✓

- [ ] **Date format in reporting:** Specify how you will report dates and times in tables/figures:
  - "2022-09-15 13:26:13 UTC" (unambiguous)
  - Or "Merge block 15537394, Unix timestamp 1663224479"
  - Both is best.

---

## 8. PANEL DATA SPECIFICS — NOT APPLICABLE

This paper does not use panel data in the traditional sense (units × time periods with multiple units). It is time-series: single chain, sequential blocks. However, identification strategy mentions potential individual-level analysis (validator heterogeneity).

**If you extend to validator-level analysis later:**

- [ ] **Panel structure:** Each validator is observed for multiple slots/epochs they are assigned to propose
- [ ] **Entry/exit:** Validators join (stake) and exit (unstake) the set; document this
- [ ] **Unbalanced panel risk:** Newer validators have fewer observations; plan accordingly
- [ ] **Time-invariant variables:** Validator identity is time-invariant; will be absorbed by fixed effects

**For now (block-level analysis only): skip section 8.**

---

## 9. CROSS-SECTIONAL SPECIFICS — NOT APPLICABLE

No survey weights or sampling design. The dataset is a **census of all Ethereum blocks**, not a sample. ✓

---

## 10. DATA INTEGRITY AND REPLICATION — CRITICAL GAPS

### 10.1 Missing: Raw Data Storage Plan

- [ ] **Data storage:**
  - Where will raw data be stored? (Local machine? Zenodo? AWS S3?)
  - How will data be versioned? (If you re-download blocks and timestamps change, how do you track this?)
  - What is the backup plan? (Never store single copy; use redundancy)

- [ ] **Data preservation timeline:**
  - Will raw data remain accessible 5 years after publication?
  - Recommended: Deposit in institutional repository or Zenodo with DOI

### 10.2 Missing: Processing Code and Reproducibility

- [ ] **Extraction scripts:**
  - Provide Python/SQL/R code for downloading blocks via RPC
  - Include error handling (what if RPC times out? Retry logic?)
  - Document dependencies (library versions, RPC endpoint URLs)

- [ ] **Data processing pipeline:**
  - Scripts for cleaning, filtering, aggregating
  - Should be runnable from raw data to analysis-ready dataset
  - Version control (Git) strongly recommended

### 10.3 Missing: Reproducibility Verification

- [ ] **Checksum verification:**
  - After downloading blocks, compute hash of raw dataset
  - Document hash so others can verify they downloaded the same data
  - Example: "Raw dataset sha256: abc123def456..."

- [ ] **Summary statistics verification:**
  - Report key summary statistics in paper (e.g., "Block count: 19,234,567; mean inter-block time: 12.04 seconds")
  - Readers can re-run code and verify these match

### 10.4 Missing: Synthetic Data or Example for Code Verification

**Important:** Ethereum block data is large. A reader cannot easily validate extraction code without downloading gigabytes of data.

**Recommendation:**
- [ ] Provide a **synthetic dataset** (mock blocks with realistic structure) and extraction code
- [ ] Example: 10,000 synthetic blocks spanning the Merge, with realistic timestamps and block heights
- [ ] Others can run code on synthetic data to verify logic before running on real data

**Example synthetic data format:**
```
block_number,timestamp,total_difficulty,gas_used
0,1438269988,131072,0
1,1438269993,137344,0
...
15537393,1663224467,0,12000000
15537394,1663224479,0,12000000
15537395,1663224491,0,12000000
```

---

## SUMMARY OF CRITICAL DATA GAPS

| Category | Issue | Severity | Required Action |
|----------|-------|----------|-----------------|
| **Source Documentation** | No data provider named | CRITICAL | Specify: Geth/Infura/Etherscan/other; version; endpoint |
| **Source Documentation** | No version/timestamp freeze | CRITICAL | Snapshot data at specific block height and date |
| **Sample Construction** | No explicit inclusion/exclusion rules | CRITICAL | Document all filtering rules; provide sample flow table |
| **Sample Construction** | Reorg handling not specified | CRITICAL | Choose finalized-block-only or longest-chain policy |
| **Missing Values** | Skipped slots handling unclear | CRITICAL | Decide: block-level vs. slot-level analysis |
| **Measurement Quality** | RPC timestamp accuracy not discussed | CRITICAL | Quantify ±error bounds; cross-check multiple endpoints |
| **Outliers** | No outlier detection/treatment plan | HIGH | Define outlier thresholds; report distribution |
| **Variable Definitions** | "Elapsed time" not precisely defined | HIGH | Specify: epoch (genesis vs. Unix), precision, rounding |
| **Data Integrity** | No reproducibility plan | HIGH | Commit to code archiving, synthetic data examples, hashes |

---

## RED FLAGS IN CURRENT DOCUMENTATION

1. ✗ **No data source explicitly named** — "Data Available" is insufficient; must specify provider
2. ✗ **No sample size or N reported** — Paper mentions "blocks from genesis to current" but not a concrete number
3. ✗ **No missing data discussion** — Are there any missing timestamps, gaps in block sequence?
4. ✗ **No balance table** — Should show: total blocks, blocks pre/post-Merge, skipped slots count, final analysis N
5. ✗ **No reorg handling specified** — How will you handle consensus layer reorganizations?
6. ✗ **Measurement error not discussed** — Block timestamps have ±1-12 second tolerance by protocol; impacts results
7. ✗ **Structural break not validated** — Econometric spec assumes Merge at block 15,537,394, but doesn't verify this in data
8. ✗ **No reproducibility checklist** — Raw data storage, code versioning, checksum verification all missing

---

## RECOMMENDATIONS BEFORE DATA COLLECTION

### Phase 1: Data Specification (Before Extraction)

1. **Create a formal data dictionary:**
   ```
   Variable: block_height
   Type: Integer
   Range: [0, ∞)
   Definition: Sequential block number on Ethereum canonical chain
   Source: eth_getBlockByNumber RPC call
   ---
   Variable: timestamp
   Type: Unix timestamp (integer seconds)
   Range: [1438269988, ∞)
   Definition: Block production time in seconds since 1970-01-01 00:00:00 UTC
   Precision: Nearest second
   Error bounds: ±1 to ±12 seconds (protocol tolerance)
   Source: eth_getBlockByNumber RPC call, block.timestamp field
   ```

2. **Document the exact RPC query:**
   ```python
   # Example: Extract blocks from source
   for block_height in range(START_BLOCK, END_BLOCK + 1):
       block = rpc.eth_getBlockByNumber(hex(block_height), detailed=True)
       block_height = block['number']
       timestamp = block['timestamp']
       # Validate: timestamp should be increasing
       # Validate: timestamp >= genesis_time
   ```

3. **Specify a data freeze:**
   - "Analysis uses all blocks from genesis (0) to block 19,234,567, extracted on 2025-01-15 from [RPC endpoint]. Future replication should use this frozen dataset, available at [DOI/URL]."

4. **Pre-register the analysis plan:**
   - Causal graph
   - Regression model
   - Outlier definition and handling
   - Robustness checks
   
   **Where:** OSF Registries (Open Science Framework) — free, timestamped, public.

### Phase 2: Data Collection

5. **Extract with validation:**
   - Cross-check multiple RPC endpoints (Infura, Alchemy, self-hosted node)
   - Verify timestamps are monotonically increasing
   - Detect and log any anomalies
   - Compute checksum of final dataset

6. **Document data quality:**
   - Count of blocks with valid data
   - Fraction of skipped slots
   - Min/max inter-block time
   - Any reorgs detected

### Phase 3: Analysis

7. **Test the core phenomenon before regression:**
   - Plot block height vs. elapsed time
   - Visual inspection for the Merge structural break
   - Compute mean inter-block time pre/post-Merge
   - Is there really a 12-second regularity post-Merge, or is it obscured by noise?

8. **Report sample accounting table:**
   - Total blocks downloaded: N1
   - Blocks after validation/filtering: N2
   - Blocks pre-Merge: N3
   - Blocks post-Merge: N4
   - Skipped slots (if slot-level): N5

---

## CONCLUSION

**The paper's research question is sound and the identification strategy is sophisticated.** However, the data collection and documentation plan is currently incomplete. Before proceeding to analysis, the authors must:

1. **Name the data source** and commit to reproducibility (DOI, code, synthetic data)
2. **Freeze a specific block range** and timestamp for analysis
3. **Specify sample rules** (reorg handling, skipped slot treatment, filtering criteria)
4. **Acknowledge measurement error** in block timestamps (±1-12 seconds)
5. **Plan outlier treatment** and robustness checks
6. **Register the analysis plan** publicly before looking at results

**Estimated effort:** 2-4 weeks of data engineering and validation before regression analysis can begin. This is normal for empirical work using blockchain data.

Once these steps are complete, the data review can be re-run to verify execution quality before final publication.

---

**Review Status:** ⚠️ **NOT READY FOR ANALYSIS** — Data documentation incomplete. Proceed to data specification phase (Phase 1 above).
