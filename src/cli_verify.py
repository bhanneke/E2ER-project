"""``e2er verify <bundle>`` — offline, keyless verification of an export bundle.

The reviewer's cheap-verification moment (make verification cheap): given a
bundle produced by ``e2er export``, re-establish that it is internally
consistent and untampered — in seconds, with no API keys and, by default, no
network at all:

  1. integrity   — re-hash every file against provenance.json (SHA-256)
  2. numbers     — re-run the numbers gate: table cells vs source JSON
  3. spec        — re-check the estimation implements the declared identification
  4. citations   — every \\cite resolves in refs.bib (registry status is read
                   from the bundled snapshot; ``--online`` re-queries live)

Checks 1–4 never touch the network. ``--online`` adds a live registry
re-verification of the citations. Recomputation is authoritative: the bundled
reports are compared against a fresh computation, so an edited report or an
edited paper is caught.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
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


def _check_integrity(bundle: Path) -> Check:
    prov = _load_json(bundle / "provenance.json")
    if not isinstance(prov, dict) or "files" not in prov:
        return Check("integrity", FAIL, "no valid provenance.json in bundle")
    files = prov["files"]
    missing, mismatched = [], []
    for rel, meta in files.items():
        p = bundle / rel
        if not p.is_file():
            missing.append(rel)
        elif _sha256(p) != meta.get("sha256"):
            mismatched.append(rel)
    on_disk = {
        p.relative_to(bundle).as_posix() for p in bundle.rglob("*") if p.is_file() and p.name != "provenance.json"
    }
    extra = sorted(on_disk - set(files))
    if missing or mismatched or extra:
        bits = []
        if mismatched:
            bits.append(f"{len(mismatched)} modified ({', '.join(mismatched[:3])})")
        if missing:
            bits.append(f"{len(missing)} missing ({', '.join(missing[:3])})")
        if extra:
            bits.append(f"{len(extra)} unlisted ({', '.join(extra[:3])})")
        return Check("integrity", FAIL, "; ".join(bits))
    return Check("integrity", PASS, f"{len(files)} files hash-verified against provenance.json")


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


# ── check 2: numbers ─────────────────────────────────────────────────────────


def _check_numbers(bundle: Path, ws: Path) -> Check:
    tex = bundle / "paper" / "paper.tex"
    if not tex.is_file():
        return Check("numbers", SKIP, "no paper/paper.tex")
    from .core.pipeline.verify_numbers import verify as verify_numbers

    report = verify_numbers(tex, ws)
    if report.skipped_reason:
        return Check("numbers", SKIP, report.skipped_reason)
    crit = report.critical_mismatches
    if crit:
        first = "; ".join(f"{m.draft_value} vs {m.source_value} ({m.source_key})" for m in crit[:3])
        return Check("numbers", FAIL, f"{len(crit)} critical mismatch(es) on recompute: {first}")
    return Check("numbers", PASS, f"{report.matched} table cell(s) trace, 0 critical mismatches")


# ── check 3: spec contract ───────────────────────────────────────────────────


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


# ── check 4: citations (offline) ─────────────────────────────────────────────


def _check_citations_offline(bundle: Path) -> Check:
    tex = bundle / "paper" / "paper.tex"
    if not tex.is_file():
        return Check("citations", SKIP, "no paper/paper.tex")
    from .core.pipeline.verify_citations import load_bib, parse_cite_keys

    keys = parse_cite_keys(tex.read_text(encoding="utf-8", errors="replace"))
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


def _run_checks(bundle: Path, online: bool) -> list[Check]:
    checks = [_check_integrity(bundle)]
    with tempfile.TemporaryDirectory() as td:
        ws = Path(td)
        _reconstruct_workspace(bundle, ws)
        checks.append(_check_numbers(bundle, ws))
        checks.append(_check_spec(ws))
        checks.append(_check_citations_offline(bundle))
    if online:
        checks.append(asyncio.run(_check_citations_online(bundle)))
    return checks


def _render(checks: list[Check]) -> str:
    width = max((len(c.name) for c in checks), default=0)
    sym = {PASS: "✓", SKIP: "·", FAIL: "✗"}
    lines = [f"  {sym[c.status]} [{c.status}] {c.name.ljust(width)}  {c.detail}" for c in checks]
    n_fail = sum(c.status == FAIL for c in checks)
    if n_fail == 0:
        lines.append("\n✅ Bundle verified — hashes, numbers, spec, and citations are internally consistent.")
    else:
        lines.append(f"\n❌ Verification FAILED — {n_fail} check(s) did not pass (see above).")
    return "\n".join(lines)


def verify(bundle: str, *, online: bool = False, json_output: bool = False) -> int:
    """Entry point for ``e2er verify``. Exit 0 iff no check FAILed."""
    bundle_path = Path(bundle)
    if not bundle_path.is_dir():
        print(f"e2er verify: {bundle} is not a directory", file=sys.stderr)
        return 2
    checks = _run_checks(bundle_path, online)
    if json_output:
        from dataclasses import asdict

        print(json.dumps({"checks": [asdict(c) for c in checks]}, indent=2))
    else:
        print(_render(checks))
    return 1 if any(c.status == FAIL for c in checks) else 0
