# `estimation_results.json` for a descriptive study — the results schema

## Purpose

A descriptive study reports what the data look like: how many observations,
the summary statistics of each variable, how the values are distributed, and
the figures that show it. It estimates no effect and tests no causal claim.
Its template declares `results = "descriptive"`, and a deterministic check
(`src/core/pipeline/result_kinds.py`) holds `estimation_results.json` to this
schema before anything is drafted. The number check then traces every number
of the paper to this file, `summary_statistics.json` or `figure_spec.json`.

Write the file from your script (`run_estimation.py`, run with `e2er-run`),
never by hand: every number is computed from the data in `data.db` or `data/`.

## Shape

```json
{
  "result_kind": "descriptive",
  "sample": {"n_observations": 60, "unit": "planet", "source": "data/exoplanets.csv"},
  "statistics": {
    "radius_earth": {"n": 60, "mean": 3.42, "sd": 2.81, "min": 0.62, "p25": 1.48,
                      "median": 2.31, "p75": 4.06, "max": 13.9, "unit": "Earth radii"},
    "transit": {"n": 60, "share": 0.75, "count": 45}
  },
  "distributions": {
    "radius": {"variable": "radius_earth",
               "bins": [{"lower": 0.5, "upper": 1.0, "count": 6}, {"lower": 1.0, "upper": 2.0, "count": 19}]},
    "method": {"variable": "discovery_method", "n": 60,
               "categories": [{"category": "Transit", "count": 45}, {"category": "Radial velocity", "count": 15}]}
  },
  "associations": {
    "radius_period": {"x": "period_days", "y": "radius_earth", "method": "spearman", "estimate": 0.21, "n": 60}
  },
  "figures": ["fig_radius_period.pdf", "fig_radius_hist.pdf"]
}
```

## Required, and what the check verifies

- `"result_kind": "descriptive"` at the top.
- `sample.n_observations`: the whole number of observations described (> 0).
- `statistics`: one object per variable, each with `n` (non-missing values,
  at most `sample.n_observations`) and at least one statistic. Order
  statistics must not decrease (`min <= p25 <= median <= p75 <= max`, also
  `p5`, `p10`, `p90`, `p95`), `sd >= 0`, the mean lies within `[min, max]`,
  a `share` lies between 0 and 1.
- `distributions`: one object per distribution, with `bins` (`lower < upper`,
  in order, not overlapping, whole non-negative `count`) or `categories`
  (`category`, `count`). When the distribution states `n`, its counts add up
  to `n`.
- `figures`: the `figure_spec.json` filenames that show the distributions
  (the data analyst's figure spec; see the figure-spec skill).

Optional: `associations` (a rank or linear correlation between two variables,
with its method and `n`), `groups` (the same statistics per subgroup), and
any further numbers the paper states. An association is a description, not an
effect: name it as one.

## Tables

The paper's tables of statistics are `records` tables in `table_spec.json`
(see the table-spec skill): `"path": "statistics"` gives one row per
variable, `"path": "distributions.radius.bins"` one row per bin.
