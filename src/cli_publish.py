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
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .core import zenodo as zen
from .core.availability import describe as describe_availability
from .core.availability import resolve
from .core.bibliography import escape_bib, point_bibliography, unresolved_citations
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
    data: str | None = None,
    code: str | None = None,
    data_url: str | None = None,
    code_url: str | None = None,
    zenodo: bool = False,
    zenodo_sandbox: bool = False,
    zenodo_plan_only: bool = False,
    site: str | None = None,
) -> tuple[int, dict[str, Any] | None]:
    from .cli_verify import _run_checks, _verdict

    b = Path(bundle).expanduser().resolve()
    if not (b / "provenance.json").is_file():
        print(f"error: {b} is not an exported bundle (no provenance.json); run `e2er export` first")
        return 1, None

    # Data and code: public or private (private unless stated). Private material
    # stays here; only its fingerprints are published, as for every file.
    repository = {k: v for k, v in {"url": repo, "commit": commit, "path": path}.items() if v}
    try:
        availability, notes = resolve(
            data=data, code=code, data_url=data_url, code_url_=code_url, repository=repository
        )
    except ValueError as e:
        print(f"error: {e}")
        return 1, None
    for n in notes:
        print(f"note: {n}")
    deposits = _deposit_plan(b, availability, project) if (zenodo or zenodo_plan_only) else {}
    if zenodo or zenodo_plan_only:
        refused = [i for i in ("data", "code") if availability[i]["access"] == "private"]
        for item in refused:
            print(f"note: --zenodo leaves the {item} alone: it is private (use --{item} public to deposit it)")
        if not deposits:
            print("error: --zenodo has nothing to deposit: neither data nor code is public, or their folders are empty")
            return 1, None
    token = None
    if zenodo and not zenodo_plan_only:
        token = zen.load_token(zenodo_sandbox)
        if not token:
            print(f"error: --zenodo needs your own Zenodo token: {zen.token_hint(zenodo_sandbox)}")
            return 1, None

    # A bundle whose paper names a bibliography it does not ship (literature.bib
    # exported as refs.bib) cannot be compiled from the bundle; repoint it first.
    tex = b / "paper" / "paper.tex"
    if tex.is_file():
        text = tex.read_text(encoding="utf-8")
        fixed = point_bibliography(text, tex.parent)
        if fixed != text:
            tex.write_text(fixed, encoding="utf-8")
            _rehash(b, ["paper/paper.tex"])
            print("✓ Pointed paper.tex at the bibliography the bundle ships (refs.bib)")
    refs = b / "paper" / "refs.bib"
    if refs.is_file():
        raw = refs.read_text(encoding="utf-8")
        escaped = escape_bib(raw)
        if escaped != raw:
            refs.write_text(escaped, encoding="utf-8")
            _rehash(b, ["paper/refs.bib"])
            print("✓ Escaped & % # in refs.bib so the paper compiles")

    checks = _run_checks(b, online=False)
    verdict, rc = _verdict(checks)
    verification = [{"check": c.name, "status": c.status, "detail": c.detail} for c in checks]
    if rc != 0:
        print(verdict)
        print("error: the bundle does not verify; fix it before publishing")
        return 1, None

    contributor: dict[str, Any] = {k: v for k, v in {"name": name, "github": github, "orcid": orcid}.items() if v}
    if contributor:
        contributor["roles"] = roles or ["conceptualization", "investigation"]
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
    site_url = (site or os.environ.get("E2ER_URL") or "https://e2er.org").rstrip("/")
    zdeps: dict[str, Any] = {}
    if deposits and zenodo_plan_only:
        _print_deposit_plan(deposits, manifest, availability, zenodo_sandbox)
    elif deposits and token:
        # Reserve the DOIs first, so they go into the dossier; then describe each
        # deposit with the dossier's address and publish it.
        z = zen.Zenodo(token, base=zen.base_url(zenodo_sandbox))
        try:
            for item in deposits:
                zdeps[item] = z.create(reserve_doi=True)
                if zdeps[item].doi:
                    availability[item]["doi"] = zdeps[item].doi
                    availability[item].setdefault("url", f"https://doi.org/{zdeps[item].doi}")
        except zen.ZenodoError as e:
            print(f"error: {e}")
            return 1, None
    doc = build_dossier(manifest, db=Path(db).expanduser() if db else None, bundle=b, availability=availability)
    did = dossier_id(doc)
    if zdeps:
        try:
            for item, dep in zdeps.items():
                for name, data_bytes in deposits[item]["files"]:
                    z.upload(dep, name, data_bytes)
                z.describe(
                    dep,
                    _deposit_metadata(item, manifest, availability, dossier_url(did), f"{site_url}/{owner}/{project}"),
                )
                done = z.publish(dep)
                availability[item]["doi"] = done["doi"]
                availability[item]["zenodo"] = done["url"]
                print(f"✓ Deposited the {item} on Zenodo: doi {done['doi']}  {done['url']}")
        except zen.ZenodoError as e:
            print(f"error: {e}")
            print("  nothing else was written; unfinished deposits stay as drafts in your Zenodo account")
            return 1, None
    if stamp and name and (b / "paper" / "paper.tex").is_file():
        try:
            changed = _stamp_and_compile(b, name, did)
        except PublishError as e:
            print(f"error: {e}")
            return 1, None
        if changed:
            checks = _run_checks(b, online=False)
            verdict, rc = _verdict(checks)
            if rc != 0:
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
            print(f"✓ Stamped paper/paper.tex ({name} with e2er, dossier footnote) and updated provenance.json")
    manifest["availability"] = availability
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
    print(f"  availability: {describe_availability(availability)}")
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
    for item, v in (m.get("availability") or {}).items():
        if v.get("access") != "public":
            m["availability"][item] = {"access": "private"}  # a private item carries no address
    m = sanitize(m, bundle)
    return {"manifest": m, "dossier": {"id": d["id"], "doc": d["doc"]}, "repository": m.get("repository") or None}


def problems(body: dict[str, Any]) -> list[str]:
    """Why a request must not leave this machine."""
    out = [f"{path}: looks like a {kind}" for path, kind in find_secrets(body)]
    out += [f"{path}: names a local home directory" for path in find_local_paths(body)]
    return out


def publish(bundle: str, *, dry_run: bool = False, to_url: str | None = None, offline: bool = False, **kw: Any) -> int:
    """`e2er publish`: describe, stamp and verify; optionally rehearse (`dry_run`) or send (`to_url`).

    `offline` prepares the folder for publishing in the browser: it writes the
    dossier and e2er.json, makes no network request and names the next step.
    """
    b = Path(bundle).expanduser().resolve()
    if kw.get("data") is None and kw.get("code") is None and sys.stdin.isatty():
        kw["data"] = _ask("Are the study's data public or private?")
        kw["code"] = _ask("Is the study's code public or private?")
    if kw.get("zenodo") and offline:
        print("error: --offline makes no network request; leave out --zenodo")
        return 2
    if offline:
        if dry_run or to_url:
            print("error: --offline sends nothing; leave out --to and --dry-run")
            return 2
        code, manifest = _describe(str(b), **kw, remote=True)
        if code or manifest is None:
            return code or 1
        found = problems(request_body(manifest, b))
        if found:
            print("warning: e2er.json contains something that must not be published; the browser will refuse it:")
            for p in found:
                print(f"  {p}")
            return 1
        site = os.environ.get("E2ER_URL", "https://e2er.org").rstrip("/")
        print("\nNothing was sent. To publish from the browser:")
        print(f"  1. open {site}/publish and sign in")
        print(f"  2. choose this folder: {b}")
        print("  The page compares every file with its fingerprint in the browser and sends only the description.")
        return 0
    if dry_run or to_url:
        # Rehearse in a scratch copy: the exact request, and nothing written here.
        with tempfile.TemporaryDirectory() as tmp:
            scratch = Path(tmp) / b.name
            if (b / "provenance.json").is_file():
                shutil.copytree(b, scratch)
            log = io.StringIO()
            # The rehearsal never deposits: a dry run prints the plan, and --to
            # deposits once, from the bundle itself, after the rehearsal passed.
            rehearsal = {
                **kw,
                "out": str(Path(tmp) / "entry"),
                "zenodo": False,
                "zenodo_plan_only": bool(kw.get("zenodo")),
            }
            with contextlib.redirect_stdout(log):
                code, manifest = _describe(str(scratch), **rehearsal, remote=True)
            plan = [ln for ln in log.getvalue().splitlines() if ln.startswith(("zenodo", "note: --zenodo"))]
            if code or manifest is None:
                print(log.getvalue().rstrip())
                return code or 1
            body = request_body(manifest, scratch)
        found = problems(body)
        if dry_run:
            print(json.dumps(body, indent=2, ensure_ascii=False))
            if kw.get("zenodo"):
                print("\n".join(plan), file=sys.stderr)
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
    """Stamp paper.tex and recompile paper.pdf with tectonic when it is installed.

    The paper is pointed at the bibliography the bundle ships (refs.bib). A
    recompile that leaves any citation unresolved is refused: paper.tex is
    restored and paper.pdf keeps its previous version, so publish never ships
    a PDF whose references turned into "?".
    """
    tex = bundle / "paper" / "paper.tex"
    old = tex.read_text(encoding="utf-8")
    new = stamp_paper(point_bibliography(old, tex.parent), author, did)
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
            res = subprocess.run(
                ["tectonic", "--keep-intermediates", "paper.tex"], cwd=work, capture_output=True, text=True
            )
            missing = unresolved_citations(work) if res.returncode == 0 else []
            if res.returncode != 0 or missing:
                tex.write_text(old, encoding="utf-8")
                why = (
                    f"{len(missing)} citation(s) unresolved: {', '.join(missing[:5])}" if missing else "tectonic failed"
                )
                raise PublishError(f"recompiling paper.tex would break the PDF ({why}); nothing was changed")
            shutil.copyfile(work / "paper.pdf", tex.parent / "paper.pdf")
        rels.append("paper/paper.pdf")
    else:
        print("note: tectonic is not installed; paper.pdf was not recompiled (the footnote is in paper.tex)")
    _rehash(bundle, rels)
    return True


def _ask(question: str) -> str:
    """public or private, private unless the researcher types public."""
    try:
        answer = input(f"{question} [private/public, default private]: ").strip().lower()
    except EOFError:
        return "private"
    return "public" if answer in ("public", "p", "pub") else "private"


def _code_zip(bundle: Path, folders: tuple[str, ...] = ("code", "replication")) -> bytes:
    """The public code as one zip with fixed timestamps, so the same code gives the same file."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for folder in folders:
            root = bundle / folder
            if not root.is_dir():
                continue
            for f in sorted(p for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts):
                info = zipfile.ZipInfo(f.relative_to(bundle).as_posix(), date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                zf.writestr(info, f.read_bytes())
    return buf.getvalue()


def _deposit_plan(bundle: Path, availability: dict[str, Any], project: str) -> dict[str, Any]:
    """What --zenodo would deposit: the public data files one by one, the public code as one zip."""
    plan: dict[str, Any] = {}
    if availability["data"]["access"] == "public" and (bundle / "data").is_dir():
        files = [
            (f.relative_to(bundle / "data").as_posix().replace("/", "_"), f.read_bytes())
            for f in sorted((bundle / "data").rglob("*"))
            if f.is_file()
        ]
        if files:
            plan["data"] = {"files": files, "upload_type": "dataset"}
    if availability["code"]["access"] == "public":
        z = _code_zip(bundle)
        if len(z) > 22:  # an empty zip is 22 bytes
            plan["code"] = {"files": [(f"{project}-code.zip", z)], "upload_type": "software"}
    return plan


def _deposit_metadata(
    item: str, manifest: dict[str, Any], availability: dict[str, Any], dossier: str, study: str
) -> dict[str, Any]:
    title = manifest["title"]
    licence = zen.LICENCES.get(manifest.get("license") or "", "cc-by-4.0" if item == "data" else "mit")
    meta: dict[str, Any] = {
        "title": f"{title} ({item})",
        "upload_type": "dataset" if item == "data" else "software",
        "description": (
            f"The {item} of the study “{title}”, published with e2er. "
            f"The study and how it was produced: {study}. Its dossier: {dossier}."
        ),
        "creators": zen.creators(manifest.get("contributors") or []),
        "access_right": "open",
        "license": licence,
        "keywords": ["e2er"],
        "related_identifiers": [
            {"identifier": dossier, "relation": "isSupplementTo", "resource_type": "other"},
            {"identifier": study, "relation": "isSupplementTo", "resource_type": "publication"},
        ],
    }
    return meta


def _print_deposit_plan(
    deposits: dict[str, Any], manifest: dict[str, Any], availability: dict[str, Any], sandbox: bool
) -> None:
    where = "sandbox.zenodo.org" if sandbox else "zenodo.org"
    for item, d in deposits.items():
        size = sum(len(b) for _, b in d["files"])
        licence = zen.LICENCES.get(manifest.get("license") or "", "cc-by-4.0" if item == "data" else "mit")
        print(
            f"zenodo {item}: would deposit {len(d['files'])} file(s), {size:,} bytes, on {where} ({d['upload_type']})"
        )
        for name, b in d["files"]:
            print(f"zenodo   {name}  {len(b):,} bytes")
        print(f"zenodo   title: {manifest['title']} ({item}); licence: {licence}; creators and ORCID from the manifest")


__all__ = ["MANIFEST_NAME", "publish"]
