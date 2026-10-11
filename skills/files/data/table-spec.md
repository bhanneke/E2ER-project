# Table Specification Format

When producing a results table, output a `table_spec.json` file that declares
the table's STRUCTURE. A regression table has specifications as columns and
coefficients / statistics as rows (below); a table of statistics, categories or
periods has entries of the results as rows (`"layout": "records"`, further
below). The pipeline fills the numbers
**deterministically from `estimation_results.json` and `robustness_results.json`**
and renders publication-quality LaTeX into `tables/<filename>.tex`.

**Do NOT hand-write the numbers in results tables.** Do not type coefficients,
standard errors, R², or N into LaTeX yourself. You author the spec; code fills
the values from the same JSON the econometrics specialist computed, so the
numbers cannot drift from the source.

In the body of the paper, reference each rendered table by `\input` and `\ref`:

```latex
See Table~\ref{tab:main}.
...
\input{tables/main.tex}
```

The `label` you give in the spec is the one `\ref{}` points to. The `filename`
you give is the one you `\input`. They must match exactly.

## Structure

```json
{
  "tables": [
    {
      "filename": "main.tex",
      "label": "tab:main",
      "caption": "In-sample and out-of-sample predictability of the equity premium",
      "columns": [
        {"spec_key": "dp_full", "header": "Dividend-price"},
        {"spec_key": "dy_full", "header": "Dividend yield"},
        {"spec_key": "tms_full", "header": "Term spread"}
      ],
      "rows": [
        {"type": "coefficient", "var": "dp",  "label": "$\\hat\\beta$"},
        {"type": "stat", "field": "r_squared",    "label": "In-sample $R^2$", "decimals": 4},
        {"type": "stat", "field": "oos_r_squared","label": "OOS $R^2$",       "decimals": 4},
        {"type": "stat", "field": "clark_west_stat","label": "Clark--West"},
        {"type": "stat", "field": "n_observations", "label": "$N$", "decimals": 0}
      ],
      "notes": "HAC (Newey--West) standard errors in parentheses. */**/*** denote significance at the 10/5/1\\% levels."
    }
  ]
}
```

## Columns

Each column names one `spec_key` — a top-level key in `estimation_results.json`
or `robustness_results.json` (e.g. `dp_full`, `tbl_post2008`,
`dp_full_ct_restricted`). The `header` is the column title you want printed.
**Use real keys only.** A `spec_key` that doesn't exist renders an empty
column (`---`) and is flagged in `table_render_report.json` — it is a visible
error, not a silent one, but it means a missing column, so get the keys right.

## Rows

Each row resolves a value within every column's spec object:

- `{"type": "coefficient", "var": "<name>"}` — renders
  `spec.coefficients.<name>.estimate` with significance stars from its
  `p_value`, and the standard error `spec.coefficients.<name>.se` in
  parentheses on the line below. Set `"se": false` to suppress the SE line.
  `<name>` must be a real key under that spec's `coefficients` (the predictor
  variable name). **Use `"var": "*"` when each column is a different
  single-predictor specification** (e.g. one column per predictor): `*` means
  "this column's own primary coefficient", so one β̂ row renders the right
  coefficient for every column. Specs with an empty `coefficients` block (e.g.
  forecast combinations) render `---` for coefficient rows — that's expected.
- `{"type": "stat", "field": "<name>"}` — renders a scalar, looked up in the
  spec's `diagnostics`, then `forecast_evaluation`, then the spec top level.
  Covers `r_squared`, `adj_r_squared`, `oos_r_squared`, `clark_west_stat`,
  `n_observations`, etc.

`"decimals"` controls formatting (default 3; use 0 for integer counts like
`N`). A field that is `null` in the source renders `---` (a legitimately
undefined statistic); a field that is absent everywhere renders `---` AND is
flagged as unresolved.

## Rules

1. **Numbers come from code, never from you.** Author structure + labels +
   caption + notes only.
2. **Read `estimation_results.json` first and use its EXACT keys.** Open the
   file, look at the top-level spec keys and the field names inside
   (`coefficients`, `diagnostics`, `forecast_evaluation`), and copy them
   verbatim into `spec_key` / `var` / `field`. The econometrics specialist
   chooses the names — e.g. it may write `full_dp` (not `dp_full`) and
   `clark_west_stat` (not `cw_stat`). Do not guess or abbreviate. The renderer
   will auto-correct pure word-order differences (`dp_full` ↔ `full_dp`), but
   it cannot invent a field that isn't there — a wrong/abbreviated name renders
   `---` and is reported in `table_render_report.json`. After rendering, if
   that report lists unresolved references, fix your `table_spec.json` to use
   the exact keys it lists as available.
3. **Check the spec before you finish: run `e2er-check-tables`.** It renders
   your `table_spec.json` against the analysis JSON and prints every reference
   that did not resolve, together with the field names each column's object
   actually has. It takes no arguments. Exit 0 means everything resolved; exit
   1 lists what to fix. Iterate until it exits 0 — do not hand back a spec you
   have not checked.

   The renderer LOOKS UP each field inside its own column's object and never
   computes. So a 'Change' / 'Difference' / '% change' column cannot ask for
   the same fields as the level columns; it can only use keys that already
   exist in that object, such as `delta_*` / `pct_change_*`. If the comparison
   you want has not been computed, ask for it in the analysis rather than
   naming a field that is not there.

   Every `{"type": "stat"}` row needs a non-empty `field`. A row with an
   empty `field` resolves to nothing and is reported as unresolved.
4. `filename` ends in `.tex`, has no path separators, and is what you `\input`.
5. `label` is what you `\ref`. Keep them consistent across the spec and prose.
6. One table per results display (main results, robustness, …). Put each in its
   own entry in the `tables` list.
7. `caption`, `notes`, `header`, and row `label` are LaTeX — write them as you
   want them typeset (math like `$R^2$` is fine).

## Tables of statistics, categories and periods (`"layout": "records"`)

Not every results table has specifications as columns. A table of summary
statistics has one row per variable; a distribution one row per bin or
category; a forecast one row per period; a spatial study one row per
statistic or unit; a text study one row per term. Declare such a table with
`"layout": "records"`: its rows are the entries found at `path` (an object of
objects, or a list of objects) inside `source`, and its columns are fields of
each entry.

```json
{
  "filename": "summary.tex",
  "label": "tab:summary",
  "caption": "Summary statistics of the planet sample",
  "layout": "records",
  "source": "estimation_results.json",
  "path": "statistics",
  "rows": ["radius_earth", "period_days"],
  "row_labels": {"radius_earth": "Radius ($R_\\oplus$)", "period_days": "Orbital period (days)"},
  "row_header": "Variable",
  "columns": [
    {"field": "n", "header": "$N$", "decimals": 0},
    {"field": "mean", "header": "Mean", "decimals": 2},
    {"field": "median", "header": "Median", "decimals": 2},
    {"field": "sd", "header": "SD", "decimals": 2}
  ]
}
```

- `source`: `estimation_results.json` (default), `robustness_results.json`
  or `summary_statistics.json`.
- `path`: dotted path to the entries, e.g. `statistics`,
  `distributions.radius.bins`, `forecasts.arima_2025.points`,
  `term_frequencies.all.terms`. List items are reached by number
  (`models.0`).
- `rows` (optional): which entries, in this order (object keys; for a list,
  the value of `key_field`). Without it, every entry in file order.
- `key_field` (for a list): the field that names each row (`period`,
  `term`, `category`); without it rows are numbered.
- `row_labels` (optional): LaTeX labels for row names; otherwise the name
  is printed as text. `row_header` heads the first column.
- `columns`: each names a `field` of the entry (dotted for nested fields,
  `_key` for the row's own name), its `header` and `decimals`. Text values
  are printed as text.

Same rules as above: you write the structure, code fills the values,
`e2er-check-tables` lists what did not resolve. A row label that is a bare
number (a year) is read by the number check like any cell; label periods with
the period as the results write it (`2025-01`) or in words.

## What still goes in hand-written LaTeX

Only **non-numeric / structural** tables (a conceptual 2×2, a variable-
definition table) may be written by hand. Anything whose cells are numbers
from the JSON sidecars MUST go through `table_spec.json`.
