#!/usr/bin/env python3
"""Make every version edit of a release in one command.

    python scripts/release.py 0.18.0                 # edit the files (refuses a dirty tree)
    python scripts/release.py 0.18.0 --commit        # ... and commit them as "Release 0.18.0"
    python scripts/release.py 0.18.0 --dry-run       # print what would change, write nothing
    python scripts/release.py --check                # every place names the same version
    python scripts/release.py --check --tag v0.18.0  # ... and it is the tag's (release.yml)

The places that name the current version (docs/RELEASING.md lists them):

- ``pyproject.toml``: ``[project].version``
- ``src/__init__.py``: ``__version__``
- ``CITATION.cff``: ``version``, ``date-released``, and ``preferred-citation``'s ``version`` and ``year``
- ``README.md``: the BibTeX entry's ``version`` and ``year``
- ``CHANGELOG.md``: ``## [Unreleased]`` becomes ``## [X.Y.Z] — YYYY-MM-DD`` under a new, empty
  ``## [Unreleased]``; the link references at the end follow (``[Unreleased]`` compares from the
  new tag, ``[X.Y.Z]`` points at its release)

Every other mention of a version in the repository is history ("up to 0.17.3", a study's recorded
``e2er_version``) and stays as it is. A mention of a version newer than the current one that is not
the version being released (a document that says a feature comes "in 0.17.4" when 0.18.0 is
released) is printed as a warning.

The script refuses a tree with uncommitted changes, a version that is not X.Y.Z, a version that is
not greater than the current one, an empty Unreleased section, and any place whose text is not
where it expects it; it then writes nothing. Standard library only: release.yml's version check
runs it before anything is installed.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REPO_URL = "https://github.com/bhanneke/E2ER-project"

_SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class ReleaseError(RuntimeError):
    """The release cannot be prepared; the message says why. Nothing was written."""


def parse_version(v: str) -> tuple[int, int, int]:
    m = _SEMVER.match(v.strip())
    if not m:
        raise ReleaseError(f"{v!r} is not a version of the form X.Y.Z")
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


# ── the places ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Field:
    """One versioned value in one file: a regex with a single group around the value."""

    file: str
    label: str
    pattern: re.Pattern[str]
    value: Callable[[str, str], str]  # (version, date) -> the new value
    reads_version: bool = True  # whether the value is the version (for --check)


def _year(_v: str, d: str) -> str:
    return d[:4]


FIELDS: tuple[Field, ...] = (
    Field(
        "pyproject.toml",
        "[project].version",
        re.compile(r'(?ms)\A.*?^\[project\]\n(?:(?!^\[).)*?^version\s*=\s*"([^"]*)"'),
        lambda v, d: v,
    ),
    Field("src/__init__.py", "__version__", re.compile(r'(?m)^__version__\s*=\s*"([^"]*)"'), lambda v, d: v),
    Field("CITATION.cff", "version", re.compile(r'(?m)^version:\s*"([^"]*)"'), lambda v, d: v),
    Field(
        "CITATION.cff",
        "date-released",
        re.compile(r'(?m)^date-released:\s*"([^"]*)"'),
        lambda v, d: d,
        reads_version=False,
    ),
    Field(
        "CITATION.cff",
        "preferred-citation.version",
        re.compile(r'(?ms)^preferred-citation:\n(?:(?!^\S).)*?^\s+version:\s*"([^"]*)"'),
        lambda v, d: v,
    ),
    Field(
        "CITATION.cff",
        "preferred-citation.year",
        re.compile(r"(?ms)^preferred-citation:\n(?:(?!^\S).)*?^\s+year:\s*(\d{4})"),
        _year,
        reads_version=False,
    ),
    Field(
        "README.md",
        "BibTeX version",
        re.compile(r"(?ms)@software\{hanneke2026e2er,.*?^\s*version\s*=\s*\{([^}]*)\}"),
        lambda v, d: v,
    ),
    Field(
        "README.md",
        "BibTeX year",
        re.compile(r"(?ms)@software\{hanneke2026e2er,.*?^\s*year\s*=\s*\{(\d{4})\}"),
        _year,
        reads_version=False,
    ),
)


def _sub(text: str, f: Field, new: str) -> str:
    m = f.pattern.search(text)
    if not m:
        raise ReleaseError(f"{f.file}: {f.label} not found where release.py expects it")
    return text[: m.start(1)] + new + text[m.end(1) :]


def read_fields(root: Path, texts: dict[str, str] | None = None) -> dict[tuple[str, str], str]:
    """Every versioned value as the files hold it now: (file, label) -> value.

    With ``texts`` (file -> content), a file named there is read from it instead of the disk: the
    release checks its new content this way before it writes anything.
    """
    out: dict[tuple[str, str], str] = {}
    for f in FIELDS:
        if texts is not None and f.file in texts:
            text = texts[f.file]
        else:
            p = root / f.file
            if not p.is_file():
                raise ReleaseError(f"{f.file} is missing")
            text = p.read_text(encoding="utf-8")
        m = f.pattern.search(text)
        if not m:
            raise ReleaseError(f"{f.file}: {f.label} not found where release.py expects it")
        out[(f.file, f.label)] = m.group(1)
    return out


def current_version(root: Path) -> str:
    return read_fields(root)[("pyproject.toml", "[project].version")]


# ── the CHANGELOG ─────────────────────────────────────────────────────────────

_UNRELEASED = re.compile(r"(?m)^## \[Unreleased\][ \t]*\n")
_NEXT_HEADING = re.compile(r"(?m)^## ")
_LINK_UNRELEASED = re.compile(r"(?m)^\[Unreleased\]:[^\n]*$")


def unreleased_body(changelog: str) -> str:
    m = _UNRELEASED.search(changelog)
    if not m:
        raise ReleaseError("CHANGELOG.md has no '## [Unreleased]' heading")
    nxt = _NEXT_HEADING.search(changelog, m.end())
    return changelog[m.end() : nxt.start() if nxt else len(changelog)]


def release_changelog(changelog: str, version: str, date: str) -> str:
    """Unreleased -> ``## [version] — date`` under a new empty Unreleased; the link references follow."""
    if f"## [{version}]" in changelog:
        raise ReleaseError(f"CHANGELOG.md already has a section for {version}")
    if not unreleased_body(changelog).strip():
        raise ReleaseError("CHANGELOG.md's Unreleased section is empty: there is nothing to release")
    m = _UNRELEASED.search(changelog)
    assert m is not None  # unreleased_body found it
    out = changelog[: m.start()] + f"## [Unreleased]\n\n## [{version}] — {date}\n" + changelog[m.end() :]
    link = _LINK_UNRELEASED.search(out)
    if link:
        refs = f"[Unreleased]: {REPO_URL}/compare/v{version}...HEAD\n[{version}]: {REPO_URL}/releases/tag/v{version}"
        out = out[: link.start()] + refs + out[link.end() :]
    return out


# ── mentions of versions that are neither history nor this release ──────────

_ANY_VERSION = re.compile(r"(?<![\w.])v?(\d+\.\d+\.\d+)(?![\w.]*\d)")
_SCANNED = ("README.md", "docs", "src", "skills", "pipelines", "AGENTS.md", "CONTRIBUTING.md", "SECURITY.md")
_SCANNED_SUFFIXES = {".md", ".py", ".html", ".toml", ".txt", ".cff"}


def future_mentions(root: Path, current: str, target: str) -> list[str]:
    """Mentions of a 0.x version newer than ``current`` that is not ``target``, as ``path:line: text``.

    Only versions with the current major part count (an R package at 2.5.1 in a skill is no e2er version).
    """
    cur, tgt = parse_version(current), parse_version(target)
    out: list[str] = []
    paths: list[Path] = []
    for name in _SCANNED:
        p = root / name
        if p.is_file():
            paths.append(p)
        elif p.is_dir():
            paths += sorted(q for q in p.rglob("*") if q.is_file() and q.suffix in _SCANNED_SUFFIXES)
    for p in paths:
        try:
            lines = p.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for n, line in enumerate(lines, 1):
            for m in _ANY_VERSION.finditer(line):
                v = parse_version(m.group(1))
                if v[0] == cur[0] and v[1] <= cur[1] + 1 and cur < v != tgt:
                    out.append(f"{p.relative_to(root).as_posix()}:{n}: {line.strip()[:160]}")
    return out


# ── the release ───────────────────────────────────────────────────────────────


def _git(root: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
    if proc.returncode != 0:
        raise ReleaseError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


def dirty(root: Path) -> list[str]:
    return [line[3:] for line in _git(root, "status", "--porcelain").splitlines() if line.strip()]


def plan(root: Path, version: str, date: str) -> dict[str, str]:
    """The new content of every file the release changes (nothing is written)."""
    if not _DATE.match(date):
        raise ReleaseError(f"{date!r} is not a date of the form YYYY-MM-DD")
    current = current_version(root)
    if parse_version(version) <= parse_version(current):
        raise ReleaseError(f"{version} is not greater than the current version {current}")
    texts: dict[str, str] = {}
    for f in FIELDS:
        text = texts.get(f.file)
        if text is None:
            text = (root / f.file).read_text(encoding="utf-8")
        texts[f.file] = _sub(text, f, f.value(version, date))
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    texts["CHANGELOG.md"] = release_changelog(changelog, version, date)
    return texts


def release(
    root: Path, version: str, date: str, *, dry_run: bool = False, commit: bool = False, allow_dirty: bool = False
) -> list[str]:
    """Edit every place for ``version``; returns the changed files. ``allow_dirty`` is for tests only."""
    if not allow_dirty and not dry_run:
        changed = dirty(root)
        if changed:
            raise ReleaseError(f"the tree has uncommitted changes ({', '.join(changed[:5])}); commit or stash them")
    current = current_version(root)
    texts = plan(root, version, date)
    files = [name for name, text in texts.items() if (root / name).read_text(encoding="utf-8") != text]
    # Checked on the new content before anything is written: a wrong pattern leaves no half release.
    after = read_fields(root, texts)
    wrong = [f"{file} {label}" for (file, label), v in after.items() if _expected(file, label, version, date) != v]
    if wrong:  # cannot happen unless a pattern is wrong; say so rather than leave a half release
        raise ReleaseError(f"after the edit these places would not name {version}: {', '.join(wrong)}")
    if dry_run:
        return files
    _write_all(root, {name: texts[name] for name in files})
    if commit:
        _git(root, "add", "--", *files)
        _git(
            root,
            "commit",
            "-m",
            f"Release {version}",
            "-m",
            f"Version edits by scripts/release.py ({current} -> {version}).",
        )
    return files


def _write_all(root: Path, texts: dict[str, str]) -> None:
    """Write every file or none: each goes to a temporary file beside it first, then all are renamed.

    A failure while writing the temporary files leaves every file as it was; a failure during the
    renames puts the files already renamed back to their earlier content.
    """
    temps: dict[str, Path] = {}
    originals = {name: (root / name).read_bytes() for name in texts}
    try:
        for name, text in texts.items():
            tmp = (root / name).with_name(f".{(root / name).name}.release-tmp")
            temps[name] = tmp
            tmp.write_text(text, encoding="utf-8")
            shutil.copymode(root / name, tmp)
        done: list[str] = []
        try:
            for name, tmp in temps.items():
                os.replace(tmp, root / name)
                done.append(name)
        except BaseException:
            for name in done:
                (root / name).write_bytes(originals[name])
            raise
    except OSError as e:
        raise ReleaseError(f"could not write the release ({e}); every file is as it was") from e
    finally:
        for tmp in temps.values():
            tmp.unlink(missing_ok=True)


def _expected(file: str, label: str, version: str, date: str) -> str:
    for f in FIELDS:
        if (f.file, f.label) == (file, label):
            return f.value(version, date)
    raise KeyError((file, label))


def check(root: Path, tag: str | None = None) -> list[str]:
    """Problems with the version places: they disagree, or they are not the tag's version."""
    fields = read_fields(root)
    version = fields[("pyproject.toml", "[project].version")]
    date = fields[("CITATION.cff", "date-released")]
    problems: list[str] = []
    for f in FIELDS:
        value = fields[(f.file, f.label)]
        if f.reads_version and value != version:
            problems.append(f"{f.file} {f.label} is {value!r}, pyproject.toml says {version!r}")
        elif f.label.endswith("year") and value != date[:4]:
            problems.append(f"{f.file} {f.label} is {value}, CITATION.cff's date-released is {date}")
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    if not re.search(rf"(?m)^## \[{re.escape(version)}\] — {re.escape(date)}\b", changelog):
        problems.append(f"CHANGELOG.md has no heading '## [{version}] — {date}'")
    if tag is not None and tag.removeprefix("v") != version:
        problems.append(f"the tag {tag} is not the version {version} (run scripts/release.py {tag.removeprefix('v')})")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("version", nargs="?", help="the new version, X.Y.Z")
    ap.add_argument("--date", default=None, help="release date, YYYY-MM-DD (default: today)")
    ap.add_argument("--dry-run", action="store_true", help="print what would change; write nothing")
    ap.add_argument("--commit", action="store_true", help='commit the edits as "Release X.Y.Z"')
    ap.add_argument("--check", action="store_true", help="only check that every place names the same version")
    ap.add_argument("--tag", default=None, help="with --check: the tag (vX.Y.Z) the version must match")
    ap.add_argument("--root", default=str(REPO_ROOT), help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    root = Path(args.root)
    try:
        if args.check:
            problems = check(root, args.tag)
            for p in problems:
                print(f"error: {p}")
            if not problems:
                print(
                    f"Version {current_version(root)}: every place agrees"
                    + (f" with the tag {args.tag}" if args.tag else "")
                )
            return 1 if problems else 0
        if not args.version:
            ap.error("give the new version (X.Y.Z), or --check")
        date = args.date or dt.date.today().isoformat()
        current = current_version(root)
        files = release(root, args.version, date, dry_run=args.dry_run, commit=args.commit)
        verb = "would change" if args.dry_run else "changed"
        print(f"{current} -> {args.version} ({date}); {verb}: {', '.join(files)}")
        if args.dry_run and dirty(root):
            print("note: the tree has uncommitted changes; the release itself refuses them")
        for w in future_mentions(root, current, args.version):
            print(f"warning: names a version that is neither history nor {args.version}: {w}")
        if not args.dry_run and not args.commit:
            print(f'next: review the diff, then git commit -am "Release {args.version}" (docs/RELEASING.md)')
        return 0
    except ReleaseError as e:
        print(f"error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
