# `estimation_results.json` for a time-series study — the results schema

## Purpose

A time-series study models one series (or a few) over time and forecasts it:
which model was fitted, how well it fits, what it forecasts with what
uncertainty, and how it did on data it was not fitted on. Its template
declares `results = "timeseries"`; a deterministic check
(`src/core/pipeline/result_kinds.py`) holds `estimation_results.json` to this
schema, and the number check traces the paper's numbers to it.

Write the file from `run_estimation.py` (run it with `e2er-run`); every number
is computed from the data.

## Shape

```json
{
  "result_kind": "timeseries",
  "series": {"name": "monthly mean temperature, Frankfurt", "frequency": "monthly",
             "start": "1995-01", "end": "2024-12", "n_observations": 360, "unit": "degrees C"},
  "models": {
    "arima_111": {"model": "ARIMA(1,1,1)", "fit": {"aic": 1234.5, "bic": 1246.1, "log_likelihood": -614.2, "sigma2": 1.82},
                  "parameters": {"ar1": {"estimate": 0.31, "se": 0.05}}},
    "seasonal_naive": {"model": "seasonal naive", "fit": {"sigma2": 2.40}}
  },
  "forecasts": {
    "arima_2025": {"model": "arima_111", "horizon": 2, "interval_level": 0.95,
                   "points": [{"period": "2025-01", "forecast": 1.9, "lower": -0.8, "upper": 4.6},
                              {"period": "2025-02", "forecast": 2.7, "lower": -0.4, "upper": 5.8}]}
  },
  "out_of_sample": {
    "arima_test": {"model": "arima_111", "train_end": "2021-12", "test_start": "2022-01", "test_end": "2024-12",
                   "n_test": 36, "rmse": 1.41, "mae": 1.12},
    "naive_test": {"model": "seasonal_naive", "test_start": "2022-01", "test_end": "2024-12",
                   "n_test": 36, "rmse": 1.63, "mae": 1.30}
  }
}
```

## Required, and what the check verifies

- `"result_kind": "timeseries"` at the top.
- `series` with its `frequency` and `n_observations` (> 0).
- `models`: each with `model` (what was fitted) and `fit` holding at least one
  fit statistic (AIC, BIC, log-likelihood, residual variance).
- `forecasts`: each names its `model` (a key of `models`), an
  `interval_level` between 0 and 1, and `points` with `period`, `forecast`,
  `lower` and `upper`; every forecast lies inside its interval, and `horizon`,
  when given, equals the number of points.
- `out_of_sample`: each names its `model`, the number of test periods
  `n_test`, and `rmse` and `mae` (non-negative; MAE can never exceed RMSE).
  Evaluate on periods the model was not fitted on, and compare with a simple
  benchmark (naive, seasonal naive or mean) so the error has a scale.

Parameters may carry `estimate`/`se`/`p_value` like a regression coefficient.
State stationarity tests, transformations and the chosen lag order in the
model entry; the econometrics/time-series skill covers the methods.

## Tables

Forecast and error tables are `records` tables (see the table-spec skill):
`"path": "forecasts.arima_2025.points", "key_field": "period"` gives one row
per forecast period; `"path": "out_of_sample"` one row per evaluation.
