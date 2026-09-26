"""Depositing on Zenodo with the researcher's own account.

Used for pre-registrations (``e2er preregister deposit --zenodo``) and for the
public data and code of a study (``e2er publish --zenodo``). Files go from this
machine straight to Zenodo; the token is the researcher's and is never sent to
e2er.org.

A deposit is created with a pre-reserved DOI, so the DOI is known before the
record is published: ``e2er publish`` writes it into the dossier, then puts
the dossier's address into the Zenodo description, then publishes.

The token comes from ``ZENODO_TOKEN`` (``ZENODO_SANDBOX_TOKEN`` for the
sandbox), else from the system keychain (service ``zenodo.org`` or
``sandbox.zenodo.org``, username ``token``).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

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


def load_token(sandbox: bool = False) -> str | None:
    """The researcher's Zenodo token: environment first, then the system keychain."""
    env = os.environ.get("ZENODO_SANDBOX_TOKEN" if sandbox else "ZENODO_TOKEN")
    if env:
        return env
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
    return f"set {var} to a personal token from {site} (Applications → Personal access tokens, scope deposit:write)"


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

    def create(self, *, reserve_doi: bool = True) -> Deposit:
        body = {"metadata": {"prereserve_doi": True}} if reserve_doi else {}
        r = self._check(self.http.post("/api/deposit/depositions", json=body, headers=self.auth), "create a deposit")
        dep = r.json()
        doi = ((dep.get("metadata") or {}).get("prereserve_doi") or {}).get("doi")
        return Deposit(id=dep["id"], bucket=dep["links"]["bucket"], doi=doi)

    def upload(self, dep: Deposit, name: str, data: bytes) -> None:
        self._check(self.http.put(f"{dep.bucket}/{name}", content=data, headers=self.auth), f"upload {name}")
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


def creators(contributors: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Zenodo creators from manifest contributors (name and ORCID)."""
    out = []
    for c in contributors:
        entry = {"name": c.get("name") or c.get("github") or "Unknown"}
        if c.get("orcid"):
            entry["orcid"] = c["orcid"]
        out.append(entry)
    return out or [{"name": "Unknown"}]
