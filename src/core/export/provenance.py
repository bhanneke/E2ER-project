"""Content-addressed provenance manifest for an exported bundle (WS-P4.1).

`provenance.json` is a self-contained inventory + derivation graph written at
export time:

  * ``files`` — every file in the bundle with its SHA-256 and size. This is
    the integrity backbone: ``e2er verify`` re-hashes each file against it, so
    any post-export tampering is detected.
  * ``run`` — the regime the paper ran under (governance / backend / model)
    plus the e2er version, so a bundle discloses its own provenance.
  * ``edges`` — derivation links reconstructed from the gate reports already
    in the bundle: table cells → source JSON keys, citations → registry,
    figures → figure spec, estimation → script, data → queries.

Derived entirely from artifacts already in the bundle — it never re-runs an
analysis. Best-effort: a missing/short report degrades an edge type to empty
rather than raising.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

PROVENANCE_FILE = "provenance.json"
SCHEMA_ID = "e2er-provenance/1"

_CHUNK = 65536


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def _e2er_version() -> str:
    try:
        from importlib.metadata import version

        return version("e2er")
    except Exception:  # noqa: BLE001 — version is best-effort metadata
        return "unknown"


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — missing/short report → skip its edges
        return None


def inventory(bundle: Path) -> dict[str, dict[str, Any]]:
    """SHA-256 + byte size for every file in the bundle, read as verify reads it.

    Keys are NFC, POSIX, bundle-relative paths, sorted for determinism. Left
    out: the root-level files that are not evidence (provenance.json itself;
    e2er.json and .e2er/ written by publish) and operating-system clutter; see
    bundle_files.py. Symbolic links are never followed (export writes none).
    """
    from .bundle_files import NOT_EVIDENCE, walk

    listing = walk(bundle)
    return {
        rel: {"sha256": _sha256(p), "bytes": p.stat().st_size}
        for rel, p in sorted(listing.files.items())
        if rel not in NOT_EVIDENCE
    }


def _source_key_file(bundle: Path, source_key: str) -> str | None:
    """Which results/*.json a flattened numeric key came from.

    ``verify_numbers`` flattens each source file with the FILENAME as prefix
    (``estimation_results.json.main.coefficients.x.estimate``), so the answer
    is already encoded in the key — match the prefix rather than re-flattening
    (a re-flatten without the same prefix produces keys that never match, which
    silently nulled every cell's source attribution)."""
    from ..pipeline.verify_numbers import _SOURCE_JSON_FILES

    for fn in _SOURCE_JSON_FILES:
        if source_key == fn or source_key.startswith((f"{fn}.", f"{fn}[")):
            return f"results/{fn}" if (bundle / "results" / fn).is_file() else None
    return None


def _edges(bundle: Path) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []

    # table_cell: a LaTeX table cell that traced to a source JSON key.
    nv = _load_json(bundle / "results" / "number_verification.json")
    if isinstance(nv, dict):
        for cell in nv.get("matched_cells", []):
            key = cell.get("source_key", "")
            edges.append(
                {
                    "type": "table_cell",
                    "output": "paper/paper.tex",
                    "cell_value": cell.get("draft_value"),
                    "table_context": cell.get("table_context"),
                    "source_key": key,
                    "source": _source_key_file(bundle, key),
                }
            )

    # citation: each cited key with its registry-verification status.
    ci = _load_json(bundle / "reviews" / "citation_integrity.json")
    if isinstance(ci, dict):
        for c in ci.get("checks", []):
            doi = c.get("matched_doi") or c.get("bib_doi")
            edges.append(
                {
                    "type": "citation",
                    "output": "paper/paper.tex",
                    "key": c.get("cite_key"),
                    "status": c.get("status"),
                    "registry": c.get("verifier") or None,
                    "external_id": f"doi:{doi}" if doi else None,
                }
            )

    # figure: rendered figures declared by the figure spec.
    figdir = bundle / "results" / "figures"
    if (bundle / "results" / "figure_spec.json").is_file() and figdir.is_dir():
        for fig in sorted(figdir.iterdir()):
            if fig.is_file():
                edges.append(
                    {
                        "type": "figure",
                        "output": f"results/figures/{fig.name}",
                        "source": "results/figure_spec.json",
                    }
                )

    # estimation: results produced by the (orchestrator-executed) script.
    if (bundle / "results" / "estimation_results.json").is_file():
        edge: dict[str, Any] = {"type": "estimation", "output": "results/estimation_results.json"}
        if (bundle / "code" / "run_estimation.py").is_file():
            edge["script"] = "code/run_estimation.py"
        if (bundle / "code" / "scratch" / "run_estimation.log").is_file():
            edge["log"] = "code/scratch/run_estimation.log"
        edges.append(edge)

    # data: the warehouse built from the recorded queries.
    if (bundle / "data" / "data.db").is_file():
        edge = {"type": "data", "output": "data/data.db"}
        if (bundle / "replication" / "data_queries.sql").is_file():
            edge["queries"] = "replication/data_queries.sql"
        if (bundle / "data" / "data_sources.json").is_file():
            edge["sources"] = "data/data_sources.json"
        edges.append(edge)

    return edges


def _preregistration(bundle: Path) -> dict[str, Any] | None:
    """The frozen pre-registration the bundle carries (file, fingerprint, time), if any.

    Recorded in ``run`` so that ``e2er verify`` knows the study had one: a
    bundle whose lock file later disappears then fails instead of losing the
    check.
    """
    try:
        from ..pipeline.preregistration import load_lock

        lock = load_lock(bundle / "design")
    except Exception:  # noqa: BLE001 — an unreadable lock is reported by verify itself
        lock = None
    if not isinstance(lock, dict):
        return None
    return {
        "file": f"design/{lock.get('file', 'preregistration.md')}",
        "sha256": lock.get("sha256"),
        "frozen_at": lock.get("frozen_at"),
    }


def build_provenance(bundle: Path, manifest: dict[str, Any], *, exported_at: str) -> dict[str, Any]:
    run: dict[str, Any] = {
        "paper_id": manifest.get("paper_id"),
        "backend": manifest.get("backend"),
        "model": manifest.get("model"),
        "governance": manifest.get("governance") or "full",
        # the template the study was run with; `e2er publish` reads it from here
        "template": manifest.get("pipeline") or None,
        "e2er_version": _e2er_version(),
        "exported_at": exported_at,
    }
    # The study's purpose as chosen when it started (publish honours it), and
    # the frozen pre-registration (verify then requires its check).
    if manifest.get("purpose"):
        run["purpose"] = manifest["purpose"]
    prereg = _preregistration(bundle)
    if prereg is not None:
        run["preregistration"] = prereg
    return {
        "schema": SCHEMA_ID,
        "run": run,
        "files": inventory(bundle),
        "edges": _edges(bundle),
    }


def dump(prov: dict[str, Any]) -> str:
    """provenance.json's text: the same layout every time it is written."""
    return json.dumps(prov, indent=2, ensure_ascii=False) + "\n"


def write_provenance(bundle: Path, manifest: dict[str, Any], *, exported_at: str) -> Path:
    """Write ``<bundle>/provenance.json`` and return its path. Call AFTER every
    other bundle file exists (README and report.html included) so the inventory is complete."""
    out = bundle / PROVENANCE_FILE
    out.write_text(dump(build_provenance(bundle, manifest, exported_at=exported_at)), encoding="utf-8")
    return out


def files_at_export(prov: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """provenance.json's ``files`` as they were at export: every amendment rolled back.

    A file publish changed gets its exported fingerprint back (the first
    amendment's ``sha256_before``); a file publish added (``sha256_before``
    None) is left out. The size of a changed file is not kept, so it is None.
    """
    files = {k: dict(v) for k, v in (prov.get("files") or {}).items()}
    first: dict[str, Any] = {}
    for a in prov.get("amendments") or []:
        path = a.get("path") if isinstance(a, dict) else None
        if isinstance(path, str) and path not in first:
            first[path] = a.get("sha256_before")
    for path, before in first.items():
        if before is None:
            files.pop(path, None)
        elif path in files:
            files[path] = {"sha256": before, "bytes": None}
    return files


def amend(bundle: Path, rel: str, reason: str, *, at: str) -> dict[str, Any] | None:
    """Record that ``rel`` changed after export: its new fingerprint, and an amendment.

    The amendment keeps the fingerprint the file had (``sha256_before``; None
    for a file the bundle did not have), the new one and why it changed, so
    the exported hash is never lost. Returns the amendment, or None when the
    file is unchanged. The caller must have checked the bundle against
    provenance.json first: the "before" is the listed fingerprint.
    """
    path = bundle / PROVENANCE_FILE
    prov = json.loads(path.read_text(encoding="utf-8"))
    f = bundle / rel
    data = f.read_bytes()
    after = hashlib.sha256(data).hexdigest()
    meta = prov["files"].get(rel)
    if meta is not None and meta.get("sha256") == after:
        return None
    entry = {
        "path": rel,
        "sha256_before": meta.get("sha256") if meta else None,
        "sha256_after": after,
        "reason": reason,
        "at": at,
    }
    prov["files"][rel] = {"sha256": after, "bytes": len(data)}
    prov["files"] = dict(sorted(prov["files"].items()))
    prov.setdefault("amendments", []).append(entry)
    path.write_text(dump(prov), encoding="utf-8")
    return entry
