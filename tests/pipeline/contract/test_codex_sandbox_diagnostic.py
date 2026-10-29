"""Codex on Linux and Windows: a sandbox that refuses every write is named, with its remedy.

Tester report, 2026-10-27: on Ubuntu (bubblewrap under AppArmor) and Windows
(openai/codex#30009: apply_patch fails under workspace-write with extra writable
folders) Codex's sandbox refused every specialist's write, Codex still exited 0,
and e2er said only "contract violation: <file>: file not written", three times.
The subprocess is mocked; the event shapes are those of `codex exec --json`.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from src.config import get_settings
from src.modules.llm.base import ToolLoopResult
from src.modules.llm.codex import CodexBackend, parse_codex_events, sandbox_diagnostic


def _events(*evs: dict) -> str:
    return "\n".join(json.dumps(e) for e in evs) + "\n"


_USAGE = {"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 5}}
_REFUSED_PATCH = {
    "type": "item.completed",
    "item": {"id": "1", "type": "file_change", "status": "failed", "changes": [{"path": "plan.md", "kind": "add"}]},
}
_REFUSED_COMMAND = {
    "type": "item.completed",
    "item": {
        "id": "2",
        "type": "command_execution",
        "command": "python3 analysis.py",
        "aggregated_output": "Traceback ...\nbwrap: setting up uid map: Permission denied\n",
        "exit_code": 1,
        "status": "failed",
    },
}
_WRITTEN = {
    "type": "item.completed",
    "item": {"id": "3", "type": "file_change", "status": "completed", "changes": [{"path": "plan.md", "kind": "add"}]},
}


def test_refused_patches_and_commands_are_read_from_the_events():
    parsed = parse_codex_events(_events(_REFUSED_PATCH, _REFUSED_COMMAND, _USAGE))
    assert parsed["error"] == "" and parsed["files_changed"] == 0
    assert parsed["sandbox_denials"][0] == "file change refused (plan.md)"
    assert "bwrap: setting up uid map: Permission denied" in parsed["sandbox_denials"][1]


def test_an_ordinary_failing_command_is_no_sandbox_refusal():
    failing = {
        "type": "item.completed",
        "item": {"type": "command_execution", "command": "python3 x.py", "aggregated_output": "ZeroDivisionError",
                 "exit_code": 1, "status": "failed"},
    }  # fmt: skip
    parsed = parse_codex_events(_events(failing, _WRITTEN, _USAGE))
    assert parsed["sandbox_denials"] == [] and parsed["files_changed"] == 1
    assert sandbox_diagnostic(parsed, platform="linux") == ""


@pytest.mark.parametrize(
    "platform, remedy",
    [("linux", "apparmor_restrict_unprivileged_userns"), ("win32", "#30009")],
)
def test_the_diagnostic_names_the_remedy_for_the_system(platform, remedy):
    parsed = parse_codex_events(_events(_REFUSED_PATCH, _USAGE))
    text = sandbox_diagnostic(parsed, platform=platform)
    assert text.startswith("Codex's sandbox refused a write or command (file change refused (plan.md))")
    assert remedy in text
    assert "CODEX_SANDBOX=danger-full-access" in text and "CODEX_ALLOW_FULL_ACCESS=true" in text


def test_no_file_change_at_all_on_linux_or_windows_is_named_too():
    parsed = parse_codex_events(
        _events({"type": "item.completed", "item": {"type": "agent_message", "text": "ok"}}, _USAGE)
    )
    assert "Codex changed no file in this call" in sandbox_diagnostic(parsed, platform="win32")
    assert sandbox_diagnostic(parsed, platform="darwin") == "", "macOS (validated) is unchanged"


def test_no_diagnostic_without_the_workspace_write_sandbox():
    parsed = parse_codex_events(_events(_REFUSED_PATCH, _USAGE))
    assert sandbox_diagnostic(parsed, platform="linux", sandbox="danger-full-access") == ""


async def test_the_backend_returns_the_diagnostic_with_a_successful_call(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CODEX_SANDBOX", raising=False)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'db' / 'papers.db'}")
    get_settings.cache_clear()
    stdout = _events(_REFUSED_PATCH, _USAGE).encode()

    async def fake_exec(*args, **kwargs):
        proc = MagicMock()
        proc.pid = 4242
        proc.returncode = 0  # Codex exits 0 although nothing was written

        async def _comm(input: bytes = b""):
            return (stdout, b"")

        proc.communicate = _comm
        return proc

    monkeypatch.setattr("src.modules.llm.codex.sys.platform", "linux")
    with patch("src.modules.llm.codex.asyncio.create_subprocess_exec", new=fake_exec):
        result = await CodexBackend().tool_loop(
            system="s", messages=[{"role": "user", "content": "u"}], tools=[], tool_handler=None
        )
    get_settings.cache_clear()
    assert result.success is True
    assert "file change refused (plan.md)" in result.diagnostic and "bubblewrap" in result.diagnostic


async def _async_noop(*args, **kwargs):
    return None


async def test_the_contract_violation_carries_the_diagnostic(tmp_workspace, paper_id):
    """The researcher sees why the file is missing; the model's retry feedback does not get it."""
    from unittest.mock import AsyncMock

    from src.core.specialists.base import run_specialist
    from src.core.specialists.contract_check import read_contract_feedback
    from src.core.specialists.contracts import WorkOrder
    from src.modules.llm.base import LLMBackend

    diagnostic = "Codex's sandbox refused a write or command (file change refused (plan.md))."

    class WroteNothing(LLMBackend):
        async def tool_loop(self, system, messages, tools, tool_handler, max_turns=30, **kw):
            return ToolLoopResult(success=True, output="done", tool_calls_made=1, diagnostic=diagnostic)

    wo = WorkOrder(paper_id=paper_id, specialist="econometrics_specialist", focus="Specify.", context_tier=1)
    with (
        patch("src.core.specialists.base.save_usage", new=_async_noop),
        patch("src.core.specialists.base.compute_cost", return_value=0),
        patch("src.db.client.execute", new=_async_noop),
        patch("src.db.events.log_event", new=AsyncMock(return_value=None)),
    ):
        contribution = await run_specialist(
            wo, backend=WroteNothing(), workspace=tmp_workspace, model="m", backend_name="codex", governance="full"
        )
    assert contribution.success is False
    assert "contract violation" in contribution.error and "file not written" in contribution.error
    assert diagnostic in contribution.error
    feedback = read_contract_feedback(tmp_workspace, "econometrics_specialist") or ""
    assert "file not written" in feedback and "sandbox" not in feedback
