"""`e2er rq` — refine a draft research question (WS-P2, pillar b).

The backend + context-gathering are mocked; the tests pin the structured
output, the normalization, error handling, sovereignty (never creates a
paper), and the `run --rq-file` resolution.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from unittest.mock import AsyncMock

import src.cli_rq as m

_PAYLOAD = {
    "research_question": "Does concentrated liquidity (Uniswap v3) reduce impermanent loss for LPs?",
    "rationale": "Sharpens the unit of analysis to the pool and names the mechanism.",
    "candidate_variables": ["impermanent_loss", "pool_type", "trading_volume"],
    "identification_options": ["DiD around the v3 launch", "matched v2/v3 pools"],
    "feasibility_notes": ["needs pool-level LP position data"],
}


def _mock_pipeline(monkeypatch, output: str):
    monkeypatch.setattr(m, "_gather_context", AsyncMock(return_value=([], [])))
    monkeypatch.setattr(m, "_call_backend", AsyncMock(return_value=output))


def test_rq_produces_valid_json(tmp_path: Path, monkeypatch):
    _mock_pipeline(monkeypatch, json.dumps(_PAYLOAD))
    out = tmp_path / "rq.json"
    rc = m.rq("does clv help LPs", out=str(out))
    assert rc == 0
    data = json.loads(out.read_text())
    assert set(m.RQ_KEYS) <= set(data)
    assert data["research_question"].startswith("Does concentrated liquidity")
    assert data["candidate_variables"] == ["impermanent_loss", "pool_type", "trading_volume"]


def test_rq_parses_fenced_json(tmp_path: Path, monkeypatch):
    _mock_pipeline(monkeypatch, f"```json\n{json.dumps(_PAYLOAD)}\n```")
    rc = m.rq("draft", out=str(tmp_path / "rq.json"))
    assert rc == 0
    assert json.loads((tmp_path / "rq.json").read_text())["research_question"]


def test_rq_normalizes_scalar_to_list(tmp_path: Path, monkeypatch):
    _mock_pipeline(monkeypatch, json.dumps({"research_question": "RQ", "feasibility_notes": "single note"}))
    out = tmp_path / "rq.json"
    assert m.rq("draft", out=str(out)) == 0
    data = json.loads(out.read_text())
    assert data["feasibility_notes"] == ["single note"]
    assert data["candidate_variables"] == []  # missing → empty list


def test_rq_empty_draft_is_rejected(monkeypatch):
    assert m.rq("   ") == 2


def test_rq_backend_without_research_question_fails(monkeypatch):
    _mock_pipeline(monkeypatch, json.dumps({"rationale": "no RQ here"}))
    assert m.rq("draft") == 1


def test_rq_backend_error_is_handled(monkeypatch):
    monkeypatch.setattr(m, "_gather_context", AsyncMock(return_value=([], [])))
    monkeypatch.setattr(m, "_call_backend", AsyncMock(side_effect=RuntimeError("no API key")))
    assert m.rq("draft") == 1


def test_rq_never_creates_a_paper():
    """Sovereignty: the rq command must not submit or create a paper."""
    src = inspect.getsource(m)
    assert "create_paper" not in src
    assert "/api/papers" not in src


# ── run --rq-file resolution ─────────────────────────────────────────────────


def test_resolve_rq_input_from_json_file(tmp_path: Path):
    from src.cli_run import resolve_rq_input

    j = tmp_path / "rq.json"
    j.write_text(json.dumps({"research_question": "From the rq.json file"}))
    assert resolve_rq_input(None, str(j)) == "From the rq.json file"


def test_resolve_rq_input_from_plain_text(tmp_path: Path):
    from src.cli_run import resolve_rq_input

    t = tmp_path / "rq.txt"
    t.write_text("A plain-text research question\n")
    assert resolve_rq_input(None, str(t)) == "A plain-text research question"


def test_resolve_rq_input_positional_and_none(tmp_path: Path):
    from src.cli_run import resolve_rq_input

    assert resolve_rq_input("Positional RQ", None) == "Positional RQ"
    assert resolve_rq_input(None, None) is None
