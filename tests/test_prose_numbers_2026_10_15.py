"""The prose number check: settings of the design are not results (2026-10-14/15 demo runs).

The weather-words study's verify listed 28 text numbers that "differ": rate
denominators ("per 10,000 words"), the cohort years of its design ("authors
born 1770--1799"), its corpus threshold ("the 30,000-token threshold") and the
settings of its corpus design. None is a result. Real numbers near a named
quantity stay checked.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.core.pipeline.verify_numbers import design_constants, verify

RESULTS = {
    "weather_rate": {"c1": 8000.0},
    "cohort_birth_year_end": {"c1": 1797},
    "corpus_token_count": 31000,
    "novels_count": 1800,
}


def _study(tmp_path: Path, prose: str, *, design: dict | None = None) -> Path:
    (tmp_path / "estimation_results.json").write_text(json.dumps(RESULTS))
    if design is not None:
        (tmp_path / "corpus_design.json").write_text(json.dumps(design))
    draft = tmp_path / "paper_draft.tex"
    draft.write_text("\\begin{document}\n" + prose + "\n\\end{document}\n")
    return draft


def _differ(tmp_path: Path, prose: str, **kw) -> list[str]:
    report = verify(_study(tmp_path, prose, **kw), tmp_path)
    return [m.draft_value for m in report.prose_mismatches]


def test_a_rate_denominator_is_not_a_result(tmp_path: Path):
    assert _differ(tmp_path, "The weather rate is counted per 10,000 words of each novel.") == []


def test_cohort_years_are_labels(tmp_path: Path):
    assert _differ(tmp_path, "The first cohort holds authors born 1770--1799, the birth year of each author.") == []
    assert _differ(tmp_path, "The cohort ends with authors born in 1799 by birth year.") == []


def test_a_threshold_named_after_the_number_is_a_setting(tmp_path: Path):
    assert _differ(tmp_path, "Novels below the 30,000-token threshold of the corpus were replaced.") == []


def test_a_setting_of_the_design_is_not_looked_for_in_the_results(tmp_path: Path):
    prose = "The corpus keeps texts of at least 25,000 tokens per novel."
    assert _differ(tmp_path, prose) == ["25,000"]  # without the design: a number near the corpus token count
    assert _differ(tmp_path, prose, design={"preprocessing": {"min_tokens": 25000}}) == []


def test_real_numbers_stay_checked(tmp_path: Path):
    design = {"preprocessing": {"min_tokens": 25000}, "cohorts": ["1770-1799"]}
    prose = (
        "The corpus has 30,500 tokens in all. We read 1,700 novels in the novels count. "
        "Among them N = 1790 novels count as gothic."
    )
    assert _differ(tmp_path, prose, design=design) == ["30,500", "1,700", "1790"]


def test_design_constants_read_the_design_files_and_the_template(tmp_path: Path):
    (tmp_path / "corpus_design.json").write_text(json.dumps({"min_tokens": 30000, "cohorts": ["1770-1799"]}))
    (tmp_path / "data_dictionary.json").write_text(
        json.dumps({"tables": [{"name": "t", "rows": 108, "min_non_null": 100}]})
    )
    (tmp_path / "preregistration.md").write_text("Rates per 10,000 words; at most 2 novels per author.\n")
    (tmp_path / "manifest.json").write_text(json.dumps({"pipeline": "text-analysis"}))
    found = design_constants(tmp_path)
    assert {30000.0, 1770.0, 1799.0, 100.0, 10000.0, 2.0} <= found
    assert 20.0 in found  # the text-analysis template's min_validation_items
    assert 108.0 not in found  # a row count is a fact about the data, checked as a result
