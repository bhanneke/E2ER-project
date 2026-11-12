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
import re
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
SOURCE_UNAVAILABLE = "source_unavailable"


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


def same_load(new: dict[str, Any], recorded: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The study's record of the load ``new`` repeats: the same table, else the same saved file, else the same
    source and request. get_data.py may repeat a load into a table and a file as a file alone (the Gaia study
    of 2026-10-13 loaded a table and saved data/gaia_dr3.csv; its get_data.py saves the file), so any one of
    them that both name is enough, for the same connector."""
    key = _key(new)
    exact = next((x for x in recorded if _key(x) == key), None)
    if exact is not None:
        return exact
    connector = new.get("connector")
    for x in recorded:
        if x.get("connector") != connector:
            continue
        for k in ("table", "saved_to", "query", "series"):
            if new.get(k) and new.get(k) == x.get(k):
                return x
    return None


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
    loaded_on = str(entry.get("retrieved_at") or "")[:10]
    for key in ("version", "service_version", "api_version", "last_updated"):
        value = entry.get(key)
        if isinstance(value, str | int | float) and str(value).strip():
            # Project Gutenberg's "version" is the day of the load, not the source's: no version of its own.
            return "" if loaded_on and str(value).startswith(loaded_on) else str(value)
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


_EBOOK = re.compile(r"/(?:cache/epub|files|ebooks)/(\d+)/")


def _part_name(key: str) -> str:
    """A changed part as a reader names it: "ebook 2276" for a Project Gutenberg text, else its file name."""
    if key.isdigit():
        return f"ebook {key}"
    m = _EBOOK.search(key)
    if m:
        return f"ebook {m.group(1)}"
    return key.rstrip("/").rsplit("/", 1)[-1] or key


def _texts(entry: dict[str, Any]) -> dict[str, str]:
    """A corpus load's texts (``texts``: id -> {sha256}), by id."""
    texts = entry.get("texts")
    if not isinstance(texts, dict):
        return {}
    return {str(k): str(v["sha256"]) for k, v in texts.items() if isinstance(v, dict) and v.get("sha256")}


def changed_parts(old: dict[str, Any], new: dict[str, Any]) -> tuple[list[str], str]:
    """(the parts of a load that differ, by name; "texts" or "files"): the texts a corpus load recorded
    (since 0.21), else the files the source served (url and SHA-256, recorded before too)."""
    a, b = _texts(old), _texts(new)
    kind = "texts"
    if not (a and b):
        a, b, kind = _files(old), _files(new), "files"
    if not (a and b):
        return [], ""
    keys = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
    return [_part_name(k) for k in keys], kind


def short(sha: str | None) -> str:
    return f"sha256:{sha[:12]}…" if sha else "none"


def compare(folder: Path, run_dir: Path, before: set[str] | None = None) -> list[dict[str, Any]]:
    """Each load a step made in the run, against the study's record of the same load.

    ``before``: the run record's loads before the steps ran (:func:`snapshot`); only the others are new.
    """
    recorded = _loads(Path(folder) / STUDY_RECORD)
    out: list[dict[str, Any]] = []
    for new in _loads(Path(run_dir) / RUN_RECORD):
        if before and json.dumps(new, sort_keys=True) in before:
            continue
        old = same_load(new, recorded)
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
        parts, kind = changed_parts(old, new)
        if parts:
            entry["parts_changed"] = parts
            entry["parts_kind"] = kind
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
            f"{short(entry.get('now'))}{rows}){versions}{_parts_words(entry)}."
        )
    if entry.get("recorded") and not entry.get("now"):
        return f"{name}: the reload recorded no fingerprint, so e2er cannot compare it with the study's ({on})."
    text = (
        f"{name}: the source fingerprint was not recorded when the study loaded these data ({on}; e2er records it "
        "since 0.21), so e2er cannot say whether the source now returns other data"
    )
    parts = entry.get("parts_changed") or []
    if entry.get("parts_kind") == "texts" or any(str(x).startswith("ebook ") for x in parts):
        text += _parts_words(entry) + " (SHA-256, against the study's record)"
    elif entry.get("files_differ"):
        text += "; the file the source served differs byte for byte from the one the study recorded (SHA-256)"
    elif entry.get("files_differ") is False:
        text += "; the file the source served is byte for byte the one the study recorded (SHA-256)"
    return text + versions + "."


def _parts_words(entry: dict[str, Any]) -> str:
    parts = entry.get("parts_changed") or []
    if not parts:
        return ""
    what = "texts" if entry.get("parts_kind") == "texts" else "files"
    shown = ", ".join(parts[:10]) + (f" and {len(parts) - 10} more" if len(parts) > 10 else "")
    return f"; the {what} that differ: {shown}"


def _new_version(s: dict[str, Any]) -> bool:
    """The source names another version, release or update date than when the study loaded it."""
    a, b = s.get("version_recorded"), s.get("version_now")
    return bool(a and b and a != b)


def changed(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Loads whose source returned other data: another fingerprint, or (a study recorded before fingerprints)
    another version by the source's own account (the WHO GHO's latest update date, a data release)."""
    return [s for s in sources if s.get("status") == CHANGED or (s.get("status") == NOT_RECORDED and _new_version(s))]


def _names(items: list[dict[str, Any]]) -> str:
    seen: list[str] = []
    for s in items:
        on = s.get("recorded_at") or "the study’s load"
        if s.get("status") == CHANGED:
            bit = f"{s['source']} returned different data than on {on}"
        else:
            bit = (
                f"{s['source']} now gives version {s.get('version_now')} of its data; the study loaded version "
                f"{s.get('version_recorded')} on {on}"
            )
        if bit not in seen:
            seen.append(bit)
    return "; ".join(seen)


#: What a step that loads data prints when a source did not answer (a time-out, a refused connection, a
#: server error): Gutendex's "did not answer within 45 s", httpx's ReadTimeout, HTTP 502/503/504.
_NO_ANSWER = re.compile(
    r"did not answer|timed? ?out|Timeout(?:Error|Exception)?\b|ReadTimeout|ConnectTimeout|ConnectError|"
    r"Connection (?:refused|reset|aborted)|Temporary failure in name resolution|Name or service not known|"
    r"Service Unavailable|Bad Gateway|Gateway Time-?out|\b(?:HTTP|status|answered with)[^\n]{0,40}\b50[234]\b|"
    r"server error \(5\d\d\)|try again later",
    re.I,
)


def unanswered(steps: list[Any]) -> tuple[Any, list[str]]:
    """(the failed step that loads data again, the lines of its output that say a source did not answer).

    Only a failed step that loads inputs again counts (the only step that reaches the web); (None, []) when
    no such step failed, or its output names no time-out or server error.
    """
    failed = next((s for s in steps if getattr(s, "exit_code", 0)), None)
    if failed is None or not getattr(failed, "reload", False):
        return None, []
    try:
        text = Path(failed.log).read_text(encoding="utf-8", errors="replace") if failed.log else ""
    except OSError:
        text = ""
    text = text or str(getattr(failed, "tail", "") or "")
    lines: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if line and _NO_ANSWER.search(line) and line not in lines:
            lines.append(line)
    return failed, lines


def judge(verdict: str, code: int, sources: list[dict[str, Any]], steps: list[Any] | None = None) -> tuple[str, str]:
    """(the verdict with the sources named where they explain it, the report's category).

    A step that loads data again and failed because a source did not answer is neither a source change nor a
    failure of the study's code: ``source_unavailable``, and a later try may succeed.
    """
    moved = changed(sources)
    if code == 0:
        return verdict, REPRODUCED
    step, lines = unanswered(steps or []) if code == 2 else (None, [])
    if step is not None and lines:
        said = lines[-1] if len(lines[-1]) <= 300 else lines[-1][:297] + "..."
        return (
            f"Could not reproduce yet: a source did not answer while `{step.command}` loaded the data again "
            f"({said}). This is not a failure of the study's code and says nothing about whether the study "
            "reproduces; the source may answer on a later try, so run the same command again later.",
            SOURCE_UNAVAILABLE,
        )
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
