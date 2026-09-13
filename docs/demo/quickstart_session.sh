#!/usr/bin/env bash
# The session recorded as quickstart.gif: install the package, run the guided
# setup, confirm the environment, see the command surface.
#
# The install is real and lands in a throwaway virtualenv, so nothing here
# touches the ambient Python environment. Everything on screen after the prompt
# is the program's own output.
#
# record.sh will not run this until PyPI carries 0.9.0 or later, because the
# published 0.8.1 predates doctor/verify/rq/compare/run-matrix — the commands
# the rest of the session demonstrates.
set -u

PROMPT=$'\033[1;36m❯\033[0m '
DIM=$'\033[2m'
RESET=$'\033[0m'

type_out() {
  printf '%s' "$PROMPT"
  local s=$1 i
  for ((i = 0; i < ${#s}; i++)); do
    printf '%s' "${s:i:1}"
    sleep 0.035
  done
  printf '\n'
}

run() {
  type_out "$1"
  eval "$1"
  printf '\n'
  sleep "${2:-1.5}"
}

note() {
  printf '%s' "$PROMPT"
  local s=$1 i
  printf '%s' "$DIM"
  for ((i = 0; i < ${#s}; i++)); do
    printf '%s' "${s:i:1}"
    sleep 0.028
  done
  printf '%s\n\n' "$RESET"
  sleep 0.8
}

cd "${E2ER_DEMO_HOME:-/tmp/e2er-demo-home}" || exit 1
sleep 1

note "# A pipeline that writes empirical papers. Start from nothing."
run "python3 -m venv .venv && source .venv/bin/activate" 1.2

run "pip install e2er" 3

note "# One guided setup: pick a backend, write .env, bundle the skills."
run "e2er init --defaults" 3

note "# Before running anything, ask whether it can run."
run "e2er doctor" 4

note "# That is the setup. Here is what you can now do."
run "e2er --help" 4
