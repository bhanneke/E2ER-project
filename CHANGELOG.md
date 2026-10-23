# Changelog

All notable changes to e2er are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Security

Fixes from the security review of 2026-10-23.

- **The dashboard serves no file outside a run's folder.** A run id in a URL became a folder name, so `/api/papers/%2E%2E/artifacts/.env` returned the studies folder's `.env` with the API keys. Every route that takes a run id now accepts a UUID only (404 otherwise), an app-wide check refuses the same for a route that forgets, and `find_workspace` refuses an id that is not a UUID or one plain name (`..`, `/`, `\` never). Hidden files of a run (`.e2er/`, `.history/`) are not served either.
- **Skill packs install inside `~/.e2er/skills` only.** A catalogue entry is someone else's YAML: a pack slug `../../.claude` wrote `~/.claude/CLAUDE.md`, and a skill slug `../../outside/CLAUDE` wrote beside the install root. Pack and skill slugs are now plain names (`a-z`, `0-9`, `-`, `_`, up to 96 characters; the catalogue's own slugs include underscores and run to 70), the resolved path must stay in the install root, `e2er skills remove` refuses the same, and the skill loader refuses a template's skill path with `..`, a backslash, an absolute path or a glob character.
- **The dashboard answers only to this computer, and its API only with the session.** A page on another site that points its own name at 127.0.0.1 (DNS rebinding) could read every run through the open GET routes. Every request now needs a `Host` of 127.0.0.1, localhost or [::1] (plus the `--host` served on, `HOST`, and the names in the new `E2ER_ALLOWED_HOSTS`), else 400; every `/api/` route needs the session token or the `API_AUTH_TOKEN` bearer token (`/health` stays open). The `e2er` commands send the token on their reads too, and check that a server is up through `/health`.
- **A new session token at every start, and a cookie that ends with the browser.** 0.14.0 kept one token per computer in `~/.e2er/session-secret` and a cookie for a year; the file is now removed at start. A tab left open across a restart of e2er needs the link `e2er` prints again.
- **`e2er serve --host <address>` other than 127.0.0.1 needs `API_AUTH_TOKEN`**, and the setting `HOST` defaults to 127.0.0.1 (was 0.0.0.0). The Docker entrypoint refuses to start without `API_AUTH_TOKEN`; docker/README.md says why the container binds 0.0.0.0 and why the published port must stay on 127.0.0.1.
- **No redirect to another site from the launch link** (`//evil.example/x?t=…` answered `Location: //evil.example/x`), and the finish page puts only http(s) links from a platform's or a source's answer into an `href` (a `javascript:` URL ran in the dashboard).
- **The workflows: least permissions, pinned actions, hashed installs.** Every workflow declares `permissions: contents: read` at the top; only the release job and the Zenodo-DOI job write contents, only the PyPI job gets `id-token: write`, only the schema-drift job writes issues (the release workflow gave every job `contents: write` and `id-token: write`). Every action is pinned to a commit SHA (`pypa/gh-action-pypi-publish@release/v1` followed a branch), checkouts keep no credentials, CI and release install from `.github/requirements/ci.txt` and `build.txt` with `--require-hashes` and build without downloading a build backend, and the release workflow keeps no pip cache. docs/RELEASING.md says how to refresh the files.
- **The dashboard's htmx is checked.** `scripts/vendor_htmx.sh` installs a download only when its SHA-256 is that of htmx 1.9.12, and the page loads the file with its `integrity` hash (the shipped file is the published one).
- **The RISE catalogue download is read with caps**: streamed and stopped past 200 MB (it was read whole first), each pack manifest read only up to 2 MB after its declared size is checked, at most 2,000 manifests, and only manifest names that are plain slugs.
- **Table and figure file names are plain names on Windows too.** The renderers refused a `/` in a spec's `filename` but not a `\` or a drive (`..\paper_draft.tex` wrote over the draft on Windows); they now refuse both, hidden names and control characters.
- **A redaction record confirms no guess of the text taken out.** `sha256_before` with the offsets and the length of the text let anyone recover a redacted phone number by trying (0.02 s). `e2er redact` now records the earlier fingerprint keyed (`hmac-sha256:…`, a salt in `~/.e2er/redaction-salt`, mode 600), except where it is public anyway (a pre-registered plan file, a folder published before), and warns about a text shorter than 16 characters. `e2er redact --check` works on the computer that redacted; a second redaction of the file still links up.
- **A copy for double-blind review keeps nothing that confirms the author.** An earlier redaction's fingerprint, offsets and sizes stayed in the blinded copy's `provenance.json`, and a reviewer could confirm the author's name from them. The copy's amendments now lose the first fingerprint before (withheld from the dossier too), all offsets and sizes (verify counts the replacements instead), and a folder with a symbolic link is refused (anonymising "the copy" wrote through a link into the original file).
- **The leak check finds the hidden forms of a name**: joined by `_`, `.`, `-` or nothing (`imogen_quarry.csv`, `ImogenQuarry`), full-width letters, zero-width characters, HTML entities, file names, PDF metadata (`pdfinfo`), compressed PDF streams and hex strings, UTF-16 big-endian text and PNG text chunks. The surname alone and "Imogen Q." are listed for the author to confirm (`--blind-ack-self-citations`).
- **Fetching checks every redirect, pins the checked address and stops at its size limit while reading.** The literature and skill fetches followed redirects inside httpx (a public URL could redirect to 127.0.0.1 or the cloud metadata address unchecked), let a name that did not resolve through to the client's own lookup, connected to whatever a second DNS answer said, and read a whole response before checking its size. Now every hop is checked again (at most 5), a DNS failure is a refusal, the connection goes to the address that was checked (the certificate is still checked for the name), and the body is read in chunks up to the cap. A redirect to another origin carries only plain headers: an API key in `Zotero-API-Key`, NOAA's `token` header or a data source's own headers no longer goes to the next host (the data sources' client follows redirects by hand for this).
- **Tokens go only to their own host.** A link in Zenodo's answer (`links.latest_draft`, `links.bucket`, a file's `links.self`) that names another scheme or host is refused before the token is sent (it went to whatever host the answer named), and the client takes only `https://zenodo.org` or `https://sandbox.zenodo.org`. The e2er.org client reaches a platform over https only (http only for a server on this computer), refuses a request path that is an absolute URL on another host, and follows no redirects.
- **`e2er reproduce` asks before it runs someone else's code, and runs it in Docker.** A package's summary could name one harmless step while its `reproduce.json` ran `sh -c` and a script that read `~/.e2er/credentials.json` and wrote outside the run folder, all at once and as the user. Now the command lists every step's exact command and the requirements, says plainly that this is the author's code and how it runs, and asks (`--yes` in a script; without a terminal and without `--yes` nothing runs); steps that load inputs from the web ask on their own. With Docker running, the packages install and every step runs in a container (src/core/reproduce_sandbox.py: `--network none`, a read-only system, `--cap-drop=ALL`, no privilege escalation, the user's id, only the run folder mounted, no key or token; e2er-data from e2er's own code mounted read-only). Without Docker nothing runs unless `--no-sandbox` is given; then the steps get `HOME` and the `XDG_*` folders pointed at an empty folder, no settings of this computer, and no proxy that carries a password.
- **Refused before anything runs:** a symbolic link in the study folder (a copy read the file it pointed to), and a requirements file with an installer option (`--index-url`, `--extra-index-url`, `-f`, `--trusted-host`, `-e`, `-r`, `-c`) or a URL, path or VCS requirement. Only `--hash` options pass, so the package locks keep working. On this computer packages install from wheels only (`--only-binary=:all:`); in the container a package without a wheel is built there.
- **Zip bombs as a whole.** Many files of exactly 1 MiB of zeros passed the per-file ratio check; a package that unpacks to more than 200 times its packed size (above 64 MiB) is refused, the default cap is 4 GiB (was 64 GiB; `E2ER_PACKAGE_MAX_BYTES`), and a package larger than the free disk space is refused before anything is written.
- **`e2er inspect` shows the commands `e2er reproduce` would run**, read from the archive's own `reproduce.json`, not the manifest's summary, and no longer crashes on an author list of numbers. Terminal control sequences and bidirectional overrides are stripped from the output of `e2er inspect`, `unpack`, `reproduce` and `verify` (src/core/safe_text.py): a title with `ESC[2K\r` printed "Title: Forged" over the real one.
- The network guard of `e2er reproduce` is documented as what it is: a report of the connections Python makes, not a protection (a raw socket or a subprocess gets past it); the container's `--network none` is the protection. docs/publishing.md no longer tells reviewers to run `e2er reproduce` on an anonymous package without the sandbox.
- `docker info --format` exits 0 with an empty server version when the daemon is down (Docker 27); the replication sandbox and `e2er reproduce` now take that for "Docker is not running".
- **`e2er publish --github` writes nothing outside its clone.** A symbolic link committed to a shared repository (`code -> /some/folder`) made the push write the study's files into that folder on the publisher's computer. A study folder with a tracked link is now refused, and every destination must resolve inside the clone. The older PyGithub path (`GITHUB_ENABLED`: the draft and the replication package pushed during a run) uploads no link, no hidden file (`.env`, `.e2er/`) and no path with `..`.
- **The key check knows today's formats and guards every way out.** It missed GitHub's `gho_`/`ghs_`/`ghu_` tokens, OpenAI's `sk-`/`sk-proj-` keys, Google's `AIza…` keys, a bearer header, FRED's and Zenodo's keys in a URL (`api_key=`, `access_token=`) and a long random value given to a lowercase or JSON key name (`zenodo_token=…`, `"ZENODO_TOKEN": "…"`); the GitHub check skipped files over 5 MB and files that were not UTF-8, and `e2er pack`, the Zenodo deposit and the export's scratch logs had no check at all. One scan (`secret_scan.scan_files`, read in chunks, bad bytes replaced) now runs before `e2er pack` (refused, naming the file), the GitHub push and every Zenodo deposit (refused before Zenodo is asked anything), and the export takes such values out of its copies of `code/scratch/` logs and scripts, with a note. A bare 32-hex or 60-character string is not flagged: checksums look the same.
- **The credentials file is written owner-only and whole.** It is written through a 0600 temporary file in the same folder and `os.replace` (no moment with a half-written or wider-readable file; `e2er logout` rewrote it with the default mode), `~/.e2er` is made 0700, and a damaged file is read with a warning (it raised) and kept as `credentials.json.damaged` when a new token is saved. After a token is saved in the keychain, an older copy in the file is removed, and the other way round, for the e2er.org and Zenodo tokens.
- **AI CLIs and AI-written scripts get an allowlisted environment** (src/core/child_env.py). The CLI's shell had e2er's whole environment minus what looked like a credential by name: `SSH_AUTH_SOCK` (the ssh agent), a `DATABASE_URL` with its password, a token under a name that did not say so. It now gets the system's basics, the user's home (the CLI signs in from it), e2er's run variables and non-secret setting names, the wrappers' data and literature keys, the CLI's own sign-in and configuration, and the run database only as a SQLite path; `DB_PASSWORD` is no longer passed. The scripts the models write (the post-run of an analysis script, the meta-analysis script, `e2er-run`) get no key or token at all and an empty `HOME` (and `XDG_*`), and run in a session of their own: at the time limit their own child processes are stopped too.
- **The AI CLIs run with their own isolation flags.** Claude Code loads none of the user's, the project's or a folder's settings (`--setting-sources ""`: no permission rules, hooks or `CLAUDE.md` of a downloaded folder), no MCP server (`--strict-mcp-config` with an empty config), and refuses the web tools, notebooks, sub-agents and reading or writing `~/.ssh`, `~/.e2er`, `~/.aws`, `~/.gnupg`, `~/.config/gh`, `~/.codex`, `~/.docker`, `~/.netrc` and every `.env` (`--disallowedTools`). Codex runs with the network off (`CODEX_NETWORK_ACCESS=true` turns it on, with a warning; `e2er-data` and `e2er-lit` cannot download under Codex without it), Codex's own default excludes of key-like variables apply (no `ignore_default_excludes`), the model's shell gets an empty `HOME` (Codex signs in from `CODEX_HOME`), and `danger-full-access` needs `CODEX_ALLOW_FULL_ACCESS=true` as well. Gemini always runs with `--sandbox`; `--approval-mode yolo` only with `GEMINI_YOLO=true` (with a warning), else `auto_edit`. docs/BACKENDS.md says what each one can and cannot reach.
- **LaTeX from a model compiles without its tricks**: latexmk with `-norc` (a workspace `latexmkrc` is Perl that latexmk runs) and `-no-shell-escape`, pdflatex with `-no-shell-escape`, tectonic with `--untrusted`; kpathsea's `openin_any=p`/`openout_any=p` keep TeX's reads and writes below the workspace; the compiler gets no key and its time limit stops what it started.
- **A folder's `.env` no longer chooses the programs e2er starts or switches a sandbox off unasked** (src/env_trust.py). `CLAUDE_CODE_PATH`, `CODEX_PATH`, `GEMINI_PATH`, their working folders, `CODEX_SANDBOX`, `CODEX_ALLOW_FULL_ACCESS`, `CODEX_NETWORK_ACCESS` and `GEMINI_YOLO` from a `.env` that is not the studies folder's are used only after `e2er` asked at a terminal (the yes is remembered for exactly those lines in `~/.e2er/trusted-env.json`); otherwise they keep their defaults and e2er says so.
- **A production query's approval is sealed** (src/modules/data/approval_seal.py). The approval was a row in the run database, which the model's shell could write. The dashboard now seals each decision with an HMAC over the query id, the decision and the query's SQL (key in `~/.e2er/approval-key`, mode 600; seals in `~/.e2er/approvals/`), and `check_approval` counts an "approved" row only with a matching seal. Claude Code's specialists cannot read `~/.e2er`; under Codex a shell command can still read the key (Codex's sandbox does not stop reads), so there the seal only stops a model that writes the database without it. The wrappers' audit rows are written by the model's own processes and cannot be protected this way.

### Added
- **Double-blind review: `e2er publish --blind`** publishes an anonymous version of a study at `e2er.org/r/<code>` (160 random bits), which e2er.org shows without any author and lists nowhere. It needs no `--owner` or `--project`. Publish works on a copy next to the folder (`<folder>-anonymous-<code>`) and leaves the folder as it is. `src/core/anonymise.py` collects what identifies the author (the e2er.org account's name, e-mail address and handles and the profile's GitHub login, ORCID iD and affiliations from `GET /api/v1/me`, git author names and addresses, the computer's user and host name, `--blind-identifier`, `E2ER_BLIND_IDENTIFIERS`, `E2ER_AFFILIATION`) and anonymises the copy: the paper's author, affiliation and acknowledgement blocks become "Anonymous author(s)", home-directory paths become `~`, identifiers become `[anonymised]`. Each changed file is recorded as an amendment of kind `anonymised` (rules, replacements and their offsets; no removed text and no fingerprint before, which could confirm a guess; the old fingerprints are also taken out of the dossier). The stamp names no author and the anonymous address, and the PDF is built again. A final leak check searches every text file, every PDF (pdftotext and bytes), every other file's bytes (zip and gzip opened), the dossier and the request for every identifier in upper and lower case, URL-encoded, HTML- and JSON-escaped, with LaTeX accents, folded to ASCII, reversed, with initials, split over lines and, for addresses, with "at" and "dot", and refuses with file:line while anything is left. Self-citations (bibliography entries with the author's surname, such citation keys, phrases like "our previous work") are listed and need `--blind-ack-self-citations`. `--github`, `--zenodo`, repository and public addresses, author options, `--no-stamp` and `--offline` are refused with `--blind`.
- **`e2er pack --blind`** writes the anonymised copy into the `.e2er` file for the journal: no author and no folder name in its list, and the file checked for leaks again.
- **`e2er verify --against https://e2er.org/r/<code>`** compares a folder or `.e2er` file with an anonymous version (`GET /api/v1/blind/<code>`).
- **`e2er zenodo login [--sandbox]`** stores your own Zenodo token without editing a file or the environment. It opens Zenodo's page for a new personal token (`/account/settings/applications/tokens/new/`; Zenodo's form takes no values from the address, so it says which scopes to tick, `deposit:write` and `deposit:actions`, and suggests a name), reads the pasted token with a hidden prompt (or one line from a pipe), checks it with `GET /api/deposit/depositions?size=1`, which changes nothing, and stores it in the system keychain (service `zenodo.org` or `sandbox.zenodo.org`, username `token`), or in `~/.e2er/credentials.json` with mode 0600 when there is no keychain. A token Zenodo refuses (401, 403) is not stored. The scopes themselves are not tested: Zenodo does not report them, and every request that would test them creates or publishes a record. `e2er zenodo status` says whether a token is stored and whether Zenodo accepts it; `e2er zenodo logout` removes it. The token is never printed or logged. In a test run the keychain is not touched (src/core/test_guard.py).
- **`e2er publish <folder> --unblind <code> --owner <handle> --project <name>`** publishes, after the review, a new version with the author's name (`POST /api/v1/blind/<code>/unblind`): the anonymised copy's files with the author shown, or a named export as the new content. The anonymous version stays as it was published.

### Changed
- **`keyring` is a dependency of e2er.** The tokens of `e2er login` (e2er.org) and `e2er zenodo login` go to the system keychain (macOS Keychain, Windows Credential Manager, the Secret Service on Linux desktops) after a plain `pip install e2er` or `uv tool install e2er`; before, they went to the keychain only where `keyring` happened to be installed and to `~/.e2er/credentials.json` everywhere else. Where there is no keychain behind it (a headless Linux server or a CI runner, where keyring selects its `fail` backend; a backend that cannot be loaded) or the keychain refuses, e2er uses `~/.e2er/credentials.json` with mode 0600 as before, without an error. A token already in the credentials file is still read. In a test run the keychain is never touched (src/core/test_guard.py); `scripts/check_wheel.sh` checks that the installed wheel has `keyring`.
- `e2er verify` accepts a pre-registered plan file whose only change since the freeze is an anonymisation (checked like a redaction: the replacements at their recorded offsets).
- `e2er publish --help`: `--owner` and `--project` are required except with `--blind`.
- `e2er publish --zenodo` and `e2er preregister deposit --zenodo` without a token say to run `e2er zenodo login` (in CI: set `ZENODO_TOKEN`). `e2er preregister deposit` now also reads the token stored by `e2er zenodo login`, in Setup or in the keychain; it read only `ZENODO_TOKEN`. The order is the environment, Setup's settings, the keychain, then `~/.e2er/credentials.json`.

### Fixed

- **A rerun from a step after the revision ends again** (review of 2026-10-23). `e2er rerun --from abstract` (or `replication`, or the specialist `abstract_writer`) set the state to "in progress", and the revision, which decides how the study ends, did not run again, so the study stayed "in progress" for good with nothing running. The revision's outcome is now kept in the state file (`revision_status`), and a run whose revision is done ends with it (a state written before this ends as completed).
- **Send-backs and reruns are not lost when something stops them** (review of 2026-10-23). The queue of send-backs (`rerun`, `sent_back` in `.pipeline_state.json`) was taken out of the state before its work ran; a check that halted, a contract stop, a full disk or any other error on the way saved the state without them, and the researcher's remarks were gone. What has not run (the send-back that was running included) goes back into the state; one that ran is not queued again. A send-back's specialist also runs with the time limit of its step (`timeout_minutes`); it ran before the run entered any step, so the backend's own limit applied.
- **Two resumes sent together start one run** (the dashboard and `e2er resume`, review of 2026-10-23). Resume checked "is a task running?" and started the task with database reads in between, so two requests sent together both passed and two runners worked in the same folder. Resume, a researcher's review action and a rerun now hold a lock of the paper from before their first wait until the run is registered (409 for the second), and a run's end removes only its own task from the list of running tasks, not a newer run of the paper.
- **"Completed" only with the final export written, "finishing" only at the end** (review of 2026-10-23). A study whose final export failed (a full disk, a permission error) was set to completed with no export folder; it now pauses with the reason ("Every step finished, but the final export failed: …"), and Resume runs no step again and writes the export. A revision that accepted the paper set "finishing (writing the export)" before the abstract and replication steps, which can take long; the study is "in progress" until its last step has run.
- **A circuit-breaker pause finalizes once.** The pause ran the compile, the audit export, the GitHub push and the export, and the `finally` of the run ran them all again.
- **The systematic review and the field map get the abstract step.** Their writers (`meta_review_writer`, `field_review_writer`) wrote the abstract into the paper themselves and nothing checked it. Both templates now end with the `abstract` step (after `revision` in systematic-review, after `review_draft` in field-map), and their writers are told to leave the abstract out, as the drafter is. `tests/test_abstract_step.py` holds every template in `pipelines/` with `compile` in its `finalize` to the step.

- **`scripts/release.py` writes a release whole or not at all.** The check that every place names the new version ran after the files were written, so a wrong pattern left a half-edited release. It now checks the new content first, writes each file to a temporary file beside it and renames them all, and puts back the files already renamed when a rename fails.
- **The release notes are the version's own section.** `release.yml`'s awk matched the version as an unanchored regex: 0.1.1 took 0.1.10's section, and a dot matched any character. It now takes the section whose heading starts with `## [X.Y.Z]`, matched literally.
- **CI runs the replay tests' `e2er reproduce` steps.** Neither workflow installed uv, so the reproduce steps of the policy-evaluation, spatial-analysis, text-analysis and systematic-review replays were skipped on every push, and a failed install was turned into a skip too. `tests.yml` and `release.yml` now install uv (astral-sh/setup-uv pinned to the v10.2.0 commit, uv 0.12.19, no cache) and set `E2ER_REQUIRE_UV=1`. There the step runs online, and a missing uv or a failed install fails the test (`tests/replay/uv.py`). Locally it still runs offline from uv's cache and is skipped without uv.
- **The PyGithub push (`GITHUB_ENABLED`) reports GitHub's errors.** `push_file` treated any failure (a 403, a rate limit, a 409 on update) as "the file does not exist yet" and tried to create it, which failed with another error or hid the first. Only a 404 now creates the file; everything else is raised, and a directory at the path is refused.
- **Tests that could not fail now can**: the estimation gate's skip for theoretical studies, the release-fact counts (checked against git, the source definitions and the README table), `push_file`, and "completed only after the final export" (it accepted "finishing" too). The suite's no-op database records what was written (`db_stub`), the settings cache is cleared before and after every test, the timing-sensitive tests poll with deadlines or freeze the clock (the cancelled CLI's child, the heartbeat, the preflight expiry, the plan-limit reset across midnight), the port tests keep their port and the replay server retries on a new one, the leaked `_never_finishes` coroutine is gone, and `tests/test_durations.json` is refreshed.

- **A re-export no longer undoes a redaction or a new abstract.** The run's export at a stop, at its end and from "Prepare the folder" replaced the newest folder whenever the run had changed, so an `e2er redact` or `e2er abstract` made there was silently lost. A folder whose provenance.json records amendments is now kept like a published one, and the next export makes a new numbered folder.
- **An export never loses the folder it replaces, and two exports of one run no longer build over each other.** The old folder was deleted before the new one existed, so a full disk left nothing, and the finish page and the run's own export could run at once with no lock. The new folder is now built in a hidden temporary folder beside the exports and renamed into place only when complete; one export per run runs at a time (`.e2er-export-<run>.lock`), and a failed export leaves no half-built or empty folder.
- **"The newest export" is the one with the highest `-YYYYMMDD-NN`**, not the newest modification time. Redacting or copying an older folder made it the newest, so the next export replaced the wrong one and the finish page offered the wrong copies for removal.
- **Runs from before 0.14 keep their id in the export.** Their manifest.json has no `paper_id`, so `run.paper_id` was empty, publish could not find the run database, and every stop made a new folder. Export now takes the id `e2er export` resolved, or the workspace's name when that is the id.
- **Data built from a source with terms is found however a script writes it.** The scan missed geopandas `to_file`, `shutil.copy`/`copy2`/`copyfile`/`move`, polars `write_parquet`/`write_json`, pyarrow `write_table`/`write_feather`, xarray `to_netcdf`, `joblib.dump`, DuckDB `COPY … TO` and f-string paths: a script that read `data/gmd.csv` and wrote `results/regions.gpkg` and a copy of the rows would have been packed and published. All of these are followed now. A script that reads restricted data and writes a path the scan cannot work out (a computed path, an f-string with a loop variable, `copytree`) counts as writing every output file newer than itself. The script log records every data-type file a run writes (it recorded only .json, .csv and .tsv), and a file over 64 MB by its path (`outputs_unhashed`).
- **provenance.json validates against its schema after a change.** `docs/schemas/provenance.schema.json` lacked `amendments` (written by redact, abstract, the anonymised copy and publish's stamp), `run.purpose`, `run.preregistration`, `run.template`, `run.derived_data` and the data edge's `sources`; these are documented now, with the new `run.left_out`. A test validates a folder after an abstract rewrite, a redaction and the stamp.
- **`e2er redact` changes a folder all or nothing.** It wrote each file in place and then provenance.json, so a full disk left a half-redacted, unrecorded folder. Every file now goes through a temporary file and a rename, provenance.json last, and on any error every file is put back. Several `--text` are all or nothing too (a refused second text left the first one redacted), and `--check` with several `--text` checks each redaction with the text it took out (with two texts it always failed).
- **`get_data.py` reloads a table a load stopped early, and the last load into a table.** A table counted as present with any rows, so a rerun after "loaded 400 of 1200 rows" kept the partial table and exited 0; with two loads into one table, the first was reloaded and the second skipped. A table now counts only with the rows the run's load recorded, and only the last load per table (and per file) is reloaded.
- **The export copies the study's data folder.** Files under the workspace's `data/` (e2er-data `--save-to` files, the researcher's own files) were copied only when a script of a working recipe named them, so a systematic review, a field map or a run whose recipe failed shipped `data_sources.json` naming files the folder lacked. Every file a source's terms let the study pass on is now copied, with the recipe's rules: at most 200 MB, no hidden or leftover file, no link out of the study unless recorded as the researcher's file.
- **No file under a hidden folder is exported** (`sandbox/run/.cache/x.json`): pack drops such paths, so the package lacked a file provenance.json listed. **A reproduction output over 200 MB is recorded as left out** (`run.left_out`, kind `size`) and named in the README and in verify's reproduction check; it was dropped with a log line only.
- **An identifier in provenance.json or e2er.json now has a way out.** The blind leak check said to use `e2er redact`, which refuses these records; both now say to take the identifier out at its source (the run's workspace) and export the study again.
- Small fixes: `saved_to` and data-file paths strip the prefix `./`, not the characters (`.hidden.csv` became `hidden.csv`); the workspace path rewritten in exported scripts no longer matches a longer folder name (`/x/ws_other` became `._other`).

- **Sandbox deposits name the DOI the sandbox publishes** (`e2er publish --zenodo-sandbox`). sandbox.zenodo.org reserves a draft's DOI with production's prefix (`prereserve_doi` says `10.5281/zenodo.N`) and publishes the record as `10.5072/zenodo.N` (seen on 2026-10-23 with deposits 625117 and 625119). Publish wrote the reserved `10.5281/…` DOI into `e2er.json`, the dossier and `.e2er/zenodo.json`, a DOI that on zenodo.org belongs to some other record, and warned "Zenodo published the data as doi 10.5072/…, not the reserved 10.5281/…". It now records `10.5072/zenodo.N` from the start, corrects a `.e2er/zenodo.json` written with the wrong prefix on the next publish, and links the sandbox's record instead of `https://doi.org/10.5072/…`, which resolves nowhere. zenodo.org deposits are unchanged.
- **A folder published on a platform and then deposited on Zenodo without `--to` publishes again.** The publish rewrote `e2er.json`, while `.e2er/link.json` still named the platform's version, so every later publish, `--to` included, refused the folder ("the folder is not what was exported … .e2er/link.json names another content than provenance.json") and `e2er verify` failed its anchor. A send the platform refused after `e2er.json` was written left the folder the same way. The link now keeps naming the platform's version and records the description `e2er.json` holds (`described_here`: content id, dossier id, time); verify accepts the link when that record matches the folder and says "e2er.json describes it again since version N on <platform>"; a publish with `--to` writes the link anew. A link that matches neither is still refused.
- **An unchanged deposit says so when publishing**, not only in a dry run: "zenodo code: unchanged since doi …; nothing new is deposited".
- **An abstract amendment changes the abstract and nothing else** (`e2er verify`, review of 2026-10-23). Verify's anchor rolled back every amendment of kind `abstract_rewritten` or `abstract_edited_by_researcher` at the end of `provenance.json`, whatever the file and whatever the change: a results file or a paragraph of the paper edited after publishing and recorded as an abstract amendment still verified "as published, before the abstract was rewritten". Now such an amendment counts only for the four files `e2er abstract` changes (`paper/abstract.tex`, `paper/paper.tex`, `paper/paper.pdf`, `report.html`); on any other file the integrity check fails. The amendment of `paper/paper.tex` records `abstract_before` (where the paper changed, the text that stood there and the SHA-256 of the old abstract); verify rebuilds the old paper from it, which must have the recorded fingerprint and be byte for byte the same outside the abstract, else the integrity check (when it is the paper's last change) and the anchor fail. An 0.18.0 amendment without the record cannot be checked: the anchor no longer rolls it back and says why.
- **A redaction or anonymisation record is checked, not taken on its word** (`e2er verify`, review of 2026-10-23). Verify checked only that the replacement sat at each recorded offset, so a whole script replaced by `<redacted>` and recorded by hand as a redaction passed, and a pre-registered plan changed that way passed as "redacted by the researcher after registration: contact details only". Now the sizes must add up (`bytes_before` = the size now plus, per place, the removed length less the replacement's), no place may lose more than 256 bytes, the file may not be taken out as a whole, and `e2er redact` records `kept`, the HMAC-SHA256 of the bytes it kept (the new file without the replacements) keyed with a random salt, which verify recomputes. An earlier redaction in a chain is checked by its sizes (and loses its `kept` record when the file is redacted again, since those bytes hold the later text). A copy for double-blind review, whose records keep no offsets or sizes, is still checked only by counting the replacements. The pre-registration passes a redacted plan file only when every record of the chain holds. `e2er redact` refuses a text longer than 256 bytes and an empty replacement. An anonymisation record with an empty replacement text (which matched any file) fails, and `e2er publish --blind` now replaces an affiliation, e-mail or `\thanks` command with the command and `[anonymised]` instead of deleting it unrecorded. Verify's wording no longer claims what it cannot see: "recorded as redacted by the researcher (personal contact details, the record says)".
- **A left-out results file no longer hides a failed numbers or tables check** (`e2er verify`, review of 2026-10-23). When a published copy left out any results JSON (a source's terms, too large for the host), every numbers failure became a skip, p-value/t inconsistencies included, and so did every differing table: a fabricated cell passed as "needs …, left out under … terms". Now a numbers failure is skipped only for the cells whose recorded source (provenance.json's `table_cell` edges) is a left-out file, or when every file the numbers are traced to is left out; a tables failure only for the tables that read a left-out file. Any other differing cell or table fails, and the statistics check always counts.
- **A package's declarations of left-out files are checked like a folder's** (`e2er verify`, review of 2026-10-23). For a `.e2er` file verify counted every file its `e2er-package.json` declared left out as left out, so a package could leave out a results file under terms no record of the study names and still pass the integrity check, with the checks that needed the file skipped. Now a declaration counts only where the study's own records support it (a source's terms, a file provenance.json records larger than the host takes), as in a folder; any other declared file is missing, and the integrity check fails with "declared left out by e2er-package.json … without support in the study's records". A package made with `e2er pack --no-data` therefore no longer verifies.
- **`e2er reproduce` checks the folder before it runs it** (review of 2026-10-23). It ran whatever `reproduce.json` the folder held and reported "Reproduced" for a folder whose recipe or results were edited after export. Now it first runs verify's integrity check: a folder whose files are not the ones `provenance.json` lists (an edited or unlisted `reproduce.json`, an edited results file) is refused with exit code 2 and the reason. Files a source's terms keep out, supported package declarations and inputs the recipe loads or builds again may be absent. A folder without `provenance.json` still runs, and the verdict begins "This folder has no provenance.json, so nothing ties its files (reproduce.json included) to a published study".
- **`e2er reproduce` renders the tables from the rerun's outputs only** (review of 2026-10-23). It copied every published results file into the render folder and overwrote only those the rerun wrote, so a table of a results file the recipe does not compare (the summary statistics, say) "rendered the same" from the published file. Now only the rerun's outputs (and the table spec) go in; a table that reads a published results file the rerun did not write again is reported as not compared ("N table(s) not compared, since they read results the rerun did not write again").
- **A whole number must be reproduced exactly** (`e2er reproduce`, review of 2026-10-23). A published float with a whole value and four or more digits (`1234.0`) counted as rounded, so a rerun's `1234.4` was "the same at the published precision". A whole number is never taken as rounded now.
- **"Reproduced" needs values that were compared** (`e2er reproduce`, review of 2026-10-23). A compared results file with no value in it (`{}`, or empty lists and objects only) on both sides counted as reproduced, and so did a run that compared nothing at all. Such a file is now "not compared, the published file holds no value to compare", and with no value compared the verdict is "Not reproduced: no value was compared" (exit code 1).
- **"Results from code" no longer skips on the record's word** (`e2er verify`, review of 2026-10-23). A `run.results_from_code` entry saying "the run predates output records", a record without an entry for one of the results files, or no record at all, was a skip whatever e2er ran or exported the study. Now every results file the record covers (`estimation_results.json`, `robustness_results.json`) must have an entry, and "predates output records" (or no record) is a skip only when the e2er that ran the study is 0.16.0 or earlier (script logs record the files a run writes since 0.16.1). Export records that version from the run's `run_identity` events (`run.e2er_version_run`, the newest version any part of the run used, with `run.e2er_versions_run` and `run.e2er_commit_run`), and the script log records it per script run. Verify reads it from there, else from the published dossier's `e2er.segments`, else from the exporting version when that is 0.16.0 or earlier; when nothing in the folder says which e2er ran the study, the check fails and says so. The five published demos exported with 0.17.0 from runs of 0.16.0 still verify, with the run's version from their dossiers.
- **The citations check reads the whole paper and every bibliography it names** (`e2er verify`, review of 2026-10-23). It read `paper/paper.tex` alone and looked keys up in `paper/refs.bib` alone, so an unresolved `\cite` in a file the paper includes passed, and a key in a second database of `\bibliography{refs,more}` failed. Now the files the paper `\input`s, `\include`s or `\subfile`s are read with it (inside `paper/` only, five levels at most), and the keys are looked up in every `.bib` file `\bibliography{…}` names (`refs.bib` when it names none).
- **The abstract's numbers are checked against results, with their signs** (the abstract check, review of 2026-10-23). A number of the abstract counted as a result when it matched any value of the results files: a standard error, a p-value, a t statistic or an interval bound, any value up to 1 times 100 as a percentage, and a design setting whatever its sign. Now statistic keys (`se`, `std_error`, `p_value`, `t`, `t_stat`, `ci_*`, …) are left out of the matching, the times-100 reading of a percentage applies only to shares and estimates (keys such as `share`, `proportion`, `estimate`, `coef`, `effect`, `rate`), and a design setting matches only with its sign.
- docs/STRUCTURED_EXPORT_SPEC.md says why an input table whose decimal numbers agree to 12 significant digits counts as the study's input (`e2er reproduce`) and that the rule never applies to result values (review of 2026-10-23; no change in behaviour).

## [0.18.0] — 2026-10-23

### Added
- **One release command: `scripts/release.py X.Y.Z`** (`make release VERSION=X.Y.Z`). It makes every version edit of a release: `pyproject.toml`, `src/__init__.py`, `CITATION.cff` (`version`, `date-released`, the preferred citation's version and year), the README's BibTeX entry (version and year) and the CHANGELOG (`## [Unreleased]` becomes `## [X.Y.Z] — date` under a new empty Unreleased, and the link references follow); `--commit` commits them, `--dry-run` writes nothing. It refuses a tree with uncommitted changes, a version that is not X.Y.Z or not greater than the current one, an empty Unreleased section and a place it cannot find, and then writes nothing; a document naming a coming version that is not the one released is printed as a warning. `--check --tag vX.Y.Z` is now the release workflow's version check (it compared only `pyproject.toml` and `src/__init__.py`). docs/RELEASING.md describes the release.
- **`release-facts.json` on every GitHub release** (`scripts/release_facts.py`): `{version, date, tag_url, concept_doi, doi, counts: {templates, specialists, skills, data_sources, tests}}`, every count computed from the code (the `pipelines/*.toml` files, the specialist registry, the `skills/files/**/*.md` files, the connectors, the tests the release runs). e2er.org reads it. The Zenodo version DOI is minted by Zenodo after the release exists, so a job of the release workflow asks Zenodo's public records API for up to 30 minutes for the version named like the tag and uploads the file again with `doi` filled in; without one `doi` stays null and readers use the concept DOI. The format is fixed in docs/RELEASING.md.
- **No coefficient in an abstract** (the abstract check). A number next to an estimate word (estimate, coefficient, shift, effect, beta, slope) is a raw estimate unless a plain unit follows it (percentage points, percent, times, deaths per 100,000, Earth radii, degrees, ...), and a signed decimal below 1 with no unit is one wherever it stands. "The estimated shift is -0.0181 in correlation units" fails; "under two correlation points" and "about 22 percentage points" pass. The showcase's version 3 abstract quoted -0.0181.
- **`e2er abstract <folder> --from-file <file> --reason <text>`**: the researcher's own abstract in place of the writer's. No AI call; the same check and number check; recorded per changed file as `kind: "abstract_edited_by_researcher"` with the reason and `edited_by: "researcher"`, shown in the dossier at the next publish; verify's anchor rolls it back like the other abstract amendments.

### Changed
- **The abstract is written last, from the final paper, and checked** (`src/core/abstract.py`). Up to 0.17.3 the abstract writer ran beside the paper drafter (the strategist's parallel group 4), on a draft that did not exist yet, without the abstract skill reaching the PDF: the compiler built the PDF from `paper_draft.tex` alone, whose abstract the drafter wrote without `writing/abstract`, while `abstract.tex` fed only the title and `report.html`. No check read either. Now every template whose strategist plans a paper has an `abstract` step after `revision`: the abstract writer reads the final `paper_draft.tex`, the result values the paper's own text cites (its `% src:` notes) and what the reviewers said about the abstract, and writes `abstract.tex`; the compiler puts it into the paper (in place of the draft's abstract environment, or after the title where the draft has none), so the PDF, `report.html` and the title show one abstract. The strategist no longer plans the abstract writer (an order for it is left out), the paper drafter and the revisor are told to leave the abstract out, and the draft-review step (`review_draft`) no longer lists `abstract.tex`. A change of approach in the iterative mode that asks for the abstract writer leaves it out and says so on the run page. The field-map and systematic-review templates keep their review writers' abstracts.
- **`writing/abstract` rewritten**: the NFT seasonality abstract of e2er v1 as the worked example, annotated sentence by sentence (its one "rather than" rephrased: "Two-thirds of the raw seasonal differential in USD returns comes from ETH price seasonality"), and the road-traffic demo as a descriptive-study example; a null result leads with what the null means, a caveat gets at most one clause, "makes no causal claim" only where the question could be read causally, plain language. `writing/cite-numbers-by-source` now says that the abstract carries one to three headline magnitudes in plain units, each with its `% src:` line, and that only the abstract writer writes it.

### Added
- **The abstract check** (governance gate `abstract`): at most 160 words; no p-values, confidence intervals ("95%", "interval"), standard errors, Fisher-z or test statistics; at most three numbers (years, the base of a rate such as "per 100,000", a sample threshold such as "magnitude 5 and larger" or "within 3 degrees" and the digits of a name such as NUTS-2 or the S&P 500 are not counted), each a value of the study's results at the precision shown; at least one sentence that states a finding; a last sentence that is no negation and has no "rather than"; no "rather than", no "X, not Y", no mirrored "changed A; changed nothing about B", and the phrase check of every draft. A failure sends the abstract writer back once with the reasons; a second failure is recorded as a finding (`abstract_check.json`, exported to `reviews/`, a failed `abstract` check in the dossier and an `abstract_finding` event) and the run goes on. A regime that does not enforce it (`off`, `contracts`) records the verdict without a resend.
- **Reviewers' points on the abstract always reach the abstract step.** The revision step reads every reviewer's file (and the self-attack report) for passages that name the abstract, whatever the reviewer scored, and writes them to `abstract_findings.json` (exported to `reviews/`) as findings on `abstract`; the abstract writer gets them. Up to 0.17.3 a reviewer scoring 6.0 or more produced no finding at all (`_REVIEW_SCORE_FINDING_FLOOR`), so its remarks on the abstract were dropped. The targeted corrections of the revision leave findings on the abstract to the abstract step.
- **`e2er abstract <folder> [--backend B] [--model M]`** writes a finished study's abstract again with the abstract step: the abstract writer once on the final paper with the configured backend (its records go to a scratch database, never the run's), the check with at most one resend, including the number check (every number of the new abstract a value of the results). On a pass it puts the abstract into `paper/paper.tex`, writes `paper/abstract.tex` (keeping its `\title`), recompiles `paper/paper.pdf` with tectonic, shows it in `report.html` and records an amendment per changed file (`kind: "abstract_rewritten"`, `model`, `backend`, `e2er_version`, `reason`, `sha256_before`/`sha256_after`, `bytes_before`), which the next `e2er publish` puts in the dossier. It then runs the checks of `e2er verify` and puts every file back when they fail; nothing changes when the check fails. A published folder whose abstract was rewritten still verifies against its `e2er.json` (the amendments rolled back, `provenance.json` is the published one) until it is published again.

### Fixed
- **A new version of a study gets new Zenodo versions for changed files** (`e2er publish --zenodo`). Up to 0.17.3 a folder published again kept the DOIs of its first deposits, also when the deposited data or code had changed since: the dossier named a DOI whose files were not the study's. Now publish compares the files with those deposited (MD5 checksums recorded in `.e2er/zenodo.json`, or Zenodo's own for older deposits): unchanged ones keep their DOI, changed ones become a new version of the same Zenodo record (`actions/newversion`, a new DOI under the same concept DOI, the earlier version's files removed from the draft), and the earlier DOIs stay in the record (`earlier`). A retry after a failed publish removes the draft's earlier files before uploading again. File names are quoted in the upload address, every deposit states its publication date, and more than the 100 files a Zenodo record takes (or two data files whose flattened names collide) go as one zip `<project>-data.zip`.
- **The release's tests run in four parallel jobs** (`E2ER_TEST_PART=k/4`, `tests/parts.py`: whole test files, balanced by `tests/test_durations.json`), each with a 30-minute limit, instead of one job of up to 30 minutes under a 50-minute limit.

## [0.17.3] — 2026-10-21

### Fixed
- **The release workflow's tests have 50 minutes.** The suite takes up to 30 minutes on a hosted runner, so the 25-minute limit cancelled the release of 0.17.2 before anything was built; 0.17.2 was tagged but never published to PyPI. 0.17.3 is 0.17.2 with this change.

## [0.17.2] — 2026-10-21 (tagged, not published)

### Added
- **`e2er publish` asks before anything is sent or pushed.** After the rehearsal it prints what goes where (the platform and handle, the GitHub repository and folder, Zenodo) and asks "Publish '<title>' to <platform> as <handle>? Files to GitHub <repo>/<path>. [y/N]"; only `y` or `yes` goes on, anything else sends nothing, pushes nothing and leaves the folder as it was. A run without a terminal on standard input needs `--yes` (`-y`) and otherwise refuses at once with nothing sent; `--dry-run` never asks and never sends. The dashboard's Publish button asks the same question in the browser and sends `confirm: true`; `POST /api/papers/<id>/publish` without it (and not a dry run) is refused with 422.
- **No publishing from a test run** (`src/core/test_guard.py`). With `PYTEST_CURRENT_TEST` set (also in a command a test starts), `E2ER_TEST=1`, or `CI=true` together with a test command (pytest, unittest, nose2, tox, nox), e2er never reads or writes the keychain or `~/.e2er/credentials.json` and reads no saved Zenodo token (only `E2ER_TOKEN`, `ZENODO_TOKEN` and a credentials file the test names in `E2ER_CREDENTIALS`), refuses every request to a platform or Zenodo other than a loopback address or the address in `E2ER_TEST_SERVER` (never e2er.org), and runs no `gh` and no push to GitHub (`E2ER_TEST_GITHUB=fake` for e2er's own tests with a fake gh). Documented under "Running e2er inside your own test suite" in docs/publishing.md. On 2026-10-20 a run of `tests/test_publish_github.py` published test studies to e2er.org with the machine's keychain token.
- **Tokens for one study, for CI.** `e2er login --scope study:<owner>/<slug>` (browser approval) or `e2er token create --study <owner>/<slug>` (with the personal login) prints a token that can only publish new versions of that study: it cannot create studies or handles, publish another study, withdraw, or make tokens. The token goes alone to standard output (`… | gh secret set E2ER_TOKEN`) and is not kept; the personal login stays in the keychain. A platform that answers without limiting the token to the study gets the token ended and nothing is kept. `e2er whoami` names the study of such a token, and `e2er logout` with `E2ER_TOKEN` set ends that token and no longer forgets the login saved on the computer. API: `POST /api/v1/tokens` with `{"name", "study"}` → `{id, token, scopes, study, expires_at}`; `GET /api/v1/me` returns `study` (e2er-site branch `study-tokens`).
- **A new version of a published study whose run database is gone carries over the earlier dossier** (`e2er publish`). When the database is not found and the folder was published before (`.e2er/link.json`), publish fetches the dossier of the version it published from the platform and checks it: `.e2er/link.json` and `e2er.json` name it, the platform's latest version is that dossier and that content, the document hashes to its id, the data fingerprints are the folder's. The new dossier is that document with its steps unchanged, the new availability (the files on GitHub) and an amendment on `e2er.json` (`kind: "carried_over"`, `from_version`, `from_dossier`, `e2er_version`): "published again with files on GitHub; run database not available, dossier carried over from version N". e2er.json keeps the earlier version's description of the run (recorded agents and skills). Nothing is invented; anything that does not match is refused and the folder stays as it was. `--no-db` still publishes a dossier without steps when asked for. Five demos lost their run databases to macOS's /tmp cleanup on 2026-10-19; without this their new versions would have had no steps.

- **`e2er redact <folder> --text <text> [--replace "<redacted>"]` takes personal data out of a study folder before publishing.** Every occurrence in the folder's text files is replaced and nothing else changes; before writing, the edit is proven (the new file with the text put back is byte for byte the old one). Each changed file gets an amendment in provenance.json: `{path, kind: "redacted", sha256_before, sha256_after, reason: "personal contact details removed by the researcher", redaction: {replacement, count, offsets, removed_bytes}}`; the record never holds the text or a hash of it. The amendments go into the dossier at the next publish. `e2er verify` checks that the replacement sits at every recorded offset, and accepts a pre-registered plan file whose only change since the freeze is a redaction: "preregistration.md redacted by the researcher after registration: contact details only" (any other change still fails). `e2er redact --check --text <text>` rebuilds each redacted file's earlier version with the text and compares its fingerprint, so whoever knows the text can confirm that nothing else changed. Text in a PDF (via `pdftotext`), a database or another binary file, or in a file provenance.json does not list, stops the redaction with nothing changed; `--dry-run` says what would change. A published folder redacted afterwards still verifies: with the redactions at the end of its amendments rolled back (the record keeps each file's earlier size), provenance.json must be exactly the published content, and the anchor says the redaction is not yet published; `e2er publish` then publishes the redacted folder as a new version. (The school-fee demo's plan files named the researcher's e-mail address, 2026-10-20.)

### Changed
- **Export records a study's whole data preparation, so a folder without `data.db` can be run again** (`reproduce.json`). The weather-words demo's export could not rebuild its 145 MB `data.db` (2026-10-21): (1) `get_data.py` was written only for sources with terms, so nothing loaded the Project Gutenberg texts again; now it lists the loads of every table a step reads and of every input file, open sources too, and loads one only when the folder lacks it (a note says that this needs the internet and takes about as long as the run's loads). (2) The tables the estimation reads (`corpus`, …) were written by `build_data.py` with `t.to_sql(name, con)`, a name the code computes, which table detection missed; now the script log records the tables of `data.db` each run created, changed or dropped (`tables: {"written", "dropped"}`, from the database before and after the run; the digests are kept in `.e2er-db-tables.json`, so an unchanged database is not read again), and for older runs the code is read for `to_sql(name)` with the table's name in a string, `to_sql(f"t_{c}")`, and tables read through an f-string. (3) The scripts that built those tables, and the tables they read in turn, are steps of the recipe in run order for every study, not only for one with restricted data (`"when_missing": ["data.db"]`). (4) A small data file such a step reads (`data/sample_ids_v2.csv`) ships with the folder, and the input names the script of the run that made it and its own inputs (`made_by`: `script`, `file`, `seeded`, `from`; here `draw_refill.py`, from `data/sample_ids.csv` of the seeded `draw_sample.py`). `reproduce.json` gains `database`: every table of `data.db` with where it came from (`how`, `source`/`by`, `evidence`), whether a step reads it, and how a rerun gets it back (`back`). A table no step reads (the demo's Gutenberg catalogue) is not loaded again, is listed in the data.db input's `not_read`, and is not compared in a rebuilt database; `e2er publish --github` and `e2er pack` count a database as rebuilt when every table a step reads comes back, and README.md says which tables a rerun does not need. A table of a rebuilt database that has more columns than the study's (the Gutenberg connector records translators since the demo ran) is compared on the study's own columns (`content_fingerprint` now records each table's `columns`), so the report names only tables whose data changed (the demo's rehearsal: ebook 161, revised by Project Gutenberg since 2026-10-14, and the corpus built from it).
- **`e2er publish --github` pushes the files only as part of a publish on a platform.** Without `--to` it published nothing: the files went to GitHub and e2er.org registered nothing (e2er-demos commit 0d9a2e3). Now `--github` without `--to` publishes on the platform `.e2er/link.json` records, else e2er.org, and says so. Before anything is pushed, publish rehearses the request in a scratch copy and checks the sign-in on the platform (`GET /api/v1/me`): not signed in, or a refused sign-in, pushes nothing. The registration names the pushed commit, so it is sent after the push; if the platform refuses it then, publish says where the files are and that the same command, run again, makes no new commit and sends the registration again. A run that would push without a platform is refused.
- **Studies never default to a temporary folder.** e2er started in a temporary folder (`/tmp`, `$TMPDIR`, `/var/folders`, …) with nothing set up uses the default studies folder (`~/e2er-studies`) instead of the current folder. A temporary folder the researcher chose (a `.env` there, `WORKSPACE_ROOT`, a SQLite `DATABASE_URL`, `OUTPUT_DIR`, the studies folder in Setup, `e2er init` there) is used, with a warning that the operating system may delete it, at `e2er` start, `e2er run`, `e2er init` and in Setup. `E2ER_TEMPORARY_FOLDER_OK=1` keeps the current folder (the test suite sets it).

### Fixed
- **Results built from restricted data stay out of a published copy unless they are aggregates** (`e2er pack`, `e2er publish --github`). Only files under `data/` counted as built from a source whose terms keep its data out, so demo 2's `results/figure_spec.json` (1.6 MB: 9,970 Gaia proper-motion pairs and 9,863 colour/magnitude pairs) and demo 6's eight `results/*.csv` (GISCO units and weights of 236 and 244 regions) would have gone up. Now any output a script wrote after reading restricted data (results/, misc/, paper/; CSV, JSON, text, NumPy, …), and the figure spec of any study that loaded restricted data, is left out unless it is an aggregate: at most a tenth of the source's rows (at most 50), no JSON array of more points than 1% of the source's rows (10 to 50) or more records than that row limit, and no identifier of the source (a value of a column whose values are all distinct, such as Gaia's `source_id`; codes the study also loaded from an open source, such as NUTS codes, do not count). Formats e2er cannot count rows in are left out. The reason says what holds the rows ("an array of 9,863 values at figures[2].y", "244 rows"). Rendered figures and LaTeX tables stay. Export records for each derived file whether it held the source's rows (`provenance.json` `run.derived_data[].holds_rows`), so a copy without it can tell left-out rows from a missing aggregate (`src/core/derived_rows.py`, `docs/STRUCTURED_EXPORT_SPEC.md`).
- **A clone without its left-out results verifies and reproduces.** `e2er verify` counts a declared left-out results file as left out, not missing, when the folder's own records say it holds restricted rows (the derivation edges are compared as if it were there), and a check that needs it is skipped: "needs results/spatial_units.csv, left out under GISCO terms; run `e2er reproduce` to rebuild it" (or "no recorded step rebuilds it"). `e2er reproduce` rebuilds each one: a file a step of the recipe writes needs nothing; one a step reads is built first, after the data are loaded again, by a script that writes it (demo 6's `code/scratch/build_data.py`, which writes `spatial_units_all244.csv`, the units and the weights and which no recorded step ran before); any other by its writer after the step that writes what it reads. The steps are in `e2er-package.json` (`rebuild`, `"output": true`) and, for new exports, in `reproduce.json`; one step runs a script once for all its files. The report lists these files apart ("Files a published folder leaves out …, as the rerun wrote them": identical, the same rows, differs) without changing the verdict. Checked on copies of demo 2 and demo 6 pushed to a local bare repository: a fresh clone verifies (demo 2: 3 content checks passed, results contract skipped for `figure_spec.json`; demo 6: 5 passed, method checks skipped for the units and weights) and reproduces (demo 2: 930 values identical or the same at the published precision; demo 6: 400 of 400 identical, 3 of 3 tables, seven left-out CSVs rebuilt identical to the study's files, `figure_spec.json` rebuilt but different, since its distribution figure came from the run's figure step). Demo 2's `figure_spec.json` cannot be rebuilt: `make_figures.py` reads the `gaia_dr3` and `gaia_clean` tables of `data.db`, which `get_data.py` does not load again.
- **`e2er reproduce` notes follow the package's rebuild list.** The export's note "results/spatial_units_all244.csv … no recorded step builds them again" was printed although the package's `rebuild` list runs `code/scratch/build_data.py` for it (demo 6): files a rebuild or reload step now covers are taken out of that note, and the note goes when none is left.
- **A left-out output the rerun's step only updates is not compared.** Demo 6's rebuilt `figure_spec.json` "differed": `run_estimation.py` reads the figure spec and adds its figures, but the study's copy was written by the figure step and changed by `code/scratch/fill_fig.py`. Such a file (the step reads it before writing it, or another script of the folder not run by the recipe writes it too; export's copy under `replication/` does not count) is reported as "not compared: the study's copy comes from the figure step …", never as differing.
- **The test suite never reaches a real platform.** An autouse fixture removes the keychain, the credentials file and `E2ER_TOKEN` and makes every platform request a test did not fake an error; it now also fakes Zenodo's client, unsets `ZENODO_TOKEN`, `GH_TOKEN`, `GITHUB_TOKEN` and `E2ER_TEST_SERVER`, and points `GH_CONFIG_DIR` at an empty folder.
- **`e2er publish --github` refuses a file larger than 100 MB before anything is pushed**, also in `--dry-run`. GitHub refuses such files, so the push failed after the dry run had listed the file as going up (the weather-words demo's 145 MB `data/data.db`, 2026-10-19).
- **Data files larger than GitHub takes stay out when a recorded step gets them back** (`e2er publish --github`). A data file over 100 MB (under `data/`, or a data output under `results/`, `misc/`, `paper/`) is left out when a step of the study's `reproduce.json` loads or builds it again; for a database, every table it holds must be loaded again or built by a recorded step. `e2er-package.json` declares it like a file left out under a source's terms (`left_out[]` with `kind: "size"`, `host`, `bytes`; terms-based entries now carry `kind: "terms"`, `--no-data` ones `kind: "no_data"`), `e2er.json`'s `repository.left_out` names the kind, and README.md says "`data/data.db`: too large for GitHub (145 MB); `e2er reproduce` loads the tables … again from the sources with code/get_data.py". A file over the limit that nothing gets back is still refused before anything is pushed, also in `--dry-run`, with a plain message per file ("no step of reproduce.json loads it or builds it again", "loads or builds only some of its tables again; no step builds corpus, …", "it is the published result a rerun is compared with"); a file over the limit that is not data is refused as before. In a clone, `e2er verify` counts a file declared too large as left out, not missing, only when the folder's `provenance.json` records it larger than GitHub's limit (a declaration alone does not count), and `e2er reproduce` loads and builds it again. `e2er pack` alone leaves nothing out for its size. (Björn, 2026-10-21, for the weather-words demo's 145 MB `data/data.db` of Project Gutenberg texts. Its export cannot use this yet: its recipe records no step that loads the texts again, since export writes `get_data.py` only for sources with terms, and the tables the study built from them come from `code/scratch/build_data.py`, which reads `data/sample_ids_v2.csv`, a file the export does not ship.)
- **Handles come from the account, not from a first publish.** `e2er submit --handle` must name one of the account's handles (added in account settings on e2er.org), `e2er whoami` with no handle says to add one there instead of "your first publication creates one", and the README's `e2er publish --owner` is a handle of the account, not the GitHub login.
- **The copy of e2er.org's research-object schema names why a file is left out** (`docs/schemas/research-object.schema.json`, from e2er-site fbd94587): `repository.left_out[].kind` is one of `terms`, `size`, `no_data`, the three kinds `e2er pack` and `e2er publish --github` give; a test checks that publish sends no other.

## [0.17.1] — 2026-10-19

### Study files on GitHub (`e2er publish --github`)
- **`e2er publish --github [owner/repo] [--github-path <folder>]`** pushes the study's files to a public GitHub repository with your own login (`gh`, or `GH_TOKEN`) and records the repository, the folder and the commit with the study; e2er.org never receives a GitHub token. `--github` alone uses `<your login>/<project>`, `--github owner/repo` that repository; either is made (public) when missing. `--github-path` puts the study in a folder, so several studies can share one repository. No Zenodo deposit and no DOI on this path: the dossier id identifies the study. Without `gh`, or with `gh` not logged in, publish says what to run and changes nothing.
- **What goes up is what `e2er pack` ships**, built and opened with pack's own code: paper, code, recipe, provenance, `e2er.json` with the dossier, `e2er-package.json`, and the data whose source's terms allow passing them on. Restricted data and files built from them stay out and are named in `e2er-package.json` and `repository.left_out`; a clone verifies (`e2er verify`) and `e2er reproduce` loads and rebuilds them. A last check before the commit refuses any such file in the folder, and a file with a key or token is refused. `--dry-run` lists every file that would go up and every file that stays out.
- **README.md** of the study opens with the title, question, dossier link, demonstration label, e2er version, template and model, the data sources with terms and citation, the left-out files and how they are rebuilt, and the licence (or that none was set); the export's README follows. It is recorded as an amendment (`kind: "readme"`), which the dossier does not list, as with the paper's stamp.
- **One ordinary commit, never forced**, on top of the default branch; only the study's folder changes. A folder with someone else's or another study's files, a folder inside another study's folder, a private or archived repository are refused. A new version is a new commit; the same files make none (the repository's `e2er.json` carries no commit, paper address or publishing time).
- **Links at the commit**: `e2er.json`, `.e2er/github.json`, `.e2er/link.json` and the publish request carry `repository.url/path/commit` (`host: "github"`, `left_out`); the paper is public at `paper/paper.pdf` at the commit, the code public, the data public only when a data file went up. The dossier keeps naming the repository without the commit. The research-object schema documents `repository.host` and `repository.left_out`.
- **A clone of the GitHub folder reproduces.** Checked on copies of demo 2 (Gaia) and demo 7 (WHO) pushed to a local bare repository: `e2er reproduce` on a fresh clone loads the left-out data again, runs the study's preparation steps and reproduces both (demo 7: 246 of 246 values, 2 of 2 tables; demo 2: 930 values identical or the same at the published precision, 3 of 3 tables).
- **Numbers equal to 12 significant digits.** Demo 2's rebuilt `data/gaia_clean.csv` had the study's rows, but pandas wrote one value as -0.0005179820886653 where the run wrote -0.0005179820886653808, so the input was "differs" and the rerun "not reproduced". Table fingerprints now also carry `numeric_sha256` (decimal numbers at 12 significant digits; integers and text exact); an input that matches it is reported as "the same rows, every decimal number equal to 12 significant digits" and the verdict says so. `e2er pack` records the fingerprint of each file it leaves out (`left_out[].content`), and a recipe written before the field takes it from there when the exact content hash is the recipe's own.
- **The package says exactly what a rerun loads and builds.** A left-out database names the tables `get_data.py` loads again from the sources and the tables each of the study's preparation scripts builds again (`left_out[].loads`, `builds`, `not_built`); `e2er inspect`, `e2er pack` and the GitHub README use these words ("loads the tables country_names, road_deaths_2021, who_rs198_2021 again from the sources with code/get_data.py; builds the tables who_region_lookup, who_rs198_2021_clean again with code/scratch/clean_rs198.py") instead of listing every table under the loader.
- **`--github <login>`** (a value without `/`) still sets the author's GitHub login, with a note; the new name for it is `--github-login`.

## [0.17.0] — 2026-10-15

### Fixes from the weather-words demo (text analysis, 2026-10-14/15)
- **`e2er rerun --from <specialist>` runs that specialist again.** On a single-pass study, `--from data_analyst` maps to the step `initial`, but the step kept its record of finished work orders (`initial_done`) and of specialists that ran (`done_specialists`): the rerun resumed only the unfinished text validator, and the data analyst never ran again. Now the named specialist and every work order of the plan that runs after it (in the dispatch's own order) lose their completion, and so do the checks and stops inside the dispatch that read their work (`corpus_gate`, `text_results_gate`); the earlier work orders, and stops such as the design review whose specialists do not run again, stand. The plan is kept after the phase (`initial_plan`), so this also works on a completed study. `--from initial` (the whole step) plans the step afresh, and every check and stop inside it comes again. On a fixed `specialists` step, `--from <specialist>` keeps the specialists before it.
- **A full disk pauses the run.** The run's task died on ENOSPC writing `.pipeline_state.json` (the failure handler's own save raised again) and the study stayed "designing" with nothing running. A full disk now pauses it: "The disk is full; free space and press Resume." (event `paused_disk_full`); the state from the last successful save stands, since it is written atomically. Anything else that escapes the run's handlers fails the run with its error instead of leaving the status as it was.
- **"completed" only after the final export.** `e2er status` said "completed" while the replication packager and the final export still ran, and a folder exported then was overwritten. The study now reads "finishing (writing the export)" (status `finishing`, counted as running) from the end of its steps until the export is written, then "completed".
- **A specialist's call that runs out of time pauses the run.** The data analyst's third attempt was stopped at Claude Code's 1,800 s limit while it loaded Gutenberg texts, and the study failed. The CLI backends now report the wall-clock deadline (`stop_reason` "timeout"); the call is recorded once (`specialist_failed`, `timed_out`), no further attempt is spent on it, and the run pauses with the reason (`paused_timeout`): "Paused: one call ran into its time limit (30 minutes, 1,800 s) and was stopped (…). The files it wrote are kept. Press Resume to give it a new attempt; …". Resume gives the specialist a fresh attempt; a reviewer's lost call is tolerated as before. A template sets the limit per specialist (`[timeouts] data_analyst = 90`, minutes) or per step (`timeout_minutes`); the data analyst gets at least 60 minutes (`docs/templates.md`, `docs/schemas/pipeline.schema.json`).
- **Gutenberg texts load in batches.** `e2er-data gutenberg text` (and `fetch_data` with `materialize`) downloads five books at a time and writes each batch into the table at once, so a call that is stopped keeps what it loaded. One call starts no new batch after ten minutes: it returns the books it has, its note begins with `INCOMPLETE` and names the rest, and the same command again reads the books downloaded that day from the cache and loads the rest. Gutendex's copyright lookup for the same books is kept for the day.
- **The Gutenberg catalogue keeps the translators.** `e2er-data gutenberg books` (and `text`) dropped Gutendex's `translators`, so ten translated novels (Dumas, Verne, Flaubert, …) stayed in an English-language corpus. Each row now has `translators` (names with years) and `authors_years` (every author with birth and death years) beside `author_birth_year`, `author_death_year`, `languages` and `bookshelves`; the catalogue-file fallback separates a "[Translator]" from the authors. The data skill says that `translators` identifies translations. Tested with a cassette recorded from Gutendex (Madame Bovary, translated by Eleanor Marx Aveling).
- **The text number check leaves the design alone.** `e2er verify` listed numbers as "differ" that are not results: rate denominators ("per 10,000 words"), cohort years ("authors born 1770--1799", "in 1799"), thresholds named after the number ("the 30,000-token threshold"), and settings of the design. Now a power of ten after "per", a threshold before or after its number, a year (without a thousands separator) in a span or after a word of time, and a number that is a setting of the study's design (its `*_design.json`, pre-registration, data dictionary apart from row counts and statistics, and the template's check settings) are not looked for in the results. Numbers that match a result still count as traced, and "1,799 novels" or "N = 1790" stay checked.

### Fixes from the 0.16.1 demo runs (2026-10-14)
- **An iterative study gets a whole draft.** In the GDP demo (spatial analysis, iterative) no round dispatched the paper drafter; the third round sent three section writers at once, each wrote `paper_draft.tex` from nothing, the last file (introduction and literature only) stood, and the study was reviewed (5.9 of 10) and exported without data, results or maps. Now, with no draft yet, the section writers of a round become one paper drafter order (the guard against whole-draft rewrites applies only once a draft exists); section writers of one parallel group run one after another, since each edits the same file; and rounds that end without a draft send the drafter out, as the single-pass initial phase already did.
- **Event times cover the declared days.** The data check compared a declared coverage bound such as `1976-01-01` with an event time `1976-01-01T00:04:05Z` as text, so an event catalogue never passed unless an event fell at midnight (the earthquake demo stopped on all five ComCat tables). Two ISO dates or timestamps now compare by their day.
- **Numeric keys of the results are source values.** `e2er verify` failed the earthquake demo's table of b-values by shift in Mc on its row labels -0.3, -0.2 and -0.1, which the results hold only as the keys of `mc_sensitivity_shift`. The number check now also reads keys that are numbers.
- **`e2er reproduce` leaves no temporary folders behind.** The run folder (with its new environment, up to ~140 MB) was kept after every run that did not reproduce, and the test suite's failing-path tests left one per run in `$TMPDIR` until a disk was full. The run folder and an unpacked `.e2er` package are now removed when the command ends, also after a failure or an error; `--keep` keeps both and the report says where. Without `--keep` the report names each failed step's log as removed with the run folder. The test suite puts every temporary folder under pytest's own base folder.
- **A run that stops at once no longer keeps its owner.** The dashboard recorded a run's owner after registering the hook that clears it; a run that paused within a second (a replayed study at its first review) cleared the owner before the claim was written, and the paused study kept this process as its owner. The text-analysis replay test failed on it on CI three times on 2026-10-14. The claim is now written first.

### A study in one file: the .e2er package (2026-10-14)
- **`e2er pack <study id | exported folder> [-o PATH] [--offline] [--no-data]`** writes a study into one file, `<slug>.e2er`: a zip archive (deflate) with `e2er-package.json` at its root, which lists every file with its SHA-256 and size, gives the package a fingerprint (SHA-256 over that list), names the data left out and why, and summarises the recipe. `e2er export --package` writes the file next to the exported folder; the finish page has a "Download package (.e2er)" button. The format (`e2er-package/1`) is in `docs/STRUCTURED_EXPORT_SPEC.md`.
- **The environment is pinned with hashes.** `e2er-package/requirements.lock.txt` lists every package the code needs (the study's pins and what they need) at one version, with the SHA-256 of each file an installer may use (`uv pip compile --generate-hashes --universal`), for the recipe's Python and with releases up to the day after the export, so packing again later gives the same lock. Without the internet the package keeps the recipe's own pins and says so.
- **`--offline` adds the wheels for this computer** under `e2er-package/wheels/<platform>/` (`pip download --only-binary=:all:` of the locked set); `e2er reproduce` installs from them with `--no-index` when the platform and Python match, else downloads and says so. The Frankfurt temperature demo: 423 KB without wheels, 47.5 MB with them (15 wheels for macOS arm64, Python 3.14).
- **Data under terms stay out and are rebuilt.** A data file from a source whose terms do not allow passing the data on (the GMD, Yahoo Finance, the WHO GHO, Gaia, …) is left out; `--no-data` leaves out every data file. `e2er reproduce` on the package loads them again with `get_data.py` and runs the data preparation (`when_missing`), as for a folder without them; a left-out file the recipe cannot load again is named ("a rerun of the package cannot rebuild it").
- **`e2er verify` and `e2er reproduce` take a `.e2er` file**: it is unpacked into a temporary folder and every file is checked against the manifest first; a changed, missing or added file stops the command with its name ("README.md does not match e2er-package.json: it was changed after packing"). Verify adds the check "package" and reports data the package left out in its integrity check instead of failing it. A rerun installs from the package's lock (the installers check the hashes).
- **`e2er unpack <file> [folder]` and `e2er inspect <file>`**: unpack writes the checked files into a new folder; inspect prints the title, authors, e2er version, the data included or loaded again (from which sources), the Python version and packages, the size and the fingerprint.
- **Opening a package runs nothing.** Absolute paths, `..`, backslashes, links, two names that differ only in case, entries not in the manifest, files that unpack to more than 1000 times their packed size and packages over 64 GB (`E2ER_PACKAGE_MAX_BYTES`) are refused before anything is written; files are written without execute permission and without following links.
- **Data built from restricted data are restricted too.** In the Gaia demo, `data/gaia_clean.csv` (the cleaned Gaia rows) was packed as "a file the study's code reads". A data file a script writes after reading a restricted file or table now inherits the source's terms, transitively (`src/core/derived_data.py`: the scripts' strings, module-level constants and write calls; in a workspace also the script log's recorded outputs). Export records them in `provenance.json` (`run.derived_data`). `e2er pack` leaves them out ("built from ESA Gaia Data Release 3 (Gaia) data, whose terms do not allow passing it on"); `e2er publish` treats them like the source's data (public only with `--accept-data-terms`) and warns when no recorded step builds one again. The recipe builds a left-out derived input again with the script that wrote it, after `get_data.py` (`"rebuild"`, `"when_missing"`); a package of an older export carries that step in its manifest (`rebuild`). The Gaia demo packed: `gaia_clean.csv` left out, `e2er reproduce` reloaded the Gaia rows, ran `clean_gaia.py`, and all 930 values and 3 tables matched.
- **An `e2er-package.json` in a folder proves nothing.** `e2er verify` on a folder accepts a missing data file as "left out of the package" only when the folder's own records say a source's terms keep it out; a `.e2er` file's manifest, checked against the archive, counts in full.
- **The same folder packs to the same bytes**: sorted entries, fixed timestamps, the export's date instead of the packing time. Packing the Frankfurt demo twice gave byte-identical files.

## [0.16.1] — 2026-10-14

### Release workflow (2026-10-14)
- The release workflow gives its test job 25 minutes (it had 10): the suite outgrew them and the job was cancelled twice before the wheel was built.

### Wording for people (2026-10-14)
- **Members, authors and sources.** The templates read "Maintained by the e2er authors" (they said contributors). A `based_on` credit is cited on the part's page as "Based on" with a link to the work; the people who wrote it are cited as the source, get no page on e2er.org, and the credit does not say its authors endorse the part (`credits.json`, `docs/templates.md`, the `credit` description in `docs/schemas/pipeline.schema.json`). `e2er publish` speaks of authors: `--github` is "Your GitHub login (author identity)", and a manifest without one asks to "name at least one author". Field names (`creator`, `contributors`, Zenodo's `creators`) are unchanged.

### Integrity fixes from the demo runs (2026-10-13/14)
- **The results come from the shipped script.** Nothing checked that `estimation_results.json` was written by the estimation script the study ships: the earthquake demo's specialist (DeepSeek V4 Pro on OpenRouter) wrote the file by hand after its script, and a rerun of the shipped script gave 289 different values, found only by `e2er reproduce`. The script log (`.e2er-script-runs.jsonl`) now records the SHA-256 of every results-type file (`.json`, `.csv`, `.tsv`) each script run wrote (`outputs`). After the analysis specialist, a results file (`estimation_results.json`, `robustness_results.json`) that is not the output of the last successful run of the script as shipped is checked by running the script chain again (the order `e2er reproduce` uses): the same values (identical, the same at the file's precision, or within float noise of 1e-9 relative, as another platform's libraries write the last digits) pass, and the specialist's file stays as it is, with the confirmation in the log; other values put the specialist's file back and fail the estimation contract with "estimation_results.json was not written by run_estimation.py as shipped (…; run again, run_estimation.py writes 1 of 3 values differently); change the script and run it." Results with no script behind them fail too: "The results have no script that computes them; write run_estimation.py that produces estimation_results.json and run it." Only a study whose script log predates output records (e2er up to 0.16.0) is not judged.
- **`e2er verify` checks that the results come from the code.** Export records in `provenance.json` (`run.results_from_code`) which run of which script wrote each results file, with its output hash; verify's new check "results from code" fails a results file that is not the file that run wrote, one no recorded run wrote ("the results have no script that computes them"), a run that failed, a script changed after the run, or a script missing from the folder; a run that predates output records reads "not checked: the run predates output records".
- **A revision round can no longer do nothing.** In the exoplanet demo every edit of the targeted corrections targeted `paper:full` (as the revision skill and the coverage check tell it to for a passage outside the named section), the merger rejected all five as "not in work order findings", nothing sent the revisor back, and the paper shipped as the reviewers had scored it. An edit targeting `paper:full` is now a text edit anywhere in `paper_draft.tex`. A patch that applies no edit while findings are open (and keeps no passage with a reason) fails the revisor's contract with the reason each edit was rejected; after the last attempt the revision round stops for the researcher (output contract), and an approval completes the run with the draft as it is. The revision skill no longer calls `[]` a valid answer to the panel's open findings (the number check's correction may still answer `[]`).
- **No credits or a spent key limit pauses the run.** OpenRouter's 402 ("insufficient credits", the key's total limit) and Anthropic's "credit balance is too low" / "reached your specified API usage limits" pause the run like a subscription plan's limit: the status says what to do ("The OpenRouter key's spending limit is reached. Raise it at openrouter.ai or choose another AI provider, then press Resume."), no attempt is counted, what the call used before the refusal is in the study's cost, and the event is `paused_billing_limit`. A send-back at a researcher step that hits the limit (the earthquake demo's draft review returned to the same stop with no error) is kept: Resume sends the specialist back again with the remark.
- **A study whose data stay out of the folder reproduces.** Without data.db the WHO demo's rerun failed: `get_data.py` reloaded the WHO tables but not the analyst's cleaned table the estimation reads. When a source with terms loaded a table into data.db, the recipe now loads every table a source loaded (Natural Earth's too) and runs the data preparation (the scripts from the script log that build the tables the estimation reads) after `get_data.py`; those steps run only when the folder lacks data.db (`"when_missing"`). The WHO demo exported again reproduces without data.db, 246 of 246 values identical.
- **Reloaded inputs are compared by their rows.** A Gaia reload with the same 14,066 rows in another order counted as a different input. The recipe now records each table input's content (CSV/TSV rows, and every table of a SQLite database, order aside); `e2er reproduce` reports "same rows in a different order (identical content)" and counts it as the study's input, and names the tables of a database that differ.

### Small fixes from the demo runs (2026-10-13)
- **The text number check reads rounding, percentages and constants.** A number in the text matches a source value rounded to the decimals it shows (7.3 for 7.25); "39 percent", "39 per cent" and `39\%` match a share of 0.39; and conventions are not checked as results: conventional confidence levels next to "confidence", "prediction" or "interval" ("95 percent"), unit factors in a formula (the 1000 of 1000/ϖ) and sample cuts after a comparison or "threshold"/"cutoff" (`$< 500$ pc`, `$M \geq 4.5$`). They are counted as excluded. The check stays non-gating.
- **`e2er review --instruction … --approve` does both.** The approval was silently dropped. Options given together now run in order: the edit, the instruction, then the send-back or the approval; the run continues only when everything before it was recorded. `--send-back` with `--approve` is refused with a plain message, and nothing is recorded.
- **`e2er rerun --from` takes a specialist.** A stop's send-back list offers specialists, `--from` took template steps only. A specialist named in a step's `run` maps to that step (`revisor` → `revision`), one the strategist dispatches (`paper_drafter`, `data_analyst`) to the strategist step; the whole step runs again, and the remark is addressed to the specialist. A specialist that runs in two steps (`initial` and `iterative` in an iterative run) is refused with the two to choose from. The dashboard's rerun takes the same names.
- **`e2er-data <source> --help` names `e2er-data`**; it showed the old name `e2er-allium-query`.
- **`e2er doctor` says "LITERATURE_DIR …: set, empty"** for a literature folder that is set but holds no PDFs or .bib files yet; it said no LITERATURE_DIR was set.
- **JEL codes only in economics papers.** The climate and earthquake drafts carried "JEL: C22, C53, Q54" lines. The abstract skill now asks for JEL codes in economics papers only; templates with another persona than the economist (descriptive, spatial, time-series, text, systematic review) tell every specialist to write none; and in those templates the draft writers' phrase check sends a draft or a revision edit with a JEL line back. Economics templates (the economist persona, the causal regression templates) keep their JEL codes.
- **Pre-registered hypotheses keep their labels.** "- **H1 (average effect)**: Abolition raises …" became the statement "average effect Abolition raises …" in the machine-readable block. The statement now reads "average effect: Abolition raises …" and the block carries the label as `label`; a bold label after a dash ("**H1 — average effect:** …") is read the same way.
- **Project Gutenberg searches no longer wait ten minutes.** Gutendex answered in 78 s per page in the weather-words demo. A `gutenberg books` search is now kept for the day (per query), Gutendex gets 45 s, and when it does not answer the search reads Project Gutenberg's own catalogue file instead: `pg_catalog.csv.gz` from the mirror's feeds directory, which Project Gutenberg asks tools to use in place of crawling its website (its catalogue data are public domain). The file is downloaded at most once a day, and for an hour after a timeout searches go to it directly. Its rows have no download counts or copyright status (ordered by book number; the note says so); `text` still checks copyright through Gutendex and, when Gutendex does not answer in 45 s, stops with a plain message.
- **A spent OpenAlex budget is said plainly.** Keyless OpenAlex requests share a daily budget per network; when it is spent OpenAlex answers 429 "Insufficient budget", and the weather-words demo's literature search silently found nothing. The refusal is now told apart from a burst limit, OpenAlex is not asked again that UTC day, and the run says "OpenAlex's free daily budget for this network is used up; the literature search found nothing today" (or that it used the other sources only), in `literature/web_search.json` (`notices`), on the study's inputs panel, as a `literature_search_notice` event and to a specialist's literature search and `e2er-lit`. `OPENALEX_API_KEY`, when set, is now sent with the literature searches too (it has its own budget).

### OpenRouter attempts cost a fraction (demo 8, 2026-10-13)
- **The conversation of an OpenRouter tool loop stays small.** Each turn resends the whole conversation; one data-analyst attempt on DeepSeek V4 Pro sent 785k fresh and 8.6M cached input tokens and cost $1.44. A tool result longer than 40,000 characters is now cut at a line break when it enters the conversation, with a note saying how much was shown and how to see the rest (`read_file` takes a new `start_line`). The last six tool exchanges stay in full; once twelve are in full, the oldest are summarised in one step (a long result becomes a note with its first lines, a long `write_file` body its length), so the start of the conversation stays the same between steps and still hits the provider's cache. On a mocked 60-turn attempt that reads 30,000-character previews, the input sent falls to about a quarter.
- **Each attempt stops at 3 million input tokens** (fresh plus cached, `OPENROUTER_ATTEMPT_TOKEN_BUDGET`, 0 for no limit), with a plain message saying what it sent and how to go on.
- **Prompt caching is asked for where the model needs it**, following OpenRouter's caching guide: Anthropic models get the top-level `cache_control`, Alibaba's explicit-caching models (Qwen, DeepSeek V3.2) a breakpoint on the system prompt; DeepSeek V4, OpenAI, Grok and the other automatic-caching models get nothing extra. Every attempt sends a `session_id` so OpenRouter keeps its calls on the provider holding its cache (when no provider order is set). Cache-write tokens are counted apart from fresh input.
- **Each specialist attempt is recorded** as an `attempt_usage` event: calls, fresh, cached, cache-write and output tokens, the largest single call, how many exchanges were summarised, the stop reason and the cost.
- **The offline price of DeepSeek V4 Pro is OpenRouter's listed one** ($0.96 in / $1.91 out / $0.08 cached per million tokens, read 2026-10-14; it was $0.23/$0.46). It prices a call only when the response reports no cost.

### The reproduce recipe installs what pandas loads on demand
- **`code/requirements.txt` pins the optional backends the scripts' pandas calls need.** It pinned only the packages a script imports, so a live Codex study that read an Excel file with `pandas.read_excel` failed its rerun with "Missing optional dependency 'openpyxl'". Export now reads the calls in the scripts: `read_excel`/`to_excel`/`ExcelWriter` add openpyxl (and xlrd for `.xls` files, XlsxWriter or odfpy when the call names that engine), the Parquet/Feather/ORC calls pyarrow, `read_xml` lxml, `read_html` lxml, beautifulsoup4 and html5lib, `to_markdown` tabulate, `to_latex` and `.style` jinja2, `read_spss` pyreadstat, the HDF5 calls tables, and `read_sql` with a database URL SQLAlchemy. Each is pinned at the version installed where e2er runs, with the reason as a comment; one that is not installed is listed without a version (the rerun installs the latest compatible release) and the recipe says so.
- **The script log records every package a script loaded.** `e2er-run`, the runner and the meta-analysis run a study's script through a small bootstrap that, when the script's interpreter exits, writes the installed packages of the modules it loaded into the script's line in `.e2er-script-runs.jsonl` (openpyxl, numpy, pytz for a pandas script that read a sheet). The recipe pins them at the run's versions, from the last successful run of the version of each script the study ships; these win over the versions of e2er's own environment.
- **The recipe names the Python the run used.** Its `python` came from the interpreter that ran the export (e2er's 3.14 for a study that ran on 3.12, which had to be set back by hand). The script log now records the Python version of the interpreter that ran each script, and the recipe takes it from the last successful run of the estimation script the study ships. A run that recorded none (e2er up to 0.16.0) falls back to the export's Python, and the recipe says so in a note.
- **`e2er reproduce` says which package was missing.** When a step fails with "Missing optional dependency 'X'" or "No module named 'X'", the report and the verdict say "The recipe does not pin openpyxl, which pandas needs to read and write Excel files (.xlsx)." (the package that asked for it is read from the traceback), next to the path of the full output.

### Preflight is quick with many data sources
- **Preflight and `e2er doctor` ask the data sources side by side** (at most 16 at once) instead of one after the other, each with a short time limit: 3 s to connect, 5 s in all (6 s for the literature search, the PDF download, Yahoo Finance and the GMD), and no retries, since a refused connection or a name that does not resolve answers the question at once. A source that does not answer in time reads "… could not be reached" like any other. Offline (connections refused, as in the site's E2E suite) the checks took 44 s and now take 1 s; online 15 s, now about 4 s; with a network that drops every packet, about 7 s.
- **The dashboard keeps the result for 3 minutes**, so opening Preflight, then New study (its banner), then Preflight again runs the checks once. The page opens at once and the checks fill in when they are done; "Check again" asks again, and saving the settings on Setup always checks again.

### Fixes from the 0.16.0 demo runs (2026-10-13)
- **`e2er run` works when it has to start the server.** It started uvicorn without the session token it then sends, so the server made its own and refused the new study with 403 ("This browser tab is not signed in to e2er"). The server it starts now gets the computer's session token, and `~/.e2er/session-<port>.json` is written once it answers, so later `e2er review`/`resume` commands are accepted too.
- **`e2er serve` (and `e2er` alone) bind `PORT` from `.env`**, the port `e2er run` and the other commands talk to; before, they bound 8280 unless `--port` was given.
- **`fetch_data` sends the model at most 50 rows of a load.** It returned every row: a USGS load of 277,935 events made the next OpenRouter request exceed its 8 MB limit and failed the data analyst. The reply now carries the first 50 rows, `items_total` and a note; a materialized load stays complete in data.db (API backends; the CLI backends load through `e2er-data`).
- **A pre-registered hypothesis tagged below the top level of the results counts.** The check that every pre-registered hypothesis has a result read the `hypothesis` field only on top-level entries; the time-series demo tagged H1 to H3 in a list of hypothesis results and under `trend`, and the estimation failed its contract three times. Nested entries with their own `hypothesis` field now count (also in `e2er verify`); a block that only lists the hypotheses does not.
- **Scatter figures can reverse an axis** (`invert_x`, `invert_y`): a colour-magnitude diagram puts bright stars, with small magnitudes, at the top. The Gaia demo had to draw the Pleiades diagram upside down and say so in the caption. The figure-spec skill shows it.
- **A load through `fetch_data` is recorded like one through `e2er-data`.** On the API backends (OpenRouter, Anthropic) a connector-kit load wrote only `data_sources.json`: the table's data dictionary entry and the source's BibTeX entry in `literature.bib` were missing, so the earthquake demo on DeepSeek cited no catalogue for its USGS data. Both are now written, and the reply names them (`recorded_in`, `cite_key`).

### From the demo studies 5–8 (2026-10-13)
- **`e2er status`, `review`, `resume`, `cancel` and `rerun` take the first characters of the id**,
  as `export` and `archive` already did (4 or more characters; an ambiguous prefix is refused and
  names the number of matches). Before, `e2er status 9ff31cc0` answered "not found".
- **The web literature search no longer searches a cut-off title.** A long question's title is cut
  at 80 characters with "..."; that cut title was the second search query, and its half word and
  unclosed parenthesis made arXiv answer 400 Bad Request (the school-fee demo got no web literature).
  The question's first sentence is searched in full instead, and arXiv queries drop parentheses.
- **The idea developer and the identification strategist see the sources the study can use**, the
  list the data architect already got. Without it a strategist planned as if only Yahoo Finance and
  the GMD were keyless, and wrote that World Bank data had no connector.
- **The idea developer, identification strategist and data architect may search the literature**
  (`e2er-lit` on Claude Code), and the sources list tells them to find a published source for facts
  no data source holds (a policy's adoption year, a book's first publication) instead of filling them
  in from memory. In the school-fee demo the architect was asked to source each abolition year and
  every search was refused; the dates stayed "recalled".
- **A specialist sent back from a researcher step has the checks that read its work run again.** At
  the school-fee demo's pre-registration the data analyst was sent back and rebuilt the panel (8
  treated countries instead of 15, ending in 2010); the design check that had passed on the old panel
  did not run again, and its report still described the old one. Now every check inside the dispatch
  that names the specialist in `after` and has run before runs again on the new work (with a retry
  of its own); a check that has not run yet is left to the dispatch.
- **An initial phase that ends without a draft sends the paper drafter out.** The school-fee demo's
  plan left the drafter out; the run went on to the review with no `paper_draft.tex`, the five
  reviewers judged the plan (4.3 of 10), and the study "completed" without a paper. The drafter is
  now sent out at the end of a single-pass initial phase when no draft exists and a review follows
  (event `drafter_sent_out`), after
  the checks it waits for.
- **The estimation script may not read e2er's records of the run.** A Codex analysis asserted on the
  completed stages in `.pipeline_state.json`, which the export does not ship, so `e2er reproduce`
  failed on its first step (all 29,146 values reproduced once that line was stubbed). The standalone
  check of the estimation chain now names a script that reads `.pipeline_state.json`,
  `.study_inputs.json` or `.e2er-script-runs.jsonl`, and the analyst fixes it within its attempts.
- **`--json` output is JSON only.** `e2er verify --json` printed a log line ("… INFO … render_tables:
  wrote 2 table(s) …") before the report, so the report could not be parsed. With `--json` every log
  line goes to stderr.
- **A number inside an identifier is not checked as a number.** The number check of the text read the
  198 of the WHO indicator code `RS\_198` (and then its tail 98) as a value and reported it as
  differing from the sample of 195 countries. Digits after a letter, an underscore or another digit
  are no longer taken as the start of a number.
- **`fetch_data` cuts long texts in its reply to the model** (2,000 characters per text field, with a
  note that the full texts are in data.db). Ten Project Gutenberg novels in one reply passed
  OpenRouter's 8 MB request limit and failed the data analyst of the text-analysis demo (the row
  limit of 50 does not help when each row is a novel).
- **Send back offers the specialists the study ran.** Several specialists write `paper_draft.tex`,
  so "its output exists" offered a descriptive study's researcher the field-map and
  systematic-review writers at the draft review. The list now keeps the specialists the run's log
  shows starting (every specialist with output when there is no log).
- **Stopping the server pauses a running study again, as intended.** The shutdown hook cancels each
  running study and then marks it paused, but its update skipped studies already marked
  `cancelled`, and the runner marks every cancelled task `cancelled` first. So a server restart left
  running studies "cancelled by user", and `e2er resume` refused them.

## [0.16.0] — 2026-10-13

### From the text-analysis live run (2026-10-11): checks before the draft, method sources
- **The draft waits for the checks it reports.** The plan left out the text validator; the
  validation check sent it out only after the draft existed, and the researcher had to send the
  draft back. A gate step inside the dispatch can now name `before = ["paper_drafter"]`: in every
  phase, before a group with the drafter runs, the specialists of the check's `after` that have not
  run are sent out (event `sent_out_before`), then the check runs (recorded, retried or stopping the
  run like every check inside the dispatch), and only then is the drafter dispatched. The strategist
  is told so. Applied to text analysis (results and validation checks), policy evaluation (DiD
  results), spatial analysis (spatial results), the descriptive study (data check, and a new
  `figures_before_draft` check of the figures) and time series (a new `forecasts_before_draft`
  forecast check; the figure and forecast checks may now also sit inside the dispatch). A check that
  runs as a step of its own may name `before` too; the template is refused unless it comes before
  every step that runs the named specialists (systematic review: extraction and synthesis before the
  review writer), and a check before a specialist the strategist dispatches needs `after`.
- **The template's method sources are in the study's bibliography.** Each template's `[[credit]]`
  entries with relation `cites` are written into `literature.bib` at the start of the run as BibTeX
  (`e2er_source = {template}`, `e2er_template = {<template>}`; the key is the credit's `cite_key` or
  surname, year and first title word, e.g. `dunning1993accurate`; an entry whose key is already in the
  file is kept; the field map's and the systematic review's fuller entries are used under their own
  keys). The writers' list of citable references marks them `[method source]` and tells them to cite
  the methods the study used and leave the others out; the paper-structure and text-analysis skills
  say the same. Nothing forces a paper to cite them. The citation check verifies them like every
  reference; the dossier lists them with `"source": "template"` and the finish page as "method
  source" (the site's references list needs the same label for `template`).
- **NMF from nndsvd: no stability across seeds.** When a topic model is NMF started from nndsvd or
  nndsvda (or no `init` recorded: scikit-learn's default is nndsvda), the text results check notes that
  the runs under different seeds are one fit, whatever their stability, and lists the model in
  `text_check.json` (`seed_independent_models`). The draft writers' phrase check then sends back every
  sentence claiming the topics are stable (or the same, robust, consistent) across seeds, unless the
  sentence says why (nndsvd, a deterministic fit, the seed ignored); `init="random"` (or `nndsvdar`)
  lifts it. `e2er verify` prints the same sentences as a note.

- **The targeted corrections pass the phrase check too.** The revisor writes edits, not the draft, so its replacement sentences were not checked; now they are, with the same feedback as the draft writers.


### Fixes from the template live runs (2026-10-11)
- **A phrase check on the draft's prose.** A live run kept "Against this background" although the
  researcher had asked the writer not to use it. The paper drafter, the section writer, the abstract
  writer and the field review writer now fail their output contract when their prose uses a
  construction the researcher rejects, and the next attempt gets each sentence to rewrite:
  "Against this background" (and "Against this backdrop"), "rather than", "not X but Y", "not only
  X but also Y" (and "not just … but"), "It is important to note" (and "It should be noted", "It is
  worth noting"), "In this section, we", "delve", "a testament to", "plays a crucial role" (also
  pivotal or vital), "navigate the complexities", and more than two em-dashes on a page (500 words).
  Quotations, citations, comments, maths, tables and the bibliography are left out; a negated action
  followed by "but" ("we do not observe X, but we infer Y") is a concession and passes. Triads used
  for rhythm are not checked: they cannot be told apart from lists reliably. `e2er verify` prints
  the same sentences of `paper/paper.tex` and `paper/abstract.tex` as a note (`writing_notes` in
  `--json`) that changes neither the verdict nor the exit code (`src/core/writing_check.py`).
- **Targeted corrections fix every passage a finding names.** The descriptive run's revisor fixed
  one of several passages that presented calculated exoplanet radii as measured. The self-critique
  now quotes every passage with a problem (`locations`), the findings reach the revisor with their
  locations and an id, and the revisor is told to search the whole draft and correct each passage.
  A passage it leaves gets an entry `"edit_type": "keep"` with its reason. A check after the revisor
  (its output contract) applies the patch to a copy and sends it back with every location neither
  corrected nor kept, every corrected passage that occurs again elsewhere unchanged, and every keep
  without a reason. What is still open after the last attempt is recorded (`revision_coverage`).
- **A send-back at a check stop reruns the check.** After sending a specialist back at a failed
  check, the run stopped at the same check again and needed an approve before the check ran. Now
  the specialist runs, then the check, and the run continues if it passes; it stops again only if
  the check still fails. Dashboard and `e2er review --send-back` alike (the CLI says so).
- **Each source with terms states its own reason.** "Its terms do not allow passing the data on"
  was too strong for Gaia (CC BY-NC 3.0 IGO) and GISCO (non-commercial use). Each restricted source
  definition gives a one-line `reason`, used in the publish note, the finish page, the confirmation
  and its refusal, `get_data.py`, the skill stub and the README: Yahoo Finance, personal use only;
  the GMD, not outside the study's replication package; Gaia, non-commercial use with credit to
  ESA/Gaia/DPAC; GISCO, non-commercial use with the EuroGeographics notice on every map; WHO, public
  health purposes and no changes without WHO's written permission; GitHub, no licence to
  redistribute the repository metadata. (The site's `RESTRICTED` map in `src/lib/requests-core.ts`
  needs the same reasons and entries for Gaia, GISCO, WHO and GitHub.)
- **GitHub data need an open-access paper.** GitHub's Acceptable Use Policies (section 7) allow
  research use of public non-personal information only if the resulting publications are open
  access. A study that used the `github` source is published only with `--paper public` (or the
  paper set to public on the finish page); otherwise publish refuses, says why and changes nothing.
  The finish page states the rule next to the paper.

### A new data source is one definition (connector kit)
- **One `Source` definition per source** (`src/modules/data/sources/<name>.py`): name, website,
  terms (address, summary, full text), citation and BibTeX, key setting (or none), whether a published
  study may pass the data on, politeness (spacing between requests, retries, request budget) and its
  operations, each with its arguments and a fetch function returning rows. From it e2er builds the
  `e2er-data <source> <operation>` subcommands (with `--table` and `--save-to`), the record of every
  load in `data_sources.json` (terms, citation, the request as made, the query, the release, the
  SHA-256 of every file read), the table's data dictionary entry, the citation in the study's
  `literature.bib`, the planning catalogue and `fetch_data` method, the sources and aliases the data
  architect may declare, the standalone check's loading commands, the dashboard's labels, a doctor
  reachability check, and, for a source whose terms keep its data with the source, the terms gate on
  publish and the reload in `get_data.py`. Before, a source touched about eight places.
- **Adapters for the common services** (`sources/adapters.py`): REST JSON with paging (page numbers,
  offset, next link), TAP/ADQL (astronomy archives), CSV/ZIP download cached by version and re-hashed
  with SHA-256, and SDMX-CSV (official statistics). Every request names e2er in its User-Agent, is
  spaced and retried after HTTP 429/502/503/504, and a failure names the URL and the status.
- **Recorded fixtures for tests** (`use_cassette`): a test records the source's responses once, live
  (`E2ER_RECORD_FIXTURES=1`), and replays them offline; a request the fixture does not hold fails the
  test. No live calls in CI.
- **Yahoo Finance, FRED and the Global Macro Database are defined the same way**, with no change in
  behaviour: their subcommands, arguments, printed results, load records, citations, terms gates,
  reload commands, labels and planning cards are identical (checked on 28 scenarios before and after).
  Their fetching and handlers stay their own; the definitions are the one place for everything else.
- **New source: the USGS Earthquake Catalog** (`e2er-data usgs events --start … --end …
  --min-magnitude … --bbox west,south,east,north`): earthquakes worldwide from the ANSS Comprehensive
  Catalog through the USGS FDSN event service, no key, U.S. public domain. A period with more than the
  service's 20,000 events per request is split into windows by their counts. Each load records the
  query URL, the service version and the SHA-256 of every CSV read, and adds the catalogue's citation
  (DOI 10.5066/F7MS3QZH) to the study's references.
- **Docs and generated text**: `docs/CONNECTORS.md` (how to add a source, with the USGS connector as
  the worked example); `scripts/gen_sources.py` writes the README's data source table from the
  definitions and a skill stub for a new source; a test fails when the README lists other sources.

### New data sources: astronomy and earth science
Each with its terms quoted from the source's own pages, its citation from the provider's recommended
citation or DOI record, a skill file (what is in it, typical calls, units, pitfalls), a doctor check,
and contract tests on responses recorded live once.
- **NASA Exoplanet Archive** (`e2er-data exoplanets planets|query`, no key): confirmed planets and
  host stars from the archive's TAP service, one row per planet (`pscomppars`, default) or one
  published solution per planet (`--catalogue ps`), with `--columns`, `--since`/`--until`, `--method`
  and an ADQL `--where`; `query` runs one ADQL SELECT. The archive states no licence; each load carries
  NASA's acknowledgement, the archive paper (Christiansen et al. 2025) and the table's DOI
  (10.26133/NEA13 or NEA12).
- **ESA Gaia** (`e2er-data gaia cone|query`, no key): Gaia DR3 sources in a cone (`--ra --dec
  --radius`, `--max-mag`, `--min-parallax-over-error`) or any ADQL SELECT, within the archive's
  anonymous quota (50,000 rows, 10 s). Gaia data are CC BY-NC 3.0 IGO: e2er handles them as data under
  terms (publishing asks for `--accept-data-terms gaia`, a Zenodo deposit takes a non-commercial
  licence, `get_data.py` reloads them from the fixed DR3 release); loads cite the Gaia mission and DR3
  papers.
- **NASA POWER** (`e2er-data nasa_power point|regional|parameters`, no key): daily, monthly or annual
  weather and solar parameters for a place (up to 20) or a 2–10 degree region (one), since 1981. Each
  load records the API version, community, time standard and units, and its citation names the API
  version and access date as POWER asks; POWER's fill value −999 becomes an empty cell.
- **NOAA Climate Data Online** (`e2er-data noaa daily|stations`, free token `NOAA_TOKEN`): GHCN-Daily
  station records (temperature, precipitation, snow), paged and split by year within the token's
  limits; the token travels in a header and is never recorded. Without a token the source is not
  offered and says where to get one.
- **TAP loads never cut a table**: `tap_capped` asks for one row more than the cap and stops the load
  when the result is larger; a TAP service's error VOTable (also on HTTP 400, as Gaia sends it) becomes
  the load's error with the service's message. `PoliteClient.get(ok_status=…)` lets a fetch function read
  a refusal's body (POWER's HTTP 422 messages).
- **Recording fixtures**: two loads inside one `use_cassette` block now record (each request gets its own
  transport; before, the second load failed with "Event loop is closed").
### New data sources: statistics, health, books and software
- **World Bank Open Data** (`e2er-data worldbank indicators | series`): development indicators by
  country and year through the Indicators API v2 (World Development Indicators by default, other
  World Bank databases with `--database`), no key, CC BY 4.0. Each load records every indicator's
  licence and data source from its metadata, names any indicator that is not CC BY 4.0, and cites in
  the World Bank's format ("The World Bank: Dataset name: Data source").
- **Eurostat** (`e2er-data eurostat datasets | dimensions | data`): EU statistics through the
  dissemination API, filtered by dimension, NUTS level (`--geo-level nuts2`) and period; no key. The
  citation follows Eurostat's copyright notice (the dataset's DOI and, for a filtered extract, its
  datacode link with the access date); the terms note that non-EU/EFTA/candidate-country data and
  data of other sources may be reused non-commercially only, and that Eurostat keeps no past versions.
- **Our World in Data** (`e2er-data owid search | chart`): the data behind any OWID chart with each
  indicator's origins and their licences (OWID's own data are CC BY; third-party data keep their
  producers' licences, recorded per origin and named in the note when not open); charts OWID marks
  as not redistributable are refused. The citation credits OWID and the producers, as OWID asks.
- **WHO Global Health Observatory** (`e2er-data who_gho indicators | data`): WHO health statistics
  by country, year, sex and age through the GHO OData API, no key. WHO's terms for its data allow use
  for public health purposes and no changes without WHO's written authorization, so a published study
  reloads GHO data (`get_data.py`) instead of shipping them, after the researcher confirms the terms.
- **Project Gutenberg** (`e2er-data gutenberg books | text`): the catalogue through Gutendex and
  plain texts from Project Gutenberg's own mirror (its website allows no automated access), at most 20
  books per load, two seconds apart. Texts are stored without Project Gutenberg's header, footer,
  licence and references (which leaves texts unrestricted by U.S. copyright, per its licence), and
  the load records what was cut; books still under copyright are refused.
- **GitHub** (`e2er-data github repos | repo | releases`): public repositories' metadata (search by
  query, topic, language, stars and creation date; details, languages, contributor count; releases),
  never their contents. Keyless within GitHub's limits; an optional `GITHUB_TOKEN` setting raises them
  (the machine's `gh` login is never used). GitHub allows research use only with open-access
  publications and grants no licence to pass the metadata on, so a published study reloads them.
- **Connector kit**: recorded fixtures replay redirects and `Link` headers, and recording works across
  several `e2er-data` calls in one test; a definition whose argument is one of e2er-data's own names
  (`source`, `table`, …) is refused.

### Templates: policy evaluation (difference-in-differences) and spatial analysis
- **`policy-evaluation`**: what a policy changed, by difference-in-differences. The identification
  strategist writes `did_design.json` (outcome, panel, treatment timing, comparison group,
  estimator). The `did_design` check reads it against the panel in `data.db` before estimation and
  stops the run when the outcome or timing is not in the data, there is no comparison group, timing
  is staggered and the estimator is two-way fixed effects (it names the heterogeneity-robust
  estimators: Callaway–Sant'Anna, Sun–Abraham, de Chaisemartin–D'Haultfœuille, Borusyak–Jaravel–Spiess,
  Gardner, stacked, Wooldridge), or no cohort has two pre-treatment periods; staggered timing with a
  robust estimator passes with a warning. The design is pre-registered (`did_design.json` is a plan
  file). After estimation, before drafting, the `did_results` check requires the event study with at
  least two pre-treatment periods, a joint pre-trends test (a rejection at 0.05 stops the run unless a
  Rambachan–Roth sensitivity analysis is reported), a placebo test or a sensitivity analysis, and the
  declared estimator under `main`; it draws the event-study plot from the results. Panel:
  identification, data, methods, writing, technical. Skill `econometrics/did-practice`.
- **`spatial-analysis`**: how a variable varies across places, with no causal claim (spatial results
  contract, researcher persona). The data architect writes `spatial_design.json`; the
  `spatial_design` check stops the run when the boundaries' source is not recorded, the CRS is
  missing or does not fit the coordinates, a data unit without geometry is not listed with a reason,
  or the weights are not documented. After the analysis the `spatial_results` check recomputes every
  Moran's I from the units and weights the analysis wrote (`spatial_units.csv`,
  `spatial_weights.csv`), requires permutation inference (at least 99 permutations), checks the
  weights file, and builds a map figure for every map the results name. Panel: methods, data,
  plausibility, writing, technical. Skill `data/spatial-statistics` (weights with numpy, Moran's I,
  LISA, MAUP, edge effects, islands). Units without geometry are listed by id or by a pattern
  (`"CH*"`, `"*ZZ"`); a sentence naming a group does not count.
- In both templates a failed method check sends its specialist back once with the reasons
  (`on_fail = "retry"`), then stops the run for the researcher; approving does not pass it.
- **Maps** (`figure_type: "map"`, `src/core/renderer/maps.py`): choropleth (quantiles, equal intervals,
  given breaks), categories (e.g. LISA clusters) and point maps, drawn from a `data.db` table of
  GeoJSON geometries or a GeoJSON file and values from a CSV or a table, with matplotlib alone (no new
  dependency); equal-area projection for Europe, Equal Earth for the world. Units without data are
  drawn as "No data", data units without geometry are named in the render report, the boundaries'
  attribution is printed on the map.
- **New sources for boundaries**: `e2er-data gisco nuts|countries` (Eurostat GISCO; NUTS 2003–2024 at
  1:1 to 1:60 million, EPSG 4326/3035/3857; terms checked 2026-10-11: non-commercial use, the notice
  "© EuroGeographics for the administrative boundaries" on every map, no right to pass the files on,
  so a published study loads them again and no Zenodo deposit holds them) and `e2er-data naturalearth
  countries` (Natural Earth v5.1.2, public domain). Each row is a unit with its geometry as GeoJSON text.
- `e2er verify` runs the results side of these checks again on an export (`method checks`); the export
  carries `did_design.json`, `spatial_design.json` and the checks' findings. `e2er reproduce` no
  longer counts files the analysis script writes (`spatial_units.csv`, weights files, anything it
  opens for writing) as its inputs; a file it reads and writes back (`figure_spec.json`) is laid out
  as the study left it; and a script that reads the data only through `e2er-data query sql` gets
  `data.db` as its input (before, the recipe left it out and the rerun had no data; found in the
  spatial live run).
- Maps in a projected CRS (EPSG:3035, EPSG:3857) honour an `extent` given in degrees; before, the
  extent was ignored and overseas regions shrank Europe to a corner (found in the spatial live run).
  The spatial results check finds the units file's id column (`id`, else the one the results name).
- Publishing no longer mistakes a URL whose path starts with `/home/` or `/Users/` for a path on this
  machine (World Bank indicator metadata cite `https://unstats.un.org/home/nso_sites/`; found when
  publishing the DiD live run).
- A template's `[[credit]]` `published` date may be as precise as the publisher gives it (YYYY-MM for a
  journal issue, YYYY for a book). Both templates cite their method sources (DOIs checked on Crossref).
- Tests: replay fixtures of a synthetic staggered panel and a synthetic grid of regions, run end to end
  (stops, both checks, number check, panel, publish offline, verify with the method checks,
  reproduce), a pre-trend that stops the run before drafting, a data unit without geometry that stops
  it before the analysis, unit tests of the checks and the map renderer, and the connectors with mocked
  files.

### A core without economics assumptions (for 0.16.0)
- **A template declares the kind of results its study reports.** `results = "regression"` (the
  default, e2er's contract as before), `"descriptive"`, `"timeseries"`, `"spatial"` or `"text"`. The
  estimation check holds `estimation_results.json` to that kind's contract
  (`src/core/pipeline/result_kinds.py`): descriptive (summary statistics with ordered quantiles,
  distributions whose counts add up to their n, figures declared in `figure_spec.json`), time series
  (models with fit statistics, forecasts inside their intervals, out-of-sample RMSE and MAE, MAE never
  above RMSE), spatial (units, spatial statistics with their weights, Moran's I expectation
  -1/(n - 1), p-values that follow from z, map specifications), text (corpus counts, term
  frequencies whose per-10,000 values follow from the counts, text-model outputs). A results file of
  these kinds starts with `"result_kind"`; one script and one file serve every kind, so rerun, export
  and `e2er reproduce` are unchanged. Each kind has a schema skill
  (`skills/files/data/<kind>-results-schema.md`) that the analysis specialist reads in place of the
  econometrics skills, and whose example the tests check against the contract.
- **The number check reads the kind's files**, and `e2er verify` adds a `results contract` check for a
  study whose results are not a regression (none for regression studies, whose output is unchanged).
- **Tables of statistics, categories and periods.** `table_spec.json` takes `"layout": "records"`: rows
  are entries of the results (variables, bins, forecast periods, spatial statistics, terms) at a
  `path` in the results or `summary_statistics.json`, columns are their fields; filled by lookup like
  the regression layout, with unresolved paths, rows and fields reported by `e2er-check-tables` and
  the repair round. Figures gain `scatter` and `histogram`.
- **`causal = false`**: no `identification_spec.json` is required or asked for, and a regression need
  not implement one. Default: causal for regression results, not for every other kind.
- **Template-declared panel, weights and polish.** The review step scores the reviewers the template's
  `aggregate` step names (until now the six economics reviewers ran whatever the template said) with
  `review_weights` in place of the default weights; the mechanism rule applies only to a panel with a
  mechanism reviewer. Two discipline-neutral reviewers can join a panel: `methods_reviewer` (skill
  `review/methods-review`) and `plausibility_reviewer` (`review/domain-plausibility`). Polish runs only
  the polish specialists the template's `polish` step lists.
- **Persona and data skills from the template.** `base_skill = "base/researcher"` replaces
  `base/economist` wherever a specialist reads it (`base/researcher` now speaks of the study's own
  field); `data_skills = [...]` replaces the blockchain, DeFi and Allium skills of the data architect
  and analyst (the general connector skills stay).
- What a template changes is recorded in the `template_components` event (`core`) and shown to every
  specialist and the strategist as a short template block; the declared skills in a study's
  description follow the same merge. Templates that set none of this run exactly as before (tests
  hold every shipped template to the registry's skills, panel and polish).
- Tests: a descriptive template replays end to end on a synthetic exoplanet radius–period dataset
  (`tests/fixtures/replay/exoplanet`, `tests/test_neutral_core_replay.py`): no regression or
  identification is asked for, the estimation gate passes on the descriptive contract, the number
  check traces the records tables, the five-reviewer panel scores with its weights, and the export
  verifies with `e2er verify` (all 36 table cells at the precision shown). Contract tests per kind in `tests/test_result_kinds.py`, records
  tables and the new figures in `tests/test_records_tables.py`.

### Template: systematic review and meta-analysis
- **`systematic-review`** (`pipelines/systematic-review.toml`): a systematic review with a random-effects
  meta-analysis, following the PRISMA 2020 statement (Page et al. 2021). Four specialists of its own:
  the protocol designer (`review_protocol.json`: the question in PICO, PECO or another form,
  eligibility criteria with ids, databases, Boolean searches, outcome, effect measure, synthesis
  settings, risk-of-bias tool with its domains and levels), the study screener, the study extractor
  and the review writer. Everything counted is code (`src/modules/metaanalysis`), run as checks of the
  template (`src/core/pipeline/meta_checks.py`). Stops for the protocol (with the search counts) and
  the screening sample; optional pre-registration of the protocol and an optional review of the
  extraction table.
  - **Search** (`meta_search`): every search of the protocol on OpenAlex through the field map's client
    (polite pool, optional key, cache, request ceiling; a search above `max_records` is refused after
    one request), Crossref as an option (its most relevant records only, said in the log), duplicates
    removed by DOI and then by title and year. `records.json`, `search_log.json` with each query as
    sent, the count reported and the time, `search_counts.md`, and a load per search in
    `data_sources.json`.
  - **Screening check** (`meta_screening`): every record decided once, every exclusion with a criterion
    the protocol defines and a reason; `screening_sample.md` for the researcher (the unsure records, the
    inclusions, a seeded sample of exclusions). Also the screener's output contract.
  - **Full texts** (`meta_fulltext`): a PDF the researcher saves in `data/fulltext/`, else the
    open-access PDF OpenAlex lists, else the open-access resolvers; text page by page into
    `fulltext/<id>.txt`; `fulltext_log.json` with the origin and SHA-256, or why no full text is
    available. Full texts are not exported.
  - **Every extracted number traced** (`meta_extraction`): the extractor gives, for each number, the
    page and a verbatim quote; the check finds the quote on that page (elsewhere in the text with a
    note, across a page break, or in the abstract for a study read from its abstract) and the number in
    the quote. Exclusions on the full text need a criterion and a reason, every included study its risk
    of bias per protocol domain. The trace is also the extractor's output contract, so the extractor is
    sent back with the untraced numbers before the run stops.
  - **Synthesis** (`meta_synthesis`): `run_estimation.py` is e2er's own code (numpy and scipy, nothing
    from e2er imported, so `e2er reproduce` reruns it): log ratios, Fisher's z, Hedges' g from group
    statistics, SE from a CI; random effects with tau^2 by REML or DerSimonian-Laird; z, p, CI, Q, I^2,
    H^2, the prediction interval (t on k - 2 df), the common-effect estimate, Egger's test and trim and
    fill (L0) with a low-power flag below ten studies, leave-one-out. On the BCG vaccine trials it gives
    metafor's published REML, DL and trim-and-fill results to four decimals. Below the protocol's
    `min_studies` the review is a narrative synthesis without a pooled estimate. A protocol changed after
    the pre-registration stops the synthesis.
  - **Results kind `metaanalysis`** (`result_kinds.py`, schema skill `data/metaanalysis-results-schema`):
    the pooled estimate and tau^2 recomputed from the studies, flow counts that add up, p from z and
    from Egger's t, a prediction interval containing the CI, weights adding to 100, a narrative synthesis
    exactly when there are too few studies. `e2er verify` checks it, and as its method checks that the
    effects are the extraction's, every extracted number is printed in its quote and the run traced all
    of them.
  - **Figures** `forest`, `funnel` and `prisma` (`src/core/renderer/meta_figures.py`) and the tables
    `meta_flow`, `meta_studies` and `meta_results`, every cell a value of the results; the methods'
    and the included studies' references are added to `literature.bib`. The writer's contract requires
    the tables and figures and a citation of every included study.
- **Live run** (Claude Code, Sonnet; 2026-10-11): grit and grades in university students, open-access
  studies in OpenAlex 2009-2025. 175 records, 1 duplicate, 174 screened (5 included, 92 unsure, 77
  excluded), 97 sought, 40 open-access PDFs read, 16 studies pooled: r = 0.18 (95% CI 0.05 to 0.29),
  I^2 = 97%, prediction interval -0.34 to 0.61; Egger p = 0.57. The extraction check stopped the run
  on three numbers that were not printed where the extractor said: two sample sizes it had summed from
  group sizes (145 + 107; 111 + 101 + 86 + 45) and one quote from the wrong sentence; the researcher
  corrected one quote and excluded the study whose total sample size is not printed. Every one of the 48
  remaining numbers traced; reading the correlation-matrix rows against their table headers confirmed
  the right cells. Not caught by any check and named by the data reviewer: a study year taken as 2024
  where the PDF says 2025. Two included studies report Spearman's rho and one a within-person
  correlation from weekly data, which the protocol's Pearson criterion does not cover; the skill now
  says so. `e2er verify` passed, `e2er reproduce` reproduced all 422 values, and the study is published
  as a demonstration on a local e2er.org. Fixed from the run: a record with neither an abstract nor an
  open-access PDF can be excluded with `source_text: "title"` (before, no value was valid and the
  extractor failed its contract three times); OpenAlex addresses that are landing pages fall back to the
  open-access resolvers; failed downloads are not repeated at every start; the full-text step reads up
  to 150 records (60 would have left 37 of the 97 unread); the skill tells the extractor never to choose
  between estimates by size.
- The review writer's draft passes the phrase check of the other writers (the live run's draft, written
  before the check existed, has 22 of the constructions; the writer would now be sent back with them).
- Method skill `methods/meta-analysis`; method sources credited in the template and `credits.json`
  (DOIs checked on Crossref): Page et al. (2021), DerSimonian and Laird (1986), Viechtbauer (2005),
  Higgins and Thompson (2002), Riley, Higgins and Deeks (2011), Egger et al. (1997), Duval and Tweedie
  (2000), Viechtbauer (2010).
- Tests: unit tests for the statistics (metafor's published values, an independent OLS fit for
  Egger's test), the protocol, the search, every refusal of the screening and extraction checks, the
  narrative synthesis, the results contract, the pre-registration, the figures and the export check; a
  replay of a synthetic review (recorded OpenAlex pages and PDFs) end to end through the three stops,
  publish, verify (and a tampered extraction that verify catches) and reproduce, and a replay in which
  an extracted number is not in its quote, which stops the run before anything is pooled until the
  researcher corrects it.

### Templates: descriptive data study, time series and forecasting
- **`descriptive-study`** (`pipelines/descriptive-study.toml`, until now a test fixture): a description
  of a sample for any field, on the discipline-neutral core (descriptive results, no causal claim, the
  researcher persona, its own panel of methods, data, plausibility, literature and writing reviewers,
  polish of numbers and references). Stops for the design review and the draft review.
  - **Data check** (`data_quality`, after the data analyst, before the analysis;
    `src/core/pipeline/data_quality.py`): every table the data dictionary declares, read from data.db.
    It stops the run on a numeric column without a `unit`, rows that repeat on the declared `key` (or as
    whole rows), a declared column that misses more than 5% of its values without a `missing` reason, a
    `coverage` the data do not span, or a declared table that is missing or empty. It writes
    `data_quality.md` and `data_quality.json`; the number check reads the latter.
  - **Figure check** (`figure_data`, after the analysis): every figure names its `source` (a data.db
    table with columns and an optional simple condition, or a list in a results file) and is re-read from
    it at the precision it states; a figure without a source, or with values that are not the data, stops
    the run (`figure_check.json`).
- **`time-series-forecasting`** (`pipelines/time-series-forecasting.toml`): a series, its trend and
  seasonality, models and forecasts. A new specialist, the **forecast designer**, writes the setup
  (`forecast_design.json`: series, hold-out, horizon, interval level, baselines, candidate models,
  stationarity and trend diagnostics) after the data are loaded.
  - **Hold-out frozen before fitting** (`forecast_design`; `src/core/pipeline/forecast_checks.py`): the
    hold-out must be the last periods with a value in each, at least 24 periods must remain to fit on,
    and a baseline (naive, seasonal naive, mean or drift), a candidate, a stationarity and a trend test
    must be declared. It writes `holdout_freeze.json` with the SHA-256 of the setup and of the hold-out
    values, refuses a setup written after a model was fitted, and refuses a change once results exist.
  - **Forecast check** (`forecast_evaluation`, after the analysis): diagnostics and models on training
    periods only (a model fitted into the hold-out is reported as leakage and stops the run), every
    declared model evaluated on exactly the hold-out with all its predictions, RMSE, MAE and interval
    coverage recomputed from the predictions and data.db, and a forecast beyond the data with the
    declared horizon and interval level. `forecast_check.json` holds the recomputed errors and each
    model's RMSE relative to the best baseline.
  - **Optional pre-registration** of the setup: a template step can now be `optional = true` (researcher
    and preregister steps only); it runs when the researcher chooses it on New study or with
    `e2er run --review-at preregister`. The forecast setup is a plan file of the pre-registration.
- **Method skills** `methods/descriptive-analysis` (sample definition, the dictionary fields the data
  check reads, quantile definitions, bins, rank correlation, figures from saved data) and
  `methods/time-series-forecasting` (the setup, decomposition, KPSS/ADF and Mann–Kendall with Sen's
  slope on training periods, ETS/ARIMA/regression, rolling-origin cross-validation, leakage, honest
  intervals with their hold-out coverage, MASE, Diebold–Mariano). The figure-spec skill documents
  `source`; time-series figures can shade an interval (`lower`, `upper`) and keep about twelve period
  labels on the axis.
- **Method sources are credited** in each template's `[[credit]]` and in `credits.json` (relation
  `cites`, DOIs checked on Crossref): for the descriptive template Emerson and Colditz (1983), Freedman
  and Diaconis (1981), Hyndman and Fan (1996), Spearman (1904), Little and Rubin (2019), Wickham (2014);
  for the time-series template Box, Jenkins and Reinsel (2008), Hyndman and Athanasopoulos (FPP3, 2021),
  Hyndman and Khandakar (2008), Hyndman and Koehler (2006), Tashman (2000), Diebold and Mariano (1995),
  Harvey, Leybourne and Newbold (1997), Dickey and Fuller (1979), Kwiatkowski et al. (1992), Mann (1945)
  and Sen (1968).
- The template list of New study, `e2er run --template` and the installed-package check now include
  `field-map` and the two new templates.
- **Tests**: the exoplanet replay runs the shipped descriptive template (both stops, the data and figure
  checks, publish, verify, reproduce); a new climate replay on NASA POWER monthly temperature at
  Frankfurt, 2001–2023 (recorded once through the connector) runs the time-series template end to end,
  with the optional pre-registration, and with an analysis that fits on the hold-out, which stops the run
  at the forecast check until the analysis is sent back; unit tests for every refusal of the four checks.

### Template: text analysis
- **`text-analysis`**: counts and models of the language of a corpus, from Project Gutenberg
  (`e2er-data gutenberg`) or the researcher's own texts (`.csv`/`.jsonl` with a text column, or `.txt`
  files read by the build script). No causal claim; the researcher persona; a panel of methods, data,
  plausibility (read as a scholar of the texts would), writing and technical reviewers; stops for the
  design review and the draft review. Method skill `methods/text-analysis`; results in the text contract.
- **Four checks** (`src/core/pipeline/text_checks.py`), each sending its specialist back once before it
  stops the run:
  - `corpus_design`, after the data architect: `corpus_design.json` states the question, the corpus and
    how its documents were selected and sampled, the metadata with their sources, the preprocessing
    (token pattern, lower-casing, stop words and lemmas as files with their sources, n-grams), the groups,
    the analyses and the corpus's sampling bias. Dictionaries and topic-model seeds are fixed here,
    before the analysis.
  - `corpus`, after the data analyst: every document with its source, licence and SHA-256; token counts
    and corpus statistics (documents, tokens, types, length distribution) recomputed with the recorded
    preprocessing; duplicate texts refused; metadata filled or their absence explained. The word lists
    are frozen with their SHA-256 (`corpus_check.json`).
  - `text_results`, after the analysis: every term count, group size, frequency per 10,000 tokens and
    dispersion recounted; keyness recomputed (log-likelihood G2, Dunning 1993 and Rayson and Garside
    2000, with the log ratio and its direction); adjacent collocations and PMI; dictionary and sentiment
    hits with the design's word list; topic models (LDA or NMF) with a recorded seed, a metric for at least
    two numbers of topics, runs under at least three seeds whose stability (mean best-match Jaccard of the
    top terms) e2er recomputes, top terms and example documents of the corpus per topic, shares adding
    up to 1; a figure drawn from the results of every diachronic, keyness and topic model; a statement of
    sampling bias.
  - `text_validation`, after a new specialist, the **text validator**, who judges every passage of the
    sample the analysis drew (with its seed) of each dictionary and sentiment measure: every passage must
    be in its document, every item judged with a reason for each wrong one, and the precision is
    recomputed. A study without such a measure has nothing to validate.
- `e2er verify` recounts the results and the validation on the exported corpus (`method checks`).
  The text kind's number check also reads `corpus_check.json` and `text_validation.json`. Export puts
  `corpus_design.json` in `design/`, `corpus_manifest.json` in `data/` and the checks' reports, the
  sample and the judgements in `results/`.
- The strategist is told which checks follow the analysis and which specialists to dispatch for them
  (it had been told "dispatch econometrics_specialist before econometrics_specialist" for the spatial
  template's results check).
- **scikit-learn** is a dependency now (topic models, vectorisers, English stop words for the analysis
  scripts; no model downloads).
- Method sources credited in the template and `credits.json`: Dunning 1993, Rayson and Garside 2000,
  Hardie's log ratio, Church and Hanks 1990, Blei, Ng and Jordan 2003, Lee and Seung 1999, Greene,
  O'Callaghan and Cunningham 2014, Grimmer and Stewart 2013, Gentzkow, Kelly and Taddy 2019 (DOIs checked
  on Crossref; the others by their pages).
- Tests: unit tests for every refusal of the four checks and the statistics; a replay of six works of
  short fiction (Project Gutenberg 41, 932, 11231, 43, 375, 1952, recorded once through the connector)
  end to end (both stops, the four checks, figures, number check, panel, publish, verify with the recount
  and a tampered export, reproduce); a dictionary widened after the design that stops at the results
  check until the analysis is sent back; a validator that leaves an item unjudged.

## [0.15.3] — 2026-10-11

### A subscription plan's usage limit pauses the run
- **Codex, Claude Code and Gemini: a used-up plan pauses the run instead of failing it.** On
  2026-10-11 (0.15.2, Codex with gpt-6-astra) a run failed with "All specialists failed in parallel
  batch: idea_developer: Codex failed (exit 1): You’ve hit your usage limit. Upgrade to Pro …". Nothing
  was broken: the ChatGPT plan's limit was used up. The CLI backends now recognise their plan-limit
  messages (Codex: "You’ve hit your usage limit", `usage_limit_reached`; Claude Code: "Claude AI usage
  limit reached|<time>", "Claude usage limit reached … reset at 2pm", "5-hour limit reached ∙ resets
  3pm", "You've hit your limit · resets …", weekly and Opus limits; Gemini: a used-up daily quota, not a
  per-minute rate limit) and raise `PlanLimitReachedError`, with the reset time when the CLI states one.
  No retry is spent on it (`src/modules/llm/plan_limit.py`).
- **The run pauses like at the spending limit.** The runner records `paused_plan_limit` (backend,
  reset time, the interrupted specialist, the status sentence), saves its state and sets the study to
  paused with "Your ChatGPT plan's usage limit is reached (resets at 14:30). The run is paused; press
  Resume when the limit has reset." (Claude: "Your Claude plan's usage limit …"). No step is marked
  failed and the interrupted specialist's attempt does not count towards its three attempts or the
  circuit breaker. Resume picks up at the first step that has not finished and runs the interrupted
  specialist again; in the first step, work orders that finished are kept, as after a spending-limit
  pause.
- **Parallel batches finish first.** When one specialist of a parallel batch hits the limit, the
  others run to their end (the ones that succeed keep their output; they usually hit the same limit at
  their next call), then the run pauses. No specialist is stopped half-way.
- **Where it shows.** The run page shows the whole sentence with the Resume button and the event
  "Paused: the plan's usage limit was reached"; the studies list and the study page show the sentence
  and a Resume button for such a run; `e2er status` prints the sentence and `e2er resume <id>`; the
  dossier records the `paused_plan_limit` event among the run's events.

## [0.15.2] — 2026-10-11

### Stale tables are set aside; a draft that cites nothing is caught
- **The renderer sets aside tables the spec no longer declares.** In the 2026-10-10 Haiku run
  section_writer cut `table_spec.json` from four tables to two; the two dropped tables (`---` in every
  cell) stayed in `tables/` and shipped in the export's `paper/tables/`. A table an earlier render
  wrote and the current spec drops now moves to the hidden `.history/tables/` (listed as `set_aside`
  in `table_render_report.json`). Tables the renderer did not write (field-map tables, `\input` stubs)
  stay. The export also leaves out of `paper/tables/` any table that is neither rendered nor included
  by the paper, which covers workspaces from before this change.
- **A draft for a study with references must cite them.** The same run's draft cited none of the 21
  entries of `literature.bib`, and the citation check, which checks the cites a draft makes, skipped
  itself. The output contract of the paper drafter and of the field review writer now fails such a
  draft with "The draft cites no work; cite the papers in literature.bib where they support the text";
  after the last attempt the run stops at the contract as usual. The study's references are the
  entries of `literature.bib` and `user_refs.bib`, or the papers chosen for it.
- **The citation check says why it checked nothing**: "no references: the draft cites no work and the
  study has no bibliography", or "the draft cites none of the N work(s) in the study's bibliography",
  in `citation_integrity.json` and the run's gate record. `e2er verify` fails a paper that cites none
  of the works in its `refs.bib`, and says "no references" when the bundle has no bibliography.

### The number check stops when no table cell was checked
- **A paper with rendered results tables and no traced table cell no longer passes the number
  check.** In the 2026-10-10 E2E-01 run on Claude Haiku the renderer wrote two tables from the results
  files, the draft `\input`-ed neither, and the number check, which reads the draft, compared 0 table
  cells, checked the prose numbers and reported a pass. The run went on to the reviewers and the export,
  and `e2er verify` then failed the export (no table_cell edges, 0 cells traced). The tables traced in
  full once included (25 of 25 cells), so the tracing itself was not at fault.
- **Under governance `full` the run now stops at the number check** and says why in plain words: which
  rendered tables the paper leaves out, and the `\input` lines it needs. Edit the draft, give an
  instruction or send back the drafter or the table layout, and the check runs again; or approve to
  continue without the table check, recorded in the dossier as your decision (`e2er verify` still
  fails such a paper). Under `contracts` and `off` the finding is recorded in `number_check.json` and
  the run notes, and the run continues.
- **The drafter's output contract checks that every table declared in `table_spec.json` is
  `\input` in the draft**, so a drafter that leaves its tables out gets the missing `\input` lines as
  feedback and another attempt before the run reaches the number check.
- `number_verification.json` records the rendered tables, those the draft leaves out, and
  `tables_untraced` with its reason. `e2er verify` gives the same reason when it fails the numbers check
  for 0 traced cells.

### Studies reproduce on their own
- **`e2er reproduce` gives the study's code e2er's read-only data access.** `e2er-data query sql` and
  `e2er-data query tables` now work inside a rerun and read the run folder's `data.db`. Before, a
  script that checked an aggregate with `e2er-data query sql` stopped with exit 2 ("paper_id
  missing"): the E2E-01 run with Codex on 0.15.1 passed `e2er verify` and failed `e2er reproduce`
  for this reason. The steps still get no API key and no e2er setting, and a rerun's queries are not
  written to e2er's own database.
- **No web outside the data step.** Only the step that loads inputs again (`get_data.py`) may use the
  network and e2er-data's loaders. In every other step a connection to another machine fails with a
  plain message, and `e2er-data yfinance|fred|gmd|allium …` exits 5 with one; the report says which
  step tried to reach what. `e2er reproduce --allow-network` lets the steps through and names the
  sites they read in the report and the verdict. The guard sees connections made by Python (a small
  module in the rerun's environment); a program started from the script (`curl`) is caught by the
  estimation contract below.
- **The estimation script is checked for web access at the estimation step.** The runner reads the
  scripts that write `estimation_results.json` (and the local modules they import) without running
  them, and flags network libraries (requests, httpx, urllib.request, yfinance, pandas_datareader,
  fredapi, …), URLs read with pandas, `curl`/`wget` in a subprocess and e2er tools other than
  `e2er-data query`. A finding is an output-contract failure for the econometrics specialist, with
  the file and line and the message "The estimation script must read its data from data.db or files
  in data/; load web data in the data step", so the specialist fixes it within its attempts; after
  the last attempt the run stops as for any contract failure. The econometrics and data skills say
  the same. The FOMC replay fixture's estimation script lost its pandas-datareader fallback, which
  this check flags.
- **The reproduce report always lists the inputs**, also when a step fails or the environment cannot
  be made, so the reader sees what the rerun had; a recipe without inputs says so.
- On the E2E-01 Codex export, the rerun now runs to the end with `--allow-network`: every estimate and
  all 15 tables are identical; the 276 differing values are the provenance of the 101 statements the
  script reads from federalreserve.gov while it estimates (retrieval times, page hashes, 16 URLs).
  Without `--allow-network` it stops at that fetch and says so.

### Gemini: not tested, API key only
- **Full runs are tested on Claude (Claude Code) and OpenAI (Codex CLI with a ChatGPT plan).** Google
  ended Gemini CLI sign-in for individual accounts in October 2026: `gemini` 0.63.0 answers "This
  client is no longer supported for Gemini Code Assist for individuals" and points to Antigravity. The
  Gemini backend therefore needs a Gemini API key (`GEMINI_API_KEY`) and is not tested. The code stays.
- **The setup page lists Gemini under "Other providers (not tested)"**, with a field for the Gemini
  API key and no sign-in command. Its note no longer says Gemini runs on a subscription. A Gemini key
  saved there is written to `.env` as `GEMINI_API_KEY`.
- **`e2er doctor` and `e2er init`.** A Gemini sign-in file no longer counts as ready; only
  `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) does, from the environment or `.env`. The check names the
  backend as not tested. `e2er init` offers Gemini last, as "Other provider, not tested", and checks
  for the key.
- **`e2er run-matrix` leaves Gemini out of its default backends.** It runs only when `--backends`
  names it.
- **Spending limit texts.** For a Gemini study, the new-study form and the run page say that Google
  bills the Gemini API key and e2er does not count the cost; they no longer call it a subscription.
- README, docs/BACKENDS.md and the command help say the same.

### OpenRouter with an open model, run live
- **First live study on OpenRouter with an open model (DeepSeek V4 Pro).** The OpenRouter backend had
  only been tested with mocks. A whole single-pass study now runs on it; what the live run showed is
  fixed below.
- **Costs are what OpenRouter bills (fix).** The cost table had no entry for open models, so every
  DeepSeek call was priced at the $3/$15-per-million guess, 10 to 40 times the bill, and the spending
  limit would have stopped a study that had spent cents. e2er now records the cost OpenRouter reports
  for each call (`usage.cost`), counts cached prompt tokens as cache reads, and for a call without a
  reported cost uses OpenRouter's published price list, read at the start of a run and kept for a day
  in `~/.e2er/cache/openrouter-models.json` (the fixed table, now with DeepSeek, when offline). On the
  live run e2er's recorded cost and OpenRouter's account differed by under a cent.
- **Calls go to the provider that is cheapest for a study (new setting `OPENROUTER_PROVIDER_SORT`,
  default `price`).** A model on OpenRouter is served by several providers at very different prices.
  Left to OpenRouter's balancing, DeepSeek calls went to a provider charging about 8 times the cheapest;
  OpenRouter's own "cheapest" ranks by fresh input and picked one that charges 9 times more for cached
  input and 10 times more for output, and a study's calls are mostly cached input. e2er now reads the
  model's providers from OpenRouter's public list (kept a day), ranks them by what a study's mix of
  calls costs there, and asks for them in that order with fallback. `throughput`, `latency` or empty
  (OpenRouter's balancing) are the other choices.
- **The spending limit holds inside a specialist (fix).** It was checked between specialists only;
  one specialist ran on while the study passed its $3 limit ($3.48 billed). The Anthropic and
  OpenRouter backends now check before every call, counting the specialists still running.
- **Stopping a run keeps the cost of the specialist that was working (fix).** Its calls were billed
  but never recorded, so a stopped study showed $2.85 where OpenRouter had billed $3.48. The Anthropic
  and OpenRouter backends now record what a loop used when its run is stopped.
- **Setup offers every OpenRouter model that can use tools, with its price** ("DeepSeek V4 Pro (open
  model, low price): $0.23 in / $0.46 out per million tokens"), suggestions first; offline, the fixed
  suggestions. A model already chosen stays selected, also in e2er's spelling (`claude-sonnet-4-5` for
  OpenRouter's `claude-sonnet-4.5`).
- **A reviewer that answers instead of writing its file (fix).** DeepSeek returned a whole review as
  its reply without calling `write_file`, and the retry cost a new review. On the Anthropic and
  OpenRouter backends a missing Markdown output is now filled with the final answer (300 characters or
  more) and the log says so; JSON, LaTeX and scripts never are.
- **Source notes no longer print in the paper, and drafts no longer write their own tables (fix).** The
  `cite-numbers-by-source` skill, loaded by the drafter, section writer, abstract writer and revisor,
  taught HTML comments (`<!-- src: ... -->`) for source notes, which LaTeX printed into the PDF, and
  showed a results table written in the draft, which the drafter's contract rejects: every live run on
  DeepSeek lost its first draft to "inline tabular", as a Claude Code run had on 2026-09-11. The skill
  now teaches `% src:` notes on a line of their own and `\input{tables/<name>.tex}` for tables;
  compiling removes any HTML comment from `paper_draft.tex` and `abstract.tex`, and the number check
  reads neither kind of note as a claim.
- **The number check skips LaTeX comments in tables (fix).** DeepSeek annotated each table row with a
  `% src:` comment naming the JSON keys (`pre_tightening_2015_2021`); read as cells they gave 15021 and
  22023, and `e2er verify` failed the exported study.
- **The number check reads `$-$0.93` as -0.93 and "2015--Feb 2022" as a period (fix).** A table with a
  minus typeset in math had its minimum of -0.93 read as 0.93, and the 2015 of a year-to-month span read
  as a value; both failed `e2er verify` on numbers that were right.
- **A call that stalls is asked again after two minutes, not ten (fix).** Each of the three live studies
  lost 10 to 11 minutes to one OpenRouter call that never answered and ran into the SDK's 600-second
  timeout. Calls are now streamed: one that sends nothing for 120 seconds (240 before its first data)
  is dropped and asked again, as is one whose provider fails mid-answer.
- **Smaller fixes in the OpenRouter loop:** a response with no answer (an upstream provider failed) is
  retried twice; tool arguments that are not valid JSON go back to the model as an error instead of
  running the tool with no arguments; empty arguments and arguments in a code fence are accepted.

## [0.15.1] — 2026-10-10

### Iterative mode, run end to end
- **The iterative mode now runs at the replay level, from the question to the finished study.** A new
  replay scenario (`tests/fixtures/replay/fomc-iterative`, on top of the FOMC one) scripts two rounds
  of improvement, a ceiling check that asks for another round and then for a change of approach, a
  self-critique with one serious finding, the polish notes and their correction, the review panel and the revision. Before,
  the replay answered "nothing further" to every round, so the rounds, the ceiling check, the change
  of approach and the self-critique's corrections had never run on the current engine. The replay
  backend takes per-round answers (`iterations`, `ceiling_checks`, `self_attack`) and per-call
  recordings (`calls`) for a specialist that runs more than once.
- **Each round is recorded (fix).** The run's log showed the specialists of the rounds one after
  another, with no sign of where a round began, what the ceiling check decided or which step was the
  change of approach. The runner now records each round (`improvement_round`), the ceiling check after
  it (`ceiling_check`: another round, a change of approach, ready for review; a second change of
  approach is refused and recorded as such), the change of approach (`pivot`), the strategist ending
  the rounds (`improvement_stopped`) and the self-critique (`self_critique`: findings, serious ones,
  corrections made).
- **The run page shows "Rounds of improvement"**: each round with its specialists, the ceiling check
  after it and the change of approach in plain words; the step says "2 rounds, then a change of
  approach", and the self-critique step its findings and corrections.
- **The dossier lists the rounds** (`run.rounds`: each round's specialists with their names, the
  ceiling check's decision and reason, the change of approach), and every step of a round says which
  round it belongs to (`round`, `pivot`). A run without rounds adds nothing, so its dossier (and its
  id) is unchanged.
- **The self-critique's corrections are kept (fix).** They were written to `paper_draft.tex.edits.json`
  and `paper_draft.tex.applied.diff`, which the revision after the review panel writes again: the
  export kept only the revision's edits, and nothing showed what the self-critique changed in the
  draft. They are now kept in `self_attack_corrections.json` (findings, edits, diff), exported with
  the reviews.
- **A change of approach runs under the same rules as a round (fix).** Its work orders went straight to the
  specialists, past the guard against rewriting the whole draft after round 1 and past the circuit breaker.
  They now run like a round's: a pivot that would rewrite the whole draft (paper drafter, revisor) is not run,
  and the record and the run page say so in a sentence; a specialist that has failed its attempts stops the
  run as in a round, and the pivot's failures count.
- **The polish notes change the paper or say why not (fix).** The notes (`polish_*.md`) were exported and read
  by no later step. Now they go to the targeted corrections, as the self-critique's findings do: the patch
  revisor edits the draft where a note asks for it, or writes no edit. The number check guards it: corrections
  that make more table or text numbers differ from the results are undone. What became of the notes is in
  `polish_corrections.json` (exported with the reviews), the `polish_applied` event and the run page
  ("Polish: 2 notes; 1 change made in the draft").
- **A ceiling verdict other than the three no longer fails the run (fix).** "stop", "Continue" or no
  JSON at all failed the check's model and with it the whole run; it is now read as "ready for
  review" (case and spaces ignored).

## [0.15.0] — 2026-10-10

### Choose the data and papers a study uses
- **New study lists your data files and papers.** The files of the data folder (name, type, size;
  search; select all or none) and the papers of the literature folder, your .bib files and the
  Library (title, authors, year). The study uses what you tick. Before, every study took everything
  in both folders and the page offered no choice. Ticked at first: the data files and the papers of
  the literature folder and .bib files (what a study took before); the Library's papers are offered
  unticked.
- **Add files before the run starts.** "Add files" takes data files, "Add PDFs or a .bib file" takes
  papers; they are copied into the study and kept with it only. One list of data file types
  everywhere (.csv, .tsv, .jsonl, .parquet, .xlsx); any other file is refused in one sentence. A
  .txt is no longer staged as data.
- **Only the chosen files count.** They are staged into the study's `data/` folder and imported into
  its `data.db` (an added file is recorded in `data_sources.json` as added by the researcher); the
  planning check, the specialists' context and the list of available sources read only the study's
  own folder, never the live data folder. The choice is recorded in `.study_inputs.json` (left out of the exported folder: it names files on this computer).
- **The researcher's papers are in the bibliography (fix).** Entries of the .bib file, a local Zotero
  library and the Zotero web library were shown to the writers as citable but never written into
  `literature.bib`, so citing one failed the citation check (missing from the bibliography). Now
  every paper offered to the writers is written into `literature.bib` before the first step, with
  the key the prompt shows; a .bib entry keeps its own key and fields.
- **Web search in addition, marked.** The literature search for the research question runs beside
  your papers (before, a .bib or Zotero library switched it off without a word). Every entry says
  where it came from (`e2er_source = {researcher}` or `{web}`); none replaces one of yours.
  "Use only my papers" turns the search off and limits the Library's evidence to the chosen papers.
- **The run page shows "Data and papers"**: the chosen files, the tables the study reads with their
  rows and source, your papers and the papers found on the web. The finish page shows "What the
  study used": data used and every reference the paper cites, marked "from your papers" or "found
  on the web". The dossier lists the cited references with their source (`references`; a study
  exported before has none, so its dossier is unchanged).
- **Readable titles.** New study, the run page and the finish page show titles without braces, LaTeX,
  author footnote marks (∗ † ‡) or "Accepted Version" banners; a title that is a file name, a page
  header or a journal citation ("J Evol Econ (2013) 23:925–953") is replaced by its DOI record's
  title, else shown as "(title not readable)". The Library's papers are a folded group of their own,
  "Your Library (N)", with its own search, below the folder's papers and .bib entries.
- **Off-topic web hits stay out.** A search hit joins the bibliography only when it shares enough of
  the research question's content words: with an abstract, 2 in the title and a third (2 to 4) in title
  and abstract; title only, a fifth (2 to 3) (`is_relevant` in `modules/literature/discovery.py`). The
  live run's 53 hits for a mortgage question (solar bonds, the federal budget, …) all stay out; the study
  records what it left out in `literature/web_search.json`, and the run page says how many. The
  panel lists the web papers the draft cites first and folds the rest.
- **Library: Add papers.** The Library page takes PDFs or a folder and reads them in the background
  with the importer of `e2er library add`.
- **`e2er run --data FILE… --papers FILE… [--only-my-papers]`** does the same in a terminal (a
  folder stands for the files in it). Without them a study takes everything, as before.

### Replication, credit, commands and the field map
- **Fixed: an installed e2er could not run the specialists' commands.** Before 0.15.0 a pip or
  `uv tool install` installation had only `e2er`, `e2er-data` and `e2er-fieldmap`. `e2er-run`,
  `e2er-lit`, `e2er-check-tables` and `e2er-allium-query` existed only in a source checkout, while
  the specialists were told to use them. On an installed e2er, specialists on the CLI backends
  (Claude Code, Codex, Gemini) could therefore not run their own scripts while writing them, not
  search or record literature, and not check their table specs; the runner still ran the
  estimation script itself after the step. All six are now console commands of the package
  (`src/wrappers.py`; the `scripts/` files of a checkout call the same code). The wheel check
  installs the package with an empty home folder and runs each of them.
- **`e2er reproduce` for every study.** `e2er export` now writes `reproduce.json` from what the run
  recorded: the estimation script and every later script of the run that wrote
  `estimation_results.json`, in the order the run ran them (`e2er-run` and the runner now record
  every script run in the workspace; for older runs the order comes from file times, and the recipe
  says so); the files they read, laid out
  where they expect them, with data files as inputs (SHA-256 and source from `data_sources.json`);
  `code/requirements.txt` with the packages they import at the versions of the run's environment;
  the estimation results (and robustness results) to compare, with the tables rendered again; and
  `code/get_data.py`, which loads Yahoo Finance and GMD data again with `e2er-data` when the folder
  does not have them. The exported scripts name the run folder instead of the workspace's full
  path. The FOMC demonstration study reproduces with it: 162 of 162 values identical and both
  tables the same, in a new environment. A study without an estimation script or without results
  gets no recipe, and its README and `e2er reproduce` say why. `e2er-data yfinance` records the
  request (ticker, dates, interval) with each load, so the reload asks for the same rows.
- **Stata packages are refused before any model call.** The replication template's download step
  now refuses a package that has no R or Python file and whose code is in Stata (`.do`, `.ado`,
  `.dta`), MATLAB, Julia, SAS, SPSS, GAMS, EViews, Mathematica or Ox. The refusal names the files and
  stops the run before the planner reads the package, so nothing is spent.
- **Template credit in the dossier.** A run records its template's `[[credit]]` in the
  `template_components` event, and the dossier of a published run carries it as `credit`
  (`{"template": …, "entries": [...]}`, the entries as the template file wrote them). Dossiers of
  templates without credit are unchanged, and so are their ids.
- **Co-authors from the terminal.** `e2er publish --coauthor "Name|github=login|orcid=…|role=…"`
  (repeatable) lists co-authors after the publisher in `e2er.json`; each needs a GitHub login or an
  ORCID iD, so e2er.org can ask them to confirm the credit. A malformed entry is refused with a
  sentence that says what is missing.
- **Skill texts without internal names.** `synthesis/context-builder` and `writing/scoped-revision`
  name the specialists in words ("the paper drafter", "targeted corrections").
- **Every terminal command is in the README**: `e2er serve`, `skills sync` (and `install-skills`),
  `verify-citations`, `preregister deposit`, `whoami`, `logout`, `dossier push`, `skills installed`
  and `remove`, and the `library` commands `list`, `stats`, `topics list`, `topics remove`, `export`
  and `remove`. A test reads every command and subcommand from the code and fails when the README
  does not name it.
- **Field-map completeness stops calibrated.** The citation-network check now stops above 50% of
  papers without internal links (before 60%) and above 40% without references (before 25%). The
  values come from five boundaries (scientometrics, information systems, economics and two niches);
  the old 25% would have stopped the information-systems and economics literatures, whose main
  paths have 18 papers. The table is in the `synthesis/main-path-analysis` skill and in
  docs/templates.md.
- **Fixed: the number check read period labels as numbers.** A table with rows labelled `2004--06`,
  `2015--18` and `2022--23` (live run 2026-10-10, mortgage pass-through study) was read as 2004
  and -06, 2015 and -18, 2022 and -23; the run stopped at the number check on two of them and
  `e2er verify` failed six cells of a correct table. Spans of years (`2004-06`, `2007–2009`,
  `1998--02`), quarters and months (`2022Q3`, `Q3 2022`, `2004m6`), decades (`1990s`), fiscal years
  (`FY2019`) and month-and-year dates (`Jan 2020`) are now labels, in table cells and in the text,
  for the run's check and for `e2er verify` alike. A dash right after a digit is a range dash, not a
  minus sign: the upper bound of `0.12--0.15` is 0.15. Negative values, standard errors in
  parentheses and bare years are read as before.

## [0.14.1] — 2026-10-08

- 0.14.1 is 0.14.0 as it was meant to ship. The tag v0.14.0 exists, but its release run stopped at a test that only read the [Unreleased] part of this file, so 0.14.0 was never published on PyPI. That test now reads the whole file.

## [0.14.0] — 2026-10-08

The local dashboard works end to end on 127.0.0.1, and every page reads plainly.

### Studies folder
- **One home for studies.** Setup asks once for a studies folder (default `~/e2er-studies`) and
  remembers it in `~/.e2er/settings.json`. `e2er` started from any folder uses it: its `.env`, its
  studies (`workspaces/`) and its exports (`exports/`). A folder with its own `.env` still works as a
  project of its own, exactly as before; Setup offers to make it the studies folder. Studies made
  before keep working from anywhere (the database records their folders). The foot of every page
  says which folder is in use.
- **Readable folder names.** A new run's folder is named after the date and the title
  (`2026-10-08-fomc-and-bank-stocks`); the run's id is in its `manifest.json`. The AI providers'
  commands get the folder in `E2ER_WORKSPACE`.
- **Exports never land in the data folder.** Without `OUTPUT_DIR` they go to `exports/` in the
  studies folder (before: `e2er_papers/` inside the data folder).

### Fixed
- **Publishing from the browser no longer hangs.** With public data and a data source's terms box
  unticked, the server asked `[y/N]` on its own terminal. The server never asks; the finish page
  says next to each unticked box what is missing.
- **A tab left open across a restart keeps working.** The session secret is made once per computer
  (`~/.e2er/session-secret`, mode 600) and the cookie lasts a year; a `localhost` page is sent to
  `127.0.0.1`, so one tab never holds two sessions. The session file a second `e2er` reads is written
  only once this server has the port.
- **No silent failures.** A wrong address, a refused form or an error shows a page with one plain
  sentence and "Back to your studies"; the API keeps answering JSON. A button or the live panel that
  cannot reach e2er shows a notice saying so.
- **The Zenodo key saved under Settings is used** for deposits (it was read from the environment
  only). Setup has a field for it, and one for the GitHub login used as owner when publishing.
- **"Also stop for you after these steps" lists the chosen template's own steps** (it showed the
  empirical steps for every template, and the replication steps were refused).
- **"Open it there"** for a run in another e2er says how to open that dashboard signed in.

### Plain pages
- One set of names for steps, specialists, templates, actions, events, checks and statuses
  (`src/core/labels.py`; a template can name itself with `title` and its steps with `label`). Ids
  appear only under "Technical details".
- The stop page leads with the decision: why the run stopped, the table of differences, the
  button; then send back, instruction, and the files, folded and readable, with "Edit this file".
  A stop you asked for lists the files the step wrote.
- One vocabulary: study, run, step, specialist, stopped for you, spending limit, files, "Download
  all files" (every file of the run, without its hidden ones).
- The publish result links to the study and its dossier; what `e2er publish` printed is folded.
- Setup shows the exact command that signs in Claude Code, Codex or Gemini, with a copy button
  (the full path for the Codex inside the ChatGPT app).
- Subscription providers show "No spending limit" in place of a $0 meter; one default limit.
- Earlier versions of rewritten outputs go to the hidden `.history/` folder (before:
  `<file>.previous` next to the output); backups, lock files and `.previous` files are never
  exported.
- `/docs` names e2er and its version; styles for the Library, Skills and Workflow pages, the status
  colours and the study page.

### Mapping a research field

- **New template `field-map`: map a research field by main path analysis.** A specialist proposes
  the boundary (search terms with the topic's older names, a journal set, years, and two to six
  alternative boundaries); the researcher approves it with the paper counts. Code retrieves the
  papers from OpenAlex (paged, cached in the study, with a request ceiling, `OPENALEX_API_KEY` as
  a bearer token when set; every load recorded in `data_sources.json` as OpenAlex, CC0), builds
  the network of citations inside the boundary with a completeness report (papers without
  internal links or references, short reference lists, duplicates, notices, broken cycles),
  computes search path count weights (exact integers), the global and local main paths and the
  key routes, and repeats this on the alternative boundaries to show which papers are on every
  main path. A specialist names lanes as questions; the researcher approves them; code draws the
  map by year and lane and writes the reading list, Pajek, GEXF, VOSviewer and CSV exports, two
  LaTeX tables and `field_map_results.json`. A specialist drafts a short field review, and the
  number check and the citation check run on it as steps of their own. Nothing is estimated: the
  template has no estimation gate and no econometrics step.
- The workflow follows Michal Hron's article "Map a research field with Claude: main path
  analysis, step by step" (LinkedIn Pulse, 8 October 2026,
  https://www.linkedin.com/pulse/map-research-field-claude-main-path-analysis-step-michal-hron-jm2ge/,
  shared by Björn Hanneke); this implementation is independent and uses OpenAlex. Adopted: the
  six-step workflow and the pitfalls it lists. e2er's own: the code, the OpenAlex retrieval, the
  cycle handling, the exports, the template's steps and stops, and the number-checked review.
  The methods: Hummon and Doreian (1989), Batagelj (2003), Liu and Lu (2012).
- **New skill `synthesis/main-path-analysis`**: the method step by step, the choices and what they
  change, the pitfalls, how to read the map, and the sources.
- **New specialists** `field_boundary_designer`, `field_lane_mapper` and `field_review_writer`, and
  the command `e2er-fieldmap` (count, sources, boundary, network, mainpath, robustness, papers,
  map, export, all), allow-listed for those three.
- **Templates can credit the work they are based on** in `[[credit]]` tables (creator, role,
  relation, title, address, publication and access dates, where it was found), checked when the
  template loads. `credits.json` lists the credit of e2er's own parts for the catalogue of
  e2er.org.
- The checks `numbers` and `citations` can run as steps of their own in a template without a
  review step.

## [0.13.9] — 2026-10-07

- **A review run again is scored from its own files.** The reviewers now rewrite their files whole:
  before a reviewer runs again (after a deep revision, or a rerun from the review step) its earlier
  review is moved to `<file>.previous`, and only each reviewer's latest reply can stand in for a
  missing file. Before, a reviewer that wrote nothing in the second round was scored from the
  first round's file, and the "no reviewer produced a score" check could not fire.
- **The deep revision survives a stop.** Its round and whether its research or its re-review is
  under way are kept in the run's state file. A resume after a stop inside the re-review (the
  number check, say) runs the review again and decides; it no longer repeats the whole deep
  revision. A finished deep revision is not repeated on a resume. `e2er rerun` from the revision
  step or earlier allows one again.
- **Approving output that failed its contract works in every phase.** In the revision, an
  iteration or a pivot, the approved specialist is not run again when the phase is planned anew
  on resume; its output stands (each approval is used once and lapses when its phase ends). A
  second contract stop while the first is being settled keeps the researcher step to come back to.
- **`e2er rerun` withdraws the approvals at the checks it runs again**: table numbers continued
  with at the number check (when the review step runs again), outputs kept as they are at a
  contract stop (in the steps that run again). `e2er verify` now accepts a table cell the
  researcher continued with only for the same cell, value and source key, as the run does
  (records written before the run kept a source key: cell and value).
- **`e2er reproduce` no longer reports "Reproduced" when the study's code wrote nothing.** The
  files the rerun is to write are taken out of the run folder before the steps run, so a published
  file is never compared with itself; a rerun that writes none of them is "Not reproduced". An
  input file that differs from the study's, or is missing, now counts against "Reproduced". The
  study's code and the installation of its packages run with a minimal environment (PATH, HOME,
  language, temporary folder, proxies and certificates, the installers' own settings without
  credentials): no API key, token or e2er setting reaches someone else's code.
- **The number check reads every data row of a table ruled with `\hline`.** The header rows are
  the rows above the first full rule that follows a row (a rule at the very top or one that only
  closes the table sets nothing apart); `\cmidrule` between header rows ends nothing. Before, a
  table with `\hline` rules and a `\midrule` lower down lost every data row above the `\midrule`.
- **`data_sources.json` keeps every load when data are loaded in parallel**: each write holds a
  lock and replaces the file whole, with the previous version as `.data_sources.json.bak`. A file
  that cannot be read is kept as `.data_sources.json.unreadable-<time>` and the record continues
  from the backup, instead of starting again empty (a lost GMD or Yahoo entry defeated their terms
  checks at publish).
- **The AI CLIs stop with everything they started.** Claude Code now runs in its own process group
  like Codex and Gemini, and on a timeout the whole group is killed. A cancelled run kills the CLI's
  process group on all three backends; before, the CLI (and a script it had started) ran on.
- **The model's shell gets no credentials it does not need.** The Claude Code, Codex and Gemini
  CLIs, and the shell commands they run, get the data and literature keys the e2er wrappers read
  (FRED, Allium, Semantic Scholar, Zotero, the database password) and the CLI's own sign-in only;
  other providers' API keys, GitHub, Zenodo and e2er.org tokens and anything else named like a
  credential are left out.
- **Starting, steering or stopping a run needs this server's session token.** `POST /api/papers`,
  resume, cancel, review, rerun, file uploads, query approvals, the new-study form and skill
  installation now need the session token `e2er` makes at start (the dashboard's cookie from the
  link `e2er` opens, or the `X-E2ER-Token` header the `e2er` commands send, read from
  `~/.e2er/session-<port>.json` or `E2ER_SESSION_TOKEN`), or the bearer `API_AUTH_TOKEN` when one
  is set. Before, they were open to any process on the computer, a run's own model shell included
  (which never gets the token). A request without it is refused with a note on how to open the
  dashboard from the link `e2er` printed.
- **Small fixes.** A data source is normalised before its other names are looked up
  ("Yahoo-Finance" is yfinance), and files in subfolders of the data folder count as available
  (`raw/x.csv`). `e2er compare` no longer counts "not reported" as a value runs agree on. Codex
  usage is the sum over its retries of a call.

## [0.13.8] — 2026-10-06

- **Claude Code runs made with 0.13.7 can be published again.** 0.13.7 recorded where the CLI is
  installed (`/Users/<name>/.local/bin/claude`) in the run's `backend_identity` event, the dossier
  copied the event as it was, and `e2er publish` refused every Claude Code run with "the dossier
  names a path on this machine". The Claude Code, Codex and Gemini backends now record the CLI's
  name and version only (`"cli": "claude"`). When the dossier is built, any path on this machine
  in what the run recorded (events, failed steps, the run's last error, researcher steps) is cut
  to its last part (`…/claude`, `…/data.csv`), so runs recorded before this release publish too.
  A record without such a path reads exactly as before, so dossiers already issued keep their
  address. A path anywhere else in the dossier (for example in `data/data_sources.json`) still
  stops publish.
- **The replay level can stand in for a named backend and model** (tests only, for the end-to-end
  story E2E-20: `e2er run-matrix` on two backends, then `e2er compare`). Under `tests/replay` the
  replayed backend now takes the backend and model the run names, so a run on `codex` with
  `--models codex=gpt-6-luna` records `codex` and `gpt-6-luna` in its `backend_identity` event, as
  a real Codex run does (before, the replay ignored both and recorded no model). Replay overrides
  under `"backends"` apply only to the runs on that backend, so two runs of one question can
  differ. `tests/fixtures/replay/fomc/two-backends.json` is the variation the story uses: the
  run on `claude_code` reports the declared treatment term with its standard error, the run on
  `codex` reports three means and names another outcome, as the live runs of 2026-10-05 did.

## [0.13.7] — 2026-10-06

- **Yahoo Finance data get the GMD's treatment.** Yahoo's terms allow personal use only, so data
  loaded with `e2er-data yfinance` are now a source with terms for `e2er publish`, beside the
  GMD. The description names Yahoo Finance and its terms (from the yfinance load record) on the
  data files that hold Yahoo data. If the data stay private, the reader note says "The data come
  from Yahoo Finance, whose terms allow personal use only, so readers on e2er.org see a link to
  the source instead of a request button." and there is no nudge to publish them. `--data public`
  needs `--accept-data-terms yfinance` or a yes to "Publish the Yahoo Finance data with the study
  although Yahoo's terms allow personal use only?". A Zenodo deposit of Yahoo data is refused
  before anything is written or sent: no Zenodo licence fits personal use only. Yahoo publishes
  no citation format, so publish asks for no BibTeX entry. The finish page says the same. A study
  with GMD and Yahoo data names both sources in one reader note, and a data file holding both
  (`data/data.db`) names both sources and their terms in the description. See `docs/publishing.md`.

- **The Codex backend works.** Validated live on a ChatGPT plan with codex-cli 0.155 (October
  2026): single calls, a whole study (`e2er run --demonstration`, empirical template) and the
  end-to-end story E2E-01. Before, `codex exec` ran read-only (no specialist could write a file),
  refused to start outside a git repository (every study folder), had no network for
  `e2er-data`/`e2er-lit`, could not write the run database, ran under the user's own Codex
  configuration (model, effort, plugins, MCP servers, notify hooks) and kept session history.
  It now runs with `-s workspace-write` (setting `CODEX_SANDBOX`), `--skip-git-repo-check`,
  network on, `--add-dir` for the run database's folder, the whole environment passed to shell
  commands, no login shell, and `--ignore-user-config --ignore-rules --ephemeral`; sign-in still
  comes from `~/.codex`. Output is read from `--json` events and `-o`: the final message, token
  usage (cached input recorded as cache reads) and the number of commands and file changes. A
  timeout stops the CLI and everything it started; a dropped connection or a server error is
  tried twice more, a used-up plan limit is not. Prompts name Codex's own tools (`apply_patch`),
  as they name Claude Code's.
- **Codex cannot be limited to e2er's commands, and the docs now say so.** Claude Code runs with
  an allowlist; Codex's command rules can only be set in the user's own `~/.codex`, which e2er
  does not change. Under Codex the model can run any shell command; writes stay inside the
  workspace, the run database's folder and the temporary folder. See `docs/BACKENDS.md`.
- **The CLI is found where it is.** `e2er doctor`, `e2er init` and the setup page used to look for
  `codex`/`gemini`/`claude` on PATH only, ignoring `CODEX_PATH` and the other path settings. They
  now use the configured path, and find the `codex` inside the ChatGPT desktop app when it is not
  on PATH. The setup page lists the models the signed-in ChatGPT plan offers.
- **A run records the model and CLI version that answered.** Without `CODEX_MODEL`, Codex runs
  were labelled `codex-cli-default`; e2er now passes the first model of the CLI's own list
  explicitly and records it. A new `backend_identity` event records backend, model, reasoning
  effort and CLI version per run. `e2er run --model` (and `run-matrix --models`) now reach the
  backend; before, the per-paper model only labelled the run while the backend ran its configured
  one.
- **Settings in the study's `.env` reach e2er's commands.** `e2er-data`, `e2er-lit` and the other
  wrappers run in the workspace (or the e2er checkout) and read their own folder's `.env`, so a
  FRED key or a study-local database set only in the study's `.env` never reached them. The CLI
  backends now pass on that `.env` and the run database, as an absolute path. Applies to Claude
  Code too.
- **Gemini backend: same fixes, not validated live.** Absolute workspace root, the wrappers on
  PATH, the run database, the tool name `replace`, JSON output with token counts and tool calls,
  a help probe that no longer pins old flags after a slow start, and a sign-in hint that names a
  command that exists. The Gemini CLI was not installed where this was tested.
- **`e2er run-matrix` takes `--template`, `--review-at`, `--demonstration` and `--models
  backend=model,...`.** Without `--backends` it runs the subscription CLIs that are ready on this
  computer, not all three. `matrix.json` and `e2er compare` name each run's model.
- `e2er-data fred series --help` crashed on a `%` in its help text; a model that asked for help
  got a traceback.
- **A deep revision round no longer fails the run when the revised analysis renames its result
  keys.** Seen live on Claude Code (Sonnet): the re-run econometrics specialist wrote
  `pooled_hac_lag_20` where `table_spec.json` still asked for `hac_lag_20`, and the render check
  failed the run before the section writer, which repairs `table_spec.json`, could run. The
  writer is now told which references no longer resolve, and the check comes after it.
- The CLI backends no longer pass e2er's own control settings (the dashboard session token, the
  API token and address, the e2er.org sign-in file) to the AI CLI; no e2er command a specialist
  runs needs them.
- `e2er run` said it started the server "on :8280" whatever port was configured.
- **`e2er` refuses to run inside a study's AI step.** Seen live on Codex: while a study was in
  its review step, a reviewer's shell started a second study on the same server with `e2er run`.
  Every AI CLI call now carries `E2ER_AI_STEP`, and `e2er` exits with a one-line message under it.
  The step's own commands (`e2er-data`, `e2er-lit`, `e2er-run`, `e2er-check-tables`) are separate
  and unaffected.
- **A re-done analysis that fails its output contract stops the run for the researcher.** In the
  deep revision round the data analyst and the econometrics specialist got one attempt and their
  contract result was ignored; seen live on Codex, the revised `estimation_results.json` lacked
  `n_clusters`, the study completed, and `e2er verify` failed the export. They now get the usual
  attempts and, if those fail, the same stop as everywhere else.
- Codex: "Selected model is at capacity" is retried.
- **`e2er compare` no longer sets different quantities against each other.** When a run does not
  report the treatment term its design declares, the first coefficient it reports is shown with a
  mark and a note, and it is left out of the dispersion of the estimate. A field one run reports
  and another does not now counts as a difference (it read as full agreement). Seen in the first
  live Claude Code (Sonnet) vs Codex comparison, where Codex reported three means and no
  `year_2023` term.

- **`e2er reproduce <study folder>` runs a study's code again and compares the results.** A
  study's `reproduce.json` names the pinned requirements, the steps, the inputs with their
  SHA-256 and the result files to compare. The code runs in a run folder of its own, inside a new
  virtual environment (uv when installed, else venv); the study folder is not changed. Every
  result value is compared with the published one (identical, the same at the published
  precision, small differences under the replication path's 10% tolerance, or different), the
  inputs with the study's own files, and the paper's tables are rendered again from the rerun's
  results. Exit code 0 reproduced, 1 differences, 2 could not run; `--json` writes the report.
  Export ships `reproduce.json`, `code/requirements.txt` and `code/get_data.py` when the workspace
  has them, and the README's "Reproduce" section now says what the folder supports: it promised
  `data/data.db` and `cd code && python run_estimation.py`, which could not run.

- **The showcase study can be run again.** `examples/showcase` is re-exported with this version:
  `code/get_data.py` reloads its 37 Yahoo Finance extracts with `e2er-data` (Yahoo's terms allow
  personal use only, so the extracts are not shipped; `data/data_sources.json` records the reload),
  `code/requirements.txt` pins numpy and pandas, and `reproduce.json` holds the SHA-256 of every
  original extract. With the study's own extracts the estimation and robustness results come out
  byte for byte; with today's Yahoo and Ken French data, `e2er reproduce examples/showcase` reports
  which values moved. The publish tests now copy `tests/fixtures/showcase_export`, the showcase as
  it was exported before publishing.

- **`.parquet` and `.xlsx` files in the data folder load.** The README offered both, but the
  packages pandas needs to read them (pyarrow, openpyxl) were not installed with e2er, so such
  files were skipped with a warning in the log. Both are now dependencies, and if one is missing
  anyway, e2er prints which file was not loaded and the command that installs the reader.

- **`e2er doctor` says what it can and cannot know.** Without any AI access chosen (no
  `LLM_BACKEND` and no `.env`), it no longer reports a missing `ANTHROPIC_API_KEY`: it says that
  nothing is set up yet, names Claude Code when it is installed, and points to the setup page or
  `e2er init --defaults`. A Claude Code, Codex or Gemini CLI that is not signed in fails the check,
  and one whose sign-in cannot be read is reported as "couldn't check" instead of "Ready". The
  Docker check now asks the Docker daemon whether it runs; an installed but stopped Docker is no
  longer reported as available.

- **`e2er skills list` and `e2er skills install` work without a local RISE checkout.** The
  default catalogue was a folder on the maintainer's computer (`~/Documents/Projects/RISE`). e2er
  now downloads the pack list from the public catalogue at github.com/bhanneke/RISE into
  `~/.e2er/cache/rise` (refreshed once a day; an older copy is used when GitHub cannot be
  reached). `RISE_PATH` and `--catalogue` still point to a local clone, and when neither works
  the error says how to set one.

- **`e2er init` copies skill files only for the chosen AI access, and asks first.** It used to
  copy all of e2er's skill files into `~/.claude`, `~/.codex` and `~/.gemini` without asking,
  whichever CLI was chosen. The wizard now asks before copying into the chosen CLI's folder and
  copies nothing for the API backends; `--defaults` copies into `~/.claude/skills` only. Both say
  where the files went. The `.env` header names the current e2er version instead of "e2er v3".

- **`e2er export <id>` works from any folder and takes a short id.** It looked for the workspace
  only under `workspaces/` in the current folder. It now uses the workspace the database records
  for the paper (new studies record the full path), falls back to `WORKSPACE_ROOT`, and accepts
  the first characters of the id (at least 4) when they match one paper. When the workspace
  cannot be found, the error says where it looked and what to do.
- **Exported studies are no longer read back in as data.** The default export folder is
  `<data folder>/e2er_papers`; with recursive staging, the next study picked up the earlier
  studies' files as its own data. Folders named `e2er_papers` are now skipped.
- **On Windows without Developer Mode, data files and PDFs are copied into the study.** Linking
  them fails there, and the files used to be left out with only a line in the log. e2er now
  copies them and says once in the terminal that copies do not follow later edits, and how
  Developer Mode lets it link instead.

- **`--methodology mixed` runs the estimation check.** It applied to empirical papers only, so
  a mixed paper with a data warehouse could reach the draft with a broken or empty estimation
  file. Mixed papers are now checked and repaired like empirical ones.

- **`e2er-data` runs on Python 3.14.** A `%` in the help of `e2er-data fred series --units`
  made Python 3.14's argparse refuse to build the command, so every `e2er-data` call failed there.
- **The nightly Allium check stops reporting the same thing every night.** Allium's OpenAPI
  files at docs.allium.so now redirect to a login page; the check read that page as a changed
  API and commented on issue #2 every night (141 comments). It now tells a spec it cannot fetch
  (a warning in the run, no comment) from a real change, fingerprints a real change, and comments
  only when the change differs from the one already reported (`scripts/check_allium_drift.py`).
  The fixtures stay as they are: the current specs are not publicly available to refresh them.

- **Internal planning notes moved to `docs/internal/`.** Version plans, run diagnoses and reviews
  sat next to the user documentation; they are now in `docs/internal/` with a note on what they
  are, and references point there. `docs/NEW_USER_WALKTHROUGH.md` no longer shows paths from the
  maintainer's computer. `docker/` has a README saying it is an optional Postgres stack for
  development, not needed to use e2er.

- **Tracebacks from estimation scripts reach the model in plain text.** On Python 3.13 and 3.14,
  with `FORCE_COLOR` set (Claude Code and uv set it), Python coloured the traceback, and the
  escape codes split the error line the specialist reads to fix its script. `e2er-run` and the
  post-step execution now turn the colours off.
- **README:** the replication template works with Zenodo packages and R or Python code only; the
  spending limit applies to the API backends, since studies on Claude Code, Codex and Gemini CLI
  cost $0 in e2er's records; e2er works with Python 3.11 to 3.14 (the automated tests now run on
  all four); `e2er --version` prints the installed version (new flag).

## [0.13.6] — 2026-10-05

- **The paper can be published with the study, and publish says what readers see for what stays
  private.** `e2er publish --paper public --paper-url <address of the PDF>` (default address with
  `--repo` and `--commit`: `paper/paper.pdf` in the repository at that commit) puts the link into
  `e2er.json` and the publish request as `access`, and e2er.org links the PDF on the study page.
  The address is not part of the dossier, so it changes no fingerprint. For each of the paper,
  the data and the code that stays private, `e2er publish` and the dashboard's finish page say in
  one sentence that readers on e2er.org see a button to ask you for it, and which flag publishes
  it. Data from the Global Macro Database get no such note: its terms do not allow passing them on
  outside the study's replication package, and readers on e2er.org are sent to the GMD. The
  finish page has the paper choice and its address.

## [0.13.5] — 2026-10-04

- **Every data connector records what it loaded, with the source's terms and citation.** Before,
  only the Global Macro Database connector wrote `data_sources.json`. Now FRED, Yahoo Finance
  (yfinance), Allium, a Zenodo record fetched by the replication template and the researcher's
  data folder write an entry for every load too, through `e2er-data` and through `fetch_data`
  (the API backends). Each entry names the source, what was loaded (series, ticker, variables,
  query or file), where it went, the release or the date it was read, the source's terms in a
  sentence or two and in full with their address, and the citation: FRED's own format from the
  series' Cite tab (with the series title and source, read from FRED), Zenodo's format for a
  record, and for Yahoo Finance and Allium, which publish no citation format, one that e2er
  suggests (`citation_by: e2er`). A file from the data folder is recorded with its SHA-256.
  The dossier keeps the new keys (`series`, `retrieved_at`, `terms_summary`, `citation_by`,
  `link`, `doi`) and lists data-folder files by `path`; e2er.org shows them as the study's
  "Data used". Studies published before this record no entries for these sources.

- **Every researcher action is in the dashboard too.** The study page runs a study again from a
  step of its template with a remark (`e2er rerun`), resumes a failed or stopped study as well as a
  paused one (`e2er resume`), resumes with a higher spending limit after the limit was reached
  (`e2er resume --max-cost`; the plain Resume, which would stop again at once, is not offered
  then), deposits the frozen pre-registration on Zenodo (`e2er preregister deposit --zenodo`),
  approves or refuses data queries waiting for approval, and shows "Demonstration or test run" on
  a demonstration study. The new-study page has the stops after a step (`e2er run --review-at`)
  and takes a spending limit in cents. Each stop page says what continuing means for its kind
  ("Keep the output as it is and continue", "Continue with these mismatches", "Approve the
  deviation and continue", "Continue: run the check again", "Approve and freeze"). The finish
  page has where public data and code live, the Zenodo deposit, name, ORCID iD, roles, licence,
  repository, commit and path, what the study builds on, `--online` citation checks, and the
  terms of a data source the study used: publishing GMD data as public needs the box that
  confirms them, as `--accept-data-terms gmd` does.
- **`e2er rerun` works after a run failed or stopped.** Before, it refused a step that had not
  been marked done (the step a run failed in) and a run stopped at a researcher step or a check.
  Now any template step of the study's mode can be the start: a step the failed run never
  reached is accepted, and the run picks up at its first unfinished step; at a stop the rerun
  takes the place of the stop (recorded as `replaces`), and the checks run again on the way. A
  step run again runs all of its specialists. `e2er resume` works as before.
- **A dossier with an approved deviation from the pre-registration is accepted by e2er.org.**
  The researcher step listed the approved changes as records under `deviations`, which the
  dossier format keeps for text; the text stays there and the records (file, SHA-256 frozen and
  approved) are under `approved_deviations`.

- **A failed number check stops the run for the researcher.** When the numbers in the paper's
  tables still differ from the results files after the automatic correction (governance `full`),
  the run stops at the researcher step `number_check`. It names each mismatch: the table cell,
  the value in the table, the value in the results and the source key, and offers the draft and
  the results files. Edit them, give an instruction, or send back `paper_drafter`,
  `section_writer` (table layout) or `econometrics_specialist`, and the check runs again; or
  approve to continue with these mismatches, recorded in the dossier as your decision. The
  reviewers run after that. Before, the check marked the run stopped, a `--review-at review`
  pause hid it, and the review step was then counted as done without a single reviewer. Under
  `contracts` and `off` the mismatches are recorded and the run continues, and `e2er status`
  and the dossier say so (`number_check.json`). The export carries the record
  (`reviews/number_check.json`); `e2er verify` passes a cell that differs only when the researcher
  continued with exactly that cell, and names it.
- **The number check no longer reads column headers and row labels as results.** All three
  critical mismatches of the live run were header cells ("Scaled, day 15 or earlier",
  "120-day window", a placebo shift of -20 days): the rows above the first `\midrule` and a row's
  label ("Surprise (25 bp)") are skipped; a bare number in the first column is still checked.
- **A dossier with output kept at a contract stop is accepted by e2er.org.** The researcher
  step listed the kept outputs under `accepted`, which the dossier format reserves for a yes/no;
  they are now under `kept`.
- **A step that fails stops the run and says why.** A review step that ends without a reviewer
  score, a revision step without its patch file, or the citation check now ends the run with the
  reason in `last_error`; no later step runs (the live run went on to the replication step), and
  the step is not counted as done, so `e2er resume` runs it again. No failed or stopped status is
  written without a reason.
- **patch_revisor's empty patch is an answer.** `[]` ("nothing I can fix by editing the draft")
  no longer counts as a contract violation, as its skill already said; a missing or unreadable
  patch file gets the usual attempts with the violation fed back. The automatic correction runs
  once per set of mismatches: a resume after the researcher's decision does not pay for it again.
- **Output that fails its check after the last attempt stops the run for the researcher.** Before,
  the run ended `failed`. Now it stops at the researcher step `output_contract`, which lists each
  attempt's violations and the files involved (`e2er status`, `e2er review`, the dashboard's
  review page). The researcher keeps the output as it is (recorded in the dossier; the step that
  wrote it is marked `approved_by_researcher` with `contract_failed`), edits a file, gives an
  instruction, or sends the specialist back with a remark for new attempts. `e2er resume` alone
  gives new attempts and never keeps failed output. Specialists in the same batch that passed
  keep their output. Crashes and an unavailable backend still fail the run.
- **A specialist no longer runs beside the one whose output it reads.** The live run had the
  econometrics specialist in the data analyst's batch, estimating before any data were loaded.
  The dispatcher now moves such an order behind its producer (`SPECIALIST_NEEDS`), and the
  strategist's example plan no longer shows it.
- **The data architect plans only tables an available source can load**: yfinance and GMD, FRED
  with `FRED_API_KEY`, Allium with `ALLIUM_API_KEY`, or a file in the study's data folder. Its
  prompt lists exactly these; any other table is a contract violation that names the table, its
  source and why it is unavailable.
- **`e2er run --demonstration`** marks a demonstration or test run from the start (manifest.json
  `purpose`); export, publish, the paper footnote, the reproduction report and the dossier take
  it from there. New disclaimer wording: "Demonstration. This study was produced with e2er as a
  demonstration or test run and is published as is. It is not presented as a research
  contribution, and its author does not vouch for its findings."

## [0.13.4] — 2026-10-03

Fixes found by the new end-to-end stories (e2er-site `npm run test:e2e`, 15 research processes
replayed from two recorded runs).

- **A plan change after the pre-registration is frozen stops the run.** The estimation check
  pauses for the researcher and lists each changed plan file with its SHA-256 at the freeze and
  now. Approving records the deviation as the researcher's decision in the dossier and in
  `preregistration.lock.json` (`approved_deviations`); `e2er verify` passes an approved deviation
  and reports it, and fails an unapproved one. Before, the deviation was only disclosed.
- **Public data or code at a fixed commit can be published.** The availability address of public
  code no longer contains the commit, so the paper footnote, `provenance.json` and the dossier
  are the same with and without `--commit`, and e2er.org's check at the commit passes. The
  commit is recorded in `e2er.json` and the publish request.
- **A contributed skill keeps its pack id** (`skill:<pack>/<skill>`), so the dossier links the part
  listed on e2er.org and its author is credited. e2er's own skills keep `skill:e2er/…`.
- **Resume after a spending-limit pause skips completed work**, also in the initial phase.
- **`LITERATURE_ACQUIRE_LIMIT=0` sends no literature request.**
- **`e2er publish --to <platform>`** uses that platform's address for the dossier link, in the
  paper footnote, `e2er.json`, the Zenodo description and the output.

## [0.13.3] — 2026-10-03

- **Global Macro Database (GMD) connector.** `e2er-data gmd versions | variables | countries |
  series` reads the GMD's release files over HTTPS (no key). `series --variables rGDP,infl
  --countries USA,DEU --start 2000 --end 2024 --table gmd_macro` loads a country-year panel with a
  `forecast_<variable>` flag per variable; the newest release is the default and `--version` pins
  one. Each load records the release, the URL and the SHA-256 of the file read in
  `data_sources.json` and in the table's `data_dictionary.json` entry (with the GMD's terms of
  use), and adds the GMD citation (`GMD2025`) to `literature.bib`. Release files are cached in
  `~/.e2er/cache/gmd/<release>/` and hashed again on every use. An unknown variable, country or
  release, or a failed download, exits non-zero and leaves data.db unchanged.
- **Export and dossier:** `data_sources.json` ships as `data/data_sources.json`; the dossier of a
  study that has it lists each load under `data_sources` (connector, release, table, file URLs and
  SHA-256). Dossiers of studies without it are unchanged.
- `e2er doctor` checks that the GMD release list is reachable (`data.gmd.versions`).

## [0.13.2] — 2026-10-02

- **The internal quality review gives a score, nothing else.** Six reviewer specialists each
  score the draft from one angle (data, identification, literature, mechanism, technical,
  writing); the score is their weighted average and decides whether the draft is revised. A run
  that finishes its steps is now `completed` whatever its score; up to 0.13.1 a low score stored
  `rejected`, which read as a peer-review decision (the FOMC demonstration study's dossier said
  "Outcome: Rejected" for a run that finished every step).
- **Dossier:** `run.outcome.status` says whether the run finished (`completed`, `failed`,
  `cancelled`, `paused`, `stopped` by a check). The new `run.internal_review` records the score
  (`score`, `scale`, `combined`, each reviewer's score in `reviewers`, their `weights`, `rounds`).
  A run stored as `rejected` reads as `completed` when it reached its review, else `stopped`.
- **Visible wording:** the dashboard, `e2er status`/`list`/`run`, the export's README and
  report.html show the status in plain words ("stopped by a check" for a check that stopped the
  run) and "e2er's internal quality review: 6.1 of 10", never a review verdict.
- **Revision round that applies no edit** completes the run and records a
  `revision_not_applied` event; a revision round that writes no patch file fails the run
  (resumable). Before, both stored `rejected`.

## [0.13.1] — 2026-10-02

- **README rewritten in plain language.** It opens with the description and the texts of the
  e2er.org About page, and every command and option it names exists. Wrong statements were
  removed: a $25 cost default (it is $5), `python -m e2er`, `.txt` as a data format, outdated
  counts of skills and specialists, an example folder that does not exist.
- **Description:** "e2er is the open infrastructure for publishing, verifying, reproducing and
  reusing AI-enabled research." in the package metadata, the CLI help and the citation metadata.

## [0.13.0] — 2026-10-02

### Name and publishing format

- **Name.** The package, the CLI and the citation metadata say "e2er (End-to-End Research)".
- **Publish matches e2er.org's format.** The study description no longer carries an
  `amendments` field, which e2er.org refused; the amendments stay in provenance.json and in
  the dossier. `docs/schemas/research-object.schema.json` is synced with the site's copy, and
  a test validates a real publish against it.

### Integrity of published studies (review of 2026-10-01)

- **Publish needs the run.** `e2er publish` finds the study's run database
  (`--db`, the study folder's `DATABASE_URL`, e2er's default) and refuses one
  that does not hold the exported paper's run, or none. Both studies published
  on 2026-10-01 had dossiers without steps. `--no-db` publishes anyway and the
  dossier and footnote say the steps are not recorded.
- **Nothing changes in an edited folder.** Publish checks the folder against
  `provenance.json` before it changes anything; each change it then makes is an
  amendment (path, fingerprint before and after, reason), so the exported hash
  is never lost. A PDF publish compiles is fingerprinted.
- **Zenodo.** The dossier is built from a copy of the final availability and
  its id from the final document; deposits are published after everything that
  can fail; reserved deposits are kept in `.e2er/zenodo.json` and reused, so a
  retry makes no new deposits and gives the same dossier.
- **The dossier says what the run recorded**: every segment of the run with its
  commit and version, components pinned at each commit they ran on (unresolved
  ones say so), the specialists and skills that ran, one researcher step per
  researcher action with every field, the runner's reruns on the steps they
  caused, the outcome, halts, pauses, failures and set-asides, UTC times, and
  bundle-relative paths only. The runner now records what each step wrote and
  the skills it read. Dossiers built from a run are `e2er-dossier/0.6`.
- **Canonical JSON** is RFC 8785, as e2er.org computes it (floats, large
  integers, NaN, key order); the four published dossiers keep their addresses.
- **`e2er verify`** never follows a link, reads `provenance.json` strictly,
  checks every file but the root `provenance.json`, `e2er.json` and `.e2er/`
  records (report.html included), compares sizes, recomputes the derivation
  edges, ignores `.DS_Store`/`Thumbs.db`/`._*` (and says so), checks
  `e2er.json` and `.e2er/link.json` against the folder, and with `--against`
  against what e2er.org published. Checks the study's record requires fail
  when their input is missing; checks over nothing are skipped, never passed;
  every table cell must be a source value at the precision shown.
- **The reproduction report** must keep e2er's summary section, and its
  sections, "N of M" counts and overall verdicts must agree with the JSON.
- **Export** creates its folder atomically, never copies dotfiles, key files or
  links that leave the workspace, never lets one file overwrite another's
  target (and says which PDF is `paper/paper.pdf`), and fingerprints
  `report.html`.
- The demonstration disclaimer is a delimited block: a new wording replaces it,
  a study without a purpose loses it, and a purpose recorded on the study is
  honoured. The paper gets the dossier link without `--name` too.

### `e2er rerun`: send a finished study back to one of its steps

- `e2er rerun <id> --from STEP --remark "…"` (and `POST
  /api/papers/{id}/rerun`) reruns a template step and every step after it in
  a study that is not stopped at a researcher step, a completed one included.
  The approvals from that step on are withdrawn, the remark goes to
  `researcher_instructions.md` and is recorded as the researcher's action
  (`researcher_action`, action `rerun`, in the dossier), and the run stops at
  the next researcher step for approval. A researcher step cannot be the
  start, nor a step that has not run; at a pending researcher step the
  send-back does this. Nothing in the workspace is deleted.

### `e2er publish` takes the template from the export

- The export records the template the study was run with in
  `provenance.json` (`run.template`): the runner passes its template, `e2er
  export` and the browser's export the papers row's `pipeline`, otherwise
  `manifest.json`'s. `e2er publish` uses it; `--template` (no longer defaulting
  to `empirical`) may only repeat it, and a different one is refused with the
  recorded name. An export made before this records nothing: publish then takes
  `--template`, else `empirical`, and says so. The FOMC study had been
  published as `empirical`; a replication now gets the replication disclaimer.
- A server answer without an error text (a proxy page, Cloudflare D1 over its
  daily read limit, an empty body) printed an empty `error:`. `e2er publish`,
  `login`, `whoami`, `status`, `dossier push` and `submit` now print the HTTP
  status and the first 200 characters of the body (`pc.error_text`).

### The written reproduction report agrees with its JSON

- The replication demonstration's `reproduction_report.md` said "16 targets"
  and "not_reproduced 2" while `reproduction_report.json` and the check had 17
  numbers, 12 reproduced, 2 reproduced_minor and 3 not reproduced, and it
  listed package versions the run did not install. Nothing compared the two.
- e2er now writes the counts and the environment into the Markdown itself:
  once the JSON checks out, the reproduction check puts a section "Counts and
  environment" (delimited by `<!-- e2er:summary … -->` comments) before the
  report's first `##` heading, rendered from `reproduction_report.json` and
  `sandbox_log.json`.
- The reproduction check (the pipeline's `reproduction_gate` and `e2er
  verify`) and the comparer's contract fail when the prose contradicts the
  JSON, and name the contradiction ("reproduction_report.md says 16 level-1
  numbers (…), reproduction_report.json has 17"): counts that name their level,
  tables of counts per label, the label stated for a number that can be
  matched to one compared number (by target id, or published and reproduced
  value), and a package version stated after its name. A missing Markdown
  report, or an edited summary section, fails too. New module
  `src/core/pipeline/reproduction_md.py`.

### Replication: packages as of the package date, strict labels

- A specialist that writes its files whole (the planner, the comparer) starts
  each attempt with its earlier files moved to `<name>.previous`; any other
  specialist is told which of its files exist and to read them before writing.
  The CLI's write tool refuses to overwrite an unread file, which made every
  retry of the comparer fail in the live rerun.

- The sandbox installs packages as of the Zenodo record's publication date by
  default (`snapshot = "package-date" | "latest" | "YYYY-MM-DD"`): R from Posit
  Package Manager's dated CRAN snapshot, Python with pip's
  `--uploaded-prior-to`; declared versions still win (`remotes::install_version`,
  `==`). The snapshot date and URL, the platform and every installed version,
  dependencies included, are read from the committed image and recorded in
  `sandbox_log.json`, also when the environment is reused.
- Labels follow the protocol's thresholds exactly, stated in
  `reproduction-protocol.md` and enforced by the check: `reproduced` only when
  equal at the target's own precision (1e-9 relative for package cells),
  `reproduced_minor` up to 10 % with the same sign, `not_reproduced` beyond; a
  result takes its worst number's label. The check and the comparer's
  contract refuse reason texts that contradict the numbers or state a cause as
  established, and require the report's environment block (snapshot, and the versions it
  names) to match the log; the full list of installed versions is written by
  code into `reproduction_check.json`, not transcribed by the model.

### Checks

- **Every pre-registered hypothesis has a result.** The preregister step now
  ends `preregistration.md` with a machine-readable block: the hypotheses the
  plan declares (`[{"id": "H1", "statement": …, "parts": ["H1a", "H1b"]}]`)
  and the sample size the design fixes (the events of `event_design.json`, or
  a `sample_size` in `identification_spec.json`). The researcher may correct
  it; on approval it is frozen into `preregistration.lock.json`. The
  estimation check and `e2er verify`'s `preregistration` check then require at
  least one result entry per hypothesis (entries name it in a `hypothesis`
  field; a part such as H1a counts for H1) and fail with the list of missing
  ones. The headline estimate's `n_observations` must equal the registered
  sample size unless `exclusions`, each with a reason, account for the
  difference; the declared exclusions are reported. A lock frozen before this
  release falls back to the hypotheses its frozen text declares.
- **p-values follow from the test statistic.** The estimation check and
  `e2er verify`'s numbers check recompute, for every coefficient with an
  estimate, standard error, t and p: t = estimate / se (allowing for
  rounding), and the p-value from t with the stated `df`, G − 1 to the normal
  for clustered errors, `df_residual`, n − k, or n − 1 for a one-sample mean
  test, within 0.005 (more when `rounding` is declared). When df is unknown the
  p-value must lie between the normal and the t with the fewest df the entry
  allows, and the check says df was unknown. One-sided tests
  (`alternative`) are checked one-sided; p-values from bootstrap or
  permutation (`p_value_method`) are left out and listed. A mismatch fails and
  names the coefficient. The t distribution is computed from the regularized
  incomplete beta function (no scipy dependency) and tested against closed
  forms and published critical values.
- **Replications verify offline.** A replication export now carries
  `sandbox/logs/` and, under `sandbox/run/`, the output files the entry points
  wrote and every file `reproduction_report.json` reads a number from, all
  hashed in `provenance.json`. `e2er verify` has a `reproduction` check for
  bundles with a reproduction report: it re-reads every compared number from
  those files at its locator, recomputes each number's label with the
  pipeline's own reproduction code and the tolerance the run used, and
  confirms the report's summary counts. A replication bundle can now be
  verified. Paper bundles are unchanged.
- The reproduction check (pipeline and verify) recomputes a label per
  compared number, fails on a stated `label` that differs, and checks the
  report's `summary` counts (numbers by label, or results by level).
- **Declared tables hold values, not only rows.** The data contract now
  fails when a value column of a declared table is less than 90% non-null
  (or the `min_non_null` share the data dictionary declares for the table or
  column), e.g. `dgs2.value: 0 of 2765 non-null (needs 90%)`. It checks the
  columns a table's entry declares, else every column that is not a date;
  tables the researcher supplied only where columns are declared.
- **Statistics come from a library.** scipy and statsmodels are now
  dependencies: the estimation runner executes `run_estimation.py` with
  e2er's own interpreter, which had neither, and the FOMC study's specialist
  wrote its own t distribution (p = 0.208 for t = -2.00 with 19 df). The
  econometrics skills require `scipy.stats` or the fitted
  `statsmodels`/`linearmodels` result for every distribution function and
  forbid hand-written approximations; entries carry `hypothesis` and `df`.

### Keys and connectors

- Settings strip surrounding whitespace from every key, token, secret and
  password, whether read from `.env` or the environment; the FRED connector
  and the Zenodo token do the same, and the setup page strips a key it keeps
  from the previous file. A FRED key pasted with a leading space was sent as
  " <key>", which FRED rejects with HTTP 400.
- `e2er-data … --table` fails with exit code 4 and leaves `data.db`
  untouched when the connector reports an error, returns no rows, or returns
  rows without a single value. Before, a failed load was reported only in the
  JSON the model reads.
- `e2er doctor` checks the FRED key's format (32 lower-case letters and
  digits) before requesting anything, and says when the key had whitespace
  around it.

### Fixed

- `event_design.json` is exported to `design/` with the other plan files. It
  went to `misc/`, so `e2er verify` reported a pre-registered event study's
  design as missing.

- The pre-registration check now recognises result files as estimation output:
  csv, tsv, parquet, json or xlsx outside `data/` and the declared data tables,
  named as results (result, estimat, car, abnormal, ar_, regression, coef) or
  with result columns (car, car_*, abnormal*, ar_*, coef*, estimate*, t_stat,
  p_value, alpha_*, beta_*). Plan and description files are never results.
  After a send-back from a blocked pre-registration the check runs again and,
  once clean, the researcher sees the pre-registration.
- A send-back no longer overwrites a file the researcher edited: the specialist
  is not asked for it, and if it rewrites it anyway the researcher's version is
  put back and the specialist's kept in `set_aside/`, recorded as
  `researcher_edit_restored`.

## [0.12.1] — 2026-09-29

### Studies and versions

- **A study is a group of attempts.** Running a question again adds an
  attempt to its study instead of a new row in the list. Attempts with the
  same research question (spacing, case and trailing punctuation ignored) and
  the same template belong to one study; each attempt is a version (v1, v2, …
  by start time), and the study takes the latest attempt's title.
- **The studies list** shows one row per study: title, template, the number
  of attempts, a status summary ("3 completed · 4 rejected · 13 failed") and
  the latest attempt's status and date. It is sorted by last activity and has
  a search box.
- **The attempts page** (`/studies/<key>`) lists a study's attempts with
  version, status, start and update dates, model and backend, and a link to
  each paper page. The paper page says which study and version it is
  ("v3 of 9").
- **Move to study…** on an attempt puts it into another study, or splits it
  off into one of its own, for questions that were grouped wrongly.

### Archiving

- An attempt, or a whole study, can be archived: it is hidden from the lists
  and nothing else changes. No record, file or workspace is deleted, and
  running and paused attempts are refused, with the reason.
- **Archive failed and cancelled attempts** shows the count and the list in
  the page before it archives, and archives only what was shown.
- **Show archived (n)** brings archived attempts back into view, with an
  Unarchive button per study and per attempt.
- On the command line: `e2er list` (`--attempts`, `--archived`, `--search`),
  `e2er archive <paper_id>`, `e2er archive --study <key|id>`,
  `e2er archive --failed` (a dry run unless `--yes`) and
  `e2er unarchive <paper_id>` (or `--study`). The first 8 characters of an id
  are enough.
- New columns `papers.study_key`, `study_override` and `archived_at`. SQLite
  databases gain them on start-up and existing attempts are grouped
  automatically; Postgres gets `sql/015_papers_study_versions.sql`. Both are
  safe to run again. The new endpoints need the dashboard session, like the
  setup and finish pages.
- The list no longer shows a cost column; the cost is on each paper page.

### Cancel a paused attempt

- A paused attempt (stopped by the budget or the circuit breaker, or waiting
  at a researcher step) can be ended with **Cancel attempt** on the attempts
  page and on the paper page, or with `e2er cancel <paper_id>`. Before, a
  paused attempt could only be resumed, so it could never be archived.
- Its status becomes cancelled and the cancellation is recorded as a
  researcher step ("cancelled by the researcher", with the time and whether it
  came from the dashboard or the command line), so the dossier of a later
  export shows it. The workspace is kept, and the attempt can then be archived
  like any cancelled one.
- Refused when another running e2er process owns the attempt, and for
  attempts that are running or already over.

### Fixed: a second e2er process paused a study another process was running

- Two e2er servers on one database: when the second one started, its start-up
  recovery paused every paper that looked "running", including a paper the
  first server was still running (recorded as "interrupted — the server
  stopped while this paper was running").
- A run now records its owner (host, PID, process start time, port and an
  instance id) when it starts or resumes, and refreshes a heartbeat every
  minute. Start-up recovery pauses a paper only when the owner process is
  gone, or when its PID now belongs to a different process. A paper owned by a
  live process is left alone and logged ("running on another e2er process
  (PID …, port …)"). For attempts started by an older e2er, which have no
  owner recorded, recovery waits until there has been no activity for 10
  minutes.
- The paper page shows such a paper as "Running in another e2er process",
  with a link to that one and without Resume or Cancel; the resume and cancel
  endpoints refuse it (409).
- New columns `papers.run_owner` and `heartbeat_at`
  (`sql/016_papers_run_owner.sql` for Postgres). Changes to these columns and
  to the study columns no longer move `updated_at`, so archiving or a
  heartbeat does not reorder the list.

## [0.12.0] — 2026-09-29

### Fixed: templates missing from the 0.11.0 package

- The 0.11.0 package on PyPI did not contain the templates (`pipelines/`).
  After `pip install e2er` no study could start: every template name failed
  with "no pipeline named 'empirical'". 0.12.0 ships all four templates
  (empirical, empirical-preregistered, event-study-finance, replication).
  Upgrade with `pip install -U e2er`.
- CI now builds the wheel, installs it into a fresh virtualenv outside the
  checkout, and checks that `e2er --help` runs, that the four templates and the
  skill files resolve, and that `e2er verify` passes on a copy of
  `examples/showcase` (`scripts/check_wheel.sh`, job `package` in
  `.github/workflows/tests.yml`). Run against the 0.11.0 wheel, the check fails.

### e2er in the browser

- **`e2er` alone opens the browser.** It starts the dashboard on 127.0.0.1 and
  opens it when started from a terminal (`--no-browser` turns that off); the
  address is always printed. When e2er is already running on the port, it opens
  that one. `e2er --port N` picks another port.
- **Setup page (`/setup`)**, shown automatically while no settings exist and
  under Settings afterwards. One card each for the AI provider (the installed
  claude/codex/gemini CLIs and whether they are signed in, API keys; a model per
  provider with the cheapest labelled), literature, data folder, Docker and
  optional keys (FRED, Allium, Semantic Scholar). With no AI provider found it
  lists the ways to get one, with links; without Docker it says only the
  replication template needs it. Saving writes the same `.env` as `e2er init`,
  owner-only (mode 600), keeps settings it does not manage, shows stored keys
  only as their last four characters, optionally creates `data/` and
  `literature/`, then runs the doctor checks.
- **Folder browser** for literature and data, served by the local server:
  folders plus .bib and .pdf (or data) files, hidden files left out. A .bib
  file, a Zotero export (a .bib with a `files/` folder), a Zotero library or a
  folder of PDFs is recognised and its references and PDFs counted. It needs the
  session token from the launch URL (traded for an HttpOnly, SameSite=Strict
  cookie), answers only to loopback clients with a local Host header and no
  foreign Origin, never adds CORS headers, stays inside the home folder (extra
  roots only via `E2ER_BROWSE_ROOTS`) and does not follow symlinks out of it.
- **New study page:** the research question, template cards read from
  `pipelines/*.toml` (description and the steps where each one stops for you),
  a demonstration box (recorded for that one study) and the rest under More
  options. A refused start is shown on the form with what was typed kept.
- **Progress:** the study's page lists its template's steps with their state,
  the current step, the specialists done and the checks passed or failed, and
  links to the review screen at each pause (offered once the run has actually
  stopped, so approving is never refused).
- **Finish page** (`/papers/<id>/finish`): prepares the exported folder, runs
  the five `e2er verify` checks, and publishes to e2er.org with the fields of
  `e2er publish`: a dry-run preview of the request first, sign-in through the
  device flow, then publish.

### Command line

- **Forgiving paths.** One helper cleans every path typed at a prompt or given
  as a flag: a leading prompt glyph (❯ › $ % > #), surrounding quotes,
  drag-and-drop backslash escapes, `file://` and `~`. `e2er init` accepts a
  folder holding one .bib ("That is a folder. It contains My Library.bib — use
  it? [Y/n]"), a Zotero export or a folder of PDFs, and says what it expected
  and what it found.
- `e2er doctor` checks the Python version and reports Docker (optional), and
  points to the install instructions when Python is too old or the claude CLI
  is missing. The `.env` from `e2er init` is written owner-only.
- README: install with uv (Python 3.12 pinned), or pip in a virtualenv.

### Other fixes

- `e2er review` without a terminal exited with an EOFError traceback; it now
  names the flags and the dashboard page to use instead.
- `e2er status` showed "single_pass / empirical" for every study; it now shows
  the study's template.
- The `empirical` template's description says "e2er's default" (was "E2ER's").

## [0.11.0] — 2026-09-29

### Templates

- **event-study-finance** (`pipelines/event-study-finance.toml`): abnormal-return
  event studies around announcements. A fork of `empirical-preregistered` that
  checks the design before estimation. The identification strategist declares
  events and windows in `event_design.json` (schema
  `docs/schemas/event_design.schema.json`, specified in
  `skills/files/econometrics/event-study.md`); the pre-registration includes it
  and treats a later change as a deviation. `docs/proposals/event-study-demo.md`
  proposes a first study (FOMC target-rate changes and bank stocks, 2015–2025),
  not yet run.
- **replication** (`pipelines/replication.toml`): reruns a published study from
  its Zenodo replication package and compares every reported number with the
  rerun. Steps: `fetch` (keyless Zenodo download, each file checked against
  Zenodo's checksum, hashed with SHA-256 and unpacked read-only), `plan` (new
  specialist `replication_planner`), `review_plan` (researcher), `sandbox_run`
  (Docker: dependencies installed with network and without the package, then
  each script run with `--network none`, CPU, memory, process and time limits,
  read-only root, no capabilities, non-root, the package mounted read-only and
  outputs in a separate folder, everything logged with hashes), `compare` (new
  specialist `reproduction_comparer`: reproduced / minor differences / not
  reproduced / could not be run), `reproduction_gate` and `review_report`
  (researcher). The product is the reproduction report and the dossier.
  - Targets have two levels: 1 = a cell of a result file the package ships,
    2 = a number printed in the paper, taken only from the paper (page, table or
    figure, printed decimals).
  - The researcher can supply the paper (`PAPER_PDF`,
    `<LOCAL_DATA_DIR>/paper.pdf` or the workspace's `data/paper.pdf`). The fetch
    step, which runs at every start, stages it read-only as `paper/paper.pdf`,
    fingerprints it, extracts its text page by page for the planner, and records
    it in the dossier as researcher-supplied (`supplied_input`).
  - `src/modules/data/zenodo.py`: keyless Zenodo connector (record metadata,
    linked publications, paced downloads, checksum verification).
  - Skills `replication/reproduction-protocol` (after the Institute for
    Replication and Brodeur et al., 2025), `replication/replication-plan`,
    `replication/reproduction-report`; schemas
    `docs/schemas/replication_plan.schema.json` and
    `docs/schemas/reproduction_report.schema.json`.
- Templates can add skills and machine-readable files to a specialist for their
  own runs (`[skills]`, `[sidecars]`), merged after the registry's; the merged
  skills are recorded in the study's description and dossier.
- Gate steps accept `after = [...]`, like researcher steps: the check runs
  inside the initial phase, after those specialists and before the econometrics
  specialist. `[steps.settings]` holds a check's parameters. A `specialists`
  step without a phase of its own dispatches its `run` list with the registry's
  default work order; a template without a `revision` step completes after its
  last step.

### Checks

- **event_window** (event-study-finance): reads `event_design.json` and stops
  the run when the estimation window is too short (default 120 trading days) or
  too close to the event window (default gap 10), when events of the same asset
  overlap in their event windows without a declared treatment (drop, cluster,
  aggregate), or when an event date is not a trading day in the data. Rule (d):
  when the design names the researcher's own event table (`events_source`), its
  event dates must be exactly that table's dates (non-trading days move to the
  next trading day, reported in the verdict); missing, extra and shifted dates
  are each listed. The calendar must be a table the data dictionary declares and
  the data analyst loaded. The limits are settings of the template; each verdict
  is recorded and appears in the dossier.
- **No estimation before the pre-registration freezes** (check
  `preregistration`, every template with a `preregister` step): estimation
  output in the workspace at that point stops the run with the list. Approving
  does not pass it; sending back the specialist that produced it moves the
  output to `set_aside/` with a manifest, recorded in the dossier.
- **Data-analyst tables**: the data analyst loads, cleans and describes data and
  never estimates. It loads the tables `data_dictionary.json` declares under
  `tables` into data.db (`e2er-data ... --table <name>`), and its contract fails
  when one is missing or empty or `data_summary.md` does not give its actual row
  count (skill `data/data-tables`).
- **reproduction** (replication): re-reads every compared number from the run's
  own output files, reads level-1 numbers from the rebuilt copy of the target's
  own file, and counts each level separately. It follows the governance regime.
  Two further checks, `package_integrity` and `sandbox`, block in every regime
  (the package could not be fetched and verified, or the sandbox could not run).
  The planner's and comparer's JSON files are part of their output contract.
- A failed check stops the run with its reasons and runs again on resume.

### Command line

- `e2er run "<question>" --template <name>` (alias `--pipeline`) chooses the
  template; an unknown name is refused before anything is started.
- `e2er review` shows why a check stopped the run.

### Publishing

- `e2er publish --demonstration`, or `E2ER_PURPOSE=demonstration` in the
  environment or the study folder's `.env`, records `purpose: "demonstration"`
  in e2er.json and the dossier (a dossier without it hashes as before). Studies
  made with the replication template also record `kind: "replication"`.
- For a demonstration, the paper stamp adds the disclaimer as a second
  first-page footnote, and the replication template's reproduction report
  carries the replication wording at the top. The wording is kept in
  `src/core/demonstration.py`.

### Fixed

- `e2er run` cut the title at the first "." anywhere in the question, so a DOI
  or a decimal ended it ("… Brazil (10"). The title is now the first sentence.
- The runner no longer runs another specialist's script on the data analyst's
  behalf (in the 2026-09-28 event study it ran `run_estimation.py`, and
  abnormal returns existed before the pre-registration).

## [0.10.0] — 2026-09-26

### Publishing on e2er.org, with a dossier on every paper

`e2er publish <bundle>` verifies an exported bundle offline and writes its
description (`e2er.json`, schema `e2er-research-object/0.1`,
`docs/schemas/research-object.schema.json`): contributors with GitHub login and
ORCID, backend and models, template and mode, the cited literature with DOIs,
data and outputs with their hashes, and the verification result. Its content id
is the SHA-256 of `provenance.json`.

Publishing also builds the study's **dossier**: every step of the run in order,
the specialist and model that carried it out, the file it produced and the
checks it passed or failed, and every template, specialist, skill and connector
pinned by content hash. The dossier's address is the SHA-256 of its canonical
JSON; the paper gets the author line "<name> with e2er" and a first-page
footnote linking the dossier, and is recompiled. Existing dossier addresses are
unchanged by this release (new fields only appear in dossiers that use them).

- `e2er login`, `logout`, `whoami`: device-code sign-in to e2er.org; the token is
  kept in the system keychain, or in `~/.e2er/credentials.json` (mode 0600)
  when the keychain refuses.
- `e2er publish --to URL` sends the description (never files or AI keys; a scan
  refuses anything that looks like a key or a home-directory path);
  `--dry-run` prints the exact request and changes nothing; `--offline` writes
  the description for publishing from a folder in the browser.
- `e2er status <folder>` and `e2er dossier push` (register a dossier for a
  private study so the paper's footnote resolves).
- `e2er submit` sends a skill, template, specialist or connector for review.
- `e2er verify --json`, for GitHub Actions reporting to e2er.org with OIDC
  (`examples/github-actions/e2er-verify.yml`).

### The researcher decides where the process stops

A template step of kind `researcher` stops the run; the researcher approves,
edits a file, gives an instruction that every later specialist receives, or
sends an earlier step back with a remark (`e2er review`, or the dashboard).
Each action is recorded and appears in the dossier as the researcher's step,
with the file's fingerprints before and after an edit.

### Pre-registration as a template option

A `preregister` step assembles the question, hypotheses, design and analysis
plan and, once the researcher approves it, freezes it with its SHA-256 and the
time. The estimation is compared with the frozen plan; a deviation is reported,
and `e2er verify` shows it. `e2er preregister deposit --zenodo` deposits it
with a DOI from the researcher's own Zenodo account.
`pipelines/empirical-preregistered.toml` uses both steps; `empirical` is
unchanged.

### Data and code, public or private

`e2er publish --data public|private --code public|private` (default private)
records availability in the description and the dossier; for private material
e2er.org receives only fingerprints. `--zenodo` deposits the public data and
code in the researcher's own Zenodo account and records the DOIs.

### Fixed

- Papers compile from their own bundle: the export ships `literature.bib` as
  `refs.bib` and now points `\bibliography` at it (before, a recompile turned
  every citation into "?"); `&`, `%` and `#` in BibTeX text fields are escaped;
  publish refuses a recompile that leaves a citation unresolved, and `verify`
  fails when the paper names a bibliography the bundle lacks.

### Changed

- The name is written lowercase, "e2er", in all visible text (CLI help and
  output, dashboard, documentation). Identifiers, `E2ER_*` settings and the
  citation title are unchanged.

## [0.9.1] — 2026-09-18

### A corpus of what papers claim, not just that they exist

A literature search returns titles and abstracts. A drafter given thirty BibTeX
entries can cite plausibly and nothing more — it has read the metadata and is
guessing at the content, which is how a related-work section ends up describing
papers nobody read.

`e2er corpus` builds a local library of *claims* instead. Each entry is an
extracted statement plus the verbatim sentence it came from, checked against the
paper's full text; a claim whose quote cannot be located is discarded rather
than flagged. That is the numbers gate one level up — a table cell must trace to
a sidecar key, a claim must trace to a sentence, and neither check asks a model
whether it is telling the truth.

```
e2er corpus add ~/papers/                  every PDF in a folder
e2er corpus add "10.1257/aer.20201397"     one paper by DOI
e2er corpus topics add "stablecoin runs"   a standing interest
e2er corpus refresh                        re-run topics, extract only what is new
e2er corpus search "null effects of listing"
```

The library lives at `~/.e2er/corpus.db` (`CORPUS_DB` to move it), outside any
workspace, and accumulates across projects. `refresh` checks coverage before
downloading or calling a model, so running it on a schedule is cheap.

A paper run reads the PDFs staged in its own `literature/` folder into the
corpus before drafting, then writes the matching claims to
`literature/corpus_evidence.md` and seeds `literature.bib` from them — so what
the drafter quotes is what it can cite. `CORPUS_AUTOINGEST=false` disables it.
With no corpus, nothing changes.

The record format is published as
[`docs/schemas/structured_review.schema.json`](docs/schemas/structured_review.schema.json)
and specified in [docs/STRUCTURED_REVIEWS.md](docs/STRUCTURED_REVIEWS.md), so
another tool can produce records E2ER reads or read records E2ER produces. It is
validated against what the code emits in CI, because a format published as
implementable is a promise and an unchecked promise drifts.

### Two thirds of the "fabrications" were the checker

`e2er corpus stats` reports how often the extractor supplied a quote that was
not in the paper — fabrication measured under the least favourable conditions
for fabricating, since the prompt states the quotes are checked mechanically.

On the first real corpus that read 1.1%. Re-downloading every paper and
re-checking each rejected quote showed **four of six were true verbatim quotes**,
failing on artefacts of PDF extraction: hyphenated line breaks arriving as
hyphen+space, and an `fi` ligature. The real rate was closer to 0.4%.

`normalize()` now folds ligatures, and quote matching falls back to a
whitespace- and hyphen-free comparison when the strict match fails — dropping
exactly what those artefacts are made of, while wording and word order still
have to match exactly. A paraphrase, a reordering and an invented sentence are
all still rejected, and there are tests for each.

The prediction this replaced was also wrong: `limitations` was expected to be
the most-invented field, being diffuse and easy to reconstruct. It produced 129
claims and zero rejections.

### Fixed

* **`e2er corpus refresh` was not incremental for preprints.** Coverage was
  checked by DOI, and arXiv assigns none — so every preprint was re-downloaded
  and re-extracted on every refresh, forever. Papers now carry a title-and-year
  key used only for the coverage check.
* **One provider could take the whole search budget.** Five OpenAlex records
  filled a limit of five, every one of their "open access" URLs was a publisher
  landing page, and arXiv — which serves real PDFs — was never reached. Sources
  are interleaved round-robin.
* **A landing page was reported as a scanned PDF.** Resolvers routinely return
  HTML at a URL ending in `.pdf`; the failure now names what actually arrived
  instead of sending the reader after an OCR problem that does not exist.
* **A local PDF was titled by its filename.** `extract_pdf_metadata()` existed
  and was not called, so a paper was stored as `1-s2.0-S0378426619301234-main`
  with no authors, year or DOI. Its title heuristic also stopped at the first
  line, truncating any title that wrapped — and a truncated title deduplicates
  against nothing.
* **The same paper could be stored twice**, once from a PDF and once from the
  web. An arXiv stamp is now read as the DOI arXiv mints from it, and a title
  that is the beginning of another counts as covered — used only to decide
  whether to skip a paper, never to decide which record a review is written to.

## [0.9.0] — 2026-09-13

### A bibliography exists before the drafter writes

Literature acquisition runs as a pipeline stage, before any specialist, and
writes `literature.bib` from the paper's own research question and title. It
self-skips when a bibliography already exists, so a researcher's own library
always wins.

It is a stage rather than a tool deliberately. The drafter already had a
`save_bibtex` tool and a skill file telling it to use one — and `tool_loop`
ignores SDK tools on every CLI backend, so the drafter cited from memory
against a `references.bib` that did not exist. Granting a capability and
instructing a model to use it does not make it used.

Also fixes the OpenAlex provider, which returned 400 for any query containing
`?` or `*`. A research question normally ends in `?`, so the provider was
failing outright and acquisition silently fell through to a weaker source.

### Verification now checks what it claims to

Four defects, found by producing the first completed run rather than by
reading the code:

* **The export dropped `tables/`.** The renderer writes one `.tex` per table
  and the draft `\input`s each; `figures/` and `replication/` were copied and
  `tables/` was not, so the bundle carried two `.tex` files against thirteen
  `\input` directives and could not compile.
* **The numbers gate never saw them.** It scanned only the draft, found no
  `tabular`, and reported a pass having traced zero cells — a green tick
  indistinguishable from one that checked every number. Expanding `\input`
  before scanning takes it from 0 traced cells to 346.
* **The provenance graph was empty.** Edges are derived from the run's gate
  report, which recorded no matched cells, so the bundle asserted that every
  number traces to a file while carrying no trace for any number. Now 385
  edges: 346 `table_cell`, 33 citation, 5 figure, 1 estimation.
* **Severity was decided by proximity.** A cell's fate depended on distance to
  the closest value anywhere in the source JSON, so a tampered cell was graded
  "major" rather than critical and did not gate.

New `tables` check: `e2er verify` re-renders the declared tables with the
renderer itself and compares bytes. A difference means the shipped table is
not what the sidecars produce, which needs no heuristic to answer. Coverage is
part of the verdict — tables the paper includes that the renderer does not
produce are named, not implied.

`integrity` now fails a bundle that ships rendered tables and records no
`table_cell` edge, and reports how many cells the graph traces.

### `examples/showcase/`

A real bundle, from the first completed run under `--governance full`: a DiD
on a coin-month panel around the January 2024 spot-ETF approval, with an event
study, a daily rolling-window DiD, a returns-level triple difference, and Chow
and Bai-Perron break tests. 69 files hash-verified, 346 traced cells, 33/33
citations. The test suite now asserts against it rather than against fixtures
the developer invented — which is how all four defects above survived 1341
tests.

### Fixed

* SSRF guard rejected public hosts on NAT64/DNS64 networks, where a public
  hostname resolves to `64:ff9b::<ipv4>` and Python reports the whole prefix
  as reserved. NAT64 and IPv4-mapped addresses are now unwrapped to the
  address the packet actually reaches — which also tightens the guard, since
  `64:ff9b::192.168.0.1` is blocked on the merits of the embedded address.
* `e2er doctor` reported an empty fallback directory as an active literature
  mode, appending "no PDFs/.bib found" to an otherwise-clean pass.
* Version strings drifted: `CITATION.cff` and the README BibTeX still said
  0.8.0, two releases behind PyPI.


### The researcher workflow — bring your own data and papers, branch across models, verify everything

This is the release's headline: E2ER stops being "a pipeline you configure"
and becomes a workflow a researcher directs. Four pillars, each with a
first-class command.

**(a) Bring your own data and your own papers.** `e2er init` now scaffolds
`data/` and `literature/` with READMEs explaining what each accepts, writes
`LOCAL_DATA_DIR` / `LITERATURE_DIR` into `.env`, and gained `--defaults` for
non-interactive/CI setup. `e2er doctor` gained two pure-local checks
(`byod_local_data`, `byod_literature`) that report what E2ER can actually see
— file counts by type, recursion, the three literature modes — so "why isn't
my data being used?" is answerable without a run. Fixed `e2er init`
environment drift: it wrote backend keys the config rejects (`codex_cli`,
`gemini_cli` instead of `codex`, `gemini`) and a `DATA_MODULE_ENABLED` toggle
that hasn't existed since data-module enablement became a computed property.
A test now instantiates `Settings(llm_backend=key)` for every key `init` can
write, so that class of drift can't come back.

**(b) Create a research question.** New `e2er rq --draft "<rough question>"`:
gathers the project's available data sources and local literature, makes one
backend call, and returns a structured `rq.json` — research question,
rationale, candidate variables, identification options, feasibility notes.
It is **advisory only and never creates a paper** (test-pinned): the
researcher reads it, edits it, and decides. `e2er run --rq-file rq.json`
consumes the result.

**(c) Different models, different versions, one comparison.** New
`e2er run-matrix "<RQ>" --backends a,b,c --repeats N` runs the same question
across k backends × n repeats into labeled sibling papers plus a
`matrix.json`. New `e2er compare <matrix.json|bundles>` then diffs what the
models actually *decided*: a design-choice matrix over `identification_spec.json`,
per-field agreement (modal share for scalars, mean pairwise Jaccard for sets),
within- vs between-backend variance, and divergent-field flags. The report
leads with the point: this is **measurement, not selection** — no run is
promoted, nothing is auto-picked, and the preamble says so, because the value
is seeing the solution space, not shopping for a result.

Human-in-the-loop: `e2er run --review-at STAGE` (repeatable) pauses the run
after any pipeline stage. Inspect or edit the workspace, then
`e2er resume <paper_id>` approves that checkpoint and continues — built on the
existing pause/resume + `.pipeline_state.json` machinery, with a Resume button
in the web UI.

**(d) Everything verifiable.** Every export bundle now carries
`provenance.json`: a SHA-256 inventory of every file plus a derivation graph
reconstructed from the gate reports already in the bundle — table cells → the
source JSON key they trace to, citations → registry + DOI, figures → the
figure spec, estimation → the executed script and its log, data → the recorded
queries. Schema at `docs/schemas/provenance.schema.json`.

New `e2er verify <bundle>` is the reviewer's cheap-verification moment:
offline, keyless, sub-second. It re-hashes every file against the manifest,
**recomputes** the numbers and spec checks from the bundled artifacts (the
recomputation is authoritative — an edited report is caught, not trusted), and
resolves every `\cite` against `refs.bib`, treating the bundled registry
result as a snapshot. `--online` re-queries the live registries. A tampered
number, a tampered report, a deleted file, and a broken citation are each
caught. Export also now includes `identification_spec.json` (under `design/`)
and the `replication/` directory, without which the spec check had nothing to
check.

### Governance regimes — the institutions became a switch, so their effect is measurable

- **`--governance off | contracts | full`** (also `GOVERNANCE` in `.env`,
  persisted per paper). `full` is the existing behaviour; `contracts` keeps
  only the specialist output contracts; `off` blocks on nothing.
- **Shadow mode.** A mechanism that isn't enforced still **runs**: it computes
  its verdict and logs `gate_shadow` instead of `gate_enforced`. So an
  ungoverned run doesn't merely fail differently — what the institutions
  *would* have caught is recorded, which is what makes fabrication measurable
  rather than absent. The regime is disclosed in the export bundle's README
  and in `provenance.json`, so a bundle can't quietly hide how it was produced.
- **New `src/core/governance.py`** holds the single enforcement matrix, read by
  both the strategist runner (the three deterministic gates) and the specialist
  layer (output contracts + cascade guard). Unknown regime strings fail closed
  to `full`.
- **Experiment driver** (`scripts/experiment_driver.py` + a YAML config, e.g.
  `experiments/governance_pilot.yaml`): runs the same RQs across regimes × N
  repeats and harvests per-run fabrication counts (critical number mismatches +
  citations missing from the bib + unverifiable citations), completion, and
  shadow/enforced gate failures into `results.csv` + `summary.md`.

### Cross-pipeline citation audit

- New `scripts/verify_external_paper.py` / `src/core/external_verify.py` runs
  E2ER's citation-verification chain (OpenAlex → Semantic Scholar → Crossref)
  over papers E2ER did not write, from their `.bib` reference lists, producing
  per-paper and aggregate "X% of citations verify" reports. Lets the same
  mechanical check be pointed at other pipelines' output.

### Per-paper backend and model override

- `e2er run --backend <name> [--model <id>]` overrides the LLM backend for a
  single paper without restarting the server (the backend used to be
  process-global via cached settings). This is the enabler for `run-matrix`
  and the governance experiment. `papers.backend` column added, with an
  idempotent SQLite backfill for existing databases.

### Fixed — the governance experiment's own measuring instrument

Found by running the pilot (3 regimes × 3 repeats) for the first time. The
metric would have reported **zero fabrication on a run carrying 166 fabricated
numbers**, so a successful-looking experiment would have produced a confidently
wrong null.

- **Prose numbers were invisible to `fabrication_count`.** The harvester counted
  only table cells (`mismatches[].severity == "critical"`). Pilot run `ab95fcba`
  reported `total_values_in_tables: 0` with an empty `mismatches` list — and
  `prose_total: 278`, `prose_mismatched: 166`. Measured fabrication: 0.
  `prose_mismatched` is now counted and reported as its own column.
- **Skipped checks were counted as clean ones.** A citation check that finds no
  bibliography writes `passed: true, total_cites: 0, skipped_reason: …`; the
  harvester read the zeros as "no fabrication". Same skipped-is-not-verified
  error as B-4 in `e2er verify`. Rows now carry `checks_skipped` and `measured`,
  and per-regime means are taken over measured runs only.
- **Non-completed runs contributed structural zeros.** Bundles are exported only
  when a run completes, so `rejected`/`failed` runs — exactly the ones most
  likely to carry fabrication — harvested nothing and averaged in as 0. This
  biased the experiment *toward the null it exists to test*. Harvesting now
  falls back to the paper's workspace, which holds the same reports.

### Fixed — five bugs found by a full review of the above

- **The `contracts` regime was dead code, and `off` still blocked.** The regime
  reached the three deterministic gates but not the specialist-contract layer,
  which is where output contracts are actually enforced. Under `--governance
  off` a missing canonical artifact still raised (run FAILED) and a hollow one
  still flipped the specialist to failure, tripping the circuit breaker after
  three attempts (run PAUSED). `off` and `contracts` were therefore
  indistinguishable, and the experiment's control cell was not a control. The
  regime is now threaded runner → dispatcher → `run_specialist`; under `off`
  the contract check still runs and logs `gate_shadow`, but does not flip
  success, write coaching feedback, or raise. Operational limits (budget cap,
  backend errors, the circuit breaker itself) remain regime-independent — they
  are not verification institutions.
- **Per-paper backend override picked the wrong model.** The model default was
  resolved against the process-global backend, so `--backend openrouter`
  without an explicit `--model` sent a bare `claude-sonnet-4-5` to OpenRouter
  (which needs the `anthropic/` prefix) and every specialist call failed — on
  exactly the multi-backend path `run-matrix` and the experiment use. Adds
  `Settings.default_model_for(backend)`; `default_model` is now defined as
  `default_model_for(llm_backend)`, so the two cannot drift.
- **`provenance.json` recorded `source: null` for every table cell.**
  `verify_numbers` records source keys prefixed with the source *filename*;
  the provenance builder re-flattened the JSON without that prefix, so the
  lookup never matched and per-cell attribution — the headline of the
  provenance work — was null 100% of the time. Now matches the filename
  prefix. (The original test used an unprefixed key and so passed against the
  bug; it now runs the real producer.)
- **`e2er verify` claimed success when it had checked almost nothing.** The
  verdict counted only failures, so a partial bundle — export is best-effort
  and can omit `paper.tex` — printed "Bundle verified — hashes, numbers, spec,
  and citations are internally consistent" and exited 0 having verified only
  hashes. A skip is not a pass: the verdict now names what ran and what was
  skipped, and exits non-zero when no content check ran at all.
- **`e2er run --rq "<RQ>"` crashed with a traceback.** argparse prefix-expanded
  `--rq` to `--rq-file` and tried to open the research question as a filename.
  `run` and `run-matrix` now take an explicit `--rq`, and an unreadable
  `--rq-file` reports one line instead of a stack trace.

### README reframed around the workflow

- The README now leads with the four-pillar workflow and the verification
  thesis rather than a feature list, adds a command table and a "For reviewers"
  section (a keyless, $0 path from install to a verified bundle), and surfaces
  the BYOD scaffolding and the three literature modes.

### Deep revision loop — referees can send the research back, not just the prose

- **`MECHANISM_FAIL` re-does the research instead of terminating.** When the
  mechanism reviewer rejected a paper's *research* (mechanism not computed /
  not convincing — score < 5), the verdict was a **terminal REJECTED**. The
  only review-driven loop that existed, `patch_revisor`, edits prose — it
  cannot recompute an out-of-sample test or re-source a dataset — so the
  referee's substantive findings (sequential validation surfaced exactly this:
  real papers rejected on "the decisive OOS test was never computed") had
  nowhere to go. `_run_revision_phase` now treats `MECHANISM_FAIL` as a trigger:
  it re-dispatches the **research specialists** (`data_analyst` →
  `econometrics_specialist`) and the writer with the **referee reports as
  guidance**, re-renders the deterministic tables, re-drafts, then **re-runs the
  full review** (gates + reviewers) and re-decides — the way a researcher
  responds to a referee.
- **Bounded and terminating.** One deep round (`_MAX_DEEP_REVISIONS = 1`); the
  re-review re-enters the revision phase with the budget spent, so a verdict the
  round can't lift falls through to REJECTED. No infinite loop (regression-
  tested). `MAJOR_REVISION` keeps its existing light prose-patch path unchanged;
  `HARD_REJECT` stays terminal (unsalvageable).
- Tests: +2 (`test_patch_revision_wiring.py`) — MECHANISM_FAIL → research
  re-dispatch with referee feedback → re-review → COMPLETED; and the bounding
  guarantee (exactly one deep round → REJECTED). All existing revision tests
  unchanged.

### Post-execution error feedback — specialists fix their own script crashes

- **Recovers E2ER v1's self-debugging loop inside v3's sandbox.** v1's
  analysis workers had `Bash(python3:*)` and iterated write→run→see-error→fix
  within their turn, so codegen bugs (a bad pandas/numpy idiom) were fixed
  silently. v3 sandboxes execution (no general code tool — the runner runs the
  script post-hoc), so a bug like `'numpy.ndarray' has no attribute 'values'`
  crashed the script, left `estimation_results.json` empty, and failed the
  paper — the model never saw the traceback (it wrote the script blind). This
  is what failed the capstone run (`c141a277`).
- **Fix:** `post_execution.read_execution_error()` reads the crash captured in
  the convention's audit log (`run_estimation.log`) — non-zero exit + empty
  sidecar — and `run_specialist` injects that traceback into the specialist's
  **next** attempt's prompt ("your script crashed: …, fix this bug, don't write
  `{}`"). The model still never runs code; the runner does and just reports
  back, so the security model is unchanged. Turns "write blind → crash → fail"
  into "write → see the traceback → fix → succeed".
- Self-limiting: returns `None` once the sidecar is populated (success) or the
  last run exited cleanly. Covers `econometrics_specialist` + `data_analyst`
  (the specialists with execution conventions).
- Tests: +5 (`test_post_execution.py`) — feedback on crash, none on clean exit /
  populated sidecar / missing log / no convention, plus an end-to-end check
  that the traceback reaches the retry prompt and the fixed script succeeds.

### patch_revisor: partial revision is progress, not rejection

- **A MAJOR_REVISION no longer rejects the paper when only some edits land.**
  The M5 validation run (`0495a50d`) cleared every gate — populated tables,
  `verify_numbers` passed — then was REJECTED in revision because
  `patch_revisor` emitted one over-reaching `paper:full` edit alongside two
  good in-scope ones. The merger correctly dropped the out-of-scope edit (its
  scope-enforcement job — whole-document edits are exactly what the pipeline
  guards against), but `_run_patch_revision` treated *any* non-applied edit as
  fatal (`fully_applied` → else REJECTED), throwing away a near-complete paper.
- **Fix:** complete on progress. If at least one edit applied,
  `_run_patch_revision` transitions to COMPLETED and logs the dropped edits
  (out-of-scope or unmatchable) as non-fatal — mirroring the self-attack
  path's tolerance. REJECTED only when the patch achieved nothing (zero edits
  applied) or no patch file was produced (both unchanged). The merger and the
  scope-enforcement invariant are untouched.
- Tests: +1 (`test_patch_revision_wiring.py`) — in-scope edit applies +
  out-of-scope `paper:full` dropped → COMPLETED with the in-scope edit landed.
  Existing zero-applied → REJECTED cases still hold.

### Closed-loop table_spec key fix

- **Results tables no longer ship with blank cells.** When a `table_spec`
  reference can't be resolved even after the renderer's order-insensitive
  normalization (a genuinely wrong/abbreviated name — e.g. the drafter wrote
  `cw_stat` where the JSON has `clark_west_stat`), `PipelineRunner` now
  dispatches ONE `section_writer` fix with the unresolved references and the
  EXACT keys/fields available in `estimation_results.json` /
  `robustness_results.json`, then re-renders. Runs in `_run_review_phase`
  right before the verify gate; one attempt, then any still-unresolved refs
  stay `---` (and visible in `table_render_report.json`). Closes the loop the
  PR-2 feedback opened — normalization handles the common case, this handles
  the long tail.
- Tests: +4 (`test_table_spec_closed_loop.py`) — feedback lists available keys,
  no-op when nothing's unresolved, dispatch + fix lands the value.

### Table key-resolution + non-gating prose check (PR-2)

- **Cross-specialist key drift is auto-resolved.** The PR-1 validation run
  completed but its results tables came out **blank**: the econometrics
  specialist named specs `full_dp` while the drafter's `table_spec.json`
  referenced `dp_full`, so every column rendered `---`. The renderer now does
  **order-insensitive token matching** (`dp_full` ≡ `full_dp`) for `spec_key`,
  coefficient `var`, and stat `field`, resolving the drift deterministically.
  It matches only when exactly one candidate's token set is equal — never
  guesses on ambiguity or genuinely-different names (`cw_stat` ≠
  `clark_west_stat`). Resolutions are recorded in `table_render_report.json`
  (`normalized`).
- **Key-resolution feedback.** References still unresolved after normalization
  (a truly wrong/abbreviated/missing name) are surfaced by `verify_numbers`
  into `number_verification.json` (`table_spec_unresolved`), annotated with the
  available spec keys, so the drafter can correct `table_spec.json`. The
  `data/table-spec` skill now tells the drafter to read `estimation_results.json`
  and copy its exact keys, and to reconcile against the render report.
- **Prose-number check ("text = table number").** `verify_numbers` now also
  checks numbers in prose (outside tables) against the JSON sources.
  **Deliberately non-gating:** prose mismatches live in their own
  `prose_mismatches` list, are capped at `major` (never `critical`), and only
  flag *near-misses* — a prose number close to but off from a source value.
  Incidental numbers (years, section refs, %s) with no close source are
  ignored, so it reintroduces no false positives; it cannot reject a paper.
- Tests: +4 renderer (token normalization, ambiguity refusal, genuinely-
  different-name stays unresolved), +5 `verify_numbers` (prose match / major-
  not-critical near-miss / unrelated-ignored / non-gating / feedback surfaced).
- **Follow-up:** a closed-loop re-dispatch (auto-fix `table_spec.json` from the
  feedback) is left for later; deterministic normalization already covers the
  validated case, and the feedback makes the rest visible.

### Deterministic results tables — render numbers from JSON, not by hand (PR-1)

- **Results-table numbers are now generated, not transcribed.** New
  `src/core/renderer/tables.py::render_tables()` reads a declarative
  `table_spec.json` (which specs are columns, which coefficients/statistics are
  rows) and fills the cells straight from `estimation_results.json` /
  `robustness_results.json` into `tables/<name>.tex`, which the draft
  `\input`s. A results-table number can no longer be fabricated or
  mis-transcribed — the failure mode the `verify_numbers` gate exists to catch,
  removed at the source. First-party deterministic code called by the runner;
  no LLM in the number path.
- **The model authors only the spec.** New `data/table-spec` skill (mirrors
  `data/figure-spec`); wired into `paper_drafter` / `section_writer`.
  `table_spec.json` is a best-effort sidecar (`SPECIALIST_OPTIONAL_SIDECARS`) —
  theory / design-without-estimates papers legitimately have none.
  `latex/tables` and `writing/cite-numbers-by-source` updated to route numeric
  tables through the spec (prose numbers still governed by cite-by-source).
- **`verify_numbers` false positives fixed.** The gate no longer reads LaTeX
  *structure* as data: `\multicolumn` rows (column-group headers, panel labels)
  are skipped and `\cmidrule` range args are stripped. This is exactly what
  rejected the M5 re-run (`92626bf8`) — `\multicolumn{6}`→"6",
  "Post-2008"→"2008", "Rolling 120"→"120" flagged as mismatches. Genuine
  fabrications in plain data rows are still caught (regression-tested).
- **Renderer is defensive + auditable.** Never raises; dynamic coefficient
  names, optional `forecast_evaluation`/`first_stage`, `null` fields, and
  empty-`coefficients` combination specs all render `---`. A `table_spec`
  reference to a missing key renders `---` AND is recorded in
  `table_render_report.json` (a *detectable* missing reference, not a silent
  wrong number). A pre-compile `ensure_input_stubs` guard backfills any
  dangling `\input{tables/...}` so a missing table can't abort compilation.
  Runner re-renders before both the verify gate and compile (idempotent).
- Tests: +19 `test_table_renderer.py`, +3 `verify_numbers` regression
  (multicolumn/cmidrule not extracted; fabrication still critical).
- **Follow-up (PR-2, not in this change):** retarget `verify_numbers` to check
  *prose* numbers ("text = table number") with conservative matching.

### Post-specialist execution — script discovery + output normalization (M5 re-run fix)

- **Hardens the runner-side execution from the previous entry** after the
  M5 re-run failed in the design phase
  ([`docs/internal/M4_RERUN_FINDINGS.md`](docs/internal/M4_RERUN_FINDINGS.md)). The first
  version keyed on a single hardcoded `run_estimation.py` /
  `estimation_results.json`; the re-run's specialist named its script
  `analyze.py` writing `analysis_output.json`, so the runner found
  nothing and no-op'd. The brittleness had moved from *"did the model run
  the script?"* to *"did the model name it canonically?"* — still a
  model-judgment dependency.
- **Script discovery** (`_discover_script`): an ordered list of canonical
  candidate names is tried first, then a `*.py` glob keeping the script
  whose source references the target sidecar or a declared alternate
  output. `ExecutionConvention` now carries `script_candidates` +
  `output_candidates` instead of a single `script`.
- **Output normalization** (`_normalize_output`): if the discovered
  script writes a populated alternate output (`analysis_output.json`)
  rather than the canonical sidecar, the runner copies it onto the
  canonical name so M4.3 sees it. Recorded in the audit log and on
  `ExecutionAttempt.normalized_from` / `.discovered`.
- **`data_analyst` execution convention** added (script →
  `summary_statistics.json`), same discovery/normalization machinery.
- **`figure_spec.json` is now a best-effort sidecar**
  (`registry.SPECIALIST_OPTIONAL_SIDECARS`): still prompted and checked
  by verify_numbers when present, but no longer hard-gated by M4.3 at the
  data-design boundary — it has no deterministic producer there (its
  values derive from analysis the model can't run). This is what
  unblocks the parallel design-phase batch.
- **Skill nudge** (`econometrics/estimation-results-schema.md`): explains
  the specialist has no code-execution tool, so the way to run estimation
  is to write `run_estimation.py` → `estimation_results.json` and let the
  runner execute it. Best-effort fast-path; discovery is the backstop.
- Tests: +6 in `test_post_execution.py` (glob discovery, output
  normalization, `data_analyst` convention) and +1 in
  `test_contract_check.py` (best-effort `figure_spec.json` not gated).
  Full suite green (841).

### Runner-side post-specialist execution (M5 prerequisite)

- **New `src/core/specialists/post_execution.py`** runs a specialist's
  declared script via `subprocess.run` before M4.3's contract check
  fires, when the script is on disk but the sidecar is empty. Closes
  the load-bearing M5 prerequisite identified in
  [`docs/internal/M4_DIAGNOSIS.md`](docs/internal/M4_DIAGNOSIS.md): in the M4 paper run,
  the econometrics specialist wrote a correct `run_estimation.py` and
  then chose to write `estimation_results.json` as `{}` (per the
  skill file's *"don't fabricate, write empty"* rule), so the paper
  shipped without findings and the mechanism reviewer correctly
  rejected it.
- **Mechanical, not prompt-based**: the runner executes via
  `subprocess.run`, not via the model's tool call. Backend-agnostic
  (works on every backend, even ones without code-execution tools
  exposed to the model). Idempotent (no-op when the sidecar is
  already populated). Auditable via `run_estimation.log` (subprocess
  exit code + full stdout/stderr).
- **Composes with M4.3 (not a replacement)**: post-exec is the
  positive path *"make the right thing happen"*; M4.3 stays the
  negative path *"refuse the wrong thing"*. If post-exec also fails
  (script error, timeout, data-shape mismatch), the sidecar stays
  empty and M4.3 flips the specialist to `success=False` exactly as
  today.
- **Registry-driven**: `EXECUTION_CONVENTIONS` maps specialist →
  script + sidecar + audit log + timeout. Starts narrow with
  `econometrics_specialist` + `run_estimation.py` +
  `estimation_results.json` (the M4 case). Extending to
  `data_analyst` (`build_panel.py` → `summary_statistics.json`) and
  `replication_packager` is a single-line addition after the first
  re-run validates the convention.
- Tests: 16 new in `tests/test_post_execution.py` — the M4 case
  (script writes populated JSON, sidecar gets populated, M4.3
  passes), script-errors path (audit log captures traceback, M4.3
  still rejects), exit-zero-without-writing path (M4.3 catches the
  silent failure), idempotency (populated sidecar = no-op),
  specialist without convention = no-op, plus six unit tests on
  the `_is_sidecar_populated` JSON-rules helper.

## v0.8.2 — 2026-06-10

Cumulative bugfix + capability release on the v0.8 line. Contains the
seven milestones (M1-M3 + M4.1-M4.3) that were developed against the
v0.9 plan in [`docs/internal/V0.9_PLAN.md`](docs/internal/V0.9_PLAN.md). They ship in
v0.8.2 because **the v0.9.0 tag is now gated on M5 producing a paper
that survives review under real conditions** — the v0.9 plan's own
*"install → trust loop closed"* bar. M1-M4.x are necessary but not
sufficient for that gate: the orchestration layer caught its own
failures correctly in the M4 live run, but the pipeline has never
produced a successful end-to-end paper. See
[`docs/internal/VERSIONING_RESET.md`](docs/internal/VERSIONING_RESET.md) for the
argument and [`docs/internal/M4_FINDINGS.md`](docs/internal/M4_FINDINGS.md) for the
live-run findings the M4.x fixes close.

The `Mi (v0.9 plan)` subsection headings below preserve the
cross-reference to the v0.9 plan document; the work itself ships on
the v0.8 line.

### M4.3 (v0.9 plan) — Specialist output-contract enforcement

- **New `src/core/specialists/contract_check.py`** validates that a
  specialist's declared artifact (primary + any sidecars in
  `SPECIALIST_SIDECAR_ARTIFACTS`) has non-trivial content before
  `run_specialist` returns success. Rules per file extension:
  - `.json` — must parse, and parsed value must not be `{}` / `[]` /
    `null`. Empty containers are the M4 failure mode.
  - `.md` / `.tex` / `.py` / `.txt` — at least 100 non-whitespace
    characters. A real specialist output is always a paragraph or more.
  - Other extensions — exists with size > 0.
- **Wired into `run_specialist`**: when the tool_loop returns
  `success=True` but contract check fails, the result is flipped to
  `success=False` with the error prefixed `contract violation: …`.
  The circuit breaker then trips after `_MAX_SPECIALIST_ATTEMPTS=3`
  consecutive failures, halting the run with `PAUSED` instead of
  paying the rest of the pipeline.
- **Closes M4 finding #4 — the biggest of the three follow-ups**: in
  the M4 paper run `econometrics_specialist` returned `success=True`
  but `estimation_results.json` was literally `{}`. The pipeline then
  burned 13.7M tokens / 29 specialist calls writing a paper around a
  hollow result before the mechanism reviewer caught it. Post-M4.3
  that single empty JSON file flips the econometrics specialist to
  failure and the run pauses at the contract boundary instead.
- **Tests**: 21 in `tests/test_contract_check.py` covering the M4
  regression (`estimation_results.json == "{}"`), empty list/null/
  whitespace JSON, invalid JSON, short prose/code, whitespace-only
  files, missing files, nested relative paths, unknown extensions,
  primary + sidecar combinations per specialist, and an
  integration test that runs `run_specialist` with a fake backend
  that writes a hollow sidecar and confirms the result is flipped
  to `success=False` with the right error.
- **Conftest mocks bulked**: pre-M4.3 the mock specialist outputs
  were short stubs (e.g. `"Formula check passed."` = 22 chars). The
  contract check would have false-tripped on them. Updated all
  mocks in `_SPECIALIST_OUTPUTS` to be paragraph-length so they
  match what a real (skill-driven) specialist emits at minimum
  substance; mock sidecars added (`summary_statistics.json`,
  `figure_spec.json`, `estimation_results.json`) so reflexive
  mocks of `econometrics_specialist` / `data_analyst` still pass.

### M4.2 (v0.9 plan) — `verify_citations` parses `\bibitem` bodies

- **New `parse_bibitem_entries(tex)`** in `src/core/pipeline/verify_citations.py`:
  parses the text between consecutive `\bibitem` commands (and between
  the last `\bibitem` and `\end{thebibliography}`) into a bib-shaped
  dict `{cite_key: {title, year, doi}}`. Extracts:
  - **DOI** anywhere in the body (`10.xxxx/yyyy`, with optional `doi:`
    / `https://doi.org/` prefix; trailing punctuation stripped).
  - **Year** from the first `(YYYY)` in the body, falling back to the
    `\bibitem[label]` year when the body uses an unparenthesised form.
  - **Title** between the closing `(YYYY).` of the author block and
    the start of the `\textit{...}` / `\emph{...}` block that wraps
    the journal name. Falls back to "first sentence after the year"
    when no italic journal marker is present.
- **Replaces the degenerate fallback** in `verify()` that constructed
  `{key: {"title": ""}}` for `\bibitem`-only papers. Pre-M4.2 every
  cite came back `unverifiable` with explanation *"bib entry has
  neither title nor DOI — nothing to verify"* — the M2 gate was
  silent on exactly the class of paper most likely to ship
  hallucinated cites.
- **Live-validated on the actual M4 paper draft**:
  - Before: `verified=0 unverifiable=9 missing_in_bib=0 total=9` →
    false-pass under warn-only default.
  - After: `verified=9 unverifiable=0 missing_in_bib=0 total=9` →
    real pass; every Welch-Goyal-replication cite (welch2008,
    clarkwest2007, campbell2008, rapach2010, goyal2024, paye2006,
    timmermann2008, stambaugh1999, cochrane2008) resolves via
    OpenAlex title-search.
- Closes M4 finding #2. 8 new tests including the M4 regression
  (exact Welch-Goyal `\bibitem` format), DOI extraction (raw + URL
  form), label-only year fallback, multi-entry, no-journal-marker
  fallback, end-to-end verify, and empty-body unverifiable
  preservation.

### M4.1 (v0.9 plan) — Cost tracker zeros for flat-rate CLI backends

- **`compute_cost(model, usage, backend=...)`** now returns
  `Decimal("0")` when `backend` is `claude_code`, `codex`, or `gemini`.
  The CLI help and v0.9 plan promise *"$0 if on the Claude Code /
  Codex / Gemini CLI backends"*; this is the implementation that
  makes that promise true. Closes M4 finding #1.
- Updated three call sites to pass `backend`:
  `core/specialists/base.py`, `modules/tracking/usage.py`,
  `core/strategist/runner.py` (`_in_memory_spent` for the budget
  cap's in-memory fallback). Test suite (`test_costs.py`) extended
  to pin the new contract: identical 2M-token usage costs $18.00 on
  `anthropic` and $0 on `claude_code`; unknown backend literals fall
  back to SDK pricing (defensive — a config typo surfaces as
  "expensive", not "free"); `backend=None` preserves legacy behaviour
  exactly.
- Background: in the M4 run, the default `--max-cost 5` cap tripped
  after the first heavy specialist on the `claude_code` backend
  (~$5.25 in fake compute_cost) — forcing an interactive
  `resume --max-cost 100` to keep the paper moving. With M4.1, the
  budget cap stays inactive on the $0 backends.

### M3 (v0.9 plan) — Open-access full-text reach

- **New OA-PDF resolver chain** (`src/modules/literature/oa_resolvers.py`)
  separate from the metadata-fetch chain. One job: produce an OA PDF
  URL for a DOI. Default order: **Unpaywall → OpenAlex → Crossref →
  Semantic Scholar**. Each adapter returns `str | None`; first hit
  wins. Closes M3 of the v0.9 plan.
- **`src/modules/literature/unpaywall.py`** — keyless polite-pool
  resolver. `find_oa(doi, email)` returns full `PaperMetadata`;
  `find_oa_pdf(doi, email)` is the chain entry point. Walks
  `best_oa_location.url_for_pdf` → `best_oa_location.url` → the
  full `oa_locations[]` list, so a paper with a green-OA copy in a
  non-default repository still surfaces.
- **`src/modules/literature/crossref.py`** — extended with
  `find_oa_pdf(doi)` that scans the `message.link[]` array for
  publisher-deposited `content-type: application/pdf` links. Catches
  cases where the publisher's own DOI record points at a PDF that
  Unpaywall hasn't indexed.
- **New `unpaywall_email` setting** (default `research@e2er.app`)
  identifies this client to the OpenAlex / Crossref / Unpaywall
  polite pools — all keyless, all require a contact in every request.
- **`LiteratureToolHandler._read_reference` falls through.** When the
  metadata chain (`doi_fetch_sources`) returns a paper with no
  `pdf_url`, the OA-PDF resolver chain runs. Per-handler-instance
  cache (`_oa_pdf_cache: dict[str, str | None]`): same DOI asked
  twice in a paper run pays the chain **once**; known-misses cache
  too, so retries don't keep hammering Unpaywall + Crossref + OpenAlex.
- **Live-validated** end-to-end: LeCun *Deep learning* (Nature 2015)
  surfaces via Unpaywall (`hal.science`) and Crossref
  (`nature.com/.../nature14539.pdf`); paywalled Science 2007 correctly
  returns no OA URL across all four resolvers.
- Tests: 24 in `tests/test_oa_resolvers.py` covering Unpaywall's
  4-step URL preference, Crossref's PDF-link picker (case-insensitive,
  missing-field, no-PDF), all four OA-resolver adapters (success +
  miss + exception), default chain order, the per-handler-instance
  cache (hit + miss + short-circuit-after-first-hit), and the
  `_read_reference` fall-through path.

### M2 (v0.9 plan) — Citation-integrity gate

- **New `e2er verify-citations` command + pre-review gate.** Mechanical,
  deterministic anti-hallucination for references: parses every
  `\cite`/`\citep`/`\citet`/`\citeauthor`/`\citeyear`/`\autocite`/
  `\textcite`/`\parencite` (plus starred variants and `\bibitem` for
  hand-rolled bibliographies) from the draft, then for each cited key
  verifies the bib entry exists via OpenAlex → Semantic Scholar →
  Crossref by DOI, then by fuzzy title+year match across the same
  three sources. Emits `citation_integrity.json` with per-key status,
  verifier source, matched DOI/title, plus a coverage report
  (cited-but-not-bibbed, bibbed-but-not-cited).
- **Verdict policy** (open question from the v0.9 plan, M2): default
  is **hard-block on `missing_in_bib`** (cite key not in
  `references.bib` — LaTeX would also fail, unambiguous bug) and
  **warn-only on `unverifiable`** (working papers, conference posters,
  industry whitepapers legitimately aren't in OpenAlex/S2/Crossref).
  Flip to hard-block on unverifiable with
  `E2ER_STRICT_CITATION_INTEGRITY=true`.
- **Title-match heuristic, year-gate graduated by match strength:**
  fuzzy matches (0.85 ≤ sim < 0.99) require year within ±1 to reject
  unrelated papers from different decades; exact-title matches
  (sim ≥ 0.99) accept any year. Live-test surfaced the failure mode
  this fixes: OpenAlex's top hit for "Attention Is All You Need" was
  a 2025 reprint; with a strict ±1 gate the canonical 2017 paper
  would never verify.
- **New `src/modules/literature/crossref.py`** — keyless Crossref
  provider (`fetch_by_doi`, `search_papers`) mirroring the existing
  OpenAlex / S2 modules. Joins the verifier chain for citation
  integrity now; M3 will extend it for OA full-text resolution.
- **Wired into the pre-review gate** in `strategist/runner.py` right
  after `verify_numbers`: a paper with hallucinated cites (or, under
  strict mode, unverifiable ones) is rejected before reviewer
  specialists spend tokens — same gating pattern, same `REJECTED`
  terminal status.
- Tests: 29 new in `tests/test_verify_citations.py` covering parse
  (8 cite-command variants + comments + escaped `\\%`), normalization
  (DOI URL prefixes, accented titles, LaTeX braces), title-match
  graduated year-gate, end-to-end happy path, missing-in-bib fail,
  unverifiable warn-vs-strict, DOI-chain fallthrough to title search,
  persistence to `citation_integrity.json`, and CLI registration.

### M1 (v0.9 plan) — `e2er doctor` user-facing preflight

- **New `e2er doctor` command.** Answers "am I ready to spend a paper run?"
  before the user does — checks the LLM backend (CLI on PATH for `$0`
  backends, API key set for SDK backends), bundled skill files, DB (SQLite
  default or Postgres reachable), and probes every configured data +
  literature provider with a one-line "what this paper would have access
  to." Verdict: ✅ Ready / ⚠️ Partial (paper runs work, some providers
  unavailable) / ❌ Blocked (backend, DB, or skills missing — exact fix
  surfaced). `--json` for scripting. Closes M1 of the v0.9 plan.
- **Fast, quiet DB probe.** The Postgres reachability check uses a direct
  `psycopg.AsyncConnection.connect(connect_timeout=5)` instead of going
  through the runtime connection pool — preflight now fails in ~5s instead
  of hanging 30s with retry spam when `DATABASE_URL` points at a Postgres
  that isn't running. Error message includes the actionable hint: unset
  `DATABASE_URL` / `POSTGRES_URL` to fall back to the zero-config SQLite
  default.
- **`scripts/live_check.py` refactored to a thin shim** over the new
  `src.doctor.run_provider_checks` engine. Dev harness and user-facing
  command now share the same probe code (DRY); live-check stays for nightly
  CI and for catching provider drift before users do.

## v0.8.1 — 2026-05-30

## v0.8.1 — 2026-05-30

Stability + corpus extensions. Bug fixes from a full code review —
**safety** (Allium guardrails no longer bypassed without a
`data_dictionary.json`; SQLite Allium-approval workflow works; SSRF
hostname resolution), **Lane-A robustness** (strategist JSON guards,
mechanism-gate, resume-status, single-order cascade), **Lane B/C wins**
(storage citations; OpenAlex/S2 null crash; `e2er run --acknowledge-
unproven`; FileToolHandler sandbox; OpenRouter `content=""`). Plus
user-driven additions: structured GitHub issue templates for data-source
and literature-provider requests, and `LOCAL_DATA_DIR` extensions
(comma-separated roots, recursive walk, PDFs staged into
`workspace/literature/` with `read_reference(path=…)`).

### Cross-lane

- **Structured GitHub issue templates** for the most common asks:
  `data_source_request` (provider, auth, coverage, example RQ) and
  `literature_provider_request` (capability, gap, auth). Both routed by
  `lane-*` / `provider-request` labels. Generic feature requests still go
  via `feature_request.md`.

### Lane A — Pipeline

- **Fix: malformed strategist JSON no longer crashes the paper.**
  `ceiling_check` and `run_self_attack` did a bare `json.loads` on LLM
  output — truncated/invalid JSON raised and failed the whole run. They now
  use the tolerant `extract_json` and skip malformed `WorkOrder`/finding
  items instead of raising.
- **Fix: a missing mechanism-reviewer score can no longer be silently
  accepted.** The Rule-1 mechanism gate no-op'd when the mechanism score was
  absent, letting a paper ACCEPT on the other reviewers' average. A missing
  (but expected) mechanism score now forces `MAJOR_REVISION`.
- **Fix: resume tolerates a bad/legacy persisted status.** `PaperStatus(
  state.last_status)` could raise `ValueError` and wedge a completed paper
  into FAILED on resume; it's now coerced with a safe fallback.
- **Fix: tier-0 context builder handles explicit-null manifest fields**
  (`datasets: null` / `research_question: null`) instead of `TypeError`.

### Lane B — Literature

- **Fix: `store_paper` persists citation counts.** `citations` was in the
  `ON CONFLICT DO UPDATE` clause but missing from the INSERT column list, so
  inserts dropped the count and conflict-updates zeroed it. Added to the
  insert.
- **`LOCAL_DATA_DIR` extensions.** Accepts a **comma-separated list** of
  roots, an opt-in **`LOCAL_DATA_DIR_RECURSIVE=true`** to walk
  subdirectories (paths under `workspace/data/` are preserved), and now
  also **stages `*.pdf` into `workspace/literature/`**. The bib-relevant
  specialists' reference summary lists those local PDFs so they can be
  read via the new `read_reference(path=...)`. New
  `src/modules/local_corpus.py` consolidates parsing/walking;
  `LocalBibLibrary` uses it for `.bib` discovery across multiple roots.
- **`read_reference`** accepts a new **`path`** argument (workspace-
  relative) for the staged local PDFs — no download, no auth, sandboxed
  under the workspace root.

### Lane C — Data

- **Fix (safety): guardrails no longer fully bypassed without a data
  dictionary.** `_query_allium` only ran `validate_all` when a
  `data_dictionary.json` was present, so a production query with no
  dictionary ran with ZERO validation. Now the structural rules (no
  `SELECT *`, time-bound) and feasibility-first/approval gate always fire;
  only the field-whitelist (Rule 2) is dictionary-gated (skipped with a
  warning).
- **Fix: audit inserts generate app-side UUIDs.** `log_query` /
  `create_approval_request` relied on a DB id default; SQLite has none, so
  `id` was NULL and the approval-request join silently never surfaced
  pending production queries on the default SQLite DB. Now both generate a
  `uuid4()` client-side — the Allium approval workflow works on SQLite.

### Cross-lane

- **Fix: cost-estimate labeling for the codex/gemini backends.** `app.py`
  checked `codex_cli`/`gemini_cli`, but the real backend literals are
  `codex`/`gemini`, so synthetic cost figures were mislabeled as real.
- **Fix: `literature_kb_enabled` honors `DATABASE_URL`.** It keyed off
  legacy `postgres_url`/`db_password`, leaving the pgvector KB silently off
  for the documented `DATABASE_URL=postgresql://…` path. Now derived from
  the resolved DB URL.
- **Fix (security): SSRF guard resolves hostnames.** `_check_url` only
  blocked literal private IPs; a hostname (e.g. `metadata.google.internal`
  → 169.254.x, or `localhost`) slipped past. It now resolves the host and
  blocks if any resolved address is private/loopback/link-local.
- **Fix: `e2er run --acknowledge-unproven` flag.** The CLI hardcoded
  `acknowledge_unproven_tuple=True`, silently disabling the $1 first-run
  floor (and the README documented a flag that didn't exist). The flag now
  exists (default off → floor enforced for metered backends); the $0
  flat-rate CLI backends (claude_code/codex/gemini) auto-acknowledge.
- **Fix: single-order dispatch gets the cascade guard.** The missing-
  canonical-artifact check ran only in `execute_parallel`; a lone specialist
  could "succeed" without its artifact and starve downstream work. Extracted
  `assert_artifacts_written`, now applied to both paths.
- **Fix: `FileToolHandler` sandbox uses path containment, not a string
  prefix** (a sibling workspace with a prefix name could escape).
- **Fix: OpenRouter tool-only turns send `content=""`** instead of `null`
  (some OpenAI-compatible servers reject `null` content + tool_calls).

## v0.8.0 — 2026-05-28

Pluggable data & literature providers. Specialists now **discover** data
sources in light of the research question — FRED and yfinance reach the
tool loop via `list_data_sources` + a unified `fetch_data`, and Allium sits
behind a `Warehouse` capability (its 5 guardrails unchanged). They also
pull the researcher's own reference library (local `.bib`, `LOCAL_DATA_DIR`,
and **Zotero** via the Web API) and read **full-text PDFs** (`read_reference`).
Both lanes are now registry-pluggable, so new providers are drop-in.

### Cross-lane

- **`scripts/live_check.py` — live smoke harness.** Exercises the real
  data/literature provider paths (yfinance, FRED, Allium connectivity,
  OpenAlex search, `read_reference` on an OA PDF, Zotero library) against
  live services, auto-skipping providers without credentials. No LLM calls
  (free). Complements `make smoke` (offline/mocked) and `make smoke-paid`
  (full LLM run). Run: `python scripts/live_check.py`.

### Lane C — Data

- **Allium folded behind a `Warehouse` capability (M3b of
  `docs/internal/MODULARIZATION_PLAN.md`).** Allium is now a first-class registered
  provider: `AlliumWarehouse` owns its `card()`, `tools()` (→ `ALLIUM_TOOLS`)
  and `handler()` (→ `DeferredAlliumToolHandler`); `_run_pipeline` assembles
  it by iterating `warehouses(settings)` instead of hardcoding, and the
  catalog builds its card from the warehouse. Pure refactor — same condition
  (Allium key present), same tools, **the 5 `QueryValidator` guardrails and
  approval flow are untouched**, and `has_allium`/`data_module_enabled` are
  unchanged. Completes the Lane-C registry (series + warehouse).
- **Series data in the agent loop + RQ-aware discovery (M3a of
  `docs/internal/MODULARIZATION_PLAN.md`).** FRED and yfinance are no longer
  CLI-only — specialists reach them in the tool loop. New `SeriesFetcher`
  capability + data registry (`providers.py`, `registry.py`) mirror the
  Lane-B pattern. Two new tools: `list_data_sources` (serves the registry
  catalog so the agent picks the right source for the research question)
  and a unified `fetch_data(provider, method, params)`. Allium is unchanged
  — it keeps its guarded `query_allium` tool and is advertised in the
  catalog (the 5 guardrails are untouched). Series tools are always on
  (yfinance needs no key); budgeted (`_MAX_FETCHES=20`). M3b will fold
  Allium behind a `Warehouse` capability into the same registry.

### Lane B — Literature

- **Fix: literature search crashed on OpenAlex/S2 explicit nulls.** A live
  search returned 0 papers because `openalex._parse` raised
  `'NoneType' object has no attribute 'get'` on a result whose
  `primary_location.source` (or `open_access` / `authorships`) was an
  explicit `null` — `.get(k, default)` doesn't apply the default for a
  present-but-null value. Both parsers now guard with `or {}` / `or []`.
  Regression tests added (the mocked payloads previously only used
  well-formed fields, so the bug only surfaced live).
- **Full-text `read_reference` tool (M2.5 of `docs/internal/MODULARIZATION_PLAN.md`).**
  Specialists can now read a reference's PDF in full to deepen the lit
  review, not just its abstract. New `read_reference` literature tool takes
  a `pdf_url` (surfaced in search/fetch results and on `[PDF]`-marked
  reference-list entries, incl. Zotero attachments) or a `doi` (resolves an
  open-access PDF). Downloads (auth'd for Zotero hrefs, `/file/view` →
  `/file`), extracts text via **pypdf** (`pdf.py`), and returns it
  truncated to ~20K chars. Tightly budgeted (`_MAX_READS=6` + per-read char
  cap) given the prior 522K-token literature blowup. `fetch_bytes` gained a
  `max_bytes` override (PDFs exceed the 2 MB default). New `pypdf` dep. New
  `ZoteroLibrary` `ReferenceLibrary` reads the researcher's Zotero library
  via the Web API's native JSON (`zotero.py`), maps items to
  `PaperMetadata`, and captures each item's primary PDF attachment href
  (for the planned on-demand `read_reference` tool, M2.5). Config:
  `ZOTERO_API_KEY` + one of `ZOTERO_USER_ID` / `ZOTERO_GROUP_ID`; merged
  into the reference summary after local `.bib`, deduped by (title, year).
  Unset → no-op. Sync `fetch_text_sync` helper added for the (sync)
  reference-library path. Degrades to `[]` on any Zotero error — can't
  break paper creation.
- **Provider interface + registry (M1 of `docs/internal/MODULARIZATION_PLAN.md`).**
  Formalized the de-facto interface the source modules already shared into
  capability sub-types — `SearchSource` (web discovery; OpenAlex, arXiv,
  Semantic Scholar) and `ReferenceLibrary` (the researcher's own corpus;
  `LocalBibLibrary` over `LITERATURE_BIBTEX_FILE` + `LOCAL_DATA_DIR`) — in
  new `providers.py` / `registry.py`. `LiteratureToolHandler` and
  `_load_reference_summary` now iterate the registry instead of hardcoding
  provider names. Pure refactor: the search (OpenAlex→arXiv) and DOI-fetch
  (OpenAlex→S2) fallback chains are reproduced exactly; +13 tests, no
  behaviour change. This is the seam Zotero (M2) and Citavi (M4) plug into.

## v0.7.3 — 2026-05-26

Fix the patch_revisor section-target resolution bug surfaced by
the v0.7.2 live re-validation on paper `7f4f2363`. The drafter
got a paper all the way through to the revision phase (v0.7.0's
verify_numbers parser fix worked), but the patch_revisor emitted
edits targeting canonical section names (`section:results`,
`section:mechanism`) that didn't exist in the actual draft. The
merger reported "target region not found" with no hint and the
paper REJECTED on parser bugs, not real hallucinations — for the
second release in a row.

### Lane A — Pipeline

- **Merger emits "did you mean..." suggestions on section/table
  not-found.** When `apply_edit` can't resolve a `section:` or
  `table:` target, the error message now appends the list of
  available section titles or labelled tables in the document.
  Example before/after:
  - Before: `target region 'section:results' not found in document`
  - After: `target region 'section:results' not found in document (available sections: 'Introduction', 'Identification Strategy', 'Empirical Strategy', 'Discussion')`
  Two new public helpers: `list_section_titles(text)` and
  `list_table_labels(text)`. Suggestions are suppressed when the
  list is empty (avoids the misleading
  `(available sections: )` suffix on minimal LaTeX skeletons).
  Universal targets (`paper:full` / `abstract` / `references`)
  don't get suggestions.
- **`writing/scoped-revision.md` skill update.** New section
  ("Before you compose any edits — list the draft's actual
  targets") instructs the patch_revisor to grep the draft for
  `\section{...}` and `\label{tab:...}` lines before composing
  patches. Explains the case-insensitive substring matching the
  merger uses, the common failure mode (canonical-name vs
  actual-heading mismatch), and the `paper:full` fallback for
  findings that don't have a dedicated section.

### Test counts

- Mocked suite: 598 passed (was 590 in v0.7.2; +8 here).
- 8 new tests in `tests/pipeline/test_patch_merger.py`:
  - 4 for `list_section_titles` and `list_table_labels` helpers.
  - 4 for the extended error: section suggestions, table
    suggestions, no suggestion for non-section/table targets, no
    misleading suffix when the list is empty.

## v0.7.2 — 2026-05-26

Closes the v0.7.1-noted follow-up: a CLI command to resume
paused / failed / zombie papers. Completes the status / cancel /
resume trio so the operator never has to drop down to curl.

### Cross-lane

- **`e2er resume <paper_id>`** — restart a paused or failed
  paper from the terminal. Optional `--max-cost N` raises the
  cap atomically with the resume (sent through to the v0.5+
  `ResumeRequest` body). Surfaces the paper's title + previous
  status + cap delta + `last_error` before issuing the POST, so
  the operator knows what they're restarting. Unlike `status`
  and `cancel`, this command DOES auto-start uvicorn — the user
  is asking the paper to start running again, so the server
  needs to be up.
  - 200 → prints the new transient status (`resuming`) +
    dashboard URL, optionally tails to terminal via `--tail`
  - 400 → surfaces the validation detail (e.g. non-positive
    cap) directly so the user can fix and retry
  - 409 → "already running" with a hint to `e2er cancel` first
  - 404 → "paper not found"
- **9 new regression tests** in `tests/test_cli_status.py`
  covering: no-cap-change happy path, cap-raise happy path,
  completed-paper short-circuit, 400 / 409 / 503 / 404 error
  paths, `--tail` integration, the API-unreachable branch.

### Test counts

- Mocked suite: 590 passed (was 581 in v0.7.1; +9 here).

## v0.7.1 — 2026-05-26

Two new lightweight CLI commands surfaced by the v0.7.0
fresh-install UX test: when `e2er run`'s tailer times out (or
the user ^C's it), there was no scripted way to re-attach,
inspect the current state, or cancel a runaway paper without
opening the dashboard.

### Cross-lane

- **`e2er status <paper_id>`** — one-shot snapshot of a paper:
  status, mode/methodology, cost meter (with the
  `cost_is_estimate` marker on CLI backends), specialist call
  count, token total, workspace path, dashboard URL. Shows
  `last_error` verbatim when present so the user can diagnose
  REJECTED / PAUSED / FAILED without parsing the events log.
  With `--tail`, re-uses the same polling loop `e2er run` uses
  so the user can re-attach after ^C. Short-circuits on already-
  terminal status (no wasted polls). Hits the local API by
  default; respects `E2ER_API_URL` for remote inspection.
- **`e2er cancel <paper_id>`** — POSTs the `/cancel` endpoint
  with a confirmation prompt (skippable via `--yes`). Surfaces
  the title + current status + spend-so-far before the user
  confirms so they don't cancel by accident. Terminal-status
  short-circuit. Treats post-cancel 404 as success (the paper
  finished while we were asking; that's what the user wanted).
  Brief post-cancel poll so the user sees the CANCELLED
  transition land before the shell returns.
- **Cost output now formats with two decimals.** Pre-fix
  `e2er status` showed `$8.462921999999999`; now `$8.46`. Float
  noise was reaching the user-facing string when the API
  returned high-precision cost totals.
- **`_poll_status` now treats `rejected` as terminal.** Pre-fix
  the `e2er run` tailer kept polling forever on REJECTED papers
  (a v0.5+ status it didn't know about). Observed during fresh-
  install testing on paper 2ca473aa.

### Test counts

- Mocked suite: 581 passed (was 554 in v0.7.0; +27 cli_status).
- 27 new tests in `tests/test_cli_status.py` covering
  formatters, exit codes, the unreachable-API branch, the
  confirmation prompt, and the post-cancel-404 race handling.

### Known follow-up (v0.7.2 candidate)

- `e2er resume <paper_id>` — natural complement to `cancel`.
  PAUSED papers can be resumed via `curl POST /resume` today;
  a CLI command would close the same UX gap that `status` and
  `cancel` close. Out of scope for v0.7.1.

## v0.7.0 — 2026-05-24

Better onboarding + a verify_numbers parser fix, bundled.
Surfaced by direct user feedback ("pip install e2er and then
what?") and by the v0.6.1 live run on paper `f79b7cd9` that hit
two false-positive critical mismatches caused by parser bugs.

### Cross-lane

- **New `e2er init` command — guided first-paper setup wizard.**
  Closes the post-`pip install e2er` onboarding gap. Walks the
  user through 4 steps (LLM backend pick + prereq check, data
  module on/off, optional BibTeX path, optional Postgres
  `DATABASE_URL`), an optional GitHub-integration prompt, then
  writes `./.env` (with confirm-overwrite), runs `e2er
  install-skills`, and prints three concrete example research
  questions to copy. Hand-rolled stdin wizard — no new
  dependencies (no `click` / `prompt_toolkit`). TTY-detected so
  non-interactive invocations exit with a helpful one-line guide
  instead of blocking on `input()`. Secrets discipline: GitHub
  PATs and API keys collected during the wizard are written to
  `.env` as comments, never as live env vars. 24 new unit tests
  in `tests/test_cli_init.py`. README quickstart updated to lead
  with `e2er init`.

### Lane A — Pipeline

- **Fix two `verify_numbers` false-positives**: ISO date strings
  in column headers (`2021-03-01`) were being parsed as the bare
  year `2021`, false-positive-mismatching against unrelated
  source values; and LaTeX brace-protected thousands separators
  (`1{,}573.89` — the form that survives math mode) were being
  split into two bogus numbers (`1` and `573.89`). Both surfaced
  on the v0.6.1 live-validation paper `f79b7cd9`, which was
  REJECTED entirely on parser bugs rather than real
  hallucinations. New `_normalize_cell(cell)` helper runs
  before `_NUMBER_RE` on each tabular cell: normalizes `{,}` →
  `,` so the existing thousands branch picks the value up
  intact, then strips ISO / slash / US date patterns so years
  inside dates don't leak as numeric claims. Bare years outside
  date context (e.g. `Sample size & 2021`) still extract — the
  fix is targeted at dates, not all four-digit numbers. 5 new
  regression tests in `tests/pipeline/test_verify_numbers.py`.

### Test counts

- Mocked suite: 554 passed (was 525 in v0.6.1; +24 wizard +5
  verify_numbers fix).

## v0.6.1 — 2026-05-23

Hot-fix on v0.6.0 closing the known follow-up surfaced by the
v0.6.0 live run on paper `3bc58e8d`.

### Lane A — Pipeline

- **Iterative-phase guard extended to drop the legacy `revisor`**
  on iterations 2+, alongside `paper_drafter`. Both specialists
  rewrite `paper_draft.tex` from scratch every time they run, so
  the same drift argument that motivated step 6's
  `paper_drafter` guard applies to `revisor`. v0.6.0's live run
  showed the strategist dispatching `revisor` during iterative
  phase even though `paper_drafter` was correctly skipped — the
  guard only filtered one. v0.6.1 closes the same door for both.
- **Strategist system prompt updated** to name `revisor`
  explicitly alongside `paper_drafter` in the iterative-phase
  rule, and to point at `patch_revisor` (dispatched automatically
  by the runner's revision phase) as the legitimate path for
  scoped revisions. Removes the v0.6.0 ambiguity where the prompt
  said "use `revisor` only when upstream artifacts are updated"
  but the runner now expects no `revisor` calls in iterative
  phase at all.
- **`test_section_writer_not_dropped_on_iteration_2` renamed** to
  `test_legitimate_specialists_not_dropped_on_iteration_2` and
  updated to reflect the v0.6.1 contract (was asserting `revisor`
  survives the guard, now asserts only the legitimate specialists
  do).
- **4 new regression tests** in `test_iterative_phase_guard.py`
  pinning the extended-guard contract.

Full mocked suite: 525 passed (was 521 in v0.6.0; +4 here).

## v0.6.0 — 2026-05-23

**Targeted-revision discipline.** Closes the three drift sources
identified in `docs/internal/V0.6_PLAN.md`: full-rewrite `revisor` on
MAJOR_REVISION, parallel-`revisor` write race in self-attack, and
unconstrained `paper_drafter` re-dispatch in the iterative phase.
Validated end-to-end on paper `3bc58e8d` (2026-05-22, 38 min,
$12.36 est., Sonnet via Claude Code CLI).

### Lane A — Pipeline

- **New `patch_revisor` specialist + deterministic merger.**
  Replaces the pre-v0.6 `revisor` in every dispatch site. Writes
  structured edits to `paper_draft.tex.edits.json`; the merger
  (`src/core/strategist/patch_merger.py`) validates each edit's
  `target` against the work order's `Finding` list, applies
  in-scope edits to `paper_draft.tex`, and emits
  `paper_draft.tex.applied.diff` as a unified-diff audit
  artifact. One edit type supported in v0.6: `replace_text`
  with `find` / `replace` / `find_must_be_unique`. Target
  schema: `section:<name>` / `table:<label>` / `references` /
  `abstract` / `paper:full`. Edits whose target isn't in the
  findings are rejected before any text is touched.
- **Structured `Finding` dataclass + three collectors.** New
  `src/core/strategist/findings.py` introduces the
  `Finding(source, source_detail, target, severity, problem,
  suggested_fix)` frozen dataclass that every revision source
  emits: `collect_self_attack_findings`,
  `collect_verify_numbers_findings`, `collect_review_findings`.
  `combine_findings` sorts severity-desc with source priority
  (verify_numbers > self_attack > review on ties — numerical
  mismatches are the most mechanical to fix).
- **MAJOR_REVISION wired through `patch_revisor`.** Replaces the
  pre-v0.6 free-text-rationale path. Combines review findings +
  (when present) verify_numbers findings, serialises them as a
  JSON block in the work order's `focus`, dispatches
  `patch_revisor`, calls `merge_patch_file`. fully_applied →
  COMPLETED; missing patch file or failed edits → REJECTED with
  the first 3 failures named in `last_error`. Edge case:
  MAJOR_REVISION with no actionable findings short-circuits to
  COMPLETED without dispatching (avoids wasted spend).
- **Self-attack critical findings wired through `patch_revisor`.**
  Eliminates the pre-v0.6 parallel-revisor write race. Top-3
  critical findings are batched into ONE patch_revisor call.
  Patch failures at this phase are advisory (logged, do NOT
  REJECT) — the downstream review phase catches what remains.
- **`verify_numbers` auto-patch loop (proactive gate).** Pre-v0.6
  the gate was defensive: critical mismatch → REJECTED. v0.6
  closes the detect → patch → re-detect loop: critical mismatch →
  dispatch `patch_revisor` with the mismatch findings → re-run
  `verify_numbers` on the patched draft → REJECTED only if the
  second pass still has criticals. Bounded by
  `_VERIFY_NUMBERS_AUTO_PATCH_BUDGET = 1` (single attempt) so a
  drafter that consistently disagrees with the source JSON
  doesn't loop. The persisted `number_verification.json`
  reflects the post-patch state.
- **Iterative-phase guard against `paper_drafter` re-dispatch.**
  Two-layer defence:
  - Soft: strategist's system prompt instructs it to use
    `section_writer` (scoped to a `section:<name>` focus) on
    iterations 2+, never `paper_drafter`. Validated on the live
    run — strategist used `section_writer` 3× in iter 2.
  - Hard: `_dispatch` drops `paper_drafter` work orders when
    `self._iteration >= 2`, logging a warning. Catches the
    strategist if it ignores the soft instruction. iteration 0
    (initial) and iteration 1 (first iterative) still allow
    `paper_drafter` legitimately.
- **`patch_revisor` loads three skills.** `writing/scoped-revision`
  (new — defines the patch-file shape with worked examples for
  verify_numbers and self_attack findings),
  `writing/cite-numbers-by-source` (v0.5 — same discipline as
  the drafter), `writing/personal-style`, `reasoning/anti-slop`.
- **Five architecture invariants pinned.** Each step has a
  primary regression test; `tests/pipeline/integration/test_v0_6_invariants.py`
  documents all five in one place and adds cross-step
  assertions (legacy `revisor` never dispatched by v0.6 runner
  paths; both source types reach `patch_revisor`'s focus when
  review + verify_numbers both have findings; merger
  scope-enforcement holds across dispatch sites).

### Test counts

- Mocked suite: 521 passed (was 422 in v0.5.0; +99 in v0.6).
- New test modules: `test_findings.py`, `test_patch_merger.py`,
  `test_patch_revision_wiring.py`, `test_self_attack_patch_wiring.py`,
  `test_verify_numbers_auto_patch.py`, `test_iterative_phase_guard.py`,
  `test_v0_6_invariants.py`.

### Known follow-ups (deferred to v0.6.1)

- The legacy `revisor` specialist is no longer dispatched by v0.6
  runner code paths, but the strategist may still freely dispatch
  it from `_run_iterative_phase`. Surfaced by the 2026-05-22 live
  run (one revisor call in iterative phase). Candidate fix:
  extend the iterative-phase guard to also drop `revisor` on
  iterations 2+, OR update the strategist prompt to discourage
  it explicitly.

## v0.5.0 — 2026-05-21

**Anti-hallucination & methodology-aware pipeline.** Full design
record at `docs/internal/V0.5_PLAN.md`. Motivated by v0.4.5 live tests on
papers `a6182f08`, `cbe8048f`, `eea5379b`, and validated end-to-end
against fresh live runs on 2026-05-20 (`234a11ea`, `fd6bf64d`) and
2026-05-21 (`525fa03c`) — see `docs/internal/V0.5_LIVE_VALIDATION.md`.

### Lane A — Pipeline

- **Programmatic anti-hallucination gate before review** (new file
  `src/core/pipeline/verify_numbers.py`, 357 lines). Scans every number
  in `\begin{tabular}` blocks of `paper_draft.tex` and matches each
  against the flat numeric values from `summary_statistics.json`,
  `estimation_results.json`, `robustness_results.json`, and
  `figure_spec.json`. Tolerance 0.5% relative; integers ≥10 must be
  exact; signs must match. Critical mismatches (relative error >10%
  vs the closest source value) → status `REJECTED` and reviewers
  never spawn. Persists `number_verification.json` at workspace root
  on every run. Live-test paper `a6182f08`'s "log realized variance
  falls by 0.41 ($t=-3.9$)" hallucination was caught by
  `technical_reviewer` only after 6 reviewers had run; this gate
  catches it deterministically, at $0, before any reviewer spends a
  token. Graceful skip when no source JSON files are present (warn +
  pass), so papers from before the analyst contract was tightened
  don't regress.
- **Methodology-aware phase routing.** `PipelineRunner.__init__` now
  accepts `methodology: str = "empirical"`, propagated from
  `papers.methodology` through `_run_pipeline` and `resume_paper` in
  the API. For `methodology == "theoretical"`,
  `_reviewers_for_methodology()` drops `data_reviewer` from the
  6-reviewer panel and `_run_replication_phase()` early-returns.
  Live-test paper `cbe8048f` burned ~$0.34 on a `data_reviewer` stub
  over an empty contract plus ~$0.43 on a replication packager with
  no replication artifacts — both wasted, both gone in v0.5.
- **New status `PaperStatus.REJECTED`, distinct from `FAILED`.**
  `FAILED` is reserved for crashes; `REJECTED` means the pipeline
  ran successfully and the quality gate (verify_numbers,
  HARD_REJECT, MECHANISM_FAIL) returned a negative verdict.
  Resumable: transitions back to IDEA / IN_PROGRESS / REVIEW /
  REVISION / CANCELLED. `_run_revision_phase`'s HARD_REJECT and
  MECHANISM_FAIL branches updated to emit REJECTED instead of
  FAILED. New IN_PROGRESS → REJECTED transition for the
  verify_numbers gate path.
- **`BudgetExceededError` → `PAUSED`, resumable.** New `except
  BudgetExceededError` branch in `PipelineRunner.run()`, alongside
  the existing `CircuitBreakerError` handler. Persists state, logs a
  `paused_budget` event with `{spent, cap}`, returns a structured
  `{status: "paused", reason: "budget_exhausted", ...}` payload.
  The operator raises `--max-cost` and POSTs
  `/api/papers/{id}/resume`; existing resume-from-disk logic picks
  up at the first incomplete phase. Previously a budget exhaustion
  was indistinguishable from a crash.
- **`PAUSED` and `REJECTED` rows now persist `last_error`** on the
  `papers` table. Pre-v0.5, only FAILED and CANCELLED rows carried
  the error/reason; PAUSED and REJECTED dropped it at the SQL layer,
  leaving the dashboard with `last_error=NULL` and no way to render
  the budget breakdown, circuit-breaker specialist, or review-gate
  rationale. `_update_status` now treats PAUSED and REJECTED the
  same way as FAILED and CANCELLED for error preservation.
  Discovered while writing the v0.5 budget-pause regression test.
- **`POST /api/papers/{id}/resume` accepts `max_cost_usd` in the
  request body.** Pre-v0.5 the endpoint silently ignored the body and
  read the cap from the DB row, so raising the cap on a budget-paused
  paper required a manual `UPDATE papers SET max_cost_usd = ...`
  beforehand (the workaround surfaced during the 2026-05-20 live
  validation). The endpoint now accepts an optional `ResumeRequest`
  body; a positive `max_cost_usd` is validated and persisted on the
  row atomically with the status reset, then passed to the runner.
  Zero or negative values 400. Calls without a body preserve the
  pre-v0.5 behaviour (use the existing row value).
- **`paper_drafter`, `section_writer`, `abstract_writer`, and
  `revisor` load a new `writing/cite-numbers-by-source` skill** that
  teaches the cite-by-JSON-key discipline: every numeric value in
  the paper must trace to a value in `summary_statistics.json`,
  `estimation_results.json`, `robustness_results.json`, or
  `figure_spec.json`. HTML-comment markers (`<!-- src: file#key -->`)
  let `verify_numbers` mismatches name the exact source path the
  drafter should have used. Reduces hallucination rate in the first
  place; complements the post-hoc gate. Includes the "empty sidecar
  → no quantitative claims" rule so the design-without-estimates
  pathway is explicit.
- **Test-mock fix:** `MockLLMBackend._detect_specialist` now matches
  on the canonical `You are the <Name> specialist` role line in the
  system prompt rather than searching for any specialist name
  substring. The old heuristic silently misrouted calls whenever a
  skill referenced another specialist by name (e.g. the new
  `writing/cite-numbers-by-source` mentions "econometrics
  specialist" → paper_drafter calls were routed to the econometrics
  output → paper_draft.tex was never produced). Now matches one
  occurrence per prompt with no skill-content interference.
- **Machine-readable JSON sidecar contract for verify_numbers.**
  Pre-v0.5 every specialist was told to write EXACTLY ONE file, so
  even when a skill described a JSON sidecar (e.g. `data/figure-spec`),
  the system prompt overrode it and the JSON never appeared. The
  2026-05-20 live runs confirmed this empirically: both papers wrote
  `number_verification.json` with `skipped_reason="no source JSON
  files found"` — the gate was effectively a no-op. v0.5 adds a
  `SPECIALIST_SIDECAR_ARTIFACTS` registry, a `sidecar_artifacts` field
  on `WorkOrder` (auto-populated by `_inject_context`), and a
  multi-file "Required Output" prompt block that lists every required
  file with its role + JSON validity rules. `data_analyst` now emits
  `summary_statistics.json` and `figure_spec.json`;
  `econometrics_specialist` now emits `estimation_results.json`
  (with optional `robustness_results.json`). Two new schema skill
  files (`data/summary-statistics-schema`,
  `econometrics/estimation-results-schema`) teach the JSON shapes and
  the "write `{}` instead of omitting when data was unavailable"
  rule that distinguishes "honest empty" from "missing" for the gate.

## v0.4.5 — 2026-05-19

Bug pack rolling up findings from the v0.4.4 live test (paper eea5379b)
that completed end-to-end on a fresh `pip install e2er`. The pipeline
itself works; these are correctness + clarity fixes around it.

### Lane C — Data

- **Fix nested workspace path on `--save-to`** (Lane C, replication
  correctness). The data_analyst subprocess runs with cwd at the paper's
  workspace dir; `_resolve_workspace` then resolved the relative default
  `workspace_root="workspaces"` against THAT cwd, so the CSV landed at
  `workspaces/<id>/workspaces/<id>/data/`. The model worked around this
  by emitting a `_candidate_csv_paths` fallback in estimation.py — a
  prompt-engineered band-aid for a pipeline bug. Fix: `_resolve_workspace`
  now prefers `$E2ER_WORKSPACE_ROOT` (claude_code injects the absolute
  path) over the relative settings default.
- **Inject absolute workspace_root into the claude_code subprocess env**
  (`E2ER_WORKSPACE_ROOT`) and use an absolute path as the subprocess cwd.
  Without both, the relative `workspaces` string can re-resolve at any
  nested call site.

### Lane A — Pipeline

- **Accept `pipeline_mode` as an alias for `mode`** in `CreatePaperRequest`.
  `e2er run --mode single_pass` reached the API as `pipeline_mode`,
  which Pydantic silently dropped → server fell back to the default
  `"iterative"` → first-run log line falsely reported the wrong mode.
  Also fix `src/cli_run.py` to send the canonical `mode` field.
- **Reword the first-run cap log line.** "override=True" read like the
  server overrode the user's cap; it actually meant the user acknowledged
  the unproven (model, methodology, mode) tuple so the $1 floor was
  lifted to their requested cap. New format spells it out:
  `cap=$20.00 (user_ack_unproven=True, first_run_floor=$1.00)`.

### Cross-lane

- **Label CLI-backend costs as estimates.** Anyone running on
  `claude_code` / `codex_cli` / `gemini_cli` sees Sonnet-rate synthetic
  dollars even though the Max plan absorbs the actual cost. Startup log
  now warns once when a flat-rate backend is selected; the `/api/papers/<id>`
  usage payload carries a `cost_is_estimate` flag so dashboards can
  render the number with the right hedge.
- **`e2er migrate` works on pip-installed wheels.** Old code pointed at
  `scripts/migrate.py` which is excluded from the wheel. Moved to
  `src/db/migrate.py` (importable, ships in the wheel), reads SQL files
  via `importlib.resources("sql")` with a dev-checkout fallback.
- **Drop the stale `_SCRIPTS_DIR` PATH entry on pip installs.** Guarded
  with `.exists()` so the resolved PATH doesn't carry a non-existent
  `site-packages/scripts/` directory that confused `which`-style probes
  inside the claude_code sandbox.

## v0.4.4 — 2026-05-19

Hot-fix over v0.4.3. The PATH-propagation logic added in v0.4.3 used
`Path(sys.executable).resolve().parent` to find the venv bin/ where pip
puts the `e2er-data` entry-point shim. On macOS framework venvs this is
wrong — `bin/python` in the venv is a symlink to the underlying
`Python.framework/Versions/3.12/Resources/Python.app/Contents/MacOS/Python`,
and `.resolve()` follows it, so `.parent` lands in
`.../Python.framework/Versions/3.12/bin/` — which does *not* contain the
venv's entry-point shims. Live test on run `3f921299` confirmed
`e2er-data` was still `command not found` even though the shim existed
at `/tmp/<venv>/bin/e2er-data`.

### Lane C — Data

- **Use `sysconfig.get_path("scripts")`** instead of `Path(sys.executable).resolve().parent`.
  `sysconfig.get_path("scripts")` is the canonical Python API for the
  current-install entry-point dir and returns the venv's own `bin/` on
  Linux, macOS framework venvs, and Windows alike. Verified: on the same
  venv where `.resolve().parent` returned the framework Python's bin,
  `sysconfig.get_path("scripts")` returns the venv's bin and the
  `e2er-data` shim exists there.

## v0.4.3 — 2026-05-19

Hot-fix over v0.4.2. The 0.4.2 wheel boots and the pipeline runs end-to-end,
but the `data_analyst` specialist hits `command not found: e2er-data` and
no data is ever fetched — so papers reach `paper_draft.tex` without any
real data behind them. Trace from run `62526787-da0b-4ebd-8cf9-cf4f3e682a04`
on the v0.4.2 PyPI wheel showed `which e2er-data` → not found inside the
claude_code subprocess, with PATH containing the venv's `site-packages/scripts/`
but not `bin/`. The skill files (`data/yfinance.md`, `data/fred.md`,
`data/allium*.md`) all instruct the model to invoke `e2er-data ...`.

### Lane C — Data

- **Register `e2er-data` as an entry point** in `pyproject.toml [project.scripts]`
  pointing at `src.modules.data.cli:main`. pip now installs a `e2er-data` shim
  next to `e2er` in the venv's `bin/`, so the bash wrapper from the dev
  checkout is no longer required on pip-installed systems.
- **Prepend the venv `bin/` to the subprocess PATH** in `claude_code.py`
  (after the dev `scripts/` dir, before the inherited PATH). Without this
  the entry-point shim is unreachable from the claude_code subprocess
  even after the shim is installed.

## v0.4.2 — 2026-05-18

Hot-fix over v0.4.1. The 0.4.1 wheel shipped only `.py` files + skill
markdown, but the runtime needs three other on-disk asset bundles: the
FastAPI static directory, the Jinja2 templates, and `sql/sqlite/schema.sql`
for the SQLite bootstrap. Without them, `e2er run` on a fresh
`pip install e2er` crashed at uvicorn startup with `RuntimeError:
Directory '.../src/api/static' does not exist`.

### Cross-lane

- **Ship runtime assets in the wheel**: `pyproject.toml` now declares
  `src.api` package-data (`static/*`, `templates/*`) and `sql` / `sql.sqlite`
  package-data (`*.sql`). Empty `sql/__init__.py` and `sql/sqlite/__init__.py`
  make `sql/` discoverable by `setuptools.packages.find`. Verified by
  fresh-venv install + `uvicorn src.api.app:app` boot, `GET /static/style.css`
  serving 5,182 bytes, and an end-to-end `e2er run` reaching terminal
  `failed` status (cost-cap test) with `~/.e2er/papers.db` and the
  workspace directory both created via the SQLite zero-config path.

## v0.4.1 — 2026-05-18

Lifecycle patch over v0.4.0. Three resume/shutdown bugs that surfaced
during the v0.4 SQLite live test.

### Lane A — Pipeline

- **Graceful shutdown** (closes #5): `@app.on_event("shutdown")` now
  cancels in-flight runner tasks and transitions papers to `paused`.
  Skips state.json-says-completed papers. Stops the "zombie row at
  designing/revision after every uvicorn restart" failure mode.
- **Resume writes terminal status** (closes #6): when resume runs on a
  paper whose state.json already has every stage complete, the runner
  now mirrors `state.last_status` back to the DB before returning.
  Previously the DB row stayed at `designing` (the entry value).
- **Resume accepts zombies** (closes #7): `/api/papers/{id}/resume` no
  longer requires status to be `paused`/`failed`. Any non-terminal
  status with no live runner task in `_RUNNING` is resumable. Combined
  with #5, this removes the manual-UPDATE workaround entirely.
- **SQLite translation extensions** (closes nothing — caught by live
  SQLite smoke after v0.4.0 shipped, fixed before tagging):
  `NOW()` → `CURRENT_TIMESTAMP`, plus `::int`/`::bigint`/`::numeric`/
  `::float` casts stripped alongside the existing type/json/interval
  casts. Without these, status UPDATEs silently failed and usage
  aggregations crashed SQLite with "unrecognized token: ':'".

### Tests

- `tests/pipeline/integration/test_graceful_shutdown.py` — 3 new.
- `tests/pipeline/integration/test_resume_terminal_status.py` — 1 new.
- `tests/pipeline/integration/test_resume_api.py` — 4 new + 1 rewritten.

Test count: 326 → 333.

## v0.4.0 — 2026-05-18

The **"actually usable by a stranger"** release. `pip install e2er`
followed by a one-command `e2er run "<RQ>"` now starts a local server,
submits the paper, and tails the run to terminal — zero database setup,
zero `.env` editing required to get to a first paper.

### Cross-lane — User journey

- **Zero-setup default**: `e2er serve` no longer requires Postgres. The
  DB client dispatches to SQLite at `~/.e2er/papers.db` by default; set
  `DATABASE_URL=postgresql://…` to opt into the production stack
  (pgvector + concurrent writes + literature KB).
- **`e2er run "<RQ>"`** subcommand: starts uvicorn in the background if
  needed, POSTs `/api/papers`, tails status to terminal, prints the
  paper's workspace + dashboard URL on completion. ^C is safe — the
  run keeps going.
- **README rewrite**: leads with the 5-minute quickstart + the BYO-CLI
  cost matrix. Architecture / artifact list moved below.
- **GitHub repo description + topics** filled in for discoverability.

### Lane C — Data

- **Raw-data persistence**: every data-pulling subcommand
  (`yfinance history`, `yfinance fundamentals`, `yfinance dividends`,
  `fred series`) gains a `--save-to <rel/path>.csv` flag. The wrapper
  writes the response rows to `workspace/data/<rel/path>` so the
  replication package is runnable offline. Skill files updated to
  mandate `--save-to` on every meaningful extraction. Closes #11.

### Internals

- **DB-client dispatch**: `src/db/client.py` now routes SQLite vs Postgres
  by URL scheme. Postgres ``%(name)s`` parameter style translates to
  SQLite ``:name`` on the fly; Postgres ``::type`` casts are stripped.
  Existing call sites need zero changes.
- **`sql/sqlite/schema.sql`** ships a SQLite-compatible schema with the
  core tables (papers, events, contributions, llm_usage, data_query_records,
  data_approval_requests). pgvector-dependent tables (literature_files,
  knowledge_chunks) are NOT created — KB feature degrades to "disabled"
  on SQLite, as designed.
- **`aiosqlite>=0.20.0`** added to dependencies.

### Tests

- New: `tests/data/contract/test_db_dispatch.py` — 9 tests pinning the
  parameter translation, cast stripping, and path resolution.

## v0.3.0 — 2026-05-16

The **stability sprint**. Five-phase overhaul focused on making v3
*actually* stable for users beyond the maintainer. Adopted patterns
from `Davidvandijcke/coarse` (branching model, slash commands, headless
CLI backends, OIDC PyPI publishing). Test count: 221 → 290.

### Cross-lane — Foundation & process

- **dev/main branch model**: `dev` is now the default integration branch;
  `main` is released-only and branch-protected (PR required, no force
  push, no deletion). All feature work goes through PRs into `dev`.
- **`AGENTS.md`** (new) codifies the three-lane split (Pipeline / Lit /
  Data), the public contracts each lane owns, hard rules (no live runs
  from `dev` without smoke-pass, cross-lane changes need explicit flag),
  and the tag-driven release procedure.
- **`.claude/hooks/session-brief.sh`** runs at SessionStart to dump
  branch, recent commits, CI status, and in-flight paper runs into
  every new Claude Code session.
- **`scripts/release_audit.py` + `make release-audit`**: hard-gates
  (version match between `pyproject.toml` and `src/__init__.py`, clean
  tree, CHANGELOG has entries, no `TODO(release)`, pytest passes) + soft
  gates (on-main, CI green). Required before tagging.
- **`.github/workflows/release.yml`** (new) tag-driven (`push:tags:v*`).
  Enforces tag↔pyproject↔__init__.py version triple-match, runs tests,
  builds wheel, creates GH release. Publishes to PyPI via OIDC trusted
  publishing — no API token secret.
- **Path-filtered per-lane CI** (`ci-pipeline.yml`, `ci-lit.yml`,
  `ci-data.yml`): each lane runs only its own tests; full `tests.yml`
  runs on every dev/main merge.
- **CHANGELOG per-lane organisation**: entries under `## Unreleased` use
  `### Lane A`, `### Lane B`, `### Lane C`, `### Cross-lane` sub-headings.

### Lane A — Pipeline (Phase 2-5)

- **Specialist circuit breaker** (`src/core/strategist/runner.py` +
  `state.py`): tracks consecutive failures per non-tolerant specialist.
  After 3 failures, the runner raises `CircuitBreakerError`, marks the
  paper `PAUSED` (new state), logs a `circuit_breaker_tripped` event,
  and returns cleanly. Tolerant specialists (reviewers, polish) are
  exempt — their failure is non-blocking. Fixes the run #14 failure
  mode where data_analyst was re-dispatched 3+ times when Allium was
  unrecoverable, burning 13 specialists before manual cancel.
- **Resume from last completed stage** (`POST /api/papers/{id}/resume`):
  re-enters the pipeline at the first phase whose canonical artifact is
  missing. Eligible from `paused` or `failed`. Avoids re-running phases
  that already succeeded after fixing a downstream issue.
- **Turn-budget signal in specialist prompts** (`src/core/specialists/base.py`):
  the system prompt opens with a "Turn Budget" section telling the
  model its max_turns and to write a first version of the canonical
  artifact within the first half. Fixes the run #16 failure where
  data_analyst saved write_file for the last turn and hit max_turns
  mid-pagination.
- **`SPECIALIST_SKILLS` consolidation**: previously two parallel dicts
  (`registry.py` and `loader.py`) that drifted whenever someone added a
  skill to one but not the other. Now one source of truth in
  `registry.SPECIALIST_SKILLS` with full paths (`data/cleaning`); loader
  resolves them.
- **Codex headless backend** (`LLM_BACKEND=codex`, src/modules/llm/codex.py)
  for ChatGPT Plus/Pro subscriptions. Shells out to `codex exec` — same
  pattern as the existing Claude Code backend. Adapted from coarse.
- **Gemini headless backend** (`LLM_BACKEND=gemini`, src/modules/llm/gemini.py)
  for Google AI Pro/Ultra. Probes `--approval-mode` vs legacy `--yolo`
  at startup. Adapted from coarse.
- **Skills bundled in the wheel** (`pyproject.toml` + `skills/__init__.py`):
  all 49 skill .md files ship in the e2er wheel. `e2er install-skills
  [--backend claude|codex|gemini|all] [--force]` copies them to the
  per-CLI skills dir (`~/.{backend}/skills/`).
- **Pre-run safety**: PR-time contract tests for specialist artifacts
  (every specialist in `SPECIALIST_ARTIFACTS` has registered skills,
  every skill path resolves to a real .md file, reviewer/polish lists
  stay aligned with registries) and integration smoke (theoretical
  pipeline end-to-end via MockLLMBackend, FastAPI POST surface,
  cascade-detection halt).
- **`POST /api/papers/{id}/resume`** (new endpoint, see above).
- **`GET /api/papers/{id}/failure-bundle`** (new): single-call
  diagnostic returning paper status + last_error (untruncated), every
  pipeline event with full payload, per-specialist drill-down
  (untruncated error_msg), workspace artifact listing (present vs
  missing), and the data_summary.md excerpt. Replaces the
  4-endpoint scavenger hunt diagnosis used to require.
- **Slash commands** (`.claude/commands/*.md`): `/pre-pr`,
  `/diagnose-run`, `/run-paper`, `/release-audit`.

### Lane B — Literature (Phase 2)

- **Provider contract tests** (`tests/lit/contract/test_provider_shapes.py`):
  first dedicated Lane B tests. For OpenAlex, Semantic Scholar, and
  arXiv, mock the documented response payloads and verify parsers
  handle standard shape, empty results, and network errors without
  crashing or raising into specialist code.

### Lane C — Data (Phase 2-3, 5)

- **Live OpenAPI contract tests** (`tests/data/contract/test_allium_developer_schema.py`):
  validates `AlliumDeveloperProvider` method kwargs against Allium's
  published OpenAPI specs (snapshots cached in
  `tests/data/fixtures/`). Catches required-param drift, list-vs-object
  body-shape mismatches, and silently-ignored unknown params. Run
  #14-#18's wrapper bugs would have been red CI checks instead of
  burning real specialist invocations.
- **Nightly schema-drift workflow** (`.github/workflows/schema-drift.yml`):
  re-fetches Allium's live OpenAPI at 03:30 UTC, diffs against the
  cached fixtures, opens a labelled issue with the unified-diff
  artifact if anything changed upstream.
- **Data-layer degradation breaker** (`src/modules/data/allium_developer.py`):
  tracks a sliding window of recent call outcomes. If >50% of the last
  6 calls errored, subsequent calls short-circuit with a structured
  "data layer degraded" envelope BEFORE hitting the network. Stops a
  specialist from draining its turn budget on dozens of 429 retries.
  Self-clears on the next successful call.
- **`GET /api/papers/{id}/data-queries`** (new): every Allium-style
  query the run submitted, with validation/approval status, executed
  timestamps, row counts, plus a rolled-up summary. Replaces the
  manual `cat audit_log.csv | grep` workflow.

### Fixed — Real bugs from the May 2026 NFT-marketplace live run

**Root cause (the hard lesson):** v3 made an architectural change v1/v2 didn't have — instead of delegating to the Claude Code CLI subprocess, it owns the tool-use loop directly via the Anthropic / OpenRouter SDKs (so `AlliumToolHandler` can intercept every tool call for guardrail validation). That introduced a class of bugs the unit-test suite never covered: the layer was never pressure-tested with realistic specialist output sizes. `MockLLMBackend` returns short canned outputs, so unit tests never saw the failure modes that hit on the first live run.

The May 2026 run lost ~$8 across two attempts before the diagnosis: `data_architect` writing `data_dictionary.json` as a single tool call exceeded `max_tokens_per_call=16384`, the model's output was truncated mid-write (`finish_reason=length`), the tool_loop correctly bailed (looping is futile — same wall every retry), the specialist was marked failed, and downstream specialists silently cascaded.

- `src/config.py`: `max_tokens_per_call` default bumped 16384 → 32768. Both Sonnet 4.6 and Haiku 4.5 support 64K out; 32K is a safe floor for the largest single tool argument any specialist emits.
- `src/core/specialists/base.py`: `_MAX_TURNS` 25 → 40. Independent issue from the same run — Sonnet specialists with Allium tools needed 29-38 turns to converge; 25 was tight enough that `idea_developer` hit the cap.
- `src/core/specialists/dispatcher.py`: cascade detection added to `execute_parallel`. After each batch, any non-tolerant specialist (anything not a reviewer / polish specialist) whose canonical artifact is missing now raises `RuntimeError` immediately — preventing downstream specialists from running on absent inputs and looping. Reviewer / polish specialists are still tolerant of partial failure (the aggregator handles gaps).
- `src/api/app.py`: invalid UUIDs on `/papers/{id}` and `/api/papers/{id}` now return 404 instead of 500. Previously a typo'd URL surfaced as `psycopg.InvalidTextRepresentation` → 500.

### Added — Stress tests for the tool-loop layer

`tests/test_tool_loop_stress.py` — five tests covering the failure modes mocked unit tests miss:
- 30 KB JSON tool argument forwarded to handler intact (the NFT-paper repro).
- 100 KB tool result threaded back into the message history verbatim.
- `finish_reason="length"` produces an actionable error referencing the setting to fix (so devs don't chase `max_turns` like I did).
- `max_tokens_per_call` default >= 32K (config-level floor).
- 25-turn message accumulation with correct token-usage summing.

Plus `tests/test_security_review_fixes.py` regression test for the cascade-detection behaviour above (`test_execute_parallel_raises_on_missing_canonical_artifact`).

### Added (P3 engineering hygiene)
- **mypy in CI.** `mypy src/` runs after `ruff` in `.github/workflows/tests.yml`.
  Config in `pyproject.toml` is pragmatic (catches real bugs without grinding
  on annotation completeness): `no_implicit_optional`, `strict_equality`,
  `warn_redundant_casts`. Per-module strictness can be ratcheted up later.
- **Pre-commit hooks.** `.pre-commit-config.yaml` runs ruff (with --fix),
  ruff-format, mypy, and standard hygiene hooks (trailing whitespace, large
  file check, merge-conflict markers, **detect-private-key**) on every commit.
  Install with `make hooks`.
- `Makefile` gains `typecheck` and `hooks` targets; help output updated.
- CONTRIBUTING.md gains a "Pre-commit hooks (recommended)" section and a
  "Local checks before pushing" cheat sheet.

### Fixed (real bugs surfaced by mypy)
- `src/modules/literature/bibtex.py` was calling `bibtexparser.load(f, parser=...)`
  which **does not exist** in bibtexparser v2 (project pins `>=2.0.0b7`).
  Any user with a `LITERATURE_BIBTEX_FILE` set would have hit
  `AttributeError: module has no attribute 'load'` at runtime. Migrated to
  `bibtexparser.parse_file()` and the v2 `Entry.fields_dict` API, with a
  glue layer keeping `_entry_to_metadata`'s dict interface unchanged.
- `src/modules/literature/arxiv.py`: `el.text` was accessed on an
  `Optional[Element]` without a None check — would raise `AttributeError`
  on author entries with missing `<atom:name>` tags.
- `src/modules/github/client.py`: `Github.get_user()` returns
  `NamedUser | AuthenticatedUser`; only `AuthenticatedUser` has `create_repo`.
  Cast added so type narrowing works without breaking tests that mock the
  user with MagicMock.
- `src/modules/github/push.py` and `src/api/app.py`: `GitHubClient(token, user)`
  was constructed with `Optional[str]` arguments that the constructor types
  as `str`. Added explicit None check (returns early when github is configured
  but token/username are missing) plus assert in push paths.
- `src/api/app.py`: `for e in events` shadowed the `except Exception as e`
  variable on the line above, which Python 3 deletes after the except block
  closes. Renamed to `exc` / `ev` to remove the deleted-variable read that
  mypy correctly flagged.
- `src/modules/llm/base.py` `tool_loop` typed `tool_handler: ToolHandler`,
  but engine.py was calling it with `tool_handler=None` for tool-less
  strategist decisions. Widened the abstract signature (and both concrete
  backends) to `ToolHandler | None`, with explicit None handling that
  surfaces a clear error if the model nonetheless requests a tool.
- `src/modules/data/tools.py`: `result` was reassigned from `ValidationResult`
  to `dict[str, Any]` in the same function, which mypy correctly flagged as
  a type confusion. Renamed the second binding to `query_result`.

### Added
- **Methodology selector** — papers now accept a `methodology` field at
  creation time: `empirical` (default, unchanged), `theoretical` (formal
  model only, no data/econometrics specialists), `mixed` (formal model +
  empirical test). Surfaced in the dashboard form and `POST /api/papers`.
- New `theory_specialist` (writes `model_spec.md`) ported from E2ER v2.
  Dispatched by the strategist when methodology is `theoretical` or
  `mixed`. Skill bundle: `base/economist`, `modeling/game-theory`,
  `modeling/asset-pricing`, `math/proof-strategies`,
  `reasoning/identification`.
- `sql/009_papers_methodology.sql` — adds `methodology` column to the
  `papers` table with a CHECK constraint.
- `tests/test_methodology.py` — 12 tests pinning the registry, prompt
  contract, manifest persistence, API validation, and specialist
  invocation.
- GitHub Actions CI: ruff lint + format + pytest on Python 3.11 and 3.12,
  triggered on push to `main` and all PRs.
- Branch protection on `main` requiring both pytest matrix jobs to pass
  before PR merges.
- `Makefile` with `make smoke` (free, ~10s, all 155 mocked tests) and
  `make smoke-paid` (~$0.50 Haiku end-to-end test).
- Issue templates (bug report, feature request) and PR template under
  `.github/`.
- `tests/test_pipeline_resilience.py` — 18 tests guarding against upstream
  result loss when downstream phases fail (crash injection per phase,
  resume-without-redo, artifact persistence, GitHub push idempotence,
  state-file atomicity, no-op replay).
- `SECURITY.md` and `CHANGELOG.md`.

### Changed
- `PipelineState.save()` now writes atomically (tmp + rename) and keeps a
  `.bak`. Previously a crash mid-write could corrupt the only state file
  and lose all upstream progress on resume.
- `PaperStatus` and `PipelineMode` now inherit from `StrEnum`, matching
  the pattern used in E2ER v2.
- Renamed `BudgetExceeded` → `BudgetExceededError` (PEP 8 exception
  naming).
- `src/api/app.py`: `TemplateResponse` calls migrated to the
  `(request, name, context)` signature for current Starlette.

### Fixed
- `tests/test_regressions.py`: removed hardcoded absolute path that
  would have failed on every CI runner.
- `src/modules/data/audit.py` and `tools.py`: missing top-level
  `from pathlib import Path` (worked at runtime only via `from __future__
  import annotations`).
- `src/modules/literature/bibtex.py`: removed unused `doi_index` dead
  code that hid an incomplete dedup intention.

## [3.0.0] — Initial public release

The first open-source release of E2ER. Differs from the private v1/v2
which were tied to internal infrastructure.

### Architecture
- Standalone package — no shared/ imports, no Docker network dependencies
  on private services.
- BYOK for all external services: `ANTHROPIC_API_KEY`, `OPENROUTER_API_KEY`,
  `ALLIUM_API_KEY`, `GITHUB_TOKEN`.
- Owns its tool-use loop in Python (no Claude Code CLI subprocess) so
  every tool call can be intercepted for guardrail validation.
- Two LLM backends: Anthropic API (with prompt caching) and OpenRouter
  (OpenAI-compatible). Switch via `LLM_BACKEND=anthropic|openrouter`.

### Pipeline
- Two modes: `single_pass` (fast draft) and `iterative` (full loop with
  ceiling detection, self-attack, polish stack).
- New phases vs v2: ceiling check, adversarial self-attack with severity
  scoring, parallel polish stack (formula, numerics, institutions,
  bibliography, equilibria), mechanical 3-rule review aggregation.
- Full pipeline state persistence and resume-from-crash support.

### Data module
- Allium integration with 5 hard guardrails (no `SELECT *`, fields must be
  in `data_dictionary.json`, time-bound `WHERE` required, transaction
  granularity requires justification, production queries require prior
  feasibility run).
- Two-phase workflow: feasibility (auto-approved sample) → production
  (researcher approval required).
- Full audit log persisted as `audit_log.csv` in the replication package.
- Module is optional: set `DATA_MODULE_ENABLED=false` for literature-only
  or manually-provided-data papers.

### GitHub integration
- Auto-creates a per-paper repo with `.gitignore` as the FIRST commit
  (so Overleaf import never pollutes git history with build artifacts).
- Pushes the LaTeX draft, replication package, and audit bundle.

### Cost tracking
- Per-call usage recorded in `llm_usage` table.
- Per-paper hard cost cap enforced at every phase boundary.
- Audit bundle export (`.tar.gz`) includes `usage.json` with full cost
  breakdown.

[Unreleased]: https://github.com/bhanneke/E2ER-project/compare/v0.18.0...HEAD
[0.18.0]: https://github.com/bhanneke/E2ER-project/releases/tag/v0.18.0
[3.0.0]: https://github.com/bhanneke/E2ER-project/releases/tag/v3.0.0
