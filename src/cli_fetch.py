"""`e2er fetch <study or dossier address>`: download the study package e2er.org records, and check it.

e2er.org keeps no file: it records where the authors keep the study's ``.e2er`` file (a GitHub release, a
Zenodo deposit), its size and SHA-256 (src/core/study_package.py). ``e2er fetch`` reads that record with
GET, downloads the file from there, checks the size and the SHA-256 against the record, and prints the
commands that open, verify and rerun it. It runs nothing itself.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .core import study_package as sp


class FetchError(Exception):
    pass


def _get(base: str, path: str) -> tuple[int, Any]:
    from .core import platform_client as pc

    try:
        with pc.client_factory(base) as client:
            resp = client.get(path, headers={"accept": "application/json"})
    except Exception as e:  # noqa: BLE001 - network errors are the reader's to see
        raise FetchError(f"could not reach {base}: {e}") from e
    try:
        body = resp.json()
    except ValueError:
        body = None
    return resp.status_code, body


def resolve(address: str, version: int | None = None) -> tuple[Any, str, str]:
    """(the package record, what it belongs to, the address to verify against) for a study or dossier address."""
    u = urlparse(address.strip())
    if u.scheme not in ("https", "http") or not u.netloc:
        raise FetchError(f"give an e2er.org address (https://…), not {address!r}")
    base = f"{u.scheme}://{u.netloc}"
    parts = [p for p in u.path.split("/") if p]
    if parts[:2] == ["api", "v1"] and len(parts) >= 4 and parts[2] in ("studies", "dossiers"):
        parts = ["d", parts[3]] if parts[2] == "dossiers" else parts[3:5]
    if len(parts) >= 2 and parts[0] == "r":
        raise FetchError(
            "an anonymous version for double-blind review has no package on e2er.org: the journal has the file "
            "the authors made with `e2er pack --blind`"
        )
    if len(parts) >= 2 and parts[0] == "d":
        if version is not None:
            raise FetchError("--version goes with a study's address; a dossier belongs to one version")
        short = parts[1]
        code, body = _get(base, f"/api/v1/dossiers/{short}/package")
        if code == 404:
            raise FetchError(f"{base} records no study package for the dossier {short}")
        if code != 200 or not isinstance(body, dict):
            raise FetchError(f"{base} answered {code} for the dossier's package")
        what = f"the dossier {short}" + (
            f" ({body.get('study')}, version {body.get('version')})" if body.get("study") else ""
        )
        return body.get("package"), what, f"{base}/d/{short}"
    if len(parts) < 2:
        raise FetchError(f"{address} names neither a study (…/<owner>/<project>) nor a dossier (…/d/<id>)")
    owner, project = parts[0], parts[1]
    code, study = _get(base, f"/api/v1/studies/{owner}/{project}")
    if code == 404:
        raise FetchError(f"{base} has no study {owner}/{project}")
    if code != 200 or not isinstance(study, dict):
        raise FetchError(f"{base} answered {code} for the study {owner}/{project}")
    versions = [v for v in study.get("versions") or [] if isinstance(v, dict)]
    latest: dict[str, Any] = study["latest"] if isinstance(study.get("latest"), dict) else {}
    number = version if version is not None else latest.get("number")
    hit = next((v for v in versions if v.get("number") == number), None)
    if hit is None:
        shown = ", ".join(str(v.get("number")) for v in versions) or "none"
        raise FetchError(f"{owner}/{project} on {base} has no version {number} (versions: {shown})")
    if hit.get("package") is None:
        raise FetchError(
            f"{base} records no study package for version {number} of {owner}/{project}; ask the authors, or "
            "verify a copy of the files with `e2er verify <folder> --against` this address"
        )
    return hit["package"], f"{owner}/{project}, version {number}", f"{base}/{owner}/{project}"


def fetch(address: str, out: str | None = None, *, version: int | None = None) -> int:
    try:
        rec, what, against = resolve(address, version)
    except FetchError as e:
        print(f"error: {e}")
        return 1
    bad = sp.record_problems(rec)
    if bad:
        print(f"error: the package record e2er.org returned is malformed: {'; '.join(bad)}")
        return 1
    name = sp.file_name(rec)
    target = Path(out).expanduser() if out else Path.cwd() / name
    if target.is_dir():
        target = target / name
    from .core.export import package as pkg

    print(f"Downloading the study package of {what} ({pkg.human_size(rec['bytes'])}) from {rec['url']}", flush=True)
    try:
        path = sp.download(rec["url"], target, expect_bytes=rec["bytes"], expect_sha256=rec["sha256"])
    except sp.PackageHostError as e:
        print(f"error: {e}")
        return 1
    from .console import shell_arg

    shown = str(path) if out else path.name
    arg = shell_arg(shown)
    print(f"✓ {shown}: {rec['bytes']:,} bytes, SHA-256 {rec['sha256']}, as e2er.org records it")
    print(f"  kept by the authors on {'GitHub' if rec['host'] == 'github' else 'Zenodo'}; e2er.org keeps no copy")
    print("\nNothing was opened or run. Next:")
    print(f"  e2er inspect {arg}")
    print("      what the package holds (nothing is unpacked)")
    print(f"  e2er verify {arg} --against {shell_arg(against)}")
    print("      checks every file, and compares the package with the one e2er.org records")
    print(f"  e2er reproduce {arg}")
    print(
        "      runs the study's code again in a Docker container (no network, no folder of yours) and compares "
        "the results"
    )
    return 0
