"""One full specialist step on the OpenRouter backend, offline (review of 2026-11-24).

The real dispatcher (``execute_work_order`` -> ``run_specialist``) drives a real
``OpenRouterBackend``; only the model is scripted: ``OpenRouterBackend._create`` is
replaced by a fake econometrics specialist that writes its specification, writes
``run_estimation.py`` with a bug, runs it with the ``e2er-run`` tool, reads the
traceback, fixes the file, runs it again and fills the numbers into its spec.
No key, no network: the key check, the model list and the completions call are stubbed.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("openai")

MODEL = "deepseek/deepseek-v4-pro"
SPEC = "econometric_spec.md"
SCRIPT = "run_estimation.py"
RESULTS = "estimation_results.json"

# A small firm-year panel, as the data step leaves it under data/.
_ROWS = ["firm,year,treatment,x1,y"]
for f in range(12):
    for t in range(6):
        treat = 1 if (f % 2 == 0 and t >= 3) else 0
        x1 = round(((f * 7 + t * 3) % 10) / 10, 2)
        y = round(1.0 + 0.5 * treat + 0.3 * x1 + ((f * 13 + t * 5) % 7) / 20, 4)
        _ROWS.append(f"{f},{2018 + t},{treat},{x1},{y}")
PANEL_CSV = "\n".join(_ROWS) + "\n"

_SCRIPT_TEMPLATE = '''"""Estimate the effect of treatment on y: OLS with firm-clustered standard errors."""
import json

import pandas as pd
import statsmodels.formula.api as smf

df = pd.read_csv("data/panel.csv")
df["treated"] = df["{col}"]
fit = smf.ols("y ~ treated + x1", data=df).fit(cov_type="cluster", cov_kwds={{"groups": df["firm"]}})
G = int(df["firm"].nunique())
coefs = {{}}
for name in ("treated", "x1"):
    coefs[name] = {{
        "estimate": float(fit.params[name]),
        "se": float(fit.bse[name]),
        "t_stat": float(fit.tvalues[name]),
        "p_value": float(fit.pvalues[name]),
    }}
results = {{
    "main": {{
        "specification": "OLS of y on treatment and x1, SEs clustered by firm",
        "n_observations": int(fit.nobs),
        "cluster_level": "firm",
        "n_clusters": G,
        "fixed_effects": [],
        "controls": ["x1"],
        "coefficients": coefs,
        "diagnostics": {{"r_squared": float(fit.rsquared)}},
    }}
}}
with open("estimation_results.json", "w", encoding="utf-8") as fh:
    json.dump(results, fh, indent=2)
print("treated", round(coefs["treated"]["estimate"], 4), "se", round(coefs["treated"]["se"], 4))
'''
BUGGY_SCRIPT = _SCRIPT_TEMPLATE.format(col="treatmnt")
FIXED_SCRIPT = _SCRIPT_TEMPLATE.format(col="treatment")

SPEC_DESIGN = (
    "# Econometric specification\n\n"
    "We regress the outcome y on the treatment indicator and the control x1 by OLS, "
    "on the firm-year panel in data/panel.csv (12 firms, 6 years). Standard errors are "
    "clustered by firm, since treatment is assigned at the firm level. The coefficient on "
    "treatment is the headline estimate; x1 is the only control the design names.\n"
)


# ── the fake provider ─────────────────────────────────────────────────────────


def _call(i: int, name: str, args: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(
        id=f"call_{i}", type="function", function=SimpleNamespace(name=name, arguments=json.dumps(args))
    )


def _response(finish: str, calls: list[SimpleNamespace] | None = None, content: str | None = None) -> SimpleNamespace:
    msg = SimpleNamespace(content=content, tool_calls=calls or None, reasoning_details=None)
    usage = SimpleNamespace(prompt_tokens=4000, completion_tokens=600, prompt_tokens_details=None, cost=0.0021)
    return SimpleNamespace(choices=[SimpleNamespace(finish_reason=finish, message=msg)], usage=usage, error=None)


def _last_tool_results(kwargs: dict[str, Any]) -> list[str]:
    """The tool results the model sees after its last call (the trailing `tool` messages)."""
    out: list[str] = []
    for m in reversed(kwargs["messages"]):
        if m.get("role") != "tool":
            break
        out.append(m["content"] if isinstance(m["content"], str) else json.dumps(m["content"]))
    return list(reversed(out))


class ScriptedModel:
    """Plays a competent econometrics specialist, turn by turn; records every request."""

    def __init__(self, plan: str = "run_and_fix") -> None:
        self.plan = plan
        self.requests: list[dict[str, Any]] = []
        self.seen: dict[str, str] = {}

    async def __call__(self, kwargs: dict[str, Any], turn: int) -> SimpleNamespace:
        self.requests.append(kwargs)
        step = len(self.requests) - 1
        return getattr(self, f"_{self.plan}")(step, kwargs)

    def _run_and_fix(self, step: int, kwargs: dict[str, Any]) -> SimpleNamespace:
        results = _last_tool_results(kwargs)
        if step == 0:
            return _response("tool_calls", [_call(0, "write_file", {"path": SPEC, "content": SPEC_DESIGN})])
        if step == 1:
            return _response("tool_calls", [_call(1, "write_file", {"path": SCRIPT, "content": BUGGY_SCRIPT})])
        if step == 2:
            return _response("tool_calls", [_call(2, "e2er-run", {"args": [SCRIPT]})])
        if step == 3:
            self.seen["first_run"] = results[-1]
            assert "KeyError" in results[-1] and "treatmnt" in results[-1], results
            fix = {"path": SCRIPT, "old_string": 'df["treatmnt"]', "new_string": 'df["treatment"]'}
            return _response("tool_calls", [_call(3, "edit_file", fix)])
        if step == 4:
            # Some providers end a turn with "stop" while sending tool calls: the calls must still run.
            return _response("stop", [_call(4, "e2er-run", {"args": [SCRIPT]})], content="Running the fixed script.")
        if step == 5:
            self.seen["second_run"] = results[-1]
            return _response("tool_calls", [_call(5, "read_file", {"path": RESULTS})])
        if step == 6:
            data = json.loads(results[-1])
            c = data["main"]["coefficients"]["treated"]
            body = (
                SPEC_DESIGN + f"\n## Results\nThe treatment raises y by {c['estimate']:.4f} (SE {c['se']:.4f}, "
                f"p = {c['p_value']:.4f}), from run_estimation.py as run with e2er-run.\n"
            )
            return _response("tool_calls", [_call(6, "write_file", {"path": SPEC, "content": body})])
        return _response("stop", content="Done.")

    def _never_runs(self, step: int, kwargs: dict[str, Any]) -> SimpleNamespace:
        """Writes spec and a correct script, never calls e2er-run: the runner's own run must make the results."""
        if step == 0:
            return _response("tool_calls", [_call(0, "write_file", {"path": SPEC, "content": SPEC_DESIGN})])
        if step == 1:
            return _response("tool_calls", [_call(1, "write_file", {"path": SCRIPT, "content": FIXED_SCRIPT})])
        return _response("stop", content="Done.")

    def _edits_results(self, step: int, kwargs: dict[str, Any]) -> SimpleNamespace:
        """Runs the script, then rewrites the results file by hand with one estimate changed."""
        results = _last_tool_results(kwargs)
        if step == 0:
            return _response(
                "tool_calls",
                [
                    _call(0, "write_file", {"path": SPEC, "content": SPEC_DESIGN}),
                    _call(1, "write_file", {"path": SCRIPT, "content": FIXED_SCRIPT}),
                ],
            )
        if step == 1:
            return _response("tool_calls", [_call(2, "e2er-run", {"args": [SCRIPT]})])
        if step == 2:
            assert results[-1].startswith("exit code: 0"), results
            return _response("tool_calls", [_call(3, "read_file", {"path": RESULTS})])
        if step == 3:
            data = json.loads(results[-1])
            data["main"]["coefficients"]["treated"]["estimate"] *= 1.5  # "nicer" headline number
            c = data["main"]["coefficients"]["treated"]
            c["t_stat"] = c["estimate"] / c["se"]
            return _response(
                "tool_calls", [_call(4, "write_file", {"path": RESULTS, "content": json.dumps(data, indent=2)})]
            )
        return _response("stop", content="Done.")

    def _queries_data(self, step: int, kwargs: dict[str, Any]) -> SimpleNamespace:
        """Inspects data.db with e2er-data as the prompt says (`e2er-data query sql "SELECT ..."`), then the run."""
        results = _last_tool_results(kwargs)
        if step == 0:
            sql = ["query", "sql", "SELECT COUNT(*) AS n FROM panel"]
            return _response("tool_calls", [_call(0, "e2er-data", {"args": sql})])
        self.seen.setdefault("query", results[-1] if results else "")
        return self._never_runs(step - 1, kwargs)


# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture()
def offline_openrouter(monkeypatch):
    """A real OpenRouterBackend with a dummy key and no network: every outside call is stubbed or refused."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setenv("OPENROUTER_MODEL", MODEL)
    monkeypatch.setenv("LLM_BACKEND", "openrouter")
    from src.config import get_settings

    get_settings.cache_clear()

    from src.modules.llm import openrouter, openrouter_models

    fetched: list[str] = []
    model_list = {
        "data": [
            {
                "id": MODEL,
                "name": "DeepSeek V4 Pro",
                "pricing": {"prompt": "0.0000004", "completion": "0.0000016", "input_cache_read": "0.0000001"},
                "context_length": 128000,
                "supported_parameters": ["tools", "tool_choice", "max_tokens"],
                "top_provider": {"max_completion_tokens": 16000},
            }
        ]
    }

    def get_json(url: str):
        fetched.append(url)
        return model_list if url == openrouter_models.MODELS_URL else None

    monkeypatch.setattr(openrouter_models, "_get_json", get_json)
    openrouter_models._reset_for_tests()
    key_checks: list[str] = []

    async def key_info(api_key: str):
        key_checks.append(api_key)
        return {"limit_remaining": 5.0, "usage": 0.0}

    monkeypatch.setattr(openrouter, "_key_info", key_info)

    def make(model: ScriptedModel):
        backend = openrouter.OpenRouterBackend()
        # The SDK client must never be reached: the scripted model answers every turn.
        refuse = AsyncMock(side_effect=AssertionError("the real completions endpoint was called"))
        monkeypatch.setattr(backend._client.chat.completions, "create", refuse)
        monkeypatch.setattr(backend, "_create", model)
        return backend

    make.fetched = fetched  # type: ignore[attr-defined]
    make.key_checks = key_checks  # type: ignore[attr-defined]
    return make


@pytest.fixture()
def study(tmp_workspace: Path) -> Path:
    (tmp_workspace / "data").mkdir()
    (tmp_workspace / "data" / "panel.csv").write_text(PANEL_CSV, encoding="utf-8", newline="\n")
    (tmp_workspace / "identification_strategy.md").write_text(
        "# Identification\n\nTreatment is assigned to even-numbered firms from 2021. OLS of y on treatment "
        "with the control x1; standard errors clustered by firm.\n",
        encoding="utf-8",
        newline="\n",
    )
    return tmp_workspace


def _real_extra_tools(paper_id: str, workspace: Path):
    """The tools and handlers the dashboard's run gives every backend (api/app.py), without warehouses."""
    from src.modules.data.discovery_tools import DATA_DISCOVERY_TOOLS, SeriesDataToolHandler
    from src.modules.data.query_tools import QUERY_DATA_TOOLS, QueryDataToolHandler
    from src.modules.literature.tools import LITERATURE_TOOLS, LiteratureToolHandler

    tools = [*DATA_DISCOVERY_TOOLS, *QUERY_DATA_TOOLS, *LITERATURE_TOOLS]
    handlers = [
        SeriesDataToolHandler(workspace),
        QueryDataToolHandler(paper_id, workspace),
        LiteratureToolHandler(workspace),
    ]
    return tools, handlers


async def _dispatch(backend, workspace: Path, paper_id: str):
    from src.core.specialists.contracts import WorkOrder
    from src.core.specialists.dispatcher import execute_work_order

    tools, handlers = _real_extra_tools(paper_id, workspace)
    wo = WorkOrder(
        paper_id=paper_id,
        specialist="econometrics_specialist",
        focus="Estimate the effect of treatment on y as identification_strategy.md specifies.",
        context_tier=1,
    )
    return await execute_work_order(
        wo,
        backend=backend,
        workspace=workspace,
        model=MODEL,
        extra_tools=tools,
        extra_handlers=handlers,
        backend_name="openrouter",
    )


def _script_runs(workspace: Path) -> list[dict]:
    from src.core.script_log import SCRIPT_RUNS

    path = workspace / SCRIPT_RUNS
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# ── the tests ────────────────────────────────────────────────────────────────


async def test_one_econometrics_step_runs_end_to_end_on_openrouter(offline_openrouter, study, paper_id, db_stub):
    from src.core.script_log import FROM_CODE, results_from_code
    from src.core.specialists.contract_check import check_specialist_artifacts
    from src.core.specialists.post_execution import RERUN_RECORD, maybe_execute_specialist_script
    from src.modules.llm.base import run_preflight
    from src.modules.llm.command_tools import COMMANDS_NOTE

    model = ScriptedModel("run_and_fix")
    backend = offline_openrouter(model)
    await run_preflight(backend)  # the run's check before its first step: key, model, limits (all stubbed)
    assert offline_openrouter.key_checks == ["sk-or-test"]
    assert backend._max_tokens == 16000  # lowered to the model's own output limit

    contribution = await _dispatch(backend, study, paper_id)

    # The step succeeded and every turn of the script was played.
    assert contribution.success is True, contribution.error
    assert contribution.contract_violations == []
    assert len(model.requests) == 8, len(model.requests)
    assert contribution.output == "Done."

    # What the model was offered: e2er-run and e2er-data, with the documented schema, once each.
    first = model.requests[0]
    tools = {t["function"]["name"]: t["function"] for t in first["tools"]}
    assert len(tools) == len(first["tools"]), "a tool name is offered twice"
    for name in ("e2er-run", "e2er-data"):
        params = tools[name]["parameters"]
        assert params["required"] == ["args"]
        assert params["properties"]["args"] == {
            "type": "array",
            "items": {"type": "string"},
            "description": "The words after the command name, one per item, unquoted.",
        }
    assert "e2er-lit" not in tools and "e2er-check-tables" not in tools
    assert first["max_tokens"] == 16000
    assert first["model"] == MODEL

    # The system prompt names the commands as tools, and no shell.
    system = first["messages"][0]
    system_text = system["content"] if isinstance(system["content"], str) else system["content"][0]["text"]
    assert system["role"] == "system"
    assert COMMANDS_NOTE in system_text
    assert "(via Bash" not in system_text
    assert "(via Bash" not in json.dumps(first["messages"][1:])
    assert "`e2er-run <your_script.py>`. It runs" in system_text

    # The model saw the crash, and the fixed run, through the tool results.
    assert model.seen["first_run"].startswith("exit code: 1")
    assert model.seen["second_run"].startswith("exit code: 0") and "treated" in model.seen["second_run"]

    # Both runs went through e2er-run and are in the script log; the last one wrote the results.
    runs = _script_runs(study)
    by_e2er_run = [r for r in runs if r.get("by") == "e2er-run" and r.get("script") == SCRIPT]
    assert len(by_e2er_run) == 2, runs
    assert by_e2er_run[0]["exit_code"] != 0 and by_e2er_run[1]["exit_code"] == 0, by_e2er_run
    assert RESULTS in (by_e2er_run[1].get("outputs") or {}), by_e2er_run[1]

    # Results come from the code: the file is the recorded output of the last run, so no rerun was needed.
    assert results_from_code(study, RESULTS)[0] == FROM_CODE
    assert not (study / RERUN_RECORD).exists()
    results = json.loads((study / RESULTS).read_text(encoding="utf-8"))
    assert results["main"]["coefficients"]["treated"]["estimate"] == pytest.approx(0.5, abs=0.1)

    # The runner's own run of the shipped script, from a clean results file, writes the same numbers.
    (study / RESULTS).unlink()
    attempt = maybe_execute_specialist_script(study, "econometrics_specialist")
    assert attempt.ran and attempt.returncode == 0 and attempt.populated_sidecar, attempt
    assert json.loads((study / RESULTS).read_text(encoding="utf-8")) == results
    assert [c for c in check_specialist_artifacts(study, "econometrics_specialist") if not c.ok] == []

    # The narrative carries the realized numbers.
    assert "## Results" in (study / SPEC).read_text(encoding="utf-8")

    # Usage and cost: 8 calls of 4000 + 600 tokens at $0.0021 each.
    assert contribution.usage_tokens == 8 * 4600
    assert contribution.cost_usd == pytest.approx(8 * 0.0021)
    usage_rows = db_stub.writes("INSERT INTO llm_usage")
    assert len(usage_rows) == 1, usage_rows
    row = usage_rows[0][1]
    assert row["backend"] == "openrouter" and row["model"] == MODEL
    assert row["input_tokens"] == 8 * 4000 and row["output_tokens"] == 8 * 600
    assert float(row["cost_usd"]) == pytest.approx(8 * 0.0021)
    attempt_events = [p for _sql, p in db_stub.writes("events") if "attempt_usage" in json.dumps(p, default=str)]
    assert attempt_events, "no attempt_usage event"
    contributions = db_stub.writes("INSERT INTO contributions")
    assert contributions and contributions[-1][1]["s"] is True

    # Only the model list was fetched (stubbed); nothing else went out.
    assert all("openrouter.ai/api/v1/models" in u for u in offline_openrouter.fetched), offline_openrouter.fetched


async def test_a_model_that_never_runs_its_script_gets_it_run_by_the_runner(offline_openrouter, study, paper_id):
    model = ScriptedModel("never_runs")
    contribution = await _dispatch(offline_openrouter(model), study, paper_id)
    assert contribution.success is True, contribution.error
    runs = _script_runs(study)
    assert [r["by"] for r in runs if r.get("script") == SCRIPT] == ["runner"], runs
    assert json.loads((study / RESULTS).read_text(encoding="utf-8"))["main"]["coefficients"]["treated"]


async def test_e2er_data_answers_a_query_inside_the_step(offline_openrouter, study, paper_id):
    import sqlite3

    con = sqlite3.connect(study / "data.db")
    con.execute("CREATE TABLE panel (firm INTEGER, year INTEGER, treatment INTEGER, x1 REAL, y REAL)")
    con.executemany("INSERT INTO panel VALUES (?, ?, ?, ?, ?)", [r.split(",") for r in _ROWS[1:]])
    con.commit()
    con.close()
    model = ScriptedModel("queries_data")
    contribution = await _dispatch(offline_openrouter(model), study, paper_id)
    assert contribution.success is True, contribution.error
    assert model.seen["query"].startswith("exit code: 0"), model.seen["query"]
    assert '"row_count": 1' in model.seen["query"] and "72" in model.seen["query"], model.seen["query"]


async def test_results_edited_after_the_run_fail_the_step(offline_openrouter, study, paper_id):
    from src.core.specialists.post_execution import RERUN_RECORD

    model = ScriptedModel("edits_results")
    contribution = await _dispatch(offline_openrouter(model), study, paper_id)
    assert contribution.success is False
    assert any(v.startswith(f"{RESULTS}:") and "not written by" in v for v in contribution.contract_violations), (
        contribution.contract_violations
    )
    record = json.loads((study / RERUN_RECORD).read_text(encoding="utf-8"))
    assert record[RESULTS]["exit_code"] == 0 and record[RESULTS]["same"] is False, record
    runs = _script_runs(study)
    assert [r["by"] for r in runs if r.get("script") == SCRIPT] == ["e2er-run", "runner (results check)"], runs
