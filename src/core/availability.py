"""Whether a study's data and code are public, and where.

The researcher states it when publishing (``e2er publish --data public|private
--code public|private``); both are private unless stated otherwise. Private
material never leaves the machine: e2er.org receives only the fingerprints it
already gets for every file. Public material names where it lives (a
repository, or a DOI) so that others can find it. The commit of a repository
is never part of it (see ``code_url``).

The manifest always records availability. The dossier records it only when
something is public: a dossier without it means data and code are private,
and studies published before this existed keep their dossier addresses.
"""

from __future__ import annotations

from typing import Any

ACCESS = ("public", "private")
ITEMS = ("data", "code")


def code_url(repository: dict[str, Any]) -> str | None:
    """Where public code lives by default: the repository's address, without the commit.

    The commit is not part of the address on purpose. The address goes into
    the dossier, the dossier id into the paper's footnote and the paper's
    fingerprint into provenance.json: an address that named the commit would
    make the files depend on the commit that holds them, and no commit could
    ever hold the published folder. The commit is recorded beside the files
    instead, in the publish request (``repository.commit``, which e2er.org
    stores with the study version and checks the files at) and in e2er.json,
    with the study's folder in the repository (``repository.path``).
    """
    url = repository.get("url")
    return url.rstrip("/") if url else None


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


def paper_access(
    paper: str | None, paper_url: str | None, repository: dict[str, Any] | None = None
) -> tuple[dict[str, Any] | None, list[str]]:
    """The manifest's ``access`` for the paper (``--paper public|private``, ``--paper-url``), and notes.

    Public needs an https address of the PDF: ``--paper-url``, else the PDF in
    the repository at the pinned commit (``paper/paper.pdf`` under
    ``repository.path``). Private, the default, adds nothing: the manifest then
    carries no ``access`` and e2er.org shows readers a button to ask for the
    paper. The address goes into e2er.json only, never into the dossier, so
    stating it changes no fingerprint.
    """
    notes: list[str] = []
    paper = paper or "private"
    if paper not in ACCESS:
        raise ValueError(f"--paper must be public or private, not {paper!r}")
    if paper == "private":
        if paper_url:
            notes.append("--paper-url ignored: the paper is private, so no address is published")
        return None, notes
    url = (paper_url or "").strip()
    if not url and repository and repository.get("url") and repository.get("commit"):
        base = str(repository["url"]).rstrip("/").removesuffix(".git")
        sub = str(repository.get("path") or "").strip("/")
        url = f"{base}/raw/{repository['commit']}/{sub + '/' if sub else ''}paper/paper.pdf"
    if not url:
        raise ValueError(
            "--paper public needs the address of the PDF: --paper-url <https address>, "
            "or --repo with --commit (the PDF in the repository at that commit)"
        )
    if not url.startswith("https://") or any(c.isspace() for c in url):
        raise ValueError(f"--paper-url must be an https address, not {url!r}")
    return {"status": "public", "pdf": url}, notes


def reader_notes(
    availability: dict[str, dict[str, Any]] | None,
    paper: dict[str, Any] | None,
    restricted: list[str] | None = None,
) -> list[str]:
    """What readers on e2er.org see for what is not public, and the flag that publishes it; one sentence each.

    ``restricted`` names data sources whose terms do not allow passing the data
    on (the GMD): their data get no nudge, and readers are sent to the source.
    """
    out: list[str] = []
    if not paper:
        out.append(
            "The paper is not public: readers on e2er.org see a button to ask you for it, "
            "and --paper public --paper-url <address of the PDF> publishes it."
        )
    av = availability or {}
    if (av.get("data") or {}).get("access") != "public":
        if restricted:
            out.append(
                f"The data come from the {', '.join(restricted)}, whose terms do not allow passing them on "
                "outside the study's replication package, so readers on e2er.org see a link to the source "
                "instead of a request button."
            )
        else:
            out.append(
                "The data are private: readers on e2er.org see a button to ask you for them, "
                "and --data public (with --data-url or --zenodo) publishes them."
            )
    if (av.get("code") or {}).get("access") != "public":
        out.append(
            "The code is private: readers on e2er.org see a button to ask you for it, "
            "and --code public (with --repo and --commit, or --zenodo) publishes it."
        )
    return out
