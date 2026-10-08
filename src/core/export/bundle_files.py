"""Which files make up an exported bundle: one reading, shared by export, verify and publish.

``e2er export`` fingerprints the files it lists here, ``e2er verify`` compares
the same listing with ``provenance.json`` and ``e2er publish`` refuses a folder
whose listing changed. Every caller walks the folder the same way:

* **Symbolic links are never followed.** A bundle holds copies; a link can
  point anywhere (outside the folder, at a file that changes later), so verify
  fails on any link it finds instead of hashing what it points at.
* **Operating-system clutter is ignored**: ``.DS_Store`` (Finder),
  ``Thumbs.db`` and ``desktop.ini`` (Windows Explorer) and ``._*``
  (AppleDouble files macOS writes on non-Apple disks). Opening the folder in a
  file browser must not make it fail; these files say nothing about the study,
  export never copies them and verify names them as ignored.
* **Paths are compared in Unicode NFC**, so a name the file system stores
  decomposed (HFS+ does) still matches the name provenance.json lists. Keys in
  provenance.json must already be NFC, relative, normalised and inside the
  folder (no absolute path, ``..``, ``.``, empty segment or backslash).
"""

from __future__ import annotations

import json
import os
import posixpath
import re
import stat
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: Files an operating system's file browser writes into any folder it shows.
JUNK_NAMES = frozenset({".DS_Store", "Thumbs.db", "desktop.ini", "Desktop.ini"})

#: Root-level files that are not evidence. provenance.json is the inventory
#: itself; e2er.json (written by publish) and .e2er/link.json (written by
#: ``publish --to``) are compared with it by verify's anchor check;
#: .e2er/zenodo.json records the Zenodo deposits publish reserved, so a retry
#: reuses them. Exempt by exact path: a file with one of these names anywhere
#: else in the bundle is an ordinary file and must be listed.
NOT_EVIDENCE = ("provenance.json", "e2er.json", ".e2er/link.json", ".e2er/zenodo.json")

#: Names a bundle never carries (keys and credentials), on top of every dotfile.
_SECRET_NAME = re.compile(r"(?i)^(?:id_(?:rsa|dsa|ecdsa|ed25519)(?:\.pub)?|.*\.(?:pem|key|p12|pfx|keystore|jks))$")


def is_junk(name: str) -> bool:
    """An operating system's own file (Finder, Explorer), not part of any study."""
    return name in JUNK_NAMES or name.startswith("._")


#: Endings of files a run or an editor leaves behind: earlier versions of an output
#: (``.previous``, from e2er before 0.14.0), backups, locks and swap files.
_LEFTOVER_ENDINGS = (".previous", ".bak", ".orig", ".tmp", ".swp", ".swo", ".lock", "~")


def is_leftover(name: str) -> bool:
    """A backup, lock or earlier version of a file: never part of an exported study."""
    return name.endswith(_LEFTOVER_ENDINGS) or name.startswith(".~lock.")


def never_exported(name: str) -> bool:
    """A name export leaves behind: OS clutter, dotfiles (``.env`` holds keys) and key files."""
    return is_junk(name) or name.startswith(".") or bool(_SECRET_NAME.match(name))


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


@dataclass
class Listing:
    """The regular files of a bundle, by NFC relative path, and what is not a regular file."""

    files: dict[str, Path] = field(default_factory=dict)
    symlinks: list[str] = field(default_factory=list)
    special: list[str] = field(default_factory=list)  # sockets, FIFOs, devices
    junk: list[str] = field(default_factory=list)
    collisions: list[str] = field(default_factory=list)  # two names, one NFC form


def walk(bundle: Path) -> Listing:
    """Every file under ``bundle`` without following a single link (see the module docstring)."""
    out = Listing()
    root = Path(bundle)
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        here = Path(dirpath)
        for d in list(dirnames):
            p = here / d
            if p.is_symlink():
                out.symlinks.append(nfc(p.relative_to(root).as_posix()))
                dirnames.remove(d)
        dirnames.sort()
        for name in sorted(filenames):
            p = here / name
            rel = nfc(p.relative_to(root).as_posix())
            mode = os.lstat(p).st_mode
            if stat.S_ISLNK(mode):
                out.symlinks.append(rel)
            elif not stat.S_ISREG(mode):
                out.special.append(rel)
            elif is_junk(name):
                out.junk.append(rel)
            elif rel in out.files:
                out.collisions.append(rel)
            else:
                out.files[rel] = p
    return out


def key_problem(key: Any) -> str | None:
    """Why ``key`` is not a path provenance.json may list, or None."""
    if not isinstance(key, str) or not key:
        return "is not a non-empty string"
    if any(ord(c) < 0x20 or ord(c) == 0x7F for c in key):
        return "contains a control character"
    if "\\" in key:
        return "contains a backslash"
    if key.startswith("/") or re.match(r"^[A-Za-z]:", key):
        return "is an absolute path"
    segs = key.split("/")
    if any(s == "" for s in segs):
        return "has an empty segment"
    if any(s == ".." for s in segs):
        return "leaves the folder (..)"
    if any(s == "." for s in segs) or posixpath.normpath(key) != key:
        return "is not a normalised path"
    if nfc(key) != key:
        return "is not in Unicode NFC"
    return None


class DuplicateKeyError(ValueError):
    pass


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in pairs:
        if k in out:
            raise DuplicateKeyError(f"the key {k!r} appears twice")
        out[k] = v
    return out


def load_json_strict(path: Path) -> tuple[Any, str | None]:
    """(value, None), or (None, why it cannot be trusted): unreadable, not JSON, or a key given twice.

    JSON lets an object name a key twice and readers then disagree on which
    value counts (Python takes the last); a document that does so is refused.
    """
    try:
        text = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return None, f"{Path(path).name} is missing"
    except (OSError, UnicodeDecodeError) as e:
        return None, f"{Path(path).name} cannot be read: {e}"
    try:
        return json.loads(text, object_pairs_hook=_no_duplicates), None
    except DuplicateKeyError as e:
        return None, f"{Path(path).name} is ambiguous: {e}"
    except ValueError as e:
        return None, f"{Path(path).name} is not valid JSON: {e}"


_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def provenance_problems(prov: Any) -> list[str]:
    """What makes a parsed provenance.json unusable as an inventory (shape, keys, fingerprints)."""
    if not isinstance(prov, dict):
        return ["provenance.json is not a JSON object"]
    files = prov.get("files")
    if not isinstance(files, dict):
        return ["provenance.json has no files object"]
    out: list[str] = []
    for key, meta in files.items():
        why = key_problem(key)
        if why:
            out.append(f"the entry {key!r} {why}")
            continue
        if not isinstance(meta, dict):
            out.append(f"the entry {key} is not an object")
            continue
        if not isinstance(meta.get("sha256"), str) or not _HEX64.match(meta["sha256"]):
            out.append(f"the entry {key} has no SHA-256 (64 lowercase hex digits)")
        b = meta.get("bytes")
        if isinstance(b, bool) or not isinstance(b, int) or b < 0:
            out.append(f"the entry {key} has no byte size")
    edges = prov.get("edges", [])
    if not isinstance(edges, list) or not all(isinstance(e, dict) for e in edges):
        out.append("provenance.json's edges are not a list of objects")
    if "run" in prov and not isinstance(prov["run"], dict):
        out.append("provenance.json's run is not an object")
    amendments = prov.get("amendments", [])
    if not isinstance(amendments, list) or not all(isinstance(a, dict) for a in amendments):
        out.append("provenance.json's amendments are not a list of objects")
    return out


__all__ = [
    "JUNK_NAMES",
    "NOT_EVIDENCE",
    "Listing",
    "is_junk",
    "key_problem",
    "load_json_strict",
    "never_exported",
    "nfc",
    "provenance_problems",
    "walk",
]
