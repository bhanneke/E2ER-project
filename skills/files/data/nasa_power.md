# NASA POWER via `e2er-data nasa_power`

NASA's Prediction Of Worldwide Energy Resources (POWER) project, at NASA
Langley Research Center, serves daily, monthly and annual weather and solar
parameters for any place on Earth since 1981. The values are grid-cell
estimates from NASA's MERRA-2 reanalysis (temperature, precipitation,
humidity, wind, pressure) and CERES satellite products (solar radiation), not
station measurements. No key is needed.

Use it for temperature or precipitation trends at a place or across a region,
weather or climate controls in a panel (match each unit's location and
period), heat or frost days, growing conditions, and solar or wind resource
studies.

## Terms of use

- Free and keyless. POWER states no licence; NASA's Earth science data use
  guidance says data from NASA-led missions without a marked restriction "are
  licensed as Creative Commons Zero (CC0)" and "there are no restrictions on
  the use of these data"
  (https://www.earthdata.nasa.gov/engage/open-data-services-software-policies/data-use-guidance).
- POWER's referencing guide (https://power.larc.nasa.gov/docs/referencing/)
  asks every publication to give both its reference ("The data was obtained
  from National Aeronautics and Space Administration (NASA) Langley Research
  Center's Prediction Of Worldwide Energy Resources (POWER) project funded
  through the NASA Earth Science Division.") and its data reference (the API,
  version and date accessed). Each load's citation in `data_sources.json`
  names them ("The data was obtained from the POWER Daily API version 2.10.0
  on 2026/10/11."): quote it in the paper's data section.
- POWER asks to be told about publications and when its data are passed to
  other researchers (larc-power-project@mail.nasa.gov); mention it to the
  researcher in `data_summary.md`, e2er sends nothing.
- A study may publish the data it loaded.

The first load adds the BibTeX entry `NASA_POWER` to the study's
literature.bib; cite it (`\cite{NASA_POWER}`) wherever the paper uses the data.

## Subcommands

```
e2er-data nasa_power parameters --search temperature
e2er-data nasa_power point --lat 50.11 --lon 8.68 --parameters T2M,T2M_MAX,T2M_MIN,PRECTOTCORR \
    --start 2000-01-01 --end 2024-12-31 --table frankfurt_daily
e2er-data nasa_power point --lat 50.11 --lon 8.68 --parameters T2M --temporal annual \
    --start 1981 --end 2024 --table frankfurt_annual
e2er-data nasa_power regional --bbox 5,47,15,55 --parameters T2M --temporal monthly \
    --start 2000 --end 2024 --table germany_t2m
```

`parameters` lists POWER's parameter codes with names, units and definitions
(`--search` filters; `--community` changes the units shown). It loads
nothing.

`point` options:

- `--lat`, `--lon` (required): degrees (−90 to 90, −180 to 180).
- `--parameters` (required): up to 20 codes, comma-separated.
- `--start`, `--end` (required, both included): days (`YYYY-MM-DD`) for daily
  data; years (`YYYY`) for monthly and annual data.
- `--temporal daily|monthly|annual` (default daily). Daily data run to a few
  days before today; monthly and annual data to the previous year.
- `--community RE|AG|SB` (default RE): POWER's user communities. It changes
  the units of some parameters: solar radiation (`ALLSKY_SFC_SW_DWN`) is
  kWh/m²/day under RE and SB, MJ/m²/day under AG. Keep one community per
  study.
- `--time-standard LST|UTC` (daily only): POWER's days are local solar time
  by default.
- `--table NAME` loads the rows into data.db as the table declared in
  data_dictionary.json; `--save-to FILE.csv` also writes them under data/.

Rows: daily `lat, lon, elevation_m, date (YYYY-MM-DD)` and one column per
parameter; monthly `year, month, date (YYYY-MM)`; annual `year` (POWER's
annual value).

`regional`: one parameter on POWER's grid inside `--bbox
west,south,east,north` (each side 2 to 10 degrees), with the same `--start`,
`--end`, `--temporal`, `--community`. One row per grid cell and day, month or
year, with the cell's `lat` and `lon`. The MERRA-2 grid is 0.5° in latitude
by 0.625° in longitude; a larger area takes several loads (one per box).

Commonly used parameters (check units with `parameters`):

| Code | What | Unit |
|---|---|---|
| `T2M`, `T2M_MAX`, `T2M_MIN` | air temperature at 2 m: mean, and the highest and lowest hourly value in the day, month or year | °C |
| `PRECTOTCORR` | precipitation (bias-corrected) | mm/day |
| `RH2M` | relative humidity at 2 m | % |
| `WS2M`, `WS10M` | wind speed at 2 m, 10 m | m/s |
| `PS` | surface pressure | kPa |
| `ALLSKY_SFC_SW_DWN` | solar radiation at the surface | kWh/m²/day (RE) |

## Pitfalls

- Values are modelled grid-cell means, not station records: they smooth
  extremes, mountains and coasts. Say so in the paper; compare with a station
  where the question depends on local extremes.
- Monthly precipitation is a mean daily rate (mm/day), not a monthly total:
  multiply by the days of the month for a total.
- Missing values (POWER's fill value −999) are empty cells, never −999.
- POWER revises data with new versions; each load records the API version
  (`version`, e.g. v2.10.0), the data sources the response names and when it
  ran.
- POWER answers HTTP 429 when asked too often and may block an application
  that keeps requesting the same location: load each place once, for the
  whole period, and reuse the table.

## What a load records

Every load that returns rows is recorded in the study's `data_sources.json`:
the terms, the citation with the API version and access date, the request as
made, the request URL, the API version, community, time standard, units and
names of every parameter, the data sources (MERRA2, SYN1DEG), the SHA-256 of
the JSON read and when it ran. A table also gets its entry in
`data_dictionary.json`. A request POWER refuses (an unknown parameter, a
region outside 2–10 degrees) exits non-zero with POWER's message and leaves
data.db unchanged. Report the error; do not build the table another way.
