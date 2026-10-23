"""The abstract step (0.18.0): the check, putting the abstract into the paper, the step, the findings.

src/core/abstract.py. Up to 0.17.3 the abstract writer ran beside the drafter,
its abstract.tex never reached the PDF, and no check read it.
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import pytest

from src.core import abstract as ab

SKILL = Path(__file__).resolve().parents[1] / "skills" / "files" / "writing" / "abstract.md"

NFT = r"""\begin{abstract}
\noindent
The Halloween effect---systematically higher November--April returns relative to May--October---is the most
robust calendar anomaly in equity markets, persisting across countries and centuries. We test whether this anomaly
extends to non-fungible token (NFT) markets, which lack the institutional features commonly invoked to explain equity
seasonality while preserving behavioral channels that operate through retail investor psychology. Using 35.8 million
Ethereum-based NFT trades across eight platforms from 2017 to 2023, we find no statistically significant Halloween
effect in either USD- or ETH-denominated returns. Two-thirds of the raw seasonal differential in USD returns comes
from ETH price seasonality. Summer returns are twice as volatile as winter returns. Day-of-week effects, by contrast,
are highly significant, suggesting that shorter-horizon calendar patterns dominate seasonal ones. The absence of a
Halloween effect in a market without institutional investors, short selling, or exchange closures is consistent
with institutional mechanisms playing a necessary role in sustaining the equity anomaly.

\medskip
\noindent\textbf{Keywords:} calendar anomaly, seasonality, cryptocurrency, behavioral finance

\noindent\textbf{JEL Codes:} G12, G14, G41
\end{abstract}
"""

ROAD = r"""\begin{abstract}
Road traffic deaths are a major source of preventable mortality, and the reported burden differs sharply between
countries. We ask how the World Health Organization's estimated road traffic death rate varies across countries and
WHO regions in 2021. We describe the rate for 195 countries from the WHO Global Health Observatory and summarise it
by region.
% src: estimation_results.json#sample.n_observations
The median country records 12.3 deaths per 100,000 population, and the average rate of the African region is about
three times that of the European region.
% src: estimation_results.json#statistics.death_rate.median
WHO region membership accounts for 39 percent of the variation between countries.
% src: estimation_results.json#variance_decomposition.between_region_share
Because the rates are WHO model estimates, comparisons between countries inherit the assumptions of WHO's
estimation model.

\noindent\textbf{Keywords:} road traffic deaths; WHO regions; descriptive statistics
\end{abstract}
"""

ROAD_RESULTS = {
    "sample": {"n_observations": 195, "year": 2021},
    "statistics": {"death_rate": {"median": 12.3, "mean": 13.285}},
    "variance_decomposition": {"between_region_share": 0.3912052929456172},
}


def _env(text: str) -> str:
    return "\\begin{abstract}\n" + text + "\n\\end{abstract}\n"


def _problems(text: str, **kw) -> list[str]:
    return ab.check(_env(text), **kw).problems


# ── the check ────────────────────────────────────────────────────────────────


def test_the_two_worked_examples_pass():
    assert ab.check(NFT).passed, ab.check(NFT).problems
    flat = {f"estimation_results.json#{k}": v for k, v in _flatten(ROAD_RESULTS).items()}
    res = ab.check(ROAD, sources=flat, economics=False)
    assert res.passed, res.problems
    assert res.numbers == ["195", "12.3", "39"]  # 2021 and "per 100,000" are not counted


def _flatten(d, prefix=""):
    out = {}
    for k, v in d.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(_flatten(v, key))
        else:
            out[key] = float(v)
    return out


def test_the_skill_carries_both_examples_and_they_pass():
    """The examples in writing/abstract.md are the ones tested here, and pass the check as quoted there."""
    text = SKILL.read_text(encoding="utf-8")
    quotes = re.findall(r"((?:^> .*\n)+)", text, re.M)
    abstracts = [" ".join(line[2:] for line in q.splitlines()) for q in quotes]
    bodies = [a.split("Keywords:")[0] for a in abstracts if len(a.split()) > 80]
    assert len(bodies) == 2
    for body in bodies:
        res = ab.check(_env(body), economics=False)
        assert res.passed, res.problems
    assert "rather than" not in bodies[0]
    assert "Two-thirds of the raw seasonal differential in USD returns comes from ETH price seasonality." in bodies[0]


def test_too_many_words():
    long = "We find that enrolment rose sharply after the reform in every country we study. " * 13
    assert any("more than 160" in p for p in _problems(long))


@pytest.mark.parametrize(
    "sentence",
    [
        "Enrolment rose by a large amount (p < 0.01) after the reform.",
        "Enrolment rose sharply, with a p-value below conventional levels.",
        "Enrolment rose sharply, with a 95\\% confidence interval that excludes zero.",
        "Enrolment rose sharply, and the interval excludes zero.",
        "Enrolment rose sharply, with a standard error of about a fifth of the effect.",
        "Enrolment rose sharply after a Fisher-z transformation of the correlations.",
        "Enrolment rose sharply, with a t-statistic far above conventional thresholds.",
        "Enrolment rose sharply ($t = 4.1$).",
    ],
)
def test_no_statistics(sentence):
    probs = _problems(f"We ask whether fees matter for enrolment. {sentence} Fee abolition widened access to school.")
    assert any(p.startswith("it reports") for p in probs), probs


def test_plain_significance_words_are_allowed():
    probs = _problems(
        "We ask whether fees matter for enrolment. We find no statistically significant effect on completion, "
        "while enrolment rose sharply. Fee abolition widened access to school."
    )
    assert probs == []


def test_at_most_three_numbers_each_a_result():
    sources = {"r#a": 22.07, "r#b": 13.0, "r#c": 0.39, "r#d": 47}
    ok = _problems(
        "We ask whether fees matter. Enrolment rose by 22 percentage points and net enrolment by 13 points, "
        "and the reform reached 39 percent of children. Fee abolition widened access to school.",
        sources=sources,
    )
    assert ok == []
    four = _problems(
        "We ask whether fees matter in 47 countries. Enrolment rose by 22 percentage points and net enrolment by 13 "
        "points, and the reform reached 39 percent of children. Fee abolition widened access to school.",
        sources=sources,
    )
    assert any("4 numbers" in p for p in four)
    invented = _problems(
        "We ask whether fees matter. Enrolment rose by 25 percentage points. Fee abolition widened access to school.",
        sources=sources,
    )
    assert any("25 is no value of the study's results" in p for p in invented)


def test_years_rate_bases_names_and_sample_bounds_are_not_counted():
    nums = ab.counted_numbers(
        "Between 1994 and 2005, magnitude 5 and larger earthquakes in NUTS-2 regions and the S\\&P 500 killed "
        "12.3 people per 100,000 in COVID-19 times within 3 degrees of the centre."
    )
    assert [n for n, _v, _p in nums] == ["12.3"]
    # A minimum detectable effect is a result, whatever follows it.
    assert [n for n, _v, _p in ab.counted_numbers("The design could detect an increase of 0.148 or larger.")] == [
        "0.148"
    ]


def test_a_finding_is_required():
    probs = _problems(
        "We ask whether fees matter for enrolment. We use World Bank data on a panel of countries. "
        "We describe the design and the data in the paper."
    )
    assert "no sentence states what the study found" in probs


@pytest.mark.parametrize(
    "last",
    [
        "The study makes no causal claim.",
        "These are associations rather than effects.",
        "The data cannot separate physical change from catalogue change.",
    ],
)
def test_the_last_sentence(last):
    probs = _problems(f"We ask whether fees matter for enrolment. Enrolment rose sharply after the reform. {last}")
    assert any(p.startswith("the last sentence") for p in probs), probs


@pytest.mark.parametrize(
    ("sentence", "named"),
    [
        ("Enrolment rose rather than fell after the reform.", "'rather than'"),
        ("These are patterns in the catalogue, not in the planet population.", "'X, not Y'"),
        (
            "The approval changed who could hold Bitcoin and in what wrapper; it changed nothing about the asset.",
            "mirrored",
        ),
        ("It is important to note that enrolment rose sharply.", "It is important to note"),
    ],
)
def test_constructions_the_researcher_rejects(sentence, named):
    probs = _problems(f"We ask whether fees matter for enrolment. {sentence} Fee abolition widened access to school.")
    assert any(named in p for p in probs), probs


def test_jel_codes_outside_economics():
    tex = _env("We ask how rates vary. The rates rose sharply. Regions differ widely.\n\\textbf{JEL:} I18")
    assert any("JEL" in p for p in ab.check(tex, economics=False).problems)
    assert ab.check(tex, economics=True).passed


def test_the_showcase_abstract_fails_on_what_the_diagnosis_named():
    """The Bitcoin showcase's abstract.tex: too long, eight numbers, the mirrored clause, the negated ending."""
    tex = (Path(__file__).parent / "fixtures" / "showcase_export" / "paper" / "abstract.tex").read_text()
    probs = " | ".join(ab.check(tex).problems)
    for part in ("more than 160", "more than 3", "mirrored", "the last sentence"):
        assert part in probs


# ── into the paper ───────────────────────────────────────────────────────────


def test_insert_replaces_the_drafts_abstract_and_its_keywords():
    paper = (
        "\\title{T}\n\\maketitle\n\\begin{abstract}\nOld text.\n\\end{abstract}\n\n"
        "\\noindent\\textbf{Keywords:} old\n\n\\section{Introduction}\nBody.\n"
    )
    out = ab.insert(paper, ROAD)
    assert "Old text" not in out and "Keywords:} old" not in out
    assert out.count("\\begin{abstract}") == 1
    assert out.index("\\begin{abstract}") < out.index("\\section{Introduction}")
    assert "% src: estimation_results.json#sample.n_observations" in out


def test_insert_adds_an_abstract_where_the_draft_has_none():
    full = "\\documentclass{article}\n\\begin{document}\n\\maketitle\n\\section{Introduction}\nBody.\n\\end{document}"
    out = ab.insert(full, ROAD)
    assert out.index("\\maketitle") < out.index("\\begin{abstract}") < out.index("\\section{Introduction}")
    body = "\\title{T}\n\n\\section{Data}\nBody."
    out = ab.insert(body, "\\title{X}\n" + ROAD)
    assert out.index("\\begin{abstract}") < out.index("\\section{Data}")
    assert "\\title{X}" not in out  # the title stays out of the paper's body
    assert ab.insert(ab.insert(body, ROAD), ROAD) == ab.insert(body, ROAD)


def test_the_compiler_puts_abstract_tex_into_the_paper(tmp_path, monkeypatch):
    from src.core.renderer import compiler

    (tmp_path / "paper_draft.tex").write_text("\\title{T}\n\\section{Introduction}\nBody text.\n")
    (tmp_path / "abstract.tex").write_text(ROAD)
    monkeypatch.setattr(compiler, "_select_engine", lambda: None)
    asyncio.run(compiler.compile_latex(tmp_path))
    tex = (tmp_path / "paper_draft.tex").read_text()
    assert "The median country records 12.3 deaths" in tex
    assert tex.index("\\maketitle") < tex.index("\\begin{abstract}") < tex.index("\\section{Introduction}")


def test_report_shows_the_abstract_without_latex(tmp_path):
    from src.core.export.report import paper_abstract

    (tmp_path / "paper").mkdir()
    (tmp_path / "paper" / "abstract.tex").write_text("\\title{T}\n" + ROAD)
    text = paper_abstract(tmp_path)
    assert text.startswith("Road traffic deaths") and "src:" not in text and "Keywords" not in text
    (tmp_path / "paper" / "abstract.tex").unlink()
    (tmp_path / "paper" / "paper.tex").write_text("\\maketitle\n" + ROAD + "\\section{A}")
    assert paper_abstract(tmp_path) == text


def test_with_title_keeps_the_studys_title():
    assert ab.with_title(ROAD, "\\title{Road deaths}").startswith("\\title{Road deaths}\n\n\\begin{abstract}")
    assert ab.with_title("\\title{A}\n" + ROAD, "\\title{B}").startswith("\\title{A}")
    assert ab.title_command("\\title{A:\\\\ B}\n\\author{x}") == "\\title{A:\\\\ B}"


# ── what the writer reads ────────────────────────────────────────────────────


def test_headline_entries_are_the_values_the_paper_cites(tmp_path):
    (tmp_path / "estimation_results.json").write_text(
        json.dumps({"groups": {"g": [{"mean": 19.44}, {"mean": 6.7}]}, "sample": {"n": 195}})
    )
    paper = (
        "Text.\n% src: estimation_results.json#sample.n, groups.g.1.mean\nMore.\n% src: estimation_results.json#nope"
    )
    assert ab.headline_entries(paper, tmp_path) == [
        "estimation_results.json#sample.n = 195",
        "estimation_results.json#groups.g.1.mean = 6.7",
    ]


# ── the step ────────────────────────────────────────────────────────────────


def _workspace(tmp_path: Path) -> Path:
    (tmp_path / "estimation_results.json").write_text(json.dumps(ROAD_RESULTS))
    (tmp_path / "paper_draft.tex").write_text("\\title{T}\n\\section{Results}\nThe median is 12.3.\n")
    return tmp_path


def test_write_abstract_sends_the_writer_back_once_then_passes(tmp_path):
    ws = _workspace(tmp_path)
    bad = _env("We ask how rates vary. The median is 12.3 deaths (p < 0.01). The study makes no causal claim.")
    focuses: list[str] = []

    async def execute(focus: str) -> bool:
        focuses.append(focus)
        (ws / "abstract.tex").write_text(bad if len(focuses) == 1 else ROAD)
        return True

    out = asyncio.run(ab.write_abstract(ws, execute, economics=False))
    assert out.passed and out.attempts == 2
    assert "Sent back by the abstract check" in focuses[1] and "p-value" in focuses[1]
    record = json.loads((ws / ab.CHECK_FILE).read_text())
    assert record["passed"] and record["history"][0]["passed"] is False


def test_write_abstract_records_a_finding_after_the_second_failure(tmp_path):
    ws = _workspace(tmp_path)
    calls = []

    async def execute(focus: str) -> bool:
        calls.append(focus)
        (ws / "abstract.tex").write_text(_env("We ask how rates vary. The study makes no causal claim."))
        return True

    out = asyncio.run(ab.write_abstract(ws, execute, economics=False))
    assert not out.passed and len(calls) == 2  # one resend, no more
    record = json.loads((ws / ab.CHECK_FILE).read_text())
    assert record["passed"] is False and "finding" in record and record["problems"]


def test_write_abstract_without_enforcement_does_not_resend(tmp_path):
    ws = _workspace(tmp_path)
    calls = []

    async def execute(focus: str) -> bool:
        calls.append(focus)
        return False  # wrote nothing

    out = asyncio.run(ab.write_abstract(ws, execute, resend=False))
    assert not out.passed and len(calls) == 1
    assert any("no abstract.tex" in p for p in out.check.problems)


def test_the_writer_gets_the_paper_the_entries_and_the_reviewers_points(tmp_path):
    ws = _workspace(tmp_path)
    (ws / "paper_draft.tex").write_text(
        "\\section{R}\nThe median is 12.3.\n% src: estimation_results.json#sample.n_observations\n"
    )
    (ws / ab.FINDINGS_FILE).write_text(
        json.dumps(
            {
                "findings": [
                    {
                        "source": "review",
                        "source_detail": "writing_reviewer",
                        "problem": "The abstract buries the finding.",
                    }
                ]
            }
        )
    )
    ctx = ab.work_context(ws, "p1")
    assert "The median is 12.3." in ctx
    assert "estimation_results.json#sample.n_observations = 195" in ctx
    assert "(writing_reviewer) The abstract buries the finding." in ctx


# ── findings on the abstract, whatever the score ─────────────────────────────


def test_abstract_findings_ignore_the_score_floor(tmp_path):
    from src.core.strategist.findings import collect_abstract_findings, collect_review_findings
    from src.core.strategist.review_aggregator import parse_review_output

    review = (
        "# Writing Review\n\nThe paper reads well.\n\n- The abstract reports eight numbers and a p-value; "
        "it should state the finding in words.\n- The conclusion is fine.\n\n"
        "OVERALL SCORE: 8/10\nRECOMMENDATION: Accept\n"
    )
    (tmp_path / "review_writing.md").write_text(review)
    (tmp_path / "self_attack_report.json").write_text(
        json.dumps(
            {
                "findings": [
                    {
                        "severity": 6,
                        "category": "framing",
                        "description": "The abstract overclaims a causal effect.",
                        "suggested_fix": "Say association.",
                    }
                ]
            }
        )
    )
    score = parse_review_output("writing_reviewer", review)
    assert score is not None and collect_review_findings([score]) == []  # above the floor: no review finding
    found = collect_abstract_findings(tmp_path, ["writing_reviewer"])
    assert [f.source_detail for f in found] == ["writing_reviewer", "self_attack"]
    assert all(f.target == "abstract" for f in found)
    assert "eight numbers" in found[0].problem


def test_the_strategists_abstract_writer_is_left_out_and_the_step_is_in_the_templates():
    from src.core.pipeline.spec import find_spec

    for name in (
        "empirical",
        "empirical-preregistered",
        "event-study-finance",
        "policy-evaluation",
        "spatial-analysis",
        "descriptive-study",
        "text-analysis",
        "time-series-forecasting",
    ):
        spec = find_spec(name)
        names = [s.name for s in spec.steps]
        assert names.index("revision") < names.index("abstract"), name
        assert spec.step("abstract").run == ("abstract_writer",)
        for s in spec.steps:
            assert "abstract.tex" not in s.files  # the abstract is written after the draft review
    from src.core.strategist import engine

    assert '"abstract_writer"' not in engine._STRATEGIST_SYSTEM


def test_no_upstream_prompt_tells_a_specialist_what_to_state_in_the_abstract():
    """Only the abstract writer decides what the abstract says (idea developer, analysis, drafter: none)."""
    root = Path(__file__).resolve().parents[1]
    rx = re.compile(
        r"\b(?:state|report|say|mention|put|include|write|give|name|quote|present)\b[^.\n]{0,80}\bin\s+the\s+abstract\b",
        re.I,
    )
    allowed = {"writing/abstract.md", "writing/cite-numbers-by-source.md"}
    hits = []
    for path in [*(root / "skills" / "files").rglob("*.md"), *(root / "src").rglob("*.py")]:
        files = root / "skills" / "files"
        rel = path.relative_to(files).as_posix() if path.is_relative_to(files) else path.name
        if rel in allowed or path.name in ("abstract.py", "test_abstract_step.py"):
            continue
        for m in rx.finditer(path.read_text(encoding="utf-8", errors="replace")):
            hits.append(f"{rel}: {m.group(0)}")
    assert hits == []


# ── the step in the runner ───────────────────────────────────────────────────


def _runner(tmp_path: Path, backend, *, governance: str = "full", pipeline: str = "descriptive-study"):
    from src.core.strategist.runner import PipelineRunner

    return PipelineRunner(
        paper_id="p1",
        workspace=tmp_path,
        backend=backend,
        model="test-model",
        mode="single_pass",
        backend_name="claude_code",
        max_cost_usd=5.0,
        governance=governance,
        pipeline=pipeline,
    )


class _Writer:
    """A backend that writes the given abstracts, one per call."""

    def __init__(self, *texts: str) -> None:
        self.texts, self.calls = list(texts), 0

    async def tool_loop(self, system, messages, tools, tool_handler, max_turns=30, *, paper_id=None, specialist=None):
        from src.modules.llm.base import TokenUsage, ToolLoopResult

        self.calls += 1
        await tool_handler.handle(
            "write_file", {"path": "abstract.tex", "content": self.texts[min(self.calls, len(self.texts)) - 1]}
        )
        return ToolLoopResult(success=True, output="ok", tool_calls_made=1, usage=TokenUsage(1, 1))

    def identity(self):
        return {}


def _events(monkeypatch) -> list[tuple[str, dict]]:
    seen: list[tuple[str, dict]] = []

    async def log_event(paper_id, kind, *, stage=None, specialist=None, payload=None):
        seen.append((kind, payload or {}))

    monkeypatch.setattr("src.db.events.log_event", log_event)
    return seen


def test_the_runner_writes_checks_and_titles_the_abstract(tmp_path, monkeypatch):
    from src.core.pipeline.components import activate, deactivate

    events = _events(monkeypatch)
    ws = _workspace(tmp_path)
    (ws / "paper_draft.tex").write_text("\\title{Road Deaths, 2021}\n\\section{Results}\nThe median is 12.3.\n")
    writer = _Writer(ROAD)
    runner = _runner(ws, writer)
    token = activate(runner._spec)
    try:
        asyncio.run(runner._run_abstract_phase())
    finally:
        deactivate(token)
    assert writer.calls == 1
    assert (ws / "abstract.tex").read_text().startswith("\\title{Road Deaths, 2021}")
    gate = [p for k, p in events if k == "gate_enforced" and p.get("gate") == "abstract"]
    assert gate and gate[0]["passed"] is True
    assert json.loads((ws / ab.CHECK_FILE).read_text())["passed"] is True


def test_a_second_failure_is_a_finding_in_the_dossier_and_the_run_goes_on(tmp_path, monkeypatch):
    from src.core.pipeline.components import activate, deactivate

    events = _events(monkeypatch)
    ws = _workspace(tmp_path)
    writer = _Writer(_env("We ask how rates vary. The study makes no causal claim."))
    runner = _runner(ws, writer)
    token = activate(runner._spec)
    try:
        asyncio.run(runner._run_abstract_phase())  # does not raise
    finally:
        deactivate(token)
    assert writer.calls == 2
    gate = [p for k, p in events if k == "gate_enforced" and p.get("gate") == "abstract"]
    assert gate and gate[0]["passed"] is False and "recorded as a finding" in gate[0]["detail"]
    assert any(k == "abstract_finding" for k, _p in events)


def test_under_governance_off_the_writer_is_not_sent_back(tmp_path, monkeypatch):
    from src.core.pipeline.components import activate, deactivate

    _events(monkeypatch)
    ws = _workspace(tmp_path)
    writer = _Writer(_env("We ask how rates vary. The study makes no causal claim."))
    runner = _runner(ws, writer, governance="off")
    token = activate(runner._spec)
    try:
        asyncio.run(runner._run_abstract_phase())
    finally:
        deactivate(token)
    assert writer.calls == 1


def test_the_strategists_abstract_writer_order_is_dropped(tmp_path):
    from src.core.strategist.actions import WorkOrder as StrategistOrder

    runner = _runner(tmp_path, _Writer(ROAD))
    orders = [
        StrategistOrder(specialist="paper_drafter", focus="Draft.", parallel_group=0),
        StrategistOrder(specialist="abstract_writer", focus="Abstract.", parallel_group=0),
    ]
    assert [o.specialist for o in runner._to_contract_orders(orders)] == ["paper_drafter"]
    # A template without the step (field map) keeps what the strategist planned.
    other = _runner(tmp_path, _Writer(ROAD), pipeline="field-map")
    assert [o.specialist for o in other._to_contract_orders(orders)] == ["paper_drafter", "abstract_writer"]


def test_the_revision_keeps_abstract_findings_for_the_abstract_step(tmp_path, monkeypatch):
    events = _events(monkeypatch)
    (tmp_path / "review_writing.md").write_text(
        "# Review\n\nThe abstract lists too many numbers and ends on a negation.\n\nOVERALL SCORE: 7.5/10\n"
        "RECOMMENDATION: Minor Revision\n"
    )
    runner = _runner(tmp_path, _Writer(ROAD))
    asyncio.run(runner._record_abstract_findings())
    doc = json.loads((tmp_path / ab.FINDINGS_FILE).read_text())
    assert [f["source_detail"] for f in doc["findings"]] == ["writing_reviewer"]
    assert any(k == "abstract_findings" for k, _p in events)


def test_the_drafter_is_told_to_leave_the_abstract_out():
    from src.core.pipeline.components import activate, deactivate
    from src.core.pipeline.spec import find_spec
    from src.core.specialists.base import _build_system_prompt

    token = activate(find_spec("empirical"))
    try:
        assert "Do not write an abstract" in _build_system_prompt("paper_drafter", "")
        assert "Do not write an abstract" not in _build_system_prompt("abstract_writer", "")
    finally:
        deactivate(token)
    token = activate(find_spec("field-map"))
    try:
        assert "Do not write an abstract" not in _build_system_prompt("paper_drafter", "")
    finally:
        deactivate(token)


# ── no coefficients quoted as raw numbers (2026-10-22) ───────────────────────


@pytest.mark.parametrize(
    "sentence",
    [
        "The estimated shift is $-0.0181$ in correlation units, which is small.",
        "The coefficient on treatment is 0.04 for every country.",
        "Enrolment changes with an effect of $\\beta = 0.31$ per reform.",
        "Returns fell by $-0.3$ over the window.",
    ],
)
def test_a_coefficient_quoted_as_a_raw_number_fails(sentence):
    probs = _problems(f"We ask whether listings matter. {sentence} Listing widened access to the asset.")
    assert any("quoted as a raw estimate" in p for p in probs), probs


@pytest.mark.parametrize(
    "sentence",
    [
        "The estimated effect is about 22 percentage points over six years.",
        "The effect shifts the correlation by under two correlation points.",
        "The estimated rise is 0.50 degrees per decade in every season.",
        "Moran's I is 0.37 under queen contiguity.",
        "Calculated radii have a median period about 45 times that of measured radii.",
    ],
)
def test_magnitudes_in_plain_units_pass(sentence):
    probs = _problems(f"We ask whether listings matter. {sentence} Listing widened access to the asset.")
    assert not any("raw estimate" in p for p in probs), probs
