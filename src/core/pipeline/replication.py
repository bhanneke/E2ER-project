"""The `replication` template's package step and its plan contract.

A computational reproduction starts from a published replication package. This
module owns the two things about that package that must be facts rather than
model output:

  * **fetch** (`fetch_package`): the Zenodo record named in the study's
    question is downloaded, every file is verified against the checksum Zenodo
    publishes and hashed with SHA-256, archives are unpacked into ``package/``,
    every unpacked file is hashed too, and the whole tree is made read-only.
    The text of each PDF in the package is extracted, page by page, into
    ``package_text/`` so the planner can cite pages. Everything is recorded in
    ``package_manifest.json``. On resume the step re-hashes the package and
    fails if a single byte changed: the original package is never altered.

  * **the plan contract** (`validate_plan`): ``replication_plan.json``, which
    the replication planner writes, is what the sandbox executes. Its image,
    commands and paths are checked here, structurally and against the package,
    before anything runs — the plan is model output, and model output never
    reaches a shell unchecked.

Schemas: ``docs/schemas/replication_plan.schema.json`` and the skill
``skills/files/replication/replication-plan.md``.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import stat
import subprocess
import tarfile
import zipfile
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from ...logging_config import get_logger

logger = get_logger(__name__)

PACKAGE_DIR = "package"
ARCHIVE_DIR = "package_archive"
TEXT_DIR = "package_text"
MANIFEST_FILE = "package_manifest.json"
PLAN_FILE = "replication_plan.json"

DEFAULT_MAX_MB = 1000
#: Unpacked size limit, as a multiple of the download limit (zip bombs).
_UNPACK_FACTOR = 5
_MAX_MEMBERS = 50_000
_MAX_PDF_BYTES = 50_000_000

#: Pinned official images only: an R version from rocker, or a Python slim image.
IMAGE_PATTERN = re.compile(r"^(rocker/r-ver:\d+\.\d+\.\d+|python:\d+\.\d+(\.\d+)?-slim(-bookworm|-bullseye|-trixie)?)$")
INTERPRETERS: dict[str, frozenset[str]] = {
    "R": frozenset({"Rscript"}),
    "Python": frozenset({"python", "python3"}),
}
#: Interpreter flags a command may carry. Nothing that runs inline code (-e, -c, -m).
_SAFE_FLAGS = frozenset({"--vanilla", "--no-save", "--no-restore", "--no-environ", "-u"})
_SAFE_ARG = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.,=+@-]*(/[A-Za-z0-9_][A-Za-z0-9_.,=+@-]*)*$")
_SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_PKG_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{0,99}$")
_PKG_VERSION = re.compile(r"^[0-9][0-9A-Za-z.+_-]{0,39}$")
_SYS_PKG = re.compile(r"^[a-z0-9][a-z0-9+.-]{0,99}$")
LEVELS = ("reproduced", "reproduced_minor", "not_reproduced", "could_not_run")
#: What a target is compared against: 1 = a result file the package ships
#: (does the code rebuild its own results?), 2 = a number printed in the paper
#: (does the rerun reproduce what was published?).
TARGET_LEVELS = (1, 2)
PAPER_DIR = "paper"
PAPER_FILE = "paper/paper.pdf"
PAPER_TEXT_DIR = "paper_text"


@dataclass(frozen=True)
class CheckResult:
    """A deterministic step's verdict, in the shape the runner records for every check."""

    passed: bool
    reasons: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    stats: dict[str, Any] = field(default_factory=dict, hash=False)
    #: Researcher-supplied inputs this step recorded (logged for the dossier).
    inputs: tuple[dict[str, Any], ...] = ()

    def detail(self) -> str:
        if self.passed:
            head = "passed: " + ", ".join(f"{k}={v}" for k, v in self.stats.items())
            return "; ".join([head, *self.notes])
        return "; ".join([*self.reasons, *self.notes])


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _rel_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file() and not p.is_symlink())


def hash_tree(root: Path) -> dict[str, dict[str, Any]]:
    """relative posix path -> {size, sha256} for every regular file under ``root``."""
    return {
        p.relative_to(root).as_posix(): {"size": p.stat().st_size, "sha256": sha256_file(p)} for p in _rel_files(root)
    }


def _make_read_only(root: Path) -> None:
    for dirpath, dirnames, filenames in os.walk(root):
        for name in filenames:
            p = Path(dirpath) / name
            if not p.is_symlink():
                p.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
        Path(dirpath).chmod(stat.S_IRUSR | stat.S_IXUSR | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)


def make_writable(root: Path) -> None:
    """Undo `_make_read_only` (used on copies, and by tests that clean up)."""
    for dirpath, _dirnames, filenames in os.walk(root):
        Path(dirpath).chmod(0o755)
        for name in filenames:
            p = Path(dirpath) / name
            if not p.is_symlink():
                p.chmod(0o644)


def _safe_member(name: str) -> PurePosixPath | None:
    p = PurePosixPath(name.replace("\\", "/"))
    if p.is_absolute() or ".." in p.parts or not p.parts:
        return None
    if p.parts[0] == "__MACOSX" or p.name == ".DS_Store":
        return None
    return p


def _unpack_zip(archive: Path, dest: Path, budget: int) -> list[str]:
    notes: list[str] = []
    with zipfile.ZipFile(archive) as zf:
        members = zf.infolist()
        if len(members) > _MAX_MEMBERS:
            raise ValueError(f"{archive.name}: {len(members)} members, above {_MAX_MEMBERS}")
        total = sum(m.file_size for m in members)
        if total > budget:
            raise ValueError(f"{archive.name}: unpacks to {total:,} bytes, above {budget:,}")
        for m in members:
            rel = _safe_member(m.filename)
            if rel is None:
                notes.append(f"skipped archive member {m.filename!r}")
                continue
            mode = (m.external_attr >> 16) & 0o170000
            if mode == stat.S_IFLNK:
                notes.append(f"skipped symbolic link {m.filename!r}")
                continue
            target = dest / rel
            if m.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(m) as src, target.open("wb") as out:
                shutil.copyfileobj(src, out)
    return notes


def _unpack_tar(archive: Path, dest: Path, budget: int) -> list[str]:
    notes: list[str] = []
    with tarfile.open(archive) as tf:
        members = tf.getmembers()
        if len(members) > _MAX_MEMBERS:
            raise ValueError(f"{archive.name}: {len(members)} members, above {_MAX_MEMBERS}")
        if sum(m.size for m in members) > budget:
            raise ValueError(f"{archive.name}: unpacks above {budget:,} bytes")
        safe = []
        for m in members:
            if _safe_member(m.name) is None or not (m.isfile() or m.isdir()):
                notes.append(f"skipped archive member {m.name!r}")
                continue
            safe.append(m)
        tf.extractall(dest, members=safe, filter="data")
    return notes


def _extract_pdf_text(package: Path, out_root: Path) -> list[str]:
    """Page-marked text of every PDF in the package, for the planner to read and cite."""
    written: list[str] = []
    try:
        from pypdf import PdfReader
    except ImportError:  # pragma: no cover — pypdf is a dependency
        return written
    for pdf in _rel_files(package):
        if pdf.suffix.lower() != ".pdf" or pdf.stat().st_size > _MAX_PDF_BYTES:
            continue
        rel = pdf.relative_to(package).as_posix()
        target = out_root / f"{rel}.txt"
        try:
            reader = PdfReader(str(pdf))
            pages = [
                f"=== page {i} ===\n{(page.extract_text() or '').strip()}\n" for i, page in enumerate(reader.pages, 1)
            ]
        except Exception as e:  # noqa: BLE001 — a PDF that will not parse is noted, not fatal
            logger.warning("package text: %s could not be read: %s", rel, e)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"# Text of {rel} ({len(pages)} pages), extracted with pypdf\n\n" + "\n".join(pages))
        written.append(target.relative_to(out_root.parent).as_posix())
    return written


def _research_question(workspace: Path) -> str:
    try:
        return str(json.loads((workspace / "manifest.json").read_text(encoding="utf-8")).get("research_question") or "")
    except (OSError, ValueError):
        return ""


def _verify_existing(workspace: Path, manifest: dict[str, Any]) -> CheckResult:
    """On resume: the package on disk must still be byte-identical to what was fetched."""
    reasons: list[str] = []
    for f in manifest.get("files") or []:
        p = workspace / ARCHIVE_DIR / f["path"]
        if not p.is_file():
            reasons.append(f"{ARCHIVE_DIR}/{f['path']} is missing")
        elif sha256_file(p) != f["sha256"]:
            reasons.append(f"{ARCHIVE_DIR}/{f['path']} changed after it was fetched")
    recorded = {f["path"]: f["sha256"] for f in manifest.get("package_files") or []}
    current = hash_tree(workspace / PACKAGE_DIR) if (workspace / PACKAGE_DIR).is_dir() else {}
    for path, digest in recorded.items():
        if path not in current:
            reasons.append(f"{PACKAGE_DIR}/{path} is missing")
        elif current[path]["sha256"] != digest:
            reasons.append(f"{PACKAGE_DIR}/{path} changed after it was fetched")
    for path in sorted(set(current) - set(recorded))[:10]:
        reasons.append(f"{PACKAGE_DIR}/{path} was added after the package was fetched")
    if reasons:
        return CheckResult(False, tuple(reasons[:20]))
    return CheckResult(
        True,
        notes=("package already fetched; every file re-hashed and unchanged",),
        stats={"record": manifest.get("record_id"), "files": len(recorded)},
    )


def fetch_package(
    workspace: Path, *, max_mb: int = DEFAULT_MAX_MB, client: Any = None, paper_pdf: str | Path | None = None
) -> CheckResult:
    """The `fetch` step: the package (downloaded once, re-verified on every start) and the researcher's paper.

    The step runs at every start of the run (``resumable = false`` in the
    template), so a paper the researcher supplies after the plan review is
    picked up the next time the run resumes.
    """
    workspace = Path(workspace)
    result = _fetch(workspace, max_mb=max_mb, client=client)
    if not result.passed:
        return result
    try:
        paper = stage_paper(workspace, paper_pdf)
    except (OSError, ValueError) as e:
        return CheckResult(False, (f"the researcher-supplied paper cannot be used: {e}",))
    if paper is None:
        return replace(result, notes=(*result.notes, f"no paper supplied ({PAPER_FILE}): level-2 targets unavailable"))
    stats = {**result.stats, "paper_sha256": paper["sha256"][:12], "paper_pages": paper["pages"]}
    inputs = (paper,) if paper.pop("new", False) else ()
    return replace(result, stats=stats, inputs=inputs)


def paper_candidates(workspace: Path, explicit: str | Path | None = None) -> list[Path]:
    """Where a researcher-supplied paper is looked for, in order.

    ``explicit`` (a caller's path), then the ``PAPER_PDF`` setting, then
    ``paper.pdf`` in each ``LOCAL_DATA_DIR`` folder, then ``data/paper.pdf`` in
    the paper's workspace.
    """
    found: list[Path] = []
    if explicit:
        found.append(Path(explicit).expanduser())
    try:
        from ...config import get_settings

        settings = get_settings()
        if getattr(settings, "paper_pdf", ""):
            found.append(Path(settings.paper_pdf).expanduser())
        for d in (settings.local_data_dir or "").split(","):
            if d.strip():
                found.append(Path(d.strip()).expanduser() / "paper.pdf")
    except Exception:  # noqa: BLE001 — settings are optional here (tests, scripts)
        pass
    found.append(Path(workspace) / "data" / "paper.pdf")
    return found


def _pdf_pages(pdf: Path) -> tuple[list[str], str]:
    """Per-page text: pdftotext -layout when installed (keeps table columns), else pypdf."""
    known = ("/opt/homebrew/bin/pdftotext", "/usr/local/bin/pdftotext", "/usr/bin/pdftotext")
    exe = shutil.which("pdftotext") or next((c for c in known if Path(c).is_file()), None)
    if exe:
        cp = subprocess.run([exe, "-layout", "-enc", "UTF-8", str(pdf), "-"], capture_output=True, timeout=300)
        if cp.returncode == 0:
            pages = cp.stdout.decode("utf-8", "replace").split("\f")
            if pages and not pages[-1].strip():
                pages = pages[:-1]
            return pages, "pdftotext -layout"
    from pypdf import PdfReader

    return [(p.extract_text() or "") for p in PdfReader(str(pdf)).pages], "pypdf"


def stage_paper(workspace: Path, explicit: str | Path | None = None) -> dict[str, Any] | None:
    """Copy the researcher's paper into the workspace, fingerprint it, and extract its text.

    Returns the record written to ``package_manifest.json`` under ``paper``
    (with ``new: True`` when this call staged it or it changed), or None when no
    paper was supplied. The paper is researcher input, not part of the package:
    it is recorded as such and never mixed into ``package/``.
    """
    workspace = Path(workspace)
    source = next((p for p in paper_candidates(workspace, explicit) if p.is_file()), None)
    manifest_path = workspace / MANIFEST_FILE
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
    staged = workspace / PAPER_FILE
    if source is None:
        if staged.is_file() and manifest.get("paper"):
            if sha256_file(staged) != manifest["paper"]["sha256"]:
                raise ValueError(f"{PAPER_FILE} changed after it was recorded")
            return dict(manifest["paper"])
        return None
    with source.open("rb") as fh:
        if fh.read(5) != b"%PDF-":
            raise ValueError(f"{source} is not a PDF")
    digest = sha256_file(source)
    previous = manifest.get("paper") or {}
    if previous.get("sha256") == digest and staged.is_file() and sha256_file(staged) == digest:
        return dict(previous)
    if staged.exists():
        staged.chmod(0o644)
    staged.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, staged)
    staged.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    pages, extractor = _pdf_pages(staged)
    text_path = workspace / PAPER_TEXT_DIR / f"{staged.name}.txt"
    text_path.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(f"=== page {i} ===\n{p.rstrip()}\n" for i, p in enumerate(pages, 1))
    text_path.write_text(
        f"# Text of {PAPER_FILE} ({len(pages)} pages, researcher-supplied), extracted with {extractor}\n\n{body}",
        encoding="utf-8",
    )
    record = {
        "supplied_by": "researcher",
        "file": PAPER_FILE,
        "original_path": str(source),
        "sha256": digest,
        "size": staged.stat().st_size,
        "pages": len(pages),
        "text": text_path.relative_to(workspace).as_posix(),
        "extractor": extractor,
        "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    if previous:
        record["replaces_sha256"] = previous.get("sha256")
    manifest["paper"] = record
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return {**record, "new": True}


def _fetch(workspace: Path, *, max_mb: int, client: Any) -> CheckResult:
    from ...modules.data.zenodo import ZenodoClient, ZenodoError, parse_record_id

    workspace = Path(workspace)
    manifest_path = workspace / MANIFEST_FILE
    if manifest_path.is_file():
        try:
            return _verify_existing(workspace, json.loads(manifest_path.read_text(encoding="utf-8")))
        except (OSError, ValueError, KeyError, TypeError) as e:
            return CheckResult(False, (f"{MANIFEST_FILE} cannot be read: {e}",))

    record_id = parse_record_id(_research_question(workspace))
    if record_id is None:
        return CheckResult(
            False,
            (
                "the study's question names no Zenodo record "
                "(a DOI 10.5281/zenodo.<id> or a zenodo.org/records/<id> link)",
            ),
        )
    archive = workspace / ARCHIVE_DIR
    package = workspace / PACKAGE_DIR
    for d in (archive, package, workspace / TEXT_DIR):
        if d.exists():
            make_writable(d)
            shutil.rmtree(d)
    try:
        fetched = (client or ZenodoClient()).fetch(record_id, archive, max_bytes=max_mb * 1_000_000)
    except ZenodoError as e:
        return CheckResult(False, (str(e),))

    notes: list[str] = []
    package.mkdir(parents=True)
    budget = max_mb * 1_000_000 * _UNPACK_FACTOR
    try:
        for f in fetched.files:
            src = archive / f.path
            name = f.path.lower()
            if name.endswith(".zip"):
                notes += _unpack_zip(src, package, budget)
            elif name.endswith((".tar.gz", ".tgz", ".tar")):
                notes += _unpack_tar(src, package, budget)
            else:
                shutil.copy2(src, package / f.path)
    except (ValueError, zipfile.BadZipFile, tarfile.TarError, OSError) as e:
        return CheckResult(False, (f"the package cannot be unpacked safely: {e}",))

    tree = hash_tree(package)
    tops = sorted({p.split("/", 1)[0] for p in tree})
    root_hint = tops[0] if len(tops) == 1 and any("/" in p for p in tree) else "."
    texts = _extract_pdf_text(package, workspace / TEXT_DIR)
    _make_read_only(package)
    _make_read_only(archive)

    doc = {
        **fetched.as_dict(),
        "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "package_dir": PACKAGE_DIR,
        "package_root": root_hint,
        "package_files": [{"path": p, **v} for p, v in tree.items()],
        "package_bytes": sum(v["size"] for v in tree.values()),
        "pdf_text": texts,
        "notes": notes,
    }
    manifest_path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    stats = {
        "record": record_id,
        "downloaded": len(fetched.files),
        "verified": sum(1 for f in fetched.files if f.verified),
        "unpacked_files": len(tree),
        "bytes": doc["package_bytes"],
    }
    if not fetched.publications:
        notes.append("the record links no publication; targets must come from the package itself")
    return CheckResult(True, notes=tuple(notes[:10]), stats=stats)


# ── the plan contract ───────────────────────────────────────────────────────


def _safe_rel(path: Any) -> bool:
    return isinstance(path, str) and (path == "." or bool(_SAFE_ARG.match(path))) and ".." not in path.split("/")


def load_plan(workspace: Path) -> tuple[dict[str, Any] | None, str]:
    path = Path(workspace) / PLAN_FILE
    if not path.is_file():
        return None, f"{PLAN_FILE} is missing"
    try:
        plan = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return None, f"{PLAN_FILE} is not valid JSON: {e}"
    if not isinstance(plan, dict):
        return None, f"{PLAN_FILE} must be a JSON object"
    return plan, ""


def validate_plan(plan: dict[str, Any], package_dir: Path | None = None, workspace: Path | None = None) -> list[str]:
    """Every way ``plan`` breaks the contract, as sentences. Empty when it is sound."""
    errs: list[str] = []
    language = plan.get("language")
    if language not in INTERPRETERS:
        errs.append(f"language must be one of {sorted(INTERPRETERS)}, not {language!r}")
    env = plan.get("environment")
    if not isinstance(env, dict):
        errs.append("environment must be an object with image, packages and system_packages")
        env = {}
    image = env.get("image")
    if not isinstance(image, str) or not IMAGE_PATTERN.match(image):
        errs.append(
            f"environment.image {image!r} is not a pinned official image (rocker/r-ver:X.Y.Z or python:X.Y[.Z]-slim)"
        )
    elif language == "R" and not image.startswith("rocker/"):
        errs.append("an R study runs on rocker/r-ver")
    elif language == "Python" and not image.startswith("python:"):
        errs.append("a Python study runs on python:X.Y-slim")
    for i, pkg in enumerate(env.get("packages") or []):
        if not isinstance(pkg, dict) or not _PKG_NAME.match(str(pkg.get("name", ""))):
            errs.append(f"environment.packages[{i}] needs a plain package name")
        elif pkg.get("version") not in (None, "") and not _PKG_VERSION.match(str(pkg["version"])):
            errs.append(f"environment.packages[{i}] ({pkg['name']}) has an unusable version {pkg['version']!r}")
    for i, name in enumerate(env.get("system_packages") or []):
        if not isinstance(name, str) or not _SYS_PKG.match(name):
            errs.append(f"environment.system_packages[{i}] {name!r} is not a plain apt package name")

    entries = plan.get("entry_points")
    ids: set[str] = set()
    if not isinstance(entries, list) or not entries:
        errs.append("entry_points must list at least one script to run")
        entries = []
    allowed = INTERPRETERS.get(str(language), frozenset())
    for i, ep in enumerate(entries):
        where = f"entry_points[{i}]"
        if not isinstance(ep, dict):
            errs.append(f"{where} must be an object")
            continue
        eid = ep.get("id")
        if not isinstance(eid, str) or not _SLUG.match(eid):
            errs.append(f"{where}.id must be a short lowercase slug")
        elif eid in ids:
            errs.append(f"{where}.id {eid!r} is used twice")
        else:
            ids.add(eid)
        cmd = ep.get("command")
        if not isinstance(cmd, list) or len(cmd) < 2 or not all(isinstance(c, str) for c in cmd):
            errs.append(f"{where}.command must be a list: an interpreter and a script")
            continue
        if cmd[0] not in allowed:
            errs.append(f"{where}.command starts with {cmd[0]!r}; allowed for {language}: {sorted(allowed)}")
        scripts = [c for c in cmd[1:] if not c.startswith("-")]
        bad = [
            c
            for c in cmd[1:]
            if (c.startswith("-") and c not in _SAFE_FLAGS) or (not c.startswith("-") and not _safe_rel(c))
        ]
        if bad:
            errs.append(f"{where}.command has argument(s) that are not package-relative paths or allowed flags: {bad}")
        cwd = ep.get("cwd", ".")
        if not _safe_rel(cwd):
            errs.append(f"{where}.cwd {cwd!r} must be a path inside the package")
        elif package_dir is not None and scripts and not bad:
            if not (package_dir / cwd).is_dir():
                errs.append(f"{where}.cwd {cwd!r} is not a folder of the package")
            elif not (package_dir / cwd / scripts[0]).is_file():
                errs.append(f"{where}: script {scripts[0]!r} does not exist in the package (relative to {cwd!r})")
        t = ep.get("timeout_minutes")
        if t is not None and (isinstance(t, bool) or not isinstance(t, int | float) or not 0 < t <= 720):
            errs.append(f"{where}.timeout_minutes must be between 0 and 720")
        if not isinstance(ep.get("needs_network", False), bool):
            errs.append(f"{where}.needs_network must be true or false")

    exhibits = plan.get("exhibits")
    ex_ids: set[str] = set()
    if not isinstance(exhibits, list):
        errs.append("exhibits must list the paper's tables and figures")
        exhibits = []
    for i, ex in enumerate(exhibits):
        if not isinstance(ex, dict) or not isinstance(ex.get("id"), str) or not ex.get("label"):
            errs.append(f"exhibits[{i}] needs an id and a label")
            continue
        ex_ids.add(ex["id"])
        for s in ex.get("scripts") or []:
            if s not in ids:
                errs.append(f"exhibits[{i}] ({ex['id']}) names entry point {s!r}, which is not in entry_points")

    targets = plan.get("targets")
    if not isinstance(targets, list):
        errs.append("targets must be a list (empty when no reported number could be found)")
        targets = []
    t_ids: set[str] = set()
    for i, t in enumerate(targets):
        where = f"targets[{i}]"
        if not isinstance(t, dict):
            errs.append(f"{where} must be an object")
            continue
        tid = t.get("id")
        if not isinstance(tid, str) or not tid:
            errs.append(f"{where} needs an id")
        elif tid in t_ids:
            errs.append(f"{where}.id {tid!r} is used twice")
        else:
            t_ids.add(tid)
        where = f"{where} ({tid})"
        if t.get("exhibit") not in ex_ids:
            errs.append(f"{where} names exhibit {t.get('exhibit')!r}, which is not in exhibits")
        v = t.get("value")
        if isinstance(v, bool) or not isinstance(v, int | float):
            errs.append(f"{where}.value must be a number (a target without a value belongs in missing_targets)")
        if not isinstance(t.get("reported"), str) or not t.get("reported"):
            errs.append(f"{where}.reported must be the value exactly as printed in its source")
        level = t.get("level")
        raw_src = t.get("source")
        src: dict[str, Any] = raw_src if isinstance(raw_src, dict) else {}
        if level not in TARGET_LEVELS:
            errs.append(f"{where}.level must be 1 (the package's own result files) or 2 (the published paper)")
        elif level == 1:
            errs += _level_1_problems(where, t, src, package_dir)
        else:
            errs += _level_2_problems(where, t, src, package_dir, workspace)
    return errs


def _level_1_problems(where: str, t: dict[str, Any], src: dict[str, Any], package_dir: Path | None) -> list[str]:
    """A level-1 target is a cell of a result file the package ships, read by code."""
    if src.get("kind") != "package_file":
        return [f"{where}: a level-1 target's source.kind is 'package_file'"]
    file, locator = src.get("file"), src.get("locator")
    if not _safe_rel(file) or not str(file).lower().endswith((".csv", ".tsv")):
        return [f"{where}: source.file must be a package-relative .csv or .tsv path"]
    if not isinstance(locator, dict) or not isinstance(locator.get("row"), dict) or not locator.get("row"):
        return [f"{where}: source.locator needs row (column: value pairs picking one row) and column"]
    if not isinstance(locator.get("column"), str):
        return [f"{where}: source.locator.column must name a column"]
    if package_dir is None:
        return []
    path = package_dir / str(file)
    if not path.is_file():
        return [f"{where}: {file} is not a file of the package"]
    from .reproduction import _cell

    value, problem = _cell(path, locator)
    if value is None:
        return [f"{where}: {problem}"]
    v = t.get("value")
    if (
        isinstance(v, int | float)
        and not isinstance(v, bool)
        and not math.isclose(value, v, rel_tol=1e-9, abs_tol=1e-12)
    ):
        return [f"{where}: the package's {file} holds {value!r} at that cell, not {v!r}"]
    return []


def _level_2_problems(
    where: str, t: dict[str, Any], src: dict[str, Any], package_dir: Path | None, workspace: Path | None
) -> list[str]:
    """A level-2 target is a number printed in the paper, cited by page and exhibit."""
    from .reproduction import _decimals

    errs: list[str] = []
    if src.get("kind") != "paper":
        return [f"{where}: a level-2 target's source.kind is 'paper'"]
    doc, page = src.get("document"), src.get("page")
    if not _safe_rel(doc) or not str(doc).lower().endswith(".pdf"):
        errs.append(f"{where}: source.document must be the paper's PDF ({PAPER_FILE}, or a PDF in the package)")
    if isinstance(page, bool) or not isinstance(page, int) or page < 1:
        errs.append(f"{where}: source.page must be the page number (1 = first page of the PDF)")
    if not (src.get("table") or src.get("figure")):
        errs.append(f"{where}: source must name the table or figure")
    dec = src.get("decimals")
    reported = t.get("reported")
    if isinstance(dec, bool) or not isinstance(dec, int) or dec < 0:
        errs.append(f"{where}: source.decimals must be the printed precision (decimal places)")
    elif isinstance(reported, str) and _decimals(reported) != dec:
        errs.append(f"{where}: reported {reported!r} has {_decimals(reported)} decimals, source.decimals says {dec}")
    if errs or workspace is None:
        return errs
    pdf = workspace / str(doc) if str(doc) == PAPER_FILE else (package_dir / str(doc) if package_dir else None)
    if pdf is None or not pdf.is_file():
        return [f"{where}: {doc} does not exist (the researcher supplies the paper as {PAPER_FILE})"]
    text = _page_text(workspace, str(doc), page if isinstance(page, int) else 0)
    if text is None:
        return []  # no extractable text (a scanned PDF): the researcher checks the page at review
    token = _printed_number(str(reported))
    if token and token not in _normalise(text):
        errs.append(f"{where}: {reported!r} is not printed on page {page} of {doc}")
    return errs


def _normalise(text: str) -> str:
    return text.replace("\u2212", "-").replace("\u2013", "-").replace("\u2009", "").replace("\u00a0", " ")


def _printed_number(reported: str) -> str:
    m = re.search(r"[-+]?(?:\d[\d,]*\.?\d*|\.\d+)", _normalise(reported))
    return m.group(0) if m else ""


def _page_text(workspace: Path, document: str, page: int) -> str | None:
    """Extracted text of one page, from paper_text/ or package_text/; None when there is none."""
    root = PAPER_TEXT_DIR if document == PAPER_FILE else TEXT_DIR
    rel = Path(document).name if document == PAPER_FILE else document
    path = workspace / root / f"{rel}.txt"
    if not path.is_file():
        return None
    pages = re.split(r"^=== page (\d+) ===$", path.read_text(encoding="utf-8", errors="replace"), flags=re.M)
    found = {int(pages[i]): pages[i + 1] for i in range(1, len(pages) - 1, 2)}
    text = found.get(page)
    return text if text and text.strip() else None


def check_plan(workspace: Path) -> list[str]:
    """Contract check for the replication planner: the plan parses and is sound."""
    plan, why = load_plan(workspace)
    if plan is None:
        return [why]
    package = Path(workspace) / PACKAGE_DIR
    return validate_plan(plan, package if package.is_dir() else None, Path(workspace))
