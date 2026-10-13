"""Full texts of the records that passed screening, page by page, or why there is none.

For every record judged ``include`` or ``unsure`` on its title and abstract,
in this order:

1. a PDF the researcher supplied: ``data/fulltext/<id>.pdf`` in the study's
   workspace, or ``fulltext/<id>.pdf`` in a ``LOCAL_DATA_DIR`` folder (``<id>`` is
   the record id, e.g. ``W2101234567``, or the DOI with ``/`` written as ``_``);
2. the open-access PDF OpenAlex lists for the work (``best_oa_location``), then
   its open-access address;
3. when neither is a PDF (OpenAlex's address is often a landing page), the
   open-access resolvers e2er uses for references (Unpaywall and others), by DOI.

The text is extracted page by page with pypdf (running heads and page numbers
removed) into ``fulltext/<id>.txt`` with ``=== page N ===`` lines, the form the
extraction cites (page and quote). ``fulltext_log.json`` records, per record,
where the text came from and the SHA-256 of the PDF, or why no full text is
available. A record without a full text is assessed on its abstract, and the
extraction says so. The step runs at every start: a PDF the researcher saved
since is read, earlier failures are not downloaded again (remove a record from
``fulltext_log.json`` to try it again). Full texts stay in the workspace: they are not exported,
because their licences differ.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

from ...logging_config import get_logger

logger = get_logger(__name__)

DIR = "fulltext"
LOG_FILE = "fulltext_log.json"
MAX_PDF_BYTES = 30 * 1024 * 1024
LIMIT_REASON = "download limit of the step reached"


def fetch_pdf(url: str) -> bytes:
    """Download one PDF (raises on failure). The replay level replaces this."""
    from ..fetch.http import fetch_bytes

    return asyncio.run(
        fetch_bytes(url, headers={"User-Agent": "e2er (research; mailto:research@e2er.app)"}, max_bytes=MAX_PDF_BYTES)
    )


def resolve_pdf(doi: str) -> tuple[str, str] | None:
    """An open-access PDF address for a DOI from the resolver chain, or None. The replay level replaces this."""
    from ..literature.fulltext import resolve_oa_pdf

    try:
        return asyncio.run(resolve_oa_pdf(doi))
    except Exception as e:  # noqa: BLE001 — a resolver outage means no full text, not a failed step
        logger.debug("OA resolvers failed for %s: %s", doi, e)
        return None


def pdf_pages(data: bytes) -> list[str]:
    """Text of each page (pypdf, page furniture removed); [] when the PDF has no text layer."""
    import io

    from pypdf import PdfReader

    from ..literature.pdf import strip_page_furniture

    try:
        reader = PdfReader(io.BytesIO(data))
        pages = [(p.extract_text() or "") for p in reader.pages]
    except Exception as e:  # noqa: BLE001 — a broken PDF is "no text", reported
        logger.debug("PDF unreadable: %s", e)
        return []
    if not any(p.strip() for p in pages):
        return []
    return strip_page_furniture(pages)


def pages_text(pages: list[str]) -> str:
    return "".join(f"=== page {i} ===\n{p.strip()}\n" for i, p in enumerate(pages, start=1))


def read_pages(path: Path) -> dict[int, str]:
    """``fulltext/<id>.txt`` back into {page: text}."""
    import re

    parts = re.split(r"^=== page (\d+) ===$", path.read_text(encoding="utf-8", errors="replace"), flags=re.M)
    return {int(parts[i]): parts[i + 1] for i in range(1, len(parts) - 1, 2)}


def _local_dirs(ws: Path) -> list[Path]:
    dirs = [ws / "data" / "fulltext"]
    try:
        from ...config import get_settings

        for d in (get_settings().local_data_dir or "").split(","):
            if d.strip():
                dirs.append(Path(d.strip()).expanduser() / "fulltext")
    except Exception:  # noqa: BLE001 — settings are optional here (tests, scripts)
        pass
    return dirs


def _local_pdf(ws: Path, rec: dict[str, Any]) -> Path | None:
    names = [f"{rec['id']}.pdf"]
    if rec.get("doi"):
        names.append(rec["doi"].replace("/", "_") + ".pdf")
    for d in _local_dirs(ws):
        for n in names:
            if (d / n).is_file():
                return d / n
    return None


def _write(ws: Path, rid: str, data: bytes, origin: str, url: str = "") -> dict[str, Any] | None:
    if data[:1024].lstrip()[:5] != b"%PDF-":
        return None
    pages = pdf_pages(data)
    if not pages:
        return {"status": "not available", "reason": f"the PDF from {origin} has no text layer (a scan?)"}
    out = ws / DIR / f"{rid}.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(pages_text(pages), encoding="utf-8")
    return {
        "status": "ok",
        "origin": origin,
        "url": url,
        "sha256": hashlib.sha256(data).hexdigest(),
        "pages": len(pages),
        "chars": sum(len(p) for p in pages),
        "text_file": f"{DIR}/{rid}.txt",
    }


def get_one(ws: Path, rec: dict[str, Any], *, allow_download: bool = True) -> dict[str, Any]:
    """The full text of one record into fulltext/<id>.txt, or why there is none."""
    attempts: list[str] = []
    local = _local_pdf(ws, rec)
    if local is not None:
        got = _write(ws, rec["id"], local.read_bytes(), "supplied by the researcher", str(local))
        if got and got["status"] == "ok":
            got["origin"] = "local"
            return got
        attempts.append(f"{local.name}: not a readable PDF")
    if not allow_download:
        return {"status": "not available", "reason": LIMIT_REASON, "attempts": attempts}
    tried: set[str] = set()

    def attempt(urls: list[str]) -> dict[str, Any] | None:
        for url in dict.fromkeys(u for u in urls if u and u not in tried):
            tried.add(url)
            try:
                data = fetch_pdf(url)
            except Exception as e:  # noqa: BLE001 — a failed download is a reason, recorded
                attempts.append(f"{url}: {str(e)[:160]}")
                continue
            got = _write(ws, rec["id"], data, "open access", url)
            if got is None:
                attempts.append(f"{url}: not a PDF (a landing page?)")
                continue
            if got["status"] == "ok":
                return got
            attempts.append(f"{url}: {got['reason']}")
        return None

    got = attempt([rec.get("oa_pdf_url") or "", rec.get("oa_url") or ""])
    if got is not None:
        return got
    # OpenAlex's addresses are often landing pages: the resolvers (Unpaywall first) may know the PDF.
    if rec.get("doi"):
        found = resolve_pdf(rec["doi"])
        if found:
            got = attempt([found[0]])
            if got is not None:
                got["origin"] = f"open access ({found[1]})"
                return got
    reason = "no open-access full text found" if not attempts else "no readable open-access PDF"
    return {"status": "not available", "reason": reason, "attempts": attempts}


def fulltext_step(ws: Path, candidates: list[dict[str, Any]], *, max_downloads: int = 150) -> dict[str, Any]:
    """Every candidate's full text (kept from an earlier run when its file is still there)."""
    ws = Path(ws)
    log_path = ws / LOG_FILE
    old = json.loads(log_path.read_text(encoding="utf-8")).get("records", {}) if log_path.is_file() else {}
    out: dict[str, Any] = {}
    downloads = 0
    for rec in candidates:
        prev = old.get(rec["id"])
        if prev and prev.get("status") == "ok" and (ws / prev.get("text_file", "")).is_file():
            out[rec["id"]] = prev
            continue
        if prev and prev.get("status") != "ok" and prev.get("reason") != LIMIT_REASON and _local_pdf(ws, rec) is None:
            # Tried before and nothing new to read: no second round of downloads at every start
            # (the live run sent the same 57 failing requests again on resume). A PDF the
            # researcher saves is read; removing the record from fulltext_log.json tries again.
            out[rec["id"]] = prev
            continue
        got = get_one(ws, rec, allow_download=downloads < max_downloads)
        if str(got.get("origin", "")).startswith("open access") or got.get("attempts"):
            downloads += 1
        out[rec["id"]] = got
    counts = {
        "sought": len(candidates),
        "retrieved": sum(1 for v in out.values() if v["status"] == "ok"),
        "not_retrieved": sum(1 for v in out.values() if v["status"] != "ok"),
    }
    log = {"records": out, "counts": counts}
    log_path.write_text(json.dumps(log, indent=2), encoding="utf-8")
    return log
