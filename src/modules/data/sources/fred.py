"""FRED, Federal Reserve Bank of St. Louis: US and international macro series; free key.

A connector written before the kit: its fetching (fred_provider.py), its
``e2er-data`` handlers (cli.py) and its ``fetch_data`` fetcher (providers.py)
are its own. FRED's terms leave each series' status to its page, and FRED's
citation names the series (load_record.fred_load), so a study may publish the
data it loaded: no terms gate.
"""

from __future__ import annotations

from typing import Any

from .base import Arg, Doctor, Key, Operation, Source
from .legacy import cli_handler as _cli
from .legacy import doctor_check


def _fetcher(settings: Any) -> Any:
    from ..providers import FredFetcher

    return FredFetcher(settings.fred_api_key)


SOURCE = Source(
    name="fred",
    label="FRED",
    dataset="FRED, Federal Reserve Bank of St. Louis",
    website="https://fred.stlouisfed.org",
    terms_url="https://fred.stlouisfed.org/legal/",
    terms_summary=(
        "FRED's terms of use apply. Each series page states its copyright status: public domain (citation "
        "requested), copyrighted with citation required, or copyrighted with the owner's permission needed "
        "for any use beyond personal use."
    ),
    licence=(
        "FRED legal notices, information and terms of use (https://fred.stlouisfed.org/legal/). Copyright status "
        "is stated beneath each series on FRED: Public Domain: Citation Requested; Copyrighted: Citation Required; "
        "Copyrighted: Pre-approval Required. Before using data series owned by third parties for anything other "
        "than your own personal use, you must contact the data owner to obtain permission. Cite each series "
        "with the suggested citation on its Cite tab."
    ),
    # Each load carries the citation on its series' Cite tab (load_record.fred_citation).
    citation="",
    citation_by="source",
    use=(
        "US macroeconomic time series — GDP, CPI/inflation, interest rates, "
        "employment, money supply, etc. Good for macro controls and conditioning variables."
    ),
    coverage="US and international macroeconomic series",
    help="Federal Reserve Economic Data (CPI, unemployment, rates, GDP, …). Free key.",
    key=Key(
        setting="fred_api_key",
        env="FRED_API_KEY",
        how_to_get="Get a free key (~30s) at https://fredaccount.stlouisfed.org/apikey",
    ),
    operations=(
        Operation(
            "series",
            "Pull a FRED time series. e.g. CPIAUCSL (CPI), UNRATE (unemployment), DGS10 (10y yield).",
            args=(
                Arg("series-id", "FRED series id, e.g. CPIAUCSL.", required=True, dest="series_id"),
                Arg("start", "Observation start date (YYYY-MM-DD)."),
                Arg("end", "Observation end date (YYYY-MM-DD)."),
                Arg("frequency", "Resample frequency: d, w, m, q, sa, a. Omit to use the series' native frequency."),
                Arg(
                    "units",
                    "Transformation: lin (raw, default), chg (level change), ch1 (yoy change), pch (%% change), log.",
                ),
                Arg("limit", "Max observations (default 100000 = FRED's max).", type=int, default=100000),
            ),
            run=_cli("_run_fred_series"),
        ),
        Operation(
            "series-info",
            "Metadata for a series: title, units, frequency. Use BEFORE pulling observations to sanity-check.",
            args=(Arg("series-id", "", required=True, dest="series_id"),),
            loads=False,
            run=_cli("_run_fred_series_info"),
        ),
        Operation(
            "search",
            "Free-text search across FRED series titles + notes. Returns up to --limit hits.",
            args=(
                Arg("query", "Search text, e.g. 'core CPI' or 'unemployment'.", required=True),
                Arg("limit", "Max hits (default 20).", type=int, default=20),
                Arg(
                    "order-by",
                    "Sort order: popularity (default), observation_start, observation_end, search_rank.",
                    default="popularity",
                ),
            ),
            loads=False,
            run=_cli("_run_fred_search"),
        ),
        Operation(
            "releases",
            "List FRED releases (Consumer Price Index, Employment Situation, …).",
            args=(Arg("limit", "Max releases returned (default 100).", type=int, default=100),),
            loads=False,
            run=_cli("_run_fred_releases"),
        ),
    ),
    skill="data/fred",
    doctor=Doctor("data.fred.observations", run=doctor_check("fred_check")),
    fetcher=_fetcher,
)
