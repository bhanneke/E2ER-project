"""A table or figure name from a spec is one plain file name (security review 2026-10-23).

The check refused ``/`` only: on Windows ``..\\paper_draft.tex`` (a backslash is a separator there)
wrote outside ``tables/``.
"""

from __future__ import annotations

import json

import pytest

from src.core.renderer.names import plain_filename

BAD = [
    "..\\paper_draft.tex",
    "a\\b.tex",
    "../x.tex",
    "C:x.tex",
    ".hidden.tex",
    ".tex",
    " x.tex",
    "x\n.tex",
    "x.txt",
    "",
]


@pytest.mark.parametrize("bad", BAD)
def test_a_name_with_a_separator_or_a_drive_is_refused(bad):
    assert not plain_filename(bad, ".tex")


def test_plain_names_pass():
    assert plain_filename("main_results.tex", ".tex") and plain_filename("fig-1.pdf", ".pdf")


def test_render_tables_writes_no_table_with_a_backslash_name(tmp_path):
    from src.core.renderer.tables import render_tables

    (tmp_path / "estimation_results.json").write_text(
        json.dumps({"main": {"coefficients": {"x": 1.0}}}), encoding="utf-8", newline="\n"
    )
    spec = {"tables": [{"filename": "..\\paper_draft.tex", "caption": "c", "columns": [], "rows": []}]}
    (tmp_path / "table_spec.json").write_text(json.dumps(spec), encoding="utf-8", newline="\n")
    report = render_tables(tmp_path)
    assert report.rendered == [] and any("invalid table filename" in e for e in report.errors)
    assert not any(p.name.endswith("paper_draft.tex") for p in tmp_path.rglob("*"))
