#!/usr/bin/env python3
"""Check that PyPI holds exactly the files of this release run's dist/, byte for byte.

The release workflow uploads dist/ to the GitHub release with ``--clobber`` and to PyPI with
``skip-existing``. When a re-run builds the files again (a wheel's bytes can differ between two
builds), the GitHub release gets the new files while PyPI keeps the old ones, and the two no longer
match. This check runs after the publish job and fails when PyPI's SHA-256 of a file differs from
dist/, or when a file is on one side only:

    python3 scripts/release_pypi_check.py dist/ --version 0.21.0 --wait 300

PyPI's JSON API can lag a few seconds behind an upload, so a file missing on PyPI is asked again
every ``--every`` seconds for up to ``--wait`` seconds; a differing SHA-256 fails at once (PyPI
never replaces a file). docs/RELEASING.md says what to do when it fails.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

PROJECT = "e2er"
URL = "https://pypi.org/pypi/{project}/{version}/json"


def _fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"accept": "application/json", "user-agent": "e2er-release-check"})
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - fixed https URL
        return bytes(resp.read())


def local_digests(dist: Path) -> dict[str, str]:
    """{file name: SHA-256} of the wheels and sdists in ``dist``."""
    out: dict[str, str] = {}
    for p in sorted(dist.iterdir()):
        if p.is_file() and (p.name.endswith(".whl") or p.name.endswith(".tar.gz")):
            out[p.name] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def pypi_digests(version: str, fetch: Callable[[str], bytes] | None = None, project: str = PROJECT) -> dict[str, str]:
    """{file name: SHA-256} of the files PyPI lists for ``version``; {} when PyPI has no such version yet."""
    try:
        data = json.loads((fetch or _fetch)(URL.format(project=project, version=version)))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {}
        raise
    return {f["filename"]: f["digests"]["sha256"] for f in data.get("urls") or []}


def compare(local: dict[str, str], remote: dict[str, str]) -> tuple[list[str], list[str]]:
    """(mismatches, missing): files whose SHA-256 differ or that only one side has.

    ``missing`` (in dist/, not yet on PyPI) may still appear; everything in ``mismatches`` is final."""
    mismatches = [
        f"{name}: dist/ {local[name]} but PyPI {remote[name]}"
        for name in sorted(local.keys() & remote.keys())
        if local[name] != remote[name]
    ]
    mismatches += [f"{name}: on PyPI but not in this run's dist/" for name in sorted(remote.keys() - local.keys())]
    missing = [f"{name}: in dist/ but not on PyPI" for name in sorted(local.keys() - remote.keys())]
    return mismatches, missing


def check(
    dist: Path,
    version: str,
    *,
    wait: float = 0,
    every: float = 15,
    fetch: Callable[[str], bytes] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> list[str]:
    """The problems; [] when PyPI holds exactly dist/'s files."""
    local = local_digests(dist)
    if not local:
        return [f"no .whl or .tar.gz in {dist}"]
    deadline = clock() + wait
    while True:
        mismatches, missing = compare(local, pypi_digests(version, fetch))
        if mismatches or not missing or clock() + every > deadline:
            return mismatches + missing
        sleep(every)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("dist", type=Path)
    ap.add_argument("--version", required=True, help="X.Y.Z (a leading v is dropped)")
    ap.add_argument("--wait", type=float, default=300, help="seconds to wait for files PyPI does not list yet")
    ap.add_argument("--every", type=float, default=15)
    args = ap.parse_args(argv)
    version = args.version.removeprefix("v")
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        print(f"not a version: {args.version!r}", file=sys.stderr)
        return 2
    problems = check(args.dist, version, wait=args.wait, every=args.every)
    if problems:
        print(f"PyPI's files of e2er {version} differ from this run's dist/:", file=sys.stderr)
        for p in problems:
            print(f"  {p}", file=sys.stderr)
        return 1
    for name, digest in local_digests(args.dist).items():
        print(f"ok  {name} {digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
