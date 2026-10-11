# Time series and forecasting: a setup fixed in advance, an honest test

A time-series study describes how one series (or a few) moves over time and
forecasts it: its trend and seasonal pattern, whether it is stationary, which
models describe it, what they forecast with what uncertainty, and how well
they did on data they were not fitted on. Read by the forecast designer and
the analysis specialist of the `time-series-forecasting` template, and by the
reviewers. The results schema is `data/timeseries-results-schema`; the
econometric detail of unit roots and ARIMA identification is in
`econometrics/time-series`.

The template enforces the order that keeps the evaluation honest:

1. the data analyst loads the series;
2. the forecast designer writes `forecast_design.json` (below) **before any
   model is fitted**;
3. the `forecast_design` check validates the setup and freezes it with its
   hold-out (`holdout_freeze.json`: SHA-256 of the design and of the
   hold-out values). From here, a changed setup stops the run once results
   exist; with the optional pre-registration the researcher also reads and
   approves the setup before it is frozen;
4. the analysis specialist fits on the training periods only, evaluates on
   the hold-out, and forecasts beyond the data;
5. the `forecast_evaluation` check recomputes every out-of-sample error from
   the predictions and the hold-out values in `data.db` and stops the run on
   leakage.

## The forecast setup (`forecast_design.json`, the forecast designer)

```json
{
  "series": {"table": "t2m_frankfurt", "time_column": "date", "value_column": "T2M",
             "name": "monthly mean 2 m air temperature, Frankfurt grid cell", "frequency": "monthly",
             "unit": "degrees C"},
  "seasonal_period": 12,
  "transformation": "none",
  "holdout": {"start": "2021-01", "end": "2023-12", "n_periods": 36},
  "horizon": 12,
  "interval_level": 0.95,
  "baselines": [
    {"model": "seasonal_naive", "method": "seasonal naive"},
    {"model": "naive", "method": "naive"}
  ],
  "candidates": [
    {"model": "trend_season", "method": "linear trend plus monthly means, OLS, normal prediction intervals"},
    {"model": "ets_ana", "method": "ETS(A,N,A), additive Holt-Winters"}
  ],
  "diagnostics": [
    {"name": "kpss_level", "kind": "stationarity", "test": "KPSS (level) on the seasonally adjusted training series"},
    {"name": "mann_kendall_annual", "kind": "trend", "test": "Mann-Kendall with Sen's slope on annual means of the training years"}
  ],
  "evaluation": {"scheme": "fixed origin", "metrics": ["rmse", "mae", "mase"]}
}
```

What the check requires:

- `series` names a table and columns in `data.db`; its periods do not repeat.
  Periods are ISO text (`2021-01`, `2021-01-31`) or numbers (years), so they
  sort in time order.
- `holdout` is the **last** `n_periods` periods of the series, with a value
  in each, and at least 24 periods (the template's setting) remain to fit on.
  Choose the hold-out by the horizon and the seasonality (at least one full
  season, and usually two to three times the horizon), never by how models
  do on it.
- `horizon` (periods to forecast beyond the data) and `interval_level`.
- At least one **baseline**: `naive` (last value), `seasonal naive` (value one
  season earlier), `mean`, or `drift` (Hyndman & Athanasopoulos, ch. 5.2). A
  forecast error means little until it is compared with what the simplest
  method achieves.
- At least one **candidate** model with its method.
- At least one **stationarity** diagnostic (ADF, KPSS) and one **trend**
  diagnostic (Mann–Kendall with Sen's slope, a linear trend test).

Write `forecast_design.md` for the researcher: why this hold-out, horizon,
these models and diagnostics, and what would change the plan.

## The analysis

**Look first.** Plot the series; decompose it (STL, or classical
decomposition for a fixed seasonal period) on the training periods; note
outliers, level shifts and changes in variance, and the dates they occur.

**Diagnostics on the training periods only.**
- Stationarity: ADF (null: unit root) and KPSS (null: stationary) together;
  agreeing results are informative, disagreeing ones point to near-unit-root
  or trend-stationary behaviour. Remove the seasonal pattern first, or use a
  seasonal test.
- Trend: Mann–Kendall (null: no monotone trend) with Sen's slope (the median
  of pairwise slopes) as the size of the trend. For seasonal data use annual
  means or the seasonal Mann–Kendall test. Autocorrelation inflates the
  significance of Mann–Kendall; say whether you corrected for it.
- Report each with its statistic, its p-value and `sample_end`, the last
  period it was computed on, which must lie before the hold-out. A
  diagnostic computed on the full series has seen the hold-out.

**Models.**
- ETS (exponential smoothing with error, trend and seasonal components) and
  ARIMA/SARIMA are the standard families; a regression on a trend and
  seasonal dummies or harmonics is a transparent alternative. Choose orders
  and components on the training periods by AIC or by time-series cross
  validation, never by hold-out error.
- Time-series cross validation (rolling origin, Tashman 2000): fit on periods
  1..t, forecast t+1..t+h, move t forward. Use it inside the training periods
  to choose models; keep the hold-out for the final comparison only.
- Fix every random seed; state software and versions in the script.

**Leakage: what makes an out-of-sample error in-sample.**
- Fitting, scaling, detrending, deseasonalising or choosing a model on
  periods that include the hold-out.
- Tuning on hold-out error, or reporting the best of many hold-out runs.
- Features that are only known after the forecast origin (a later revision of
  the series, a centred moving average).
- Refitting on the full series and calling its fit to the hold-out a forecast.
  (Refit on the full series only for the forecast beyond the data, as its
  own model entry.)

**Intervals.** Every forecast has an interval at the declared level.
Intervals from a model's formula ignore parameter and model uncertainty and
are usually too narrow; bootstrapped residual paths or empirical quantiles of
cross-validation errors are alternatives. Report the hold-out **coverage**
(share of hold-out values inside their intervals): 95% intervals that cover
70% are not 95% intervals, and the paper says so.

**Accuracy.** RMSE and MAE on the hold-out, in the series' unit; MASE
(Hyndman & Koehler 2006: MAE scaled by the in-sample MAE of the seasonal
naive method) to compare across series. MAPE is undefined at zero and
asymmetric; avoid it for temperatures and counts. To say one model forecasts
better than another, use the Diebold–Mariano test on the hold-out loss
differences, with the Harvey–Leybourne–Newbold small-sample correction; with a
short hold-out, say that the comparison has little power.

## What the results file must hold (beyond the schema)

```json
"diagnostics": {
  "kpss_level": {"test": "KPSS", "statistic": 0.21, "p_value": 0.1, "sample_end": "2020-12",
                 "note": "p-value from the KPSS table, bounded at 0.1"},
  "mann_kendall_annual": {"test": "Mann-Kendall", "statistic": 2.71, "p_value": 0.0067,
                          "sen_slope": 0.051, "sample_end": "2020-12"}
},
"models": {
  "seasonal_naive": {"model": "seasonal naive", "train_end": "2020-12", "fit": {"sigma2": 2.1}}
},
"out_of_sample": {
  "seasonal_naive_test": {"model": "seasonal_naive", "train_end": "2020-12", "test_start": "2021-01",
                          "test_end": "2023-12", "n_test": 36, "rmse": 1.9, "mae": 1.5, "coverage": 0.94,
                          "predictions": [{"period": "2021-01", "forecast": 2.3, "lower": -0.6, "upper": 5.2}]}
}
```

- `diagnostics.<name>` for every diagnostic of the setup, with `statistic`,
  `p_value` and `sample_end`.
- `models.<key>` for every baseline and candidate, with `train_end`.
- `out_of_sample` entries for every baseline and candidate, on exactly the
  hold-out periods, with all `predictions` (period, forecast; lower and upper
  when the model gives intervals). The check recomputes RMSE, MAE and the
  coverage from them and the hold-out values in `data.db`.
- At least one `forecasts` entry beyond the last period of the data with the
  declared horizon and interval level (from a model refitted on all periods:
  give it its own `models` entry and do not evaluate it on the hold-out).

The check writes `forecast_check.json`: the recomputed errors and each
model's RMSE relative to the best baseline.

## What a forecasting paper must not do

- Call an in-sample fit a forecast, or compare models on the periods used to
  choose them.
- Report forecasts without intervals, or intervals without their hold-out
  coverage.
- Claim a model is better without the baseline comparison and a test of the
  difference.
- Read a trend test as the cause of the trend.

## References

- Box, G. E. P., Jenkins, G. M., & Reinsel, G. C. (2008). *Time Series Analysis: Forecasting and Control* (4th ed.). Wiley. https://doi.org/10.1002/9781118619193
- Hyndman, R. J., & Athanasopoulos, G. (2021). *Forecasting: Principles and Practice* (3rd ed.). OTexts. https://otexts.com/fpp3/
- Hyndman, R. J., & Khandakar, Y. (2008). Automatic time series forecasting: the forecast package for R. *Journal of Statistical Software*, 27(3). https://doi.org/10.18637/jss.v027.i03
- Hyndman, R. J., & Koehler, A. B. (2006). Another look at measures of forecast accuracy. *International Journal of Forecasting*, 22(4), 679–688. https://doi.org/10.1016/j.ijforecast.2006.03.001
- Tashman, L. J. (2000). Out-of-sample tests of forecasting accuracy: an analysis and review. *International Journal of Forecasting*, 16(4), 437–450. https://doi.org/10.1016/S0169-2070(00)00065-0
- Diebold, F. X., & Mariano, R. S. (1995). Comparing predictive accuracy. *Journal of Business & Economic Statistics*, 13(3), 253–263. https://doi.org/10.1080/07350015.1995.10524599
- Harvey, D., Leybourne, S., & Newbold, P. (1997). Testing the equality of prediction mean squared errors. *International Journal of Forecasting*, 13(2), 281–291. https://doi.org/10.1016/S0169-2070(96)00719-4
- Dickey, D. A., & Fuller, W. A. (1979). Distribution of the estimators for autoregressive time series with a unit root. *Journal of the American Statistical Association*, 74(366a), 427–431. https://doi.org/10.1080/01621459.1979.10482531
- Kwiatkowski, D., Phillips, P. C. B., Schmidt, P., & Shin, Y. (1992). Testing the null hypothesis of stationarity against the alternative of a unit root. *Journal of Econometrics*, 54(1–3), 159–178. https://doi.org/10.1016/0304-4076(92)90104-Y
- Mann, H. B. (1945). Nonparametric tests against trend. *Econometrica*, 13(3), 245–259. https://doi.org/10.2307/1907187
- Sen, P. K. (1968). Estimates of the regression coefficient based on Kendall's tau. *Journal of the American Statistical Association*, 63(324), 1379–1389. https://doi.org/10.1080/01621459.1968.10480934
