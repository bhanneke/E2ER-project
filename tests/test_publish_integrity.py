"""`e2er publish`: what the 2026-10-01 review found (findings 1–4, 7, 8, 21, 24, 27).

Publish built a dossier with an empty workflow when --db was left out; it
changed files without checking them against provenance.json first, and lost
their exported fingerprints; with --zenodo the dossier's id did not match its
document, deposits were published before the steps that can still fail, and
every retry made new deposits and a new dossier; a PDF publish compiled was
never fingerprinted; the demonstration disclaimer was doubled and never
removed; a purpose recorded on the study was ignored; local paths could reach
the dossier; without --name the paper got no dossier link; the footnote
claimed more than the dossier holds.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import httpx
import pytest

from src.cli_publish import publish
from src.cli_verify import FAIL, _run_checks
from src.core import platform_client as pc
from src.core import zenodo as zen
from src.core.demonstration import disclaimer
from src.core.dossier import dossier_id
from tests.run_db import make_run_db, paper_id_of

ROOT = Path(__file__).resolve().parents[1]
SHOWCASE = ROOT / "examples" / "showcase"
ARGS = dict(owner="bhanneke", project="demo", github="bhanneke", commit="abc1234", data="private", code="private")


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("E2ER_PURPOSE", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr("src.cli_publish.shutil.which", lambda _: None)  # no tectonic unless a test says so
    monkeypatch.setattr("src.db.client._sqlite_path", _no_home_default(monkeypatch, tmp_path))
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)


def _no_home_default(monkeypatch, tmp_path: Path):
    """e2er's default database (~/.e2er/papers.db) is a test-local file, never the developer's own."""
    from src.db import client

    real = client._sqlite_path

    def path(url: str) -> str:
        return str(tmp_path / "home-default.db") if not url else real(url)

    return path


@pytest.fixture
def bundle(tmp_path: Path) -> Path:
    dst = tmp_path / "study" / "exports" / "showcase"
    shutil.copytree(SHOWCASE, dst)
    return dst


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _snapshot(b: Path) -> dict[str, bytes]:
    return {p.relative_to(b).as_posix(): p.read_bytes() for p in b.rglob("*") if p.is_file()}


def _manifest(b: Path) -> dict:
    return json.loads((b / "e2er.json").read_text())


# ── 1: the run's database is found, checked and required ─────────────────────


def test_publish_finds_the_studys_database_and_the_dossier_lists_the_run(bundle: Path, tmp_path: Path, capsys):
    make_run_db(tmp_path / "study", paper_id_of(bundle), researcher_actions=3)
    assert publish(str(bundle), **ARGS, out=str(tmp_path / "e")) == 0
    out = capsys.readouterr().out
    assert "3 researcher actions" in out
    doc = _manifest(bundle)["dossier"]["doc"]
    assert [s["type"] for s in doc["workflow"]].count("researcher") == 3
    assert [s.get("specialist") for s in doc["workflow"] if s["type"] == "specialist"] == [
        "idea_developer",
        "paper_drafter",
    ]
    assert doc["e2er"]["commit"] == "0" * 40  # the run's, not the publishing checkout's


def test_without_the_database_publish_refuses_and_changes_nothing(bundle: Path, tmp_path: Path, capsys):
    before = _snapshot(bundle)
    assert publish(str(bundle), **ARGS, out=str(tmp_path / "e")) == 1
    out = capsys.readouterr().out
    assert "no run database with paper" in out and "--db" in out and "--no-db" in out
    assert _snapshot(bundle) == before


def test_a_database_of_another_study_is_refused(bundle: Path, tmp_path: Path, capsys):
    other = make_run_db(tmp_path / "other", "11111111-2222-3333-4444-555555555555", env=False)
    assert publish(str(bundle), **ARGS, db=str(other), out=str(tmp_path / "e")) == 1
    assert "holds no run of paper" in capsys.readouterr().out
    assert not (bundle / "e2er.json").exists()


def test_no_db_publishes_loudly_and_the_dossier_and_footnote_say_the_steps_are_missing(
    bundle: Path, tmp_path: Path, capsys
):
    assert publish(str(bundle), **ARGS, no_db=True, name="Ada Lovelace", out=str(tmp_path / "e")) == 0
    assert "WARNING: --no-db" in capsys.readouterr().out
    doc = _manifest(bundle)["dossier"]["doc"]
    assert doc["workflow"] == [] and doc["run"]["workflow_recorded"] is False and doc["e2er"]["commit"] is None
    tex = (bundle / "paper" / "paper.tex").read_text()
    assert "the steps of the run are not recorded" in tex and "lists every step" not in tex


# ── 2: nothing changes in an edited folder; every change is an amendment ─────


def test_a_folder_edited_after_export_is_refused_before_anything_changes(bundle: Path, tmp_path: Path, capsys):
    make_run_db(tmp_path / "study", paper_id_of(bundle))
    tex = bundle / "paper" / "paper.tex"
    tex.write_text(tex.read_text().replace("\\begin{document}", "\\begin{document}\nWe find a huge effect.", 1))
    before = _snapshot(bundle)
    assert publish(str(bundle), **ARGS, name="Ada Lovelace", out=str(tmp_path / "e")) == 1
    out = capsys.readouterr().out
    assert "not what was exported" in out and "paper/paper.tex" in out
    assert _snapshot(bundle) == before


def test_each_change_publish_makes_keeps_the_exported_fingerprint(bundle: Path, tmp_path: Path):
    make_run_db(tmp_path / "study", paper_id_of(bundle))
    exported = json.loads((bundle / "provenance.json").read_text())["files"]["paper/paper.tex"]["sha256"]
    assert publish(str(bundle), **ARGS, name="Ada Lovelace", out=str(tmp_path / "e")) == 0
    prov = json.loads((bundle / "provenance.json").read_text())
    tex_amendments = [a for a in prov["amendments"] if a["path"] == "paper/paper.tex"]
    assert tex_amendments[0]["sha256_before"] == exported
    assert tex_amendments[-1]["sha256_after"] == _sha(bundle / "paper" / "paper.tex")
    assert all(a["reason"] and a["at"].endswith("Z") for a in prov["amendments"])
    assert not any(c.status == FAIL for c in _run_checks(bundle, online=False))
    # publishing again changes nothing and still verifies
    assert publish(str(bundle), **ARGS, name="Ada Lovelace", out=str(tmp_path / "e")) == 0
    assert json.loads((bundle / "provenance.json").read_text())["amendments"] == prov["amendments"]


# ── 3: Zenodo: the id is the document's, irreversible steps last, retries reuse ─


class FakeZenodo:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.next_id = 100

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.calls.append((req.method, req.url.path))
        if req.method == "POST" and req.url.path == "/api/deposit/depositions":
            self.next_id += 1
            i = self.next_id
            return httpx.Response(
                201,
                json={
                    "id": i,
                    "links": {"bucket": f"https://{req.url.host}/api/files/b{i}"},
                    "metadata": {"prereserve_doi": {"doi": f"10.5072/zenodo.{i}"}},
                },
            )
        if req.url.path.endswith("/actions/publish"):
            i = int(req.url.path.split("/")[4])
            return httpx.Response(
                202, json={"doi": f"10.5072/zenodo.{i}", "links": {"record_html": f"https://zenodo.org/records/{i}"}}
            )
        return httpx.Response(200, json={})

    def count(self, what: str) -> int:
        if what == "create":
            return sum(1 for m, p in self.calls if m == "POST" and p == "/api/deposit/depositions")
        return sum(1 for _, p in self.calls if p.endswith("/actions/publish"))


@pytest.fixture
def fake_zenodo(monkeypatch) -> FakeZenodo:
    f = FakeZenodo()
    monkeypatch.setattr(
        zen, "client_factory", lambda base: httpx.Client(base_url=base, transport=httpx.MockTransport(f))
    )
    monkeypatch.setenv("ZENODO_TOKEN", "tok")
    return f


ZARGS = {**ARGS, "data": "public", "code": "public", "zenodo": True, "name": "Ada Lovelace"}


def test_the_dossier_id_is_the_hash_of_the_document_with_the_dois(bundle: Path, tmp_path: Path, fake_zenodo):
    make_run_db(tmp_path / "study", paper_id_of(bundle))
    assert publish(str(bundle), **ZARGS, out=str(tmp_path / "e")) == 0
    m = _manifest(bundle)
    assert m["dossier"]["id"] == dossier_id(m["dossier"]["doc"])
    av = m["dossier"]["doc"]["availability"]
    assert av["data"]["doi"] == "10.5072/zenodo.101" and av["data"]["zenodo"].endswith("/records/101")
    assert av == m["availability"]


def test_a_failing_stamp_publishes_no_deposit_and_the_retry_reuses_the_drafts(
    bundle: Path, tmp_path: Path, fake_zenodo, monkeypatch, capsys
):
    make_run_db(tmp_path / "study", paper_id_of(bundle))
    import subprocess

    monkeypatch.setattr("src.cli_publish.shutil.which", lambda _: "/usr/bin/tectonic")
    monkeypatch.setattr("src.cli_publish.subprocess.run", lambda *a, **k: subprocess.CompletedProcess(a, 1, "", "boom"))
    assert publish(str(bundle), **ZARGS, out=str(tmp_path / "e")) == 1
    assert "tectonic failed" in capsys.readouterr().out
    assert fake_zenodo.count("create") == 2 and fake_zenodo.count("publish") == 0  # drafts only
    monkeypatch.setattr("src.cli_publish.shutil.which", lambda _: None)
    assert publish(str(bundle), **ZARGS, out=str(tmp_path / "e")) == 0
    assert fake_zenodo.count("create") == 2 and fake_zenodo.count("publish") == 2  # the same two deposits


def test_retrying_after_a_server_error_reuses_the_deposits_and_the_dossier(
    bundle: Path, tmp_path: Path, fake_zenodo, monkeypatch
):
    make_run_db(tmp_path / "study", paper_id_of(bundle))
    sent: list[str] = []

    def refuse(base, method, path, token=None, body=None):
        sent.append(body["dossier"]["id"])
        return 500, {"error": "internal server error"}

    monkeypatch.setattr(pc, "request", refuse)
    monkeypatch.setattr(pc, "load_token", lambda base: "tok")
    for _ in range(2):
        assert publish(str(bundle), **ZARGS, to_url="https://e2er.example", site="https://e2er.example") == 1
    assert len(sent) == 2 and sent[0] == sent[1]
    assert fake_zenodo.count("create") == 2 and fake_zenodo.count("publish") == 2


# ── 4: a PDF publish compiles is fingerprinted ───────────────────────────────


def test_a_pdf_compiled_by_publish_is_added_to_provenance(bundle: Path, tmp_path: Path, monkeypatch):
    make_run_db(tmp_path / "study", paper_id_of(bundle))
    (bundle / "paper" / "paper.pdf").unlink()
    prov = json.loads((bundle / "provenance.json").read_text())
    del prov["files"]["paper/paper.pdf"]
    (bundle / "provenance.json").write_text(json.dumps(prov, indent=2))
    import subprocess

    def tectonic(cmd, cwd, **kw):
        (Path(cwd) / "paper.pdf").write_bytes(b"%PDF compiled by publish")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr("src.cli_publish.shutil.which", lambda _: "/usr/bin/tectonic")
    monkeypatch.setattr("src.cli_publish.subprocess.run", tectonic)
    monkeypatch.setattr("src.cli_publish.unresolved_citations", lambda work: [])
    assert publish(str(bundle), **ARGS, name="Ada Lovelace", out=str(tmp_path / "e")) == 0
    prov = json.loads((bundle / "provenance.json").read_text())
    assert prov["files"]["paper/paper.pdf"]["sha256"] == _sha(bundle / "paper" / "paper.pdf")
    [added] = [a for a in prov["amendments"] if a["path"] == "paper/paper.pdf"]
    assert added["sha256_before"] is None and added["kind"] == "stamp"
    assert not any(c.status == FAIL for c in _run_checks(bundle, online=False))


# ── 7, 8: the disclaimer follows the study's purpose ─────────────────────────


def _repl_bundle(tmp_path: Path) -> Path:
    from src.core.export.structured import export_paper
    from src.core.pipeline.reproduction import check_reproduction

    ws = tmp_path / "study" / "workspaces" / "ws"
    shutil.copytree(ROOT / "tests" / "fixtures" / "replication_demo", ws)
    (ws / "paper_draft.tex").write_text("\\documentclass{article}\\author{X}\\begin{document}R\\end{document}\n")
    assert check_reproduction(ws).passed
    b = export_paper(ws, tmp_path / "study" / "exports", date_str="20260930", template="replication")
    make_run_db(tmp_path / "study", paper_id_of(b), workspace=ws)
    return b


def test_a_changed_wording_replaces_the_disclaimer_and_no_purpose_removes_it(tmp_path: Path, monkeypatch):
    from src.core import demonstration as demo
    from src.core.demonstration import mark_report

    p = tmp_path / "r.md"
    p.write_text("\ufeff# Report\n")
    assert mark_report(p, "replication") and not mark_report(p, "replication")
    assert p.read_text().startswith("\ufeff<!-- e2er:disclaimer begin -->")
    monkeypatch.setitem(demo.DISCLAIMERS, "replication", "Demonstration. New wording.")
    assert mark_report(p, "replication")
    assert p.read_text().count("Demonstration.") == 1 and "New wording" in p.read_text()
    assert mark_report(p, "replication", purpose=None)
    assert p.read_text() == "\ufeff# Report\n"
    old = tmp_path / "old.md"
    old.write_text("> Demonstration. This reproduction was run as is (older wording).\n\n# Report\n")
    assert mark_report(old, "replication") and old.read_text().count("Demonstration.") == 1


def test_republishing_without_a_purpose_removes_the_disclaimer_everywhere(tmp_path: Path):
    b = _repl_bundle(tmp_path)
    report = b / "misc" / "reproduction_report.md"
    assert publish(str(b), **ARGS, demonstration=True, out=str(tmp_path / "e")) == 0
    assert disclaimer("replication") in report.read_text()
    assert disclaimer("replication") in (b / "paper" / "paper.tex").read_text()
    assert publish(str(b), **ARGS, out=str(tmp_path / "e")) == 0
    m = _manifest(b)
    assert "purpose" not in m and "purpose" not in m["dossier"]["doc"]
    assert "Demonstration." not in report.read_text()
    assert "Demonstration." not in (b / "paper" / "paper.tex").read_text()
    assert not any(c.status == FAIL for c in _run_checks(b, online=False))


def test_a_purpose_recorded_on_the_study_is_honoured_without_the_flag(tmp_path: Path):
    b = _repl_bundle(tmp_path)
    ws = tmp_path / "study" / "workspaces" / "ws"
    manifest = json.loads((ws / "manifest.json").read_text())
    (ws / "manifest.json").write_text(json.dumps({**manifest, "purpose": "demonstration"}))
    assert publish(str(b), **ARGS, out=str(tmp_path / "e")) == 0
    m = _manifest(b)
    assert m["purpose"] == "demonstration" and m["kind"] == "replication"


# ── 21: no local path reaches the dossier ────────────────────────────────────


def test_a_local_path_in_the_runs_record_stops_publish(bundle: Path, tmp_path: Path, capsys):
    import sqlite3

    db = make_run_db(tmp_path / "study", paper_id_of(bundle))
    con = sqlite3.connect(db)
    con.execute(
        "INSERT INTO pipeline_events VALUES "
        "('x', ?, 'researcher_action', 'review_draft', NULL, ?, '2026-09-11 11:00:00')",
        (paper_id_of(bundle), json.dumps({"action": "instruction", "text": "Use /private/var/folders/ab/data.csv"})),
    )
    con.commit()
    con.close()
    assert publish(str(bundle), **ARGS, out=str(tmp_path / "e")) == 1
    assert "names a path on this machine" in capsys.readouterr().out
    assert not (bundle / "e2er.json").exists()


# ── 24, 27: the dossier link without --name, and a footnote that does not overclaim ─


def test_without_a_name_the_paper_still_carries_the_dossier_link_and_keeps_its_author(bundle: Path, tmp_path: Path):
    make_run_db(tmp_path / "study", paper_id_of(bundle))
    tex = bundle / "paper" / "paper.tex"
    own = tex.read_text().split("\\author{", 1)[1].split("\\thanks", 1)[0]  # the paper's own author text
    assert publish(str(bundle), **ARGS, demonstration=True, out=str(tmp_path / "e")) == 0
    text = tex.read_text()
    m = _manifest(bundle)
    assert m["dossier"]["url"] in text and disclaimer() in text
    assert f"\\author{{{own}\\thanks{{This paper was produced with e2er" in text  # its author line, kept
    assert text.count("This paper was produced with e2er") == 1
    # unresolved pins (the run's commit is not in this checkout): the footnote does not claim exact versions
    assert "where E2ER's repository holds them" in text
    assert publish(str(bundle), **ARGS, demonstration=True, out=str(tmp_path / "e")) == 0
    assert tex.read_text() == text  # stamping again changes nothing


def test_deposits_hold_only_the_files_the_bundle_fingerprints(bundle: Path, tmp_path: Path, fake_zenodo):
    from src.cli_publish import _code_zip, _deposit_plan

    (bundle / "data" / ".DS_Store").write_bytes(b"\0\0\0\1Bud1")
    (bundle / "code" / "Thumbs.db").write_bytes(b"x")
    plan = _deposit_plan(bundle, {"data": {"access": "public"}, "code": {"access": "public"}}, "demo")
    assert ".DS_Store" not in [n for n, _ in plan["data"]["files"]]
    import io
    import zipfile

    names = zipfile.ZipFile(io.BytesIO(_code_zip(bundle))).namelist()
    assert names and "code/Thumbs.db" not in names


def test_long_text_is_clipped_to_the_sites_limit_in_utf16_units():
    from src.core.dossier import _clip

    clipped = _clip("😀" * 15000)
    assert len(clipped.encode("utf-16-le")) // 2 <= 20000


def test_a_recompile_with_non_fatal_errors_is_kept_as_the_run_compiled_it(bundle: Path, tmp_path: Path, monkeypatch):
    """The FOMC paper loads inputenc, which xetex rejects; the run compiled it with -Z continue-on-errors."""
    import subprocess

    make_run_db(tmp_path / "study", paper_id_of(bundle))
    seen: list[list[str]] = []

    def tectonic(cmd, cwd, **kw):
        seen.append(cmd)
        (Path(cwd) / "paper.pdf").write_bytes(b"%PDF with a non-fatal error")
        return subprocess.CompletedProcess(cmd, 1, "", "inputenc is not designed for xetex")

    monkeypatch.setattr("src.cli_publish.shutil.which", lambda _: "/usr/bin/tectonic")
    monkeypatch.setattr("src.cli_publish.subprocess.run", tectonic)
    monkeypatch.setattr("src.cli_publish.unresolved_citations", lambda work: [])
    assert publish(str(bundle), **ARGS, out=str(tmp_path / "e")) == 0
    assert "continue-on-errors" in seen[0]
    assert (bundle / "paper" / "paper.pdf").read_bytes() == b"%PDF with a non-fatal error"
