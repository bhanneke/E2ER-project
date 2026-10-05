# Paper Plan

**Working title:** *No Cash Flows, New Owners: Spot Bitcoin ETFs and the Origins of Comovement*

**Alternative titles:** "Who Holds the Asset Determines Its Betas: Evidence from the Spot Bitcoin ETF Approval" · "Access Without Fundamentals: Habitat Effects in an Asset with No Cash Flows"

**Research question:** Did the January 2024 approval of US spot Bitcoin ETFs change the co-movement between Bitcoin returns and US equity returns — and if so, through which channel?

**Paper ID:** e432cf3f-9008-4202-8ee6-ff09a93948ec · **Stage:** idea → plan · **Methodology:** empirical

---

## 0. Executive summary for the pipeline

This paper uses the SEC's January 10–11, 2024 approval of eleven US spot Bitcoin ETFs as a structural break in the *investor base* and *access technology* for Bitcoin, and asks whether Bitcoin's factor loadings on US equities changed as a result.

The intellectual centerpiece is a property of the setting that no equity-market study of comovement can claim: **Bitcoin has no cash flows.** In every prior index-inclusion or ETF-comovement study, a post-event rise in comovement is contestable — perhaps the firm's fundamentals genuinely became more correlated with the market. Here that alternative is shut off by construction. Bitcoin's protocol issuance schedule is fixed and public; there are no earnings, no analysts revising forecasts, no cash-flow news to become more correlated. Any change in factor loadings is therefore a *discount-rate* or *clientele* effect. The setting turns a decades-old identification debate — Barberis–Shleifer–Wurgler's category/habitat view versus the fundamentals view of comovement — into a test where one side of the debate is unavailable a priori.

The paper is therefore not "does Bitcoin correlate with stocks now." It is: **does changing who holds an asset change its factor structure, when fundamentals are held mechanically constant?**

Four layered research designs, in descending order of identification strength:

| # | Design | What it identifies | Primary threat |
|---|--------|--------------------|----------------|
| **D1** | Staggered DiD across coins (BTC Jan-2024, ETH Jul-2024, SOL/XRP 2025 cohorts; never-treated controls) | Differential change in equity beta attributable to ETF access, netting out common macro regime | Coins not exchangeable; cross-coin spillovers attenuate toward zero |
| **D2** | Intraday session decomposition (US cash session vs. Asia/Europe overnight) | Whether new comovement is *mechanically located* in US trading hours | Session-specific macro news timing |
| **D3** | Flow dose–response, splitting basis-trade from allocation flows; IV from platform/wirehouse access openings | The habitat/arbitrage mechanism | Flow endogeneity; instrument exclusion |
| **D4** | Announcement event study, with the Jan-9 false tweet as a sentiment-only placebo | Separates *news* from *plumbing* | Anticipation; narrow window |

**D2 is the paper's most persuasive single exhibit and it is cheap to produce.** A general risk-on macro regime raises BTC–equity correlation in *all* sessions equally; only the ETF channel predicts the increase concentrates in 09:30–16:00 ET and specifically into the NAV-strike window. Downstream specialists should prioritize it.

**Both signs are publishable.** If beta does not rise, the paper's contribution flips to a reverse insight (§7.5): shared ownership and a shared trading venue are *insufficient* for habitat comovement, which would favor the information-diffusion view over the pure category view. This is pre-committed in §9, not rationalized after the fact.

---

## 1. The phenomenon (stated without reference to any paper)

On January 10, 2024, the SEC approved eleven spot Bitcoin exchange-traded products; they began trading January 11. Within roughly a year the complex had gathered on the order of $100 billion in assets, and BlackRock's IBIT became one of the fastest-growing ETFs in the history of the product. Overnight, an asset that US wealth-management channels could previously access only awkwardly — through a futures-based ETF with roll costs, through a closed-end trust trading at a persistent discount, or by opening an account at a crypto exchange and self-custodying — became a line item with a CUSIP, a daily NAV, standard brokerage custody, and eligibility for model portfolios and margin.

Nothing about Bitcoin itself changed. The supply schedule, the block time, the code, the 24/7 global spot market: all identical on January 12 to what they were on January 9. The only thing that changed was *who could conveniently hold it, and in what wrapper.*

The puzzle: Bitcoin was, for most of its history, marketed and empirically defended as a diversifier — an asset uncorrelated with equities. Over 2020–2022 that claim weakened considerably as correlations with US technology stocks rose. After January 2024, does Bitcoin become a conventional risk asset — moving with the S&P 500 because it is now owned inside portfolios that move with the S&P 500 — or does it retain a distinct return process because the money flowing into these ETFs is crypto-native money that happens to have found a more convenient pipe?

**Why this needs explanation.** There is a real tension. Standard portfolio theory says the wrapper is irrelevant: an asset's covariance with the market is a property of its payoff, not its custody arrangement. The habitat and style-investing literatures say the opposite: ownership structure shapes comovement even absent any change in fundamentals. Bitcoin, having no fundamentals to change, is the sharpest available referee between these views.

**Who cares and what changes.** (i) *Asset allocators*: the entire case for a 1–5% crypto sleeve rests on a low correlation input. If β rose from ~0.5 to ~1.0, the mean–variance-optimal sleeve shrinks materially, and the marginal risk contribution of that sleeve to a 60/40 portfolio rises roughly in proportion. Concretely, the paper will report the implied change in optimal weight and in marginal contribution to portfolio risk — this is the deliverable allocators act on. (ii) *Regulators*: the SEC's own approval order and dissents debated whether an ETF would import crypto volatility into mainstream portfolios and create a new channel of contagion. This paper measures that channel. (iii) *Financial economists*: this is a clean test of whether the marginal investor's identity determines an asset's factor loadings.

---

## 2. The core economic tension

Two hypotheses make opposing predictions. Both are ex-ante plausible; the paper is designed so that the data can distinguish them.

### H1 — Broadened access / institutional integration (β rises)

The ETF lowers the participation cost for US investors whose marginal utility is already tied to US equity wealth. As those investors become the marginal price-setters in Bitcoin, Bitcoin's price loads on *their* stochastic discount factor. Three sub-channels:

- **Clientele/SDF channel.** A Merton (1987) investor-recognition story: pre-ETF, a participation cost κ excludes US allocators; the ETF cuts κ; the marginal investor's SDF shifts toward the one that prices US equities. Common discount-rate shocks (Fed policy, risk premia) now transmit to Bitcoin.
- **Habitat/category channel.** Barberis–Shleifer–Wurgler: assets held by a common clientele comove because that clientele's flows are correlated, regardless of fundamentals. Bitcoin has entered the US brokerage habitat.
- **Arbitrage/plumbing channel.** Da–Shive and Ben-David–Franzoni–Moussawi: creation/redemption arbitrage mechanically links ETF-wrapped assets to the trading of the wrapper. Authorized-participant activity injects wrapper-level (and hence equity-market-hours, equity-market-liquidity) shocks into the underlying.

**Predictions:** β_BTC,MKT ↑; conditional correlation ↑; loading on funding-liquidity and risk-appetite factors ↑; the increase concentrated in US cash-session hours and scaling with creation/redemption intensity.

### H2 — Segmentation / diversifier persistence (β unchanged or falls)

If ETF flows are driven by *idiosyncratic crypto-native demand* — halving-cycle narratives, digital-gold beliefs, election-driven policy speculation — then the entrants' demand shocks are orthogonal to the equity SDF and comovement need not rise. Two sub-channels, one of which predicts a *decline*:

- **Orthogonal-demand channel.** New money is large but its information set is crypto-specific. Bitcoin becomes more liquid and better-arbitraged without becoming more equity-like.
- **Noise-reduction channel.** Pre-ETF retail accessed both meme equities and crypto through the same brokerage apps and the same sentiment cycle — a correlated-noise-trader channel. A deep, institutionally-arbitraged ETF can *displace* that marginal noise trader and *reduce* the sentiment-driven component of comovement. β falls.

**Predictions:** β flat or ↓; no session concentration; no flow dose–response.

### H3 — The basis-trade confound (a third path that must be separated)

A large share of early institutional ETF ownership was not allocation at all: hedge funds ran the cash-and-carry basis trade, long the spot ETF and short CME futures. This position is market-neutral by construction and predicts **no** change in Bitcoin's equity beta despite enormous AUM. Any test that uses headline AUM or headline flows as the treatment intensity will therefore be badly mis-specified.

**This is the plan's key specification insight.** §5.3 decomposes flows into a basis-trade component (projected on the annualized CME futures basis and futures open interest) and an allocation component (the residual, validated against 13F filer types). H1 predicts only the *allocation* component moves beta. A finding that AUM exploded while the allocation component stayed small would reconcile a large flow story with a null beta result — and would itself be an important result.

### Distinguishing the hypotheses

| Test | H1 Integration | H2 Segmentation | H3 Basis trade |
|---|---|---|---|
| Δβ post-2024, net of macro (D1) | > 0 | ≤ 0 | ≈ 0 |
| Comovement concentrated in US session (D2) | Yes | No | No |
| β scales with *allocation* flows (D3) | Yes | No | No |
| β scales with *total* flows (D3) | Yes | No | Spuriously yes |
| Factor loading migrates tech → broad market (§6.4) | Yes | No | No |
| Real approval > false-tweet effect (D4) | Yes | — | — |

---

## 3. Contribution and positioning

### 3.1 The archetypal problem

Stripped of its setting, the paper asks: **does the identity of the marginal investor determine an asset's factor structure?** This is the comovement question of Barberis–Shleifer–Wurgler, the financialization question of Tang–Xiong and Cheng–Xiong, and the market-integration question of Bekaert–Harvey. Bitcoin is the lens, not the subject.

### 3.2 Closest prior work

> **Pipeline note.** The bibliography supplied with this work order (`literature.bib`) is largely auto-harvested and off-topic. The literature specialist must replace it. The two entries below are genuinely close and must be retrieved in full; the remainder of the supplied bib should be treated as noise. Characterizations of `khatib2026from` below are inferred **from its title and outlet only** — the full text has not been read and these inferences must be verified before the positioning paragraph is written.

**Direct competitors (must be read in full and cited by name):**

1. **Al khatib & Alshaib (2026), "From contagion to stabilization: Spot Bitcoin ETFs and the regime shift in crypto-equity integration," *International Review of Economics & Finance*.** This is the nearest competitor and asks a very similar question. Based on title and outlet, it likely documents a regime shift using a connectedness or TVP-VAR framework. **Do not write around this paper.** Position head-on: they characterize the shift; we identify it against a counterfactual (D1) and test its mechanism (D2, D3). If, on reading, they already implement a cross-asset counterfactual, the paper repositions onto the mechanism tests and the cash-flow-free identification argument, which remain unclaimed.
2. **Tang (2026), "The Structural Impact of Bitcoin Spot ETFs on Liquidity and Risk Spillovers in the Cryptocurrency Market."** Within-crypto spillovers; our outcome is crypto→equity factor loadings. Complementary, and a source of the SUTVA concern in D1.
3. **Pucher, Schiereck & Bormann (2026), "False-News Triggers As New Manipulation Risk — Evidence From The Bitcoin ETF Approval," *JAIS*.** Studies the January 9, 2024 compromised-SEC-account false approval tweet. **We repurpose their event as our placebo** (D4): a pure sentiment shock with no access change, against the January 10–11 access shock. Cite generously — this is a complement, not a competitor.
4. **Guliyev & Ahmadova (2025), "From Flows to Value: Cointegration Between Bitcoin Spot ETF Assets and Bitcoin Price," *Ledger*.** Flows→price level. We study flows→*factor loadings*, and we decompose flows (§5.3), which a cointegration design cannot.

**Foundational literature the paper builds on** (to be verified and completed by the literature specialist):

- *Comovement and habitat:* Barberis & Shleifer (2003, JFE) style investing; Barberis, Shleifer & Wurgler (2005, JFE) comovement; Boyer (2011, JF) style-related comovement using mechanical index reclassification; Greenwood (2008, RFS) Nikkei redefinition.
- *Index/ETF inclusion:* Shleifer (1986, JF) and Harris & Gurel (1986, JF) demand curves; Vijh (1994, RFS) S&P inclusion and beta — the direct antecedent; Da & Shive (2018, JBF) ETF ownership and return correlations; Ben-David, Franzoni & Moussawi (2018, JF) ETFs and volatility; Israeli, Lee & Sridharan (2017, RAST).
- *Financialization — the closest structural analogue:* Tang & Xiong (2012, FAJ) index investment and commodity comovement; Cheng & Xiong (2014, ARFE) — the nuanced counterweight, arguing index-flow effects are overstated; Henderson, Pearson & Wang (2015, RFS) commodity-linked notes; Basak & Pavlova (2016, ManSci); Hong & Yogo (2012, JFE). **Commodities are the precedent: a new financial product arrived and correlations with equities jumped. Our setting improves on it because commodities have real supply-and-demand fundamentals that could plausibly have become more correlated; Bitcoin has none.**
- *Segmentation and integration:* Merton (1987, JF) investor recognition — the workhorse for §4; Bekaert & Harvey (1995, JF) time-varying integration; Karolyi & Stulz (1996, JF).
- *Crypto asset pricing:* Liu & Tsyvinski (2021, RFS); Liu, Tsyvinski & Wu (2022, JF); Makarov & Schoar (2020, JFE) cross-exchange segmentation and (2022, BPEA) ownership concentration; Biais et al. (2023, RFS); Iyer (2022, IMF WP) "Cryptic Connections" — the pre-period benchmark for rising crypto–equity spillovers.
- *Econometrics:* Engle (2002, JBES) DCC and Engle (2016) dynamic conditional beta; Bai & Perron (1998, 2003); Andrews (1993) sup-Wald; Callaway & Sant'Anna (2021); Sun & Abraham (2021); Borusyak, Jaravel & Spiess (2024); Scholes & Williams (1977) and Dimson (1979) for non-synchronous trading.

### 3.3 Contribution matrix

| Dimension | **This paper** | Al khatib & Alshaib (2026) | Da & Shive (2018) | Tang & Xiong (2012) |
|---|---|---|---|---|
| Question | Does the marginal investor's identity set an asset's factor loadings? | Did crypto–equity integration regime-shift after spot ETFs? | Does ETF ownership raise comovement among stocks? | Did index investment raise commodity–equity comovement? |
| Setting | BTC + control coins, 2021–2025 | BTC/crypto–equity, around 2024 | US equities, 2006–2013 | Commodity futures, 2000s |
| Counterfactual | Never-ETF coins; synthetic BTC | Pre-period regime (no cross-asset control) | Cross-sectional variation in ETF ownership | Indexed vs. non-indexed commodities |
| Method | Staggered DiD (CS/SA) + intraday decomposition + flow IV | TVP-VAR / connectedness (inferred) | Panel regression, instrumented ETF ownership | Correlation trends, index-membership comparison |
| Cash-flow channel | **Shut off by construction** | Not addressed | Present, must be controlled | Present (real fundamentals) |
| Mechanism test | Session location + flow decomposition (basis vs. allocation) | Regime characterization | Arbitrage channel | Index-flow channel |
| Policy output | Optimal crypto sleeve; contagion channel for regulators | Stability narrative | Market-quality | Commodity-market regulation |

**The contribution lives in three cells that differ from *all* prior work:** the zero-cash-flow identification argument, the cross-coin staggered counterfactual for a crypto–equity beta, and the basis-vs-allocation flow decomposition.

### 3.4 Contribution type and outlet

- **Primary type: new identification + mechanism.** An old question (does access/ownership change comovement) in a setting that removes the standard confound.
- **Secondary: quantification.** How much of the post-2024 change in Bitcoin's equity beta is the ETF channel versus the macro regime?
- **Tertiary: new measurement.** The basis-trade-adjusted allocation flow series is a construct of independent use.

**Target:** *Journal of Financial Economics* / *Review of Financial Studies* if the cross-coin design and session decomposition both deliver and the zero-cash-flow framing carries the introduction. Realistic strong fallbacks: *Journal of Financial and Quantitative Analysis*, *Review of Finance*, *Management Science*. Field fallback: *Journal of Banking & Finance*, *Journal of Financial Markets*. Given that Al khatib & Alshaib (2026) has already staked the descriptive claim in a field journal, **the top-journal case rests entirely on identification and mechanism, not on documenting the correlation change.** The pipeline should not let the paper drift back toward description.

### 3.5 Stress test — could a reader have guessed the answer?

Partly, and the plan must confront this. Most practitioners would guess "yes, beta rose." Three things make the paper non-derivative:

1. **The magnitude decomposition is not guessable.** β = ρ·(σ_BTC/σ_MKT). Bitcoin's own volatility declined over the sample. A rising correlation with *flat* beta and a rising beta with *flat* correlation are economically opposite statements, and casual readers conflate them. §6.2 separates them; the sign of the volatility-ratio term is genuinely unknown ex ante.
2. **The basis-trade wedge is not guessable** and could plausibly generate a large-flows/no-beta-change result that contradicts everyone's prior.
3. **Attribution is not guessable.** 2024–2025 contains a Fed easing cycle, a US election that repriced crypto policy, and a tariff shock. The naive prior confounds all of these with the ETF. The paper's job is to say how much is ETF — and the honest answer may be "much less than the raw correlation chart suggests."

---

## 4. Conceptual framework (Section 3 of the paper)

A deliberately minimal two-clientele model, in the spirit of Merton (1987), sufficient to generate the tests and no more.

**Setup.** One risky asset in fixed supply with **no cash flows** — terminal value is purely the resale price; there is no dividend process and hence no cash-flow news. Two investor groups:

- **Crypto-natives** (mass $m_c$), wealth $W_c$, whose SDF $M_c$ is orthogonal to the US equity market return $R_m$.
- **US allocators** (mass $m_a$), wealth $W_a$ tied to equity markets, SDF $M_a$ with $\mathrm{Cov}(M_a, R_m) \neq 0$. They face a per-period participation cost $\kappa$ for holding Bitcoin (custody, operational risk, career risk, mandate restrictions, tax reporting).

**The ETF** is modeled as a reduction in $\kappa$ from $\kappa_0$ to $\kappa_1 < \kappa_0$, which raises allocator participation $\lambda = \lambda(\kappa)$, $\lambda' < 0$.

**Result (to be derived formally in §3 of the paper).** In equilibrium the asset's beta on the equity market is a participation-weighted average of the two clienteles' implied loadings:

$$\beta_{\text{BTC}} \;=\; \omega(\lambda)\,\beta^{a} \;+\; \bigl(1-\omega(\lambda)\bigr)\,\beta^{c}, \qquad \beta^{c} \approx 0,\; \frac{\partial \omega}{\partial \lambda} > 0$$

so that $\dfrac{\partial \beta_{\text{BTC}}}{\partial \kappa} < 0$: cutting the access cost raises the equity beta.

**Three testable implications, each mapped to a design:**

- **(P1)** $\Delta\beta > 0$, and increasing in the allocator wealth that actually enters. → **D1**, **D3**
- **(P2)** $\Delta\beta = 0$ if entrants' demand is orthogonal to the equity SDF (H2), **or** if entrants are market-neutral basis traders (H3). The model makes explicit that flows and beta changes are *not* the same object. → **D3** decomposition
- **(P3)** Because allocator trading is confined to exchange hours while crypto-native trading is continuous, the induced covariance is concentrated in the US cash session. → **D2**

P3 is the implication that no macro-regime alternative generates, which is why D2 carries disproportionate weight.

---

## 5. Empirical strategy

### 5.0 Outcome measurement

**Primary outcome:** the time-varying beta of daily Bitcoin excess returns on the US equity market excess return, $\beta_t$.

**Secondary:** conditional correlation $\rho_t$; the variance share $\rho_t^2$; loadings on a macro/risk factor set.

Four estimators, reported side by side in the main table, because each has a distinct failure mode:

1. **Rolling OLS**, 60-trading-day *backward-looking* window. Transparent but smears the break across the window; a centered window would contaminate ±30 days around the event. Backward-looking only, stated explicitly.
2. **DCC-GARCH** (Engle 2002) on the BTC–MKT pair, plus an asymmetric ADCC variant.
3. **Kalman-filter state-space TVP beta** with a random-walk coefficient — the cleanest for *locating* a break because it imposes no window.
4. **Endogenous break tests: Bai–Perron multiple-break and Andrews sup-Wald** on the BTC-on-MKT regression, **estimated without being told the treatment date.**

> **Estimator 4 is a commitment device.** If the data-selected break lands on or near January 2024, that is far more convincing than any test conditioned on the known date. If it lands elsewhere — the November 2024 election, the 2022 rate cycle, March 2020 — **that must be reported as the headline finding of Table 4**, not buried. The plan pre-commits to reporting the full break-date set regardless of whether it flatters the hypothesis.

**Two measurement decisions that materially change the answer** and are elevated to first-class robustness axes:

- **The return clock.** Bitcoin trades continuously; US equities close at 16:00 ET. Daily Bitcoin returns sampled on 00:00 UTC boundaries are non-synchronous with equity closes, mechanically attenuating contemporaneous beta and manufacturing spurious lead–lag. **Baseline: construct Bitcoin returns on a 16:00 ET–to–16:00 ET clock.** Report the 00:00 UTC version as robustness. This is a plausible source of disagreement across the existing literature and should be flagged as such.
- **Beta versus correlation.** $\beta = \rho \cdot (\sigma_{\text{BTC}}/\sigma_{\text{MKT}})$. Bitcoin's daily volatility runs roughly 3–5× the market's, so $\beta \approx 3\text{–}5\rho$ and small correlation changes produce large beta changes. **Every result is decomposed into the correlation term and the relative-volatility term.**
- **Calibration discipline.** Even at $\rho = 0.4$, only ~16% of Bitcoin's return variance is equity-driven. The paper will **not** write "Bitcoin became a risk asset." It will report $\rho^2$ alongside every correlation and make claims about the margin.

### 5.1 D1 — Staggered difference-in-differences across coins (primary design)

**Unit:** coin $i$. **Time:** day $t$ (or month, for estimated-beta outcomes). **Outcome:** coin $i$'s equity beta $\hat\beta_{it}$, estimated in a first stage.

**Treatment cohorts (verify all dates against primary sources):**

| Cohort | Asset | US spot ETF trading begins |
|---|---|---|
| 1 | BTC | January 11, 2024 |
| 2 | ETH | July 23, 2024 (19b-4 approved May 23, 2024) |
| 3 | SOL | 2025 — **verify exact date** |
| 4 | XRP | 2025 — **verify exact date** |
| Never-treated | ADA, LTC, LINK, DOGE, BCH, AVAX, DOT, XLM | — |

**Estimator:** Callaway–Sant'Anna, with Sun–Abraham and Borusyak–Jaravel–Spiess as alternatives. Never-treated coins as the comparison group; not-yet-treated as an alternative. Two-way clustering by coin and day.

**Identifying assumption:** absent ETF listing, treated and never-treated coins' equity betas would have followed parallel paths. Supported by (i) event-study pre-trend plots — the primary diagnostic, reported prominently in Figure 4; (ii) pre-period placebo listing dates; (iii) Rambachan–Roth honest-DiD sensitivity bounds on the degree of pre-trend violation the result can tolerate.

**Threats and responses:**

- *Coins are not exchangeable.* Bitcoin is unique in size, narrative, and institutional standing. Mitigations: restrict to large-cap coins; **synthetic control** for Bitcoin's beta built from never-treated coins plus gold and the Nasdaq (Figure 8); report the DiD on the beta *change* rather than the level, which differences out fixed differences in integration.
- *SUTVA violation / spillovers.* Bitcoin's ETF plausibly raised other coins' betas through crypto-market integration. **This biases the DiD toward zero, so the estimate is a lower bound on the integration effect.** State this explicitly rather than hoping no referee notices. Supplement with "clean control" coins that are small, non-US-exchange-listed, and least likely to be affected.
- *ETH cohort contamination.* Ether ETF flows were an order of magnitude smaller than Bitcoin's. Report cohort-specific ATTs, do not only report the pooled average, and interpret a weak ETH effect as consistent with the dose–response logic of D3 rather than as a failure.

### 5.2 D2 — Intraday session decomposition (the mechanism's sharpest test)

Partition each 24-hour day into **Asia (00:00–07:00 ET)**, **Europe (07:00–09:30 ET)**, **US cash (09:30–16:00 ET)**, and **US post-close (16:00–24:00 ET)**, with a separate **NAV-strike window (15:45–16:00 ET)**.

For each session $s$ and regime $r \in \{\text{pre}, \text{post}\}$, compute (i) Bitcoin's share of daily return variance, (ii) the realized covariance of Bitcoin with the S&P 500 E-mini future (which trades nearly 24 hours, making the covariance well-defined in every session), and (iii) the session-level beta.

**Test:** is the *increase* in BTC–equity covariance concentrated in the US cash session?

$$\Delta \text{Cov}^{\text{US}} - \Delta \text{Cov}^{\text{Asia}} > 0$$

**Why this is the cleanest test in the paper.** A macro regime shift that raises global risk-asset correlation raises it in *all* sessions. Only a mechanism operating through US-listed vehicles — the ETF — relocates covariance into US exchange hours. This is a within-asset, within-day test that requires no cross-coin comparability assumption and no parallel-trends assumption.

**Companion test — the weekend margin.** Equity markets and the ETF close on weekends; Bitcoin does not. If the ETF's marginal holder now sets the price, Bitcoin's weekend share of volume and volatility should fall post-2024, and weekend returns should become less informative for Monday pricing. A documented collapse in Bitcoin weekend activity would corroborate the channel from an entirely independent direction.

### 5.3 D3 — Flow dose–response and the basis/allocation decomposition

**Step 1 — Build daily net creation flow** per fund, from daily shares outstanding × NAV, aggregated across all eleven funds, **netting GBTC's large outflows.** Gross creations and gross redemptions separately, since arbitrage intensity depends on gross activity.

**Step 2 — Decompose flow into basis-trade and allocation components.** This is the specification insight of §2, H3. Project daily net flow on the annualized CME futures basis (cash-and-carry carry), CME futures open interest changes, and CME COT positioning:

$$\text{Flow}_t = \gamma_0 + \gamma_1 \text{Basis}_t + \gamma_2 \Delta \text{OI}^{\text{CME}}_t + \varepsilon_t$$

Fitted value = **basis-trade flow**; residual $\varepsilon_t$ = **allocation flow**. Validate the split against quarterly 13F filings of spot-ETF holders, classified into hedge funds (basis traders), RIAs and wealth platforms (allocators), and other. If the 13F-based classification and the basis-projection classification agree, the measure is credible.

**Step 3 — Dose–response.** Estimate whether the conditional beta is higher on high-flow days, separately by component:

$$\hat\beta_t = \alpha + \delta_A \cdot \text{AllocFlow}_t + \delta_B \cdot \text{BasisFlow}_t + \Gamma' X_t + u_t$$

**H1 predicts $\delta_A > 0$ and $\delta_B \approx 0$.** A finding of $\delta_B > 0$ would indicate the flow measure is picking up something other than allocation and should prompt re-examination.

**Step 4 — IV for flows.** Daily flows respond to Bitcoin returns, which respond to equity returns; OLS is contaminated. **Instrument:** the staggered opening of solicited access at major wirehouses and wealth platforms (e.g., Merrill Lynch and Wells Fargo in August 2024, Morgan Stanley in August 2024 — *all dates to be verified from primary sources*). These decisions shift *access* on committees' internal timetables, plausibly unrelated to that week's Bitcoin fundamentals. **Exclusion restriction:** platform approval dates affect Bitcoin's equity beta only through the flows they enable. Threat: approvals may be timed to market conditions; test by regressing approval timing on prior returns and volatility, and by checking for anticipatory flow before announcement. Report first-stage F; if it is weak, present Anderson–Rubin confidence sets rather than leaning on point estimates.

### 5.4 D4 — Announcement event study and the false-news placebo

**Events:**
- **E1 — Anticipation:** August 29, 2023, the DC Circuit ruling in *Grayscale v. SEC*.
- **E2 — False news:** January 9, 2024, the compromised SEC social-media account announcing approval, retracted within minutes. **Pure sentiment shock, no access change.**
- **E3 — Approval:** January 10, 2024, ~16:00 ET, SEC order.
- **E4 — Listing:** January 11, 2024, 09:30 ET, trading begins. **Actual access change.**

**The placebo logic.** E2 and E3/E4 carry nearly identical *news* content — "spot Bitcoin ETFs are approved" — but only E3/E4 changed the *plumbing*. If the change in comovement is a sentiment or narrative effect, E2 should move it too. If it is an access effect, only E3/E4 should. This separates news from plumbing using two events days apart, holding the macro environment fixed. The Pucher–Schiereck–Bormann (2026) *JAIS* paper documents E2 in detail and should be leaned on for event construction.

### 5.5 Handling anticipation: the donut

The approval was heavily anticipated after the August 2023 Grayscale ruling; by December 2023 market-implied odds were very high. Treatment leaked backward.

**Baseline: a donut specification.** Clean pre-period through **August 28, 2023**; excluded anticipation window **August 29, 2023 – January 31, 2024**; clean post-period from **February 1, 2024** (letting the listing settle and excluding the GBTC-outflow transition). Report with and without the donut, and report an explicit three-regime specification (pre / anticipation / post) in which the anticipation regime's coefficient is itself interpretable.

---

## 6. Data

| Series | Source | Frequency | Notes |
|---|---|---|---|
| BTC price | CoinMetrics community reference rate; Kraken/Coinbase via CCXT; Allium | Hourly → daily | **Sample at 16:00 ET.** Cross-validate across venues |
| Control coins | Same | Hourly → daily | ETH, SOL, XRP, ADA, LTC, LINK, DOGE, BCH, AVAX, DOT, XLM |
| US equity market | CRSP value-weighted; SPY; ES front-month for intraday | Daily / intraday | ES needed for overnight covariance in D2 |
| Factors | Ken French daily: MKT-RF, SMB, HML, RMW, CMA, MOM | Daily | |
| Tech/speculative proxies | QQQ, ARKK, high-short-interest basket | Daily | For the factor-migration test §6.4 |
| Macro/risk | VIX, MOVE, DXY, 10y nominal, 10y TIPS real, breakevens, SOFR–OIS | Daily | FRED + CBOE |
| ETF flows | Issuer daily shares outstanding × NAV (all 11 funds); Farside Investors; Bloomberg | Daily | Net **and** gross creations/redemptions; net out GBTC |
| ETF AUM & ownership | 13F filings from Q1 2024 | Quarterly | Classify filers: HF vs. RIA vs. other |
| Futures | CME BTC futures settle, open interest, COT | Daily / weekly | For the basis decomposition |
| GBTC discount/premium | Grayscale; Bloomberg | Daily | Arbitrage-restoration evidence |
| Platform access dates | Press reports, filings | Event dates | IV in D3 — **verify each from primary sources** |

**Sample:** January 1, 2021 – December 31, 2025 (~1,250 trading days; three years pre, two years post). A 2018-start extension is used for the endogenous break tests so that earlier candidate breaks can compete. Starting in 2021 avoids the March 2020 COVID correlation spike dominating the pre-period; this choice is reported, not hidden, and the 2018-start results appear in robustness.

**Cleaning decisions to document:** venue selection and cross-venue price validation; treatment of exchange outages; winsorization at 0.5%/99.5% (reported both ways); US market holidays (Bitcoin trades, equities do not — exclude from daily-beta estimation, retain for the weekend/holiday test); the stablecoin-denomination question (USD vs. USDT pairs).

---

## 7. Paper structure

**1. Introduction** — Lead with the phenomenon (§1), not the literature. State the tension (§2). Preview the zero-cash-flow identification argument early — it is the paper's distinguishing idea. Preview results. Positioning paragraph naming Al khatib & Alshaib (2026), Da & Shive (2018), and Tang & Xiong (2012) explicitly.

**2. Institutional background** — The path to approval (Winklevoss denial → futures ETF October 2021 → *Grayscale v. SEC* August 2023 → approval January 2024). What the ETF changed: custody, tax wrapper, model-portfolio eligibility, margin, solicited access. What it did **not** change: supply schedule, the 24/7 spot market, the underlying technology. The GBTC discount collapse. **The basis trade** — essential setup for §5.3.

**3. Conceptual framework** — The two-clientele model of §4; P1–P3.

**4. Data** — §6, plus summary statistics and cleaning decisions.

**5. Empirical strategy** — D1–D4, identifying assumptions stated as assumptions.

**6. Results** — 6.1 descriptive beta/correlation dynamics; 6.2 the ρ vs. σ-ratio decomposition; 6.3 the DiD; 6.4 factor-loading migration (does Bitcoin's loading shift from Nasdaq/ARKK-specific toward broad-market and macro factors? — the financialization test, distinguishing "became an allocator asset" from "became a high-beta tech proxy"); 6.5 endogenous break dates.

**7. Mechanism** — 7.1 session decomposition; 7.2 weekend margin; 7.3 flow dose–response with the basis/allocation split; 7.4 IV estimates; 7.5 **what a null would mean** (reverse insight, see below).

**8. Robustness and external validity** — Return clock; donut; estimation windows; coin sample; DCC specification; winsorization; alternative market proxies; placebo dates and placebo assets (gold/GLD — which has had an ETF since 2004 and should show nothing). External validity: this is one asset, one jurisdiction, one wrapper, two post-years. Be explicit about what does and does not generalize.

**9. Conclusion** — What we learn about the determinants of comovement; implications for allocators (optimal sleeve), for regulators (contagion channel), and for the design of access vehicles for other alternative assets.

### 7.5 Pre-committed interpretation of a null result

If $\Delta\beta \approx 0$ net of macro, the paper does **not** become a failed paper. The reverse insight: shared ownership and a shared trading venue were **not sufficient** to generate habitat comovement in an asset with no cash flows. That would be evidence against the pure category/habitat view and in favor of the information-diffusion view — because the one ingredient Bitcoin lacks is a shared cash-flow-news interpretation and a shared analyst/media coverage structure. A null here localizes *where* habitat effects come from, which is a contribution to the Barberis–Shleifer–Wurgler debate in its own right. This interpretation is committed to **now**, before estimation.

---

## 8. Tables and figures

### Tables

| # | Content |
|---|---|
| **T1** | Summary statistics by regime (pre / anticipation / post): returns, volatility, correlation, beta, volume, for BTC and each control coin |
| **T2** | Pre/post beta and correlation across all four estimators — descriptive benchmark |
| **T3** | **Main result.** Staggered DiD (Callaway–Sant'Anna), cohort-specific and pooled ATTs, with Sun–Abraham and BJS alternatives |
| **T4** | Endogenous structural-break tests (Bai–Perron, Andrews sup-Wald) — **all estimated break dates reported** |
| **T5** | Flow dose–response: total flows, then basis vs. allocation split; OLS and IV panels with first-stage F |
| **T6** | Intraday session decomposition: variance shares, realized covariances, session betas, pre vs. post |
| **T7** | Factor-loading migration: BTC on {MKT, QQQ-orth, ARKK-orth, VIX, real yield, DXY, funding spread}, pre vs. post |
| **T8** | Robustness grid: return clock × donut × window × coin sample × winsorization |
| **T9** | Placebos: false-news event vs. approval; placebo dates; placebo asset (gold) |
| **A1–A6** | Appendix: per-fund flow construction; 13F classification; synthetic-control weights and fit; DCC parameters; honest-DiD sensitivity; full break-test output |

### Figures

| # | Content |
|---|---|
| **F1** | **Lead figure.** 60-day rolling BTC–S&P correlation and beta, 2018–2025, with vertical lines at E1–E4 and shaded anticipation window |
| **F2** | Beta decomposed: correlation path and σ_BTC/σ_MKT path plotted separately — makes the §5.0 decomposition visual |
| **F3** | Kalman TVP beta with confidence bands, overlaid with endogenously estimated break dates |
| **F4** | **DiD event-study coefficient plot with pre-trends** — the key identification diagnostic |
| **F5** | Cumulative ETF flows stacked by issuer, GBTC netted, with total AUM on a right axis |
| **F6** | Session decomposition: share of BTC return variance and of BTC–equity covariance by session, pre vs. post — the mechanism figure |
| **F7** | Binscatter of conditional beta against flow intensity, split into basis-trade and allocation components |
| **F8** | Synthetic control: actual BTC beta vs. synthetic BTC beta, with placebo-in-space distribution |

---

## 9. Pre-analysis commitments

Registered before estimation, in the pre-registration spirit of the persona standard:

1. **Primary specification:** D1, Callaway–Sant'Anna, never-treated controls, 60-day backward rolling beta on 16:00 ET returns, donut excluding 2023-08-29 to 2024-01-31, two-way clustered by coin and day.
2. **Primary outcome:** $\hat\beta_{it}$, Bitcoin on the CRSP value-weighted excess return.
3. **Decision rule:** H1 is supported if the pooled ATT is positive and significant at the 5% level **and** the session decomposition (D2) shows the increase concentrated in the US cash session. **Either one alone is insufficient** — the DiD alone cannot rule out a crypto-specific shock coinciding with the event, and the session result alone cannot rule out a change in the global news cycle.
4. **All specifications attempted will be reported**, including those that fail. The robustness grid (T8) is populated exhaustively, not selectively.
5. **The endogenous break dates (T4) will be reported in full**, whether or not they coincide with January 2024.
6. **Null interpretation is fixed in advance** (§7.5).
7. **Hypotheses will not be revised after seeing the data.** Post-hoc observations, if any, are labelled exploratory and confined to a clearly marked subsection.

---

## 10. Threats to validity — honest inventory

| Threat | Severity | Response |
|---|---|---|
| Macro regime confound (Fed cuts, Nov-2024 election, 2025 tariff shock) | **High** | D1 differences out common crypto shocks; D2 is immune to global regime shifts; T9 placebo assets |
| Anticipation / treatment leakage | **High** | Donut; three-regime specification; E1 event study |
| Cross-coin spillovers (SUTVA) | **Medium-high** | Biases toward zero → estimates are a lower bound; clean-control subsample |
| Bitcoin not comparable to control coins | **Medium-high** | Synthetic control; change-in-beta outcome; large-cap restriction |
| Basis trade masquerading as allocation | **Medium** | Explicit decomposition (§5.3) — converted from a threat into a test |
| Non-synchronous trading | **Medium** | 16:00 ET clock baseline; Scholes–Williams/Dimson lead-lag betas |
| Generated-regressor problem (β̂ as outcome) | **Medium** | Bootstrap standard errors accounting for first-stage estimation; report a one-step DCC-X specification where the conditional correlation is modelled jointly with the treatment indicator |
| Weak instrument in D3 | **Medium** | Report first-stage F; Anderson–Rubin confidence sets if weak |
| Short post-period (two years) | **Medium** | Acknowledge; report results by post-year; frame as medium-run, not long-run |
| Multiple hypothesis testing across designs | **Low-medium** | Pre-specified primary (§9.1); Romano–Wolf adjusted p-values for the secondary family |

**What would make us wrong.** If the estimated break in Bitcoin's equity beta is dated to November 2024 rather than January 2024, the election-and-policy story dominates the ETF story. If the session decomposition shows the covariance increase spread evenly across Asian and US hours, the mechanism is global macro, not the ETF. If the allocation-flow coefficient is zero while the basis-flow coefficient is positive, the flow measure is mis-specified and §5.3 needs rebuilding. Each of these is a reportable outcome, not a reason to re-specify.

---

## 11. Magnitude interpretation (enforced throughout)

Every estimate is translated into at least one economically meaningful unit:

- **Variance share:** $\rho^2$ — what fraction of Bitcoin's return variance is equity-driven, reported alongside every correlation.
- **Portfolio impact:** the change in marginal contribution to risk of a 1%, 3%, and 5% Bitcoin sleeve in a 60/40 portfolio.
- **Optimal weight:** the change in the mean–variance-optimal Bitcoin allocation implied by the estimated $\Delta\beta$, holding expected returns fixed — the number allocators actually act on.
- **Dollar terms:** applied to the estimated AUM of the spot ETF complex, the implied change in aggregate portfolio risk attributable to the integration effect.

Statistical and economic significance are reported and discussed separately in every results subsection.

---

## 12. Handoff to the next specialist

**Literature specialist:**
1. `literature.bib` as supplied is mostly auto-harvested and off-topic — **rebuild it.** Retain only `khatib2026from`, `tang2026the`, `pucher2026falsenews`, `guliyev2025from`.
2. **Priority one: retrieve Al khatib & Alshaib (2026) in full.** All characterizations in §3.2 are inferred from title and outlet only and must be verified. If they already implement a cross-asset counterfactual, flag it immediately — the positioning in §3.3 must change.
3. Populate the foundational list in §3.2 with verified citations; confirm every author/year/journal against primary sources. Do not propagate any citation that has not been verified to exist.
4. Search specifically for work on the commodity-financialization analogue applied to crypto — this is where an unnoticed competitor is most likely to be hiding.

**Data specialist:**
1. Bash was unavailable in this session, so **no data has been pulled and no stylized fact in this plan is empirically verified.** Figure 1 must be produced first, as a feasibility check on the whole project.
2. Verify all event dates from primary sources: the SEC approval order, each fund's listing date, the ETH/SOL/XRP spot ETF dates in §5.1, and the platform access dates in §5.3.
3. Build the 16:00 ET Bitcoin return series **first** — the entire analysis depends on it.
4. The eleven-fund daily flow panel and the CME basis series are the long pole; start them early.

**Econometrics specialist:**
1. Implement the §9 primary specification before any alternative.
2. The generated-regressor problem (β̂ as a DiD outcome) needs a defensible solution; the two-step bootstrap is the fallback, the joint DCC-X specification is preferred.
3. Figure 4's pre-trends determine whether the paper has an identification strategy or a description. Produce it early and report it honestly.

**Do not let the paper drift back to description.** The descriptive claim is already staked in a field journal. This paper's reason to exist is the counterfactual, the mechanism, and the zero-cash-flow argument.
