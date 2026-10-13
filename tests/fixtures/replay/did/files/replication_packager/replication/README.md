# Replication package: a staggered difference-in-differences evaluation of a synthetic panel

**Paper ID**: @@PAPER_ID@@

`estimation.py` reads tables `panel` and `adoption` from `data.db` (loaded from `data/panel.csv` and `data/adoption.csv`) and writes `estimation_results.json`: the overall ATT, the event study, the pre-trends test, the placebo and the sensitivity analyses. numpy and scipy; run it with `python estimation.py` in a folder holding `data.db`.

The data are synthetic test data; the units are no real countries.
