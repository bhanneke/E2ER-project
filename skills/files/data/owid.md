# Our World in Data via `e2er-data owid`

Our World in Data (OWID) publishes about 5,000 charts on health, demography,
economic development, poverty, energy, emissions, education, food and
conflict, by country and year, compiled from the WHO, the UN, the World Bank,
academic datasets and OWID's own work. `owid chart` loads the data behind one
chart with the metadata of each indicator: who produced the data and under
which licence. No key is needed.

Use it when a question needs a long-run or compiled series that no single
statistical office publishes (life expectancy since 1800, CO2 per capita,
literacy, extreme poverty), and to find out which producer a series comes
from. When a study needs the producer's own revision or breakdowns, load from
the producer (World Bank, WHO, Eurostat) instead.

## Terms of use

- Data produced by OWID are CC BY: use and pass them on, citing OWID.
- Most data on OWID come from third parties and remain under their licences.
  Every load records each origin's licence (`indicators.<column>.origins` in
  data_sources.json) and the note names any origin whose licence is not an
  open one (for example "JSTOR terms"): check those terms before the study
  publishes the data.
- Charts OWID marks as not redistributable are not loaded.
- Full terms: https://ourworldindata.org/faqs

Cite both OWID and the producers, as OWID asks: each load's citation is the
indicators' own long citation ("… – with major processing by Our World in
Data. … [original data]. Retrieved … from https://ourworldindata.org/grapher/
<slug>"). The first load adds the BibTeX entry `OWID`; cite it and the
producers named in the load record.

## Subcommands

```
e2er-data owid search --query "life expectancy"
e2er-data owid chart --chart life-expectancy --entities DEU,FRA,ITA --start 1950 \
    --table life_expectancy
e2er-data owid chart --chart co2-emissions-per-capita --table co2pc
```

`search` lists charts matching words (slug, title, variant, subtitle, number
of entities, last update); it loads nothing. The slug is the end of a chart's
URL (https://ourworldindata.org/grapher/<slug>).

`chart` options:

- `--chart` (required): the slug (a chart URL works too).
- `--entities`: countries or regions, by name (`Germany`) or ISO3 code
  (`DEU`), comma-separated. Default: all, regions and income groups included.
- `--columns`: only these indicator columns (their short names).
- `--start`, `--end`: years.
- `--table NAME` / `--save-to FILE.csv` as for every source.

One row per entity and year (or `day` for daily series): `entity`, `code`
(ISO3; empty for OWID's regions such as "Europe" or "High-income countries"),
`year`, and one column per indicator, named by its short name.

## Pitfalls

- OWID's regional aggregates are OWID's own sums and may differ from the
  producers' aggregates; rows with an empty `code` are aggregates.
- Long-run series join several sources (see the indicator's origins); breaks
  at the joins are common. Say which sources cover which years.
- Charts are updated and slugs sometimes change (the API redirects an old
  slug, sometimes to a chart with more dimensions); the load records each
  indicator's last update as the version.

## What a load records

Every load that returns rows is recorded in `data_sources.json`: the terms,
the citation, the request, the CSV URL and its SHA-256, the chart's title,
each indicator's title, unit, last update, OWID variable id, dataset version
and origins (producer, title, licence and its URL, the producer's citation),
and when it ran. A table also gets its entry in `data_dictionary.json`. An
unknown chart, an entity the chart does not have, or a chart marked not
redistributable exits non-zero and leaves data.db unchanged. Report the error;
do not build the table another way.
