"""Read a local Zotero library (``zotero.sqlite`` + ``storage/`` PDFs).

Distinct from ``providers.ZoteroLibrary``, which uses the Zotero *Web API*. This
reads the on-disk SQLite database a desktop Zotero install maintains, so a user
can point ``LITERATURE_DIR`` at their Zotero data folder with no API key.

**Never writes to the user's database.** Zotero keeps ``zotero.sqlite`` locked
(WAL mode) while running, so we copy it (plus any ``-wal``/``-shm``) to a scratch
dir and open the copy ``mode=ro&immutable=1``. The copy is deleted after read.

Robust to Zotero schema-version drift: we query by stable field/type *names*
(``title``, ``DOI``, …), never numeric IDs, and degrade to ``[]`` on any error.
"""

from __future__ import annotations

import re
import shutil
import sqlite3
import tempfile
from pathlib import Path

from ...logging_config import get_logger
from .models import PaperMetadata

logger = get_logger(__name__)

_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
_SKIP_TYPES = {"attachment", "note", "annotation"}


def detect_zotero(root: Path) -> Path | None:
    """Return the ``zotero.sqlite`` path if ``root`` is (or contains) a Zotero
    data dir, else None."""
    root = Path(root)
    direct = root / "zotero.sqlite"
    if direct.is_file():
        return direct
    if root.name == "zotero.sqlite" and root.is_file():
        return root
    return None


def _year(value: str | None) -> int | None:
    if not value:
        return None
    m = _YEAR_RE.search(value)
    return int(m.group(0)) if m else None


def _copy_ro(db_path: Path) -> tuple[Path, Path]:
    """Copy zotero.sqlite (+ WAL/SHM) into a temp dir. Returns (temp_dir, db_copy)."""
    tmp = Path(tempfile.mkdtemp(prefix="e2er_zotero_"))
    copy = tmp / "zotero.sqlite"
    shutil.copy2(db_path, copy)
    for suffix in ("-wal", "-shm"):
        side = db_path.with_name(db_path.name + suffix)
        if side.is_file():
            shutil.copy2(side, tmp / (db_path.name + suffix))
    return tmp, copy


def read_zotero_sqlite(zotero_dir: Path) -> list[PaperMetadata]:
    """Extract bibliographic items from a local Zotero library. Never raises."""
    zotero_dir = Path(zotero_dir)
    db_path = detect_zotero(zotero_dir)
    if db_path is None:
        return []
    storage_dir = db_path.parent / "storage"

    tmp_dir: Path | None = None
    try:
        tmp_dir, copy = _copy_ro(db_path)
        conn = sqlite3.connect(f"file:{copy}?mode=ro&immutable=1", uri=True)
        try:
            return _extract(conn, storage_dir)
        finally:
            conn.close()
    except Exception as e:  # noqa: BLE001 — degrade to [] on any failure
        logger.warning("local Zotero read failed for %s: %s", db_path, e)
        return []
    finally:
        if tmp_dir is not None:
            shutil.rmtree(tmp_dir, ignore_errors=True)


def _extract(conn: sqlite3.Connection, storage_dir: Path) -> list[PaperMetadata]:
    # Field values per item: itemData → itemDataValues + fields (by name).
    fields_by_item: dict[int, dict[str, str]] = {}
    for item_id, field_name, value in conn.execute(
        "SELECT id.itemID, f.fieldName, idv.value "
        "FROM itemData id JOIN fields f ON f.fieldID = id.fieldID "
        "JOIN itemDataValues idv ON idv.valueID = id.valueID"
    ):
        fields_by_item.setdefault(item_id, {})[field_name] = value

    # Authors per item, ordered.
    authors_by_item: dict[int, list[str]] = {}
    for item_id, first, last, field_mode in conn.execute(
        "SELECT ic.itemID, c.firstName, c.lastName, c.fieldMode "
        "FROM itemCreators ic JOIN creators c ON c.creatorID = ic.creatorID "
        "ORDER BY ic.itemID, ic.orderIndex"
    ):
        # fieldMode=1 → single-field (institutional) name stored in lastName.
        name = (last or "").strip() if field_mode == 1 else f"{(first or '').strip()} {(last or '').strip()}".strip()
        if name:
            authors_by_item.setdefault(item_id, []).append(name)

    # PDF attachments → resolved storage path, keyed by parent item.
    pdf_by_parent: dict[int, str] = {}
    for parent_id, att_key, path in conn.execute(
        "SELECT ia.parentItemID, i.key, ia.path "
        "FROM itemAttachments ia JOIN items i ON i.itemID = ia.itemID "
        "WHERE ia.parentItemID IS NOT NULL AND ia.contentType = 'application/pdf'"
    ):
        if not path:
            continue
        if path.startswith("storage:"):
            resolved = storage_dir / att_key / path[len("storage:") :]
        else:
            resolved = Path(path)  # linked-file (absolute) attachment
        if parent_id not in pdf_by_parent and resolved.is_file():
            pdf_by_parent[parent_id] = str(resolved)

    deleted = {row[0] for row in conn.execute("SELECT itemID FROM deletedItems")}

    out: list[PaperMetadata] = []
    for item_id, type_name in conn.execute(
        "SELECT i.itemID, it.typeName FROM items i JOIN itemTypes it ON it.itemTypeID = i.itemTypeID"
    ):
        if type_name in _SKIP_TYPES or item_id in deleted:
            continue
        f = fields_by_item.get(item_id, {})
        title = (f.get("title") or "").strip()
        if not title:
            continue
        journal = f.get("publicationTitle") or f.get("bookTitle") or f.get("proceedingsTitle") or ""
        source_pdf = pdf_by_parent.get(item_id, "")
        out.append(
            PaperMetadata(
                title=title[:500],
                authors=authors_by_item.get(item_id, []),
                year=_year(f.get("date")),
                doi=(f.get("DOI") or "").strip(),
                abstract=(f.get("abstractNote") or "").strip(),
                journal=journal.strip(),
                url=(f.get("url") or "").strip(),
                source="zotero_local",
                raw={"source_pdf": source_pdf} if source_pdf else {},
            )
        )
    return out
