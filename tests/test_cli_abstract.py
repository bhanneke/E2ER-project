"""`e2er abstract <folder>`: a finished study's abstract written again by the abstract step (0.17.4).

The backend is a fake: it writes abstract.tex through the file tool, as a
specialist does. The PDF is "compiled" by a stand-in (no tectonic in tests).
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from src.cli_abstract import AbstractError, rewrite
from src.cli_verify import FAIL, PASS, _check_anchor, _run_checks
from src.core import abstract as ab
from src.modules.llm.base import LLMBackend, TokenUsage, ToolLoopResult

ROOT = Path(__file__).resolve().parents[1]
SHOWCASE = ROOT / "tests" / "fixtures" / "showcase_export"

GOOD = r"""\begin{abstract}
Spot Bitcoin ETFs opened Bitcoin to investors who hold it through a brokerage account. We ask whether their
approval made Bitcoin move more closely with US stocks. We compare Bitcoin with 9 cryptocurrencies that received no
US spot ETF, month by month, before and after the approval.
% src: summary_statistics.json#n_units
Bitcoin's co-movement with stocks changed by about as much as that of the comparison coins, while its volatility
relative to stocks fell. The approval changed who holds Bitcoin and left its link to the stock market where it was.

\noindent\textbf{Keywords:} Bitcoin; exchange-traded funds; co-movement
\end{abstract}
"""


class FakeWriter(LLMBackend):
    """Writes the given abstracts, one per call, through the file tool."""

    def __init__(self, *texts: str) -> None:
        self.texts = list(texts)
        self.calls = 0
        self.prompts: list[str] = []

    async def tool_loop(self, system, messages, tools, tool_handler, max_turns=30, *, paper_id=None, specialist=None):
        from src.home import find_workspace

        self.calls += 1
        self.prompts.append(str(messages[0]["content"]))
        # A CLI backend runs in the workspace it finds by the paper id: the scratch workspace.
        self.cwd = find_workspace(paper_id or "")
        assert (self.cwd / "paper_draft.tex").is_file(), self.cwd
        text = self.texts[min(self.calls, len(self.texts)) - 1]
        await tool_handler.handle("write_file", {"path": "abstract.tex", "content": text})
        return ToolLoopResult(success=True, output="written", tool_calls_made=1, usage=TokenUsage(1, 1))


def _fake_pdf(bundle: Path) -> None:
    tex = (bundle / "paper" / "paper.tex").read_bytes()
    (bundle / "paper" / "paper.pdf").write_bytes(b"%PDF-fake " + hashlib.sha256(tex).hexdigest().encode())


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr("src.cli_publish.shutil.which", lambda _: None)


@pytest.fixture
def bundle(tmp_path: Path) -> Path:
    dst = tmp_path / "study" / "exports" / "showcase"
    shutil.copytree(SHOWCASE, dst)
    return dst


def _snapshot(b: Path) -> dict[str, bytes]:
    return {p.relative_to(b).as_posix(): p.read_bytes() for p in b.rglob("*") if p.is_file()}


def _run(bundle: Path, writer: FakeWriter, **kw):
    return rewrite(
        bundle,
        backend="claude_code",
        model="fake-model",
        backend_factory=lambda n, m: writer,
        compile_pdf=_fake_pdf,
        say=lambda _s: None,
        **kw,
    )


def test_the_abstract_goes_into_paper_pdf_and_provenance(bundle: Path):
    prov_before = (bundle / "provenance.json").read_text()
    old_tex = (bundle / "paper" / "paper.tex").read_bytes()
    writer = FakeWriter(GOOD)
    out = _run(bundle, writer)
    assert writer.calls == 1
    assert out["numbers"] == ["9"] and out["new_words"] < 160 and out["old_words"] == 197
    # The writer read the final paper and the headline entries.
    assert "## The final paper (paper_draft.tex)" in writer.prompts[0]
    assert "## Headline result entries" in writer.prompts[0]

    paper = (bundle / "paper" / "paper.tex").read_text()
    assert "Spot Bitcoin ETFs opened Bitcoin to investors" in paper and paper.count("\\begin{abstract}") == 1
    abstract = (bundle / "paper" / "abstract.tex").read_text()
    assert abstract.startswith("\\title{No Cash Flows, New Owners:")  # the study's title stays where it was read
    assert (bundle / "paper" / "paper.pdf").read_bytes().startswith(b"%PDF-fake")

    prov = json.loads((bundle / "provenance.json").read_text())
    mine = [a for a in prov["amendments"] if a.get("kind") == ab.AMENDMENT_KIND]
    assert {a["path"] for a in mine} == {"paper/abstract.tex", "paper/paper.tex", "paper/paper.pdf"}
    tex_entry = next(a for a in mine if a["path"] == "paper/paper.tex")
    assert tex_entry["sha256_before"] == hashlib.sha256(old_tex).hexdigest()
    assert tex_entry["sha256_after"] == hashlib.sha256((bundle / "paper" / "paper.tex").read_bytes()).hexdigest()
    assert (
        tex_entry["model"] == "fake-model" and tex_entry["e2er_version"] and tex_entry["reason"] == ab.AMENDMENT_REASON
    )
    # e2er verify passes; rolled back, provenance.json is exactly the exported one.
    checks = _run_checks(bundle, False)
    assert not [c for c in checks if c.status == FAIL], [(c.name, c.detail) for c in checks if c.status == FAIL]
    from src.core.redact import provenance_before_redactions

    texts, n = provenance_before_redactions(bundle)
    assert n == 3 and prov_before in texts


def test_an_abstract_that_fails_twice_changes_nothing(bundle: Path):
    before = _snapshot(bundle)
    bad = (
        "\\begin{abstract}\nWe ask about ETFs. The estimate is $-0.018$ (p = 0.4). "
        "The study makes no causal claim.\n\\end{abstract}"
    )
    writer = FakeWriter(bad)
    with pytest.raises(AbstractError, match="failed its check after 2 attempt"):
        _run(bundle, writer)
    assert writer.calls == 2  # one resend, no more
    assert "Sent back by the abstract check" in writer.prompts[1]
    assert _snapshot(bundle) == before


def test_a_number_that_is_no_result_is_refused(bundle: Path):
    before = _snapshot(bundle)
    invented = GOOD.replace("with 9 cryptocurrencies", "with 9.137 cryptocurrencies")
    with pytest.raises(AbstractError, match="9.137 is no value of the study's results"):
        _run(bundle, FakeWriter(invented))
    assert _snapshot(bundle) == before


def test_a_resend_that_passes_is_used(bundle: Path):
    too_many = GOOD.replace("We ask whether", "Across 10 funds, 11 approvals and 80 percent of flows, we ask whether")
    writer = FakeWriter(too_many, GOOD)
    out = _run(bundle, writer)
    assert writer.calls == 2 and out["attempts"] == 2


def test_an_edited_folder_is_refused(bundle: Path):
    (bundle / "paper" / "refs.bib").write_text("edited")
    with pytest.raises(AbstractError, match="not what was exported"):
        _run(bundle, FakeWriter(GOOD))


def test_a_failed_compile_puts_everything_back(bundle: Path):
    from src.cli_publish import PublishError

    before = _snapshot(bundle)

    def broken(_b: Path) -> None:
        raise PublishError("tectonic failed")

    with pytest.raises(AbstractError, match="could not be recompiled"):
        rewrite(
            bundle, backend="claude_code", model="m", backend_factory=lambda n, m: FakeWriter(GOOD), compile_pdf=broken
        )
    assert _snapshot(bundle) == before


def test_after_a_publish_the_anchor_holds_and_publish_puts_the_amendments_in_the_dossier(
    bundle: Path, tmp_path: Path, monkeypatch
):
    from src.cli_publish import publish
    from src.db import client
    from tests.run_db import make_run_db, paper_id_of

    real = client._sqlite_path
    monkeypatch.setattr(client, "_sqlite_path", lambda url: str(tmp_path / "home.db") if not url else real(url))
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    make_run_db(tmp_path / "study", paper_id_of(bundle))
    args = dict(owner="bhanneke", project="demo", github="bhanneke", commit="abc1234", data="private", code="private")
    assert publish(str(bundle), **args, out=str(tmp_path / "e"), yes=True) == 0
    assert _check_anchor(bundle).status == PASS

    _run(bundle, FakeWriter(GOOD))
    anchor = _check_anchor(bundle)
    assert anchor.status == PASS and "abstract was rewritten" in anchor.detail

    assert publish(str(bundle), **args, out=str(tmp_path / "e2"), yes=True) == 0
    doc = json.loads((bundle / "e2er.json").read_text())["dossier"]["doc"]
    kinds = [a.get("kind") for a in doc.get("amendments") or []]
    assert kinds.count(ab.AMENDMENT_KIND) == 3


def test_the_command_line_entry(bundle: Path, monkeypatch, capsys):
    from src.cli_abstract import abstract

    writer = FakeWriter(GOOD)
    monkeypatch.setattr("src.modules.llm.registry.get_backend", lambda settings, name=None, model=None: writer)
    monkeypatch.setattr("src.cli_publish.recompile_paper", _fake_pdf)
    assert abstract(str(bundle), backend="claude_code", model="m") == 0
    out = capsys.readouterr().out
    assert "Abstract check passed on attempt 1" in out and "abstract_rewritten" in out
