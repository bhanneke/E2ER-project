# Forecast setup

- **Series**: `t2m_frankfurt.T2M`, monthly, 2001-01 to 2023-12 (276 months), degrees C.
- **Hold-out**: the last 36 months, 2021-01 to 2023-12: three full seasonal cycles, three times the horizon. Training: 2001-01 to 2020-12 (240 months).
- **Horizon**: 12 months beyond the data (2024), with 95% intervals.
- **Baselines**: naive (last training value) and seasonal naive (the same month of 2020).
- **Candidate**: a regression on a linear trend and twelve monthly means (OLS). It is transparent and has a trend parameter that answers the question; its intervals include parameter uncertainty.
- **Diagnostics, training years only**: KPSS for level stationarity after removing the monthly means; Mann-Kendall with Sen's slope on the 20 annual means.
- **Evaluation**: one forecast origin (2020-12); RMSE, MAE, MASE (scaled by the seasonal naive's in-sample MAE) and the share of hold-out months inside the 95% intervals.

The hold-out was chosen by the horizon and the seasonal cycle, before any model was fitted. With 36 months the comparison of two forecasts has little power; the paper says so.
