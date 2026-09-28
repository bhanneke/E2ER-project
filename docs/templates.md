# Templates

A template is a pipeline file in `pipelines/` (schema:
`docs/schemas/pipeline.schema.json`). A run follows the template chosen when the
paper is created; resume keeps it. e2er ships four:

| Template | For |
|---|---|
| `empirical` | Question and data in, empirical paper out. The default. |
| `empirical-preregistered` | `empirical` with a design review, a pre-registration frozen before estimation, and a review of the draft (see `researcher-step.md`). |
| `event-study-finance` | Abnormal-return event studies around announcements; checks the estimation window and overlapping events before estimation. |
| `replication` | Computational reproduction of a published study from its Zenodo replication package; the product is a reproduction report, not a paper. |

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
  to the next trading day, and the verdict lists each such mapping. Without
  `events_source`, a table in the data that looks like an event list only
  produces a warning.

The calendar is a table `data_dictionary.json` declares under `tables` and the data analyst
loaded; when it is not, the failure lists the tables in `data.db`. Before the pre-registration
freezes, the run also stops if anything has already been estimated (see `researcher-step.md`).

The three settings are in the template, under the gate's `[steps.settings]`.
A failed check stops the run at the check with its reasons (`e2er review`
shows them): edit `event_design.json` or send the identification strategist
back, and the check runs again on resume. Approving does not pass it. Each
verdict is recorded like the other checks and appears in the dossier. With
`on_fail = "retry"` the identification strategist is sent back once with the
reasons before the run stops; with `"shadow"` the verdict is only recorded.

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
| `plan` | specialist `replication_planner` | Reads the README, the documentation and the code; lists the entry points in run order, the pinned image and the packages, maps every table and figure to its script and output, and records the targets at two levels (below). Writes `replication_plan.json` (schema `docs/schemas/replication_plan.schema.json`) and `replication_plan.md`. The plan is validated before it is accepted: pinned official image, interpreter plus package-relative script, no inline code, no shell. |
| `review_plan` | researcher | The run stops. Approve, edit the plan, or send the planner back. |
| `sandbox_run` | check `sandbox` | Runs the plan in Docker (below). Fails only when the sandbox cannot work (no Docker, invalid plan, image unavailable, package modified); a script that fails is a result. |
| `compare` | specialist `reproduction_comparer` | Levels each result by the protocol: reproduced, reproduced with minor differences, not reproduced, could not be run. Writes `reproduction_report.json` (schema `docs/schemas/reproduction_report.schema.json`) and `reproduction_report.md`. |
| `reproduction_gate` | check `reproduction` | Re-reads every reproduced number from the output file the report names (a CSV cell when a locator is given), requires that file to be one the run wrote, not one the package shipped, recomputes the differences, checks each level against them, and checks that every target is compared or listed as unassessed with a reason. Writes `reproduction_check.json`. |
| `review_report` | researcher | The run stops for the researcher to read the report. |

The protocol both specialists follow is `skills/files/replication/reproduction-protocol.md`.

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
