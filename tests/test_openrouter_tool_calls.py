"""The OpenRouter tool loop with what providers actually send (review of 2026-11-23).

- Some providers end a turn that asks for tools with ``finish_reason="stop"``: the calls run.
- Some stream tool-call fragments without an ``index``: the fragments join the call they belong to.
- Reasoning models send ``reasoning_details``; they go back with the tool results unchanged.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from src.modules.llm.base import ToolHandler
from src.modules.llm.openrouter import _collect


class _Handler(ToolHandler):
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def can_handle(self, tool_name: str) -> bool:
        return True

    async def handle(self, tool_name: str, tool_input: dict) -> str:
        self.calls.append((tool_name, dict(tool_input)))
        return "written"


def _chunk(*, content=None, calls=None, finish=None, reasoning=None, usage=None):
    delta = SimpleNamespace(content=content, tool_calls=calls, model_extra={})
    if reasoning is not None:
        delta.model_extra = {"reasoning_details": reasoning}
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta, finish_reason=finish)], usage=usage, model_extra={})


def _frag(*, index=None, id=None, name=None, args=None):
    return SimpleNamespace(index=index, id=id, function=SimpleNamespace(name=name, arguments=args))


async def _stream(chunks):
    for c in chunks:
        yield c


async def test_fragments_without_an_index_join_their_call():
    chunks = [
        _chunk(calls=[_frag(id="a", name="write_file", args='{"path": "x.py", ')]),
        _chunk(calls=[_frag(args='"content": "print(1)"}')]),
        _chunk(calls=[_frag(id="b", name="read_file", args='{"path": "y.csv"}')]),
        _chunk(finish="tool_calls"),
    ]
    out = await _collect(_stream(chunks))
    calls = out.choices[0].message.tool_calls
    assert [(c.id, c.function.name) for c in calls] == [("a", "write_file"), ("b", "read_file")]
    assert json.loads(calls[0].function.arguments) == {"path": "x.py", "content": "print(1)"}


async def test_numbered_fragments_still_go_by_index():
    chunks = [
        _chunk(calls=[_frag(index=0, id="a", name="write_file", args='{"path"')]),
        _chunk(calls=[_frag(index=1, id="b", name="read_file", args='{"path": "y"}')]),
        _chunk(calls=[_frag(index=0, args=': "x"}')]),
        _chunk(finish="tool_calls"),
    ]
    calls = (await _collect(_stream(chunks))).choices[0].message.tool_calls
    assert [json.loads(c.function.arguments) for c in calls] == [{"path": "x"}, {"path": "y"}]


async def test_reasoning_details_are_collected():
    blocks = [{"type": "reasoning.encrypted", "data": "abc", "index": 0}]
    chunks = [
        _chunk(reasoning=blocks),
        _chunk(calls=[_frag(index=0, id="a", name="list_directory", args="{}")]),
        _chunk(finish="tool_calls"),
    ]
    msg = (await _collect(_stream(chunks))).choices[0].message
    assert msg.reasoning_details == blocks


def _response(*, finish, content="", calls=None, reasoning=None):
    msg = SimpleNamespace(content=content, tool_calls=calls, reasoning_details=reasoning)
    return SimpleNamespace(
        choices=[SimpleNamespace(finish_reason=finish, message=msg)],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, prompt_tokens_details=None, cost=None),
        model_extra={},
    )


def _call(id, name, args):
    return SimpleNamespace(id=id, type="function", function=SimpleNamespace(name=name, arguments=args))


@pytest.fixture
def backend(monkeypatch):
    pytest.importorskip("openai")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    from src.config import get_settings

    get_settings.cache_clear()
    from src.modules.llm.openrouter import OpenRouterBackend

    return OpenRouterBackend()


async def test_tool_calls_run_when_the_provider_says_stop_and_reasoning_goes_back(backend, monkeypatch):
    blocks = [{"type": "reasoning.text", "text": "plan", "index": 0}]
    sent: list[list[dict]] = []
    answers = [
        _response(
            finish="stop", calls=[_call("a", "write_file", '{"path": "x.py", "content": "1"}')], reasoning=blocks
        ),
        _response(finish="stop", content="Done."),
    ]

    async def create(kwargs, turn):
        sent.append(json.loads(json.dumps(kwargs["messages"], default=str)))
        return answers[turn]

    monkeypatch.setattr(backend, "_create", create)
    handler = _Handler()
    result = await backend.tool_loop(
        system="s",
        messages=[{"role": "user", "content": "go"}],
        tools=[{"name": "write_file", "description": "", "input_schema": {"type": "object"}}],
        tool_handler=handler,
        max_turns=5,
    )
    assert result.success and result.output == "Done."
    assert handler.calls == [("write_file", {"path": "x.py", "content": "1"})]
    assistant = next(m for m in sent[1] if m["role"] == "assistant")
    assert assistant["reasoning_details"] == blocks


# --- limits inside a step (review of 2026-11-23) ------------------------------------------------


async def test_the_spending_limit_inside_a_step_pauses_the_run(backend, monkeypatch):
    from src.core.strategist.state import BudgetExceededError

    async def over(paper_id, loop_key, cost):
        return True, 5.02, 5.0

    recorded = []

    async def record(*a):
        recorded.append(a)

    monkeypatch.setattr("src.modules.tracking.usage.loop_over_budget", over)
    monkeypatch.setattr("src.modules.tracking.usage.record_cancelled_loop", record)
    with pytest.raises(BudgetExceededError) as e:
        await backend.tool_loop(
            system="s",
            messages=[{"role": "user", "content": "go"}],
            tools=[],
            tool_handler=None,
            max_turns=3,
            paper_id="p1",
            specialist="data_analyst",
        )
    assert (e.value.spent, e.value.cap) == (5.02, 5.0) and recorded and recorded[0][0] == "p1"


async def test_too_little_credit_for_the_output_limit_asks_for_less(backend, monkeypatch):
    calls: list[int] = []

    async def create(kwargs, turn):
        calls.append(kwargs["max_tokens"])
        if len(calls) == 1:
            raise RuntimeError(
                "Error code: 402 - This request requires more credits, or fewer max_tokens. "
                "You requested up to 32768 tokens, but can only afford 9000."
            )
        return _response(finish="stop", content="Done.")

    monkeypatch.setattr(backend, "_create", create)
    result = await backend.tool_loop(
        system="s", messages=[{"role": "user", "content": "go"}], tools=[], tool_handler=None, max_turns=4
    )
    assert result.success and calls[0] > 9000 and calls[1] == 9000 - 64


async def test_the_step_stops_at_its_time_limit(backend, monkeypatch):
    import asyncio

    from src.modules.llm.cli_support import call_timeout

    class Slow(_Handler):
        async def handle(self, tool_name, tool_input):
            await asyncio.sleep(1.2)
            return "ok"

    async def create(kwargs, turn):
        return _response(finish="tool_calls", calls=[_call(f"c{turn}", "list_directory", "{}")])

    monkeypatch.setattr(backend, "_create", create)
    token = call_timeout.set((1, False))
    try:
        result = await backend.tool_loop(
            system="s",
            messages=[{"role": "user", "content": "go"}],
            tools=[{"name": "list_directory", "description": "", "input_schema": {"type": "object"}}],
            tool_handler=Slow(),
            max_turns=10,
        )
    finally:
        call_timeout.reset(token)
    assert not result.success and result.stop_reason == "timeout" and "limit 1s" in result.error


def test_the_strategist_tells_paid_backends_its_study_only():
    from pathlib import Path

    from src.core.strategist.engine import StrategistEngine

    class Paid:
        bills_per_call = True

    class Cli:
        pass

    assert StrategistEngine(Paid(), Path("."), "p1")._paid_call() == {"paper_id": "p1"}
    assert StrategistEngine(Cli(), Path("."), "p1")._paid_call() == {}
