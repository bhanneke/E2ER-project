"""The export records the study's template; `e2er publish` reads it, and names a server error it cannot parse.

The FOMC study (template event-study-finance) was published as `empirical`,
because `e2er publish --template` defaulted to `empirical` and the export
recorded nothing; the replication would have carried the general demonstration
disclaimer instead of the replication one. And a publish refused by the server
without a JSON `error` field (Cloudflare D1 over its daily read limit) printed
an empty `error:` line.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import httpx
import pytest

from src.cli_publish import publish, recorded_template, resolve_template
from src.core import platform_client as pc
from src.core.demonstration import DISCLAIMERS
from src.core.export.structured import export_paper
from src.core.pipeline.reproduction import check_reproduction
from tests.run_db import make_run_db, paper_id_of

FIXTURES = Path(__file__).parent / "fixtures"
REPL = FIXTURES / "replication_demo"
SHOWCASE = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "showcase_export"
ARGS = dict(owner="ada-lab", project="repro", github="ada-lab", commit="abc1234")


@pytest.fixture(autouse=True)
def offline(monkeypatch, tmp_path):
    monkeypatch.setattr("src.cli_publish.shutil.which", lambda _: None)  # no tectonic in tests
    monkeypatch.setattr(pc, "_keyring", lambda: None)
    monkeypatch.setenv("E2ER_CREDENTIALS", str(tmp_path / "credentials.json"))
    for var in ("E2ER_TOKEN", "E2ER_URL", "E2ER_PURPOSE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.chdir(tmp_path)  # no study folder .env


def _workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    shutil.copytree(REPL, ws)
    assert check_reproduction(ws).passed  # writes the summary into reproduction_report.md
    pid = json.loads((ws / "manifest.json").read_text()).get("paper_id") or ws.name
    make_run_db(tmp_path, pid)  # the study folder's run database, named in its .env
    return ws


def _prov(bundle: Path) -> dict:
    return json.loads((bundle / "provenance.json").read_text())


# ── the export records the template ───────────────────────────────────────────


def test_the_export_records_the_template_it_is_given(tmp_path: Path):
    bundle = export_paper(_workspace(tmp_path), tmp_path / "out", date_str="20260930", template="replication")
    assert _prov(bundle)["run"]["template"] == "replication"
    assert recorded_template(bundle) == "replication"


def test_the_export_falls_back_to_the_manifest(tmp_path: Path):
    ws = _workspace(tmp_path)
    manifest = json.loads((ws / "manifest.json").read_text())
    (ws / "manifest.json").write_text(json.dumps({**manifest, "pipeline": "event-study-finance"}))
    bundle = export_paper(ws, tmp_path / "out", date_str="20260930")
    assert recorded_template(bundle) == "event-study-finance"


def test_an_export_without_a_template_records_none(tmp_path: Path):
    bundle = export_paper(_workspace(tmp_path), tmp_path / "out", date_str="20260930")
    assert _prov(bundle)["run"]["template"] is None and recorded_template(bundle) is None


def test_the_runner_and_the_browser_pass_the_study_template():
    src = Path(__file__).resolve().parents[1] / "src"
    assert "template=self._spec.name" in (src / "core" / "strategist" / "runner.py").read_text()
    finish = (src / "api" / "finish.py").read_text()
    assert finish.count('template=paper.get("pipeline") or None') == 2


# ── publish reads it ──────────────────────────────────────────────────────────


def test_resolve_template(tmp_path: Path):
    bundle = export_paper(_workspace(tmp_path), tmp_path / "out", date_str="20260930", template="replication")
    assert resolve_template(bundle, None) == ("replication", "")
    assert resolve_template(bundle, "replication") == ("replication", "")
    template, why = resolve_template(bundle, "empirical")
    assert template is None
    assert why == (
        "--template empirical does not match the template this study was run with, replication "
        "(recorded in provenance.json at export); leave out --template"
    )
    old = export_paper(_workspace(tmp_path / "b"), tmp_path / "out-b", date_str="20260930")
    assert resolve_template(old, "event-study-finance") == ("event-study-finance", "")
    template, why = resolve_template(old, None)
    assert template == "empirical" and "records no template" in why


def test_publish_uses_the_recorded_template_and_its_disclaimer(tmp_path: Path, capsys):
    bundle = export_paper(_workspace(tmp_path), tmp_path / "out", date_str="20260930", template="replication")
    rc = publish(str(bundle), **ARGS, demonstration=True, out=str(tmp_path / "entry"), data="public", code="public")
    out = capsys.readouterr().out
    assert rc == 0, out
    manifest = json.loads((bundle / "e2er.json").read_text())
    assert manifest["kind"] == "replication" and manifest["purpose"] == "demonstration"
    assert "template:replication" in json.dumps(manifest)
    assert "template:empirical" not in json.dumps(manifest)
    md = (bundle / "misc" / "reproduction_report.md").read_text()
    assert DISCLAIMERS["replication"] in md.split("\n#", 1)[0]  # above the title, once
    assert md.count(DISCLAIMERS["replication"]) == 1


def test_publish_refuses_a_template_other_than_the_recorded_one(tmp_path: Path, capsys):
    bundle = export_paper(_workspace(tmp_path), tmp_path / "out", date_str="20260930", template="replication")
    rc = publish(str(bundle), **ARGS, template="empirical", out=str(tmp_path / "entry"), data="public", code="public")
    out = capsys.readouterr().out
    assert rc == 1
    assert "error: --template empirical does not match the template this study was run with, replication" in out
    assert not (bundle / "e2er.json").exists()


# ── a server error without an error text ──────────────────────────────────────


@pytest.mark.parametrize(
    ("response", "shown"),
    [
        (httpx.Response(503, text="error code: 1101"), "error: HTTP 503: error code: 1101"),
        (httpx.Response(500, text=""), "error: HTTP 500: (empty body)"),
        (httpx.Response(500, json={"ok": False, "d1": "too many reads"}), 'error: HTTP 500: {"ok": false, "d1"'),
        (httpx.Response(500, json={"error": ""}), 'error: HTTP 500: {"error": ""}'),
        (httpx.Response(409, json={"error": "this version exists"}), "error: this version exists"),
    ],
)
def test_a_refused_publish_names_the_status_and_the_body(tmp_path: Path, monkeypatch, capsys, response, shown):
    bundle = tmp_path / "showcase"
    shutil.copytree(SHOWCASE, bundle)
    make_run_db(bundle.parent, paper_id_of(bundle))

    def fake(req: httpx.Request) -> httpx.Response:
        return response

    monkeypatch.setattr(
        pc, "client_factory", lambda url: httpx.Client(base_url=url, transport=httpx.MockTransport(fake))
    )
    monkeypatch.setenv("E2ER_TOKEN", "e2er_" + "C" * 43)
    rc = publish(
        str(bundle), to_url="https://platform.test", owner="ada-lab", project="showcase", github="ada-lab",
        name="Ada Lovelace", commit="abc1234", data="public", code="public",
    )  # fmt: skip
    out = capsys.readouterr().out
    assert rc == 1
    line = next(ln for ln in out.splitlines() if ln.startswith("error:"))
    assert line.startswith(shown), out
    assert line != "error: "


def test_error_text_shortens_a_long_page():
    text = pc.error_text(502, {"_body": "<html>" + "x" * 1000})
    assert text.startswith("HTTP 502: <html>xxx") and text.endswith("…") and len(text) < 230
