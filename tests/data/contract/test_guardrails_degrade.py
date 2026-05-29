"""Regression: a missing data_dictionary must NOT bypass all guardrails.

Before the fix, `validate_all` was only called when a dictionary was present,
so a production query with no `data_dictionary.json` ran with ZERO validation
(no SELECT*, no time-bound, no feasibility-first). Now only the field-whitelist
(Rule 2) is dictionary-gated; the structural rules always fire.
"""

from __future__ import annotations

from src.modules.data.guardrails import QueryValidator


async def test_select_star_blocked_without_dictionary():
    r = await QueryValidator.validate_all(
        sql="SELECT * FROM ethereum.transactions WHERE block_time > '2024-01-01'",
        query_type="feasibility",  # avoids the DB-backed Rule 5
        fields_requested=[],
        aggregation_level="daily",
        granularity_justification="",
        dictionary=None,
        paper_id="p1",
    )
    assert not r.valid
    assert "SELECT *" in r.rejection_reason


async def test_missing_time_bound_blocked_without_dictionary():
    r = await QueryValidator.validate_all(
        sql="SELECT from_address, value FROM ethereum.transactions",
        query_type="feasibility",
        fields_requested=["from_address", "value"],
        aggregation_level="daily",
        granularity_justification="",
        dictionary=None,
        paper_id="p1",
    )
    assert not r.valid
    assert "time-bound" in r.rejection_reason.lower()


async def test_valid_query_passes_without_dictionary_but_warns():
    r = await QueryValidator.validate_all(
        sql="SELECT from_address, value FROM ethereum.transactions WHERE block_time > '2024-01-01'",
        query_type="feasibility",
        fields_requested=["from_address", "value"],
        aggregation_level="daily",
        granularity_justification="",
        dictionary=None,
        paper_id="p1",
    )
    assert r.valid
    assert any("field-whitelist" in w.lower() or "rule 2" in w.lower() for w in r.warnings)
