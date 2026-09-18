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
    from src.cli_verify import _strip_tex_comments

    paper = BUNDLE / "paper" / "paper.tex"
    body = _strip_tex_comments(paper.read_text(encoding="utf-8"))
    refs = _INPUT_RE.findall(body)
    assert refs, "the showcase paper should include its tables by \\input"

    missing = []
    for ref in refs:
        base = BUNDLE / "paper" / ref
        if not base.is_file() and not Path(f"{base}.tex").is_file():
            missing.append(ref)
    assert not missing, f"bundle cannot compile — missing {missing}"


def test_no_input_is_satisfied_by_a_stub(tmp_path: Path):
    """This test used to pass by accident.

    paper.tex documents its conventions in a comment holding a literal
    \\input{tables/...}; the pipeline wrote a stub for it, and
    Path("tables/...").with_suffix(".tex") names exactly that stub — so a bogus
    reference resolved to a junk file and the check went green.
    """
    from src.cli_verify import _strip_tex_comments

    body = _strip_tex_comments((BUNDLE / "paper" / "paper.tex").read_text(encoding="utf-8"))
    assert "tables/..." not in body, "commented-out \\input leaked into the parsed body"

    for ref in _INPUT_RE.findall(body):
        target = BUNDLE / "paper" / ref
        text = target.read_text(encoding="utf-8") if target.is_file() else ""
        assert "% stub:" not in text, f"{ref} is a stub, not a table"


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


def test_every_bundle_file_is_committed():
    """A file in provenance.json that git does not track fails for everyone but
    the person who built the bundle.

    .gitignore's `*.log` swallowed code/scratch/paper_draft.log: integrity
    passed locally against the working tree and failed in CI against a fresh
    checkout. Any future run emitting a .db, .aux or .pdf would do the same, so
    the check is on the whole inventory rather than that one extension.
    """
    import subprocess

    repo = BUNDLE.parents[1]
    listed = set(json.loads((BUNDLE / "provenance.json").read_text(encoding="utf-8"))["files"])

    out = subprocess.run(
        ["git", "ls-files", "-z", "examples/showcase"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    if out.returncode != 0:
        pytest.skip("not a git checkout")
    prefix = "examples/showcase/"
    tracked = {p[len(prefix) :] for p in out.stdout.split("\0") if p.startswith(prefix)}

    untracked = sorted(listed - tracked)
    assert not untracked, f"provenance lists files git does not track: {untracked}"


def test_the_bundle_verifies_clean():
    """The whole point of shipping it: a stranger can check it offline."""
    checks = _checks()
    failed = [name for name, c in checks.items() if c.status == "FAIL"]
    assert not failed, f"showcase bundle fails: {failed}"
    assert checks["integrity"].status == "PASS"
    assert checks["citations"].status == "PASS"


def test_tables_reproduce_byte_identically_from_the_sidecars():
    """Every declared table re-renders from the spec and the result JSONs."""
    import tempfile

    from src.cli_verify import _check_tables, _reconstruct_workspace

    with tempfile.TemporaryDirectory() as td:
        ws = Path(td)
        _reconstruct_workspace(BUNDLE, ws)
        check = _check_tables(BUNDLE, ws)

    assert check.status == "PASS", check.detail
    assert "reproduce byte-identically" in check.detail


def test_an_edited_table_cell_fails_the_tables_check(tmp_path: Path):
    """The reason this check exists.

    The numbers gate decides severity by distance to the closest value anywhere
    in the source JSON, so a fabricated cell that lands near an unrelated number
    is graded "major" and does not gate — only the hash catches it. Re-rendering
    asks the actual question: is this what the sidecars produce?
    """
    import re
    import shutil
    import tempfile

    from src.cli_verify import _check_numbers, _check_tables, _reconstruct_workspace

    bundle = tmp_path / "b"
    shutil.copytree(BUNDLE, bundle)

    table = bundle / "paper" / "tables" / "main.tex"
    text = table.read_text(encoding="utf-8")
    match = re.search(r"-?\d+\.\d{3,}", text)
    assert match, "expected a decimal estimate in main.tex"
    table.write_text(text.replace(match.group(0), "-9.9999", 1), encoding="utf-8")

    with tempfile.TemporaryDirectory() as td:
        ws = Path(td)
        _reconstruct_workspace(bundle, ws)
        tables = _check_tables(bundle, ws)
        numbers = _check_numbers(bundle, ws)

    assert tables.status == "FAIL"
    assert "main.tex" in tables.detail
    # Documents the gap this check closes: the nearest-value heuristic still
    # grades the edited cell non-critical and lets it through.
    assert numbers.status == "PASS"


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
