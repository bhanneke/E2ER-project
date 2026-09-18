# Architecture diagrams

Two kinds of diagrams live in the docs:

- **`docs/figures/pipeline.{dot,svg}` — generated from the source of truth.**
  The "How it works" figure (also embedded in the top-level `README.md`) is
  produced by [`scripts/gen_pipeline_figure.py`](../../scripts/gen_pipeline_figure.py),
  which reads the real specialist roster and JSON artifact contracts from
  `src/core/specialists/registry.py`. It therefore cannot drift from the code —
  rename a specialist or a sidecar and the figure (and `tests/test_pipeline_figure.py`)
  follow automatically. Regenerate with `python scripts/gen_pipeline_figure.py`
  (needs Graphviz for SVG/PDF: `brew install graphviz`; the `.dot` is always written).

- **The `*.md` Mermaid diagrams in this folder** (`pipeline_overview.md`,
  `system_architecture.md`, `specialist_dag.md`, …) — hand-authored mental
  models for reading the code. Keep them roughly in sync by hand.
