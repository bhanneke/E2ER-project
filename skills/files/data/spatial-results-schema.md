# `estimation_results.json` for a spatial study — the results schema

## Purpose

A spatial study describes how a variable varies across places: the spatial
units, the variable by unit, whether neighbouring units are alike (spatial
autocorrelation, e.g. Moran's I), where clusters lie, and the maps that show
it. Its template declares `results = "spatial"`; a deterministic check
(`src/core/pipeline/result_kinds.py`) holds `estimation_results.json` to this
schema, and the number check traces the paper's numbers to it.

Write the file from `run_estimation.py` (run it with `e2er-run`).

## Shape

```json
{
  "result_kind": "spatial",
  "units": {"type": "NUTS 2 region", "n_units": 240, "id_field": "geo", "crs": "EPSG:4326", "year": 2023},
  "variables": {"unemployment_rate": {"n": 240, "mean": 6.1, "sd": 3.4, "min": 1.8, "median": 5.2, "max": 23.4}},
  "spatial_statistics": {
    "moran_unemployment": {"statistic": "morans_i", "variable": "unemployment_rate",
                           "weights": "queen contiguity, row-standardised",
                           "estimate": 0.62, "expected": -0.0042, "z": 14.8, "p_value": 0.0,
                           "p_value_method": "normal"}
  },
  "clusters": {"high_high": {"count": 31}, "low_low": {"count": 44}},
  "maps": [{"id": "map_unemployment", "variable": "unemployment_rate", "classification": "quantiles", "classes": 5}]
}
```

## Required, and what the check verifies

- `"result_kind": "spatial"` at the top.
- `units`: the spatial unit (`type`) and their number `n_units` (> 0).
- `spatial_statistics`: each with `statistic`, `variable`, `weights` (how
  neighbours are defined) and a numeric `estimate`. For Moran's I a stated
  `expected` must be -1/(n_units - 1). A `p_value` lies between 0 and 1 and,
  unless `p_value_method` names a permutation test, follows from `z` (two-sided
  normal p, within 0.005).
- `maps`: the map specifications, each with an `id` and the `variable` shown
  (and how values are classed).

In the `spatial-analysis` template the analysis also writes the units and
values it used (`spatial_units.csv`) and its weights (`spatial_weights.csv`:
from, to, weight), and the template's check recomputes every Moran's I from
them, requires permutation inference (`"p_value_method": "permutation"`,
`n_permutations` >= 99) and builds a map figure for every entry of `maps`
(see `data/spatial-statistics`).

Units without neighbours (islands) change the weights: say how they were
handled. Results depend on the weights; report a second weights definition as
a robustness entry when the conclusion rests on clustering.

## Tables

`"path": "spatial_statistics"` in a `records` table gives one row per
statistic; `"path": "variables"` one row per variable (see the table-spec skill).
