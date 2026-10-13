# NASA Exoplanet Archive via `e2er-data exoplanets`

The NASA Exoplanet Archive (NASA Exoplanet Science Institute, IPAC/Caltech)
lists every confirmed exoplanet (6,445 in the composite table in October
2026) with its orbit, size, mass and host star, compiled from the refereed
literature. e2er queries its TAP service with ADQL. No key is needed.

Use it for radius–period and mass–radius distributions, discovery-method and
facility selection effects over time, planet properties by host-star type
(temperature, metallicity, mass), multiplicity (planets per system) and
distances of known systems.

## Two tables, two meanings

- `pscomppars` (default, "Planetary Systems Composite Parameters"): one row
  per planet. Each column holds the archive's preferred value, and values can
  come from different papers for the same planet (the `*_reflink` columns
  name them). Most complete; best for population counts. Not internally
  consistent: a planet radius from one paper and a stellar radius from
  another.
- `ps` ("Planetary Systems"): one row per planet **and published solution**.
  `--catalogue ps` keeps one solution per planet (`default_flag = 1`, a
  self-consistent set from one paper, named in `pl_refname`);
  `--all-solutions` returns every solution (several rows per planet: never
  count planets from it).

Say in `data_summary.md` which table the study uses and why.

## Terms of use

- Free and keyless; the archive's pages state no licence.
- NASA asks for its standard acknowledgement in any published material:
  "This research has made use of the NASA Exoplanet Archive, which is operated
  by the California Institute of Technology, under contract with the National
  Aeronautics and Space Administration under the Exoplanet Exploration
  Program." Put it in the paper's acknowledgements.
- Cite the archive paper (Christiansen et al. 2025, The Planetary Science
  Journal 6, 186) and the table's DOI: 10.26133/NEA13 (`pscomppars`) or
  10.26133/NEA12 (`ps`).
- "If you use data from a specific literature reference, please acknowledge
  that reference directly": a study that leans on a few planets' values cites
  the papers behind them (`pl_refname`, `*_reflink`).
- Full terms: https://exoplanetarchive.ipac.caltech.edu/docs/acknowledge.html
- A study may publish the rows it loaded.

The first load adds three BibTeX entries to the study's literature.bib:
`Christiansen2025_NEA` (the archive paper), `NEA_PSCompPars` and `NEA_PS`
(the table DOIs). Cite `\cite{Christiansen2025_NEA}` and the table's key
wherever the paper uses the data.

## Subcommands

```
e2er-data exoplanets planets --table planets
e2er-data exoplanets planets --since 2010 --method Transit \
    --columns pl_name,hostname,pl_rade,pl_orbper,st_teff,disc_year --where "pl_rade is not null" \
    --table transiting
e2er-data exoplanets planets --catalogue ps --columns pl_name,pl_rade,pl_bmasse,pl_bmassprov,pl_refname \
    --where "pl_bmasse is not null and pl_rade is not null" --table mass_radius
e2er-data exoplanets query --adql "select disc_year, discoverymethod, count(*) as n \
    from pscomppars group by disc_year, discoverymethod" --table discoveries
```

`planets` options:

- `--catalogue pscomppars|ps` (default `pscomppars`).
- `--columns`: comma-separated column names. Default: `pl_name, hostname,
  sy_snum, sy_pnum, discoverymethod, disc_year, disc_facility, pl_orbper,
  pl_orbsmax, pl_rade, pl_bmasse, pl_orbeccen, pl_eqt, st_teff, st_rad,
  st_mass, st_met, sy_dist, ra, dec`. All columns:
  https://exoplanetarchive.ipac.caltech.edu/docs/API_PS_columns.html
- `--since`, `--until`: discovery years (included).
- `--method`: discovery method, as the archive writes it: `Transit`,
  `Radial Velocity`, `Microlensing`, `Imaging`, `Transit Timing Variations`,
  `Astrometry`, … (case-sensitive).
- `--where`: one more ADQL condition, e.g. `"pl_rade < 4 and sy_dist < 100"`.
- `--all-solutions` (with `--catalogue ps`): every published solution.
- `--max-rows` (default 100,000): the load stops, rather than saving a cut
  table, when the query returns more rows.
- `--table NAME` loads the rows into data.db as the table declared in
  data_dictionary.json; `--save-to FILE.csv` also writes them under data/.

`query`: one ADQL `SELECT` (`--adql`) on any table of the archive's TAP
service (`ps`, `pscomppars`, `stellarhosts`, `toi` for TESS candidates,
`k2pandc`, `keplernames`, …), with the same `--max-rows`. Use it for
aggregates and joins the `planets` options cannot express.

Rows come back sorted by `pl_name` (`planets`) or as the query orders them.

## Units and pitfalls

- Units: `pl_orbper` days, `pl_orbsmax` au, `pl_rade` Earth radii,
  `pl_bmasse` Earth masses (`pl_bmassj` Jupiter masses), `pl_insol` Earth
  flux, `pl_eqt` K, `st_teff` K, `st_rad` and `st_mass` solar units, `st_met`
  dex, `sy_dist` pc, `ra`/`dec` degrees.
- `pl_bmasse` is the "best" mass: a true mass, M·sin(i) from radial
  velocities, or a mass from a mass–radius relation; `pl_bmassprov` says
  which. Do not mix them silently in a mass–radius study.
- Columns ending in `err1`/`err2` are upper/lower uncertainties; `*lim`
  columns flag upper or lower limits (1/−1): drop or treat those rows before
  averaging.
- An empty cell is a value no paper reported (not zero). Radii are mostly
  known for transiting planets, masses mostly for radial-velocity planets: a
  sample with both is not representative of all planets.
- Discovery methods have strong selection effects (transits favour short
  periods and large planets; radial velocities favour massive planets;
  imaging favours wide, young, massive ones). A raw histogram is not the true
  population; say what the sample can and cannot show.
- The archive has no releases: planets are added and values revised as papers
  appear. Each load records when it ran, the ADQL and the SHA-256 of the CSV;
  a later load can differ.

## What a load records

Every load that returns rows is recorded in the study's `data_sources.json`:
the terms, the citation, the request as made, the ADQL, the TAP URL, the
table's DOI, the SHA-256 of the CSV read and when it ran. A table also gets
its entry in `data_dictionary.json`. A query the archive refuses (an unknown
column, a syntax error), a query with no rows, or one above `--max-rows`
exits non-zero, with the archive's message, and leaves data.db unchanged.
Report the error; do not build the table another way.
