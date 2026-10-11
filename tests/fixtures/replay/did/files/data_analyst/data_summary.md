# Data summary

## Tables loaded

| Table | Source | Rows |
|-------|--------|------|
| `panel` | the researcher's file `data/panel.csv` | 384 |
| `adoption` | the researcher's file `data/adoption.csv` | 24 |

The panel is balanced: 24 units, each observed every year from 2000 to 2015, with no missing outcome. Six units adopt the policy in 2006, six in 2010 and twelve never within the panel. The data are synthetic test data generated for e2er's tests (`tests/fixtures/replay/did/make_fixture.py`); the units are no real countries.

`summary_statistics.json` records the counts and the outcome's summary statistics; `figure_spec.json` the mean outcome by adoption cohort.
