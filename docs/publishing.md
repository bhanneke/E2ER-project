# Publishing a study

`e2er publish <folder>` describes an exported study, writes its dossier and, with `--to https://e2er.org`, publishes the description. The files stay on your computer or in your repository; e2er.org receives the description, the dossier and a fingerprint (SHA-256) of every file. With `--github` the files go to a public GitHub repository of yours (see below). The dossier's address (in the paper's footnote, e2er.json and the output) is on the platform you publish to: `--to`, else `E2ER_URL`, else https://e2er.org. Prepare with `--offline` under the same `E2ER_URL` you publish to, or the footnote changes when you publish.

## Publish asks first

Nothing leaves your computer before you say yes. When the rehearsal of the request has passed, `e2er publish` prints what goes where and asks:

```
What goes where:
  https://e2er.org (ada/road-deaths): the description, the dossier, file fingerprints
  GitHub github.com/ada/studies, folder road-deaths: the study's files as `e2er pack` ships them (public)
Publish 'Road deaths in 2021' to https://e2er.org as ada? Files to GitHub ada/studies/road-deaths. [y/N]:
```

Only `y` or `yes` publishes; anything else (or Enter) sends nothing, pushes nothing and leaves the folder as it was. With `--zenodo` the question names the Zenodo deposits too. A run without a terminal on standard input (a script, a CI job) cannot be asked, so it needs `--yes` (`-y`); without it publish refuses at once, with nothing sent. `--dry-run` never asks and never sends, with or without a terminal. The dashboard's Publish button asks the same question in the browser and sends the yes along with the request (`confirm: true` on `POST /api/papers/<id>/publish`); the local server refuses a publish without it.

## Publishing from CI: a token for one study

Your personal login (`e2er login`, kept in the system keychain) can publish any study under your handles. A CI job should not hold it. Give it a token that can only publish new versions of one study:

```
e2er login --scope study:ada/road-deaths | gh secret set E2ER_TOKEN      # approve in the browser
e2er token create --study ada/road-deaths | gh secret set E2ER_TOKEN     # or with your personal login, no browser
```

The token is printed once, alone on standard output, so it can go straight into the CI secret; e2er does not keep it, and your personal login stays as it is. Such a token publishes new versions of `ada/road-deaths` only: it cannot create a study or a handle, cannot publish another study, cannot withdraw a study, and cannot create or list tokens. The study must already be published. In the CI job:

```
env:
  E2ER_TOKEN: ${{ secrets.E2ER_TOKEN }}
run: e2er publish ./study --owner ada --project road-deaths --to https://e2er.org --yes
```

`e2er whoami` with such a token says which study it is for. Revoke it on your account page (e2er.org/account) or with `e2er logout` run with it in `E2ER_TOKEN`, which ends that token and leaves a login saved on the computer as it is. On the platform the token is a row of `api_token` with the study in its `study` column (`POST /api/v1/tokens` with `{"study": "<owner>/<slug>"}`); e2er refuses to keep a token from a platform that does not limit it to the study.

## Running e2er inside your own test suite

When e2er runs inside a test runner it never uses your own login and never publishes anywhere but a local test server. A test run is one with `PYTEST_CURRENT_TEST` set (pytest sets it for every test, and a command a test starts inherits it), `E2ER_TEST=1` (set it for any other runner, or for a shell script of tests), or `CI=true` together with a test command (pytest, unittest, nose2, tox, nox). In a test run:

- e2er never reads or writes the system keychain or `~/.e2er/credentials.json`; the Zenodo token saved in Setup or the keychain is not read either. Only `E2ER_TOKEN`, `ZENODO_TOKEN` and a credentials file the test names itself (`E2ER_CREDENTIALS`) are used.
- Every request to a platform or to Zenodo is refused before it is made unless it goes to `localhost`, `127.0.0.1` (or another loopback address), or the one address in `E2ER_TEST_SERVER`, for a local copy of the platform your tests run. `E2ER_TEST_SERVER` may never name e2er.org or one of its subdomains. The refusal says "e2er is running under a test runner … Nothing was sent."
- `gh` is not run and nothing is pushed to GitHub (e2er's own tests run a fake `gh` and say so with `E2ER_TEST_GITHUB=fake`).

So a test that calls `e2er publish --to https://e2er.org --yes` on a machine signed in to e2er.org publishes nothing. (On 2026-10-20 a run of e2er's own tests did, with the machine's keychain token; the guard is in `src/core/test_guard.py`.)

## The run's database

The dossier lists the steps of the run: each specialist with its model, each check, each of your actions as researcher, and the run's outcome. `e2er publish` reads them from the study's run database, which it finds the way the server does: `--db` when you give it, else the database the study folder's `.env` names (`DATABASE_URL`), else e2er's default `~/.e2er/papers.db`. The database must hold the run of the paper the folder was exported from (its id is in `provenance.json`); a database of another study is refused, and without one publish stops and says where it looked.

A folder published before whose database is gone (`.e2er/link.json` names the version it published) carries over that version's dossier instead. Publish fetches the dossier from the platform the folder was published to and uses it only when everything agrees: `.e2er/link.json` and `e2er.json` name it, the platform's latest version of the study is that dossier and that content, the document hashes to its id, and the data fingerprints are this folder's. The new version's dossier is that document with its steps, segments, events, components and outcome unchanged, the new availability (for instance the files on GitHub), and an amendment on `e2er.json` (`kind: "carried_over"`, `from_version`, `from_dossier`, the e2er version that published it) whose reason reads "published again with files on GitHub; run database not available, dossier carried over from version N". e2er.json's description of the run (agents, process, skills) is the earlier version's. No step is added, removed or rebuilt, and the output says what was carried over. A version published from somewhere else, another project, a dossier that does not hash to its id or an unreachable platform is refused, and nothing in the folder changes.

`--no-db` publishes a folder whose database is gone. The dossier then records the template, components and data but no steps, no commit and no researcher actions, says so (`run.workflow_recorded: false`), and the paper's footnote says so too.

Each part of a run that a process ran (every start and resume) is a segment with the e2er commit and version it ran on (`e2er.segments`); every step names its segment, and every template, specialist, skill and connector is pinned at each commit it ran on. A file git cannot find at that commit is recorded as unresolved. A skill is named by where it comes from: e2er's own as `skill:e2er/<category>/<name>`, a skill from an installed pack (`~/.e2er/skills/<pack>/<skill>.md`) as `skill:<pack>/<skill>`, the id e2er.org lists it under, so the dossier links the listed part and its author is credited. A pack's skill is not part of e2er and has no pin at an e2er commit. In runs started after e2er 0.12.1 the runner records, with each step, the SHA-256 of every file the step wrote and the skills it read; for runs before that, the dossier gives the exported file's hash, as `sha256_at_export`, to the last step that wrote it.

## What publish changes in the folder

Publish first checks that every file is still the one `provenance.json` lists; a folder edited after export is refused, and nothing in it changes. Publish then changes a few files: it points `paper.tex` at the bibliography the folder ships, escapes `refs.bib`, puts the demonstration disclaimer into (or takes it out of) the reproduction report, and stamps the paper's first page with the dossier link and, for a demonstration study, the disclaimer (the author line `<name> with e2er` only with `--name`). Each change is recorded in `provenance.json` as an amendment: the file, its fingerprint before (the exported one for the first change), after, and why. `e2er verify` checks that the amendments of each file link up.

## Data and code: public or private

You state separately whether the study's data and its code are public:

```
e2er publish ./my-study --owner you --project my-study --data private --code public \
  --repo https://github.com/you/my-study --commit 3b91f0e
```

Both are private unless you say otherwise; run in a terminal without the two flags, `e2er publish` asks. For private material, only fingerprints are published, never contents or an address. For public material, give its address with `--data-url` or `--code-url`; public code defaults to your repository. The dossier names the repository, not the commit: the dossier's address is in the paper's footnote and the paper's fingerprint in provenance.json, so a commit-dependent dossier would change the very files the commit holds. The commit (`--commit`) is recorded beside the files, in e2er.json and in the publish request; e2er.org stores it with the study version, reads every file at it and compares it with provenance.json and the published fingerprints. So you can prepare the folder (`e2er publish --offline`), commit it, and publish with `--commit`: nothing the commit holds changes.

The study page and the dossier show what you chose, for instance "data private · code public". A dossier lists availability only when something is public, so a private study's dossier address does not change.

### The paper

The paper is private unless you publish its PDF's address: `--paper public --paper-url https://…/paper.pdf`. Without `--paper-url`, a public paper points at `paper/paper.pdf` in your repository at `--commit`. The address goes into `e2er.json` and the publish request only, never into the dossier, so stating it changes no fingerprint: publishing the same folder again with `--paper public` keeps the version and adds the link.

### What readers see for what is not public

On e2er.org, a paper, data or code that is not public has a button "Ask the authors for …" on the study page and the dossier, with the number of readers who asked (no names). A signed-in reader writes a short message; e2er.org forwards it to the authors who have an account there, without showing anyone's address. The reader may agree to be answered by email. You find the requests on your page "My submissions" (e2er.org/me), with the command that publishes the item; publishing it on a new version closes every open request for it and tells the readers. You can also mark a request as answered privately, decline it, or stop receiving requests.

`e2er publish` and the dashboard's finish page say this in one sentence for each item you keep private, with the flag that publishes it. Data from a source with terms of its own get no such note: the note names the source and its reason, and readers on e2er.org see a link to the source instead of a request button. Each source states its own reason: Yahoo Finance's terms allow personal use only; the Global Macro Database's terms do not allow passing the data on outside the study's replication package; Gaia's terms allow non-commercial use only, with credit to ESA/Gaia/DPAC (CC BY-NC 3.0 IGO); the GISCO terms allow non-commercial use only, with the EuroGeographics notice on every map; WHO's terms allow use for public health purposes only, and no changes without WHO's written permission; GitHub grants no licence to redistribute the repository metadata. The README's data source table lists the same reasons, from the same definitions.

### Data with terms of use: the Global Macro Database

Data loaded with `e2er-data gmd` come under the GMD's terms (version 1.1, https://www.globalmacrodata.com/license.html): free for academic use; a study's replication package may include the GMD data it used, labelled as GMD data; the data may not be republished anywhere else. Whatever you choose, the study's description (`e2er.json`) names the GMD, its terms and its citation on the data files that hold GMD data, and the dossier lists each GMD load with the same. The GMD citation is added to the paper's references when the data are loaded.

Publishing the GMD data with the study (`--data public`, also with `--zenodo`) needs your confirmation. In a terminal, publish shows the terms and asks; otherwise add `--accept-data-terms gmd`. Without it, publish refuses and changes nothing. With `--data private` no confirmation is needed. A Zenodo deposit of GMD data takes Zenodo's licence "Other (Non-Commercial)" and states the GMD terms and citation in its description.

### Data with terms of use: Yahoo Finance

Data loaded with `e2er-data yfinance` come under Yahoo's terms of use (https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html). The yfinance project notes that Yahoo's finance data are intended for personal use only; yfinance is not affiliated with Yahoo. The study's description names Yahoo Finance and these terms on the data files that hold Yahoo data. Yahoo publishes no citation format, so publish asks for no BibTeX entry; the dossier lists each load with the citation e2er wrote for it.

If the data stay private, readers on e2er.org see a link to Yahoo Finance instead of a request button, and publish does not suggest publishing them. Publishing them with the study (`--data public`) needs your confirmation that you know Yahoo's terms allow personal use only: in a terminal publish asks "Publish the Yahoo Finance data with the study although Yahoo's terms allow personal use only?"; otherwise add `--accept-data-terms yfinance`. e2er does not deposit Yahoo data on Zenodo: a deposit republishes the data for anyone to reuse, which no Zenodo licence reconciles with personal use only. `--zenodo` with public Yahoo data is refused before anything is written or sent; keep the data private to deposit the code alone.

### Data with terms of use: GitHub

GitHub's Acceptable Use Policies (section 7, Information Usage Restrictions) allow research use of public, non-personal information only if the resulting publications are open access. A study that used data loaded with `e2er-data github` is therefore published with its paper public: `e2er publish` refuses `--paper private` (the default) for it, says why, and changes nothing; add `--paper public --paper-url <address of the PDF>`, or set the paper to public on the finish page, which states the same reason next to the paper. GitHub also grants no licence to redistribute the repository metadata, so publishing the data with the study needs `--accept-data-terms github`, and the replication package loads them again.

## A DOI for public data and code in one step

`--zenodo` deposits the public data and code on Zenodo with your own account and records the DOIs:

```
export ZENODO_TOKEN=…   # a personal token from zenodo.org, scope deposit:write
e2er publish ./my-study … --data public --code public --zenodo
```

The data files are deposited one by one, the code (`code/` and `replication/`) as one zip. Each deposit names the study's authors with their ORCID iDs, its licence, and links back to the study page and the dossier; the DOIs go into the dossier and the study page. The files go from your computer straight to Zenodo; the token is never sent to e2er.org. Private material is never deposited.

The DOIs are reserved first (drafts), everything that can still fail runs next (the dossier, the paper's stamp and recompile, the checks), and the deposits are published last. The reserved deposits are recorded in `.e2er/zenodo.json`; if publish stops on the way, or the platform refuses the request, the next publish reuses them, so a retry makes no new deposits and gives the same dossier.

To try it first, use Zenodo's sandbox (`--zenodo-sandbox`, token in `ZENODO_SANDBOX_TOKEN`), or add `--dry-run` to see what would be deposited without depositing anything.

## The files in a public GitHub repository

`--github` puts the study's files in a public GitHub repository with your own GitHub login and links them from the study page and the dossier:

```
gh auth login                       # once; or set GH_TOKEN to a token of your own
e2er publish ./my-study --owner you --project my-study --github --to https://e2er.org
e2er publish ./my-study --owner you --project my-study --github you/studies --github-path my-study --to https://e2er.org
```

`--github` alone uses the repository `<your login>/<project>` and makes it (public) when it does not exist. `--github owner/name` uses that repository, making it when it does not exist; `--github-path <folder>` puts the study in a folder of it, so several studies can share one repository. The push uses the GitHub command line tool (`gh`) with your login, or `GH_TOKEN`; without `gh`, or when it is not logged in, publish says what to run and changes nothing. e2er.org never receives a GitHub token: it reads the public files at the commit, as for any study that names a repository. A private or archived repository is refused. There is no Zenodo deposit and no DOI on this path; the dossier id identifies the study, so `--github` does not go with `--zenodo`, `--repo`, `--commit`, `--path`, the `--…-url` options or `--data/--code/--paper private`.

**What goes up** is what `e2er pack` ships: the paper (PDF and LaTeX), the code, the results, the design and reviews, `reproduce.json`, `provenance.json`, `e2er.json` with the dossier, the package's `e2er-package.json` and its pinned environment, and the data whose source's terms allow passing them on. Data a source's terms keep out (the GMD, Yahoo Finance, the WHO GHO, Gaia, GISCO, GitHub) stay out, and so do files the study built from them: data files, and results that hold the source's rows (a units table of 244 regions, a figure spec with a point per star). A table of estimates or a handful of group means built from them is an aggregate and goes up (few rows against the source, no identifier of the source; the rule is in `docs/STRUCTURED_EXPORT_SPEC.md`), and so do the rendered figures. `e2er-package.json` names each left-out file with the reason, and `e2er reproduce` on a clone loads the data from the source again and builds the derived files with the study's own scripts; `e2er verify` on a clone skips a check that needs a left-out file and says which. Right before the commit, publish checks once more that no such file is in the folder, and it refuses a file that holds a key or token. `--dry-run` lists every file that would go up and every file that stays out, and pushes nothing.

**Files larger than GitHub takes (100 MB).** A data file over the limit (under `data/`, or a data output under `results/`, `misc/` or `paper/`) stays out when a step of the study's `reproduce.json` loads or builds it again. `e2er-package.json` declares it like a file left out under a source's terms, with `kind: "size"` (and `host`, `bytes`), and README.md says why and how a rerun gets it back: "`data/data.db`: too large for GitHub (145 MB); `e2er reproduce` loads the tables … again from the sources with code/get_data.py". A database counts as rebuilt only when every table a step reads is loaded again or built by a recorded step; a table no step reads (reproduce.json's `database`, `read: false`) is not needed and the README names it ("does not need the tables …"). A file over the limit that nothing gets back (no step loads or builds it, it holds a table no step builds, it is the published result itself, or it is not data) stops the publish, in `--dry-run` too, and nothing is pushed: "GitHub does not take files larger than 100 MB, and no recorded step of the study gets these back, so a copy without them could not be run again: data/data.db (145 MB): no step of reproduce.json loads it or builds it again". In a clone, `e2er verify` counts such a file as left out, not missing, only when the folder's `provenance.json` records it larger than GitHub's limit, and `e2er reproduce` loads and builds it again. `e2er pack` alone leaves nothing out for its size.

**README.md** opens with what a visitor of the repository needs: the title, the question, the dossier link, the demonstration label of a demonstration study, the e2er version, template and model, each data source with its terms and citation, the files left out and how `e2er reproduce` rebuilds them, and the licence of the code and text (`--license`, or a sentence that none was set). The export's own README follows below. The change is an amendment of README.md (`kind: "readme"`); like the paper's stamp, it names the dossier, so the dossier does not list it.

**How it is pushed.** One ordinary commit on top of the repository's default branch, never a force push; a repository that moved meanwhile is reported and nothing is overwritten. Only the study's folder changes: in the repository's root, or in `--github-path`. A folder that holds files of anyone else, or of another study, is refused, and so is a folder inside another study's folder. Publishing a new version adds a commit; publishing the same files again adds none.

**Only with a platform, and in this order.** The files go to GitHub only as part of a publish on a platform: `--to`, else the platform `.e2er/link.json` records (where the folder was published before), else e2er.org; publish says which. A run that would push without a platform is refused. The registration names the commit that holds the files, so the push comes first, and everything that can be checked before it is: the rehearsal of the request in a scratch copy, the sign-in on the platform (`GET /api/v1/me`; not signed in, or a refused sign-in, pushes nothing) and the files themselves. If the platform still refuses the registration after the push (an owner or dossier conflict it checks only when it receives the request), publish names the files' address and says so: run the same command again once the problem is solved; the files are already there, so no new commit is made, and the registration is sent again.

**What is recorded.** The repository, the folder and the commit go into `e2er.json` (`repository.url`, `path`, `commit`, with `host: "github"` and `left_out`), `.e2er/github.json` and the publish request. The study page shows "Files: github.com/<owner>/<repo>/tree/<commit>/<folder>"; the paper's address is `paper/paper.pdf` at the commit; public code and data link the `code/` and `data/` folders at the commit. The data are public only when at least one data file went up; otherwise they are private, and readers see the sources' links. The dossier names the repository and never the commit (see above), and the copy of `e2er.json` in the repository records neither the commit nor the paper's address nor the time of publishing: no commit can name itself. e2er.org checks every file at the commit against `provenance.json` and counts a data file the study declares as left out under its source's terms as left out, not missing.

## Taking personal data out before publishing

`e2er redact <folder> --text <text>` replaces every occurrence of the text in the folder's text files with `<redacted>` (`--replace` sets another word) and changes nothing else; before writing, it proves that the new file with the text put back is byte for byte the old one. Each changed file gets an amendment in `provenance.json`: `{path, kind: "redacted", sha256_before, sha256_after, reason: "personal contact details removed by the researcher", redaction: {replacement, count, offsets, removed_bytes, bytes_before}}`. The record never holds the text, nor a hash of it. The next publish shows the redactions in the dossier. `e2er verify` checks that the replacement sits at every recorded offset, and a pre-registered plan file whose only change since the freeze is a redaction passes with "redacted by the researcher after registration: contact details only"; any other change still fails. A folder published before and redacted since still verifies against its `e2er.json` (with the redactions rolled back, `provenance.json` is the published one) until it is published again. `e2er redact <folder> --check --text <text>` rebuilds each redacted file's earlier version with the text and compares its hash value, so whoever knows the text can confirm that nothing else changed. Text in a PDF (searched with `pdftotext`), a database or another binary file, or in a file `provenance.json` does not list, stops the redaction with nothing changed: redact the PDF's LaTeX source and let publish build the PDF again. `--dry-run` says what would change.

## Writing a finished study's abstract again

`e2er abstract <folder>` runs e2er's abstract step on a study that was exported, or published, before the abstract had a step of its own (0.17.4). It lays the study out in a scratch folder (the final `paper/paper.tex`, the results, the reviews), runs the abstract writer once with the configured backend (`--backend`, `--model`), and then the abstract check: at most 160 words; no p-values, intervals, standard errors, Fisher-z or test statistics; at most three numbers, each a value of the study's results at the precision shown; a sentence that states a finding; a last sentence that is no negation and has no "rather than"; none of the constructions the phrase check refuses ("rather than", "X, not Y", the mirrored "changed A; changed nothing about B"). A failure sends the writer back once with the reasons; a second failure changes nothing in the folder. The calls' records go to a scratch database, never to the run's.

On a pass it puts the abstract into `paper/paper.tex` (in place of its abstract, or after the title where it had none), writes `paper/abstract.tex` (the study's `\title` stays in it when it was there), recompiles `paper/paper.pdf` with tectonic and shows the abstract in `report.html`. Each changed file gets an amendment in `provenance.json`: `{path, kind: "abstract_rewritten", sha256_before, sha256_after, bytes_before, model, backend, e2er_version, reason: "abstract rewritten by e2er's abstract step after the abstract fix; the paper's text and results are unchanged"}`, which the next publish puts in the dossier. The command then runs the checks of `e2er verify` and puts every file back when they fail. A published folder still verifies against its `e2er.json` until it is published again (with these amendments rolled back, `provenance.json` is the published one).

`e2er abstract <folder> --from-file <file> --reason "<why>"` puts the researcher's own abstract (a LaTeX abstract environment, or its text) in place of the writer's, for instance to correct one sentence of a written abstract. Nothing is sent to an AI. The abstract passes the same check, number check included, and each changed file gets an amendment of kind `abstract_edited_by_researcher` with the reason and `edited_by: "researcher"`.

## Demonstration studies

`e2er run --demonstration` (or the box in the dashboard's new-study form) marks a demonstration or test run when it starts; the choice is recorded in the study's manifest.json, and `e2er resume`, `e2er rerun`, export and publish keep it. `e2er publish --demonstration` (or `E2ER_PURPOSE=demonstration` in the study folder's `.env`) sets it at publishing: e2er.json and the dossier record `purpose: "demonstration"`, and the paper's first page carries the disclaimer; with `--template replication` the study is recorded as `kind: "replication"`, and the paper and the reproduction report carry the replication wording (src/core/demonstration.py).

The purpose recorded on the study when it started (the dashboard's "demonstration" box) counts as well; a study published again without a purpose loses the disclaimer in the report and on the paper.

## Checking a published study

`e2er verify <folder>` checks the folder against its own `provenance.json`, and `e2er.json` and `.e2er/link.json` against it. Whoever holds the folder can rewrite all three consistently, so this alone verifies the folder against itself, and verify says so. `e2er verify <folder> --against https://e2er.org/<owner>/<project>` also compares the folder's content id (the SHA-256 of `provenance.json`, which fixes every file) with the versions e2er.org published, reading them with a GET request; `--against https://e2er.org/d/<id>` compares the dossier, and `--against-file` a saved copy of either. After the checks, verify notes each sentence of `paper/paper.tex` and `paper/abstract.tex` that uses a construction the writing guidance rejects (the phrase check the draft writers' output contract applies during a run); the note changes neither the verdict nor the exit code.
