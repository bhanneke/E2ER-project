# Identification strategy

**Design.** Staggered difference-in-differences. Units adopt the policy in 2006 or 2010; 12 units never adopt within the panel and form the comparison group.

**Estimator.** Callaway and Sant'Anna's group-time ATT without covariates, with the universal base period (the year before adoption), aggregated to an overall ATT by cohort size and to effects by event time from -5 to 5. Two-way fixed effects is not used: with staggered adoption it averages comparisons that use earlier adopters as controls.

**Identifying assumption.** Without the policy, the adopters' outcome would have moved in parallel with the never-adopters' (parallel trends), and units did not change their outcome before adoption (no anticipation).

**Checks.** The pre-adoption effects (event time -5 to -2) and their joint Wald test; a placebo with adoption moved 3 years earlier on pre-adoption years only; the not-yet-adopted comparison group; a conservative relative-magnitudes bound at event time 0.

**Inference.** Bootstrap over units (999 draws); 24 clusters.
