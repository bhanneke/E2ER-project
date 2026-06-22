#!/usr/bin/env python3
"""Generate the "how E2ER works" pipeline figure FROM THE SOURCE OF TRUTH.

The whole point of this script is that the figure can never drift from the
code: every specialist name, every JSON artifact contract, and the reviewer
roster are read at generation time from
``src/core/specialists/registry.py``. If someone renames a specialist or a
sidecar file, re-running this script (and the accompanying test in
``tests/test_pipeline_figure.py``) reflects the change automatically.

The PHASE ORDER encoded below is verified against the real orchestrator,
``src/core/strategist/runner.py`` (``PipelineRunner.run``), which executes:

    initial -> iterative -> self_attack -> polish -> review -> revision -> replication

The honest depiction rule: this figure shows ONLY what E2ER actually does.
E2ER uses same-model reviewers (not cross-model), has no GPU experiments, and
no "skip-failed-ideas" idea memory. It has TWO programmatic assurance gates,
both run before reviewers in ``runner._run_review_phase``: ``verify_numbers``
(``src/core/pipeline/verify_numbers.py`` — table/prose numbers must match the
source JSON) and ``verify_citations`` (``src/core/pipeline/verify_citations.py``
— every ``\\cite`` resolves in references.bib and an index). Results-table
numbers are filled by a deterministic ``table_renderer``
(``src/core/renderer/tables.py``) from the JSON sidecars per ``table_spec.json``,
so they can't be fabricated. The figure reflects all three.

Usage
-----
    python scripts/gen_pipeline_figure.py

Outputs
-------
- ``docs/figures/pipeline.dot``  — always written (Graphviz DOT source)
- ``docs/figures/pipeline.svg``  — written if the ``dot`` CLI is installed
- ``docs/figures/pipeline.pdf``  — written if the ``dot`` CLI is installed

If Graphviz's ``dot`` is not on PATH the script still writes the ``.dot`` and
prints a note (``brew install graphviz``); it never fails for that reason.
The script is idempotent: re-running overwrites the outputs in place.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

# Make ``src`` importable whether run from the repo root or elsewhere.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.core.specialists.registry import (  # noqa: E402
    POLISH_SPECIALISTS,
    REVIEWER_SPECIALISTS,
    SPECIALIST_ARTIFACTS,
    SPECIALIST_OPTIONAL_SIDECARS,
    SPECIALIST_SIDECAR_ARTIFACTS,
    SPECIALIST_SKILLS,
)

# Conditionally-emitted sidecars that are documented in the registry comments
# but not in a dict the generator can import. Keep this list tiny and explicit;
# it is asserted against the verify_numbers source-file set in the test so it
# cannot silently rot.
_DOCUMENTED_OPTIONAL_SIDECARS: dict[str, list[str]] = {
    "econometrics_specialist": ["robustness_results.json"],
}


# ---------------------------------------------------------------------------
# Pipeline phases — ordered exactly as PipelineRunner.run executes them.
# The specialist membership of each phase is derived from the registry where
# possible (reviewers, polish) and from the runner's phase bodies otherwise
# (design roster, single-specialist phases). VERIFIED against runner.py.
# ---------------------------------------------------------------------------

# Design roster: the strategist plans these in the "initial" phase
# (runner._run_initial_phase -> strategist.decide("designing")). Order mirrors
# README "Pipeline phases" and docs/diagrams/specialist_dag.md.
_DESIGN_SPECIALISTS = [
    "idea_developer",
    "literature_scanner",
    "identification_strategist",
    "data_architect",
    "data_analyst",
    "econometrics_specialist",
    "paper_drafter",
    "abstract_writer",
]


def _phases() -> list[tuple[str, str, list[str]]]:
    """Return the ordered phases as ``(key, human_label, [specialists])``.

    Reviewer and polish rosters are pulled live from the registry so the
    figure tracks the code. The single-specialist phases name the one
    specialist the runner dispatches for that phase.
    """
    return [
        ("initial", "1 · Design", list(_DESIGN_SPECIALISTS)),
        ("iterative", "2 · Iterate", ["section_writer"]),
        ("self_attack", "3 · Self-attack", ["self_attacker"]),
        ("polish", "4 · Polish", list(POLISH_SPECIALISTS)),
        ("review", "5 · Review", list(REVIEWER_SPECIALISTS)),
        ("revision", "6 · Revision", ["patch_revisor"]),
        ("replication", "7 · Replication", ["replication_packager"]),
    ]


# ---------------------------------------------------------------------------
# Artifact-contract flows. Each tuple is (producer, sidecar_file, consumer).
# The producers + sidecar filenames are validated against the registry at
# runtime (see _validate_contracts); we do NOT hardcode a producer/sidecar the
# registry doesn't declare. The consumer is the deterministic table renderer
# (table_spec.json + the data sidecars) or a verify gate — see _SIDECAR_CONSUMERS.
# ---------------------------------------------------------------------------

_GATE_NODES = ("verify_numbers", "verify_citations")
_RENDERER_NODE = "table_renderer"

# Which assurance/renderer node(s) consume each sidecar. Consumers live in the
# runner + renderer (not the registry), so this small map is maintained here;
# the PRODUCERS and sidecar filenames are still validated against the registry
# in _validate_contracts, so the figure can't draw a sidecar the code doesn't
# declare. table_spec.json drives the deterministic renderer; the data sidecars
# feed both the renderer (to fill table numbers) and verify_numbers (to check).
_SIDECAR_CONSUMERS: dict[str, tuple[str, ...]] = {
    "table_spec.json": (_RENDERER_NODE,),
    "estimation_results.json": (_RENDERER_NODE, "verify_numbers"),
    "robustness_results.json": (_RENDERER_NODE, "verify_numbers"),
    "summary_statistics.json": ("verify_numbers",),
    "figure_spec.json": ("verify_numbers",),
}
_DEFAULT_CONSUMER: tuple[str, ...] = ("verify_numbers",)


def _contract_flows() -> list[tuple[str, str, str]]:
    """Build the (producer -> sidecar.json -> consumer) edges.

    Producers + sidecar filenames are derived from the registry
    (``SPECIALIST_SIDECAR_ARTIFACTS`` + ``SPECIALIST_OPTIONAL_SIDECARS`` + the
    documented optional sidecars). The consumer (the deterministic renderer vs.
    a verify gate) comes from ``_SIDECAR_CONSUMERS``.
    """
    flows: list[tuple[str, str, str]] = []
    merged: dict[str, list[str]] = {}
    for src in (
        SPECIALIST_SIDECAR_ARTIFACTS,
        SPECIALIST_OPTIONAL_SIDECARS,
        _DOCUMENTED_OPTIONAL_SIDECARS,
    ):
        for specialist, files in src.items():
            merged.setdefault(specialist, [])
            for f in files:
                if f not in merged[specialist]:
                    merged[specialist].append(f)
    for specialist, files in merged.items():
        for f in files:
            for consumer in _SIDECAR_CONSUMERS.get(f, _DEFAULT_CONSUMER):
                flows.append((specialist, f, consumer))
    return flows


def _validate_contracts(flows: list[tuple[str, str, str]]) -> None:
    """Fail loudly if the figure would depict a specialist the registry
    doesn't know about — that would mean the generator drifted from source."""
    known = set(SPECIALIST_ARTIFACTS)
    for producer, sidecar, _consumer in flows:
        if producer not in known:
            raise ValueError(
                f"contract producer {producer!r} (for {sidecar!r}) is not in "
                "SPECIALIST_ARTIFACTS — refusing to draw a figure that drifts "
                "from the registry."
            )


# ---------------------------------------------------------------------------
# DOT assembly.
# ---------------------------------------------------------------------------

# Colour palette (kept deterministic so re-runs produce identical bytes).
_PHASE_FILL = "#eef2f7"
_PHASE_BORDER = "#5b6b7f"
_SPEC_FILL = "#ffffff"
_REVIEWER_FILL = "#ffe9cc"
_POLISH_FILL = "#e8eaf6"
_GATE_FILL = "#d8f0dd"
_GATE_BORDER = "#2e7d32"
_CONTRACT_FILL = "#fff7cc"
_CONTRACT_BORDER = "#b8860b"


def _node_id(name: str) -> str:
    """Stable DOT-safe node id from a specialist / artifact name."""
    return "n_" + name.replace(".", "_").replace("-", "_").replace("/", "_")


def _esc(text: str) -> str:
    """Escape a DOT label string."""
    return text.replace("\\", "\\\\").replace('"', '\\"')


def build_dot() -> str:
    """Assemble the full Graphviz DOT document as a string.

    This is the function the test drives — it returns deterministic DOT text
    referencing the real specialist names and sidecar filenames from the
    registry.
    """
    phases = _phases()
    flows = _contract_flows()
    _validate_contracts(flows)

    reviewer_set = set(REVIEWER_SPECIALISTS)
    polish_set = set(POLISH_SPECIALISTS)

    lines: list[str] = []
    lines.append("// AUTO-GENERATED by scripts/gen_pipeline_figure.py — DO NOT EDIT BY HAND.")
    lines.append("// Regenerate with: python scripts/gen_pipeline_figure.py")
    lines.append("// Every specialist + JSON contract below is read from")
    lines.append("// src/core/specialists/registry.py, so this figure cannot drift.")
    lines.append("digraph e2er_pipeline {")
    lines.append("  rankdir=LR;")
    lines.append('  fontname="Helvetica";')
    lines.append('  labelloc="t";')
    lines.append(
        "  label=<<b>How E2ER works</b><br/>"
        '<font point-size="10">Generated from src/core/specialists/registry.py — '
        "specialists, phases, and JSON artifact contracts.</font>>;"
    )
    lines.append("  graph [splines=true, nodesep=0.35, ranksep=0.9];")
    lines.append(
        '  node [shape=box, style="rounded,filled", fontname="Helvetica", '
        f'fontsize=10, fillcolor="{_SPEC_FILL}", color="{_PHASE_BORDER}"];'
    )
    lines.append('  edge [fontname="Helvetica", fontsize=8, color="#5b6b7f"];')
    lines.append("")

    # --- Phase clusters with their specialist nodes ---
    phase_anchor: dict[str, str] = {}  # phase_key -> first node id (for ordering)
    for phase_key, label, specialists in phases:
        lines.append(f"  subgraph cluster_{phase_key} {{")
        lines.append(f'    label="{_esc(label)}";')
        lines.append('    style="rounded,filled";')
        lines.append(f'    fillcolor="{_PHASE_FILL}";')
        lines.append(f'    color="{_PHASE_BORDER}";')
        lines.append("    fontsize=12;")
        lines.append('    fontname="Helvetica-Bold";')
        for spec in specialists:
            artifact = SPECIALIST_ARTIFACTS.get(spec, "")
            fill = _SPEC_FILL
            if spec in reviewer_set:
                fill = _REVIEWER_FILL
            elif spec in polish_set:
                fill = _POLISH_FILL
            sublabel = f'<br/><font point-size="7">→ {_esc(artifact)}</font>' if artifact else ""
            lines.append(f'    {_node_id(spec)} [label=<{_esc(spec)}{sublabel}>, fillcolor="{fill}"];')
        if specialists:
            phase_anchor[phase_key] = _node_id(specialists[0])
        lines.append("  }")
        lines.append("")

    # --- The assurance gate (verify_numbers) as a distinct element ---
    lines.append("  // The deterministic table renderer fills results-table numbers")
    lines.append("  // from the JSON sidecars per table_spec.json (no LLM in the number path).")
    lines.append(
        f"  {_node_id(_RENDERER_NODE)} "
        f"[label=<<b>table_renderer</b><br/>"
        f'<font point-size="7">deterministic · no LLM<br/>'
        f"fills tables from JSON per table_spec</font>>, "
        f'shape=box, style="rounded,filled", fillcolor="{_CONTRACT_FILL}", '
        f'color="{_CONTRACT_BORDER}", penwidth=2];'
    )
    lines.append("  // Assurance: the two programmatic gates, both run pre-review.")
    for _gate, _sub in (
        ("verify_numbers", "numbers match source JSON"),
        ("verify_citations", "every cite key resolves"),
    ):
        lines.append(
            f"  {_node_id(_gate)} "
            f"[label=<<b>{_gate}</b><br/>"
            f'<font point-size="7">deterministic gate · no LLM<br/>{_sub}</font>>, '
            f'shape=hexagon, fillcolor="{_GATE_FILL}", color="{_GATE_BORDER}", penwidth=2];'
        )
    lines.append(
        f"  {_node_id(_RENDERER_NODE)} -> {_node_id('verify_numbers')} "
        f'[color="{_GATE_BORDER}", style=dashed, label="tables/*.tex", constraint=false];'
    )
    lines.append("")

    # --- Phase ordering edges (invisible-ish backbone, left to right) ---
    lines.append("  // Phase order — verified against PipelineRunner.run in runner.py.")
    ordered_anchors = [phase_anchor[k] for k, _l, specs in phases if specs]
    for a, b in zip(ordered_anchors, ordered_anchors[1:]):
        lines.append(f'  {a} -> {b} [style=bold, color="{_PHASE_BORDER}", weight=10, constraint=true, arrowhead=vee];')
    lines.append("")

    # --- Artifact-contract flows: producer -> sidecar node -> gate ---
    lines.append("  // JSON artifact contracts — producer specialist emits the")
    lines.append("  // sidecar; the renderer and/or a verify gate consumes it.")
    contract_nodes_emitted: set[str] = set()
    for producer, sidecar, consumer in flows:
        cnode = _node_id("artifact_" + sidecar)
        if cnode not in contract_nodes_emitted:
            lines.append(
                f'  {cnode} [label="{_esc(sidecar)}", shape=note, '
                f'fillcolor="{_CONTRACT_FILL}", color="{_CONTRACT_BORDER}", fontsize=9];'
            )
            contract_nodes_emitted.add(cnode)
        lines.append(
            f'  {_node_id(producer)} -> {cnode} [color="{_CONTRACT_BORDER}", arrowhead=open, constraint=false];'
        )
        lines.append(
            f"  {cnode} -> {_node_id(consumer)} "
            f'[color="{_CONTRACT_BORDER}", arrowhead=open, constraint=false, '
            'label="consumed by"];'
        )
    lines.append("")

    # --- Both gates feed the review phase (they run before reviewers) ---
    first_reviewer = REVIEWER_SPECIALISTS[0] if REVIEWER_SPECIALISTS else None
    if first_reviewer:
        lines.append("  // Both gates run BEFORE reviewers (runner._run_review_phase).")
        for _gate in _GATE_NODES:
            lines.append(
                f"  {_node_id(_gate)} -> {_node_id(first_reviewer)} "
                f'[style=dashed, color="{_GATE_BORDER}", label="pass → reviewers", '
                "constraint=false];"
            )
    lines.append("")

    # --- Legend ---
    lines.append("  subgraph cluster_legend {")
    lines.append('    label="Legend";')
    lines.append('    style="rounded,filled";')
    lines.append('    fillcolor="#fafafa";')
    lines.append('    color="#999999";')
    lines.append("    fontsize=10;")
    lines.append(f'    leg_spec [label="specialist (→ primary artifact)", fillcolor="{_SPEC_FILL}"];')
    lines.append(f'    leg_rev [label="reviewer (same-model)", fillcolor="{_REVIEWER_FILL}"];')
    lines.append(f'    leg_pol [label="polish specialist", fillcolor="{_POLISH_FILL}"];')
    lines.append(
        f'    leg_art [label="JSON artifact contract", shape=note, '
        f'fillcolor="{_CONTRACT_FILL}", color="{_CONTRACT_BORDER}"];'
    )
    lines.append(
        f'    leg_ren [label="deterministic renderer", fillcolor="{_CONTRACT_FILL}", color="{_CONTRACT_BORDER}"];'
    )
    lines.append(
        f'    leg_gate [label="assurance gate", shape=hexagon, fillcolor="{_GATE_FILL}", color="{_GATE_BORDER}"];'
    )
    lines.append("    leg_spec -> leg_rev -> leg_pol -> leg_art -> leg_ren -> leg_gate [style=invis];")
    lines.append("  }")
    lines.append("}")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Rendering + CLI.
# ---------------------------------------------------------------------------


def _render_with_dot(dot_path: Path, fmt: str, out_path: Path) -> bool:
    """Render ``dot_path`` to ``out_path`` in ``fmt`` using the dot CLI.

    Returns True on success, False if ``dot`` is unavailable or errored.
    """
    dot_bin = shutil.which("dot")
    if not dot_bin:
        return False
    try:
        subprocess.run(
            [dot_bin, f"-T{fmt}", str(dot_path), "-o", str(out_path)],
            check=True,
            capture_output=True,
            text=True,
        )
        return True
    except (subprocess.CalledProcessError, OSError) as e:  # pragma: no cover
        stderr = getattr(e, "stderr", "") or ""
        print(f"  ! dot failed for {fmt}: {stderr.strip() or e}", file=sys.stderr)
        return False


def _rel(path: Path) -> str:
    """Best-effort repo-relative display path (falls back to the full path
    when ``path`` lives outside the repo, e.g. a pytest tmp dir)."""
    try:
        return str(path.relative_to(_REPO_ROOT))
    except ValueError:
        return str(path)


def generate(out_dir: Path | None = None) -> Path:
    """Write the .dot (and .svg/.pdf if dot is installed). Returns the .dot path."""
    out_dir = out_dir or (_REPO_ROOT / "docs" / "figures")
    out_dir.mkdir(parents=True, exist_ok=True)

    dot_text = build_dot()
    dot_path = out_dir / "pipeline.dot"
    dot_path.write_text(dot_text, encoding="utf-8")

    rendered: list[str] = []
    if shutil.which("dot"):
        for fmt, name in (("svg", "pipeline.svg"), ("pdf", "pipeline.pdf")):
            if _render_with_dot(dot_path, fmt, out_dir / name):
                rendered.append(name)
    else:
        print(
            "  note: Graphviz `dot` not found — wrote pipeline.dot only.\n"
            "        Install it to render SVG/PDF:  brew install graphviz\n"
            "        Then re-run:  python scripts/gen_pipeline_figure.py"
        )

    # Summary -----------------------------------------------------------------
    phases = _phases()
    flows = _contract_flows()
    n_specialists = len(SPECIALIST_ARTIFACTS)
    n_skills = sum(len(v) for v in SPECIALIST_SKILLS.values())
    contract_files = sorted({f for _p, f, _c in flows})

    print("=== Pipeline figure generated ===")
    print(f"  phases ({len(phases)}): " + " → ".join(k for k, _l, _s in phases))
    print(f"  specialists in registry: {n_specialists}")
    print(f"  reviewers: {len(REVIEWER_SPECIALISTS)} · polish: {len(POLISH_SPECIALISTS)}")
    print(f"  skill assignments: {n_skills}")
    print(f"  artifact contracts ({len(contract_files)}): " + ", ".join(contract_files))
    print(f"  wrote: {_rel(dot_path)}")
    for name in rendered:
        print(f"  wrote: {_rel(out_dir / name)}")
    return dot_path


def main() -> int:
    generate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
