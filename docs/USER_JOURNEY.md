# User journey

**Date:** 2026-08-13 · **Method:** one operator (experienced, with repo access)
taking the documented path from a clean shell to a finished run, recording every
point where the system's behaviour diverged from what the documentation implies.

This is not a design document. Everything below was observed. Where a stage was
not exercised, it says so.

---

## Summary

Three executions of the same cell were observed: one at concurrency 3 (a
misconfiguration, described in Finding 2.2), one at the intended concurrency 1,
and one resume of the latter.

**The core fixes work under live conditions.** The reliability guard fired under
`regime: off`, where it previously only shadowed. The estimation sidecar came
back populated at 23,918 bytes instead of `{}`. The tz-comparison crash did not
occur. The restored `e2er-run` debug loop was used by the specialist. The
timeout message is coherent for the first time.

**No run produced a paper.** Three attempts, including one resume. One halted
because two specialists returned nothing. Two halted on the same missing file —
`econometric_spec.md`, the econometrics specialist's declared artifact — once
after being cut off at the 30-minute cap and once after finishing on its own in
24 minutes. Every halt was correct. Every halt discarded completed analysis.

Three distinct problems, in order of severity:

1. **The econometrics specialist does not write its declared artifact.**
   Reproduced twice, and not a timeout (Finding 5.2). While this holds, no run
   reaches drafting, no run is measurable, and the experiment collects nothing
   in any regime.
2. **The long-lived API server holds code and configuration from whenever it
   started**, and every entry point silently reuses it (Findings 2.1, 2.2).
3. **The pipeline is not running on the dependencies it declares.** The project
   was never installed into the interpreter that runs it, so three declared
   constraints are unsatisfied — including `pandas<3.0`, which is pinned
   specifically to keep generated estimation scripts working and is violated by
   the pandas 3.0.2 that ran every cell here (Finding 1.2). The test suite says
   so, in 32 failures nobody was reading.

Of the findings below, three are cosmetic, five can invalidate or destroy a run
without warning, and one of those invalidated a run during this session. Two
further findings (5.3, 5.4) come from reading the two failed runs' event rows
rather than from the operator's path: the repair loop written for this exact
failure is unreachable, and the gate event does not record which check did the
blocking.

---

## Stage 0 — Install

Documented path:

```bash
pip install e2er
e2er init --defaults
e2er run "<question>"
```

**Finding 0.1 — `python3` is 3.9 on stock macOS.**
Invoking any entry point with the system interpreter produces a 40-line pydantic
traceback ending in

```
TypeError: unsupported operand type(s) for |: 'type' and 'NoneType'
```

Nothing in that message mentions Python versions. `README.md` troubleshooting
documents a *different* symptom for the same cause (`ImportError: cannot import
name 'UTC' from 'datetime'`), which appears on a different code path. A user
who hits the pydantic form finds nothing when they search the README for it.

*Cost to user:* high on first contact, zero afterwards.
*Fix:* a version check at `src/__main__.py` entry, before any import of
`config.py`. Three lines, and it converts the worst first-touch error in the
system into one sentence.

---

## Stage 1 — Preflight (`e2er doctor`)

`doctor` is the right idea and reports real things: it found the yfinance path
live (`3 rows for SPY`), correctly skipped FRED and Allium as keyless, and
confirmed the SQLite default.

**Finding 1.1 — `doctor` blocks on a backend the run will not use.**
Observed verbatim:

```
✗ [FAIL] backend.anthropic   ANTHROPIC_API_KEY not set — `e2er run` will fail
❌ Blocked — fix the backend / DB / skills failure above before running a paper.
```

The run that followed used `claude_code` and never touched Anthropic. `doctor`
checks the backend in settings, not the backend the user intends. A reader
following the README's `claude_code` path sees a hard block that does not apply
to them, and the prescription — set an API key — is wrong for their setup.

*Fix:* `doctor --backend claude_code`, and have the summary line name which
backend it judged.

**Finding 1.2 — `pypdf` is not installed, and PDF reading fails.**

```
WARNING | src.modules.literature.pdf | pypdf not installed — cannot extract PDF text
✗ [FAIL] lit.read_reference (OA PDF)
```

Local PDF reading is a headline feature ("bring your own papers"). Without
`pypdf` it degrades to OpenAlex metadata. `doctor` catches it, which is the
system working.

*Correction (2026-08-19).* This document originally called that a packaging gap
and proposed moving `pypdf` into the base dependency set. That is wrong:
`pyproject.toml:23` already declares `pypdf>=4.0` as a base dependency. The
actual condition is worse and explains more:

```
$ python3.12 -c "import importlib.metadata as m; m.version('e2er')"
PackageNotFoundError
pypdf         MISSING          (declared: pypdf>=4.0)
bibtexparser  1.4.4            (declared: bibtexparser>=2.0.0b7)
pandas        3.0.2            (declared: pandas>=2.0,<3.0)
```

The project was never installed into the interpreter that runs the pipeline.
Nothing depends on it being installed: every entry point resolves `src` from the
repository root via `sys.path`, so the pipeline runs, the server serves, and the
specialists work — on whatever the ambient Homebrew interpreter happens to
contain. Three declared constraints are unsatisfied there, and none of them
fails loudly. `pypdf` is the only one `doctor` reports.

The pandas constraint is the serious one, because it lands directly on the path
this experiment measures. `pyproject.toml:28` pins `pandas>=2.0,<3.0`, and the
comment above the pin states the reason: pandas 3.0 removed the legacy offset
aliases, and "LLM-generated estimation scripts use `resample("M")` (the pre-3.0
idiom), which raises on 3.x". The interpreter that ran every cell in this
document has pandas 3.0.2. Probing it:

```
resample("M")           ValueError: 'M' is no longer supported for offsets. Please use 'ME' instead.
resample("Y")           ValueError: 'Y' is no longer supported for offsets. Please use 'YE' instead.
date_range(freq="M")    ValueError: 'M' is no longer supported for offsets. Please use 'ME' instead.
resample("ME")          OK
```

So the specialist writing `run_estimation.py` was working against an environment
the project explicitly forbids, in exactly the way the pin was written to
prevent. This does not explain the missing `econometric_spec.md` — that file
needs no pandas — but it is a plausible contributor to the 24 to 30 minutes the
specialist spent in the write/run/fix loop (Finding 4b.1), and it means the debug
loop's measured expense is partly the cost of a misconfigured environment rather
than an intrinsic property of the design. Any run intended as evidence should
first assert the declared constraints hold.

The bibtexparser breakage is the quieter one, and not reported anywhere:

```
WARNING | src.modules.literature.bibtex | Failed to parse …/curated.bib:
        module 'bibtexparser' has no attribute 'parse_file'
```

`LocalBibLibrary.entries()` catches the parse failure, logs at WARNING, and
returns an empty list. A user who points `LITERATURE_BIBTEX_FILE` at a real
library gets a specialist prompt with no bibliography block in it and no error —
the same degrade-to-output shape the contracts work is meant to eliminate, in a
module the contracts do not cover. This did not affect the runs in this document
(there is no `.env` in the worktree and both settings default to `None`, so no
library was configured), but it is live for anyone who configures one.

The test suite already reports all of this, and nobody was reading it. On this
interpreter `pytest tests/` gives **32 failed, 1174 passed**, and every one of
the 32 traces to an unsatisfied declared dependency:

| file | n | cause |
|---|---|---|
| `test_verify_citations.py` | 10 | bibtexparser 1.x |
| `test_local_data_dir.py` | 7 | bibtexparser 1.x |
| `test_cli_verify.py` | 3 | bibtexparser 1.x |
| `lit/contract/test_read_reference.py` | 3 | pypdf missing |
| `lit/contract/test_provider_registry.py` | 3 | bibtexparser 1.x |
| `test_local_corpus_extensions.py` | 2 | bibtexparser 1.x |
| `test_external_verify.py` | 2 | bibtexparser 1.x |
| `test_data_normalize.py` | 2 | pandas 3.x (`datetime64[us]` vs `[ns]`) |

None are in the specialist, contract, or governance modules. A green suite is
one `pip install -e ".[dev]"` away, and it would have flagged the pandas
violation before the canary ran rather than after.

*Fix:* install the project into the interpreter that actually runs the pipeline,
in a virtualenv rather than the Homebrew Python, and have `doctor` compare
installed distributions against the declared dependency set instead of
import-probing one library at a time — a dependency the project pins and the
environment violates should be a `doctor` failure, not a silent one. Separately,
a `.bib` library that fails to parse should surface as a failure, not as an empty
bibliography.

---

## Stage 2 — The server, and the three traps in it

Every entry point (`e2er run`, `e2er status`, the experiment driver) talks to a
uvicorn process on `127.0.0.1:8280`. If one is reachable, it is used. If not,
`_ensure_api_up()` starts one.

That single behaviour produces three distinct failure modes.

**Finding 2.1 — a running server serves the code it started with.**
uvicorn runs without `--reload`. On this machine three servers were live, started
Jul 28, Aug 4, and Aug 5. The Jul 28 process runs from the current worktree and
answers on the default port — so any `e2er run` issued today would have executed
three-week-old code while every file on disk showed the fix.

There is no version, build, or start-time in `/api/papers`, so nothing about the
response reveals which code answered it.

*Cost to user:* silent and total. A fix appears not to work; a regression appears
to reappear; a measurement describes code that no longer exists.
*Fix:* stamp a build identity (git SHA + start time) into the app at startup,
expose it on a health route, and have the CLI compare it against the working tree
and warn on mismatch.

**Finding 2.2 — environment variables reach the server only if the CLI starts it.**
This is the one that cost a run in this session.

`experiments/validation_cell.yaml` documents its own invocation as:

```bash
MAX_CONCURRENT_SPECIALISTS=1 python scripts/experiment_driver.py experiments/validation_cell.yaml
```

That works *only* when no server is running, because the variable is inherited by
the uvicorn child that `_ensure_api_up()` spawns. When a server is already up,
the variable stays in the driver process — which does not execute specialists —
and the server continues at its own default of 3.

Observed: with `MAX_CONCURRENT_SPECIALISTS=1` set on the driver, all three
specialists emitted `specialist_start` at the same second (22:05:52). The cell
labelled "concurrency 1" ran at concurrency 3.

The result looked entirely plausible. It failed in a way consistent with the
prior pilot, and had the specialist timestamps not been checked it would have
been reported as a concurrency-1 result.

*Cost to user:* silent invalidation of a measurement, with a believable output.
*Fix:* settings that govern execution belong on the paper record, not the server
environment — the run request already carries `backend`, `model`, `governance`,
and `max_cost`. `max_concurrent_specialists` should travel the same way. Failing
that, echo the effective value in the run's opening log line and into the events
table, so the configuration is recorded with the measurement.

**Finding 2.3 — no interpreter pinning.**
The servers on this machine run Homebrew 3.12; `python3` in a fresh shell is 3.9.
Whether `e2er run` works depends on which shell started what. Related to 0.1 but
distinct: here the failure is not an error message, it is two different
interpreters running two parts of the same system.

---

## Stage 3 — Run and monitor

The driver prints one line per phase with a running token and cost total, which
is legible and enough to follow:

```
[idea        ] specialists=  0  tokens=         0  cost=$0
[designing   ] specialists=  2  tokens=    168460  cost=$0
```

`cost=$0` is correct for `claude_code` under a Max plan, though the underlying
CLI reports notional per-call costs (`total_cost_usd: 1.19`) that never surface.
For a user judging whether a run is affordable on a metered backend, the printed
zero is accurate for their plan and uninformative about the work performed.

---

## Stage 4 — Failure, as the user receives it

The reliability guard works. From the concurrency-3 run, in the events table:

```json
{"gate": "contracts", "passed": false, "enforced": true, "regime": "off",
 "check": "missing_artifact", "detail": "idea_developer -> paper_plan.md missing …"}
```

`enforced: true` under `regime: off` is the reliability/governance split
operating live: two of three specialists produced no artifact and the run halted
instead of drafting over the gap. Before the change this logged `gate_shadow`
and continued.

**Finding 4.1 — the halt is correct and the message is unusable.**
What the user actually sees in `last_error`:

```
RuntimeError: Specialist(s) did not produce canonical artifact: idea_developer ->
paper_plan.md missing (Exit code 1: {"is_error":true,"duration_api_ms":307043,
"num_turns":2,"stop_reason":"stop_sequence","session_id":"5be4ec2d-…",
"total_cost_usd":1.189327,"usage":{"input_tokens":2,…,"server_tool_use":
{"web_search_requests":0,"web_fetch_reque
```

It ends mid-key. The message names the specialist and the missing artifact —
genuinely useful — and then spends its entire budget on a raw JSON dump that
tells the user nothing and is cut off before its own end.

Cause: `src/modules/llm/claude_code.py:415`.

```python
if proc.returncode != 0:
    error_msg = stderr.strip() or f"Exit code {proc.returncode}: {_clip(stdout.strip())}"
```

On a non-zero exit with empty stderr, the raw stdout JSON is dumped. The
human-readable extraction at line 437 — `raw.get("result") or raw.get("error")` —
sits on the branch that handles a CLI exiting **0** while self-reporting an
error. The real failure took the other branch.

*Fix:* parse stdout as JSON on the non-zero path too, and prefer `result` /
`error` over the raw blob. The information the user needs is already in the
payload being discarded.

**Finding 4.2 — the underlying specialist failure is still unexplained.**
Both failures ran 306.5s and 307.0s and stopped with
`stop_reason: "stop_sequence"`, `is_error: true`, and output dominated by
thinking tokens (6491 of 6616). The near-identical durations point at a limit
rather than a model error. `claude_code_timeout` is 1800s, so it is not ours.
This reproduces the earlier pilot's failure signature at concurrency 3 and did
not recur at concurrency 1.

---

## Stage 4b — The same cell at true concurrency 1

Re-run with the concurrency setting on the server process rather than the
driver. This is the run the cell was supposed to be.

It behaved completely differently, and mostly well. Over 66 minutes and 7
specialist calls it produced a research design, a literature review, an
identification strategy, a data dictionary, summary statistics, a populated
estimation sidecar, a figure spec, three rendered figure PDFs, and a
`replication/` directory.

**The two artifacts that define the earlier failure both inverted:**

| | Failing run (2026-08-05) | This run |
|---|---|---|
| `estimation_results.json` | 2 bytes (`{}`) | **23,918 bytes**, real estimates |
| tz-comparison crash | fatal | **0 occurrences** |

The detail log shows Markov-switching AR models fitting with real
log-likelihoods and observation counts (`ll=-907.81 obs=1093 stab=1.00`).

**Finding 4b.1 — the restored debug loop is real, and it is expensive.**
The workspace contains `explore.py`, `build_analysis_data.py`, `make_figspec.py`,
`validate_json.py`, `selftest.py` alongside intermediate outputs `_explore.json`,
`_figspec.json`, `_results.json`. Those intermediates can only exist if the
specialist executed its own scripts — the orchestrator runs only the final
estimation script. The `e2er-run` loop is being used as designed.

It is also what killed the run. The econometrics specialist iterated for the
full 30-minute cap and hit the wall before writing `econometric_spec.md`:

```
econometrics_specialist -> econometric_spec.md missing
(Claude Code timed out after 1800s (limit 1800s))
```

The guard then halted correctly. But note what was lost: real estimates, real
figures, and a replication directory were all on disk, discarded because one
markdown file was not written in time. The specialist spent its budget on
analysis and ran out before documentation.

This message is also evidence the timeout reporting fix works: "1800s (limit
1800s)" is coherent, where the previous code produced impossible strings like
"timed out after 69s, limit 1800s".

The obvious reading — raise the cap — turned out to be wrong. See Stage 5.

**Finding 4b.2 — the empty-sidecar pattern survives, intermittently, in
`robustness_results.json`.**
`estimation_results.json` is now guarded: a failed script quarantines its
unpopulated sidecar. `robustness_results.json` is not. It was written at
**2 bytes** (`{}`) on the first attempt and at **23,381 bytes** of real content
on the second — same cell, same specialist.

Intermittency makes this worse rather than better. A sidecar that is usually
populated and occasionally `{}` will pass review by inspection and fail
silently in the one run nobody checks. Every existence check passes on `{}`.

The robustness axis is the second half of the verification/robustness split, and
it is now producing real output — which is the point at which it needs the same
populated-or-absent guard estimation already has.

---

## Stage 5 — Recovery

`POST /api/papers/<id>/resume` accepted the failed paper and restarted at
`data_analyst` — the phase that failed — rather than from `idea_developer` and
rather than re-halting immediately.

So the feared resume/halt loop does not occur, and neither does a full redo.
Resume re-enters at the failed phase and re-runs that phase's specialists.

**Finding 5.1 — `.pipeline_state.json` records nothing.**
After a run that produced a dozen artifacts across four phases:

```json
{"completed_stages": [], "current_stage": "", "contributions_count": 0}
```

`README.md` troubleshooting tells users to "check
`workspaces/<id>/.pipeline_state.json` for the last completed phase". It will
tell them nothing. The skip logic evidently works off artifacts on disk, so
behaviour is correct while the documented diagnostic is empty.

**Finding 5.2 — resume re-ran the phase and failed at the same artifact.**

| | First attempt | After resume |
|---|---|---|
| duration | 30 min (hit the 1800s cap) | **24 min 14 s — finished inside the cap** |
| `econometric_spec.md` | not written | **not written** |
| analysis output | populated | populated (re-derived from scratch) |

The second attempt is the informative one. The specialist was not cut off. It
ran to its own completion in 24 minutes, rewrote `run_estimation.py`,
`summary_statistics.json`, `figure_spec.json` and a populated
`robustness_results.json` — and again did not write the one file its contract
declares:

```python
# src/core/specialists/registry.py:11
"econometrics_specialist": "econometric_spec.md",
```

So this is not a timeout problem. Raising `claude_code_timeout` would not have
helped. The specialist reliably spends its session on analysis and does not
produce its declared prose artifact. Restoring the debug loop appears to have
sharpened the trade-off: given the ability to run code, the specialist runs code.

**This is currently the blocker on completing any paper.** The contract check is
behaving correctly — the artifact genuinely is missing — but the phase cannot
pass, so resume reproduces the halt deterministically. Two consecutive attempts,
one truncated and one not, produced the same outcome.

*Fix:* have the specialist write `econometric_spec.md` first, from the plan,
before it begins iterating on scripts, and update it at the end. A specification
written before the analysis is also the more defensible artifact.

*Cost of not fixing:* no run reaches drafting, so no run is measurable, so the
experiment has no observations in any regime.

*Status (2026-08-19):* the prompt half is implemented in
`src/core/specialists/base.py` — a Write Order block that names the artifact and
puts it ahead of the script, an early-write deadline moved from turn 40 to turn
10 for script-writing specialists, and the removal of a contradiction that had
been telling this specialist "One specialist = one artifact" and "produce exactly
one final write_file at the end" while its work order asked for three files. Two
caveats. First, this is a behavioural fix: it makes compliance likelier, it does
not make the artifact deterministic, so the next canary is the test. Second, it
does not touch Finding 5.3 below.

**Finding 5.3 — the repair loop built for this failure never runs.**

Two mechanisms cover this failure class, and the wrong one wins. Reading the
two runs' `pipeline_events` rows:

```
2026-08-12 23:54:43  gate_enforced  contracts  {"check": "missing_artifact", ...}
2026-08-12 23:54:43  failed         RuntimeError: Specialist(s) did not produce
                                    canonical artifact: econometrics_specialist
                                    -> econometric_spec.md missing
2026-08-15 00:29:32  gate_enforced  contracts  {"specialist": "econometrics_specialist", ...}
2026-08-15 00:29:32  failed         RuntimeError: All specialists failed in
                                    parallel batch: ... econometric_spec.md: file not written
```

Both halts are raised inside the analysis phase — the first by `guard_artifacts`
(`src/core/specialists/dispatcher.py:233`), the second by the specialist-boundary
contract check (`src/core/specialists/base.py:179`). The strategist's estimation
gate (`runner.py:547`) is a *later* phase, and it contains a repair loop that
re-dispatches `econometrics_specialist` up to three times with the contract
feedback and any script traceback injected into the retry prompt. Its own comment
says it exists because "the specialist-level contract flips a bad econometrics
attempt to failure, but nothing compelled the strategist to re-dispatch". It
never gets the chance: the phase raises first, so the run ends after one attempt.

The asymmetry is the odd part. An `estimation_results.json` that exists but is
hollow reaches the gate and gets three repair attempts. An `econometric_spec.md`
that is *missing* gets zero. The halt itself is right — writing a placeholder
would be the degrade-to-output failure this project is built against — but
halting and repairing are not alternatives, and the repair path is currently
dead code for the case it names.

**Finding 5.4 — the gate event cannot tell you which check stopped the run.**

The resume attempt failed two contracts at once, and the event records both in
one string:

```json
{"gate": "contracts", "enforced": true, "regime": "off",
 "detail": "econometric_spec.md: file not written;
            estimation_results.json: identified-spec contract: declared controls
            ['log_vix', 'd_dgs2', 'halving_window'] appear neither in
            main.controls nor among main.coefficients ..."}
```

The code is correct: `enforced` is `bool(blocking)`, and only the missing file
was blocking — the identified-spec mismatch is a verification check, which
regime `off` shadows, and it was logged as shadowed in the process log. But
`detail` concatenates blocking and shadowed failures indiscriminately, and
`detail` is what survives into the database. An analyst reading these rows would
attribute the halt to a verification check that this regime deliberately did not
enforce. Since the whole experiment is a comparison of what each regime enforces,
the one field that records enforcement should not be ambiguous about it. A
`blocked_by` / `shadowed` split in the payload is additive and would not disturb
existing fields.

Second, substantively: the estimation the specialist *did* produce omitted all
three declared controls from its headline specification. Under `contracts` or
`full` that blocks; under `off` it is shadowed and the paper would have carried a
main result that does not implement its own declared design. That is the
experiment's treatment effect appearing in a single cell, and it is worth
retaining as an illustration.

---

## What this implies for the instrument

Two things, one operational and one about the experiment.

**The run is not verified to the standard the paper is.** Findings 2.1 and 2.2
describe a pipeline whose code and configuration live in an invisible background
process and can be silently ignored. That is not hypothetical: it invalidated a
run in the session that produced this document, and it was caught by reading
specialist timestamps, not by anything the system reported. Every number in a
paper is traceable to a sidecar; nothing about the run records which code,
interpreter, or concurrency produced it. A run record stating git SHA,
interpreter, effective concurrency, and backend would close that gap, and it is
smaller than anything already built for the paper.

**A halted run yields no measurement.** The harvest for the concurrency-1 cell:

```
status=failed  completed=0  measured=0  checks_skipped="numbers,citations"
enforced_gate_blocks=1
"1/1 runs were not measurable"
```

Fail-closed converts a fabricating run into a run with nothing to score. If halt
rates differ across regimes — and they will, since that is the mechanism — then
comparing fabrication among completed papers compares selected samples. The
outcome needs a third category (*completed and verified* / *completed and
fabricated* / *halted*), and the headline claim should be about the joint
distribution.

The generated `summary.md` has already drifted from the code. It still asserts
that "under `off`/`contracts` the deterministic gates ran in shadow (computed +
logged, did not block)" while the same run reports `enforced_gate_blocks=1`
under `off`. The sentence describes the pre-split system.
