"""v0.6 step 2: patch_merger — deterministic application of scoped edits.

The `patch_revisor` specialist writes structured edits to
`paper_draft.tex.edits.json`; this merger validates them against
the work order's Finding list, applies in-scope edits to the
draft, and emits a unified diff side artifact.

Coverage:
- Patch-file parsing: valid JSON, malformed shapes, extra-field tolerance.
- Target validation: in-scope vs out-of-scope split, paper:full widening.
- Region extraction: section, table, abstract, references, paper:full.
- Edit application: replace_text with unique find, ambiguous find,
  missing find, missing region, unknown edit_type.
- End-to-end merge_patch_file: writes patched draft + diff side artifact.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.core.strategist.findings import Finding
from src.core.strategist.patch_merger import (
    Edit,
    apply_edit,
    apply_patch,
    list_section_titles,
    list_table_labels,
    merge_patch_file,
    parse_patch_file,
    validate_targets,
)

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


_DRAFT = r"""\documentclass{article}
\begin{document}
\title{Example}
\maketitle

\begin{abstract}
The treatment effect is 0.80 according to our estimates.
\end{abstract}

\section{Introduction}
We propose a study of X. The headline finding will be reported in
Section~\ref{sec:results}.

\section{Identification Strategy}
The parallel-trends assumption holds, as we verify in our setting.

\section{Results}
Table~\ref{tab:main} reports the main estimates.

\label{tab:main}
\begin{tabular}{lcc}
\toprule
Variable & Coef & SE \\
\midrule
log RV & 0.80 & 0.10 \\
size & 0.04 & 0.01 \\
\bottomrule
\end{tabular}

\bibliography{refs}

\end{document}
"""


def _finding(target: str) -> Finding:
    return Finding(
        source="verify_numbers",
        source_detail="verify_numbers",
        target=target,
        severity=7,
        problem="x",
        suggested_fix="y",
    )


# ---------------------------------------------------------------------------
# parse_patch_file
# ---------------------------------------------------------------------------


class TestParsePatchFile:
    def test_parses_well_formed_list(self, tmp_path: Path):
        path = tmp_path / "edits.json"
        path.write_text(
            json.dumps(
                [
                    {
                        "target": "table:tab:main",
                        "edit_type": "replace_text",
                        "find": "0.80",
                        "replace": "0.50",
                    }
                ]
            )
        )
        edits = parse_patch_file(path)
        assert len(edits) == 1
        assert edits[0].target == "table:tab:main"
        assert edits[0].edit_type == "replace_text"
        assert edits[0].find == "0.80"
        assert edits[0].replace == "0.50"

    def test_defaults_find_must_be_unique_true(self, tmp_path: Path):
        path = tmp_path / "edits.json"
        path.write_text(json.dumps([{"target": "abstract", "edit_type": "replace_text", "find": "x", "replace": "y"}]))
        edits = parse_patch_file(path)
        assert edits[0].find_must_be_unique is True

    def test_generates_id_when_absent(self, tmp_path: Path):
        path = tmp_path / "edits.json"
        path.write_text(
            json.dumps(
                [
                    {"target": "abstract", "edit_type": "replace_text", "find": "x", "replace": "y"},
                    {"target": "abstract", "edit_type": "replace_text", "find": "p", "replace": "q"},
                ]
            )
        )
        edits = parse_patch_file(path)
        # Index-based IDs e0, e1 — deterministic so the merger's
        # report can name specific edits without the LLM having to
        # provide IDs.
        assert [e.edit_id for e in edits] == ["e0", "e1"]

    def test_preserves_caller_provided_id(self, tmp_path: Path):
        path = tmp_path / "edits.json"
        path.write_text(
            json.dumps(
                [
                    {
                        "id": "fix_main_coef",
                        "target": "abstract",
                        "edit_type": "replace_text",
                        "find": "x",
                        "replace": "y",
                    },
                ]
            )
        )
        edits = parse_patch_file(path)
        assert edits[0].edit_id == "fix_main_coef"

    def test_extra_fields_tolerated(self, tmp_path: Path):
        """Forward-compat: patch_revisor may add annotations the
        merger doesn't know about. They're silently dropped."""
        path = tmp_path / "edits.json"
        path.write_text(
            json.dumps(
                [
                    {
                        "target": "abstract",
                        "edit_type": "replace_text",
                        "find": "x",
                        "replace": "y",
                        "future_field_v0_7": "annotation",
                    }
                ]
            )
        )
        edits = parse_patch_file(path)
        assert len(edits) == 1

    def test_empty_list_is_valid(self, tmp_path: Path):
        path = tmp_path / "edits.json"
        path.write_text("[]")
        assert parse_patch_file(path) == []

    def test_non_list_top_level_rejected(self, tmp_path: Path):
        path = tmp_path / "edits.json"
        path.write_text('{"edits": []}')
        with pytest.raises(ValueError, match="top-level JSON list"):
            parse_patch_file(path)

    def test_non_object_entry_rejected(self, tmp_path: Path):
        path = tmp_path / "edits.json"
        path.write_text('["not an object"]')
        with pytest.raises(ValueError, match="must be an object"):
            parse_patch_file(path)


# ---------------------------------------------------------------------------
# validate_targets — scope enforcement
# ---------------------------------------------------------------------------


class TestValidateTargets:
    def test_in_scope_edit_passes_through(self):
        edits = [Edit(target="section:identification", edit_type="replace_text", find="x", replace="y")]
        findings = [_finding("section:identification")]
        in_scope, out_of_scope = validate_targets(edits, findings)
        assert len(in_scope) == 1
        assert out_of_scope == []

    def test_out_of_scope_edit_rejected(self):
        """The merger's load-bearing invariant: edits whose target
        isn't in the Finding list are rejected before any text is
        touched. This is the scope-enforcement-by-construction
        equivalent of unified diff's region constraint."""
        edits = [Edit(target="section:conclusion", edit_type="replace_text", find="x", replace="y")]
        findings = [_finding("section:identification")]
        in_scope, out_of_scope = validate_targets(edits, findings)
        assert in_scope == []
        assert len(out_of_scope) == 1
        assert "not in work order findings" in out_of_scope[0].error
        assert not out_of_scope[0].success

    def test_paper_full_finding_widens_scope_to_everything(self):
        edits = [
            Edit(target="section:conclusion", edit_type="replace_text", find="x", replace="y"),
            Edit(target="table:tab:other", edit_type="replace_text", find="x", replace="y"),
        ]
        findings = [_finding("paper:full")]
        in_scope, out_of_scope = validate_targets(edits, findings)
        # paper:full opens the door to everything.
        assert len(in_scope) == 2
        assert out_of_scope == []

    def test_no_findings_means_no_edits_in_scope(self):
        edits = [Edit(target="abstract", edit_type="replace_text", find="x", replace="y")]
        in_scope, out_of_scope = validate_targets(edits, [])
        assert in_scope == []
        assert len(out_of_scope) == 1
        assert "none" in out_of_scope[0].error  # the error names the empty set


# ---------------------------------------------------------------------------
# Region extraction (via apply_edit's effects)
# ---------------------------------------------------------------------------


class TestRegionExtraction:
    """Indirect coverage of _extract_region by checking which
    replacements land where."""

    def test_section_target_scopes_replacement(self):
        """An edit targeting `section:identification` must only edit
        within that section — even when the same text appears
        elsewhere in the draft."""
        text = _DRAFT
        # "headline" appears once in the Introduction, not in Identification.
        # Test: an edit targeting section:identification with find="headline"
        # must fail (not found in target region) even though it exists
        # elsewhere.
        edit = Edit(target="section:identification", edit_type="replace_text", find="headline", replace="X")
        _, result = apply_edit(text, edit)
        assert not result.success
        assert "not found within" in result.error

    def test_table_target_scopes_replacement(self):
        text = _DRAFT
        edit = Edit(target="table:tab:main", edit_type="replace_text", find="0.80", replace="0.50")
        new_text, result = apply_edit(text, edit)
        assert result.success
        # The 0.80 in the abstract is untouched.
        assert "0.80 according to our estimates" in new_text
        # The 0.80 in the table is replaced.
        assert "log RV & 0.50" in new_text

    def test_abstract_target_finds_abstract(self):
        text = _DRAFT
        edit = Edit(target="abstract", edit_type="replace_text", find="0.80", replace="0.50")
        new_text, result = apply_edit(text, edit)
        assert result.success
        # Abstract's 0.80 replaced; table's 0.80 untouched.
        assert "treatment effect is 0.50" in new_text
        assert "log RV & 0.80" in new_text  # table unchanged

    def test_references_target_finds_bibliography_line(self):
        text = _DRAFT
        edit = Edit(target="references", edit_type="replace_text", find="refs", replace="references")
        new_text, result = apply_edit(text, edit)
        assert result.success
        assert "\\bibliography{references}" in new_text

    def test_paper_full_target_finds_everything(self):
        text = _DRAFT
        # `0.80` appears in two places — must be ambiguous when target is
        # paper:full and find_must_be_unique=True.
        edit = Edit(
            target="paper:full",
            edit_type="replace_text",
            find="0.80",
            replace="0.50",
            find_must_be_unique=True,
        )
        _, result = apply_edit(text, edit)
        assert not result.success
        assert "ambiguous" in result.error
        assert result.matches == 2

    def test_paper_full_target_replace_all_when_unique_disabled(self):
        text = _DRAFT
        edit = Edit(
            target="paper:full",
            edit_type="replace_text",
            find="0.80",
            replace="0.50",
            find_must_be_unique=False,
        )
        new_text, result = apply_edit(text, edit)
        assert result.success
        # Both 0.80s flipped.
        assert new_text.count("0.80") == 0
        assert new_text.count("0.50") >= 2

    def test_missing_section_returns_failure(self):
        text = _DRAFT
        edit = Edit(target="section:phantom_section", edit_type="replace_text", find="x", replace="y")
        _, result = apply_edit(text, edit)
        assert not result.success
        assert "not found in document" in result.error

    def test_missing_table_label_returns_failure(self):
        text = _DRAFT
        edit = Edit(target="table:tab:nonexistent", edit_type="replace_text", find="x", replace="y")
        _, result = apply_edit(text, edit)
        assert not result.success
        assert "not found in document" in result.error


# ---------------------------------------------------------------------------
# v0.7.3: "did you mean..." suggestions on section/table not-found
# ---------------------------------------------------------------------------


class TestSectionTableCatalogHelpers:
    """v0.7.3 surfaces helpers that list the addressable targets in a
    draft. The merger uses them to enrich the error message when a
    section: or table: target isn't found; they're also exposed as
    public API for future tooling (e.g. an `e2er sections` debug
    command). Pin the contract."""

    def test_list_section_titles_in_document_order(self):
        # _DRAFT has \section{Introduction}, \section{Identification
        # Strategy}, \section{Results}
        titles = list_section_titles(_DRAFT)
        assert titles == ["Introduction", "Identification Strategy", "Results"]

    def test_list_section_titles_empty_when_no_sections(self):
        assert list_section_titles(r"\documentclass{article}\begin{document}\end{document}") == []

    def test_list_table_labels_in_document_order(self):
        labels = list_table_labels(_DRAFT)
        assert labels == ["tab:main"]

    def test_list_table_labels_empty_when_no_labelled_tables(self):
        tex = r"""
\begin{tabular}{lc}
x & 0.42 \\
\end{tabular}
"""
        assert list_table_labels(tex) == []


class TestApplyEditNotFoundIncludesSuggestions:
    """The v0.7.2 live re-validation REJECTED on a paper whose
    patch_revisor emitted ``section:results`` and ``section:mechanism``
    targets that didn't exist in the draft. The merger reported
    "target region not found" with no hint. v0.7.3 appends the list
    of available section names so the patch_revisor's retry has
    actionable info."""

    def test_section_not_found_error_lists_available_sections(self):
        edit = Edit(
            target="section:mechanism",  # NOT in _DRAFT
            edit_type="replace_text",
            find="x",
            replace="y",
        )
        _, result = apply_edit(_DRAFT, edit)
        assert not result.success
        assert "not found in document" in result.error
        # The actual available sections must be named verbatim
        assert "Introduction" in result.error
        assert "Identification Strategy" in result.error
        assert "Results" in result.error
        # And the "available sections:" lead-in so the patch_revisor
        # knows what the list means
        assert "available sections" in result.error

    def test_table_not_found_error_lists_available_labels(self):
        edit = Edit(
            target="table:tab:phantom",  # NOT in _DRAFT
            edit_type="replace_text",
            find="x",
            replace="y",
        )
        _, result = apply_edit(_DRAFT, edit)
        assert not result.success
        assert "not found in document" in result.error
        assert "tab:main" in result.error
        assert "available table labels" in result.error

    def test_no_suggestions_when_target_not_section_or_table(self):
        """For `paper:full` / `abstract` / `references`, suggestions
        aren't useful — these are universal targets. (And `paper:full`
        in particular never fails to resolve.) Just don't append the
        suggestion suffix."""
        # Construct a doc without an abstract
        empty_doc = r"\documentclass{article}\begin{document}\end{document}"
        edit = Edit(target="abstract", edit_type="replace_text", find="x", replace="y")
        _, result = apply_edit(empty_doc, edit)
        assert not result.success
        # The "available ..." suffix should NOT appear for abstract
        assert "available sections" not in result.error
        assert "available table labels" not in result.error

    def test_no_suggestions_when_no_sections_exist_at_all(self):
        """Defensive: if the draft has zero sections, suggesting
        '(available sections: )' would be misleading. Suppress the
        suffix entirely in that case."""
        tex = r"\documentclass{article}\begin{document}\end{document}"
        edit = Edit(target="section:anything", edit_type="replace_text", find="x", replace="y")
        _, result = apply_edit(tex, edit)
        assert not result.success
        # No "available sections:" line should appear when the list is empty
        assert "available sections" not in result.error


# ---------------------------------------------------------------------------
# apply_edit failure modes
# ---------------------------------------------------------------------------


class TestApplyEditFailureModes:
    def test_unknown_edit_type(self):
        text = _DRAFT
        edit = Edit(target="abstract", edit_type="reformat_everything", find="x", replace="y")
        _, result = apply_edit(text, edit)
        assert not result.success
        assert "unknown edit_type" in result.error

    def test_empty_find_rejected(self):
        text = _DRAFT
        edit = Edit(target="abstract", edit_type="replace_text", find="", replace="y")
        _, result = apply_edit(text, edit)
        assert not result.success
        assert "non-empty `find`" in result.error

    def test_find_not_in_region(self):
        text = _DRAFT
        edit = Edit(target="abstract", edit_type="replace_text", find="never appears here", replace="x")
        _, result = apply_edit(text, edit)
        assert not result.success
        assert "not found within" in result.error
        assert result.matches == 0


# ---------------------------------------------------------------------------
# apply_patch — sequential application + diff
# ---------------------------------------------------------------------------


class TestApplyPatch:
    def test_multiple_edits_applied_in_order(self):
        text = _DRAFT
        edits = [
            Edit(target="table:tab:main", edit_type="replace_text", find="0.80", replace="0.50"),
            Edit(target="abstract", edit_type="replace_text", find="0.80", replace="0.50"),
        ]
        result = apply_patch(text, edits)
        assert result.fully_applied
        assert result.n_applied == 2
        assert result.n_failed == 0
        assert "0.80" not in result.patched_text
        assert result.patched_text.count("0.50") >= 2

    def test_failed_edit_does_not_halt_subsequent_edits(self):
        text = _DRAFT
        edits = [
            Edit(target="section:phantom", edit_type="replace_text", find="x", replace="y"),  # FAILS
            Edit(target="table:tab:main", edit_type="replace_text", find="0.80", replace="0.50"),  # SUCCEEDS
        ]
        result = apply_patch(text, edits)
        assert result.n_applied == 1
        assert result.n_failed == 1
        # Second edit still applied.
        assert "log RV & 0.50" in result.patched_text

    def test_diff_emitted_on_change(self):
        text = _DRAFT
        edits = [Edit(target="table:tab:main", edit_type="replace_text", find="0.80", replace="0.50")]
        result = apply_patch(text, edits)
        assert result.diff
        assert "-log RV & 0.80 & 0.10 \\\\" in result.diff
        assert "+log RV & 0.50 & 0.10 \\\\" in result.diff

    def test_empty_edits_produces_empty_diff(self):
        text = _DRAFT
        result = apply_patch(text, [])
        assert result.diff == ""
        assert result.patched_text == text


# ---------------------------------------------------------------------------
# merge_patch_file — top-level entry
# ---------------------------------------------------------------------------


class TestMergePatchFile:
    def _setup(self, tmp_path: Path) -> Path:
        ws = tmp_path / "workspace"
        ws.mkdir()
        (ws / "paper_draft.tex").write_text(_DRAFT)
        return ws

    def test_persists_patched_draft_and_diff(self, tmp_path: Path):
        ws = self._setup(tmp_path)
        (ws / "paper_draft.tex.edits.json").write_text(
            json.dumps(
                [
                    {
                        "target": "table:tab:main",
                        "edit_type": "replace_text",
                        "find": "0.80",
                        "replace": "0.50",
                    }
                ]
            )
        )
        findings = [_finding("table:tab:main")]
        result = merge_patch_file(ws, findings)
        assert result.fully_applied

        # Draft was patched on disk
        patched = (ws / "paper_draft.tex").read_text()
        assert "log RV & 0.50" in patched
        assert "log RV & 0.80" not in patched

        # Diff side artifact written
        diff_path = ws / "paper_draft.tex.applied.diff"
        assert diff_path.is_file()
        diff_text = diff_path.read_text()
        assert "-log RV & 0.80" in diff_text
        assert "+log RV & 0.50" in diff_text

    def test_out_of_scope_edit_rolled_into_failures(self, tmp_path: Path):
        ws = self._setup(tmp_path)
        (ws / "paper_draft.tex.edits.json").write_text(
            json.dumps(
                [
                    {
                        "target": "section:conclusion",  # NOT in findings
                        "edit_type": "replace_text",
                        "find": "x",
                        "replace": "y",
                    }
                ]
            )
        )
        findings = [_finding("table:tab:main")]
        result = merge_patch_file(ws, findings, persist=False)
        assert result.n_applied == 0
        assert result.n_failed == 1
        assert "not in work order findings" in result.failed[0].error

    def test_missing_draft_raises(self, tmp_path: Path):
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "paper_draft.tex.edits.json").write_text("[]")
        with pytest.raises(FileNotFoundError, match="draft not found"):
            merge_patch_file(ws, [])

    def test_missing_patch_file_raises(self, tmp_path: Path):
        ws = self._setup(tmp_path)
        with pytest.raises(FileNotFoundError, match="patch file not found"):
            merge_patch_file(ws, [])

    def test_persist_false_does_not_write(self, tmp_path: Path):
        ws = self._setup(tmp_path)
        (ws / "paper_draft.tex.edits.json").write_text(
            json.dumps(
                [
                    {
                        "target": "table:tab:main",
                        "edit_type": "replace_text",
                        "find": "0.80",
                        "replace": "0.50",
                    }
                ]
            )
        )
        original = (ws / "paper_draft.tex").read_text()
        result = merge_patch_file(ws, [_finding("table:tab:main")], persist=False)
        assert result.fully_applied
        # Draft is unchanged on disk
        assert (ws / "paper_draft.tex").read_text() == original
        # No diff file emitted
        assert not (ws / "paper_draft.tex.applied.diff").exists()


# ---------------------------------------------------------------------------
# patch_revisor specialist registry wiring
# ---------------------------------------------------------------------------


class TestPatchRevisorRegistry:
    def test_patch_revisor_artifact(self):
        from src.core.specialists.registry import SPECIALIST_ARTIFACTS

        assert SPECIALIST_ARTIFACTS["patch_revisor"] == "paper_draft.tex.edits.json"

    def test_patch_revisor_loads_scoped_revision_skill(self):
        from src.core.specialists.registry import SPECIALIST_SKILLS

        skills = SPECIALIST_SKILLS["patch_revisor"]
        assert "writing/scoped-revision" in skills, (
            "patch_revisor MUST load writing/scoped-revision — without it "
            "the specialist has no contract for the patch file format"
        )

    def test_patch_revisor_loads_cite_skill(self):
        """v0.5 cite-by-source discipline applies to patched edits too —
        otherwise revisions can introduce new hallucinations the
        original gate already cleared."""
        from src.core.specialists.registry import SPECIALIST_SKILLS

        assert "writing/cite-numbers-by-source" in SPECIALIST_SKILLS["patch_revisor"]

    def test_scoped_revision_skill_file_exists(self):
        skill_path = Path(__file__).resolve().parents[2] / "skills" / "files" / "writing" / "scoped-revision.md"
        assert skill_path.exists(), f"scoped-revision.md missing at {skill_path}"
