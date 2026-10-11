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
    # Discipline-neutral reviewers (0.16.0) for templates outside economics: the
    # methods the study used, and whether its numbers are plausible in its domain.
    "methods_reviewer": "review_methods.md",
    "plausibility_reviewer": "review_plausibility.md",
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
    # Replication template (pipelines/replication.toml): reproduce a published
    # study from its replication package. The planner maps the paper's tables
    # and figures to the package's scripts and records the published numbers;
    # the comparer levels each result against what the sandbox run produced.
    "replication_planner": "replication_plan.md",
    "reproduction_comparer": "reproduction_report.md",
    # Field-map template (pipelines/field-map.toml): main path analysis of a
    # research field. The boundary designer proposes the search terms, journals
    # and years (and the alternative boundaries); the lane mapper groups the
    # mapped papers into lanes named as questions; the review writer drafts a
    # short field review from the computed results. The computation in between
    # is code (src/modules/fieldmap), run as steps of the template.
    "field_boundary_designer": "field_boundary.md",
    "field_lane_mapper": "field_lanes.md",
    "field_review_writer": "paper_draft.tex",
    # Time-series template (pipelines/time-series-forecasting.toml): declares the
    # forecast setup (series, hold-out, horizon, baselines, candidate models,
    # diagnostics, interval level) before any model is fitted; the setup and the
    # hold-out are frozen by the forecast_design check (forecast_checks.py).
    "forecast_designer": "forecast_design.md",
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
        # Declares the data.db tables the analyst loads (data_dictionary.json `tables`).
        "data/data-tables",
        "data/query-data",
        "data/blockchain",
        "data/crypto-defi",
        "base/economist",
        "data/allium-cli",
        "data/allium-developer-api",
        "data/yfinance",
        "data/fred",
        "data/gmd",
    ],
    "identification_strategist": [
        # Names data by the tables the data dictionary declares.
        "data/data-tables",
        "causal-inference/judge-designs",
        "causal-inference/natural-experiments",
        "reasoning/identification",
        # Machine-readable sidecar contract: identification_spec.json
        # declares the primary FE/controls/clustering that the
        # econometrics specialist's `main` entry must echo (the
        # identified-spec contract in contract_check.py).
        "causal-inference/identification-spec-schema",
    ],
    "econometrics_specialist": [
        "data/query-data",
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
        # Loads the declared tables into data.db, reports real row counts, never estimates.
        "data/data-tables",
        "data/query-data",
        "data/cleaning",
        "data/figure-spec",
        "econometrics/panel-data",
        "data/allium-cli",
        "data/allium-developer-api",
        "data/yfinance",
        "data/fred",
        "data/gmd",
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
    "methods_reviewer": ["review/methods-review", "review/consistency-check"],
    "plausibility_reviewer": ["review/domain-plausibility", "review/consistency-check"],
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
    "replication_planner": ["replication/reproduction-protocol", "replication/replication-plan"],
    "reproduction_comparer": ["replication/reproduction-protocol", "replication/reproduction-report"],
    "field_boundary_designer": ["synthesis/main-path-analysis", "base/researcher"],
    "field_lane_mapper": ["synthesis/main-path-analysis", "reasoning/anti-slop"],
    "field_review_writer": [
        "synthesis/main-path-analysis",
        "writing/personal-style",
        "writing/cite-numbers-by-source",
        "reasoning/anti-slop",
    ],
    "forecast_designer": [
        "base/researcher",
        "methods/time-series-forecasting",
        "data/data-tables",
        "data/query-data",
    ],
}


def _add_source_skills() -> None:
    """The data architect and the data analyst read the skill of every connector-kit source.

    The sources written before the kit are listed above; a source added to
    modules/data/sources/ brings its skill (``Source.skill``) here.
    """
    from ...modules.data.sources import all_sources

    for specialist in ("data_architect", "data_analyst"):
        skills = SPECIALIST_SKILLS[specialist]
        for source in all_sources():
            if source.skill and source.skill not in skills:
                skills.append(source.skill)


_add_source_skills()

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
    "identification_strategist": [
        # Machine-readable core of identification_strategy.md: the declared
        # primary FE/controls/clustering. Consumed by the identified-spec
        # contract (contract_check.check_matches_declared_spec) which gates
        # the econometrics specialist's `main` entry against it.
        "identification_spec.json",
    ],
    "econometrics_specialist": [
        "estimation_results.json",
        # robustness_results.json is conditionally emitted by the
        # specialist when robustness checks were actually run. Not
        # required by the registry; the skill file explains when to
        # include it.
    ],
    # The plan is what the sandbox executes; the report is what the
    # reproduction check verifies number by number. Both are required.
    "replication_planner": ["replication_plan.json"],
    "reproduction_comparer": ["reproduction_report.json"],
    # The field map's two judgement files, read by code: the boundaries the
    # retrieval step fetches, and the lanes the map step draws.
    "field_boundary_designer": ["field_boundary.json"],
    "field_lane_mapper": ["field_lanes.json"],
    # The forecast setup the forecast_design check validates and freezes.
    "forecast_designer": ["forecast_design.json"],
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
# (docs/internal/M4_RERUN_FINDINGS.md). Figures are a paper-assembly concern: they
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

#: Every reviewer a template may put on its panel (its `aggregate` step): e2er's
#: default panel above, then the discipline-neutral reviewers. Membership tests
#: ("is this a reviewer?") use this list; REVIEWER_SPECIALISTS stays the panel of
#: the economics templates, whose behaviour 0.16.0 leaves as it was.
ALL_REVIEWERS = [*REVIEWER_SPECIALISTS, "methods_reviewer", "plausibility_reviewer"]

#: Data skills that belong to one domain (blockchain and DeFi data, the Allium
#: warehouse). A template that declares ``data_skills`` replaces these with its
#: own; the general connector skills (FRED, yfinance, GMD, ...) stay.
DOMAIN_DATA_SKILLS: frozenset[str] = frozenset(
    {"data/blockchain", "data/crypto-defi", "data/allium-cli", "data/allium-developer-api"}
)

POLISH_SPECIALISTS = [
    "polish_formula",
    "polish_numerics",
    "polish_institutions",
    "polish_bibliography",
    "polish_equilibria",
]


#: What each specialist reads that another specialist writes, by producer. When
#: both are in one dispatch the dispatcher runs the producer's group first
#: (``dispatcher.order_by_dependencies``), whatever groups the strategist chose.
#: The 2026-10-03 live run had ``econometrics_specialist`` in the same parallel
#: group as ``data_analyst`` (the strategist's own prompt example did that), so
#: estimation ran against a data.db that was still being loaded and every
#: attempt failed its contract.
SPECIALIST_NEEDS: dict[str, tuple[str, ...]] = {
    # data_dictionary.json: the tables to load.
    "data_analyst": ("data_architect",),
    # data.db and data_summary.md (the loaded data), data_dictionary.json, and
    # identification_spec.json (the declared specification the results are checked against).
    "econometrics_specialist": ("data_architect", "data_analyst", "identification_strategist", "forecast_designer"),
    # data.db (the series) and data_dictionary.json: the hold-out is chosen on the loaded series.
    "forecast_designer": ("data_architect", "data_analyst"),
    # estimation_results.json (the results table), data_summary.md, model_spec.md.
    "paper_drafter": ("data_analyst", "econometrics_specialist", "theory_specialist"),
    # field_lanes.json names the lanes the review is organised by.
    "field_review_writer": ("field_lane_mapper",),
}

#: Specialists that write their output files whole on every attempt. Before an
#: attempt their earlier files are moved to `.history/<name>.<n>` (see
#: specialists/base.py), so a retry or a send-back never trips over, or passes
#: with, a file from before. The reviewers are among them: a review run again
#: (after a deep revision, or a rerun from the review step) must never be
#: scored from the review file of the round before.
SPECIALIST_REWRITES_OUTPUTS: frozenset[str] = frozenset(
    {
        "replication_planner",
        "reproduction_comparer",
        "field_boundary_designer",
        "field_lane_mapper",
        *ALL_REVIEWERS,
    }
)

#: The work order a fixed `specialists` step of a template gives a specialist
#: when the runner has no phase of its own for that step (the strategist writes
#: the focus everywhere else). Paths are workspace-relative.
SPECIALIST_DEFAULT_FOCUS: dict[str, str] = {
    "replication_planner": (
        "Plan the computational reproduction of the published study whose replication package was fetched "
        "into `package/` (read-only; file list and SHA-256 in `package_manifest.json`, which also names the "
        "record's linked publication). The text of every PDF in the package, page by page, is in "
        "`package_text/`. When the researcher supplied the published paper, it is `paper/paper.pdf` "
        "(`package_manifest.json` -> `paper`), with its text page by page in `paper_text/paper.pdf.txt`. "
        "Read the package's README and documentation and its code. Write `replication_plan.json` exactly as "
        "your replication-plan skill specifies: entry points in run order, the pinned image, every package the "
        "code loads, every table and figure mapped to the script that produces it, and two levels of targets in "
        "one `targets` list, each with `level`: level 1 = cells of result files the package ships "
        "(source.kind 'package_file': file and locator), level 2 = numbers printed in the paper, taken only "
        "from the paper (source.kind 'paper': document, page, table or figure, decimals). Also write "
        "`replication_plan.md` for the researcher who reviews it. Do not run anything and do not change the "
        "package. A target you cannot find goes in missing_targets with its level; never estimate one."
    ),
    "reproduction_comparer": (
        "Compare what the sandbox run reproduced with the published targets, number by number, following the "
        "reproduction protocol, separately for level 1 (the package's own result files, rebuilt) and level 2 "
        "(the numbers printed in the paper). The plan (with the targets and their levels) is "
        "`replication_plan.json`; what ran, with exit codes, logs and the files each run wrote, is "
        "`sandbox_log.json`; the output files are under `sandbox/run/`. Read each reproduced number from an "
        "output file the run wrote (never from a file the package shipped), and write "
        "`reproduction_report.json` exactly as your reproduction-report skill specifies, plus "
        "`reproduction_report.md`. Label every number strictly by the protocol's thresholds (`reproduced` only "
        "when equal at the target's own precision: printed decimals for the paper, 1e-9 relative for a package "
        "cell); a result takes its worst number's label. Name causes of a difference only as possible causes, "
        "and copy the environment (snapshot date and URL, platform, and the versions of the packages you "
        "discuss) from `sandbox_log.json` into the report's `environment` block. A deterministic check "
        "re-reads every number, recomputes every label, compares the reason texts and the environment with "
        "the numbers and the log, and fails the run on any disagreement. e2er writes the counts and the "
        "environment into `reproduction_report.md` itself; do not restate them. Every count, label and version "
        "your Markdown states is compared with `reproduction_report.json`."
    ),
    "field_boundary_designer": (
        "Propose the boundary of the research field the question names, for a main path analysis, as your "
        "main-path-analysis skill describes. Write `field_boundary.json`: `main` (query, search_in, sources, "
        "from_year, to_year, types, exclude, note) and `alternatives`, 2 to 6 boundaries with their own `name` "
        "that change one choice each (another journal set, the method's older names left out or added, a year "
        "range without the last years). Join terms with OR or AND, never commas; quote phrases. Include the older "
        "names the topic went by. Check sizes with `e2er-fieldmap count --query ... [--sources S..] [--from Y] "
        "[--to Y]` (one OpenAlex request each; aim at 300 to 2,000 papers for `main`) and journal ids with "
        '`e2er-fieldmap sources "<journal>"`; stay under 20 such calls. Write `field_boundary.md` for the '
        "researcher: each term and journal with why it is in, the counts you saw, and what each alternative "
        "tests. Code retrieves the boundaries after you; the researcher then approves or edits them."
    ),
    "field_lane_mapper": (
        "Group the papers of the field map into lanes, as your main-path-analysis skill describes. "
        "`e2er-fieldmap papers --abstracts` lists the mapped papers (the main path and the key routes of the "
        "main boundary) with titles, abstracts and keywords; `main_path.md` and `robustness.md` show the paths. "
        "Write `field_lanes.json`: `lanes`, 2 to 8, each with `id`, `question` (the lane named as a question the "
        "papers in it answer, ending with '?') and `papers` (OpenAlex ids; each paper in one lane at most; at "
        "most a quarter of the mapped papers in none). Decide from titles and abstracts only, not from what you "
        "remember of the field. Write `field_lanes.md`: each lane, the papers in it by year, and one sentence on "
        "why. The researcher approves or edits the lanes before the map is drawn."
    ),
    "field_review_writer": (
        "Write a short field review in LaTeX (`paper_draft.tex`: \\title, the abstract and the body, without "
        "\\documentclass or a bibliography command; e2er adds the preamble and the bibliography) from the "
        "field map, as your main-path-analysis skill describes. Read `field_map_results.json` (every number you "
        "may state), `main_path.md`, `robustness.md`, `completeness_report.md`, `field_lanes.json`, "
        "`field_boundary.md` and `reading_list.csv`. Include \\input{tables/field_map_summary.tex} and "
        "\\input{tables/main_path_list.tex} and the figure `figures/field_map.pdf`; write no table yourself. Every "
        "number in the text must be a value of `field_map_results.json`. Cite the papers of the main path from "
        "`literature.bib` (run `e2er-lit save --doi <doi>` for each one you cite; the DOIs are in "
        "`reading_list.csv`) and the method with the keys hummon1989connectivity, batagelj2003efficient and "
        "liu2012integrated, which are in `literature.bib` already. Describe how the field moved along the main "
        "path, lane by lane, which papers hold across the boundaries, and state the limits: the boundary decides "
        "the result, recent papers are under-cited so the end of the path is unsettled, database coverage and "
        "short reference lists drop links, and a main path shows how citations flow, not what the field "
        "believes. Two to four pages."
    ),
}
