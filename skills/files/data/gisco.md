# Eurostat GISCO boundaries via `e2er-data gisco`

Boundaries of the EU's statistical regions (NUTS 0 to 3, versions 2003 to 2024) and of countries, as GeoJSON geometries in data.db, to map regional data (Eurostat's NUTS tables) and to build spatial weights. Non-commercial use; maps carry the EuroGeographics notice. Website: https://ec.europa.eu/eurostat/web/gisco. No key is needed.

## Terms of use

- Non-commercial use only.
- Every map and publication using the boundaries carries: © EuroGeographics for the administrative boundaries.
- The boundary files are not passed on: a published study loads them again.
- Full terms: https://ec.europa.eu/eurostat/web/gisco/geodata/statistical-units
- A published study may not pass these data on: publishing asks the researcher to confirm the terms, and the replication package loads the data again (get_data.py) instead of shipping them.

Cite: Eurostat, GISCO. Territorial units for statistics (NUTS), boundaries. European Commission. https://ec.europa.eu/eurostat/web/gisco/geodata/statistical-units/territorial-units-statistics. © EuroGeographics for the administrative boundaries. (BibTeX key `Eurostat_GISCO_NUTS`, added to the study's literature.bib on the first load).

## Subcommands

```
e2er-data gisco nuts --level <level>    # NUTS regions of one level, e.g. --level 2 --year 2021 --scale 20M --crs 4326.
e2er-data gisco countries    # Country boundaries, e.g. --year 2024 --scale 20M.
```

`nuts` options:

- `--level` (required): NUTS level: 0 (countries), 1, 2 or 3.
- `--year`: NUTS version: 2003, 2006, 2010, 2013, 2016, 2021, 2024. Default 2021.
- `--scale`: Generalisation: 01M (detailed) to 60M (coarse). Default 20M.
- `--crs`: EPSG code: 4326 (lon/lat, default), 3035 (ETRS89-LAEA metres), 3857.
- `--countries`: Only these country codes, e.g. DE,FR,IT (EL for Greece). Default: all.
- `--table NAME` loads the rows into the study's data.db as the table declared in data_dictionary.json; `--save-to FILE.csv` also writes them under data/.

`countries` options:

- `--year`: Version: 2001, 2006, 2010, 2013, 2016, 2020, 2024. Default 2024.
- `--scale`: Generalisation: 01M to 60M. Default 20M.
- `--crs`: EPSG code: 4326 (default), 3035, 3857.
- `--countries`: Only these GISCO country ids, e.g. DE,FR. Default: all.
- `--table NAME` loads the rows into the study's data.db as the table declared in data_dictionary.json; `--save-to FILE.csv` also writes them under data/.

## What e2er records

Every load that returns rows is recorded in the study's `data_sources.json`: the source, its terms, the citation, the request as made, the query sent and the SHA-256 of every file read, and when it ran. A table also gets its entry in `data_dictionary.json`. A load that fails or returns no rows leaves data.db unchanged and exits non-zero; read the error and fix the request.

## Using the boundaries in a spatial study

```
e2er-data gisco nuts --level 2 --year 2021 --scale 20M --crs 4326 --table nuts2_boundaries
```

- One row per region: `nuts_id`, `levl_code`, `cntr_code`, `name_latn`,
  `nuts_name`, `mount_type`, `urbn_type`, `coast_type` and `geometry` (the
  GeoJSON geometry as text). Name the table in `spatial_design.json` under
  `boundaries` (`"source": "gisco", "table": "nuts2_boundaries",
  "id_column": "nuts_id", "geometry_column": "geometry"`), with
  `"crs": "EPSG:4326"`.
- Match the NUTS version to the data. Eurostat's regional tables use the
  NUTS version in force for their year (NUTS 2021 from 2021 data on, NUTS 2016
  before); codes change between versions (regions are split, merged and
  renamed). A data unit whose code is not in the boundaries is listed in
  `units_without_geometry` with the reason; the spatial design check fails on
  any that are not.
- The 20M file covers the EU, EFTA and candidate countries, overseas regions
  included (Canarias, Guadeloupe, Réunion, …). Say whether overseas regions are
  in the analysis: they have no land neighbours, so contiguity weights leave
  them as islands.
- Greece is `EL`, not `GR`; the United Kingdom is `UK` in NUTS 2016 and absent
  from NUTS 2021.
- `--scale 60M` is enough for maps of NUTS 2 and contiguity weights; `01M` is
  large (tens of MB).
- Every map drawn from these boundaries carries the notice "© EuroGeographics
  for the administrative boundaries" (the map figure's `attribution`), and the
  paper names it where it describes the data. Not for commercial use.
