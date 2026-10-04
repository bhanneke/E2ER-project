# The researcher step

A researcher step is a point in a template where the run stops for the researcher. There the researcher can approve and continue, edit one of the step's files, give an instruction for the following steps, or send an earlier step back with a remark. Everything done at a researcher step appears in the study's dossier, so readers see where the researcher decided and where the specialists worked.

## In a template

```toml
# Stop after the draft and the estimation check, before the reviewers read it.
[[steps]]
kind  = "researcher"
name  = "review_draft"
files = ["paper_draft.tex", "abstract.tex"]

# Stop inside the initial phase, right after the design specialists, before
# anything else runs.
[[steps]]
kind  = "researcher"
name  = "review_design"
after = ["idea_developer", "literature_scanner", "identification_strategist", "data_architect"]
files = ["paper_plan.md", "identification_strategy.md"]
```

`files` names the workspace files the researcher sees and may edit. A step with `after` stops as soon as those specialists have written their output; while it is open, no other specialist of the initial phase runs, so nothing, estimation included, happens before the researcher has seen the design. `e2er run --review-at STAGE` still works and stops after that stage in the same way.

`pipelines/empirical-preregistered.toml` is the empirical template with a design review, a pre-registration and a review of the draft.

## Pre-registration

A `preregister` step assembles `preregistration.md` from the design files (question and hypotheses, identification strategy, the machine-readable identification, the analysis plan) and stops for the researcher, who may edit it. Approving it freezes it: the file's SHA-256, the SHA-256 of the plan files and the time go into `preregistration.lock.json`.

Nothing may be estimated before the freeze. When the pre-registration comes up, e2er looks for estimation output in the workspace: the econometrics specialist's results and scripts, any script that estimates, result tables and figures, result files (csv, tsv, parquet, json, xlsx outside `data/` named as results or with columns such as `car_*`, `abnormal*`, `coef*`, `t_stat`, `p_value`), and data tables named as results. If there is any, the run stops at the step with the list (a `preregistration` check, recorded in the dossier) and approving does not pass it. Send back the specialist that produced it: the outputs are moved to `set_aside/<time>/` with a manifest of their fingerprints and row counts, the move appears in the dossier, and the check runs again. Nothing is deleted.

From then on the estimation check compares the plan files with those fingerprints. A change to the plan after the freeze stops the run there, before the estimation, at a researcher step that names each changed file with its SHA-256 at the freeze and now. The researcher then decides:

- approve: the change stays as a deviation from the pre-registered plan. The decision and each changed file (SHA-256 at the freeze and the approved one) are recorded in `preregistration.lock.json` and in the dossier, and the deviation is disclosed. A later change to the same file needs approving again.
- edit the file back to the frozen version (`e2er review --edit`), then approve; there is no deviation.
- send back the step that changed it; the check runs again when it is done.

Without one of these the estimation does not run. `e2er verify` reports "estimation follows the pre-registered plan (frozen <date>)", or the deviations the researcher approved (the check passes and lists them), or a change nobody approved (the check fails).

`e2er preregister deposit <paper_id> --zenodo` deposits the frozen file on Zenodo with the researcher's own token (`ZENODO_TOKEN`; `--sandbox` uses Zenodo's sandbox and `ZENODO_SANDBOX_TOKEN`) and records the DOI. Nothing passes through e2er.org. A deposit on OSF Registries is not built yet.

## Using it

In the dashboard a paused run shows **Review step**: the step's files in an editor, a field for an instruction, a list of steps that can be sent back, and **Approve and continue**.

From the command line:

```
e2er review <paper_id>                                   # shows the step and asks what to do
e2er review <paper_id> --edit paper_plan.md              # opens the file in $EDITOR
e2er review <paper_id> --instruction "Use monthly data."
e2er review <paper_id> --send-back identification_strategist --remark "Add an instrument."
e2er review <paper_id> --approve
```

An instruction is kept in `researcher_instructions.md`; every later specialist and the strategist receive it. Sending back re-runs that template step (and the steps after it) or that specialist with the remark, then the run stops at the same researcher step again.

A study that is no longer stopped at a researcher step (a completed one, say) can be sent back too:

```
e2er rerun <paper_id> --from compare --remark "Write the report again from the comparison."
```

The step and every step after it run again with the remark (a researcher step cannot be the start); their approvals are withdrawn, so the run stops at the next researcher step, where the new result needs approving.

## When output keeps failing its check

A specialist's output is checked against its contract after every attempt, and a failed check is
fed back into the next attempt. When the last attempt still fails, the run stops at the
researcher step `output_contract`. It lists, per specialist, each attempt's violations and the
files involved. You can keep the output as it is (`e2er review <id> --approve`; recorded in the
dossier, and the step that wrote it is marked as failing its check), edit one of the files, give
an instruction, or send the specialist back with a remark (`--send-back data_analyst --remark
"..."`), which gives it new attempts. `e2er resume` alone also gives it new attempts. The
specialists of the same batch that passed keep their output. A crash or an unavailable backend
still fails the run, which can then be resumed.

## In the dossier

Each action is a workflow step of type `researcher`: `edit` (file, SHA-256 before and after), `instruction` (the text), `send_back` and `rerun` (target and remark), `approve` (at a change to the pre-registered plan, with `decision: deviation_approved` and the changed files), `preregistration_frozen` (SHA-256), and `supplied_input` (a file the researcher supplied, such as the paper in the replication template: file, SHA-256, and the SHA-256 it replaces when it was changed). A frozen pre-registration also appears as its own block: file, SHA-256, time of freezing, the deviations the researcher approved and, after a deposit, the DOI. Dossiers with either use the format `e2er-dossier/0.4`; a study without them keeps `0.3`, so existing dossier addresses stay valid.

A send-back revises the specialist's work, not the researcher's: files the researcher edited at a researcher step are not requested from the specialist again, and if it rewrites one anyway, e2er puts the researcher's version back, keeps the specialist's in `set_aside/`, and records both fingerprints.
