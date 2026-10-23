"""``e2er redact <folder> --text <text>``: take personal data out of a study folder before publishing.

See ``src/core/redact.py``. The files change, provenance.json records an
amendment per file (kind "redacted"), and the next ``e2er publish`` shows the
amendments in the dossier. ``--check`` changes nothing: with the text that was
removed, it rebuilds each redacted file's earlier version and compares its
fingerprint.
"""

from __future__ import annotations

from pathlib import Path

from .core import redact as rd


def redact(folder: str, texts: list[str], *, replacement: str, dry_run: bool = False, check: bool = False) -> int:
    root = Path(folder).expanduser().resolve()
    if not root.is_dir():
        print(f"error: {root} is not a folder")
        return 2
    if not texts:
        print("error: name the text to remove with --text")
        return 2
    try:
        if check:
            # Each amendment is checked with the text it took out (rd.check matches them).
            lines = rd.check(root, texts)
            if not lines:
                print("No redaction is recorded in provenance.json.")
                return 1
            for line in lines:
                print(line)
            return 1 if any(line.startswith("✗") for line in lines) else 0
        total = 0
        # All or nothing: a refused second text puts the first one's changes back (rd.redact_all).
        results = rd.redact_all(root, texts, replacement=replacement, dry_run=dry_run)
        for i, (t, (found, written)) in enumerate(zip(texts, results, strict=True), 1):
            label = f"text {i}" if len(texts) > 1 else "the text"
            for rel in found.pdfs_unread:
                print(f"note: {rel} was not searched (no pdftotext on this computer); check it before publishing")
            if not found.edits:
                print(f"{label}: not found in the folder's files")
                continue
            for rel, (_b, _a, offsets) in found.edits.items():
                verb = "would replace" if dry_run else "replaced"
                print(f"  {rel}: {verb} {len(offsets)} occurrence(s) of {label} with {replacement}")
            total += len(found.edits)
            if written:
                print(f'✓ Recorded {len(written)} amendment(s) in provenance.json (kind "{rd.KIND}": {rd.REASON})')
            public = [e["path"] for e in written if not str(e.get("sha256_before") or "").startswith(rd.KEYED)]
            if found.edits and rd.guessable(t):
                where = (
                    f" The earlier fingerprint of {', '.join(public)} is public (a pre-registered file, or a folder "
                    "published before): with it, a guess can be confirmed."
                    if public
                    else " Its record keeps the earlier fingerprint keyed to this computer, so the record alone "
                    "confirms no guess."
                )
                print(
                    f"warning: {label} is short ({len(t.strip())} characters): a short text such as a phone number "
                    f"can be guessed by trying.{where}"
                )
    except rd.RedactError as e:
        msg = str(e)
        if len(texts) > 1 and not dry_run and "nothing was changed" not in msg:
            msg += "; nothing was changed (none of the texts was redacted)"
        print(f"error: {msg}")
        return 1
    except OSError as e:
        print(f"error: the folder could not be written ({e}); every file was put back as it was")
        return 1
    if dry_run:
        print("dry run: nothing was changed")
    elif total:
        print("  The next `e2er publish` shows the redactions in the dossier; `e2er verify` checks them.")
    return 0
