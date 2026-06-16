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

**One-line fix**: in `run_specialist`, after the tool_loop returns
and before the M4.3 contract check, if the specialist is
`econometrics_specialist` and `run_estimation.py` exists but
`estimation_results.json` is empty/missing, the runner executes the
script itself via `subprocess.run`. Backend-agnostic, deterministic,
idempotent. The skill file's *"write `{}` not fabricated numbers"*
rule stays correct; the runner just ensures execution happens when
it can. See [**What needs to change** below](#what-needs-to-change)
for the design rationale (including the rejected skill-file
alternative).

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

> **Design note (2026-06-10)**: First draft of this section proposed
> a skill-file fix — one paragraph telling the specialist *"if you can
> run, run."* Owner pushed back: *"It would be good to have that more
> mechanically/deterministically solved."* That's right. A skill-file
> nudge puts the load-bearing decision back on the LLM. The mechanical
> fix below puts it on the runner.

### The mechanical fix — runner-side post-specialist execution

After the econometrics specialist's tool_loop returns and before the
M4.3 contract check fires, the **runner** checks:

- Does `run_estimation.py` exist in the workspace?
- Is `estimation_results.json` missing, `{}`, `[]`, `null`, or
  whitespace-only?

If both are true, the runner shells out and executes the script
itself with a subprocess timeout, captures stdout/stderr to
`run_estimation.log`, and lets the specialist's own output stand.
Then M4.3's contract check runs as before.

```python
# Sketch — actual code in the fix PR.
def maybe_execute_estimation_script(workspace: Path, specialist: str) -> None:
    if specialist != "econometrics_specialist":
        return
    script = workspace / "run_estimation.py"
    sidecar = workspace / "estimation_results.json"
    if not script.is_file():
        return  # specialist didn't write a script; nothing to run
    if _sidecar_is_populated(sidecar):
        return  # specialist already filled it; nothing to do
    logger.info("post-specialist exec: running %s", script.name)
    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=workspace, capture_output=True, text=True,
        timeout=600,
    )
    (workspace / "run_estimation.log").write_text(
        f"rc={result.returncode}\n--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )
```

Properties this has that the skill-file fix doesn't:

- **Backend-agnostic.** The runner executes via `subprocess.run`,
  not via the model's tool call. Works identically on `anthropic`,
  `openrouter`, `claude_code`, `codex`, `gemini` — even on backends
  that don't expose a code-execution tool to the model at all.
- **Idempotent.** If the specialist did the right thing and
  populated the sidecar, the runner sees the populated file and
  does nothing. No duplicate work.
- **Auditable.** `run_estimation.log` records the subprocess
  invocation's exit code and full output. The next reviewer can
  read it.
- **Catches the M4 failure mode by construction.** It does not
  depend on the LLM following any new instruction.

### M4.3 stays as the safety net

The post-specialist execution can fail too — the script might error
on import, the data shape might not match, the timeout might fire.
When that happens, `estimation_results.json` stays empty and M4.3
flips the specialist to `success=False` exactly as today. The two
mechanisms compose: the post-exec is the *positive* path (make the
right thing happen), M4.3 is the *negative* path (refuse the wrong
thing).

### What about the skill file

Leave it alone for now. The skill's *"if you didn't run, write `{}`
not fabricated numbers"* guidance is still correct in spirit. With
the mechanical fix, the specialist's choice between *"run it
myself"* and *"write `{}` and let the runner handle it"* becomes
operationally equivalent — both paths produce a populated sidecar
when execution is possible. A future skill update can simplify the
guidance, but it's no longer load-bearing.

### Why not generalise across specialists right now

This fix is specific: `econometrics_specialist` + `run_estimation.py`
+ `estimation_results.json`. We could extend the same convention to
`data_analyst` (e.g., `build_panel.py` → `summary_statistics.json`),
or `replication_packager` (e.g., `replication/estimation.py` →
already declared as the primary artifact). Start specific. If the
re-run shows the convention works, generalise in a follow-up.

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
2. Land the **mechanical fix** as a small `fix(runner):
   post-specialist execution for econometrics` PR — adds the
   `maybe_execute_estimation_script` hook above plus tests.
3. Re-run the M4 Welch-Goyal RQ on the `claude_code` backend.
4. **If the re-run produces a real `estimation_results.json` and
   survives review** → M5 is done; pick a sharper RQ for the
   `examples/showcase/` paper.
5. **If it produces real results but fails review for a different
   reason** → file the new finding in `M4_FINDINGS.md` style; iterate
   per the v0.9 plan.
6. **If `estimation_results.json` is still empty after the runner
   ran the script** → the script itself errored. Read
   `run_estimation.log` (which the post-exec writes), fix the script
   or the data shape, re-run. This is a debuggable failure, not a
   skill-prompt failure.

## Why this is a docs PR

No code changes here. This is the diagnosis, locked into the repo so
the skill-file fix that follows has a clear *"why"* to reference, and
so the M5 attempt has a known prerequisite that has been thought
through.
