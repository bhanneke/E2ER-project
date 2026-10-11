# Research plan: did adopting the policy lower the outcome?

**Question.** Did the units that adopted the policy see their outcome fall, compared with units that did not adopt it?

**Kind of study.** Policy evaluation by difference-in-differences. Adoption is staggered: 6 units adopt in 2006, 6 in 2010, 12 never in the panel (2000 to 2015).

**Data.** The researcher's files `data/panel.csv` (one row per unit and year: outcome) and `data/adoption.csv` (the first year each unit had the policy in force; empty for units that never adopted). The rows are synthetic test data generated for e2er's tests; the units are no real countries.

**Hypothesis.**

- H1: Adopting the policy lowers the outcome (the average effect on the adopters after adoption is negative).

**Results to report.**
1. The overall ATT with a bootstrap confidence interval.
2. Effects by year relative to adoption, from 5 years before to 5 years after, and the joint test of the pre-adoption effects.
3. A placebo (adoption moved 3 years earlier) and the not-yet-adopted comparison group as a sensitivity analysis.

**Limits to state.** A synthetic panel; parallel trends cannot be proven by a pre-test.
