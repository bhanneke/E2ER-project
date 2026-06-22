# Citing Numbers by JSON Source Key

> **Note on results tables.** Numbers in regression / results tables are no
> longer hand-written — they are rendered deterministically from the JSON
> sidecars via `table_spec.json` (see the `data/table-spec` skill), so a
> rendered table cell cannot drift from its source and needs no `% src:`
> comment. The rule below still governs every number you write in **prose**
> (abstract, body text, figure captions) and in any hand-written non-numeric
> table.

## The rule

Every numeric value you put in a paper — in the abstract, in body
text, in a table cell, in a figure caption — MUST trace back to a
value in one of the workspace's machine-readable JSON sidecars.

The sidecars are:

- `summary_statistics.json` — descriptive statistics on the assembled
  dataset (sample sizes, means, SDs, group counts, time coverage).
  Written by the `data_analyst`.
- `estimation_results.json` — regression coefficients, standard
  errors, t-statistics, p-values, confidence intervals, model
  diagnostics (R², F-stats). Written by the
  `econometrics_specialist`.
- `robustness_results.json` — same shape as estimation_results, used
  for the robustness section.
- `figure_spec.json` — numeric values that appear in figures.

If a number in your draft does not appear in one of these files, you
either invented it or you're citing a derived quantity that you have
not actually computed. Both are hard errors — the `verify_numbers`
gate runs before reviewers and rejects the paper at the audit gate
when numbers in LaTeX tables don't match the JSON sources.

## Citation convention

In the markdown / LaTeX source, mark every numeric citation with a
brief HTML comment naming the source file and dotted key path:

```latex
% The treatment effect <!-- src: estimation_results.json#main.coefficients.treatment.estimate -->
The treatment effect is $-0.231$ (s.e. $0.058$), statistically
significant at the $1\%$ level.
```

Or in a table:

```latex
\begin{tabular}{lcc}
\toprule
Variable & Coef & SE \\
\midrule
Treatment & -0.231 & 0.058 \\  % src: estimation_results.json#main.coefficients.treatment
Control X1 & 0.045 & 0.012 \\  % src: estimation_results.json#main.coefficients.x1
\bottomrule
\end{tabular}
```

The dotted-key path matches the JSON structure. So
`estimation_results.json#main.coefficients.treatment.estimate`
resolves to:

```json
{
  "main": {
    "coefficients": {
      "treatment": {"estimate": -0.231, ...}
    }
  }
}
```

These comments are invisible in the rendered PDF but make
verify_numbers's diagnostics actionable: when a mismatch fires, the
report quotes the source key and the operator can see exactly where
the drafter went wrong.

## When the sidecar is empty (or missing a value)

If `estimation_results.json` is `{}` — the econometrics specialist
ran but no estimation was performed (e.g. data acquisition failed) —
then the paper must NOT contain any regression coefficients. The
discipline:

1. Read the sidecar at the start of your work.
2. If it's empty, the paper is a "design without estimates" version:
   research question, identification strategy, model specification,
   data plan. **No** numbers in tables, **no** "the coefficient is
   X" claims, **no** invented placeholders like "X.XX".
3. Write the limitations section honestly: "Estimation could not be
   performed because [transparent reason from `data_summary.md`].
   The specification stands; results pending data access."

Inventing numbers to fill in the gaps — including pulling from prior
literature without attribution — violates the project's
data-integrity rule and will be caught by the gate.

## When you need a derived quantity

Some numbers in the paper are derived from sidecar values rather
than appearing directly. Examples:

- Percentage change: `(coef_after − coef_before) / coef_before × 100`
- Half-life: `−ln(2) / coef_persistence`
- Effect size in dollars: `coef × mean_y × n_observations`

For these:

1. Either add the derived quantity to the sidecar under a clear key
   (preferred) — request the data_analyst or econometrics specialist
   to compute it.
2. Or show the computation explicitly in a comment so a reader can
   reproduce it:
   ```latex
   The treatment increases revenue by $\$1.23M$ <!--
   computed: coef (-0.231) * mean_y (estimation_results#main.diagnostics.mean_y)
   * n (24890) — see /derived_quantities.md -->
   ```

When verify_numbers encounters a derived quantity that doesn't match
any sidecar value, it classifies it as `unverifiable` (not
`critical`) and does not fail the gate. But a reviewer will ask
where the number came from, so the comment is required for credibility.

## Tolerance

verify_numbers matches with a 0.5% relative tolerance by default, so
small rounding (0.231 vs 0.23) is fine. But:

- Sign must match. Writing "-0.231" as "0.231" is a sign flip and
  ALWAYS flagged critical.
- Integer values ≥10 must be exact. Writing N=12,451 instead of
  12,450 is a critical mismatch.

When in doubt: cite the source key and let verify_numbers tell you
whether the rounding works.

## Examples of right vs wrong

**Right.** Drafter reads `summary_statistics.json`, sees
`n_observations: 24890`, writes:

> The sample contains 24,890 pool-day observations
> <!-- src: summary_statistics.json#n_observations -->.

**Wrong (no source).** Drafter invents:

> The sample contains approximately 25,000 pool-day observations.

verify_numbers compares 25000 to 24890: relative error 0.4%, source
is integer ≥10 → must be exact → critical mismatch. Paper rejected
before reviewers.

**Right with empty sidecar.** `estimation_results.json` is `{}`:

> Estimation of the model in Section 3 could not be completed for
> this revision because [reason from data_summary.md]. The
> specification stands and the analysis is rerunnable once data
> access is restored.

**Wrong with empty sidecar.** Drafter writes:

> The main coefficient is -0.23 (s.e. 0.06).

These numbers cannot exist in the empty sidecar. Critical mismatches
on both → paper rejected.
