"""``e2er publish <bundle>`` — describe an exported bundle as a research object.

Verifies the bundle offline, writes ``e2er.json`` into it, and writes the entry
to submit to the E2ER registry as a pull request. Nothing is uploaded: the
artifacts stay in your repository, the registry only records who made the
object, what it depends on and what verified.

    e2er publish ./my-bundle --owner bhanneke --project etf-comovement \\
        --github bhanneke --orcid 0009-0000-7466-9581 \\
        --repo https://github.com/bhanneke/E2ER-project --commit 3b91f0e --path examples/showcase \\
        --db ~/.e2er/e2er.db
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .core.dossier import build_dossier, dossier_id, dossier_url, stamp_paper
from .core.research_object import MANIFEST_NAME, PublishError, build_manifest, write_manifest

REGISTRY = "https://github.com/bhanneke/e2er-site"
REGISTRY_DIR = "registry/objects"


def publish(
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
) -> int:
    from .cli_verify import _run_checks, _verdict

    b = Path(bundle).expanduser().resolve()
    if not (b / "provenance.json").is_file():
        print(f"error: {b} is not an exported bundle (no provenance.json); run `e2er export` first")
        return 1

    checks = _run_checks(b, online=False)
    verdict, code = _verdict(checks)
    verification = [{"check": c.name, "status": c.status, "detail": c.detail} for c in checks]
    if code != 0:
        print(verdict)
        print("error: the bundle does not verify; fix it before publishing")
        return 1

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
        return 1

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
                return 1
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
    print(f"✓ Registry entry: {entry}")
    if not repository.get("commit"):
        print("  note: no --commit given; the registry can only verify an object pinned to a commit")
    print(f"\nTo publish, open a pull request against {REGISTRY} that adds\n  {REGISTRY_DIR}/{owner}/{project}.json")
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
