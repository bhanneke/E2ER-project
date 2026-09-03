"""Deterministic regression-table rendering — anti-fabrication by construction.

The drafter no longer hand-writes the numbers in results tables. Instead the
model authors a declarative ``table_spec.json`` (which specifications are
columns, which coefficients / statistics are rows, caption, notes), and this
module fills the numbers straight from the authoritative JSON sidecars
(``estimation_results.json`` / ``robustness_results.json``) into
``tables/<filename>.tex`` files that the draft ``\\input``s.

Because the cells come from the same computation that wrote the sidecar, a
results-table number cannot be fabricated or mis-transcribed — the failure
mode the ``verify_numbers`` gate exists to catch, removed at the source.

This is first-party deterministic code, called directly by the runner (see
``core/strategist/runner.py``). It is NOT an LLM specialist and NOT a
``post_execution`` script — the model's only contribution is the spec.

Design rules:
- **Never raise.** Every error path degrades to ``---`` in a cell and a
  recorded entry in ``table_render_report.json`` — a *detectable* missing
  reference instead of a silent wrong number.
- **Idempotent.** Re-rendering from the same spec + sidecars yields identical
  bytes; the runner re-renders before both the verify gate and compile so a
  revision never leaves stale tables.
- **Schema-defensive.** Coefficient names are data-driven; ``forecast_evaluation``
  / ``first_stage`` are optional; numeric fields may be ``null``; combination
  specs have empty ``coefficients`` / ``diagnostics``. All tolerated.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ...logging_config import get_logger

logger = get_logger(__name__)

_MISSING = "---"  # LaTeX em dash for an absent / null cell


@dataclass
class UnresolvedRef:
    """A ``table_spec`` reference that did not resolve to a JSON value."""

    table: str  # the table filename
    kind: str  # "spec_key" | "coefficient" | "stat"
    ref: str  # the offending key/var/field
    column: str = ""  # the column spec_key the row was resolved against


@dataclass
class Normalized:
    """A ``table_spec`` reference resolved by something other than an exact key
    hit — an order-insensitive token match (the drafter wrote ``dp_full`` but
    the JSON key is ``full_dp``), or a nested-path match (``p_HH_pre`` found at
    ``transition_probabilities_pre.p_HH``). Recorded so every substitution
    behind a rendered number stays auditable."""

    table: str
    kind: str  # "spec_key" | "coefficient" | "stat"
    requested: str
    resolved: str  # a key, or a dotted path when resolved by descent


@dataclass
class RenderReport:
    rendered: list[str] = field(default_factory=list)  # filenames written under tables/
    unresolved: list[UnresolvedRef] = field(default_factory=list)
    normalized: list[Normalized] = field(default_factory=list)  # order-insensitive key fixes
    errors: list[str] = field(default_factory=list)  # per-table render failures
    skipped_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _token_set(name: str) -> frozenset[str]:
    """Lowercased token set of a key, split on `_`, `-`, whitespace."""
    return frozenset(t for t in re.split(r"[_\-\s]+", name.lower()) if t)


def _resolve_by_tokens(target: str, available: Any) -> str | None:
    """Find a key whose token set equals ``target``'s — an order-insensitive
    match (``dp_full`` ≡ ``full_dp``). Returns the match ONLY when exactly one
    candidate matches; never guesses on ambiguity or no match. This is the
    deterministic fix for cross-specialist key-ordering drift (the
    econometrics specialist names specs ``full_dp``; the drafter may write
    ``dp_full``)."""
    want = _token_set(target)
    if not want:
        return None
    matches = [k for k in available if _token_set(k) == want]
    return matches[0] if len(matches) == 1 else None


def _fmt(value: Any, decimals: int = 3) -> str:
    """Format a numeric value, or ``---`` for null / non-numeric / non-finite."""
    if value is None or isinstance(value, bool):
        return _MISSING
    try:
        x = float(value)
    except (TypeError, ValueError):
        return _MISSING
    if math.isnan(x) or math.isinf(x):
        return _MISSING
    if decimals <= 0:
        # Integer-style (e.g. N): thousands separators, no decimal point.
        return f"{int(round(x)):,}"
    return f"{x:.{decimals}f}"


def _stars(p_value: Any) -> str:
    """Significance stars from a p-value (*/**/*** at .10/.05/.01)."""
    if p_value is None or isinstance(p_value, bool):
        return ""
    try:
        p = float(p_value)
    except (TypeError, ValueError):
        return ""
    if math.isnan(p):
        return ""
    if p < 0.01:
        return "***"
    if p < 0.05:
        return "**"
    if p < 0.10:
        return "*"
    return ""


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("render_tables: could not read %s: %s", path.name, e)
        return {}


def _resolve_stat(spec: dict[str, Any], field_name: str) -> tuple[Any, bool]:
    """Resolve a scalar statistic from a spec object.

    Looks in ``diagnostics``, then ``forecast_evaluation``, then the spec
    top-level (covers ``n_observations``). Returns ``(value, found)``;
    ``found`` is False only when the key is absent everywhere (a genuine
    unresolved reference) — a present-but-``null`` value returns
    ``(None, True)`` so it renders ``---`` quietly without being flagged.
    """
    for container_key in ("diagnostics", "forecast_evaluation"):
        container = spec.get(container_key)
        if isinstance(container, dict) and field_name in container:
            return container[field_name], True
    if field_name in spec:
        return spec[field_name], True
    return None, False


def _stat_field_names(spec: dict[str, Any]) -> list[str]:
    """All scalar-statistic field names available in a spec object —
    diagnostics + forecast_evaluation keys plus scalar top-level keys."""
    names: list[str] = []
    for container_key in ("diagnostics", "forecast_evaluation"):
        container = spec.get(container_key)
        if isinstance(container, dict):
            names.extend(container.keys())
    names.extend(k for k, v in spec.items() if not isinstance(v, dict | list))
    return names


def _path_tokens(path: str) -> frozenset[str]:
    """Token set of a dotted path — dots are separators like `_` and `-`."""
    return _token_set(path.replace(".", "_"))


def _nested_paths(spec: dict[str, Any], max_depth: int = 3) -> dict[str, Any]:
    """Dotted path -> node for everything nested inside a spec object.

    ``coefficients`` is excluded at the top level: coefficient cells are their
    own row type with their own resolution path, and letting a ``stat`` row
    reach into them would let two different table constructs resolve to the
    same number by accident.
    """
    out: dict[str, Any] = {}

    def walk(node: dict[str, Any], prefix: str, depth: int) -> None:
        if depth > max_depth:
            return
        for k, v in node.items():
            if not prefix and k in ("coefficients", "_meta"):
                continue
            path = f"{prefix}.{k}" if prefix else k
            out[path] = v
            if isinstance(v, dict):
                walk(v, path, depth + 1)

    walk(spec, "", 1)
    return out


def _resolve_nested_stat(spec: dict[str, Any], field_name: str) -> tuple[Any, bool, str]:
    """Last-resort resolution for a stat nested below the three places
    ``_resolve_stat`` looks — e.g. the spec asks for ``p_HH_pre`` and the
    sidecar holds it at ``transition_probabilities_pre.p_HH``.

    The rule is deliberately narrow, because a wrong match here puts a wrong
    number in a published table. The requested name's tokens must be a SUBSET
    of the candidate path's tokens, and among the SHALLOWEST candidates there
    must be exactly ONE. Ambiguity resolves to "not found", never to a guess —
    ``delta_p_HH`` matching both ``delta_p_HH`` and ``delta_p_LL`` would be
    refused, and only the fact that ``pre``/``post`` discriminate the
    transition-probability blocks makes those resolvable.

    Every hit is recorded in ``table_render_report.json``, so the substitution
    is auditable rather than silent.

    Returns ``(value, found, resolved_path)``.
    """
    want = _token_set(field_name)
    if not want:
        return None, False, ""
    candidates = [
        (path, node) for path, node in _nested_paths(spec).items() if "." in path and want <= _path_tokens(path)
    ]
    if not candidates:
        return None, False, ""
    depth = min(path.count(".") for path, _ in candidates)
    shallowest = [(path, node) for path, node in candidates if path.count(".") == depth]

    scalars = [_scalar_at(path, node) for path, node in shallowest]
    if any(not ok for _, ok, _ in scalars):
        # At least one candidate is a container rather than a number, so which
        # one was meant is genuinely open. Refuse.
        return None, False, ""

    first = scalars[0][0]
    if not all(value == first for value, _, _ in scalars):
        return None, False, ""
    # Either one candidate, or several that agree exactly — the ambiguity is
    # nominal (``p_HH_pre`` sits at both ``transition_probabilities_pre.p_HH``
    # and ``logistic_regression.implied_p_HH_pre``, same number), so no choice
    # between competing values is being made. Record every path that agreed.
    return first, True, " == ".join(path for _, _, path in scalars)


def _scalar_at(path: str, node: Any) -> tuple[Any, bool, str]:
    """The scalar a nested node stands for: itself, or — for an estimate-shaped
    object (``estimate``/``se``/``p_value``) — its point estimate."""
    if isinstance(node, dict):
        est = node.get("estimate")
        if "estimate" in node and not isinstance(est, dict | list):
            return est, True, f"{path}.estimate"
        return None, False, path
    if isinstance(node, list):
        return None, False, path
    return node, True, path


def _render_one_table(
    table: dict[str, Any],
    sources: dict[str, Any],
) -> tuple[str, list[UnresolvedRef], list[Normalized]]:
    """Build the LaTeX for a single table.

    Returns (latex, unresolved_refs, normalized_refs).
    """
    filename = str(table.get("filename", "table.tex"))
    label = str(table.get("label", ""))
    caption = str(table.get("caption", ""))
    notes = str(table.get("notes", ""))
    columns = table.get("columns") or []
    rows = table.get("rows") or []
    unresolved: list[UnresolvedRef] = []
    normalized: list[Normalized] = []

    # Spec keys eligible for matching (dict-valued; skip _meta etc.).
    dict_keys = [k for k, v in sources.items() if isinstance(v, dict)]

    # Resolve each column's source spec object once.
    col_specs: list[dict[str, Any]] = []
    for col in columns:
        spec_key = str(col.get("spec_key", ""))
        spec_obj = sources.get(spec_key)
        if not isinstance(spec_obj, dict):
            # Order-insensitive retry (dp_full ≡ full_dp) before giving up.
            nk = _resolve_by_tokens(spec_key, dict_keys)
            if nk is not None:
                spec_obj = sources[nk]
                normalized.append(Normalized(filename, "spec_key", spec_key, nk))
            else:
                unresolved.append(UnresolvedRef(filename, "spec_key", spec_key))
                spec_obj = {}
        col_specs.append(spec_obj)

    headers = [str(col.get("header", col.get("spec_key", ""))) for col in columns]
    ncols = len(columns)
    colspec = "l" + "c" * ncols

    lines: list[str] = [
        "\\begin{table}[t]",
        "\\centering",
        "\\begin{threeparttable}",
    ]
    if caption:
        lines.append(f"\\caption{{{caption}}}")
    if label:
        lines.append(f"\\label{{{label}}}")
    lines.append(f"\\begin{{tabular}}{{{colspec}}}")
    lines.append("\\toprule")
    lines.append(" & " + " & ".join(headers) + " \\\\")
    lines.append("\\midrule")

    for row in rows:
        rtype = str(row.get("type", "stat"))
        row_label = str(row.get("label", ""))
        decimals = int(row.get("decimals", 3))

        if rtype == "coefficient":
            # `var` names the predictor. "*" (or empty) means "this spec's
            # primary coefficient" — for results tables whose columns are
            # different single-predictor specs (e.g. Welch-Goyal), each column
            # shows its own coefficient from one β̂ row.
            var = str(row.get("var", "")).strip()
            primary = var in ("", "*")
            estimate_cells: list[str] = []
            se_cells: list[str] = []
            show_se = bool(row.get("se", True))
            for spec_obj in col_specs:
                coeffs = spec_obj.get("coefficients")
                coef: Any = None
                if isinstance(coeffs, dict) and coeffs:
                    if primary:
                        coef = next(iter(coeffs.values()))
                    else:
                        coef = coeffs.get(var)
                        if coef is None:
                            nv = _resolve_by_tokens(var, coeffs.keys())
                            if nv is not None:
                                coef = coeffs.get(nv)
                                normalized.append(Normalized(filename, "coefficient", var, nv))
                if not isinstance(coef, dict):
                    # Only flag as unresolved when the column actually has a
                    # (non-empty) coefficient block AND a specific var was
                    # named — combination specs have `coefficients: {}` by
                    # design and should render `---`.
                    if isinstance(coeffs, dict) and coeffs and not primary:
                        unresolved.append(UnresolvedRef(filename, "coefficient", var, _spec_name(spec_obj)))
                    estimate_cells.append(_MISSING)
                    se_cells.append("")
                    continue
                est = _fmt(coef.get("estimate"), decimals)
                est_str = est + _stars(coef.get("p_value")) if est != _MISSING else _MISSING
                estimate_cells.append(est_str)
                se = _fmt(coef.get("se"), decimals)
                se_cells.append(f"({se})" if se != _MISSING else "")
            lines.append(f"{row_label} & " + " & ".join(estimate_cells) + " \\\\")
            if show_se and any(se_cells):
                lines.append(" & " + " & ".join(se_cells) + " \\\\")

        else:  # "stat" (diagnostics / forecast_evaluation / top-level scalar)
            field_name = str(row.get("field", ""))
            cells: list[str] = []
            for col, spec_obj in zip(columns, col_specs):
                value, found = _resolve_stat(spec_obj, field_name)
                if not found and spec_obj:
                    # Order-insensitive retry against the spec's actual fields.
                    nf = _resolve_by_tokens(field_name, _stat_field_names(spec_obj))
                    if nf is not None:
                        value, found = _resolve_stat(spec_obj, nf)
                        if found:
                            normalized.append(Normalized(filename, "stat", field_name, nf))
                if not found and spec_obj:
                    # Still nothing at the three flat locations — descend.
                    value, found, npath = _resolve_nested_stat(spec_obj, field_name)
                    if found:
                        normalized.append(Normalized(filename, "stat", field_name, npath))
                if not found:
                    if spec_obj:  # only flag when the column resolved at all
                        unresolved.append(UnresolvedRef(filename, "stat", field_name, str(col.get("spec_key", ""))))
                    cells.append(_MISSING)
                else:
                    cells.append(_fmt(value, decimals))
            lines.append(f"{row_label} & " + " & ".join(cells) + " \\\\")

    lines.append("\\bottomrule")
    lines.append("\\end{tabular}")
    if notes:
        lines.append("\\begin{tablenotes}[flushleft]")
        lines.append("\\footnotesize")
        lines.append(f"\\item {notes}")
        lines.append("\\end{tablenotes}")
    lines.append("\\end{threeparttable}")
    lines.append("\\end{table}")
    return "\n".join(lines) + "\n", unresolved, normalized


def _spec_name(spec_obj: dict[str, Any]) -> str:
    spec = spec_obj.get("specification")
    return str(spec)[:40] if isinstance(spec, str) else ""


def render_tables(workspace: Path) -> RenderReport:
    """Render all tables declared in ``table_spec.json`` to ``tables/*.tex``.

    Idempotent and never raises. Returns a ``RenderReport`` and also writes it
    to ``table_render_report.json`` for the runner / reviewers / dashboard.
    """
    workspace = Path(workspace)
    spec_path = workspace / "table_spec.json"
    if not spec_path.is_file():
        return RenderReport(skipped_reason="no table_spec.json in workspace")

    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        report = RenderReport(skipped_reason=f"table_spec.json unparseable: {e}")
        _save_report(workspace, report)
        return report
    if not isinstance(spec, dict) or not isinstance(spec.get("tables"), list):
        report = RenderReport(skipped_reason="table_spec.json has no 'tables' list")
        _save_report(workspace, report)
        return report

    # Merge the per-spec result sources. estimation first, robustness overlays
    # by its own (distinct) keys; collisions favour robustness but in practice
    # the key namespaces don't overlap (e.g. dp_full vs dp_full_ct_restricted).
    sources: dict[str, Any] = {}
    sources.update(_load_json(workspace / "estimation_results.json"))
    sources.update(_load_json(workspace / "robustness_results.json"))

    tables_dir = workspace / "tables"
    tables_dir.mkdir(exist_ok=True)

    report = RenderReport()
    for table in spec["tables"]:
        if not isinstance(table, dict):
            report.errors.append("non-object entry in tables list")
            continue
        filename = str(table.get("filename", "")).strip()
        if not filename or "/" in filename or not filename.endswith(".tex"):
            report.errors.append(f"invalid table filename: {filename!r}")
            continue
        try:
            latex, unresolved, normalized = _render_one_table(table, sources)
        except Exception as e:  # noqa: BLE001 — never let one bad table abort the rest
            logger.warning("render_tables: failed to render %s: %s", filename, e)
            report.errors.append(f"{filename}: {e!r}")
            continue
        (tables_dir / filename).write_text(latex, encoding="utf-8")
        report.rendered.append(filename)
        report.unresolved.extend(unresolved)
        report.normalized.extend(normalized)

    if report.normalized:
        logger.info(
            "render_tables: %d reference(s) resolved by order-insensitive token match "
            "(e.g. dp_full->full_dp) — drafter key naming drifted from the JSON",
            len(report.normalized),
        )
    if report.unresolved:
        logger.warning(
            "render_tables: %d unresolved reference(s) across %d table(s) — see table_render_report.json",
            len(report.unresolved),
            len(report.rendered),
        )
    logger.info("render_tables: wrote %d table(s) to %s", len(report.rendered), tables_dir)
    _save_report(workspace, report)
    return report


def _save_report(workspace: Path, report: RenderReport) -> None:
    try:
        (workspace / "table_render_report.json").write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    except OSError as e:
        logger.warning("render_tables: could not write table_render_report.json: %s", e)


_INPUT_RE = re.compile(r"\\input\{(tables/[^}]+?)\}")


def ensure_input_stubs(workspace: Path) -> list[str]:
    """Create empty stub files for any ``\\input{tables/...}`` in
    ``paper_draft.tex`` that has no file on disk.

    A dangling ``\\input`` is a *hard* LaTeX error that aborts compilation
    entirely. If the drafter referenced a table the renderer didn't produce
    (e.g. a `table_spec` entry was dropped, or the draft `\\input`s a name not
    in the spec), a stub keeps the rest of the paper compiling. Returns the
    list of stub paths created.
    """
    workspace = Path(workspace)
    draft = workspace / "paper_draft.tex"
    if not draft.is_file():
        return []
    text = draft.read_text(encoding="utf-8", errors="replace")
    created: list[str] = []
    for m in _INPUT_RE.finditer(text):
        rel = m.group(1).strip()
        # LaTeX appends .tex when the extension is omitted.
        rel_tex = rel if rel.endswith(".tex") else rel + ".tex"
        target = workspace / rel_tex
        if target.exists():
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                "% stub: no matching table_spec entry was rendered for this \\input\n",
                encoding="utf-8",
            )
            created.append(rel_tex)
        except OSError as e:
            logger.warning("ensure_input_stubs: could not write stub %s: %s", rel_tex, e)
    if created:
        logger.warning("ensure_input_stubs: created %d stub(s) for dangling \\input: %s", len(created), created)
    return created
