# IV and Natural Experiments Database: Blockchain Economy

A curated database of potential identification strategies for causal research in the blockchain economy. Each entry documents an event, protocol change, or discontinuity that can serve as an instrument or treatment in an econometric design, together with the identification assumptions it requires and the threats it faces.

Contributions welcome: open a pull request or contact hanneke@wiwi.uni-frankfurt.de.

---

## How to read this table

**Type** classifies the design:
- **RDD** — regression discontinuity around a threshold (block number, parameter value, vote share)
- **DiD** — difference-in-differences around a policy or protocol event
- **IV** — instrumental variable (event or parameter shift used as instrument for an endogenous variable)
- **Event study** — abnormal-return or abnormal-activity analysis around a known date

**Relevance** is the primary outcome the strategy can credibly identify.

**Status** reflects whether the event has been used in published research (`Published`), is available and unused (`Available`), or is pending validation of data quality (`Check data`).

---

## Protocol Upgrades

| Event | Date | Chain | Type | Relevance | Identifying assumption | Key threats | Status |
|-------|------|-------|------|-----------|----------------------|-------------|--------|
| Ethereum Merge (PoW → PoS) | 2022-09-15 | ETH | DiD / Event study | Energy consumption, validator incentives, decentralisation | Date is fixed; irreversible | Anticipation effects (staking influx months before) | Available |
| EIP-1559 (fee burn, base fee) | 2021-08-05 | ETH | RDD / Event study | Gas price dynamics, miner revenue, transaction demand | Block-height cutoff is sharp | London hardfork was broadly anticipated | Available |
| EIP-4844 (proto-danksharding, blobs) | 2024-03-13 | ETH | DiD / Event study | L2 data costs, L2 activity, L1–L2 fee pass-through | Activation block is known | L2-specific anticipation; confounded by March 2024 market cycle | Available |
| Ethereum Shanghai upgrade (staking withdrawals enabled) | 2023-04-12 | ETH | Event study | Staking liquidity, liquid staking token prices, ETH sell pressure | Withdrawal queue opened at known block | Pre-positioning by large stakers | Available |
| Uniswap v3 launch (concentrated liquidity) | 2021-05-05 | ETH | DiD | LP returns, capital efficiency, impermanent loss | Pairs migrated sequentially to v3; v2 continues as control | Self-selection of pools migrating first | Available |
| Uniswap v4 launch (hooks, singleton) | 2024-Q4 | ETH | DiD | LP customisation, fee innovation, pool fragmentation | Pool-level adoption is staggered | Hooks introduce heterogeneous treatment | Check data |
| Curve Wars / bribe mechanism (Convex launch) | 2021-05-17 | ETH | DiD / Event study | Governance token value, liquidity incentive efficiency | Convex launch date is clean | Curve gauge weights were already contested before | Available |
| Arbitrum Nitro upgrade | 2022-08-31 | ARB | DiD | L2 throughput, gas costs, user migration from L1 | Upgrade block is known | Demand shocks coincide with bear market | Available |
| Optimism Bedrock upgrade | 2023-06-06 | OP | DiD | L2 gas costs, sequencer revenue, deposit/withdrawal latency | Known upgrade date | Contemporaneous market conditions | Available |
| Solana TurbineV3 / QUIC | 2022–2023 | SOL | Event study | Network throughput, validator economics | Network-level parameter change | Phased rollout reduces sharpness | Check data |

---

## Regulatory and Legal Events

| Event | Date | Jurisdiction | Type | Relevance | Identifying assumption | Key threats | Status |
|-------|------|-------------|------|-----------|----------------------|-------------|--------|
| Bitcoin spot ETF approval (BlackRock, Fidelity et al.) | 2024-01-10 | US | DiD / Event study | BTC volatility, institutional participation, basis trade | Approval date from SEC is exogenous to intraday market | Pre-positioning; leaked information | Published |
| SEC action against Coinbase and Binance | 2023-06-06/13 | US | Event study | Exchange volume, token delistings, DeFi migration | Filing dates are known | Both actions on consecutive days make DiD difficult | Available |
| MiCA regulation (Markets in Crypto-Assets) — entry into force | 2023-06-29 / 2024-12-30 | EU | DiD | Stablecoin issuance, EU exchange activity, compliance costs | EU firms face regulation; non-EU firms as control | Phased implementation; anticipation | Available |
| China crypto mining ban (final order) | 2021-09-24 | CN | DiD / Event study | Bitcoin hash rate reallocation, mining revenue, energy market | Mining ban date is sharp; China-attributable hash rate measurable | Prior partial bans create anticipation | Published |
| Tornado Cash OFAC sanction | 2022-08-08 | US | Event study | DeFi privacy protocol usage, on-chain compliance, mixer alternatives | Sanction date is sharp | Contemporaneous ETH bear market | Available |
| Ripple partial summary judgment (XRP not a security in secondary sales) | 2023-07-13 | US | Event study | XRP price, exchange relisting decisions, altcoin correlation | Court order date is publicly known | Market-wide crypto rally contemporaneous | Available |
| FTX collapse and bankruptcy filing | 2022-11-11 | — | Event study | Exchange contagion, DEX vs CEX volume, token prices | Filing date is known | Multi-day crisis; spillovers to other entities | Published |
| 3AC / Celsius / BlockFi insolvencies | 2022-06/07 | — | Event study | Contagion to CeFi lending, BTC/ETH collateral liquidations | Sequential filing dates | Clustered defaults make DiD design difficult | Available |

---

## DeFi Governance and Parameter Changes

| Event | Date | Protocol | Type | Relevance | Identifying assumption | Key threats | Status |
|-------|------|---------|------|-----------|----------------------|-------------|--------|
| Compound "COMP" liquidity mining launch | 2020-06-15 | Compound | DiD / Event study | Yield farming, TVL, token incentive efficiency | Activation block is known; no prior COMP distribution | Concurrent Balancer BAL launch | Published |
| Aave v3 Portals / cross-chain collateral | 2022-03-16 | Aave | DiD | Cross-chain capital flows, liquidation efficiency | Deployment block per chain is known | Phased rollout | Available |
| MakerDAO PSM launch (USDC peg stability module) | 2020-11-01 | Maker | DiD | DAI peg quality, USDC holdings in Maker, DeFi composability | Launch block is known | DAI was already largely pegged | Available |
| MakerDAO spark SubDAO and DAI Savings Rate changes | 2023 | Maker | IV / DiD | On-chain savings behaviour, DAI demand | DSR changes are governance-voted on known dates | Endogenous to macro rates | Available |
| Uniswap fee switch governance vote | 2024 | Uniswap | Event study | UNI token valuation, LP behaviour anticipation | Vote outcome is exogenous to LP returns | Not yet activated at time of writing | Check data |
| Curve gauge weight manipulation / Mochi attack | 2021-10 | Curve | Event study | Governance token attack surface, bribe market dynamics | Attack date is known | Short-lived; data cleaning required | Available |
| Liquity v1 launch (0% interest, 110% CR) | 2021-04-05 | Liquity | DiD | CDP usage, stablecoin peg mechanics, competitor protocol deposits | Launch date is known; distinct parameter regime | LUSD market size limits power | Available |

---

## NFT Market Events

| Event | Date | Platform | Type | Relevance | Identifying assumption | Key threats | Status |
|-------|------|---------|------|-----------|----------------------|-------------|--------|
| OpenSea move to Seaport protocol | 2022-06-14 | OpenSea | DiD | Marketplace fees, NFT liquidity, royalty enforcement | Protocol migration date is known | Blur was already emerging as competitor | Available |
| Blur launch and airdrop farming | 2022-10-19 | Blur | DiD | NFT bid-ask spreads, wash trading, royalty bypassing | Launch date known; OpenSea as control | Wash trading confounds volume metrics | Available |
| Creator royalty enforcement breakdown (EIP-2981 not enforced) | 2022–2023 | Market-wide | DiD | Creator revenue, NFT floor prices, collection launches | Platform-by-platform adoption of bypass is staggered | Demand trends confound identification | Available |
| Bored Ape Yacht Club / Yuga Labs Otherside mint | 2022-04-30 | ETH | Event study | Gas market congestion, NFT mint mechanisms, ETH burn | Date is known; event caused extreme gas spike | Non-random selection of participating wallets | Available |

---

## Cross-Chain and Bridging Events

| Event | Date | Type | Relevance | Identifying assumption | Key threats | Status |
|-------|------|------|-----------|----------------------|-------------|--------|
| Ronin Bridge hack ($625M) | 2022-03-23 | Event study | Bridge security, TVL flight, insurance protocol demand | Hack date is known | Contemporaneous macro events | Available |
| Wormhole bridge exploit ($320M) | 2022-02-02 | Event study | Cross-chain TVL reallocation, bridge usage after exploit | Exploit date is known | Overlaps with BTC/ETH correction | Available |
| LayerZero V2 mainnet / airdrop | 2024 | DiD | Omnichain messaging, cross-chain DeFi composability | Activation date known; v1 as control | Airdrop farming distorts usage | Check data |
| Cosmos IBC v1 launch | 2021-03-18 | IBC | DiD | Cross-chain token flows, DEX arbitrage, validator behaviour | IBC activation per chain is staggered | Chain heterogeneity is large | Available |

---

## Bitcoin-Specific Events

| Event | Date | Type | Relevance | Identifying assumption | Key threats | Status |
|-------|------|------|-----------|----------------------|-------------|--------|
| Bitcoin halving (block reward 50→25) | 2012-11-28 | Event study | Miner revenue, hash rate, price | Block-height cutoff is exact | Anticipation effect from known schedule | Published |
| Bitcoin halving (25→12.5) | 2016-07-09 | Event study | As above | As above | As above | Published |
| Bitcoin halving (12.5→6.25) | 2020-05-11 | Event study | As above | As above | As above | Published |
| Bitcoin halving (6.25→3.125) | 2024-04-19 | Event study | As above; first halving in ETF era | As above | Institutional demand from ETFs changes regime | Available |
| Taproot activation (Schnorr, MAST) | 2021-11-14 | DiD / Event study | Script complexity, Lightning channel adoption, privacy | Block height 709,632 is sharp | Long anticipation period (BIP proposed 2020) | Available |
| Lightning Network capacity growth | Ongoing | IV | Payment channel economics, BTC settlement velocity | Network capacity growth is exogenous to individual node decisions | Endogeneity if researcher selects capacity-driven episodes | Available |
| MicroStrategy first BTC purchase | 2020-08-11 | Event study | Institutional demand signal, altcoin correlation | Purchase announcement date | Strategy was telegraphed in earnings call before closing | Available |

---

## Stablecoin Events

| Event | Date | Type | Relevance | Identifying assumption | Key threats | Status |
|-------|------|------|-----------|----------------------|-------------|--------|
| Terra/Luna UST depeg and collapse | 2022-05-09 | Event study | Algorithmic stablecoin viability, contagion, DeFi TVL | Depeg cascade start date | Complex multi-day event; endogenous reflexivity | Published |
| USDC depeg after SVB collapse | 2023-03-10 | Event study | Fiat-backed stablecoin tail risk, bank reserve exposure | SVB receivership announcement | Weekend depeg partially recovers before markets open | Available |
| Tether transparency improvements (attestation releases) | 2021–2023 | DiD | USDT discount/premium, counterparty risk perception | Attestation release dates are exogenous to market | Markets had variable reactions; power is low | Check data |
| BUSD wind-down order (Paxos / NYDFS) | 2023-02-13 | Event study | Stablecoin market concentration, Binance USD volume | Regulatory order date is known | Binance-specific confounds | Available |

---

## Infrastructure and Tooling

| Event | Date | Type | Relevance | Identifying assumption | Key threats | Status |
|-------|------|------|-----------|----------------------|-------------|--------|
| Flashbots MEV-Boost launch (PBS for validators) | 2022-09-15 | DiD | MEV extraction, validator revenue, transaction ordering | Launched at the Merge; validators opt in | Rapid adoption rate reduces pre/post contrast | Available |
| ERC-4337 account abstraction deployment | 2023-03-01 | DiD | Wallet UX, gas sponsorship, smart account adoption | Deployment block is known | Slow adoption limits statistical power | Check data |
| Chainlink CCIP launch | 2023-07-17 | DiD | Cross-chain oracle reliability, bridge alternatives | Launch date known; existing Chainlink oracles as control | Limited adoption in first months | Check data |
| Ethereum validator slashing events (major) | Various | Event study | Validator behaviour, staking yield, slashing insurance demand | Slashing blocks are on-chain observable | Small number of major events limits power | Available |

---

## Using this database

**For DiD designs**: select protocol-change events with a plausible control group (comparable chains or tokens not affected) and verify pre-trends in at least 4 weeks of panel data.

**For event studies**: use intraday data where available; standard windows are [-1, +1], [-5, +5], and [-30, +30] trading days. Account for Bitcoin/Ethereum market beta before attributing abnormal returns to the event.

**For IV designs**: verify the first stage (instrument relevance) with F > 10 before interpreting LATE. Check exclusion restriction narratives carefully: almost all blockchain instruments affect multiple outcomes.

**For RDD designs**: the forcing variable (block number, vote threshold, parameter value) must be continuous and manipulable by agents only if they can perfectly time on-chain actions. In practice, block-number RDDs are sharp but anticipation is common.

---

## Contributing

To add an entry:

1. Fork the repository
2. Add your event to the relevant section with all columns populated
3. Include a `Status` of `Check data` if you have not personally verified data availability
4. Open a pull request with a one-sentence summary of why the event is a useful instrument

Priority areas: **Layer 2 governance events**, **DeFi liquidation cascade triggers**, **cross-chain bridge exploits**, **DAO treasury management decisions**, and **oracle manipulation attacks**.
