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
    # Theoretical-paper specialist (dispatched when methodology is theoretical or mixed)
    "theory_specialist": "model_spec.md",
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
    # v0.6: scoped revisor. Writes a structured patch file rather than
    # rewriting paper_draft.tex from scratch. The merger
    # (src/core/strategist/patch_merger.py) reads the patch file,
    # validates each edit's target against the work order's Finding
    # list, applies in-scope edits, emits a unified diff side artifact.
    "patch_revisor": "paper_draft.tex.edits.json",
    "replication_packager": "replication/estimation.py",
}

SPECIALIST_SKILLS: dict[str, list[str]] = {
    "idea_developer": [
        "base/researcher",
        "base/economist",
        "reasoning/creative-ideation",
        "reasoning/novelty",
    ],
    "literature_scanner": ["base/researcher", "synthesis/context-builder"],
    "data_architect": [
        "data/blockchain",
        "data/crypto-defi",
        "base/economist",
        "data/allium-cli",
        "data/allium-developer-api",
        "data/yfinance",
        "data/fred",
    ],
    "identification_strategist": [
        "causal-inference/judge-designs",
        "causal-inference/natural-experiments",
        "reasoning/identification",
    ],
    "econometrics_specialist": [
        "econometrics/iv-estimation",
        "econometrics/did",
        "econometrics/panel-data",
        "econometrics/event-study",
        # v0.5: machine-readable sidecar contract consumed by
        # verify_numbers + paper_drafter. Without this skill the
        # specialist doesn't know what shape estimation_results.json
        # must take.
        "econometrics/estimation-results-schema",
    ],
    "data_analyst": [
        "data/cleaning",
        "data/figure-spec",
        "econometrics/panel-data",
        "data/allium-cli",
        "data/allium-developer-api",
        "data/yfinance",
        "data/fred",
        # v0.5: machine-readable sidecar contract. Teaches the analyst
        # the summary_statistics.json shape that verify_numbers gates
        # against and the drafter cites by key.
        "data/summary-statistics-schema",
    ],
    "theory_specialist": [
        "base/economist",
        "modeling/game-theory",
        "modeling/asset-pricing",
        "math/proof-strategies",
        "reasoning/identification",
    ],
    "paper_drafter": [
        "writing/paper-structure",
        "writing/personal-style",
        "base/researcher",
        # v0.5: teaches the drafter to cite every number by JSON source
        # key. Complements the post-hoc verify_numbers gate by reducing
        # the rate of hallucinated table values in the first place.
        "writing/cite-numbers-by-source",
        # Results tables: author table_spec.json (structure only); the
        # renderer fills the numbers from the JSON sidecars deterministically.
        "data/table-spec",
    ],
    "section_writer": [
        "writing/paper-structure",
        "writing/personal-style",
        "reasoning/anti-slop",
        "writing/cite-numbers-by-source",
        "data/table-spec",
    ],
    "abstract_writer": [
        "writing/abstract",
        "reasoning/anti-slop",
        # Abstracts cite the headline numbers — must trace to sidecars.
        "writing/cite-numbers-by-source",
    ],
    "latex_formatter": ["latex/econ-model", "latex/tables"],
    "mechanism_reviewer": ["review/referee-simulation", "modeling/market-microstructure"],
    "technical_reviewer": ["review/technical-review", "review/consistency-check"],
    "literature_reviewer": ["review/referee-simulation", "synthesis/context-builder"],
    "writing_reviewer": ["review/writing-quality", "reasoning/anti-slop"],
    "data_reviewer": ["review/data-quality", "data/cleaning"],
    "identification_reviewer": ["causal-inference/sensitivity", "review/technical-review"],
    "self_attacker": [
        "review/referee-simulation",
        "reasoning/argument-audit",
        "causal-inference/sensitivity",
    ],
    "polish_formula": ["latex/econ-model", "math/optimization-verification"],
    "polish_numerics": ["data/cleaning", "review/consistency-check"],
    "polish_institutions": ["base/economist", "data/crypto-defi"],
    "polish_bibliography": ["latex/bibtex", "synthesis/context-builder"],
    "polish_equilibria": ["modeling/game-theory", "math/proof-strategies"],
    "revisor": [
        "writing/paper-structure",
        "writing/personal-style",
        "reasoning/anti-slop",
        # v0.5: the revisor edits paper_draft.tex; same cite-by-source
        # discipline as the drafter, otherwise revisions can introduce
        # new hallucinations that pass review only because the gate
        # already ran on the pre-revision draft.
        "writing/cite-numbers-by-source",
    ],
    # v0.6: scoped patch revisor. Writes paper_draft.tex.edits.json
    # rather than rewriting the whole .tex. The scoped-revision skill
    # is load-bearing — without it the specialist has no contract
    # for the patch file format.
    "patch_revisor": [
        "writing/scoped-revision",
        "writing/cite-numbers-by-source",
        "writing/personal-style",
        "reasoning/anti-slop",
    ],
    "replication_packager": ["data/cleaning", "base/researcher", "synthesis/replication-package"],
}

# Sidecar artifacts produced ALONGSIDE the primary SPECIALIST_ARTIFACTS file.
# These are machine-readable JSON files that downstream specialists + the
# verify_numbers gate consume. Pre-v0.5.0 the framework only declared one
# output file per specialist, so even when a skill (e.g. data/figure-spec.md)
# instructed JSON emission, the system prompt's "EXACTLY ONE file" rule
# overrode it and the JSON never appeared. Adding the file here both
# auto-populates `work_order.sidecar_artifacts` and triggers the
# multi-file output block in `_build_user_prompt`.
#
# Coverage rule: every file consumed by `verify_numbers` MUST appear here
# under the specialist responsible for it. Adding new consumers is a
# coordinated change: schema skill file + this dict + the consumer code.
SPECIALIST_SIDECAR_ARTIFACTS: dict[str, list[str]] = {
    "data_analyst": [
        "summary_statistics.json",
        "figure_spec.json",
    ],
    "econometrics_specialist": [
        "estimation_results.json",
        # robustness_results.json is conditionally emitted by the
        # specialist when robustness checks were actually run. Not
        # required by the registry; the skill file explains when to
        # include it.
    ],
    "paper_drafter": [
        # Declarative results-table spec. Prompted via the multi-file
        # output block; the renderer (core/renderer/tables.py) fills the
        # numbers from estimation_results.json / robustness_results.json.
        # Best-effort (see SPECIALIST_OPTIONAL_SIDECARS) — theory papers
        # and design-without-estimates drafts legitimately have no results
        # table.
        "table_spec.json",
    ],
}

# Best-effort sidecars: prompted (they stay in SPECIALIST_SIDECAR_ARTIFACTS,
# so the multi-file output block still asks for them) and validated by
# verify_numbers when present — but NOT hard-gated by the M4.3 contract
# check at the specialist boundary.
#
# Why figure_spec.json is here: specialists have no general code-execution
# tool (see modules/llm/claude_code.py), and a figure spec's values are
# *derived* from the analysis the runner executes post-hoc — so the model
# legitimately can't author populated figure values at the data-design
# boundary. Hard-gating it there killed the M5 re-run in the design phase
# (docs/M4_RERUN_FINDINGS.md). Figures are a paper-assembly concern: they
# get authored in the iterative phase and checked by verify_numbers if
# present, which is the right place to enforce them.
SPECIALIST_OPTIONAL_SIDECARS: dict[str, frozenset[str]] = {
    "data_analyst": frozenset({"figure_spec.json"}),
    # table_spec.json is prompted but not hard-gated: a theory paper or a
    # design-without-estimates draft has no results table, and that must not
    # fail the drafter at the contract boundary.
    "paper_drafter": frozenset({"table_spec.json"}),
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
