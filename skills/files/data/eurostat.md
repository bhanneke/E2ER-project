# Eurostat via `e2er-data eurostat`

Eurostat publishes the official statistics of the EU, its member states and
regions: national and regional accounts, prices (HICP), labour market,
population and migration, health, education, energy, environment, trade,
tourism, agriculture; several thousand datasets, many by NUTS region (NUTS 1,
2 and 3). e2er reads them through Eurostat's dissemination API
(https://ec.europa.eu/eurostat/api/dissemination/). No key is needed.

## Terms of use

- Reuse for commercial or non-commercial purposes is authorised provided the
  source is acknowledged.
- Data that belong to other sources, and data for countries outside the EU,
  EFTA and the candidate countries (e.g. the USA, Japan, China), may be reused
  non-commercially only. A research paper is non-commercial reuse.
- Changed data must be marked as changed, with a disclaimer that Eurostat is
  not responsible: say so in `data_summary.md` and the paper when the study
  transforms Eurostat figures.
- Eurostat keeps no past versions of a dataset; the study's extract, recorded
  with its SHA-256, is the record.
- Full terms: https://ec.europa.eu/eurostat/en/help/copyright-notice

Cite as Eurostat asks: "Source: [DOI of the dataset], [access date]"; a
filtered extract is a customised version: "Source: [datacode link], [access
date]". Each load writes both into its citation (the DOI is
`https://doi.org/10.2908/<CODE>`). The first load adds the BibTeX entry
`Eurostat_Database`; cite it and give the dataset code and DOI in the text.

## Subcommands

```
e2er-data eurostat datasets --query "gdp nuts 2"
e2er-data eurostat dimensions --dataset nama_10r_2gdp
e2er-data eurostat data --dataset nama_10r_2gdp --filter unit=MIO_EUR --geo-level nuts2 \
    --start 2010 --end 2023 --table gdp_nuts2
e2er-data eurostat data --dataset prc_hicp_manr --filter coicop=CP00,geo=DE+FR+IT \
    --start 2015-01 --table hicp
```

`datasets` searches Eurostat's table of contents (code, title, type, last
update, first and last period, number of values); it loads nothing.
`dimensions` lists a dataset's dimensions and the codes of its latest period
(e.g. `unit`, `na_item`, `geo`); it loads nothing. Read it before `data`.

`data` options:

- `--dataset` (required): the dataset code, e.g. `nama_10r_2gdp`.
- `--filter`: `dimension=code` pairs, comma-separated; several codes of one
  dimension joined with `+`, e.g. `unit=MIO_EUR,geo=DE1+DE2`. Filter every
  dimension that has more codes than the study needs (unit, sex, age, na_item):
  otherwise all are loaded.
- `--geo-level`: one of `country`, `nuts1`, `nuts2`, `nuts3`, `aggregate`,
  `city`: all regions of that level. Give either this or a `geo` filter.
- `--start`, `--end`: periods in the dataset's format (`2015`, `2015-Q1`,
  `2015-01`).
- `--table NAME` / `--save-to FILE.csv` as for every source.

One row per observation: each dimension's code and label (`geo`,
`geo_label`, …), `time`, `value` and Eurostat's `flag` (`p` provisional, `e`
estimated, `b` break in series, `c` confidential, `u` low reliability, `d`
definition differs). Report flagged values; `b` and `d` matter for a panel.

## Pitfalls

- A request above 500,000 values is refused (Eurostat answers it only
  asynchronously): filter more.
- NUTS boundaries change (NUTS 2016, 2021, 2024): codes of one region can
  differ across years. Check `dimensions` and the data before linking regions
  over time.
- Aggregates (`EU27_2020`, `EA20`) are in the `geo` list with countries; drop
  them before a country-level analysis.
- Datasets are updated twice a day and earlier versions are not kept: the
  load records the `updated` time stamp.

## What a load records

Every load that returns rows is recorded in `data_sources.json`: the terms,
the citation (DOI and extract link), the request, the query URL, the
dataset's `updated` time stamp (version), the SHA-256 of the answer, and when
it ran. A table also gets its entry in `data_dictionary.json`. A bad code, an
unknown dimension or a request Eurostat refuses exits non-zero and leaves
data.db unchanged. Report the error; do not build the table another way.
