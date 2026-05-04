# Blockchain Data Skill

## Data characteristics

Blockchain data is:
- **Fully public and deterministic** — every transaction is recorded on-chain and verifiable
- **Pseudonymous, not anonymous** — addresses can often be linked to entities via clustering
- **High-frequency and granular** — transactions occur at block-level (seconds to minutes)
- **Irreversible** — no retroactive changes; ideal for natural experiments

## Common datasets

| Dataset | Granularity | Use case |
|---------|------------|----------|
| Transfer events | Per transaction | DeFi flows, token velocity |
| DEX trades | Per swap | Price impact, liquidity |
| LP positions | Per block | Liquidity provision behavior |
| Governance votes | Per proposal | Voting patterns, whale behavior |
| Smart contract calls | Per call | Protocol usage, feature adoption |

## Data quality issues

- **Wash trading**: circular transactions inflate volume — filter using address clustering
- **MEV**: sandwich attacks distort price discovery — consider filtering MEV bots
- **Dust transactions**: small-value spam — apply minimum value threshold
- **Bridge transactions**: cross-chain flows may double-count — identify bridge contracts

## Identification opportunities

- **Protocol launches/upgrades**: sharp treatment discontinuities
- **Token incentive changes**: regression discontinuity on governance votes
- **Network congestion events**: exogenous variation in fees (IV for adoption)
- **Hack/exploit events**: difference-in-differences (affected vs. comparable protocol)

## Required data fields

Always request: timestamp, block_number, transaction_hash, from_address, to_address, value/amount.
Add token_address for ERC-20 transfers.

## Query best practices (Allium)

- Always add a time-bound WHERE clause on `block_timestamp`
- Aggregate to daily/weekly for large datasets before requesting full production run
- Run feasibility query first with LIMIT 1000
- Justify transaction-level granularity if needed (most questions don't need it)
