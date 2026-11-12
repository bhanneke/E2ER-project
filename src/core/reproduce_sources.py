"""Did the source return the same data? The data versions a rerun's reloads compare with the study's.

Since 0.21 every load e2er-data records in ``data_sources.json`` carries a ``fingerprint``: a SHA-256 of the
rows it returned in a canonical form (modules/data/load_record.py, ``fingerprint_rows``). A study whose data
cannot ship (a source's terms) is run again with get_data.py, which loads the data again with e2er-data in
the run folder; e2er-data records those loads in the run folder's ``data_sources.json``. This module pairs
each new load with the study's record of the same load (the same table, else the same saved file, else the
same source and series) and says plainly whether the source returned the same data.

A study recorded before 0.21 has no fingerprint: the report says so. Where both loads record the files the
source served (``files``: url and SHA-256), a difference there is named as a hint.

When a later step fails, or results differ, after a source returned other data, the report names the source
change as the likely cause: the verdict says so and the JSON report's ``category`` is ``source_changed``.
"""

from __future__ import annotations

import json
import platform
import sys
from pathlib import Path
from typing import Any

#: The run folder's record of the loads a step made (e2er-data writes it in the workspace, the run folder).
RUN_RECORD = "data_sources.json"
#: The study's own record, in an exported folder.
STUDY_RECORD = "data/data_sources.json"

SAME = "same"
CHANGED = "changed"
NOT_RECORDED = "not_recorded"

#: The JSON report's ``category``: what kind of outcome the verdict is.
REPRODUCED = "reproduced"
NOT_REPRODUCED = "not_reproduced"
COULD_NOT_RUN = "could_not_run"
SOURCE_CHANGED = "source_changed"


def _loads(path: Path) -> list[dict[str, Any]]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    loads = doc.get("loads") if isinstance(doc, dict) else None
    return [x for x in loads if isinstance(x, dict)] if isinstance(loads, list) else []


def _key(entry: dict[str, Any]) -> tuple[Any, ...]:
    from ..modules.data.load_record import _key as key

    return key(entry)


def snapshot(run_dir: Path) -> set[str]:
    """The loads the run folder's record holds before the steps run (normally none)."""
    return {json.dumps(x, sort_keys=True) for x in _loads(Path(run_dir) / RUN_RECORD)}


def _label(entry: dict[str, Any]) -> str:
    connector = str(entry.get("connector") or "")
    try:
        from ..modules.data import sources

        source = sources.get(connector)
    except Exception:  # noqa: BLE001 — a name for a sentence
        source = None
    if source is not None and source.label:
        return str(source.label)
    return str(entry.get("dataset") or connector or "the source")


def _version(entry: dict[str, Any]) -> str:
    """The source's own version, release or last-updated value as the load recorded it, else empty."""
    for key in ("version", "service_version", "api_version", "last_updated"):
        value = entry.get(key)
        if isinstance(value, str | int | float) and str(value).strip():
            return str(value)
    return ""


def _fp(entry: dict[str, Any]) -> dict[str, Any] | None:
    fp = entry.get("fingerprint")
    return fp if isinstance(fp, dict) and isinstance(fp.get("sha256"), str) else None


def _files(entry: dict[str, Any]) -> dict[str, str]:
    return {
        str(f["url"]): str(f["sha256"])
        for f in entry.get("files") or []
        if isinstance(f, dict) and f.get("url") and f.get("sha256")
    }


def short(sha: str | None) -> str:
    return f"sha256:{sha[:12]}…" if sha else "none"


def compare(folder: Path, run_dir: Path, before: set[str] | None = None) -> list[dict[str, Any]]:
    """Each load a step made in the run, against the study's record of the same load.

    ``before``: the run record's loads before the steps ran (:func:`snapshot`); only the others are new.
    """
    recorded = {_key(x): x for x in _loads(Path(folder) / STUDY_RECORD)}
    out: list[dict[str, Any]] = []
    for new in _loads(Path(run_dir) / RUN_RECORD):
        if before and json.dumps(new, sort_keys=True) in before:
            continue
        old = recorded.get(_key(new))
        if old is None:
            continue  # a load the study did not record: nothing to compare it with
        what = new.get("table") or new.get("saved_to")
        entry: dict[str, Any] = {
            "source": _label(new),
            "connector": str(new.get("connector") or ""),
            "loaded_into": str(what) if what else None,
            "recorded_at": str(old.get("retrieved_at") or "")[:10] or None,
            "reloaded_at": str(new.get("retrieved_at") or "") or None,
            "version_recorded": _version(old) or None,
            "version_now": _version(new) or None,
        }
        had, has = _fp(old), _fp(new)
        if had is None:
            entry["status"] = NOT_RECORDED
            entry["now"] = has["sha256"] if has else None
            entry["rows_now"] = has.get("rows") if has else new.get("rows")
            before_files, now_files = _files(old), _files(new)
            shared = sorted(set(before_files) & set(now_files))
            if shared:
                entry["files_differ"] = any(before_files[u] != now_files[u] for u in shared)
        else:
            entry.update(
                {
                    "status": SAME if has is not None and has["sha256"] == had["sha256"] else CHANGED,
                    "recorded": had["sha256"],
                    "now": has["sha256"] if has else None,
                    "rows_recorded": had.get("rows"),
                    "rows_now": has.get("rows") if has else new.get("rows"),
                    "form": had.get("form"),
                }
            )
            if has is None:
                # This e2er recorded no fingerprint for the reload (it should): the data cannot be compared.
                entry["status"] = NOT_RECORDED
        entry["sentence"] = sentence(entry)
        out.append(entry)
    return out


def sentence(entry: dict[str, Any]) -> str:
    """One plain line for the report."""
    name = entry["source"] + (f" ({entry['loaded_into']})" if entry.get("loaded_into") else "")
    on = entry.get("recorded_at") or "the study's load"
    versions = ""
    if entry.get("version_recorded") and entry.get("version_now") and entry["version_recorded"] != entry["version_now"]:
        versions = f"; its version changed from {entry['version_recorded']} to {entry['version_now']}"
    if entry["status"] == SAME:
        return f"{name} returned the same data as on {on} ({short(entry.get('recorded'))}){versions}."
    if entry["status"] == CHANGED:
        rows = ""
        if entry.get("rows_recorded") != entry.get("rows_now") and entry.get("rows_now") is not None:
            rows = f", {entry.get('rows_recorded')} rows then, {entry.get('rows_now')} now"
        return (
            f"{name} returned different data than on {on} (recorded {short(entry.get('recorded'))}, now "
            f"{short(entry.get('now'))}{rows}){versions}."
        )
    if entry.get("recorded") and not entry.get("now"):
        return f"{name}: the reload recorded no fingerprint, so e2er cannot compare it with the study's ({on})."
    text = (
        f"{name}: the source fingerprint was not recorded when the study loaded these data ({on}; e2er records it "
        "since 0.21), so e2er cannot say whether the source now returns other data"
    )
    if entry.get("files_differ"):
        text += "; the file the source served differs byte for byte from the one the study recorded (SHA-256)"
    elif entry.get("files_differ") is False:
        text += "; the file the source served is byte for byte the one the study recorded (SHA-256)"
    return text + versions + "."


def changed(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [s for s in sources if s.get("status") == CHANGED]


def _names(items: list[dict[str, Any]]) -> str:
    seen: list[str] = []
    for s in items:
        bit = f"{s['source']} returned different data than on {s.get('recorded_at') or 'the study’s load'}"
        if bit not in seen:
            seen.append(bit)
    return "; ".join(seen)


def judge(verdict: str, code: int, sources: list[dict[str, Any]]) -> tuple[str, str]:
    """(the verdict with the sources named where they explain it, the report's category)."""
    moved = changed(sources)
    if code == 0:
        return verdict, REPRODUCED
    if moved:
        cause = (
            "the change at the source is the likely cause, not the study's code"
            if code == 2
            else "the change at the source is the likely cause of the differences"
        )
        return f"{verdict} {_names(moved)}: {cause}.", SOURCE_CHANGED
    unknown = [s for s in sources if s.get("status") == NOT_RECORDED]
    if unknown:
        hint = (
            " The study recorded no fingerprint of the data it loaded (e2er records it since 0.21), so e2er "
            "cannot say whether the source changed"
        )
        if any(s.get("files_differ") for s in unknown):
            files = sorted({s["source"] for s in unknown if s.get("files_differ")})
            hint += f"; the files {', '.join(files)} served differ from the ones the study recorded"
        verdict = verdict + hint + "."
    return verdict, (COULD_NOT_RUN if code == 2 else NOT_REPRODUCED)


def host() -> dict[str, Any]:
    """Facts about the computer the rerun ran on (the steps' own Python is in ``environment``)."""
    from .. import __version__

    return {
        "e2er_version": __version__,
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "python": sys.version.split()[0],
    }
