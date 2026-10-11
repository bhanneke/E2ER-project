# NOAA Climate Data Online via `e2er-data noaa` (needs a free token)

NOAA's National Centers for Environmental Information (NCEI) serve daily
weather-station records from the Global Historical Climatology Network -
Daily (GHCN-Daily) through the Climate Data Online (CDO) web services:
maximum and minimum temperature, precipitation, snowfall and snow depth per
station and day, for stations worldwide, some reaching back to the 1800s.

**A free token is needed.** Request one by email at
https://www.ncdc.noaa.gov/cdo-web/token and set `NOAA_TOKEN`. Without it the
source is not offered to the data architect and a load says how to get one.
The token is sent in a header, never printed or recorded.

Use it for station-level temperature or precipitation trends and extremes
(heat days, frost days, heavy-rain days) and for weather controls tied to a
place. For gridded values anywhere on Earth without a token, use
`nasa_power` (modelled, not measured).

## Terms of use

- Free with the token; NOAA states no licence and no limit on passing the
  data on. A study may publish the data it loaded.
- The token allows five requests a second and 10,000 a day.
- Cite the dataset with the subset used and the access date, and the overview
  article (both are on the dataset's page,
  https://www.ncei.noaa.gov/access/metadata/landing-page/bin/iso?id=gov.noaa.ncdc:C00861).
  Each load's citation in `data_sources.json` fills in the stations, types,
  period and access date. The first load adds `GHCND_Menne2012` and
  `Menne2012_GHCND_overview` to the study's literature.bib; cite both.

## Subcommands

```
e2er-data noaa stations --bbox -74.3,40.5,-73.7,40.9 --datatypes TMAX
e2er-data noaa daily --stations USW00094728 --datatypes TMAX,TMIN,PRCP \
    --start 2015-01-01 --end 2024-12-31 --table central_park
```

`stations` lists stations (id, name, latitude, longitude, elevation, first
and last date, data coverage) in `--bbox west,south,east,north` or a CDO
`--location` (e.g. `FIPS:36`), optionally only those with `--datatypes`. It
loads nothing.

`daily` options:

- `--stations` (required): GHCN-Daily ids, comma-separated (`USW00094728` is
  New York Central Park; the `GHCND:` prefix is added).
- `--datatypes`: e.g. `TMAX,TMIN,PRCP,SNOW,SNWD` (default: all the station
  has).
- `--start`, `--end` (required, both included): days, `YYYY-MM-DD`. The
  service gives one year of daily data per request; e2er splits longer periods
  by calendar year (at most 30 years per load).
- `--table NAME` loads the rows into data.db as the table declared in
  data_dictionary.json; `--save-to FILE.csv` also writes them under data/.

Rows are long: `date, station, datatype, value, attributes`, one per station,
day and data type. Pivot in the analysis (one column per data type).

## Units and pitfalls

- e2er asks for metric units: temperatures in °C, precipitation and snowfall
  in mm, snow depth in mm.
- `attributes` holds GHCN-Daily's flags (measurement, quality, source,
  comma-separated). A non-empty quality flag (the second) marks a value that
  failed a quality check: drop such values and say how many.
- Stations move, change instruments and have gaps; check `mindate`,
  `maxdate` and `datacoverage` with `stations` and report missing days per
  year before computing trends.
- A day missing from the rows is a day without a report, not a zero.
- Precipitation is the 24 hours ending at the station's observation time,
  which differs between stations.

## What a load records

Every load that returns rows is recorded in the study's `data_sources.json`:
the terms, the citation with the subset and access date, the request as made,
every page's URL (without the token) and SHA-256, and when it ran. A table
also gets its entry in `data_dictionary.json`. A missing token, a refused
request or an empty result exits non-zero and leaves data.db unchanged.
Report the error; do not build the table another way.
