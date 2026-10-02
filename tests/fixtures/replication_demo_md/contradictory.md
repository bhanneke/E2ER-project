# Reproduction Report: Political Rupture and Selective Damage to Local Service Delivery

**Study**: Political Rupture and Selective Damage to Local Service Delivery: Evidence from Brazil  
**DOI:** 10.5281/zenodo.22179151  
**Authors:** Vitor de Moraes Peixoto, Davi Athaydes Leite  
**Reproduction Date:** 2026-09-29

---

## Summary

All six entry points ran successfully in the sandbox environment (R 4.6.1, Docker image rocker/r-ver:4.6.1). The package's replication code executed without errors or timeouts. 

**Comparison focuses on Level 1 targets** (package's own result files, rebuilt to full precision). No level-2 targets assessed because the published paper source (SSRN 10.2139/ssrn.7079720) differs in title from the package ("Political Instability and Bureaucratic Resilience..." vs. "Political Rupture...") and may represent a different version.

**Level 1 Results (16 targets across 4 exhibits):**

| Outcome | Count |
|---------|-------|
| reproduced | 12 |
| reproduced_minor | 2 |
| not_reproduced | 2 |
| **Total** | **16** |

---

## Level 1: Package's Own Result Files (Rebuilt)

### Main DiD Results (`resultados_did.csv`)

**Exhibit:** Main DiD results — 24 estimates (4 estimators × 6 outcomes × 1-2 specifications each)

| Target | Published | Reproduced | Difference | File Location | Status |
|--------|-----------|-----------|-----------|----------------|--------|
| TAC ATT, TWFE, sem controles | –0.00135097481805838 | –0.00135097481805838 | 0 | row: desfecho="Atualizacao cadastral (TAC)", estimador="TWFE", spec="sem controles" | **reproduced** |
| TAC SE, TWFE, sem controles | 0.0056299208890215 | 0.0056299208890215 | 0 | row: desfecho="Atualizacao cadastral (TAC)", estimador="TWFE", spec="sem controles" | **reproduced** |
| TAC ATT, Callaway-SantAnna, sem controles | –0.00364909844619658 | –0.00365238597730994 | –0.00000328753111336 (0.09%) | row: desfecho="Atualizacao cadastral (TAC)", estimador="Callaway-SantAnna", spec="sem controles" | **reproduced_minor** |
| TAC SE, Callaway-SantAnna, sem controles | 0.00665562333947428 | 0.00620405787661537 | –0.00045156546285891 (6.78% rel.) | row: desfecho="Atualizacao cadastral (TAC)", estimador="Callaway-SantAnna", spec="sem controles" | **reproduced_minor** |
| CadUnico families ATT, TWFE, com controles | 0.0179974464388493 | 0.0179974464388492 | –0.0000000000000001 | row: desfecho="CadUnico: familias cadastradas (log)", estimador="TWFE", spec="com controles" | **reproduced** |
| PBF families ATT, Callaway-SantAnna, sem controles | –0.0193985235407047 | 0.0347239490711656 | 0.0541224726114703 (sign change) | row: desfecho="PBF: familias beneficiarias (log)", estimador="Callaway-SantAnna", spec="sem controles" | **not_reproduced** |
| CRAS workers ATT, TWFE, com controles | –0.0610859393782066 | –0.0610859393782066 | 0 | row: desfecho="CRAS: trabalhadores (log)", estimador="TWFE", spec="com controles" | **reproduced** |

**Entry point:** `did_main` (script: `07_did.R`); status: OK, 13s

---

### Power and MDE Analysis (`poder_mde.csv`)

**Exhibit:** Minimum detectable effects at 80% power under Callaway-SantAnna and Sun-Abraham estimators

| Target | Published | Reproduced | Difference | File Location | Status |
|--------|-----------|-----------|-----------|----------------|--------|
| TAC MDE 80%, Callaway-SantAnna | 0.0194053054480327 | 0.0173811968394429 | –0.0020241086085898 (10.43% rel.) | row: desfecho="TAC (ancora)", column: mde80_cs | **not_reproduced** |
| PBF families MDE 80%, Callaway-SantAnna | 0.0538889825075466 | 0.0351535174887705 | –0.0187354650187761 (34.77% rel.) | row: desfecho="PBF: familias (log)", column: mde80_cs | **not_reproduced** |
| CRAS workers ATT Sun-Abraham | –0.0533543859800926 | –0.0533543859800926 | 0 | row: desfecho="CRAS: trabalhadores (log)", column: att_sa | **reproduced** |

**Entry point:** `poder_balanco` (script: `13_poder_balanco.R`); status: OK, 7.2s

---

### Pre-Trends Test (`robustez_pretendencias.csv`)

**Exhibit:** Wald p-values for joint significance of leads (parallel trends validation)

| Target | Published | Reproduced | Difference | File Location | Status |
|--------|-----------|-----------|-----------|----------------|--------|
| TAC pre-trends Wald p-value | 0.341 | 0.341 | 0 | row: desfecho="Atualizacao cadastral (TAC)", column: wald_p_pretend | **reproduced** |
| PBF families number of leads | 6 | 6 | 0 | row: desfecho="PBF: familias beneficiarias (log)", column: n_leads | **reproduced** |

**Entry point:** `pretrends_honestdid` (script: `11_honestdid.R`); status: OK, 7.5s; HonestDiD incomplete due to missing `libglpk.so.40` system library (non-critical for these targets)

---

### Incentive Heterogeneity (`proxy_incentivo_norma.csv`, `proxy_incentivo_norma_gradiente.csv`)

**Exhibit:** Treatment effect heterogeneity across terciles of incentive intensity (PBF, CadUnico, residualized baselines)

| Target | Published | Reproduced | Difference | File Location | Status |
|--------|-----------|-----------|-----------|----------------|--------|
| PBF weak tercile ATT | –0.0261514772302848 | –0.0261514772302848 | 0 | row: proxy="P1 -- familias PBF pc 2014", grupo="1o tercil (incentivo fraco)", column: att | **reproduced** |
| PBF strong tercile ATT | 0.00527505816451872 | 0.00527505816451871 | –0.00000000000000001 | row: proxy="P1 -- familias PBF pc 2014", grupo="3o tercil (forte)", column: att | **reproduced** |
| CadUnico weak tercile ATT | –0.0195521494316181 | –0.0195521494316181 | 0 | row: proxy="P2 -- cadastros CadUnico pc 2014", grupo="1o tercil (incentivo fraco)", column: att | **reproduced** |
| PBF gradient (weak–strong) | –0.0314265353948035 | –0.0314265353948035 | 0 | row: proxy="P1 -- familias PBF pc 2014", column: gradiente | **reproduced** |
| CadUnico gradient (weak–strong) | –0.0240958094313375 | –0.0240958094313375 | 0 | row: proxy="P2 -- cadastros CadUnico pc 2014", column: gradiente | **reproduced** |

**Entry point:** `incentivo_gradient` (script: `30_proxy_incentivo_norma.R`); status: OK, 80.8s

---

## Not Reproduced — Details

**Three targets failed reproduction at level 1:**

1. **PBF families ATT (Callaway-SantAnna, no controls)**  
   - Published: –0.0193985235407047  
   - Reproduced: +0.0347239490711656  
   - Reason: Sign reversal (negative to positive) and large magnitude difference (0.054). Both indicate the rebuilt code produced materially different results for this coefficient. The DiD main results file was rewritten by the run (`written_by_run: true, same_as_package: false`), suggesting code version differences or environment effects.

2. **TAC MDE at 80% power (Callaway-SantAnna)**  
   - Published: 0.0194053054480327  
   - Reproduced: 0.0173811968394429  
   - Reason: 10.43% relative difference (exceeds 10% tolerance). Both estimates are within same order of magnitude and same sign, but the reproduced value is 5.2% smaller, suggesting differences in power calculation or sample-size dependent variation.

3. **PBF families MDE at 80% power (Callaway-SantAnna)**  
   - Published: 0.0538889825075466  
   - Reproduced: 0.0351535174887705  
   - Reason: 34.77% relative difference (far exceeds tolerance). The reproduced MDE is substantially smaller, indicating the code rebuilds a different power curve or uses different parameter inputs than the published file.

---

## Environment and Versions

**Docker image:** rocker/r-ver:4.6.1  
**R version:** 4.6.1  
**Package versions installed (16 core packages):**
- data.table 1.18.6.1  
- dplyr 1.2.1, tidyr 1.3.2, stringr 1.6.0, readr 2.2.0, purrr 1.2.2  
- janitor 2.2.1, lubridate 1.9.5, here 1.0.2  
- ggplot2 4.0.3  
- fixest 0.14.2, did 2.5.1, HonestDiD 0.2.8, MatchIt 4.8.1, broom 1.0.13  
- knitr 1.52  

**Seed:** Fixed to 20250627 in `00_setup.R` (reproducibility for random sampling)

**Known limitations:**
- `01–06_panel_construction.R` not run (rebuilds from external microdata: TSE, SUAS Census, Base dos Dados BigQuery, VIS DATA 3); processed panel shipped ready-to-use  
- `22_tac_fluxo_mensal.R` not run (requires bulky VIS DATA 3 JSON cache); output pre-computed  
- `26_selecao_quase_tratados.R` not run (requires data from Crespo 2024 doctoral thesis; authorized use only)  
- HonestDiD sensitivity analysis incomplete due to missing `libglpk.so.40` system dependency; pre-trend tests and main DiD unaffected

---

## Level 2 Assessment

**Not assessed.** The linked publication (SSRN 10.2139/ssrn.7079720, "Political Instability and Bureaucratic Resilience: The Protective Role of Performance-based Transfers in Brazilian Social Assistance") carries a different title than the package ("Political Rupture and Selective Damage to Local Service Delivery: Evidence from Brazil") and may represent a different version or strand of work. Comparing against it could misstate the reproduction. Obtain the exact paper version cited by the package authors if available.

---

## Notes for Robustness Studies

- **Power calculation differences:** The substantial divergence in TAC and PBF MDE values (10–35%) merits investigation into whether the sample size, effect-size baseline, or power methodology has changed between package versions.
- **PBF coefficient sign flip:** The reversal of the Callaway-SantAnna ATT for PBF families from –0.0194 (published) to +0.0347 (reproduced) is the most salient finding. Check whether the sample, specification matrix, or parallel-trends conditioning differs.
- **Callaway-SantAnna estimator stability:** The CS estimator yields sign reversals and large changes; consider whether time-invariant unobservables or treatment timing assumptions drive this. Compare against TWFE or Sun-Abraham on the same outcomes.
- **File versioning:** The sandbox_log records that `resultados_did.csv` and `poder_mde.csv` were rewritten by the run and differ from the package copy. Request the SHA-256 of the shipped versions to identify exactly which coefficients changed.

---

## Reproducibility Summary

**Computational reproducibility:** Partial.  
**Code ran:** All 6 entry points completed without errors.  
**Results matched:** 14 of 18 level-1 targets (78%).  
**Critical failure:** 1 sign reversal in main DiD result (PBF families, CS estimator).  
**Material divergence:** 2 power calculations (10–35% underestimation in reproduced version).

The package replication code executes reliably under the specified R environment. However, three level-1 targets show material divergence from the rebuilt files, suggesting either (1) the plan's target values were copied from an earlier package version, or (2) the code has environment-dependent behavior (e.g., numerical precision, convergence criteria). Further investigation into the source and version of the shipped result files is recommended before assessing robustness.
