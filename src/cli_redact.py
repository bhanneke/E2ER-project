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
            bad = False
            for t in texts:
                lines = rd.check(root, t)
                if not lines:
                    print("No redaction is recorded in provenance.json.")
                    return 1
                for line in lines:
                    print(line)
                bad = bad or any(line.startswith("✗") for line in lines)
            return 1 if bad else 0
        total = 0
        for i, t in enumerate(texts, 1):
            label = f"text {i}" if len(texts) > 1 else "the text"
            found, written = rd.redact(root, t, replacement=replacement, dry_run=dry_run)
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
    except rd.RedactError as e:
        print(f"error: {e}")
        return 1
    if dry_run:
        print("dry run: nothing was changed")
    elif total:
        print("  The next `e2er publish` shows the redactions in the dossier; `e2er verify` checks them.")
    return 0
