"""A cost cap of NaN or infinity switched the budget check off (review of 2026-11-21, finding 11)."""

from __future__ import annotations

import argparse
import asyncio
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from src.__main__ import _cost_cap
from src.api.app import CreatePaperRequest, ResumeRequest


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), 0.0, -1.0])
def test_the_requests_refuse_a_cap_that_is_no_cap(value):
    with pytest.raises(ValidationError):
        CreatePaperRequest(title="t", research_question="q", max_cost_usd=value)
    if value <= 0:
        return  # resume_paper answers 400 for those, as before
    with pytest.raises(ValidationError):
        ResumeRequest(max_cost_usd=value)


def test_the_json_api_refuses_nan():
    from fastapi.testclient import TestClient

    from src.api.app import app

    r = TestClient(app).post(
        "/api/papers/00000000-0000-0000-0000-000000000000/resume",
        content=b'{"max_cost_usd": NaN}',
        headers={"content-type": "application/json"},
    )
    assert r.status_code == 422


@pytest.mark.parametrize("text", ["nan", "inf", "-inf", "0", "-3", "five"])
def test_the_command_line_refuses_it(text):
    with pytest.raises(argparse.ArgumentTypeError):
        _cost_cap(text)
    assert _cost_cap("2.5") == 2.5


def test_the_budget_check_holds_even_so():
    from src.core.strategist.state import BudgetExceededError
    from src.modules.tracking.usage import check_budget

    async def fetch_one(*a, **k):
        return {"spent": 1000.0}

    with patch("src.db.client.fetch_one", side_effect=fetch_one), pytest.raises(BudgetExceededError):
        asyncio.run(check_budget("p", float("nan")))
