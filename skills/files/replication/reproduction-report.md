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

Do it twice, once per target level, and keep the two apart: level 1 (the
package's own result files, rebuilt) and level 2 (the numbers printed in the
paper). Each result in the report carries `target_level`, and every number it
compares is a target of that level. An exhibit with targets at both levels
gets two results (e.g. `table_2_l1` and `table_2_l2`).

For every exhibit with targets:

1. Find the entry point that produces it and its status. Failed, timed out or
   skipped → `could_not_run`, with the error from the log in one sentence.
2. Open the output file the run wrote and find each target's number. Record
   the value you read and exactly where: the file path relative to
   `sandbox/run/`, and for a CSV a `locator` naming the row (column: value
   pairs that pick exactly one row) and the column. Copy the number as the
   file holds it; do not round it. For a level-1 target the file is the
   rebuilt copy of the target's own file (same path) and the locator is the
   plan's, so the same cell is compared.
3. Compute `abs_diff` = reproduced − published and the relative difference,
   and label each number strictly by the protocol's thresholds (`label` on the
   comparison): `reproduced` only when equal at the target's own precision
   (level 2: the printed decimals; level 1: within 1e-9 relative),
   `reproduced_minor` when at most 10 % off with the same sign,
   `not_reproduced` otherwise. The result's `level` is its worst number's
   label. The check recomputes all of it and stops the run on any
   disagreement.
4. Write the reason from the numbers (which number, how far off). Name causes
   only as possible ones, with what points to them (an unpinned dependency, no
   seed before a bootstrap, a different platform); never "because", "due to",
   "caused by". Never write "equals" or "at full precision" about a number that
   differs.
5. Copy the environment from `sandbox_log.json` into the report's
   `environment` block: `snapshot` (`date`, `url`), `platform`, and
   `installed` (every package and version in `install.installed`, including
   dependencies). The check compares it with the log entry by entry.
6. A target you cannot assess (the output does not contain it, the value is
   only graphical) goes in `unassessed` with the reason.

## `reproduction_report.json`

```json
{
  "schema_version": 1,
  "study": {"title": "…", "zenodo_doi": "10.5281/zenodo.…"},
  "summary": {
    "level_1": {"reproduced": 2, "reproduced_minor": 0, "not_reproduced": 0, "could_not_run": 1},
    "level_2": {"reproduced": 1, "reproduced_minor": 1, "not_reproduced": 0, "could_not_run": 1}
  },
  "results": [
    {
      "id": "table_2_l2",
      "exhibit": "table_2",
      "target_level": 2,
      "level": "reproduced",
      "reason": "All four coefficients and standard errors equal the printed values at three decimals.",
      "entry_points": ["did"],
      "comparisons": [
        {
          "target_id": "l2_att_col1",
          "published": -0.012,
          "reproduced": -0.01214,
          "abs_diff": -0.00014,
          "rel_diff": 0.0117,
          "label": "reproduced",
          "source": {
            "file": "study_package/output/tables/did_main.csv",
            "locator": {"row": {"outcome": "y1", "estimator": "cs"}, "column": "att"}
          }
        }
      ]
    },
    {"id": "figure_3_l2", "exhibit": "figure_3", "target_level": 2, "level": "could_not_run",
     "reason": "03_figures.R failed: package 'sf' not available.", "entry_points": ["figures"],
     "comparisons": [{"target_id": "f3_peak", "published": 0.04, "reproduced": null, "label": "could_not_run"}]}
  ],
  "environment": {
    "snapshot": {"date": "2026-08-30", "url": "https://p3m.dev/cran/__linux__/noble/2026-08-30"},
    "platform": "aarch64-unknown-linux-gnu",
    "installed": {"did": "2.5.1", "DRDID": "1.3.0", "fixest": "0.14.2", "…": "every package in sandbox_log.json"}
  },
  "unassessed": [{"target_id": "t5_power", "reason": "the output does not report the power figure"}],
  "notes_for_robustness": ["…"]
}
```

Rules the reproduction check enforces (the run stops at the check if one is
broken):

- Every result has `target_level` (1 or 2) and compares only targets of that level.
- `published` is the plan's value for that target, unchanged.
- Each comparison's `label` and each result's `level` follow the protocol's
  thresholds exactly; the reason text does not contradict the numbers and
  names causes only as possible ones.
- `environment` matches `sandbox_log.json`: snapshot date and URL, and every
  installed package with its version.
- A level-1 number is read from the rebuilt copy of the target's own file.
- `reproduced` is a number read from `source.file`, a file the run wrote. With
  a `locator` the check reads that exact cell; without one it needs a number in
  the file that rounds to your value. Report the value with the decimals the
  file has.
- `abs_diff`, when given, is reproduced − published.
- `reproduced` requires every number of the result to equal the published one
  at the published precision; `reproduced_minor` requires every relative
  difference within the tolerance and no sign change; `could_not_run` has
  `reproduced: null` everywhere.
- Every target, at each level, is either compared or listed in `unassessed`
  with a reason.

## `reproduction_report.md`

For the researcher, level 1 and level 2 in separate sections: one line per
exhibit with its level; then per exhibit the
compared numbers (published, reproduced, difference, file); what could not
run and why (from the logs); the environment actually used (image, digest,
platform, package snapshot date and URL, installed versions against the
documented ones, including dependencies the package does not declare); the
possible causes of each difference, named as possible; and notes for a robustness
study, kept separate from the levels.
