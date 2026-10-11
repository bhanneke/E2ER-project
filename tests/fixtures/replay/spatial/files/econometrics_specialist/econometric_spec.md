# Analysis plan (spatial)

`run_estimation.py` reads tables `regions` and `regional` from `data.db` and writes the spatial results (`"result_kind": "spatial"`), the units and values it used (`spatial_units.csv`) and its weights (`spatial_weights.csv`, `spatial_weights_knn4.csv`):

1. Units: the 30 regions with a 2023 rate and a geometry (RZZ has no geometry).
2. Weights: queen contiguity (regions sharing a boundary vertex), row-standardised; robustness: the 4 nearest regions by centroid distance.
3. Moran's I of the 2023 rate under both weights, 999 permutations, two-sided pseudo p-values.
4. LISA under queen weights, 999 conditional permutations per region, significance 0.05.
5. Maps: the rate in five quantile classes; the LISA clusters.

numpy only; no web access.
