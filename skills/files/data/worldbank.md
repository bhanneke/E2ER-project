# World Bank Open Data via `e2er-data worldbank`

World Bank Open Data serves development indicators by country and year
through the Indicators API (https://api.worldbank.org/v2/). The default
database is the World Development Indicators (WDI, about 1,500 series, 1960 to
the latest year, about 217 economies plus regional and income-group
aggregates); `--database` reaches the others (3 Worldwide Governance
Indicators, 6 International Debt Statistics, 14 Gender Statistics, 16 Health
Nutrition and Population Statistics, …). No key is needed.

Use it for cross-country panels: GDP and growth (`NY.GDP.PCAP.KD`,
`NY.GDP.MKTP.KD.ZG`), population (`SP.POP.TOTL`), life expectancy
(`SP.DYN.LE00.IN`), school enrolment, poverty headcounts (`SI.POV.DDAY`),
trade openness (`NE.TRD.GNFS.ZS`), CO2 and energy use, inflation
(`FP.CPI.TOTL.ZG`).

## Terms of use

- The World Bank's datasets are licensed CC BY 4.0 unless labelled otherwise.
- Attribution, in the World Bank's format: "The World Bank: Dataset name: Data
  source (if known)". Each load builds this citation from the database and the
  indicators' data sources.
- Some third-party indicators may not be redistributed or carry other terms;
  the indicator metadata says so. Every load records each indicator's licence
  (`indicator_licences` in data_sources.json) and the load's note names any
  indicator that is not CC BY 4.0: check those terms before the study
  publishes the data.
- Full terms: https://www.worldbank.org/ext/en/legal/terms-conditions/datasets

The first load adds the BibTeX entry `WorldBank_OpenData` to the study's
literature.bib; cite it (`\cite{WorldBank_OpenData}`) and name the data
sources the load record lists.

## Subcommands

```
e2er-data worldbank indicators --query "gdp per capita"
e2er-data worldbank series --indicator NY.GDP.PCAP.KD,SP.POP.TOTL --countries DEU,FRA,ITA \
    --start 1990 --end 2023 --table macro_panel --save-to macro_panel.csv
```

`indicators` lists the indicators of one database whose name or code contains
every word of `--query` (id, name, unit, data source, description). It loads
nothing. Options: `--query` (required), `--database` (default 2, WDI),
`--limit` (default 50).

`series` options:

- `--indicator` (required): indicator codes, comma-separated, at most 20.
- `--countries`: ISO3 (or ISO2) codes of countries or aggregates (`WLD`,
  `EUU`, `HIC`, `SSF`), comma-separated. Default: all, which includes the
  aggregates: drop them before a country-level regression.
- `--start`, `--end`: years. Give both: a study that must be rerun needs a
  fixed period.
- `--database`: the database id (default 2).
- `--table NAME` loads the rows into data.db as the table declared in
  data_dictionary.json; `--save-to FILE.csv` also writes them under data/.

One row per indicator, country and year (long format): `indicator`,
`indicator_name`, `country`, `iso3`, `year`, `value`, `obs_status`, `unit`.
`value` is null where the World Bank has no figure; recent years are often
missing for slow indicators (poverty, education). Pivot to wide format in the
analysis, not in the load.

## Pitfalls

- WDI is revised with every release (the load records `lastupdated` as the
  version): figures for past years change. Report the version.
- Current-US$ and constant-price series differ (`…CD` vs `…KD`); growth rates
  come from constant prices.
- Aggregates are weighted by the World Bank's own methods; do not average
  country rows yourself and call it the world figure.

## What a load records

Every load that returns rows is recorded in `data_sources.json`: the terms,
the citation, the request, the query URLs, the database's last-updated date
(version), the SHA-256 of every page read, each indicator's licence and data
source, and when it ran. A table also gets its entry in `data_dictionary.json`.
A bad code or a request the API refuses exits non-zero and leaves data.db
unchanged. Report the error; do not build the table another way.
