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
from src.core.dossier import build_dossier, canonical, dossier_id, recorded_workflow, stamp_paper
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


@pytest.fixture
def workflow_db(run_db: Path) -> Path:
    con = sqlite3.connect(run_db)
    con.executescript(
        "CREATE TABLE pipeline_events (id TEXT, paper_id TEXT, event_type TEXT, stage TEXT, specialist TEXT,"
        " payload TEXT, created_at TEXT);"
        "CREATE TABLE contributions (id TEXT, paper_id TEXT, specialist TEXT, stage TEXT, output_file TEXT,"
        " success INT, error_msg TEXT, usage_tokens INT, cost_usd REAL, duration_sec REAL, created_at TEXT);"
    )
    ws = f"workspaces/{PAPER_ID}/"
    events = [
        ("run_identity", None, None, {"git_sha": "f" * 40, "git_dirty": False}),
        ("phase_start", "initial", None, {}),
        ("specialist_start", None, "idea_developer", {}),
        ("specialist_end", None, "idea_developer", {"success": True}),
        ("specialist_start", None, "paper_drafter", {}),
        (
            "gate_enforced",
            "contracts",
            None,
            {"gate": "contracts", "passed": False, "enforced": True, "detail": "inline tabular"},
        ),
        ("specialist_end", None, "paper_drafter", {"success": False}),
        ("specialist_start", None, "paper_drafter", {}),
        ("specialist_end", None, "paper_drafter", {"success": True}),
    ]
    for i, (etype, stage, sp, payload) in enumerate(events):
        con.execute(
            "INSERT INTO pipeline_events VALUES (?,?,?,?,?,?,?)",
            (str(i), PAPER_ID, etype, stage, sp, json.dumps(payload), f"2026-09-11 10:{i:02d}:00"),
        )
    for i, (sp, out, ok, err) in enumerate(
        [
            ("idea_developer", "paper_plan.md", 1, None),
            ("paper_drafter", "paper_draft.tex", 0, "contract violation"),
            ("paper_drafter", "paper_draft.tex", 1, None),
        ]
    ):
        con.execute(
            "INSERT INTO contributions VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (str(i), PAPER_ID, sp, None, ws + out, ok, err, 0, 0.0, 1.0, f"2026-09-11 10:{i:02d}:30"),
        )
    con.commit()
    con.close()
    return run_db


def test_workflow_lists_steps_checks_and_intermediate_files(bundle: Path, workflow_db: Path):
    steps = recorded_workflow(workflow_db, PAPER_ID, bundle)
    kinds = [(s["type"], s.get("specialist") or s.get("check")) for s in steps]
    assert kinds == [
        ("specialist", "idea_developer"),
        ("check", "contracts"),
        ("specialist", "paper_drafter"),
        ("specialist", "paper_drafter"),
    ]
    plan = steps[0]["output"]
    prov = json.loads((bundle / "provenance.json").read_text())["files"]
    assert plan == {"file": "design/paper_plan.md", "sha256": prov["design/paper_plan.md"]["sha256"]}
    assert steps[1]["passed"] is False and steps[1]["detail"] == "inline tabular"
    assert steps[2]["accepted"] is False and steps[2]["stopped_by"] == "contract violation"
    assert steps[3]["output"] == {"file": "paper_draft.tex", "exported": False}


def test_dossier_id_is_the_hash_of_its_canonical_json_and_ignores_the_paper(bundle: Path, workflow_db: Path):
    m = _manifest(bundle, db=workflow_db)
    doc = build_dossier(m, db=workflow_db, bundle=bundle)
    assert doc["e2er"]["commit"] == "f" * 40
    assert dossier_id(doc) == "sha256:" + hashlib.sha256(canonical(doc).encode()).hexdigest()
    (bundle / "paper" / "paper.tex").write_text("changed", encoding="utf-8")
    assert dossier_id(build_dossier(m, db=workflow_db, bundle=bundle)) == dossier_id(doc)


def test_stamp_writes_author_and_footnote_once():
    tex = "\\title{T}\n\\author{}\n\\begin{document}\n"
    did = "sha256:" + "ab" * 32
    once = stamp_paper(tex, "Ada Lovelace", did)
    assert "\\author{Ada Lovelace with e2er\\thanks{" in once
    assert "\\url{https://e2er.org/d/abababababababab}" in once
    assert stamp_paper(once, "Ada Lovelace", did) == once


def test_publish_stamps_the_paper_and_the_bundle_still_verifies(
    bundle: Path, workflow_db: Path, tmp_path: Path, monkeypatch
):
    monkeypatch.setattr("src.cli_publish.shutil.which", lambda _: None)  # no recompile in tests
    code = publish(
        str(bundle),
        owner="bhanneke",
        project="demo",
        github="bhanneke",
        name="Ada Lovelace",
        db=str(workflow_db),
        commit="abc1234",
        out=str(tmp_path / "entry"),
    )
    assert code == 0
    m = json.loads((bundle / "e2er.json").read_text())
    assert m["dossier"]["id"] == dossier_id(m["dossier"]["doc"])
    assert m["dossier"]["url"] in (bundle / "paper" / "paper.tex").read_text()
    assert m["dossier"]["doc"]["workflow"]
    assert all(c.status == "PASS" for c in _run_checks(bundle, online=False))


# ── bibliography: the paper must compile from the bundle ────────────────────
from src.core.bibliography import bibliography_names, point_bibliography, unresolved_citations  # noqa: E402


def test_bibliography_is_repointed_to_the_shipped_file(tmp_path: Path):
    (tmp_path / "refs.bib").write_text("@article{a2020x, title={T}}\n")
    tex = "\\bibliographystyle{chicago}\n\\bibliography{literature}\n"
    assert bibliography_names(tex) == ["literature"]
    assert "\\bibliography{refs}" in point_bibliography(tex, tmp_path)
    (tmp_path / "literature.bib").write_text("@article{a2020x, title={T}}\n")
    assert point_bibliography(tex, tmp_path) == tex  # named file present: unchanged


def test_unresolved_citations_compares_aux_with_bbl(tmp_path: Path):
    (tmp_path / "paper.aux").write_text("\\citation{a2020x,b2021y}\n\\citation{c2022z}\n")
    (tmp_path / "paper.bbl").write_text("\\bibitem[A(2020)]{a2020x} x\n\\bibitem{c2022z} z\n")
    assert unresolved_citations(tmp_path) == ["b2021y"]


def test_verify_fails_when_the_paper_names_a_bibliography_the_bundle_lacks(bundle: Path):
    tex = bundle / "paper" / "paper.tex"
    tex.write_text(tex.read_text().replace("\\bibliography{refs}", "\\bibliography{literature}"))
    check = next(c for c in _run_checks(bundle, online=False) if c.name == "citations")
    assert check.status == "FAIL" and "literature.bib" in check.detail


@pytest.mark.skipif(shutil.which("tectonic") is None, reason="tectonic not installed")
def test_publish_refuses_a_recompile_that_loses_citations(bundle: Path, workflow_db: Path, tmp_path: Path):
    refs = bundle / "paper" / "refs.bib"
    text = refs.read_text()
    first = text.index("@", 1)  # drop the first entry so one cited key has no bib entry
    refs.write_text(text[first:])
    before_tex, before_pdf = (
        (bundle / "paper" / "paper.tex").read_bytes(),
        (bundle / "paper" / "paper.pdf").read_bytes(),
    )
    code = publish(
        str(bundle),
        owner="bhanneke",
        project="demo",
        github="bhanneke",
        name="Ada Lovelace",
        db=str(workflow_db),
        commit="abc1234",
        out=str(tmp_path / "entry"),
    )
    assert code == 1
    assert (bundle / "paper" / "paper.pdf").read_bytes() == before_pdf
    assert (bundle / "paper" / "paper.tex").read_bytes() in (
        before_tex,
        before_tex.replace(b"\\bibliography{literature}", b"\\bibliography{refs}"),
    )
