"""Build a replay fixture from a recorded demonstration run (run by hand, read-only on the source).

    python -m tests.replay.extract fomc --workspace <run workspace> --db <run database> --out tests/fixtures/replay/fomc
    python -m tests.replay.extract replication --workspace <run workspace> --db <run database> \
        --out tests/fixtures/replay/replication

The source workspace and database are only read. What is copied:

* for each specialist, the files it wrote, in their final recorded version;
* the token counts of its last recorded call (``llm_usage``), so a replayed run
  costs what the real one did under a metered backend;
* nothing personal: absolute paths and the run's paper id are replaced by
  ``@@WORKSPACE@@`` and ``@@PAPER_ID@@`` (filled in again when replayed), no
  keys, no researcher remarks, no corpus excerpts. ``data.db`` is copied with
  ``VACUUM INTO`` (the tables the steps need, nothing else).

The fixtures in the repository were made with this script from the FOMC bank
event study (paper 9a623c39, 2026-09-28/29) and the replication demonstration
(paper 08af321d, 2026-09-28/10-01), both run with Claude Haiku through Claude Code.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
from pathlib import Path

#: Which files each specialist of the FOMC run wrote (final versions), workspace-relative.
FOMC_FILES: dict[str, list[str]] = {
    "idea_developer": ["paper_plan.md"],
    "literature_scanner": ["literature_review.md"],
    "identification_strategist": ["identification_strategy.md", "identification_spec.json", "event_design.json"],
    "data_architect": ["data_dictionary.json"],
    "data_analyst": ["data_summary.md", "summary_statistics.json", "figure_spec.json", "data.db"],
    "econometrics_specialist": ["econometric_spec.md", "run_estimation.py", "estimation_results.json"],
    "paper_drafter": ["paper_draft.tex", "table_spec.json"],
    "abstract_writer": ["abstract.tex"],
    "mechanism_reviewer": ["review_mechanism.md"],
    "technical_reviewer": ["review_technical.md"],
    "literature_reviewer": ["review_literature.md"],
    "writing_reviewer": ["review_writing.md"],
    "data_reviewer": ["review_data.md"],
    "identification_reviewer": ["review_identification.md"],
    "patch_revisor": ["paper_draft.tex.edits.json"],
    "replication_packager": ["replication/estimation.py", "replication/README.md"],
}

#: The strategist's plan for the initial phase, as the real run dispatched it (groups in order).
FOMC_INITIAL_GROUPS: list[list[str]] = [
    ["idea_developer", "literature_scanner", "identification_strategist"],
    ["data_architect"],
    ["data_analyst"],
    ["econometrics_specialist"],
    ["paper_drafter", "abstract_writer"],
]

REPLICATION_FILES: dict[str, list[str]] = {
    "replication_planner": ["replication_plan.json", "replication_plan.md"],
    "reproduction_comparer": ["reproduction_report.json", "reproduction_report.md"],
}

#: Columns kept in data.db (tables not listed keep every column): what the replayed steps read.
FOMC_DB_COLUMNS: dict[str, list[str]] = {
    "spy_prices": ["date", "close"],
    "kbe_prices": ["date", "close"],
    "xlf_prices": ["date", "close"],
    "dgs2": ["date", "value"],
}

SCENARIOS = {
    "fomc": {
        "files": FOMC_FILES,
        "initial_groups": FOMC_INITIAL_GROUPS,
        "db_columns": FOMC_DB_COLUMNS,
        "template": "event-study-finance",
        "source": "FOMC bank event study, e2er demonstration run 9a623c39 (2026-09-28/29), "
        "Claude Haiku 4.5 through Claude Code",
    },
    "replication": {
        "files": REPLICATION_FILES,
        "initial_groups": [],
        "template": "replication",
        "source": "Replication demonstration, e2er run 08af321d (2026-09-28 to 2026-10-01), "
        "Claude Haiku 4.5 through Claude Code",
    },
}


def _scrub(text: str, workspace: Path, paper_id: str) -> str:
    text = text.replace(str(workspace) + "/", "@@WORKSPACE@@/").replace(str(workspace), "@@WORKSPACE@@")
    return text.replace(paper_id, "@@PAPER_ID@@")


def _trim_db(path: Path, keep: dict[str, list[str]]) -> None:
    """Drop the columns no replayed step reads, then compact the file."""
    con = sqlite3.connect(path)
    try:
        for table, cols in keep.items():
            col_list = ", ".join(f'"{c}"' for c in cols)
            con.execute(f'CREATE TABLE "_keep" AS SELECT {col_list} FROM "{table}"')
            con.execute(f'DROP TABLE "{table}"')
            con.execute(f'ALTER TABLE "_keep" RENAME TO "{table}"')
        con.commit()
        con.execute("VACUUM")
    finally:
        con.close()


def _last_usage(db: Path, paper_id: str) -> dict[str, dict[str, int | str]]:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT specialist, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, model "
            "FROM llm_usage WHERE paper_id = ? ORDER BY created_at, rowid",
            (paper_id,),
        ).fetchall()
    finally:
        con.close()
    out: dict[str, dict[str, int | str]] = {}
    for sp, i, o, cr, cw, model in rows:
        out[sp] = {
            "input_tokens": i,
            "output_tokens": o,
            "cache_read_tokens": cr,
            "cache_write_tokens": cw,
            "model": model,
        }
    return out


def extract(name: str, workspace: Path, db: Path, out: Path) -> None:
    spec = SCENARIOS[name]
    manifest = json.loads((workspace / "manifest.json").read_text(encoding="utf-8"))
    paper_id = manifest["paper_id"]
    usage = _last_usage(db, paper_id)
    files_root = out / "files"
    if files_root.exists():
        shutil.rmtree(files_root)
    specialists: dict[str, dict] = {}
    for sp, rels in spec["files"].items():
        for rel in rels:
            src, dest = workspace / rel, files_root / sp / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            if rel.endswith(".db"):
                con = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
                try:
                    con.execute("VACUUM INTO ?", (str(dest),))
                finally:
                    con.close()
                _trim_db(dest, spec.get("db_columns") or {})
                continue
            raw = src.read_bytes()
            try:
                dest.write_text(_scrub(raw.decode("utf-8"), workspace, paper_id), encoding="utf-8")
            except UnicodeDecodeError:
                dest.write_bytes(raw)
        u = usage.get(sp, {})
        specialists[sp] = {
            "files": rels,
            "output": f"Wrote {', '.join(rels)}.",
            "usage": {k: v for k, v in u.items() if k != "model"},
        }
    scenario = {
        "name": name,
        "source": spec["source"],
        "template": spec["template"],
        "research_question": manifest["research_question"],
        "title": manifest["title"],
        "model": next((u["model"] for u in usage.values() if u.get("model")), "unknown"),
        "initial_groups": spec["initial_groups"],
        "specialists": specialists,
    }
    if name == "replication":
        scenario["sandbox"] = _replication_sandbox(workspace, out)
        scenario["zenodo"] = _replication_record(workspace, out)
    (out / "scenario.json").write_text(json.dumps(scenario, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


#: Package files kept besides the entry-point scripts and the result files they write.
REPLICATION_KEEP = ("README.md", "AMBIENTE.md", "MAPA_REPRODUCAO.md")


def _replication_sandbox(workspace: Path, out: Path) -> dict:
    """The recorded environment and, per entry point, the files it wrote (copied to files/sandbox/run)."""
    plan = json.loads((workspace / "replication_plan.json").read_text(encoding="utf-8"))
    log = json.loads((workspace / "sandbox_log.json").read_text(encoding="utf-8"))
    run_root = workspace / str(log.get("run_dir") or "sandbox/run")
    eps = []
    for ep in plan["entry_points"]:
        cwd = str(ep.get("cwd") or ".").strip("/")
        produces = []
        for rel in ep.get("produces") or []:
            run_rel = rel if cwd in ("", ".") else f"{cwd}/{rel}"
            src = run_root / run_rel
            if src.is_file():
                dest = out / "files" / "sandbox" / "run" / run_rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(src.read_bytes())
                produces.append(run_rel)
        eps.append({"id": ep["id"], "script": ep["command"][-1], "produces": produces})
    return {
        "image_digest": log.get("image_digest"),
        "platform": (log.get("install") or {}).get("platform"),
        "repos": (log.get("snapshot") or {}).get("url"),
        "installed": (log.get("install") or {}).get("installed") or {},
        "entry_points": eps,
    }


def _replication_record(workspace: Path, out: Path) -> dict:
    """A Zenodo record serving a trimmed package: scripts, shipped results, documentation."""
    import hashlib
    import zipfile

    manifest = json.loads((workspace / "package_manifest.json").read_text(encoding="utf-8"))
    plan = json.loads((workspace / "replication_plan.json").read_text(encoding="utf-8"))
    package = workspace / "package"
    root = manifest.get("package_root") or "."
    keep: set[str] = set()
    for ep in plan["entry_points"]:
        cwd = str(ep.get("cwd") or ".").strip("/")
        for c in ep["command"][1:]:
            if not c.startswith("-"):
                keep.add(c if cwd in ("", ".") else f"{cwd}/{c}")
        for rel in ep.get("produces") or []:
            keep.add(rel if cwd in ("", ".") else f"{cwd}/{rel}")
    for t in plan.get("targets") or []:
        if (t.get("source") or {}).get("file"):
            keep.add(t["source"]["file"])
    for name in REPLICATION_KEEP:
        keep.add(name if root in ("", ".") else f"{root}/{name}")
    keep = {k for k in keep if (package / k).is_file()}
    rec_dir = out / "zenodo" / str(manifest["record_id"])
    if rec_dir.exists():
        shutil.rmtree(rec_dir)
    (rec_dir / "files").mkdir(parents=True)
    key = manifest["files"][0]["key"]
    archive = rec_dir / "files" / key
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in sorted(keep):
            info = zipfile.ZipInfo(rel, date_time=(2026, 8, 30, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, (package / rel).read_bytes())
    data = archive.read_bytes()
    record = {
        "id": int(manifest["record_id"]),
        "doi": manifest["doi"],
        "links": {"html": manifest["url"]},
        "access": {"files": "open"},
        "metadata": {
            "title": manifest["title"],
            "creators": [{"name": c} for c in manifest.get("creators") or []],
            "license": {"id": manifest.get("licence") or ""},
            "publication_date": manifest.get("publication_date") or "",
            "version": manifest.get("version") or "",
            "related_identifiers": [
                {
                    "identifier": p["identifier"],
                    "relation": p.get("relation") or "isSupplementTo",
                    "resource_type": p.get("resource_type") or "publication-article",
                }
                for p in manifest.get("publications") or []
                if p.get("from") == "related"
            ],
            "description": "Trimmed copy for the e2er end-to-end tests: the entry-point scripts, the result "
            "files they write and the documentation of the published package.",
        },
        "files": [{"key": key, "size": len(data), "checksum": "md5:" + hashlib.md5(data).hexdigest()}],
    }
    (rec_dir / "record.json").write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"record_id": manifest["record_id"], "doi": manifest["doi"], "files": len(keep)}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("scenario", choices=sorted(SCENARIOS))
    p.add_argument("--workspace", required=True, type=Path)
    p.add_argument("--db", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    extract(a.scenario, a.workspace.expanduser().resolve(), a.db.expanduser(), a.out)
    print(f"wrote {a.out}")


if __name__ == "__main__":
    main()
