"""`e2er publish` runs the study's code again before it publishes, and publishes only a study that reproduces.

The reproduction is `e2er reproduce --yes` in the Docker sandbox, on the folder about to be published (on the
anonymised copy with --blind). Docker and the run are faked here: no test starts Docker, runs a study, reaches
a network or calls a model. Its outcome goes into the description's ``verification`` list (e2er.json and the
request), never into provenance.json or the dossier, whose ids must not depend on the computer that published.
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from src.cli_publish import publish
from src.core import platform_client as pc
from src.core import prepublish
from src.core.dossier import dossier_id
from tests.conftest import FAKE_REPRODUCED_REPORT, REAL_REPRODUCE_FIRST
from tests.run_db import make_run_db, paper_id_of
from tests.test_blind import rehash
from tests.test_publish_integrity import ARGS, bundle  # noqa: F401  (fixture)
from tests.test_publish_site_schema import SCHEMA

SITE = "https://e2er.example"


class Server:
    """A fake e2er.org: records every request publish sends."""

    def __init__(self) -> None:
        self.sent: list[dict] = []

    def __call__(self, base, method, path, token=None, body=None):
        if path == "/api/v1/me":
            return 200, {"name": "Test"}
        self.sent.append(body)
        oid = body["manifest"]["id"]
        return 201, {"id": oid, "owner_project": oid, "version": 1, "study_url": f"{base}/{oid}", "dossier_url": "x"}


@pytest.fixture
def server(monkeypatch) -> Server:
    fake = Server()
    monkeypatch.setattr(pc, "request", fake)
    monkeypatch.setattr(pc, "load_token", lambda base: "tok")
    return fake


@pytest.fixture
def runs(monkeypatch, bundle: Path, tmp_path: Path) -> list[Path]:  # noqa: F811
    """The real step, with a reproduce.json in the folder, and the folders the (faked) run was asked to run."""
    (bundle / "reproduce.json").write_text('{"schema": "e2er-reproduce/1"}\n', encoding="utf-8", newline="\n")
    rehash(bundle, ["reproduce.json"])
    make_run_db(tmp_path / "study", paper_id_of(bundle), researcher_actions=2)
    monkeypatch.setattr(prepublish, "reproduce_first", REAL_REPRODUCE_FIRST)
    seen: list[Path] = []

    def reproduced(folder, report):
        seen.append(Path(folder))
        report.update(FAKE_REPRODUCED_REPORT)
        return 0

    monkeypatch.setattr(prepublish, "run_reproduction", reproduced)
    return seen


def _go(b: Path, **kw) -> int:
    return publish(str(b), **ARGS, to_url=SITE, site=SITE, yes=True, interactive=False, **kw)


def test_a_study_that_reproduces_is_published_with_the_outcome(bundle, server, runs, capsys):  # noqa: F811
    assert _go(bundle) == 0, capsys.readouterr().out
    assert runs == [bundle], "the folder about to be published is the one that ran"
    [body] = server.sent
    manifest = body["manifest"]
    [entry] = [v for v in manifest["verification"] if v["check"] == "reproduction"]
    assert entry["status"] == "PASS"
    assert entry["detail"].startswith("reproduced before publishing, on ")
    assert (
        "in Docker (python:3.12-slim): 3 of 3 values identical or the same at the published precision"
        in (entry["detail"])
    )
    rec = entry["reproduction"]
    assert rec["reproduced"] is True and rec["exit_code"] == 0 and rec["category"] == "reproduced"
    assert rec["e2er_version"] == "0.0.0-test" and rec["platform"]["machine"] == "x86_64"
    assert rec["python"] == "3.12.14" and rec["sandbox"] == "python:3.12-slim"
    assert rec["counts"]["values"] == 3 and rec["counts"]["identical"] == 3
    # As the site validates it, and in e2er.json; not in the dossier (its id stays the study's).
    d = body["dossier"]
    jsonschema.Draft202012Validator(SCHEMA).validate(
        {**manifest, "dossier": {"id": d["id"], "url": manifest["dossier"]["url"], "doc": d["doc"]}}
    )
    written = json.loads((bundle / "e2er.json").read_text(encoding="utf-8"))
    assert [v for v in written["verification"] if v["check"] == "reproduction"] == [entry]
    assert "reproduction" not in json.dumps(d["doc"]) and dossier_id(d["doc"]) == d["id"]
    assert json.loads((bundle / prepublish.REPORT_FILE).read_text(encoding="utf-8"))["exit_code"] == 0


def test_a_study_that_does_not_reproduce_is_not_published(bundle, server, runs, monkeypatch, capsys):  # noqa: F811
    def differs(folder, report):
        report.update({**FAKE_REPRODUCED_REPORT, "exit_code": 1, "verdict": "Not reproduced exactly: 2 differ."})
        return 1

    monkeypatch.setattr(prepublish, "run_reproduction", differs)
    assert _go(bundle) == 1
    out = capsys.readouterr().out
    assert server.sent == [], "nothing was sent"
    assert "error: not published: the study does not reproduce. Not reproduced exactly: 2 differ." in out
    assert '--skip-reproduce "<why>"' in out and "export it again" in out
    assert not (bundle / "e2er.json").exists()


def test_without_docker_nothing_runs_and_publish_says_how_to_start_it(bundle, server, runs, monkeypatch, capsys):  # noqa: F811
    monkeypatch.setattr(prepublish, "docker_missing", lambda: "Docker is not running")
    assert _go(bundle) == 1
    out = capsys.readouterr().out
    assert runs == [] and server.sent == []
    assert "error: e2er publish runs the study's code again in a Docker sandbox before it publishes, and docker " in (
        out
    )
    assert "https://docs.docker.com/get-docker/" in out and "Docker Desktop" in out and "--skip-reproduce" in out


def test_skip_reproduce_publishes_and_records_why(bundle, server, runs, capsys):  # noqa: F811
    assert _go(bundle, skip_reproduce="the data provider is down this week") == 0, capsys.readouterr().out
    assert runs == []
    [entry] = [v for v in server.sent[0]["manifest"]["verification"] if v["check"] == "reproduction"]
    assert entry["status"] == "SKIP"
    assert entry["detail"] == "not reproduced before publishing: the data provider is down this week"
    assert entry["reproduction"]["reproduced"] is False
    assert entry["reproduction"]["skipped"] == "the data provider is down this week"


def test_skip_reproduce_needs_a_reason(bundle, server, runs, capsys):  # noqa: F811
    assert _go(bundle, skip_reproduce="  ") == 2
    assert "--skip-reproduce needs the reason" in capsys.readouterr().out
    assert runs == [] and server.sent == []


def test_a_folder_without_reproduce_json_is_refused_with_what_to_do(bundle, server, monkeypatch, capsys):  # noqa: F811
    make_run_db(bundle.parent.parent, paper_id_of(bundle), researcher_actions=2)
    monkeypatch.setattr(prepublish, "reproduce_first", REAL_REPRODUCE_FIRST)
    assert _go(bundle) == 1
    out = capsys.readouterr().out
    assert "this folder has no reproduce.json" in out and "e2er export" in out and "--skip-reproduce" in out
    assert server.sent == []


def test_a_dry_run_runs_nothing_unless_asked(bundle, runs, capsys):  # noqa: F811
    assert publish(str(bundle), **ARGS, dry_run=True, to_url=SITE, site=SITE) == 0
    captured = capsys.readouterr()
    assert runs == []
    assert "this dry run does not. --reproduce runs it in the dry run too" in captured.err
    body = json.loads(captured.out)
    assert not [v for v in body["manifest"]["verification"] if v["check"] == "reproduction"]
    assert publish(str(bundle), **ARGS, dry_run=True, reproduce=True, to_url=SITE, site=SITE) == 0
    captured = capsys.readouterr()
    assert len(runs) == 1
    body = json.loads(captured.out)  # standard output holds the request alone
    [entry] = [v for v in body["manifest"]["verification"] if v["check"] == "reproduction"]
    assert entry["status"] == "PASS"


def test_offline_reproduces_before_it_prepares_the_folder(bundle, runs, capsys):  # noqa: F811
    assert publish(str(bundle), **ARGS, offline=True) == 0, capsys.readouterr().out
    assert runs == [bundle]
    written = json.loads((bundle / "e2er.json").read_text(encoding="utf-8"))
    assert [v["status"] for v in written["verification"] if v["check"] == "reproduction"] == ["PASS"]


def test_the_report_file_does_not_unsettle_verify(bundle, server, runs, capsys):  # noqa: F811
    from src.cli_verify import FAIL, _run_checks

    assert _go(bundle) == 0, capsys.readouterr().out
    assert (bundle / prepublish.REPORT_FILE).is_file()
    assert not [c for c in _run_checks(bundle, online=False) if c.status == FAIL]


def test_counts_leave_out_files_that_were_not_compared():
    report = {
        "results": [
            {"values": 4, "counts": {"identical": 3, "same_at_precision": 1}},
            {"values": 0, "counts": {}, "not_compared": True},
        ],
        "tables": {"rendered": 2, "identical": ["a.tex", "b.tex"]},
        "inputs": [{"status": "identical"}, {"status": "differs", "reloaded": True}, {"output": True}],
    }
    c = prepublish.counts(report)
    assert c["values"] == 4 and c["identical"] == 3 and c["same_at_precision"] == 1
    assert c["result_files"] == 1 and c["result_files_not_compared"] == 1
    assert c["tables"] == 2 and c["tables_identical"] == 2
    assert c["inputs"] == 2 and c["inputs_identical"] == 1 and c["inputs_reloaded"] == 1


def test_a_source_that_did_not_answer_says_to_try_again_later(bundle, server, runs, monkeypatch, capsys):  # noqa: F811
    def unanswered(folder, report):
        report.update(
            {
                **FAKE_REPRODUCED_REPORT,
                "exit_code": 2,
                "category": "source_unavailable",
                "verdict": "Could not reproduce yet: a source did not answer while `python get_data.py` loaded the "
                "data again (Gutendex did not answer within 45 s).",
            }
        )
        return 2

    monkeypatch.setattr(prepublish, "run_reproduction", unanswered)
    assert _go(bundle) == 1
    out = capsys.readouterr().out
    assert "error: not published yet: Could not reproduce yet: a source did not answer" in out
    assert "Run the same command again later." in out and server.sent == []
