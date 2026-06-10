# M4 root-cause diagnosis — why the estimator never ran

> **Status**: closed diagnosis (2026-06-10). Follow-up to
> [`docs/M4_FINDINGS.md`](M4_FINDINGS.md) finding #4 (specialist
> contract violation). M4.3 catches the symptom (empty
> `estimation_results.json`) at the boundary. This document identifies
> the cause — a skill-file gap, not a code bug — and proposes the fix.
> This is the load-bearing M5 prerequisite.

## TL;DR

The M4 paper failed not because the econometrics specialist couldn't
estimate. It failed because **the skill file gave the specialist
explicit permission to write `{}`**, and never instructed it that —
when data and a code-execution tool are present — it MUST run its
estimation script before writing the JSON. The specialist did the
documented-honest thing. The documentation was wrong.

**One-line fix**: amend
`skills/files/econometrics/estimation-results-schema.md` to require
execution when data + code-execution tool are both present, before
the `{}`-is-honest fallback applies. The fallback stays for backends
that genuinely can't execute.

## What I checked

I re-opened the M4 paper workspace
(`tests/workspaces/864008e9-2eac-4f82-8a55-dda5660259db/`) and walked
the contract chain end-to-end without spending any LLM cost.

### 1. The data was there

```
data/
├── gspc_daily.csv
├── irx_daily.csv      irx_monthly.csv
├── sp500tr_daily.csv  test_sp500tr.csv
└── tnx_daily.csv      tnx_monthly.csv  tnx_check.csv
```

8 CSV files: S&P 500 returns, 3-month T-bill, 10-year Treasury yield.
Everything Welch-Goyal needs. The `data_analyst` specialist
**succeeded at its job**.

### 2. The estimation script the specialist wrote is correct

`run_estimation.py` is 369 lines. Builds the monthly panel from the
local CSVs, computes dp / dy / tms predictors, runs in-sample
predictive regressions with **Stambaugh-corrected** slopes,
recursive expanding-window OOS R² against the prevailing mean, and
the **Clark-West** encompassing test. Newey-West HAC standard errors
at 6 lags.

The `econometrics_specialist` **wrote correct code**.

### 3. The script produces real results when run

I ran it manually:

```
$ python run_estimation.py
=== Estimation Summary ===
panel: 1991-01-31 .. 2024-12-31 (408 months)
dp:  IS R²(full)=0.0110  beta=0.0177  | OOS-R² full=0.009362  CW=1.2034
dy:  IS R²(full)=0.0106  beta=0.0173  | OOS-R² full=0.008617  CW=1.2746
tms: IS R²(full)=0.0017  beta=-0.0014 | OOS-R² full=-0.006842 CW=-1.0776
```

…and overwrote `estimation_results.json` with a real
3.5-KB document containing Stambaugh-corrected coefficients,
Newey-West SEs, Clark-West statistics, AR(1) diagnostics — every
required field from the schema, with non-fabricated numbers from
real data.

**The specialist did not run its own correct script during the M4
paper run.**

### 4. The skill file gave it permission not to

`skills/files/econometrics/estimation-results-schema.md`:

> *"If you only specified the model (wrote down the equation, fixed
> effects, instrument strategy) and did not run estimation against
> real data, write `estimation_results.json` as `{}` rather than
> fabricating values. **The empty file is the honest signal.**"*

And in the *"Failure modes — write `{}`, not no file"* section:

> *"If you specified the model but did not run estimation:
> - Write `estimation_results.json` as `{}`.
> - The drafter sees an empty JSON and produces a 'design without
>   estimates' version of the paper."*

The skill file has **no instruction anywhere** that says *"if you
have data files and a code-execution tool, you MUST run your
estimation script before falling back to `{}`."*

So the specialist read the skill, wrote a script, considered that an
honest-empty-JSON was the documented behaviour, and wrote `{}`. That
behaviour was designed as an escape hatch for backends without
code execution — but on the `claude_code` backend (which has Bash
and ran 39 tool calls for the data_analyst on the same run) the
escape hatch was misapplied.

The "design without estimates" paper then went to the mechanism
reviewer who correctly rejected it. The mechanism reviewer's binding
quote: *"the required 'revision' is to run the study."* The reviewer
was right. So is the skill file's "don't fabricate" rule. The bug is
that the skill never says *"…but if you can run it, run it."*

## What needs to change

### Change #1 (load-bearing) — one paragraph in the skill file

Amend `skills/files/econometrics/estimation-results-schema.md` to
add an **execution requirement** before the `{}`-is-honest fallback:

```markdown
## When to write this file

**Execution requirement.** If the workspace has data files (in
`data/`, `workspace/data/`, or any path your `data_analyst` peer
wrote) AND your tool list includes a code-execution tool (Bash,
python_executor, etc.), you **must** run your estimation script
against that data and write the JSON from real output. Writing
`{}` is only acceptable when execution is genuinely impossible —
no data, no executor — not when you simply chose not to execute.

**The honest-empty fallback** below applies only when the
execution requirement above cannot be met.
```

The existing "honest empty" section stays — it's the right escape
hatch for backends without execution tooling. The new paragraph is
the missing precondition.

### Change #2 (companion) — a small skill at `econometrics/run-estimation.md`

Five-paragraph how-to-execute guide:

- Default invocation: `python run_estimation.py 2>&1 | tail -200`.
- The `tail` keeps stdout summary inside the turn budget; full
  artifacts go to disk.
- After execution, **inspect** `estimation_results.json` — if it
  came out empty / malformed, fix the script and re-run; don't
  silently fall back to `{}`.
- If the executor isn't in the tool list, that's when the fallback
  applies — and emit one warning line so the strategist sees it.

### Change #3 (defensive, optional) — strategist visibility

When the strategist plans the econometrics phase on a backend with
a code-execution tool, the dispatch could log a single line
*"execution available — econometrics_specialist must run its
script"*. Cheap, surfaces the expectation in the run log. Skip if
felt over-engineered.

## Why M4.3 isn't enough alone

The M4.3 contract check catches `estimation_results.json == "{}"`
and flips the specialist to `success=False`. The circuit breaker
(`_MAX_SPECIALIST_ATTEMPTS=3`) then halts the run after three
consecutive failures.

Without the skill-file fix, the next paper run on the same RQ would
hit M4.3 three times in a row — three full econometrics-specialist
runs, each writing `{}` because the skill still says that's honest,
and the circuit breaker pauses. **That's a faster failure, not a
success.** The skill-file change is what makes the specialist
actually estimate; M4.3 is what catches it when the change isn't
enough on some future run.

## What this changes about M5

With this skill-file fix in, M5 becomes credibly attempt-able:

1. Re-run the same Welch-Goyal RQ. Expect `estimation_results.json`
   to come back populated (the script we already have works).
2. paper_drafter sees real estimates and writes a paper with
   results.
3. verify_numbers gate checks table values against the populated
   JSON.
4. verify_citations gate runs (post-M4.2 it parses `\bibitem`).
5. Mechanism reviewer scores the paper — this time with substance,
   not a design-without-findings. Whether it survives is the M5
   gate question that this fix unblocks.

Without this fix, M5 cannot succeed on this RQ or any other
empirical RQ — the specialist will dutifully write `{}` every time.

## Proposed sequence

1. Land this diagnosis doc (this PR).
2. Land the skill-file fix as a small `fix(skills): econometrics
   must execute…` PR.
3. Re-run the M4 Welch-Goyal RQ on the `claude_code` backend.
4. **If the re-run produces a real `estimation_results.json` and
   survives review** → M5 is done; pick a sharper RQ for the
   `examples/showcase/` paper.
5. **If it produces real results but fails review for a different
   reason** → file the new finding in `M4_FINDINGS.md` style; iterate
   per the v0.9 plan.
6. **If it still writes `{}`** → the skill-file fix didn't reach the
   model; investigate prompt assembly, tool availability per backend.

## Why this is a docs PR

No code changes here. This is the diagnosis, locked into the repo so
the skill-file fix that follows has a clear *"why"* to reference, and
so the M5 attempt has a known prerequisite that has been thought
through.
