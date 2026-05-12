# Allium queries via the gatekeeper CLI

This skill applies when the pipeline runs under `LLM_BACKEND=claude_code`
(Claude Code CLI). In that mode you have **no direct access to Allium's
HTTP API**. Instead, you invoke the bash command `e2er-allium-query`,
which validates your query against the same 5 guardrails as the JSON-tool
`query_allium` (used in API-backend mode), then forwards approved queries
to Allium and reports results back.

## Critical: discover before you filter

Allium stores enum-like columns (marketplace, currency, chain) with
**specific literal casings and values that you cannot guess**. The
marketplace column may store `'OpenSea'`, `'opensea'`, a smart-contract
address, or a numeric code — the answer depends on the table. **Always
discover, then filter.** Otherwise your `WHERE marketplace IN ('opensea')`
returns zero rows and the whole empirical section dies on no data.

Workflow:

```bash
# 1. Discover available schemas / tables
e2er-allium-query list-tables

# 2. Discover columns + types of a target table
e2er-allium-query describe-table --schema ethereum --table nft_trades

# 3. Discover actual values for any grouping column you intend to filter on
e2er-allium-query distinct-values --schema ethereum --table nft_trades --column marketplace --limit 50
# → returns the top-50 actual literals + their row counts
```

Only AFTER discovery, compose your feasibility / production queries using
the literals Allium reported back. If the values surprise you (numeric
codes? full contract addresses?), update `data_dictionary.json` to reflect
what's actually there.

## GROUP BY before WHERE IN

When you want to study cross-platform variation but don't yet know the
literals, **prefer `GROUP BY` to `WHERE IN (...)`**:

```sql
-- ✗ Fragile: if Allium stores 'OpenSea' not 'opensea', returns 0 rows
SELECT date, marketplace, SUM(price_native)
FROM ethereum.nft_trades
WHERE marketplace IN ('opensea', 'blur', 'x2y2')
  AND block_timestamp >= '2024-01-01'
GROUP BY 1, 2;

-- ✓ Robust: works whatever Allium uses; you see all venues, filter in pandas
SELECT date, marketplace, SUM(price_native) AS volume
FROM ethereum.nft_trades
WHERE block_timestamp >= '2024-01-01'
GROUP BY 1, 2
HAVING SUM(price_native) > 0;
```

GROUP BY buckets whatever literals exist; downstream analysis can filter
case-insensitively or by row count. WHERE IN locks you into your guess.

## The six subcommands

Two are discovery (read-only, no guardrail):
- `list-tables` — INFORMATION_SCHEMA.TABLES
- `describe-table` — INFORMATION_SCHEMA.COLUMNS for one table
- `distinct-values` — top values + counts of a column

Four are guarded queries (5 guardrails apply):
- `feasibility` — 1000-row sample, auto-approved
- `production` — full query, human approval required
- `check-approval` — poll a production query's status

Discovery first, feasibility second, production last.

## Discovery subcommands

You **do NOT need to pass `--paper-id`** — the runner has already wired it
into the environment. Just call the wrapper with the query-specific args:

```bash
# 1) Sample a query (1000-row LIMIT, auto-approved)
e2er-allium-query feasibility \
  --sql "SELECT block_number, ts FROM ethereum.blocks WHERE ts >= '2024-01-01' LIMIT 1000" \
  --fields block_number,ts \
  --aggregation daily \
  --rationale "verify data availability for the analysis window" \
  --primary-table ethereum.blocks

# 2) Submit a full query for human approval
e2er-allium-query production \
  --sql "..." --fields ... --aggregation transaction \
  --rationale "..." --primary-table ...

# 3) Poll for a production query's approval status
e2er-allium-query check-approval --query-id <QUERY_ID_FROM_STEP_2>

# 4) List available Allium dataset schemas/tables
e2er-allium-query list-tables
```

## Workflow rules

1. **Always run a `feasibility` query first** for any new table. Production
   queries on a table with no prior approved feasibility are rejected
   automatically (guardrail #5).
2. **Every query must list its fields explicitly** — no `SELECT *` (#1).
3. **Every query must have a time-bound `WHERE` clause** matching the
   `time_filter` declared in `data_dictionary.json` (#3).
4. **All selected fields must be in `data_dictionary.json`** (#2). Update
   the dictionary first if you need a new field.
5. **Transaction- or event-level granularity requires `--rationale`** that
   justifies why aggregating wouldn't suffice (#4).

## What the wrapper returns

stdout text mirrors what the JSON-tool returns to API-mode specialists:

- **On guardrail rejection**: a multi-line message starting with
  `"Query rejected by guardrails:"` followed by the specific rule that
  failed and a hint at how to fix it. Read it carefully — it tells you
  exactly what to change.
- **On feasibility success**: `query_id`, row count, the first 3 rows as
  JSON, and the columns. You may then use the data, or if you want the
  full result set, submit a `production` query (which the human reviews).
- **On production submission**: `query_id` and a reminder to poll
  `check-approval` until status is `APPROVED` or `REJECTED`. Do NOT keep
  resubmitting the same query.
- **On approval rejected**: the researcher's note explaining why. Submit
  a corrected production query — do not poll the rejected one again.

## Things you MUST NOT do

- **Do not call Allium HTTPS endpoints directly** (`mcp.allium.so`,
  `api.allium.so`, etc.). The CLI's tool restriction layer denies it; you
  will only frustrate yourself.
- **Do not pipe data through other bash commands** to bypass the
  gatekeeper. Curl, wget, custom Python — all blocked.
- **Do not skip the data dictionary update** if you need a new field. The
  gatekeeper checks every selected column against the live dictionary
  file in your workspace.

The wrapper IS your only Allium access.
