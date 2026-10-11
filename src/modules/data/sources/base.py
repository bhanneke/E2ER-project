"""The connector kit's building blocks: a data source and its operations, declared once.

A :class:`Source` names the source (website, terms, licence, citation, key),
how e2er treats its data (may a published study pass them on?), how politely
it asks (spacing between requests, retries, a User-Agent) and what it can do:
one :class:`Operation` per ``e2er-data <source> <operation>`` subcommand, with
its arguments (:class:`Arg`) and a fetch function that returns a
:class:`Fetched` (a pandas DataFrame or a list of records, plus what the load
record names: series, query, version, files).

Everything else is derived from the definition (``runtime.py``, ``docs.py``):
the ``e2er-data`` subcommands with ``--table``/``--save-to``, the record in
``data_sources.json``, the data dictionary entry, the citation in
``literature.bib``, the planning catalogue and ``fetch_data``, the labels, the
doctor's reachability check, the terms handling of sources whose data a study
may not pass on (``data_terms`` and ``get_data.py``), the README table and a
skill stub. docs/CONNECTORS.md walks through adding a source.

This module imports nothing heavy (no httpx, no pandas): the definitions are
read by the dashboard's labels and the planning checks.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .http import PoliteClient


@dataclass(frozen=True)
class SourceInfo:
    """What e2er records about a source on every load: its name, terms and citation."""

    connector: str
    dataset: str
    website: str
    terms_url: str
    #: The terms in one or two sentences, for a study page.
    terms_summary: str
    #: The terms in full, as the connector states them.
    licence: str
    #: ``source``: the source publishes the citation format; ``e2er``: it publishes none.
    citation_by: str


@dataclass(frozen=True)
class Key:
    """The setting that holds a source's key, and how a researcher gets one."""

    #: The attribute of ``Settings`` (read first), e.g. ``fred_api_key``.
    setting: str
    #: The environment variable (read when Settings has no such attribute), e.g. ``FRED_API_KEY``.
    env: str
    #: One sentence: where to get a key and what it costs.
    how_to_get: str
    #: True when the source works without the key too (a key only raises its limits).
    optional: bool = False


@dataclass(frozen=True)
class Restricted:
    """How e2er states terms that do not let a published study pass the data on.

    Only for a source with ``redistribution=False``. The fields become the
    source's ``data_terms.SourceTerms`` (publishing asks for confirmation, the
    description names the terms on every data file, a Zenodo deposit takes
    ``zenodo_licence`` or is refused) and its loads are repeated by
    ``get_data.py`` instead of shipped.
    """

    #: The short name in sentences ("GMD", "Yahoo Finance").
    short: str
    #: Zenodo's licence id that does not contradict the terms; None: e2er does not deposit the data on Zenodo.
    zenodo_licence: str | None
    #: The name in sentences; default: the source's ``dataset``.
    name: str = ""
    #: Why no Zenodo licence fits (when ``zenodo_licence`` is None).
    no_zenodo_why: str = ""
    limit: str = "do not allow passing them on outside the study's replication package"
    limit_finish: str = "do not allow passing the data on outside the study's replication package"
    confirm: str = "under these terms"
    warn: str = ""
    article: str = "the "
    #: The terms in plain words, one line each; default: the source's ``terms_plain``.
    plain: tuple[str, ...] = ()
    #: False when the source publishes a citation the paper must carry but no BibTeX key is checked.
    cite_required: bool = True


@dataclass(frozen=True)
class Polite:
    """How the kit's HTTP client treats the source's servers."""

    #: Seconds between two requests to this source (all operations of one process share it).
    min_interval: float = 0.5
    #: Retries after HTTP 429, 502, 503 or 504 (honouring Retry-After, else 1 s, 2 s, 4 s …).
    retries: int = 2
    #: Seconds to wait for a response.
    timeout: float = 60.0
    #: The most requests one operation may make (a guard against runaway paging).
    max_requests: int = 200
    #: Extra headers (the kit always sends a User-Agent naming e2er).
    headers: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class Cache:
    """What the kit keeps on disk under ``~/.e2er/cache/<source>`` (``$E2ER_CACHE_DIR`` when set)."""

    #: Files fetched by ``download_file`` with a version are kept by version and re-hashed on every use.
    by_version: bool = True
    #: Seconds a response of ``PoliteClient.get_cached`` stays fresh; None: never cached.
    ttl: int | None = None


@dataclass(frozen=True)
class Arg:
    """One argument of an operation: ``--<name>`` on the command line, ``<dest>`` in ``fetch_data`` params."""

    name: str
    help: str
    #: ``str``, ``int``, ``float``, ``"list"`` (comma-separated → list of str) or ``"flag"`` (store_true).
    type: Any = str
    required: bool = False
    default: Any = None
    choices: tuple[Any, ...] | None = None
    #: The params key; default: ``name`` with dashes as underscores.
    dest: str = ""

    @property
    def key(self) -> str:
        return self.dest or self.name.replace("-", "_")


@dataclass
class Fetched:
    """What an operation's fetch function returns."""

    #: A pandas DataFrame or a list of dicts.
    rows: Any
    #: What was loaded, for a study page ("M≥5 earthquakes 2024-01-01 to 2024-02-01").
    series: str
    #: The request as sent (a URL, an ADQL query); recorded so the load can be repeated.
    query: str | None = None
    #: The release read, where the source publishes releases.
    version: str | None = None
    #: ``{url, sha256}`` of every file read.
    files: list[dict[str, Any]] = field(default_factory=list)
    #: A page that shows what was loaded.
    link: str | None = None
    #: This load's citation, when it differs from the source's.
    citation: str | None = None
    #: Further keys for the load's entry in data_sources.json.
    record: dict[str, Any] = field(default_factory=dict)
    #: A note for the specialist, printed with the result.
    note: str | None = None
    #: The table's frequency for the data dictionary ("annual", "event", …).
    frequency: str | None = None


class FetchError(Exception):
    """A request the source cannot serve; the message is shown to the specialist as the load's error."""


@dataclass
class Context:
    """What a fetch function gets besides its params."""

    source: Source
    http: PoliteClient
    #: The key's value, or None (a keyless source, or an optional key not set).
    key: str | None
    #: ``~/.e2er/cache/<source>`` (created on first use by the adapters).
    cache_dir: Any


FetchFn = Callable[[Context, dict[str, Any]], Awaitable[Fetched]]


@dataclass(frozen=True)
class Operation:
    """One ``e2er-data <source> <name>`` subcommand and ``fetch_data`` method."""

    name: str
    help: str
    args: tuple[Arg, ...] = ()
    #: The kit path: fetch rows; the kit saves, records and cites them.
    fetch: FetchFn | None = None
    #: True: the rows are data for the study (``--table``/``--save-to``, recorded, cited);
    #: False: a listing that helps choose (printed only).
    loads: bool = True
    #: The method's description in the planning catalogue; default: its arguments.
    card: str = ""
    #: A connector written before the kit: its own ``e2er-data`` handler (``async (argparse.Namespace) -> str``).
    run: Callable[[Any], Awaitable[str]] | None = None


@dataclass(frozen=True)
class Doctor:
    """The doctor's reachability check: one cheap request."""

    #: The check's id (``data.<source>.<operation>``), shown under "Technical details".
    check: str
    #: The kit path: run this operation with these params; PASS when it returns rows.
    operation: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    #: A connector written before the kit: its own check function (``async (settings) -> doctor.Check``).
    run: Callable[[Any], Awaitable[Any]] | None = None


@dataclass(frozen=True)
class Source:
    """One data source, declared once. See the module docstring and docs/CONNECTORS.md."""

    #: The connector name: ``e2er-data <name>``, the ``source`` of a data dictionary table.
    name: str
    #: The name the pages show ("USGS Earthquake Catalog").
    label: str
    #: The source's name in data_sources.json ("ANSS Comprehensive Earthquake Catalog (ComCat), USGS").
    dataset: str
    website: str
    terms_url: str
    #: The terms in one or two sentences, for a study page.
    terms_summary: str
    #: The terms in full, as e2er states them.
    licence: str
    #: The citation of the source (a load may give its own: ``Fetched.citation``).
    citation: str
    #: ``source``: the source publishes the citation; ``e2er``: it publishes none and e2er suggests one.
    citation_by: str
    #: What the source is for, in the planning catalogue.
    use: str
    #: The README table's "Coverage" cell.
    coverage: str
    operations: tuple[Operation, ...] = ()
    #: The terms in plain words, one line each; default: ``terms_summary``.
    terms_plain: tuple[str, ...] = ()
    #: The BibTeX entry added to the study's literature.bib on a load, and its key.
    bibtex: str = ""
    cite_key: str = ""
    key: Key | None = None
    #: May a published study pass the data on? False: ``restricted`` says how e2er states the terms.
    redistribution: bool = True
    restricted: Restricted | None = None
    polite: Polite = Polite()
    cache: Cache = Cache()
    #: Other names a data dictionary may use for the source (written lower case, "_" for spaces and dashes).
    aliases: tuple[str, ...] = ()
    #: The specialists' skill file (``data/<name>`` under skills/files).
    skill: str = ""
    doctor: Doctor | None = None
    #: The name in "… could not be reached"; default: ``label``.
    reached: str = ""
    #: The README table's "Setting" cell; default from ``key``.
    setting_note: str = ""
    #: ``e2er-data`` arguments that repeat a recorded load (get_data.py); default: from its ``request``.
    reload: Callable[[dict[str, Any]], tuple[list[str], str] | None] | None = None
    #: A connector written before the kit: its own ``SeriesFetcher`` factory (``(settings) -> SeriesFetcher``).
    fetcher: Callable[[Any], Any] | None = None
    #: One line under ``e2er-data --help``.
    help: str = ""

    # ── derived ──────────────────────────────────────────────────────────────

    @property
    def info(self) -> SourceInfo:
        return SourceInfo(
            connector=self.name,
            dataset=self.dataset,
            website=self.website,
            terms_url=self.terms_url,
            terms_summary=self.terms_summary,
            licence=self.licence,
            citation_by=self.citation_by,
        )

    @property
    def plain(self) -> tuple[str, ...]:
        return self.terms_plain or (self.terms_summary,)

    @property
    def is_kit(self) -> bool:
        """True when e2er-data runs the source's operations through the kit (no handler of its own)."""
        return all(op.run is None for op in self.operations)

    def operation(self, name: str) -> Operation | None:
        return next((op for op in self.operations if op.name == name), None)

    def setting_cell(self) -> str:
        if self.setting_note:
            return self.setting_note
        if self.key is None:
            return "no key"
        return f"`{self.key.env}` ({'optional' if self.key.optional else 'free'})"

    def key_value(self, settings: Any) -> str | None:
        """The key from Settings, else the environment; None when unset."""
        if self.key is None:
            return None
        import os

        value = getattr(settings, self.key.setting, None) if settings is not None else None
        if value is None and not hasattr(settings, self.key.setting):
            value = os.environ.get(self.key.env)
        value = (str(value).strip() if value else "") or None
        return value

    def available(self, settings: Any) -> bool:
        """Can a study use the source now (keyless, an optional key, or its key is set)?"""
        return self.key is None or self.key.optional or bool(self.key_value(settings))

    def validate(self) -> list[str]:
        """What is wrong with the definition (empty when nothing is)."""
        problems = []
        for attr in ("name", "label", "dataset", "website", "terms_url", "terms_summary", "licence", "use"):
            if not getattr(self, attr):
                problems.append(f"{self.name or '?'}: {attr} is empty")
        if self.citation_by not in ("source", "e2er"):
            problems.append(f"{self.name}: citation_by must be 'source' or 'e2er'")
        if not self.redistribution and self.restricted is None:
            problems.append(f"{self.name}: redistribution=False needs `restricted` (how e2er states the terms)")
        if self.bibtex and not self.cite_key:
            problems.append(f"{self.name}: bibtex needs cite_key")
        if self.bibtex and self.cite_key and self.cite_key not in self.bibtex:
            problems.append(f"{self.name}: cite_key {self.cite_key!r} is not the key of its bibtex entry")
        names = [op.name for op in self.operations]
        if len(set(names)) != len(names):
            problems.append(f"{self.name}: two operations share a name")
        for op in self.operations:
            if (op.fetch is None) == (op.run is None):
                problems.append(f"{self.name} {op.name}: give exactly one of fetch (kit) or run (own handler)")
        if self.doctor and self.doctor.operation and self.operation(self.doctor.operation) is None:
            problems.append(f"{self.name}: the doctor check names no operation of the source")
        return problems
