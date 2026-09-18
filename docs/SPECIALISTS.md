# Specialists and skills

**Generated — do not edit.** `python scripts/gen_specialist_manifest.py`

Every specialist the strategist can dispatch, the skill files it is given, and
the artifacts it must produce. A specialist that does not write its declared
artifact fails its contract and is retried with the violation fed back.

- **26** specialists
- **58** skill files on disk
- **47** referenced by at least one specialist
- **11** never referenced

## Shipped but never loaded

These skill files are packaged and no specialist references them. Each is
either a capability that was written and never wired up, or dead weight.
`econometrics/rdd` and `econometrics/time-series` are the striking ones: the
methodology guidance exists, and no specialist is given it.

- `causal-inference/shift-share`
- `causal-inference/weak-instruments`
- `data/byod`
- `data/visualization`
- `econometrics/rdd`
- `econometrics/time-series`
- `review/constructive-feedback`
- `review/reference-check`
- `synthesis/deliverables`
- `writing/discussion`
- `writing/revision`

## Specialists

### `abstract_writer`

- **Writes:** `abstract.tex`
- **Skills (3):** `writing/abstract`, `reasoning/anti-slop`, `writing/cite-numbers-by-source`

### `data_analyst`

- **Writes:** `data_summary.md`
- **Sidecars:** `summary_statistics.json`, `figure_spec.json` _(optional)_
- **Skills (9):** `data/query-data`, `data/cleaning`, `data/figure-spec`, `econometrics/panel-data`, `data/allium-cli`, `data/allium-developer-api`, `data/yfinance`, `data/fred`, `data/summary-statistics-schema`

### `data_architect`

- **Writes:** `data_dictionary.json`
- **Skills (8):** `data/query-data`, `data/blockchain`, `data/crypto-defi`, `base/economist`, `data/allium-cli`, `data/allium-developer-api`, `data/yfinance`, `data/fred`

### `data_reviewer`

- **Writes:** `review_data.md`
- **Skills (2):** `review/data-quality`, `data/cleaning`

### `econometrics_specialist`

- **Writes:** `econometric_spec.md`
- **Sidecars:** `estimation_results.json`
- **Skills (6):** `data/query-data`, `econometrics/iv-estimation`, `econometrics/did`, `econometrics/panel-data`, `econometrics/event-study`, `econometrics/estimation-results-schema`

### `idea_developer`

- **Writes:** `paper_plan.md`
- **Skills (4):** `base/researcher`, `base/economist`, `reasoning/creative-ideation`, `reasoning/novelty`

### `identification_reviewer`

- **Writes:** `review_identification.md`
- **Skills (2):** `causal-inference/sensitivity`, `review/technical-review`

### `identification_strategist`

- **Writes:** `identification_strategy.md`
- **Sidecars:** `identification_spec.json`
- **Skills (4):** `causal-inference/judge-designs`, `causal-inference/natural-experiments`, `reasoning/identification`, `causal-inference/identification-spec-schema`

### `latex_formatter`

- **Writes:** `paper_draft.tex`
- **Skills (2):** `latex/econ-model`, `latex/tables`

### `literature_reviewer`

- **Writes:** `review_literature.md`
- **Skills (2):** `review/referee-simulation`, `synthesis/context-builder`

### `literature_scanner`

- **Writes:** `literature_review.md`
- **Skills (2):** `base/researcher`, `synthesis/context-builder`

### `mechanism_reviewer`

- **Writes:** `review_mechanism.md`
- **Skills (2):** `review/referee-simulation`, `modeling/market-microstructure`

### `paper_drafter`

- **Writes:** `paper_draft.tex`
- **Sidecars:** `table_spec.json` _(optional)_
- **Skills (5):** `writing/paper-structure`, `writing/personal-style`, `base/researcher`, `writing/cite-numbers-by-source`, `data/table-spec`

### `patch_revisor`

- **Writes:** `paper_draft.tex.edits.json`
- **Skills (4):** `writing/scoped-revision`, `writing/cite-numbers-by-source`, `writing/personal-style`, `reasoning/anti-slop`

### `polish_bibliography`

- **Writes:** `polish_bibliography.md`
- **Skills (2):** `latex/bibtex`, `synthesis/context-builder`

### `polish_equilibria`

- **Writes:** `polish_equilibria.md`
- **Skills (2):** `modeling/game-theory`, `math/proof-strategies`

### `polish_formula`

- **Writes:** `polish_formula.md`
- **Skills (2):** `latex/econ-model`, `math/optimization-verification`

### `polish_institutions`

- **Writes:** `polish_institutions.md`
- **Skills (2):** `base/economist`, `data/crypto-defi`

### `polish_numerics`

- **Writes:** `polish_numerics.md`
- **Skills (2):** `data/cleaning`, `review/consistency-check`

### `replication_packager`

- **Writes:** `replication/estimation.py`
- **Skills (3):** `data/cleaning`, `base/researcher`, `synthesis/replication-package`

### `revisor`

- **Writes:** `paper_draft.tex`
- **Skills (4):** `writing/paper-structure`, `writing/personal-style`, `reasoning/anti-slop`, `writing/cite-numbers-by-source`

### `section_writer`

- **Writes:** `paper_draft.tex`
- **Skills (5):** `writing/paper-structure`, `writing/personal-style`, `reasoning/anti-slop`, `writing/cite-numbers-by-source`, `data/table-spec`

### `self_attacker`

- **Writes:** `self_attack_report.json`
- **Skills (3):** `review/referee-simulation`, `reasoning/argument-audit`, `causal-inference/sensitivity`

### `technical_reviewer`

- **Writes:** `review_technical.md`
- **Skills (2):** `review/technical-review`, `review/consistency-check`

### `theory_specialist`

- **Writes:** `model_spec.md`
- **Skills (5):** `base/economist`, `modeling/game-theory`, `modeling/asset-pricing`, `math/proof-strategies`, `reasoning/identification`

### `writing_reviewer`

- **Writes:** `review_writing.md`
- **Skills (2):** `review/writing-quality`, `reasoning/anti-slop`

## Skill → specialists

The reverse index: who is affected if you edit a skill file.

| Skill | Loaded by |
|---|---|
| `base/economist` | `data_architect`, `idea_developer`, `polish_institutions`, `theory_specialist` |
| `base/researcher` | `idea_developer`, `literature_scanner`, `paper_drafter`, `replication_packager` |
| `causal-inference/identification-spec-schema` | `identification_strategist` |
| `causal-inference/judge-designs` | `identification_strategist` |
| `causal-inference/natural-experiments` | `identification_strategist` |
| `causal-inference/sensitivity` | `identification_reviewer`, `self_attacker` |
| `data/allium-cli` | `data_analyst`, `data_architect` |
| `data/allium-developer-api` | `data_analyst`, `data_architect` |
| `data/blockchain` | `data_architect` |
| `data/cleaning` | `data_analyst`, `data_reviewer`, `polish_numerics`, `replication_packager` |
| `data/crypto-defi` | `data_architect`, `polish_institutions` |
| `data/figure-spec` | `data_analyst` |
| `data/fred` | `data_analyst`, `data_architect` |
| `data/query-data` | `data_analyst`, `data_architect`, `econometrics_specialist` |
| `data/summary-statistics-schema` | `data_analyst` |
| `data/table-spec` | `paper_drafter`, `section_writer` |
| `data/yfinance` | `data_analyst`, `data_architect` |
| `econometrics/did` | `econometrics_specialist` |
| `econometrics/estimation-results-schema` | `econometrics_specialist` |
| `econometrics/event-study` | `econometrics_specialist` |
| `econometrics/iv-estimation` | `econometrics_specialist` |
| `econometrics/panel-data` | `data_analyst`, `econometrics_specialist` |
| `latex/bibtex` | `polish_bibliography` |
| `latex/econ-model` | `latex_formatter`, `polish_formula` |
| `latex/tables` | `latex_formatter` |
| `math/optimization-verification` | `polish_formula` |
| `math/proof-strategies` | `polish_equilibria`, `theory_specialist` |
| `modeling/asset-pricing` | `theory_specialist` |
| `modeling/game-theory` | `polish_equilibria`, `theory_specialist` |
| `modeling/market-microstructure` | `mechanism_reviewer` |
| `reasoning/anti-slop` | `abstract_writer`, `patch_revisor`, `revisor`, `section_writer`, `writing_reviewer` |
| `reasoning/argument-audit` | `self_attacker` |
| `reasoning/creative-ideation` | `idea_developer` |
| `reasoning/identification` | `identification_strategist`, `theory_specialist` |
| `reasoning/novelty` | `idea_developer` |
| `review/consistency-check` | `polish_numerics`, `technical_reviewer` |
| `review/data-quality` | `data_reviewer` |
| `review/referee-simulation` | `literature_reviewer`, `mechanism_reviewer`, `self_attacker` |
| `review/technical-review` | `identification_reviewer`, `technical_reviewer` |
| `review/writing-quality` | `writing_reviewer` |
| `synthesis/context-builder` | `literature_reviewer`, `literature_scanner`, `polish_bibliography` |
| `synthesis/replication-package` | `replication_packager` |
| `writing/abstract` | `abstract_writer` |
| `writing/cite-numbers-by-source` | `abstract_writer`, `paper_drafter`, `patch_revisor`, `revisor`, `section_writer` |
| `writing/paper-structure` | `paper_drafter`, `revisor`, `section_writer` |
| `writing/personal-style` | `paper_drafter`, `patch_revisor`, `revisor`, `section_writer` |
| `writing/scoped-revision` | `patch_revisor` |
