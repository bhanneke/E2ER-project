# Architecture diagrams

The Mermaid diagrams in this directory (`pipeline_overview.md`,
`specialist_dag.md`, `review_aggregation.md`, `system_architecture.md`,
`data_module.md`, `llm_tool_loop.md`) are hand-maintained conceptual diagrams.

> **Note:** the publication-quality "How E2ER works" figure at
> [`../figures/pipeline.svg`](../figures/pipeline.svg) is **generated from the
> source of truth** by [`scripts/gen_pipeline_figure.py`](../../scripts/gen_pipeline_figure.py)
> (it reads the real specialists + artifact contracts from
> `src/core/specialists/registry.py`), so it can never drift from the code.
> Regenerate it with `python scripts/gen_pipeline_figure.py`.
