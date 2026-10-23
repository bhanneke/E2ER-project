"""``e2er verify <bundle>`` — offline, keyless verification of an export bundle.

The reviewer's cheap-verification moment (make verification cheap): given a
bundle produced by ``e2er export``, re-establish that it is internally
consistent and untampered — in seconds, with no API keys and, by default, no
network at all:

  1. integrity   — re-hash every file against provenance.json (SHA-256, size);
                   nothing unlisted, no symbolic link, no ambiguous entry; the
                   derivation edges recomputed; publish-time amendments chained
  2. anchor      — e2er.json and .e2er/link.json (once published) describe this
                   folder: content id = SHA-256 of provenance.json, the dossier
                   hashes to its id, the published fingerprints are the listed ones
  3. numbers     — every table cell is a source value at the precision shown
  4. tables      — the rendered tables re-render byte for byte from the sidecars
  5. spec        — re-check the estimation implements the declared identification
  6. citations   — every \\cite resolves in refs.bib (registry status is read
                   from the bundled snapshot; ``--online`` re-queries live)
  7. results from code — each results file is the output the last run of the
                   study's script wrote, with the script as the folder ships it
                   (the run's script log, recorded in provenance.json)

The numbers check also recomputes, for every coefficient in the result files,
t from estimate / se and the p-value from t (``pipeline/statistics.py``).
Two checks run only when the bundle has what they check:

  * preregistration — the plan files match the frozen fingerprints, every
                      pre-registered hypothesis has a result, and the headline
                      sample is the registered one or its exclusions are declared
  * reproduction    — a replication bundle: every compared number is re-read
                      from the exported run outputs (``sandbox/run/``) and
                      relabelled with the pipeline's own reproduction check

A check whose input is missing is SKIPped with its reason, never passed;
a check the study's own record requires (the replication template's
reproduction, a frozen pre-registration) FAILs when its input is missing.

The checks never touch the network. ``--online`` adds a live registry
re-verification of the citations. Recomputation is authoritative: the bundled
reports are compared against a fresh computation, so an edited report or an
edited paper is caught.

Everything in the folder can be rewritten consistently by whoever holds it,
provenance.json and e2er.json included. ``--against <e2er.org address>``
compares the folder with what e2er.org published (GET only): the one anchor
outside the folder. Without it, verify says it verified against the folder only.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"

_CHUNK = 65536


@dataclass
class Check:
    name: str
    status: str
    detail: str = ""


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


# ── check 1: integrity ───────────────────────────────────────────────────────


def _load_provenance(bundle: Path) -> tuple[dict[str, Any] | None, str | None]:
    """provenance.json, or why it cannot serve as the inventory (unreadable, ambiguous, malformed)."""
    from .core.export.bundle_files import load_json_strict, provenance_problems

    prov, why = load_json_strict(bundle / "provenance.json")
    if why:
        return None, why
    problems = provenance_problems(prov)
    if problems:
        more = f"; and {len(problems) - 3} more" if len(problems) > 3 else ""
        return None, "provenance.json cannot serve as the inventory: " + "; ".join(problems[:3]) + more
    return prov, None


def _check_integrity(bundle: Path, package_left_out: dict[str, dict[str, Any]] | None = None) -> Check:
    """Every file against provenance.json: listed, same bytes, same size; nothing else; no links.

    The folder is walked without following links (bundle_files.walk); only the
    root-level provenance.json, e2er.json and .e2er/ records are exempt, by
    path (the anchor check compares them with provenance.json). Operating-
    system clutter (.DS_Store, Thumbs.db, ._*) is ignored and named.
    """
    from .core.export.bundle_files import not_evidence, walk
    from .core.export.package import supported_left_out

    prov, why = _load_provenance(bundle)
    if prov is None:
        return Check("integrity", FAIL, why or "no valid provenance.json in bundle")
    files: dict[str, dict[str, Any]] = prov["files"]
    listing = walk(bundle)
    on_disk = {rel: p for rel, p in listing.files.items() if not not_evidence(rel)}
    # Data files a .e2er package left out (a source's terms, too large for GitHub). A declaration in
    # e2er-package.json, in a package verify opened or in a folder, counts only for a file the study's own
    # records say a source's terms keep out, or that provenance.json records as larger than the host takes
    # (--no-data is the packer's choice, not a record of the study's).
    declared = package_left_out if package_left_out is not None else supported_left_out(bundle)
    missing: list[str] = []
    mismatched: list[str] = []
    resized: list[str] = []
    left_out: list[str] = []
    for rel, meta in files.items():
        p = on_disk.get(rel)
        if p is None:
            (left_out if rel in declared else missing).append(rel)
            continue
        if p.stat().st_size != meta["bytes"]:
            resized.append(rel)
        if _sha256(p) != meta["sha256"]:
            mismatched.append(rel)
    extra = sorted(set(on_disk) - set(files))
    bits = []
    if listing.symlinks:
        bits.append(
            f"{len(listing.symlinks)} symbolic link(s) ({', '.join(listing.symlinks[:3])}): a bundle holds copies, "
            "and verify never follows a link"
        )
    if listing.special:
        bits.append(f"{len(listing.special)} special file(s) ({', '.join(listing.special[:3])})")
    if listing.collisions:
        bits.append(f"names that differ only in Unicode normalisation ({', '.join(listing.collisions[:3])})")
    if mismatched:
        bits.append(f"{len(mismatched)} modified ({', '.join(mismatched[:3])})")
    if resized and set(resized) - set(mismatched):
        odd = sorted(set(resized) - set(mismatched))
        bits.append(f"{len(odd)} with a size other than provenance.json lists ({', '.join(odd[:3])})")
    if missing:
        from .core.export.package import declared_left_out

        claimed = declared_left_out(bundle)
        unsupported = [rel for rel in missing if rel in claimed]
        if unsupported:
            reasons = sorted({str(claimed[rel].get("reason") or "no reason") for rel in unsupported})
            bits.append(
                f"{len(unsupported)} missing ({', '.join(unsupported[:3])}), declared left out by e2er-package.json "
                f"({'; '.join(reasons[:2])}) without support in the study's records (no source's terms keep them "
                "out, and provenance.json does not record them larger than the host takes): the checks cannot see "
                "them, so the folder is not verified"
            )
        rest = [rel for rel in missing if rel not in claimed]
        if rest:
            bits.append(f"{len(rest)} missing ({', '.join(rest[:3])})")
    if "report.html" in extra:
        extra.remove("report.html")
        bits.append(
            "report.html is not fingerprinted (exported before e2er fingerprinted it), so nothing vouches "
            "for what it shows: delete it, or export again"
        )
    if extra:
        bits.append(f"{len(extra)} unlisted ({', '.join(extra[:3])})")
    if not bits:
        from .core.dossier import canonical
        from .core.export.provenance import _edges

        recorded = prov.get("edges", [])
        if canonical(recorded) != canonical(_edges(bundle, set(left_out))):
            bits.append(
                "the derivation edges in provenance.json are not the ones the bundle's own reports give "
                "(table cells, citations, figures, estimation, data): provenance.json was edited"
            )
        bits += _amendment_problems(prov)
        bits += _redaction_problems(bundle, prov)
    if bits:
        return Check("integrity", FAIL, "; ".join(bits))
    if _bundle_has_rendered_tables(bundle) and not _table_cell_edges(prov):
        # Hashes prove nothing was modified; they say nothing about whether the
        # derivation graph was ever populated. A bundle that ships rendered
        # tables and records no cell→source edge asserts a provenance claim it
        # cannot support.
        return Check(
            "integrity",
            FAIL,
            f"{len(files)} files hash-verified, but provenance records no table_cell "
            "edges while the paper ships rendered tables — the derivation graph is empty",
        )
    notes = ""
    if left_out:
        shown = ", ".join(sorted(left_out)[:3]) + (f" and {len(left_out) - 3} more" if len(left_out) > 3 else "")
        notes += (
            f"; {len(left_out)} data file(s) left out of the package ({shown}): "
            f"{declared[sorted(left_out)[0]].get('reason')}"
        )
    amendments = prov.get("amendments") or []
    if amendments:
        paths = sorted({a["path"] for a in amendments})
        notes += f"; {len(amendments)} change(s) after export recorded as amendments ({', '.join(paths[:3])})"
    rewritten = sorted({a["path"] for a in amendments if a.get("kind") == "abstract_rewritten"})
    if rewritten:
        notes += f"; the abstract rewritten after export by e2er's abstract step ({', '.join(rewritten[:4])})"
    edited = sorted({a["path"] for a in amendments if a.get("kind") == "abstract_edited_by_researcher"})
    if edited:
        notes += f"; the abstract edited by the researcher after export ({', '.join(edited[:4])})"
    redacted = sorted({a["path"] for a in amendments if a.get("kind") == "redacted"})
    if redacted:
        notes += (
            f"; {len(redacted)} file(s) recorded as redacted by the researcher ({', '.join(redacted[:3])}): the "
            "records match the files; what was taken out is not in the folder (personal contact details, the "
            "records say)"
        )
    if listing.junk:
        notes += (
            f"; ignored {len(listing.junk)} operating-system file(s) ({', '.join(listing.junk[:3])}), "
            "which are never part of a bundle"
        )
    return Check(
        "integrity",
        PASS,
        f"{len(files) - len(left_out)} files hash-verified against provenance.json; "
        f"{_table_cell_edges(prov)} table cell(s) traced in the derivation graph{notes}",
    )


def _amendment_problems(prov: dict[str, Any]) -> list[str]:
    """Each file changed after export (``e2er publish``) keeps a chain from its exported fingerprint.

    Per path, the amendments must link up (each ``sha256_before`` is the
    previous ``sha256_after``) and end at the fingerprint the file has now.
    """
    from .core.abstract import AMENDMENT_KINDS, CHANGED_FILES

    out: list[str] = []
    last: dict[str, str | None] = {}
    for a in prov.get("amendments") or []:
        path, before, after = a.get("path"), a.get("sha256_before"), a.get("sha256_after")
        if not isinstance(path, str) or not isinstance(after, str):
            out.append("an amendment in provenance.json names no file or no new fingerprint")
            continue
        if a.get("kind") in AMENDMENT_KINDS and path not in CHANGED_FILES:
            # e2er abstract changes the abstract, the paper, its PDF and report.html: nothing else.
            out.append(f"{path}: recorded as an abstract amendment, but e2er abstract never changes that file")
        if path in last and last[path] != before:
            out.append(f"the amendments of {path} do not link up")
        last[path] = after
    for path, after in last.items():
        if (prov["files"].get(path) or {}).get("sha256") != after:
            out.append(f"{path}: its last amendment is not the fingerprint provenance.json lists")
    return out


def _redaction_problems(bundle: Path, prov: dict[str, Any]) -> list[str]:
    """A redaction recorded as a file's last change must match the file: the replacement at every offset.

    An abstract amendment of paper/paper.tex recorded as its last change must too: rebuilt with the
    recorded old abstract, the paper is the one before, unchanged outside the abstract.
    """
    from .core import abstract as ab
    from .core import redact as rd

    last: dict[str, dict[str, Any]] = {}
    for a in prov.get("amendments") or []:
        if isinstance(a, dict) and isinstance(a.get("path"), str):
            last[a["path"]] = a
    from .core import anonymise as an

    out = []
    for path, a in last.items():
        if a.get("kind") in ab.AMENDMENT_KINDS and path == ab.PAPER_FILE and "abstract_before" in a:
            f = bundle / path
            why, _before = ab.paper_problem(a, f.read_bytes() if f.is_file() else None)
            if why:
                out.append(why)
            continue
        if a.get("kind") not in (rd.KIND, an.KIND):
            continue
        f = bundle / path
        check = rd.record_problem if a.get("kind") == rd.KIND else an.record_problem
        why = check(a, f.read_bytes() if f.is_file() else None)
        if why:
            out.append(why)
    return out


def _table_cell_edges(prov: dict) -> int:
    edges = prov.get("edges")
    if not isinstance(edges, list):
        return 0
    return sum(1 for e in edges if isinstance(e, dict) and e.get("type") == "table_cell")


# ── the anchor: e2er.json and .e2er/link.json against provenance.json ────────


def _content_id(bundle: Path) -> str | None:
    prov = bundle / "provenance.json"
    return f"sha256:{_sha256(prov)}" if prov.is_file() else None


def _fingerprint_problems(entries: Any, files: dict[str, Any], where: str) -> list[str]:
    """Paths in e2er.json or the dossier whose fingerprint is not the one provenance.json lists."""
    if entries is None:
        return []
    if not isinstance(entries, list):
        return [f"{where} is not a list"]
    out = []
    for e in entries:
        if not isinstance(e, dict) or not isinstance(e.get("path"), str):
            out.append(f"{where} has an entry without a path")
            continue
        listed = files.get(e["path"])
        if listed is None:
            out.append(f"{where} names {e['path']}, which provenance.json does not list")
        elif str(e.get("sha256", "")).removeprefix("sha256:") != listed["sha256"]:
            out.append(f"{where} gives {e['path']} another fingerprint than provenance.json")
        elif "bytes" in e and e["bytes"] != listed["bytes"]:
            out.append(f"{where} gives {e['path']} another size than provenance.json")
    return out


def _availability_problems(av: Any, where: str) -> list[str]:
    from .core.availability import ACCESS, ITEMS

    if av is None:
        return []
    if not isinstance(av, dict) or set(av) - set(ITEMS):
        return [f"{where} is not an object of data and code"]
    out = []
    for item, v in av.items():
        if not isinstance(v, dict) or v.get("access") not in ACCESS:
            out.append(f"{where}.{item} has no access (public or private)")
    return out


def _manifest_problems(manifest: Any, prov: dict[str, Any] | None, content_id: str | None) -> list[str]:
    """e2er.json against provenance.json and against its own dossier."""
    from .core.availability import any_public
    from .core.dossier import CanonicalError, dossier_id

    if not isinstance(manifest, dict):
        return ["e2er.json is not a JSON object"]
    out: list[str] = []
    if manifest.get("content_id") != content_id:
        out.append(
            f"e2er.json describes the content {str(manifest.get('content_id'))[:19]}…, but provenance.json is "
            f"{str(content_id)[:19]}…: the folder changed after it was published, or e2er.json was edited"
        )
    files = (prov or {}).get("files") or {}
    out += _fingerprint_problems(manifest.get("data"), files, "e2er.json data")
    out += _fingerprint_problems(manifest.get("outputs"), files, "e2er.json outputs")
    out += _availability_problems(manifest.get("availability"), "e2er.json availability")
    dossier = manifest.get("dossier")
    if dossier is None:
        return out
    if not isinstance(dossier, dict) or not isinstance(dossier.get("doc"), dict):
        return [*out, "e2er.json's dossier has no document"]
    doc = dossier["doc"]
    try:
        real = dossier_id(doc)
    except CanonicalError as e:
        return [*out, f"e2er.json's dossier has no canonical form: {e}"]
    if dossier.get("id") != real:
        out.append(
            f"e2er.json's dossier does not hash to its id ({str(dossier.get('id'))[:23]}… named, {real[:23]}… computed)"
        )
    out += _fingerprint_problems(doc.get("data"), files, "the dossier's data")
    if (doc.get("study") or {}).get("title") != manifest.get("title"):
        out.append("e2er.json's title is not the dossier's")
    for key in ("purpose", "kind"):
        if manifest.get(key) != doc.get(key):
            out.append(f"e2er.json's {key} is not the dossier's")
    out += _availability_problems(doc.get("availability"), "the dossier's availability")
    av = manifest.get("availability")
    if doc.get("availability") is not None:
        if av != doc["availability"]:
            out.append("e2er.json's availability is not the dossier's")
    elif not _availability_problems(av, "") and any_public(av):
        out.append("e2er.json states public data or code, the dossier does not")
    return out


def _check_anchor(bundle: Path) -> Check:
    """e2er.json and .e2er/link.json, when present, must describe exactly this folder.

    ``content_id`` is the SHA-256 of provenance.json, which fixes every other
    file; the dossier must hash to its id; the fingerprints e2er.json and the
    dossier publish must be provenance.json's. This ties the folder to its own
    published description. It is not an outside anchor: whoever can edit the
    folder can rewrite all three files. Only ``--against`` compares with what
    e2er.org holds.
    """
    from .core.export.bundle_files import load_json_strict

    e2er_path, link_path = bundle / "e2er.json", bundle / ".e2er" / "link.json"
    if not e2er_path.exists() and not link_path.exists():
        return Check("anchor", SKIP, "no e2er.json (not published): verified against the folder only")
    content_id = _content_id(bundle)
    prov, _ = _load_provenance(bundle)
    problems: list[str] = []
    manifest: Any = None
    later = ""
    if e2er_path.exists():
        manifest, why = load_json_strict(e2er_path)
        problems += [why] if why else _manifest_problems(manifest, prov, content_id)
    else:
        problems.append("e2er.json is missing, although .e2er/link.json says the folder was published")
    if link_path.exists():
        link, why = load_json_strict(link_path)
        if why:
            problems.append(why)
        elif not isinstance(link, dict):
            problems.append(".e2er/link.json is not a JSON object")
        else:
            named = ((manifest or {}).get("dossier") or {}).get("id") if isinstance(manifest, dict) else None
            here = link.get("described_here")
            if (
                named
                and isinstance(here, dict)
                and here.get("content_id") == content_id
                and here.get("dossier_id") == named
            ):
                # Described again after the version on the platform (a publish without --to, or a send that
                # failed): the link names that version and records the description e2er.json now holds.
                later = (
                    f"; e2er.json describes it again since version {link.get('version')} on {link.get('platform_url')}"
                )
            else:
                if link.get("content_id") != content_id:
                    problems.append(".e2er/link.json names another content than provenance.json")
                if link.get("dossier_id") != named:
                    problems.append(".e2er/link.json names another dossier than e2er.json")
    if problems:
        before = _anchor_before_redactions(bundle)
        if before is not None:
            return before
        more = f"; and {len(problems) - 4} more" if len(problems) > 4 else ""
        return Check("anchor", FAIL, "; ".join(problems[:4]) + more)
    has_link = " and .e2er/link.json" if link_path.exists() else ""
    return Check(
        "anchor",
        PASS,
        f"e2er.json{has_link} describe this folder (content {str(content_id)[:19]}…) and the dossier hashes to its id"
        f"{later}",
    )


def _anchor_before_redactions(bundle: Path) -> Check | None:
    """The anchor of a published folder the researcher redacted afterwards (`e2er redact`), or None.

    e2er.json names the content as published; the redactions since (the last amendments, each matching its
    file: the integrity check) changed provenance.json. Rolled back, provenance.json must be exactly the
    published one, and e2er.json and .e2er/link.json must describe it.
    """
    from .core import redact as rd

    texts, n, why = rd.rollback(bundle)
    if not texts:
        if why:
            return Check(
                "anchor",
                FAIL,
                "e2er.json describes the folder before its latest amendments, and they cannot be checked: " + why,
            )
        return None
    for text in texts:
        with tempfile.TemporaryDirectory() as td:
            scratch = Path(td)
            (scratch / "provenance.json").write_text(text, encoding="utf-8")
            if (bundle / "e2er.json").is_file():
                shutil.copy2(bundle / "e2er.json", scratch / "e2er.json")
            if (bundle / ".e2er" / "link.json").is_file():
                (scratch / ".e2er").mkdir()
                shutil.copy2(bundle / ".e2er" / "link.json", scratch / ".e2er" / "link.json")
            if _check_anchor(scratch).status == PASS:
                from .core.abstract import AMENDMENT_KINDS

                kinds = {a.get("kind") for a in (_load_json(bundle / "provenance.json") or {}).get("amendments") or []}
                if kinds & set(AMENDMENT_KINDS) and rd.KIND not in kinds:
                    what = f"the abstract was rewritten ({n} file(s): e2er abstract)"
                    again = "publish again to publish the new abstract"
                else:
                    what = (
                        f"{n} change(s) recorded as redactions by the researcher (personal contact details, the "
                        "record says)"
                    )
                    again = "publish again to publish the redacted folder"
                return Check("anchor", PASS, f"e2er.json describes this folder as published, before {what}; {again}")
    return None


# ── the outside anchor: what e2er.org published (--against) ──────────────────


class AgainstError(Exception):
    pass


def _fetch_published(spec: str) -> tuple[str, Any]:
    """('study' | 'dossier', the record), fetched with GET from e2er.org (or another e2er site)."""
    from urllib.parse import urlparse

    from .core import platform_client as pc

    u = urlparse(spec)
    if u.scheme not in ("https", "http") or not u.netloc:
        raise AgainstError(f"--against needs an e2er.org address (https://…), not {spec!r}")
    parts = [p for p in u.path.split("/") if p]
    base = f"{u.scheme}://{u.netloc}"
    if len(parts) >= 2 and parts[0] == "d":
        kind, path = "dossier", f"/api/v1/dossiers/{parts[1]}"
    elif len(parts) >= 2 and parts[0] == "r":
        # An anonymous version for double-blind review (e2er publish --blind): its record lists the one version.
        kind, path = "study", f"/api/v1/blind/{parts[1]}"
    elif len(parts) >= 4 and parts[:2] == ["api", "v1"] and parts[2] in ("studies", "dossiers"):
        kind = "study" if parts[2] == "studies" else "dossier"
        path = "/" + "/".join(parts)
    elif len(parts) >= 2:
        kind, path = "study", f"/api/v1/studies/{parts[0]}/{parts[1]}"
    else:
        raise AgainstError(f"{spec} names neither a study (…/<owner>/<project>, …/r/<code>) nor a dossier (…/d/<id>)")
    try:
        with pc.client_factory(base) as client:
            resp = client.get(path, headers={"accept": "application/json"})
    except Exception as e:  # noqa: BLE001 - network errors are the user's to see
        raise AgainstError(f"could not reach {base}: {e}") from e
    if resp.status_code != 200:
        raise AgainstError(f"{base}{path} answered {resp.status_code}")
    try:
        return kind, resp.json()
    except ValueError as e:
        raise AgainstError(f"{base}{path} did not answer with JSON") from e


def _read_published_file(path: str) -> tuple[str, Any]:
    from .core.export.bundle_files import load_json_strict

    data, why = load_json_strict(Path(path).expanduser())
    if why:
        raise AgainstError(why)
    if isinstance(data, dict) and isinstance(data.get("versions"), list):
        return "study", data
    if isinstance(data, dict) and str(data.get("schema", "")).startswith("e2er-dossier/"):
        return "dossier", data
    if isinstance(data, dict) and "content_id" in data:
        return "manifest", data
    raise AgainstError(f"{path} is neither a study record, a dossier nor an e2er.json")


def _check_against(bundle: Path, kind: str, record: Any, source: str, short: str | None = None) -> Check:
    """The folder against what was published: the content id (and the dossier), the real anchor."""
    from .core.dossier import CanonicalError, dossier_id

    content_id = _content_id(bundle)
    manifest = _load_json(bundle / "e2er.json")
    named_dossier = ((manifest or {}).get("dossier") or {}).get("id") if isinstance(manifest, dict) else None
    if kind == "study":
        versions = [v for v in record.get("versions") or [] if isinstance(v, dict)]
        latest = (record.get("latest") or {}).get("number")
        hit = next((v for v in versions if v.get("content_id") == content_id), None)
        if hit is None:
            shown = ", ".join(f"v{v.get('number')} {str(v.get('content_id'))[:19]}…" for v in versions) or "none"
            return Check(
                "published",
                FAIL,
                f"this folder (content {str(content_id)[:19]}…) is no version {source} published ({shown})",
            )
        if named_dossier is not None and hit.get("dossier_id") != named_dossier:
            return Check(
                "published",
                FAIL,
                f"the folder is version {hit.get('number')} of {source}, but e2er.json names another dossier "
                f"({named_dossier[:23]}…) than the one published ({str(hit.get('dossier_id'))[:23]}…)",
            )
        which = "the latest" if hit.get("number") == latest else f"not the latest (that is version {latest})"
        return Check(
            "published",
            PASS,
            f"the folder is version {hit.get('number')} of {source}, {which}: its content id (the SHA-256 of "
            "provenance.json, which fixes every file) is the one published",
        )
    if kind == "dossier":
        try:
            did = dossier_id(record)
        except CanonicalError as e:
            return Check("published", FAIL, f"the dossier from {source} has no canonical form: {e}")
        if short and not did.removeprefix("sha256:").startswith(short):
            return Check("published", FAIL, f"the dossier from {source} does not hash to its address")
        if named_dossier is None:
            return Check("published", FAIL, f"the folder has no e2er.json naming a dossier to compare with {source}")
        if did != named_dossier:
            return Check("published", FAIL, f"e2er.json names another dossier than {source} ({did[:23]}…)")
        prov, _ = _load_provenance(bundle)
        problems = _fingerprint_problems(record.get("data"), (prov or {}).get("files") or {}, "the dossier's data")
        if problems:
            return Check("published", FAIL, "; ".join(problems[:3]))
        return Check(
            "published",
            PASS,
            f"e2er.json names the dossier {source} holds and its data files have the fingerprints it publishes; a "
            "dossier fixes the data files only, the study record (…/<owner>/<project>) fixes every file",
        )
    if record.get("content_id") != content_id:
        return Check("published", FAIL, f"the folder's content id is not the one {source} names")
    return Check("published", PASS, f"the folder's content id is the one {source} names")


# ── workspace reconstruction for the reuse-based checks ──────────────────────


def _reconstruct_workspace(bundle: Path, ws: Path) -> None:
    """Lay the bundle's spec + result JSONs out flat, the way the numbers and
    spec verifiers expect a run workspace — so their logic is reused unchanged."""
    resdir = bundle / "results"
    if resdir.is_dir():
        for f in resdir.glob("*.json"):
            shutil.copy2(f, ws / f.name)
    spec = bundle / "design" / "identification_spec.json"
    if spec.is_file():
        shutil.copy2(spec, ws / "identification_spec.json")
    # The method checks of the policy-evaluation and spatial-analysis templates read
    # their design file and the files the analysis wrote (units, weights).
    for name in ("did_design.json", "spatial_design.json", "review_protocol.json", "extraction.json"):
        if (bundle / "design" / name).is_file():
            shutil.copy2(bundle / "design" / name, ws / name)
    if resdir.is_dir():
        for f in resdir.glob("*.csv"):
            shutil.copy2(f, ws / f.name)
    # The study's design settings, which the number check does not look for in the results
    # (verify_numbers.design_constants): design files, pre-registration, data dictionary, template.
    for src in [*sorted((bundle / "design").glob("*_design.json")), bundle / "design" / "preregistration.md"]:
        if src.is_file() and not (ws / src.name).exists():
            shutil.copy2(src, ws / src.name)
    if (bundle / "data" / "data_dictionary.json").is_file():
        shutil.copy2(bundle / "data" / "data_dictionary.json", ws / "data_dictionary.json")
    template = ((_load_json(bundle / "provenance.json") or {}).get("run") or {}).get("template")
    if template and not (ws / "manifest.json").exists():
        (ws / "manifest.json").write_text(json.dumps({"pipeline": template}), encoding="utf-8")
    # A text study's checks recount the corpus: its design, the corpus (data.db) and
    # the word lists the design names (stop words, lemmas, dictionaries, lexicons).
    if (bundle / "design" / "corpus_design.json").is_file():
        _reconstruct_text_workspace(bundle, ws)


def _reconstruct_text_workspace(bundle: Path, ws: Path) -> None:
    from .core.pipeline.text_checks import DESIGN_FILE, MANIFEST_FILE, referenced_files

    shutil.copy2(bundle / "design" / DESIGN_FILE, ws / DESIGN_FILE)
    for name in ("data.db", MANIFEST_FILE):
        if (bundle / "data" / name).is_file():
            shutil.copy2(bundle / "data" / name, ws / name)
    design = _load_json(ws / DESIGN_FILE)
    for rel in referenced_files(design if isinstance(design, dict) else {}):
        target = ws / rel
        if target.is_file() or not target.resolve().is_relative_to(ws.resolve()):
            continue
        found = sorted(p for p in bundle.rglob(Path(rel).name) if p.is_file())
        if found:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(found[0], target)


# ── check 2: numbers ─────────────────────────────────────────────────────────


def _check_statistics(ws: Path) -> tuple[list[str], str]:
    """t = estimate / se and p follows from t, in the bundle's result files."""
    from .core.pipeline.statistics import check_statistics

    docs = [(n, _load_json(ws / n)) for n in ("estimation_results.json", "robustness_results.json")]
    report = check_statistics([(n, d) for n, d in docs if d is not None])
    return report.problems, report.summary() if report.checked or report.not_analytic else ""


def _left_out_cells(bundle: Path, left: dict[str, dict[str, Any]]) -> dict[tuple[str, str], str]:
    """(table context, cell value) → the left-out results file provenance.json traces the cell to.

    The derivation edges are recomputed by the integrity check, so a cell counts only where the study's own
    record ties it to a file a published copy left out.
    """
    if not left:
        return {}
    prov = _load_json(bundle / "provenance.json")
    edges = prov.get("edges") if isinstance(prov, dict) else None
    out: dict[tuple[str, str], str] = {}
    for e in edges if isinstance(edges, list) else []:
        if isinstance(e, dict) and e.get("type") == "table_cell" and e.get("source") in left:
            out[(str(e.get("table_context")), str(e.get("cell_value")))] = str(e["source"])
    return out


def _check_numbers(bundle: Path, ws: Path, left: dict[str, dict[str, Any]] | None = None) -> Check:
    """Every table cell a source value at the precision shown; t and p consistent in the results.

    ``left``: results files a published copy left out. A failure is skipped for them only where it is theirs:
    a cell whose recorded source is a left-out file, or no cell checked because the files the numbers are
    traced to are left out. The statistics (p-value and t) of the files that are here always count.
    """
    left = left or {}
    left_json = sorted(p for p in left if p.endswith(".json") and p.count("/") == 1)
    stats_problems, stats_note = _check_statistics(ws)
    if stats_problems:
        more = f"; and {len(stats_problems) - 3} more" if len(stats_problems) > 3 else ""
        shown = "; ".join(stats_problems[:3]) + more
        return Check("numbers", FAIL, f"{len(stats_problems)} p-value/t inconsistenc(ies): {shown}")
    note = f"; {stats_note}" if stats_note else ""
    tex = bundle / "paper" / "paper.tex"
    if not tex.is_file():
        return Check("numbers", SKIP, f"no paper/paper.tex{note}")
    from .core.pipeline.verify_numbers import verify as verify_numbers

    # verify's rule is stricter than the run's gate: every table cell must be a
    # source value rounded to the decimals the cell shows. A cell no source
    # value rounds to is a failure, however far it is from every source value
    # (the run's gate let values within 10% pass as "major" and cells with no
    # value nearby pass as "unverifiable").
    report = verify_numbers(tex, ws, rounding=True)
    sources_left = [p for p in left_json if p.rsplit("/", 1)[-1] in set(report.source_files_missing)]
    if report.skipped_reason and not report.tables_conclusive:
        if sources_left and not report.source_files_found:
            # Every file the numbers are traced to is left out: nothing here to check them against.
            return _needs("numbers", left, sources_left)
        if _bundle_has_rendered_tables(bundle):
            return Check(
                "numbers",
                FAIL,
                f"the paper ships rendered tables but no table cell could be checked: {report.skipped_reason}",
            )
        return Check("numbers", SKIP, f"{report.skipped_reason}{note}")
    approved, open_ = _researcher_approved_cells(bundle, report.mismatches)
    if approved and not open_:
        # Every cell that differs is one the researcher continued with at the
        # number check: the decision travels in the bundle (reviews/number_check.json,
        # hashed in provenance.json) and in the dossier, so the check passes and says so.
        shown = "; ".join(
            f"{m.draft_value} ({m.table_context}; the results say {m.source_value}, {m.source_key})"
            for m in approved[:3]
        )
        return Check(
            "numbers",
            PASS,
            f"{report.matched} table cell(s) are source values at the precision shown; {len(approved)} differ from "
            f"the results and the researcher continued with them at the number check (recorded in the dossier): "
            f"{shown}{note}{_prose_note(report)}",
        )
    if open_:
        # A cell whose recorded source is a left-out file cannot be checked here; any other differing cell fails.
        cells = _left_out_cells(bundle, left)
        theirs = [m for m in open_ if (m.table_context, m.draft_value) in cells]
        rest = [m for m in open_ if m not in theirs]
        if not rest:
            return _needs("numbers", left, sorted({cells[(m.table_context, m.draft_value)] for m in theirs}))
        first = "; ".join(
            f"{m.draft_value} ({m.table_context}; nearest source value {m.source_value}, {m.source_key})"
            for m in rest[:3]
        )
        return Check(
            "numbers",
            FAIL,
            f"{len(rest)} of {report.total_values_in_tables} table cell(s) are no source value at the "
            f"precision shown: {first}",
        )
    if not report.tables_conclusive:
        if sources_left and _left_out_cells(bundle, left):
            # The tables' cells are traced to left-out files only: nothing here to check them against.
            return _needs("numbers", left, sources_left)
        if _bundle_has_rendered_tables(bundle):
            # The paper ships rendered tables and the check traced no cell in any of
            # them. That is not a pass: it is the gate failing to run on the one
            # channel the anti-fabrication claim rests on.
            why = report.untraced_reason or "the numbers check did not run on them"
            return Check("numbers", FAIL, f"0 table cell(s) traced although the paper ships rendered tables: {why}")
        return Check("numbers", SKIP, f"the paper has no table cell to check{note}{_prose_note(report)}")
    return Check(
        "numbers",
        PASS,
        f"{report.matched} table cell(s) are source values at the precision shown{note}{_prose_note(report)}",
    )


def _researcher_approved_cells(bundle: Path, mismatches: list[Any]) -> tuple[list[Any], list[Any]]:
    """Split mismatches into those the researcher continued with at the number check and the rest.

    A cell counts as approved when reviews/number_check.json records the
    researcher's decision (``accepted_by_researcher``) for the same table cell,
    the same printed value and the same source key, as the run matched it. A
    record from a regime that does not stop (``recorded_and_continued``) is no
    decision and approves nothing.
    """
    try:
        doc = json.loads((bundle / "reviews" / "number_check.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [], list(mismatches)
    if not isinstance(doc, dict) or doc.get("decision") != "accepted_by_researcher":
        return [], list(mismatches)
    from .core.pipeline.researcher import mismatch_key

    # The run lets exactly these through: the cell, the table's value and the source key (mismatch_key).
    recs = [m for m in doc.get("mismatches") or [] if isinstance(m, dict)]
    keys = {str(m.get("key") or f"{m.get('cell')}|{m.get('in_table')}|{m.get('source_key')}") for m in recs}
    # A record without a source key (written before the runner kept one): the cell and its value.
    cells = {(str(m.get("cell")), str(m.get("in_table"))) for m in recs if not m.get("key") and not m.get("source_key")}

    def ok(m: Any) -> bool:
        return mismatch_key(m) in keys or (m.table_context, m.draft_value) in cells

    return [m for m in mismatches if ok(m)], [m for m in mismatches if not ok(m)]


def _prose_note(report: Any) -> str:
    """Numbers in the text are reported, never gating: prose has too many incidental numbers to fail on."""
    if not report.prose_total:
        return ""
    return (
        f"; text (not gating): {report.prose_matched} of {report.prose_total} number(s) are source values, "
        f"{report.prose_mismatched} differ from the quantity named nearby, {report.prose_unverifiable} untraced"
    )


def _bundle_has_rendered_tables(bundle: Path) -> bool:
    """Did the renderer produce tables for this paper?

    Read from the render report the pipeline already writes; fall back to
    looking for the table files themselves, so an older bundle without the
    report is still judged on what it actually contains.
    """
    report_path = bundle / "results" / "table_render_report.json"
    if report_path.is_file():
        try:
            import json

            rendered = json.loads(report_path.read_text(encoding="utf-8")).get("rendered")
            if isinstance(rendered, list):
                return bool(rendered)
        except (OSError, ValueError):
            pass
    return any((bundle / "paper" / "tables").glob("*.tex"))


# ── check 3: tables reproduce from the sidecars ──────────────────────────────

_INPUT_RE = re.compile(r"\\input\{([^}]+)\}")


def _strip_tex_comments(tex: str) -> str:
    r"""Drop LaTeX comments before looking for \input.

    paper.tex documents its own conventions in a comment containing a literal
    \input{tables/...}, and the pipeline dutifully wrote a stub file for it.
    """
    out = []
    for line in tex.splitlines():
        idx = 0
        while True:
            idx = line.find("%", idx)
            if idx == -1:
                out.append(line)
                break
            if idx > 0 and line[idx - 1] == "\\":
                idx += 1
                continue
            out.append(line[:idx])
            break
    return "\n".join(out)


def _included_tables(bundle: Path) -> set[str]:
    tex = bundle / "paper" / "paper.tex"
    if not tex.is_file():
        return set()
    body = _strip_tex_comments(tex.read_text(encoding="utf-8", errors="replace"))
    names = set()
    for ref in _INPUT_RE.findall(body):
        name = Path(ref).name
        names.add(name if name.endswith(".tex") else f"{name}.tex")
    return names


def _table_sources(ws: Path) -> dict[str, set[str]]:
    from .core.renderer.tables import table_sources

    return table_sources(ws)


def _check_tables(bundle: Path, ws: Path, left: dict[str, dict[str, Any]] | None = None) -> Check:
    """Re-render the declared tables and compare them byte for byte.

    ``left``: results files a published copy left out. A table that differs is skipped only when it reads one
    of them; every other table that differs fails.
    """
    left = left or {}
    if "results/table_spec.json" in left:
        return _needs("tables", left, ["results/table_spec.json"])
    if not (ws / "table_spec.json").is_file():
        return Check("tables", SKIP, "no results/table_spec.json in bundle")

    from .core.renderer.tables import render_tables

    shipped_dir = bundle / "paper" / "tables"
    if not shipped_dir.is_dir():
        return Check("tables", SKIP, "bundle ships no paper/tables directory")

    report = render_tables(ws)
    if report.skipped_reason:
        return Check("tables", SKIP, report.skipped_reason)

    differing, missing = [], []
    for name in report.rendered:
        shipped = shipped_dir / name
        fresh = ws / "tables" / name
        if not shipped.is_file():
            missing.append(name)
        elif shipped.read_bytes() != fresh.read_bytes():
            differing.append(name)

    if differing and left:
        reads = _table_sources(ws)
        gone = {p.rsplit("/", 1)[-1]: p for p in left if p.count("/") == 1}
        theirs = {n: sorted(gone[f] for f in reads.get(n, set()) if f in gone) for n in differing}
        if not missing and all(theirs.values()):
            return _needs("tables", left, sorted({p for ps in theirs.values() for p in ps}))
        differing = [n for n in differing if not theirs[n]] or differing
    if differing or missing:
        bits = []
        if differing:
            bits.append(f"{len(differing)} differ from the sidecars ({', '.join(sorted(differing)[:3])})")
        if missing:
            bits.append(f"{len(missing)} not shipped ({', '.join(sorted(missing)[:3])})")
        return Check("tables", FAIL, "; ".join(bits))

    # Coverage: what the paper includes that the renderer never produced.
    uncovered = sorted(_included_tables(bundle) - set(report.rendered))
    note = ""
    if uncovered:
        note = f"; {len(uncovered)} not renderer-produced ({', '.join(uncovered[:3])})"
    return Check(
        "tables",
        PASS,
        f"{len(report.rendered)} table(s) reproduce byte-identically from the sidecars{note}",
    )


# ── check 4: spec contract ───────────────────────────────────────────────────


def _check_spec(ws: Path) -> Check:
    if not (ws / "identification_spec.json").is_file():
        return Check("spec", SKIP, "no design/identification_spec.json")
    if not (ws / "estimation_results.json").is_file():
        return Check("spec", SKIP, "no results/estimation_results.json")
    from .core.specialists.contract_check import check_matches_declared_spec

    c = check_matches_declared_spec(ws, "estimation_results.json")
    if c.ok:
        return Check("spec", PASS, "estimation implements the declared identification")
    return Check("spec", FAIL, c.reason)


# ── check 4b: the results contract of a study that is not a regression ───────


def _check_results_contract(ws: Path) -> Check | None:
    """The results file against the contract of the kind it names (``result_kind``).

    None for a regression study (the file names no kind): its contract is the
    spec and numbers checks above, and its verify output stays as it was.
    """
    from .core.pipeline.result_kinds import RESULTS_FILE, check_results, file_kind, get

    kind = file_kind(ws)
    if kind is None or kind == "regression":
        return None
    problems = check_results(kind, _load_json(ws / RESULTS_FILE), ws)
    if problems:
        more = f"; and {len(problems) - 3} more" if len(problems) > 3 else ""
        return Check("results contract", FAIL, f"{kind}: " + "; ".join(problems[:3]) + more)
    return Check("results contract", PASS, f"{kind} results ({get(kind).label}) are complete and consistent")


# ── check 4c: the template's method checks on the exported files ─────────────


def _check_method(ws: Path) -> Check | None:
    """The checks of a DiD, spatial or meta-analysis study's results, again on the exported files.

    None when the bundle carries neither design file. The design-side checks
    need the study's data (data.db), which a bundle may not ship (boundaries
    under terms of their own), so only the results side
    runs here: for DiD the event-study path, the pre-trends test, the placebo or
    sensitivity analysis and the declared estimator; for a spatial study the
    weights file and Moran's I recomputed from the units and weights.
    """
    from .core.pipeline.did_checks import DESIGN_FILE as DID_DESIGN
    from .core.pipeline.did_checks import check_did_results
    from .core.pipeline.spatial_checks import DESIGN_FILE as SPATIAL_DESIGN
    from .core.pipeline.spatial_checks import check_spatial_results

    if (ws / DID_DESIGN).is_file():
        what, verdict = "difference-in-differences", check_did_results(ws)
    elif (ws / SPATIAL_DESIGN).is_file():
        what, verdict = "spatial", check_spatial_results(ws)
    elif (ws / "review_protocol.json").is_file() and (ws / "extraction.json").is_file():
        # A meta-analysis: the extracted numbers against their quotes, and the effects
        # against the extraction (src/modules/metaanalysis/workflow.py, export_check).
        from .modules.metaanalysis.workflow import export_check

        what, verdict = "meta-analysis", export_check(ws)  # type: ignore[assignment]
    elif (ws / "corpus_design.json").is_file():
        return _check_text_method(ws)
    else:
        return None
    if verdict.passed:
        found = ", ".join(f"{k}={v}" for k, v in verdict.stats.items())
        return Check("method checks", PASS, f"{what}: {found}")
    more = f"; and {len(verdict.reasons) - 3} more" if len(verdict.reasons) > 3 else ""
    return Check("method checks", FAIL, f"{what}: " + "; ".join(verdict.reasons[:3]) + more)


def _check_text_method(ws: Path) -> Check:
    """A text study's results and hand-checked samples, recounted from the exported corpus."""
    from .core.pipeline.text_checks import check_text_results, check_text_validation

    if not (ws / "data.db").is_file():
        return Check(
            "method checks", SKIP, "text: the corpus (data/data.db) is not in the folder, so nothing is recounted"
        )
    results, validation = check_text_results(ws), check_text_validation(ws)
    reasons = [*results.reasons, *validation.reasons]
    if reasons:
        more = f"; and {len(reasons) - 3} more" if len(reasons) > 3 else ""
        return Check("method checks", FAIL, "text: " + "; ".join(reasons[:3]) + more)
    found = ", ".join(f"{k}={v}" for k, v in {**results.stats, **validation.stats}.items())
    return Check("method checks", PASS, f"text: recounted from the corpus: {found}")


# ── check 4: citations (offline) ─────────────────────────────────────────────


def _check_citations_offline(bundle: Path) -> Check:
    tex = bundle / "paper" / "paper.tex"
    if not tex.is_file():
        return Check("citations", SKIP, "no paper/paper.tex")
    from .core.pipeline.verify_citations import load_bib, parse_bibitem_keys, parse_cite_keys

    text = tex.read_text(encoding="utf-8", errors="replace")
    keys = parse_cite_keys(text)
    from .core.bibliography import bibliography_names

    absent = [n for n in bibliography_names(text) if not (bundle / "paper" / f"{n}.bib").is_file()]
    if keys and absent:
        return Check(
            "citations",
            FAIL,
            f"paper.tex uses {', '.join(n + '.bib' for n in absent)}, which is not in the bundle; "
            "compiled from the bundle, every citation would be unresolved",
        )
    refs = bundle / "paper" / "refs.bib"
    bib = load_bib(refs) if refs.is_file() else {}
    missing = [k for k in keys if k not in bib]

    # Consistency of the bundled registry snapshot: recomputed status counts
    # must match the stored aggregates (a tampered report is caught here).
    ci = _load_json(bundle / "reviews" / "citation_integrity.json")
    snapshot = ""
    if isinstance(ci, dict):
        checks = ci.get("checks") or []
        recomputed_missing = sum(1 for c in checks if c.get("status") == "missing_in_bib")
        if recomputed_missing != ci.get("missing_in_bib", recomputed_missing):
            return Check("citations", FAIL, "citation_integrity.json counts do not match its records (tampered?)")
        snapshot = f"; snapshot: {ci.get('verified', 0)} verified, {ci.get('unverifiable', 0)} unverifiable at run time"

    if missing:
        return Check("citations", FAIL, f"{len(missing)} cited key(s) not in refs.bib: {', '.join(missing[:5])}")
    if not keys and not parse_bibitem_keys(text):
        # The template's method sources are citable, never required: they do not count here.
        literature = [k for k, f in bib.items() if f.get("e2er_source") != "template"]
        if literature:
            # The paper ignores the bibliography it ships: nothing it says is
            # tied to a source (the 2026-10-10 Haiku paper, 21 entries, 0 cites).
            return Check(
                "citations", FAIL, f"paper.tex cites none of the {len(literature)} work(s) in refs.bib{snapshot}"
            )
        return Check(
            "citations",
            SKIP,
            f"no references: paper.tex cites nothing and the bundle has no bibliography (paper/refs.bib){snapshot}",
        )
    if not keys:
        return Check("citations", SKIP, f"paper.tex cites nothing, so there is no citation to check{snapshot}")
    return Check("citations", PASS, f"{len(keys)} cite key(s) resolve in refs.bib{snapshot}")


# ── check 4b: citations (online) ─────────────────────────────────────────────


async def _check_citations_online(bundle: Path) -> Check:
    tex = bundle / "paper" / "paper.tex"
    refs = bundle / "paper" / "refs.bib"
    if not tex.is_file():
        return Check("citations.online", SKIP, "no paper/paper.tex")
    from .core.pipeline.verify_citations import verify as verify_citations

    report = await verify_citations(tex, bib_path=refs if refs.is_file() else None)
    if report.skipped_reason:
        return Check("citations.online", SKIP, report.skipped_reason)
    if report.missing_in_bib:
        return Check("citations.online", FAIL, f"{report.missing_in_bib} cited key(s) missing from refs.bib")
    return Check(
        "citations.online",
        PASS,
        f"{report.verified}/{report.total_cites} verified live, {report.unverifiable} unverifiable",
    )


# ── orchestration + output ───────────────────────────────────────────────────


def _check_preregistration(bundle: Path, required: str | None = None) -> Check | None:
    """A frozen pre-registration: the plan files still match their fingerprints.

    Returns None for a bundle without one, so ordinary bundles report the same
    checks as before, unless ``required`` says why the study had one: then a
    missing lock file FAILS (deleting it must not make the check disappear).
    """
    from .core.pipeline.preregistration import deviation_details, load_lock

    design = bundle / "design"
    lock = load_lock(design)
    if lock is None:
        if required:
            return Check(
                "preregistration",
                FAIL,
                f"design/preregistration.lock.json is missing or unreadable, but {required}",
            )
        return None
    when = str(lock.get("frozen_at", ""))[:10]
    details = deviation_details(design, lock)
    # A plan file whose only change since the freeze is the researcher's redaction of personal data
    # (`e2er redact`, recorded as amendments that match the file): redacted, not changed.
    redacted = [d for d in details if not d["approved"] and _only_redacted(bundle, d)]
    details = [d for d in details if d not in redacted]
    unapproved = [d["text"] for d in details if not d["approved"]]
    approved = [d["text"] for d in details if d["approved"]]
    if unapproved:
        return Check(
            "preregistration",
            FAIL,
            f"deviates from the pre-registered plan (frozen {when}) without the researcher's approval: "
            + "; ".join(unapproved),
        )
    # A deviation the researcher approved at the estimation check passes, and is reported.
    approved_note = [f"deviation approved by the researcher: {d}" for d in approved]
    from .core.redact import PREREG_WORDS

    approved_note += [f"{d['file']} {_redaction_words(bundle, d['file'], PREREG_WORDS)}" for d in redacted]
    problems, notes = _preregistered_results(bundle, lock)
    if problems:
        return Check(
            "preregistration",
            FAIL,
            f"pre-registered plan (frozen {when}): " + "; ".join(problems + notes + approved_note),
        )
    extra = ("; " + "; ".join(approved_note + notes)) if approved_note or notes else ""
    head = "estimation follows the pre-registered plan" if not approved else "the pre-registered plan"
    return Check("preregistration", PASS, f"{head} (frozen {when}){extra}")


def _redaction_words(bundle: Path, name: str, redacted_words: str) -> str:
    """What verify says about a pre-registered plan file changed after the freeze by redaction or anonymisation."""
    from .core import anonymise as an

    prov = _load_json(bundle / "provenance.json")
    kinds = {
        a.get("kind")
        for a in ((prov or {}).get("amendments") or [] if isinstance(prov, dict) else [])
        if isinstance(a, dict) and a.get("path") == f"design/{name}"
    }
    if an.KIND in kinds and "redacted" not in kinds:
        return (
            "recorded as anonymised for double-blind review after registration (identifying details, the record says)"
        )
    return redacted_words


def _only_redacted(bundle: Path, d: dict[str, Any]) -> bool:
    """Is the deviation ``d`` (preregistration.deviation_details) explained by redactions alone, each recorded
    in provenance.json and the last one matching the file?"""
    from .core import redact as rd

    prov = _load_json(bundle / "provenance.json")
    if not isinstance(prov, dict):
        return False
    rel = f"design/{d['file']}"
    amendments = [a for a in prov.get("amendments") or [] if isinstance(a, dict)]
    links = rd.chain(amendments, rel, d.get("sha256_frozen"), d.get("sha256_now"))
    if not links:
        return False
    f = bundle / rel
    # Each record holds: the sizes add up, the replacement sits at its offsets, the kept bytes are the ones
    # recorded, no more than contact details' length taken out at a place.
    return rd.chain_problem(links, f.read_bytes() if f.is_file() else None) is None


def _preregistered_results(bundle: Path, lock: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Every pre-registered hypothesis has a result, on the registered sample (the bundle's results/)."""
    from .core.pipeline.preregistration import headline_entry, preregistered, result_coverage

    design = bundle / "design"
    folder = design if (design / "event_design.json").is_file() else bundle / "misc"
    prereg = preregistered(folder, lock, prereg_dir=design)
    docs = [_load_json(bundle / "results" / n) for n in ("estimation_results.json", "robustness_results.json")]
    docs = [d for d in docs if isinstance(d, dict)]
    if not docs:
        wanted = [h["id"] for h in prereg.get("hypotheses") or []]
        return ([f"no results/estimation_results.json, so no result for {', '.join(wanted)}"] if wanted else []), []
    return result_coverage(docs, prereg, headline_entry(docs[0], prereg))


# ── reproduction (replication bundles) ────────────────────────────────────────


def _reproduction_file(bundle: Path, name: str) -> Path | None:
    for p in (bundle / "misc" / name, bundle / name):
        if p.is_file():
            return p
    return None


def _check_reproduction(bundle: Path, required: str | None = None) -> Check | None:
    """Re-read every compared number from the exported run outputs and recompute the labels.

    Uses the pipeline's own reproduction check (``reproduction.evaluate``) with
    the tolerance the run used, as recorded in reproduction_check.json. None
    for a bundle without a reproduction report, so paper bundles are unchanged.
    """
    from .core.pipeline.reproduction import (
        CHECK_FILE,
        DEFAULT_MINOR_REL_TOLERANCE,
        MD_FILE,
        REPORT_FILE,
        evaluate,
        report_text_reasons,
    )

    report_path = _reproduction_file(bundle, REPORT_FILE)
    if report_path is None:
        if required:
            return Check("reproduction", FAIL, f"{REPORT_FILE} is missing, but {required}")
        return None
    plan = _load_json(_reproduction_file(bundle, "replication_plan.json") or bundle / "-")
    log = _load_json(_reproduction_file(bundle, "sandbox_log.json") or bundle / "-")
    report = _load_json(report_path)
    if not isinstance(plan, dict) or not isinstance(log, dict):
        return Check("reproduction", FAIL, "a reproduction report without replication_plan.json or sandbox_log.json")
    bundled = _load_json(_reproduction_file(bundle, CHECK_FILE) or bundle / "-")
    tol = bundled.get("minor_rel_tolerance") if isinstance(bundled, dict) else None
    if isinstance(tol, bool) or not isinstance(tol, int | float) or not 0 <= tol < 1:
        tol = DEFAULT_MINOR_REL_TOLERANCE
    run_rel = str(log.get("run_dir") or "sandbox/run")
    run_dir = (bundle / run_rel).resolve()
    if run_rel.startswith("/") or not run_dir.is_relative_to(bundle.resolve()):
        return Check("reproduction", FAIL, f"sandbox_log.json names a run folder outside the bundle ({run_rel})")
    if not run_dir.is_dir():
        return Check(
            "reproduction",
            FAIL,
            f"the bundle has no {run_rel}/: the run's output files were not exported, so no compared number "
            "can be re-read (export again with this version of e2er)",
        )
    doc = evaluate(plan, report, log, run_dir, minor_rel_tolerance=float(tol))
    md_path = _reproduction_file(bundle, MD_FILE)
    md_text = md_path.read_text(encoding="utf-8") if md_path is not None else None
    reasons = [*doc["reasons"], *report_text_reasons(md_text, report if isinstance(report, dict) else {}, log)]
    if reasons:
        shown = "; ".join(reasons[:3]) + (f"; and {len(reasons) - 3} more" if len(reasons) > 3 else "")
        return Check("reproduction", FAIL, f"{len(reasons)} problem(s): {shown}")
    stats = doc["stats"]
    parts = []
    for key in ("level_1", "level_2"):
        tier = stats.get(key) or {}
        if not tier.get("targets"):
            continue
        counts = tier.get("numbers") or {}
        shown = ", ".join(f"{counts[lv]} {lv.replace('_', ' ')}" for lv in counts if counts[lv])
        parts.append(f"{key.replace('_', ' ')}: {shown or 'nothing compared'}")
    return Check(
        "reproduction",
        PASS,
        f"{stats.get('numbers_checked', 0)} compared number(s) re-read from the run's outputs and relabelled "
        f"(minor tolerance {float(tol):.0%}); "
        + "; ".join(parts)
        + ("; the report's summary counts agree" if doc.get("summary") else "; the report states no summary counts")
        + f"; {MD_FILE} agrees with {REPORT_FILE}",
    )


_REPRODUCTION_FILES = ("replication_plan.json", "sandbox_log.json", "reproduction_check.json", "reproduction_report.md")


def _check_results_from_code(bundle: Path, left_out: set[str] | None = None) -> Check | None:
    """Each results file is the file the last run of the study's script wrote (provenance.json records which).

    The run's script log records the SHA-256 of every file each script run
    wrote; export puts the run that wrote each results file into
    ``run.results_from_code``. The bundle's results file must have that run's
    output hash, the run must have succeeded with the script as the study ships
    it, and the folder must carry the script. A results file no recorded run
    wrote fails ("the results have no script that computes them"). SKIP for a
    run that predates output records (e2er up to 0.16.0); None for a bundle
    without a results file.
    """
    prov = _load_json(bundle / "provenance.json")
    run = prov.get("run") if isinstance(prov, dict) else None
    record = run.get("results_from_code") if isinstance(run, dict) else None
    if not isinstance(record, dict) or not record:
        if (bundle / "results" / "estimation_results.json").is_file():
            # Exported by e2er up to 0.16.0: the run recorded no script outputs.
            return Check("results from code", SKIP, "not checked: the run predates output records")
        return None
    problems: list[str] = []
    traced: list[str] = []
    skipped: list[str] = []
    left: list[str] = []
    for rel, entry in sorted(record.items()):
        name = str(rel).rsplit("/", 1)[-1]
        if not isinstance(entry, dict):
            problems.append(f"{name}: the record is unreadable")
            continue
        if entry.get("outcome") == "not_recorded":
            skipped.append(name)
            continue
        path = bundle / str(rel)
        if not path.is_file() and str(rel) in (left_out or set()):
            left.append(name)  # left out under a source's terms: nothing here to compare
            continue
        if not path.is_file():
            problems.append(f"{name} is not in the folder")
            continue
        script = entry.get("script")
        if not script:
            problems.append(f"{name}: the results have no script that computes them")
            continue
        if entry.get("output_sha256") != _sha256(path):
            problems.append(f"{name} is not the file {script} wrote (run {entry.get('ran_at') or '?'})")
            continue
        if entry.get("exit_code") not in (0, None):
            problems.append(f"{name} was written by a run of {script} that failed")
            continue
        if entry.get("outcome") != "from_code":
            # The script changed after the run that wrote the file: the folder ships other code.
            problems.append(f"{name} was not written by {script} as shipped ({entry.get('reason') or 'changed'})")
            continue
        shipped = entry.get("script_in_folder")
        if not shipped or not (bundle / str(shipped)).is_file():
            problems.append(f"{script}, which wrote {name}, is not in the folder")
            continue
        if entry.get("script_in_folder_sha256") != _sha256(bundle / str(shipped)):
            problems.append(f"{shipped} is not the script that wrote {name}")
            continue
        traced.append(f"{name} ← {script}")
    if problems:
        return Check("results from code", FAIL, "; ".join(problems))
    if not traced:
        if left:
            return Check(
                "results from code",
                SKIP,
                f"not checked: {', '.join(left)} left out under a source's terms; `e2er reproduce` writes "
                + ("it" if len(left) == 1 else "them")
                + " again",
            )
        return Check("results from code", SKIP, "not checked: the run predates output records")
    detail = "written by the last run of the shipped script: " + ", ".join(traced)
    if skipped:
        detail += f"; not checked (the run predates output records): {', '.join(skipped)}"
    if left:
        detail += f"; not checked (left out under a source's terms): {', '.join(left)}"
    return Check("results from code", PASS, detail)


def _required_checks(bundle: Path) -> dict[str, str]:
    """The checks the study's own record says it must have, with the reason.

    What the bundle says the study was (provenance.json, e2er.json and its
    dossier) decides which checks are required, not which input files happen
    to be there: deleting ``preregistration.lock.json`` or
    ``reproduction_report.json`` then fails the required check instead of
    making it disappear.
    """

    def obj(value: Any) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}

    run = obj(obj(_load_json(bundle / "provenance.json")).get("run"))
    manifest = obj(_load_json(bundle / "e2er.json"))
    doc = obj(obj(manifest.get("dossier")).get("doc"))
    out: dict[str, str] = {}
    template = run.get("template") or obj(manifest.get("process")).get("template")
    if template == "replication":
        out["reproduction"] = "the study was run with the replication template (provenance.json)"
    else:
        present = [n for n in _REPRODUCTION_FILES if _reproduction_file(bundle, n)]
        if present:
            out["reproduction"] = f"the bundle carries a reproduction ({', '.join(present)})"
    if run.get("preregistration"):
        out["preregistration"] = "provenance.json records a frozen pre-registration"
    elif doc.get("preregistration"):
        out["preregistration"] = "the published dossier (e2er.json) records a frozen pre-registration"
    return out


def _left_out_here(bundle: Path, package_left_out: dict[str, dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    """Files a published copy left out (a source's terms, too large for the host) and the folder does not have.

    From a package verify opened, its checked manifest; in a folder, only declarations the folder's own
    records support (package.supported_left_out), as the integrity check counts them.
    """
    from .core.export.package import supported_left_out

    declared = package_left_out if package_left_out is not None else supported_left_out(bundle)
    return {p: i for p, i in declared.items() if not (bundle / p).exists()}


def _needs(name: str, left: dict[str, dict[str, Any]], paths: list[str]) -> Check:
    """SKIP: the check needs files a published copy left out under a source's terms."""
    from .core.data_terms import known

    terms = known()
    shown = sorted(paths)
    sources = []
    hosts = []
    for p in shown:
        if left[p].get("kind") == "size":
            host = str(left[p].get("host") or "the host")
            if host not in hosts:
                hosts.append(host)
            continue
        c = left[p].get("source")
        t = terms.get(str(c)) if c else None
        label = t.short if t else str(c or "its source's")
        if label not in sources:
            sources.append(label)
    rebuilt = all(left[p].get("rebuilt_by") for p in shown)
    what = ", ".join(shown[:3]) + (f" and {len(shown) - 3} more" if len(shown) > 3 else "")
    how = (
        "run `e2er reproduce` to rebuild " + ("it" if len(shown) == 1 else "them")
        if rebuilt
        else "no recorded step rebuilds " + ("it" if len(shown) == 1 else "all of them")
    )
    why = ([f"under {' and '.join(sources)} terms"] if sources else []) + (
        [f"as too large for {' and '.join(hosts)}"] if hosts else []
    )
    return Check(name, SKIP, f"needs {what}, left out {' and '.join(why)}; {how}")


def _referenced(ws: Path, left: dict[str, dict[str, Any]], names: tuple[str, ...] = ()) -> list[str]:
    """Left-out files (folder paths) that the workspace's results or design files name, or that are ``names``."""
    by_base: dict[str, list[str]] = {}
    for p in left:
        by_base.setdefault(p.rsplit("/", 1)[-1], []).append(p)
    texts = ""
    for f in sorted(ws.glob("*.json")):
        try:
            texts += f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
    out = []
    for base, paths in by_base.items():
        if base in names or f'"{base}"' in texts:
            out += [p for p in paths if p.startswith("results/")]
    return sorted(out)


def _mentions(check: Check, left: dict[str, dict[str, Any]]) -> Check:
    """A failed check whose reason names a left-out file is skipped instead: the file is missing for a reason."""
    if check.status != FAIL or not left:
        return check
    named = [p for p in left if re.search(rf"(?<![\w.]){re.escape(p.rsplit('/', 1)[-1])}(?![\w])", check.detail)]
    return _needs(check.name, left, named) if named else check


def _run_checks(bundle: Path, online: bool, package_left_out: dict[str, dict[str, Any]] | None = None) -> list[Check]:
    checks = [_check_integrity(bundle, package_left_out), _check_anchor(bundle)]
    # Results files a published copy left out (they hold a restricted source's rows): a check that needs one
    # is skipped and says which, instead of failing on a file that is missing for a reason.
    left = {p: i for p, i in _left_out_here(bundle, package_left_out).items() if p.startswith("results/")}
    with tempfile.TemporaryDirectory() as td:
        ws = Path(td)
        _reconstruct_workspace(bundle, ws)
        checks.append(_check_numbers(bundle, ws, left))
        checks.append(_check_tables(bundle, ws, left))
        if "results/estimation_results.json" in left:
            checks.append(_needs("spec", left, ["results/estimation_results.json"]))
        else:
            checks.append(_mentions(_check_spec(ws), left))
            contract = _check_results_contract(ws)
            if contract is not None:
                checks.append(_mentions(contract, left))
        method = _check_method(ws)
        if method is not None:
            from .core.pipeline.spatial_checks import UNITS_FILE, WEIGHTS_FILE

            needed = _referenced(ws, left, (UNITS_FILE, WEIGHTS_FILE) if "spatial" in method.detail else ())
            if needed and method.status != PASS:
                method = _needs("method checks", left, needed)
            elif "results/estimation_results.json" in left:
                method = _needs("method checks", left, ["results/estimation_results.json"])
            checks.append(_mentions(method, left))
        checks.append(_check_citations_offline(bundle))
    from_code = _check_results_from_code(bundle, set(left))
    if from_code is not None:
        checks.append(from_code)
    required = _required_checks(bundle)
    prereg = _check_preregistration(bundle, required.get("preregistration"))
    if prereg is not None:
        checks.append(prereg)
    reproduction = _check_reproduction(bundle, required.get("reproduction"))
    if reproduction is not None:
        checks.append(reproduction)
    if online:
        checks.append(asyncio.run(_check_citations_online(bundle)))
    return checks


# The checks that actually verify CONTENT. Integrity (hashing files against
# provenance.json) proves only that the bundle is unchanged since export — a
# bundle can be perfectly self-consistent and still have had nothing checked.
_CONTENT_CHECKS = frozenset(
    {
        "numbers",
        "tables",
        "spec",
        "results contract",
        "method checks",
        "citations",
        "results from code",
        "preregistration",
        "reproduction",
    }
)


def _verdict(checks: list[Check]) -> tuple[str, int]:
    """Final banner + exit code.

    A SKIP is NOT a pass. Export is best-effort and can emit a partial bundle
    (e.g. no paper.tex → numbers/spec/citations all skip); reporting that as
    "verified" would be the single most misleading thing this command could
    say, since the whole point is cheap, honest verification. The banner
    names exactly the checks that passed and those that were skipped.
    """
    fails = [c for c in checks if c.status == FAIL]
    if fails:
        return f"❌ Verification FAILED — {len(fails)} check(s) did not pass: {', '.join(c.name for c in fails)}.", 1

    content = [c for c in checks if c.name.split(".")[0] in _CONTENT_CHECKS]
    verified = [c.name for c in content if c.status == PASS]
    skipped = [c.name for c in content if c.status == SKIP]

    if not verified:
        return (
            "⚠️  NOT verified — the bundle is intact, but every content check was skipped "
            f"({', '.join(skipped) or 'none ran'}). An incomplete bundle proves nothing "
            "about its numbers, spec, or citations.",
            1,
        )
    banner = f"✅ Bundle verified — {len(verified)} content check(s) passed ({', '.join(verified)})"
    if skipped:
        banner += f"; {len(skipped)} skipped ({', '.join(skipped)})"
    return banner + "; every file matches provenance.json.", 0


def _anchor_line(checks: list[Check], bundle: Path) -> str:
    """Which anchor the verdict rests on. Without one outside the folder, say so."""
    published = next((c for c in checks if c.name == "published"), None)
    if published is not None and published.status == PASS:
        return f"   anchor: e2er.org — {published.detail}"
    hint = ""
    link = _load_json(bundle / ".e2er" / "link.json")
    if isinstance(link, dict) and link.get("platform_url") and link.get("owner_project"):
        hint = f" (to compare with e2er.org: --against {link['platform_url']}/{link['owner_project']})"
    return f"   anchor: none outside the folder — verified against the folder only{hint}"


def _render(checks: list[Check], bundle: Path | None = None) -> str:
    width = max((len(c.name) for c in checks), default=0)
    sym = {PASS: "✓", SKIP: "·", FAIL: "✗"}
    lines = [f"  {sym[c.status]} [{c.status}] {c.name.ljust(width)}  {c.detail}" for c in checks]
    lines.append("\n" + _verdict(checks)[0])
    if bundle is not None:
        lines.append(_anchor_line(checks, bundle))
    return "\n".join(lines)


def verify(
    bundle: str,
    *,
    online: bool = False,
    json_output: bool = False,
    against: str | None = None,
    against_file: str | None = None,
) -> int:
    """Entry point for ``e2er verify``. Exit 0 iff nothing FAILed AND at least
    one content check (numbers/tables/spec/citations/…) actually ran.

    ``against`` (an e2er.org study or dossier address, fetched with GET) or
    ``against_file`` (a saved copy of one) compares the folder with what was
    published: the only anchor outside the folder.
    """
    import contextlib

    from .core.export import package as pkg

    bundle_path = Path(bundle)
    with contextlib.ExitStack() as stack:
        pre: list[Check] = []
        left_out: dict[str, dict[str, Any]] | None = None
        if pkg.is_package(bundle_path):
            # A .e2er package: unpacked into a temporary folder, every file checked against its manifest first.
            tmp = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="e2er-verify-")))
            try:
                opened = pkg.open_package(bundle_path, tmp / "study")
            except pkg.PackageError as e:
                if json_output:
                    print(
                        json.dumps(
                            {
                                "checks": [{"name": "package", "status": FAIL, "detail": str(e)}],
                                "verdict": f"The package is not intact: {e}",
                                "verified": False,
                            },
                            indent=2,
                        )
                    )
                else:
                    print(f"e2er verify: the package is not intact: {e}", file=sys.stderr)
                return 1
            pre.append(
                Check(
                    "package",
                    PASS,
                    f"{opened.files} file(s) match {pkg.MANIFEST}; fingerprint {opened.manifest.get('fingerprint')}",
                )
            )
            bundle_path = opened.root
            # The manifest's declarations are the packer's word: only those the study's own records support
            # count (a source's terms, larger than the host takes), as in a folder.
            left_out = pkg.supported_left_out(bundle_path)
        elif not bundle_path.is_dir():
            print(f"e2er verify: {bundle} is not a folder or a .e2er package", file=sys.stderr)
            return 2
        return _verify_folder(bundle_path, pre, online, json_output, against, against_file, left_out)
    return 2  # not reached


def _verify_folder(
    bundle_path: Path,
    pre: list[Check],
    online: bool,
    json_output: bool,
    against: str | None,
    against_file: str | None,
    package_left_out: dict[str, dict[str, Any]] | None = None,
) -> int:
    checks = pre + _run_checks(bundle_path, online, package_left_out)
    if against or against_file:
        try:
            if against:
                kind, record = _fetch_published(against)
                source, short = against, (against.rstrip("/").rsplit("/", 1)[-1] if "/d/" in against else None)
            else:
                kind, record = _read_published_file(str(against_file))
                source, short = str(against_file), None
            checks.append(_check_against(bundle_path, kind, record, source, short))
        except AgainstError as e:
            checks.append(Check("published", FAIL, str(e)))
    banner, code = _verdict(checks)
    # Everything printed is computed first: the verdict is never followed by a crash.
    av = _availability(bundle_path)
    try:
        from .core.availability import describe

        av_line = describe(av) if av is not None else None
    except (AttributeError, KeyError, TypeError):
        av_line = "stated in e2er.json, but not readable (see the anchor check)"
    writing = _writing_notes(bundle_path)
    if json_output:
        from dataclasses import asdict

        from . import __version__

        published = next((c for c in checks if c.name == "published"), None)
        # The content id (SHA-256 of provenance.json) and the version let a platform
        # match this result to the published study version (e.g. from GitHub Actions).
        print(
            json.dumps(
                {
                    "checks": [asdict(c) for c in checks],
                    "verdict": banner,
                    "verified": code == 0,
                    "anchor": "e2er.org" if published is not None and published.status == PASS else "folder only",
                    "e2er_version": __version__,
                    "content_id": _content_id(bundle_path),
                    "availability": av if isinstance(av, dict) else None,
                    "writing_notes": writing,
                },
                indent=2,
            )
        )
    else:
        print(_render(checks, bundle_path))
        if av_line is not None:
            print(f"   availability: {av_line}")
        if writing:
            # A note on the prose, not a check: it changes neither the verdict nor the exit code.
            print(f"   note: {len(writing)} sentence(s) use a construction the writing guidance rejects:")
            for line in writing[:20]:
                print(f"     - {line}")
            if len(writing) > 20:
                print(f"     ... and {len(writing) - 20} more")
    return code


def _writing_notes(bundle: Path) -> list[str]:
    """Constructions the researcher rejects, in the paper's prose: a note, never a failed check.

    The same phrase check the draft writers' output contract applies
    (``core.writing_check``), on ``paper/paper.tex`` and ``paper/abstract.tex``.
    """
    from .core.writing_check import find_in_file

    notes: list[str] = []
    for rel in ("paper/paper.tex", "paper/abstract.tex"):
        path = bundle / rel
        if path.is_file():
            notes += [f"{rel}: {h.line()}" for h in find_in_file(path, bundle / "results")]
    return notes


def _availability(bundle: Path) -> Any:
    """Data and code availability as stated when publishing (from e2er.json), if published."""
    manifest = _load_json(bundle / "e2er.json")
    return manifest.get("availability") if isinstance(manifest, dict) else None
