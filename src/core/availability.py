"""Whether a study's data and code are public, and where.

The researcher states it when publishing (``e2er publish --data public|private
--code public|private``); both are private unless stated otherwise. Private
material never leaves the machine: e2er.org receives only the fingerprints it
already gets for every file. Public material names where it lives (a
repository at a commit, or a DOI) so that others can find it.

The manifest always records availability. The dossier records it only when
something is public: a dossier without it means data and code are private,
and studies published before this existed keep their dossier addresses.
"""

from __future__ import annotations

from typing import Any

ACCESS = ("public", "private")
ITEMS = ("data", "code")


def code_url(repository: dict[str, Any]) -> str | None:
    """Where public code lives by default: the repository at the pinned commit and path."""
    url, commit = repository.get("url"), repository.get("commit")
    if not url or not commit:
        return None
    base = f"{url.rstrip('/')}/tree/{commit}"
    path = (repository.get("path") or "").strip("/")
    return f"{base}/{path}" if path else base


def resolve(
    *,
    data: str | None,
    code: str | None,
    data_url: str | None = None,
    code_url_: str | None = None,
    repository: dict[str, Any] | None = None,
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """The availability block and notes for the researcher (e.g. a URL ignored for private material)."""
    notes: list[str] = []
    out: dict[str, dict[str, Any]] = {}
    for item, access, url in (("data", data, data_url), ("code", code, code_url_)):
        access = access or "private"
        if access not in ACCESS:
            raise ValueError(f"--{item} must be public or private, not {access!r}")
        entry: dict[str, Any] = {"access": access}
        if access == "public":
            if url:
                entry["url"] = url
            elif item == "code" and repository and code_url(repository):
                entry["url"] = code_url(repository)
        elif url:
            notes.append(f"--{item}-url ignored: the {item} is private, so no address is published")
        out[item] = entry
    return out, notes


def any_public(availability: dict[str, dict[str, Any]] | None) -> bool:
    if not availability:
        return False
    return any(v.get("access") == "public" for v in availability.values())


def describe(availability: dict[str, dict[str, Any]] | None) -> str:
    """One line for the terminal: 'data private · code public (doi 10.5281/…)'."""
    if not availability:
        return "data private · code private (not stated)"
    parts = []
    for item in ITEMS:
        v = availability.get(item) or {"access": "private"}
        where = v.get("doi") and f"doi {v['doi']}" or v.get("url")
        parts.append(f"{item} {v['access']}" + (f" ({where})" if v["access"] == "public" and where else ""))
    return " · ".join(parts)
