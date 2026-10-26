"""A published study's files in a public GitHub repository (``e2er publish --github``).

``e2er publish --github`` pushes the study's files to a public repository with
the researcher's own GitHub login (the ``gh`` command line tool, or
``GH_TOKEN``) and records the repository, the folder and the commit with the
study. e2er.org never receives a GitHub token: it reads the public files at
the commit, as for any study that names a repository.

- **What goes up** is exactly what ``e2er pack`` ships (package.py): the paper,
  the code, the recipe, provenance.json, e2er.json with its dossier, the
  package's own e2er-package.json, and the data only where the source's terms
  allow passing them on. Data a source's terms keep out, and files the study
  built from them, stay out; the recipe's steps load and build them again.
  The package is built and opened here, so the logic is pack's own.
- **Where**: ``--github`` alone makes ``<your login>/<project>``;
  ``--github owner/repo`` uses that repository, making it when it does not
  exist; ``--github-path <folder>`` puts the study in a folder of it, so
  several studies can share one repository.
- **How**: one ordinary commit on top of the repository's default branch, never
  a force push. Only the study's folder changes. A folder that holds another
  study's or anyone else's files is refused, and so is a folder inside another
  study's folder. A new version is a new commit; publishing the same files
  again makes none.

e2er.json in the repository records the repository and the folder but not the
commit: no commit can name itself. The commit is recorded in the local
e2er.json, in ``.e2er/github.json`` and with the study on e2er.org.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

GITHUB = "https://github.com"
RECORD = ".e2er/github.json"
#: GitHub's rules: an owner is a login or an organisation, a repository name letters, digits, . _ -
_OWNER = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
_REPO = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")

NO_GH = (
    "--github pushes the files with your own GitHub login through the GitHub command line tool (gh), "
    "which is not installed. Install it from https://cli.github.com, run `gh auth login`, and publish again. "
    "e2er.org never receives a GitHub token."
)
NOT_LOGGED_IN = (
    "gh is not logged in to GitHub. Run `gh auth login` (or set GH_TOKEN to a token of your own), "
    "then publish again. e2er.org never receives a GitHub token."
)


class GitHubError(Exception):
    """Pushing the files failed or was refused. The message is shown as is; nothing was pushed."""


@dataclass(frozen=True)
class Target:
    """Where the study's files go: a repository and a folder in it ("" for the repository's root)."""

    owner: str
    repo: str
    path: str = ""

    @property
    def full(self) -> str:
        return f"{self.owner}/{self.repo}"

    @property
    def url(self) -> str:
        return f"{GITHUB}/{self.owner}/{self.repo}"

    @property
    def remote(self) -> str:
        return f"{self.url}.git"

    def tree(self, commit: str) -> str:
        return f"{self.url}/tree/{commit}" + (f"/{self.path}" if self.path else "")

    def where(self) -> str:
        return f"github.com/{self.full}" + (f", folder {self.path}" if self.path else "")


def clean_path(path: str | None) -> str:
    """The study's folder in the repository, checked: plain names separated by "/", nothing hidden, no "..".

    Raises ValueError with the reason.
    """
    raw = (path or "").strip().strip("/")
    if not raw:
        return ""
    if "\\" in raw or len(raw) > 300:
        raise ValueError(f"--github-path {path!r}: use plain folder names separated by /")
    parts = raw.split("/")
    for part in parts:
        if not _SEGMENT.match(part) or part in (".", ".."):
            raise ValueError(
                f"--github-path {path!r}: {part!r} is not a plain folder name "
                "(letters, digits, . _ -, not starting with a dot)"
            )
    return "/".join(parts)


def parse_target(spec: str | None, *, project: str, login: str | None, path: str | None = None) -> Target:
    """``--github`` (None: ``<login>/<project>``) or ``--github owner/repo``, with ``--github-path``."""
    folder = clean_path(path)
    if spec:
        owner, sep, repo = spec.strip().removeprefix(f"{GITHUB}/").removesuffix(".git").partition("/")
        if not sep or not _OWNER.match(owner) or not _REPO.match(repo) or repo in (".", ".."):
            raise ValueError(f"--github {spec!r}: give the repository as owner/name, e.g. bhanneke/e2er-demos")
        return Target(owner, repo, folder)
    if not login:
        raise ValueError("--github without a repository needs your GitHub login (gh auth login)")
    if not _REPO.match(project):
        raise ValueError(f"--project {project!r} is not a GitHub repository name; give --github owner/name")
    return Target(login, project, folder)


# ── gh: the researcher's own login ───────────────────────────────────────────


def _run(cmd: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    from .test_guard import RefusedInTestError, check_github

    # Every command here talks to GitHub (gh, or git with gh's login): none in a test run (test_guard.py).
    if cmd[:1] in (["gh"], ["git"]):
        try:
            check_github()
        except RefusedInTestError as e:
            raise GitHubError(str(e)) from e
    return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=600)


def _last_line(proc: subprocess.CompletedProcess) -> str:
    lines = (proc.stderr or proc.stdout or "").strip().splitlines()
    return lines[-1] if lines else f"exit {proc.returncode}"


def gh_user() -> dict[str, Any]:
    """The GitHub account gh is logged in as: ``{"login": …, "id": …}``. Raises GitHubError with what to run."""
    if not shutil.which("gh"):
        raise GitHubError(NO_GH)
    proc = _run(["gh", "api", "user"])
    if proc.returncode != 0:
        text = f"{proc.stderr}\n{proc.stdout}".lower()
        if any(w in text for w in ("auth login", "not logged", "authentication", "401", "bad credentials")):
            raise GitHubError(NOT_LOGGED_IN)
        raise GitHubError(f"gh could not ask GitHub who you are ({_last_line(proc)}); nothing was pushed")
    try:
        user = json.loads(proc.stdout)
    except ValueError as e:
        raise GitHubError(f"gh answered something that is not JSON ({e}); nothing was pushed") from e
    if not isinstance(user, dict) or not isinstance(user.get("login"), str):
        raise GitHubError(NOT_LOGGED_IN)
    return user


def repo_state(t: Target) -> dict[str, Any] | None:
    """The repository as gh sees it (visibility, default branch), or None when it does not exist."""
    proc = _run(["gh", "repo", "view", t.full, "--json", "visibility,defaultBranchRef,isArchived"])
    if proc.returncode != 0:
        text = f"{proc.stderr}\n{proc.stdout}"
        if "could not resolve" in text.lower() or "not found" in text.lower():
            return None
        raise GitHubError(f"gh could not look up {t.full} ({_last_line(proc)}); nothing was pushed")
    try:
        state = json.loads(proc.stdout)
    except ValueError as e:
        raise GitHubError(f"gh answered something that is not JSON for {t.full} ({e})") from e
    return state if isinstance(state, dict) else {}


def check_repo(state: dict[str, Any] | None, t: Target) -> None:
    """Refuse a repository whose files the public cannot read, or that takes no pushes."""
    if state is None:
        return
    if str(state.get("visibility") or "").upper() not in ("PUBLIC", ""):
        raise GitHubError(
            f"{t.full} is {str(state['visibility']).lower()}: --github puts the study's files in a public "
            "repository, so e2er.org and readers can open them. Choose a public repository, or publish without "
            "--github."
        )
    if state.get("isArchived"):
        raise GitHubError(f"{t.full} is archived and takes no new commits; choose another repository")


def create_repo(t: Target, description: str) -> None:
    proc = _run(["gh", "repo", "create", t.full, "--public", "--description", description[:300]])
    if proc.returncode != 0:
        raise GitHubError(f"gh could not create the public repository {t.full} ({_last_line(proc)})")


# ── what goes up: what `e2er pack` ships ─────────────────────────────────────

#: The host, as package.left_out_data names it ("too large for GitHub (145 MB)").
HOST = "GitHub"
#: GitHub refuses a push with a file larger than this (100 MiB); there is no Git LFS on this path. A data file
#: over it that a recorded step gets back is left out; any other file over it stops the publish (too_large).
GITHUB_FILE_LIMIT = 100 * 1024 * 1024


@dataclass
class Staged:
    """The study's files as the package ships them, opened in ``root``."""

    root: Path
    files: list[str]
    left_out: list[dict[str, Any]]
    manifest: dict[str, Any] = field(default_factory=dict)


def stage(bundle: Path, dest: Path, keep: Path | None = None) -> Staged:
    """Pack the study (package.build) and open the package into the new folder ``dest``: what goes up.

    Data a source's terms keep out (and data built from them) are not in the package, so they are not
    here; nor is a data file larger than GitHub takes that a recorded step of the study loads or builds
    again (one that nothing gets back raises package.TooLargeError). The package's own e2er-package.json
    is: it names what was left out and how a rerun loads and builds it again, which `e2er verify` and
    `e2er reproduce` read in a clone of the repository.

    ``keep``: the package itself is copied there too (the study package a release of the repository carries,
    study_package.py): the folder that goes up is exactly that package, opened.
    """
    from .export import package as pkg

    with tempfile.TemporaryDirectory(prefix="e2er-github-pack-") as td:
        packed = pkg.build(bundle, Path(td) / f"study{pkg.SUFFIX}", host=HOST, max_file_bytes=GITHUB_FILE_LIMIT)
        opened = pkg.open_package(packed.path, dest)
        if keep is not None:
            keep.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(packed.path, keep)
    files = sorted(p.relative_to(opened.root).as_posix() for p in opened.root.rglob("*") if p.is_file())
    return Staged(
        root=opened.root, files=files, left_out=list(packed.manifest.get("left_out") or []), manifest=packed.manifest
    )


def kept_out(bundle: Path, staged: Staged) -> list[str]:
    """Files of the staged copy that must never be published (a check on top of pack's own): none, normally."""
    from .data_terms import restricted_paths, uses

    restricted = set(restricted_paths(bundle))
    for use in uses(bundle):
        restricted |= {f for f in use.files if f.startswith("data/") and not f.endswith((".json", ".md"))}
    restricted |= {i["path"] for i in staged.left_out}
    return sorted(set(staged.files) & restricted)


def secrets_in(staged: Staged) -> list[str]:
    """``path: kind`` for every staged file that holds a key or token (secret_scan.scan_files, the shared check).

    Every file, whatever its size or encoding (read in chunks; bytes that are not UTF-8 are replaced).
    """
    from .secret_scan import scan_files

    return scan_files(staged.root, staged.files)


def too_large(staged: Staged) -> list[str]:
    """``path (size)`` for every staged file GitHub would refuse: larger than 100 MiB."""
    out: list[str] = []
    for rel in staged.files:
        size = (staged.root / rel).stat().st_size
        if size > GITHUB_FILE_LIMIT:
            out.append(f"{rel} ({size / 1_000_000:.0f} MB)")
    return out


# ── the push: one ordinary commit, never forced ──────────────────────────────


@dataclass
class Pushed:
    commit: str
    branch: str
    created: bool
    changed: bool
    kept: list[str] = field(default_factory=list)  # files in the study's folder that are not the study's


def _git_env() -> dict[str, str]:
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"  # never ask on the terminal: gh's login, or a plain error
    return env


def _git(args: list[str], cwd: Path | None = None, *, check: bool = True) -> subprocess.CompletedProcess:
    # The researcher's own gh login answers git's request for credentials; nothing is stored.
    cmd = ["git", "-c", "credential.helper=", "-c", "credential.helper=!gh auth git-credential", *args]
    proc = _run(cmd, cwd=cwd, env=_git_env())
    if check and proc.returncode != 0:
        raise GitHubError(f"git {args[0]} failed: {_last_line(proc)}")
    return proc


def _ids(folder: Path) -> set[str]:
    """What a folder in the repository says it is: its study's paper id and its e2er.org id."""
    out: set[str] = set()
    for name, keys in (("provenance.json", ("run", "paper_id")), ("e2er.json", ("id",))):
        try:
            doc: Any = json.loads((folder / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for k in keys:
            doc = doc.get(k) if isinstance(doc, dict) else None
        if isinstance(doc, str) and doc:
            out.add(doc)
    return out


def _previous_files(folder: Path) -> set[str]:
    """The files an earlier version of the study put in its folder (its package list and its provenance)."""
    out = {"e2er-package.json", "e2er.json", "provenance.json"}
    try:
        pkg_doc = json.loads((folder / "e2er-package.json").read_text(encoding="utf-8"))
        out |= {
            c["path"] for c in pkg_doc.get("contents") or [] if isinstance(c, dict) and isinstance(c.get("path"), str)
        }
    except (OSError, ValueError, AttributeError):
        pass
    try:
        prov = json.loads((folder / "provenance.json").read_text(encoding="utf-8"))
        out |= set((prov.get("files") or {}).keys())
    except (OSError, ValueError, AttributeError):
        pass
    return out


def _claim(work: Path, t: Target, study_ids: set[str]) -> list[str]:
    """Check that the study may write its folder; returns the tracked files of the folder (relative to it)."""
    path = t.path
    where = f"{t.full}" + (f", folder {path}" if path else " (its root)")
    if path:
        parts = path.split("/")
        for i in range(len(parts)):
            above = work.joinpath(*parts[:i])
            if (above / "provenance.json").is_file():
                inside = "/".join(parts[:i]) or "the repository's root"
                raise GitHubError(
                    f"{path} is inside the folder of another study ({inside} in {t.full}); nothing was pushed. "
                    "Choose a --github-path outside it."
                )
            if above.joinpath(parts[i]).is_file() or above.joinpath(parts[i]).is_symlink():
                raise GitHubError(f"{where}: {'/'.join(parts[: i + 1])} is a file, not a folder; nothing was pushed")
    folder = work / path if path else work
    proc = _git(["ls-files", "-z", "--", path or "."], cwd=work)
    tracked = [p for p in proc.stdout.split("\0") if p]
    if not tracked:
        return []
    rel = [p[len(path) + 1 :] if path else p for p in tracked]
    if not (_ids(folder) & study_ids):
        shown = ", ".join(rel[:3]) + (f" and {len(rel) - 3} more" if len(rel) > 3 else "")
        hint = "Choose another --github-path" if path else "Give a --github-path for the study's own folder"
        raise GitHubError(
            f"{where} already holds files that are not this study's ({shown}); nothing was pushed. "
            f"e2er never overwrites them. {hint}, or another repository."
        )
    return rel


def _inside(root: Path, path: Path) -> bool:
    """Does ``path`` (with every link on the way resolved) stay inside ``root`` (resolved)?"""
    try:
        return path.resolve().is_relative_to(root)
    except (OSError, RuntimeError):
        return False


def _tracked_links(work: Path, path: str) -> list[str]:
    """The symbolic links git tracks in the study's folder (mode 120000)."""
    proc = _git(["ls-files", "-s", "-z", "--", path or "."], cwd=work)
    out = []
    for entry in proc.stdout.split("\0"):
        meta, _, name = entry.partition("\t")
        if name and meta.split(" ", 1)[0] == "120000":
            out.append(name)
    return sorted(out)


def push(
    t: Target,
    staged: Staged,
    *,
    study_ids: set[str],
    message: str,
    user: dict[str, Any],
    restricted: set[str],
    exists: bool,
) -> Pushed:
    """Commit the staged files into the study's folder and push them; returns the commit that holds them.

    The study's folder is replaced by the staged files: an earlier version's files that the new version no
    longer has are removed, files of the folder that were never the study's are kept (and named). Nothing
    outside the folder changes. A push the repository rejects (it moved meanwhile) is reported; it is never
    forced.
    """
    with tempfile.TemporaryDirectory(prefix="e2er-github-") as td:
        work = Path(td) / "repo"
        _git(["-c", "init.defaultBranch=main", "clone", "--quiet", "--depth", "1", t.remote, str(work)])
        branch = _git(["symbolic-ref", "--short", "HEAD"], cwd=work).stdout.strip() or "main"
        tracked = _claim(work, t, study_ids)
        links = _tracked_links(work, t.path)
        if links:
            # A collaborator's committed link ("code" -> /Users/…/victim_dir) made e2er write the study's files
            # outside the clone, on this computer (security review 2026-10-23).
            raise GitHubError(
                f"{t.full} holds symbolic links in the study's folder ({', '.join(links[:5])}); e2er does not write "
                "through them. Remove them from the repository; nothing was pushed."
            )
        folder = work / t.path if t.path else work
        root = work.resolve()
        previous = _previous_files(folder) if tracked else set()
        new = set(staged.files)
        kept = [r for r in tracked if r not in new and r not in previous and not r.startswith("e2er-package/")]
        for r in tracked:
            if r not in new and r not in kept:
                _git(["rm", "--quiet", "--", f"{t.path}/{r}" if t.path else r], cwd=work)
        for r in staged.files:
            dst = folder / r
            if not _inside(root, dst):
                raise GitHubError(f"{t.full}: {r} would be written outside the clone; nothing was pushed")
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.is_symlink() or dst.is_dir() or not _inside(root, dst):
                raise GitHubError(f"{t.full}: {r} in the study's folder is not a plain file; nothing was pushed")
            shutil.copyfile(staged.root / r, dst, follow_symlinks=False)
        # The last word: no file a source's terms keep out is in the folder about to be committed.
        present = sorted(r for r in restricted if (folder / r).exists())
        if present:
            raise GitHubError(
                f"{', '.join(present)} would be published in {t.full}, but the source's terms keep "
                "it out; nothing was pushed"
            )
        _git(["add", "--all", "--", t.path or "."], cwd=work)
        staged_changes = _git(["diff", "--cached", "--quiet"], cwd=work, check=False).returncode != 0
        if not staged_changes:
            head = _git(["rev-parse", "HEAD"], cwd=work, check=False)
            if head.returncode == 0:
                return Pushed(head.stdout.strip(), branch, created=not exists, changed=False, kept=kept)
        ident: list[str] = []
        if not _git(["config", "user.email"], cwd=work, check=False).stdout.strip():
            login = str(user.get("login"))
            email = (
                f"{user['id']}+{login}@users.noreply.github.com"
                if user.get("id")
                else f"{login}@users.noreply.github.com"
            )
            ident = ["-c", f"user.name={login}", "-c", f"user.email={email}"]
        _git([*ident, "commit", "--quiet", "--allow-empty", "-m", message], cwd=work)
        commit = _git(["rev-parse", "HEAD"], cwd=work).stdout.strip()
        proc = _git(["push", "--quiet", "origin", f"HEAD:refs/heads/{branch}"], cwd=work, check=False)
        if proc.returncode != 0:
            text = f"{proc.stderr}\n{proc.stdout}".lower()
            if "rejected" in text or "fetch first" in text or "non-fast-forward" in text:
                raise GitHubError(
                    f"{t.full} changed while publishing (a commit arrived on {branch}); nothing was overwritten "
                    "and nothing was pushed. Publish again."
                )
            raise GitHubError(f"git push to {t.full} failed: {_last_line(proc)}")
        return Pushed(commit, branch, created=not exists, changed=True, kept=kept)


def save_record(bundle: Path, record: dict[str, Any]) -> Path:
    """``.e2er/github.json``: where the files went, at which commit (a local record, never published)."""
    p = bundle / RECORD
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return p
