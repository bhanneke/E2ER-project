"""e2er publish: the research-object manifest derived from an exported bundle."""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from src.cli_publish import publish
from src.cli_verify import _run_checks
from src.core.research_object import PublishError, build_manifest

ROOT = Path(__file__).resolve().parents[1]
SHOWCASE = ROOT / "examples" / "showcase"
PAPER_ID = json.loads((SHOWCASE / "provenance.json").read_text())["run"]["paper_id"]


@pytest.fixture
def bundle(tmp_path: Path) -> Path:
    dst = tmp_path / "showcase"
    shutil.copytree(SHOWCASE, dst)
    return dst


@pytest.fixture
def run_db(tmp_path: Path) -> Path:
    db = tmp_path / "run.db"
    con = sqlite3.connect(db)
    con.executescript(
        "CREATE TABLE papers (id TEXT, mode TEXT, methodology TEXT, governance TEXT);"
        "CREATE TABLE llm_usage (id TEXT, paper_id TEXT, specialist TEXT, backend TEXT, model TEXT,"
        " input_tokens INT, output_tokens INT, cache_read_tokens INT, cache_write_tokens INT,"
        " cost_usd REAL, created_at TEXT);"
    )
    con.execute("INSERT INTO papers VALUES (?, 'single_pass', 'empirical', 'full')", (PAPER_ID,))
    for i, agent in enumerate(["strategist:decide", "idea_developer", "paper_drafter", "paper_drafter"]):
        con.execute(
            "INSERT INTO llm_usage VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (str(i), PAPER_ID, agent, "claude_code", "claude-sonnet-4-5", 10, 20, 0, 0, 0.0, f"2026-09-11 10:0{i}:00"),
        )
    con.commit()
    con.close()
    return db


def _manifest(bundle: Path, **kw):
    return build_manifest(bundle, owner="bhanneke", project="demo", contributors=[{"github": "bhanneke"}], **kw)


def test_content_id_is_the_digest_of_provenance(bundle: Path):
    m = _manifest(bundle)
    assert m["content_id"] == "sha256:" + hashlib.sha256((bundle / "provenance.json").read_bytes()).hexdigest()
    assert m["provenance"]["files"] == len(json.loads((bundle / "provenance.json").read_text())["files"])


def test_agents_are_recorded_from_the_run_database(bundle: Path, run_db: Path):
    m = _manifest(bundle, db=run_db)
    assert m["ai"]["agents_source"] == "recorded"
    assert m["ai"]["agents"] == ["idea_developer", "paper_drafter"]
    assert next(u for u in m["ai"]["usage"] if u["agent"] == "paper_drafter")["calls"] == 2
    assert "agent:paper_drafter" in m["dependencies"]["uses"]


def test_without_a_database_agents_come_from_the_template_file(bundle: Path):
    m = _manifest(bundle, template_file=ROOT / "pipelines" / "empirical.toml")
    assert m["ai"]["agents_source"] == "declared"
    assert "self_attacker" not in m["ai"]["agents"]  # iterative-only step, not in single_pass


def test_literature_comes_from_the_citation_edges(bundle: Path):
    m = _manifest(bundle)
    assert m["literature"] and all(x["cite_key"] for x in m["literature"])


def test_publish_writes_a_manifest_that_does_not_break_verify(bundle: Path, run_db: Path, tmp_path: Path):
    code = publish(
        str(bundle),
        owner="bhanneke",
        project="demo",
        github="bhanneke",
        db=str(run_db),
        commit="abc1234",
        out=str(tmp_path / "entry"),
    )
    assert code == 0
    assert (bundle / "e2er.json").is_file()
    assert (tmp_path / "entry" / "registry" / "objects" / "bhanneke" / "demo.json").is_file()
    assert all(c.status == "PASS" for c in _run_checks(bundle, online=False))


def test_invalid_owner_and_missing_provenance_are_rejected(bundle: Path, tmp_path: Path):
    with pytest.raises(PublishError):
        build_manifest(bundle, owner="Not A Login", project="demo", contributors=[{"github": "x"}])
    with pytest.raises(PublishError):
        build_manifest(tmp_path, owner="bhanneke", project="demo", contributors=[{"github": "x"}])
