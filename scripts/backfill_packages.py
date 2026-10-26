#!/usr/bin/env python3
"""Give the studies published before the study package (0.20) their package: pack, host, record.

For the latest published version of each study below, this script

1. reads the version from e2er.org (GET; the version must have no package yet),
2. takes the study's folder from its repository at the version's pinned commit (``git archive``; a local
   clone with ``--clone OWNER/REPO=PATH``, else a fresh clone in the work folder) and checks that its
   provenance.json hashes to the version's content id,
3. packs it: a folder ``e2er publish --github`` pushed is the package, opened, so it is written into its
   ``.e2er`` file again from its own e2er-package.json (package.repack: the same list, the same
   fingerprint); any other folder is packed with ``e2er pack``'s logic (package.build, GitHub's size rule),
4. checks the file: unpacked against its list, then ``e2er verify <file> --against`` the study on e2er.org,
5. with ``--run`` only: uploads it as the file of the release ``<project>-v<N>`` (study_package.host_release:
   never forced, never overwritten, never "latest") and records it on the existing version with
   ``POST /api/v1/studies/<owner>/<project>/versions/<N>/package`` (e2er.org downloads it, checks its size,
   SHA-256 and that its list names this version's content id, and only then records it; the version's
   content and dossier stay as they are).

Without ``--run`` nothing is uploaded or recorded: the script prints what it would do and writes a report.
The Bitcoin showcase lives in bhanneke/E2ER-project, whose releases Zenodo archives as versions of e2er
itself, so its package is the file of a release of bhanneke/e2er-demos instead.

    python scripts/backfill_packages.py --work /tmp/e2er-backfill                      # dry run
    python scripts/backfill_packages.py --work /tmp/e2er-backfill --run                # after `e2er login`

No LLM call, no token printed; GitHub is used with your own gh login.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.core import github_files as gf  # noqa: E402
from src.core import platform_client as pc  # noqa: E402
from src.core import study_package as sp  # noqa: E402
from src.core.export import package as pkg  # noqa: E402

PLATFORM = "https://e2er.org"
OWNER = "bhanneke"
DEMOS = "bhanneke/e2er-demos"


@dataclass(frozen=True)
class Study:
    project: str
    repo: str  # where the study's files are
    path: str  # the study's folder in it
    commit: str  # the latest version's pinned commit (checked against e2er.org's own check)
    host: str = DEMOS  # the repository whose release carries the package


STUDIES = [
    Study(
        "exoplanet-radius-period-provenance",
        DEMOS,
        "exoplanet-radius-period-provenance",
        "da15c2dd213fd05ca6585804e9f47fac563ba8a8",
    ),
    Study("pleiades-gaia-dr3-members", DEMOS, "pleiades-gaia-dr3-members", "3c1dec90a8d53a76b19ff5ea699d8b691ce7693d"),
    Study(
        "earthquake-counts-b-value-by-decade",
        DEMOS,
        "earthquake-counts-b-value-by-decade",
        "f2e4bbf7ee50089cc754033f6348145202c288e7",
    ),
    Study(
        "frankfurt-temperature-trend-forecasts",
        DEMOS,
        "frankfurt-temperature-trend-forecasts",
        "45869a9f2aac977fa869f8379601b645fc7b6905",
    ),
    Study(
        "school-fee-abolition-enrolment-africa",
        DEMOS,
        "school-fee-abolition-enrolment-africa",
        "33e784b03e4105860352862b0a35d6e47d313a88",
    ),
    Study(
        "eu-regional-gdp-spatial-clustering",
        DEMOS,
        "eu-regional-gdp-spatial-clustering",
        "96d04afc49ab90c7d8ba8615e57fe8f5bd13e14c",
    ),
    Study(
        "road-traffic-death-rates-2021",
        DEMOS,
        "road-traffic-death-rates-2021",
        "f573917d0d2f12d257a0066f986497258a35f9a6",
    ),
    Study(
        "weather-words-english-novels",
        DEMOS,
        "weather-words-english-novels",
        "6b1d83cc358c9754b5f9c41721f5c508e3732ce3",
    ),
    Study(
        "spot-bitcoin-etf-comovement",
        "bhanneke/E2ER-project",
        "examples/showcase",
        "25a30912064ce70bb86f6810ff166c60485fa1f7",
    ),
]


class StopError(Exception):
    """This study cannot be backfilled now; the message says why."""


def _git(args: list[str], cwd: Path | None = None) -> str:
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=900)
    if proc.returncode != 0:
        raise StopError(f"git {args[0]} failed: {(proc.stderr or proc.stdout).strip().splitlines()[-1:]}")
    return proc.stdout


def _clone(repo: str, work: Path, given: dict[str, Path]) -> Path:
    if repo in given:
        return given[repo]
    dest = work / "clones" / repo.replace("/", "__")
    if not dest.is_dir():
        dest.parent.mkdir(parents=True, exist_ok=True)
        _git(["clone", "--quiet", "--filter=blob:none", "--no-checkout", f"https://github.com/{repo}.git", str(dest)])
    return dest


def _folder_at(clone: Path, commit: str, path: str, dest: Path) -> Path:
    """The study's folder at ``commit`` (git archive), extracted into ``dest``; nothing outside it is written."""
    have = subprocess.run(["git", "cat-file", "-e", f"{commit}^{{commit}}"], cwd=clone, capture_output=True)
    if have.returncode != 0:
        _git(["fetch", "--quiet", "origin", commit], cwd=clone)
    proc = subprocess.run(
        ["git", "archive", "--format=tar", commit, "--", path], cwd=clone, capture_output=True, timeout=900
    )
    if proc.returncode != 0:
        raise StopError(
            f"git archive {commit[:7]} {path} failed: {proc.stderr.decode(errors='replace').strip()[-200:]}"
        )
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(proc.stdout)) as tar:
        tar.extractall(dest, filter="data")
    folder = dest / path
    if not folder.is_dir():
        raise StopError(f"{path} is not a folder at {commit[:7]}")
    return folder


def _verify(file: Path, against: str) -> dict[str, Any]:
    """`e2er verify <file> --against <study>` in a process of its own (its JSON report, and its exit code)."""
    proc = subprocess.run(
        [sys.executable, "-m", "src", "verify", str(file), "--json", "--against", against],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=1800,
    )
    text = proc.stdout
    try:
        report = json.JSONDecoder().raw_decode(text[text.index("{\n") :])[0] if "{\n" in text else {}
    except ValueError:
        report = {}
    if not isinstance(report, dict) or "checks" not in report:
        report = {"checks": [], "verdict": (text or proc.stderr)[-300:]}
    report["exit"] = proc.returncode
    return report


def _release_state(host: str, tag: str, name: str) -> str:
    """What the release looks like now (read only)."""
    try:
        rel = sp._release(host, tag)
        at = sp._tag_commit(host, tag)
    except (sp.PackageHostError, gf.GitHubError) as e:
        return f"could not be read ({e})"
    if rel is None and at is None:
        return "does not exist yet"
    if rel is None:
        return f"no release, but the tag exists at {at[:7] if at else '?'}"
    names = [a.get("name") for a in rel.get("assets") or [] if isinstance(a, dict)]
    return f"exists at {at[:7] if at else '?'} with files {names}"


def backfill(s: Study, *, work: Path, clones: dict[str, Path], platform: str, run: bool) -> dict[str, Any]:
    out: dict[str, Any] = {"study": f"{OWNER}/{s.project}", "repository": s.repo, "path": s.path, "commit": s.commit}
    code, study = pc.request(platform, "GET", f"/api/v1/studies/{OWNER}/{s.project}")
    if code != 200 or not isinstance(study, dict):
        raise StopError(f"{platform} answered {code} for {OWNER}/{s.project}")
    latest = study.get("latest") or {}
    n = latest.get("number")
    version = next((v for v in study.get("versions") or [] if v.get("number") == n), None) or {}
    out["version"] = n
    if version.get("package") or latest.get("package"):
        out["action"] = "skip: the latest version has a package already"
        return out
    checked = (study.get("platform_check") or {}).get("commit_sha")
    if checked and checked != s.commit:
        raise StopError(
            f"e2er.org checked version {n} at {checked[:7]}, not the pinned {s.commit[:7]}; update the table"
        )
    folder = _folder_at(_clone(s.repo, work, clones), s.commit, s.path, work / "folders" / s.project)
    got = "sha256:" + hashlib.sha256((folder / "provenance.json").read_bytes()).hexdigest()
    if got != latest.get("content_id"):
        raise StopError(f"provenance.json at {s.commit[:7]} is {got[:19]}…, version {n} is {latest.get('content_id')}")
    name, tag = sp.asset_name(s.project, int(n)), sp.tag_for(s.project, int(n))
    file = work / "packages" / name
    file.parent.mkdir(parents=True, exist_ok=True)
    file.unlink(missing_ok=True)
    if (folder / pkg.MANIFEST).is_file():
        packed = pkg.repack(folder, file)
        out["packed"] = "repacked from the folder's own e2er-package.json (the package it was opened from)"
    else:
        packed = pkg.build(folder, file, host=gf.HOST, max_file_bytes=gf.GITHUB_FILE_LIMIT)
        out["packed"] = "packed with e2er pack's logic (the folder holds no package of its own)"
    out["notes"] = packed.notes
    with tempfile.TemporaryDirectory(prefix="e2er-backfill-open-") as td:
        pkg.open_package(file, Path(td) / "study")  # every file against its list
    report = _verify(file, f"{platform}/{OWNER}/{s.project}")
    checks = {c["name"]: c["status"] for c in report.get("checks") or []}
    out["verify"] = {"exit": report["exit"], "verdict": report.get("verdict"), "published": checks.get("published")}
    if checks.get("published") != "PASS":
        raise StopError(
            f"e2er verify --against does not find this package's content in version {n}: {report.get('verdict')}"
        )
    url = sp.release_url(s.host, tag, name)
    rec = sp.record(file, url, "github", packed.manifest["fingerprint"])
    out["package"] = rec
    # The release's commit: the version's own when the package's repository holds the study, else its head.
    target = (
        s.commit if s.host == s.repo else _git(["ls-remote", f"https://github.com/{s.host}.git", "HEAD"]).split()[0]
    )
    out["release"] = {
        "repository": s.host,
        "tag": tag,
        "file": name,
        "target": target,
        "now": _release_state(s.host, tag, name),
    }
    out["attach"] = {
        "POST": f"{platform}/api/v1/studies/{OWNER}/{s.project}/versions/{n}/package",
        "body": {"package": rec},
    }
    if not run:
        out["action"] = "dry run: nothing uploaded or recorded"
        return out
    files_at = f"https://github.com/{s.repo}/tree/{s.commit}/{s.path}"
    hosted = sp.host_release(
        s.host,
        tag=tag,
        commit=target,
        file=file,
        name=name,
        title=f"{OWNER}/{s.project} version {n}: the study package",
        notes=(
            f"The study package of {OWNER}/{s.project}, version {n}, on e2er.org: every file of the study as "
            f"published at {files_at}, in one .e2er file.\n\n"
            f"    e2er fetch {platform}/{OWNER}/{s.project}\n"
            f"    e2er verify {name} --against {platform}/{OWNER}/{s.project}\n"
            f"    e2er reproduce {name}\n"
        ),
    )
    token = pc.load_token(platform)
    if not token:
        raise StopError(f"uploaded {name}, but not signed in to {platform}: run `e2er login`, then this again")
    code, body = pc.request(
        platform,
        "POST",
        f"/api/v1/studies/{OWNER}/{s.project}/versions/{n}/package",
        token=token,
        body={"package": rec},
    )
    answer = pc.error_text(code, body) if code >= 300 else "recorded"
    out["action"] = f"release {'made' if hosted.created else 'reused'}; e2er.org answered {code}: {answer}"
    if code >= 300:
        raise StopError(out["action"])
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", action="store_true", help="Upload and record (default: a dry run).")
    ap.add_argument("--work", required=True, type=Path, help="A work folder (clones, folders, packages, report).")
    ap.add_argument("--platform", default=PLATFORM)
    ap.add_argument("--only", action="append", default=None, metavar="PROJECT")
    ap.add_argument(
        "--clone",
        action="append",
        default=[],
        metavar="OWNER/REPO=PATH",
        help="Use a local clone of that repository (read only) instead of cloning it.",
    )
    args = ap.parse_args()
    clones = {k: Path(v).expanduser().resolve() for k, _, v in (c.partition("=") for c in args.clone)}
    work = args.work.expanduser().resolve()
    work.mkdir(parents=True, exist_ok=True)
    chosen = [s for s in STUDIES if not args.only or s.project in args.only]
    results = []
    for s in chosen:
        print(f"── {OWNER}/{s.project}", flush=True)
        try:
            r = backfill(s, work=work, clones=clones, platform=args.platform.rstrip("/"), run=args.run)
        except (StopError, pkg.PackageError, sp.PackageHostError, gf.GitHubError) as e:
            r = {"study": f"{OWNER}/{s.project}", "error": str(e)}
        results.append(r)
        if "error" in r:
            print(f"   stopped: {r['error']}")
            continue
        if "package" not in r:
            print(f"   {r['action']}")
            continue
        p, rel = r["package"], r["release"]
        print(f"   version {r['version']} at {s.repo}@{s.commit[:7]}/{s.path}: {r['packed']}")
        print(
            f"   {rel['file']}: {pkg.human_size(p['bytes'])}, sha256 {p['sha256'][:16]}…, "
            f"fingerprint {p['fingerprint'][:23]}…"
        )
        print(f"   verify --against: {r['verify']['verdict']} (published: {r['verify']['published']})")
        print(f"   release {rel['tag']} of {rel['repository']} at {rel['target'][:7]} ({rel['now']})")
        print(f"   {r['action']}")
    (work / "backfill-report.json").write_text(json.dumps(results, indent=2) + "\n")
    print(f"\nreport: {work / 'backfill-report.json'}")
    return 1 if any("error" in r for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
