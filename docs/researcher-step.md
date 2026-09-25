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

From then on the estimation check compares the plan files with those fingerprints, and `e2er verify` reports either "estimation follows the pre-registered plan (frozen <date>)" or what changed. A change is a deviation that is disclosed, not a failure of the run.

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

## In the dossier

Each action is a workflow step of type `researcher`: `edit` (file, SHA-256 before and after), `instruction` (the text), `send_back` and `rerun` (target and remark), `approve`, and `preregistration_frozen` (SHA-256). A frozen pre-registration also appears as its own block: file, SHA-256, time of freezing and, after a deposit, the DOI. Dossiers with either use the format `e2er-dossier/0.4`; a study without them keeps `0.3`, so existing dossier addresses stay valid.
