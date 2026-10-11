"""The connector kit: every data source e2er can load from, each declared once.

Adding a source is one module in this package with a ``SOURCE = Source(...)``
definition, and its name in ``_MODULES`` below (docs/CONNECTORS.md). The kit
derives the rest from the definitions:

- ``e2er-data <source> <operation>`` (cli.py builds its subcommands and dispatch from here);
- the record of every load (data_sources.json), the data dictionary entry and
  the citation in the study's literature.bib (``runtime.py``);
- the planning catalogue and ``fetch_data`` (``registry.series_fetchers``);
- the sources the data architect may declare (``data_sources.CONNECTORS``);
- the commands the standalone check treats as loading data;
- the dashboard's labels and the doctor's reachability check;
- the terms handling of sources whose data a study may not pass on
  (``data_terms.known``, ``get_data.py`` in the reproduce recipe);
- the README's data source table and a skill stub (``docs.py``).

Allium stays outside the kit: its SQL warehouse has its own guarded tool and
approval flow (``data_sources.CONNECTORS`` adds it by hand).
"""

from __future__ import annotations

import importlib

from .base import (
    Arg,
    Cache,
    Context,
    Doctor,
    Fetched,
    FetchError,
    Key,
    Operation,
    Polite,
    Restricted,
    Source,
    SourceInfo,
)

__all__ = [
    "Arg",
    "Cache",
    "Context",
    "Doctor",
    "FetchError",
    "Fetched",
    "Key",
    "Operation",
    "Polite",
    "Restricted",
    "Source",
    "SourceInfo",
    "all_sources",
    "get",
    "names",
    "register",
    "unregister",
]

#: The definitions, in catalogue order (the planning catalogue, the README table, `e2er-data --help`).
_MODULES = ("yfinance", "fred", "gmd", "usgs")

_REGISTRY: dict[str, Source] | None = None


def _load() -> dict[str, Source]:
    global _REGISTRY
    if _REGISTRY is None:
        found: dict[str, Source] = {}
        for mod in _MODULES:
            source: Source = importlib.import_module(f"{__name__}.{mod}").SOURCE
            problems = source.validate()
            if problems:
                raise ValueError("invalid source definition: " + "; ".join(problems))
            found[source.name] = source
        _REGISTRY = found
    return _REGISTRY


def all_sources() -> list[Source]:
    """Every source, in catalogue order."""
    return list(_load().values())


def names() -> list[str]:
    return list(_load())


def get(name: str) -> Source | None:
    return _load().get(name)


def register(source: Source) -> None:
    """Add (or replace) a source at run time: a test's fake source, a plugin's."""
    problems = source.validate()
    if problems:
        raise ValueError("invalid source definition: " + "; ".join(problems))
    _load()[source.name] = source


def unregister(name: str) -> None:
    _load().pop(name, None)
