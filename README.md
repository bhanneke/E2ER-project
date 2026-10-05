# e2er (End-to-End Research)

[![Status](https://img.shields.io/badge/status-active%20development-blue)](https://github.com/bhanneke/E2ER-project)
[![License](https://img.shields.io/badge/license-MIT-green)](https://github.com/bhanneke/E2ER-project/blob/main/LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://pypi.org/project/e2er/)
[![Tests](https://github.com/bhanneke/E2ER-project/actions/workflows/tests.yml/badge.svg)](https://github.com/bhanneke/E2ER-project/actions/workflows/tests.yml)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.20187238.svg)](https://doi.org/10.5281/zenodo.20187238)
[![PyPI](https://img.shields.io/pypi/v/e2er.svg)](https://pypi.org/project/e2er/)

e2er is the open infrastructure for publishing, verifying, reproducing and reusing AI-enabled research.

Templates describe research processes as a sequence of steps. Each template organizes specialists, i.e., AI agents with defined roles, and each specialist draws on skills, i.e., written descriptions of methods. Researchers can adjust any template, specialist, or skill and publish their version for fellow researchers.

Researchers decide at which steps the process pauses for their review.

A study produced with e2er comes with a dossier that helps others verify and reproduce the work and attributes everyone whose templates, specialists, and skills it used.

## Install

    uv tool install --python 3.12 e2er
    e2er

`e2er` opens a page in your browser. There you choose your AI provider, your literature and your data folder, start a study, review it where it pauses, check it and publish it.

## Verifying research

Before a study is published, e2er checks it against its dossier. The dossier lists every file of the study with its hash value. The check confirms that none of these files has changed since the specialists produced them, and that every table in the study can be rebuilt from the estimation results the specialists saved.

The check is built into e2er, so anyone who has the study's files can repeat it with the hash values in the dossier. e2er.org repeats the check when the study's files are in a public repository.

Examples:

[The Bitcoin study](https://e2er.org/bhanneke/spot-bitcoin-etf-comovement) ([its dossier](https://e2er.org/d/c46711b0dc073e96)) has its data and code in a public repository and is checked by e2er.org.

[The FOMC study](https://e2er.org/bhanneke/fomc-bank-event-study) ([its dossier](https://e2er.org/d/493e6ed4a9b568bd)) keeps its files private, so its dossier shows only the check its author ran.

## Reproducing research

The replication template reproduces a published study from its replication package on Zenodo. Specialists read the package and plan which of the study's numbers to compare. The researcher reviews that plan before anything is executed.

The authors' code is then executed again in a container on the researcher's computer, without network access. Every number the study reports is compared with the number from the new execution and labelled reproduced, reproduced with a minor difference, or not reproduced. The researcher reviews the report, and the dossier records every comparison.

Example:

[The replication of Peixoto and Leite](https://e2er.org/bhanneke/replication-political-rupture-brazil), "Political Rupture and Selective Damage to Local Service Delivery: Evidence from Brazil" ([its dossier](https://e2er.org/d/84b3ab11d9ce589e)): 12 of 17 numbers reproduced, 2 with a minor difference, 3 not reproduced. All five differences are in numbers from the Callaway and Sant'Anna estimator: two estimates, one standard error and two minimum detectable effects. The replication is not an assessment of the authors' work; differences can come from e2er or from software versions.

## Installation in detail

e2er needs Python 3.11 or newer. The automated tests run on Ubuntu with Python 3.11 and 3.12, and e2er is developed on macOS. Windows is untested so far.

The installer uv downloads Python together with e2er. On Mac and Linux, in a terminal:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv tool install --python 3.12 e2er
uv tool update-shell        # then open a new terminal window
e2er
```

On Windows, in PowerShell:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
uv tool install --python 3.12 e2er
uv tool update-shell        # then open a new PowerShell window
e2er
```

`uv tool upgrade e2er` updates an installation.

With your own Python installation, install e2er into a virtual environment, for example on a Mac:

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install e2er
e2er
```

`e2er --no-browser` starts the page without opening the browser and prints its address. The page runs on port 8280 unless `--port` sets another one.

### AI access

e2er works with one of the following. The setup page shows which of them it finds.

- A Claude subscription through Claude Code. Install Claude Code following [Anthropic's instructions](https://code.claude.com/docs/en/setup), then run `claude` once and sign in. Studies then run on the subscription.
- An API key from [Anthropic](https://console.anthropic.com/settings/keys) or [OpenRouter](https://openrouter.ai/keys), billed per use. You paste the key on the setup page.
- The [Codex CLI](https://github.com/openai/codex) with a ChatGPT plan or the [Gemini CLI](https://github.com/google-gemini/gemini-cli) with a Google AI plan. e2er uses them in the same way as Claude Code.

In the terminal, the setting `LLM_BACKEND` selects the access: `claude_code`, `codex`, `gemini`, `anthropic` or `openrouter`.

The replication template also needs [Docker Desktop](https://docs.docker.com/get-started/get-docker/), because it executes the authors' code in a container.

## Terminal commands

### Setting up

```bash
e2er init                # asks questions, writes .env
e2er init --defaults     # the same without questions, with Claude Code
e2er doctor              # checks the setup
```

`e2er init` asks which AI access to use and checks that it is installed. The command then creates the folders `data/` and `literature/` and writes the settings to `.env` in the current folder; `--force` overwrites an existing `.env`. For Claude Code, Codex or Gemini it asks before copying e2er's skill files into that CLI's skills folder (`~/.claude/skills`, `~/.codex/skills` or `~/.gemini/skills`); `--defaults` copies them into `~/.claude/skills` only. Other CLIs' folders are left alone. The setup page in the browser writes the same file. `e2er doctor` reports the AI access, the database and the data and literature it finds.

Studies are recorded in a SQLite database at `~/.e2er/papers.db`. Setting `DATABASE_URL` to a Postgres address switches e2er to Postgres, and `e2er migrate` then creates the tables.

With `GITHUB_TOKEN` and `GITHUB_USERNAME` set, e2er pushes each study to a GitHub repository of its own, in a layout Overleaf can import.

### Running a study

```bash
e2er question --draft "<draft research question>"
e2er run "<research question>"
e2er run "<research question>" --template empirical-preregistered
e2er status <paper_id> --tail
```

`e2er question` (short form `e2er rq`) sharpens a draft research question against your data and literature. The command gives advice and starts no study.

`e2er run` starts a study and follows it in the terminal. Ctrl+C stops the output in the terminal, and the study keeps running in the background. The options are:

- `--template NAME`: the template the study follows (default `empirical`).
- `--max-cost USD`: the spending limit of the study in US dollars (default 5).
- `--review-at STEP`: an additional pause for your review after this step (repeatable).
- `--backend` and `--model`: another AI access or model for this study.
- `--methodology empirical|theoretical|mixed` and `--mode single_pass|iterative`.
- `--governance off|contracts|full`: which checks stop the study (default `GOVERNANCE` from `.env`, else `full`). Under `off` and `contracts`, the remaining checks still run and record what they find.

`e2er run` starts a local server on port 8280 when none is running. The page at http://127.0.0.1:8280 lists all studies. The files of a study are in `workspaces/<paper_id>/`.

`e2er run-matrix "<research question>" --backends claude_code,codex,gemini --repeats 3` runs one question with several AI providers, and `e2er compare matrix.json` lists the design choices each run made.

### Reviewing, stopping and resuming

A study pauses for you at a design review, at a pre-registration or after a failed check. A study also pauses when its plan changes after the pre-registration was frozen. The estimation runs only after the researcher decides. Approving the change records it in the dossier as a deviation, and `e2er verify` reports it. The researcher can also edit the plan back or send back the step that changed it. `e2er review <paper_id>` shows the step and its files.

```bash
e2er review <paper_id> --approve
e2er review <paper_id> --edit paper_plan.md
e2er review <paper_id> --instruction "<instruction for the following steps>"
e2er review <paper_id> --send-back <step> --remark "<what should change>"
e2er rerun <paper_id> --from <step> --remark "<what should change>"
e2er cancel <paper_id>
e2er resume <paper_id> --max-cost 15
```

The dossier records every review action. `e2er rerun` sends a study (finished, failed or stopped) back to one of its steps, and that step and all later steps run again. The dashboard offers each of these actions on the study's pages. `e2er cancel` stops a running or paused study and keeps its files. `e2er resume` continues a paused or failed study and skips the steps whose output already exists; `--max-cost` raises the spending limit at the same time.

### Studies and versions

Running the same question again with the same template adds an attempt to the existing study. Attempts are numbered v1, v2, … by start time.

```bash
e2er list                      # one entry per study
e2er list --attempts           # with each study's attempts
e2er archive <paper_id>        # hide one attempt (the first 8 characters of the id suffice)
e2er archive --failed --yes    # hide all failed and cancelled attempts
e2er unarchive <paper_id>
```

Archiving hides attempts from the lists and deletes no file. Running and paused attempts cannot be archived. `e2er archive --failed` without `--yes` only lists the attempts it would hide.

### Exporting, checking and publishing

```bash
e2er export <paper_id>
e2er verify <study folder>
e2er verify <study folder> --against https://e2er.org/<owner>/<project>
e2er login
e2er publish <study folder> --owner <github-login> --project <name> --to https://e2er.org
```

`e2er export` writes the study folder with the subfolders `paper/`, `code/`, `data/`, `results/`, `design/` and `reviews/`. The file `provenance.json` in it lists every file with its hash value. `--to` sets where the folder is written (default: `OUTPUT_DIR`, else `e2er_papers/` in the data folder, which is never read back in as data). The command works from any folder and takes the first characters of the paper id when they are unique.

`e2er verify` runs the check offline and without API keys. The check recomputes the hash values, rebuilds the tables from the estimation results, recomputes t and p values, compares the estimation with the declared identification strategy and confirms that every citation is in the bibliography. A pre-registration or a reproduction in the folder is checked as well. `--online` also looks up the citations in OpenAlex, Semantic Scholar and Crossref. `--against` compares the folder with the study or dossier that e2er.org published and only reads from e2er.org.

`e2er publish` checks the folder and writes the study's description (`e2er.json`) and its dossier. `--to` sends the description, the dossier and the hash values of the files to e2er.org after `e2er login`. The files themselves stay on your computer. `--dry-run` prints the request and sends nothing. `--data` and `--code` state whether data and code are public (default private), and `--zenodo` deposits public data and code on Zenodo with your own token. `--demonstration` marks a demonstration or test run that is published as is: `e2er.json` and the dossier record it, and the paper and the reproduction report carry a disclaimer. A study started with `e2er run --demonstration` (or with the box in the dashboard) is marked from the start and needs no flag at publishing; `E2ER_PURPOSE` from the environment or `.env` also sets it. `--offline` prepares the folder for publishing in the browser at e2er.org/publish and sends nothing.

`e2er submit` sends a skill, template, specialist or connector to e2er.org for review.

## Templates

A template is a `.toml` file. e2er ships four in [`pipelines/`](https://github.com/bhanneke/E2ER-project/tree/main/pipelines):

- `empirical` (default): from a research question and data to an empirical paper.
- `empirical-preregistered`: `empirical` with three pauses for the researcher (design review, pre-registration frozen before any estimation, draft review).
- `event-study-finance`: abnormal-return event studies around announcements, with the pauses of `empirical-preregistered`. A check before estimation tests the estimation window, the overlap between events and the event dates.
- `replication`: reproduction of a published study from its replication package on Zenodo, executed in a Docker container. The result is a reproduction report.

The three empirical templates end with e2er's internal quality review. Six reviewer specialists each score the draft from one angle on a scale of 0 to 10. The six angles are data, identification, literature, mechanism, technical quality and writing. The score is their weighted average. The score decides whether the draft is revised before the study ends, and the study reports it, for example "e2er's internal quality review: 6.1 of 10". A study that finishes its steps is completed whatever its score.

e2er ships with 63 skill files and 28 specialist roles. `e2er run --template NAME` looks for a template in `./pipelines`, then in `~/.e2er/pipelines`, then among the four above. [docs/templates.md](https://github.com/bhanneke/E2ER-project/blob/main/docs/templates.md) describes the file format, and [docs/researcher-step.md](https://github.com/bhanneke/E2ER-project/blob/main/docs/researcher-step.md) describes the pauses. `e2er skills list` and `e2er skills install` read the [RISE catalogue](https://github.com/bhanneke/RISE) of skill packs: e2er downloads its pack list from GitHub (refreshed daily), or reads a local clone named by `RISE_PATH` or `--catalogue`. Packs are installed from their own sources.

## Data sources

Your own data go in the folder that `LOCAL_DATA_DIR` names (`data/` after `e2er init`). Files in the formats `.csv`, `.tsv`, `.jsonl`, `.parquet` and `.xlsx` are made available to each study and loaded into a SQLite database for that study.

Specialists can also draw on four sources:

| Source | Coverage | Setting |
|---|---|---|
| yfinance | Equities, ETFs, crypto, FX, indices | no key |
| FRED | US and international macroeconomic series | `FRED_API_KEY` (free) |
| Global Macro Database (GMD) | Annual macroeconomic data for 239 economies, in versioned releases. Free for academic use. | no key |
| Allium | On-chain blockchain data | `ALLIUM_API_KEY` (paid query credits) |

Every Allium query passes five checks before it runs. A query on a table first runs as a feasibility query of at most 1000 rows, and the full query waits for the researcher's approval. Allium supported this project with data access and technical collaboration.

Each GMD load records the release, the address and the SHA-256 of the file it read. The study's references then include the GMD citation.

## Literature

The folder that `LITERATURE_DIR` names (`literature/` after `e2er init`) can hold reference PDFs, a Zotero library (a folder with `zotero.sqlite`) or a `.bib` file. `LITERATURE_BIBTEX_FILE` adds a single `.bib` file, and `ZOTERO_API_KEY` with `ZOTERO_USER_ID` or `ZOTERO_GROUP_ID` adds an online Zotero library. The PDFs stay on your computer; the exported study folder contains the references as `paper/refs.bib`.

Specialists also search OpenAlex for literature and read the full text of open-access papers. The search falls back to arXiv and Semantic Scholar.

`e2er library` (also `e2er corpus`) keeps a local library of what papers claim. Each claim is stored with the sentence it comes from, and a claim whose sentence cannot be found in the paper's full text is dropped.

```bash
e2er library add ~/papers/                 # every PDF in a folder
e2er library add "10.1257/aer.20201397"    # one paper by DOI
e2er library topics add "stablecoin runs"  # a standing search
e2er library refresh                       # run the searches again, extract what is new
e2er library search "null effects of listing"
```

The library is stored at `~/.e2er/corpus.db` (`CORPUS_DB` moves it). Before drafting, a study adds the PDFs from its own `literature/` folder to the library (`CORPUS_AUTOINGEST=false` turns this off) and writes the matching claims to `literature/corpus_evidence.md`. [docs/CORPUS.md](https://github.com/bhanneke/E2ER-project/blob/main/docs/CORPUS.md) has the details.

## Costs

Each study has a spending limit, set with `--max-cost` (default 5 US dollars in the terminal). A study that reaches the limit pauses, and `e2er resume <paper_id> --max-cost <higher limit>` continues it. The first study with a given combination of model, methodology and mode is limited to 1 US dollar until one such study has completed. `--acknowledge-unproven` lifts this limit. On Claude Code, Codex and Gemini CLI, e2er lifts it automatically.

## Troubleshooting

`e2er: command not found` after installing: the folder with the `e2er` command is missing from your PATH. After `uv tool update-shell`, open a new terminal window.

`ImportError: cannot import name 'UTC' from 'datetime'`: the Python version is older than 3.11. Install with `uv tool install --python 3.12 e2er`.

A study that pauses with `BudgetExceededError` has reached its spending limit. Continue it with `e2er resume <paper_id> --max-cost <higher limit>`.

A study that stops with `verify_numbers: N critical mismatches` reports a number in its draft that differs from the estimation results. `number_verification.json` in the study's folder lists each mismatch.

A study that stays in `in_progress`: the server log is at `~/.e2er/uvicorn.log`, and `e2er resume <paper_id>` continues the study from the last completed step.

OpenRouter `402 Payment Required`: the OpenRouter balance is empty.

With `API_AUTH_TOKEN` set, requests to the e2er API need the header `Authorization: Bearer <token>`.

## Development

```bash
git clone https://github.com/bhanneke/E2ER-project.git
cd E2ER-project
pip install -e ".[dev]"
make smoke        # test suite with mocked AI calls, no API key needed
make lint         # ruff check and format check
make typecheck    # mypy
make smoke-paid   # one real study on Claude Haiku 4.5 (needs ANTHROPIC_API_KEY, billed)
```

[AGENTS.md](https://github.com/bhanneke/E2ER-project/blob/main/AGENTS.md) describes the branch model, [CONTRIBUTING.md](https://github.com/bhanneke/E2ER-project/blob/main/CONTRIBUTING.md) the contribution process and [skills/CONTRIBUTING_SKILLS.md](https://github.com/bhanneke/E2ER-project/blob/main/skills/CONTRIBUTING_SKILLS.md) the format of skill files. [docs/WORKFLOW.md](https://github.com/bhanneke/E2ER-project/blob/main/docs/WORKFLOW.md) describes the steps of a study and the checks in detail.

### Related projects

- [Project APE](https://ape.socialcatalystlab.org/) (Social Catalyst Lab, University of Zurich).
- [ZeroPaper](https://github.com/alejandroll10/zeropaper) (Institute for Automated Research). Several of e2er's review steps follow ZeroPaper.

## Citing

```bibtex
@software{hanneke2026e2er,
  author       = {Hanneke, Bj{\"o}rn},
  title        = {{e2er (End-to-End Research): The Open Infrastructure for
                   Publishing, Verifying, Reproducing and Reusing AI-Enabled Research}},
  year         = {2026},
  version      = {0.13.6},
  url          = {https://github.com/bhanneke/E2ER-project},
  doi          = {10.5281/zenodo.20187238},
  license      = {MIT},
  institution  = {Goethe University Frankfurt},
}
```

The concept DOI `10.5281/zenodo.20187238` resolves to the latest release. [Zenodo lists all versions](https://zenodo.org/records/20187238) for citing a specific one.

## License

MIT. See [LICENSE](https://github.com/bhanneke/E2ER-project/blob/main/LICENSE).

## Contact

Björn Hanneke, information systems researcher at the Chair of Information Systems and Information Management (Prof. Dr. Oliver Hinz), Goethe University Frankfurt. [bjornhanneke.com](https://www.bjornhanneke.com) · <hanneke@wiwi.uni-frankfurt.de> · [ORCID](https://orcid.org/0009-0000-7466-9581) · [Google Scholar](https://scholar.google.com/citations?user=N5fbuZIAAAAJ) · [LinkedIn](https://www.linkedin.com/in/bhanneke/)
