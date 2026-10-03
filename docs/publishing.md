# Publishing a study

`e2er publish <folder>` describes an exported study, writes its dossier and, with `--to https://e2er.org`, publishes the description. The files stay on your computer or in your repository; e2er.org receives the description, the dossier and a fingerprint (SHA-256) of every file.

## The run's database

The dossier lists the steps of the run: each specialist with its model, each check, each of your actions as researcher, and the run's outcome. `e2er publish` reads them from the study's run database, which it finds the way the server does: `--db` when you give it, else the database the study folder's `.env` names (`DATABASE_URL`), else e2er's default `~/.e2er/papers.db`. The database must hold the run of the paper the folder was exported from (its id is in `provenance.json`); a database of another study is refused, and without one publish stops and says where it looked.

`--no-db` publishes a folder whose database is gone. The dossier then records the template, components and data but no steps, no commit and no researcher actions, says so (`run.workflow_recorded: false`), and the paper's footnote says so too.

Each part of a run that a process ran (every start and resume) is a segment with the e2er commit and version it ran on (`e2er.segments`); every step names its segment, and every template, specialist, skill and connector is pinned at each commit it ran on. A file git cannot find at that commit is recorded as unresolved. In runs started after e2er 0.12.1 the runner records, with each step, the SHA-256 of every file the step wrote and the skills it read; for runs before that, the dossier gives the exported file's hash, as `sha256_at_export`, to the last step that wrote it.

## What publish changes in the folder

Publish first checks that every file is still the one `provenance.json` lists; a folder edited after export is refused, and nothing in it changes. Publish then changes a few files: it points `paper.tex` at the bibliography the folder ships, escapes `refs.bib`, puts the demonstration disclaimer into (or takes it out of) the reproduction report, and stamps the paper's first page with the dossier link and, for a demonstration study, the disclaimer (the author line `<name> with e2er` only with `--name`). Each change is recorded in `provenance.json` as an amendment: the file, its fingerprint before (the exported one for the first change), after, and why. `e2er verify` checks that the amendments of each file link up.

## Data and code: public or private

You state separately whether the study's data and its code are public:

```
e2er publish ./my-study --owner you --project my-study --data private --code public \
  --repo https://github.com/you/my-study --commit 3b91f0e
```

Both are private unless you say otherwise; run in a terminal without the two flags, `e2er publish` asks. For private material, only fingerprints are published, never contents or an address. For public material, give its address with `--data-url` or `--code-url`; public code defaults to your repository at the pinned commit.

The study page and the dossier show what you chose, for instance "data private · code public". A dossier lists availability only when something is public, so a private study's dossier address does not change.

### Data with terms of use: the Global Macro Database

Data loaded with `e2er-data gmd` come under the GMD's terms (version 1.1, https://www.globalmacrodata.com/license.html): free for academic use; a study's replication package may include the GMD data it used, labelled as GMD data; the data may not be republished anywhere else. Whatever you choose, the study's description (`e2er.json`) names the GMD, its terms and its citation on the data files that hold GMD data, and the dossier lists each GMD load with the same. The GMD citation is added to the paper's references when the data are loaded.

Publishing the GMD data with the study (`--data public`, also with `--zenodo`) needs your confirmation. In a terminal, publish shows the terms and asks; otherwise add `--accept-data-terms gmd`. Without it, publish refuses and changes nothing. With `--data private` no confirmation is needed. A Zenodo deposit of GMD data takes Zenodo's licence "Other (Non-Commercial)" and states the GMD terms and citation in its description.

## A DOI for public data and code in one step

`--zenodo` deposits the public data and code on Zenodo with your own account and records the DOIs:

```
export ZENODO_TOKEN=…   # a personal token from zenodo.org, scope deposit:write
e2er publish ./my-study … --data public --code public --zenodo
```

The data files are deposited one by one, the code (`code/` and `replication/`) as one zip. Each deposit names the study's authors with their ORCID iDs, its licence, and links back to the study page and the dossier; the DOIs go into the dossier and the study page. The files go from your computer straight to Zenodo; the token is never sent to e2er.org. Private material is never deposited.

The DOIs are reserved first (drafts), everything that can still fail runs next (the dossier, the paper's stamp and recompile, the checks), and the deposits are published last. The reserved deposits are recorded in `.e2er/zenodo.json`; if publish stops on the way, or the platform refuses the request, the next publish reuses them, so a retry makes no new deposits and gives the same dossier.

To try it first, use Zenodo's sandbox (`--zenodo-sandbox`, token in `ZENODO_SANDBOX_TOKEN`), or add `--dry-run` to see what would be deposited without depositing anything.

## Demonstration studies

`e2er publish --demonstration` (or `E2ER_PURPOSE=demonstration` in the study folder's `.env`) marks a study as published only to demonstrate e2er: e2er.json and the dossier record `purpose: "demonstration"`, and the paper's first page carries the disclaimer; with `--template replication` the study is recorded as `kind: "replication"`, and the paper and the reproduction report carry the replication wording (src/core/demonstration.py).

The purpose recorded on the study when it started (the dashboard's "demonstration" box) counts as well; a study published again without a purpose loses the disclaimer in the report and on the paper.

## Checking a published study

`e2er verify <folder>` checks the folder against its own `provenance.json`, and `e2er.json` and `.e2er/link.json` against it. Whoever holds the folder can rewrite all three consistently, so this alone verifies the folder against itself, and verify says so. `e2er verify <folder> --against https://e2er.org/<owner>/<project>` also compares the folder's content id (the SHA-256 of `provenance.json`, which fixes every file) with the versions e2er.org published, reading them with a GET request; `--against https://e2er.org/d/<id>` compares the dossier, and `--against-file` a saved copy of either.
