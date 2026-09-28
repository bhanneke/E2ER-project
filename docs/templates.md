# Templates

A template is a pipeline file in `pipelines/` (schema:
`docs/schemas/pipeline.schema.json`). A run follows the template chosen when the
paper is created; resume keeps it. e2er ships three:

| Template | For |
|---|---|
| `empirical` | Question and data in, empirical paper out. The default. |
| `empirical-preregistered` | `empirical` with a design review, a pre-registration frozen before estimation, and a review of the draft (see `researcher-step.md`). |
| `event-study-finance` | Abnormal-return event studies around announcements; checks the estimation window and overlapping events before estimation. |

## Skills and files a template adds

A template can give its specialists extra skills and ask them for extra
machine-readable files, for its own runs only:

```toml
[skills]
identification_strategist = ["econometrics/event-study"]

[sidecars]
identification_strategist = ["event_design.json"]
```

Both are added after the specialist's own entries in
`src/core/specialists/registry.py`, never instead of them. A skill must name a
file e2er ships (`skills/files/<path>.md`) or has installed; an unknown skill,
specialist or file name stops the template from loading. The merged skills are
listed in the study's description (`e2er.json`, `components.skills`) and pinned
in its dossier; the run also logs them as a `template_components` event.

## `event-study-finance`

A fork of `empirical-preregistered` with one more step: the `event_window`
check, which runs inside the initial phase after the identification strategist,
the data architect and the data analyst, and before the econometrics specialist.
The identification strategist declares the events and windows in
`event_design.json` (schema in `skills/files/econometrics/event-study.md`). The
check fails, and the run stops before estimation, when

- the estimation window is shorter than `min_estimation_days` (default 120
  trading days) or ends fewer than `min_gap_days` (default 10) before the event
  window;
- more than `max_overlap_share` (default 0) of the events overlap in their event
  windows for the same firm or asset, and the design declares no treatment for
  overlaps (`drop`, `cluster` or `aggregate`);
- an event date is not a trading day in the data calendar the design names, or
  a window runs past the data.

The three settings are in the template, under the gate's `[steps.settings]`.
A failed check stops the run at the check with its reasons (`e2er review`
shows them): edit `event_design.json` or send the identification strategist
back, and the check runs again on resume. Approving does not pass it. Each
verdict is recorded like the other checks and appears in the dossier. With
`on_fail = "retry"` the identification strategist is sent back once with the
reasons before the run stops; with `"shadow"` the verdict is only recorded.

A gate step with `after = [...]` is how any check can sit inside the initial
phase; it also runs before a group that contains the econometrics specialist,
so a plan that leaves out one of the named specialists does not skip it.
