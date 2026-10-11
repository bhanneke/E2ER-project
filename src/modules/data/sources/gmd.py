"""The Global Macro Database: annual macro panels in versioned releases; no key; academic-use terms.

A connector written before the kit: its fetching (gmd_provider.py, which also
holds its terms, licence and citation), its ``e2er-data`` handlers (cli.py)
and its ``fetch_data`` fetcher (providers.py) are its own. The definition
below is the one place for everything else.
"""

from __future__ import annotations

from typing import Any

from .. import gmd_provider as gmd
from .base import Arg, Doctor, Operation, Restricted, Source
from .legacy import cli_handler as _cli
from .legacy import doctor_check


def _fetcher(settings: Any) -> Any:
    from ..providers import GMDFetcher

    return GMDFetcher()


def reload(entry: dict[str, Any]) -> tuple[list[str], str] | None:
    """The e2er-data command that repeats a GMD load (without its target); None if unknown."""
    variables = entry.get("variables") or str(entry.get("series") or "").split(",")
    variables = [str(v) for v in variables if str(v).strip()]
    if not variables:
        return None
    args = ["gmd", "series", "--variables", ",".join(variables)]
    countries = entry.get("countries")
    if isinstance(countries, list) and countries:
        args += ["--countries", ",".join(str(c) for c in countries)]
    for key in ("start", "end"):
        if entry.get(key) is not None:
            args += [f"--{key}", str(entry[key])]
    if entry.get("version"):
        args += ["--version", str(entry["version"])]
    return args, ""


SOURCE = Source(
    name=gmd.SOURCE,
    label="Global Macro Database",
    dataset=gmd.DATASET,
    website=gmd.WEBSITE,
    terms_url=gmd.TERMS_URL,
    terms_summary=gmd.TERMS_SUMMARY,
    terms_plain=gmd.TERMS_PLAIN,
    licence=gmd.LICENCE,
    citation=gmd.CITATION,
    citation_by="source",
    bibtex=gmd.BIBTEX,
    cite_key=gmd.CITE_KEY,
    use=(
        "Annual macroeconomic panels for 239 economies (GDP, inflation, rates, exchange rates, "
        "government finances, trade, money, house prices, crises), 1086 to today plus forecasts, "
        "in versioned quarterly releases. Free for academic use; cite the GMD."
    ),
    coverage="Annual macroeconomic data for 239 economies, in versioned releases. Free for academic use.",
    help="Global Macro Database: annual macro panels for 239 economies, versioned releases. No key.",
    operations=(
        Operation(
            "versions",
            "List GMD releases, newest first (the newest is the default).",
            loads=False,
            run=_cli("_run_gmd_versions"),
        ),
        Operation(
            "variables", "List GMD variables with units and definitions.", loads=False, run=_cli("_run_gmd_variables")
        ),
        Operation("countries", "List GMD countries: ISO3 code and name.", loads=False, run=_cli("_run_gmd_countries")),
        Operation(
            "series",
            "Load a country-year panel, e.g. --variables rGDP,infl --countries USA,DEU --start 2000 --end 2024.",
            args=(
                Arg("variables", "Comma-separated GMD variable codes, e.g. rGDP,infl.", required=True),
                Arg("countries", "Comma-separated ISO3 codes, e.g. USA,DEU. Omit for all countries."),
                Arg("start", "First year (e.g. 2000).", type=int),
                Arg("end", "Last year (e.g. 2024).", type=int),
                Arg(
                    "version",
                    "GMD release, e.g. 2026_09. Default: the newest release. The release used is always recorded.",
                ),
            ),
            run=_cli("_run_gmd_series"),
        ),
    ),
    redistribution=False,
    restricted=Restricted(short="GMD", name=gmd.DATASET, zenodo_licence="other-nc"),
    aliases=("global_macro_database",),
    skill="data/gmd",
    doctor=Doctor("data.gmd.versions", run=doctor_check("gmd_check")),
    reached="The Global Macro Database",
    reload=reload,
    fetcher=_fetcher,
)
