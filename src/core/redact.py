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
       "redaction": {"replacement", "count", "offsets", "removed_bytes",
                     "bytes_before", "kept": {"salt", "hmac_sha256"}}}

  ``offsets`` are the byte offsets of the replacement in the new file and
  ``removed_bytes`` the length of the text taken out. The record never holds
  the text, nor a hash of it. ``kept`` is the
  HMAC-SHA256 of the bytes the redaction kept (the new file with the
  replacements cut out), keyed with a random salt recorded beside it (the kept
  bytes are in the published file anyway: no guess can be confirmed with it);
* ``sha256_before`` is keyed (``hmac-sha256:<hex>``, an HMAC with a salt kept on
  this computer in ``~/.e2er/redaction-salt``) unless the earlier fingerprint is
  public anyway: a pre-registered plan file (its frozen fingerprint is in the lock
  file) or a folder published before (its fingerprints are on the platform). A
  plain SHA-256 of the earlier file, with the offsets, confirms a guess of a short
  text: a phone number was recovered from the record in 0.02 s (security review of
  2026-10-23). ``e2er redact --check`` on this computer still rebuilds the earlier
  file and compares it;
* before anything is written, the edit is proven: the new file, with the text
  put back at the offsets, has exactly the fingerprint the file had. A text
  longer than ``MAX_REMOVED_BYTES`` is refused: contact details are short.

The amendments go into the dossier when the study is published. ``e2er verify``
checks each record against the file: the replacement sits at every recorded
offset, the sizes add up (``bytes_before`` is the size now plus, per place, the
removed length less the replacement's), the kept bytes have the recorded
fingerprint, and no place lost more than ``MAX_REMOVED_BYTES``. A pre-registered
plan file whose only change since the freeze is such a redaction passes, "recorded
as redacted by the researcher after registration": the record holds, but what was
taken out is not in the folder, so verify cannot confirm it was contact details.

Text inside a binary file (a PDF, a database) cannot be replaced in place;
``redact`` names such files and changes nothing.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
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
#: What verify says about a pre-registered plan file whose only change is a redaction. The record matches the
#: file; what was taken out is not in the folder, so verify cannot say it was contact details.
PREREG_WORDS = "recorded as redacted by the researcher after registration (personal contact details, the record says)"
#: The longest text one redaction takes out, in bytes: an e-mail address, a telephone number, a postal address.
#: Anything longer is no redaction of contact details (a fake one could replace a whole script).
MAX_REMOVED_BYTES = 256
#: Local records, never published: not searched and not changed.
_LOCAL = (".e2er/",)


#: Said after "export again": a new export makes a new folder, so the redactions of this one are made there again.
REEXPORT_NOTE = "; the new export is a new folder, so make this folder's other redactions there again"


def is_record(rel: str) -> bool:
    """A record of the folder that no redaction can change: provenance.json, e2er.json, the files under .e2er/
    and a package's own files (bundle_files.not_evidence). An identifier there needs a new export."""
    from .export.bundle_files import not_evidence

    return not_evidence(rel) or rel.startswith(".e2er/")


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
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
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


def keyed_fingerprint(salt: str, data: bytes) -> str:
    """HMAC-SHA256 of ``data`` keyed with ``salt`` (hex): the fingerprint of the bytes a redaction kept."""
    return hmac.new(bytes.fromhex(salt), data, hashlib.sha256).hexdigest()


def kept_bytes(after: bytes, spans: list[tuple[int, int]]) -> bytes:
    """``after`` with the (offset, length) spans of the replacements cut out: the bytes the change kept,
    the same before and after it."""
    out = bytearray()
    i = 0
    for off, length in sorted(spans):
        out += after[i:off]
        i = off + length
    out += after[i:]
    return bytes(out)


def kept_record(after: bytes, spans: list[tuple[int, int]]) -> dict[str, str]:
    """The ``kept`` record of an amendment: a fresh random salt and the keyed fingerprint of the kept bytes.

    The salt is published with the record, so anyone can recompute the fingerprint from the file. Keyed per
    record, it matches nothing outside this amendment (no table of fingerprints of common files applies).
    """
    salt = secrets.token_hex(16)
    return {"salt": salt, "hmac_sha256": keyed_fingerprint(salt, kept_bytes(after, spans))}


def kept_problem(entry: dict[str, Any], kept: Any, data: bytes, spans: list[tuple[int, int]]) -> str | None:
    """Why the ``kept`` record does not match ``data`` with the replacement spans cut out (None: it matches, or
    the record predates it)."""
    if kept is None:
        return None
    path = entry.get("path")
    salt, mac = (kept.get("salt"), kept.get("hmac_sha256")) if isinstance(kept, dict) else (None, None)
    if not (isinstance(salt, str) and isinstance(mac, str) and re.fullmatch(r"[0-9a-f]{32,128}", salt)):
        return f"{path}: the record of the kept bytes is incomplete"
    if not hmac.compare_digest(keyed_fingerprint(salt, kept_bytes(data, spans)), mac):
        return f"{path}: the bytes outside the replacements are not the ones the change kept"
    return None


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
    if not replacement:
        raise RedactError("the replacement is empty; give a word that shows where the text was (--replace)")
    if text in replacement:
        raise RedactError("the replacement contains the text it replaces")
    if replacement in text:
        raise RedactError("the replacement is part of the text it replaces; choose another replacement")
    if len(text.encode("utf-8")) > MAX_REMOVED_BYTES:
        raise RedactError(
            f"the text is {len(text.encode('utf-8'))} bytes long; redact takes out personal contact details, at most "
            f"{MAX_REMOVED_BYTES} bytes at a time (an e-mail address, a telephone number, an address)"
        )
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
    records = [rel for rel in found.unlisted if is_record(rel)]
    others = [rel for rel in found.unlisted if not is_record(rel)]
    if records:
        stuck.append(
            f"{', '.join(records)} {'is' if len(records) == 1 else 'are'} e2er's own record of the folder, which "
            "redact cannot change (the fingerprints of every file are kept there): take the text out of the "
            "study's files where it comes from (the run's workspace, its manifest.json or data_sources.json) and "
            f"export again (`e2er export <run id>`){REEXPORT_NOTE}"
        )
    if others:
        stuck.append(
            f"{', '.join(others)} {'is' if len(others) == 1 else 'are'} not listed in "
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
        published = (folder / "e2er.json").is_file() or (folder / ".e2er" / "link.json").is_file()
        if previous is not None and previous.get("kind") == KIND and isinstance(previous.get("redaction"), dict):
            # The earlier redaction's kept bytes hold this text: their fingerprint would confirm a guess of it.
            # Verify checks an earlier redaction of a file by its sizes only, so nothing is lost. A record
            # already published stays as it was (the bytes it covers were published with it).
            if not published:
                previous["redaction"].pop("kept", None)
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
                # The bytes the redaction kept (the file without the replacements), keyed: verify recomputes it.
                "kept": kept_record(after, [(o, len(rep)) for o in offsets]),
            },
        }
        listed[rel] = {"sha256": entry["sha256_after"], "bytes": len(after)}
        amendments.append(entry)
        written.append(entry)
    prov["files"] = dict(sorted(listed.items()))
    from .export.provenance import dump

    # The files first, provenance.json last, each through a temporary file and a rename; on any error every
    # file written is put back as it was (write_all), so the folder never holds half a redaction.
    changes = {folder / rel: after for rel, (_b, after, _o) in found.edits.items()}
    changes[folder / "provenance.json"] = dump(prov).encode("utf-8")
    write_all(changes)
    return found, written


def _tmp_name(path: Path) -> Path:
    return path.with_name(f".{path.name}.e2er-redact-{os.getpid()}-{secrets.token_hex(4)}.tmp")


def write_all(changes: dict[Path, bytes]) -> None:
    """Write every file in ``changes`` (in order) or none of them.

    Each new content goes to a temporary file beside its file first (a full disk fails here, before anything
    changed), then each is renamed over its file (``os.replace``). If a rename fails, the files already
    replaced get their earlier bytes back. Temporary files never stay behind.
    """
    temps: dict[Path, Path] = {}
    try:
        for path, data in changes.items():
            tmp = _tmp_name(path)
            temps[path] = tmp
            with open(tmp, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            try:
                shutil.copymode(path, tmp)
            except OSError:
                pass
        originals: dict[Path, bytes | None] = {}
        try:
            for path, tmp in temps.items():
                originals[path] = path.read_bytes() if path.is_file() else None
                os.replace(tmp, path)
        except BaseException:
            for path, old in originals.items():
                try:
                    if old is None:
                        path.unlink(missing_ok=True)
                    else:
                        back = _tmp_name(path)
                        back.write_bytes(old)
                        os.replace(back, path)
                except OSError:
                    pass
            raise
    finally:
        for tmp in temps.values():
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass


def redact_all(
    folder: Path, texts: list[str], *, replacement: str = DEFAULT_REPLACEMENT, dry_run: bool = False
) -> list[tuple[Plan, list[dict[str, Any]]]]:
    """:func:`redact` for each text in turn, all or nothing: if one is refused or fails, the folder is put back
    as it was before the first (every file a redaction changed, and provenance.json)."""
    folder = Path(folder)
    if dry_run:
        return [redact(folder, t, replacement=replacement, dry_run=True) for t in texts]
    saved: dict[Path, bytes | None] = {}

    def save(path: Path) -> None:
        if path not in saved:
            saved[path] = path.read_bytes() if path.is_file() else None

    save(folder / "provenance.json")
    out: list[tuple[Plan, list[dict[str, Any]]]] = []
    try:
        for t in texts:
            # Which files this text changes: saved before it changes them.
            for rel in plan(folder, [t], replacement).edits:
                save(folder / rel)
            out.append(redact(folder, t, replacement=replacement))
    except BaseException:
        if len(out):
            restore_files = {p: d for p, d in saved.items() if d is not None}
            write_all(restore_files)
        raise
    return out


def provenance_before_redactions(folder: Path) -> tuple[list[str], int]:
    """provenance.json's text as it was before the redactions at the end of its amendments, and their number.

    The abstract rewritten after publishing (``e2er abstract``, kinds ``abstract_rewritten`` and
    ``abstract_edited_by_researcher``) is rolled back the same way: each such amendment records the size the
    file had (``bytes_before``), or that it was new. Only the files ``e2er abstract`` changes count
    (abstract.CHANGED_FILES), and the paper itself only with the record of the text the new abstract
    replaced: rebuilt from it, the paper must be the one before, unchanged outside its abstract
    (abstract.paper_problem). Each redaction must match the file as it was after it, where that is known
    (:func:`record_problem`).

    Several texts when the redactions added the "amendments" list itself (with and without an empty list):
    the caller compares each with an earlier publish's content id. ([], 0) when the last amendment is not a
    redaction or an abstract amendment, or one of them cannot be checked.
    """
    texts, n, _why = rollback(folder)
    return texts, n


def rollback(folder: Path) -> tuple[list[str], int, str | None]:
    """:func:`provenance_before_redactions`, and why an amendment at the end cannot be rolled back (or None)."""
    from .export.provenance import dump

    folder = Path(folder)
    try:
        prov = json.loads((folder / "provenance.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [], 0, None
    if not isinstance(prov, dict) or not isinstance(prov.get("files"), dict):
        return [], 0, None
    from . import abstract as ab

    amendments = list(prov.get("amendments") or [])
    files = dict(prov["files"])
    # Each file's bytes after the amendment being rolled back: the file as it is, then as rebuilt from an
    # abstract amendment's record (None: missing). A file in ``unknown`` was redacted later: its earlier bytes
    # cannot be rebuilt without the text.
    current: dict[str, bytes | None] = {}
    unknown: set[str] = set()

    def now(rel: str) -> bytes | None:
        if rel not in current:
            p = folder / rel
            current[rel] = p.read_bytes() if p.is_file() and not p.is_symlink() else None
        return current[rel]

    n = 0
    while amendments and isinstance(amendments[-1], dict) and amendments[-1].get("kind") in (KIND, *ab.AMENDMENT_KINDS):
        a = amendments.pop()
        rel = a.get("path")
        if not isinstance(rel, str):
            return [], 0, "an amendment names no file"
        if a.get("kind") in ab.AMENDMENT_KINDS:
            if rel not in ab.CHANGED_FILES:
                return [], 0, f"{rel}: an abstract amendment of a file e2er abstract never changes"
            if rel == ab.PAPER_FILE and a.get("sha256_before") is not None:
                if rel in unknown:
                    return [], 0, f"{rel}: the abstract amendment comes before a later change that cannot be undone"
                why, before = ab.paper_problem(a, now(rel))
                if why or before is None:
                    return [], 0, why
                if len(before) != a.get("bytes_before"):
                    return [], 0, f"{rel}: the abstract amendment records another size before than its old text gives"
                current[rel] = before
            else:
                unknown.add(rel)
            # The file as it was, or none.
            if a.get("sha256_before") is None:
                files.pop(rel, None)
            elif isinstance(a.get("sha256_before"), str) and isinstance(a.get("bytes_before"), int):
                files[rel] = {"sha256": a["sha256_before"], "bytes": a["bytes_before"]}
            else:
                return [], 0, f"{rel}: the abstract amendment records no fingerprint or size before"
            n += 1
            continue
        size = (a.get("redaction") or {}).get("bytes_before") if isinstance(a.get("redaction"), dict) else None
        if not isinstance(a.get("sha256_before"), str) or size is None:
            return [], 0, f"{rel}: the redaction records no fingerprint or size before"
        known = rel not in unknown
        data = now(rel) if known else None
        why = record_problem(a, data, size_after=(files.get(rel) or {}).get("bytes"), bytes_known=known)
        if why is not None:
            return [], 0, why
        unknown.add(rel)  # the redacted text is not known: the file before cannot be rebuilt
        files[rel] = {"sha256": a["sha256_before"], "bytes": size}
        n += 1
    if not n:
        return [], 0, None
    prov["files"] = files
    prov["amendments"] = amendments
    texts = [dump(prov)]
    if not amendments:
        texts.append(dump({k: v for k, v in prov.items() if k != "amendments"}))
    return texts, n, None


def record_problem(
    entry: dict[str, Any], data: bytes | None, *, size_after: int | None = None, bytes_known: bool = True
) -> str | None:
    """Why a redaction amendment does not describe the file ``data`` (its bytes after the redaction), or None.

    Checks the record's shape and that the replacement sits at every recorded offset. ``bytes_known=False``:
    the file after this redaction is not known (a later redaction changed it again), and only the record
    itself is checked.
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
        if not bytes_known:
            return None
        if data is None:
            return f"{path} is missing"
        if data.count(rep.encode("utf-8")) < count:
            return f"{path}: the redaction record does not match the file (fewer {rep} than recorded)"
        return None
    before = red.get("bytes_before")
    if not (
        isinstance(rep, str)
        and rep
        and isinstance(offsets, list)
        and offsets
        and all(isinstance(o, int) and not isinstance(o, bool) and o >= 0 for o in offsets)
        and count == len(offsets)
        and isinstance(removed, int)
        and not isinstance(removed, bool)
        and removed > 0
        and isinstance(before, int)
        and not isinstance(before, bool)
    ):
        return f"{path}: the redaction record is incomplete"
    if removed > MAX_REMOVED_BYTES:
        return (
            f"{path}: the redaction record says {removed} bytes were taken out at each place; a redaction of "
            f"contact details takes out at most {MAX_REMOVED_BYTES}"
        )
    if before - count * removed <= 0:
        return f"{path}: the redaction record says the whole file was taken out; a redaction keeps the file"
    r = rep.encode("utf-8")
    size = len(data) if bytes_known and data is not None else size_after
    # The sizes add up: the file before is the file after with each replacement swapped for the removed text.
    if isinstance(size, int) and before != size + count * (removed - len(r)):
        return (
            f"{path}: the redaction record's sizes do not add up ({before} bytes before, {size} after, "
            f"{count} x {removed} bytes taken out and {count} x {len(r)} put in)"
        )
    if not bytes_known:
        return None
    if data is None:
        return f"{path} is missing"
    last = -1
    for o in offsets:
        if o <= last or data[o : o + len(r)] != r:
            return f"{path}: the redaction record does not match the file (no {rep} at byte {o})"
        last = o + len(r) - 1
    return kept_problem(entry, red.get("kept"), data, [(o, len(r)) for o in offsets])


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


def chain(amendments: list[dict[str, Any]], rel: str, sha_from: str | None, sha_to: str | None) -> list[dict[str, Any]]:
    """The amendments that take ``rel`` from ``sha_from`` to ``sha_to`` (see :func:`explains`), or [] when
    redactions and anonymisations alone do not."""
    if not sha_from or not sha_to:
        return []
    at: str | None = sha_from
    out: list[dict[str, Any]] = []
    for a in amendments:
        if not isinstance(a, dict) or a.get("path") != rel or a.get("sha256_before") != at:
            continue
        if a.get("kind") not in (KIND, "anonymised"):
            return []
        out.append(a)
        at = a.get("sha256_after")
        if at == sha_to:
            return out
    return []


def chain_problem(links: list[dict[str, Any]], data: bytes | None) -> str | None:
    """Why the chain of redactions (and anonymisations) of one file does not hold, or None.

    The last link is checked against the file as it is (``data``); an earlier one only as a record, its
    sizes against the size the next link records the file had before it.
    """
    from . import anonymise as an

    size: int | None = None
    for i in range(len(links) - 1, -1, -1):
        a = links[i]
        last = i == len(links) - 1
        if a.get("kind") == an.KIND:
            why = an.record_problem(a, data) if last else None
            size = None
        else:
            why = record_problem(a, data, size_after=size, bytes_known=last)
            red: dict[str, Any] = a["redaction"] if isinstance(a.get("redaction"), dict) else {}
            size = red.get("bytes_before") if isinstance(red.get("bytes_before"), int) else None
        if why:
            return why
    return None


def check(folder: Path, text: str | list[str]) -> list[str]:
    """With the text(s) that were removed: rebuild each redacted file's earlier version and compare its fingerprint.

    Returns one line per redaction amendment ("✓ path: …" or "✗ path: …"). Only the last redaction of a file can be
    rebuilt from the file as it is now; earlier ones are named. With several texts (``--text`` given more than
    once), each amendment is checked with the text it took out: the one that rebuilds the earlier file; a ✗
    only when none does.
    """
    folder = Path(folder)
    texts = [text] if isinstance(text, str) else list(text)
    prov = _provenance(folder)
    reds = [a for a in prov.get("amendments") or [] if isinstance(a, dict) and a.get("kind") == KIND]
    last: dict[str, dict[str, Any]] = {}
    for a in prov.get("amendments") or []:
        if isinstance(a, dict) and isinstance(a.get("path"), str):
            last[a["path"]] = a
    encoded = [t.encode("utf-8") for t in texts]
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
        sized = [t for t in encoded if len(t) == red["removed_bytes"]]
        if not sized:
            lengths = ", ".join(str(len(t)) for t in encoded)
            out.append(
                f"✗ {rel}: the text{'s are' if len(encoded) > 1 else ' is'} {lengths} bytes long, "
                f"the redaction removed {red['removed_bytes']}"
            )
            continue
        recorded = str(a.get("sha256_before") or "")
        if recorded.startswith(KEYED) and not salt_file().is_file():
            out.append(
                f"· {rel}: its earlier fingerprint is keyed to the computer that redacted it "
                "(~/.e2er/redaction-salt); run the check there"
            )
            continue
        rep = red["replacement"].encode("utf-8")
        matched = False
        for t in sized:
            before = restore(data, red["offsets"], rep, t)
            if (keyed(before) if recorded.startswith(KEYED) else _sha(before)) == recorded:
                matched = True
                break
        if matched:
            out.append(
                f"✓ {rel}: with the text put back, the file is exactly the earlier one ({red['count']} place(s))"
            )
        else:
            out.append(f"✗ {rel}: with the text put back, the file is not the earlier one")
    return out
