# Writing the Reproduction Report

You compare what the sandbox run produced with the published numbers, one by
one, and level each result by the reproduction protocol. You do not rerun
anything.

## What you have

- `replication_plan.json` — the entry points, the exhibits, and `targets`: the
  published numbers with their pages. These are fixed; do not change them.
- `sandbox_log.json` — for each entry point: the command, `status` (`ok`,
  `failed`, `timed_out`, `skipped`), the exit code, the tail of stdout and
  stderr (full logs under `sandbox/logs/`), and `outputs`: every file the run
  wrote or changed, with its SHA-256. `install` records what was installed.
- `sandbox/run/` — the output folder: a copy of the package plus everything the
  run wrote. Only files listed in `sandbox_log.json` → `outputs` were written
  by the run. Every other file there is the package's own copy of a result;
  reading a number from one of those is not a reproduction.

## What to do

For every exhibit with targets:

1. Find the entry point that produces it and its status. Failed, timed out or
   skipped → `could_not_run`, with the error from the log in one sentence.
2. Open the output file the run wrote and find each target's number. Record
   the value you read and exactly where: the file path relative to
   `sandbox/run/`, and for a CSV a `locator` naming the row (column: value
   pairs that pick exactly one row) and the column. Copy the number as the
   file holds it; do not round it.
3. Compute `abs_diff` = reproduced − published, and level the result by the
   protocol: `reproduced`, `reproduced_minor`, `not_reproduced`,
   `could_not_run`.
4. A target you cannot assess (the output does not contain it, the value is
   only graphical) goes in `unassessed` with the reason.

## `reproduction_report.json`

```json
{
  "schema_version": 1,
  "study": {"title": "…", "zenodo_doi": "10.5281/zenodo.…"},
  "summary": {"reproduced": 3, "reproduced_minor": 1, "not_reproduced": 0, "could_not_run": 2},
  "results": [
    {
      "id": "table_2",
      "exhibit": "table_2",
      "level": "reproduced",
      "reason": "All four coefficients and standard errors equal the printed values at three decimals.",
      "entry_points": ["did"],
      "comparisons": [
        {
          "target_id": "t2_att_col1",
          "published": -0.012,
          "reproduced": -0.01214,
          "abs_diff": -0.00014,
          "source": {
            "file": "study_package/output/tables/did_main.csv",
            "locator": {"row": {"outcome": "y1", "estimator": "cs"}, "column": "att"}
          }
        }
      ]
    },
    {"id": "figure_3", "exhibit": "figure_3", "level": "could_not_run",
     "reason": "03_figures.R failed: package 'sf' not available.", "entry_points": ["figures"],
     "comparisons": [{"target_id": "f3_peak", "published": 0.04, "reproduced": null}]}
  ],
  "unassessed": [{"target_id": "t5_power", "reason": "the output does not report the power figure"}],
  "notes_for_robustness": ["…"]
}
```

Rules the reproduction check enforces (the run stops at the check if one is
broken):

- `published` is the plan's value for that target, unchanged.
- `reproduced` is a number read from `source.file`, a file the run wrote. With
  a `locator` the check reads that exact cell; without one it needs a number in
  the file that rounds to your value. Report the value with the decimals the
  file has.
- `abs_diff`, when given, is reproduced − published.
- `reproduced` requires every number of the result to equal the published one
  at the published precision; `reproduced_minor` requires every relative
  difference within the tolerance and no sign change; `could_not_run` has
  `reproduced: null` everywhere.
- Every target is either compared or listed in `unassessed` with a reason.

## `reproduction_report.md`

For the researcher: one line per exhibit with its level; then per exhibit the
compared numbers (published, reproduced, difference, file); what could not
run and why (from the logs); the environment actually used (image, digest,
installed versions against the documented ones); and notes for a robustness
study, kept separate from the levels.
