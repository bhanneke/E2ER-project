# WHO Global Health Observatory via `e2er-data who_gho`

The WHO Global Health Observatory (GHO) holds WHO's health statistics for its
194 member states and WHO regions: life expectancy and healthy life
expectancy, mortality by cause and age, maternal and child health,
immunization coverage, HIV, tuberculosis and malaria, noncommunicable disease
risk factors (tobacco, alcohol, obesity, blood pressure), health workforce,
health spending, universal health coverage; about 2,000 indicators, mostly
yearly, many by sex, age group or urban/rural residence. e2er reads them
through the GHO OData API (https://ghoapi.azureedge.net/api/). No key is
needed. The API carries no COVID-19 data.

## Terms of use

- WHO allows use, reproduction and distribution of its datasets for public
  health purposes.
- Changes beyond matching a publication's style need WHO's prior written
  authorization; the data may not be sold or used to promote a commercial
  enterprise.
- These are not an open licence. A published study does not ship GHO data:
  publishing asks the researcher to confirm WHO's terms
  (`--accept-data-terms who_gho`), and the replication package loads the data
  again (get_data.py).
- Full terms: https://www.who.int/about/policies/publishing/data-policy/terms-and-conditions

Cite in WHO's format: "WHO, title of dataset, year, date of access,
acknowledgement of the country or countries having provided the underlying
data". Each load writes this citation. The first load adds the BibTeX entry
`WHO_GHO`; cite it and the indicator in the text.

## Subcommands

```
e2er-data who_gho indicators --query "life expectancy"
e2er-data who_gho data --indicator WHOSIS_000001 --countries DEU,FRA,ITA --start 2000 \
    --end 2021 --sex both --table life_expectancy
```

`indicators` lists the indicators whose name or code contains every word of
`--query` (code, name); it loads nothing.

`data` options:

- `--indicator` (required): the GHO code, e.g. `WHOSIS_000001` (life
  expectancy at birth), `WHOSIS_000002` (healthy life expectancy at birth).
  Find others with `indicators`.
- `--countries`: ISO3 codes, comma-separated. Default: every location,
  including WHO regions, World Bank income groups and the global figure.
- `--start`, `--end`: years.
- `--sex`: `female`, `male` or `both` (the total) keeps one sex; without it,
  every breakdown is loaded.
- `--table NAME` / `--save-to FILE.csv` as for every source.

One row per location, period and breakdown: `location` (ISO3 or a region
code), `spatial_type` (`COUNTRY`, `REGION`, `GLOBAL`, `WORLDBANKINCOMEGROUP`),
`parent_location`, `year`, `period`, `dim1_type`/`dim1` to `dim3_type`/`dim3`
(e.g. `SEX`/`SEX_FMLE`, `AGEGROUP`/`AGEGROUP_AGE15-19`, `RESIDENCEAREATYPE`/`RESIDENCEAREATYPE_CITY`),
`value` (numeric), `low` and `high` (the uncertainty interval where WHO gives
one), `value_text` (WHO's display text), `comments` and `updated`.

## Pitfalls

- Totals and breakdowns sit in the same table (`SEX_BTSX` next to
  `SEX_FMLE` and `SEX_MLE`): filter on the dim columns before summing or
  averaging.
- Many indicators are WHO model estimates, revised with every release; the
  load records the latest `updated` date as the version.
- Regions and income groups appear as locations when `--countries` is not
  given; drop rows whose `spatial_type` is not `COUNTRY` for a country panel.

## What a load records

Every load that returns rows is recorded in `data_sources.json`: the terms,
the citation, the request, the query URL, the SHA-256 of the records read, the
indicator's name, the latest `updated` date and when it ran. A table also gets
its entry in `data_dictionary.json`. A bad code or a request the API refuses
exits non-zero and leaves data.db unchanged. Report the error; do not build
the table another way.
