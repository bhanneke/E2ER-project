"""Send back offers the specialists the study ran, not every specialist whose output file exists.

Several specialists write paper_draft.tex, so a descriptive study's draft review
offered the field-map and systematic-review writers (2026-10-13 demo).
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from src.api.app import _sendable


def _state():
    return SimpleNamespace(completed_stages=[], metadata={})


def test_only_specialists_that_ran_are_offered(tmp_path: Path):
    (tmp_path / "paper_draft.tex").write_text("x")
    pending = SimpleNamespace(kind="researcher", stage="review_draft")
    offered = _sendable(tmp_path, _state(), pending, None, {"paper_drafter", "data_analyst"})
    assert "paper_drafter" in offered
    assert "field_review_writer" not in offered and "meta_review_writer" not in offered


def test_without_a_log_every_specialist_with_output_stays(tmp_path: Path):
    (tmp_path / "paper_draft.tex").write_text("x")
    pending = SimpleNamespace(kind="researcher", stage="review_draft")
    offered = _sendable(tmp_path, _state(), pending, None, None)
    assert {"paper_drafter", "field_review_writer"} <= set(offered)
