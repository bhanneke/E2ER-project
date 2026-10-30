"""The targeted corrections' replacement sentences pass the phrase check (2026-10-11)."""

import json

from src.core.specialists.contract_check import check_patch_phrases


def _write(tmp_path, edits):
    (tmp_path / "paper_draft.tex.edits.json").write_text(json.dumps(edits), encoding="utf-8", newline="\n")


def test_a_replacement_with_a_rejected_construction_fails(tmp_path):
    _write(
        tmp_path,
        [{"edit_type": "replace_text", "find": "old", "replace": "Against this background, the radii are calculated."}],
    )
    c = check_patch_phrases(tmp_path)
    assert not c.ok and "Against this background" in c.reason


def test_clean_replacements_and_keeps_pass(tmp_path):
    _write(
        tmp_path,
        {
            "edits": [
                {
                    "edit_type": "replace_text",
                    "find": "old",
                    "replace": "The archive calculates these radii from the planets' masses.",
                },
                {"edit_type": "keep", "find": "x", "reason": "rather than is quoted from the source"},
            ]
        },
    )
    assert check_patch_phrases(tmp_path).ok


def test_no_edits_file_passes(tmp_path):
    assert check_patch_phrases(tmp_path).ok
