# USGS Earthquake Catalog via `e2er-data usgs`

The ANSS Comprehensive Earthquake Catalog (ComCat), served by the U.S.
Geological Survey's FDSN event web service
(https://earthquake.usgs.gov/fdsnws/event/1/), lists earthquakes worldwide:
time, latitude, longitude, depth, magnitude and magnitude type, location
uncertainties, the network that reported each event and its review status. No
key is needed.

Use it for frequency–magnitude (Gutenberg–Richter) studies, aftershock
sequences, seismicity rates of a region over time, and depth or magnitude
distributions. The catalogue reaches back to 1900, but small events are only
complete in recent decades and in densely monitored regions (California, Japan):
choose a minimum magnitude the catalogue records completely for the region
and period, and say which in `data_summary.md`.

## Terms of use

- USGS-authored or produced data are in the U.S. public domain; USGS asks that
  proper credit be given.
- Full terms: https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits
- A study may publish the data it loaded.

Cite: U.S. Geological Survey. (2017). Advanced National Seismic System (ANSS)
Comprehensive Catalog. U.S. Geological Survey.
https://doi.org/10.5066/F7MS3QZH. The first load adds the BibTeX entry
`USGS_ComCat` to the study's literature.bib; cite it (`\cite{USGS_ComCat}`)
wherever the paper uses the data.

## Subcommand

```
e2er-data usgs events --start 2024-01-01 --end 2024-02-01 --min-magnitude 4.5 \
    --table quakes --save-to quakes.csv
e2er-data usgs events --start 2020-01-01 --end 2025-01-01 --min-magnitude 2.5 \
    --bbox -125,32,-114,42 --table california_m25
```

`events` options:

- `--start` (required): first day (`YYYY-MM-DD`, or a UTC time `YYYY-MM-DDTHH:MM:SS`).
- `--end`: end of the period, same format. Default: now. Give it: a study
  that must be rerun needs a fixed period.
- `--min-magnitude`, `--max-magnitude`: the magnitude range.
- `--bbox west,south,east,north` in degrees, e.g. `-125,32,-114,42`
  (California). Default: worldwide.
- `--event-type earthquake` keeps earthquakes only; without it the catalogue
  also lists quarry blasts, explosions and other events.
- `--table NAME` loads the rows into data.db as the table declared in
  data_dictionary.json; `--save-to FILE.csv` also writes them under data/.

One row per event, in time order, with the catalogue's own columns: `time`
(UTC, ISO 8601), `latitude`, `longitude`, `depth` (km), `mag`, `magType`,
`nst`, `gap`, `dmin`, `rms`, `net`, `id`, `updated`, `place`, `type`,
`horizontalError`, `depthError`, `magError`, `magNst`, `status`
(`reviewed`/`automatic`), `locationSource`, `magSource`. Magnitudes of
different types (`mww`, `mb`, `ml`, `md`) are not on one scale; say how the
study treats them.

The service answers at most 20,000 events per request. A larger request is
split into time windows by their counts (at most 40 windows); beyond that the
load stops with a message: raise `--min-magnitude` or shorten the period.

## What a load records

Every load that returns rows is recorded in the study's `data_sources.json`:
the terms, the citation, the request as made, the query URL, the service
version, the SHA-256 of every CSV read and when it ran. A table also gets its
entry in `data_dictionary.json`. ComCat has no releases: events are revised as
they are reviewed (`updated`), so a later load of the same period can differ
slightly; the record says when the study's load ran.

A bad date or region, or a request the service refuses, exits non-zero; with
`--table`, so does a period without events, and data.db is left unchanged.
Report the error; do not build the table another way.
