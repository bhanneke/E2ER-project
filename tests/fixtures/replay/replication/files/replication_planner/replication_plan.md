# Replication Plan: Political Rupture and Selective Damage to Local Service Delivery — Evidence from Brazil

**Study authors:** Vitor de Moraes Peixoto, Davi Athaydes Leite  
**Zenodo record:** 10.5281/zenodo.22179151 (v2, published 2026-08-30)

---

## Level 1 Only

This plan reproduces **Level 1 targets only**: the code rebuilds the replication package's own shipped result files. All targets come from `.csv` files in `supplementary_elections_social_assistance/assistencia_social/output/data/`. Exact column names and row values are preserved in Portuguese (e.g., desfecho, estimador, spec, att, ep).

**Level 2 (published paper numbers) is not assessed.** The only linked publication (SSRN 10.2139/ssrn.7079720) carries a different title than the package and may be a different version, so comparing against it could misstate the reproduction.

---

## Environment

**R version:** 4.6.1 (platform: x86_64-pc-linux-gnu, Ubuntu 26.04.1 LTS)  
**Random seed:** 20250627 (fixed in `00_setup.R`)  
**Version source:** `AMBIENTE.md`

**Required packages** (16 total; no installation at run time):
- data.table 1.18.4
- dplyr, tidyr, stringr, readr, purrr, janitor
- lubridate
- ggplot2 4.0.3
- fixest 0.14.2
- did 2.5.1
- here 1.0.2
- knitr 1.51
- HonestDiD 0.2.8
- MatchIt 4.7.2
- broom 1.0.13

**Optional packages:** didimputation, etwfe, bigrquery (conditionally installed; not required for shipped results).

---

## Entry Points: Executable Scripts

Scripts **07–30** run from the shipped panel (`painel_assistencia_completo.csv`). Scripts **01–06** rebuild the panel but are documentary only (raw data not included).

| Script | Produces | Timeout |
|---|---|---|
| `07_did.R` | `resultados_did.csv` | 30 min |
| `08_robustez.R` | `robustez_*.csv` (5 files) | 30 min |
| `10_robustez_completa.R` | `robustez_multidesfecho_fdr.csv` | 60 min |
| `11_honestdid.R` | `robustez_pretendencias.csv`, `honestdid_cs.csv` | 30 min |
| `12_hierarquico_spillover.R` | `hierarquico_uf_blups.csv`, `spillover_regiao_saude.csv` | 20 min |
| `13_poder_balanco.R` | `poder_mde.csv`, `balanco_tratado_naotratado.csv` | 15 min |
| `20_heterogeneidade_incentivo.R` | `heterogeneidade_incentivo.csv` + variants | 30 min |
| `27_tost_tac.R` | `tost_tac.csv` | 10 min |
| `28_antecipacao.R` | `antecipacao_tac.csv` | 10 min |
| `30_proxy_incentivo_norma.R` | `proxy_incentivo_norma.csv`, `_gradiente.csv`, `_permutacao.csv`, `_residual.csv` | 20 min |

**Scripts not reproducible from this package:** `22_tac_fluxo_mensal.R` (needs VIS DATA JSON cache), `26_selecao_quase_tratados.R` (needs Crespo thesis spreadsheets). Their outputs are pre-computed and shipped.

---

## Level 1 Targets

All targets read from shipped `.csv` result files. Column names and row values preserved in Portuguese (original language).

### Main Results (`resultados_did.csv`)

| Target | Row match | Column | Value |
|---|---|---|---|
| `l1_tac_att_twfe_sem` | desfecho="Atualizacao cadastral (TAC)", estimador="TWFE", spec="sem controles" | att | -0.00135097481805838 |
| `l1_tac_ep_twfe_sem` | desfecho="Atualizacao cadastral (TAC)", estimador="TWFE", spec="sem controles" | ep | 0.0056299208890215 |
| `l1_tac_att_cs_sem` | desfecho="Atualizacao cadastral (TAC)", estimador="Callaway-SantAnna", spec="sem controles" | att | -0.00364909844619658 |
| `l1_cadunico_att_twfe_com` | desfecho="CadUnico: familias cadastradas (log)", estimador="TWFE", spec="com controles" | att | 0.0179974464388493 |
| `l1_pbf_familias_att_cs_sem` | desfecho="PBF: familias beneficiarias (log)", estimador="Callaway-SantAnna", spec="sem controles" | att | -0.0193985235407047 |
| `l1_cras_trabalhadores_att_twfe_com` | desfecho="CRAS: trabalhadores (log)", estimador="TWFE", spec="com controles" | att | -0.0610859393782066 |

### Power Analysis (`poder_mde.csv`)

| Target | Row match | Column | Value |
|---|---|---|---|
| `l1_mde_tac_cs` | desfecho="TAC (ancora)" | mde80_cs | 0.0194053054480327 |
| `l1_mde_pbf_cs` | desfecho="PBF: familias (log)" | mde80_cs | 0.0538889825075466 |
| `l1_att_sa_cras_trab` | desfecho="CRAS: trabalhadores (log)" | att_sa | -0.0533543859800926 |

### Pre-Trends Test (`robustez_pretendencias.csv`)

| Target | Row match | Column | Value |
|---|---|---|---|
| `l1_pretrend_tac_p` | desfecho="Atualizacao cadastral (TAC)" | wald_p_pretend | 0.341 |
| `l1_pretrend_pbf_fam_leads` | desfecho="PBF: familias beneficiarias (log)" | n_leads | 6 |

### Incentive Heterogeneity (`proxy_incentivo_norma.csv`)

| Target | Row match | Column | Value |
|---|---|---|---|
| `l1_incentivo_pbf_weak_att` | proxy="P1 -- familias PBF pc 2014 (norma revogada)", grupo="1o tercil (incentivo fraco) -- PBF pc 2014" | att | -0.0261514772302848 |
| `l1_incentivo_pbf_strong_att` | proxy="P1 -- familias PBF pc 2014 (norma revogada)", grupo="3o tercil (forte) -- PBF pc 2014" | att | 0.00527505816451872 |
| `l1_incentivo_cadunico_weak_att` | proxy="P2 -- cadastros CadUnico pc 2014", grupo="1o tercil (incentivo fraco) -- cadastros CU pc 2014" | att | -0.0195521494316181 |

### Incentive Gradient (`proxy_incentivo_norma_gradiente.csv`)

| Target | Row match | Column | Value |
|---|---|---|---|
| `l1_gradient_pbf` | proxy="P1 -- familias PBF pc 2014 (norma revogada)" | gradiente | -0.0314265353948035 |
| `l1_gradient_cadunico` | proxy="P2 -- cadastros CadUnico pc 2014" | gradiente | -0.0240958094313375 |

---

## Summary

**Scope:** Level 1 only (computational reproduction of shipped result files).

**Packages required:** 16 (all specified; no installation at run time).

**Entry points:** 12 analysis scripts, 0 network calls, no missing data dependencies for results.

**Targets:** 9 level-1 targets from 5 CSV outputs (main results, power, pre-trends, incentive heterogeneity, gradient).

**Level 2 (published paper) not assessed** due to title mismatch between the preprint and the package.
