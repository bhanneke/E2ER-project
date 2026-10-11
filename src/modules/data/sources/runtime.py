"""Running a kit source: one operation, its envelope, its record, its citation.

``run_operation`` is shared by ``e2er-data <source> <operation>`` (``cli_handler``)
and the planning tools' ``fetch_data`` (``KitFetcher``): it opens the source's
polite HTTP client, calls the operation's fetch function and returns the
canonical envelope ``{source, items, error, row_count, ...}``, with the load's
data_sources.json entry under ``_load_record``. It never raises.

On the command line a loading operation also takes ``--table`` and
``--save-to``; a load that returned rows is recorded in data_sources.json
(``cli._record``), a table gets its data dictionary entry
(``record_in_dictionary``) and the source's BibTeX goes into the study's
literature.bib (``add_citation``).
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

from ..providers import SeriesFetcher
from .base import Arg, Context, Fetched, FetchError, Operation, Source

#: Keys of the envelope that are not rows (the CLI prints them; the specialist reads them).
LOAD_RECORD = "_load_record"


def _clean(value: Any) -> Any:
    """A cell as JSON: NaN/NaT → None, numpy scalars → Python numbers, timestamps → ISO text."""
    if value is None:
        return None
    if hasattr(value, "isoformat") and not isinstance(value, str):
        try:
            import pandas as pd

            if value is pd.NaT:
                return None
        except ImportError:  # pragma: no cover
            pass
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            value = value.item()
        except (ValueError, AttributeError):
            return str(value)
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def to_items(rows: Any) -> list[dict[str, Any]]:
    """A DataFrame or a list of dicts as JSON-ready records."""
    if rows is None:
        return []
    if hasattr(rows, "to_dict"):
        records = rows.to_dict(orient="records")
    else:
        records = list(rows)
    return [{str(k): _clean(v) for k, v in r.items()} for r in records if isinstance(r, dict)]


def _envelope(source: Source, items: list[Any] | None = None, error: str | None = None, **extra: Any) -> dict:
    out: dict[str, Any] = {"source": source.name, "items": items or [], "error": error}
    out.update({k: v for k, v in extra.items() if v is not None})
    return out


def coerce_params(op: Operation, params: dict[str, Any]) -> dict[str, Any]:
    """``fetch_data`` params by the operation's arguments: keys by dest or flag name, types as declared.

    A missing required argument raises KeyError (``fetch_data`` reports it).
    """
    out: dict[str, Any] = {}
    for arg in op.args:
        raw = params.get(arg.key, params.get(arg.name, arg.default))
        if raw is None:
            if arg.required:
                raise KeyError(arg.key)
            out[arg.key] = None
            continue
        out[arg.key] = _coerce(arg, raw)
    return out


def _coerce(arg: Arg, raw: Any) -> Any:
    if arg.type == "list":
        if isinstance(raw, str):
            return [x.strip() for x in raw.replace(";", ",").split(",") if x.strip()]
        return [str(x).strip() for x in raw if str(x).strip()]
    if arg.type == "flag":
        return raw if isinstance(raw, bool) else str(raw).lower() in ("1", "true", "yes")
    if arg.type in (int, float):
        return arg.type(raw)
    return str(raw)


def citation_of(source: Source, fetched: Fetched) -> str:
    return fetched.citation or source.citation


def load_record(source: Source, op: Operation, params: dict[str, Any], fetched: Fetched, retrieved_at: str) -> dict:
    """The load's entry in data_sources.json (see load_record.py for the keys)."""
    from ..load_record import base

    entry: dict[str, Any] = base(source.info)
    entry.update(
        {
            "series": fetched.series,
            "link": fetched.link or source.website,
            "retrieved_at": retrieved_at,
            "citation": citation_of(source, fetched),
            "citation_by": source.citation_by,
        }
    )
    if source.cite_key:
        entry["cite_key"] = source.cite_key
    if fetched.version:
        entry["version"] = fetched.version
    if fetched.query:
        entry["query"] = fetched.query
    if fetched.files:
        entry["files"] = fetched.files
    # The request as it was made, so the load can be repeated (`e2er reproduce`, get_data.py).
    entry["request"] = {"command": op.name, **{k: v for k, v in params.items() if v is not None}}
    entry.update(fetched.record)
    return entry


async def run_operation(source: Source, op: Operation, params: dict[str, Any], settings: Any = None) -> dict:
    """Run one kit operation; the envelope with its rows, or with the error. Never raises."""
    from ..load_record import now_utc
    from .adapters import cache_dir
    from .http import PoliteClient

    if op.fetch is None:
        return _envelope(source, error=f"{source.name} {op.name} has no fetch function")
    if settings is None:
        from ....config import get_settings

        settings = get_settings()
    key = source.key_value(settings)
    if source.key is not None and not source.key.optional and not key:
        return _envelope(source, error=f"{source.key.env} not configured. {source.key.how_to_get}")
    try:
        async with PoliteClient(source.name, source.polite) as http:
            ctx = Context(source=source, http=http, key=key, cache_dir=cache_dir(source.name))
            fetched = await op.fetch(ctx, params)
    except FetchError as e:
        return _envelope(source, error=str(e))
    except Exception as e:  # noqa: BLE001 — a connector bug is reported to the specialist, never raised into its loop
        return _envelope(source, error=f"{type(e).__name__}: {e}")
    items = to_items(fetched.rows)
    out = _envelope(
        source,
        items=items,
        row_count=len(items),
        version=fetched.version,
        note=fetched.note,
    )
    if op.loads:
        record = load_record(source, op, params, fetched, now_utc())
        if fetched.frequency:
            record["frequency"] = fetched.frequency
        out[LOAD_RECORD] = record
    return out


# ── the study's records: data dictionary and literature.bib ──────────────────


class RecordError(RuntimeError):
    """The load could not be written into the study's records."""


def record_in_dictionary(workspace: Path, table: str, source: Source, record: dict[str, Any]) -> Path:
    """Update (or add) the ``tables`` entry of ``table`` in ``data_dictionary.json``.

    Sets ``source``/``series``, the version and source files where the load
    has them, the licence and the citation. Other keys the data architect
    wrote (role, columns, min_non_null, …) are kept.
    """
    path = Path(workspace) / "data_dictionary.json"
    doc: dict[str, Any] = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                doc = loaded
        except (OSError, ValueError):
            raise RecordError(f"{path.name} is not valid JSON; the load was not recorded in it") from None
    found = doc.get("tables")
    tables: list[Any] = found if isinstance(found, list) else []
    entry: dict[str, Any] = next((t for t in tables if isinstance(t, dict) and t.get("name") == table), {})
    if not entry:
        entry = {"name": table}
        tables.append(entry)
    version = record.get("version")
    update: dict[str, Any] = {
        "source": source.name,
        "series": record.get("series"),
        "licence": source.licence,
        "citation": record.get("citation") or source.citation,
        "provenance": f"{source.dataset} ({source.website})" + (f", release {version}" if version else ""),
    }
    if record.get("frequency") or not entry.get("frequency"):
        update["frequency"] = record.get("frequency") or entry.get("frequency")
    if version:
        update["version"] = version
    if record.get("files"):
        update["source_files"] = [{"url": f.get("url"), "sha256": f.get("sha256")} for f in record["files"]]
    if source.cite_key:
        update["cite_key"] = source.cite_key
    entry.update({k: v for k, v in update.items() if v is not None})
    doc["tables"] = tables
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def add_citation(workspace: Path, source: Source) -> bool:
    """Add the source's BibTeX entry to the study's ``literature.bib`` (exported as ``paper/refs.bib``).

    True when the entry was added; False when the key was already there or the source has no entry.
    """
    if not source.bibtex or not source.cite_key:
        return False
    path = Path(workspace) / "literature.bib"
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    if re.search(r"@\w+\s*\{\s*" + re.escape(source.cite_key) + r"\s*,", text):
        return False
    head = text.rstrip("\n") + "\n\n" if text.strip() else ""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(head + source.bibtex.strip() + "\n", encoding="utf-8")
    return True


# ── e2er-data ────────────────────────────────────────────────────────────────


def add_arguments(parser: Any, op: Operation) -> None:
    """The operation's arguments on its argparse subparser (``--table``/``--save-to`` are added by cli.py)."""
    for arg in op.args:
        flag = f"--{arg.name}"
        if arg.type == "flag":
            parser.add_argument(flag, dest=arg.key, action="store_true", help=arg.help)
            continue
        kw: dict[str, Any] = {"dest": arg.key, "help": arg.help, "default": arg.default}
        if arg.required:
            kw["required"] = True
        if arg.type in (int, float):
            kw["type"] = arg.type
        if arg.choices:
            kw["choices"] = list(arg.choices)
        parser.add_argument(flag, **kw)


def cli_handler(source: Source, op: Operation) -> Any:
    """The ``e2er-data <source> <op>`` handler of a kit operation."""

    async def _run(args: Any) -> str:
        from .. import cli

        params = {a.key: _coerce(a, v) if (v := getattr(args, a.key, None)) is not None else None for a in op.args}
        table = getattr(args, "table", None)
        workspace = cli._resolve_workspace(args.paper_id)
        dict_path = workspace / "data_dictionary.json"
        if op.loads and table and dict_path.is_file():
            # The load is recorded in the dictionary; check it can be before data.db changes.
            try:
                json.loads(dict_path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as e:
                bad = _envelope(source, error=f"data_dictionary.json is not valid JSON ({e}); fix it before loading")
                cli._maybe_save_table(bad, args)
                return json.dumps(bad, indent=2, default=str)

        result = await run_operation(source, op, params)
        record = result.pop(LOAD_RECORD, None)
        if result.get("error") and not table:
            cli._TABLE_FAILURES.append(f"{source.label}: {result['error']}")
        if not op.loads:
            return json.dumps(result, indent=2, default=str)
        cli._maybe_save_csv(result, args)
        cli._maybe_save_table(result, args)
        if record and not result.get("error") and not result.get("table_error") and result.get("items"):
            cli._record(result, args, record)
            try:
                if result.get("saved_table"):
                    record_in_dictionary(workspace, result["saved_table"], source, record)
                    result.setdefault("recorded_in", []).append("data_dictionary.json")
                if source.bibtex:
                    result["citation_added"] = add_citation(workspace, source)
                    result["cite_key"] = source.cite_key
            except (RecordError, OSError) as e:
                result["record_error"] = f"{type(e).__name__}: {e}"
                cli._TABLE_FAILURES.append(f"{source.label}: the load could not be recorded: {e}")
            result["provenance"] = {
                k: record[k] for k in ("version", "query", "files", "licence", "citation") if k in record
            }
        return json.dumps(result, indent=2, default=str)

    return _run


# ── the planning tools (fetch_data) ──────────────────────────────────────────


def method_card(op: Operation) -> str:
    if op.card:
        return op.card
    if not op.args:
        return op.help
    parts = []
    for a in op.args:
        kind = "list" if a.type == "list" else getattr(a.type, "__name__", str(a.type))
        parts.append(f"{a.key} ({kind}{', required' if a.required else ''})")
    return f"{op.help} Params: " + ", ".join(parts)


class KitFetcher(SeriesFetcher):
    """A ``SeriesFetcher`` for a kit source: its card and ``fetch_data`` dispatch, from the definition."""

    def __init__(self, source: Source, settings: Any = None) -> None:
        self.source = source
        self.name = source.name
        self._settings = settings

    def card(self) -> dict[str, Any]:
        s = self.source
        return {
            "name": s.name,
            "kind": "series",
            "use": s.use,
            "requires": s.key.env if s.key and not s.key.optional else "(none)",
            "terms": s.terms_summary,
            "methods": {op.name: method_card(op) for op in s.operations},
        }

    async def fetch(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        op = self.source.operation(method)
        if op is None:
            known = ", ".join(o.name for o in self.source.operations)
            return {"source": self.name, "error": f"unknown method '{method}' for {self.name}; available: {known}"}
        return await run_operation(self.source, op, coerce_params(op, params or {}), self._settings)


# ── the doctor ───────────────────────────────────────────────────────────────


async def doctor_check(source: Source, settings: Any) -> Any:
    """The source's reachability check: one cheap request (``Source.doctor``)."""
    from ....doctor import FAIL, PASS, SKIP, Check

    d = source.doctor
    if d is None:
        return None
    if d.run is not None:
        return await d.run(settings)
    if source.key is not None and not source.key.optional and not source.key_value(settings):
        return Check(d.check, SKIP, f"{source.key.env} not set")
    op = source.operation(d.operation)
    if op is None:
        return Check(d.check, FAIL, f"{source.name} has no operation {d.operation!r}")
    env = await run_operation(source, op, coerce_params(op, d.params), settings)
    n = len(env.get("items") or [])
    if env.get("error"):
        return Check(d.check, FAIL, str(env["error"])[:300])
    return Check(d.check, PASS if n else FAIL, f"{n} rows from {source.label}" if n else "no rows returned")


# ── get_data.py: repeating a load whose data a study may not pass on ─────────


def reload_args(source: Source, entry: dict[str, Any]) -> tuple[list[str], str] | None:
    """The e2er-data arguments that repeat a recorded load (without its target), and a note; None if unknown."""
    if source.reload is not None:
        return source.reload(entry)
    req = entry.get("request")
    if not isinstance(req, dict) or not req.get("command"):
        return None
    op = source.operation(str(req["command"]))
    if op is None or not op.loads:
        return None
    args = [source.name, op.name]
    for a in op.args:
        value = req.get(a.key)
        if value is None:
            continue
        if a.type == "flag":
            if value:
                args.append(f"--{a.name}")
            continue
        args += [f"--{a.name}", ",".join(str(v) for v in value) if isinstance(value, list) else str(value)]
    return args, ""


def source_terms(source: Source) -> Any:
    """The ``data_terms.SourceTerms`` of a source whose data a study may not pass on."""
    from ....core.data_terms import SourceTerms

    r = source.restricted
    assert r is not None
    return SourceTerms(
        connector=source.name,
        name=r.name or source.dataset,
        short=r.short,
        terms_url=source.terms_url,
        plain=r.plain or source.plain,
        zenodo_licence=r.zenodo_licence,
        no_zenodo_why=r.no_zenodo_why,
        cite_key=(source.cite_key or None) if r.cite_required else None,
        citation=source.citation if r.cite_required else "",
        licence=source.licence,
        limit=r.limit,
        limit_finish=r.limit_finish,
        confirm=r.confirm,
        warn=r.warn,
        article=r.article,
    )
