# Replication package: spatial autocorrelation of a rate on a synthetic grid of regions

**Paper ID**: @@PAPER_ID@@

`estimation.py` reads tables `regions` and `regional` from `data.db` (loaded from `data/regions.csv` and `data/regional.csv`) and writes `estimation_results.json`, `spatial_units.csv` and the weights files: Moran's I under queen contiguity and 4 nearest neighbours with permutation inference, and LISA clusters. numpy only; run it with `python estimation.py` in a folder holding `data.db`.

The data are synthetic test data; the regions are no real regions.
