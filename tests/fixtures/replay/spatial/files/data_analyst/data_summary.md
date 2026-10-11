# Data summary

## Tables loaded

| Table | Source | Rows |
|-------|--------|------|
| `regions` | the researcher's file `data/regions.csv` | 30 |
| `regional` | the researcher's file `data/regional.csv` | 62 |

`regions` holds the boundaries of 30 square regions (a synthetic 6 x 5 grid, longitude 0 to 12 E, latitude 44 to 54 N). `regional` holds the rate of each region in 2022 and 2023, and of the extra-regio code RZZ, which has no territory and no geometry. The data are synthetic test data generated for e2er's tests (`tests/fixtures/replay/spatial/make_fixture.py`).
