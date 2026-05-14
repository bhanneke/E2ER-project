# Allium Developer-tier API (when SQL Explorer is unavailable)

If `e2er-allium-query list-tables` returns empty or `Allium run failed`,
the account is on the **Developer tier**, not Explorer. The SQL surface
(`feasibility`, `production`, `list-tables`, `describe-table`,
`distinct-values`) is NOT available — using it wastes the rate budget.

Instead, use the developer REST endpoints exposed as these subcommands.
**All work through the same `e2er-allium-query` wrapper** — the model
never makes direct HTTP calls and the same audit / pacing applies.

## Tools available

```
e2er-allium-query get-transfers \
  --chain ethereum \
  --address 0x098B716B8Aaf21512996dC57EB0615e2383E2f96 \
  --token 0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48 \
  --min-timestamp 2022-03-22 \
  --max-timestamp 2022-03-25 \
  --limit 100
```
Token transfers involving a WALLET (the `--address`). Despite the path
name, this is wallet-scoped — Allium requires `address` and the optional
`token` filters to a single ERC-20 contract. Returns `from_address`,
`to_address`, `value`, `transaction_hash`, `block_timestamp`. **The date
filter actually works on this endpoint** (`min_timestamp` / `max_timestamp`
are the supported names per Allium's OpenAPI spec). Prefer this over
`get-wallet-tx` when you need a specific historical window.

```
e2er-allium-query get-wallet-tx \
  --chain ethereum \
  --address 0x098B716B8Aaf21512996dC57EB0615e2383E2f96 \
  --limit 25
```
Transaction history for one address. **No date filter is supported by
Allium on this endpoint.** It returns the most recent `--limit`
transactions and pages BACKWARD through history via `--cursor`. For
hack-event studies, use one of:
- `--transaction-hash 0x...` if you know the drain tx hash from the
  public post-mortem (cheapest path), or
- `--cursor <from_prev_response>` to walk back through history (only
  feasible if the target date is recent — old hacks require many pages).
For old events, **prefer `get-transfers`** instead — it supports
`--min-timestamp` and `--max-timestamp` directly.

```
e2er-allium-query get-balances-history \
  --chain ethereum \
  --address 0xa0c68C638235ee32657e8f720a23ceC1bFc77C77 \
  --from-ts 2023-07-25 \
  --to-ts 2023-08-15
```
Daily balance snapshots for one address. Required for measuring the
drawdown shape on victim contracts or whale wallets.

```
e2er-allium-query get-prices-history \
  --chain ethereum \
  --token-address 0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2 \
  --from-ts 2022-03-01 \
  --to-ts 2022-04-30
```
OHLC price history. **Fungible tokens only** — NFT contracts return
`{"items":[]}` with no error. Sanity-check first with `get-price`.

```
e2er-allium-query get-price \
  --chain ethereum \
  --token-address 0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2
```
Latest spot price. Cheap call; use it to verify a contract is indexed
before running a history window over it.

## Supported chains (this tier)

`ethereum`, `arbitrum`, `base`, `polygon`, `optimism`, `bsc`, `avalanche`,
`solana`, `bitcoin`, `near`, `stellar`, `hyperevm`, `unichain`, `celo`,
`worldchain`, `zora`, `x_layer`, `zksync` — coverage varies by endpoint.

## Critical discipline

**Write `data_summary.md` EARLY, then append.** Start by writing the
file with your plan and the events list — even before any data calls.
After each event's calls, append findings. This way `data_summary.md`
ALWAYS exists, even if you run out of turns mid-extraction. A partial
report is far more useful than no report and a "max_turns" failure.

**Always pass a time window** (`--from-ts` / `--to-ts`) on the history
endpoints. Without it, queries can scan all of chain history and burn
the rate budget on millions of unwanted rows.

**Budget your turns.** You have ~80 agent turns. Each tool call uses
~2. That's ~40 tool calls total — enough for ~10 events × 4 endpoints
× 1 page each if you keep pages SMALL (limit=20-50 is plenty for
proving the pattern). DO NOT page through entire histories — pick one
narrow window per event and move on.

**One page per call is usually enough.** Pagination via `next_token`
only when the first page clearly truncated something critical for the
analysis. For "what did the hacker do on day 0", limit=20 captures it.

**One contract per call**. The Allium API accepts list bodies but the
wrapper exposes one entry per call to keep error envelopes clean.
For multiple tokens, run multiple `get-prices-history` calls.

**Sanity-check before you blast history**. `get-price` on the contract
first — if it returns `{"items":[]}` with "No price data found", the
contract is an NFT or unindexed asset; don't run `get-prices-history`
on it.

## Output shape (uniform across all subcommands)

```json
{
  "items": [ /* response rows */ ],
  "next_token": "abc123..." | null,
  "error": null | "HTTP 429: ..." | "transport error: ..."
}
```

Check `error` BEFORE iterating `items`. On error, do NOT fabricate
substitute data — report the failure with the actual error string and
stop. The pipeline's data-quality rule applies the same here as for SQL.

## Hack-event study design (when this is the research question)

For an event study around a public exploit:

1. **Find the event details** via `WebFetch` or literature: exploit
   timestamp, hacker EOA, drained token contracts.
2. **Verify with `get-price`** that drained-token contracts are indexed.
3. **Pull `get-transfers`** for each affected token, window [t₀-30, t₀+30].
4. **Pull `get-wallet-tx`** for the hacker EOA, same window — captures
   the drain + first-hop laundering.
5. **Pull `get-balances-history`** for victim contracts (the protocol
   vaults that were drained) over the same window — drawdown shape.
6. **Pull `get-prices-history`** for the affected fungible token to add
   price impact alongside transfer-count dynamics.
7. Build a panel: token × day × outcome, write to
   `workspace/data/<event_slug>.parquet`.

Control groups: matched non-hacked tokens in the same window, OR the
same token in a placebo window 90d earlier.

If any step returns an error envelope and retry doesn't recover, stop
that event and move to the next. Document failures in `data_summary.md`.
Do NOT invent rows.
