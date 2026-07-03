# `identification_spec.json` — Identification Strategist Sidecar

## Purpose

Your prose strategy in `identification_strategy.md` is read by humans and
reviewers. This sidecar is its **machine-readable core**: the one primary
specification the paper stands on, declared precisely enough that the
pipeline can verify — deterministically, without a reviewer — that the
econometrics specialist actually estimated it.

Two consumers depend on this file:

1. **The identified-spec contract gate** — the econometrics specialist's
   headline entry (`main` in `estimation_results.json`) must echo the
   fixed effects, controls, and clustering you declare here. If it
   reports a raw gap instead of your identified design, the gate rejects
   it mechanically and the specialist retries with the mismatch spelled
   out.
2. **Reviewers and the drafter** — a compact, unambiguous statement of
   the design the rest of the paper must be consistent with.

## Required shape

Write BOTH files: `identification_strategy.md` (prose, as before) AND
`identification_spec.json`:

```json
{
  "primary": {
    "estimator": "twfe_ols",
    "unit_of_analysis": "collection-month",
    "outcome": "royalty_rate",
    "treatment": "aggregator_share",
    "fixed_effects": ["collection", "month"],
    "controls": ["log_volume", "collection_age"],
    "cluster_level": "collection",
    "identifying_assumption": "Within-collection changes in aggregator share are unrelated to unobserved royalty-rate trends conditional on the FE."
  },
  "fallback": {
    "estimator": "ols",
    "fixed_effects": ["month"],
    "controls": [],
    "cluster_level": "collection",
    "when": "If collection FE absorb all treatment variation."
  }
}
```

Only `primary` is enforced; `fallback` is optional documentation for the
econometrics specialist.

## Naming rules — these strings are matched mechanically

- `fixed_effects` and `controls` entries are **variable-level names in
  snake_case**, matching what the data actually contains (check the data
  dictionary / Local Data Warehouse catalog) — not prose ("collection
  fixed effects") and not LaTeX.
- Matching is normalization-tolerant (case and punctuation are ignored:
  `Collection` ≡ `collection`) but NOT fuzzy: `month` does not match
  `year_month`. Declare the name the estimation will actually use.
- `cluster_level`: `"unit"`, `"time"`, `"unit_and_time"`, `"none"`, or a
  specific variable name — same vocabulary as
  `estimation_results.json`.

## Honesty rules

- Declare the design you actually argue for in the prose — the two files
  must describe the SAME primary specification.
- Empty lists are legitimate: a clean natural experiment may need no
  controls; a pure cross-sectional design has no fixed effects. Declare
  `[]` rather than padding the design to look rigorous. `"cluster_level":
  "none"` is likewise honest for designs without clustered errors.
- Do NOT declare fixed effects or controls the data cannot support (a
  variable that doesn't exist can never be echoed back, and the
  econometrics specialist will be caught between your declaration and
  reality). When in doubt, check the data catalog first.

## Failure modes

- **Prose-only output** (writing `identification_strategy.md` but not
  this file) fails your output contract — both are required.
- **Padded declarations** (FE/controls the design doesn't need) force
  the econometrics specialist to either estimate an over-specified model
  or fail the gate. Declare the minimal identified design.
