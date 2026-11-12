"""What a reader needs to reproduce a study, and the data and their terms: one record, written from e2er's own records.

``e2er pack`` writes the record into the package's list (``e2er-package.json``, key
``reproduction_requirements``) and as text into ``e2er-package/README.md``; ``e2er publish`` writes it
into the description (``e2er.json`` and the request to e2er.org, same key) and, with ``--github``, into the
top of the study's README. ``e2er inspect`` and ``e2er fetch`` print a short summary; for a package made
before the record existed they derive it from the package's own files on the fly.

Every fact comes from a record e2er already keeps; a fact no record holds is left out:

- software: Docker (``e2er reproduce`` runs the study's code in a Docker sandbox), the e2er version that
  exported the study, the Python of the study's ``reproduce.json`` and the pinned packages (the package's
  lock file, else the study's requirements file);
- accounts and keys: the key each data source's connector declares (``Source.key``; Allium's
  ``ALLIUM_API_KEY``), and whether a rerun needs it (only when the data are loaded again);
- data access: which data files come with the package, which loads a rerun repeats at their source (the
  ``RELOADS`` list e2er writes into ``code/get_data.py``, the left-out list, the recipe's inputs) and from
  which host, and whether a rerun needs the network;
- the sources: one entry per connector with the dataset, the source's own version, the load dates, the
  terms in plain words (as the load recorded them), whether the data come with the package or why not,
  the citation and the data fingerprints (``data_sources.json``, since e2er 0.21).

The size of the package and the duration of the rerun before publishing are not part of the record: a
package cannot name its own size, and the rerun's time differs between computers. They are shown next to
the record where known: the file's size (``inspect``, ``fetch``, ``package.bytes`` on e2er.org) and the
reproduction entry of the description's ``verification`` list (``seconds``, ``reload_seconds``).

The record never changes provenance.json or the dossier: the content id and the dossier's id stay the
study's. A package or description without it is still valid; readers derive what they can.
"""

from __future__ import annotations

import ast
import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

FORMAT = "e2er-requirements/1"
#: The key in e2er-package.json and e2er.json.
KEY = "reproduction_requirements"
#: The text file ``e2er pack`` adds to the package (part "package": outside provenance.json).
README = "e2er-package/README.md"
#: The few words that explain a data fingerprint wherever one is shown.
FINGERPRINT_WORDS = (
    "a fingerprint is a SHA-256 of the rows a load returned; the same rows give the same fingerprint, so a "
    "rerun can tell whether a source now returns other data"
)

#: Reads one file of the study (a path relative to its folder) as bytes; None when absent or unreadable.
Reader = Callable[[str], bytes | None]

#: Sources outside the connector kit: (name, the key's setting, what a reader needs).
_OUTSIDE_KIT: dict[str, tuple[str, str | None, str]] = {
    "allium": ("Allium", "ALLIUM_API_KEY", "an Allium account and its API key; Allium queries use paid query credits"),
    "data-folder": ("The researcher's data folder", None, ""),
    "zenodo": ("Zenodo", None, ""),
}

_PIN = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._\-]*(?:\[[^\]]*\])?)\s*==")


# ── reading ─────────────────────────────────────────────────────────────────


def _json(read: Reader, rel: str) -> Any:
    raw = read(rel)
    if raw is None:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None


def _str(x: Any) -> str:
    return x.strip() if isinstance(x, str) else ""


def pinned_count(text: str) -> int:
    """How many packages a requirements or lock file pins (``name==version`` lines; hashes and comments aside)."""
    joined = re.sub(r"\\\r?\n", " ", text)
    return sum(1 for line in joined.splitlines() if _PIN.match(line) and not line.lstrip().startswith("#"))


def get_data_reloads(source: str) -> list[dict[str, Any]] | None:
    """The ``RELOADS`` list of a get_data.py e2er wrote (read with ast, never run); None when it has none."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "RELOADS" for t in node.targets):
            try:
                value = ast.literal_eval(node.value)
            except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
                return None
            if isinstance(value, list):
                return [v for v in value if isinstance(v, dict)]
    return None


def _host(load: dict[str, Any]) -> str:
    """The host a load read from (its request, else its first file); empty when none is recorded."""
    candidates = [load.get("query")] + [f.get("url") for f in load.get("files") or [] if isinstance(f, dict)]
    for url in candidates:
        if isinstance(url, str) and url.startswith(("https://", "http://")):
            host = urlsplit(url).hostname or ""
            if host:
                return host
    return ""


def _definition(connector: str) -> Any:
    try:
        from ..modules.data import sources

        return sources.get(connector)
    except Exception:  # noqa: BLE001 - a missing definition only means fewer facts
        return None


def _restricted_reason(connector: str) -> str:
    """Why the source's terms keep its data out of a published study ("allow personal use only"), or ""."""
    try:
        from . import data_terms

        t = data_terms.known().get(connector)
    except Exception:  # noqa: BLE001
        return ""
    return f"its terms {t.reason}" if t is not None else ""


# ── the record ──────────────────────────────────────────────────────────────


def derive(manifest: dict[str, Any], read: Reader, *, files: set[str] | None = None) -> dict[str, Any]:
    """The record for a study, from a package's list (``e2er-package.json``) and the study's own files.

    ``manifest`` needs ``contents`` (or ``files`` gives the paths the package holds), ``left_out``,
    ``environment`` and ``study``; ``read`` reads ``reproduce.json``, ``data/data_sources.json``,
    ``code/get_data.py`` and the lock or requirements file.
    """
    from .export import package as pkg

    contents: list[Any] = manifest["contents"] if isinstance(manifest.get("contents"), list) else []
    held = set(files) if files is not None else {str(c.get("path")) for c in contents if isinstance(c, dict)}
    raw_recipe = _json(read, "reproduce.json")
    recipe: dict[str, Any] | None = raw_recipe if isinstance(raw_recipe, dict) else None
    summary: dict[str, Any] = manifest["recipe"] if isinstance(manifest.get("recipe"), dict) else {}
    if summary.get("present") is False:
        recipe = None  # reproduce.json is there but e2er reproduce refuses it (the summary says why)
    env: dict[str, Any] = manifest["environment"] if isinstance(manifest.get("environment"), dict) else {}
    study: dict[str, Any] = manifest["study"] if isinstance(manifest.get("study"), dict) else {}
    left_out = [i for i in manifest.get("left_out") or [] if isinstance(i, dict) and isinstance(i.get("path"), str)]

    out: dict[str, Any] = {"format": FORMAT, "reproducible": recipe is not None}
    if recipe is None:
        why = summary.get("why")
        out["why"] = _str(why) or "the study has no reproduce.json"

    # Software.
    software: dict[str, Any] = {"docker": recipe is not None}
    if _str(study.get("e2er_version")):
        software["e2er"] = _str(study.get("e2er_version"))
    python = _str((recipe or {}).get("python")) or _str(env.get("python"))
    if recipe is not None and python:
        software["python"] = python
    lock = _str(env.get("lock"))
    req = _str((recipe or {}).get("requirements"))
    for rel, hashes in ((lock, bool(env.get("hashes"))), (req, False)):
        if rel and rel in held:
            raw = read(rel)
            if raw is not None:
                software["packages"] = {
                    "file": rel,
                    "count": pinned_count(raw.decode("utf-8", "replace")),
                    "hashes": hashes,
                }
                break
    out["software"] = software

    # What a rerun reads, and how it gets what the package does not hold.
    rfiles: dict[str, Any] = recipe["files"] if recipe is not None and isinstance(recipe.get("files"), dict) else {}
    inputs = {
        str(rfiles.get(i["path"], i["path"])): i
        for i in (recipe or {}).get("inputs") or []
        if isinstance(i, dict) and isinstance(i.get("path"), str)
    }
    steps = [s for s in (recipe or {}).get("steps") or [] if isinstance(s, dict)]

    def runs(script: str) -> bool:
        return any(isinstance(s.get("run"), list) and any(Path(str(a)).name == script for a in s["run"]) for s in steps)

    get_data = next((p for p in sorted(held) if Path(p).name == "get_data.py"), "") if runs("get_data.py") else ""
    reloads: list[dict[str, Any]] | None = None
    if get_data:
        raw = read(get_data)
        reloads = get_data_reloads(raw.decode("utf-8", "replace")) if raw is not None else None
    reload_tables = {str(r["table"]) for r in reloads or [] if r.get("table")}
    reload_files = {str(r.get("file") or r.get("save_to") or "") for r in reloads or []} - {""}
    db_in = "data/data.db" in held or "data.db" in held

    def input_of(rel: str) -> dict[str, Any] | None:
        return inputs.get(rel) or inputs.get(Path(rel).name)

    def left_item(load: dict[str, Any]) -> dict[str, Any] | None:
        saved, table = _str(load.get("saved_to")), _str(load.get("table"))
        for item in left_out:
            if saved and item["path"] == saved:
                return item
            if table and Path(item["path"]).name == "data.db":
                return item
        return None

    def placement(load: dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
        """shipped, reloaded, not_needed or missing; and the left-out entry that holds the load's data."""
        saved, table = _str(load.get("saved_to")), _str(load.get("table"))
        item = left_item(load)
        if (saved and saved in held) or (table and db_in):
            return "shipped", item
        if (table and table in reload_tables) or (saved and saved in reload_files):
            return "reloaded", item
        if item is not None:
            if table and table in (item.get("not_read") or []):
                return "not_needed", item
            if table and table in (item.get("loads") or []):
                return "reloaded", item
            if item.get("needed") is False:
                return "not_needed", item
            how = item.get("rebuilt_by") if isinstance(item.get("rebuilt_by"), dict) else None
            if how and Path(str(how.get("by") or "")).name == "get_data.py":
                return "reloaded", item
            return ("missing" if reloads is not None or not get_data else "reloaded"), item
        # Not in the package and not declared left out (an export that kept the file out).
        needed = bool(saved and input_of(saved)) or bool(table and input_of("data.db"))
        if not needed:
            return "not_needed", None
        if get_data and reloads is None:
            return "reloaded", None  # a get_data.py of the study's own, as `e2er reproduce` reads it
        return "missing", None

    loads_doc = _json(read, "data/data_sources.json")
    loads = [x for x in (loads_doc or {}).get("loads") or [] if isinstance(x, dict) and _str(x.get("connector"))]
    groups: dict[str, list[tuple[dict[str, Any], str, dict[str, Any] | None]]] = {}
    for load in loads:
        state, item = placement(load)
        groups.setdefault(_str(load["connector"]), []).append((load, state, item))

    sources: list[dict[str, Any]] = []
    accounts: list[dict[str, Any]] = []
    for connector, rows in groups.items():
        sources.append(_source_entry(connector, rows))
        acc = _account(connector, any(state == "reloaded" for _l, state, _i in rows))
        if acc:
            accounts.append(acc)
    out["accounts"] = accounts

    reloaded = [s for s in sources if s.get("reloaded")]
    data: dict[str, Any] = {
        "network": bool(reloaded) or any(_is_reload_input(i) for i in inputs.values()),
        "shipped": sorted(p for p in held if pkg._is_data(p)),
        "left_out": [
            {
                "path": i["path"],
                "reason": _str(i.get("reason")),
                **({"kind": i["kind"]} if _str(i.get("kind")) else {}),
                "needed": i.get("needed") is not False,
            }
            for i in left_out
        ],
    }
    if get_data and data["network"]:
        data["reload_step"] = get_data
    out["data"] = data
    out["sources"] = sources
    return out


def _is_reload_input(i: dict[str, Any]) -> bool:
    return isinstance(i.get("reload"), str) and bool(i["reload"])


def _source_entry(connector: str, rows: list[tuple[dict[str, Any], str, dict[str, Any] | None]]) -> dict[str, Any]:
    definition = _definition(connector)
    first = rows[0][0]

    def uniq(values: list[str]) -> list[str]:
        seen: list[str] = []
        for v in values:
            if v and v not in seen:
                seen.append(v)
        return seen

    name = (definition.label if definition is not None else "") or _OUTSIDE_KIT.get(connector, ("",))[0]
    loads = [load for load, _s, _i in rows]
    entry: dict[str, Any] = {
        "connector": connector,
        "name": name or _str(first.get("dataset")) or connector,
        "dataset": uniq([_str(x.get("dataset")) for x in loads])[:3],
        "versions": uniq([_str(x.get("version")) for x in loads])[:10],
        "loaded": sorted(uniq([_str(x.get("retrieved_at"))[:10] for x in loads])),
        "loads": len(loads),
    }
    terms = uniq([_str(x.get("terms_summary")) for x in loads]) or (
        [definition.terms_summary] if definition is not None and definition.terms_summary else []
    )
    if terms:
        entry["terms"] = terms[0]
    url = uniq([_str(x.get("terms")) for x in loads if _str(x.get("terms")).startswith("https://")])
    if url or (definition is not None and definition.terms_url):
        entry["terms_url"] = url[0] if url else definition.terms_url
    cites = uniq([_str(x.get("citation")) for x in loads])
    if cites:
        entry["citation"] = cites[0] if len(cites) == 1 else cites[0]
        if len(cites) > 1:
            entry["citations"] = len(cites)
    states = [s for _l, s, _i in rows]
    entry["shipped"] = states.count("shipped")
    entry["reloaded"] = states.count("reloaded")
    entry["not_needed"] = states.count("not_needed")
    entry["missing"] = states.count("missing")
    if entry["reloaded"]:
        hosts = uniq([_host(load) for load, s, _i in rows if s == "reloaded"])
        if hosts:
            entry["from"] = hosts[:5]
    reasons = uniq(
        [
            f"{i['path']}: {_str(i.get('reason'))}"
            for _l, s, i in rows
            if i is not None and s != "shipped" and _str(i.get("reason"))
        ]
    )
    if not reasons and entry["shipped"] < len(rows):
        why = _restricted_reason(connector)
        if why:
            reasons = [why]
    if reasons:
        entry["left_out_because"] = reasons[:3]
    prints = [
        (load.get("fingerprint") or {}).get("sha256")
        for load in loads
        if isinstance(load.get("fingerprint"), dict) and isinstance((load.get("fingerprint") or {}).get("sha256"), str)
    ]
    entry["fingerprints"] = [p if str(p).startswith("sha256:") else f"sha256:{p}" for p in prints][:50]
    entry["fingerprints_missing"] = len(loads) - len(prints)
    return entry


def _account(connector: str, reloaded: bool) -> dict[str, Any] | None:
    definition = _definition(connector)
    if definition is not None:
        key = definition.key
        if key is None:
            return None
        return {
            "source": connector,
            "name": definition.label,
            "setting": key.env,
            "how": key.how_to_get,
            "optional": bool(key.optional),
            "needed": reloaded and not key.optional,
        }
    name, setting, how = _OUTSIDE_KIT.get(connector, ("", None, ""))
    if not setting:
        return None
    return {"source": connector, "name": name, "setting": setting, "how": how, "optional": False, "needed": reloaded}


# ── the record of a package, of a folder ────────────────────────────────────


def of_package(path: Path) -> tuple[dict[str, Any] | None, bool]:
    """(the record, whether it was derived now) of a .e2er file; (None, False) when the file has no list."""
    from .export import package as pkg

    try:
        manifest = pkg.read_manifest(path)
    except pkg.PackageError:
        return None, False
    rec = manifest.get(KEY)
    if isinstance(rec, dict) and rec.get("format") == FORMAT:
        return rec, False
    try:
        return derive(manifest, lambda rel: pkg.read_member(path, rel, limit=8 * 1024 * 1024)), True
    except Exception:  # noqa: BLE001 - an old or odd package: nothing to say beats a traceback
        return None, False


def e2er_json_of_package(path: Path) -> dict[str, Any] | None:
    from .export import package as pkg

    raw = pkg.read_member(path, "e2er.json", limit=32 * 1024 * 1024)
    if raw is None:
        return None
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def for_folder(folder: Path, *, host: str | None = None, max_file_bytes: int | None = None) -> dict[str, Any]:
    """The record of an exported study folder, with the files ``e2er pack`` would leave out (``host``: as for GitHub).

    For ``e2er publish``: the packages are pinned by the study's requirements file here (the lock is made
    when the package is built).
    """
    from .export import package as pkg

    folder = Path(folder)
    files = pkg.study_files(folder)
    recipe, why = pkg._recipe(folder)
    left = pkg.left_out_data(folder, files, recipe, no_data=False, host=host, max_file_bytes=max_file_bytes)
    prov = pkg._read_json(folder / "provenance.json") or {}
    run: dict[str, Any] = prov["run"] if isinstance(prov.get("run"), dict) else {}
    manifest = {
        "left_out": left,
        "environment": {"python": str((recipe or {}).get("python") or "")},
        "study": {"e2er_version": str(run.get("e2er_version") or "")},
        # The reason names the folder by its path on this computer: "." instead (the description leaves this computer).
        "recipe": {
            "present": recipe is not None,
            "why": why.replace(str(folder.resolve()), ".").replace(str(folder), "."),
        },
    }
    out = {p for p in files if p not in {i["path"] for i in left}}

    def read(rel: str) -> bytes | None:
        p = files.get(rel)
        try:
            return p.read_bytes() if p is not None and p.stat().st_size <= 32 * 1024 * 1024 else None
        except OSError:
            return None

    return derive(manifest, read, files=out)


def rerun_of(description: dict[str, Any] | None) -> dict[str, Any] | None:
    """The reproduction before publishing, from a description's ``verification`` list (None: none recorded)."""
    for v in (description or {}).get("verification") or []:
        if isinstance(v, dict) and v.get("check") == "reproduction" and isinstance(v.get("reproduction"), dict):
            return {"status": v.get("status"), **v["reproduction"]}
    return None


# ── words ───────────────────────────────────────────────────────────────────


def _plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def duration(seconds: float) -> str:
    """A duration in plain words: "about 25 minutes", "about 40 seconds"."""
    s = max(0.0, float(seconds))
    if s < 90:
        return f"about {max(1, round(s))} seconds"
    if s < 90 * 60:
        return f"about {round(s / 60)} minutes"
    return f"about {s / 3600:.1f} hours".replace(".0 hours", " hours")


def short_fingerprint(fp: str) -> str:
    return fp.removeprefix("sha256:")[:12]


def software_lines(rec: dict[str, Any]) -> list[str]:
    sw = rec.get("software") or {}
    parts = []
    if sw.get("docker"):
        parts.append("Docker (`e2er reproduce` runs the study's code in a Docker sandbox)")
    if sw.get("e2er"):
        parts.append(f"e2er {sw['e2er']} or later (the version that exported the study)")
    if sw.get("python"):
        minor = re.match(r"^\d+\.\d+$", str(sw["python"]))
        image = f" (the sandbox's image python:{sw['python']}-slim)" if minor else ""
        parts.append(f"Python {sw['python']}{image}")
    pk = sw.get("packages") if isinstance(sw.get("packages"), dict) else None
    if pk:
        hashes = " with their hashes" if pk.get("hashes") else ""
        parts.append(f"{_plural(int(pk.get('count') or 0), 'package')} pinned{hashes} in {pk.get('file')}")
    return parts


def accounts_line(rec: dict[str, Any]) -> str:
    accs = [a for a in rec.get("accounts") or [] if isinstance(a, dict)]
    needed = [a for a in accs if a.get("needed")]
    if needed:
        line = "; ".join(f"{a.get('name')}: {a.get('setting')} ({a.get('how')})" for a in needed)
        return (
            f"{line}. `e2er reproduce` passes no API key or token to the study's code, so the step that loads "
            "these data again cannot use one"
        )
    shipped = [a for a in accs if not a.get("optional")]
    if shipped:
        names = ", ".join(str(a.get("name")) for a in shipped)
        return f"none (the study loaded {names} with a key; a rerun does not load those data again)"
    return "none"


def data_lines(rec: dict[str, Any]) -> list[str]:
    data = rec.get("data") or {}
    out = []
    shipped = data.get("shipped") or []
    if shipped:
        out.append(
            f"with the package: {', '.join(shipped[:6])}"
            + (f" and {len(shipped) - 6} more" if len(shipped) > 6 else "")
        )
    for s in rec.get("sources") or []:
        if s.get("reloaded"):
            where = f" ({', '.join(s['from'])})" if s.get("from") else ""
            out.append(f"loaded again from {s.get('name')}{where} ({_plural(int(s['reloaded']), 'load')})")
        if s.get("missing"):
            out.append(
                f"{s.get('name')}: {_plural(int(s['missing']), 'load')} the package lacks and no step loads again"
            )
    if data.get("network"):
        step = f" while {data['reload_step']} runs" if data.get("reload_step") else ""
        out.append(f"network access: needed{step}; the other steps run without it")
    elif rec.get("reproducible"):
        out.append("network access: not needed")
    return out


def effort_line(package_bytes: int | None, rerun: dict[str, Any] | None) -> str:
    from .export import package as pkg

    parts = []
    if package_bytes:
        parts.append(f"downloading the package: {pkg.human_size(int(package_bytes))}")
    if rerun and isinstance(rerun.get("seconds"), int | float) and rerun.get("reproduced"):
        text = f"the rerun before publishing took {duration(rerun['seconds'])}"
        rs = rerun.get("reload_seconds")
        if isinstance(rs, int | float) and rs >= 60 and rs >= 0.5 * float(rerun["seconds"]):
            names = rerun.get("reloaded_sources") or []
            src = f" from {', '.join(map(str, names))}" if names else ""
            text += f", mostly loading data again{src}"
        parts.append(text)
    return "; ".join(parts)


def rerun_line(rerun: dict[str, Any] | None) -> str:
    if not rerun:
        return ""
    day = str(rerun.get("date") or "")[:10]
    ver = rerun.get("e2er_version")
    if rerun.get("skipped"):
        return f"not reproduced before publishing ({rerun['skipped']})"
    if rerun.get("nothing_to_run"):
        return "nothing to run again before publishing"
    if rerun.get("reproduced"):
        return f"reproduced before publishing on {day} with e2er {ver}" + (
            f": {rerun['verdict']}" if rerun.get("verdict") else ""
        )
    return ""


def summary_lines(rec: dict[str, Any], *, package_bytes: int | None = None, rerun: dict[str, Any] | None = None,
                  derived: bool = False) -> list[str]:  # fmt: skip
    """The short "Required for reproduction" block of ``e2er inspect`` and ``e2er fetch``."""
    from .safe_text import printable

    lines = ["Required for reproduction" + (" (derived now from the package's files)" if derived else "") + ":"]
    if not rec.get("reproducible"):
        lines.append(f"  not possible: {rec.get('why')}")
    sw = software_lines(rec)
    if sw:
        lines.append("  Software: " + "; ".join(sw))
    lines.append("  Accounts and keys: " + accounts_line(rec))
    for i, d in enumerate(data_lines(rec)):
        lines.append(("  Data: " if i == 0 else "        ") + d)
    effort = effort_line(package_bytes, rerun)
    if effort:
        lines.append("  Effort: " + effort)
    last = rerun_line(rerun)
    lines.append("  Last rerun: " + (last or "none recorded in the package"))
    srcs = [s for s in rec.get("sources") or [] if isinstance(s, dict)]
    lines.append("")
    lines.append("Data and licences:")
    if not srcs:
        lines.append("  no data load recorded (data/data_sources.json lists none)")
    for s in srcs:
        lines.append("  " + _source_line(s))
        if s.get("terms"):
            lines.append(f"    terms: {s['terms']}" + (f" ({s['terms_url']})" if s.get("terms_url") else ""))
        if s.get("citation"):
            lines.append(f"    cite: {_cut(s['citation'], 240)}{_more_citations(s)}")
        fp = s.get("fingerprints") or []
        if fp:
            more = f" and {len(fp) - 3} more" if len(fp) > 3 else ""
            lines.append(f"    fingerprint: {', '.join(short_fingerprint(f) for f in fp[:3])}{more}")
        elif s.get("loads"):
            lines.append("    fingerprint: not recorded (e2er records it since 0.21)")
    if any(s.get("fingerprints") for s in srcs):
        lines.append(f"  ({FINGERPRINT_WORDS})")
    return [printable(x, newlines=False) for x in lines]


def _more_citations(s: dict[str, Any]) -> str:
    n = s.get("citations")
    return f" (the first of {n} citations; data/data_sources.json lists each)" if isinstance(n, int) and n > 1 else ""


def _cut(text: str, n: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def placement_words(s: dict[str, Any]) -> str:
    """Where a source's data are: "with the package", "left out (…); loaded again from …"."""
    n = int(s.get("loads") or 0)
    shipped, reloaded = int(s.get("shipped") or 0), int(s.get("reloaded") or 0)
    if shipped == n:
        return "with the package"
    why = "; ".join(s.get("left_out_because") or [])
    parts = []
    if shipped:
        parts.append(f"{shipped} of {n} loads with the package")
    parts.append("left out" + (f" ({why})" if why else ""))
    if reloaded:
        parts.append("a rerun loads " + ("them" if reloaded == n - shipped else f"{reloaded} of them") + " again")
    if s.get("not_needed"):
        parts.append(f"{_plural(int(s['not_needed']), 'load')} the study's code does not read")
    if s.get("missing"):
        parts.append(f"{_plural(int(s['missing']), 'load')} no step loads again")
    return "; ".join(parts)


def _source_line(s: dict[str, Any]) -> str:
    head = str(s.get("name"))
    if s.get("versions"):
        head += f", version {', '.join(s['versions'][:3])}"
    loaded = s.get("loaded") or []
    if loaded:
        head += f", loaded {loaded[0]}" + (f" to {loaded[-1]}" if len(loaded) > 1 else "")
    return f"{head}: {placement_words(s)}"


def markdown(rec: dict[str, Any], *, package_bytes: int | None = None, rerun: dict[str, Any] | None = None) -> str:
    """The two sections as Markdown, for README files."""
    lines = ["## Required for reproduction", ""]
    if not rec.get("reproducible"):
        lines += [f"Not possible: {rec.get('why')}.", ""]
    sw = software_lines(rec)
    if sw:
        lines.append("- **Software:** " + "; ".join(sw) + ".")
    lines.append("- **Accounts and keys:** " + accounts_line(rec) + ".")
    data = data_lines(rec)
    if data:
        lines.append("- **Data:** " + "; ".join(data) + ".")
    effort = effort_line(package_bytes, rerun)
    if effort:
        lines.append(f"- **Effort:** {effort}.")
    last = rerun_line(rerun)
    if last:
        lines.append(f"- **Last rerun:** {last}.")
    lines += ["", "## Data and licences", ""]
    srcs = [s for s in rec.get("sources") or [] if isinstance(s, dict)]
    if not srcs:
        lines += ["The study records no data load (data/data_sources.json lists none).", ""]
        return "\n".join(lines)
    lines += [
        "| Source | Version | Loaded | Terms | In the package | Citation | Fingerprint |",
        "|---|---|---|---|---|---|---|",
    ]

    def cell(x: Any) -> str:
        return " ".join(str(x).split()).replace("|", "\\|") or "not recorded"

    for s in srcs:
        loaded = s.get("loaded") or []
        when = (loaded[0] + (f" to {loaded[-1]}" if len(loaded) > 1 else "")) if loaded else ""
        terms = s.get("terms") or ""
        if s.get("terms_url"):
            terms = f"{terms} ({s['terms_url']})".strip()
        fp = s.get("fingerprints") or []
        prints = ", ".join(f"`{short_fingerprint(f)}`" for f in fp[:3]) + (
            f" and {len(fp) - 3} more" if len(fp) > 3 else ""
        )
        lines.append(
            "| "
            + " | ".join(
                [
                    cell(s.get("name")),
                    cell(", ".join(s.get("versions") or [])),
                    cell(when),
                    cell(terms),
                    cell(placement_words(s)),
                    cell(_cut(s.get("citation") or "", 400) + _more_citations(s) if s.get("citation") else ""),
                    prints or "not recorded",
                ]
            )
            + " |"
        )
    lines += [
        "",
        "A fingerprint is a SHA-256 of the rows a load returned: the same rows give the same fingerprint, so "
        "`e2er reproduce` can tell whether a source now returns other data.",
        "",
    ]
    return "\n".join(lines)


def package_readme(rec: dict[str, Any]) -> str:
    """``e2er-package/README.md``: the two sections, written by ``e2er pack`` from the record in e2er-package.json."""
    head = [
        "# What a reproduction of this study needs",
        "",
        "Written by `e2er pack` from the study's own records (reproduce.json, data/data_sources.json, the package's "
        "list of files). The same facts are in `e2er-package.json` under `reproduction_requirements`. A fact no "
        "record holds is left out.",
        "",
    ]
    return "\n".join(head) + "\n" + markdown(rec)


def print_summary(path: Path, *, size: int | None = None) -> None:
    """Print the "Required for reproduction" block of a .e2er file (``inspect``, ``fetch``); silent when it has none."""
    rec, derived = of_package(path)
    if rec is None:
        return
    rerun = rerun_of(e2er_json_of_package(path))
    for line in summary_lines(rec, package_bytes=size, rerun=rerun, derived=derived):
        print(line)
