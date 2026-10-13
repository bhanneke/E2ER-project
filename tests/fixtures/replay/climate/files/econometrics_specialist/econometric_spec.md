# Analysis plan (time series)

`run_estimation.py` implements the frozen setup of `forecast_design.json` and writes `estimation_results.json` in the time-series results schema (`"result_kind": "timeseries"`):

1. `diagnostics`: KPSS (level) on the training series with monthly means removed (Bartlett long-run variance, lag 4); Mann-Kendall on the 20 annual means 2001-2020 with Sen's slope. Both end at 2020-12.
2. `models`: naive, seasonal naive and the trend-and-season regression, each fitted on 2001-01 to 2020-12; the regression refitted on every month for the 2024 forecast (`trend_season_full`).
3. `out_of_sample`: each model on the 36 hold-out months, with every prediction and its 95% interval, RMSE, MAE, MASE and coverage.
4. `forecasts.trend_season_2024`: 12 months with 95% intervals.

Standard library only; reads `data.db`; no randomness.
