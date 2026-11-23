"""The e2er commands as tools, for the backends that call a model through an API (OpenRouter, Anthropic).

Under Claude Code, Codex and Gemini the model runs ``e2er-run``, ``e2er-data``, ``e2er-lit``,
``e2er-check-tables`` and ``e2er-fieldmap`` in its shell (``claude_code.allowed_tools_for``). A model
reached through an API has no shell. Without these tools a script writer could not run its script
before handing it in (the first run came after the step, where a bug cost a whole new attempt),
and the skills' instructions named commands the model did not have.

Each tool has the command's name and takes the words after it (``args``), so every instruction
written for the shell holds as it stands. A call starts the command's own code as a separate
process in the study's folder, so each command keeps its guarantees: ``e2er-run`` runs one
workspace-relative ``.py`` file with its time limit, in the operating system's sandbox, without
keys, recorded in the script log; ``e2er-data`` records each load in ``data_sources.json``. The
specialists that get each tool are the ones Claude Code gives the command to.
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path
from typing import Any

from .base import ToolHandler

#: The folder that holds e2er's ``src`` package (a checkout or site-packages).
_PACKAGE_ROOT = Path(__file__).resolve().parents[3]
#: The tail of a command's output the model sees (a traceback ends there).
_OUTPUT_TAIL = 12_000

#: Command → its entry point (pyproject.toml [project.scripts]).
ENTRY_POINTS: dict[str, tuple[str, str]] = {
    "e2er-run": ("src.wrappers", "run_main"),
    "e2er-data": ("src.modules.data.cli", "main"),
    "e2er-lit": ("src.wrappers", "lit_main"),
    "e2er-check-tables": ("src.wrappers", "check_tables_main"),
    "e2er-fieldmap": ("src.modules.fieldmap.cli", "main"),
}

_RUNNER = """
import importlib, sys
module, name = sys.argv[1], sys.argv[2]
sys.argv = [sys.argv[3], *sys.argv[4:]]
sys.exit(getattr(importlib.import_module(module), name)(sys.argv[1:]))
"""

_DESCRIPTIONS = {
    "e2er-run": (
        "Run one Python script of the study's folder and see its output and exit code: args = [the "
        'workspace-relative .py path], e.g. ["run_estimation.py"]. It runs as the reader\'s computer '
        "will run it (a time limit, no keys, recorded in the study's script log). After writing your "
        "script, run it, read the traceback if it fails, fix the file and run it again before you finish."
    ),
    "e2er-data": (
        "The data command: args = the words after `e2er-data`, as the instructions write them, e.g. "
        '["--help"], ["worldbank", "--help"], ["query", "tables"], ["query", "sql", "SELECT ..."]. '
        "It loads data from the sources and records each load for the study."
    ),
    "e2er-lit": (
        'The literature command: args = the words after `e2er-lit`, e.g. ["search", "query words", '
        '"--limit", "5"], ["list"], ["save", "--doi", "10.1234/x"]. A work it finds becomes citable.'
    ),
    "e2er-check-tables": (
        "Render results/table_spec.json and list every cell that does not resolve to a value in the "
        "results: args = []. Run it after writing or changing the table spec."
    ),
    "e2er-fieldmap": (
        'The field map\'s steps: args = the words after `e2er-fieldmap`, e.g. ["count", "--query", '
        '"\\"main path\\" OR \\"main paths\\"", "--from", "1989", "--to", "2026"], ["boundary"], '
        '["mainpath", "--key-routes", "10"]. Exit code 0 when the step passed.'
    ),
}


def _tool(name: str) -> dict[str, Any]:
    return {
        "name": name,
        "description": _DESCRIPTIONS[name],
        "input_schema": {
            "type": "object",
            "properties": {
                "args": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "The words after the command name, one per item, unquoted.",
                }
            },
            "required": ["args"],
        },
    }


def command_tools_for(specialist: str | None) -> list[dict[str, Any]]:
    """The command tools a specialist gets: the commands Claude Code lets it run."""
    from .claude_code import (
        _FIELDMAP_SPECIALISTS,
        _LITERATURE_SPECIALISTS,
        _SCRIPT_WRITING_SPECIALISTS,
        _SPEC_WRITING_SPECIALISTS,
    )

    names = ["e2er-data"]
    if specialist in _LITERATURE_SPECIALISTS:
        names.append("e2er-lit")
    if specialist in _SCRIPT_WRITING_SPECIALISTS:
        names.append("e2er-run")
    if specialist in _SPEC_WRITING_SPECIALISTS:
        names.append("e2er-check-tables")
    if specialist in _FIELDMAP_SPECIALISTS:
        names.append("e2er-fieldmap")
    return [_tool(n) for n in names]


#: Read at the top of an API backend's prompt: how the commands named in the instructions are called.
COMMANDS_NOTE = (
    "## The e2er commands are tools here\n"
    "These instructions write commands as a shell would run them (`e2er-run run_estimation.py`, "
    '`e2er-data query sql "SELECT ..."`, `e2er-lit search "..."`). You have no shell: each command you '
    "may use is a tool of the same name. Call it with `args`, the words after the command name, one per "
    'item and unquoted: `e2er-data query sql "SELECT 1"` is the tool `e2er-data` with args '
    '["query", "sql", "SELECT 1"]. Commands that are not among your tools are not available to you.'
)

_VIA_BASH = re.compile(r" \(via Bash\)")
#: The backends that call a model through an API and get the commands as tools.
API_BACKENDS = frozenset({"openrouter", "anthropic"})


def for_api_backend(text: str) -> str:
    """Instructions written for a shell, for a model that calls the commands as tools."""
    text = text.replace("(via Bash; ", "(")
    return _VIA_BASH.sub("", text)


class CommandToolHandler(ToolHandler):
    """Runs the command tools in ``workspace``."""

    def __init__(self, workspace: Path, names: set[str], *, timeout: float | None = None) -> None:
        self._workspace = Path(workspace).resolve()
        self._names = set(names) & set(ENTRY_POINTS)
        try:
            run_limit = float(os.environ.get("E2ER_RUN_TIMEOUT") or 600)
        except ValueError:
            run_limit = 600.0
        # e2er-run keeps its own limit for the script; this one only catches a hung command.
        self._timeout = timeout if timeout is not None else run_limit + 120

    def can_handle(self, tool_name: str) -> bool:
        return tool_name in self._names

    async def handle(self, tool_name: str, tool_input: dict[str, Any]) -> str:
        if tool_name not in self._names:
            return f"Error: {tool_name} is not one of your tools."
        raw = tool_input.get("args", [])
        if isinstance(raw, str):  # a model that sends the words as one string
            import shlex

            try:
                raw = shlex.split(raw)
            except ValueError as e:
                return f"Error: could not split the arguments ({e}); send them as a list of strings."
        if not isinstance(raw, list) or not all(isinstance(a, str) for a in raw):
            return f'Error: {tool_name} takes {{"args": [ ...words after the command... ]}}, a list of strings.'
        if raw and raw[0] == tool_name:  # the command name repeated as the first word
            raw = raw[1:]
        if any(a == "--workspace" or a.startswith("--workspace=") for a in raw):
            return f"Error: {tool_name} works on this study's folder; --workspace is not allowed."
        return await self._run(tool_name, raw)

    async def _run(self, command: str, args: list[str]) -> str:
        module, func = ENTRY_POINTS[command]
        env = dict(os.environ)
        # e2er's own code, never a module of the study's folder: -P keeps the folder off sys.path.
        env["PYTHONPATH"] = os.pathsep.join(p for p in (str(_PACKAGE_ROOT), env.get("PYTHONPATH", "")) if p)
        env["E2ER_WORKSPACE"] = str(self._workspace)
        env["PYTHONIOENCODING"] = "utf-8"
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-P",
            "-c",
            _RUNNER,
            module,
            func,
            command,
            *args,
            cwd=str(self._workspace),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), self._timeout)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return f"exit code: none, {command} was stopped after {self._timeout:.0f} s"
        text = (out or b"").decode("utf-8", "replace")
        if len(text) > _OUTPUT_TAIL:
            text = f"[… {len(text) - _OUTPUT_TAIL:,} characters before this are cut …]\n" + text[-_OUTPUT_TAIL:]
        return f"exit code: {proc.returncode}\n{text}".rstrip()
