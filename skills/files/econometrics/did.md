# Difference-in-Differences

## Core equation

$$Y_{it} = \alpha + \beta \cdot \text{Post}_t \cdot \text{Treated}_i + \gamma_i + \delta_t + \varepsilon_{it}$$

Where:
- $\gamma_i$ = unit fixed effects (absorbs time-invariant unit characteristics)
- $\delta_t$ = time fixed effects (absorbs common shocks)
- $\beta$ = ATT (average treatment effect on the treated)

## Required assumptions

1. **Parallel trends**: in the absence of treatment, treated and control units would have
   followed the same trend. Always test with pre-period event study.

2. **No anticipation**: units did not change behavior before the treatment was announced.
   Test by checking for pre-treatment effects in event study.

3. **SUTVA**: no spillovers between treated and control units.

## Parallel trends test (mandatory)

Run event study with relative-time dummies. The period -1 should be omitted (reference).
Pre-treatment coefficients should be near zero and jointly insignificant.

Report: F-test of joint pre-treatment significance.

## Staggered DiD

If treatment is staggered (different units treated at different times):
- Use Callaway-Sant'Anna or Sun-Abraham estimator
- Do NOT use two-way FE (Goodman-Bacon decomposition shows it can be negative-weighted)
- Report heterogeneity in treatment effects by cohort

## Standard error choices

- Cluster at the unit level (default)
- Consider two-way clustering (unit + time) if correlated shocks
- Report wild bootstrap p-values for small number of clusters (<30)
