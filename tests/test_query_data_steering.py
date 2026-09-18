"""query_data skill-steering: data specialists are told to SQL-explore the
warehouse and verify columns before defining variables (the run-2 proxy bug)."""

from __future__ import annotations

from src.core.specialists.base import _build_system_prompt
from src.core.specialists.registry import SPECIALIST_SKILLS


def _prompt(specialist: str, has_data_db: bool) -> str:
    return _build_system_prompt(specialist, skills_text="", has_data_db=has_data_db)


def test_mandate_present_for_data_specialists_with_data_db():
    for spec in ("data_analyst", "data_architect", "econometrics_specialist"):
        p = _prompt(spec, has_data_db=True)
        assert "query_data" in p
        assert "DO NOT GUESS COLUMNS" in p
        assert "construct-validity" in p  # the proxy-vs-real-column lesson


def test_no_mandate_without_data_db():
    assert "Local Data Warehouse" not in _prompt("data_analyst", has_data_db=False)


def test_no_mandate_for_non_data_specialist():
    assert "query_data" not in _prompt("paper_drafter", has_data_db=True)


def test_sample_flow_steering_in_data_mandate():
    # data specialists are told to document the sample construction (sample-flow)
    p = _prompt("data_analyst", has_data_db=True)
    assert "SAMPLE CONSTRUCTION" in p
    assert "sample-flow" in p
    # gated on a data.db like the rest of the mandate
    assert "SAMPLE CONSTRUCTION" not in _prompt("data_analyst", has_data_db=False)


def test_econometrics_identified_spec_mandate():
    # The headline-must-be-identified mandate fires for econometrics, not others.
    p = _prompt("econometrics_specialist", has_data_db=True)
    assert "IDENTIFIED specification" in p
    assert "raw" in p and "identification_strategy.md" in p
    assert "IDENTIFIED specification" not in _prompt("data_analyst", has_data_db=True)


def test_query_data_skill_in_data_bundles():
    for spec in ("data_analyst", "data_architect", "econometrics_specialist"):
        assert "data/query-data" in SPECIALIST_SKILLS[spec], spec


def test_query_data_skill_file_loads():
    from src.skills.loader import _load_skill

    text = _load_skill("data/query-data")
    assert "query_data" in text and "DISTINCT" in text
