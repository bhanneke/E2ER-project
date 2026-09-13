"""Let a ``table_spec.json`` author see what the renderer sees.

WHY THIS EXISTS

``table_spec.json`` is written blind. ``paper_drafter`` authors it as a sidecar
(``registry.SPECIALIST_SIDECAR_ARTIFACTS``) and ``section_writer`` repairs it
(``runner._table_spec_repair_directive``), and neither can render. Whether a
spec is valid is purely a function of the JSON sidecars sitting next to it —
``render_tables`` resolves each stat ``field`` *inside its own column's spec
object*, by lookup, never by arithmetic — and the author cannot see those
objects' key structure at authoring time.

Canary #6 (paper ``8d3d9ce6``, commit ``4126714``) is the cost. A ``comparison``
column asked for the same six stat rows as ``pre_etf``/``post_etf``, but
``estimation_results.json['comparison']`` holds only five delta keys. Ten
unresolved references, ``render_all_or_halt`` fired, and the repair pass went
7 -> 10 because the repairer was guessing too.

This is the ``e2er-run`` treatment for specs: commit ``eff7ae1`` gave the two
script-writing specialists a guarded way to run what they wrote and read the
traceback; this gives the two spec-writing specialists a guarded way to render
what they wrote and read the unresolved list. Same loop, same reason.

It is a REPORT, not a gate. The runner still re-renders deterministically
before the verify gate and compile (see the ``tables`` module docstring), so
provenance comes from that render and not from whatever the model did while
iterating. Re-rendering here is safe for exactly that reason: it is idempotent,
and every artifact it touches is rewritten by the runner anyway.

The available-key lists come from the renderer's OWN helpers (``_stat_field_names``,
``_resolve_by_tokens``), not from a second opinion about what a spec object
contains. A checker that reports keys the renderer would not accept — or omits
ones it would — is worse than no checker, because it sends the author looking
in the wrong place.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from .tables import (
    RenderReport,
    UnresolvedRef,
    _load_json,
    _resolve_by_tokens,
    _spec_name,
    _stat_field_names,
    render_tables,
)

#: The sidecars ``render_tables`` merges, in its order — estimation first,
#: robustness overlaying by its own distinct keys. Kept in step with
#: ``tables.render_tables``; if that gains a source, this must gain it too, or
#: the checker will report a missing key the renderer can actually find.
_SOURCE_FILES = ("estimation_results.json", "robustness_results.json")

EXIT_OK = 0
EXIT_UNRESOLVED = 1
EXIT_CANNOT_CHECK = 2


def _sources(workspace: Path) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for name in _SOURCE_FILES:
        merged.update(_load_json(workspace / name))
    return merged


def _spec_keys(sources: dict[str, Any]) -> list[str]:
    """Top-level keys eligible to be a column's ``spec_key`` — the renderer
    only matches dict-valued entries (``dict_keys`` in ``_render_one_table``)."""
    return sorted(k for k, v in sources.items() if isinstance(v, dict))


def _spec_by_key(sources: dict[str, Any], spec_key: str) -> dict[str, Any] | None:
    """The spec object a column resolves to, by the renderer's own rules —
    exact key first, then the order-insensitive token match."""
    obj = sources.get(spec_key)
    if isinstance(obj, dict):
        return obj
    nk = _resolve_by_tokens(spec_key, _spec_keys(sources))
    got = sources.get(nk) if nk else None
    return got if isinstance(got, dict) else None


def _spec_by_label(sources: dict[str, Any], label: str) -> dict[str, Any] | None:
    """Find a spec object by its ``specification`` string.

    Needed because an unresolved *coefficient* records ``_spec_name(spec_obj)``
    in its ``column`` field — a human-readable label — where an unresolved
    *stat* records the column's ``spec_key``. Same field, two meanings.
    """
    for value in sources.values():
        if isinstance(value, dict) and _spec_name(value) == label:
            return value
    return None


def _coefficient_names(spec_obj: dict[str, Any]) -> list[str]:
    coeffs = spec_obj.get("coefficients")
    return sorted(coeffs) if isinstance(coeffs, dict) else []


def _group(refs: list[UnresolvedRef]) -> dict[str, dict[tuple[str, str], list[UnresolvedRef]]]:
    """table -> (kind, column) -> refs. Grouping by kind as well as column is
    what keeps the 'available keys' line honest: the two kinds key off
    different things."""
    out: dict[str, dict[tuple[str, str], list[UnresolvedRef]]] = {}
    for ref in refs:
        out.setdefault(ref.table, {}).setdefault((ref.kind, ref.column), []).append(ref)
    return out


def _describe(kind: str, column: str, refs: list[UnresolvedRef], sources: dict[str, Any]) -> list[str]:
    """The lines for one (kind, column) group: what is missing, and what exists."""
    missing = ", ".join(r.ref or "(empty)" for r in refs)

    if kind == "spec_key":
        # `column` is empty here; the offending key IS the ref.
        return [
            f"  column spec_key not found in the analysis JSON: {missing}",
            f"      available spec keys: {', '.join(_spec_keys(sources)) or '(none)'}",
        ]

    if kind == "coefficient":
        spec_obj = _spec_by_label(sources, column)
        head = f"  coefficients missing from spec {column!r}:" if column else "  coefficients missing:"
        lines = [head, f"      MISSING: {missing}"]
        if spec_obj is None:
            lines.append("      (could not locate that spec object to list its coefficients)")
        else:
            names = _coefficient_names(spec_obj)
            lines.append(f"      that spec HAS these coefficients: {', '.join(names) if names else '(none)'}")
        return lines

    # "stat" — `column` is the column's spec_key.
    spec_obj = _spec_by_key(sources, column)
    lines = [f"  column {column!r}" if column else "  (no column recorded)"]

    # A row with no `field` at all is a different defect from a row naming a
    # field that does not exist, and it needs a different instruction. Canary
    # #6's main.tex carried four of these — malformed rows emitted by the
    # repair pass, which nothing rejects. "MISSING stat fields: (empty)" tells
    # the author nothing; naming the shape does.
    named = [r.ref for r in refs if r.ref]
    empty = len(refs) - len(named)
    if empty:
        lines.append(
            f"      {empty} stat row(s) declare no 'field' at all — every "
            "{'type': 'stat'} row needs a non-empty 'field' naming a key below."
        )
    if named:
        lines.append(f"      MISSING stat fields: {', '.join(named)}")
    if spec_obj is None:
        lines.append("      that spec_key is not in the analysis JSON at all.")
        lines.append(f"      available spec keys: {', '.join(_spec_keys(sources)) or '(none)'}")
    else:
        names = sorted(_stat_field_names(spec_obj))
        lines.append(f"      that object HAS these fields: {', '.join(names) if names else '(none)'}")
    return lines


def format_report(report: RenderReport, sources: dict[str, Any]) -> str:
    """Render the unresolved list as something a model can act on.

    The load-bearing line is "that object HAS these fields". A bare "field not
    found" invites another guess; the actual list is what ends the loop.
    """
    if report.skipped_reason:
        return f"table_spec.json could not be checked: {report.skipped_reason}"

    out: list[str] = []
    if report.errors:
        out.append(f"{len(report.errors)} table(s) failed to render:")
        out += [f"  {e}" for e in report.errors]
        out.append("")

    if not report.unresolved:
        rendered = ", ".join(report.rendered) or "(none)"
        out.append(f"OK — every reference in table_spec.json resolved. Rendered: {rendered}")
        if report.normalized:
            out += [
                "",
                f"{len(report.normalized)} reference(s) resolved by fuzzy match rather than an exact "
                "key hit. These render correctly, but the spec reads more clearly using the JSON's own names:",
            ]
            out += [f"  {n.table}: {n.requested!r} -> {n.resolved!r}" for n in report.normalized]
        return "\n".join(out)

    grouped = _group(report.unresolved)
    out.append(f"{len(report.unresolved)} unresolved reference(s) across {len(grouped)} table(s).")
    out.append("")
    for table, groups in grouped.items():
        out.append(table)
        for (kind, column), refs in groups.items():
            out += _describe(kind, column, refs, sources)
        out.append("")

    out += [
        "The renderer LOOKS UP each field inside its own column's object. It never",
        "computes. A column derived from the others — a 'Change', 'Difference' or",
        "'% change' column — can only use keys that already exist in that object,",
        "such as delta_* / pct_change_*.",
        "",
        "Fix table_spec.json so every field names a key listed above, then run",
        "e2er-check-tables again. Do not invent keys, and do not move a number into",
        "the prose to avoid the check.",
    ]
    return "\n".join(out)


def check(workspace: Path) -> tuple[int, str]:
    """(exit code, human-readable report) for the spec in ``workspace``."""
    report = render_tables(workspace)
    text = format_report(report, _sources(workspace))
    if report.skipped_reason:
        return EXIT_CANNOT_CHECK, text
    return (EXIT_UNRESOLVED if report.unresolved else EXIT_OK), text


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) > 1:
        print("e2er-check-tables: takes no arguments", file=sys.stderr)
        return EXIT_CANNOT_CHECK
    # The wrapper passes the workspace it captured from `pwd` before cd'ing to
    # the project root. The model passes nothing — see scripts/e2er-check-tables.
    workspace = Path(args[0]) if args else Path.cwd()
    code, text = check(workspace)
    print(text)
    return code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
