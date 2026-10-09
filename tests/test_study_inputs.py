"""Choosing the data files and papers a study uses (0.15.0, pillar "bring your own data and papers").

Before 0.15.0 every study got everything in the data folder and the literature
folder, New study offered no choice, and the entries of a .bib file or a Zotero
library were shown to the writers as citable without ever being written into
the study's bibliography. These tests pin the new path end to end: what New
study lists, what a choice stages, what the planning check and the prompts
see, what literature.bib holds (with which keys and which source tags), what
the run page, the finish page and the dossier show, and `e2er run --data/--papers`.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from src.api.app import app
from src.core import study_inputs as si
from src.modules.literature.models import PaperMetadata
from tests.test_browser_setup import live_db  # noqa: F401 — the fixture
from tests.test_corpus_cli import minimal_pdf

BASE = "http://127.0.0.1:8290"
BIB = """@article{Bernanke:2005,
  title = {What Explains the Stock Market's Reaction to {Federal Reserve} Policy?},
  author = {Bernanke, Ben S. and Kuttner, Kenneth N.},
  journal = {Journal of Finance},
  year = {2005},
  volume = {60},
  pages = {1221--1257},
}

@article{Unchosen:2010,
  title = {A Paper Nobody Chose},
  author = {Nobody, N.},
  year = {2010},
}
"""


def _client() -> TestClient:
    return TestClient(app, base_url=BASE, client=("127.0.0.1", 50000))


def _settings(tmp_path: Path, **kw):
    base = {
        "local_data_dir": None,
        "local_data_dir_recursive": False,
        "literature_dir": None,
        "literature_bibtex_file": None,
        "literature_max_ingest": 500,
        "literature_acquire_limit": 0,
        "zotero_api_key": None,
        "zotero_user_id": None,
        "zotero_group_id": None,
        "workspace_root": str(tmp_path / "workspaces"),
        **kw,
    }
    ns = SimpleNamespace(**base)
    ns.resolved_literature_dirs = lambda: base["literature_dir"] or base["local_data_dir"]
    return ns


def _pdf(path: Path, title: str, doi: str = "") -> Path:
    body = f"{title}\nAnn Author\n" + (f"doi:{doi}\n" if doi else "") + "Published 2021.\n" + "Text. " * 40
    path.write_bytes(minimal_pdf(body))
    return path


@pytest.fixture(autouse=True)
def _own_home(tmp_path, monkeypatch):
    """Uploads and the PDF title cache go to ~/.e2er: a home of the test's own."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))


# ── what New study lists ────────────────────────────────────────────────────


def test_the_data_list_holds_only_the_files_e2er_reads(tmp_path: Path):
    data = tmp_path / "data"
    (data / "e2er_papers" / "old").mkdir(parents=True)
    for name in ("b.csv", "a.parquet", "notes.txt", "raw.json", ".hidden.csv"):
        (data / name).write_text("x\n1\n")
    (data / "e2er_papers" / "old" / "export.csv").write_text("x\n")
    opts = si.data_options(_settings(tmp_path, local_data_dir=str(data)))
    assert [o.name for o in opts] == ["a.parquet", "b.csv"]
    assert opts[1].kind == "CSV" and opts[1].size == 4 and Path(opts[1].path).is_absolute()


def test_the_paper_list_holds_pdfs_bib_entries_and_the_library(tmp_path: Path, monkeypatch):
    lit = tmp_path / "lit"
    lit.mkdir()
    _pdf(lit / "one.pdf", "Monetary Policy Surprises and Bank Stocks")
    (lit / "refs.bib").write_text(BIB)
    monkeypatch.setattr(
        si,
        "_library_options",
        lambda: [si.PaperOption("library:k1", "From the Library", [], 2020, "library", "Library")],
    )
    opts = si.paper_options(_settings(tmp_path, literature_dir=str(lit)))
    kinds = {o.kind: o for o in opts}
    assert kinds["pdf"].title.startswith("Monetary Policy Surprises")
    assert {o.id.rsplit("#", 1)[-1] for o in opts if o.kind == "bib"} == {"Bernanke:2005", "Unchosen:2010"}
    assert kinds["library"].id == "library:k1"
    # The PDF's title is read once and kept (New study opens fast the next time).
    assert (Path.home() / ".e2er" / "pdf_metadata_cache.json").is_file()


def test_new_study_ticks_the_folder_and_offers_the_library_unticked(tmp_path: Path, monkeypatch):
    from src.api.inputs import paper_choices

    monkeypatch.setattr(
        si,
        "paper_options",
        lambda s: [
            si.PaperOption("pdf:/x/a.pdf", "A", ["Ann Author"], 2020, "pdf", "a.pdf"),
            si.PaperOption("library:k", "L", [], 2021, "library", "Library"),
        ],
    )
    view = paper_choices(_settings(tmp_path), None)
    assert [p["ticked"] for p in view["papers"]] == [True, False]
    assert [p["ticked"] for p in paper_choices(_settings(tmp_path), ["library:k"])["papers"]] == [False, True]


# ── checking a choice ───────────────────────────────────────────────────────


def test_a_file_e2er_cannot_read_is_refused_in_one_sentence(tmp_path: Path):
    (tmp_path / "notes.txt").write_text("x")
    with pytest.raises(si.InputError, match=r"^notes.txt is not a data file e2er can read. Use .csv, .tsv"):
        si.check_data_files([str(tmp_path / "notes.txt")])
    with pytest.raises(si.InputError, match="does not exist"):
        si.check_data_files([str(tmp_path / "gone.csv")])
    with pytest.raises(si.InputError, match="not a full path"):
        si.check_data_files(["prices.csv"])
    with pytest.raises(si.InputError, match="not a paper e2er can read"):
        si.check_paper_ids([str(tmp_path / "notes.txt")])


def test_paths_become_paper_ids(tmp_path: Path):
    pdf = _pdf(tmp_path / "p.pdf", "Some Paper Title Here")
    bib = tmp_path / "r.bib"
    bib.write_text(BIB)
    assert si.check_paper_ids([str(pdf), str(bib), "library:abc"]) == [
        f"pdf:{pdf.resolve()}",
        f"bibfile:{bib.resolve()}",
        "library:abc",
    ]


# ── starting a study ────────────────────────────────────────────────────────


def _start(c: TestClient, **body) -> dict:
    r = c.post(
        "/api/papers",
        json={
            "title": "T",
            "research_question": "Do FOMC surprises move bank stocks?",
            "mode": "single_pass",
            "acknowledge_unproven_tuple": True,
            **body,
        },
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_only_the_chosen_data_files_reach_the_study_and_its_planning_check(live_db, monkeypatch):  # noqa: F811
    from src.core.specialists.data_sources import available_sources, check_declared_sources

    data = live_db / "data"
    data.mkdir()
    for name in ("prices.csv", "dates.csv", "unrelated.csv"):
        (data / name).write_text("date,x\n2020-01-02,1\n")
    monkeypatch.setenv("LOCAL_DATA_DIR", str(data))
    from src.config import get_settings

    get_settings.cache_clear()
    with _client() as c:
        ws = Path(_start(c, data_files=[str(data / "prices.csv"), str(data / "dates.csv")])["workspace"])
    staged = sorted(p.name for p in (ws / "data").iterdir())
    assert staged == ["dates.csv", "prices.csv"]
    record = json.loads((ws / si.INPUTS_FILE).read_text())
    assert record["data"]["chosen"] is True
    assert {f["name"]: f["origin"] for f in record["data"]["files"]} == {"prices.csv": "folder", "dates.csv": "folder"}
    assert json.loads((ws / "manifest.json").read_text())["datasets"] == ["prices.csv", "dates.csv"]
    assert available_sources(ws, get_settings()).files == ("dates.csv", "prices.csv")
    (ws / "data_dictionary.json").write_text(
        json.dumps({"tables": [{"name": "unrelated", "source": "file", "file": "unrelated.csv"}]})
    )
    [check] = check_declared_sources(ws, get_settings())
    assert not check.ok and "no file 'unrelated.csv' among the study's data files" in check.reason


def test_without_a_choice_the_study_takes_the_whole_data_folder_as_before(live_db, monkeypatch):  # noqa: F811
    data = live_db / "data"
    data.mkdir()
    (data / "a.csv").write_text("x\n1\n")
    (data / "b.csv").write_text("x\n1\n")
    monkeypatch.setenv("LOCAL_DATA_DIR", str(data))
    from src.config import get_settings

    get_settings.cache_clear()
    with _client() as c:
        ws = Path(_start(c)["workspace"])
    assert sorted(p.name for p in (ws / "data").iterdir()) == ["a.csv", "b.csv"]
    record = json.loads((ws / si.INPUTS_FILE).read_text())
    assert record["data"]["chosen"] is False and len(record["data"]["files"]) == 2
    assert record["papers"] == {"chosen": False, "web_search": True, "requested": []}


def test_a_refused_choice_starts_nothing(live_db):  # noqa: F811
    bad = live_db / "notes.txt"
    bad.write_text("x")
    with _client() as c:
        r = c.post(
            "/api/papers",
            json={
                "title": "T",
                "research_question": "Q?",
                "acknowledge_unproven_tuple": True,
                "data_files": [str(bad)],
            },
        )
        assert r.status_code == 422 and "notes.txt is not a data file e2er can read" in r.json()["detail"]
        assert c.get("/api/papers").json() in ([], {"papers": []}) or not any(
            p.get("title") == "T" for p in (c.get("/api/papers").json() or [])
        )
    assert not (live_db / "workspaces").exists() or not any((live_db / "workspaces").iterdir())


def test_the_new_study_form_sends_the_ticks_and_the_added_files(live_db, monkeypatch):  # noqa: F811
    data = live_db / "data"
    data.mkdir()
    (data / "prices.csv").write_text("date,p\n2020-01-02,1\n")
    (data / "other.csv").write_text("date,p\n2020-01-02,1\n")
    monkeypatch.setenv("LOCAL_DATA_DIR", str(data))
    from src.config import get_settings

    get_settings.cache_clear()
    with _client() as c:
        page = c.get("/papers/new").text
        assert 'name="data_file"' in page and "prices.csv" in page and "Add files" in page
        assert 'name="only_my_papers"' in page and 'hx-get="/htmx/new/papers"' in page
        r = c.post(
            "/papers",
            data={
                "research_question": "Do FOMC surprises move bank stocks?",
                "pipeline": "empirical",
                "data_choice": "1",
                "data_file": [str(data / "prices.csv")],
                "paper_choice": "1",
                "only_my_papers": "1",
            },
            files=[
                ("data_upload", ("added.csv", b"date,v\n2020-01-02,3\n", "text/csv")),
                ("paper_upload", ("mine.bib", BIB.encode(), "application/x-bibtex")),
                (
                    "paper_upload",
                    ("paper.pdf", minimal_pdf("A Paper Added On The Form\nAnn Author\n"), "application/pdf"),
                ),
            ],
            follow_redirects=False,
        )
        assert r.status_code == 303, r.text
        pid = r.headers["location"].rsplit("/", 1)[1]
        ws = Path(c.get(f"/api/papers/{pid}").json()["workspace"])
    assert sorted(p.name for p in (ws / "data").iterdir()) == ["added.csv", "prices.csv"]
    assert not (ws / "data" / "added.csv").is_symlink(), "an added file is copied: its waiting folder is removed"
    record = json.loads((ws / si.INPUTS_FILE).read_text())
    assert {f["name"]: f["origin"] for f in record["data"]["files"]} == {"prices.csv": "folder", "added.csv": "upload"}
    assert record["papers"]["chosen"] is True and record["papers"]["web_search"] is False
    assert sorted(Path(x.split(":", 1)[1]).name for x in record["papers"]["requested"]) == ["mine.bib", "paper.pdf"]
    assert all(str(ws.resolve()) in x for x in record["papers"]["requested"]), "the copies in the study"
    assert not any((Path.home() / ".e2er" / "uploads").iterdir())


def test_a_file_of_the_wrong_type_added_on_the_form_is_refused_there(live_db):  # noqa: F811
    with _client() as c:
        r = c.post(
            "/papers",
            data={"research_question": "Q?", "data_choice": "1"},
            files=[("data_upload", ("notes.txt", b"x", "text/plain"))],
        )
    assert r.status_code == 422
    assert "notes.txt is not a data file e2er can read" in r.text and "Nothing was started" in r.text
    assert "Q?" in r.text


# ── the papers: literature.bib, keys, tags ──────────────────────────────────


def _prepare(ws: Path, settings, record: dict, acquire=None) -> None:
    si.write_record(ws, record)
    with (
        patch("src.modules.literature.discovery.acquire_literature", new=acquire or AsyncMock(return_value=0)),
        patch("src.modules.literature.storage.store_paper", new=AsyncMock()),
        patch("src.modules.literature.discovery._enrich_one", new=AsyncMock(side_effect=lambda m: m)),
    ):
        asyncio.run(si.prepare_papers(ws, "pid", settings, ["q"]))


def test_exactly_the_chosen_papers_are_written_with_the_keys_the_prompts_show(tmp_path: Path):
    from src.core.pipeline.verify_citations import load_bib
    from src.core.specialists.base import _load_reference_summary, _workspace_bib_for_prompt

    lit = tmp_path / "lit"
    lit.mkdir()
    pdf = _pdf(lit / "surprises.pdf", "Monetary Policy Surprises and Bank Stocks", doi="10.1234/mps.2021")
    _pdf(lit / "skip.pdf", "A PDF The Researcher Did Not Tick")
    (lit / "refs.bib").write_text(BIB)
    ws = tmp_path / "ws"
    ws.mkdir()
    acquire = AsyncMock(return_value=0)
    _prepare(
        ws,
        _settings(tmp_path, literature_dir=str(lit)),
        {
            "papers": {
                "chosen": True,
                "web_search": False,
                "requested": [f"pdf:{pdf}", f"bib:{(lit / 'refs.bib').resolve()}#Bernanke:2005"],
            }
        },
        acquire,
    )
    bib = load_bib(ws / "literature.bib")
    assert set(bib) == {"Bernanke:2005", "unknown2021monetary"}
    assert all(f["e2er_source"] == "researcher" for f in bib.values())
    assert bib["Bernanke:2005"]["pages"] == "1221--1257", "the researcher's entry keeps its fields"
    assert (ws / "literature" / "surprises.pdf").exists() and not (ws / "literature" / "skip.pdf").exists()
    record = si.read_record(ws)["papers"]
    assert {i["key"]: i["kind"] for i in record["items"]} == {"Bernanke:2005": "bib", "unknown2021monetary": "pdf"}
    # The web search is told the choice: off, and limited to the chosen papers.
    assert acquire.await_args.kwargs["web_search"] is False and len(acquire.await_args.kwargs["chosen"]) == 2
    with (
        patch("src.home.find_workspace", return_value=ws),
        patch("src.config.get_settings", return_value=_settings(tmp_path)),
    ):
        shown = _load_reference_summary("paper_drafter", "pid") + _workspace_bib_for_prompt("paper_drafter", "pid")
    for key in bib:
        assert f"\\cite{{{key}}}" in shown
    assert "Unchosen" not in shown and "[PDF: literature/surprises.pdf]" in shown


def test_the_same_paper_as_pdf_and_bib_entry_is_one_entry_with_the_researchers_key(tmp_path: Path):
    pdf = PaperMetadata(
        title="Same Paper",
        authors=["A B"],
        year=2005,
        doi="10.1/x",
        source="byod_pdf",
        raw={"source_pdf": "/x/same.pdf"},
    )
    entry = PaperMetadata(
        title="Same Paper", authors=["A B"], year=2005, doi="10.1/X", source="bibtex", cite_key="AB:2005"
    )
    [kept] = si.dedupe([entry, pdf])
    assert kept.bibtex_key == "AB:2005" and kept.raw["source_pdf"] == "/x/same.pdf"


def test_two_papers_with_one_derived_key_get_their_own(tmp_path: Path):
    a = PaperMetadata(title="Markets today", authors=["Ann Smith"], year=2020)
    b = PaperMetadata(title="Markets tomorrow", authors=["Bob Smith"], year=2020)
    si.unique_keys([a, b])
    assert (a.bibtex_key, b.bibtex_key) == ("smith2020markets", "smith2020marketsb")


def test_chosen_library_papers_bring_their_claims_and_only_mine_drops_the_rest(tmp_path: Path):
    from src.modules.literature.corpus import ClaimHit, PaperRow
    from src.modules.literature.corpus_context import CorpusEvidence, with_chosen

    def row(k, t):
        return PaperRow(k, "", t, ["A"], 2020, "byod_pdf", 1)

    ev = CorpusEvidence(
        hits=[
            ClaimHit("key_findings", "x", "q1", "", "k1", "Chosen PDF Paper", 2020, ""),
            ClaimHit("key_findings", "y", "q2", "", "k2", "Not Chosen", 2020, ""),
        ],
        papers={"k1": row("k1", "Chosen PDF Paper"), "k2": row("k2", "Not Chosen")},
        queries=["q"],
    )
    chosen = [PaperMetadata(title="Chosen PDF Paper", source="byod_pdf")]
    assert set(with_chosen(ev, chosen, only=False).papers) == {"k1", "k2"}
    only = with_chosen(ev, chosen, only=True)
    assert set(only.papers) == {"k1"} and [h.key for h in only.hits] == ["k1"]


# ── what the pages show ─────────────────────────────────────────────────────


def _workspace_with_inputs(ws: Path) -> None:
    import sqlite3

    ws.mkdir(parents=True, exist_ok=True)
    si.write_record(
        ws,
        {
            "data": {"chosen": True, "files": [{"name": "prices.csv", "origin": "upload", "size": 2048}]},
            "papers": {
                "chosen": True,
                "web_search": True,
                "items": [{"key": "Bernanke:2005", "title": "What Explains", "kind": "bib", "origin": "folder"}],
            },
        },
    )
    mine = PaperMetadata(
        title="What Explains", authors=["Ben Bernanke"], year=2005, source="bibtex", cite_key="Bernanke:2005"
    )
    web = PaperMetadata(title="Found Online", authors=["Bo Web"], year=2021, source="openalex")
    (ws / "literature.bib").write_text(mine.to_bibtex() + "\n\n" + web.to_bibtex() + "\n")
    (ws / "paper_draft.tex").write_text("As \\citet{Bernanke:2005} and \\citep{web2021found} show.")
    con = sqlite3.connect(ws / "data.db")
    con.execute("CREATE TABLE prices (d TEXT)")
    con.executemany("INSERT INTO prices VALUES (?)", [("a",), ("b",)])
    con.commit()
    con.close()
    (ws / "data_sources.json").write_text(
        json.dumps(
            {
                "loads": [
                    {
                        "connector": "data-folder",
                        "dataset": "Added by the researcher for this study",
                        "series": "prices.csv",
                        "table": "prices",
                        "files": [{"path": "data/prices.csv", "sha256": "a" * 64}],
                    }
                ]
            }
        )
    )


def test_the_run_panel_and_the_finish_card_say_what_the_study_used(tmp_path: Path):
    from src.api.inputs import inputs_view

    ws = tmp_path / "ws"
    _workspace_with_inputs(ws)
    v = inputs_view(ws)
    assert v["files"] == [{"name": "prices.csv", "origin": "added for this study", "size": 2048}]
    assert v["tables"] == [{"table": "prices", "rows": 2, "source": "your data file (prices.csv)"}]
    assert [p["key"] for p in v["mine"]] == ["Bernanke:2005"] and v["mine"][0]["kind"] == ".bib entry"
    assert [p["key"] for p in v["web"]] == ["web2021found"]
    assert [(r["key"], r["source"]) for r in v["references"]] == [
        ("Bernanke:2005", "from your papers"),
        ("web2021found", "found on the web"),
    ]
    assert v["loads"][0]["uploaded"] is True


def test_the_dossier_lists_each_cited_reference_with_its_source(tmp_path: Path):
    from src.core.dossier import _references

    bundle = tmp_path / "bundle"
    (bundle / "paper").mkdir(parents=True)
    ws = tmp_path / "ws"
    _workspace_with_inputs(ws)
    (bundle / "paper" / "refs.bib").write_text((ws / "literature.bib").read_text())
    (bundle / "paper" / "paper.tex").write_text((ws / "paper_draft.tex").read_text())
    assert _references(bundle) == [
        {"key": "Bernanke:2005", "title": "What Explains", "source": "researcher", "year": "2005"},
        {"key": "web2021found", "title": "Found Online", "source": "web", "year": "2021"},
    ]
    # A study exported before 0.15.0 (no tags): no references, so its dossier and address stay the same.
    (bundle / "paper" / "refs.bib").write_text("@article{old2020, title={Old}, year={2020}}\n")
    assert _references(bundle) == []


def test_an_uploaded_file_is_recorded_as_added_for_this_study(tmp_path: Path):
    from src.modules.data.byod_import import _import_corpus_sync

    ws = tmp_path / "ws"
    (ws / "data").mkdir(parents=True)
    (ws / "data" / "added.csv").write_text("a,b\n1,2\n")
    (ws / "data" / "folder.csv").write_text("a,b\n1,2\n")
    si.write_record(
        ws,
        {
            "data": {
                "chosen": True,
                "files": [{"name": "added.csv", "origin": "upload"}, {"name": "folder.csv", "origin": "folder"}],
            }
        },
    )
    _import_corpus_sync(ws, 1000)
    loads = {x["series"]: x["dataset"] for x in json.loads((ws / "data_sources.json").read_text())["loads"]}
    assert loads == {
        "added.csv": "Added by the researcher for this study",
        "folder.csv": "The researcher's data folder",
    }


# ── e2er run --data / --papers ──────────────────────────────────────────────


def test_e2er_run_resolves_files_and_folders(tmp_path: Path, monkeypatch):
    from src.cli_run import resolve_inputs

    (tmp_path / "prices.csv").write_text("x\n")
    lit = tmp_path / "lit"
    lit.mkdir()
    _pdf(lit / "a.pdf", "A Paper Title For The Test")
    (lit / "refs.bib").write_text(BIB)
    monkeypatch.chdir(tmp_path)
    data, papers = resolve_inputs(["prices.csv"], [str(lit)])
    assert data == [str((tmp_path / "prices.csv").resolve())]
    assert papers == [f"pdf:{(lit / 'a.pdf').resolve()}", f"bibfile:{(lit / 'refs.bib').resolve()}"]
    assert resolve_inputs(None, None) == (None, None)
    with pytest.raises(ValueError, match="notes.txt is not a data file"):
        (tmp_path / "notes.txt").write_text("x")
        resolve_inputs(["notes.txt"], None)


def test_e2er_run_has_the_options():
    import subprocess
    import sys

    out = subprocess.run([sys.executable, "-m", "src", "run", "--help"], capture_output=True, text=True).stdout
    assert "--data" in out and "--papers" in out and "--only-my-papers" in out


# ── the Library page: Add papers ────────────────────────────────────────────


def test_add_papers_on_the_library_page_uses_the_library_importer(tmp_path: Path, monkeypatch):
    import time

    from src.api import inputs

    seen: list[str] = []

    async def fake_target(target, *, limit, search):
        seen.append(target)
        return [PaperMetadata(title="P")]

    async def fake_ingest(conn, papers, *, skip_known, on_event):
        on_event("stored", "P", "")

    monkeypatch.setattr("src.modules.literature.ingest.papers_for_target", fake_target)
    monkeypatch.setattr("src.modules.literature.ingest.ingest_papers", fake_ingest)
    monkeypatch.setattr("src.modules.literature.corpus.corpus_path", lambda explicit=None: tmp_path / "c.db")
    inputs._ADDING.clear()
    folder = tmp_path / "papers"
    folder.mkdir()
    with _client() as c:
        r = c.post("/library/add", data={"folder": str(folder)}, follow_redirects=False)
        assert r.status_code == 303 and "Reading the PDFs" in r.headers["location"].replace("+", " ")
        for _ in range(50):
            if inputs._ADDING.get("finished"):
                break
            time.sleep(0.05)
        assert seen == [str(folder)] and inputs._ADDING["stored"] == 1
        assert "1 new" in c.get("/htmx/library/adding").text
        r = c.post("/library/add", files=[("pdf", ("x.txt", b"x", "text/plain"))], follow_redirects=False)
        assert "x.txt is not a PDF" in r.headers["location"].replace("+", " ")


# ── a paper that cites must compile with its bibliography ───────────────────


def test_a_whole_paper_that_cites_without_a_bibliography_line_gets_one():
    """Found by E2E-28: a drafter's complete document cited the researcher's papers but had no
    \\bibliography line, so the run's PDF and the published one printed "?" for every citation."""
    from src.core.bibliography import add_missing_bibliography
    from src.core.renderer.templates import assemble_document

    tex = "\\documentclass{article}\n\\usepackage{natbib}\n\\begin{document}\nAs \\citet{a} show.\n\\end{document}\n"
    fixed = assemble_document(tex)
    assert fixed.endswith("\\bibliographystyle{plainnat}\n\\bibliography{refs}\n\\end{document}\n")
    assert add_missing_bibliography(fixed) == fixed
    plain = "\\documentclass{article}\n\\begin{document}\nNo citations.\n\\end{document}\n"
    assert assemble_document(plain) == plain


def test_e2ers_own_markers_never_reach_the_bibliography(tmp_path: Path):
    bib = tmp_path / "r.bib"
    bib.write_text(BIB)
    resolved = si.resolve_papers([f"bib:{bib}#Bernanke:2005"], tmp_path)
    text = resolved.items[0].to_bibtex()
    assert "e2er_origin" not in text and "e2er_id" not in text and str(tmp_path) not in text
    assert "e2er_source = {researcher}" in text and "pages = {1221--1257}" in text


def test_the_record_of_the_choice_stays_out_of_the_exported_folder(tmp_path: Path):
    """Found by E2E-05 and E2E-28: the record names files on this computer by their full paths, and an
    exported folder that carried it (misc/) put them on e2er.org. A dot file is never exported."""
    from src.core.export.structured import export_paper

    ws = tmp_path / "ws"
    _workspace_with_inputs(ws)
    (ws / "manifest.json").write_text(json.dumps({"title": "T", "paper_id": "p"}))
    assert si.INPUTS_FILE.startswith(".")
    out = export_paper(ws, tmp_path / "exports", date_str="20261010")
    assert not [p for p in out.rglob("*") if "study_inputs" in p.name]
