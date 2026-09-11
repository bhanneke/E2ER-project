"""Regression tests against the real exported bundle, not a synthetic one.

Two defects shipped past 1341 tests because every test on both sides of the
export/verify seam used a workspace the developer invented rather than one the
pipeline produces. The fixture draft is
``\\documentclass{article}\\begin{document}hi\\end{document}`` — no tables, no
``\\input`` — so:

  * the export could drop ``tables/`` and no test noticed, because no fixture
    workspace had a ``tables/`` to drop; and
  * the numbers gate could scan only the draft and find no tabular at all,
    because the gate's own tests fed it inline tabulars as strings.

Each unit was tested against a fiction of its neighbour, and the composition
was tested by nothing. The first completed run found both in minutes.

``examples/showcase/`` is now a real bundle in the repository, so these tests
assert against what the pipeline actually emits. They are cheap: verify is
offline and sub-second.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

BUNDLE = Path(__file__).resolve().parents[1] / "examples" / "showcase"

pytestmark = pytest.mark.skipif(
    not (BUNDLE / "provenance.json").is_file(),
    reason="examples/showcase bundle not present",
)

_INPUT_RE = re.compile(r"\\input\{([^}]+)\}")


def _checks() -> dict[str, object]:
    from src.cli_verify import _run_checks

    return {c.name: c for c in _run_checks(BUNDLE, online=False)}


def test_every_input_resolves_inside_the_bundle():
    """A bundle whose paper cannot compile is not a deliverable.

    The exported paper carried thirteen \\input directives and two .tex files.
    """
    paper = BUNDLE / "paper" / "paper.tex"
    refs = _INPUT_RE.findall(paper.read_text(encoding="utf-8"))
    assert refs, "the showcase paper should include its tables by \\input"

    missing = []
    for ref in refs:
        target = BUNDLE / "paper" / ref
        if not target.is_file() and not target.with_suffix(".tex").is_file():
            missing.append(ref)
    assert not missing, f"bundle cannot compile — missing {missing}"


def test_the_numbers_gate_actually_traced_cells():
    """Coverage, not just a verdict.

    `passed` stayed True while the gate traced zero cells, which in the report
    was indistinguishable from a run that checked every number.
    """
    import tempfile

    from src.cli_verify import _reconstruct_workspace
    from src.core.pipeline.verify_numbers import verify as verify_numbers

    with tempfile.TemporaryDirectory() as td:
        ws = Path(td)
        _reconstruct_workspace(BUNDLE, ws)
        report = verify_numbers(BUNDLE / "paper" / "paper.tex", ws)

    assert report.tables_conclusive, "the table channel reached no verdict at all"
    assert report.matched > 0
    assert not report.critical_mismatches


def test_the_bundle_verifies_clean():
    """The whole point of shipping it: a stranger can check it offline."""
    checks = _checks()
    failed = [name for name, c in checks.items() if c.status == "FAIL"]
    assert not failed, f"showcase bundle fails: {failed}"
    assert checks["integrity"].status == "PASS"
    assert checks["citations"].status == "PASS"


def test_provenance_records_a_cell_edge_for_every_traced_number():
    """The bundle shipped with 34 edges, every one a citation, and no table_cell
    edge at all — because the run's gate report recorded no matched cells and
    the graph is derived from it. It claimed every number traces to a file while
    carrying no trace for any number."""
    prov = json.loads((BUNDLE / "provenance.json").read_text(encoding="utf-8"))
    cells = [e for e in prov["edges"] if e.get("type") == "table_cell"]

    assert cells, "derivation graph has no table_cell edges"
    for edge in cells[:20]:
        assert edge.get("source_key"), f"cell edge without a source key: {edge}"
        assert edge.get("cell_value") is not None
        assert edge.get("table_context")


def test_empty_derivation_graph_fails_integrity(tmp_path: Path):
    """Hashes prove nothing was modified. They say nothing about whether the
    graph was ever populated, so integrity has to check both."""
    import shutil

    from src.cli_verify import _check_integrity

    bundle = tmp_path / "b"
    shutil.copytree(BUNDLE, bundle)

    prov = json.loads((bundle / "provenance.json").read_text(encoding="utf-8"))
    assert _check_integrity(bundle).status == "PASS"

    # Strip the cell edges, leaving the hashes untouched and correct.
    prov["edges"] = [e for e in prov["edges"] if e.get("type") != "table_cell"]
    (bundle / "provenance.json").write_text(json.dumps(prov), encoding="utf-8")

    check = _check_integrity(bundle)
    assert check.status == "FAIL"
    assert "derivation graph is empty" in check.detail


def test_rendered_tables_with_no_traced_cells_is_not_a_pass(tmp_path: Path):
    """The guard itself: a paper that ships rendered tables and traces nothing
    in them must not print the same tick as one that checked every number."""
    from src.cli_verify import _bundle_has_rendered_tables

    bundle = tmp_path / "b"
    (bundle / "paper" / "tables").mkdir(parents=True)
    (bundle / "results").mkdir(parents=True)

    # No render report, but table files present.
    (bundle / "paper" / "tables" / "main.tex").write_text("\\begin{tabular}{l}x\\end{tabular}")
    assert _bundle_has_rendered_tables(bundle) is True

    # Render report wins when present, and an empty one means no tables.
    (bundle / "results" / "table_render_report.json").write_text(json.dumps({"rendered": []}))
    assert _bundle_has_rendered_tables(bundle) is False

    (bundle / "results" / "table_render_report.json").write_text(json.dumps({"rendered": ["main.tex"]}))
    assert _bundle_has_rendered_tables(bundle) is True
