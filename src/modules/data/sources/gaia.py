"""ESA Gaia: positions, parallaxes, proper motions and photometry of stars, from the Gaia archive's TAP service.

- Service: https://gea.esac.esa.int/tap-server/tap (keyless, ADQL, CSV). The
  main table is ``gaiadr3.gaia_source`` (Gaia Data Release 3, 1.8 billion
  sources). Anonymous users get (https://www.cosmos.esa.int/web/gaia-users/archive/collaborate,
  "Gaia archive user quotas", checked 2026-10-11): a synchronous query
  time-out of 10 s and at most 50,000 rows per query. e2er queries
  synchronously and never cuts a table silently: a load that would return
  more rows than its cap stops and says how to narrow it.
- Terms (https://www.cosmos.esa.int/web/gaia-users/license, checked
  2026-10-11): "Gaia data are distributed under the CC BY-NC 3.0 IGO license."
  The ESA archives' terms (https://www.cosmos.esa.int/web/esdc/terms-and-conditions)
  make the data "open and free to use by the User subject to proper
  acknowledgment" (credit line "ESA, Gaia DPAC"), and ask for ESA's
  authorisation before any commercial use. Not share-alike. e2er treats the
  data as restricted (``redistribution=False``): a published study states the
  non-commercial terms on every file holding Gaia rows, a Zenodo deposit takes
  a non-commercial licence, and get_data.py loads the rows again from the
  archive (DR3 is a fixed release, so the reload returns the same rows).
- Citation (https://gea.esac.esa.int/archive/documentation/GDR3/Miscellaneous/sec_credit_and_citation_instructions/):
  "please cite both the Gaia mission paper and the Gaia DR3 release paper":
  Gaia Collaboration, Prusti et al. (2016), A&A 595, A1, and Gaia
  Collaboration, Vallenari et al. (2023), A&A 674, A1; plus the acknowledgement.
"""

from __future__ import annotations

import re
from typing import Any

from .base import Arg, Context, Doctor, Fetched, FetchError, Operation, Polite, Restricted, Source

SERVICE = "https://gea.esac.esa.int/tap-server/tap"
#: The archive's limit on the rows one anonymous query returns.
ANON_MAX_ROWS = 50_000
#: The largest cone e2er asks for in one load (degrees); a wider one times out or overflows anonymously.
MAX_RADIUS = 5.0

ACKNOWLEDGEMENT = (
    "This work has made use of data from the European Space Agency (ESA) mission Gaia "
    "(https://www.cosmos.esa.int/gaia), processed by the Gaia Data Processing and Analysis Consortium (DPAC, "
    "https://www.cosmos.esa.int/web/gaia/dpac/consortium). Funding for the DPAC has been provided by national "
    "institutions, in particular the institutions participating in the Gaia Multilateral Agreement."
)
CITE_KEY = "GaiaDR3_Vallenari2023"
CITATION = (
    "Gaia Collaboration, Vallenari, A., Brown, A. G. A., Prusti, T., et al. (2023). Gaia Data Release 3: Summary "
    "of the content and survey properties. Astronomy & Astrophysics, 674, A1. "
    "https://doi.org/10.1051/0004-6361/202243940; and Gaia Collaboration, Prusti, T., de Bruijne, J. H. J., "
    "Brown, A. G. A., et al. (2016). The Gaia mission. Astronomy & Astrophysics, 595, A1. "
    "https://doi.org/10.1051/0004-6361/201629272. Acknowledgement: " + ACKNOWLEDGEMENT
)
#: From the DOIs' metadata (Crossref), author lists shortened, with e2er's keys.
BIBTEX = """@article{GaiaDR3_Vallenari2023,
  author    = {{Gaia Collaboration} and Vallenari, A. and Brown, A. G. A. and Prusti, T. and
               de Bruijne, J. H. J. and Arenou, F. and others},
  title     = {{Gaia} Data Release 3: Summary of the content and survey properties},
  journal   = {Astronomy \\& Astrophysics},
  volume    = {674},
  pages     = {A1},
  year      = {2023},
  publisher = {EDP Sciences},
  doi       = {10.1051/0004-6361/202243940}
}

@article{GaiaMission_Prusti2016,
  author    = {{Gaia Collaboration} and Prusti, T. and de Bruijne, J. H. J. and Brown, A. G. A. and
               Vallenari, A. and Babusiaux, C. and others},
  title     = {The {Gaia} mission},
  journal   = {Astronomy \\& Astrophysics},
  volume    = {595},
  pages     = {A1},
  year      = {2016},
  publisher = {EDP Sciences},
  doi       = {10.1051/0004-6361/201629272}
}"""

#: The columns a cone load returns unless --columns names others.
DEFAULT_COLUMNS = (
    "source_id",
    "ra",
    "dec",
    "parallax",
    "parallax_error",
    "pmra",
    "pmdec",
    "phot_g_mean_mag",
    "phot_bp_mean_mag",
    "phot_rp_mean_mag",
    "bp_rp",
    "radial_velocity",
    "ruwe",
)
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_RELEASES = {"gaiadr3": "DR3", "gaiaedr3": "EDR3", "gaiadr2": "DR2", "gaiadr1": "DR1", "gaiafpr": "FPR"}


def _cap(params: dict[str, Any]) -> int:
    raw = params.get("max_rows")
    cap = int(raw) if raw is not None else ANON_MAX_ROWS
    if not 1 <= cap <= ANON_MAX_ROWS:
        raise FetchError(f"--max-rows must be between 1 and {ANON_MAX_ROWS:,} (the archive's anonymous limit)")
    # One more row than the cap is asked for to tell a full table from a cut one; the archive gives at most 50,000.
    return min(cap, ANON_MAX_ROWS - 1)


def _num(params: dict[str, Any], key: str, lo: float, hi: float, what: str) -> float:
    value = float(params[key])
    if not lo <= value <= hi:
        raise FetchError(f"--{key.replace('_', '-')} {value}: {what}")
    return value


def _release(adql: str) -> str | None:
    found = {
        _RELEASES[m.lower()] for m in re.findall(r"\b(gaia(?:e?dr\d|fpr))\.", adql, re.I) if m.lower() in _RELEASES
    }
    return ", ".join(sorted(found)) or None


def _fetched(df: Any, adql: str, url: str, sha: str, series: str, version: str | None) -> Fetched:
    return Fetched(
        rows=df,
        series=series,
        query=url,
        version=version,
        files=[{"url": url, "sha256": sha}],
        link="https://gea.esac.esa.int/archive/",
        record={"adql": adql},
        note=(
            "Units (gaia_source data model): ra, dec degrees (ICRS, epoch 2016.0); parallax and parallax_error mas; "
            "pmra (already times cos dec), pmdec mas/yr; phot_*_mean_mag and bp_rp Vega magnitudes; "
            "radial_velocity km/s; ruwe unitless (above 1.4 suggests a poor astrometric fit). "
            "Distance is not 1/parallax for noisy or negative parallaxes; see the skill file."
        ),
    )


async def fetch_cone(ctx: Context, params: dict[str, Any]) -> Fetched:
    from .adapters import tap_capped

    ra = _num(params, "ra", 0.0, 360.0, "right ascension must be within 0–360 degrees")
    dec = _num(params, "dec", -90.0, 90.0, "declination must be within ±90 degrees")
    radius = _num(params, "radius", 1e-6, MAX_RADIUS, f"the radius must be above 0 and at most {MAX_RADIUS} degrees")
    cols = params.get("columns") or list(DEFAULT_COLUMNS)
    bad = [c for c in cols if not _IDENT.match(c)]
    if bad:
        raise FetchError(f"--columns: {', '.join(bad)} are not column names (letters, digits, _)")
    where = [f"1 = CONTAINS(POINT('ICRS', ra, dec), CIRCLE('ICRS', {ra}, {dec}, {radius}))"]
    if params.get("max_mag") is not None:
        where.append(f"phot_g_mean_mag < {float(params['max_mag'])}")
    if params.get("min_parallax_over_error") is not None:
        where.append(f"parallax_over_error > {float(params['min_parallax_over_error'])}")
    adql = (
        f"SELECT {', '.join(cols)}, DISTANCE(POINT('ICRS', ra, dec), POINT('ICRS', {ra}, {dec})) AS dist_deg "
        f"FROM gaiadr3.gaia_source WHERE {' AND '.join(where)} ORDER BY source_id"
    )
    cap = _cap(params)
    try:
        df, url, sha = await tap_capped(ctx.http, SERVICE, adql, cap)
    except FetchError as e:
        if "the table would be cut" in str(e):
            raise FetchError(
                f"more than {cap:,} stars in this cone; set --max-mag (e.g. 15), a smaller --radius "
                "or --min-parallax-over-error to load them in one go"
            ) from None
        raise
    if df.empty:
        raise FetchError(f"no Gaia DR3 sources in this cone ({adql}); widen --radius or raise --max-mag")
    limits = ""
    if params.get("max_mag") is not None:
        limits += f", G < {params['max_mag']}"
    if params.get("min_parallax_over_error") is not None:
        limits += f", parallax_over_error > {params['min_parallax_over_error']}"
    series = f"Gaia DR3 sources within {radius} deg of RA {ra}, Dec {dec}{limits}"
    return _fetched(df, adql, url, sha, series, "DR3")


async def fetch_query(ctx: Context, params: dict[str, Any]) -> Fetched:
    from .adapters import adql_select_only, tap_capped

    adql = adql_select_only(params["adql"])
    df, url, sha = await tap_capped(ctx.http, SERVICE, adql, _cap(params))
    if df.empty:
        raise FetchError(f"the query returned no rows ({adql})")
    return _fetched(df, adql, url, sha, f"Gaia archive ADQL query: {adql}", _release(adql))


TERMS_SUMMARY = (
    "Gaia data are distributed under CC BY-NC 3.0 IGO: free to use with credit to ESA/Gaia/DPAC; "
    "commercial use needs ESA's authorisation. Cite the Gaia mission and DR3 papers."
)

SOURCE = Source(
    name="gaia",
    label="ESA Gaia Archive",
    dataset="Gaia Data Release 3 (ESA/Gaia/DPAC), Gaia ESA Archive",
    website="https://gea.esac.esa.int/archive/",
    terms_url="https://www.cosmos.esa.int/web/gaia-users/license",
    terms_summary=TERMS_SUMMARY,
    terms_plain=(
        "Gaia data are distributed under the CC BY-NC 3.0 IGO licence.",
        "Free to use with credit to ESA, Gaia DPAC (the acknowledgement sentence).",
        "Any commercial use needs ESA's authorisation first (data.licences@esa.int).",
        "Cite the Gaia mission paper (2016) and the Gaia DR3 summary paper (2023).",
    ),
    licence=(
        "CC BY-NC 3.0 IGO (https://creativecommons.org/licenses/by-nc/3.0/igo/). "
        'The Gaia licence page (https://www.cosmos.esa.int/web/gaia-users/license): "Gaia data are distributed '
        "under the CC BY-NC 3.0 IGO license.\" The ESA archives' terms "
        '(https://www.cosmos.esa.int/web/esdc/terms-and-conditions): data "are open and free to use by the User '
        'subject to proper acknowledgment to be given in accordance with the credit lines provided below" '
        '(Gaia: "Credit: ESA, Gaia DPAC"), and "Prior to any commercial use by the User of any Data or Data '
        "Product, including any use or application that directly or indirectly generates a financial gain, a "
        'detailed request for authorisation/licence shall be made". Acknowledgement: ' + ACKNOWLEDGEMENT
    ),
    citation=CITATION,
    citation_by="source",
    bibtex=BIBTEX,
    cite_key=CITE_KEY,
    use=(
        "Stars of the Milky Way from ESA's Gaia DR3 (1.8 billion sources): positions, parallaxes (distances), "
        "proper motions, G/BP/RP photometry and colours, radial velocities. Good for colour–magnitude "
        "(HR) diagrams, star clusters, stellar kinematics and the local stellar population. Keyless; at most "
        "50,000 rows per load (anonymous archive quota). Non-commercial licence (CC BY-NC 3.0 IGO)."
    ),
    coverage="Gaia DR3 stars: astrometry and photometry (cone search, ADQL). CC BY-NC 3.0 IGO.",
    help="ESA Gaia DR3: positions, parallaxes, proper motions, photometry of stars (TAP/ADQL). No key.",
    operations=(
        Operation(
            "cone",
            "Gaia DR3 sources around a point, e.g. --ra 56.75 --dec 24.12 --radius 1 --max-mag 15 (the Pleiades).",
            args=(
                Arg("ra", "Right ascension of the centre, degrees (ICRS).", type=float, required=True),
                Arg("dec", "Declination of the centre, degrees (ICRS).", type=float, required=True),
                Arg("radius", f"Cone radius in degrees (at most {MAX_RADIUS}).", type=float, required=True),
                Arg("max-mag", "Only sources brighter than this G magnitude, e.g. 15.", type=float),
                Arg(
                    "min-parallax-over-error",
                    "Only sources whose parallax is at least this many times its error, e.g. 5.",
                    type=float,
                ),
                Arg(
                    "columns", "Comma-separated gaia_source columns (default: astrometry and photometry).", type="list"
                ),
                Arg(
                    "max-rows",
                    f"Stop instead of cutting the table above this many rows (at most {ANON_MAX_ROWS:,}).",
                    type=int,
                ),
            ),
            fetch=fetch_cone,
            card=(
                "Gaia DR3 stars in a cone → one row per source (with dist_deg from the centre). Params: ra, dec, "
                f"radius (degrees, ≤{MAX_RADIUS}; all required), max_mag (G), min_parallax_over_error, columns "
                "(list), max_rows (≤50,000)."
            ),
        ),
        Operation(
            "query",
            "Any ADQL SELECT on the Gaia archive (gaiadr3.gaia_source, gaiadr3.astrophysical_parameters, …), "
            'e.g. --adql "SELECT TOP 1000 source_id, bp_rp, phot_g_mean_mag FROM gaiadr3.gaia_source WHERE '
            'parallax > 50".',
            args=(
                Arg("adql", "One ADQL SELECT query (the archive stops anonymous queries after 10 s).", required=True),
                Arg(
                    "max-rows",
                    f"Stop instead of cutting the table above this many rows (at most {ANON_MAX_ROWS:,}).",
                    type=int,
                ),
            ),
            fetch=fetch_query,
            card="An ADQL SELECT on the Gaia archive → its rows. Params: adql (required), max_rows (≤50,000).",
        ),
    ),
    redistribution=False,
    restricted=Restricted(
        short="Gaia",
        name="ESA Gaia Data Release 3",
        zenodo_licence="other-nc",
        limit="allow non-commercial use only (CC BY-NC 3.0 IGO)",
        limit_finish="allow non-commercial use only (CC BY-NC 3.0 IGO); commercial use needs ESA's authorisation",
        confirm="under CC BY-NC 3.0 IGO (non-commercial use, credit to ESA/Gaia/DPAC)",
        warn="Gaia's licence (CC BY-NC 3.0 IGO) rules out commercial use without ESA's authorisation.",
        article="",
    ),
    # The archive publishes quotas, no request rate; one query per second keeps a study's loads light.
    polite=Polite(min_interval=1.0, timeout=120.0, max_requests=10),
    aliases=("esa_gaia", "gaia_dr3", "gaiadr3", "gaia_archive", "gaia_esa_archive"),
    skill="data/gaia",
    doctor=Doctor(
        "data.gaia.cone",
        operation="cone",
        params={"ra": 56.75, "dec": 24.12, "radius": 0.1, "max_mag": 10, "columns": "source_id,phot_g_mean_mag"},
    ),
)
