#!/usr/bin/env bash
# SessionStart hook: injects a mandatory onboarding brief at the top of every
# new Claude Code session in this repo. Wired in .claude/settings.json.
#
# Two parts:
#   1. Static brief — what this repo is, the three-lane split, required
#      reading, hard rules. Edit this section as the codebase evolves.
#   2. Dynamic state — branch, recent commits, CI status, open critical
#      issues. Generated fresh at session start so Claude has current
#      context without spending tokens on git/gh commands.
#
# Output is captured by Claude Code as additional session context.

set -euo pipefail

cat <<'BRIEF'
# Session brief — E2ER v3

This repo is `E2ER` — End-to-End Researcher, an open-source pipeline for
producing peer-review-quality empirical research papers in IS, economics,
and finance. BYOK + three optional LLM backends (Anthropic SDK,
OpenRouter, Claude Code CLI subprocess; Codex/Gemini headless backends
coming in Phase 4 of the stability sprint).

Before responding to the user's first message, read items 1-3 below so
you have a working model of the codebase. This is a hard requirement.

## Required reading (do these first, in order)

1. `AGENTS.md` — branch workflow (dev/main split), three-lane split with
   public contracts, release procedure, hard rules.
2. `CLAUDE.md` — Claude-specific notes: pipeline mechanics, hot-spots,
   Allium gatekeeper, CLI-backend gotchas.
3. `docs/NEXT_STEPS.md` — current snapshot of in-flight work + open issues.

## Skim (glance, don't deep-read)

4. `src/core/` — Lane A (knowledge production pipeline)
5. `src/modules/literature/` — Lane B (literature/KB ingestion)
6. `src/modules/data/` — Lane C (data module + Allium clients)
7. `.claude/commands/` — available slash commands (once Phase 5 lands)
8. `tests/{pipeline,lit,data,shared}/` — tests mirror lane structure

## Read on demand (only when the user's task touches the area)

| Area                              | File(s) to read                                  |
|-----------------------------------|--------------------------------------------------|
| Specialist orchestration          | `src/core/specialists/{base,dispatcher,registry}.py` |
| Strategist / runner               | `src/core/strategist/runner.py`, `engine.py`     |
| LLM backends                      | `src/modules/llm/{base,claude_code,anthropic,openrouter}.py` |
| Allium SQL                        | `src/modules/data/allium.py`                     |
| Allium developer REST             | `src/modules/data/allium_developer.py`           |
| CLI gatekeeper                    | `src/modules/data/cli.py`, `scripts/e2er-allium-query` |
| Guardrails / audit / dictionary   | `src/modules/data/{guardrails,audit,dictionary}.py` |
| Skills                            | `src/skills/loader.py`, `skills/files/<category>/<name>.md` |
| API                               | `src/api/app.py`                                 |
| LaTeX rendering                   | `src/core/renderer/`                             |

## Hard rules (re-stated from AGENTS.md)

- **Branch model**: `dev` is integration, `main` is released. Feature
  PRs target `dev`, never `main`. Branch protection enforces this on
  `main`.
- **No direct push to `main`.** PRs only.
- **No live paper runs from `dev`** without prior integration-smoke pass.
- **Cross-lane changes need an explicit flag** in the PR description.
- **A failed live paper run is a test failure** — fix lands with a
  regression test in the relevant lane's `tests/`.
- **Specialists access Allium ONLY via `e2er-allium-query`** wrapper.
  The `--allowedTools=Bash(e2er-allium-query:*)` pattern is enforced;
  no bare `Bash` is allowed.

## What to do after reading

Reply to the user's first message normally. One sentence acknowledging
you have context is enough. Don't recite the brief back.

If the user's first message is trivial ("hi", "what time is it"), skip
items 2-3 but still read AGENTS.md.

---
BRIEF

# Dynamic state — generated fresh at session start.
echo "## Current repo state ($(date +'%Y-%m-%d %H:%M %Z'))"
echo

cd "$CLAUDE_PROJECT_DIR" 2>/dev/null || true

# Branch + uncommitted state
branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "?")
ahead_behind=$(git rev-list --left-right --count "@{u}...HEAD" 2>/dev/null | awk '{print "behind=" $1 " ahead=" $2}' || echo "no upstream")
dirty=$(git status --porcelain 2>/dev/null | wc -l | tr -d ' ')
echo "**Branch**: \`$branch\` ($ahead_behind, dirty=$dirty files)"

# Last 5 commits
echo
echo "**Last 5 commits**:"
git log --oneline -5 2>/dev/null | sed 's/^/  /' || echo "  (no git history available)"

# CI status of latest run
echo
if command -v gh >/dev/null 2>&1; then
  latest_ci=$(gh run list -L 1 --json conclusion,workflowName,headBranch,createdAt 2>/dev/null \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(f\"{d[0]['conclusion'] or 'in_progress'} • {d[0]['workflowName']} on {d[0]['headBranch']} ({d[0]['createdAt'][:16]})\") if d else print('(no runs)')" 2>/dev/null)
  echo "**Last CI run**: ${latest_ci:-(unavailable)}"
else
  echo "**Last CI run**: (gh CLI not installed)"
fi

# Open issues count (only show if there are any with critical/blocker labels)
if command -v gh >/dev/null 2>&1; then
  critical_count=$(gh issue list --label "critical,blocker" --state open --json number 2>/dev/null | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "?")
  if [ "$critical_count" != "0" ] && [ "$critical_count" != "?" ]; then
    echo
    echo "**⚠️  $critical_count open critical/blocker issue(s)** — check with \`gh issue list --label critical,blocker --state open\`"
  fi
fi

# In-flight paper runs (if app is up locally)
if curl -sf -o /tmp/_e2er_papers.json --max-time 2 http://127.0.0.1:8280/api/papers 2>/dev/null; then
  in_progress=$(python3 -c "import json; d=json.load(open('/tmp/_e2er_papers.json')); print(sum(1 for p in d if p.get('status') in ('running','in_progress','designing','review','revision')))" 2>/dev/null)
  if [ "${in_progress:-0}" -gt 0 ]; then
    echo
    echo "**🔬 $in_progress paper run(s) in flight on local app** (port 8280)"
  fi
fi

echo
echo "---"
echo
