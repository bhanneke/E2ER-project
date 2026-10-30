#!/usr/bin/env python3
"""The facts of a release, computed from the code: ``release-facts.json``.

    python scripts/release_facts.py --out release-facts.json            # counts the tests with pytest
    python scripts/release_facts.py --tests 4213 --out release-facts.json
    python scripts/release_facts.py zenodo-doi release-facts.json --wait 1800

release.yml writes the file at the tag and attaches it to the GitHub release; e2er.org reads it.
The format (docs/RELEASING.md) is fixed:

    {"version": "0.18.0", "date": "2026-10-23",
     "tag_url": "https://github.com/bhanneke/E2ER-project/releases/tag/v0.18.0",
     "concept_doi": "10.5281/zenodo.20187238",
     "doi": null,
     "counts": {"templates": 11, "specialists": 39, "skills": 90, "data_sources": 17, "tests": 4314}}

- ``version``: ``pyproject.toml``'s; ``date``: ``CITATION.cff``'s ``date-released`` (scripts/release.py sets both).
- ``templates``: the files ``pipelines/*.toml``.
- ``specialists``: every specialist of the registry (``src/core/specialists/registry.py``), as
  docs/SPECIALISTS.md counts them.
- ``skills``: the files ``skills/files/**/*.md``.
- ``data_sources``: the connectors a study can load from (``src/core/specialists/data_sources.py``).
- ``tests``: the tests the release workflow runs (``pytest tests/ -m "not e2e"``, collected).
- ``doi``: the Zenodo DOI of this version. Zenodo's GitHub integration mints it after the release
  is created; ``zenodo-doi`` asks Zenodo's public records API for the concept record's version named
  like the tag and fills it in. Until then, or when Zenodo made none, it is null and a reader uses
  ``concept_doi``.

No count is written by hand.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
REPO_URL = "https://github.com/bhanneke/E2ER-project"
CONCEPT_RECID = "20187238"
CONCEPT_DOI = f"10.5281/zenodo.{CONCEPT_RECID}"
ZENODO_API = "https://zenodo.org/api"

KEYS = ("version", "date", "tag_url", "concept_doi", "doi", "counts")
COUNT_KEYS = ("templates", "specialists", "skills", "data_sources", "tests")


# ── the counts ────────────────────────────────────────────────────────────────


def count_templates(root: Path) -> int:
    return sum(1 for _ in (root / "pipelines").glob("*.toml"))


def count_skills(root: Path) -> int:
    return sum(1 for p in (root / "skills" / "files").rglob("*.md") if p.is_file())


def _import_root(root: Path) -> None:
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


def count_specialists(root: Path) -> int:
    _import_root(root)
    from src.core.specialists.registry import SPECIALIST_ARTIFACTS, SPECIALIST_SKILLS

    return len(set(SPECIALIST_ARTIFACTS) | set(SPECIALIST_SKILLS))


def count_data_sources(root: Path) -> int:
    _import_root(root)
    from src.core.specialists.data_sources import _connectors

    return len(_connectors())


_COLLECTED = re.compile(r"^(?:(\d+)/)?(\d+) tests? collected(?: \((\d+) deselected\))?", re.M)


def parse_collected(output: str) -> int:
    """The number of tests pytest selected, from ``pytest --collect-only -q``'s last line.

    ``4213 tests collected in 9.1s`` -> 4213; ``4200/4213 tests collected (13 deselected) in 9.1s`` -> 4200.
    """
    lines = [ln for ln in output.splitlines() if "collected" in ln]
    for line in reversed(lines):
        m = _COLLECTED.match(line.strip())
        if m:
            return int(m.group(1) or m.group(2))
    if re.search(r"^no tests collected", output, re.M):
        return 0
    raise ValueError("pytest printed no 'N tests collected' line")


def count_tests(root: Path, python: str = sys.executable) -> int:
    proc = subprocess.run(
        [python, "-m", "pytest", "tests/", "--collect-only", "-q", "-m", "not e2e", "-p", "no:cacheprovider"],
        cwd=root,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode not in (0, 5):  # 5: no tests collected
        raise RuntimeError(
            f"pytest --collect-only failed ({proc.returncode}):\n{proc.stdout[-2000:]}{proc.stderr[-2000:]}"
        )
    return parse_collected(proc.stdout)


# ── the facts ─────────────────────────────────────────────────────────────────


def _version_and_date(root: Path) -> tuple[str, str]:
    import importlib.util

    spec = importlib.util.spec_from_file_location("e2er_release_script", Path(__file__).with_name("release.py"))
    assert spec is not None and spec.loader is not None
    release = sys.modules.get(spec.name) or importlib.util.module_from_spec(spec)
    if spec.name not in sys.modules:
        sys.modules[spec.name] = release
        spec.loader.exec_module(release)
    fields = release.read_fields(root)
    return fields[("pyproject.toml", "[project].version")], fields[("CITATION.cff", "date-released")]


def facts(root: Path, *, tests: int | None = None, doi: str | None = None) -> dict[str, Any]:
    version, date = _version_and_date(root)
    return {
        "version": version,
        "date": date,
        "tag_url": f"{REPO_URL}/releases/tag/v{version}",
        "concept_doi": CONCEPT_DOI,
        "doi": doi,
        "counts": {
            "templates": count_templates(root),
            "specialists": count_specialists(root),
            "skills": count_skills(root),
            "data_sources": count_data_sources(root),
            "tests": count_tests(root) if tests is None else tests,
        },
    }


def validate(doc: dict[str, Any]) -> list[str]:
    """Problems with a facts document against the fixed format (docs/RELEASING.md)."""
    problems: list[str] = []
    if tuple(doc) != KEYS:
        problems.append(f"keys are {list(doc)}, not {list(KEYS)}")
    if not re.fullmatch(r"\d+\.\d+\.\d+", str(doc.get("version"))):
        problems.append("version is not X.Y.Z")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(doc.get("date"))):
        problems.append("date is not YYYY-MM-DD")
    if doc.get("tag_url") != f"{REPO_URL}/releases/tag/v{doc.get('version')}":
        problems.append("tag_url is not the version's release")
    if doc.get("concept_doi") != CONCEPT_DOI:
        problems.append(f"concept_doi is not {CONCEPT_DOI}")
    d = doc.get("doi")
    if d is not None and not re.fullmatch(r"10\.\d{4,9}/\S+", str(d)):
        problems.append("doi is neither null nor a DOI")
    counts = doc.get("counts")
    if not isinstance(counts, dict) or tuple(counts) != COUNT_KEYS:
        problems.append(f"counts must have exactly {list(COUNT_KEYS)}")
    else:
        for k, v in counts.items():
            if not isinstance(v, int) or isinstance(v, bool) or v < 0:
                problems.append(f"counts.{k} is not a whole number")
    return problems


def write(doc: dict[str, Any], out: Path) -> None:
    problems = validate(doc)
    if problems:
        raise ValueError("release facts do not have the fixed format: " + "; ".join(problems))
    out.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


# ── the Zenodo version DOI ────────────────────────────────────────────────────

Fetch = Callable[[str], Any]


def _get_json(url: str) -> Any:
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "e2er-release-facts"})
    with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 - a fixed https address
        return json.loads(r.read().decode("utf-8"))


def _named(version: str, record: dict[str, Any]) -> bool:
    named = str((record.get("metadata") or {}).get("version") or "").strip()
    return named.removeprefix("v") == version


def find_version_doi(version: str, fetch: Fetch = _get_json) -> str | None:
    """The DOI Zenodo minted for ``version`` under the concept record, or None if there is none yet.

    Zenodo's GitHub integration names a version after the release's tag (``v0.17.3``). The latest
    version is asked first; the concept's newest versions after it (a later release may already be
    the latest). A record of the concept whose version is another is never taken.
    """
    candidates: list[dict[str, Any]] = []
    try:
        latest = fetch(f"{ZENODO_API}/records/{CONCEPT_RECID}/versions/latest")
        if isinstance(latest, dict):
            candidates.append(latest)
    except (urllib.error.URLError, OSError, ValueError):
        pass
    try:
        found = fetch(f"{ZENODO_API}/records?q=conceptrecid:{CONCEPT_RECID}&allversions=true&sort=newest&size=10")
        candidates += list(((found or {}).get("hits") or {}).get("hits") or [])
    except (urllib.error.URLError, OSError, ValueError):
        pass
    for rec in candidates:
        if not isinstance(rec, dict) or not _named(version, rec):
            continue
        if str(rec.get("conceptrecid") or CONCEPT_RECID) != CONCEPT_RECID:
            continue
        doi = rec.get("doi") or (rec.get("pids") or {}).get("doi", {}).get("identifier")
        if doi and doi != CONCEPT_DOI:
            return str(doi)
    return None


def wait_for_doi(
    version: str,
    *,
    wait: float,
    every: float = 30.0,
    fetch: Fetch = _get_json,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> str | None:
    """Ask Zenodo every ``every`` seconds for up to ``wait`` seconds."""
    deadline = clock() + wait
    while True:
        doi = find_version_doi(version, fetch)
        if doi or clock() + every > deadline:
            return doi
        sleep(every)


def fill_doi(path: Path, *, wait: float, every: float = 30.0, fetch: Fetch = _get_json, **kw: Any) -> str | None:
    doc = json.loads(path.read_text(encoding="utf-8"))
    if doc.get("doi"):
        return str(doc["doi"])
    doi = wait_for_doi(doc["version"], wait=wait, every=every, fetch=fetch, **kw)
    if doi:
        doc["doi"] = doi
        write(doc, path)
    return doi


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["zenodo-doi"]:
        ap = argparse.ArgumentParser(prog="release_facts.py zenodo-doi")
        ap.add_argument("file", help="the release-facts.json to fill in")
        ap.add_argument("--wait", type=float, default=1800, help="seconds to keep asking (default 1800)")
        ap.add_argument("--every", type=float, default=30, help="seconds between requests (default 30)")
        a = ap.parse_args(argv[1:])
        doi = fill_doi(Path(a.file), wait=a.wait, every=a.every)
        if doi:
            print(f"doi: {doi}")
        else:
            print(f"Zenodo has no version DOI yet after {a.wait:.0f}s; doi stays null (readers use {CONCEPT_DOI})")
        return 0
    ap = argparse.ArgumentParser(description="Write release-facts.json from the code.")
    ap.add_argument("--out", default="release-facts.json")
    ap.add_argument("--tests", type=int, default=None, help="the collected test count, if already known")
    ap.add_argument("--doi", default=None, help="the Zenodo version DOI, if already known")
    ap.add_argument("--root", default=str(REPO_ROOT), help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    doc = facts(Path(a.root), tests=a.tests, doi=a.doi)
    write(doc, Path(a.out))
    print(json.dumps(doc, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
