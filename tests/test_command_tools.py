"""The e2er commands as tools for the API backends (OpenRouter, Anthropic; review of 2026-11-23).

A model reached through an API has no shell. It gets e2er-run, e2er-data, e2er-lit, e2er-check-tables
and e2er-fieldmap as tools of the same name, for the specialists Claude Code lets run them, and each
call runs the command's own code in the study's folder.
"""

from __future__ import annotations

import json

import pytest

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
    assert "leave out --workspace" in await h.handle("e2er-data", {"args": ["query", "tables", "--workspace", "/"]})
    assert not h.can_handle("e2er-lit") and h.can_handle("e2er-data")


async def test_e2er_data_answers_in_the_study_folder(tmp_path):
    ws = tmp_path / "study"
    ws.mkdir()
    out = await CommandToolHandler(ws, {"e2er-data"}).handle("e2er-data", {"args": ["--help"]})
    assert out.startswith("exit code: 0") and "usage" in out.lower(), out


# --- review of 2026-11-24: the step's own study, no options that choose another, no links out ---------


def _study_with_db(tmp_path):
    import sqlite3

    ws = tmp_path / "study"
    ws.mkdir()
    con = sqlite3.connect(ws / "data.db")
    con.execute("CREATE TABLE t (v TEXT)")
    con.execute("INSERT INTO t VALUES ('OWN-ROW')")
    con.commit()
    con.close()
    return ws


async def test_e2er_data_queries_the_steps_own_study(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-secret-test")
    ws = _study_with_db(tmp_path)
    h = CommandToolHandler(ws, {"e2er-data"}, paper_id="p1", specialist="data_analyst")
    out = await h.handle("e2er-data", {"args": ["query", "sql", "SELECT v FROM t"]})
    assert out.startswith("exit code: 0") and "OWN-ROW" in out, out
    (ws / "show_env.py").write_text("import os\nprint(sorted(os.environ.items()))\n")
    env_dump = await CommandToolHandler(ws, {"e2er-run"}, paper_id="p1", specialist="data_analyst").handle(
        "e2er-run", {"args": ["show_env.py"]}
    )
    assert "sk-or-secret-test" not in env_dump


@pytest.mark.parametrize(
    "args",
    [
        ["--paper-id", "other", "query", "tables"],
        ["--paper-id=other", "query", "tables"],
        ["--pap", "other", "query", "tables"],
        ["--spec", "referee", "query", "tables"],
        ["--works", "/tmp", "query", "tables"],
        ["--workspace=/tmp", "query", "tables"],
    ],
)
async def test_options_that_choose_another_study_are_refused_in_every_spelling(tmp_path, args):
    ws = _study_with_db(tmp_path)
    out = await CommandToolHandler(ws, {"e2er-data", "e2er-fieldmap"}, paper_id="p1").handle(
        "e2er-data", {"args": args}
    )
    assert out.startswith("Error:") and "leave out" in out, out


async def test_a_link_into_what_the_sandbox_denies_stops_the_commands(tmp_path, monkeypatch):
    """Review of 2026-11-24: a link to a secret (here ~/.ssh of a stand-in home) stops every command."""
    home = tmp_path / "home"
    (home / ".ssh").mkdir(parents=True)
    (home / ".ssh" / "id_test").write_text("SECRET-KEY-LINE\n")
    monkeypatch.setenv("HOME", str(home))
    ws = tmp_path / "study"
    ws.mkdir()
    (ws / "data_dictionary.json").symlink_to(home / ".ssh" / "id_test")
    h = CommandToolHandler(ws, {"e2er-data", "e2er-check-tables"}, paper_id="p1", specialist="data_analyst")
    for args in (["query", "tables"], ["query", "sql", "SELECT 1"]):
        out = await h.handle("e2er-data", {"args": args})
        assert "SECRET-KEY-LINE" not in out and "lead out of it" in out, out
    out = await h.handle("e2er-check-tables", {"args": []})
    assert "lead out of it" in out and "data_dictionary.json" in out, out


def test_links_e2er_makes_to_the_researchers_data_stay_allowed(tmp_path, monkeypatch):
    """Review of 2026-11-24: e2er links the researcher's data and PDFs into the study; those are not refused."""
    from src.core.workspace_guard import guard_ai_step

    outside = tmp_path / "my-data"
    outside.mkdir()
    (outside / "x.csv").write_text("a,b\n1,2\n")
    ws = tmp_path / "study"
    (ws / "data").mkdir(parents=True)
    (ws / "data" / "x.csv").symlink_to(outside / "x.csv")
    monkeypatch.setenv("E2ER_AI_STEP", "data_analyst")
    monkeypatch.setenv("E2ER_WORKSPACE", str(ws))
    assert guard_ai_step("e2er-data") is None


def test_a_folder_too_large_to_check_is_refused(tmp_path, monkeypatch):
    from src.core import workspace_guard

    ws = tmp_path / "study"
    ws.mkdir()
    for i in range(12):
        (ws / f"f{i}").write_text("")
    monkeypatch.setattr(workspace_guard, "_MAX_ENTRIES", 10)
    assert "more than 10 files and folders" in (workspace_guard.refusal(ws, "e2er-data") or "")


def test_data_db_itself_refuses_a_link(tmp_path):
    from src.db.paper_data_db import UnsafeDataDbError, data_db_path, has_data_db

    ws = tmp_path / "study"
    ws.mkdir()
    (tmp_path / "x.sqlite").write_bytes(b"")
    (ws / "data.db").symlink_to(tmp_path / "x.sqlite")
    with pytest.raises(UnsafeDataDbError):
        data_db_path(ws)
    assert has_data_db(ws) is False


def test_e2er_data_in_an_ai_step_refuses_another_study_on_the_cli_path(monkeypatch, capsys):
    from src.modules.data.cli import main

    monkeypatch.setenv("E2ER_AI_STEP", "data_analyst")
    monkeypatch.setenv("E2ER_PAPER_ID", "p1")
    monkeypatch.setenv("E2ER_SPECIALIST", "data_analyst")
    assert main(["--paper-id", "other", "query", "tables"]) == 2
    assert "another" in capsys.readouterr().err


def test_a_link_out_of_the_study_is_refused_outside_data_and_literature(tmp_path, monkeypatch):
    """Re-review of 2026-11-24: under Codex or Gemini the model can make links; an e2er command would write
    through data_dictionary.json or tables/ to a file outside the study."""
    from src.core.workspace_guard import guard_ai_step

    other = tmp_path / "other-study"
    other.mkdir()
    (other / "data_dictionary.json").write_text("{}")
    ws = tmp_path / "study"
    ws.mkdir()
    (ws / "data_dictionary.json").symlink_to(other / "data_dictionary.json")
    (ws / "inner.txt").write_text("x")
    (ws / "alias.txt").symlink_to(ws / "inner.txt")  # a link within the study is fine
    monkeypatch.setenv("E2ER_AI_STEP", "data_analyst")
    monkeypatch.setenv("E2ER_WORKSPACE", str(ws))
    assert guard_ai_step("e2er-data") == 2
    (ws / "data_dictionary.json").unlink()
    assert guard_ai_step("e2er-data") is None


# --- live test of 2026-11-25: a placeholder from the history copied into a file; broken JSON --------


async def test_a_write_carrying_a_history_placeholder_is_refused(tmp_path):
    from src.modules.llm.history import ELIDED
    from src.modules.llm.tools import FileToolHandler

    h = FileToolHandler(tmp_path)
    for text in ('{"a": 1, [713 characters, not repeated]}', f'x = "[713 characters, {ELIDED}]"'):
        out = await h.handle("write_file", {"path": "notes.txt", "content": text})
        assert out.startswith("Error: nothing written") and "read_file" in out, out
    assert not (tmp_path / "notes.txt").exists()


async def test_a_json_file_that_would_not_parse_is_not_written(tmp_path):
    from src.modules.llm.tools import FileToolHandler

    h = FileToolHandler(tmp_path)
    ok = await h.handle("write_file", {"path": "d.json", "content": '{"tables": [{"name": "t"}]}'})
    assert ok.startswith("Written")
    bad = await h.handle("edit_file", {"path": "d.json", "old_string": '"t"}', "new_string": '"t" "x": 1}'})
    assert bad.startswith("Error: nothing written") and "valid JSON" in bad, bad
    assert (tmp_path / "d.json").read_text() == '{"tables": [{"name": "t"}]}'


def test_a_sparse_column_gets_the_hint_to_declare_its_share(tmp_path):
    """Live test 2026-11-25: DeepSeek read "a table whose values are NULL was not loaded" for a column USGS fills
    in 7 of 150 rows, and loaded the data again three times."""
    import json as _json
    import sqlite3

    from src.core.specialists.contract_check import check_declared_tables

    con = sqlite3.connect(tmp_path / "data.db")
    con.execute("CREATE TABLE quakes (mag REAL, nst REAL)")
    con.executemany("INSERT INTO quakes VALUES (?, ?)", [(5.0 + i / 100, 12.0 if i < 7 else None) for i in range(150)])
    con.commit()
    con.close()
    (tmp_path / "data_dictionary.json").write_text(
        _json.dumps({"tables": [{"name": "quakes", "source": "usgs", "columns": [{"name": "mag"}, {"name": "nst"}]}]})
    )
    reason = check_declared_tables(tmp_path)[0].reason
    assert "quakes.nst: 7 of 150" in reason and "min_non_null" in reason and "test load" in reason, reason
