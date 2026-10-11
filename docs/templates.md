# Templates

A template is a pipeline file in `pipelines/` (schema:
`docs/schemas/pipeline.schema.json`). A run follows the template chosen when the
paper is created; resume keeps it. e2er ships five:

| Template | For |
|---|---|
| `empirical` | Question and data in, empirical paper out. The default. |
| `empirical-preregistered` | `empirical` with a design review, a pre-registration frozen before estimation, and a review of the draft (see `researcher-step.md`). |
| `event-study-finance` | Abnormal-return event studies around announcements; checks the estimation window and overlapping events before estimation. |
| `replication` | Computational reproduction of a published study from its Zenodo replication package; the product is a reproduction report, not a paper. |
| `field-map` | A map of a research field by main path analysis of its citation network (OpenAlex), with robustness across alternative boundaries, a reading list, network exports and a short field review. |

## Skills and files a template adds

A template can give its specialists extra skills and ask them for extra
machine-readable files, for its own runs only:

```toml
[skills]
identification_strategist = ["econometrics/event-study"]

[sidecars]
identification_strategist = ["event_design.json"]
```

Both are added after the specialist's own entries in
`src/core/specialists/registry.py`, never instead of them. A skill must name a
file e2er ships (`skills/files/<path>.md`) or has installed; an unknown skill,
specialist or file name stops the template from loading. The merged skills are
listed in the study's description (`e2er.json`, `components.skills`) and pinned
in its dossier; the run also logs them as a `template_components` event.

## Results, causal claim, persona, data skills and panel (outside economics)

e2er's defaults come from economics: the analysis must report a regression
(`coefficients`, t = estimate / se), an identification strategy is required,
specialists read the economist persona, the data specialists read the
blockchain and DeFi skills, and six reviewers score the draft with mechanism
and identification among them. A template for astronomy, earth science,
geography, health or literature declares what it needs instead:

```toml
results     = "descriptive"     # regression (default) | descriptive | timeseries | spatial | text
causal      = false             # default: true for regression, false for every other kind
base_skill  = "base/researcher" # default base/economist
data_skills = []                # replaces the blockchain/DeFi/Allium data skills; absent = as before
review_weights = { methods_reviewer = 1.5, data_reviewer = 1.25 }

[[steps]]
kind = "aggregate"
name = "review"
run  = ["data_reviewer", "methods_reviewer", "plausibility_reviewer", "literature_reviewer", "writing_reviewer"]
```

- **`results`** names the contract `estimation_results.json` is held to
  (`src/core/pipeline/result_kinds.py`). Every kind is written by the same
  script (`run_estimation.py`) to the same file, so rerun, export and
  reproduce work unchanged; a file of a kind other than regression starts
  with `"result_kind": "<kind>"`. Each kind has a schema skill
  (`skills/files/data/<kind>-results-schema.md`) and deterministic checks:
  *descriptive* (summary statistics with ordered quantiles, distributions
  whose counts add up, figures declared in `figure_spec.json`), *timeseries*
  (fitted models with fit statistics, forecasts inside their intervals,
  out-of-sample RMSE and MAE with MAE <= RMSE), *spatial* (units, spatial
  statistics with their weights, Moran's I expectation -1/(n - 1), p from z,
  map specifications), *text* (corpus counts, term frequencies whose
  per-10,000 values follow from the counts, text-model outputs). The number
  check traces the paper's numbers to the kind's files, and `e2er verify`
  adds a `results contract` check for these kinds. Tables of statistics,
  bins, periods or terms are `records` tables in `table_spec.json` (see
  `skills/files/data/table-spec.md`); figures may be `scatter` and
  `histogram` besides the earlier types.
- **`causal = false`**: `identification_spec.json` is not required and not
  asked for, and a regression need not implement one.
- **`base_skill`** replaces `base/economist` wherever a specialist reads it.
- **`data_skills`** replaces the domain data skills of the data architect
  and analyst (`data/blockchain`, `data/crypto-defi`, `data/allium-cli`,
  `data/allium-developer-api`); the general connector skills stay.
- **The panel** is the template's `aggregate` step, now honoured as written
  (the six economics reviewers are the default panel). Two
  discipline-neutral reviewers can join it: `methods_reviewer` (whether the
  methods answer the question in the field's own terms) and
  `plausibility_reviewer` (whether the numbers are plausible in the domain).
  `review_weights` sets a reviewer's weight in the combined score; the
  mechanism rule applies only to a panel with a mechanism reviewer.
- **Polish** runs only the polish specialists the template's `polish` step lists.

A template that sets none of these runs exactly as before. What a template
changes is logged in the `template_components` event (`core`) and shown to
every specialist and the strategist as a short template block in their
context. `tests/fixtures/replay/exoplanet/pipelines/descriptive-study.toml` is
a complete descriptive template (the replay test runs it end to end on a
synthetic dataset).

## Credit

A template names the work it is based on, draws from or cites in `[[credit]]`
tables: the creator, the role (`conceptualization`, `method`, `related work`),
the relation (`based_on`, `related_work`, `cites`), the title, the address, the
dates it was published and read, and where it was found. `based_on` says where
the idea came from; it does not say its creator endorses the template. e2er's
own parts also list their credit in `credits.json` at the repository root, for
the catalogue of e2er.org.

A run records its template's credit in the `template_components` event, and
the dossier of a published run carries it as `credit`: the template's name and
the `[[credit]]` entries as the template file wrote them, so e2er.org can say
"Template based on …". A template without `[[credit]]` adds nothing to the
dossier.

```json
"credit": {
  "template": "field-map",
  "entries": [
    {"creator": "Michal Hron", "role": "conceptualization", "relation": "based_on",
     "title": "Map a research field with Claude: main path analysis, step by step",
     "url": "https://www.linkedin.com/pulse/…", "accessed": "2026-10-08", "…": "…"}
  ]
}
```

```toml
[[credit]]
creator   = "Michal Hron"
role      = "conceptualization"
relation  = "based_on"
title     = "Map a research field with Claude: main path analysis, step by step"
publisher = "LinkedIn Pulse"
published = "2026-10-08"
url       = "https://www.linkedin.com/pulse/map-research-field-claude-main-path-analysis-step-michal-hron-jm2ge/"
accessed  = "2026-10-08"
found_via = "shared by Björn Hanneke"
```

## `field-map`

Maps a research field by main path analysis. The workflow follows Michal Hron's
article "Map a research field with Claude: main path analysis, step by step"
(LinkedIn Pulse, 8 October 2026); this implementation is independent and uses
OpenAlex. Taken from the article: the six steps below and the pitfalls the
skill lists. e2er's own: the code (`src/modules/fieldmap`), the OpenAlex
retrieval, the handling of citation cycles, the exports, the steps and stops,
and the number-checked review. Hron's own implementation runs on Scopus
(github.com/michalhron/scopus-plus-mcp); nothing of it is used.

| Step | Kind | What happens |
|---|---|---|
| `design_boundary` | specialist | The boundary designer writes `field_boundary.json`: the main boundary (search terms with the topic's older names, OpenAlex source ids of a journal set, years) and 2 to 6 alternatives. `e2er-fieldmap count` and `e2er-fieldmap sources` read sizes and journal ids, one OpenAlex request each. |
| `retrieve_boundary` | check `field_retrieve` | Retrieves every boundary from OpenAlex: one request for the size (a boundary above `max_papers` is refused), then pages of 100 with cursor paging, at most `max_requests`, cached in `fieldmap/cache/`. Runs at every start; unchanged boundaries send no request. Each load is recorded in `data_sources.json` (OpenAlex, CC0, with OpenAlex's citation). |
| `review_boundary` | researcher | Approve or edit the boundaries, with the counts in `field_boundary_counts.md`. |
| `citation_network` | check `field_network` | The network of citations inside the main boundary (from the cited to the citing paper) and `completeness_report.md`: papers without internal links, without references, with short reference lists, probable duplicates, notices, broken cycles. Stops when more than `max_isolated_share` (default 50%) of the papers have no internal link, more than `max_missing_refs_share` (default 40%) have no references, or there are fewer than `min_papers` (default 100). The defaults come from five boundaries (see the calibration below). |
| `main_path` | check `field_main_path` | SPC weights (exact integers), the global main path (largest total SPC; ties all kept and counted), the local forward main path, key routes from the `key_routes` heaviest links (ties with the last included), the heaviest links (`main_path.md`). |
| `robustness` | check `field_robustness` | The same on every alternative boundary; papers on the main path of every boundary are robust (`robustness.md`). |
| `propose_lanes` | specialist | The lane mapper groups the mapped papers into 2 to 8 lanes named as questions (`field_lanes.json`), from titles and abstracts. |
| `review_lanes` | researcher | Approve or edit the lanes. |
| `draw_map` | check `field_map` | `figures/field_map.png`/`.svg`/`.pdf`, `reading_list.csv`/`.json`, `exports/` (Pajek `.net`, GEXF, VOSviewer map and network, CSV edges), `tables/field_map_summary.tex`, `tables/main_path_list.tex`, `field_map_results.json`; the methods' references go into `literature.bib`. |
| `write_review` | specialist | The review writer drafts `paper_draft.tex`, with every number from `field_map_results.json`. |
| `number_check`, `citation_check` | checks `numbers`, `citations` | The number check and the citation check on the draft, as steps of their own. |
| `review_draft` | researcher | Read the draft. |

Cycles: inside each group of papers that cite each other in a circle, only the
citations from an earlier to a later paper (year, date, OpenAlex id) are kept;
every dropped citation is listed in `completeness_report.json`. Nothing is
estimated, so the template has no estimation gate and no econometrics step.
Set `OPENALEX_API_KEY` (free) to use a key's own request budget instead of the
budget OpenAlex shares among keyless requests from one network.

### Calibration of the completeness stops

The stop values of `citation_network` were set on 2026-10-10 from five
boundaries (main boundary only, 31 OpenAlex requests for the four new ones):

| Boundary | Papers | Without internal links | Without references | Main path |
|---|---:|---:|---:|---:|
| main path analysis (scientometrics, 2026-10-08) | 346 | 18% | 15% | 17 papers |
| expectation-confirmation model / IS continuance (information systems) | 1,164 | 33% | 35% | 18 papers |
| Ricardian equivalence (economics) | 685 | 40% | 30% | 18 papers |
| wash trading (finance niche) | 62 | 58% | 44% | 5 papers, 8 tied |
| token airdrops (crypto niche) | 60 | 87% | 62% | 5 papers |

Established literatures stay at or below 40% without internal links and 35%
without references; the two niches are above 55% and 44%. The stops are set
between the groups: 50% and 40% (before: 60% and 25%; 25% would have stopped the
information-systems and economics boundaries). `skills/files/synthesis/main-path-analysis.md`
has the full table.

## `event-study-finance`

A fork of `empirical-preregistered` with one more step: the `event_window`
check, which runs inside the initial phase after the identification strategist,
the data architect and the data analyst, and before the econometrics specialist.
The identification strategist declares the events and windows in
`event_design.json` (schema in `skills/files/econometrics/event-study.md`). The
check fails, and the run stops before estimation, when

- the estimation window is shorter than `min_estimation_days` (default 120
  trading days) or ends fewer than `min_gap_days` (default 10) before the event
  window;
- more than `max_overlap_share` (default 0) of the events overlap in their event
  windows for the same firm or asset, and the design declares no treatment for
  overlaps (`drop`, `cluster` or `aggregate`);
- an event date is not a trading day in the data calendar the design names, or
  a window runs past the data.
- the design names the researcher's own event table (`events_source`) and its
  event dates are not exactly that table's dates; a date without trading maps
  to the next trading day, and the check's result lists each such mapping. Without
  `events_source`, a table in the data that looks like an event list only
  produces a warning.

The calendar is a table `data_dictionary.json` declares under `tables` and the data analyst
loaded; when it is not, the failure lists the tables in `data.db`. Before the pre-registration
freezes, the run also stops if anything has already been estimated, and after it freezes, a change to
the plan stops the run before the estimation until the researcher approves it as a deviation or puts the
plan back (see `researcher-step.md`).

The three settings are in the template, under the gate's `[steps.settings]`.
A failed check stops the run at the check with its reasons (`e2er review`
shows them): edit `event_design.json` or send the identification strategist
back, and the check runs again on resume. Approving does not pass it. Each
result is recorded like the other checks and appears in the dossier. With
`on_fail = "retry"` the identification strategist is sent back once with the
reasons before the run stops; with `"shadow"` the result is only recorded.

A gate step with `after = [...]` is how any check can sit inside the initial
phase; it also runs before a group that contains the econometrics specialist,
so a plan that leaves out one of the named specialists does not skip it.

## `replication`

A computational reproduction: rerun a published study with its own data and
code and compare every reported number with what the rerun produces
("reproduction tests rerun published studies", Brodeur et al., 2025; Kohler et
al., 2026). Robustness checks are a separate study. The question names the
Zenodo record:

```bash
e2er run "Computational reproduction of <paper title> (10.5281/zenodo.<id>)" --template replication
```

| Step | Kind | What happens |
|---|---|---|
| `fetch` | check `package_integrity` | The record is read from the public Zenodo API (no key). Every file is downloaded, verified against the checksum Zenodo publishes (MD5) and hashed with SHA-256; a mismatch fails the step. Archives are unpacked into `package/`, every unpacked file is hashed, and the tree is made read-only. PDF text goes to `package_text/`, page by page. All of it is in `package_manifest.json`. The step runs at every start: the package is re-hashed (one changed byte fails the step), and the paper the researcher supplies is staged (below). |
| `plan` | specialist `replication_planner` | Reads the README, the documentation and the code; lists the entry points in run order, the pinned image and the packages, maps every table and figure to its script and output, and records the targets at two levels (below). Writes `replication_plan.json` (schema `docs/schemas/replication_plan.schema.json`) and `replication_plan.md`. The plan is validated before the run uses it: pinned official image, interpreter plus package-relative script, no inline code, no shell. |
| `review_plan` | researcher | The run stops. Approve, edit the plan, or send the planner back. |
| `sandbox_run` | check `sandbox` | Runs the plan in Docker (below). Fails only when the sandbox cannot work (no Docker, invalid plan, image unavailable, package modified); a script that fails is a result. |
| `compare` | specialist `reproduction_comparer` | Levels each result by the protocol: reproduced, reproduced with minor differences, not reproduced, could not be run. Writes `reproduction_report.json` (schema `docs/schemas/reproduction_report.schema.json`) and `reproduction_report.md`. |
| `reproduction_gate` | check `reproduction` | Re-reads every reproduced number from the output file the report names (a CSV cell when a locator is given), requires that file to be one the run wrote, not one the package shipped, recomputes the differences, checks each level against them, and checks that every target is compared or listed as unassessed with a reason. Then it writes the counts and the environment into `reproduction_report.md` from the JSON (section "Counts and environment") and fails when the report's prose contradicts the JSON: a count that names its level, a table of counts, the label stated for a number, a package version. Writes `reproduction_check.json`. |
| `review_report` | researcher | The run stops for the researcher to read the report. |

The protocol both specialists follow is `skills/files/replication/reproduction-protocol.md`.

### Package versions: as of the package date

By default (`snapshot = "package-date"` in the sandbox step's settings) the
install phase installs packages as they were on the Zenodo record's
publication date: R packages from Posit Package Manager's dated CRAN snapshot
(the image's p3m URL with `/latest` replaced by the date, e.g.
`https://p3m.dev/cran/__linux__/noble/2026-08-30`, also written to
`Rprofile.site` so it is the repository inside the run), Python packages with
pip's `--uploaded-prior-to <date>T23:59:59Z`. `"latest"` installs the newest
and `"YYYY-MM-DD"` a given day. Versions the plan declares win: R installs them
with `remotes::install_version`, Python pins them with `==`. After the install a
no-network container of the committed image reports the repository, the
platform and every installed version, dependencies included; `sandbox_log.json`
records them under `snapshot`, `install.installed`, `install.platform` and
`declared_versions`, and the reproduction check copies them into
`reproduction_check.json`. The comparer's report states the snapshot and the
versions of the packages it discusses; the check compares each with the log.

### Strict labels

Each compared number is labelled by the protocol's thresholds, which the
reproduction check applies too: `reproduced` when equal at the target's own
precision (the printed decimals for the paper; within 1e-9 relative for a
full-precision package cell), `reproduced_minor` when at most
`minor_rel_tolerance` (10 %) off with the same sign, `not_reproduced`
otherwise; a result takes its worst number's label. The check also refuses a
reason text that says "equals" or "at full precision" when no compared number
is equal (or "differs" when all are), and one that states a cause as
established ("because", "due to", "caused by", "bug") instead of naming
possible causes.

### Two levels of targets

Every target in `replication_plan.json` has `level: 1` or `level: 2`, and the
report and the check treat the levels separately.

- **Level 1: the package's own result files.** Does the code rebuild them? The
  source is `{"kind": "package_file", "file", "locator": {"row", "column"}}`, a
  cell of a shipped `.csv`/`.tsv`. The plan contract reads the cell and refuses
  a value that is not there; the reproduction check reads the same cell of the
  rebuilt copy of that file.
- **Level 2: the published paper.** Does the rerun reproduce the printed
  numbers? Taken only from the paper: `{"kind": "paper", "document", "page",
  "table" | "figure", "decimals"}`. The contract checks that the printed value
  is on that page of the paper's extracted text and that `decimals` matches
  it.

Each result of `reproduction_report.json` carries `target_level` and compares
only targets of that level; every target of each level is compared or listed
as unassessed; `reproduction_check.json` counts each level separately.

### The paper, supplied by the researcher

Publishers often refuse automated downloads (SSRN answers 403), so the paper
is researcher input: save it as a PDF where the fetch step looks, in this
order — the `PAPER_PDF` setting, `paper.pdf` in a `LOCAL_DATA_DIR` folder, or
`data/paper.pdf` in the study's workspace. At the next start of the run the
fetch step copies it to `paper/paper.pdf` (read-only), records its SHA-256,
size, pages and original path under `paper` in `package_manifest.json`, and
extracts its text page by page (`pdftotext -layout` when installed, else
pypdf) into `paper_text/paper.pdf.txt` for the planner. The run logs a
`researcher_input` event, which the dossier lists as a researcher step
(`supplied_input`, with the SHA-256, and the one it replaces when the paper
changes). Without a paper there are no level-2 targets.

After supplying it at the plan review, send back the step `plan` or the
specialist `replication_planner`: the fetch step runs first either way, so the
planner works with the paper.

### The sandbox

- **Image**: the plan's pinned official image, `rocker/r-ver:X.Y.Z` or
  `python:X.Y[.Z]-slim`; its digest is logged.
- **Install phase** (network on): a container with no mounts at all installs
  the listed apt and R or Python packages, prints what was installed, and is
  committed as a local image (reused on resume). Only package managers run; no
  code from the package runs while the network is available.
- **Run phase**: the package is copied to `sandbox/run/`, the output folder.
  Each entry point runs in its own container with `--network none`,
  `--cpus`, `--memory` (no swap), `--pids-limit`, `--read-only` root file
  system with a `/tmp` tmpfs, `--cap-drop=ALL`, `no-new-privileges`, as user
  1000:1000, and a time limit (the container is removed when it runs over).
  The only mounts are the original package, read-only, at `/work/package`, and
  the output folder at `/work/run`. The home directory is never mounted.
- **Log**: `sandbox_log.json` holds each `docker` command, exit code, duration,
  the tails of stdout and stderr (full logs in `sandbox/logs/`), the installed
  versions, and the SHA-256 of every file the run wrote or changed. The package
  is re-hashed after the run.
- Scripts marked `needs_network` (downloaders) are skipped and their results
  become "could not be run".

Settings, in the template: `max_mb` (fetch, default 1000), `cpus`,
`memory_gb`, `timeout_minutes` per entry point and `install_timeout_minutes`
(sandbox), `minor_rel_tolerance` (reproduction, default 0.10). `fetch` and
`sandbox_run` block in every governance regime; `reproduction` follows the
regime like the other verification checks.

A `specialists` step whose name has no phase of its own in the runner
dispatches its `run` list with the registry's default work order
(`SPECIALIST_DEFAULT_FOCUS`), and a gate whose check runs as a step
(`package_integrity`, `sandbox`, `reproduction`) runs in sequence and halts
like a check inside the dispatch. A template without a `revision` step is
complete when its last step is done.
