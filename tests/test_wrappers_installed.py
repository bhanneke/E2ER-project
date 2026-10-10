"""Every command a specialist is told to run is a console entry point of the package.

Before 0.15.0 an installed e2er (pip, uv tool install) had only `e2er`,
`e2er-data` and `e2er-fieldmap`: `e2er-run`, `e2er-lit`, `e2er-check-tables`
and `e2er-allium-query` existed as shell files in a source checkout only, while
Claude Code's allowlist and the specialists' instructions named them.
scripts/check_wheel.sh installs the built wheel and runs each of them; these
tests keep the declarations and the implementation in step.
"""

from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path

import pytest

from src import wrappers
from src.core.script_log import read_script_runs

ROOT = Path(__file__).resolve().parent.parent
ENTRY_POINTS = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["scripts"]


def _named_commands() -> set[str]:
    """The e2er-* commands the allowlists, the specialists' instructions and skills name."""
    allow = (ROOT / "src" / "modules" / "llm" / "claude_code.py").read_text(encoding="utf-8")
    names = set(re.findall(r"Bash\((e2er-[a-z-]+):\*\)", allow))
    wrappers_in_checkout = {p.name for p in (ROOT / "scripts").glob("e2er-*")}
    texts = [p.read_text(encoding="utf-8", errors="replace") for p in (ROOT / "skills" / "files").rglob("*.md")]
    texts += [p.read_text(encoding="utf-8") for p in (ROOT / "src").rglob("*.py")]
    for text in texts:
        names |= {n for n in re.findall(r"`(e2er-[a-z-]+)[ `]", text) if n in wrappers_in_checkout}
    return names | wrappers_in_checkout


def test_every_command_a_specialist_is_given_is_an_entry_point():
    named = _named_commands()
    assert {"e2er-run", "e2er-lit", "e2er-check-tables", "e2er-allium-query", "e2er-data", "e2er-fieldmap"} <= named
    missing = sorted(n for n in named if n not in ENTRY_POINTS)
    assert not missing, f"named for specialists but not installed with the package: {missing}"


def test_the_checkout_wrappers_call_the_entry_points_implementation():
    """One implementation: scripts/e2er-run, -lit, -check-tables, -allium-query run src.wrappers."""
    for name, command in (
        ("e2er-run", "run"),
        ("e2er-lit", "lit"),
        ("e2er-check-tables", "check-tables"),
        ("e2er-allium-query", "allium-query"),
    ):
        text = (ROOT / "scripts" / name).read_text(encoding="utf-8")
        assert f"-m src.wrappers {command} " in text, name
        module, func = ENTRY_POINTS[name].split(":")
        assert module == "src.wrappers" and callable(getattr(wrappers, func))


def test_run_records_the_run_and_passes_the_exit_code_on(tmp_path: Path, monkeypatch, capfd):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("E2ER_PYTHON", sys.executable)
    (tmp_path / "ok.py").write_text("print('ran')\n", encoding="utf-8")
    (tmp_path / "bad.py").write_text("raise SystemExit(5)\n", encoding="utf-8")
    assert wrappers.run_main(["ok.py"]) == 0
    assert wrappers.run_main(["bad.py"]) == 5
    assert "ran" in capfd.readouterr().out
    runs = read_script_runs(tmp_path)
    assert [(r["script"], r["exit_code"], r["by"]) for r in runs] == [
        ("ok.py", 0, "e2er-run"),
        ("bad.py", 5, "e2er-run"),
    ]


def test_run_stops_a_script_at_the_time_limit(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("E2ER_RUN_TIMEOUT", "1")
    (tmp_path / "slow.py").write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
    assert wrappers.run_main(["slow.py"]) == wrappers.TIMED_OUT
    assert read_script_runs(tmp_path)[-1]["exit_code"] == wrappers.TIMED_OUT


@pytest.mark.parametrize("args", [["/etc/passwd.py"], ["../x.py"], ["x.txt"], ["missing.py"], ["a.py", "b"], []])
def test_run_refuses_what_the_shell_wrapper_refused(tmp_path: Path, monkeypatch, args):
    monkeypatch.chdir(tmp_path)
    assert wrappers.run_main(args) == wrappers.REFUSED
    assert not (tmp_path / ".e2er-script-runs.jsonl").exists()


def test_run_refuses_a_link_out_of_the_workspace(tmp_path: Path, monkeypatch):
    outside = tmp_path / "outside.py"
    outside.write_text("print('no')\n", encoding="utf-8")
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "link.py").symlink_to(outside)
    monkeypatch.chdir(ws)
    assert wrappers.run_main(["link.py"]) == wrappers.REFUSED


def test_lit_uses_the_folder_it_is_called_in(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("E2ER_WORKSPACE", "/somewhere/else")
    with pytest.raises(SystemExit) as done:
        wrappers.lit_main(["--help"])
    assert done.value.code == 0 and "usage" in capsys.readouterr().out.lower()
    import os

    assert os.environ["E2ER_WORKSPACE"] == str(tmp_path.resolve())


def test_check_tables_takes_no_arguments_and_checks_the_current_folder(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert wrappers.check_tables_main(["x"]) == wrappers.REFUSED
    code = wrappers.check_tables_main([])
    assert code != 0 and "no table_spec.json" in capsys.readouterr().out


def test_allium_query_is_e2er_data_allium(monkeypatch):
    seen = {}

    def fake(argv):
        seen["argv"] = argv
        return 0

    monkeypatch.setattr("src.modules.data.cli.main", fake)
    assert wrappers.allium_query_main(["list-tables"]) == 0
    assert seen["argv"] == ["allium", "list-tables"]
    json.dumps(seen)
