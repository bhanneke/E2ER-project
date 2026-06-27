# Spec — Structured paper export (DRAFT for review)

> **Status:** spec only, not implemented. Edit the layout / decisions below and
> hand it back. Separate feature from the BYOD-SQLite PR (#81).

## Problem

A run's workspace (`Tests/workspaces/<uuid>/`) is a **flat scratch dir** — throwaway
probe scripts, `.tex`, `.json`, `.md`, `data/`, `data.db`, `literature/` all dumped
together. It's load-bearing for the pipeline (specialists write artifacts by hardcoded
filename via `SPECIALIST_ARTIFACTS`; resume + context builders read them there), so we
must **not** reorganize it in place. Instead, add an **export** step that assembles a
clean, navigable project tree **in a folder the user chose**, leaving the workspace
untouched.

## Proposed layout  ← **the part to shape**

```
<OUTPUT_DIR>/<slug>/
├── README.md            generated: research question, verdict, key result, how to reproduce
├── paper/
│   ├── paper.pdf        compiled (if the LaTeX compile succeeded)
│   ├── paper.tex        ← paper_draft.tex
│   ├── abstract.tex
│   └── refs.bib         ← literature.bib
├── code/
│   ├── run_estimation.py
│   └── scratch/         the model's throwaway probes (_explore.py, _diag.py, profile.py, *.log)
├── data/
│   ├── data.db          the per-paper SQLite warehouse (copy or symlink — see D3)
│   ├── data_summary.md
│   └── data_dictionary.json
├── results/
│   ├── estimation_results.json
│   ├── robustness_results.json
│   ├── summary_statistics.json
│   ├── number_verification.json
│   └── figures/         figure_spec.json + any generated figures/tables
├── design/
│   ├── paper_plan.md
│   ├── identification_strategy.md
│   └── econometric_spec.md
└── reviews/
    ├── review_aggregation.json     the verdict
    ├── review_mechanism.md
    ├── review_literature.md
    ├── review_*.md                 (technical / writing / data / identification, when present)
    ├── self_attack_report.json
    └── polish_*.md
```

### Artifact → folder mapping (driven by `SPECIALIST_ARTIFACTS`, registry.py)

| Source artifact(s) | → destination |
|---|---|
| `paper_draft.tex`, `abstract.tex`, `literature.bib`, compiled PDF | `paper/` |
| `run_estimation.py`; `_*.py`, `profile.py`, `*.log` | `code/`, `code/scratch/` |
| `data.db`, `data_summary.md`, `data_dictionary.json` | `data/` |
| `estimation_results.json`, `robustness_results.json`, `summary_statistics.json`, `number_verification.json`, `figure_spec.json`, `table_spec.json` | `results/` |
| `paper_plan.md`, `identification_strategy.md`, `econometric_spec.md`, `model_spec.md` | `design/` |
| `review_*.md`, `review_aggregation.json`, `self_attack_report.json`, `polish_*.md`, `citation_integrity.json` | `reviews/` |
| `manifest.json` + verdict + key coef | synthesized into `README.md` |

Mapping lives in one dict so it's trivial to re-shape; anything unmatched falls into a
`misc/` folder rather than being dropped (no silent loss).

## Locked decisions

- **D1 — Output location.** `OUTPUT_DIR` env if set, else `<LOCAL_DATA_DIR>/e2er_papers/<slug>/`, else
  `~/e2er-papers/<slug>/`.
- **D2 — Slug.** `<title-kebab>-<YYYYMMDD>-<NN>`, where `NN` is a 2-digit version counter — the smallest
  unused number for that `<title>-<date>` prefix. So same-day re-exports increment
  (`routing-around-royalties-20260627-01`, `-02`, `-03`, …). This makes each export a new, versioned
  folder and **subsumes D5** (no overwrite — re-running just bumps `NN`).
- **D3 — `data.db` handling.** **Copy** (portable deliverable; ~1 GB is fine). Never symlink — the
  folder must survive being moved/shared and the workspace being cleaned up.
- **D4 — When it runs.** Both: **auto** at terminal status (completed *and* rejected/failed), plus a
  manual CLI `e2er export <paper_id> [--to DIR]` for on-demand / re-export.
- **D5 — Re-export.** Handled by D2's `NN` version counter — each export is a fresh `-NN` folder; nothing
  is overwritten.
- **D6 — Folder names.** As proposed: `paper/ code/ (+code/scratch/) data/ results/ design/ reviews/`.
  Probe scripts kept under `code/scratch/` for reproducibility.
- **D7 — Partial runs.** Yes — best-effort over whatever artifacts exist, so a rejected/failed run still
  yields its reviews + draft.

## Implementation sketch (once the layout is fixed)

- New module `src/core/export/structured.py`: pure function `export_paper(workspace, dest, manifest) ->
  Path` that walks the mapping, copies/symlinks, and renders `README.md`. No pipeline coupling — it just
  reads the finished workspace.
- New runner phase `_run_export_phase()` (sibling to `_run_github_push_phase`) invoked at terminal
  status; gated on `OUTPUT_DIR`/`EXPORT_ENABLED`.
- New CLI `e2er export <paper_id> [--to DIR]` for on-demand / re-export.
- Reuses `SPECIALIST_ARTIFACTS` + the artifact registry so the mapping stays in sync as specialists
  change. Tests: mapping correctness on a synthetic workspace, missing-artifact tolerance, README render.

## Non-goals
- Restructuring the internal workspace (too invasive; breaks resume/artifact contracts).
- Changing how specialists name or write artifacts.
