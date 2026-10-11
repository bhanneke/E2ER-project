# Replication package: monthly temperature at Frankfurt, trend and forecast

**Paper ID**: @@PAPER_ID@@

`estimation.py` reads table `t2m_frankfurt` from `data.db` (NASA POWER monthly T2M at 50.11 N, 8.68 E, 2001-2023, loaded with `e2er-data nasa_power point`) and writes `estimation_results.json`: diagnostics on the training years, the naive, seasonal naive and trend-and-season forecasts of the 2021-2023 hold-out with their errors, and the 2024 forecast. Standard library only; run it with `python estimation.py` in a folder holding `data.db`.
