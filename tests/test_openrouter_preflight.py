"""OpenRouter's check before a run, and refusals no retry fixes (review of 2026-11-23).

A wrong key, a model without tool support or with too little context used to fail every step three
times; the run now pauses before the first step, or at the first such refusal, and says what to change.
"""

from __future__ import annotations

import pytest

from src.modules.llm import openrouter as orb
from src.modules.llm.openrouter_models import OpenRouterModel, parse_models
from src.modules.llm.plan_limit import BackendSetupError, detect_setup


def _model(**kw):
    base = dict(
        id="x/m",
        name="M",
        input_per_m="1",
        output_per_m="2",
        cache_read_per_m=None,
        context_length=200_000,
        tools=True,
        max_completion_tokens=8192,
    )
    base.update(kw)
    return OpenRouterModel(**base)


@pytest.fixture
def backend(monkeypatch):
    pytest.importorskip("openai")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    from src.config import get_settings

    get_settings.cache_clear()
    b = orb.OpenRouterBackend(model="x/m")
    b._max_tokens = 32768
    return b


def _with(monkeypatch, key, model):
    async def key_info(_):
        return key

    monkeypatch.setattr(orb, "_key_info", key_info)
    monkeypatch.setattr("src.modules.llm.openrouter_models.find_model", lambda m, network=False: model)


async def test_a_good_key_and_model_pass_and_the_output_limit_follows_the_model(backend, monkeypatch):
    _with(monkeypatch, {"limit_remaining": 4.2}, _model())
    await backend.preflight()
    assert backend._max_tokens == 8192


@pytest.mark.parametrize(
    ("key", "model", "says"),
    [
        ("rejected", _model(), "does not accept the key (401)"),
        ({}, _model(tools=False), "cannot call tools"),
        ({}, _model(context_length=32_000), "reads at most 32,000 tokens"),
    ],
)
async def test_what_no_step_could_survive_stops_before_the_first(backend, monkeypatch, key, model, says):
    _with(monkeypatch, key, model)
    with pytest.raises(BackendSetupError) as e:
        await backend.preflight()
    assert (
        says in e.value.status
        and e.value.status.startswith("Stopped before the first step")
        and e.value.event == "paused_backend_setup"
    )


async def test_offline_the_run_goes_on(backend, monkeypatch):
    _with(monkeypatch, None, None)
    await backend.preflight()
    assert backend._max_tokens == 32768


def test_refusals_during_a_run_pause_it():
    assert (
        "does not accept the key"
        in detect_setup("openrouter", "Error code: 401 - {'error': {'message': 'User not found.'}}").status
    )
    assert (
        "can call tools"
        in detect_setup("openrouter", "Error code: 404 - No endpoints found that support tool use.").status
    )
    assert detect_setup("openrouter", "Error code: 429 - rate limited") is None
    assert detect_setup("codex", "Error code: 401") is None


def test_the_model_list_reads_the_output_limit():
    m = parse_models(
        {
            "data": [
                {
                    "id": "a/b",
                    "context_length": 1000,
                    "supported_parameters": ["tools"],
                    "top_provider": {"max_completion_tokens": 512},
                    "pricing": {},
                }
            ]
        }
    )["a/b"]
    assert m.max_completion_tokens == 512 and m.tools


async def test_a_used_up_key_limit_pauses_at_the_billing_limit(backend, monkeypatch):
    from src.modules.llm.plan_limit import BillingLimitReachedError, is_plan_limit_status

    _with(monkeypatch, {"limit_remaining": 0}, _model())
    with pytest.raises(BillingLimitReachedError) as e:
        await backend.preflight()
    assert e.value.event == "paused_billing_limit" and is_plan_limit_status(e.value.status)


def test_the_setup_pause_reads_as_a_pause():
    from src.modules.llm.plan_limit import is_plan_limit_status

    status = detect_setup("openrouter", "Error code: 401 - User not found.").status
    assert is_plan_limit_status(status) and ";" not in status
