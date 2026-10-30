"""The study package that goes with a published study: one ``.e2er`` file, kept by the authors.

``e2er publish`` builds the package with ``e2er pack``'s own logic (package.py: the same files, the same
left-out rules; data a source's terms keep out are never in it) and puts it next to the study's files:

- ``--github``: as an asset of a GitHub release of the study's repository, one release per study version
  (tag ``<project>-v<N>``, asset ``<project>-v<N>.e2er``), made with the researcher's own gh login. A
  release that exists is reused only when its tag names the same commit and its asset has the same
  bytes; nothing is ever overwritten or forced.
- ``--zenodo``: as one more file in the code deposit (``<project>-v<N>.e2er``).

The publish request and e2er.json record it as ``package: {url, sha256, bytes, host, fingerprint}``:
the address, the SHA-256 and size of the file, where it is kept, and the package fingerprint
(e2er-package.json's own, over its list of files). e2er.org stores this record, never the file.

The package cannot be named inside the dossier it carries: it holds e2er.json and the stamped paper,
which name the dossier. e2er.org keeps the record next to the dossier instead (the study's versions and
``/api/v1/dossiers/<id>/package``); ``e2er verify <file> --against <address>`` compares a package with it
and ``e2er fetch <address>`` downloads it and checks its size and SHA-256.

In double-blind mode nothing is hosted: ``e2er pack --blind`` makes the file for the journal.
"""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin, urlsplit

from .export import package as pkg

HOSTS = ("github", "zenodo")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_FINGERPRINT = re.compile(r"^sha256:[0-9a-f]{64}$")
#: Redirects a download follows at most (GitHub sends a release asset to its storage host once).
MAX_REDIRECTS = 5
#: Local record of the package a publish made (never published itself; ``.e2er/`` stays out of every package).
RECORD = ".e2er/package.json"


class PackageHostError(RuntimeError):
    """The package could not be hosted, or downloaded and checked. The message is shown as is."""


# ── names and the record ─────────────────────────────────────────────────────


def tag_for(project: str, version: int) -> str:
    """The release of one study version: ``<project>-v<N>`` (never ``v*``, the pattern of e2er's own releases)."""
    return f"{project}-v{int(version)}"


def asset_name(project: str, version: int) -> str:
    return f"{tag_for(project, version)}{pkg.SUFFIX}"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def record(path: Path, url: str, host: str, fingerprint: str) -> dict[str, Any]:
    """``package`` as e2er.json and the publish request carry it."""
    if host not in HOSTS:
        raise ValueError(f"unknown package host {host!r}")
    return {
        "url": url,
        "sha256": sha256_file(path),
        "bytes": Path(path).stat().st_size,
        "host": host,
        "fingerprint": fingerprint,
    }


def record_problems(rec: Any) -> list[str]:
    """Why ``rec`` is not a package record (empty: it is one)."""
    if not isinstance(rec, dict):
        return ["the package record is not an object"]
    out: list[str] = []
    url = rec.get("url")
    if (
        not isinstance(url, str)
        or not urlsplit(url).hostname
        or not (urlsplit(url).scheme == "https" or test_server_url(url))
    ):
        out.append("its address is not an https address")
    if not isinstance(rec.get("sha256"), str) or not _SHA256.match(rec["sha256"]):
        out.append("its SHA-256 is not 64 hexadecimal characters")
    if not isinstance(rec.get("bytes"), int) or isinstance(rec.get("bytes"), bool) or rec["bytes"] < 1:
        out.append("its size is not a positive whole number of bytes")
    if rec.get("host") not in HOSTS:
        out.append(f"its host is not one of {', '.join(HOSTS)}")
    if not isinstance(rec.get("fingerprint"), str) or not _FINGERPRINT.match(rec["fingerprint"]):
        out.append("its fingerprint is not sha256:<64 hexadecimal characters>")
    return out


def file_name(rec: dict[str, Any]) -> str:
    """The file's name from its address (the last part), checked to be a plain ``<name>.e2er``."""
    raw = urlsplit(str(rec.get("url") or "")).path.rsplit("/", 1)[-1]
    from urllib.parse import unquote

    name = unquote(raw)
    if not name.lower().endswith(pkg.SUFFIX) or "/" in name or "\\" in name or name.startswith(".") or len(name) > 200:
        return "study.e2er"
    return name


def save_local(bundle: Path, rec: dict[str, Any], **extra: Any) -> Path:
    p = bundle / RECORD
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({**rec, **extra}, indent=2) + "\n", encoding="utf-8", newline="\n")
    return p


# ── the version number the platform will give ───────────────────────────────


def version_for(
    base: str, owner_project: str, content_id: str | None, request: Callable[..., Any] | None = None
) -> int:
    """The number e2er.org gives this version: the one that already has this content, else one past the latest.

    Read with GET from the study's public record before anything is pushed (a study not published yet: 1).
    """
    if request is None:
        from .platform_client import request as request_
    else:
        request_ = request
    try:
        code, study = request_(base, "GET", f"/api/v1/studies/{owner_project}")
    except Exception as e:  # noqa: BLE001 - a network error is the researcher's to see
        raise PackageHostError(f"could not ask {base} which version this is: {e}") from e
    if code == 404:
        return 1
    if code != 200 or not isinstance(study, dict):
        raise PackageHostError(f"{base} did not say which version this is (HTTP {code})")
    numbers: list[int] = []
    for v in study.get("versions") or []:
        if not isinstance(v, dict) or not isinstance(v.get("number"), int):
            continue
        if content_id and v.get("content_id") == content_id:
            return int(v["number"])
        numbers.append(int(v["number"]))
    latest = (study.get("latest") or {}).get("number") if isinstance(study.get("latest"), dict) else None
    if isinstance(latest, int):
        numbers.append(latest)
    return max(numbers, default=0) + 1


# ── GitHub: one release per study version, the package as its asset ──────────


def release_url(full: str, tag: str, name: str) -> str:
    return f"https://github.com/{full}/releases/download/{quote(tag, safe='')}/{quote(name, safe='')}"


def _gh(args: list[str]) -> Any:
    from .github_files import _run

    return _run(["gh", *args])


def _last(proc: Any) -> str:
    from .github_files import _last_line

    return str(_last_line(proc))


def _not_found(proc: Any) -> bool:
    text = f"{proc.stderr}\n{proc.stdout}".lower()
    return "not found" in text or "404" in text


def _tag_commit(full: str, tag: str) -> str | None:
    """The commit the tag names in ``full`` (an annotated tag followed to its commit), or None without the tag."""
    proc = _gh(["api", f"repos/{full}/git/ref/tags/{tag}"])
    if proc.returncode != 0:
        if _not_found(proc):
            return None
        raise PackageHostError(f"gh could not read the tag {tag} of {full} ({_last(proc)}); nothing was uploaded")
    try:
        obj = json.loads(proc.stdout).get("object") or {}
    except (ValueError, AttributeError) as e:
        raise PackageHostError(f"gh answered something that is not a tag for {tag} ({e})") from e
    sha, kind = str(obj.get("sha") or ""), obj.get("type")
    if kind == "tag":
        proc = _gh(["api", f"repos/{full}/git/tags/{sha}"])
        if proc.returncode != 0:
            raise PackageHostError(f"gh could not read the tag {tag} of {full} ({_last(proc)})")
        try:
            obj = json.loads(proc.stdout).get("object") or {}
        except (ValueError, AttributeError) as e:
            raise PackageHostError(f"gh answered something that is not a tag for {tag} ({e})") from e
        sha, kind = str(obj.get("sha") or ""), obj.get("type")
    if kind != "commit" or not sha:
        raise PackageHostError(f"the tag {tag} of {full} names no commit")
    return sha


def _release(full: str, tag: str) -> dict[str, Any] | None:
    proc = _gh(["release", "view", tag, "--repo", full, "--json", "tagName,isDraft,assets,url"])
    if proc.returncode != 0:
        if _not_found(proc) or "release not found" in f"{proc.stderr}".lower():
            return None
        raise PackageHostError(f"gh could not look up the release {tag} of {full} ({_last(proc)})")
    try:
        rel = json.loads(proc.stdout)
    except ValueError as e:
        raise PackageHostError(f"gh answered something that is not JSON for the release {tag} ({e})") from e
    return rel if isinstance(rel, dict) else None


def _same_asset(full: str, tag: str, name: str, file: Path, listed_size: Any) -> bool:
    """Whether the release's asset ``name`` has the bytes of ``file`` (the size first, then the SHA-256)."""
    if isinstance(listed_size, int) and listed_size != file.stat().st_size:
        return False
    with tempfile.TemporaryDirectory(prefix="e2er-asset-") as td:
        proc = _gh(["release", "download", tag, "--repo", full, "--pattern", name, "--dir", td])
        got = Path(td) / name
        if proc.returncode != 0 or not got.is_file():
            raise PackageHostError(
                f"gh could not download {name} from the release {tag} of {full} to compare it ({_last(proc)})"
            )
        return sha256_file(got) == sha256_file(file)


def _named(file: Path, name: str, folder: Path) -> Path:
    """``file`` under the asset's name (gh names an asset after its file): itself, or a copy in ``folder``."""
    if file.name == name:
        return file
    import shutil

    out = folder / name
    shutil.copyfile(file, out)
    return out


@dataclass
class Hosted:
    url: str
    tag: str
    name: str
    created: bool  # False: the release and its asset were there already, with these bytes


def host_release(full: str, *, tag: str, commit: str, file: Path, name: str, title: str, notes: str) -> Hosted:
    """Put ``file`` as asset ``name`` on the release ``tag`` of ``full`` at ``commit``; GitHubError-free.

    An existing release or tag is used only when the tag names ``commit``; an existing asset only when its
    bytes are the file's. The release is never marked "latest" (a repository's own releases stay first).
    """
    rel = _release(full, tag)
    at = _tag_commit(full, tag)
    if at is not None and at != commit:
        raise PackageHostError(
            f"{full} already has the tag {tag} at another commit ({at[:7]}, not {commit[:7]}); e2er never moves a "
            "tag. The package was not uploaded."
        )
    url = release_url(full, tag, name)
    if rel is not None:
        if rel.get("isDraft"):
            raise PackageHostError(
                f"the release {tag} of {full} is a draft, whose files nobody else can download; publish or delete "
                "it on GitHub, then publish again. The package was not uploaded."
            )
        asset = next((a for a in rel.get("assets") or [] if isinstance(a, dict) and a.get("name") == name), None)
        if asset is not None:
            if _same_asset(full, tag, name, file, asset.get("size")):
                return Hosted(url=url, tag=tag, name=name, created=False)
            raise PackageHostError(
                f"the release {tag} of {full} already has a file {name} with other bytes; e2er never overwrites it. "
                "The package was not uploaded."
            )
        with tempfile.TemporaryDirectory(prefix="e2er-asset-") as td:
            proc = _gh(["release", "upload", tag, str(_named(file, name, Path(td))), "--repo", full])
        if proc.returncode != 0:
            raise PackageHostError(f"gh could not upload {name} to the release {tag} of {full} ({_last(proc)})")
        return Hosted(url=url, tag=tag, name=name, created=True)
    with tempfile.TemporaryDirectory(prefix="e2er-asset-") as td:
        src = _named(file, name, Path(td))
        args = ["release", "create", tag, str(src), "--repo", full, "--title", title[:200], "--notes", notes[:4000]]
        args += ["--latest=false"]
        if at is None:
            args += ["--target", commit]
        else:
            args += ["--verify-tag"]
        proc = _gh(args)
    if proc.returncode != 0:
        raise PackageHostError(f"gh could not create the release {tag} of {full} ({_last(proc)})")
    return Hosted(url=url, tag=tag, name=name, created=True)


def plan_lines(full: str, tag: str, name: str, size: int | None = None) -> list[str]:
    shown = f" ({pkg.human_size(size)})" if size else ""
    return [f"github: would upload {name}{shown} as the file of the release {tag} of github.com/{full}"]


# ── Zenodo: one more file in the code deposit ────────────────────────────────


def zenodo_url(base: str, record_id: int | str, name: str) -> str:
    return f"{base.rstrip('/')}/records/{record_id}/files/{quote(name, safe='')}"


# ── fetching a recorded package (`e2er fetch`) ───────────────────────────────


def download_client() -> Any:
    """The HTTP client for downloads; tests replace this with an httpx.MockTransport client."""
    import httpx

    return httpx.Client(timeout=httpx.Timeout(60.0, read=300.0), headers={"user-agent": "e2er-cli"})


def test_server_url(url: str) -> bool:
    """A package on a test's own server: http or https to this computer, in a test run only (test_guard).

    e2er's tests of ``e2er fetch`` and ``e2er verify --against`` (tests/test_reviewer_path.py) serve the
    package from a local server. Outside a test run every package address is https to a public host.
    """
    from .test_guard import _loopback, under_test

    parts = urlsplit(url)
    return under_test() and parts.scheme in ("http", "https") and _loopback((parts.hostname or "").lower())


def _check_hop(url: str) -> None:
    from ..modules.fetch.http import check_url
    from .test_guard import RefusedInTestError, check_target

    if test_server_url(url):
        return  # a test's own server on this computer (never outside a test run)
    if urlsplit(url).scheme != "https":
        raise PackageHostError(f"the package's address is not https ({url[:120]}); nothing was downloaded")
    try:
        check_target(url)
    except RefusedInTestError as e:
        raise PackageHostError(str(e)) from e
    try:
        check_url(url)
    except ValueError as e:
        raise PackageHostError(f"refusing to download from {urlsplit(url).hostname}: {e}") from e


def download(url: str, dest: Path, *, expect_bytes: int, expect_sha256: str, max_bytes: int | None = None) -> Path:
    """Stream ``url`` into ``dest`` and check its size and SHA-256 against the record; the file, else an error.

    Redirects are followed by hand (https only, every hop checked); the download stops past the recorded
    size (and the package cap); a file that does not match is removed, and nothing is left at ``dest``.
    """
    cap = min(int(expect_bytes), int(max_bytes or pkg.MAX_TOTAL_BYTES))
    if expect_bytes > cap:
        raise PackageHostError(
            f"the recorded package is {pkg.human_size(expect_bytes)}, more than e2er opens "
            f"({pkg.human_size(cap)}; E2ER_PACKAGE_MAX_BYTES raises it)"
        )
    dest = Path(dest)
    if dest.exists():
        raise PackageHostError(f"{dest} exists already; choose another place with -o")
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_name(f".{dest.name}.partial")
    h = hashlib.sha256()
    n = 0
    try:
        with download_client() as client:
            current = url
            for _ in range(MAX_REDIRECTS + 1):
                _check_hop(current)
                with client.stream("GET", current, follow_redirects=False) as r:
                    if r.status_code in (301, 302, 303, 307, 308):
                        loc = r.headers.get("location")
                        if not loc:
                            raise PackageHostError(f"{urlsplit(current).hostname} redirected without an address")
                        current = urljoin(current, loc)
                        continue
                    if r.status_code != 200:
                        raise PackageHostError(
                            f"{urlsplit(current).hostname} answered {r.status_code} for the package; nothing was kept"
                        )
                    with partial.open("wb") as out:
                        for chunk in r.iter_bytes(1 << 20):
                            n += len(chunk)
                            if n > cap:
                                raise PackageHostError(
                                    f"the file is larger than the recorded {expect_bytes} bytes; nothing was kept"
                                )
                            h.update(chunk)
                            out.write(chunk)
                    break
            else:
                raise PackageHostError(f"more than {MAX_REDIRECTS} redirects for the package; nothing was kept")
        if n != expect_bytes:
            raise PackageHostError(f"the file has {n} bytes, the record says {expect_bytes}; nothing was kept")
        if h.hexdigest() != expect_sha256:
            raise PackageHostError(
                "the file's SHA-256 is not the one e2er.org records (it changed after publishing, or the download "
                "was altered); nothing was kept"
            )
        partial.replace(dest)
    except PackageHostError:
        partial.unlink(missing_ok=True)
        raise
    except Exception as e:  # noqa: BLE001 - a network error is the reader's to see
        partial.unlink(missing_ok=True)
        raise PackageHostError(f"the download stopped: {e}") from e
    return dest


__all__ = [
    "HOSTS",
    "Hosted",
    "PackageHostError",
    "asset_name",
    "download",
    "host_release",
    "record",
    "record_problems",
    "tag_for",
    "version_for",
]
