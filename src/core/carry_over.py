"""A new version of a published study whose run database is gone: the earlier version's dossier, carried over.

The dossier's steps come from the run database. When it is gone (deleted,
or on another machine) and the folder was published before (``.e2er/link.json``),
``e2er publish`` takes the dossier of the version published last instead of
building one without steps. Before it does, the earlier dossier must be the
one this folder published: ``.e2er/link.json`` and ``e2er.json`` name it,
e2er.org's latest version of the study is that dossier (and that content),
and the document e2er.org serves hashes to its id.

The new dossier is that document unchanged (its steps, segments, events,
components and outcome), with the availability of the new version and an
amendment on ``e2er.json`` that says what happened: published again, the run
database not available, the dossier carried over from version N. No step is
added, removed or rebuilt.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .availability import any_public
from .dossier import dossier_id, short_id

#: The amendment's ``kind``: the dossier was carried over from an earlier version.
KIND = "carried_over"

#: The parts of e2er.json that describe the run: from the earlier version, since nothing here can read them again.
RUN_PARTS = ("ai", "process", "components")


class CarryOverError(Exception):
    """The earlier dossier cannot be carried over; the message says why, for the researcher."""


@dataclass
class Previous:
    """The published version whose dossier is carried over."""

    version: int
    dossier_id: str
    doc: dict[str, Any]
    manifest: dict[str, Any]  # the earlier e2er.json
    manifest_sha256: str
    platform_url: str

    @property
    def steps(self) -> int:
        return len(self.doc.get("workflow") or [])


def _json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def published_link(bundle: Path) -> dict[str, Any] | None:
    """The folder's record of its last publication (``.e2er/link.json``), or None."""
    link = _json(bundle / ".e2er" / "link.json")
    return link if isinstance(link, dict) and link.get("dossier_id") else None


def fetch_previous(bundle: Path, owner_project: str, request: Any = None) -> Previous:
    """The dossier of the version this folder published, as e2er.org holds it, checked against the folder.

    ``request`` is :func:`src.core.platform_client.request` (tests pass their own).
    """
    if request is None:
        from .platform_client import request as request_
    else:
        request_ = request
    link = published_link(bundle)
    if link is None:
        raise CarryOverError("the folder has no .e2er/link.json, so it was never published from here")
    if link.get("owner_project") != owner_project:
        raise CarryOverError(
            f".e2er/link.json says the folder was published as {link.get('owner_project')}, not {owner_project}; "
            "another study's dossier is never carried over"
        )
    did = str(link["dossier_id"])
    manifest = _json(bundle / "e2er.json")
    if not isinstance(manifest, dict):
        raise CarryOverError("e2er.json is missing or unreadable, so the earlier version cannot be checked")
    named = (manifest.get("dossier") or {}).get("id")
    if named != did:
        raise CarryOverError(f"e2er.json names the dossier {named}, .e2er/link.json {did}")
    base = str(link.get("platform_url") or "https://e2er.org").rstrip("/")
    try:
        code, study = request_(base, "GET", f"/api/v1/studies/{owner_project}")
    except Exception as e:  # noqa: BLE001 - a network error is the researcher's to see
        raise CarryOverError(f"could not reach {base} to fetch the earlier dossier: {e}") from e
    if code != 200:
        raise CarryOverError(f"{base} has no study {owner_project} (HTTP {code})")
    latest = study.get("latest") or {}
    if latest.get("dossier_id") != did:
        raise CarryOverError(
            f"the latest version on {base} (version {latest.get('number')}) has the dossier "
            f"{latest.get('dossier_id')}, not {did}, the one this folder published; "
            "a version published from elsewhere is never carried over"
        )
    if link.get("content_id") and latest.get("content_id") != link.get("content_id"):
        raise CarryOverError(
            f"the latest version on {base} describes other content ({latest.get('content_id')}) than this "
            f"folder published ({link.get('content_id')})"
        )
    try:
        code, doc = request_(base, "GET", f"/api/v1/dossiers/{short_id(did)}")
    except Exception as e:  # noqa: BLE001
        raise CarryOverError(f"could not fetch the dossier {short_id(did)} from {base}: {e}") from e
    if code != 200 or not isinstance(doc, dict) or "_body" in doc:
        raise CarryOverError(f"{base} did not return the dossier {short_id(did)} (HTTP {code})")
    got = dossier_id(doc)
    if got != did:
        raise CarryOverError(f"the dossier {base} returned hashes to {got}, not {did}; it is not carried over")
    local = (manifest.get("dossier") or {}).get("doc")
    if isinstance(local, dict) and dossier_id(local) != did:
        raise CarryOverError("the dossier in e2er.json does not hash to its id")
    version = latest.get("number")
    if not isinstance(version, int):
        version = int(link.get("version") or 0)
    return Previous(
        version=version,
        dossier_id=did,
        doc=doc,
        manifest=manifest,
        manifest_sha256=hashlib.sha256((bundle / "e2er.json").read_bytes()).hexdigest(),
        platform_url=base,
    )


def reason(previous: Previous, *, github: bool) -> str:
    where = " with files on GitHub" if github else ""
    return (
        f"published again{where}; run database not available, dossier carried over from version "
        f"{previous.version} ({previous.platform_url}/d/{short_id(previous.dossier_id)}). Its steps are the ones "
        "that version recorded; none was added or rebuilt."
    )


def data_mismatch(previous: Previous, data: list[dict[str, Any]]) -> list[str]:
    """Data files whose fingerprints differ between the earlier dossier and this folder."""
    before = {d.get("path"): d.get("sha256") for d in previous.doc.get("data") or []}
    now = {d["path"]: d["sha256"] for d in data}
    return sorted(p for p in set(before) | set(now) if before.get(p) != now.get(p))


def carried_dossier(
    previous: Previous,
    *,
    availability: dict[str, dict[str, Any]],
    amendments: list[dict[str, Any]],
    purpose: str | None,
    kind: str | None,
    github: bool,
    at: str,
    e2er_version: str,
) -> dict[str, Any]:
    """The new version's dossier: the earlier one, the new availability, the amendments and the carry-over."""
    doc = copy.deepcopy(previous.doc)
    if any_public(availability):
        doc["availability"] = copy.deepcopy(availability)
    else:
        doc.pop("availability", None)
    doc.pop("purpose", None)
    doc.pop("kind", None)
    if purpose:
        doc["purpose"] = purpose
        if kind:
            doc["kind"] = kind
    listed = list(doc.get("amendments") or [])
    seen = {json.dumps(a, sort_keys=True) for a in listed}
    for a in amendments:
        if json.dumps(a, sort_keys=True) not in seen:
            listed.append(copy.deepcopy(a))
    listed.append(
        {
            "path": "e2er.json",
            "kind": KIND,
            "sha256_before": previous.manifest_sha256,
            "reason": reason(previous, github=github),
            "at": at,
            "from_version": previous.version,
            "from_dossier": previous.dossier_id,
            "e2er_version": e2er_version,
        }
    )
    doc["amendments"] = listed
    return doc


def carried_manifest_parts(manifest: dict[str, Any], previous: Previous) -> None:
    """e2er.json's description of the run (agents, process, skills, the parts used): the earlier version's."""
    for key in RUN_PARTS:
        if key in previous.manifest:
            manifest[key] = copy.deepcopy(previous.manifest[key])
    uses = ((previous.manifest.get("dependencies") or {}).get("uses")) or None
    if uses is not None:
        manifest.setdefault("dependencies", {})["uses"] = list(uses)
