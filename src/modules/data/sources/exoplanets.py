"""NASA Exoplanet Archive: confirmed exoplanets and their host stars, through the archive's TAP service.

- Service: https://exoplanetarchive.ipac.caltech.edu/TAP (keyless, ADQL, CSV).
  Two tables answer most questions: ``pscomppars`` (Planetary Systems
  Composite Parameters, one row per planet, the archive's best value of each
  parameter drawn from several papers) and ``ps`` (Planetary Systems, one row
  per planet and published solution; ``default_flag = 1`` keeps one solution
  per planet, a self-consistent set from one paper).
- Terms (checked 2026-10-11): the acknowledgement page
  (https://exoplanetarchive.ipac.caltech.edu/docs/acknowledge.html) asks for a
  standard acknowledgement in "any published material that makes use of the
  NASA Exoplanet Archive's services", for the archive paper (Christiansen et
  al. 2025) and for the literature reference of any value used; the TAP page
  asks to "cite the archive's DOI for the data" (10.26133/NEA12 for ``ps``,
  10.26133/NEA13 for ``pscomppars``). The archive's pages state no licence; the
  tables are values published in the refereed literature, compiled by a
  NASA-funded archive. A study may pass on the rows it loaded, with the
  acknowledgement and the citations.
- The archive has no releases: rows are added and revised as papers appear.
  Each load records the ADQL query, the table's DOI, the SHA-256 of the CSV read
  and when it ran.
"""

from __future__ import annotations

import re
from typing import Any

from .base import Arg, Context, Doctor, Fetched, FetchError, Operation, Polite, Source

SERVICE = "https://exoplanetarchive.ipac.caltech.edu/TAP"
#: The most rows one load returns unless --max-rows says otherwise (the whole ps table is ~40,000 rows).
DEFAULT_CAP = 100_000
MAX_CAP = 500_000

ACKNOWLEDGEMENT = (
    "This research has made use of the NASA Exoplanet Archive, which is operated by the California Institute "
    "of Technology, under contract with the National Aeronautics and Space Administration under the Exoplanet "
    "Exploration Program."
)
CITE_KEY = "Christiansen2025_NEA"
PAPER = (
    "Christiansen, J. L., McElroy, D. L., Harbut, M., et al. (2025). The NASA Exoplanet Archive and Exoplanet "
    "Follow-up Observing Program: Data, Tools, and Usage. The Planetary Science Journal, 6(8), 186. "
    "https://doi.org/10.3847/PSJ/ade3c2"
)
#: The tables' dataset DOIs (https://exoplanetarchive.ipac.caltech.edu/docs/doi.html, DataCite).
TABLES = {
    "pscomppars": ("Planetary Systems Composite Table", "10.26133/NEA13"),
    "ps": ("Planetary Systems Table", "10.26133/NEA12"),
}
CITATION = (
    PAPER + ". Data: NASA Exoplanet Science Institute (2020), Planetary Systems Composite Table, IPAC, "
    "https://doi.org/10.26133/NEA13, or Planetary Systems Table, https://doi.org/10.26133/NEA12. "
    "Acknowledgement: " + ACKNOWLEDGEMENT
)
#: The paper from its DOI's metadata (Crossref), shortened author list; the two table DOIs from DataCite.
BIBTEX = """@article{Christiansen2025_NEA,
  author    = {Christiansen, Jessie L. and McElroy, Douglas L. and Harbut, Marcy and Ciardi, David R. and
               Crane, Megan and Good, John and Hardegree-Ullman, Kevin K. and Kesseli, Aurora Y. and
               Lund, Michael B. and Lynn, Meca and others},
  title     = {The {NASA} Exoplanet Archive and Exoplanet Follow-up Observing Program: Data, Tools, and Usage},
  journal   = {The Planetary Science Journal},
  volume    = {6},
  number    = {8},
  pages     = {186},
  year      = {2025},
  publisher = {American Astronomical Society},
  doi       = {10.3847/PSJ/ade3c2}
}

@misc{NEA_PSCompPars,
  author    = {{NASA Exoplanet Science Institute}},
  title     = {Planetary Systems Composite Table},
  publisher = {IPAC},
  year      = {2020},
  doi       = {10.26133/NEA13},
  url       = {https://doi.org/10.26133/NEA13}
}

@misc{NEA_PS,
  author    = {{NASA Exoplanet Science Institute}},
  title     = {Planetary Systems Table},
  publisher = {IPAC},
  year      = {2020},
  doi       = {10.26133/NEA12},
  url       = {https://doi.org/10.26133/NEA12}
}"""

#: The columns a planets load returns unless --columns names others.
DEFAULT_COLUMNS = (
    "pl_name",
    "hostname",
    "sy_snum",
    "sy_pnum",
    "discoverymethod",
    "disc_year",
    "disc_facility",
    "pl_orbper",
    "pl_orbsmax",
    "pl_rade",
    "pl_bmasse",
    "pl_orbeccen",
    "pl_eqt",
    "st_teff",
    "st_rad",
    "st_mass",
    "st_met",
    "sy_dist",
    "ra",
    "dec",
)
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _columns(params: dict[str, Any]) -> list[str]:
    cols = params.get("columns") or list(DEFAULT_COLUMNS)
    bad = [c for c in cols if not _IDENT.match(c)]
    if bad:
        raise FetchError(f"--columns: {', '.join(bad)} are not column names (letters, digits, _)")
    return cols


def _cap(params: dict[str, Any]) -> int:
    raw = params.get("max_rows")
    cap = int(raw) if raw is not None else DEFAULT_CAP
    if not 1 <= cap <= MAX_CAP:
        raise FetchError(f"--max-rows must be between 1 and {MAX_CAP:,}")
    return cap


def _fetched(df: Any, adql: str, url: str, sha: str, table: str | None, series: str) -> Fetched:
    record: dict[str, Any] = {"adql": adql}
    if table in TABLES:
        record["table_doi"] = TABLES[table][1]
    return Fetched(
        rows=df,
        series=series,
        query=url,
        files=[{"url": url, "sha256": sha}],
        link="https://exoplanetarchive.ipac.caltech.edu/",
        record=record,
        note=(
            "Units follow the archive's column definitions "
            "(https://exoplanetarchive.ipac.caltech.edu/docs/API_PS_columns.html): pl_orbper days, pl_orbsmax au, "
            "pl_rade Earth radii, pl_bmasse Earth masses, pl_eqt K, st_teff K, st_rad solar radii, st_mass solar "
            "masses, st_met dex, sy_dist pc, ra/dec degrees. Empty cells are values no paper reported."
        ),
    )


async def fetch_planets(ctx: Context, params: dict[str, Any]) -> Fetched:
    from .adapters import tap_capped

    table = (params.get("catalogue") or "pscomppars").lower()
    if table not in TABLES:
        raise FetchError(f"--catalogue must be one of {', '.join(TABLES)}")
    cols = _columns(params)
    where = []
    if table == "ps" and not params.get("all_solutions"):
        where.append("default_flag = 1")
    if params.get("since") is not None:
        where.append(f"disc_year >= {int(params['since'])}")
    if params.get("until") is not None:
        where.append(f"disc_year <= {int(params['until'])}")
    if params.get("method"):
        method = str(params["method"]).replace("'", "''")
        where.append(f"discoverymethod = '{method}'")
    if params.get("where"):
        cond = " ".join(str(params["where"]).split())
        if ";" in cond:
            raise FetchError("--where must be one ADQL condition (no ';')")
        where.append(f"({cond})")
    adql = f"select {', '.join(cols)} from {table}"
    if where:
        adql += " where " + " and ".join(where)
    adql += " order by pl_name"
    df, url, sha = await tap_capped(ctx.http, SERVICE, adql, _cap(params))
    if df.empty:
        raise FetchError(f"no planets match ({adql}); loosen --where, --since, --until or --method")
    title = TABLES[table][0]
    series = f"confirmed exoplanets, NASA Exoplanet Archive {title} ({table})" + (
        f" where {' and '.join(where)}" if where else ""
    )
    return _fetched(df, adql, url, sha, table, series)


async def fetch_query(ctx: Context, params: dict[str, Any]) -> Fetched:
    from .adapters import adql_select_only, tap_capped

    adql = adql_select_only(params["adql"])
    df, url, sha = await tap_capped(ctx.http, SERVICE, adql, _cap(params))
    if df.empty:
        raise FetchError(f"the query returned no rows ({adql})")
    m = re.search(r"\bfrom\s+([A-Za-z_][\w.]*)", adql, re.I)
    table = m.group(1).lower() if m else None
    return _fetched(df, adql, url, sha, table, f"NASA Exoplanet Archive ADQL query: {adql}")


SOURCE = Source(
    name="exoplanets",
    label="NASA Exoplanet Archive",
    dataset="NASA Exoplanet Archive (NASA Exoplanet Science Institute, IPAC/Caltech): Planetary Systems tables",
    website="https://exoplanetarchive.ipac.caltech.edu/",
    terms_url="https://exoplanetarchive.ipac.caltech.edu/docs/acknowledge.html",
    terms_summary=(
        "Free and keyless. NASA asks for its standard acknowledgement and a citation of the archive paper "
        "(Christiansen et al. 2025) and the table's DOI, plus the literature reference of any value used. "
        "The archive states no licence."
    ),
    terms_plain=(
        "Free and keyless; no licence is stated on the archive's pages.",
        "Acknowledge the archive with NASA's standard sentence and cite Christiansen et al. (2025).",
        "Cite the table's DOI (10.26133/NEA13 for pscomppars, 10.26133/NEA12 for ps).",
        "Cite the paper behind any single planet's values you rely on (the *_reflink columns).",
    ),
    licence=(
        "No licence stated. The acknowledgement page "
        '(https://exoplanetarchive.ipac.caltech.edu/docs/acknowledge.html) asks: "Please include the following '
        "standard acknowledgment in any published material that makes use of the NASA Exoplanet Archive's "
        f'services. {ACKNOWLEDGEMENT}" and "if you use data from a specific literature reference, please '
        'acknowledge that reference directly", and to "cite Christiansen et al. (2025)". The TAP page '
        '(https://exoplanetarchive.ipac.caltech.edu/docs/TAP/usingTAP.html) asks: "If you use any of the '
        "following data sets for your research, please cite the archive's DOI for the data.\""
    ),
    citation=CITATION,
    citation_by="source",
    bibtex=BIBTEX,
    cite_key=CITE_KEY,
    use=(
        "Confirmed exoplanets (more than 6,000) with orbital period, radius, mass, equilibrium temperature, "
        "discovery method/year/facility and host-star properties (temperature, radius, mass, metallicity, "
        "distance), from the NASA Exoplanet Archive. Good for radius–period and mass–radius distributions, "
        "discovery-method selection effects, planet properties by host-star type. Keyless; ADQL queries for "
        "anything else."
    ),
    coverage="Confirmed exoplanets and host stars (Planetary Systems tables), via TAP/ADQL. Keyless.",
    help="NASA Exoplanet Archive: confirmed exoplanets and host stars (TAP/ADQL). No key.",
    operations=(
        Operation(
            "planets",
            "Confirmed planets, one row each, e.g. --since 2014 --method Transit "
            "--columns pl_name,pl_rade,pl_orbper --where 'pl_rade < 4'.",
            args=(
                Arg(
                    "catalogue",
                    "pscomppars (default: one row per planet, best value of each parameter) or ps "
                    "(one published solution per planet, default_flag = 1).",
                    choices=("pscomppars", "ps"),
                ),
                Arg("columns", "Comma-separated column names (default: name, host, orbit, size, star).", type="list"),
                Arg("since", "First discovery year.", type=int),
                Arg("until", "Last discovery year.", type=int),
                Arg("method", "Discovery method, e.g. Transit, 'Radial Velocity', Imaging, Microlensing."),
                Arg("where", 'An extra ADQL condition, e.g. "pl_rade < 4 and sy_dist < 100".'),
                Arg("all-solutions", "With --catalogue ps: every published solution, not one per planet.", type="flag"),
                Arg(
                    "max-rows",
                    f"Stop instead of cutting the table above this many rows (default {DEFAULT_CAP:,}).",
                    type=int,
                ),
            ),
            fetch=fetch_planets,
            card=(
                "Confirmed exoplanets → one row per planet. Params: catalogue ('pscomppars' default | 'ps'), "
                "columns (list), since, until (discovery years), method (discovery method), where (ADQL "
                "condition), all_solutions, max_rows."
            ),
        ),
        Operation(
            "query",
            "Any ADQL SELECT on the archive's TAP tables (ps, pscomppars, stellarhosts, toi, k2pandc, …), "
            'e.g. --adql "select hostname, count(*) as n from pscomppars group by hostname".',
            args=(
                Arg("adql", "One ADQL SELECT query.", required=True),
                Arg(
                    "max-rows",
                    f"Stop instead of cutting the table above this many rows (default {DEFAULT_CAP:,}).",
                    type=int,
                ),
            ),
            fetch=fetch_query,
            card="An ADQL SELECT on the archive's TAP tables → its rows. Params: adql (required), max_rows.",
        ),
    ),
    # The archive publishes no rate limit; one query per second keeps a study's loads light.
    polite=Polite(min_interval=1.0, timeout=180.0, max_requests=10),
    aliases=(
        "nasa_exoplanet_archive",
        "exoplanet_archive",
        "nasa_exoplanets",
        "exoplanetarchive",
        "pscomppars",
    ),
    skill="data/exoplanets",
    doctor=Doctor(
        "data.exoplanets.planets",
        operation="planets",
        params={"columns": "pl_name,pl_rade,pl_orbper", "where": "pl_name = 'Kepler-22 b'"},
    ),
)
