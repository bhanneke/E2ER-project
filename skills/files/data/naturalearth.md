# Natural Earth via `e2er-data naturalearth`

Country boundaries of the world (Natural Earth, release v5.1.2, 1:110m, 1:50m, 1:10m) as GeoJSON geometries in data.db, to map country data (World Bank, WHO, OWID) by ISO3 code. Public domain. Website: https://www.naturalearthdata.com/. No key is needed.

## Terms of use

- Public domain; no permission is needed and crediting the authors is unnecessary.
- Full terms: https://www.naturalearthdata.com/about/terms-of-use/

Cite: Natural Earth (release v5.1.2). Admin 0 – Countries. https://www.naturalearthdata.com/. Made with Natural Earth. Free vector and raster map data @ naturalearthdata.com. (BibTeX key `NaturalEarth`, added to the study's literature.bib on the first load).

## Subcommands

```
e2er-data naturalearth countries    # Country boundaries, e.g. --scale 110m (--countries FRA,DEU to keep some).
```

`countries` options:

- `--scale`: 110m (coarse, default), 50m or 10m (detailed, large).
- `--countries`: Only these ISO3 codes (adm0_a3 or iso_a3_eh), e.g. FRA,DEU.
- `--table NAME` loads the rows into the study's data.db as the table declared in data_dictionary.json; `--save-to FILE.csv` also writes them under data/.

## What e2er records

Every load that returns rows is recorded in the study's `data_sources.json`: the source, its terms, the citation, the request as made, the query sent and the SHA-256 of every file read, and when it ran. A table also gets its entry in `data_dictionary.json`. A load that fails or returns no rows leaves data.db unchanged and exits non-zero; read the error and fix the request.

## Using the boundaries

```
e2er-data naturalearth countries --scale 110m --table world_countries
```

- One row per country: `adm0_a3`, `iso_a3_eh`, `iso_a3`, `name`,
  `name_long`, `continent`, `region_un`, `subregion`, `pop_est` and
  `geometry` (GeoJSON text, EPSG:4326).
- Join ISO3 country codes (World Bank, WHO, OWID) on `iso_a3_eh` or
  `adm0_a3`. `iso_a3` is -99 for France, Norway, Kosovo, Northern Cyprus and
  Somaliland. Aggregates in the data (World Bank regions such as `EUU`, `WLD`)
  have no geometry: leave them out of the units or list them in
  `units_without_geometry`.
- 1:110m has 177 countries and leaves out small island states; use `50m` when
  they matter.
- The files are the release `v5.1.2` of the Natural Earth vector repository,
  pinned so a rerun reads the same geometry.
