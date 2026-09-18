# Finish the debug loop: `table_spec.json` is still written blind

> **Status**: design note (2026-08-28). Prepared but deliberately NOT
> implemented — landing it would change the code the Phase 2.1 repeats cell is
> measuring. Extends Phase 1 of [`V1.0_PLAN.md`](V1.0_PLAN.md).

## The finding

The v1→v3 capability regression is real but it is **already half-fixed**, and
the half that is missing is the half that killed canary #6.

E2ER v1 (`E2ER/src/claude_code.py:364`) gave stages real execution:

```python
_CODE_EXEC_TOOLS = ["Read", "Write", "Edit", "Bash(python3:*)", "Bash(python:*)"]
```

A specialist wrote its script, ran it, read the traceback, and fixed it — many
times inside one session. v3 removed that and had the orchestrator run scripts
post-hoc instead: better provenance, much worse reliability, because the model
writes blind and one crash costs a whole dispatch.

Commit `eff7ae1` ("restore the debug loop") already brought the loop back the
right way — not by restoring arbitrary shell, but through a gatekeeper:

```python
_SCRIPT_WRITING_SPECIALISTS = frozenset({"econometrics_specialist", "data_analyst"})
_RUN_TOOL = "Bash(e2er-run:*)"
```

`scripts/e2er-run` runs exactly one workspace-relative `.py` file, no
arguments, no traversal, hard timeout. The orchestrator still re-runs the final
script through `post_execution` for the record, so provenance comes from that
run and not from whatever the model did while iterating.

**But only two specialists write executable scripts. A third artifact is
authored just as blind, and nothing lets its author check it: `table_spec.json`.**

## Why this is the same defect

`table_spec.json` is a `paper_drafter` sidecar
(`registry.py:202-210`), optional rather than hard-gated
(`SPECIALIST_OPTIONAL_SIDECARS`, `registry.py:231`), and repaired later by
`section_writer` (`runner.py:1337`). Both specialists load the `data/table-spec`
skill; neither can render.

The renderer resolves each stat `field` **inside its own column's spec object**
— a lookup, never arithmetic. So a spec is valid or invalid purely as a
function of the JSON sidecars sitting next to it, and the author cannot see
those sidecars' key structure at authoring time.

Canary #6 (`8d3d9ce6`, commit `4126714`) is the cost. `summary_stats.tex`
declared three columns — `pre_etf`, `post_etf`, `comparison`. All six stat rows
exist under the first two. `comparison` in `estimation_results.json` holds only
five keys:

```
delta_p11, pct_change_p11, delta_duration, pct_change_duration, persistence_declined
```

A "Change" column asking for `n_observations` is asking the renderer to
subtract, which it does not do. Ten unresolved references,
`render_all_or_halt` fired, the run died in `designing` — and the repair loop
went **7 → 10** before the stall detector stopped it, because the repairer was
also guessing.

This is exactly "write blind → crash → fail". A human fixes it in seconds by
looking at the two files side by side. So does a model, *if it is allowed to
look*.

## The fix: `e2er-check-tables`

Symmetric with `e2er-run`, and thin, because the checker already exists.
`render_tables(workspace)` (`src/core/renderer/tables.py:408`) is idempotent,
never raises, returns a `RenderReport` carrying `unresolved`, and already
writes `table_render_report.json`.

The gatekeeper is a wrapper over it in report mode:

- takes **no arguments** — it always checks `table_spec.json` in the current
  workspace, so there is nothing to smuggle
- prints each unresolved reference as `table → column spec_key → missing field`,
  plus the keys that column's spec object *does* have (this is the line that
  would have solved canary #6 outright)
- exits non-zero when anything is unresolved, so the model can tell pass from
  fail without parsing prose
- writes nothing the orchestrator relies on: the runner re-renders afterwards
  for the record, exactly as it re-runs scripts after `e2er-run`

Wiring is one line — add `paper_drafter` and `section_writer` to a
`_SPEC_WRITING_SPECIALISTS` set granted `Bash(e2er-check-tables:*)`, alongside
the existing `_SCRIPT_WRITING_SPECIALISTS`.

### Why not just restore `Bash(python3:*)`

v1's tool profile was safe **because of where it ran**: inside Docker, on
`infra-net`, behind an egress firewall. v3 runs directly on the user's laptop,
and canary #4 already showed `literature_scanner` writing five `search_*.py`
files into the repo root. Granting arbitrary Python there is not a like-for-like
restoration — it is a new capability in a weaker container. `scripts/e2er-run`
says this in its own header comment; this note holds the same line.

## Scope

| Change | File | Size |
|---|---|---|
| New gatekeeper | `scripts/e2er-check-tables` | ~60 lines, mirrors `e2er-run` |
| Grant the tool | `src/modules/llm/claude_code.py` | ~4 lines |
| Tell the drafter to use it | `skills/files/data/table-spec.md` | a short section |
| Tests | `tests/test_table_spec_checker.py` | new |

Deliberately **not** in scope:

- **Derived cells** (a "Change" column computed as `post − pre`). A real
  capability gap, and the more interesting fix — but it puts arithmetic into
  the number path, which is the one place the anti-fabrication design says no
  LLM and no inference may go. It needs its own design, not a bolt-on here.
- **Malformed repair rows.** Canary #6's `main.tex` carried four references
  with `"ref": ""` — emitted by the repair pass, rejected by nothing. Worth a
  guard, separate change.
- **The missing `references.bib`** seen in canary #4, which silently skips the
  citation check.

## Test plan

Unit-level, no network and no LLM, consistent with the rest of the suite:

1. A spec whose fields all resolve → exit 0, no unresolved output.
2. Canary #6's actual spec + `estimation_results.json` → exit non-zero, and the
   report names `comparison` and lists its five real keys.
3. Absent / unparseable `table_spec.json` → the `skipped_reason` path, no crash.
4. Argument rejection: any argument at all is refused.
5. The tool appears in `allowed_tools_for("paper_drafter")` and
   `allowed_tools_for("section_writer")`, and **not** in the default set.

## Sequencing

Land this **after** the Phase 2.1 repeats cell finishes. The repeats cell's
whole claim is three runs of one frozen commit; committing into the tree while
it runs turns it back into one run each of three pipelines, which is the exact
defect `_provenance_lines` was written to shout about.
