#!/usr/bin/env bash
# The session recorded as byod.gif: point E2ER at your own data and your own
# references, then confirm it can run.
#
# Every command below is executed for real and everything on screen after the
# prompt is the program's own output. The only theatre is the typing delay,
# which exists so a reader can follow the line being entered.
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

# Types a line and runs it.
run() {
  type_out "$1"
  eval "$1"
  printf '\n'
  sleep "${2:-1.5}"
}

# Types a line of narration without running anything.
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

cd "${E2ER_DEMO_DIR:-/tmp/e2er-demo}" || exit 1
sleep 1

note "# Your own data, your own references. Two folders."
run "ls data literature" 2.2

note "# Point E2ER at them. Two settings, no code."
run "cat .env" 2.8

note "# Then ask whether it can actually run."
run "e2er doctor" 4
