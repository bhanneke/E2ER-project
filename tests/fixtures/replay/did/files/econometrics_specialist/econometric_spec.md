# Analysis plan

`run_estimation.py` reads tables `panel` and `adoption` from `data.db` and writes `estimation_results.json`:

1. `main`: Callaway and Sant'Anna's overall ATT (group-time effects ATT(g, t) for t >= g against the base year g - 1, never-adopters as the comparison group, averaged with cohort-size weights). Tests H1.
2. `event_study`: effects by event time -5 to 5, universal base period; event time -1 is the reference (0 by construction).
3. `pre_trends`: Wald test that the effects at event times -5 to -2 are jointly zero, with the covariance of the bootstrap draws (chi-squared, 4 df).
4. `placebo`: adoption moved 3 years earlier, each cohort's years from adoption on dropped.
5. `sensitivity`: the not-yet-adopted comparison group, and a conservative relative-magnitudes bound at event time 0 (Mbar = 1; the largest change between consecutive pre-adoption effects).

Inference: bootstrap over units, 999 draws, seed 20261011; t = estimate / se; p from Student's t with 23 degrees of freedom (24 clusters). numpy and scipy; no web access.
