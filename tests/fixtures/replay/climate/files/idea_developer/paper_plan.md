# Research plan: monthly temperature at Frankfurt, its trend and a one-year forecast

**Question.** How has the monthly mean air temperature at the Frankfurt grid cell changed from 2001 to 2023, and how well does a simple trend-and-season model forecast it, compared with naive forecasts?

**Kind of study.** Time series and forecasting. The study describes the series (seasonal cycle, trend), tests for a trend and for level stationarity on the training years, fits one candidate model and two baselines on 2001 to 2020, evaluates all three on the hold-out 2021 to 2023, and forecasts 2024 with 95% intervals. It makes no causal claim about why the temperature changed.

**Data.** NASA POWER, monthly mean 2 m air temperature (T2M, degrees C) at 50.11 N, 8.68 E, 2001-01 to 2023-12 (276 months), loaded with `e2er-data nasa_power point`. POWER values are grid-cell estimates from the MERRA-2 reanalysis, not station measurements.

**Results to report.**
1. The series and its seasonal cycle (figure).
2. Diagnostics on the training years: KPSS (level stationarity, monthly means removed) and Mann-Kendall with Sen's slope on annual means.
3. Out-of-sample RMSE, MAE, MASE and interval coverage on the 36 hold-out months for the naive, seasonal naive and trend-and-season forecasts.
4. The 2024 forecast with 95% intervals, from the model refitted on all years.

**Limits to state.** One grid cell; reanalysis values; a 20-year training window; a linear trend is a description of these years, not a projection of climate change.
