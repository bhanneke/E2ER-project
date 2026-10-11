# Data summary

## Table loaded

| Table | Source | Rows |
|-------|--------|------|
| `t2m_frankfurt` | NASA POWER, `e2er-data nasa_power point --lat 50.11 --lon 8.68 --parameters T2M --temporal monthly --start 2001 --end 2023` | 276 |

`t2m_frankfurt` holds 276 rows, one per month from 2001-01 to 2023-12, with no missing value of T2M. POWER's annual values (month 13) are not loaded. The values are grid-cell estimates from NASA's MERRA-2 reanalysis (POWER Monthly and Annual API v2.10.0), not station measurements; `data_sources.json` records the request, the API version and the SHA-256 of the response.

## Variables

- `date`: the month (YYYY-MM).
- `T2M`: monthly mean air temperature at 2 m, degrees C (-4.58 to 24.67).
- `lat`, `lon`, `elevation_m`: the place requested and the grid cell's elevation (171.61 m).

## Sample construction

All 276 months are used. `summary_statistics.json` records the summary statistics; `figure_spec.json` the series figure.
