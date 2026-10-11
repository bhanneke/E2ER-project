# Spatial statistics in practice: units, boundaries, weights, Moran's I, clusters, maps

For the `spatial-analysis` template. The results file follows
`data/spatial-results-schema`; this skill says what the template's checks
require and how to do the analysis well.

## 1. The design file: `spatial_design.json` (data architect)

```json
{
  "units": {"type": "NUTS 2 region", "table": "unemployment", "id_column": "geo", "year": 2023, "level": "NUTS 2"},
  "boundaries": {"source": "gisco", "table": "nuts2_boundaries", "id_column": "nuts_id",
                 "geometry_column": "geometry", "dataset": "NUTS 2021, 1:20 million",
                 "attribution": "© EuroGeographics for the administrative boundaries"},
  "crs": "EPSG:4326",
  "weights": {"type": "queen", "row_standardised": true,
              "islands": "regions without a land neighbour are linked to their nearest region by centroid distance"},
  "units_without_geometry": [{"id": "ITZZ", "reason": "extra-regio code, no territory"}],
  "excluded_units": [{"id": "FRY1", "reason": "overseas region outside the mainland frame"}],
  "map_projection": "laea_europe"
}
```

- `boundaries`: loaded with `e2er-data gisco nuts …` (NUTS regions, countries)
  or `e2er-data naturalearth countries` (countries of the world) into a data.db
  table (`source` names the connector), or a GeoJSON file the researcher put
  under `data/` (`file`, `id_property`, with `source`, `licence` and
  `attribution` written out).
- `crs`: the coordinate reference system of the boundaries' coordinates
  (EPSG:4326 = longitude/latitude in degrees, as both connectors load by
  default; EPSG:3035 = ETRS89-LAEA in metres).
- `weights.type`: `queen` (shared border or corner), `rook` (shared border),
  `knn` (with `k`), `distance_band` (with `threshold`, in the CRS's units or
  km), `inverse_distance`, `kernel` (with `bandwidth`); `row_standardised`
  true or false; `islands`: what happens to units without neighbours.
- `units_without_geometry`: every unit of the data whose id is not in the
  boundaries, with the reason (aggregates such as `EU27_2020`, "not
  regionalised" codes ending in `ZZ`, a region of another NUTS version). One
  entry per id, or a pattern for a group (`{"id": "*ZZ", "reason": "extra-regio
  codes, no territory"}`, `{"id": "CH*", "reason": "…"}`); a sentence that
  names a group is not matched. Before writing it, compare the ids of the data
  with the ids of the boundaries (both are in data.db): a NUTS version that
  does not fit the data's year leaves real regions without geometry (Eurostat's
  data from 2024 on use NUTS 2024: NL35, NL36, PT19 to PT1D), and the right
  fix then is the matching boundaries, not a longer list.

### What the design check (`spatial_design`) stops on

- the boundaries' source is not recorded (no load in data_sources.json, or a
  file without source, licence and attribution);
- no CRS, or one that does not fit the coordinates;
- a unit of the data has no geometry and is not listed with a reason, or more
  than 20% of the units have none (the boundaries do not fit the data: wrong
  NUTS level, version or id scheme);
- the weights are not documented (type and its parameter, row
  standardisation, islands).

## 2. The analysis (econometrics specialist, in `run_estimation.py`)

e2er's interpreter has numpy, pandas, scipy and statsmodels, not GeoPandas,
shapely or PySAL. Read the geometries from data.db (`json.loads` of the
`geometry` column) and compute what you need with numpy:

- **Contiguity** (queen): two polygons are neighbours when they share a vertex.
  GISCO's generalised files are topologically consistent, so neighbouring
  regions share their border vertices exactly; round coordinates to 6
  decimals, build a map from vertex to units, and link units that meet at a
  vertex. Rook needs a shared edge (two consecutive shared vertices).
- **Centroids**: the area-weighted centroid of the polygon rings (shoelace
  formula), on projected coordinates (for Europe project lon/lat to ETRS89-LAEA
  first, or use `--crs 3035` boundaries); distances in km.
- **k nearest neighbours** on centroids: every unit has exactly k neighbours,
  so there are no islands; the matrix is not symmetric.

Write what the analysis used, so e2er can check it:

- `spatial_units.csv`: one row per unit in the analysis, column `id` (the
  boundaries' id) and one column per analysed variable;
- `spatial_weights.csv`: one row per link, columns `from`, `to`, `weight`
  (after row standardisation when it is declared: each unit's weights sum
  to 1). A second weights definition goes in its own file named by
  `weights_file` on its statistic.

**Moran's I**: I = (n / S0) · Σ_ij w_ij z_i z_j / Σ_i z_i², z = x - mean(x),
S0 = Σ_ij w_ij (Moran 1950; Cliff and Ord 1981). Under no autocorrelation
E[I] = -1/(n - 1). Inference by permutation: shuffle the values over the units
999 times (`numpy.random.default_rng(<seed>)`, seed in the script), recompute
I each time; the pseudo p-value is (1 + #{|I_perm - E| >= |I - E|}) / (999 + 1)
two-sided (or one-sided for positive autocorrelation; say which). Report:

```json
"moran_unemployment": {"statistic": "morans_i", "variable": "unemployment_rate",
  "weights": "queen contiguity, row-standardised", "weights_file": "spatial_weights.csv",
  "estimate": 0.62, "expected": -0.0042, "z": 14.8, "p_value": 0.001,
  "p_value_method": "permutation", "n_permutations": 999, "alternative": "two-sided"}
```

`z` is (I - mean of the permuted I) / their standard deviation. The results
check (`spatial_results`) recomputes I from the two files and stops the run
when it differs (beyond rounding), when no Moran's I has permutation inference
with at least 99 permutations, when a p-value is smaller than 1/(permutations
+ 1), or when the weights file names units the units file does not, links a
unit to itself, or (row-standardised) has rows that do not sum to 1.

**Local clusters (LISA, Anselin 1995)**, optional: I_i = z_i Σ_j w_ij z_j /
(Σ z² / n); conditional permutation (shuffle the other values around unit i)
for each unit's pseudo p-value; classify significant units as high-high,
low-low, high-low, low-high by the sign of z_i and of its spatial lag. Many
local tests: say how many units are significant at 0.05 and that about 5%
would be by chance; a false discovery rate correction is the honest default.
Report counts under `clusters` and the per-unit category as a column of
`spatial_units.csv` (for a categories map). Getis and Ord's G_i* (1992) finds
hot and cold spots of high and low values in the same way.

## 3. Practice: what changes the answer

- **The modifiable areal unit problem** (Openshaw 1984): the same data at
  NUTS 1, 2 and 3, or on different boundaries, give different correlations and
  different Moran's I. Say why the chosen level fits the question; where it
  matters, repeat the main statistic at another level.
- **Weights choice**: results depend on the neighbour definition. Report the
  main statistic under a second definition (e.g. queen and k = 6 nearest
  neighbours) as a robustness entry; a conclusion that holds under one only is
  weak.
- **Edge effects and islands**: units at the edge of the study area (borders
  with countries outside the data, coasts) have fewer neighbours; islands and
  overseas regions have none under contiguity. Say how they were handled
  (dropped, linked to the nearest unit, k-nearest weights) and how many there
  were. Do not let a geographic outlier (Canarias, Guyane) drive the result
  silently.
- **Missing values**: Moran's I needs a value for every unit in the weights;
  drop units without a value from both files and say how many.
- **Different sizes**: rates of small and large regions are not equally
  reliable; say so where a few small regions are extreme.
- **Spatial autocorrelation is a description**, not a cause: neighbours can
  be alike because of a common cause, interaction or sorting. A spatial
  regression (spatial lag or error model, Anselin 1988) is a further study.

## 4. Maps

Every entry of `maps` in the results becomes a map figure. When
`figure_spec.json` has no figure named by the map's `figure` (default
`fig_<id>.pdf`), the results check builds one from `spatial_design.json`
(the boundaries) and `spatial_units.csv` (the values). A map entry:

```json
{"id": "map_unemployment", "variable": "unemployment_rate", "classification": "quantiles", "classes": 5,
 "legend_label": "Unemployment rate 2023 (%)", "extent": [-25, 34, 45, 72]}
```

`classification`: `quantiles`, `equal_interval`, `breaks` (with `breaks`) or
`categories` (for LISA clusters, with `categories` mapping each value to a
`label` and `color`). `extent` (west, south, east, north in degrees) frames
the map; the overseas regions outside it are not shown. The map carries the
boundaries' attribution (GISCO requires "© EuroGeographics for the
administrative boundaries" on every map). See `data/figure-spec` for the map
figure type.
