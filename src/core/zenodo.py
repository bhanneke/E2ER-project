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
sandbox), else from the settings file Setup writes, else from the system
keychain (service ``zenodo.org`` or ``sandbox.zenodo.org``, username
``token``), else from the credentials file e2er's own login uses
(``~/.e2er/credentials.json``, mode 0600, key ``zenodo.org`` or
``sandbox.zenodo.org``). ``e2er zenodo login`` stores it in the keychain, or in
that file when there is no keychain.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote, urlsplit

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
    """A deposit could not be made; the message says why in plain words.

    ``status`` is Zenodo's HTTP status when Zenodo answered with an error (404: no such deposit), else None.
    """

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


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


def service(sandbox: bool = False) -> str:
    """The keychain service (and credentials-file key) of the token: ``zenodo.org`` or ``sandbox.zenodo.org``."""
    return "sandbox.zenodo.org" if sandbox else "zenodo.org"


#: The keychain username the token is stored under.
KEYRING_USER = "token"


def stored_token(sandbox: bool = False) -> tuple[str | None, str | None]:
    """The token ``e2er zenodo login`` stored and where it is: the keychain, else the credentials file.

    In a test run the keychain is never touched and only a credentials file the test names itself
    (``E2ER_CREDENTIALS``) is read (src/core/test_guard.py).
    """
    from . import platform_client as pc

    path = pc.credentials_path()
    if path is not None and pc.file_first(service(sandbox)):  # saved while the keychain refused: the newer one
        token = pc._read_credentials(path).get(service(sandbox))
        if isinstance(token, str) and token.strip():
            return token.strip(), str(path)
    kr = pc._keyring()
    if kr is not None:
        try:
            token = kr.get_password(service(sandbox), KEYRING_USER)
        except Exception:  # noqa: BLE001 - locked or unavailable keychain
            token = None
        if token and token.strip():
            return token.strip(), "the system keychain"
    if path is not None:
        token = pc._read_credentials(path).get(service(sandbox))
        if isinstance(token, str) and token.strip():
            return token.strip(), str(path)
    return None, None


def save_token(token: str, sandbox: bool = False) -> str:
    """Store the token in the system keychain, else in the credentials file (mode 0600); returns where."""
    from . import platform_client as pc

    kr = pc._keyring()
    if kr is not None:
        try:
            kr.set_password(service(sandbox), KEYRING_USER, token)
        except Exception:  # noqa: BLE001 - locked or unavailable keychain (no GUI session)
            pass
        else:
            pc._remove_credential(service(sandbox))  # no older copy stays in the file
            return "the system keychain"
    try:
        where = str(pc._write_credentials(service(sandbox), token, newer_than_keychain=kr is not None))
    except pc.PlatformError as e:
        raise ZenodoError(str(e)) from e
    if kr is not None:
        try:
            kr.delete_password(service(sandbox), KEYRING_USER)  # no older copy stays in the keychain
        except Exception:  # noqa: BLE001 - nothing stored there, or the keychain is locked
            pass
    return where


def forget_token(sandbox: bool = False, left: list[str] | None = None) -> list[str]:
    """Remove the stored token from the keychain and the credentials file; returns where it was removed.

    ``left`` gets what could not be removed: a keychain that refused (locked) may still hold the token.
    """
    from . import platform_client as pc

    removed: list[str] = []
    kr = pc._keyring()
    if kr is not None:
        try:
            if kr.get_password(service(sandbox), KEYRING_USER):
                kr.delete_password(service(sandbox), KEYRING_USER)
                removed.append("the system keychain")
        except Exception as e:  # noqa: BLE001 - the keychain is locked or unavailable
            if left is not None:
                left.append(f"the system keychain (it refused: {type(e).__name__}; it may be locked)")
    gone = pc._remove_credential(service(sandbox))
    if gone is not None:
        removed.append(str(gone))
    return removed


def _settings_token(sandbox: bool) -> str:
    try:
        from ..config import get_settings

        settings = get_settings()
        return (getattr(settings, "zenodo_sandbox_token" if sandbox else "zenodo_token", None) or "").strip()
    except Exception:  # noqa: BLE001 - an unreadable settings file means "not saved there"
        return ""


def env_var(sandbox: bool = False) -> str:
    return "ZENODO_SANDBOX_TOKEN" if sandbox else "ZENODO_TOKEN"


def find_token(sandbox: bool = False) -> tuple[str | None, str | None]:
    """The token publish uses and where it comes from: the environment, Setup's settings file, then what
    ``e2er zenodo login`` stored (keychain, credentials file)."""
    env = (os.environ.get(env_var(sandbox)) or "").strip()
    if env:
        return env, env_var(sandbox)
    from .test_guard import saved_logins_allowed

    if saved_logins_allowed():  # a test run reads no settings file (src/core/test_guard.py)
        saved = _settings_token(sandbox)
        if saved:
            return saved, "the settings file Setup writes"
    return stored_token(sandbox)


def load_token(sandbox: bool = False) -> str | None:
    """The researcher's Zenodo token: environment, settings file, keychain, credentials file."""
    return find_token(sandbox)[0]


def token_hint(sandbox: bool = False) -> str:
    flag = " --sandbox" if sandbox else ""
    return f"run `e2er zenodo login{flag}` once (in CI, set {env_var(sandbox)} instead)"


@dataclass
class TokenCheck:
    """What a harmless authenticated request said about a token."""

    works: bool
    message: str


def check_token(token: str, sandbox: bool = False, *, client: Any = None) -> TokenCheck:
    """Ask Zenodo for one of the account's deposits (``GET /api/deposit/depositions?size=1``): it changes nothing.

    Zenodo does not say which scopes a token has, and every request that would test deposit:write or
    deposit:actions creates or publishes something, so only the token itself is checked.
    """
    base = base_url(sandbox)
    try:
        http = client or client_factory(base)
        r = http.get("/api/deposit/depositions", params={"size": 1}, headers={"Authorization": f"Bearer {token}"})
    except ZenodoError as e:
        return TokenCheck(False, str(e))
    except Exception as e:  # noqa: BLE001 - network error; the message names no token
        return TokenCheck(False, f"could not reach {base} ({type(e).__name__}); nothing was checked")
    if r.status_code == 200:
        return TokenCheck(True, f"{base} accepted the token (it read your deposits; nothing was changed)")
    if r.status_code == 401:
        return TokenCheck(False, f"{base} does not accept this token (401): it is wrong, expired or was deleted")
    if r.status_code == 403:
        return TokenCheck(
            False,
            f"{base} knows the token but refused to show your deposits (403): it lacks a scope; "
            "make a new one with deposit:write and deposit:actions",
        )
    return TokenCheck(False, f"{base} answered {r.status_code}; the token could not be checked")


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


#: The only hosts the token goes to (over https): Zenodo and its sandbox.
TOKEN_HOSTS = frozenset({"zenodo.org", "sandbox.zenodo.org"})


class Zenodo:
    """A small client for Zenodo's deposit API (create, upload, describe, publish).

    The token goes only to ``https://zenodo.org`` or ``https://sandbox.zenodo.org`` (the one of
    ``base``): a link in Zenodo's answer (``links.bucket``, ``links.latest_draft``, a file's
    ``links.self``) that names another scheme or host is refused before anything is sent to it.
    """

    def __init__(self, token: str, *, base: str = ZENODO_URL, client: Any = None) -> None:
        parts = urlsplit(base)
        if parts.scheme != "https" or (parts.hostname or "").lower() not in TOKEN_HOSTS:
            raise ZenodoError(f"refusing to send the Zenodo token to {base}: only https://zenodo.org or its sandbox")
        self.base = base
        self._host = (parts.hostname or "").lower()
        self.http = client or client_factory(base)
        self.auth = {"Authorization": f"Bearer {token}"}

    def _url(self, link: str) -> str:
        """``link`` when it is a path on this Zenodo or an https URL on its host; else ZenodoError."""
        parts = urlsplit(str(link))
        if not parts.scheme and not parts.netloc:
            if not str(link).startswith("/"):
                raise ZenodoError(f"Zenodo answered with a link that is not a path: {str(link)[:120]}")
            return str(link)
        if parts.scheme != "https" or (parts.hostname or "").lower() != self._host or parts.port not in (None, 443):
            raise ZenodoError(
                f"Zenodo's answer points to {parts.scheme}://{parts.hostname}; the token is sent to {self._host} only"
            )
        return str(link)

    def _check(self, r: Any, what: str) -> Any:
        if r.status_code >= 400:
            try:
                detail = r.json().get("message") or r.text
            except Exception:  # noqa: BLE001
                detail = r.text
            raise ZenodoError(f"Zenodo refused to {what} ({r.status_code}): {str(detail)[:300]}", r.status_code)
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
            draft = self._check(self.http.get(self._url(draft_url), headers=self.auth), "read the new version").json()
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
            self._check(
                self.http.delete(self._url(url), headers=self.auth), f"remove {f.get('filename')} from the draft"
            )

    def upload(self, dep: Deposit, name: str, data: bytes) -> None:
        self._check(
            self.http.put(self._url(f"{dep.bucket}/{quote(name, safe='')}"), content=data, headers=self.auth),
            f"upload {name}",
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


def refuse_secrets(files: list[tuple[str, bytes]]) -> None:
    """ZenodoError naming every file of a deposit that holds a key or token."""
    from .secret_scan import scan_bytes

    hits = [f"{name}: looks like a {kind}" for name, data in files for kind in scan_bytes(data)]
    if hits:
        raise ZenodoError(
            "a file of the deposit holds something that looks like a key or token; nothing was sent:\n  "
            + "\n  ".join(hits[:20])
        )


def deposit_files(
    files: list[tuple[str, bytes]],
    metadata: dict[str, Any],
    token: str,
    *,
    base: str = ZENODO_URL,
    client: Any = None,
) -> dict[str, Any]:
    """Create, upload, describe and publish in one go; returns {service, doi, url}.

    Nothing is sent when a file holds a key or token (secret_scan, the check pack and the GitHub push run).
    """
    refuse_secrets(files)
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
