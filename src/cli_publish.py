"""``e2er publish <bundle>`` — describe an exported bundle as a research object.

Verifies the bundle offline, writes ``e2er.json`` into it, and writes the entry
to submit to the E2ER registry as a pull request. Nothing is uploaded: the
artifacts stay in your repository, the registry only records who made the
object, what it depends on and what verified.

    e2er publish ./my-bundle --owner bhanneke --project etf-comovement \\
        --github bhanneke --orcid 0009-0000-7466-9581 \\
        --repo https://github.com/bhanneke/E2ER-project --commit 3b91f0e --path examples/showcase \\
        --db ~/.e2er/e2er.db

``--dry-run`` rehearses everything in a scratch copy of the bundle and prints
the exact request ``--to`` would send; nothing in the bundle changes and
nothing is sent. ``--to https://e2er.org`` (after ``e2er login``) publishes the
description, the dossier and the file fingerprints; the files stay here. A
request that contains anything resembling a key or token is refused before it
leaves the machine.
"""

from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .core.dossier import build_dossier, dossier_id, dossier_url, stamp_paper
from .core.research_object import MANIFEST_NAME, PublishError, build_manifest, write_manifest
from .core.secret_scan import find_local_paths, find_secrets, sanitize

REGISTRY = "https://github.com/bhanneke/e2er-site"
REGISTRY_DIR = "registry/objects"


def _describe(
    bundle: str,
    *,
    owner: str,
    project: str,
    github: str | None = None,
    orcid: str | None = None,
    name: str | None = None,
    roles: list[str] | None = None,
    repo: str | None = None,
    commit: str | None = None,
    path: str | None = None,
    db: str | None = None,
    template: str = "empirical",
    license_id: str | None = None,
    derived_from: list[str] | None = None,
    out: str | None = None,
    stamp: bool = True,
    remote: bool = False,
) -> tuple[int, dict[str, Any] | None]:
    from .cli_verify import _run_checks, _verdict

    b = Path(bundle).expanduser().resolve()
    if not (b / "provenance.json").is_file():
        print(f"error: {b} is not an exported bundle (no provenance.json); run `e2er export` first")
        return 1, None

    checks = _run_checks(b, online=False)
    verdict, code = _verdict(checks)
    verification = [{"check": c.name, "status": c.status, "detail": c.detail} for c in checks]
    if code != 0:
        print(verdict)
        print("error: the bundle does not verify; fix it before publishing")
        return 1, None

    contributor: dict[str, Any] = {k: v for k, v in {"name": name, "github": github, "orcid": orcid}.items() if v}
    if contributor:
        contributor["roles"] = roles or ["conceptualization", "investigation"]
    repository = {k: v for k, v in {"url": repo, "commit": commit, "path": path}.items() if v}
    template_file = Path(__file__).resolve().parents[1] / "pipelines" / f"{template}.toml"
    try:
        manifest = build_manifest(
            b,
            owner=owner,
            project=project,
            contributors=[contributor] if contributor else [],
            repository=repository,
            db=Path(db).expanduser() if db else None,
            template=template,
            template_file=template_file,
            license_id=license_id,
            derived_from=derived_from,
            verification=verification,
        )
    except PublishError as e:
        print(f"error: {e}")
        return 1, None

    # The dossier: settings, pinned parts and data, addressed by its hash. The paper
    # then carries the standard author line and a first-page footnote with the
    # dossier link; its files are re-hashed and every check runs again.
    doc = build_dossier(manifest, db=Path(db).expanduser() if db else None, bundle=b)
    did = dossier_id(doc)
    if stamp and name and (b / "paper" / "paper.tex").is_file():
        changed = _stamp_and_compile(b, name, did)
        if changed:
            checks = _run_checks(b, online=False)
            verdict, code = _verdict(checks)
            if code != 0:
                print(verdict)
                print("error: the bundle no longer verifies after stamping the paper")
                return 1, None
            verification = [{"check": c.name, "status": c.status, "detail": c.detail} for c in checks]
            manifest = build_manifest(
                b,
                owner=owner,
                project=project,
                contributors=[contributor] if contributor else [],
                repository=repository,
                db=Path(db).expanduser() if db else None,
                template=template,
                template_file=template_file,
                license_id=license_id,
                derived_from=derived_from,
                verification=verification,
            )
            print(f"✓ Stamped paper/paper.tex ({name} with E2ER, dossier footnote) and updated provenance.json")
    manifest["dossier"] = {"id": did, "url": dossier_url(did), "doc": doc}

    written = write_manifest(b, manifest)
    # The registry-entry file is for a pull request; publishing to a platform needs none unless asked for.
    entry: Path | None = None
    if out or not remote:
        entry_root = Path(out).expanduser() if out else Path.cwd() / "e2er-registry-entry"
        entry = entry_root / REGISTRY_DIR / owner / f"{project}.json"
        entry.parent.mkdir(parents=True, exist_ok=True)
        entry.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    agents = manifest["ai"]["agents"]
    print(f"✓ Bundle verified ({len(checks)} checks)")
    print(f"✓ Wrote {written.relative_to(b.parent)}  ({manifest['content_id'][:19]}…)")
    print(
        f"  {manifest['id']}: {len(agents)} agents ({manifest['ai']['agents_source']}), "
        f"{len(manifest['literature'])} references, {len(manifest['data'])} data files, "
        f"{manifest['provenance']['files']} hashed files"
    )
    print(f"✓ Dossier {did[:23]}…  {dossier_url(did)}")
    if entry:
        print(f"✓ Registry entry: {entry}")
    if not repository.get("commit"):
        print("  note: no --commit given; the registry can only verify an object pinned to a commit")
    if not remote:
        print(
            f"\nTo publish, open a pull request against {REGISTRY} that adds\n  {REGISTRY_DIR}/{owner}/{project}.json"
        )
    return 0, manifest


def request_body(manifest: dict[str, Any], bundle: Path) -> dict[str, Any]:
    """What `--to` sends: the manifest (dossier id and url only), the dossier, the repository pin."""
    m = copy.deepcopy(manifest)
    d = m.pop("dossier")
    m["dossier"] = {"id": d["id"], "url": d["url"]}
    m = sanitize(m, bundle)
    return {"manifest": m, "dossier": {"id": d["id"], "doc": d["doc"]}, "repository": m.get("repository") or None}


def problems(body: dict[str, Any]) -> list[str]:
    """Why a request must not leave this machine."""
    out = [f"{path}: looks like a {kind}" for path, kind in find_secrets(body)]
    out += [f"{path}: names a local home directory" for path in find_local_paths(body)]
    return out


def publish(bundle: str, *, dry_run: bool = False, to_url: str | None = None, **kw: Any) -> int:
    """`e2er publish`: describe, stamp and verify; optionally rehearse (`dry_run`) or send (`to_url`)."""
    b = Path(bundle).expanduser().resolve()
    if dry_run or to_url:
        # Rehearse in a scratch copy: the exact request, and nothing written here.
        with tempfile.TemporaryDirectory() as tmp:
            scratch = Path(tmp) / b.name
            if (b / "provenance.json").is_file():
                shutil.copytree(b, scratch)
            log = io.StringIO()
            with contextlib.redirect_stdout(log):
                code, manifest = _describe(str(scratch), **{**kw, "out": str(Path(tmp) / "entry")}, remote=True)
            if code or manifest is None:
                print(log.getvalue().rstrip())
                return code or 1
            body = request_body(manifest, scratch)
        found = problems(body)
        if dry_run:
            print(json.dumps(body, indent=2, ensure_ascii=False))
            for p in found:
                print(f"refused: {p}", file=sys.stderr)
            print("dry run: nothing was written or sent", file=sys.stderr)
            return 1 if found else 0
        if found:
            print(
                "error: the request contains something that must not leave this machine; nothing was written or sent:"
            )
            for p in found:
                print(f"  {p}")
            return 1
    code, manifest = _describe(str(b), **kw, remote=bool(to_url))
    if code or manifest is None or not to_url:
        return code
    return _send(b, manifest, to_url)


def _send(b: Path, manifest: dict[str, Any], to_url: str) -> int:
    from .cli_platform import write_link
    from .core import platform_client as pc

    base = pc.base_url(to_url)
    body = request_body(manifest, b)
    found = problems(body)
    if found:
        print("error: the request contains something that must not leave this machine; nothing was sent:")
        for p in found:
            print(f"  {p}")
        return 1
    token = pc.load_token(base)
    if not token:
        print(f"error: not signed in to {base}; run `e2er login --url {base}`")
        return 1
    try:
        code, resp = pc.request(base, "POST", "/api/v1/studies", token=token, body=body)
    except Exception as e:  # noqa: BLE001 - network errors are the user's to see
        print(f"error: could not reach {base}: {e}")
        return 1
    if code not in (200, 201):
        print(f"error: {resp.get('error', code)}")
        for p in resp.get("problems") or []:
            print(f"  {p}")
        if resp.get("claim"):
            print(f"  {base}{resp['claim']}")
        return 1
    link = write_link(
        b,
        {
            "platform_url": base,
            "id": resp["id"],
            "owner_project": resp["owner_project"],
            "version": resp["version"],
            "dossier_id": body["dossier"]["id"],
            "content_id": manifest.get("content_id"),
            "published_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
    )
    word = "already published as" if resp.get("existing") else "published as"
    print(f"✓ {word} {resp['owner_project']}, version {resp['version']}: {resp['study_url']}")
    print(f"  dossier {resp['dossier_url']}")
    print(f"  link written to {link.relative_to(b)}")
    return 0


def _rehash(bundle: Path, rels: list[str]) -> None:
    prov_path = bundle / "provenance.json"
    prov = json.loads(prov_path.read_text(encoding="utf-8"))
    for rel in rels:
        f = bundle / rel
        if f.is_file() and rel in prov["files"]:
            data = f.read_bytes()
            prov["files"][rel].update(sha256=hashlib.sha256(data).hexdigest(), bytes=len(data))
    prov_path.write_text(json.dumps(prov, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _stamp_and_compile(bundle: Path, author: str, did: str) -> bool:
    """Stamp paper.tex; recompile paper.pdf with tectonic when it is installed."""
    tex = bundle / "paper" / "paper.tex"
    old = tex.read_text(encoding="utf-8")
    new = stamp_paper(old, author, did)
    if new == old:
        return False
    tex.write_text(new, encoding="utf-8")
    rels = ["paper/paper.tex"]
    if shutil.which("tectonic"):
        # Compile in a scratch copy: the export keeps figures in results/figures,
        # while the paper includes them from figures/ as in the run's workspace.
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp) / "paper"
            shutil.copytree(tex.parent, work)
            figs = bundle / "results" / "figures"
            if not (work / "figures").exists() and figs.is_dir():
                shutil.copytree(figs, work / "figures")
            res = subprocess.run(["tectonic", "paper.tex"], cwd=work, capture_output=True, text=True)
            if res.returncode == 0:
                shutil.copyfile(work / "paper.pdf", tex.parent / "paper.pdf")
        if res.returncode == 0:
            rels.append("paper/paper.pdf")
        else:
            print("warning: tectonic could not compile paper.tex; paper.pdf keeps the old version")
    else:
        print("note: tectonic is not installed; paper.pdf was not recompiled (the footnote is in paper.tex)")
    _rehash(bundle, rels)
    return True


__all__ = ["MANIFEST_NAME", "publish"]
