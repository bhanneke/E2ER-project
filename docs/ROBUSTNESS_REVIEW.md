# Robustness review: why E2ER v3 produces papers it should refuse to produce

**Date:** 2026-08-11 · **Scope:** whole-system, not a diff · **Method:** one fully
measured run (`70c33410`) traced end to end, plus a structural comparison against
E2ER v1 as it ran inside 100xOS.

---

## Verdict

The system does not fail. That is the bug.

Every layer between a crashed analysis script and a submitted paper **detected**
the problem and **continued anyway**. Nothing is missing a check. The checks are
there, they fired, they were written to disk, and the run went on. E2ER is
engineered — deliberately and consistently — to emit a paper rather than to
stop, and a research pipeline that always emits a paper will emit a fabricated
one whenever the analysis fails.

This is why fixing single points of failure has not helped. Each fix plugs one
leak in a design that leaks by policy.

---

## The cascade, traced

One run. Public yfinance data. Governance `off`.

| # | What happened | Where |
|---|---|---|
| 1 | `run_estimation.py` crashed: `TypeError: Invalid comparison between dtype=datetime64[ns, UTC] and Timestamp` | `run_estimation.log` |
| 2 | The script wrote `estimation_results.json` = `{}` (2 bytes) **anyway** | workspace |
| 3 | Runner captured `rc != 0` and classified it correctly as `"script exited with code 1"` | `post_execution.py:346` |
| 4 | Under `off` the contract check logged `gate_shadow` and did **not** flip `success`, so no retry fired and the traceback was never fed back | `base.py:198` |
| 5 | Renderer could not resolve `full_sample`, `time_varying`, `ethereum` (all live in the estimation results). Rendered `---`, logged a warning | `runner.py:1285` |
| 6 | Drafter wrote **4 inline `tabular` blocks with invented numbers**, under the same labels as the rendered tables | `paper_draft.tex` |
| 7 | 53 of 110 table values traced to nothing; 20 contradicted source outright | `number_verification.json` |
| 8 | Reviewers returned `HARD_REJECT` | `review_aggregation.json` |

**The worst detail is step 6.** The renderer produced `tables/regime_baseline.tex`,
`tables/regime_break.tex`, and `tables/eth_comparison.tex`. The draft contains
`\input{}` for **none** of them and inline tables labelled
`tab:regime_baseline`, `tab:regime_break`, `tab:eth_comparison` — the same
labels, hand-written. The provenance chain was fully constructed and then
silently bypassed. The rendered files sit orphaned on disk.

The claim "no LLM in the number path" is false as built. Not because the gate is
weak, but because the drafter has an unguarded parallel path around it.

---

## The systemic property: degrade to output

The same policy appears at every boundary, and in two places it is stated
outright in a docstring.

| Mechanism | Behaviour on missing/broken input | Location |
|---|---|---|
| `ensure_input_stubs` | creates **empty stub .tex files** so a dangling `\input` "keeps the rest of the paper compiling" | `renderer/tables.py:391` |
| `ensure_figure_placeholders` | same, for figures | `renderer/figures.py:287` |
| table_spec resolution | unresolved refs render as `---`, one repair attempt, then a warning | `strategist/runner.py:1285` |
| analysis script | non-zero exit recorded, never gated | `specialists/base.py:154` |
| results sidecar | `{}` counts as written; only `_is_populated` distinguishes, and only inside the contract check | `post_execution.py` |
| verification gates | run last, after the paper exists | `pipeline/verify_*.py` |

Graceful degradation is correct for a web service. For a research pipeline it
converts every infrastructure failure into a fabrication.

---

## What actually changed since v1 — and what did not

The "it worked in 100xOS, breaks standalone" hypothesis is half right. Two
common explanations are **wrong**, and I checked both:

- **Nothing was lost with `shared/`.** v3 has zero `from shared` imports and
  reimplements what it needs. v1 had exactly one such import (`skills/loader.py`).
  The extraction was clean.
- **v3 is not less defensive.** It has *more* of everything: retry 65 vs 23,
  `except` 317 vs 193, resume 199 vs 32, schema 173 vs 126.

What did change:

| | v1 (100xOS) | v3 (standalone) |
|---|---|---|
| Python | 27,001 lines / 82 files | **56,660 lines / 256 files** |
| Specialist code execution | `estimation`, `analysis` ran with `Bash(python3:*)`, `nohup`, `bash` | **none** — only `Bash(e2er-data:*)`, `Bash(e2er-allium-query:*)` |
| Debug loop | agent wrote → ran → saw traceback → fixed, **inside one session**, up to the turn budget | orchestrator runs the script **after** the call; one traceback per *whole new dispatch*, and only if a regime flipped `success` |

**This is the one real capability regression.** v1's specialists could iterate on
their own code many times per session at no orchestration cost. v3 replaced that
with a coarse cross-dispatch loop. `post_execution.read_execution_error` exists
precisely to compensate — its docstring says "Recovers v1's self-debugging loop
without giving the model a code tool" — but one coached retry per dispatch is not
equivalent to N iterations per session, and under `off` it never fires at all.

The execution separation is a deliberate principle (agents write code, only the
orchestrator runs it, so results are reproducible). It is defensible. It was just
not paid for.

---

## The design error underneath all of it

Three different concerns are wired to one switch:

1. **Reliability** — did the pipeline execute correctly? Did the script run? Is
   the sidecar populated? Do table refs resolve?
2. **Verification** — do the paper's claims trace to their sources?
3. **Robustness** — is the specification defensible? (designed, not built)

Governance `off` currently disables **1 and 2 together**. So the experiment's
control cell is not "the same pipeline without verification" — it is "a pipeline
with no error recovery at all". That is why the measured fabrication sits
downstream of a crashed script rather than downstream of a working analysis, and
it confounds fabrication with completion in the Stage-2 design.

Reliability is not a treatment condition. A crashed script is a bug in every arm.

---

## Status

All six recommendations are implemented, in `eff7ae1` (1–4) and `a49bc1b`
(5–6). 1,197 tests pass. What is NOT done is the thing that matters most:
**none of this has been exercised by a live run.** The evidence below is from
unit tests and from replaying the fixes against the stored failing workspace.
A governed run at concurrency 1 is the next step, and until it happens these
are fixes in principle.

Three tests that asserted the old semantics were rewritten rather than deleted,
each carrying a note about why the previous expectation was wrong. If you are
reading a diff and one of them looks like a weakened assertion, that is the
reliability/verification split, not a concession.

## Recommendations

Structural, in dependency order. The first two are the ones that matter.

### 1. Fail closed at every artifact boundary

Invert the default. An artifact is either valid or the run stops.

- Delete `ensure_input_stubs` and `ensure_figure_placeholders`, or demote them to
  a `--best-effort` flag used only for human preview. A dangling `\input` *should*
  abort compilation; that is the signal working correctly.
- Unresolved table_spec refs after the repair attempt: hard stop, not `---`.
- A script that exits non-zero: hard stop, in every regime.
- A script that fails must write **no** sidecar. `{}` is worse than absent,
  because every existence check passes.

### 2. Split reliability from governance

`governance` should gate verification only. Add a separate, always-on reliability
invariant set that no regime can disable. Concretely: `off` keeps the coached
retry and the circuit breaker; it only stops *enforcing the numbers and citation
gates*. This makes the control cell mean what the paper says it means, and it
fixes the experimental confound at the same time.

### 3. Close the drafter's parallel path

`paper_draft.tex` must contain zero `\begin{tabular}`. Tables enter only through
`\input{tables/*.tex}`. This is a ~20-line deterministic contract, and it would
have turned this run's 53 silent fabrications into one loud violation at draft
time. Enforce under `contracts` and `full`; shadow under `off`.

### 4. Restore a real debug loop

Two-phase execution gets both properties. Let the specialist execute its script
in a scratch sandbox and iterate until it runs — that is v1's inner loop. Then
have the orchestrator re-run the *final* script from a clean workspace for the
record. Reproducibility comes from the second run, robustness from the first.
Nothing about provenance requires that the model never execute anything.

### 5. Normalise datetimes at the data boundary

The tz-aware/naive crash is a recurring failure mode in generated pandas code.
Fix it once where data is handed to specialists rather than hoping each generated
script gets it right.

### 6. Confront the complexity

57k lines across 256 files for a pipeline that v1 ran in 27k across 82 is the
background cause of all of the above: more boundaries, more places to degrade.
Not urgent, but every new guard added to this design makes the next failure
harder to trace, and the fix list above should shrink the surface rather than
grow it.

---

## Smaller items found on the way

- `modules/llm/claude_code.py:343` catches bare `TimeoutError`, an `OSError`
  subclass since 3.11, so inner pipe timeouts are reported as the wall-clock
  deadline. Produces impossible messages ("timed out after 69s, limit 1800s").
  Actively misleading during diagnosis; still unfixed.
- CLI error strings truncate to ~500 chars in both `contributions.error_msg` and
  the server log, which is why the pilot's eight subprocess failures were never
  definitively explained.
- `robustness_results.json` is an optional sidecar written only if the
  econometrics specialist happens to run checks. The robustness axis does not
  exist yet.
