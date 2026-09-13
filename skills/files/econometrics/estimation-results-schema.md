# `estimation_results.json` — Econometrics Specialist Sidecar

## Purpose

When you actually run estimation (not just specify the model on
paper), you write the point estimates, standard errors, test
statistics, and diagnostic numbers to a machine-readable JSON file:
`estimation_results.json`. Robustness specifications go into the
optional `robustness_results.json`.

Two consumers depend on this file:

1. **`verify_numbers` gate** — every coefficient, standard error,
   t-statistic, p-value, R² in the paper's regression tables must
   match a value in this file. Mismatches with relative error >10%
   are flagged critical and the paper is rejected before reviewers
   run.
2. **`paper_drafter` and `latex_formatter`** — read this to build the
   regression tables in the paper. Without it, table cells have no
   source of truth and the drafter must invent.

## When to write this file

- Write it whenever you have actually estimated a model and obtained
  numeric output (point estimates, SEs, etc.).
- If you only specified the model (wrote down the equation, fixed
  effects, instrument strategy) and did not run estimation against
  real data, write `estimation_results.json` as `{}` rather than
  fabricating values. The empty file is the honest signal.

## How estimation actually runs — write a script, the runner executes it

You do **not** have a general code-execution tool: you can read data and
write files, but you cannot run Python yourself. That is by design. So
the way to "run estimation" is:

1. Write your estimation code as a script named **exactly
   `run_estimation.py`** in the workspace root. It must read the
   workspace data files and write its numeric output to **exactly
   `estimation_results.json`**.
2. Finish your turn. After you return, the **runner executes
   `run_estimation.py` for you** and validates that
   `estimation_results.json` came out populated. The run is logged to
   `run_estimation.log` (exit code + stdout/stderr) for the next reviewer.

Naming matters: the runner looks for `run_estimation.py` →
`estimation_results.json` first. If you must use other names it will try
to discover the script by content, but the canonical names are the
reliable path — use them.

This means: when the workspace has data, the correct action is almost
always **write `run_estimation.py`**, not give up. "I could not run
estimation" is only true when there is genuinely no data to estimate on.

## Your primary specification must be IDENTIFIED, not a raw gap

The FIRST / headline specification you report must implement the design in
`identification_strategy.md` — its fixed effects, controls, and clustering.
A raw, unconditional difference in means (a two-coefficient `const + treatment`
regression with no fixed effects or controls) is at most a *descriptive
baseline*; reporting it as the main result is the single most common reason
these papers score low on identification. Put the identified specification
under the top-level key **`main`** (mandatory name — the export and the
contract gate assume it), and make its `diagnostics` reflect what was actually
estimated (fixed-effects absorbed, number of clusters, within-R²) — not nulls.

**This is deterministically enforced when `identification_spec.json` exists
in the workspace** (the identification strategist writes it — read it before
you estimate). The gate checks that your `main` entry ECHOES the declared
design:

- `main.fixed_effects` — a list naming every fixed effect actually absorbed;
  must include all FE declared in the spec's `primary.fixed_effects`.
- `main.controls` — a list naming the included controls (declared controls
  may alternatively appear directly among `coefficients` keys).
- `main.cluster_level` + `main.n_clusters` — required and matching when the
  spec declares clustering.

Echo what you ACTUALLY estimated. If the declared design turns out to be
inestimable (e.g. the FE absorb all treatment variation), do not silently
substitute a weaker spec under `main` — the gate will reject it. Follow the
spec's `fallback` if one is declared, or state the problem explicitly in
`econometric_spec.md` and put the honest spec under a non-`main` key so the
mismatch is visible rather than laundered.

## Required shape

A JSON object with one entry per estimated specification. Each entry
contains coefficients and diagnostics.

**Mandatory top-level structure:**

```json
{
  "main": {
    "specification": "OLS with two-way fixed effects",
    "n_observations": 24890,
    "n_clusters": 6225,
    "cluster_level": "unit",
    "fixed_effects": ["unit", "time"],
    "controls": ["x1"],
    "coefficients": {
      "treatment": {
        "estimate": -0.231,
        "se": 0.058,
        "t_stat": -3.98,
        "p_value": 0.0001,
        "ci_lower": -0.345,
        "ci_upper": -0.117
      },
      "x1": {
        "estimate": 0.045,
        "se": 0.012,
        "t_stat": 3.75,
        "p_value": 0.0002,
        "ci_lower": 0.022,
        "ci_upper": 0.068
      }
    },
    "diagnostics": {
      "r_squared": 0.34,
      "adj_r_squared": 0.32,
      "f_statistic": 45.2,
      "df_residual": 24850
    }
  }
}
```

**Conventions:**

- The top-level key (e.g. `main`, `iv_2sls`, `did_event_study`)
  identifies the specification. Use the same name in the markdown
  spec and the paper's table column header.
- Coefficient names match the variable names in your data dictionary.
  Use snake_case; do not use the LaTeX-prettified labels here (those
  belong to the LaTeX formatter).
- Standard errors are clustered by default. The `cluster_level` field
  documents the clustering choice when it's not obvious.

**Per-specification optional fields:**

- `cluster_level`: `"unit"`, `"time"`, `"unit_and_time"`, `"none"`,
  or a specific variable name.
- `first_stage`: nested object with first-stage F, partial R², and
  weak-instrument diagnostics (for IV/2SLS).
- `pre_trend_p_value`, `placebo_p_value`: for DiD/event-study.
- `cragg_donald_f`, `kleibergen_paap_f`: standard IV diagnostics.

**Add specifications as additional top-level keys.** A paper with main
+ heterogeneity by year + robustness with controls dropped is three
entries:

```json
{
  "main":            { ... },
  "by_year_2024":    { ... },
  "no_controls":     { ... }
}
```

## `robustness_results.json` — conditional sidecar

When the paper reports robustness checks beyond the main specification
(alternative samples, alternative controls, alternative SE clustering,
placebo tests), write them to `robustness_results.json` with the same
shape. The split between `estimation_results.json` and
`robustness_results.json` is a courtesy to readers — both files are
consumed identically by verify_numbers and the drafter.

Do NOT duplicate the main spec into both files. Each value should
appear exactly once across the two files.

### Every spec object needs the same scalars — tables render in ROWS

A results table has one column per specification and one row per
statistic, and the renderer fills a row across *every* column. So a
scalar that exists for `main` but not for your robustness entries
leaves that row half-empty — and an unresolvable reference halts the
render rather than shipping a table with blank cells.

Concretely: if you report `n_observations`, sample counts
(`n_pre_treatment` / `n_post_treatment`), a threshold, or any other
sample-defining scalar for `main`, report **the same fields under the
same names for every other spec object**, in both files. Recompute them
for that specification — do not copy `main`'s value across, because an
alternative measure or sample generally has a different N.

```json
{
  "rv5_measure": {
    "specification": "5-day realized volatility threshold",
    "n_observations": 415,
    "n_pre_treatment": 192,
    "n_post_treatment": 223,
    "threshold_percentile": 75,
    "delta_p_HH": 0.018
  }
}
```

The headline estimate alone is not enough. A robustness column carrying
only its point estimate cannot be tabulated next to `main`.

### Report every robustness check you specified

If `econometric_spec.md` declares seven robustness checks, the sidecar
should carry seven entries. Declaring checks in prose and emitting two
of them is the same failure as writing `{}` while data is available:
the paper claims work the artifacts do not contain. If a check turned
out to be infeasible, say so explicitly in `econometric_spec.md` rather
than silently dropping it.

## Rules

1. **Plain numbers, not strings.** `-0.231`, not `"-0.231"` and not
   `"−0.231"` with a unicode minus.
2. **Use `null` for genuinely missing diagnostics** (e.g. r_squared
   is undefined for some non-OLS estimators).
3. **No `NaN` or `Infinity`.** Use `null` if a diagnostic is
   undefined.
4. **Coefficient signs must match the paper.** A drafter that writes
   "treatment increases the outcome by 0.23" while
   `estimation_results.json` reports `estimate: -0.23` is a critical
   mismatch (sign flip) — verify_numbers will catch it.
5. **Cite by key in the markdown.** When `econometric_spec.md` says
   "the treatment effect is -0.23 (SE 0.06, p < 0.001)", the trio
   `-0.23 / 0.058 / 0.0001` must appear in this file under a path
   that traces back from the citation. Convention:
   `> Source: estimation_results.json#main.coefficients.treatment`.

## Failure modes — write `{}` only when estimation is genuinely impossible

`{}` is the honest signal **only** when there is no data to estimate on
(no usable files in the workspace). When data IS present, do not write
`{}` and stop — write `run_estimation.py` (see above) and let the runner
execute it. Writing `{}` while data is available, instead of writing the
script, is the M4 failure mode and will fail the output-contract check.

If estimation is genuinely impossible (no data):

- Write `estimation_results.json` as `{}`.
- The drafter sees an empty JSON and produces a "design without
  estimates" version of the paper (specification + identification +
  data summary, but no numbers in tables).
- `robustness_results.json` should not be created at all in this
  case.

Inventing coefficients and putting them in this file is a hard
violation of the project's data-integrity rule.

## Example for an IV/2SLS paper

```json
{
  "ols_naive": {
    "specification": "OLS, no controls",
    "n_observations": 12450,
    "coefficients": {
      "treatment": {"estimate": 0.18, "se": 0.04, "t_stat": 4.50, "p_value": 0.0001}
    },
    "diagnostics": {"r_squared": 0.08}
  },
  "iv_2sls": {
    "specification": "2SLS with instrument Z, controls X1+X2",
    "n_observations": 12450,
    "n_clusters": 6225,
    "cluster_level": "unit",
    "coefficients": {
      "treatment_hat": {"estimate": -0.23, "se": 0.06, "t_stat": -3.83, "p_value": 0.0001},
      "x1": {"estimate": 0.04, "se": 0.01, "t_stat": 4.00, "p_value": 0.0001}
    },
    "first_stage": {
      "cragg_donald_f": 45.2,
      "kleibergen_paap_f": 38.1,
      "instrument_partial_r_squared": 0.18
    },
    "diagnostics": {"r_squared": 0.34}
  }
}
```

The drafter writes "the 2SLS estimate is -0.23 (SE 0.06, first-stage
F = 38.1)" and every number traces to this file.
