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
    """SHA-256 + byte size for every file in the bundle (excluding the manifest
    itself). Keys are POSIX bundle-relative paths, sorted for determinism."""
    files: dict[str, dict[str, Any]] = {}
    for p in sorted(bundle.rglob("*")):
        if p.is_file() and p.name != PROVENANCE_FILE:
            rel = p.relative_to(bundle).as_posix()
            files[rel] = {"sha256": _sha256(p), "bytes": p.stat().st_size}
    return files


def _source_key_file(bundle: Path, source_key: str) -> str | None:
    """Which results/*.json a flattened numeric key came from — using the same
    flatten convention verify_numbers uses, so keys align exactly."""
    from ..pipeline.verify_numbers import _SOURCE_JSON_FILES, _flatten_json

    for fn in _SOURCE_JSON_FILES:
        data = _load_json(bundle / "results" / fn)
        if data is not None and source_key in _flatten_json(data):
            return f"results/{fn}"
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
        edges.append(edge)

    return edges


def build_provenance(bundle: Path, manifest: dict[str, Any], *, exported_at: str) -> dict[str, Any]:
    return {
        "schema": SCHEMA_ID,
        "run": {
            "paper_id": manifest.get("paper_id"),
            "backend": manifest.get("backend"),
            "model": manifest.get("model"),
            "governance": manifest.get("governance") or "full",
            "e2er_version": _e2er_version(),
            "exported_at": exported_at,
        },
        "files": inventory(bundle),
        "edges": _edges(bundle),
    }


def write_provenance(bundle: Path, manifest: dict[str, Any], *, exported_at: str) -> Path:
    """Write ``<bundle>/provenance.json`` and return its path. Call AFTER every
    other bundle file exists (incl. README) so the inventory is complete."""
    out = bundle / PROVENANCE_FILE
    out.write_text(
        json.dumps(build_provenance(bundle, manifest, exported_at=exported_at), indent=2),
        encoding="utf-8",
    )
    return out
