# Analysis plan (descriptive)

The study reports descriptive results, written by `run_estimation.py` to `estimation_results.json` in the descriptive results schema (`"result_kind": "descriptive"`):

1. `statistics`: n, mean, standard deviation, minimum, quartiles and maximum of radius and period; the count and share of transit discoveries.
2. `distributions.radius`: planets per radius bin, edges 0.5, 1, 1.5, 2, 3, 4, 6, 10 and 16 Earth radii (left-closed bins).
3. `distributions.method`: planets per discovery method.
4. `associations.radius_period`: Spearman's rank correlation of period and radius (ties get mean ranks). An association, not an effect.
5. `figures`: the two figures of `figure_spec.json`.

No regression is estimated and no test of a causal hypothesis is made. Quantiles interpolate linearly between order statistics. The script uses the standard library only and reads `data.db`.
