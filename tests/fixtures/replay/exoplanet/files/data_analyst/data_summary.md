# Data summary

## Table loaded

| Table | Source | Rows |
|-------|--------|------|
| `exoplanets` | the researcher's file `data/exoplanets.csv` | 60 |

The table `exoplanets` holds 60 rows, one per planet, with no missing radius or period. The data are synthetic test data generated for e2er's tests (`tests/fixtures/replay/exoplanet/make_fixture.py`); they describe no real planet.

## Variables

- `period_days`: orbital period in days (0.87 to 279.189).
- `radius_earth`: radius in Earth radii (1.2 to 14.29).
- `discovery_method`: Transit (47 planets) or Radial velocity (13 planets).
- `discovery_year`: year of discovery.

## Sample construction

All 60 rows of the file are used; no row is dropped. `summary_statistics.json` records the counts and the summary statistics, `figure_spec.json` the two figures (radius against period, the radius histogram).
