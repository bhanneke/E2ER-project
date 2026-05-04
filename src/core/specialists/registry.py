"""Specialist registry — maps specialist names to output artifacts and skills."""
from __future__ import annotations

SPECIALIST_ARTIFACTS: dict[str, str] = {
    # Research phase
    "idea_developer": "paper_plan.md",
    "literature_scanner": "literature_review.md",
    "data_architect": "data_dictionary.json",
    "identification_strategist": "identification_strategy.md",
    "econometrics_specialist": "econometric_spec.md",
    "data_analyst": "data_summary.md",
    # Writing phase
    "paper_drafter": "paper_draft.tex",
    "section_writer": "paper_draft.tex",
    "abstract_writer": "abstract.tex",
    "latex_formatter": "paper_draft.tex",
    # Review phase
    "mechanism_reviewer": "review_mechanism.md",
    "technical_reviewer": "review_technical.md",
    "literature_reviewer": "review_literature.md",
    "writing_reviewer": "review_writing.md",
    "data_reviewer": "review_data.md",
    "identification_reviewer": "review_identification.md",
    # V3 extensions
    "self_attacker": "self_attack_report.json",
    "polish_formula": "polish_formula.md",
    "polish_numerics": "polish_numerics.md",
    "polish_institutions": "polish_institutions.md",
    "polish_bibliography": "polish_bibliography.md",
    "polish_equilibria": "polish_equilibria.md",
    # Revision
    "revisor": "paper_draft.tex",
    "replication_packager": "replication/estimation.py",
}

SPECIALIST_SKILLS: dict[str, list[str]] = {
    "idea_developer": ["base/researcher", "base/economist", "reasoning/creative-ideation", "reasoning/novelty"],
    "literature_scanner": ["base/researcher", "synthesis/context-builder"],
    "data_architect": ["data/blockchain", "data/crypto-defi", "base/economist"],
    "identification_strategist": ["causal-inference/judge-designs", "causal-inference/natural-experiments", "reasoning/identification"],
    "econometrics_specialist": ["econometrics/iv-estimation", "econometrics/did", "econometrics/panel-data", "econometrics/event-study"],
    "data_analyst": ["data/cleaning", "data/figure-spec", "econometrics/panel-data"],
    "paper_drafter": ["writing/paper-structure", "writing/personal-style", "base/researcher"],
    "section_writer": ["writing/paper-structure", "writing/personal-style", "reasoning/anti-slop"],
    "abstract_writer": ["writing/abstract", "reasoning/anti-slop"],
    "latex_formatter": ["latex/econ-model", "latex/tables"],
    "mechanism_reviewer": ["review/referee-simulation", "modeling/market-microstructure"],
    "technical_reviewer": ["review/technical-review", "review/consistency-check"],
    "literature_reviewer": ["review/referee-simulation", "synthesis/context-builder"],
    "writing_reviewer": ["review/writing-quality", "reasoning/anti-slop"],
    "data_reviewer": ["review/data-quality", "data/cleaning"],
    "identification_reviewer": ["causal-inference/sensitivity", "review/technical-review"],
    "self_attacker": ["review/referee-simulation", "reasoning/argument-audit", "causal-inference/sensitivity"],
    "polish_formula": ["latex/econ-model", "math/optimization-verification"],
    "polish_numerics": ["data/cleaning", "review/consistency-check"],
    "polish_institutions": ["base/economist", "data/crypto-defi"],
    "polish_bibliography": ["latex/bibtex", "synthesis/context-builder"],
    "polish_equilibria": ["modeling/game-theory", "math/proof-strategies"],
    "revisor": ["writing/paper-structure", "writing/personal-style", "reasoning/anti-slop"],
    "replication_packager": ["data/cleaning", "base/researcher"],
}

REVIEWER_SPECIALISTS = [
    "mechanism_reviewer",
    "technical_reviewer",
    "literature_reviewer",
    "writing_reviewer",
    "data_reviewer",
    "identification_reviewer",
]

POLISH_SPECIALISTS = [
    "polish_formula",
    "polish_numerics",
    "polish_institutions",
    "polish_bibliography",
    "polish_equilibria",
]
