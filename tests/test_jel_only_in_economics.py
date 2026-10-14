"""JEL codes belong to economics papers only (2026-10-13 demos).

The climate (time-series) and earthquake (descriptive) drafts carried
"JEL: C22, C53, Q54" lines. Only templates with the economist persona ask for
JEL codes; the others tell every specialist not to write them, and the draft
writers' phrase check sends a JEL line back.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.core.pipeline.components import activate, deactivate
from src.core.pipeline.result_kinds import active_economics
from src.core.pipeline.spec import find_spec
from src.core.specialists.contract_check import check_draft_phrases, check_patch_phrases
from src.core.strategist.context import template_context
from src.core.writing_check import jel_lines

DRAFT = (
    "\\begin{abstract}\nWe forecast monthly temperature at one grid cell.\n\\end{abstract}\n"
    "\\noindent\\textbf{JEL:} C22, C53, Q54. \\textbf{Keywords:} forecasting, MERRA-2.\n"
    "\\section{Introduction}\nThe series is long.\n"
)


@pytest.fixture
def template():
    tokens = []

    def use(name: str) -> None:
        tokens.append(activate(find_spec(name)))

    yield use
    for t in reversed(tokens):
        deactivate(t)


@pytest.mark.parametrize("name", ["descriptive-study", "time-series-forecasting", "spatial-analysis", "text-analysis"])
def test_non_economics_drafts_with_a_jel_line_go_back(tmp_path: Path, template, name: str):
    template(name)
    assert not active_economics()
    (tmp_path / "paper_draft.tex").write_text(DRAFT, encoding="utf-8")
    c = check_draft_phrases(tmp_path, "paper_draft.tex")
    assert not c.ok
    assert '"JEL codes" in:' in c.reason and "C22, C53, Q54" in c.reason
    assert "not an economics paper" in c.reason


@pytest.mark.parametrize("name", ["empirical", "policy-evaluation"])
def test_economics_drafts_keep_their_jel_codes(tmp_path: Path, template, name: str):
    template(name)
    assert active_economics()
    (tmp_path / "paper_draft.tex").write_text(DRAFT, encoding="utf-8")
    assert check_draft_phrases(tmp_path, "paper_draft.tex").ok


def test_without_a_template_jel_is_allowed(tmp_path: Path):
    (tmp_path / "paper_draft.tex").write_text(DRAFT, encoding="utf-8")
    assert check_draft_phrases(tmp_path, "paper_draft.tex").ok


def test_a_revisor_edit_that_adds_a_jel_line_goes_back(tmp_path: Path, template):
    import json

    template("descriptive-study")
    edits = {"edits": [{"edit_type": "replace_text", "find": "x", "replace": "JEL: C22. Keywords: earthquakes."}]}
    (tmp_path / "paper_draft.tex.edits.json").write_text(json.dumps(edits), encoding="utf-8")
    assert not check_patch_phrases(tmp_path).ok


def test_only_non_economics_templates_tell_the_specialists_no_jel(template):
    template("descriptive-study")
    assert "no JEL codes" in template_context()


def test_economics_template_context_says_nothing_about_jel(template):
    template("policy-evaluation")
    assert "JEL" not in template_context()


def test_jel_in_a_comment_or_a_citation_is_not_prose():
    assert jel_lines("% JEL: C22\nText \\cite{JEL2020}.\n") == []


def test_the_abstract_skill_asks_for_jel_only_in_economics():
    text = (Path(__file__).resolve().parents[1] / "skills/files/writing/abstract.md").read_text(encoding="utf-8")
    assert "JEL codes (economics papers only)" in text
    assert "has no JEL line" in text
