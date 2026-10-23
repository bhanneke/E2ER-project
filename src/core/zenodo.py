"""Depositing on Zenodo with the researcher's own account.

Used for pre-registrations (``e2er preregister deposit --zenodo``) and for the
public data and code of a study (``e2er publish --zenodo``). Files go from this
machine straight to Zenodo; the token is the researcher's and is never sent to
e2er.org.

A deposit is created with a pre-reserved DOI, so the DOI is known before the
record is published: ``e2er publish`` writes it into the dossier, then puts
the dossier's address into the Zenodo description, then publishes.

A new version of a study whose deposited files changed becomes a new version
of the same Zenodo record (``newversion``): a new DOI under the record's
concept DOI. The calls are those of Zenodo's deposit API
(https://developers.zenodo.org/): ``POST /api/deposit/depositions``, ``PUT
<bucket>/<name>``, ``PUT /api/deposit/depositions/<id>``, ``POST
.../actions/publish``, ``POST .../actions/newversion`` and the draft it names
in ``links.latest_draft``, ``GET``/``DELETE .../files``.

The token comes from ``ZENODO_TOKEN`` (``ZENODO_SANDBOX_TOKEN`` for the
sandbox), else from the system keychain (service ``zenodo.org`` or
``sandbox.zenodo.org``, username ``token``).
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

#: Zenodo takes at most this many files in one record.
MAX_FILES = 100

ZENODO_URL = "https://zenodo.org"
ZENODO_SANDBOX_URL = "https://sandbox.zenodo.org"

# Zenodo's licence ids for the SPDX ids e2er studies use.
LICENCES = {
    "MIT": "mit",
    "Apache-2.0": "apache-2.0",
    "BSD-3-Clause": "bsd-3-clause",
    "GPL-3.0": "gpl-3.0",
    "GPL-3.0-only": "gpl-3.0",
    "CC-BY-4.0": "cc-by-4.0",
    "CC-BY-SA-4.0": "cc-by-sa-4.0",
    "CC0-1.0": "cc0-1.0",
    "CC-BY-NC-4.0": "cc-by-nc-4.0",
}


class ZenodoError(RuntimeError):
    """A deposit could not be made; the message says why in plain words."""


def base_url(sandbox: bool = False) -> str:
    return ZENODO_SANDBOX_URL if sandbox else ZENODO_URL


def registered_doi(doi: str | None, base: str = ZENODO_URL) -> str | None:
    """The DOI a deposit is published under.

    sandbox.zenodo.org reserves a DOI with production's prefix (``prereserve_doi`` says
    ``10.5281/zenodo.N``) but publishes the record as ``10.5072/zenodo.N``, the test prefix
    (seen 2026-10-23, deposits 625117 and 625119). ``10.5281/zenodo.N`` is a real record on
    zenodo.org, so a sandbox deposit must never name it.
    """
    if doi and base.rstrip("/") == ZENODO_SANDBOX_URL and doi.startswith("10.5281/"):
        return "10.5072/" + doi.removeprefix("10.5281/")
    return doi


def load_token(sandbox: bool = False) -> str | None:
    """The researcher's Zenodo token: environment first, then the settings file Setup writes, then the keychain."""
    env = (os.environ.get("ZENODO_SANDBOX_TOKEN" if sandbox else "ZENODO_TOKEN") or "").strip()
    if env:
        return env
    from .test_guard import saved_logins_allowed

    if not saved_logins_allowed():
        return None  # a test run reads no saved token (src/core/test_guard.py)
    try:
        from ..config import get_settings

        settings = get_settings()
        saved = (getattr(settings, "zenodo_sandbox_token" if sandbox else "zenodo_token", None) or "").strip()
    except Exception:  # noqa: BLE001 - an unreadable settings file means "not saved there"
        saved = ""
    if saved:
        return saved
    try:
        import keyring  # type: ignore[import-not-found]
    except ImportError:
        return None
    try:
        token: str | None = keyring.get_password("sandbox.zenodo.org" if sandbox else "zenodo.org", "token")
    except Exception:  # noqa: BLE001 - locked or unavailable keychain
        return None
    return token


def token_hint(sandbox: bool = False) -> str:
    var = "ZENODO_SANDBOX_TOKEN" if sandbox else "ZENODO_TOKEN"
    site = "sandbox.zenodo.org" if sandbox else "zenodo.org"
    return (
        f"set {var} to a personal token from {site} "
        "(Applications → Personal access tokens, scopes deposit:write and deposit:actions)"
    )


@dataclass
class Deposit:
    """One deposition in progress: created with a reserved DOI, published at the end."""

    id: int
    bucket: str
    doi: str | None
    files: list[str] = field(default_factory=list)


def client_factory(base: str) -> Any:
    """The HTTP client for ``base``; tests replace this with an httpx.MockTransport client."""
    import httpx

    from .test_guard import RefusedInTestError, check_target

    try:
        check_target(base)
    except RefusedInTestError as e:
        raise ZenodoError(str(e)) from e
    return httpx.Client(base_url=base, timeout=120.0)


class Zenodo:
    """A small client for Zenodo's deposit API (create, upload, describe, publish)."""

    def __init__(self, token: str, *, base: str = ZENODO_URL, client: Any = None) -> None:
        self.base = base
        self.http = client or client_factory(base)
        self.auth = {"Authorization": f"Bearer {token}"}

    def _check(self, r: Any, what: str) -> Any:
        if r.status_code >= 400:
            try:
                detail = r.json().get("message") or r.text
            except Exception:  # noqa: BLE001
                detail = r.text
            raise ZenodoError(f"Zenodo refused to {what} ({r.status_code}): {str(detail)[:300]}")
        return r

    def _deposit(self, dep: dict[str, Any]) -> Deposit:
        doi = ((dep.get("metadata") or {}).get("prereserve_doi") or {}).get("doi")
        return Deposit(id=dep["id"], bucket=(dep.get("links") or {})["bucket"], doi=registered_doi(doi, self.base))

    def create(self, *, reserve_doi: bool = True) -> Deposit:
        body = {"metadata": {"prereserve_doi": True}} if reserve_doi else {}
        r = self._check(self.http.post("/api/deposit/depositions", json=body, headers=self.auth), "create a deposit")
        return self._deposit(r.json())

    def get(self, dep_id: int | str) -> dict[str, Any]:
        r = self._check(self.http.get(f"/api/deposit/depositions/{dep_id}", headers=self.auth), "read a deposit")
        out: dict[str, Any] = r.json()
        return out

    def new_version(self, published_id: int | str) -> Deposit:
        """A draft of a new version of the published deposit ``published_id``, with its own reserved DOI.

        Zenodo answers ``newversion`` with the published deposit, whose ``links.latest_draft`` is the
        new draft. The draft starts with the files of the version before; ``clear_files`` removes them.
        """
        r = self._check(
            self.http.post(f"/api/deposit/depositions/{published_id}/actions/newversion", headers=self.auth),
            "start a new version",
        )
        answer = r.json()
        draft_url = (answer.get("links") or {}).get("latest_draft")
        if draft_url:
            draft = self._check(self.http.get(draft_url, headers=self.auth), "read the new version").json()
        elif str(answer.get("id")) != str(published_id):
            draft = answer  # a Zenodo that answers with the draft itself
        else:
            raise ZenodoError("Zenodo started no new version: its answer names no draft (links.latest_draft)")
        dep = self._deposit(draft)
        if not dep.doi:
            raise ZenodoError(f"Zenodo reserved no DOI for the new version (deposit {dep.id}); nothing was published")
        return dep

    def files(self, dep_id: int | str) -> list[dict[str, Any]]:
        """The deposit's files as Zenodo lists them (``filename``, ``checksum``, ``links.self``)."""
        r = self._check(self.http.get(f"/api/deposit/depositions/{dep_id}/files", headers=self.auth), "list files")
        got = r.json()
        return [f for f in got if isinstance(f, dict)] if isinstance(got, list) else []

    def checksums(self, dep_id: int | str) -> dict[str, str]:
        """{filename: md5} of a deposit's files."""
        return {
            str(f.get("filename") or f.get("key")): str(f.get("checksum") or "").removeprefix("md5:")
            for f in self.files(dep_id)
        }

    def clear_files(self, dep: Deposit) -> None:
        """Remove every file of a draft (those a new version starts with, or a failed attempt's)."""
        for f in self.files(dep.id):
            url = (f.get("links") or {}).get("self") or f"/api/deposit/depositions/{dep.id}/files/{f.get('id')}"
            self._check(self.http.delete(url, headers=self.auth), f"remove {f.get('filename')} from the draft")

    def upload(self, dep: Deposit, name: str, data: bytes) -> None:
        self._check(
            self.http.put(f"{dep.bucket}/{quote(name, safe='')}", content=data, headers=self.auth), f"upload {name}"
        )
        dep.files.append(name)

    def describe(self, dep: Deposit, metadata: dict[str, Any]) -> None:
        meta = dict(metadata)
        if dep.doi:
            meta["prereserve_doi"] = True
        self._check(
            self.http.put(f"/api/deposit/depositions/{dep.id}", json={"metadata": meta}, headers=self.auth),
            "set the deposit's description",
        )

    def publish(self, dep: Deposit) -> dict[str, Any]:
        r = self._check(
            self.http.post(f"/api/deposit/depositions/{dep.id}/actions/publish", headers=self.auth), "publish"
        )
        done = r.json()
        links = done.get("links") or {}
        return {
            "service": "zenodo" if self.base == ZENODO_URL else self.base,
            "doi": done.get("doi") or dep.doi,
            "url": links.get("record_html") or links.get("html") or links.get("latest_html"),
        }


def deposit_files(
    files: list[tuple[str, bytes]],
    metadata: dict[str, Any],
    token: str,
    *,
    base: str = ZENODO_URL,
    client: Any = None,
) -> dict[str, Any]:
    """Create, upload, describe and publish in one go; returns {service, doi, url}."""
    z = Zenodo(token, base=base, client=client)
    dep = z.create(reserve_doi=False)
    for name, data in files:
        z.upload(dep, name, data)
    z.describe(dep, metadata)
    return z.publish(dep)


def md5s(files: list[tuple[str, bytes]]) -> dict[str, str]:
    """{name: md5} of the files of a deposit, as Zenodo's checksums state them."""
    return {name: hashlib.md5(data, usedforsecurity=False).hexdigest() for name, data in files}


def creators(contributors: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Zenodo creators from manifest contributors (name and ORCID)."""
    out = []
    for c in contributors:
        entry = {"name": c.get("name") or c.get("github") or "Unknown"}
        if c.get("orcid"):
            entry["orcid"] = c["orcid"]
        out.append(entry)
    return out or [{"name": "Unknown"}]
