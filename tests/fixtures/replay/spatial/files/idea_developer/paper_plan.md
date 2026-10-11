# Research plan: is the regional rate spatially clustered?

**Question.** How does the rate vary across the regions in 2023, and are neighbouring regions alike?

**Kind of study.** Spatial analysis, descriptive. The study maps the rate, measures spatial autocorrelation with Moran's I (permutation inference) under two neighbour definitions, and locates local clusters (LISA). It makes no causal claim.

**Data.** The researcher's files `data/regions.csv` (the regions' boundaries as GeoJSON) and `data/regional.csv` (the rate by region and year). Both are synthetic test data made for e2er's tests: a grid of 30 square regions, no real region.

**Results to report.**
1. Summary statistics of the 2023 rate.
2. Moran's I under queen contiguity and under 4 nearest neighbours, with permutation p-values.
3. LISA clusters (high-high, low-low) and their counts.
4. Two maps: the rate in quantile classes, and the LISA clusters.

**Limits to state.** A synthetic grid; Moran's I depends on the neighbour definition and the regions' size and shape.
