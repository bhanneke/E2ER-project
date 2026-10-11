# Descriptive analysis: describing a sample so others can trust the description

A descriptive study says what the data look like: how many observations,
which values they take, how those values are distributed, how two variables
move together, and what the data cannot show. It estimates no effect. Most
papers in astronomy, earth science and official statistics are descriptive in
large part, and nearly every empirical paper in any field starts with a
description of its sample (Emerson & Colditz 1983 found that 58% of the
articles in one volume of the New England Journal of Medicine could be read
with descriptive statistics alone).

This skill is read by the data architect, the data analyst and the analysis
specialist of the `descriptive-study` template. The results schema is in
`data/descriptive-results-schema`; tables in `data/table-spec`; figures in
`data/figure-spec`.

## 1. Define the sample before computing anything

- Name the unit (one planet, one station-month, one country-year) and the
  population the sample stands for. Name every filter with its reason, in the
  order applied, with the count left after each (e.g. "6,153 confirmed
  planets; 4,412 with a measured radius and period").
- Say how the observations were produced and what that process cannot record
  (detection limits, stations that closed, countries that did not report).
  A distribution of what was observed is not the distribution of what
  exists; say which one the paper describes.

## 2. The data dictionary the data check reads

The template's data check (`data_quality`) runs after the data analyst and
before the analysis. It reads every table `data_dictionary.json` declares from
`data.db` and stops the run when the data are not fit to describe. The data
architect declares, per table:

```json
{"name": "planets", "source": "exoplanets", "key": ["pl_name"],
 "coverage": {"column": "disc_year", "from": 1995, "to": 2025},
 "columns": [
   {"name": "pl_name", "type": "TEXT", "description": "planet name"},
   {"name": "pl_orbper", "type": "REAL", "unit": "days", "description": "orbital period"},
   {"name": "pl_rade", "type": "REAL", "unit": "Earth radii", "description": "planet radius",
    "missing": "no radius for planets found by radial velocity only; the radius statistics use the planets with a radius"},
   {"name": "disc_year", "type": "INTEGER", "unit": "year", "description": "year of discovery"}
 ]}
```

- `unit` on every numeric column the study uses ("none" for counts, codes and
  identifiers). A number without a unit cannot be checked for plausibility.
- `key`: the columns that identify a row. Without a key the check counts
  whole repeated rows. Duplicates stop the run: remove them when loading.
- `missing` on every column that misses more than 5% of its values (the
  template's setting): why the values are missing, and what the analysis does
  (uses the rows with a value, reports the share, never fills in silently).
- `coverage`: the range the data must span (years, dates), when the question
  names one.

The check writes `data_quality.md` and `data_quality.json` (rows, duplicates,
missing values per column, units, ranges). Cite its numbers in the data
section; the number check reads `data_quality.json`.

## 3. Summary statistics

- Report n (non-missing values) for every statistic, next to it.
- Mean and standard deviation only where the distribution is roughly
  symmetric; always the median and the quartiles; the minimum and maximum;
  for skewed positive quantities (periods, masses, incomes, counts) also the
  statistics of the logarithm or the geometric mean, and say which.
- Quantiles: state the definition. Python's `statistics.quantiles(...,
  method="inclusive")` and numpy's default are Hyndman & Fan's type 7 (linear
  interpolation between order statistics); R's default is the same. Different
  packages give different quartiles for small samples.
- Shares with their denominators ("47 of 60, 78.3%").
- Round only at the end; keep full precision in `estimation_results.json`
  and let the table renderer round.

## 4. Distributions

- Histograms: choose bins on purpose and say how. The Freedman–Diaconis
  width (2 × IQR × n^(−1/3)) is a sound default for continuous data; for
  quantities spanning orders of magnitude, bin in log space (equal width in
  log10) and say so. Report the bins and counts in `distributions` (they must
  add up to n) and draw the histogram from those bins.
- Categories: every category with its count, including "other" and
  "unknown", ordered by count or by a natural order.
- Check the conclusion against a second bin width. A feature (a gap, a second
  peak) that appears at one bin width only is not a finding.

## 5. Associations

- Rank correlation (Spearman's ρ) for monotone relations in skewed data;
  Pearson's r only for roughly linear relations without strong outliers. Give
  n and, if inference is wanted, a confidence interval (bootstrap, with the
  seed stated).
- An association between two variables in an observed sample is a
  description. Selection can produce it (in exoplanet surveys, small planets
  are easier to find on short orbits). Name the selection effects that could.
- Groups: the same statistics per group, with each group's n.

## 6. Figures from saved data

Every figure in `figure_spec.json` names where its values come from, and the
template's figure check re-reads them and stops the run when a figure shows
values that are not the data:

- `"source": {"table": "planets", "columns": {"x": "pl_orbper", "y": "pl_rade", "groups": "discoverymethod"}, "where": "pl_rade IS NOT NULL AND pl_orbper > 0"}`
  for a scatter of the rows of a data.db table;
- `"source": {"results": "distributions.radius.bins"}` for a histogram of
  the bins in `estimation_results.json`.

Write the figure values from the same query the source names (the data
analyst's script, or the analysis script), rounded to no fewer decimals than
needed. Keep figures under about 10,000 points; a figure that would need more
is a histogram or a binned plot, sourced from the results.

## 7. What a descriptive paper must not do

- Claim causes, effects or mechanisms the description cannot show.
- Report a statistic without its n, a share without its denominator, a
  number without its unit.
- Describe a filtered sample as if it were the population.
- Fill missing values without saying so, or drop them without counting.

## References

- Emerson, J. D., & Colditz, G. A. (1983). Use of statistical analysis in The New England Journal of Medicine. *NEJM*, 309(12), 709–713. https://doi.org/10.1056/NEJM198309223091206
- Freedman, D., & Diaconis, P. (1981). On the histogram as a density estimator: L2 theory. *Zeitschrift für Wahrscheinlichkeitstheorie und verwandte Gebiete*, 57, 453–476. https://doi.org/10.1007/BF01025868
- Hyndman, R. J., & Fan, Y. (1996). Sample quantiles in statistical packages. *The American Statistician*, 50(4), 361–365. https://doi.org/10.1080/00031305.1996.10473566
- Spearman, C. (1904). The proof and measurement of association between two things. *The American Journal of Psychology*, 15(1), 72–101. https://doi.org/10.2307/1412159
- Wickham, H. (2014). Tidy data. *Journal of Statistical Software*, 59(10). https://doi.org/10.18637/jss.v059.i10
- Little, R. J. A., & Rubin, D. B. (2019). *Statistical Analysis with Missing Data* (3rd ed.). Wiley. https://doi.org/10.1002/9781119482260
