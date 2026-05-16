# Pre-PR Checklist for E2ER

Run this before opening a PR from a feature branch into `dev`. Three
gates, in order — each blocks the next.

Base branch is **`dev`**, not `main`. Release PRs (`dev` → `main`) follow
a different flow; see AGENTS.md.

## Process

### Step 1: Identify what changed (per lane)

```bash
git fetch origin
git diff origin/dev...HEAD --stat
git log origin/dev..HEAD --oneline
```

Categorize the diff by lane (Pipeline / Lit / Data) per `AGENTS.md`.
If a single PR touches more than one lane, call it out — the lane-CI
workflows will all fire, and per the discipline that's fine, but it
needs to be intentional, not accidental.

### Step 2: Security gate (BLOCKING)

```bash
# No secret should appear in any tracked file.
git diff origin/dev...HEAD -- '*.env*' | head -5
git diff origin/dev...HEAD | grep -iE 'api[_-]?key|secret|token' | head -5
```

If anything looks like a leaked credential, **halt**, surface the file
+ line, and ask the user to confirm. Don't proceed to Step 3 until
resolved.

Also check `.env` and `.env.example` haven't been swapped — `.env`
must NEVER be tracked.

```bash
git ls-files | grep -E '^\.env$' && echo "FAIL: .env is tracked" || echo "OK: .env is not tracked"
```

### Step 3: Run the local check suite

```bash
make check
```

This runs ruff + pytest. Both must pass. Tail the output and report
which step failed if any. `make check` is the same gate CI runs, so a
green local run is a strong signal CI will also be green.

### Step 4: Verify CHANGELOG entry exists

```bash
git diff origin/dev...HEAD -- CHANGELOG.md | head -20
```

Substantive changes (any code change beyond docs/typos) need an entry
under `## Unreleased` in the right lane sub-heading (`### Lane A`,
`### Lane B`, or `### Lane C` — see AGENTS.md).

If missing, suggest one to the user, edit it in, run Step 4 again.

### Step 5: Read the diff with one fresh agent

```bash
# Hand the diff to a code-review subagent.
```

Use the Agent tool with a focused review prompt:
- Spot bugs (off-by-one, race conditions, missed error cases)
- Verify the test diff actually covers the code diff
- Check for accidental scope creep (changes unrelated to the PR title)

Keep the review prompt under 200 words; ask for a "blocker / nit /
nothing" verdict.

### Step 6: Verdict

Report to the user:
- ✓ / ✗ each step
- Suggested PR title (use the first commit subject if multiple)
- Suggested CHANGELOG entry if you wrote one

If every gate passed, suggest the exact `gh pr create` invocation
(base `dev`, label by lane if your repo uses lane labels).
