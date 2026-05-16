# Run a Paper

Submit a research question to the local pipeline and monitor it.
`$ARGUMENTS` is the research question prose. Optional flags:

- `--methodology empirical|theoretical|mixed` (default: empirical)
- `--mode single_pass|iterative` (default: single_pass)
- `--max-cost 5.0` (default: 5.0 USD per paper)
- `--monitor-seconds 600` (how long to follow the run; default 10 min)

## Process

### Step 1: Confirm the local app is up

```bash
curl -sf -o /dev/null -w "HTTP %{http_code}\n" http://127.0.0.1:8280/api/papers
```

If not 200, suggest `make rebuild-app` to start it. Don't proceed until
the API is reachable.

### Step 2: Submit the paper

```bash
curl -s -X POST http://127.0.0.1:8280/api/papers \
  -H "Content-Type: application/json" \
  -d '{
    "title": "<derive a 50-char title from the RQ>",
    "research_question": "<$ARGUMENTS verbatim>",
    "methodology": "<chosen methodology>",
    "pipeline_mode": "<chosen mode>",
    "max_specialists_per_phase": 6,
    "acknowledge_unproven_tuple": true,
    "max_cost_usd": <chosen cap>
  }' | python3 -m json.tool
```

Capture the `paper_id` from the response. Output it prominently — the
user will reference it.

### Step 3: Monitor

Open the dashboard URL in the response:

```
http://127.0.0.1:8280/papers/<paper_id>
```

Then poll status every 30 seconds for up to `--monitor-seconds`:

```bash
curl -s http://127.0.0.1:8280/api/papers/<paper_id> | \
  python3 -c "import sys, json; d=json.load(sys.stdin); u=d.get('usage',{}); print(f\"{d['status']} • specialists={u.get('specialist_calls')} • tokens={u.get('total_tokens')}\")"
```

Stop polling early if:
- `status` is `completed`, `failed`, `cancelled`, or `paused`
- The user types anything (interrupt)

### Step 4: Final report

When the run terminates, do ONE of these depending on status:

- **completed**: Show usage summary, link to the paper artifacts page,
  show the abstract from `workspace/abstract.tex` if present.
- **paused** (circuit breaker): Invoke `/diagnose-run <paper_id>`
  inline to surface the cause, then suggest the resume command.
- **failed**: Invoke `/diagnose-run <paper_id>` inline.
- **cancelled**: Acknowledge, don't auto-diagnose.

Do NOT auto-resume / auto-retry. The user decides.
