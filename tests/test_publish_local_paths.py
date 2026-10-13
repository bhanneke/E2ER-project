"""Runs recorded with e2er 0.13.7 publish: no path of this machine reaches the dossier (2026-10-06 review, P0 #1).

0.13.7 recorded the CLI's install path in the run's ``backend_identity`` event
(``/Users/<name>/.local/bin/claude``); the dossier copied the event as it was
and ``e2er publish`` refused every Claude Code run ("the dossier names a path
on this machine"). Error messages that quote a file (a failed step, the run's
last error) did the same. The backends now record the CLI's name, and the
dossier cuts any path in what the run recorded to its last part, so runs
recorded before the fix publish too. A path anywhere else in the dossier still
stops publish.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.cli_publish import publish
from src.core import platform_client as pc
from src.core.dossier import build_dossier, dossier_id, read_run
from src.core.secret_scan import find_local_paths, strip_local_paths
from src.modules.llm import cli_support
from tests.run_db import make_run_db, paper_id_of
from tests.test_publish_data_terms import _add

ROOT = Path(__file__).resolve().parents[1]
SHOWCASE = ROOT / "tests" / "fixtures" / "showcase_export"
ARGS = dict(owner="bhanneke", project="demo", github="bhanneke", commit="abc1234", data="private", code="private")
CLI = "/Users/ann/.local/bin/claude"


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("E2ER_PURPOSE", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr("src.cli_publish.shutil.which", lambda _: None)
    from src.db import client

    real = client._sqlite_path
    monkeypatch.setattr(
        "src.db.client._sqlite_path", lambda url: real(url) if url else str(tmp_path / "home-default.db")
    )
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)


@pytest.fixture
def bundle(tmp_path: Path) -> Path:
    dst = tmp_path / "study" / "exports" / "showcase"
    shutil.copytree(SHOWCASE, dst, ignore=shutil.ignore_patterns(".e2er", "e2er.json"))
    return dst


def _record_0137_run(db: Path, pid: str) -> None:
    """What a 0.13.7 Claude Code run that hit a missing file recorded."""
    ws = f"/Users/ann/e2er-studies/s/workspaces/{pid}"
    con = sqlite3.connect(db)
    rows = [
        (
            "backend_identity",
            {"backend": "claude_code", "model": "sonnet", "cli": CLI, "cli_version": "2.1.270 (Claude Code)"},
        ),
        ("failed", {"error": f"FileNotFoundError: [Errno 2] No such file or directory: '{ws}/data/x.csv'"}),
        ("paper_paused", {"reason": f"step stopped: could not read {ws}/results/table.tex"}),
    ]
    for i, (etype, payload) in enumerate(rows):
        con.execute(
            "INSERT INTO pipeline_events VALUES (?,?,?,NULL,NULL,?,?)",
            (f"p{i}", pid, etype, json.dumps(payload), f"2026-09-11 10:0{i}:30"),
        )
    con.execute(
        "UPDATE papers SET last_error = ? WHERE id = ?", (f"Could not open /private/var/folders/ab/T/{pid}.log", pid)
    )
    con.commit()
    con.close()


def _no_path_left(doc: dict) -> None:
    assert find_local_paths(doc) == []
    text = json.dumps(doc, ensure_ascii=False)
    import re

    assert "/Users/" not in text and "/private/" not in text and not re.search(r"\bann\b", text)


def test_a_0137_claude_code_run_publishes_without_a_local_path(bundle: Path, tmp_path: Path, monkeypatch, capsys):
    pid = paper_id_of(bundle)
    db = make_run_db(tmp_path / "study", pid)
    _record_0137_run(db, pid)

    assert publish(str(bundle), **ARGS, dry_run=True) == 0
    assert "names a path on this machine" not in capsys.readouterr().out

    sent: list[dict] = []

    def server(base, method, path, token=None, body=None):
        sent.append(body)
        oid = body["manifest"]["id"]
        return 201, {"id": oid, "owner_project": oid, "version": 1, "study_url": "u", "dossier_url": "d"}

    monkeypatch.setattr(pc, "request", server)
    monkeypatch.setattr(pc, "load_token", lambda base: "tok")
    assert publish(str(bundle), **ARGS, to_url="https://e2er.example") == 0
    doc = sent[0]["dossier"]["doc"]
    _no_path_left(doc)
    events = {e["event"]: e for e in doc["run"]["events"]} if "run" in doc else {}
    if not events:  # where the dossier keeps the run's events
        events = {e["event"]: e for e in doc.get("events", [])}
    ident = events["backend_identity"]
    assert ident["cli"] == "…/claude" and ident["cli_version"] == "2.1.270 (Claude Code)"
    assert events["failed"]["error"].endswith("'…/x.csv'")
    assert sent[0]["dossier"]["id"] == dossier_id(doc)


def test_the_run_record_keeps_everything_but_the_paths(tmp_path: Path, bundle: Path):
    pid = paper_id_of(bundle)
    db = make_run_db(tmp_path / "study", pid)
    _record_0137_run(db, pid)
    rec = read_run(db, pid)
    _no_path_left({"e": rec.events, "o": rec.outcome, "w": rec.workflow, "s": rec.segments})
    assert rec.outcome["error"] == f"Could not open …/{pid}.log"
    paused = next(e for e in rec.events if e["event"] == "paper_paused")
    assert paused["reason"] == "step stopped: could not read …/table.tex"


def test_a_run_without_paths_gives_the_same_dossier_as_before(tmp_path: Path, bundle: Path, monkeypatch):
    """Issued dossiers keep their address: the cut touches only strings holding a path."""
    pid = paper_id_of(bundle)
    db = make_run_db(tmp_path / "study", pid)
    m = json.loads((SHOWCASE / "e2er.json").read_text()) if (SHOWCASE / "e2er.json").is_file() else None
    rec = read_run(db, pid)
    monkeypatch.setattr("src.core.dossier.strip_local_paths", lambda v: v)
    unscrubbed = read_run(db, pid)
    assert rec == unscrubbed
    if m is not None:
        assert dossier_id(build_dossier(m, run=rec, bundle=bundle)) == dossier_id(
            build_dossier(m, run=unscrubbed, bundle=bundle)
        )


def test_a_local_path_outside_the_run_record_still_stops_publish(bundle: Path, tmp_path: Path, capsys):
    pid = paper_id_of(bundle)
    make_run_db(tmp_path / "study", pid)
    load = {
        "connector": "local",
        "files": [{"path": "/Users/ann/Downloads/prices.csv", "sha256": "b" * 64}],
    }
    _add(bundle, "data/data_sources.json", json.dumps({"loads": [load]}).encode())
    assert publish(str(bundle), **ARGS, dry_run=True) == 1
    assert "names a path on this machine" in capsys.readouterr().out
    assert not (bundle / "e2er.json").exists()


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("/Users/ann/.local/bin/claude", "…/claude"),
        ("see /private/var/folders/x/T/a.txt, then", "see …/a.txt, then"),
        ("C:\\Users\\ann\\x.py", "…/x.py"),
        ("/opt/homebrew/bin/gemini", "…/gemini"),
        ("/home/bob/", "~"),
        ("https://e2er.org/d/123 and data/x.csv", "https://e2er.org/d/123 and data/x.csv"),
        ("~/x", "~/x"),
    ],
)
def test_strip_local_paths(text: str, want: str):
    assert strip_local_paths(text) == want
    assert find_local_paths(strip_local_paths({"a": [text]})) == []


@pytest.mark.parametrize("backend", ["claude_code", "codex", "gemini"])
def test_backends_record_the_cli_name_not_its_path(backend: str, monkeypatch):
    from src.config import get_settings
    from src.modules.llm.registry import get_backend

    get_settings.cache_clear()
    b = get_backend(get_settings(), name=backend)
    b._cli_path = f"/Users/ann/.local/bin/{backend}"  # noqa: SLF001
    cli_support.cli_version.cache_clear()
    with patch("src.modules.llm.cli_support.subprocess.run") as run:
        run.return_value = MagicMock(returncode=0, stdout="9.9.9\n", stderr="")
        ident = b.identity()
    cli_support.cli_version.cache_clear()
    assert ident["cli"] == backend and ident["cli_version"] == "9.9.9"
    assert find_local_paths(ident) == []


def test_a_url_whose_path_starts_with_home_is_not_a_local_path():
    """World Bank's indicator metadata cite "https://unstats.un.org/home/nso_sites/" (2026-10-11 live run):
    publishing refused the dossier as naming a path on this machine."""
    from src.core.secret_scan import find_local_paths

    assert find_local_paths({"citation": "uri: https://unstats.un.org/home/nso_sites/, publisher: UN"}) == []
    assert find_local_paths({"f": "file:///Users/ada/data.csv"}) == ["$.f"]
    assert find_local_paths({"f": "read /home/ada/data.csv"}) == ["$.f"]
