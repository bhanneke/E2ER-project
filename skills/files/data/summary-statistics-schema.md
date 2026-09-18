# `summary_statistics.json` — Data Analyst Sidecar

## Purpose

After the data acquisition + cleaning + variable construction is
complete, you write the descriptive statistics of the assembled
analysis dataset to a machine-readable JSON file: `summary_statistics.json`.

Two consumers depend on this file:

1. **`verify_numbers` gate** — runs before reviewers and compares every
   number in the paper's LaTeX tables against the flattened numeric
   values in this file. A draft that cites a sample size of 12,450 or
   a mean of 0.42 must have those numbers traceable here. Numbers in
   the paper that don't match are flagged as critical mismatches and
   the paper is rejected before reviewers spend tokens.
2. **`paper_drafter`** — reads this file to populate the descriptive
   statistics section and the first column of Table 1. Without it,
   the drafter has nothing to cite by reference and must invent.

## Required shape

A JSON object whose leaves are numeric. Nested grouping is encouraged
for readability but not required. The verify_numbers gate flattens
the structure to dotted keys
(e.g. `treatment.n`, `outcome.mean.full_sample`), so any layout works.

**Mandatory top-level fields:**

```json
{
  "n_observations": 12450,
  "n_units": 6225,
  "time_coverage": {
    "start_iso": "2024-01-01",
    "end_iso": "2024-12-31",
    "n_periods": 365
  },
  "outcome": {
    "mean": 0.42,
    "sd": 0.18,
    "min": 0.0,
    "p25": 0.30,
    "median": 0.41,
    "p75": 0.55,
    "max": 1.0
  }
}
```

**Mandatory: `sample_flow` (the sample-construction record).**
Referees consistently dock the data score when there is no record of how the
estimation sample was built from the raw data — a "sample-flow table" is the
data-review standard. Document each inclusion/exclusion filter, in order, with
the row count remaining after it and the number dropped. Build it from
`e2er-data query` (or `query_data`) `COUNT(*)` before/after each filter — the
SAME filters your estimation script applies:

```json
"sample_flow": [
  {"step": "raw rows", "n": 2109829, "dropped": 0},
  {"step": "drop null/zero price", "n": 2087340, "dropped": 22489},
  {"step": "restrict to outright sales (event_type='sale')", "n": 1950122, "dropped": 137218},
  {"step": "final estimation sample", "n": 1950122, "dropped": 0}
]
```

The last step's `n` should equal `n_observations`. Also report how missing
values were handled (dropped vs. coded zero) — referees flag silent
`col IS NOT NULL` drops.

**Conditionally required:**

- If the paper uses a treatment/control comparison:
  ```json
  "by_group": {
    "treated":  {"n": 6225, "mean_outcome": 0.42, "sd_outcome": 0.18},
    "control":  {"n": 6225, "mean_outcome": 0.50, "sd_outcome": 0.16}
  }
  ```
- If you constructed any derived variables (winsorized, log-transformed,
  standardized) report descriptive stats for the constructed version
  under a named key matching what you cite in the markdown.

**Extension is encouraged.** Add any descriptive statistic that the
paper text cites or that a referee might reasonably ask for. The
verify_numbers gate handles arbitrary depth; the drafter benefits
from richer information.

## Rules

1. **Numeric leaves only.** Don't put strings, lists of strings, or
   booleans in places where a number belongs. Sample sizes are
   integers; means and SDs are floats.
2. **Plain numbers, not strings.** Write `0.42`, not `"0.42"`.
   Verify_numbers parses the JSON and skips string values.
3. **Use `null` for genuinely missing data**, not `"N/A"` or `-999`.
   Sentinel numbers will be picked up as real values by downstream
   readers.
4. **No `NaN` or `Infinity`** — these aren't valid JSON. Use `null`
   if the statistic is undefined.
5. **Cite by key in the markdown.** When `data_summary.md` says "the
   sample contains 12,450 pool-day observations", the value `12450`
   MUST appear in `summary_statistics.json` under a key that anyone
   reading both files can trace. The convention is to flag the
   citation:
   `> Source: summary_statistics.json#n_observations`.

## Failure modes — write an empty JSON, not no file

If the data acquisition step failed (Allium quota exhausted,
specification asked for a table you can't access, etc.) and you are
writing a transparent failure report in `data_summary.md`:

- Still produce `summary_statistics.json`, with value `{}`.
- This signals to verify_numbers that the file was emitted on purpose
  and contains nothing to verify against — distinct from "the file
  was never created" (which would block the gate from running at
  all).
- The drafter sees an empty JSON, knows there's nothing to cite, and
  produces a paper without quantitative claims.

Writing `{}` is the correct, honest signal. Inventing plausible
numbers and putting them in this file is a hard violation of the
project's data-integrity rule.

## Example for a panel-data paper

```json
{
  "n_observations": 24890,
  "n_units": 6225,
  "n_periods_per_unit_mean": 4.0,
  "time_coverage": {
    "start_iso": "2024-01-01",
    "end_iso": "2024-12-31",
    "n_periods": 365
  },
  "outcome": {
    "y": {
      "mean": 0.4231,
      "sd":   0.1842,
      "min":  0.0,
      "p25":  0.30,
      "median": 0.41,
      "p75":  0.55,
      "max":  1.0
    }
  },
  "treatment": {
    "share_treated": 0.50,
    "treated":  {"n_units": 3112, "n_obs": 12450, "mean_y": 0.42, "sd_y": 0.18},
    "control":  {"n_units": 3113, "n_obs": 12440, "mean_y": 0.50, "sd_y": 0.16}
  },
  "controls": {
    "x1": {"mean": 1.23, "sd": 0.45},
    "x2": {"mean": 4.56, "sd": 0.78}
  },
  "missingness": {
    "y_pct_missing": 0.02,
    "x1_pct_missing": 0.00,
    "x2_pct_missing": 0.15
  }
}
```

The drafter can then write "Table 1 reports descriptive statistics for
the 24,890 pool-day observations across 6,225 pools…" and every
number in that sentence traces back to this file.
