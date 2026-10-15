"""One file that holds a whole study: the ``.e2er`` package.

``e2er pack`` writes an exported study folder into a single file,
``<slug>.e2er``: a zip archive (deflate) with ``e2er-package.json`` at its
root. ``e2er verify``, ``e2er reproduce``, ``e2er unpack`` and ``e2er inspect``
read it. The format is described in docs/STRUCTURED_EXPORT_SPEC.md
("The .e2er package"); in short:

- **Everything the folder holds**: paper, code, results, design, reviews,
  ``provenance.json``, ``reproduce.json`` and the data, unless a source's terms
  keep the data out (then the recipe's ``get_data.py`` and data-preparation
  steps rebuild them when the package is reproduced) or ``--no-data`` asks for
  none.
- **The environment, pinned**: ``e2er-package/requirements.lock.txt`` holds
  every package (the study's own and what they need) at one version, with
  the SHA-256 of each file the installer may use, resolved as of the day the
  study was exported. Offline it cannot be resolved; the package then carries
  the recipe's own pins and says so.
- **Optionally the installers' files** (``--offline``):
  ``e2er-package/wheels/<platform>/`` holds the wheels for this computer, so a
  rerun on the same kind of computer installs without the internet.
- **A manifest** listing every file with its SHA-256 and size, and a
  fingerprint over that list. The same export packs to the same bytes (sorted
  entries, fixed timestamps, no packing date), so two people can compare
  fingerprints.

Opening a package never runs anything: names are checked (no absolute path,
no ``..``, no link), sizes are capped, and every file is checked against the
manifest before any command reads the folder.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unicodedata
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

FORMAT = "e2er-package/1"
MANIFEST = "e2er-package.json"
#: Files the package adds to the study folder (never part of the study's own evidence).
PACKAGE_DIR = "e2er-package"
LOCK = f"{PACKAGE_DIR}/requirements.lock.txt"
WHEELS = f"{PACKAGE_DIR}/wheels"
SUFFIX = ".e2er"

#: The timestamp every entry carries (the earliest a zip can hold), so the bytes do not depend on when it was packed.
_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
#: Limits when a package is opened: all files together, one file, the number of files, the manifest.
MAX_TOTAL_BYTES = int(os.environ.get("E2ER_PACKAGE_MAX_BYTES", str(64 * 1024**3)))
MAX_ENTRIES = 200_000
MAX_MANIFEST_BYTES = 32 * 1024 * 1024
#: A file that unpacks to more than this many times its packed size is refused (a "zip bomb").
MAX_RATIO = 1000
#: Above this, the wheels make the package large enough to say so.
LARGE_WHEELS = 200 * 1024 * 1024
#: Files that are data, as the recipe counts them (reproduce_recipe.DATA_SUFFIXES).
_DATA_SUFFIXES = frozenset({".db", ".sqlite", ".sqlite3", ".csv", ".tsv", ".parquet", ".xlsx", ".jsonl", ".dta"})
#: Records about the data that are not the data (kept in a package without data).
_DATA_RECORDS = frozenset({"data/data_sources.json", "data/data_dictionary.json", "data/data_summary.md"})


class PackageError(Exception):
    """The package cannot be written or opened. The message is shown as is."""


# ── helpers ──────────────────────────────────────────────────────────────────


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def fingerprint(contents: list[dict[str, Any]]) -> str:
    """The package fingerprint: SHA-256 over the contents list (path, sha256, bytes; sorted by path)."""
    rows = sorted(
        ({"path": c["path"], "sha256": c["sha256"], "bytes": c["bytes"]} for c in contents), key=lambda c: c["path"]
    )
    return "sha256:" + hashlib.sha256(_canonical(rows)).hexdigest()


def is_package(path: Path) -> bool:
    """A file that is (or claims to be) a .e2er package: by its ending, else a zip with the manifest."""
    path = Path(path)
    if not path.is_file():
        return False
    if path.suffix.lower() == SUFFIX:
        return True
    try:
        with zipfile.ZipFile(path) as zf:
            return MANIFEST in zf.namelist()
    except (zipfile.BadZipFile, OSError):
        return False


def human_size(n: int) -> str:
    size = float(n)
    for unit in ("bytes", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{int(size)} bytes" if unit == "bytes" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{n} bytes"


def platform_key(python_minor: str) -> str:
    """The folder the wheels for this computer go in: ``darwin-arm64-py3.12``."""
    machine = (platform.machine() or "unknown").lower().replace("amd64", "x86_64").replace("aarch64", "arm64")
    return f"{sys.platform}-{machine}-py{python_minor}"


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# ── what goes in ─────────────────────────────────────────────────────────────


def _data_suffix(rel: str) -> bool:
    return rel not in _DATA_RECORDS and Path(rel).suffix.lower() in _DATA_SUFFIXES


def _is_data(rel: str) -> bool:
    """A data file of the study: under data/ (the replication log's CSV is a record, not data)."""
    return rel.startswith("data/") and _data_suffix(rel)


def _input_files(recipe: dict[str, Any] | None) -> set[str]:
    """The folder's files that the recipe lists as inputs (the data the code reads), wherever they are."""
    if not recipe:
        return set()
    files = recipe.get("files") or {}
    paths = {i.get("path") for i in recipe.get("inputs") or [] if isinstance(i, dict)}
    return {str(files.get(p, p)) for p in paths if isinstance(p, str)}


def _skipped(rel: str) -> bool:
    """Files of the folder a package never carries: local records of publishing, an earlier package's files."""
    from .bundle_files import never_exported

    parts = rel.split("/")
    return rel == MANIFEST or parts[0] == PACKAGE_DIR or parts[0] == ".e2er" or any(never_exported(p) for p in parts)


def study_files(folder: Path) -> dict[str, Path]:
    """The study's files (relative path -> file), read as verify reads the folder; refuses links."""
    from .bundle_files import walk

    listing = walk(folder)
    if listing.symlinks:
        raise PackageError(
            f"the folder holds symbolic links ({', '.join(listing.symlinks[:3])}); a package holds copies only. "
            "Export the study again, or replace the links with the files."
        )
    if listing.special:
        raise PackageError(f"the folder holds files that are not regular files ({', '.join(listing.special[:3])})")
    return {rel: p for rel, p in sorted(listing.files.items()) if not _skipped(rel)}


def _recipe(folder: Path) -> tuple[dict[str, Any] | None, str]:
    """The folder's reproduce.json, checked, or (None, why there is none)."""
    from .. import reproduce as rp

    try:
        return rp.load_recipe(folder), ""
    except rp.RecipeError as e:
        return None, str(e)


def _run_paths(recipe: dict[str, Any], rel: str) -> set[str]:
    files = recipe.get("files") or {}
    return {dst for dst, src in files.items() if src == rel} or {rel}


def _rebuilt(recipe: dict[str, Any] | None, rel: str, plan: list[dict[str, Any]]) -> dict[str, Any] | None:
    """How a rerun gets ``rel`` back when the package leaves it out: loaded again, or built again by a script."""
    if not recipe:
        return None
    files = recipe.get("files") or {}
    run_paths = _run_paths(recipe, rel)
    for item in recipe.get("inputs") or []:
        if not (isinstance(item, dict) and item.get("path") in run_paths):
            continue
        if isinstance(item.get("reload"), str):
            return {"by": f"code/{Path(item['reload']).name}", "source": str(item.get("source") or "")}
        if isinstance(item.get("rebuild"), str):
            return {"by": str(files.get(item["rebuild"], item["rebuild"])), "source": "", "kind": "rebuild"}
    for p in plan:
        if p["path"] in run_paths:
            return {"by": p["from"], "source": "", "kind": "rebuild"}
    return None


def rebuild_for(folder: Path, recipe: dict[str, Any] | None, left_out: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The steps a rerun of the package needs to build left-out derived inputs again (derived_data.rebuild_plan)."""
    if not recipe:
        return []
    from ..derived_data import derived, rebuild_plan

    paths = {i["path"] for i in left_out}
    found = [d for d in derived(folder) if d.path in paths]
    return rebuild_plan(folder, recipe, found) if found else []


def left_out_data(
    folder: Path, files: dict[str, str] | dict[str, Path], recipe: dict[str, Any] | None, *, no_data: bool
) -> list[dict[str, Any]]:
    """The data files the package leaves out, each with why and how a rerun rebuilds it (or that it cannot)."""
    from .. import data_terms

    out: dict[str, dict[str, Any]] = {}
    for use in data_terms.uses(folder):
        for rel in use.files:
            if rel in files and _is_data(rel):
                out[rel] = {"path": rel, "reason": use.reason(rel), "source": use.terms.connector}
    if no_data:
        inputs = _input_files(recipe)
        for rel in files:
            if (_is_data(rel) or (rel in inputs and _data_suffix(rel))) and rel not in out:
                out[rel] = {"path": rel, "reason": "packed with --no-data"}
    inputs = _input_files(recipe)
    plan = rebuild_for(folder, recipe, list(out.values()))
    for rel, item in out.items():
        item["rebuilt_by"] = _rebuilt(recipe, rel, plan)
        # Whether the study's code reads it: a file no step reads is not needed for a rerun.
        item["needed"] = rel in inputs
    return [out[k] for k in sorted(out)]


def rerun_words(item: dict[str, Any]) -> str:
    """What a rerun of the package does about a left-out file, in plain words."""
    how = item.get("rebuilt_by")
    if isinstance(how, dict) and how.get("kind") == "rebuild":
        return f"`e2er reproduce` builds it again with {how['by']} from the data it loads again"
    if isinstance(how, dict):
        return f"`e2er reproduce` loads it again with {how['by']}" + (
            f" from {how['source']}" if how.get("source") else ""
        )
    if item.get("needed") is False:
        return "the study's code does not read it, so a rerun does not need it"
    return "a rerun cannot rebuild it"


# ── the environment ──────────────────────────────────────────────────────────

#: (requirements file, python "3.12", resolve as of "2026-10-15") -> (lock text or None, a note in plain words).
Locker = Callable[[Path, str, str], tuple[str | None, str]]
#: (requirements or lock file, python "3.12", destination folder) -> (wheel files, a note in plain words).
Downloader = Callable[[Path, str, Path], tuple[list[Path], str]]


def uv_lock(requirements: Path, python_minor: str, as_of: str) -> tuple[str | None, str]:
    """Every package at one version with the SHA-256 of its files: ``uv pip compile --generate-hashes``."""
    uv = shutil.which("uv")
    if not uv:
        return None, "uv is not installed, so the packages the study needs could not be resolved with their hashes"
    with tempfile.TemporaryDirectory(prefix="e2er-lock-") as td:
        out = Path(td) / "lock.txt"
        cmd = [
            uv,
            "pip",
            "compile",
            str(requirements),
            "--quiet",
            "--generate-hashes",
            "--universal",
            "--no-header",
            "--no-annotate",
            "--python-version",
            python_minor,
            "-o",
            str(out),
        ]
        if as_of:
            cmd += ["--exclude-newer", as_of]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        except (OSError, subprocess.SubprocessError) as e:
            return None, f"the packages could not be resolved ({e})"
        if proc.returncode != 0 or not out.is_file():
            tail = (proc.stderr or proc.stdout).strip().splitlines()[-1:] or ["no output"]
            return None, f"the packages could not be resolved (offline, or a pin has no release): {tail[0]}"
        return out.read_text(encoding="utf-8"), ""


def _pip_command() -> list[str] | None:
    import importlib.util

    if importlib.util.find_spec("pip") is not None:
        return [sys.executable, "-m", "pip"]
    uv = shutil.which("uv")
    return [uv, "tool", "run", "--from", "pip", "pip"] if uv else None


def pip_download(requirements: Path, python_minor: str, dest: Path) -> tuple[list[Path], str]:
    """The wheels for this computer: ``pip download --only-binary=:all:`` of the pinned set."""
    pip = _pip_command()
    if pip is None:
        return [], "neither pip nor uv is installed, so no wheels were downloaded"
    dest.mkdir(parents=True, exist_ok=True)
    locked = "--hash=" in requirements.read_text(encoding="utf-8", errors="replace")
    cmd = [
        *pip,
        "download",
        "--quiet",
        "--only-binary=:all:",
        "--python-version",
        python_minor,
        "--dest",
        str(dest),
        "-r",
        str(requirements),
    ]
    if locked:
        cmd.append("--no-deps")  # the lock lists every package already
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    except (OSError, subprocess.SubprocessError) as e:
        return [], f"the wheels could not be downloaded ({e})"
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout).strip().splitlines()[-1:] or ["no output"]
        return [], f"the wheels could not be downloaded (a package may have no wheel for this computer): {tail[0]}"
    return sorted(dest.glob("*.whl")), ""


def _as_of(prov: dict[str, Any]) -> str:
    """The day after the export (resolve packages as they were then), from provenance.json's ``exported_at``."""
    raw = str((prov.get("run") or {}).get("exported_at") or "")
    m = re.match(r"^(\d{4})-?(\d{2})-?(\d{2})", raw)
    if not m:
        return ""
    try:
        return (date(int(m[1]), int(m[2]), int(m[3])) + timedelta(days=1)).isoformat()
    except ValueError:
        return ""


# ── the study, in a few fields ───────────────────────────────────────────────


def _authors(folder: Path) -> list[str]:
    doc = _read_json(folder / "e2er.json")
    names: list[str] = []
    if isinstance(doc, dict):
        for a in doc.get("authors") or doc.get("creators") or []:
            if isinstance(a, dict):
                name = a.get("name") or a.get("github") or a.get("orcid")
                if name:
                    names.append(str(name))
            elif isinstance(a, str):
                names.append(a)
    if names:
        return names
    tex = folder / "paper" / "paper.tex"
    if tex.is_file():
        m = re.search(r"\\author\{(.+?)\}\s*\n", tex.read_text(encoding="utf-8", errors="replace"), re.S)
        if m:
            text = re.sub(r"\\(thanks|footnote)\{[^}]*\}", "", m.group(1))
            parts = re.split(r"\\and|\\\\|,", text)
            names = [re.sub(r"\s+", " ", re.sub(r"[{}\\]", "", p)).strip() for p in parts]
            return [n for n in names if n and "e2er" not in n.lower()]
    return []


def _study(folder: Path, prov: dict[str, Any]) -> dict[str, Any]:
    from ..research_object import _question_and_title

    question, title = _question_and_title(folder)
    tex = folder / "paper" / "paper.tex"
    if tex.is_file():  # the paper's own title, when abstract.tex has none (README's heading is cut short)
        m = re.search(r"\\title\{(.+?)\}\s*\n", tex.read_text(encoding="utf-8", errors="replace"), re.S)
        if m and (not title or title.endswith("...") or title == question):
            title = re.sub(r"\s+", " ", m.group(1).replace("\\\\", " ").replace("--", "–")).strip()
    run: dict[str, Any] = prov["run"] if isinstance(prov.get("run"), dict) else {}
    return {
        "id": str(run.get("paper_id") or ""),
        "title": title,
        "question": question,
        "authors": _authors(folder),
        "folder": folder.name,
        "template": str(run.get("template") or ""),
        "exported_at": str(run.get("exported_at") or ""),
        "e2er_version": str(run.get("e2er_version") or ""),
        "purpose": str(run.get("purpose") or ""),
    }


def _recipe_summary(recipe: dict[str, Any] | None, why: str) -> dict[str, Any]:
    if recipe is None:
        return {"present": False, "why": why}
    from .. import reproduce as rp

    return {
        "present": True,
        "python": str(recipe.get("python") or ""),
        "requirements": recipe.get("requirements"),
        "steps": [
            {
                "run": rp.step_argv(s),
                "about": str(s.get("about") or ""),
                **({"when_missing": s["when_missing"]} if s.get("when_missing") else {}),
            }
            for s in recipe.get("steps") or []
        ],
        "inputs": [
            {"path": i.get("path"), "source": i.get("source"), "reload": i.get("reload")}
            for i in recipe.get("inputs") or []
            if isinstance(i, dict)
        ],
        "compare": [c.get("published") for c in recipe.get("compare") or [] if isinstance(c, dict)],
    }


# ── writing ──────────────────────────────────────────────────────────────────


@dataclass
class Packed:
    path: Path
    manifest: dict[str, Any]
    size: int
    notes: list[str] = field(default_factory=list)


def default_path(folder: Path) -> Path:
    return folder.parent / f"{folder.name}{SUFFIX}"


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=_ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3  # Unix: the permission bits below are read as such everywhere
    info.external_attr = (stat.S_IFREG | 0o644) << 16
    return info


def _write_zip(target: Path, manifest_bytes: bytes, entries: list[tuple[str, Path]]) -> None:
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        zf.writestr(_zip_info(MANIFEST), manifest_bytes, compresslevel=6)
        for name, src in entries:
            info = _zip_info(name)
            with src.open("rb") as fin, zf.open(info, "w", force_zip64=src.stat().st_size > (1 << 31)) as fout:
                shutil.copyfileobj(fin, fout, 1 << 20)


def build(
    folder: Path,
    out: Path | None = None,
    *,
    offline: bool = False,
    no_data: bool = False,
    locker: Locker | None = None,
    downloader: Downloader | None = None,
) -> Packed:
    """Write the exported study ``folder`` into one ``.e2er`` file; returns where and what it holds."""
    from ... import __version__

    folder = Path(folder).expanduser().resolve()
    if not folder.is_dir():
        raise PackageError(f"{folder} is not a folder")
    if not (folder / "provenance.json").is_file():
        raise PackageError(
            f"{folder} has no provenance.json: it is not a study folder exported by e2er (`e2er export`)."
        )
    target = Path(out).expanduser() if out else default_path(folder)
    if target.is_dir():
        target = target / f"{folder.name}{SUFFIX}"
    target = target.resolve()
    if target.is_relative_to(folder):
        raise PackageError("the package cannot be written into the folder it packs; choose another place with -o")

    prov = _read_json(folder / "provenance.json") or {}
    files = study_files(folder)
    recipe, why = _recipe(folder)
    left_out = left_out_data(folder, files, recipe, no_data=no_data)
    for item in left_out:
        files.pop(item["path"], None)
    rebuild = rebuild_for(folder, recipe, left_out)
    notes: list[str] = []
    for item in left_out:
        if item["rebuilt_by"] is None and item["needed"]:
            notes.append(
                f"{item['path']} is left out ({item['reason']}), and the study's reproduce.json has no step that "
                "loads it again: a rerun of the package cannot rebuild it."
            )

    with tempfile.TemporaryDirectory(prefix="e2er-pack-") as td:
        staging = Path(td)
        extra: dict[str, Path] = {}
        python_minor = str((recipe or {}).get("python") or f"{sys.version_info.major}.{sys.version_info.minor}")
        environment: dict[str, Any] = {"python": python_minor, "lock": None, "hashes": False, "note": ""}
        requirements = folder / str(recipe["requirements"]) if recipe else None
        if recipe is not None and requirements is not None and requirements.is_file():
            as_of = _as_of(prov)
            text, note = (locker or uv_lock)(requirements, python_minor, as_of)
            if text:
                lock = staging / "requirements.lock.txt"
                header = (
                    "# Every package the study's code needs, at one version each, with the SHA-256 of every file\n"
                    f"# an installer may use. Resolved by e2er from {recipe['requirements']} for Python {python_minor}"
                    + (f", with releases up to {as_of}" if as_of else "")
                    + ".\n"
                )
                lock.write_text(header + text, encoding="utf-8")
                extra[LOCK] = lock
                environment.update(
                    lock=LOCK,
                    hashes="--hash=" in text,
                    resolved_as_of=as_of or None,
                    note=f"{LOCK} pins every package with its hashes; `e2er reproduce` installs from it.",
                )
            else:
                environment["note"] = (
                    f"{note}. The package carries {recipe['requirements']} (the study's own pins, without hashes); "
                    "`e2er reproduce` installs from it."
                )
                notes.append(environment["note"])
        elif recipe is None:
            environment["note"] = "The study has no reproduce.json, so no environment is pinned."

        wheels: dict[str, Any] | None = None
        if offline:
            source = extra.get(LOCK) or requirements
            key = platform_key(python_minor)
            if source is None:
                notes.append("--offline: the study has no requirements to download wheels for.")
            else:
                got, note = (downloader or pip_download)(source, python_minor, staging / "wheels" / key)
                if got:
                    for whl in got:
                        extra[f"{WHEELS}/{key}/{whl.name}"] = whl
                    total = sum(w.stat().st_size for w in got)
                    wheels = {
                        "platform": key,
                        "python": python_minor,
                        "folder": f"{WHEELS}/{key}",
                        "files": len(got),
                        "bytes": total,
                    }
                    if total > LARGE_WHEELS:
                        notes.append(
                            f"The wheels add {human_size(total)} to the package; without --offline it is that much "
                            "smaller, and a rerun downloads them instead."
                        )
                else:
                    notes.append(f"--offline: {note}. The package has no wheels; a rerun downloads the packages.")

        contents: list[dict[str, Any]] = []
        entries: list[tuple[str, Path]] = []
        for rel, src in sorted({**files, **extra}.items()):
            contents.append(
                {
                    "path": rel,
                    "sha256": _sha256(src),
                    "bytes": src.stat().st_size,
                    "part": "package" if rel.startswith(PACKAGE_DIR + "/") else "study",
                }
            )
            entries.append((rel, src))
        study = _study(folder, prov)
        manifest: dict[str, Any] = {
            "format": FORMAT,
            "e2er_version": __version__,
            "study": study,
            # The export's date, not the packing time: the same export packs to the same bytes.
            "created": study["exported_at"],
            "contents": contents,
            "fingerprint": fingerprint(contents),
            "left_out": left_out,
            # Steps a rerun adds to the study's reproduce.json to build left-out derived inputs again.
            "rebuild": rebuild,
            "recipe": _recipe_summary(recipe, why),
            "environment": environment,
            "wheels": wheels,
            "notes": notes,
        }
        manifest_bytes = (json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode()
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(f".{target.name}.partial")
        try:
            _write_zip(partial, manifest_bytes, entries)
            os.replace(partial, target)
        finally:
            partial.unlink(missing_ok=True)
    return Packed(path=target, manifest=manifest, size=target.stat().st_size, notes=notes)


# ── reading ──────────────────────────────────────────────────────────────────


@dataclass
class Opened:
    root: Path
    manifest: dict[str, Any]

    @property
    def files(self) -> int:
        return len(self.manifest.get("contents") or [])


def _name_problem(name: str) -> str | None:
    from .bundle_files import key_problem

    if name.endswith("/"):
        name = name[:-1]
    return key_problem(name)


def _is_link(info: zipfile.ZipInfo) -> bool:
    return info.create_system == 3 and stat.S_ISLNK(info.external_attr >> 16)


def read_manifest(path: Path) -> dict[str, Any]:
    """The package's e2er-package.json, without unpacking anything (for `e2er inspect`)."""
    try:
        with zipfile.ZipFile(path) as zf:
            return _manifest_of(zf)
    except (zipfile.BadZipFile, OSError) as e:
        raise PackageError(f"{Path(path).name} is not a readable .e2er package ({e})") from e


def _manifest_of(zf: zipfile.ZipFile) -> dict[str, Any]:
    try:
        info = zf.getinfo(MANIFEST)
    except KeyError as e:
        raise PackageError(f"the package has no {MANIFEST} at its root: it is not a .e2er package") from e
    if info.file_size > MAX_MANIFEST_BYTES:
        raise PackageError(f"{MANIFEST} is larger than {human_size(MAX_MANIFEST_BYTES)}")
    from .bundle_files import _no_duplicates

    try:
        manifest = json.loads(zf.read(MANIFEST).decode("utf-8"), object_pairs_hook=_no_duplicates)
    except (ValueError, UnicodeDecodeError) as e:
        raise PackageError(f"{MANIFEST} cannot be read: {e}") from e
    if not isinstance(manifest, dict):
        raise PackageError(f"{MANIFEST} is not a JSON object")
    fmt = str(manifest.get("format") or "")
    if not fmt.startswith("e2er-package/"):
        raise PackageError(f"{MANIFEST} does not name the package format")
    if fmt != FORMAT:
        raise PackageError(f"the package is in format {fmt}; this e2er reads {FORMAT}. Update e2er.")
    contents = manifest.get("contents")
    if not isinstance(contents, list) or not all(
        isinstance(c, dict)
        and isinstance(c.get("path"), str)
        and isinstance(c.get("sha256"), str)
        and isinstance(c.get("bytes"), int)
        and not isinstance(c.get("bytes"), bool)
        and c["bytes"] >= 0
        for c in contents
    ):
        raise PackageError(f"{MANIFEST} has no valid contents list (path, sha256 and bytes for every file)")
    if len({c["path"] for c in contents}) != len(contents):
        raise PackageError(f"{MANIFEST} lists a file twice")
    if manifest.get("fingerprint") != fingerprint(contents):
        raise PackageError(f"the fingerprint in {MANIFEST} does not match its own list of files")
    return manifest


def _folded(name: str) -> str:
    return unicodedata.normalize("NFC", name).casefold()


def check_entries(zf: zipfile.ZipFile, manifest: dict[str, Any], max_total: int = MAX_TOTAL_BYTES) -> None:
    """Refuse an unsafe or incomplete archive before anything is written (names, links, sizes, the list)."""
    infos = zf.infolist()
    if len(infos) > MAX_ENTRIES:
        raise PackageError(f"the package holds {len(infos)} entries; more than {MAX_ENTRIES} is refused")
    listed = {c["path"]: c for c in manifest["contents"]}
    seen: set[str] = set()
    total = 0
    for info in infos:
        name = info.filename
        why = _name_problem(name)
        if why:
            raise PackageError(f"unsafe name in the package: {name!r} {why}")
        if _is_link(info):
            raise PackageError(f"the package holds a symbolic link ({name}); a package holds files only")
        if info.is_dir():
            continue
        folded = _folded(name)
        if folded in seen:
            raise PackageError(f"the package holds {name} twice (or two names that differ only in case)")
        seen.add(folded)
        if name == MANIFEST:
            continue
        item = listed.get(name)
        if item is None:
            raise PackageError(f"{name} is in the package but not in {MANIFEST} (added after packing)")
        if info.file_size != item["bytes"]:
            raise PackageError(f"{name} does not match {MANIFEST}: its size changed after packing")
        if info.file_size > (1 << 20) and info.file_size > max(info.compress_size, 1) * MAX_RATIO:
            raise PackageError(f"{name} unpacks to more than {MAX_RATIO} times its packed size; refused")
        total += info.file_size
        if total > max_total:
            raise PackageError(f"the package unpacks to more than {human_size(max_total)}; refused")
    for path in listed:
        why = _name_problem(path)
        if why:
            raise PackageError(f"unsafe name in {MANIFEST}: {path!r} {why}")
        if _folded(path) not in seen:
            raise PackageError(f"{path} is missing from the package (listed in {MANIFEST})")


def open_package(path: Path, dest: Path, *, max_total: int = MAX_TOTAL_BYTES) -> Opened:
    """Unpack ``path`` into the new or empty folder ``dest``, checking every file against the manifest.

    Nothing is run. A file whose bytes differ from the manifest stops the unpacking with its name; the
    folder is then removed again (when this call made it).
    """
    path = Path(path).expanduser()
    dest = Path(dest).expanduser()
    if dest.exists() and (not dest.is_dir() or any(dest.iterdir())):
        raise PackageError(f"{dest} already exists and is not empty; choose a new folder")
    made = not dest.exists()
    try:
        zf = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as e:
        raise PackageError(f"{path.name} is not a readable .e2er package ({e})") from e
    try:
        with zf:
            manifest = _manifest_of(zf)
            check_entries(zf, manifest, max_total)
            dest.mkdir(parents=True, exist_ok=True)
            root = dest.resolve()
            for item in sorted(manifest["contents"], key=lambda c: c["path"]):
                _extract(zf, item, root)
            (root / MANIFEST).write_bytes(zf.read(MANIFEST))
    except BaseException:
        if made:
            shutil.rmtree(dest, ignore_errors=True)
        else:
            for child in dest.iterdir():
                if child.is_dir() and not child.is_symlink():
                    shutil.rmtree(child, ignore_errors=True)
                else:
                    child.unlink(missing_ok=True)
        raise
    return Opened(root=root, manifest=manifest)


def _extract(zf: zipfile.ZipFile, item: dict[str, Any], root: Path) -> None:
    rel = item["path"]
    target = root.joinpath(*rel.split("/"))
    if not target.resolve().is_relative_to(root):
        raise PackageError(f"unsafe name in the package: {rel!r} leaves the folder")
    target.parent.mkdir(parents=True, exist_ok=True)
    h = hashlib.sha256()
    written = 0
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o644)
    with os.fdopen(fd, "wb") as fout, zf.open(rel) as fin:
        for chunk in iter(lambda: fin.read(1 << 20), b""):
            written += len(chunk)
            if written > item["bytes"]:
                raise PackageError(f"{rel} does not match {MANIFEST}: it is larger than listed")
            h.update(chunk)
            fout.write(chunk)
    if written != item["bytes"] or h.hexdigest() != item["sha256"]:
        raise PackageError(f"{rel} does not match {MANIFEST}: it was changed after packing")


# ── a package's own files in an unpacked folder ──────────────────────────────


def package_manifest(folder: Path) -> dict[str, Any] | None:
    """The e2er-package.json of an unpacked package (None in an ordinary export folder)."""
    doc = _read_json(Path(folder) / MANIFEST)
    return doc if isinstance(doc, dict) and str(doc.get("format") or "").startswith("e2er-package/") else None


def declared_left_out(folder: Path) -> dict[str, dict[str, Any]]:
    """Data files the package says it left out, by path (data files only: nothing else may be left out)."""
    doc = package_manifest(folder)
    out: dict[str, dict[str, Any]] = {}
    for item in (doc or {}).get("left_out") or []:
        if isinstance(item, dict) and isinstance(item.get("path"), str) and _data_suffix(item["path"]):
            out[item["path"]] = item
    return out


def rebuild_steps(folder: Path) -> list[dict[str, Any]]:
    """The manifest's ``rebuild`` steps of an unpacked package (none in an ordinary folder)."""
    items = (package_manifest(folder) or {}).get("rebuild")
    return [i for i in items if isinstance(i, dict)] if isinstance(items, list) else []


def install_source(folder: Path, recipe: dict[str, Any]) -> dict[str, Any]:
    """What `e2er reproduce` installs from in an unpacked package: the lock, and the wheels when they fit here."""
    doc = package_manifest(folder) or {}
    out: dict[str, Any] = {}
    env: dict[str, Any] = doc["environment"] if isinstance(doc.get("environment"), dict) else {}
    if env.get("lock") == LOCK and (Path(folder) / LOCK).is_file():
        out["requirements"] = LOCK
    wheels = doc.get("wheels") if isinstance(doc.get("wheels"), dict) else None
    if wheels:
        python_minor = str(recipe.get("python") or wheels.get("python") or "")
        here = platform_key(python_minor)
        folder_rel = f"{WHEELS}/{wheels.get('platform')}"
        if wheels.get("platform") == here and (Path(folder) / folder_rel).is_dir():
            out["wheelhouse"] = folder_rel
        else:
            out["wheelhouse_skipped"] = (
                f"the package's wheels are for {wheels.get('platform')}, this computer is {here}: "
                "the packages are downloaded"
            )
    return out


# ── a plain summary ──────────────────────────────────────────────────────────


def summary(manifest: dict[str, Any], size: int | None = None) -> str:
    """What `e2er inspect` prints."""
    study = manifest.get("study") or {}
    lines = [f"Title: {study.get('title') or '(no title)'}"]
    authors = study.get("authors") or []
    lines.append(
        "Authors: " + (", ".join(authors) if authors else "not named (authors are added when the study is published)")
    )
    if study.get("id"):
        lines.append(f"Study id: {study['id']}")
    made = study.get("e2er_version") or "unknown"
    lines.append(f"e2er version: packed with {manifest.get('e2er_version')}, study exported with {made}")
    exported = str(study.get("exported_at") or "")
    if exported:
        m = re.match(r"^(\d{4})(\d{2})(\d{2})$", exported)
        lines.append(f"Exported: {'-'.join(m.groups()) if m else exported}")
    if study.get("purpose") == "demonstration":
        lines.append("Demonstration: published as is, not endorsed.")
    contents = manifest.get("contents") or []
    study_files_ = [c for c in contents if c.get("part") != "package"]
    data = [c["path"] for c in study_files_ if _is_data(c["path"])]
    left = manifest.get("left_out") or []
    lines.append("")
    lines.append("Data:")
    if data:
        lines.append(f"  included: {', '.join(data)}")
    for item in left:
        lines.append(f"  left out: {item['path']} ({item.get('reason')}); {rerun_words(item)}")
    if not data and not left:
        lines.append("  the study has no data files")
    env = manifest.get("environment") or {}
    lines.append("")
    lines.append(f"Python: {env.get('python') or 'not recorded'}")
    if env.get("lock"):
        lines.append(f"Packages: pinned with their hashes ({env['lock']})")
    else:
        lines.append(f"Packages: {env.get('note') or 'not pinned'}")
    wheels = manifest.get("wheels")
    if wheels:
        lines.append(
            f"Offline install: {wheels.get('files')} wheel(s) for {wheels.get('platform')} "
            f"({human_size(int(wheels.get('bytes') or 0))})"
        )
    recipe = manifest.get("recipe") or {}
    if recipe.get("present"):
        steps = recipe.get("steps") or []
        lines.append(f"Reproduce: {len(steps)} step(s), `e2er reproduce` on the package runs them again")
    else:
        lines.append(f"Reproduce: not possible ({recipe.get('why') or 'no reproduce.json'})")
    lines.append("")
    total = sum(int(c.get("bytes") or 0) for c in contents)
    size_words = f"{human_size(size)} packed, " if size is not None else ""
    lines.append(f"Size: {size_words}{human_size(total)} unpacked, {len(contents)} file(s)")
    lines.append(f"Fingerprint: {manifest.get('fingerprint')}")
    for n in manifest.get("notes") or []:
        lines.append(f"Note: {n}")
    return "\n".join(lines) + "\n"
