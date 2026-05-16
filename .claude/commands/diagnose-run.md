# Diagnose Paper Run

Given a paper UUID, surface what actually went wrong. This is the
fastest path from "the dashboard says failed" to "here's the
truncated-error-string-the-cascade-detector-hid-from-you".

`$ARGUMENTS` is the paper UUID. If absent, list the most recent failed/
paused papers and ask the user to pick.

## Process

### Step 1: Get high-level status

```bash
curl -s http://127.0.0.1:8280/api/papers/$ARGUMENTS | python3 -m json.tool
```

Read: `status`, `methodology`, `usage.specialist_calls`, `last_error`.
If `status` is `completed` and `last_error` is null, there's nothing to
diagnose — say so and stop.

### Step 2: Pull the event timeline

```bash
curl -s http://127.0.0.1:8280/api/papers/$ARGUMENTS/events | python3 -m json.tool | tail -80
```

Look for: `circuit_breaker_tripped`, `specialist_failed`, `failed`,
`phase_end` immediately followed by `phase_start` of the same phase
(retry storm), and any event with an `error` payload.

### Step 3: Pull the failure bundle (single-call diagnostic)

```bash
curl -s http://127.0.0.1:8280/api/papers/$ARGUMENTS/failure-bundle | python3 -m json.tool > /tmp/fb-$ARGUMENTS.json
```

The bundle has, in one JSON:
- Every event with full untruncated error text
- Per-specialist exit reasons, turn counts, durations, costs
- Workspace file listing (which canonical artifacts are present vs missing)
- Last 200 lines of the app log scoped to this paper

Highlight in your output:
- Which specialists failed and what they wrote (or didn't)
- Which canonical artifacts are missing — that's what cascade detection
  catches, and the missing-artifact name pins which phase died
- The first transient API error if any (api_error_status, overloaded_error)

### Step 4: Inspect the workspace if needed

```bash
ls -la Tests/workspaces/$ARGUMENTS/
```

If `data_summary.md` exists but is short, read it — `data_analyst`
writes failure reports there when the data layer is degraded. That's
often the most useful artifact.

### Step 5: Diagnose + recommend

Report to the user:
- **Root cause**: one sentence
- **Recoverable?**: if PAUSED, suggest `POST /api/papers/{id}/resume`
  after the underlying fix; if FAILED on transient API error, suggest
  resume directly; if FAILED on a real bug, surface the file + line
  that needs a fix
- **Regression test**: if the failure cause is something the test suite
  doesn't currently catch, propose adding a contract test in the
  appropriate `tests/{pipeline,data,lit}/contract/` dir

Do NOT auto-fix. The user decides whether and how to proceed.
