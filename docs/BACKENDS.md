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
ChatGPT plan). On 18 June 2026 Google ended the Gemini CLI for AI Pro/Ultra
plans and free individual accounts (replaced by its Antigravity CLI, `agy`,
which e2er does not support), so the Gemini backend works only with a paid
Gemini API key and is not tested.

The three CLI backends hand the CLI the specialist's whole prompt and let it
work in the study's workspace folder with its own tools. They differ in what
the model may do there.

## What the model can run

**Claude Code** is started with a list of allowed tools: reading and writing
files, and the e2er commands (`e2er-data`, `e2er-lit`, `e2er-run`,
`e2er-check-tables`, and `e2er-fieldmap` for the field-map template's
specialists). Any other shell command is refused. Since 0.19.0 the call also
loads none of your Claude Code settings, the project's or a folder's
(`--setting-sources ""`: no permission rules, hooks or `CLAUDE.md` of yours or
of a downloaded folder), no MCP server (`--strict-mcp-config` with an empty
MCP config), and refuses, whatever a setting says, the web tools
(`WebFetch`, `WebSearch`), notebooks, sub-agents, and reading or writing the
files that hold logins and keys (`~/.ssh`, `~/.e2er`, `~/.aws`, `~/.gnupg`,
`~/.config/gh`, `~/.codex`, `~/.docker`, `~/.netrc`, `~/.pgpass`, every `.env`)
(`--disallowedTools`).

**Codex** has no such list for a single run. Its command rules are read only
from the user's own `~/.codex/rules` folder or a trusted project, and a rule can
forbid a command but cannot forbid everything outside a list. e2er does not
change the user's Codex settings, so under Codex the model can run any shell
command. What does hold:

- Writes are confined by Codex's sandbox (`workspace-write`) to the study's
  workspace folder, the run database's folder and the temporary folder.
  `CODEX_SANDBOX=danger-full-access` (no sandbox) runs only with
  `CODEX_ALLOW_FULL_ACCESS=true` as well, and with a warning; otherwise e2er
  uses `workspace-write`.
- **Network access is off** (since 0.19.0). With it on, a shell command could
  reach any address, not only the sources `e2er-data` and `e2er-lit` load from.
  Under Codex these two therefore cannot download unless you set
  `CODEX_NETWORK_ACCESS=true` (e2er warns at the start of each call); data
  already in the workspace, `data.db` and your own files work either way.
- The run uses none of your own Codex settings (`--ignore-user-config`,
  `--ignore-rules`): not your model, reasoning effort, plugins, MCP servers or
  notification hooks. It leaves no session history (`--ephemeral`). Sign-in
  still comes from `~/.codex/auth.json` (`CODEX_HOME` points there); the
  model's shell commands get an empty `HOME`, so `~/.ssh` and other logins are
  not where they look.
- The environment is an allowlist (the system's basics, e2er's run variables
  and non-secret settings, the wrappers' data keys, the CLI's sign-in), and
  Codex's own default excludes apply on top: variables whose names contain
  `KEY`, `SECRET` or `TOKEN` do not reach the model's shell. The e2er commands
  read the data keys from the settings file of the studies folder instead.
  e2er's own control settings (dashboard session, API token and address,
  e2er.org sign-in file), an ssh agent and a database password are never
  passed. Codex's sandbox does not stop reading files, so a shell command can
  still read what you can read, the settings file included.

**Gemini** always runs in the CLI's sandbox (`--sandbox`: a container, or
macOS's `sandbox-exec`). Its shell tool runs commands without asking only with
`GEMINI_YOLO=true` (`--approval-mode yolo`, with a warning); otherwise it runs
with `--approval-mode auto_edit`, in which it may edit files but not run the
e2er commands. The Gemini backend is not tested. Since 18 June 2026 the Gemini CLI refuses sign-in with
AI Pro/Ultra plans and free individual accounts (version 0.63.0 answers "This client is no longer
supported for Gemini Code Assist for individuals"), so the backend runs only
with a paid `GEMINI_API_KEY`, and no study has run that way. Its command line and
output reading follow the CLI's documentation and are covered by tests with a
simulated CLI only. Google bills the key; e2er records the cost of a Gemini
study as $0, so its spending limit does not apply.

**Scripts the models write** (the analysis script e2er runs after a specialist,
the meta-analysis script, `e2er-run`) run with no key or token at all, an empty
`HOME`, and in a session of their own that the time limit stops as a whole.

The orchestrator does not rely on what a specialist ran: it re-runs the final
analysis script itself, re-renders the tables and checks every number in the
paper against the results, on every backend.

## Codex settings

| setting | default | what it does |
| --- | --- | --- |
| `CODEX_PATH` | `codex` | the CLI; found on PATH or inside the ChatGPT desktop app when unset |
| `CODEX_MODEL` | first model in the CLI's own list | the model, passed as `-m` and recorded with the run |
| `CODEX_REASONING_EFFORT` | the model's default | `low`, `medium`, `high`, `xhigh` (some models also `max`) |
| `CODEX_SANDBOX` | `workspace-write` | `read-only` stops specialists from writing any file; `danger-full-access` needs `CODEX_ALLOW_FULL_ACCESS=true` too |
| `CODEX_NETWORK_ACCESS` | `false` | `true` lets the model's shell commands (and `e2er-data`, `e2er-lit`) reach the network |
| `CODEX_TIMEOUT` | 1800 | seconds per specialist call; the CLI and everything it started are stopped after it |

`e2er doctor` shows where it found the CLI, and the setup page lists the models
your ChatGPT plan offers (read from `~/.codex/models_cache.json`).

### Codex on Linux and Windows

e2er's Codex runs were validated on macOS, where Codex sandboxes with Seatbelt.
A specialist writes its files with Codex's `apply_patch` inside the
`workspace-write` sandbox, and e2er makes one more folder writable with
`--add-dir`: the run database's folder (`~/.e2er`), because `e2er-data` and
`e2er-lit` record what they fetched there. When the sandbox refuses the writes,
Codex still ends without an error and the step fails with
"contract violation: …: file not written"; e2er now adds what Codex's sandbox
refused and the remedy for your system to that message.

- **Linux.** Codex's sandbox uses bubblewrap, which needs unprivileged user
  namespaces. Install it (`sudo apt install bubblewrap`). Ubuntu 23.10 and later
  restrict the namespaces with AppArmor (`sysctl
  kernel.apparmor_restrict_unprivileged_userns` prints 1): allow them for
  `bwrap` with an AppArmor profile, or for the whole system with
  `sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0`.
- **Windows.** Codex's sandbox refuses `apply_patch` under `workspace-write`
  when extra writable folders are given (openai/codex issue #30009), which
  e2er does whenever the run database lies outside the study's folder (by
  default it does). Run e2er inside WSL2, where Codex uses its Linux sandbox.
- **Without a sandbox.** `CODEX_SANDBOX=danger-full-access` together with
  `CODEX_ALLOW_FULL_ACCESS=true`, in your studies folder's `.env`, runs Codex
  without any sandbox: every shell command the model chooses then runs as you,
  with your files. e2er warns at every call. Use it only on a machine or account
  set aside for it.

On macOS nothing changes.

Each run records which backend, model, reasoning effort and CLI version
answered its calls (the `backend_identity` event, kept with the study).

## Running one question on several backends

`e2er run-matrix "<question>" --backends claude_code,codex --models
claude_code=sonnet,codex=gpt-6-luna --repeats 1` runs the same question on each
backend and exports each completed run. Without `--backends` it runs every
subscription CLI that `e2er doctor` finds ready (Claude Code, Codex); Gemini
runs only when `--backends` names it. `e2er compare <out>/matrix.json`
then lists the design choices each run made, with the model that made them.
