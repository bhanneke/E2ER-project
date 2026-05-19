"""Pin the v0.4.5 fix for the `pipeline_mode` → `mode` field alias.

Live test eea5379b on v0.4.4 had `e2er run --mode single_pass` POST
`{"pipeline_mode": "single_pass", ...}` to /api/papers. Pydantic
silently dropped the unknown field, the API used its `mode="iterative"`
default, and the first-run log line falsely reported mode=iterative
even though the user picked single_pass.

Fix: CreatePaperRequest.mode now accepts `mode` or `pipeline_mode` via
`AliasChoices`. cli_run.py was also updated to send the canonical
`mode` field — but the alias keeps older external clients working.
"""

from __future__ import annotations

from src.api.app import CreatePaperRequest


def test_accepts_canonical_mode_field() -> None:
    req = CreatePaperRequest.model_validate({"title": "T", "research_question": "Q", "mode": "single_pass"})
    assert req.mode == "single_pass"


def test_accepts_legacy_pipeline_mode_alias() -> None:
    """External clients + tests/pipeline/integration/test_e2e_smoke.py
    still send `pipeline_mode` — keep that working."""
    req = CreatePaperRequest.model_validate({"title": "T", "research_question": "Q", "pipeline_mode": "single_pass"})
    assert req.mode == "single_pass", f"pipeline_mode alias not honored: got mode={req.mode!r}"


def test_defaults_to_iterative_when_neither_supplied() -> None:
    req = CreatePaperRequest.model_validate({"title": "T", "research_question": "Q"})
    assert req.mode == "iterative"
