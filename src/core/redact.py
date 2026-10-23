"""Redacting personal data from a study folder before it is published (``e2er redact``).

A researcher may need to take a piece of personal data out of the exported
files, an e-mail address in a plan the run wrote, for example. Editing the
files by hand breaks the folder: their fingerprints no longer match
provenance.json, and a pre-registration no longer matches its frozen
fingerprint. ``redact`` does the edit the supported way:

* every occurrence of the text in the folder's text files is replaced by the
  replacement (``<redacted>`` by default), and nothing else in the file changes;
* each changed file gets an amendment in provenance.json::

      {"path", "kind": "redacted", "sha256_before", "sha256_after",
       "reason": "personal contact details removed by the researcher", "at",
       "redaction": {"replacement", "count", "offsets", "removed_bytes"}}

  ``offsets`` are the byte offsets of the replacement in the new file and
  ``removed_bytes`` the length of the text taken out. The record never holds
  the text, nor a hash of it;
* ``sha256_before`` is keyed (``hmac-sha256:<hex>``, an HMAC with a salt kept on
  this computer in ``~/.e2er/redaction-salt``) unless the earlier fingerprint is
  public anyway: a pre-registered plan file (its frozen fingerprint is in the lock
  file) or a folder published before (its fingerprints are on the platform). A
  plain SHA-256 of the earlier file, with the offsets, confirms a guess of a short
  text: a phone number was recovered from the record in 0.02 s (security review of
  2026-10-23). ``e2er redact --check`` on this computer still rebuilds the earlier
  file and compares it;
* before anything is written, the edit is proven: the new file, with the text
  put back at the offsets, has exactly the fingerprint the file had.

The amendments go into the dossier when the study is published. ``e2er verify``
accepts a pre-registered plan file whose only change since the freeze is such a
redaction ("redacted by the researcher after registration: contact details
only"), after checking that the record matches the file: the replacement sits
at every recorded offset.

Text inside a binary file (a PDF, a database) cannot be replaced in place;
``redact`` names such files and changes nothing.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

KIND = "redacted"
REASON = "personal contact details removed by the researcher"
DEFAULT_REPLACEMENT = "<redacted>"
#: What verify says about a pre-registered plan file whose only change is a redaction.
PREREG_WORDS = "redacted by the researcher after registration: contact details only"
#: Local records, never published: not searched and not changed.
_LOCAL = (".e2er/",)


class RedactError(Exception):
    """The redaction cannot be made; the message says why. Nothing was changed."""


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


#: The prefix of a keyed fingerprint (an HMAC-SHA256 with this computer's salt) in ``sha256_before``.
KEYED = "hmac-sha256:"
#: Below this many characters a redacted text can be guessed from the earlier file's fingerprint, where one is
#: public (a pre-registered plan, a folder published before): a phone number, a postcode, an extension.
SHORT_TEXT = 16


def salt_file() -> Path:
    return Path.home() / ".e2er" / "redaction-salt"


def _salt() -> bytes:
    """This computer's redaction salt (made once, mode 600 in a 700 folder). Never published."""
    p = salt_file()
    try:
        raw = p.read_text(encoding="utf-8").strip()
        if len(raw) >= 64:
            return bytes.fromhex(raw)
    except (OSError, ValueError):
        pass
    p.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    value = secrets.token_hex(32)
    tmp = p.with_name(f".{p.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(value + "\n")
    os.replace(tmp, p)
    return bytes.fromhex(value)


def keyed(data: bytes) -> str:
    """The keyed fingerprint of ``data``: confirms nothing to anyone without this computer's salt."""
    return KEYED + hmac.new(_salt(), data, hashlib.sha256).hexdigest()


def guessable(text: str) -> bool:
    """Is ``text`` short enough to be guessed by trying (a phone number, an extension, a postcode)?"""
    return len(text.strip()) < SHORT_TEXT


def _public_before(folder: Path, rel: str) -> bool:
    """Is the fingerprint ``rel`` has now public anyway? A pre-registered file, or a folder published before."""
    from .anonymise import prereg_paths

    return rel in prereg_paths(folder) or (folder / "e2er.json").is_file() or (folder / ".e2er" / "link.json").is_file()


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class Plan:
    """What a redaction changes (or, in a dry run, would change)."""

    #: rel → (bytes now, bytes after, offsets of the replacement in the new bytes)
    edits: dict[str, tuple[bytes, bytes, list[int]]] = field(default_factory=dict)
    #: Binary files that hold the text (it cannot be replaced in place).
    binary: list[str] = field(default_factory=list)
    #: PDFs whose extracted text holds it (pdftotext), so the paper must be built again from its source.
    pdfs: list[str] = field(default_factory=list)
    #: Files that hold the text but are not listed in provenance.json (records of an earlier publish).
    unlisted: list[str] = field(default_factory=list)
    #: PDFs whose text could not be read (no pdftotext): the text may be in them, compressed.
    pdfs_unread: list[str] = field(default_factory=list)


def replace_with_offsets(data: bytes, old: bytes, new: bytes) -> tuple[bytes, list[int]]:
    """``data`` with every ``old`` replaced by ``new``, and the offsets of ``new`` in the result."""
    out = bytearray()
    offsets: list[int] = []
    i = 0
    while True:
        j = data.find(old, i)
        if j < 0:
            out += data[i:]
            break
        out += data[i:j]
        offsets.append(len(out))
        out += new
        i = j + len(old)
    return bytes(out), offsets


def restore(after: bytes, offsets: list[int], replacement: bytes, text: bytes) -> bytes:
    """The file before the redaction: ``text`` back in place of the replacement at each offset."""
    out = bytearray()
    i = 0
    for off in offsets:
        out += after[i:off] + text
        i = off + len(replacement)
    out += after[i:]
    return bytes(out)


def _is_text(data: bytes) -> bool:
    if b"\x00" in data[:8192]:
        return False
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def _pdf_text(path: Path) -> str | None:
    exe = shutil.which("pdftotext")
    if exe is None:
        return None
    try:
        proc = subprocess.run([exe, "-q", str(path), "-"], capture_output=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return proc.stdout.decode("utf-8", errors="replace") if proc.returncode == 0 else None


def _files(folder: Path) -> list[str]:
    return sorted(
        p.relative_to(folder).as_posix()
        for p in folder.rglob("*")
        if p.is_file() and not p.is_symlink() and not p.relative_to(folder).as_posix().startswith(_LOCAL)
    )


def plan(folder: Path, texts: list[str], replacement: str = DEFAULT_REPLACEMENT) -> Plan:
    """Where the texts are and what replacing them changes. Reads only."""
    folder = Path(folder)
    prov = _provenance(folder)
    listed = prov.get("files") or {}
    rep = replacement.encode("utf-8")
    wanted = [t.encode("utf-8") for t in texts]
    out = Plan()
    for rel in _files(folder):
        path = folder / rel
        data = path.read_bytes()
        if path.suffix.lower() == ".pdf":
            text = _pdf_text(path)
            if any(w in data for w in wanted) or (text is not None and any(t in text for t in texts)):
                out.pdfs.append(rel)
            elif text is None:
                out.pdfs_unread.append(rel)
            continue
        if not any(w in data for w in wanted):
            continue
        if not _is_text(data):
            out.binary.append(rel)
            continue
        if rel not in listed:
            out.unlisted.append(rel)
            continue
        new, offsets = data, list[int]()
        for w in wanted:
            if w not in new:
                continue
            if offsets:
                raise RedactError("give one --text per redaction: several texts in one file are redacted one by one")
            new, offsets = replace_with_offsets(new, w, rep)
        out.edits[rel] = (data, new, offsets)
    return out


def _provenance(folder: Path) -> dict[str, Any]:
    p = folder / "provenance.json"
    if not p.is_file():
        raise RedactError(f"{folder} has no provenance.json: redact works on an exported study folder")
    try:
        prov = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise RedactError(f"provenance.json cannot be read: {e}") from e
    if not isinstance(prov, dict) or not isinstance(prov.get("files"), dict):
        raise RedactError("provenance.json lists no files")
    return prov


def redact(
    folder: Path, text: str, *, replacement: str = DEFAULT_REPLACEMENT, dry_run: bool = False
) -> tuple[Plan, list[dict[str, Any]]]:
    """Replace ``text`` in the folder's text files and record an amendment per file (see the module docstring).

    Refuses (RedactError, nothing changed) when the text is empty or inside the replacement, when a file to
    change does not match provenance.json, or when the text is in a binary file, a PDF or a file provenance.json
    does not list. Returns the plan and the amendments written (none in a dry run).
    """
    folder = Path(folder)
    if not text.strip():
        raise RedactError("--text is empty")
    if text in replacement:
        raise RedactError("the replacement contains the text it replaces")
    if replacement in text:
        raise RedactError("the replacement is part of the text it replaces; choose another replacement")
    found = plan(folder, [text], replacement)
    stuck = []
    if found.binary:
        stuck.append(
            f"{', '.join(found.binary)} hold{'s' if len(found.binary) == 1 else ''} it in binary form, which "
            "cannot be edited in place"
        )
    if found.pdfs:
        stuck.append(
            f"{', '.join(found.pdfs)}: the PDF's text holds it; redact its source (paper/paper.tex) and build the "
            "PDF again (e2er publish compiles paper/paper.pdf from paper/paper.tex)"
        )
    if found.unlisted:
        stuck.append(
            f"{', '.join(found.unlisted)} {'is' if len(found.unlisted) == 1 else 'are'} not listed in "
            "provenance.json (a record of an earlier publish, rewritten by the next one); remove the text there "
            "by hand or publish again first"
        )
    if stuck:
        raise RedactError("the text is also where redact cannot replace it; nothing was changed: " + "; ".join(stuck))
    prov = _provenance(folder)
    listed = prov["files"]
    changed = [
        rel for rel, (before, _a, _o) in found.edits.items() if (listed[rel] or {}).get("sha256") != _sha(before)
    ]
    if changed:
        raise RedactError(
            f"{', '.join(changed)} {'does' if len(changed) == 1 else 'do'} not match provenance.json: the folder "
            "was changed after export; nothing was changed"
        )
    rep = replacement.encode("utf-8")
    t = text.encode("utf-8")
    for rel, (before, after, offsets) in found.edits.items():
        # The proof: the new file with the text put back is exactly the file as it was.
        if restore(after, offsets, rep, t) != before or t in after:
            raise RedactError(f"{rel}: the redaction could not be proven to change only the text; nothing was changed")
    if dry_run or not found.edits:
        return found, []
    at = _now()
    written: list[dict[str, Any]] = []
    amendments = prov.setdefault("amendments", [])
    for rel, (before, after, offsets) in found.edits.items():
        mine = [a for a in amendments if isinstance(a, dict) and a.get("path") == rel]
        previous = mine[-1] if mine else None
        # Keyed unless the fingerprint is public anyway, or an earlier amendment of another kind names it in plain.
        key_it = not _public_before(folder, rel) and (
            previous is None or (previous.get("kind") == KIND and previous.get("sha256_after") == _sha(before))
        )
        before_value = keyed(before) if key_it else _sha(before)
        if key_it and previous is not None:
            # The earlier redaction's "after" is this one's "before": keyed as well, so the chain still links.
            previous["sha256_after"] = before_value
        entry = {
            "path": rel,
            "kind": KIND,
            "sha256_before": before_value,
            "sha256_after": _sha(after),
            "reason": REASON,
            "at": at,
            "redaction": {
                "replacement": replacement,
                "count": len(offsets),
                "offsets": offsets,
                "removed_bytes": len(t),
                # The size provenance.json listed: with it, the listing before the redaction can be rebuilt
                # exactly (an earlier publish's content id, see :func:`provenance_before_redactions`).
                "bytes_before": (listed[rel] or {}).get("bytes"),
            },
        }
        listed[rel] = {"sha256": entry["sha256_after"], "bytes": len(after)}
        amendments.append(entry)
        written.append(entry)
    prov["files"] = dict(sorted(listed.items()))
    from .export.provenance import dump

    # The files first, provenance.json last: an interrupted run leaves files that do not match it, which verify
    # reports, never a record of an edit that was not made.
    for rel, (_b, after, _o) in found.edits.items():
        (folder / rel).write_bytes(after)
    (folder / "provenance.json").write_text(dump(prov), encoding="utf-8")
    return found, written


def provenance_before_redactions(folder: Path) -> tuple[list[str], int]:
    """provenance.json's text as it was before the redactions at the end of its amendments, and their number.

    The abstract rewritten after publishing (``e2er abstract``, kind ``abstract_rewritten``) is rolled back
    the same way: each such amendment records the size the file had (``bytes_before``), or that it was new.

    Several texts when the redactions added the "amendments" list itself (with and without an empty list):
    the caller compares each with an earlier publish's content id. ([], 0) when the last amendment is not a
    redaction or a redaction lacks the size the file had.
    """
    from .export.provenance import dump

    try:
        prov = json.loads((Path(folder) / "provenance.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [], 0
    if not isinstance(prov, dict) or not isinstance(prov.get("files"), dict):
        return [], 0
    from .abstract import AMENDMENT_KINDS as ABSTRACT_KINDS

    amendments = list(prov.get("amendments") or [])
    files = dict(prov["files"])
    n = 0
    while amendments and isinstance(amendments[-1], dict) and amendments[-1].get("kind") in (KIND, *ABSTRACT_KINDS):
        a = amendments.pop()
        if a.get("kind") in ABSTRACT_KINDS:
            # The abstract rewritten after publishing (`e2er abstract`): the file as it was, or none.
            if not isinstance(a.get("path"), str):
                return [], 0
            if a.get("sha256_before") is None:
                files.pop(a["path"], None)
            elif isinstance(a.get("sha256_before"), str) and isinstance(a.get("bytes_before"), int):
                files[a["path"]] = {"sha256": a["sha256_before"], "bytes": a["bytes_before"]}
            else:
                return [], 0
            n += 1
            continue
        size = (a.get("redaction") or {}).get("bytes_before") if isinstance(a.get("redaction"), dict) else None
        if not isinstance(a.get("path"), str) or not isinstance(a.get("sha256_before"), str) or size is None:
            return [], 0
        files[a["path"]] = {"sha256": a["sha256_before"], "bytes": size}
        n += 1
    if not n:
        return [], 0
    prov["files"] = files
    prov["amendments"] = amendments
    texts = [dump(prov)]
    if not amendments:
        texts.append(dump({k: v for k, v in prov.items() if k != "amendments"}))
    return texts, n


def record_problem(entry: dict[str, Any], data: bytes | None) -> str | None:
    """Why a redaction amendment does not describe the file ``data`` (its current bytes), or None.

    Checks the record's shape and that the replacement sits at every recorded offset.
    """
    red = entry.get("redaction")
    path = entry.get("path")
    if not isinstance(red, dict):
        return f"{path}: the redaction record is missing"
    rep, offsets, count, removed = (
        red.get("replacement"),
        red.get("offsets"),
        red.get("count"),
        red.get("removed_bytes"),
    )
    if (
        red.get("withheld")
        and offsets is None
        and isinstance(rep, str)
        and rep
        and isinstance(count, int)
        and count > 0
    ):
        # A copy for double-blind review keeps no offsets (src/core/anonymise.py): the replacement is counted.
        if data is None:
            return f"{path} is missing"
        if data.count(rep.encode("utf-8")) < count:
            return f"{path}: the redaction record does not match the file (fewer {rep} than recorded)"
        return None
    if not (
        isinstance(rep, str)
        and rep
        and isinstance(offsets, list)
        and offsets
        and all(isinstance(o, int) and o >= 0 for o in offsets)
        and count == len(offsets)
        and isinstance(removed, int)
        and removed > 0
    ):
        return f"{path}: the redaction record is incomplete"
    if data is None:
        return f"{path} is missing"
    r = rep.encode("utf-8")
    last = -1
    for o in offsets:
        if o <= last or data[o : o + len(r)] != r:
            return f"{path}: the redaction record does not match the file (no {rep} at byte {o})"
        last = o + len(r) - 1
    return None


def explains(amendments: list[dict[str, Any]], rel: str, sha_from: str | None, sha_to: str | None) -> bool:
    """Do redactions alone take ``rel`` from ``sha_from`` to ``sha_to``: an unbroken chain of its amendments, each
    of kind "redacted" (or "anonymised", for double-blind review)?"""
    if not sha_from or not sha_to:
        return False
    at: str | None = sha_from
    for a in amendments:
        if not isinstance(a, dict) or a.get("path") != rel or a.get("sha256_before") != at:
            continue
        # A redaction, or an anonymisation for double-blind review (src/core/anonymise.py): personal details only.
        if a.get("kind") not in (KIND, "anonymised"):
            return False
        at = a.get("sha256_after")
        if at == sha_to:
            return True
    return False


def check(folder: Path, text: str) -> list[str]:
    """With the text that was removed: rebuild each redacted file's earlier version and compare its fingerprint.

    Returns one line per redaction amendment ("✓ path: …" or "✗ path: …"). Only the last redaction of a file can be
    rebuilt from the file as it is now; earlier ones are named.
    """
    folder = Path(folder)
    prov = _provenance(folder)
    reds = [a for a in prov.get("amendments") or [] if isinstance(a, dict) and a.get("kind") == KIND]
    last: dict[str, dict[str, Any]] = {}
    for a in prov.get("amendments") or []:
        if isinstance(a, dict) and isinstance(a.get("path"), str):
            last[a["path"]] = a
    t = text.encode("utf-8")
    out = []
    for a in reds:
        rel = str(a.get("path"))
        if last.get(rel) is not a:
            out.append(f"· {rel}: a later change of the file follows this redaction; not rebuilt")
            continue
        path = folder / rel
        data = path.read_bytes() if path.is_file() else None
        why = record_problem(a, data)
        if why or data is None:
            out.append(f"✗ {why}")
            continue
        red = a["redaction"]
        if len(t) != red["removed_bytes"]:
            out.append(f"✗ {rel}: the text is {len(t)} bytes long, the redaction removed {red['removed_bytes']}")
            continue
        before = restore(data, red["offsets"], red["replacement"].encode("utf-8"), t)
        recorded = str(a.get("sha256_before") or "")
        if recorded.startswith(KEYED) and not salt_file().is_file():
            out.append(
                f"· {rel}: its earlier fingerprint is keyed to the computer that redacted it "
                "(~/.e2er/redaction-salt); run the check there"
            )
            continue
        if (keyed(before) if recorded.startswith(KEYED) else _sha(before)) == recorded:
            out.append(
                f"✓ {rel}: with the text put back, the file is exactly the earlier one ({red['count']} place(s))"
            )
        else:
            out.append(f"✗ {rel}: with the text put back, the file is not the earlier one")
    return out
