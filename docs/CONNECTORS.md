# How to add a data source

A data source in e2er is one definition: a `Source` in
`src/modules/data/sources/<name>.py`. From it e2er builds everything else:

| From the definition | Where it shows |
|---|---|
| `e2er-data <name> <operation> …` with `--table` and `--save-to` | the specialists' command line (CLI backends) |
| the record of every load in `data_sources.json` (terms, citation, request, query, version, SHA-256 of the files read) | the study page's "Data used", the dossier |
| the table's entry in `data_dictionary.json` | the data contract, export |
| the BibTeX entry in the study's `literature.bib` | `paper/refs.bib` |
| the planning catalogue card and `fetch_data` method | `list_data_sources` / `fetch_data` (API backends) |
| the sources the data architect may declare, and their other names | the planning contract check |
| the commands the standalone check treats as loading data | the estimation's standalone check |
| the dashboard's names for the source and its doctor check | Preflight, Setup, study pages |
| a reachability check (one cheap request) | `e2er doctor`, Preflight |
| for a source whose data a study may not pass on: the terms gate on publish and a reload in `get_data.py` | `e2er publish`, `e2er reproduce` |
| the README's data source table and a skill stub | `scripts/gen_sources.py` |

## The definition

```python
from .base import Arg, Context, Doctor, Fetched, FetchError, Operation, Polite, Source

SOURCE = Source(
    name="usgs",                          # e2er-data usgs …, the `source` of a dictionary table
    label="USGS Earthquake Catalog",      # what the pages show
    dataset="ANSS Comprehensive Earthquake Catalog (ComCat), U.S. Geological Survey",
    website="https://earthquake.usgs.gov/earthquakes/search/",
    terms_url="https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits",
    terms_summary="USGS-authored or produced data are in the U.S. public domain; …",
    licence="U.S. public domain (…): \"USGS-authored or produced data …\"",
    citation="U.S. Geological Survey. (2017). Advanced National Seismic System (ANSS) …",
    citation_by="source",                 # "source": the source publishes it; "e2er": e2er suggests one
    bibtex=BIBTEX, cite_key="USGS_ComCat",
    use="Earthquakes worldwide from …",   # the planning catalogue's description
    coverage="Earthquakes worldwide (ANSS ComCat): time, place, depth, magnitude. Public domain.",
    operations=(
        Operation(
            "events",
            "Earthquakes in a period, e.g. --start 2024-01-01 --end 2024-02-01 --min-magnitude 4.5.",
            args=(
                Arg("start", "First day (YYYY-MM-DD).", required=True),
                Arg("end", "End (exclusive). Default: now."),
                Arg("min-magnitude", "Smallest magnitude, e.g. 2.5.", type=float),
                Arg("bbox", "Region: west,south,east,north in degrees."),
            ),
            fetch=fetch_events,
        ),
    ),
    polite=Polite(min_interval=0.5, max_requests=85),
    aliases=("comcat", "usgs_earthquakes"),
    skill="data/usgs",
    doctor=Doctor("data.usgs.events", operation="events",
                  params={"start": "2024-01-01", "end": "2024-01-02", "min_magnitude": 5}),
)
```

The fields, in plain words:

- **Terms.** `terms_url` is the source's own page; read it and quote it in
  `licence`. `terms_summary` is one or two sentences for a study page;
  `terms_plain` (optional) the terms one line each.
- **May a published study pass the data on?** `redistribution=True` (the
  default) when the terms allow it. Otherwise set `redistribution=False` and
  `restricted=Restricted(short=…, zenodo_licence=…)`: publishing then asks the
  researcher to confirm the terms (`--accept-data-terms <name>`), the
  description names the terms on every data file holding the data, a Zenodo
  deposit takes `zenodo_licence` (or is refused when it is None, with
  `no_zenodo_why`), and `get_data.py` loads the data again instead of
  shipping them. The reload command is built from the request each load
  records; give `reload=` only when it cannot be.
- **Citation.** `citation_by="source"` when the source publishes a citation
  (quote it, and take `bibtex` from it: a DOI's metadata gives one with
  `curl -LH "Accept: application/x-bibtex" https://doi.org/<doi>`); `"e2er"`
  when it publishes none. A load may give its own citation (`Fetched.citation`).
- **Key.** `key=Key(setting="noaa_token", env="NOAA_TOKEN", how_to_get="Get a
  free token at …")` for a source that needs one (`optional=True` when a key
  only raises the limits). Without the key the source is not offered to the
  data architect, and a load says how to get one. The key is read from
  Settings when it has the attribute, else from the environment; it is never
  printed.
- **Politeness.** `Polite(min_interval=…, retries=…, max_requests=…)`: the
  seconds between two requests, retries after HTTP 429/502/503/504 (honouring
  `Retry-After`), and the most requests one load may make. Every request names
  e2er in its User-Agent. Use the source's documented limits.
- **Operations.** One per subcommand. `loads=False` for a listing that helps
  choose (it prints rows but takes no `--table`, and nothing is recorded).
  Arguments: `type=str|int|float|"list"|"flag"`; `--min-magnitude` arrives as
  `params["min_magnitude"]`.

## The fetch function

```python
async def fetch_events(ctx: Context, params: dict) -> Fetched:
    q = {"minmagnitude": params.get("min_magnitude"), "format": "csv", "starttime": params["start"], …}
    content = await ctx.http.get_bytes(f"{SERVICE}/query", q)       # polite, retried, errors name URL + status
    return Fetched(
        rows=pd.read_csv(io.BytesIO(content)),                       # a DataFrame or a list of dicts
        series="earthquakes of magnitude 4.5 and above worldwide, 2024-01-01 to 2024-02-01",
        query=ctx.http.requests[-1],                                 # the request as sent
        files=[{"url": ctx.http.requests[-1], "sha256": sha256_bytes(content)}],
        version=None,                                                # the release, where there are releases
        frequency="event",
    )
```

Raise `FetchError("…")` with a message the specialist can act on ("raise
--min-magnitude or shorten the period"); any other exception is reported as
the load's error too, never raised into the specialist's loop. `ctx.key` is
the key (or None), `ctx.cache_dir` the source's cache folder.

## Adapters

`src/modules/data/sources/adapters.py` covers the common services, so most
fetch functions are a few lines:

- `rest_json_pages(http, url, params, items="results", paging="page"|"offset"|"next", …)`:
  a JSON API, page after page (World Bank, WHO GHO, GitHub, Gutendex).
- `tap_query(http, "https://exoplanetarchive.ipac.caltech.edu/TAP", adql)`: an
  IVOA TAP service queried with ADQL, as CSV (NASA Exoplanet Archive, Gaia,
  SDSS). A refused query raises FetchError with the service's message.
- `download_file(http, url, source, version="2026_09")` and
  `read_table(path, member=…)`: a CSV, TSV or ZIP file, cached by version under
  `~/.e2er/cache/<source>/<version>/` and re-hashed on every use (the GMD's way).
- `sdmx_data(http, base, flow, key, start=…, end=…)`: an SDMX 2.1 service as
  SDMX-CSV (Eurostat, OECD, IMF, ECB).

A TAP source, for example, needs only:

```python
async def fetch_planets(ctx, params):
    adql = f"select pl_name, pl_rade, pl_orbper from ps where default_flag = 1 and disc_year >= {params['since']}"
    df, url = await tap_query(ctx.http, "https://exoplanetarchive.ipac.caltech.edu/TAP", adql)
    return Fetched(rows=df, series=f"confirmed planets discovered since {params['since']}", query=adql)
```

## Registering it

1. Add the module's name to `_MODULES` in `src/modules/data/sources/__init__.py`
   (the order is the catalogue's order).
2. Run `python scripts/gen_sources.py`: it updates the README's table and
   writes `skills/files/data/<name>.md` as a stub from the definition (what
   the source is, its terms, its subcommands and arguments, what a load
   records). Edit the stub: say which series answer which questions, the
   source's pitfalls (coverage, revisions, units) and a worked call. The data
   architect and the data analyst read it (`SPECIALIST_SKILLS` adds every
   source's skill). Then run `python scripts/gen_specialist_manifest.py`.
3. A new key needs a `Settings` field only if it should be saved from the
   dashboard; the environment works without one.
4. Add a line under `[Unreleased]` in CHANGELOG.md.

## Tests

Tests never call a live service. Record the source's responses once and
replay them:

```python
from src.modules.data.sources.http import use_cassette

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "usgs_events_2024_01.json"

def test_events_load_a_table(ws, capsys):
    with use_cassette(FIXTURE):
        code = cli.main(["--paper-id", PID, "usgs", "events", "--start", "2024-01-01",
                         "--end", "2024-01-08", "--min-magnitude", "5", "--table", "quakes"])
    ...
```

The first run, with `E2ER_RECORD_FIXTURES=1`, makes the requests live and
writes them to the fixture; every run after replays them with no network and
no waiting. A request the fixture does not hold fails the test with its URL.
Keep recorded requests small (a week, a few series). Mock failures and edge
cases (the service's limits, refused requests) with `respx`, and switch off
the waiting between requests in those tests
(`monkeypatch.setattr("src.modules.data.sources.http.PACING", False)`).
`tests/data/contract/test_usgs_connector.py` is the pattern;
`tests/data/contract/test_connector_kit.py` checks that every source is wired
in everywhere and that the README lists it.

Before merging, make one live call within the source's limits
(`e2er-data <name> <operation> … --paper-id <a study>`) and run `e2er doctor`.

## Sources written before the kit

Yahoo Finance, FRED and the Global Macro Database keep their own fetching
(`yfinance_provider.py`, `fred_provider.py`, `gmd_provider.py`), `e2er-data`
handlers (`Operation(run=…)`), `fetch_data` fetchers (`Source(fetcher=…)`)
and doctor checks (`Doctor(run=…)`). Their definitions are the one place for
their subcommands' arguments, terms, labels, aliases, planning entry, terms
gate and reload. Allium stays outside the kit: its SQL warehouse has its own
guarded tool and approval flow.
