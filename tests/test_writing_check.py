"""The phrase check: constructions the researcher rejects, found in a draft and sent back with the sentences.

A template live run (2026-10-11) kept "Against this background" in its draft
although the researcher had told the writer not to use it. The check reads the
prose of the draft writers' output (paper drafter, section writer, abstract
writer, field review writer) and fails their output contract with the exact
sentences; `e2er verify` prints the same as a note that changes no verdict.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from src.cli_verify import verify
from src.core.specialists.contract_check import check_specialist_artifacts, read_contract_feedback
from src.core.writing_check import PHRASES, find

LIVE = (
    "Against this background, this paper asks how US bank stocks respond to Federal Reserve target-rate announcements."
)


def _phrases(tex: str) -> list[str]:
    return [h.phrase for h in find(tex)]


def test_the_live_phrase_is_found_with_its_sentence():
    (hit,) = find("Rates moved a lot in 2022. " + LIVE + " We use daily data.")
    assert hit.phrase == "Against this background"
    assert hit.sentence == LIVE
    assert "Against this backdrop" not in LIVE and _phrases("Against this backdrop, we ask.") == [
        "Against this background"
    ]


@pytest.mark.parametrize(
    ("sentence", "phrase"),
    [
        ("The effect reflects ETH prices rather than NFT demand.", "rather than"),
        ("The estimate is not a technicality but the difference between a null and a finding.", "not X but Y"),
        ("The closest analogue is not an index inclusion, but the financialization of commodities.", "not X but Y"),
        ("The ETF changed not only the investor base but also the trading hours.", "not only X but also Y"),
        ("We ask not just whether volatility fell, but whether it converged.", "not only X but also Y"),
        ("It is important to note that the sample ends in 2025.", "It is important to note"),
        ("It should be noted that the sample ends in 2025.", "It is important to note"),
        ("In this section, we describe the data.", "In this section, we"),
        ("We delve into the mechanism.", "delve"),
        ("The result is a testament to the design.", "a testament to"),
        ("Liquidity plays a crucial role in price discovery.", "plays a crucial role"),
        ("Investors navigate the complexities of the market.", "navigate the complexities"),
    ],
)
def test_each_construction_is_found(sentence: str, phrase: str):
    assert _phrases(sentence) == [phrase]


@pytest.mark.parametrize(
    "sentence",
    [
        # Concessions with a negated action are not the "not X but Y" construction.
        "We do not observe the holdings, but we infer them from the flows.",
        "The trust could not redeem shares, but it could issue them.",
        "The coefficient is not significant.",
        "Other than the halving, no event falls in the window.",
        "The interaction plays a role in the second stage.",
        "We cannot reject the null, but the sign matches the prediction.",
    ],
)
def test_ordinary_sentences_pass(sentence: str):
    assert find(sentence) == []


def test_quotations_citations_comments_and_maths_are_left_out():
    tex = r"""
\begin{quote}Against this background, the Fed acted rather than waited.\end{quote}
As \citet{x} write, ``it is important to note that rates matter''.
He called it "a testament to central banking".
% Against this background, a comment.
$\beta$ rather than $\gamma$ is in the table: \begin{tabular}{l} rather than \end{tabular}
\begin{equation} x = y \text{ rather than } z \end{equation}
"""
    assert _phrases(tex) == ["rather than"]  # only the sentence of prose with "$\beta$ rather than $\gamma$"


def test_more_than_two_em_dashes_on_a_page_are_a_chain():
    two = "The model---a market model---fits. " + "Word " * 100 + "Prices --- and yields --- moved."
    hits = find(two)
    assert [h.phrase for h in hits] == ["em-dash chain"]
    assert hits[0].sentence.startswith("4 em-dashes on one page: The model---a market model---fits.")
    assert find("The model---a market model---fits. " + "Word " * 600 + "Prices --- moved.") == []


def test_the_list_names_every_construction_checked():
    assert PHRASES == (
        "Against this background",
        "rather than",
        "not only X but also Y",
        "not X but Y",
        "It is important to note",
        "In this section, we",
        "delve",
        "a testament to",
        "plays a crucial role",
        "navigate the complexities",
        "em-dash chain",
    )


# ── the output contract of the draft writers ─────────────────────────────────


DRAFT = (
    r"""\documentclass{article}
\begin{document}
\section{Introduction}
"""
    + LIVE
    + r""" We use daily data from 2015 to 2025 and a market model for each announcement.
\section{Results}
The announcement-day returns of bank stocks are small and not distinguishable from zero in our sample.
\end{document}
"""
)


@pytest.mark.parametrize(
    ("specialist", "file"),
    [
        ("paper_drafter", "paper_draft.tex"),
        ("section_writer", "paper_draft.tex"),
        ("field_review_writer", "paper_draft.tex"),
        ("abstract_writer", "abstract.tex"),
    ],
)
def test_a_draft_writer_is_sent_back_with_the_sentence(tmp_path: Path, specialist: str, file: str):
    (tmp_path / file).write_text(DRAFT, encoding="utf-8", newline="\n")
    failed = [c for c in check_specialist_artifacts(tmp_path, specialist) if not c.ok]
    phrase = [c for c in failed if "construction" in c.reason]
    assert len(phrase) == 1 and phrase[0].artifact == file
    assert f'"Against this background" in: {LIVE}' in phrase[0].reason
    assert "Rewrite each of these sentences" in phrase[0].reason
    (tmp_path / file).write_text(DRAFT.replace("Against this background, this", "This"), encoding="utf-8", newline="\n")
    assert not [c for c in check_specialist_artifacts(tmp_path, specialist) if "construction" in c.reason]


def test_the_feedback_reaches_the_next_attempt(tmp_path: Path):
    """The dispatcher's attempt loop feeds the sentences into the writer's next prompt."""
    from src.core.specialists.contract_check import write_contract_feedback

    (tmp_path / "paper_draft.tex").write_text(DRAFT, encoding="utf-8", newline="\n")
    failures = [c for c in check_specialist_artifacts(tmp_path, "paper_drafter") if not c.ok]
    write_contract_feedback(tmp_path, "paper_drafter", "; ".join(f"{c.artifact}: {c.reason}" for c in failures))
    block = read_contract_feedback(tmp_path, "paper_drafter")
    assert block and LIVE in block and "OUTPUT-CONTRACT VIOLATION" in block


# ── e2er verify: a note, never a failed check ───────────────────────────────


def test_verify_notes_the_constructions_without_changing_the_verdict(tmp_path: Path, capsys):
    showcase = Path(__file__).resolve().parent.parent / "examples" / "showcase"
    b = tmp_path / "showcase"
    shutil.copytree(showcase, b)
    code = verify(str(b))
    out = capsys.readouterr().out
    assert "   note: " in out and "use a construction the writing guidance rejects" in out
    assert 'paper/paper.tex: "rather than" in:' in out
    assert code == 0  # the showcase verifies; the note changes nothing
    assert verify(str(b), json_output=True) == 0
    out = capsys.readouterr().out
    data = json.loads(out[out.index("{\n") :])  # after any log line
    assert data["verified"] is True
    assert any(n.startswith('paper/paper.tex: "rather than"') for n in data["writing_notes"])
