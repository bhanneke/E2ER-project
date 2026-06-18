# M4 re-run findings — why #69 didn't fire, and the #70 fix

> Re-run of the M4 Welch-Goyal RQ on `claude_code` after merging the
> runner-side post-specialist execution fix (#69). Captured honestly.
> Paper `e5f6d704-f800-42e0-9a92-499620a59e5b`.

## Outcome

The run **failed in the design phase** (18 min, 7 specialists, 3.28M
tokens, $0) — *before* the estimation checkpoint, not at it. Final error:

```
All specialists failed in parallel batch:
  data_analyst: contract violation: figure_spec.json: empty JSON ('{}');
  econometrics_specialist: contract violation: estimation_results.json: empty JSON ('{}')
```

M4.3 did its job (caught both empty sidecars and failed the batch). The
#69 fix, which should have populated `estimation_results.json`, never
ran. So the run failed faster — but still failed.

## Root cause

Three facts, established from the workspace with no LLM cost:

1. **Specialists have no general code-execution tool — by design.** On
   every backend they get Read/Write/Edit/Glob/Grep + the guarded
   `e2er-data` / `e2er-allium-query` wrappers, and nothing else (see
   `src/modules/llm/claude_code.py`: *"Specialists that need execution
   get their tools wired through Python at the runner level, not via
   Bash from the model"*). The failed run's `summary_statistics.json`
   even said so: *"estimation was NOT executed (code-execution not
   approved in this environment)."* The specialist was being honest — it
   literally cannot run Python. This is exactly why runner-side execution
   (#69) is the right design: it's the **only** execution path.

2. **#69 keyed on a single hardcoded filename.** It looked for
   `run_estimation.py` → `estimation_results.json`. This run's specialist
   named its script **`analyze.py`**, writing **`analysis_output.json`**.
   So `maybe_execute_specialist_script` found no `run_estimation.py`,
   no-op'd, and the sidecar stayed `{}`. The brittleness had just moved
   from *"did the model run the script?"* to *"did the model name it the
   canonical name?"* — still a model-judgment dependency in the critical
   path.

3. **`figure_spec.json` has no deterministic producer.** The
   `data/figure-spec` skill says to author it directly with data values
   ("Do NOT write matplotlib code"). Those values derive from analysis
   the model can't run, so at the data-design boundary the model can't
   populate it. Hard-gating it there killed the batch regardless of (2).

## The #70 fix

1. **Script discovery** (`post_execution._discover_script`): try an
   ordered list of canonical candidate names first
   (`run_estimation.py`, `analyze.py`, …), then fall back to globbing
   `*.py` and picking the script whose source references the target
   sidecar or a declared alternate output — the script that *claims* to
   write what we need. Backend- and name-agnostic.

2. **Output normalization** (`post_execution._normalize_output`): if the
   discovered script writes a populated alternate output
   (`analysis_output.json`) rather than the canonical sidecar, copy it
   onto `estimation_results.json` so M4.3 (which keys on the canonical
   name) sees it.

3. **`data_analyst` convention** added (script → `summary_statistics.json`),
   same discovery/normalization machinery.

4. **`figure_spec.json` → best-effort sidecar**
   (`SPECIALIST_OPTIONAL_SIDECARS`): still prompted, still checked by
   verify_numbers when present, but no longer a hard gate at the
   specialist boundary. Figures are a paper-assembly concern, enforced in
   the iterative phase where the numbers exist.

5. **Skill nudge** (`estimation-results-schema.md`): tell the specialist
   it has no code-execution tool, so the way to "run estimation" is to
   write `run_estimation.py` → `estimation_results.json` and let the
   runner execute it. Best-effort fast-path; discovery is the backstop.

## What's deliberately NOT claimed

This is a unit/contract-level fix with new tests; it has **not** been
re-validated end-to-end on a live paper run yet. M5 (and the v0.9.0 tag)
stay gated on a live re-run that produces a paper surviving review.
