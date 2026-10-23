"""Double-blind review: the anonymiser's rules, the leak check, and publish/pack/verify/unblind --blind.

The platform is faked (httpx.MockTransport, as conftest requires); nothing reaches a real one. git, the
computer's user and host name and PDF reading are replaced, so the tests see the fixture author only.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import shutil
import zipfile
from pathlib import Path

import httpx
import pytest

from src import cli_blind
from src.cli_publish import publish
from src.cli_verify import _fetch_published, _redaction_problems, _run_checks
from src.core import anonymise as an
from src.core import platform_client as pc
from src.core.export.provenance import files_at_export
from tests.run_db import make_run_db, paper_id_of
from tests.test_platform_cli import SHOWCASE, snapshot

URL = "https://platform.test"
NAME = "Imogen Quärry"
EMAIL = "imogen.quarry@uni-x.example"
HANDLE = "iquarry"
GITHUB = "iq-lab"
ORCID = "0000-0002-1825-0097"
AFFIL = "Quarry Institute of Data"
USER = "imogenq"
HOST = "imogens-laptop"
#: Every form of the fixture author's identity a page, request or file must never hold.
NEEDLES = ["Quärry", "Quarry", "Quaerry", "imogen.quarry", "iquarry", "iq-lab", "0000-0002-1825-0097", "1825-0097",
           "Quarry Institute", "/Users/imogenq", "imogens-laptop", "uni-x.example"]  # fmt: skip

ME = {
    "id": "user-1",
    "name": NAME,
    "email": EMAIL,
    "scopes": ["publish", "read:own"],
    "handles": [HANDLE],
    "study": None,
    "profile": {"name": NAME, "github": GITHUB, "orcid": ORCID, "affiliations": [AFFIL]},
}


def ids() -> list[an.Identifier]:
    return an.collect(ME, local=False)


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def rehash(folder: Path, rels: list[str]) -> None:
    """A file planted in an exported folder, as export would have listed it."""
    prov = json.loads((folder / "provenance.json").read_text(encoding="utf-8"))
    for rel in rels:
        data = (folder / rel).read_bytes()
        prov["files"][rel] = {"sha256": _sha(data), "bytes": len(data)}
    (folder / "provenance.json").write_text(json.dumps(prov, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def drop(folder: Path, rel: str) -> None:
    (folder / rel).unlink()
    prov = json.loads((folder / "provenance.json").read_text(encoding="utf-8"))
    prov["files"].pop(rel, None)
    (folder / "provenance.json").write_text(json.dumps(prov, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def mini(tmp_path: Path) -> Path:
    """A small exported folder: provenance.json lists every file."""
    b = tmp_path / "mini"
    (b / "paper").mkdir(parents=True)
    (b / "design").mkdir()
    (b / "code").mkdir()
    (b / "paper" / "paper.tex").write_text(
        "\\documentclass{article}\n\\title{A Test}\n"
        f"\\author{{{NAME}\\thanks{{{AFFIL}, \\email{{{EMAIL}}}}}}}\n"
        "\\begin{document}\n\\maketitle\nText \\citet{quarry2024} shows it.\n"
        "\\section*{Acknowledgements}\nWe thank the Quarry family foundation.\n\\bibliography{refs}\n\\end{document}\n",
        encoding="utf-8",
    )
    (b / "paper" / "refs.bib").write_text(
        '@article{quarry2024,\n  author = {Qu{\\"a}rry, Imogen and Smith, Ann},\n  title = {Earlier},\n'
        "  year = {2024}\n}\n@article{other2020,\n  author = {Doe, Jane},\n  title = {Other},\n  year = {2020}\n}\n",
        encoding="utf-8",
    )
    (b / "design" / "paper_plan.md").write_text(
        f"# Plan\nContact: {EMAIL.replace('@', ' [at] ')}\nORCID {ORCID.replace('-', ' ')}\n", encoding="utf-8"
    )
    (b / "code" / "run.py").write_text(
        f"DATA = '/Users/{USER}/projects/x.csv'  # by @{HANDLE}\nprint('ok')\n", encoding="utf-8"
    )
    (b / "README.md").write_text("# A Test\n\n**Research question:** Does it work?\n", encoding="utf-8")
    prov = {"schema": "e2er-provenance/1", "run": {"paper_id": "p-1"}, "files": {}}
    (b / "provenance.json").write_text(json.dumps(prov), encoding="utf-8")
    rehash(b, ["paper/paper.tex", "paper/refs.bib", "design/paper_plan.md", "code/run.py", "README.md"])
    return b


# ── what identifies the author ───────────────────────────────────────────────


def test_collect_takes_the_account_profile_and_what_the_author_adds(monkeypatch):
    found = an.collect(ME, local=False, extra=["Ann Smith"], environ={"E2ER_AFFILIATION": "Lab X; Lab Y"})
    kinds = {(i.kind, i.value) for i in found}
    assert ("name", NAME) in kinds and ("email", EMAIL) in kinds and ("email-user", "imogen.quarry") in kinds
    assert ("handle", HANDLE) in kinds and ("github", GITHUB) in kinds and ("orcid", ORCID) in kinds
    assert ("affiliation", AFFIL) in kinds and ("affiliation", "Lab Y") in kinds and ("extra", "Ann Smith") in kinds


def test_collect_reads_this_computer_and_leaves_out_generic_names(monkeypatch, tmp_path):
    monkeypatch.setattr(an, "_git", lambda args, cwd=None: ["Imogen Quärry"] if "user.name" in args else [])
    monkeypatch.setattr(an.getpass, "getuser", lambda: "runner")
    monkeypatch.setattr(an.socket, "gethostname", lambda: "imogens-laptop.local")
    found = an.collect(None, environ={"HOME": "/Users/imogenq"})
    kinds = {(i.kind, i.value) for i in found}
    assert ("name", "Imogen Quärry") in kinds and ("user", "imogenq") in kinds
    assert ("host", "imogens-laptop") in kinds
    assert not any(i.value == "runner" for i in found)
    monkeypatch.setattr(an.socket, "gethostname", lambda: "MacBook-Pro.local")
    assert not any(i.kind == "host" for i in an.collect(None, environ={"HOME": "/tmp/x"}))


def test_a_handle_that_is_the_surname_reads_as_a_name():
    me = {**ME, "handles": ["quärry"]}
    assert any(i.kind == "name" and i.value == "quärry" for i in an.collect(me, local=False))


# ── every form an identifier can take ────────────────────────────────────────


@pytest.mark.parametrize(
    "text, kind",
    [
        ("by Imogen Quärry et al", "name"),
        ("IMOGEN QUÄRRY", "name"),
        ("Quärry, Imogen", "name"),
        ("Quarry, Imogen", "name"),
        ("Imogen Quaerry", "name"),
        ("I. Quärry", "name"),
        ("Quärry, I.", "name"),
        ("Imogen\n   Quärry", "name"),
        ("Imogen~Quärry", "name"),
        ("Imogen Qua-\nrry", "name"),
        ('Imogen Qu\\"{a}rry', "name"),
        ('Imogen Qu{\\"a}rry', "name"),
        ("Imogen Qu&auml;rry", "name"),
        ("Imogen Qu&#228;rry", "name"),
        ("Imogen Qu\\u00e4rry", "name"),
        ("Imogen%20Qu%C3%A4rry", "name"),
        ("Imogen+Qu%c3%a4rry", "name"),
        ("Imogen Qua\u0308rry", "name"),
        ("imogen.quarry@uni-x.example", "email"),
        ("IMOGEN.QUARRY@UNI-X.EXAMPLE", "email"),
        ("imogen.quarry [at] uni-x [dot] example", "email"),
        ("imogen.quarry at uni-x dot example", "email"),
        ("imogen.quarry%40uni-x.example", "email"),
        ("imogen.quarry(at)uni-x.example", "email"),
        ("0000-0002-1825-0097", "orcid"),
        ("0000 0002 1825 0097", "orcid"),
        ("0000000218250097", "orcid"),
        ("https://orcid.org/0000-0002-1825-0097", "orcid"),
        ("github.com/iq-lab/data", "github"),
        ("@iquarry wrote", "handle"),
        ("Quarry Institute of Data", "affiliation"),
        ("Quarry%20Institute%20of%20Data", "affiliation"),
        ("/Users/imogenq/data.csv", "home"),
        ("/home/imogenq/x", "home"),
        ("C:\\Users\\imogenq\\x", "home"),
        ('"C:\\\\Users\\\\imogenq\\\\x"', "home"),
        ("C:/Users/imogenq/x", "home"),
    ],
)
def test_the_patterns_find_every_form(text, kind):
    hits = an.Patterns(ids()).find(text)
    assert any(h[2].kind == kind for h in hits), (text, [h[2].kind for h in hits])


@pytest.mark.parametrize(
    "text",
    [
        "xiquarry and iquarryx",
        "Imogen alone",
        "https://github.com/bhanneke/E2ER-project/blob/abc/pipelines/empirical.toml",
        "/Users/Shared/data",
        "C:\\Users\\Public\\x",
        "0000-0002-1825-00970",
    ],
)
def test_the_patterns_leave_other_text_alone(text):
    assert an.Patterns(ids()).find(text) == []


def test_a_name_in_a_citation_counts_as_a_citation():
    i = an.Identifier("name", NAME, "t")
    pats = an.Patterns([i])
    for rel, text in [
        ("paper/refs.bib", "author = {Quärry, Imogen}"),
        ("paper/paper.pdf", "Imogen Quärry (2024) shows"),
        ("paper/paper.pdf", "as in Quärry, Imogen, 2024"),
        ("paper/paper.tex", "\\citet{x, Imogen Quärry}"),
    ]:
        (s, e, who), *_ = pats.find(text)
        assert an.is_citation(rel, text, s, e, who), (rel, text)
    text = "Body text.\nReferences\nQuärry, Imogen. A paper. Journal."
    (s, e, who), *_ = pats.find(text)
    assert an.is_citation("paper.pdf", text, s, e, who, an.references_start(text))
    text = "This study was written by Imogen Quärry alone."
    (s, e, who), *_ = pats.find(text)
    assert not an.is_citation("paper/paper.tex", text, s, e, who)
    email = an.Identifier("email", EMAIL, "t")
    text = f"author = {{{EMAIL}}}"
    (s, e, who), *_ = an.Patterns([email]).find(text)
    assert not an.is_citation("paper/refs.bib", text, s, e, who)  # an e-mail address is never a citation


# ── the LaTeX blocks ─────────────────────────────────────────────────────────


def test_the_author_affiliation_and_acknowledgements_go():
    tex = (
        "\\title{T}\n\\author{A B\\thanks{Univ X}\\and C D}\n\\affiliation{Univ X}\n\\email{a@x.org}\n"
        "\\begin{document}\nBody.\n\\section*{Acknowledgments}\nWe thank Z.\n\\section{Next}\nMore.\n"
        "\\begin{acknowledgements}\nThanks Y.\n\\end{acknowledgements}\n\\end{document}\n"
    )
    blocks = an.latex_blocks(tex)
    out, at = [], 0
    for s, e, rep, _rule in blocks:
        out += [tex[at:s], rep]
        at = e
    new = "".join(out) + tex[at:]
    assert "\\author{Anonymous author(s)}" in new and "Univ X" not in new and "a@x.org" not in new
    assert "We thank Z." not in new and "Thanks Y." not in new and "Removed for double-blind review." in new
    assert "\\section{Next}\nMore." in new and "Body." in new


# ── anonymising a folder ─────────────────────────────────────────────────────


def test_anonymise_records_each_change_without_the_text_or_the_old_fingerprint(tmp_path):
    b = mini(tmp_path)
    before = json.loads((b / "provenance.json").read_text(encoding="utf-8"))["files"]
    (b / "e2er.json").write_text("{}", encoding="utf-8")  # an earlier publish's record: not part of the study
    (b / ".e2er").mkdir()
    (b / ".e2er" / "link.json").write_text("{}", encoding="utf-8")
    result = an.anonymise(b, ids())
    assert "e2er.json" in result.removed and not (b / ".e2er").exists()
    prov = json.loads((b / "provenance.json").read_text(encoding="utf-8"))
    changed = {a["path"]: a for a in prov["amendments"]}
    assert set(changed) == {"paper/paper.tex", "design/paper_plan.md", "code/run.py"}
    for rel, a in changed.items():
        assert a["kind"] == "anonymised" and a["sha256_before"] is None
        assert a["anonymisation"]["count"] >= 1 and "withheld" in a["anonymisation"]["fingerprint_before"]
        assert an.record_problem(a, (b / rel).read_bytes()) is None
        assert prov["files"][rel]["sha256"] == _sha((b / rel).read_bytes())
    assert result.withheld == {before[r]["sha256"] for r in changed}
    raw = (b / "provenance.json").read_text(encoding="utf-8")
    for needle in ("Quärry", "imogen.quarry", "imogenq", "1825"):
        assert needle not in raw
    tex = (b / "paper" / "paper.tex").read_text(encoding="utf-8")
    assert "\\author{Anonymous author(s)}" in tex and "Quarry family" not in tex
    assert "\\citet{quarry2024}" in tex  # a citation stays; self_citations lists it
    assert (b / "paper" / "refs.bib").read_text(encoding="utf-8").count('Qu{\\"a}rry') == 1  # the bibliography stays
    assert "~/projects/x.csv" in (b / "code" / "run.py").read_text(encoding="utf-8")
    assert "[anonymised]" in (b / "code" / "run.py").read_text(encoding="utf-8")
    assert _redaction_problems(b, prov) == []
    # A record that does not match the file is named.
    bad = dict(changed["code/run.py"])
    bad["anonymisation"] = {**bad["anonymisation"], "replacements": [{"text": "[anonymised]", "offsets": [0]}]}
    assert "does not match" in str(an.record_problem(bad, (b / "code" / "run.py").read_bytes()))


def test_files_at_export_counts_an_anonymised_file_as_anonymised(tmp_path):
    b = mini(tmp_path)
    an.anonymise(b, ids())
    prov = json.loads((b / "provenance.json").read_text(encoding="utf-8"))
    at_export = files_at_export(prov)
    assert at_export["code/run.py"]["sha256"] == prov["files"]["code/run.py"]["sha256"]
    assert set(at_export) == set(prov["files"])


def test_a_binary_file_that_names_the_author_is_named(tmp_path):
    b = mini(tmp_path)
    (b / "data").mkdir()
    (b / "data" / "x.db").write_bytes(b"SQLite format 3\x00" + "author: Imogen Quärry".encode() + b"\x00" * 10)
    rehash(b, ["data/x.db"])
    assert an.anonymise(b, ids()).binary == ["data/x.db"]


def test_a_pre_registered_plan_keeps_its_fingerprint_and_still_verifies(tmp_path):
    from src.cli_verify import _only_redacted

    b = mini(tmp_path)
    plan = b / "design" / "paper_plan.md"
    frozen = _sha(plan.read_bytes())
    (b / "design" / "preregistration.md").write_text("# Pre-registration\n", encoding="utf-8")
    lock = {"file": "preregistration.md", "sha256": _sha((b / "design" / "preregistration.md").read_bytes()),
            "frozen_at": "2026-10-01T00:00:00Z", "plan_files": {"paper_plan.md": frozen}}  # fmt: skip
    (b / "design" / "preregistration.lock.json").write_text(json.dumps(lock), encoding="utf-8")
    rehash(b, ["design/preregistration.md", "design/preregistration.lock.json"])
    result = an.anonymise(b, ids())
    assert result.prereg == ["design/paper_plan.md"] and frozen not in result.withheld
    prov = json.loads((b / "provenance.json").read_text(encoding="utf-8"))
    a = next(x for x in prov["amendments"] if x["path"] == "design/paper_plan.md")
    assert a["sha256_before"] == frozen
    d = {"file": "paper_plan.md", "sha256_frozen": frozen, "sha256_now": _sha(plan.read_bytes()), "approved": False}
    assert _only_redacted(b, d)


def test_withhold_takes_the_old_fingerprints_out_of_the_dossier():
    h = "a" * 64
    doc = {"workflow": [{"output": {"file": "x", "sha256": f"sha256:{h}"}}, {"sha256": h}], "keep": "b" * 64}
    assert an.withhold(doc, {h}) == {"workflow": [{"output": {"file": "x", "sha256": None}}, {"sha256": None}],
                                     "keep": "b" * 64}  # fmt: skip


# ── the leak check ───────────────────────────────────────────────────────────


def test_the_leak_check_passes_an_anonymised_folder_and_lists_the_citations(tmp_path):
    b = mini(tmp_path)
    an.anonymise(b, ids())
    report = an.leak_check(b, ids(), pdf=lambda p: "")
    assert report.clean, [str(f) for f in report.leaks]
    assert any(f.where == "paper/refs.bib" for f in report.citations)


@pytest.mark.parametrize(
    "content",
    [
        "Imogen\nQuärry",
        "imogen.quarry%40uni-x.example",
        "Imogen%20Qu%C3%A4rry",
        "0000 0002 1825 0097",
        "see C:\\Users\\imogenq\\data",
        "Qu&auml;rry, Imogen",
    ],
)
def test_the_leak_check_finds_split_and_encoded_forms(tmp_path, content):
    (tmp_path / "f.txt").write_text(f"line one\n{content}\n", encoding="utf-8")
    report = an.leak_check(tmp_path, ids())
    assert [str(f) for f in report.leaks] and report.leaks[0].where == "f.txt" and report.leaks[0].line == 2


def test_the_leak_check_reads_pdfs_archives_and_texts(tmp_path):
    (tmp_path / "fig.pdf").write_bytes(b"%PDF-1.4 compressed")
    report = an.leak_check(tmp_path, ids(), pdf=lambda p: "Figure 1\nby Imogen Quärry\n")
    assert [str(f) for f in report.leaks] == [
        "fig.pdf:2: your name (e2er.org account)",
    ]
    # A PDF whose metadata is not compressed: found in its bytes too.
    (tmp_path / "fig.pdf").write_bytes(b"%PDF-1.4 /Author (imogen.quarry@uni-x.example)")
    assert any("bytes" in f.what for f in an.leak_check(tmp_path, ids(), pdf=lambda p: "").leaks)
    # Without pdftotext a PDF is not readable: refused as well.
    assert not an.leak_check(tmp_path, ids(), pdf=lambda p: None).clean
    (tmp_path / "fig.pdf").unlink()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("inner/notes.md", "written by @iquarry\n")
    report = an.leak_check(
        None, ids(), files={"study.e2er": buf.getvalue(), "x.json.gz": gzip.compress(b'{"a": "iq-lab"}')}
    )
    assert {f.where for f in report.leaks} == {"study.e2er!inner/notes.md", "x.json"}
    report = an.leak_check(None, ids(), texts={"the request": json.dumps({"x": "Imogen Qu\u00e4rry"})})
    assert report.leaks and report.leaks[0].where.startswith("the request")


def test_a_compressed_data_file_is_named_as_unread(tmp_path):
    (tmp_path / "d.parquet").write_bytes(b"PAR1\x00\x01\x02")
    assert [f.where for f in an.leak_check(tmp_path, ids()).unread] == ["d.parquet"]


def test_self_citations_are_listed(tmp_path):
    b = mini(tmp_path)
    (b / "paper" / "intro.tex").write_text(
        "As we showed in earlier work, and in our previous paper, X.\n", encoding="utf-8"
    )
    found = [str(f) for f in an.self_citations(b, ids())]
    assert any(f.startswith("paper/refs.bib:1: @article{quarry2024}") for f in found)
    assert not any("other2020" in f for f in found)
    assert any("cites quarry2024" in f for f in found)
    assert any('"in our previous"' in f for f in found) and any('we showed in"' in f for f in found)


# ── publish --blind, pack --blind, verify --against, --unblind ────────────────


class BlindPlatform:
    def __init__(self, me: dict | None = None):
        self.me = me or ME
        self.requests: list[tuple[str, str, dict]] = []
        self.blind: dict | None = None

    def __call__(self, req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content) if req.content else {}
        self.requests.append((req.method, req.url.path, body))
        p = req.url.path
        if p == "/api/v1/me":
            return httpx.Response(200, json=self.me)
        if p == "/api/v1/blind" and req.method == "POST":
            self.blind = body
            code = body["blind"]["code"]
            return httpx.Response(201, json={"code": code, "url": f"{URL}/r/{code}", "state": "published",
                                             "version": 1, "existing": False})  # fmt: skip
        if p.startswith("/api/v1/blind/") and p.endswith("/unblind"):
            return httpx.Response(201, json={"id": "iquarry/study", "owner_project": "iquarry/study", "version": 1,
                                             "study_url": f"{URL}/iquarry/study"})  # fmt: skip
        if p.startswith("/api/v1/blind/") and self.blind:
            m = self.blind["manifest"]
            v = {"number": 1, "content_id": m["content_id"], "dossier_id": self.blind["dossier"]["id"]}
            return httpx.Response(200, json={"id": m["id"], "state": "published", "latest": v, "versions": [v]})
        return httpx.Response(404, json={"error": "not found"})


@pytest.fixture
def platform(monkeypatch, tmp_path) -> BlindPlatform:
    fake = BlindPlatform()
    monkeypatch.setattr(
        pc, "client_factory", lambda url: httpx.Client(base_url=url, transport=httpx.MockTransport(fake))
    )
    monkeypatch.setenv("E2ER_TOKEN", "e2er_" + "B" * 43)
    return fake


@pytest.fixture(autouse=True)
def quiet_computer(monkeypatch, tmp_path):
    """This computer, as the fixture author's: no real git identity, user, host name, tectonic or pdftotext."""
    monkeypatch.setattr(an, "_git", lambda args, cwd=None: [])
    monkeypatch.setattr(an.getpass, "getuser", lambda: USER)
    monkeypatch.setattr(an.socket, "gethostname", lambda: f"{HOST}.local")
    home = tmp_path / "Users" / USER
    home.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("src.cli_publish.shutil.which", lambda _: None)
    monkeypatch.setattr(an, "pdf_text", lambda p: "")
    monkeypatch.delenv("E2ER_BLIND_IDENTIFIERS", raising=False)
    monkeypatch.delenv("E2ER_AFFILIATION", raising=False)


@pytest.fixture
def study(tmp_path) -> Path:
    """The showcase export with the fixture author's identity planted, and no paper.pdf (no tectonic here)."""
    b = tmp_path / "exports" / "showcase"
    shutil.copytree(SHOWCASE, b)
    drop(b, "paper/paper.pdf")
    drop(b, "paper/tables/....tex")  # a name a package never carries (it starts with a dot)
    tex = b / "paper" / "paper.tex"
    tex.write_text(tex.read_text(encoding="utf-8").replace("Björn Hanneke", NAME), encoding="utf-8")
    plan = b / "design" / "paper_plan.md"
    plan.write_text(
        plan.read_text(encoding="utf-8") + f"\n\nContact {EMAIL}, ORCID {ORCID}, {AFFIL}.\n", encoding="utf-8"
    )
    code = b / "code" / "run_estimation.py"
    code.write_text(f"# data in /Users/{USER}/Desktop on {HOST}\n" + code.read_text(encoding="utf-8"), encoding="utf-8")
    rev = b / "reviews" / "review_data.md"
    rev.write_text(rev.read_text(encoding="utf-8") + f"\n\nAsk @{HANDLE} or github.com/{GITHUB}.\n", encoding="utf-8")
    rehash(b, ["paper/paper.tex", "design/paper_plan.md", "code/run_estimation.py", "reviews/review_data.md"])
    make_run_db(tmp_path / "exports", paper_id_of(b))
    return b


def blind(b: Path, **kw):
    return publish(str(b), to_url=URL, yes=True, interactive=False, blind=True, **kw)


def grep(text: str) -> list[str]:
    low = text.lower()
    return [n for n in NEEDLES if n.lower() in low]


def test_publish_blind_sends_an_anonymous_version_and_leaves_the_folder(study, platform, capsys):
    before = snapshot(study)
    assert blind(study) == 0, capsys.readouterr().out
    out = capsys.readouterr().out
    assert snapshot(study) == before
    body = platform.blind
    assert body is not None and [r[1] for r in platform.requests] == ["/api/v1/me", "/api/v1/blind"]
    code = body["blind"]["code"]
    assert len(code) == 32 and set(code) <= set("abcdefghijklmnopqrstuvwxyz234567")
    assert set(body["blind"]) == {"code"}
    m = body["manifest"]
    assert m["id"] == f"anonymous/{code}" and m["contributors"] == []
    assert "repository" not in m and "repository" not in body
    assert m["dossier"]["url"] == f"{URL}/r/{code}" and "access" not in m
    assert grep(json.dumps(body, ensure_ascii=False)) == [] and grep(json.dumps(body)) == []
    copy = cli_blind.copy_path(study, code)
    assert copy.is_dir() and cli_blind.anonymous_code(copy) == code
    assert f"{URL}/r/{code}" in out and "e2er pack --blind" in out
    for f in copy.rglob("*"):
        if f.is_file():
            assert grep(f.read_text(encoding="utf-8", errors="ignore")) == [], f
    tex = (copy / "paper" / "paper.tex").read_text(encoding="utf-8")
    assert "Anonymous author(s)" in tex and f"/r/{code}" in tex
    checks = {c.name: c.status for c in _run_checks(copy, online=False)}
    assert checks["integrity"] == "PASS" and checks["anchor"] == "PASS"


@pytest.mark.parametrize(
    "extra, word",
    [
        ({"github_repo": True}, "--github"),
        ({"zenodo": True}, "--zenodo"),
        ({"repo": "https://github.com/x/y"}, "--repo"),
        ({"commit": "abc1234"}, "--commit"),
        ({"data_url": "https://x.org/d"}, "--data-url"),
        ({"code_url": "https://x.org/c"}, "--code-url"),
        ({"paper_url": "https://x.org/p.pdf"}, "--paper-url"),
        ({"name": NAME}, "--name"),
        ({"orcid": ORCID}, "--orcid"),
        ({"coauthors": ["Ann|github=ann"]}, "--coauthor"),
        ({"paper": "public"}, "--paper public"),
        ({"stamp": False}, "--no-stamp"),
    ],
)
def test_options_that_would_name_the_author_are_refused(study, platform, capsys, extra, word):
    assert blind(study, **extra) == 2
    assert word in capsys.readouterr().out and platform.requests == []


def test_blind_needs_a_platform_and_a_personal_sign_in(study, platform, monkeypatch, capsys):
    assert publish(str(study), yes=True, interactive=False, blind=True) == 2
    assert "--to" in capsys.readouterr().out
    platform.me = {**ME, "study": "iquarry/x"}
    assert blind(study) == 1 and "personal login" in capsys.readouterr().out
    monkeypatch.delenv("E2ER_TOKEN")
    assert blind(study) == 1 and "not signed in" in capsys.readouterr().out
    assert platform.blind is None


def test_a_dry_run_sends_nothing_and_leaves_no_copy(study, platform, capsys):
    before = snapshot(study)
    assert publish(str(study), dry_run=True, blind=True, interactive=False) == 0
    out = capsys.readouterr().out
    assert '"manifest"' in out and platform.blind is None and snapshot(study) == before
    assert not list(study.parent.glob("showcase-anonymous-*"))


def test_an_identifier_left_where_it_cannot_be_taken_out_stops_the_publish(study, platform, monkeypatch, capsys):
    (study / "misc" / "extra.pdf").write_bytes(b"%PDF-1.4 x")
    rehash(study, ["misc/extra.pdf"])
    monkeypatch.setattr(an, "pdf_text", lambda p: "Made by Imogen Quärry" if p.stat().st_size == 10 else "")
    assert blind(study) == 1
    out = capsys.readouterr().out
    assert "misc/extra.pdf:1: your name" in out and "nothing was sent" in out
    assert platform.blind is None and not list(study.parent.glob("showcase-anonymous-*"))


def test_self_citations_need_the_authors_confirmation(study, platform, capsys):
    refs = study / "paper" / "refs.bib"
    refs.write_text(refs.read_text(encoding="utf-8") + "\n@article{quarry2023,\n  author = {Quärry, Imogen},\n"
                    "  title = {Before},\n  year = {2023}\n}\n", encoding="utf-8")  # fmt: skip
    rehash(study, ["paper/refs.bib"])
    assert blind(study) == 1
    out = capsys.readouterr().out
    assert "@article{quarry2023}" in out and "--blind-ack-self-citations" in out and platform.blind is None
    assert blind(study, blind_ack_self_citations=True) == 0
    assert "you confirmed these places" in capsys.readouterr().out


def test_a_platform_without_anonymous_versions_keeps_nothing(study, platform, monkeypatch, capsys):
    real = platform.__call__

    def old(req):
        return httpx.Response(404, json={"error": "Not found"}) if req.url.path == "/api/v1/blind" else real(req)

    monkeypatch.setattr(
        pc, "client_factory", lambda url: httpx.Client(base_url=url, transport=httpx.MockTransport(old))
    )
    assert blind(study) == 1
    assert "does not take anonymous versions" in capsys.readouterr().out
    assert not list(study.parent.glob("showcase-anonymous-*"))


def test_pack_blind_writes_the_file_for_the_journal_and_verify_against_r(study, platform, tmp_path, capsys):
    from src.cli_verify import verify

    assert blind(study) == 0
    code = platform.blind["blind"]["code"]
    out = tmp_path / "for-journal.e2er"
    assert cli_blind.pack_blind(str(study), str(out)) == 0, capsys.readouterr().out
    with zipfile.ZipFile(out) as zf:
        manifest = json.loads(zf.read("e2er-package.json"))
        assert manifest["study"]["authors"] == [] and manifest["study"]["folder"] == "anonymous"
        for name in zf.namelist():
            assert grep(zf.read(name).decode("utf-8", errors="ignore")) == [], name
    capsys.readouterr()
    assert _fetch_published(f"{URL}/r/{code}")[0] == "study"
    rc = verify(str(out), against=f"{URL}/r/{code}")
    text = capsys.readouterr().out
    assert "is version 1 of" in text, text
    assert rc == 0, text


def test_pack_blind_needs_an_anonymised_copy(study, capsys):
    assert cli_blind.pack_blind(str(study), None) == 1
    assert "publish it first" in capsys.readouterr().out


def test_unblind_asks_the_platform_for_a_version_with_authors(study, platform, capsys):
    assert blind(study) == 0
    code = platform.blind["blind"]["code"]
    copy = cli_blind.copy_path(study, code)
    rc = publish(str(copy), to_url=URL, yes=True, interactive=False, unblind=code, owner=HANDLE, project="study",
                 name=NAME, github=GITHUB, orcid=ORCID)  # fmt: skip
    assert rc == 0, capsys.readouterr().out
    method, path, body = platform.requests[-1]
    assert (method, path) == ("POST", f"/api/v1/blind/{code}/unblind")
    assert body["owner"] == HANDLE and body["project"] == "study" and body["contributors"][0]["orcid"] == ORCID
    assert "manifest" not in body
    platform.me = {**ME, "study": "iquarry/study"}
    assert publish(str(copy), to_url=URL, yes=True, interactive=False, unblind=code, owner=HANDLE, project="s") == 1
    assert "personal login" in capsys.readouterr().out


def test_unblind_needs_a_handle_and_a_name(study, platform, capsys):
    assert publish(str(study), to_url=URL, yes=True, interactive=False, unblind="a" * 32, owner="", project="") == 2
    assert publish(str(study), to_url=URL, yes=True, interactive=False, unblind="nope", owner="a", project="b") == 2


def test_the_command_line_has_the_flags():
    import subprocess
    import sys

    out = subprocess.run([sys.executable, "-m", "src", "publish", "--help"], capture_output=True, text=True).stdout
    assert "--blind" in out and "--blind-ack-self-citations" in out and "--unblind" in out
    out = subprocess.run([sys.executable, "-m", "src", "pack", "--help"], capture_output=True, text=True).stdout
    assert "--blind" in out


def test_an_anonymisation_record_with_an_empty_replacement_fails(tmp_path):
    """An empty replacement sits at every offset: it would vouch for any change (review 2026-10-23)."""
    b = mini(tmp_path)
    an.anonymise(b, ids())
    prov = json.loads((b / "provenance.json").read_text(encoding="utf-8"))
    a = next(x for x in prov["amendments"] if x["path"] == "code/run.py")
    data = (b / "code" / "run.py").read_bytes()
    assert "kept" in a["anonymisation"] and an.record_problem(a, data) is None
    empty = {**a, "anonymisation": {**a["anonymisation"], "replacements": [{"text": "", "offsets": [0]}], "count": 1}}
    assert "empty replacement" in str(an.record_problem(empty, data))
    # A change beside the replacements: the kept bytes are not the recorded ones.
    edited = data.replace(b"print", b"prinz", 1)
    assert "not the ones the change kept" in str(an.record_problem(a, edited))


def test_the_affiliation_and_thanks_blocks_are_replaced_never_deleted():
    tex = "\\title{T}\n\\thanks{Univ X}\n\\affiliation{Univ X}\n"
    assert all(rep for _s, _e, rep, _r in an.latex_blocks(tex))
