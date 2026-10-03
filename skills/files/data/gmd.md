# Global Macro Database via `e2er-data gmd`

The Global Macro Database (GMD, https://www.globalmacrodata.com) has annual
data on 46 macroeconomic variables for 239 economies, from 1086 to the
present, with forecasts for the next years. It comes in versioned quarterly
releases (e.g. `2026_09`). No key is needed.

Use it for cross-country annual macro panels: real and nominal GDP,
inflation, CPI, interest rates, exchange rates, government debt and deficits,
trade, money supply, house prices, and banking, currency and sovereign debt
crises. For monthly or daily US series use FRED.

## Terms of use

The GMD is free for academic use: research meant for publication, teaching
and theses by students, faculty and researchers at universities and academic
research institutes. Everyone else needs written permission from the GMD
(commercial users: Anansi Data Analytics). The data may go into the study's
replication package, labelled as coming from the GMD; it may not be
republished anywhere else. If the study is not academic use, stop and tell
the researcher before loading anything.

## Subcommands

```
e2er-data gmd versions      # releases, newest first
e2er-data gmd variables     # variable codes with units and definitions
e2er-data gmd countries     # ISO3 codes and country names
e2er-data gmd series --variables rGDP,infl --countries USA,DEU --start 2000 --end 2024 \
    --save-to gmd_macro.csv --table gmd_macro
```

`series` options:

- `--variables` GMD variable codes, comma-separated (`rGDP`, `infl`, `CPI`,
  `cbrate`, `govdebt_GDP`, …). Run `variables` for the list.
- `--countries` ISO3 codes, comma-separated. Omit for every country.
- `--start`, `--end` years.
- `--version` a release from `versions`. Without it the newest release is
  used. Name the release in `data_summary.md`; for a study that must be
  rerun later, pass the release explicitly.

Each row is one country-year: `ISO3`, `countryname`, `year`, the variables,
and a `forecast_<variable>` column per variable. `forecast_<variable> = 1`
marks a GMD forecast, not an observation. Drop or flag forecast years before
estimation. Country-years where every requested variable is empty are left
out.

## What a load records

- The release used, the URL and the SHA-256 of the release file read, in
  `data_sources.json` and in the table's entry in `data_dictionary.json`
  (with the terms of use and the citation). Export ships both files and the
  dossier lists the release and the hash.
- The GMD citation (`\cite{GMD2025}`) is added to the study's bibliography.
  Cite it wherever the paper uses GMD data.

An unknown variable, an unknown ISO3 code, an unknown release or a failed
download exits non-zero with the valid choices in the message, and data.db is
not changed. Report the error; do not build the table another way.

Long histories are sparse in early years. A table whose variables are less
than 90% filled fails the data contract unless its dictionary entry declares
`min_non_null`; prefer a year range where the variables are observed.
