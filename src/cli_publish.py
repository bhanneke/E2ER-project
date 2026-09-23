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

import json
from pathlib import Path
from typing import Any

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
    print(f"✓ Registry entry: {entry}")
    if not repository.get("commit"):
        print("  note: no --commit given; the registry can only verify an object pinned to a commit")
    print(f"\nTo publish, open a pull request against {REGISTRY} that adds\n  {REGISTRY_DIR}/{owner}/{project}.json")
    return 0


__all__ = ["MANIFEST_NAME", "publish"]
