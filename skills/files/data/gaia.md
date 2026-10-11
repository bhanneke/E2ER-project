# ESA Gaia Archive via `e2er-data gaia`

ESA's Gaia mission measured positions, parallaxes, proper motions and
brightness of about 1.8 billion stars; Data Release 3 (DR3) is served by the
Gaia ESA Archive through a TAP service queried with ADQL. e2er reads the main
table, `gaiadr3.gaia_source`, and any other archive table with `query`. No
key is needed.

Use it for colour–magnitude (Hertzsprung–Russell) diagrams, open and globular
clusters (members share parallax and proper motion), the local stellar
population within a distance, stellar kinematics, and nearby-star or
white-dwarf samples.

## Limits of anonymous access

The archive gives anonymous users (e2er queries without an account) a
synchronous query time-out of **10 seconds** and at most **50,000 rows** per
query (https://www.cosmos.esa.int/web/gaia-users/archive/collaborate, "Gaia
archive user quotas"). A load never saves a cut table: when a query would
return more rows than its cap, it stops and says so. Keep queries narrow:

- a cone of at most a few degrees, with `--max-mag` (G magnitude) in crowded
  fields (the Galactic plane, the bulge, the Magellanic Clouds);
- conditions on positions, `parallax`, `phot_g_mean_mag` or `source_id`
  rather than computed expressions over the whole sky;
- `SELECT TOP n … ORDER BY …` only when a sample is what the study wants,
  and say so in `data_summary.md`.

## Terms of use

- "Gaia data are distributed under the CC BY-NC 3.0 IGO license"
  (https://www.cosmos.esa.int/web/gaia-users/license): free to use and share
  for non-commercial purposes with credit to "ESA, Gaia DPAC"; any commercial
  use needs ESA's authorisation first (data.licences@esa.int,
  https://www.cosmos.esa.int/web/esdc/terms-and-conditions). Not share-alike.
- e2er handles Gaia rows as data under terms: publishing a study asks the
  researcher to confirm the non-commercial terms (`--accept-data-terms
  gaia`), names them on every data file holding Gaia rows, gives a Zenodo
  deposit a non-commercial licence, and the replication package loads the
  rows again from the archive (`get_data.py`). DR3 is a fixed release, so the
  reload returns the same rows.
- Put ESA's acknowledgement in the paper: "This work has made use of data from
  the European Space Agency (ESA) mission Gaia
  (https://www.cosmos.esa.int/gaia), processed by the Gaia Data Processing and
  Analysis Consortium (DPAC,
  https://www.cosmos.esa.int/web/gaia/dpac/consortium). Funding for the DPAC
  has been provided by national institutions, in particular the institutions
  participating in the Gaia Multilateral Agreement."
- ESA asks to cite both the Gaia mission paper (Gaia Collaboration, Prusti et
  al. 2016, A&A 595, A1) and the DR3 summary paper (Gaia Collaboration,
  Vallenari et al. 2023, A&A 674, A1). The first load adds both to the study's
  literature.bib, `GaiaDR3_Vallenari2023` and `GaiaMission_Prusti2016`; cite
  both wherever the paper uses Gaia data. Papers on specific DR3 products are
  listed at https://www.cosmos.esa.int/web/gaia/dr3-papers.

## Subcommands

```
e2er-data gaia cone --ra 56.75 --dec 24.12 --radius 1 --max-mag 15 --table pleiades
e2er-data gaia cone --ra 217.43 --dec -62.68 --radius 0.5 --min-parallax-over-error 10 --table proxima_field
e2er-data gaia query --adql "SELECT source_id, parallax, bp_rp, phot_g_mean_mag \
    FROM gaiadr3.gaia_source WHERE parallax > 50 AND parallax_over_error > 10" --table within_20pc
```

`cone` options:

- `--ra`, `--dec` (required): the centre, degrees (ICRS).
- `--radius` (required): degrees, at most 5.
- `--max-mag`: only sources brighter than this G magnitude.
- `--min-parallax-over-error`: only sources whose parallax is at least this
  many times its error (5–10 for usable distances).
- `--columns`: comma-separated `gaia_source` columns. Default: `source_id, ra,
  dec, parallax, parallax_error, pmra, pmdec, phot_g_mean_mag,
  phot_bp_mean_mag, phot_rp_mean_mag, bp_rp, radial_velocity, ruwe`. A
  `dist_deg` column (angular distance from the centre, degrees) is always
  added; rows are sorted by `source_id`. All columns:
  https://gea.esac.esa.int/archive/documentation/GDR3/Gaia_archive/chap_datamodel/sec_dm_main_source_catalogue/ssec_dm_gaia_source.html
- `--max-rows` (at most 50,000).
- `--table NAME` loads the rows into data.db as the table declared in
  data_dictionary.json; `--save-to FILE.csv` also writes them under data/.

`query`: one ADQL `SELECT` (`--adql`) on any archive table
(`gaiadr3.gaia_source`, `gaiadr3.astrophysical_parameters`,
`gaiadr3.vari_summary`, `external.gaiaedr3_distance` for the Bailer-Jones et
al. 2021 distances, …) with `--max-rows`. The load records the release the
query names (DR3, EDR3, DR2).

## Units and pitfalls

- Units: `ra`, `dec` degrees (epoch 2016.0); `parallax`, `parallax_error`
  milliarcseconds (mas); `pmra` (already multiplied by cos dec), `pmdec` mas
  per year; `phot_g_mean_mag`, `phot_bp_mean_mag`, `phot_rp_mean_mag`, `bp_rp`
  Vega magnitudes; `radial_velocity` km/s; `ruwe` unitless.
- **Distance is not 1/parallax** for noisy parallaxes: below
  `parallax_over_error` of about 5 the inverse is biased, and negative
  parallaxes are valid measurements. Cut on `parallax_over_error` and say so,
  or use the Bailer-Jones et al. (2021) distances
  (`external.gaiaedr3_distance`, `r_med_geo` in pc; cite that paper).
  Distance in parsecs = 1000 / parallax (mas) only for precise parallaxes.
- Absolute magnitude: `M_G = phot_g_mean_mag + 5·log10(parallax/1000) + 5`
  (parallax in mas), without extinction: dust dims and reddens distant stars
  in the Galactic plane.
- DR3 parallaxes carry a zero-point offset of a few hundredths of a mas that
  depends on magnitude, colour and position (Lindegren et al. 2021); it
  matters for distant stars, hardly for nearby clusters.
- `ruwe` above about 1.4 flags a poor single-star astrometric fit (binaries,
  crowding); a common quality cut is `ruwe < 1.4`.
- `radial_velocity` exists for bright stars only (about 33 million);
  `bp_rp` is missing for some faint or crowded sources.

## What a load records

Every load that returns rows is recorded in the study's `data_sources.json`:
the terms, the citation, the request as made, the ADQL, the TAP URL, the
release (DR3), the SHA-256 of the CSV read and when it ran. A table also gets
its entry in `data_dictionary.json`. A query the archive refuses (with its
message: an unknown column, a time-out), an empty result, or one above the row
cap exits non-zero and leaves data.db unchanged. Report the error; do not
build the table another way.
