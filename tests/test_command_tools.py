"""The e2er commands as tools for the API backends (OpenRouter, Anthropic; review of 2026-11-23).

A model reached through an API has no shell. It gets e2er-run, e2er-data, e2er-lit, e2er-check-tables
and e2er-fieldmap as tools of the same name, for the specialists Claude Code lets run them, and each
call runs the command's own code in the study's folder.
"""

from __future__ import annotations

import json

from src.core.script_log import SCRIPT_RUNS as LOG_NAME
from src.modules.llm.command_tools import COMMANDS_NOTE, CommandToolHandler, command_tools_for, for_api_backend


def _names(specialist):
    return [t["name"] for t in command_tools_for(specialist)]


def test_each_specialist_gets_the_commands_claude_code_gives_it():
    assert _names("econometrics_specialist") == ["e2er-data", "e2er-run"]
    assert _names("paper_drafter") == ["e2er-data", "e2er-lit", "e2er-check-tables"]
    assert _names("field_boundary_designer") == ["e2er-data", "e2er-lit", "e2er-fieldmap"]
    assert _names("referee") == ["e2er-data"]


def test_instructions_lose_the_shell_and_explain_the_call():
    text = (
        'Run it: `e2er-run <your_script.py>` (via Bash). SQL with `e2er-data query sql "SELECT ..."` '
        "(via Bash; read-only)."
    )
    out = for_api_backend(text)
    assert "via Bash" not in out and "`e2er-run <your_script.py>`. SQL" in out and "(read-only)" in out
    assert 'args ["query", "sql", "SELECT 1"]' in COMMANDS_NOTE


async def test_e2er_run_runs_the_script_records_it_and_returns_the_traceback(tmp_path):
    ws = tmp_path / "study"
    ws.mkdir()
    (ws / "ok.py").write_text("import json\njson.dump({'n': 3}, open('results.json', 'w'))\nprint('wrote results')\n")
    (ws / "bad.py").write_text("import pandas_that_does_not_exist\n")
    h = CommandToolHandler(ws, {"e2er-run"})
    out = await h.handle("e2er-run", {"args": ["ok.py"]})
    assert out.startswith("exit code: 0") and "wrote results" in out, out
    assert json.loads((ws / "results.json").read_text()) == {"n": 3}
    runs = [json.loads(line) for line in (ws / LOG_NAME).read_text().splitlines() if line.strip()]
    assert runs and runs[-1]["script"] == "ok.py" and runs[-1]["by"] == "e2er-run", runs
    bad = await h.handle("e2er-run", {"args": "bad.py"})  # one string is split like a shell would
    assert not bad.startswith("exit code: 0") and "ModuleNotFoundError" in bad, bad


async def test_paths_out_of_the_folder_and_other_tools_are_refused(tmp_path):
    ws = tmp_path / "study"
    ws.mkdir()
    (tmp_path / "outside.py").write_text("print('outside')\n")
    h = CommandToolHandler(ws, {"e2er-run", "e2er-data"})
    out = await h.handle("e2er-run", {"args": ["../outside.py"]})
    assert "not allowed" in out and "outside\n" not in out.split("\n", 1)[-1], out
    assert "not one of your tools" in await h.handle("e2er-lit", {"args": ["list"]})
    assert "--workspace is not allowed" in await h.handle(
        "e2er-data", {"args": ["query", "tables", "--workspace", "/"]}
    )
    assert not h.can_handle("e2er-lit") and h.can_handle("e2er-data")


async def test_e2er_data_answers_in_the_study_folder(tmp_path):
    ws = tmp_path / "study"
    ws.mkdir()
    out = await CommandToolHandler(ws, {"e2er-data"}).handle("e2er-data", {"args": ["--help"]})
    assert out.startswith("exit code: 0") and "usage" in out.lower(), out
