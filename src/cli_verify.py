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
    # provenance.json cannot inventory itself; report.html is a rendering of the
    # bundle written after it, and asserts nothing the hashed files do not.
    # e2er.json (written by `e2er publish`) describes the bundle and records the
    # digest of provenance.json itself, so it is not part of the evidence either;
    # nor is .e2er/, where `e2er publish --to` notes which platform holds the study.
    _NOT_EVIDENCE = {"provenance.json", "report.html", "e2er.json"}
    on_disk = {
        p.relative_to(bundle).as_posix()
        for p in bundle.rglob("*")
        if p.is_file() and p.name not in _NOT_EVIDENCE and p.relative_to(bundle).parts[0] != ".e2er"
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
    return Check(
        "integrity",
        PASS,
        f"{len(files)} files hash-verified against provenance.json; "
        f"{_table_cell_edges(prov)} table cell(s) traced in the derivation graph",
    )


def _table_cell_edges(prov: dict) -> int:
    edges = prov.get("edges")
    if not isinstance(edges, list):
        return 0
    return sum(1 for e in edges if isinstance(e, dict) and e.get("type") == "table_cell")


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
    if not report.tables_conclusive and _bundle_has_rendered_tables(bundle):
        # The paper ships rendered tables and the check traced no cell in any of
        # them. That is not a pass: it is the gate failing to run on the one
        # channel the anti-fabrication claim rests on, and it must not print the
        # same tick as a run that checked every number.
        return Check(
            "numbers",
            FAIL,
            "0 table cell(s) traced although the paper ships rendered tables — the numbers check did not run on them",
        )
    return Check("numbers", PASS, f"{report.matched} table cell(s) trace, 0 critical mismatches")


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


def _check_tables(bundle: Path, ws: Path) -> Check:
    """Re-render the declared tables and compare them byte for byte."""
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
        checks.append(_check_tables(bundle, ws))
        checks.append(_check_spec(ws))
        checks.append(_check_citations_offline(bundle))
    if online:
        checks.append(asyncio.run(_check_citations_online(bundle)))
    return checks


# The checks that actually verify CONTENT. Integrity (hashing files against
# provenance.json) proves only that the bundle is unchanged since export — a
# bundle can be perfectly self-consistent and still have had nothing checked.
_CONTENT_CHECKS = frozenset({"numbers", "spec", "citations"})


def _verdict(checks: list[Check]) -> tuple[str, int]:
    """Final banner + exit code.

    A SKIP is NOT a pass. Export is best-effort and can emit a partial bundle
    (e.g. no paper.tex → numbers/spec/citations all skip); reporting that as
    "verified" would be the single most misleading thing this command could
    say, since the whole point is cheap, honest verification.
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
    if skipped:
        return (
            f"✅ Bundle verified — {len(verified)} content check(s) passed ({', '.join(verified)}); "
            f"{len(skipped)} skipped ({', '.join(skipped)}).",
            0,
        )
    return (
        "✅ Bundle verified — hashes, tables, numbers, spec, and citations are internally consistent.",
        0,
    )


def _render(checks: list[Check]) -> str:
    width = max((len(c.name) for c in checks), default=0)
    sym = {PASS: "✓", SKIP: "·", FAIL: "✗"}
    lines = [f"  {sym[c.status]} [{c.status}] {c.name.ljust(width)}  {c.detail}" for c in checks]
    lines.append("\n" + _verdict(checks)[0])
    return "\n".join(lines)


def verify(bundle: str, *, online: bool = False, json_output: bool = False) -> int:
    """Entry point for ``e2er verify``. Exit 0 iff nothing FAILed AND at least
    one content check (numbers/spec/citations) actually ran."""
    bundle_path = Path(bundle)
    if not bundle_path.is_dir():
        print(f"e2er verify: {bundle} is not a directory", file=sys.stderr)
        return 2
    checks = _run_checks(bundle_path, online)
    banner, code = _verdict(checks)
    if json_output:
        from dataclasses import asdict

        from . import __version__

        prov = bundle_path / "provenance.json"
        # The content id (SHA-256 of provenance.json) and the version let a platform
        # match this result to the published study version (e.g. from GitHub Actions).
        print(
            json.dumps(
                {
                    "checks": [asdict(c) for c in checks],
                    "verdict": banner,
                    "verified": code == 0,
                    "e2er_version": __version__,
                    "content_id": f"sha256:{_sha256(prov)}" if prov.is_file() else None,
                },
                indent=2,
            )
        )
    else:
        print(_render(checks))
    return code
