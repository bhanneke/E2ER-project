> Demonstration. This reproduction was run as is to demonstrate e2er's replication template. It is not an assessment of the original authors' work; differences can come from e2er itself.

# Reproduction Report: Political Rupture and Selective Damage to Local Service Delivery

Peixoto & Leite (2026), SSRN preprint 7079720  
Zenodo: 10.5281/zenodo.22179151

<!-- e2er:summary begin: written by e2er from reproduction_report.json; edits here fail the check -->
## Counts and environment

Written by e2er from `reproduction_report.json` and `sandbox_log.json`. Each compared number is counted once, under its label; a result (one exhibit at one level) takes its worst number's label.

### Level 1: the package's own result files, rebuilt

17 compared numbers in 11 results.

| Label | Numbers | Results |
|---|---:|---:|
| reproduced | 12 | 6 |
| reproduced_minor | 2 | 2 |
| not_reproduced | 3 | 3 |
| could_not_run | 0 | 0 |
| Total | 17 | 11 |

### Level 2: the numbers printed in the paper

No number compared at this level.

Not assessed, each with its reason in `reproduction_report.json`: `level_2_targets`.

### Environment of the rerun

- Package snapshot: 2026-08-30 (https://p3m.dev/cran/__linux__/noble/2026-08-30)
- Platform: aarch64-unknown-linux-gnu
- Image: rocker/r-ver:4.6.1 (rocker/r-ver@sha256:4e6e6696ff54a86625c7f80046478e67014a2184e942b85eeff43db7b992d93e)
- Installed versions of the packages the report names: data.table 1.18.4, dplyr 1.2.1, tidyr 1.3.2, stringr 1.6.0, readr 2.2.0, purrr 1.2.2, janitor 2.2.1, lubridate 1.9.5, ggplot2 4.0.3, fixest 0.14.2, did 2.5.1, here 1.0.2, knitr 1.51, HonestDiD 0.2.8, MatchIt 4.7.2, broom 1.0.13, DRDID 1.3.0
- All 131 installed packages, dependencies included: `reproduction_check.json` → `environment.installed`

<!-- e2er:summary end -->

## Level 1: Package's Own Result Files

The package reproduces its own results with mixed success: 12 of 17 numbers equal the shipped files at full precision, 2 show minor differences within 10% tolerance, and 3 diverge beyond tolerance thresholds.

### Main DiD Results

**Table 1: TAC Atualizacao cadastral (TAC), TWFE, sem controles**
- ATT: published –0.00135097481805838, reproduced –0.00135097481805838 (reproduced ✓)
- SE: published 0.0056299208890215, reproduced 0.0056299208890215 (reproduced ✓)

**Table 2: TAC Atualizacao cadastral (TAC), Callaway-SantAnna, sem controles (ATT)**
- Published –0.00364909844619658, reproduced –0.00365238597730994
- Relative difference: 0.09% (within 10% tolerance)
- Label: reproduced_minor ⚠

**Table 3: TAC Atualizacao cadastral (TAC), Callaway-SantAnna, sem controles (SE)**
- Published 0.00665562333947428, reproduced 0.00620405787661537
- Relative difference: 6.79% (within 10% tolerance)
- Label: reproduced_minor ⚠

**Table 4: CadUnico familias cadastradas (log), TWFE, com controles**
- ATT: published 0.0179974464388493, reproduced 0.0179974464388492
- Relative difference: 5.56 × 10⁻¹⁸ (reproduced ✓)

**Table 5: PBF familias beneficiarias (log), Callaway-SantAnna, sem controles**
- Published –0.0193985235407047, reproduced +0.0347239490711656
- Sign reversal: negative published, positive reproduced
- Relative difference: 2.79 (far exceeds tolerance)
- Label: not_reproduced ✗

**Table 6: CRAS trabalhadores (log), TWFE, com controles**
- ATT: published –0.0610859393782066, reproduced –0.0610859393782066 (reproduced ✓)

### Power and MDE Analysis

**Table 7: TAC MDE at 80% power, Callaway-SantAnna**
- Published 0.0194053054480327, reproduced 0.0173811968394429
- Relative difference: 10.43% (exceeds 10% tolerance)
- Label: not_reproduced ✗

**Table 8: PBF familias MDE at 80% power, Callaway-SantAnna**
- Published 0.0538889825075466, reproduced 0.0351535174887705
- Relative difference: 34.77% (far exceeds tolerance)
- Label: not_reproduced ✗

**Table 9: CRAS trabalhadores ATT, Sun-Abraham**
- Published –0.0533543859800926, reproduced –0.0533543859800926 (reproduced ✓)

### Pre-Trends and Leads

**Table 10: Pre-Trends Wald Test**
- TAC Wald p-value: published 0.341, reproduced 0.341 (reproduced ✓)
- PBF families number of leads: published 6, reproduced 6 (reproduced ✓)

### Incentive Heterogeneity

**Table 11: Incentive Terciles and Gradient**
- PBF weak tercile ATT: published –0.0261514772302848, reproduced –0.0261514772302848 (reproduced ✓)
- PBF strong tercile ATT: published 0.00527505816451872, reproduced 0.00527505816451871 (relative diff 1.9 × 10⁻¹⁸, reproduced ✓)
- CadUnico weak tercile ATT: published –0.0195521494316181, reproduced –0.0195521494316181 (reproduced ✓)
- PBF gradient: published –0.0314265353948035, reproduced –0.0314265353948035 (reproduced ✓)
- CadUnico gradient: published –0.0240958094313375, reproduced –0.0240958094313375 (reproduced ✓)

## Unassessed Targets

**Level 2 (published paper):** Not assessed. The linked publication (SSRN 10.2139/ssrn.7079720) carries the title "Political Instability and Bureaucratic Resilience: The Protective Role of Performance-based Transfers in Brazilian Social Assistance," differing from the package's title "Political Rupture and Selective Damage to Local Service Delivery: Evidence from Brazil." This difference suggests a possible version mismatch. To avoid misstatement of reproduction, level-2 targets were not compared against a potentially different paper.

## Notes for Robustness Study

**PBF coefficient sign reversal:** The Callaway-SantAnna estimate for PBF families (sem controles) reversed sign from published –0.019 to reproduced +0.035. This is the most critical divergence. Investigate whether the time-conditioning, sample restriction, or specification matrix differs between runs.

**Power calculation divergence:** TAC and PBF MDE estimates show 10–35% underestimation in the reproduced version. Possible causes: changes in sample size, baseline effect magnitude, power methodology, or convergence behavior of the power calculation.

**Callaway-SantAnna estimator sensitivity:** This estimator produced the largest divergences (sign flip, large SE difference, large MDE difference) relative to TWFE and Sun-Abraham. Callaway-SantAnna may be sensitive to time-invariant unobservables or violations of parallel trends assumptions.

**File versioning:** The rebuilt output files (resultados_did.csv, poder_mde.csv) differ from the shipped package versions. Obtain the original file SHA-256 hashes to pinpoint which coefficients changed and at which decision point in the pipeline.

**Numerical precision:** Most reproduced targets match at full 15+ decimal precision, suggesting deterministic RNG seeding (documented as seed 20250627 in 00_setup.R) and reliable convergence. The three divergences likely reflect code updates, package refinements, or environment-dependent numerical libraries (BLAS/LAPACK variants).

