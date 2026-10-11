# Replication package: the radius–period distribution of a synthetic planet sample

**Paper ID**: @@PAPER_ID@@

`estimation.py` reads table `exoplanets` from `data.db` (loaded from `data/exoplanets.csv`) and writes `estimation_results.json`: summary statistics, the radius distribution, the discovery methods and the rank correlation of radius and period. Standard library only; run it with `python estimation.py` in a folder holding `data.db`.

The data are synthetic test data; they describe no real planet.
