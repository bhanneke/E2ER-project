# Configurable pipelines — design

**Status:** design, not implemented. Written 2026-09-22.

The goal: a researcher can define their own research process as a file — their
phases, their specialists, their checks — and run it on e2er without writing
Python. A theory-construction pipeline, a reproduction pipeline and an empirical
pipeline are then three files, not three forks.

What must not become configurable is whether claims are checked.

---

## Where the pipeline actually lives today

Worth stating plainly, because it is easy to get wrong by reading the wrong
file.

`_PHASES` in `src/api/app.py` is **not** the pipeline. It maps phase names to
the artifacts they should produce, for the workflow page's inventory.

The pipeline is `StrategistRunner.run()` in `src/core/strategist/runner.py`:

```python
await _phase("initial",         self._run_initial_phase)
      _phase("iterative",       self._run_iterative_phase)
      _phase("estimation_gate", self._enforce_estimation_gate)
      _phase("self_attack",     self._run_self_attack_phase)
      _phase("polish",          self._run_polish_phase)
      _phase("review",          self._run_review_phase)
      # revision (bypasses _phase — needs the status argument)
      _phase("replication",     self._run_replication_phase)
```

Each phase is a Python method containing budget checks, strategist calls, gate
enforcement and retry logic. So this is a refactor of the runner, not a file
move.

### What is already reusable

Three pieces need no change, which is why this is tractable:

| Piece | Why it already works |
|---|---|
| `WorkOrder` (`specialists/contracts.py`) | One invocation as data: specialist, focus, tools, `output_file`, `sidecar_artifacts`, `parallel_group`, `context_tier` |
| `dispatcher` | `execute_work_order` / `execute_parallel` / `execute_with_dependencies` are pipeline-agnostic — they take WorkOrders and have no idea what sequence they belong to |
| Skills | Already markdown files loaded by name; adding one needs no code |

`registry.py` is four dicts (specialist → artifact, → skills, → sidecars). Data
already; it just lives in Python.

---

## The shape

A pipeline is an ordered list of **steps**. A step is one of four kinds.

| kind | does | existing handler |
|---|---|---|
| `specialists` | dispatch a set of specialists, optionally in parallel | `_run_initial_phase`, `_run_polish_phase` |
| `gate` | run a check; halt, retry or shadow on failure | `_enforce_estimation_gate` |
| `iterate` | strategist loop until a stopping condition | `_run_iterative_phase` |
| `aggregate` | combine reviewer output into a verdict | `_run_review_phase` |

Making gates *steps* rather than a global setting is the point. The pipeline
file then records what was actually checked, in order, and a check can run twice
or mid-process rather than only at the end.

### Format

**TOML**, parsed with stdlib `tomllib` (3.11+, no new dependency). Comments and
multi-line strings matter because `focus` fields are prose and humans write
them.

**Validated against a JSON Schema**, like `structured_review.schema.json`.
Validation is independent of serialisation: parse TOML, validate the dict. So
readability costs nothing.

### A pipeline

```toml
name = "theory-construction"
description = "Develop and formalise a construct, with claims checked against sources."

[[steps]]
kind = "specialists"
name = "Conceptualisation"
run  = ["construct_developer", "boundary_setter"]

[[steps]]
kind    = "gate"
name    = "every claim traces to a source"
check   = "claims"
on_fail = "retry"

[[steps]]
kind     = "specialists"
name     = "Formalisation"
parallel = true
run      = ["theory_specialist", "proof_checker"]

[[steps]]
kind = "aggregate"
name = "Review"
run  = ["mechanism_reviewer", "writing_reviewer"]
```

No numbers gate — a theory paper has no estimated numbers. The claims gate
instead, because that is what it can actually get wrong.

### A specialist

```toml
output   = "construct_map.md"
sidecars = ["constructs.json"]
skills   = ["base/researcher", "reasoning/creative-ideation"]
tools    = ["read_file", "write_file"]

focus = """
Develop the focal construct. State what it is, what it is not, and the
boundary conditions under which it applies. Every claim about prior work
must quote the sentence it rests on.
"""
```

A specialist is then name + skills + output artifact + focus. No Python.

---

## Discovery and precedence

Searched in order; first match wins:

1. `./pipelines/<name>.toml` — project-local, ships with the paper
2. `~/.e2er/pipelines/<name>.toml` — the researcher's own
3. built-in, packaged with e2er

Project-local winning means a paper can carry the exact pipeline that produced
it, which is what makes a pipeline file a citable artifact rather than a local
preference. Same three-level search for `specialists/`.

---

## The floor

A pipeline may add checks and may enforce them harder. It may not remove them.

```
declared checks  =  pipeline's own steps  ∪  MANDATORY
enforcement      =  max(pipeline's, floor's)
```

Without this, "the gates are not yours" stops being true the moment someone
writes their own pipeline — they would simply omit them. This is the same logic
as `KIND_RELIABILITY`, which is enforced even under the `off` regime.

The floor is the reliability-kind checks that already run in every regime.
`GATES = ("contracts", "estimation", "numbers", "citations")` stay available;
which of them a pipeline declares is its business, subject to the floor.

A pipeline that declares no gates at all still runs the floor, and its report
says so — so an unchecked run is visible rather than silent.

---

## What changes

| File | Change |
|---|---|
| `src/core/pipeline/spec.py` | **new** — `PipelineSpec`, `StepSpec`, `SpecialistSpec`, loader, precedence |
| `docs/schemas/pipeline.schema.json` | **new** — validates a parsed pipeline |
| `pipelines/empirical.toml` | **new** — today's pipeline, as a file |
| `src/core/strategist/runner.py` | `run()` interprets a spec; existing phase methods become step handlers |
| `src/api/app.py` | `_PHASES` derived from the active spec rather than hardcoded |
| `src/cli_run.py` | `--pipeline <name>` |

The existing phase methods survive as handlers. The refactor is the sequencing,
not the work.

---

## Tests that must pass

**The one that matters most**

- `test_the_builtin_pipeline_reproduces_todays_sequence` — `pipelines/empirical.toml`
  executed as a spec produces exactly the phase order `initial, iterative,
  estimation_gate, self_attack, polish, review, revision, replication`. If this
  fails, the refactor changed behaviour rather than relocating it.

**The floor**

- `test_a_pipeline_that_declares_no_gates_still_runs_the_floor`
- `test_a_pipeline_cannot_downgrade_an_enforced_gate_to_shadow`
- `test_a_pipeline_may_escalate_a_gate` — shadow → halt is allowed
- `test_the_report_says_which_checks_were_declared_and_which_came_from_the_floor`

**Loading**

- `test_an_unknown_specialist_fails_at_load_not_at_runtime` — naming a
  specialist that does not exist must fail before any model is called, with the
  file and the name in the message
- `test_an_unknown_check_fails_at_load`
- `test_malformed_toml_names_the_file_and_the_line`
- `test_unknown_keys_are_rejected` — a typo'd key is a mistake, not an extension
  point
- `test_a_step_of_unknown_kind_is_rejected`
- `test_an_empty_pipeline_is_rejected`

**Precedence**

- `test_project_local_beats_user_level`
- `test_user_level_beats_builtin`
- `test_a_missing_pipeline_names_where_it_looked`

**Behaviour**

- `test_a_theory_pipeline_runs_without_a_numbers_gate` — and the numbers gate
  does not fire spuriously on a paper with no tables
- `test_parallel_groups_are_preserved`
- `test_a_gate_can_appear_twice_in_one_pipeline`
- `test_on_fail_retry_re_runs_the_preceding_step_once`
- `test_on_fail_halt_stops_the_run_and_records_why`
- `test_budget_checks_still_apply_per_step`

**Specialist specs**

- `test_a_specialist_defined_in_a_file_is_dispatchable`
- `test_a_file_specialist_can_use_a_file_skill` — neither needs Python
- `test_a_specialist_missing_its_output_declaration_is_rejected`

---

## Risks

**The refactor changes behaviour silently.** The golden sequence test is the
guard, and it should be written before the refactor, not after.

**A configurable pipeline produces confident nonsense.** That is what the floor
is for, and it is why the floor cannot be a setting.

**Specialists without skills produce worse output than the built-ins**, and
users will blame the tool. `e2er doctor` should report a pipeline whose
specialists declare no skills.

**Scope.** Steps 1–3 (spec, loader, built-in pipeline as a file) are worth doing
on their own: they make the current behaviour legible and testable without
changing it. Step 4 (user pipelines end to end) is the part that earns the
"reusable research infrastructure" claim.
