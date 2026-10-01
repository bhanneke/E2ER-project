"""``e2er publish <bundle>`` — describe an exported bundle as a research object.

Verifies the bundle offline, writes ``e2er.json`` into it, and writes the entry
to submit to the E2ER registry as a pull request. Nothing is uploaded: the
artifacts stay in your repository, the registry only records who made the
object, what it depends on and what verified.

    e2er publish ./my-bundle --owner bhanneke --project etf-comovement \\
        --github bhanneke --orcid 0009-0000-7466-9581 \\
        --repo https://github.com/bhanneke/E2ER-project --commit 3b91f0e --path examples/showcase

Before anything in the folder changes, publish checks that every file is
still the one provenance.json lists; a folder edited after export is refused.
Every change publish then makes (the bibliography repointed, the disclaimer,
refs.bib escaped, the dossier stamp, a recompiled PDF) is recorded in
provenance.json as an amendment: the file's exported fingerprint, its new
one and why, so the exported hash is never lost.

The dossier is built from the study's run database, which publish finds by
itself: ``--db``, else the database the study folder's settings name (the
first ``.env`` above the bundle, ``DATABASE_URL``, as the server reads it),
else the one of the current folder, else ``~/.e2er/papers.db``. It must hold
the run of the paper the folder was exported from; without one, publish
refuses. ``--no-db`` publishes anyway, with a dossier that says its workflow
is not recorded.

``--dry-run`` rehearses everything in a scratch copy of the bundle and prints
the exact request ``--to`` would send; nothing in the bundle changes and
nothing is sent. ``--to https://e2er.org`` (after ``e2er login``) publishes the
description, the dossier and the file fingerprints; the files stay here. A
request that contains anything resembling a key or token, or a local path, is
refused before it leaves the machine.
"""

from __future__ import annotations

import contextlib
import copy
import io
import json
import os
import shutil
import sqlite3
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
from .core.demonstration import PURPOSES, disclaimer, kind_for, mark_report, resolve_purpose
from .core.dossier import build_dossier, dossier_id, dossier_url, read_run, stamp_paper
from .core.research_object import MANIFEST_NAME, PublishError, build_manifest, write_manifest
from .core.secret_scan import find_local_paths, find_secrets, sanitize

REGISTRY = "https://github.com/bhanneke/e2er-site"
REGISTRY_DIR = "registry/objects"
ZENODO_RECORD = ".e2er/zenodo.json"


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── the run's database ───────────────────────────────────────────────────────


def _has_paper(db: Path, paper_id: str) -> bool:
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    except sqlite3.Error:
        return False
    try:
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if "pipeline_events" not in tables:
            return False
        return (
            con.execute("SELECT 1 FROM pipeline_events WHERE paper_id = ? LIMIT 1", (paper_id,)).fetchone() is not None
        )
    except sqlite3.Error:
        return False
    finally:
        con.close()


def _db_from_settings(env: Path | None) -> tuple[Path | None, str]:
    """The SQLite database a study folder's settings name (``DATABASE_URL``; empty: e2er's default)."""
    from .db.client import _sqlite_path

    url = ""
    if env is not None:
        from dotenv import dotenv_values

        url = str(dotenv_values(env).get("DATABASE_URL") or "").strip()
    elif os.environ.get("DATABASE_URL"):
        url = os.environ["DATABASE_URL"].strip()
    if url and not url.startswith("sqlite"):
        return None, f"{env or 'the environment'} names a Postgres database; publish reads the run's SQLite database"
    try:
        return Path(_sqlite_path(url)).expanduser(), ""
    except ValueError as e:
        return None, str(e)


def _study_folder(bundle: Path) -> Path | None:
    """The study folder a bundle was exported into: the first folder above it with e2er's settings (.env)."""
    return next((p for p in bundle.parents if (p / ".env").is_file()), None)


def find_run_db(bundle: Path, given: str | None, paper_id: str | None) -> tuple[Path | None, str]:
    """The run database of the paper the folder was exported from, or (None, why not).

    ``--db`` when given (it must hold the paper); else, as the server finds it,
    the study folder's settings (the first ``.env`` above the bundle), the
    current folder's, the environment's, and e2er's default
    (``~/.e2er/papers.db``). The first that holds the paper's run is used.
    """
    if not paper_id:
        return None, "provenance.json names no paper id, so the run's database cannot be found (export it again)"
    if given:
        db = Path(given).expanduser()
        if not db.is_file():
            return None, f"--db {db}: no such file"
        if not _has_paper(db, paper_id):
            return None, (
                f"--db {db} holds no run of paper {paper_id}, the one this folder was exported from: "
                "it is another study's database"
            )
        return db, ""
    tried: list[str] = []
    candidates: list[Path | None] = []
    folder = _study_folder(bundle)
    study_env = folder / ".env" if folder is not None else None
    if study_env is not None:
        candidates.append(study_env)
    if (Path.cwd() / ".env").is_file() and Path.cwd() / ".env" != study_env:
        candidates.append(Path.cwd() / ".env")
    candidates.append(None)  # the environment, else e2er's default
    for env in candidates:
        found, why = _db_from_settings(env)
        if found is None:
            tried.append(why)
            continue
        if found.is_file() and _has_paper(found, paper_id):
            return found, ""
        tried.append(f"{found} ({'no run of this paper' if found.is_file() else 'no such file'})")
    return None, (
        f"no run database with paper {paper_id} found (looked at: {'; '.join(dict.fromkeys(tried))}). "
        "Pass --db <the study's database>; or --no-db to publish without the run's steps"
    )


def _workspace_of(db: Path, paper_id: str) -> Path | None:
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            cols = {r[1] for r in con.execute("PRAGMA table_info(papers)")}
            if "workspace" not in cols:
                return None
            row = con.execute("SELECT workspace FROM papers WHERE id = ?", (paper_id,)).fetchone()
        finally:
            con.close()
    except sqlite3.Error:
        return None
    return Path(row[0]) if row and row[0] else None


def _purpose(flag: bool, prov: dict[str, Any], workspace: Path | None, folder: Path | None) -> str | None:
    """The study's purpose: the flag; else the one recorded on the study when it started (the
    export, then the run's workspace manifest); else E2ER_PURPOSE (environment, the study folder's .env)."""
    if flag:
        return resolve_purpose(True)
    recorded = (prov.get("run") or {}).get("purpose")
    if recorded in PURPOSES:
        return str(recorded)
    if workspace is not None and (workspace / "manifest.json").is_file():
        try:
            mine = json.loads((workspace / "manifest.json").read_text(encoding="utf-8")).get("purpose")
        except (OSError, ValueError, AttributeError):
            mine = None
        if mine in PURPOSES:
            return str(mine)
    # E2ER_PURPOSE: the environment, the study folder's .env, then the current folder's.
    found = resolve_purpose(False, folder)
    if found is None and folder is not None and Path.cwd() != folder:
        found = resolve_purpose(False, Path.cwd())
    return found


# ── changes to the folder, each one an amendment ─────────────────────────────


def _amend(bundle: Path, rel: str, reason: str, kind: str | None = None) -> dict[str, Any] | None:
    from .core.export.provenance import amend

    entry = amend(bundle, rel, reason, at=_now())
    if entry is not None and kind:
        prov_path = bundle / "provenance.json"
        prov = json.loads(prov_path.read_text(encoding="utf-8"))
        prov["amendments"][-1]["kind"] = kind
        from .core.export.provenance import dump

        prov_path.write_text(dump(prov), encoding="utf-8")
        entry["kind"] = kind
    return entry


def _rehash(bundle: Path, rels: list[str], reason: str = "changed by e2er publish") -> None:
    """Record ``rels`` as changed after export (amendments in provenance.json)."""
    for rel in rels:
        if (bundle / rel).is_file():
            _amend(bundle, rel, reason)


def _amendments_for_dossier(bundle: Path) -> list[dict[str, Any]]:
    """The amendments the dossier carries: all but the paper's stamp, which depends on the dossier."""
    prov = json.loads((bundle / "provenance.json").read_text(encoding="utf-8"))
    return [a for a in prov.get("amendments") or [] if a.get("kind") != "stamp"]


def _checks_while_publishing(b: Path) -> list[Any]:
    """verify's checks, minus the anchor: e2er.json (from an earlier publish) is about to be rewritten."""
    from .cli_verify import _run_checks

    return [c for c in _run_checks(b, online=False) if c.name != "anchor"]


def _folder_problems(b: Path) -> list[str]:
    """Why publish must not touch the folder: it no longer is what was exported (or published)."""
    from .cli_verify import FAIL, _check_anchor, _check_integrity

    return [f"{c.name}: {c.detail}" for c in (_check_integrity(b), _check_anchor(b)) if c.status == FAIL]


# ── Zenodo deposits, reused on a retry ───────────────────────────────────────


def _zenodo_record(b: Path) -> dict[str, Any]:
    p = b / ZENODO_RECORD
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_zenodo_record(b: Path, record: dict[str, Any]) -> None:
    p = b / ZENODO_RECORD
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")


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
    no_db: bool = False,
    template: str | None = None,
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
    demonstration: bool = False,
    study_folder: Path | None = None,
) -> tuple[int, dict[str, Any] | None]:
    from .cli_verify import _verdict

    b = Path(bundle).expanduser().resolve()
    if not (b / "provenance.json").is_file():
        print(f"error: {b} is not an exported bundle (no provenance.json); run `e2er export` first")
        return 1, None

    # 1. Nothing changes in a folder that is not what was exported (or last published).
    found = _folder_problems(b)
    if found:
        print("error: the folder is not what was exported; publish changes nothing in it:")
        for p in found:
            print(f"  {p}")
        print("  Export the study again, or undo the edits.")
        return 1, None
    prov = json.loads((b / "provenance.json").read_text(encoding="utf-8"))
    paper_id = (prov.get("run") or {}).get("paper_id")

    # 2. The run's database: the dossier's workflow comes from it.
    run_db: Path | None = None
    run_record = None
    if no_db:
        print(
            "WARNING: --no-db: publishing WITHOUT the run's database. The dossier will not list the steps of the "
            "run, the commit it ran on or the researcher's actions, and says so."
        )
    else:
        run_db, why = find_run_db(b, db, paper_id)
        if run_db is None:
            print(f"error: {why}")
            return 1, None
        assert paper_id is not None
        run_record = read_run(run_db, paper_id, prov.get("files") or {})
        if not run_record.recorded:
            print(f"error: the database {run_db} holds no recorded steps for paper {paper_id}")
            return 1, None
        print(f"note: the run's steps are read from {run_db} (paper {paper_id})")

    template, why = resolve_template(b, template)
    if template is None:
        print(f"error: {why}")
        return 1, None
    if why:
        print(f"note: {why}")

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
    # A demonstration study (--demonstration, the purpose recorded on the study, or
    # E2ER_PURPOSE in the environment or the study folder's .env) says so in
    # e2er.json, the dossier, the paper's first page and the reproduction report.
    if study_folder is None:
        study_folder = _study_folder(b)
    workspace = _workspace_of(run_db, paper_id) if run_db is not None and paper_id else None
    try:
        purpose = _purpose(demonstration, prov, workspace, study_folder)
    except ValueError as e:
        print(f"error: {e}")
        return 1, None
    kind = kind_for(template) if purpose else None
    if purpose and not stamp:
        print("error: a demonstration study's paper must carry the disclaimer; leave out --no-stamp")
        return 1, None
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

    # 3. Changes, each recorded as an amendment (the exported fingerprint is kept).
    tex = b / "paper" / "paper.tex"
    if tex.is_file():
        text = tex.read_text(encoding="utf-8")
        fixed = point_bibliography(text, tex.parent)
        if fixed != text:
            tex.write_text(fixed, encoding="utf-8")
            _amend(b, "paper/paper.tex", "pointed at the bibliography the bundle ships (refs.bib)")
            print("✓ Pointed paper.tex at the bibliography the bundle ships (refs.bib)")
    for report in (b / "reproduction_report.md", b / "misc" / "reproduction_report.md"):
        if report.is_file() and mark_report(report, kind, purpose=purpose):
            rel = report.relative_to(b).as_posix()
            what = "put the demonstration disclaimer at the top" if purpose else "removed the demonstration disclaimer"
            _amend(b, rel, what)
            print(f"✓ {what[0].upper()}{what[1:]} of {rel}")
    refs = b / "paper" / "refs.bib"
    if refs.is_file():
        raw = refs.read_text(encoding="utf-8")
        escaped = escape_bib(raw)
        if escaped != raw:
            refs.write_text(escaped, encoding="utf-8")
            _amend(b, "paper/refs.bib", "escaped & % # so the paper compiles")
            print("✓ Escaped & % # in refs.bib so the paper compiles")

    checks = _checks_while_publishing(b)
    verdict, rc = _verdict(checks)
    if rc != 0:
        print(verdict)
        print("error: the bundle does not verify; fix it before publishing")
        return 1, None

    contributor: dict[str, Any] = {k: v for k, v in {"name": name, "github": github, "orcid": orcid}.items() if v}
    if contributor:
        contributor["roles"] = roles or ["conceptualization", "investigation"]
    # Without the run, the template file declares the agents (today's file, said to be declared).
    template_file = Path(__file__).resolve().parents[1] / "pipelines" / f"{template}.toml"

    def manifest_now(verification: list[dict[str, str]]) -> dict[str, Any]:
        m = build_manifest(
            b,
            owner=owner,
            project=project,
            contributors=[contributor] if contributor else [],
            repository=repository,
            db=run_db,
            template=template,
            template_file=template_file,
            license_id=license_id,
            derived_from=derived_from,
            verification=verification,
            run_record=run_record,
        )
        _declare(m, purpose, kind)
        return m

    try:
        manifest = manifest_now([{"check": c.name, "status": c.status, "detail": c.detail} for c in checks])
    except PublishError as e:
        print(f"error: {e}")
        return 1, None

    # 4. Zenodo, reversible part: reserve the DOIs (drafts), reusing the deposits
    # an earlier attempt for this folder reserved or published.
    site_url = (site or os.environ.get("E2ER_URL") or "https://e2er.org").rstrip("/")
    zrec = _zenodo_record(b)
    if zrec and zrec.get("sandbox") != bool(zenodo_sandbox):
        zrec = {}
    z = zen.Zenodo(token, base=zen.base_url(zenodo_sandbox)) if deposits and token else None
    if deposits and zenodo_plan_only:
        _print_deposit_plan(deposits, manifest, availability, zenodo_sandbox)
    if deposits:
        zrec.setdefault("sandbox", bool(zenodo_sandbox))
        reserved = zrec.setdefault("deposits", {})
        try:
            for item in deposits:
                if item not in reserved and z is not None:
                    dep = z.create(reserve_doi=True)
                    reserved[item] = {"id": dep.id, "bucket": dep.bucket, "doi": dep.doi, "state": "draft"}
                    _save_zenodo_record(b, zrec)
                got = reserved.get(item)
                if got and got.get("doi"):
                    availability[item]["doi"] = got["doi"]
                    availability[item].setdefault("url", f"https://doi.org/{got['doi']}")
                    availability[item]["zenodo"] = (
                        got.get("record") or f"{zen.base_url(zenodo_sandbox)}/records/{got['id']}"
                    )
        except zen.ZenodoError as e:
            print(f"error: {e}")
            return 1, None

    # 5. The dossier, from the final availability (a copy: nothing changes it afterwards).
    manifest["amendments"] = _amendments_for_dossier(b)
    doc = build_dossier(manifest, db=run_db, bundle=b, availability=copy.deepcopy(availability), run=run_record)
    del manifest["amendments"]
    leaks = find_local_paths(doc)
    if leaks:
        print("error: the dossier names a path on this machine; nothing was written:")
        for p in leaks[:10]:
            print(f"  {p}")
        return 1, None
    did = dossier_id(doc)

    # 6. The paper's first page: the dossier link (and the disclaimer); the author line with --name.
    if stamp and tex.is_file():
        try:
            changed = _stamp_and_compile(b, name, did, purpose=purpose, kind=kind, doc=doc)
        except PublishError as e:
            print(f"error: {e}")
            return 1, None
        if changed:
            checks = _checks_while_publishing(b)
            verdict, rc = _verdict(checks)
            if rc != 0:
                print(verdict)
                print("error: the bundle no longer verifies after stamping the paper")
                return 1, None
            extra = ", demonstration footnote" if purpose else ""
            who = f"{name} with e2er, " if name else ""
            print(f"✓ Stamped paper/paper.tex ({who}dossier footnote{extra}) and recorded it in provenance.json")
    elif not stamp:
        print("note: --no-stamp: the paper does not carry the dossier link")
    manifest = manifest_now([{"check": c.name, "status": c.status, "detail": c.detail} for c in checks])
    manifest["availability"] = copy.deepcopy(availability)
    amendments = json.loads((b / "provenance.json").read_text(encoding="utf-8")).get("amendments") or []
    if amendments:
        manifest["amendments"] = amendments
    manifest["dossier"] = {"id": did, "url": dossier_url(did), "doc": doc}
    leaks = problems(request_body(manifest, b))
    if leaks:
        print("error: the description would carry something that must not leave this machine; nothing was written:")
        for p in leaks:
            print(f"  {p}")
        return 1, None

    # 7. Zenodo, irreversible part: last, after everything that can fail.
    if deposits and z is not None:
        try:
            for item in deposits:
                rec = zrec["deposits"][item]
                if rec.get("state") == "published":
                    continue
                dep = zen.Deposit(id=rec["id"], bucket=rec["bucket"], doi=rec.get("doi"))
                for fname, data_bytes in deposits[item]["files"]:
                    z.upload(dep, fname, data_bytes)
                z.describe(
                    dep,
                    _deposit_metadata(item, manifest, availability, dossier_url(did), f"{site_url}/{owner}/{project}"),
                )
                done = z.publish(dep)
                rec.update(state="published", published_url=done.get("url"))
                _save_zenodo_record(b, zrec)
                if rec.get("doi") and done.get("doi") and done["doi"] != rec["doi"]:
                    print(f"warning: Zenodo published the {item} as doi {done['doi']}, not the reserved {rec['doi']}")
                print(f"✓ Deposited the {item} on Zenodo: doi {rec.get('doi')}  {done.get('url')}")
        except zen.ZenodoError as e:
            print(f"error: {e}")
            print(
                "  e2er.json was not written; the deposits stay as drafts in your Zenodo account and the next "
                f"publish reuses them ({ZENODO_RECORD})"
            )
            return 1, None

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
    steps = len(doc.get("workflow") or [])
    researcher = sum(1 for s in doc.get("workflow") or [] if s.get("type") == "researcher")
    print(f"✓ Dossier {did[:23]}…  {dossier_url(did)}  ({steps} steps, {researcher} researcher actions)")
    print(f"  availability: {describe_availability(availability)}")
    if purpose:
        print(f"  purpose: {purpose}{f' ({kind})' if kind else ''}: {disclaimer(kind)}")
    if entry:
        print(f"✓ Registry entry: {entry}")
    if not repository.get("commit"):
        print("  note: no --commit given; the registry can only verify an object pinned to a commit")
    if not remote:
        print(
            f"\nTo publish, open a pull request against {REGISTRY} that adds\n  {REGISTRY_DIR}/{owner}/{project}.json"
        )
    return 0, manifest


DEFAULT_TEMPLATE = "empirical"


def recorded_template(bundle: Path) -> str | None:
    """The template the export recorded (provenance.json → run.template), or None for an older export."""
    try:
        prov = json.loads((bundle / "provenance.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    run = prov.get("run") if isinstance(prov, dict) else None
    value = run.get("template") if isinstance(run, dict) else None
    return value if isinstance(value, str) and value else None


def resolve_template(bundle: Path, given: str | None) -> tuple[str | None, str]:
    """The template to publish under, and a note (or, with None, the reason to refuse).

    The export records the template the study ran with; ``--template`` may only
    repeat it. A bundle exported before the template was recorded takes
    ``--template``, else the default, and says so.
    """
    recorded = recorded_template(bundle)
    if recorded and given and given != recorded:
        return None, (
            f"--template {given} does not match the template this study was run with, {recorded} "
            "(recorded in provenance.json at export); leave out --template"
        )
    if recorded:
        return recorded, ""
    if given:
        return given, ""
    return DEFAULT_TEMPLATE, (
        f"the export records no template (exported before e2er recorded it); publishing as {DEFAULT_TEMPLATE}. "
        "Pass --template, or export again"
    )


def _declare(manifest: dict[str, Any], purpose: str | None, kind: str | None) -> None:
    """Record the study's purpose (and kind) in the manifest; nothing when it has none."""
    if purpose:
        manifest["purpose"] = purpose
        if kind:
            manifest["kind"] = kind


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
    # The run's database and the study folder belong to the real folder: found here, so the
    # rehearsal in a scratch copy (somewhere else on disk) uses the same ones.
    if (b / "provenance.json").is_file() and not kw.get("no_db"):
        try:
            paper_id = (json.loads((b / "provenance.json").read_text(encoding="utf-8")).get("run") or {}).get(
                "paper_id"
            )
        except (OSError, ValueError, AttributeError):
            paper_id = None
        run_db, _why = find_run_db(b, kw.get("db"), paper_id)
        if run_db is not None:
            kw["db"] = str(run_db)
    kw.setdefault("study_folder", _study_folder(b))
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
        print(f"error: {pc.error_text(code, resp)}")
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


def _stamp_and_compile(
    bundle: Path,
    author: str | None,
    did: str,
    *,
    purpose: str | None = None,
    kind: str | None = None,
    doc: dict[str, Any] | None = None,
) -> bool:
    """Stamp paper.tex and recompile paper.pdf with tectonic when it is installed.

    The paper is pointed at the bibliography the bundle ships (refs.bib). A
    recompile that leaves any citation unresolved is refused: paper.tex is
    restored and paper.pdf keeps its previous version, so publish never ships
    a PDF whose references turned into "?". Both files are recorded as
    amendments (``kind: "stamp"``); a PDF the export did not have is added.
    """
    tex = bundle / "paper" / "paper.tex"
    old = tex.read_text(encoding="utf-8")
    new = stamp_paper(point_bibliography(old, tex.parent), author, did, purpose=purpose, kind=kind, doc=doc)
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
            (work / "paper.pdf").unlink(missing_ok=True)  # only a PDF this compile writes counts
            # As the run compiled it (renderer/compiler.py): tectonic continues past
            # non-fatal errors (a package option xetex ignores, a missing figure).
            subprocess.run(
                ["tectonic", "--keep-intermediates", "-Z", "continue-on-errors", "paper.tex"],
                cwd=work,
                capture_output=True,
                text=True,
            )
            produced = (work / "paper.pdf").is_file()
            missing = unresolved_citations(work) if produced else []
            if not produced or missing:
                tex.write_text(old, encoding="utf-8")
                why = (
                    f"{len(missing)} citation(s) unresolved: {', '.join(missing[:5])}" if missing else "tectonic failed"
                )
                raise PublishError(f"recompiling paper.tex would break the PDF ({why}); nothing was changed")
            shutil.copyfile(work / "paper.pdf", tex.parent / "paper.pdf")
        rels.append("paper/paper.pdf")
    else:
        print("note: tectonic is not installed; paper.pdf was not recompiled (the footnote is in paper.tex)")
    for rel in rels:
        what = "stamped with the dossier link" if rel.endswith(".tex") else "recompiled with the dossier link"
        _amend(bundle, rel, what, kind="stamp")
    return True


def _ask(question: str) -> str:
    """public or private, private unless the researcher types public."""
    try:
        answer = input(f"{question} [private/public, default private]: ").strip().lower()
    except EOFError:
        return "private"
    return "public" if answer in ("public", "p", "pub") else "private"


def _listed(bundle: Path, folder: str) -> list[str]:
    """The files under ``folder`` that provenance.json fingerprints: what a deposit may contain.

    Never a file the folder merely holds (an operating system's .DS_Store, a
    file added later): only the ones the bundle vouches for.
    """
    try:
        files = json.loads((bundle / "provenance.json").read_text(encoding="utf-8")).get("files") or {}
    except (OSError, ValueError):
        return []
    return sorted(rel for rel in files if rel.startswith(f"{folder}/") and (bundle / rel).is_file())


def _code_zip(bundle: Path, folders: tuple[str, ...] = ("code", "replication")) -> bytes:
    """The public code as one zip with fixed timestamps, so the same code gives the same file."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for folder in folders:
            for rel in _listed(bundle, folder):
                if "__pycache__" in rel.split("/"):
                    continue
                f = bundle / rel
                info = zipfile.ZipInfo(rel, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                zf.writestr(info, f.read_bytes())
    return buf.getvalue()


def _deposit_plan(bundle: Path, availability: dict[str, Any], project: str) -> dict[str, Any]:
    """What --zenodo would deposit: the public data files one by one, the public code as one zip."""
    plan: dict[str, Any] = {}
    if availability["data"]["access"] == "public" and (bundle / "data").is_dir():
        files = [
            (rel.removeprefix("data/").replace("/", "_"), (bundle / rel).read_bytes())
            for rel in _listed(bundle, "data")
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
