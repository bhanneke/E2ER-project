"""Zenodo connector — download a published record's files, keyless, and verify them.

Used by the `replication` template's `fetch` step, not by specialists: a
replication package is the input of the study, so it is fetched by the runner
before any model sees it, and its integrity is a fact recorded by code.

What it does, for one record:

  * reads the record from the public REST API (``/api/records/<id>``, no key);
  * refuses it when the files are not open (restricted, embargoed) or larger
    than the size limit;
  * downloads every file, sequentially and with a small delay between
    requests, streaming each one through SHA-256 *and* the checksum Zenodo
    publishes for it (``md5:<hex>`` today); a mismatch deletes the file and
    raises, so nothing half-verified is left behind;
  * returns the record's metadata, the publication it points to, and one entry
    per file with both digests, for ``package_manifest.json``.

Zenodo publishes MD5 checksums, not SHA-256. The SHA-256 of each file is
computed here, from the same bytes that were verified against Zenodo's
checksum, and is what the rest of e2er (sandbox log, dossier) refers to.
"""

from __future__ import annotations

import hashlib
import html
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from ...logging_config import get_logger

logger = get_logger(__name__)

API_ROOT = "https://zenodo.org/api"
USER_AGENT = "e2er-zenodo-connector (+https://e2er.org)"
#: Pause between requests. Zenodo's public API is rate-limited per IP; a
#: replication fetches a handful of files, so politeness costs seconds.
REQUEST_DELAY_SECONDS = 1.0
DEFAULT_MAX_BYTES = 1_000_000_000  # 1 GB
_TIMEOUT = httpx.Timeout(60.0, read=300.0)
_CHUNK = 1 << 20

_RECORD_PATTERNS = (
    re.compile(r"10\.5281/zenodo\.(\d+)", re.IGNORECASE),
    re.compile(r"zenodo\.org/(?:records|record|api/records)/(\d+)", re.IGNORECASE),
)
_DOI = re.compile(r"\b10\.\d{4,9}/[^\s\"<>,;)]+")
_SAFE_KEY = re.compile(r"^[^/\\\x00]+$")


class ZenodoError(RuntimeError):
    """The record cannot be fetched as an open, verified package."""


class ZenodoChecksumError(ZenodoError):
    """A downloaded file does not match the checksum Zenodo publishes for it."""


@dataclass(frozen=True)
class FetchedFile:
    key: str
    path: str  # relative to the destination folder
    size: int
    sha256: str
    zenodo_checksum: str  # as Zenodo publishes it, e.g. "md5:e12d…"
    verified: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "path": self.path,
            "size": self.size,
            "sha256": self.sha256,
            "zenodo_checksum": self.zenodo_checksum,
            "verified": self.verified,
        }


@dataclass
class FetchedRecord:
    record_id: str
    doi: str
    title: str
    creators: list[str]
    licence: str
    publication_date: str
    version: str
    publications: list[dict[str, str]]
    files: list[FetchedFile] = field(default_factory=list)
    url: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": "zenodo",
            "record_id": self.record_id,
            "doi": self.doi,
            "url": self.url,
            "title": self.title,
            "creators": self.creators,
            "licence": self.licence,
            "publication_date": self.publication_date,
            "version": self.version,
            "publications": self.publications,
            "files": [f.as_dict() for f in self.files],
        }


def parse_record_id(text: str) -> str | None:
    """The Zenodo record id in a DOI, a record URL, or free text that contains one."""
    for pattern in _RECORD_PATTERNS:
        m = pattern.search(text or "")
        if m:
            return m.group(1)
    return None


def linked_publications(metadata: dict[str, Any]) -> list[dict[str, str]]:
    """Publications the record points to: related identifiers, then DOIs in the description.

    Datasets the record was derived from (Eurostat tables, other Zenodo
    deposits) are not publications and are left out.
    """
    found: list[dict[str, str]] = []
    seen: set[str] = set()
    for rel in metadata.get("related_identifiers") or []:
        ident = str(rel.get("identifier") or "")
        rtype = str(rel.get("resource_type") or "")
        relation = str(rel.get("relation") or "")
        if not ident or ident in seen:
            continue
        is_pub = rtype.startswith("publication") or (
            relation in {"isSupplementTo", "isPublishedIn", "isDocumentedBy", "cites", "references"}
            and ident.startswith("10.")
            and "zenodo" not in ident
            and not rtype.startswith("dataset")
        )
        if is_pub:
            seen.add(ident)
            found.append({"identifier": ident, "relation": relation, "resource_type": rtype, "from": "related"})
    desc = html.unescape(str(metadata.get("description") or ""))
    for doi in _DOI.findall(desc):
        doi = doi.rstrip(".")
        if doi not in seen and "zenodo" not in doi:
            seen.add(doi)
            found.append({"identifier": doi, "relation": "", "resource_type": "", "from": "description"})
    return found


def _digest_name(checksum: str) -> tuple[str, str]:
    algo, _, value = (checksum or "").partition(":")
    return algo.lower(), value.lower()


class ZenodoClient:
    """Keyless client for the public Zenodo REST API.

    ``client`` is injectable so tests can hand in an ``httpx.Client`` on a
    ``MockTransport``; ``sleep`` so they need not wait.
    """

    def __init__(
        self,
        api_root: str = API_ROOT,
        *,
        client: httpx.Client | None = None,
        delay: float = REQUEST_DELAY_SECONDS,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._root = api_root.rstrip("/")
        self._client = client or httpx.Client(
            timeout=_TIMEOUT, follow_redirects=True, headers={"User-Agent": USER_AGENT}
        )
        self._delay = delay
        self._sleep = sleep
        self._requests = 0

    def _pace(self) -> None:
        if self._requests and self._delay > 0:
            self._sleep(self._delay)
        self._requests += 1

    def get_record(self, record_id: str) -> dict[str, Any]:
        if not str(record_id).isdigit():
            raise ZenodoError(f"not a Zenodo record id: {record_id!r}")
        self._pace()
        r = self._client.get(f"{self._root}/records/{record_id}", headers={"Accept": "application/json"})
        if r.status_code == 404:
            raise ZenodoError(f"Zenodo record {record_id} does not exist")
        if r.status_code != 200:
            raise ZenodoError(f"Zenodo record {record_id}: HTTP {r.status_code}")
        return r.json()

    def fetch(self, record_id: str, dest: Path, *, max_bytes: int = DEFAULT_MAX_BYTES) -> FetchedRecord:
        """Download and verify every file of an open record into ``dest``."""
        rec = self.get_record(record_id)
        meta = rec.get("metadata") or {}
        access = (rec.get("access") or {}).get("files") or meta.get("access_right") or "open"
        if access != "open":
            raise ZenodoError(f"Zenodo record {record_id}: files are {access}, not open")
        files = rec.get("files") or []
        if not files:
            raise ZenodoError(f"Zenodo record {record_id} has no files")
        total = sum(int(f.get("size") or 0) for f in files)
        if total > max_bytes:
            raise ZenodoError(f"Zenodo record {record_id} is {total:,} bytes, above the limit of {max_bytes:,}")

        out = FetchedRecord(
            record_id=str(record_id),
            doi=str(rec.get("doi") or meta.get("doi") or ""),
            url=str((rec.get("links") or {}).get("html") or f"https://zenodo.org/records/{record_id}"),
            title=str(meta.get("title") or ""),
            creators=[str(c.get("name") or "") for c in meta.get("creators") or []],
            licence=str((meta.get("license") or {}).get("id") or ""),
            publication_date=str(meta.get("publication_date") or ""),
            version=str(meta.get("version") or ""),
            publications=linked_publications(meta),
        )
        dest.mkdir(parents=True, exist_ok=True)
        for f in files:
            out.files.append(self._download(record_id, f, dest))
        return out

    def _download(self, record_id: str, entry: dict[str, Any], dest: Path) -> FetchedFile:
        key = str(entry.get("key") or "")
        if not key or not _SAFE_KEY.match(key) or key in {".", ".."}:
            raise ZenodoError(f"Zenodo record {record_id}: refusing file name {key!r}")
        checksum = str(entry.get("checksum") or "")
        algo, expected = _digest_name(checksum)
        if algo not in hashlib.algorithms_available or not expected:
            raise ZenodoError(f"{key}: Zenodo publishes no usable checksum ({checksum!r})")
        url = ((entry.get("links") or {}).get("self")) or f"{self._root}/records/{record_id}/files/{key}/content"
        target = dest / key
        sha = hashlib.sha256()
        other = hashlib.new(algo)
        size = 0
        self._pace()
        try:
            with self._client.stream("GET", url) as r:
                if r.status_code != 200:
                    raise ZenodoError(f"{key}: HTTP {r.status_code}")
                with target.open("wb") as fh:
                    for chunk in r.iter_bytes(_CHUNK):
                        fh.write(chunk)
                        sha.update(chunk)
                        other.update(chunk)
                        size += len(chunk)
        except httpx.HTTPError as e:
            target.unlink(missing_ok=True)
            raise ZenodoError(f"{key}: download failed: {e}") from e
        except ZenodoError:
            target.unlink(missing_ok=True)
            raise
        got = other.hexdigest()
        if got != expected:
            target.unlink(missing_ok=True)
            raise ZenodoChecksumError(f"{key}: {algo} {got} does not match Zenodo's {expected}")
        declared = entry.get("size")
        if declared is not None and int(declared) != size:
            target.unlink(missing_ok=True)
            raise ZenodoChecksumError(f"{key}: {size} bytes downloaded, Zenodo declares {declared}")
        logger.info("zenodo %s: %s verified (%s, sha256 %s)", record_id, key, checksum, sha.hexdigest()[:12])
        return FetchedFile(
            key=key, path=key, size=size, sha256=sha.hexdigest(), zenodo_checksum=checksum, verified=True
        )
