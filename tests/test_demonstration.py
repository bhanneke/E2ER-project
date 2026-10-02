"""Demonstration studies: `e2er publish --demonstration` / E2ER_PURPOSE and the disclaimer."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.cli_publish import publish
from src.cli_verify import _run_checks
from src.core.demonstration import DISCLAIMERS, disclaimer, kind_for, mark_report, resolve_purpose
from src.core.dossier import build_dossier, dossier_id, stamp_paper
from src.core.research_object import build_manifest
from tests.run_db import make_run_db, paper_id_of

ROOT = Path(__file__).resolve().parents[1]
SHOWCASE = ROOT / "examples" / "showcase"
DID = "sha256:" + "ab" * 32


@pytest.fixture(autouse=True)
def _no_purpose(monkeypatch, tmp_path: Path):
    """No E2ER_PURPOSE from the caller's environment, and a working directory without .env."""
    monkeypatch.delenv("E2ER_PURPOSE", raising=False)
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    monkeypatch.setattr("src.cli_publish.shutil.which", lambda _: None)  # no recompile in tests
    return cwd


@pytest.fixture
def bundle(tmp_path: Path) -> Path:
    dst = tmp_path / "showcase"
    shutil.copytree(SHOWCASE, dst)
    make_run_db(tmp_path, paper_id_of(dst))  # the study folder's run database, named in its .env
    return dst


def _publish(bundle: Path, tmp_path: Path, **kw) -> int:
    return publish(
        str(bundle),
        owner="bhanneke",
        project="demo",
        github="bhanneke",
        name="Ada Lovelace",
        commit="abc1234",
        out=str(tmp_path / "entry"),
        data="private",
        code="private",
        **kw,
    )


# ── wording and resolution ──────────────────────────────────────────────────
def test_the_two_wordings():
    assert disclaimer() == disclaimer("study") == DISCLAIMERS["study"]
    assert disclaimer("replication") == DISCLAIMERS["replication"]
    assert disclaimer().startswith("Demonstration. This study was produced with e2er")
    assert "replication template" in disclaimer("replication")
    assert kind_for("replication") == "replication" and kind_for("empirical") is None


def test_purpose_from_flag_env_and_dotenv(monkeypatch, _no_purpose: Path):
    assert resolve_purpose() is None
    assert resolve_purpose(True) == "demonstration"
    (_no_purpose / ".env").write_text("FRED_API_KEY=x\nE2ER_PURPOSE=demonstration\n")
    assert resolve_purpose() == "demonstration"
    monkeypatch.setenv("E2ER_PURPOSE", "")  # the environment wins over .env; empty means none
    assert resolve_purpose() is None


def test_an_unknown_purpose_is_refused(monkeypatch):
    monkeypatch.setenv("E2ER_PURPOSE", "showcase")
    with pytest.raises(ValueError, match="E2ER_PURPOSE"):
        resolve_purpose()
    assert resolve_purpose(True) == "demonstration"  # the flag needs no environment


# ── the paper's first page ──────────────────────────────────────────────────
def test_stamp_without_purpose_is_unchanged():
    tex = "\\title{T}\n\\author{}\n\\begin{document}\n"
    plain = stamp_paper(tex, "Ada Lovelace", DID)
    assert "Demonstration" not in plain
    assert plain == stamp_paper(tex, "Ada Lovelace", DID, purpose=None, kind="replication")


@pytest.mark.parametrize("kind", [None, "replication"])
def test_stamp_adds_the_disclaimer_footnote_once(kind):
    tex = "\\title{T}\n\\author{}\n\\begin{document}\n"
    once = stamp_paper(tex, "Ada Lovelace", DID, purpose="demonstration", kind=kind)
    assert f"\\thanks{{{disclaimer(kind)}}}}}" in once
    assert once.count("\\thanks{") == 2
    assert stamp_paper(once, "Ada Lovelace", DID, purpose="demonstration", kind=kind) == once
    # Stamping again without the purpose returns the plain stamp.
    assert stamp_paper(once, "Ada Lovelace", DID) == stamp_paper(tex, "Ada Lovelace", DID)


# ── the dossier ─────────────────────────────────────────────────────────────
def test_dossier_hash_is_unchanged_without_purpose(bundle: Path):
    m = build_manifest(bundle, owner="bhanneke", project="demo", contributors=[{"github": "bhanneke"}])
    plain = build_dossier(m, bundle=bundle)
    assert "purpose" not in plain and "kind" not in plain
    demo = build_dossier({**m, "purpose": "demonstration", "kind": "replication"}, bundle=bundle)
    assert demo["purpose"] == "demonstration" and demo["kind"] == "replication"
    assert dossier_id(demo) != dossier_id(plain)
    assert dossier_id(build_dossier(m, bundle=bundle)) == dossier_id(plain)


# ── e2er publish ────────────────────────────────────────────────────────────
def test_publish_without_the_flag_records_no_purpose(bundle: Path, tmp_path: Path):
    assert _publish(bundle, tmp_path) == 0
    m = json.loads((bundle / "e2er.json").read_text())
    assert "purpose" not in m and "kind" not in m and "purpose" not in m["dossier"]["doc"]
    assert "Demonstration" not in (bundle / "paper" / "paper.tex").read_text()


def test_publish_demonstration_writes_manifest_dossier_and_paper(bundle: Path, tmp_path: Path):
    assert _publish(bundle, tmp_path, demonstration=True) == 0
    m = json.loads((bundle / "e2er.json").read_text())
    assert m["purpose"] == "demonstration" and "kind" not in m
    assert m["dossier"]["doc"]["purpose"] == "demonstration" and m["dossier"]["id"] == dossier_id(m["dossier"]["doc"])
    assert disclaimer() in (bundle / "paper" / "paper.tex").read_text()
    entry = json.loads((tmp_path / "entry" / "registry" / "objects" / "bhanneke" / "demo.json").read_text())
    assert entry["purpose"] == "demonstration"
    assert all(c.status == "PASS" for c in _run_checks(bundle, online=False))


def test_env_in_the_study_folder_makes_it_the_default(bundle: Path, tmp_path: Path, _no_purpose: Path):
    (_no_purpose / ".env").write_text("E2ER_PURPOSE=demonstration\n")
    assert _publish(bundle, tmp_path) == 0
    assert json.loads((bundle / "e2er.json").read_text())["purpose"] == "demonstration"


def test_a_bad_env_value_stops_publish(bundle: Path, tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setenv("E2ER_PURPOSE", "maybe")
    assert _publish(bundle, tmp_path) == 1
    assert "E2ER_PURPOSE" in capsys.readouterr().out
    assert not (bundle / "e2er.json").exists()


def _replication_bundle(tmp_path: Path) -> Path:
    """The replication demonstration as a run exports it: checked (summary written), then exported."""
    from src.core.export.structured import export_paper
    from src.core.pipeline.reproduction import check_reproduction

    ws = tmp_path / "ws"
    shutil.copytree(ROOT / "tests" / "fixtures" / "replication_demo", ws)
    (ws / "paper_draft.tex").write_text("\\documentclass{article}\\author{X}\\begin{document}R\\end{document}\n")
    assert check_reproduction(ws).passed
    bundle = export_paper(ws, tmp_path / "out", date_str="20260930", template="replication")
    make_run_db(tmp_path, paper_id_of(bundle))
    return bundle


def test_a_replication_study_gets_kind_and_the_replication_wording(tmp_path: Path):
    bundle = _replication_bundle(tmp_path)
    report = bundle / "misc" / "reproduction_report.md"
    assert _publish(bundle, tmp_path, demonstration=True) == 0
    m = json.loads((bundle / "e2er.json").read_text())
    assert m["purpose"] == "demonstration" and m["kind"] == "replication"
    assert m["dossier"]["doc"]["kind"] == "replication"
    assert disclaimer("replication") in report.read_text().split("\n# ", 1)[0]  # above the title
    assert disclaimer("replication") in (bundle / "paper" / "paper.tex").read_text()
    assert not any(c.status == "FAIL" for c in _run_checks(bundle, online=False))


def test_dry_run_request_carries_the_purpose(bundle: Path, capsys):
    code = publish(
        str(bundle), owner="bhanneke", project="demo", github="bhanneke", name="Ada Lovelace",
        commit="abc1234", data="private", code="private", dry_run=True, demonstration=True,
    )  # fmt: skip
    assert code == 0
    body = json.loads(capsys.readouterr().out)
    assert body["manifest"]["purpose"] == "demonstration"
    assert body["dossier"]["doc"]["purpose"] == "demonstration"
    assert not (bundle / "e2er.json").exists()


def test_the_cli_flag_exists():
    out = subprocess.run([sys.executable, "-m", "src", "publish", "--help"], cwd=ROOT, capture_output=True, text=True)
    assert "--demonstration" in out.stdout


# ── the reproduction report ─────────────────────────────────────────────────
def test_mark_report_is_idempotent(tmp_path: Path):
    p = tmp_path / "reproduction_report.md"
    assert not mark_report(p)  # no report, nothing to do
    p.write_text("# Report\n")
    assert mark_report(p) and not mark_report(p)
    assert p.read_text() == (
        f"<!-- e2er:disclaimer begin -->\n> {disclaimer('replication')}\n<!-- e2er:disclaimer end -->\n\n# Report\n"
    )


def test_the_reproduction_step_marks_the_report_in_a_demonstration_study(tmp_path: Path, monkeypatch):
    from src.core.pipeline.reproduction import CheckResult
    from src.core.strategist.runner import _reproduction_with_disclaimer

    (tmp_path / "reproduction_report.md").write_text("# Report\n")
    step = _reproduction_with_disclaimer(lambda ws, **kw: CheckResult(True, ()))
    assert step(tmp_path).passed
    assert (tmp_path / "reproduction_report.md").read_text() == "# Report\n"
    monkeypatch.setenv("E2ER_PURPOSE", "demonstration")
    assert step(tmp_path).passed
    assert disclaimer("replication") in (tmp_path / "reproduction_report.md").read_text().split("# Report")[0]
