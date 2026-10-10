# AI backends: what each one can do on your computer

e2er runs its specialists through one of five backends, chosen with
`LLM_BACKEND` (or `--backend` per study):

| backend | runs on | billed |
| --- | --- | --- |
| `claude_code` | the Claude Code CLI (`claude`) | your Claude subscription |
| `codex` | the Codex CLI (`codex`) | your ChatGPT plan |
| `gemini` (not tested) | the Gemini CLI (`gemini`) | a Gemini API key (`GEMINI_API_KEY`), billed by Google |
| `anthropic` | the Anthropic API | per use |
| `openrouter` | OpenRouter | per use |

Full runs are tested on Claude (Claude Code) and OpenAI (Codex CLI with a
ChatGPT plan). Google ended Gemini CLI sign-in for individual accounts in
October 2026, so the Gemini backend needs a Gemini API key and is not tested.

The three CLI backends hand the CLI the specialist's whole prompt and let it
work in the study's workspace folder with its own tools. They differ in what
the model may do there.

## What the model can run

**Claude Code** is started with a list of allowed tools: reading and writing
files, and the e2er commands (`e2er-data`, `e2er-lit`, `e2er-run`,
`e2er-check-tables`, and `e2er-fieldmap` for the field-map template's
specialists). Any other shell command is refused.

**Codex** has no such list for a single run. Its command rules are read only
from the user's own `~/.codex/rules` folder or a trusted project, and a rule can
forbid a command but cannot forbid everything outside a list. e2er does not
change the user's Codex settings, so under Codex the model can run any shell
command. What does hold:

- Writes are confined by Codex's sandbox (`workspace-write`) to the study's
  workspace folder, the run database's folder and the temporary folder.
- Network access is on, because `e2er-data` and `e2er-lit` download data and
  literature. A shell command could reach other addresses too.
- The run uses none of your own Codex settings (`--ignore-user-config`,
  `--ignore-rules`): not your model, reasoning effort, plugins, MCP servers or
  notification hooks. It leaves no session history (`--ephemeral`). Sign-in
  still comes from `~/.codex/auth.json` (or `$CODEX_HOME`).
- Every variable in e2er's environment, data keys included, is visible to the
  model's shell commands, because the e2er commands need the data keys. e2er's
  own control settings (dashboard session, API token and address, e2er.org
  sign-in file) are removed first. The local e2er server itself has no
  password unless `API_AUTH_TOKEN` is set, so a shell command on this computer
  could still reach it.

**Gemini** runs with `--approval-mode yolo`, so its shell tool can run any
command too, and it has no sandbox unless you start it with one. The Gemini
backend is not tested. Since October 2026 the Gemini CLI refuses sign-in for
individual accounts (version 0.63.0 answers "This client is no longer
supported for Gemini Code Assist for individuals"), so the backend runs only
with `GEMINI_API_KEY`, and no study has run that way. Its command line and
output reading follow the CLI's documentation and are covered by tests with a
simulated CLI only. Google bills the key; e2er records the cost of a Gemini
study as $0, so its spending limit does not apply.

The orchestrator does not rely on what a specialist ran: it re-runs the final
analysis script itself, re-renders the tables and checks every number in the
paper against the results, on every backend.

## Codex settings

| setting | default | what it does |
| --- | --- | --- |
| `CODEX_PATH` | `codex` | the CLI; found on PATH or inside the ChatGPT desktop app when unset |
| `CODEX_MODEL` | first model in the CLI's own list | the model, passed as `-m` and recorded with the run |
| `CODEX_REASONING_EFFORT` | the model's default | `low`, `medium`, `high`, `xhigh` (some models also `max`) |
| `CODEX_SANDBOX` | `workspace-write` | `read-only` stops specialists from writing any file |
| `CODEX_TIMEOUT` | 1800 | seconds per specialist call; the CLI and everything it started are stopped after it |

`e2er doctor` shows where it found the CLI, and the setup page lists the models
your ChatGPT plan offers (read from `~/.codex/models_cache.json`).

Each run records which backend, model, reasoning effort and CLI version
answered its calls (the `backend_identity` event, kept with the study).

## Running one question on several backends

`e2er run-matrix "<question>" --backends claude_code,codex --models
claude_code=sonnet,codex=gpt-6-luna --repeats 1` runs the same question on each
backend and exports each completed run. Without `--backends` it runs every
subscription CLI that `e2er doctor` finds ready (Claude Code, Codex); Gemini
runs only when `--backends` names it. `e2er compare <out>/matrix.json`
then lists the design choices each run made, with the model that made them.
