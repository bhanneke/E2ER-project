# Literature Review — Spot Bitcoin ETFs and Crypto–Equity Comovement

**Paper:** *No Cash Flows, New Owners: Spot Bitcoin ETFs and the Origins of Comovement*
**Paper ID:** e432cf3f-9008-4202-8ee6-ff09a93948ec · **Stage:** idea → plan · **Methodology:** empirical
**Specialist:** Literature Scanner · **Prepared:** 2026-09-11

> **How to use this document.** This is a *context brief*, not a paper section. It is structured input for the drafting specialist. Section 1 is the operational part: which `\cite{}` keys actually compile and which do not. Sections 2–5 survey the four strands named in the work order. Section 6 is the contribution calibration the work order asked for — read it before writing the introduction. Section 7 lists what I could not verify. Section 8 is the grouped bibliography.

---

## 0. What I did, and the limits of it

**Actions taken.** I rebuilt `literature.bib` as the paper plan (§12) instructed. The supplied bibliography contained 25 auto-harvested entries, of which roughly four were on-topic. I resolved and recorded **30 additional references by DOI**, bringing the file to **55 citable keys**. I retrieved and read the full text of two directly relevant papers (`guliyev2025from`, `tang2026the`).

**Three hard limits, stated up front because they change what downstream specialists should rely on:**

1. **The `e2er-lit save` budget is exhausted (30/30 entries used).** No further references can be recorded in this session. Strand 3 — the commodity-financialization strand named explicitly in the work order (Tang–Xiong, Basak–Pavlova, Henderson–Pearson–Wang, Cheng–Xiong, Merton) — **hit the cap and is not citable.** §1.4 lists these with DOIs for immediate saving when budget refreshes. This is the single most important handoff item in this document.
2. **External literature search is unavailable in this session.** `e2er-lit search` degraded to local-library-only lookup; direct network fetching (`curl`, `WebFetch`) is blocked. Everything in §1.4 and §7 is therefore proposed from domain knowledge with DOIs attached, **not discovered by search, and not verified against a publisher record.** Each must be confirmed on save.
3. **The nearest competitor could not be read.** `e2er-lit read --doi 10.1016/j.iref.2026.105664` returns `403 Forbidden` from ScienceDirect. **Al khatib & Alshaib (2026) remains unread.** Every characterization of it below — as in the paper plan — is inferred from title and outlet only. The plan flagged this as "priority one"; it is still open, and it is the one unresolved item that can materially change the positioning.

---

## 1. Bibliographic status — read this before citing anything

### 1.1 Verified and citable (resolved via DOI this session)

These 30 keys now exist in `literature.bib` and will compile. Author/title/journal fields come from the resolved DOI metadata.

| Key | Work | Strand |
|---|---|---|
| `barberis2003style` | Barberis & Shleifer, "Style investing", *JFE* | 1 |
| `barberis2004comovement` | Barberis, Shleifer & Wurgler, "Comovement", *JFE* | 1 |
| `boyer2011stylerelated` | Boyer, "Style-Related Comovement: Fundamentals or Labels?", *JF* | 1 |
| `greenwood2007excess` | Greenwood, "Excess Comovement of Stock Returns… Nikkei 225 Weights", *RFS* | 1 |
| `vijh1994sp` | Vijh, "S&P 500 Trading Strategies and Stock Betas", *RFS* | 1 |
| `shleifer1986do` | Shleifer, "Do Demand Curves for Stocks Slope Down?", *JF* | 1 |
| `harris1986price` | Harris & Gurel, "Price and Volume Effects… S&P 500 List", *JF* | 1 |
| `chen2004the` | Chen, Noronha & Singal, "The Price Response to S&P 500 Index Additions and Deletions", *JF* | 1 |
| `pindyck1993the` | Pindyck & Rotemberg, "The Comovement of Stock Prices", *QJE* | 1 |
| `froot1999how` | Froot & Dabora, "How are stock prices affected by the location of trade?", *JFE* | 1 |
| `da2017exchange` | Da & Shive, "Exchange traded funds and asset return correlations", *EFM* | 1 |
| `bendavid2014do` | Ben-David, Franzoni & Moussawi, "Do ETFs Increase Volatility?", *JF* | 1 |
| `bendavid2017exchangetraded` | Ben-David, Franzoni & Moussawi, "Exchange-Traded Funds", *ARFE* | 1 |
| `israeli2017is` | Israeli, Lee & Sridharan, "Is there a dark side to exchange traded funds?", *RAST* | 1 |
| `glosten2020etf` | Glosten, Nallareddy & Zou, "ETF Activity and Informational Efficiency of Underlying Securities", *ManSci* | 1 |
| `brown2020etf` | Brown, Davies & Ringgenberg, "ETF Arbitrage, Non-Fundamental Demand, and Return Predictability", *Rev. Finance* | 1 |
| `coles2022on` | Coles, Heath & Ringgenberg, "On index investing", *JFE* | 1 |
| `baltussen2018indexing` | Baltussen, van Bekkum & Da, "Indexing and stock market serial dependence around the world", *JFE* | 1 |
| `liu2020risks` | Liu & Tsyvinski, "Risks and Returns of Cryptocurrency", *RFS* | 2 |
| `liu2022common` | Liu, Tsyvinski & Wu, "Common Risk Factors in Cryptocurrency", *JF* | 2 |
| `makarov2019trading` | Makarov & Schoar, "Trading and arbitrage in cryptocurrency markets", *JFE* | 2 |
| `biais2023equilibrium` | Biais, Bisière, Bouvard, Casamatta & Menkveld, "Equilibrium Bitcoin Pricing", *JF* | 2 |
| `griffin2020is` | Griffin & Shams, "Is Bitcoin Really Untethered?", *JF* | 2 |
| `hu2019cryptocurrencies` | Hu, Parlour & Rajan, "Cryptocurrencies: Stylized facts on a new investible instrument", *FM* | 2 |
| `corbet2018exploring` | Corbet, Meegan, Larkin, Lucey & Yarovaya, "Exploring the dynamic relationships between cryptocurrencies and other financial assets", *Econ. Letters* | 2 |
| `baur2017bitcoin` | Baur, Hong & Lee, "Bitcoin: Medium of exchange or speculative assets?", *JIFMIM* | 2 |
| `bouri2016on` | Bouri, Molnár, Azzi, Roubaud & Hagfors, "On the hedge and safe haven properties of Bitcoin", *FRL* | 2 |
| `conlon2020safe` | Conlon & McGee, "Safe haven or risky hazard? Bitcoin during the Covid-19 bear market", *FRL* | 2 |
| `corbet2020the` | Corbet, Larkin & Lucey, "The contagion effects of the COVID-19 pandemic: Evidence from gold and cryptocurrencies", *FRL* | 2 |
| `corbet2018retracted` | **RETRACTED — do not cite.** See §1.3. | 2 |

### 1.2 Year and journal fields require correction before compilation

The resolver populates years from OpenAlex, which frequently records the **working-paper or online-first year, not the year of record**. Downstream specialists must not quote these years in prose. The following corrections are, to the best of my knowledge, the published versions; **each should be confirmed against the publisher page before the paper is submitted**, since I could not verify them by fetch in this session.

| Key | Bib says | Published version of record (verify) |
|---|---|---|
| `barberis2004comovement` | 2004 | Barberis, Shleifer & Wurgler (**2005**), *JFE* 75(2), 283–317 |
| `bendavid2014do` | 2014 | Ben-David, Franzoni & Moussawi (**2018**), *JF* 73(6), 2471–2535 |
| `da2017exchange` | 2017 | Da & Shive (**2018**), *European Financial Management* 24(1), 136–168 |
| `greenwood2007excess` | 2007 | Greenwood (**2008**), *RFS* 21(3), 1153–1186 |
| `liu2020risks` | 2020 | Liu & Tsyvinski (**2021**), *RFS* 34(6), 2689–2727 |
| `makarov2019trading` | 2019 | Makarov & Schoar (**2020**), *JFE* 135(2), 293–319 |
| `glosten2020etf` | 2020 | Glosten, Nallareddy & Zou (**2021**), *Management Science* 67(1), 22–47 |
| `brown2020etf` | 2020, journal = "European Finance Review" | Brown, Davies & Ringgenberg (**2021**), ***Review of Finance*** 25(4), 937–972 — the journal name in the bib is the pre-2004 title and is **wrong as printed** |
| `baltussen2018indexing` | 2018 | Baltussen, van Bekkum & Da (**2019**), *JFE* 132(1), 26–48 |
| `baur2017bitcoin` | 2017 | Baur, Hong & Lee (**2018**), *JIFMIM* 54, 177–189 |
| `bouri2016on` | 2016 | Bouri et al. (**2017**), *Finance Research Letters* 20, 192–198 |

### 1.3 Do not cite

- **`corbet2018retracted`** — DOI `10.1016/j.irfa.2018.09.003`. The resolved title is literally *"RETRACTED: Cryptocurrencies as a financial asset: A systematic analysis"*. This is a heavily-cited survey and it is easy to pull in from memory. **Do not.** Where a general crypto-as-asset-class survey is needed, use `corbet2018exploring` (Economics Letters, not retracted) or `hu2019cryptocurrencies`. Citing a retracted paper in a JFE/RFS submission is a referee-level error.
- **Inherited noise to drop from the bibliography.** The following supplied keys are off-topic or in outlets that will not survive referee scrutiny, and citing them signals a weak literature search: `h2024dynamic` (carbon/renewables TVP-VAR), `shah2025climate` (South Asian climate comovement), `ernst2025an` (South African staking tax), `doucette2025singapore` (Busan regulatory geography), `smagula2026bitcoin` (undergraduate thesis repository), `goforth2025how` (CFTC enforcement law review), `mutter2026an` (securities-regulation law review), `singhi2025an` (LLM trading agent), `haidar2025the`, `yeboah2026cryptocurrency`, `daruwala2025exploring` (predatory/low-tier outlets), `bindseil2025the`, `kellerman2024into`, `currie2025insights` (qualitative/political-economy, wrong literature).
- **Marginal, cite only if a specific claim needs them:** `apostolov2026diversification` (crypto vs. commodities as diversifiers — thematically adjacent to strand 3, weak outlet), `kang2025a` (ML prediction of dynamic crypto correlations — cite only to note that the correlation object is actively modelled), `fantini2025informational` (bibliometric review — usable as a single "for a survey, see" cite), `ashfaq2026tokenized`, `daga2026crossdomain`, `haase2025wisdom` (no role).

### 1.4 **BLOCKED — must be added before drafting.** Save budget exhausted.

These are named in the work order or required by the paper plan, and **none of them is currently citable**. The commands are ready to run the moment budget refreshes. DOIs are supplied from domain knowledge and **must be checked against the resolved title on save** — if a DOI resolves to the wrong paper, discard it and search.

**Strand 3 — financialization (the work order's explicit list; entirely missing):**

```
e2er-lit save --doi 10.2469/faj.v68.n6.5                      # Tang & Xiong (2012), FAJ 68(6) — index investment and financialization of commodities
e2er-lit save --doi 10.1111/jofi.12408                        # Basak & Pavlova (2016), JF 71(4) — a model of financialization of commodities
e2er-lit save --doi 10.1257/aer.103.5.1728                    # Basak & Pavlova (2013), AER 103(5) — asset prices and institutional investors
e2er-lit save --doi 10.1093/rfs/hhu091                        # Henderson, Pearson & Wang (2015), RFS 28(5) — commodity-linked notes (ETNs)
e2er-lit save --doi 10.1146/annurev-financial-110613-034432   # Cheng & Xiong (2014), ARFE 6 — financialization of commodity markets (the counterweight)
e2er-lit save --doi 10.1016/j.jfineco.2012.04.005             # Hong & Yogo (2012), JFE 105(3) — futures market interest and asset prices
e2er-lit save --doi 10.1287/mnsc.2013.1756                    # Singleton (2014), ManSci 60(2) — investor flows and the 2008 oil boom/bust
e2er-lit save --doi 10.1016/j.jimonfin.2013.08.004            # Büyükşahin & Robe (2014), JIMF 42 — speculators and cross-market linkages
```

**Segmentation / integration (the theoretical spine of §4 of the paper):**

```
e2er-lit save --doi 10.1111/j.1540-6261.1987.tb04565.x        # Merton (1987), JF 42(3) — investor recognition. THE workhorse cite; its absence is disqualifying.
e2er-lit save --doi 10.1111/j.1540-6261.1995.tb04790.x        # Bekaert & Harvey (1995), JF 50(2) — time-varying world market integration
e2er-lit save --doi 10.1111/j.1540-6261.1996.tb02713.x        # Karolyi & Stulz (1996), JF 51(3) — why do markets move together?
e2er-lit save --doi 10.1086/701683                            # Koijen & Yogo (2019), JPE 127(4) — demand system asset pricing
```

**Strand 2 — crypto works that did not fit in budget:**

```
e2er-lit save --doi 10.1093/rfs/hhaa089                       # Cong, Li & Wang (2021), RFS 34(3) — tokenomics
e2er-lit save --doi 10.1016/j.jmoneco.2019.07.002             # Schilling & Uhlig (2019), JME 106 — simple bitcoin economics
e2er-lit save --doi 10.1016/j.jempfin.2018.11.002             # Borri (2019), JEF 50 — conditional tail risk in crypto
e2er-lit save --doi 10.1016/j.jfs.2022.101066                 # Auer & Tercero-Lucas (2022), JFS 62 — who invests in crypto
e2er-lit save --doi 10.1353/eca.2022.0014                     # Makarov & Schoar (2022), BPEA — ownership concentration (verify DOI)
```

**Econometrics (required by the plan's designs; none currently citable):**

```
e2er-lit save --doi 10.1198/073500102288618487                # Engle (2002), JBES 20(3) — DCC
e2er-lit save --doi 10.1093/jjfinec/nbw006                    # Engle (2016), J. Fin. Econometrics 14(4) — dynamic conditional beta
e2er-lit save --doi 10.2307/2998540                           # Bai & Perron (1998), Econometrica 66(1)
e2er-lit save --doi 10.1002/jae.659                           # Bai & Perron (2003), JAE 18(1)
e2er-lit save --doi 10.2307/2951764                           # Andrews (1993), Econometrica 61(4) — sup-Wald
e2er-lit save --doi 10.1016/j.jeconom.2020.12.001             # Callaway & Sant'Anna (2021), J. Econometrics 225(2)
e2er-lit save --doi 10.1016/j.jeconom.2020.09.006             # Sun & Abraham (2021), J. Econometrics 225(2)
e2er-lit save --doi 10.1093/restud/rdae007                    # Borusyak, Jaravel & Spiess (2024), REStud 91(6)
e2er-lit save --doi 10.1093/restud/rdad018                    # Rambachan & Roth (2023), REStud 90(5) — honest DiD
e2er-lit save --doi 10.1016/0304-405X(77)90041-1              # Scholes & Williams (1977), JFE 5(3) — nonsynchronous betas
e2er-lit save --doi 10.1016/0304-405X(79)90013-8              # Dimson (1979), JFE 7(2)
e2er-lit save --doi 10.1198/jasa.2009.ap08746                 # Abadie, Diamond & Hainmueller (2010), JASA — synthetic control
e2er-lit save --doi 10.1016/j.ijforecast.2011.02.006          # Diebold & Yilmaz (2012), IJF 28(1) — connectedness (needed to engage khatib2026from)
```

**Policy-institution sources with no DOI** (must be added as `@techreport` via `e2er-lit save --entry`, not `--doi`):

- Iyer, T. (2022), *Cryptic Connections: Spillovers between Crypto and Equity Markets*, IMF Global Financial Stability Note 2022/001. **This is the pre-period benchmark for the paper's central quantity** and the plan names it.
- Auer, R., Farag, M., Lewrick, U., Orazem, L. & Zoss, M. (2022), *Banking in the shadow of Bitcoin? The institutional adoption of cryptocurrencies*, BIS Working Paper 1013.
- Cornelli, G., Doerr, S., Frost, J. & Gambacorta, L. (2023), *Crypto shocks and retail losses*, BIS Bulletin 69.
- Aramonte, S., Huang, W. & Schrimpf, A. (2021), *DeFi risks and the decentralisation illusion*, BIS Quarterly Review, December.
- SEC (2024), *Order approving proposed rule changes… spot bitcoin exchange-traded products*, Release No. 34-99306, January 10, 2024 — the primary source for the event date; cite directly.
- *Grayscale Investments, LLC v. SEC*, 82 F.4th 1239 (D.C. Cir. 2023) — the E1 anticipation event.

---

## 2. Strand 1 — ETF/index inclusion and asset comovement

### 2.1 The foundational claim: comovement without fundamentals

The strand begins with the observation that return comovement exceeds what cash-flow comovement can explain. `pindyck1993the` establishes the excess-comovement puzzle for stocks. `barberis2003style` supplies the mechanism: investors allocate at the level of *styles* or *categories* rather than individual securities, so correlated style-level flows induce correlated returns among securities sharing a label. `barberis2004comovement` (BSW) is the canonical test, using S&P 500 additions and deletions: a stock added to the index begins comoving more with the index and less with non-index stocks, and the effect is stronger in the later period when indexing was larger. BSW frame this as a horse race between a **fundamentals view** (comovement tracks correlated cash-flow news) and **category/habitat views** (comovement tracks the trading of a shared clientele).

The subsequent literature works to close off the fundamentals channel:

- `vijh1994sp` is the **direct antecedent for this paper's outcome variable**: S&P inclusion raises a stock's *beta*, and Vijh attributes this to trading-driven rather than fundamental effects. Any paper measuring "did an index/ETF event change an asset's beta" is writing in Vijh's format.
- `boyer2011stylerelated` is the sharpest identification in the strand and the one this paper must position against most carefully. Boyer exploits *mechanical* reclassification of stocks across value/growth style indices — reclassifications driven by rank thresholds rather than by news — and finds comovement follows the **label**, not the fundamentals. This is a near-fundamentals-invariant design already in print.
- `greenwood2007excess` uses the 2000 Nikkei 225 redefinition, where index weights shifted for reasons unrelated to firm fundamentals, and finds comovement tracks weights.
- `froot1999how` (twin shares, Royal Dutch/Shell) is the cleanest possible fundamentals control — two claims on *identical* cash flows — and finds returns comove with the market where each trades. **This is the most important precedent for the paper's "fundamentals held constant" claim and is currently absent from the plan's positioning.**
- `shleifer1986do`, `harris1986price` and `chen2004the` establish the demand-curve/price-pressure foundation: index demand moves prices, and the effect is asymmetric (`chen2004the` finds additions and deletions are not mirror images, favouring an investor-awareness/recognition story over pure downward-sloping demand — which is the Merton (1987) channel this paper's model uses).

### 2.2 ETFs specifically

- `da2017exchange` — **the work order's anchor for this strand.** Da & Shive show that ETF ownership is associated with higher return comovement among the underlying securities, and that the effect operates through **arbitrage activity**: comovement is stronger where ETF arbitrage is more intense and where the underlying is less liquid. This is the plan's "arbitrage/plumbing channel" in its original form.
- `bendavid2014do` — Ben-David, Franzoni & Moussawi show ETF ownership raises the volatility of underlying stocks, with the effect operating through arbitrage trading that propagates non-fundamental shocks from the ETF to the underlying. The quantitative anchor, as reported in `guliyev2025from`: **a one-standard-deviation increase in ETF ownership is associated with roughly a 16% rise in daily stock volatility.** (Second-hand figure — verify against the JF article before quoting.)
- `brown2020etf` — ETF arbitrage transmits **non-fundamental demand** into the underlying, and the resulting mispricing predicts returns. This is the strongest available statement that the ETF wrapper injects wrapper-specific shocks into the asset.
- `israeli2017is` — the work order's third anchor. ETF ownership degrades the *information environment* of the underlying: higher bid-ask spreads, lower analyst following, reduced price informativeness about future earnings. Note the tension with `glosten2020etf`, which finds ETF activity **increases** informational efficiency with respect to *systematic* earnings information while doing nothing for firm-specific information. **These are not contradictory and the paper should say so:** ETFs shift the informational content of prices from idiosyncratic toward systematic. That is precisely a comovement-increasing mechanism, and it is the cleanest available micro-foundation for H1. It is also the mechanism whose *absence* in Bitcoin (no earnings, systematic or otherwise) generates the paper's pre-committed null interpretation (plan §7.5).
- `baltussen2018indexing` — indexing changes the *serial dependence* of index returns internationally, i.e. the wrapper changes the return process, not just the level.
- `coles2022on` — index investing does not make prices less efficient on average; a useful counterweight against over-claiming ETF distortions.
- `bendavid2017exchangetraded` — the survey; use for the one-sentence "for a review, see" cite.

### 2.3 What strand 1 gives this paper

A well-specified prior (**ETF/index inclusion raises comovement, through arbitrage and clientele channels, by roughly the magnitudes above**) and a well-specified identification problem (**the fundamentals alternative**). The paper's entire framing is that Bitcoin removes the second. §6.2 assesses whether that claim survives contact with `boyer2011stylerelated` and `froot1999how`.

---

## 3. Strand 2 — Bitcoin/crypto comovement with traditional assets

### 3.1 Crypto as its own asset class with its own factor structure

- `liu2020risks` (Liu & Tsyvinski) — the foundational result for this paper's identification claim. Cryptocurrency returns are **not explained by** equity-market factors, macro factors, or the returns of currencies and commodities; they are driven by crypto-specific factors, chiefly **momentum** and **investor-attention/network** proxies. **This is the paper's pre-period benchmark: as of the sample Liu & Tsyvinski study, β^c ≈ 0 is an empirical finding, not an assumption.** It is the single most useful citation for the plan's two-clientele model (§4), which posits crypto-natives whose SDF is orthogonal to the equity market.
- `liu2022common` (Liu, Tsyvinski & Wu) — a three-factor model (crypto market, size, momentum) prices the cross-section of crypto returns. Reinforces the same point: crypto had an internally coherent, externally disconnected factor structure.
- `biais2023equilibrium` — an equilibrium model of Bitcoin pricing; useful for the claim that Bitcoin's price is a pure resale-value/convenience-yield object with **no dividend process**. This is the theoretical citation for "no cash flows," and the drafting specialist should lean on it rather than asserting the point rhetorically.
- `hu2019cryptocurrencies` — stylized facts; cryptoassets comove strongly with each other and load on a Bitcoin-like common factor. **This is the citation that establishes the SUTVA concern in design D1**: if all coins load on a common crypto factor, an ETF shock to Bitcoin propagates to the never-treated controls and attenuates the DiD toward zero. The plan already concedes this; `hu2019cryptocurrencies` is the evidence for the concession.
- `makarov2019trading` — cross-exchange arbitrage and market segmentation in crypto. Two uses: (i) it documents that crypto markets are *segmented across venues and geographies*, which is exactly the friction the ETF removes for US investors; (ii) its arbitrage-spread measures are a natural input to the paper's D2 session analysis.
- `griffin2020is` — non-fundamental demand (Tether issuance) moved Bitcoin prices. Precedent that Bitcoin's price responds to flow rather than information, which is the paper's H1 in its crudest form.

### 3.2 Diversifier, hedge, or risk asset — and the COVID break

This sub-strand is where the paper's descriptive claim is **already documented**, and the drafting specialist must be careful not to present it as new.

- `bouri2016on` — Bitcoin is a **poor hedge** and only a weak diversifier; it hedges only in specific regimes and horizons. Published 2017, i.e. the "digital gold" claim was already contested before COVID.
- `baur2017bitcoin` — Bitcoin is held and traded predominantly as a **speculative asset**, not as a medium of exchange, and its return correlation with traditional assets is low in the pre-2018 sample.
- `corbet2018exploring` — dynamic relationships between cryptocurrencies and other financial assets: crypto is **relatively isolated** from traditional assets at daily and intraday frequencies in the pre-2018 sample, with strong internal connectedness. The pre-period benchmark.
- `conlon2020safe` — **the COVID break.** Bitcoin was *not* a safe haven in the March 2020 bear market; it amplified portfolio losses. Correlation with equities rose sharply precisely when diversification was needed.
- `corbet2020the` — contagion from equity markets into crypto during COVID; gold retained safe-haven properties while Bitcoin did not.

**Bottom line for the contribution claim:** the literature already establishes (i) a low pre-2020 crypto–equity correlation, (ii) a sharp COVID-era increase, and (iii) the failure of the diversifier narrative. A paper whose headline is "Bitcoin now moves with stocks" is contributing nothing. This is consistent with the plan's §3.4 warning and reinforces it.

### 3.3 The post-COVID institutional literature (IMF/BIS) — **gap**

The work order names "IMF/BIS work on crypto-equity spillovers" as a required component. **I could not record any of it** (no DOIs for working papers; save budget exhausted; external search unavailable). §1.4 lists the four institutional sources with full citations for manual entry. The substantive content, stated from domain knowledge and flagged as **unverified**:

- **Iyer (2022, IMF GFSN 2022/001), "Cryptic Connections."** Documents that Bitcoin–S&P 500 return and volatility spillovers rose markedly from 2020 onward relative to 2017–2019, and argues the increase reflects the entry of institutional investors into crypto and shared exposure to monetary-policy shocks. **This is the paper's direct antecedent and the closest thing in the literature to "what the answer was before the ETF."** It is essential that the drafting specialist obtain and read it: if Iyer already attributes rising comovement to institutional entry, then the *hypothesis* of this paper is pre-existing and only the *identification* is new. That is still a contribution, but it must be framed as such.
- BIS work (Auer et al. 2022; Cornelli et al. 2023) documents institutional and retail adoption patterns and the transmission of crypto shocks; useful for motivation, not for identification.

### 3.4 Verified adjacent work in the supplied bibliography

- `kang2025a` — ML models for predicting dynamic crypto correlations. Cite once, if at all, to note that the time-varying correlation object is actively modelled; not a competitor.
- `apostolov2026diversification` — crypto vs. commodities as equity diversifiers. Thematically the bridge between strands 2 and 3; weak outlet; cite only in a footnote if the diversification framing needs support.
- `fantini2025informational` — *Journal of Economic Surveys* bibliometric review of crypto informational efficiency, 2015–2024. The one respectable survey in the supplied set; usable as a single "for a review of this literature, see" cite.

---

## 4. Strand 3 — Institutional adoption and financialization of alternative assets

**Status: this is the strand the work order emphasized and it is the strand I could not record.** See §1.4. Everything below is offered as a substantive map for the drafting specialist; none of it is citable until saved, and the claims should be re-verified on reading.

### 4.1 Why this strand is the paper's closest structural analogue

Commodity financialization is the one prior episode with the same shape as the Bitcoin ETF: **a new financial product made an asset class accessible to a new clientele, and comovement with equities rose.** The paper's contribution claim is fundamentally a claim of improvement on this literature, so the positioning must be precise.

- **Tang & Xiong (2012, FAJ).** The canonical result: after the mid-2000s growth of commodity index investment, individual commodity futures prices became increasingly correlated with oil and with equity markets, and the increase was **concentrated in indexed commodities** relative to off-index commodities. The cross-sectional index-membership comparison is the direct methodological ancestor of this paper's design D1 (ETF-listed coins vs. never-treated coins).
- **Basak & Pavlova (2016, JF).** The theoretical counterpart: a model in which institutional investors benchmarked to a commodity index bid up index commodities, raise their volatility, and raise their correlation with each other and with the broader market — **all without any change in commodity fundamentals.** This is the closest existing formal model to the two-clientele model in plan §4, and the paper's model must be positioned as a variant of it in which the risky asset has no cash flows.
- **Basak & Pavlova (2013, AER).** The general institutional-investors-and-asset-prices result. Benchmarking makes institutions' demand insensitive in a particular way and changes equilibrium risk premia and correlations. The theoretical backbone for "who holds the asset determines its betas."
- **Henderson, Pearson & Wang (2015, RFS).** The work order's third named anchor and, methodologically, **the single best template for this paper's design D3.** They use the issuance of commodity-linked notes (CLNs) as a source of *plausibly exogenous* hedging-driven flow into commodity futures — the issuer must hedge, on a schedule set by the note's terms rather than by commodity news — and show that this financial-investor flow moves futures prices. The logic (isolate the component of flow that is mechanically driven rather than information-driven) is exactly the logic of the plan's basis-vs-allocation decomposition, run in the opposite direction: Henderson–Pearson–Wang isolate the *mechanical* component as the instrument; the plan isolates the mechanical (basis-trade) component in order to *discard* it and keep the discretionary residual. **The drafting specialist should make this inversion explicit — it is a genuine methodological contribution and it is legible to referees precisely because HPW is well known.**
- **Cheng & Xiong (2014, ARFE).** The essential counterweight. They argue that the index-flow explanation for commodity comovement is **overstated**, that much of the observed correlation increase reflects common macro shocks (global demand, the dollar, monetary policy) rather than financialization, and that index traders are not obviously destabilizing. **A referee who knows this literature will raise Cheng–Xiong against this paper's H1 immediately.** The paper's answer must be design D2: the macro-shock alternative predicts a uniform correlation increase across all trading sessions; only a US-vehicle channel relocates covariance into US exchange hours. The drafting specialist should make Cheng–Xiong the named antagonist in the introduction and D2 the named response.
- **Hong & Yogo (2012, JFE); Singleton (2014, ManSci); Büyükşahin & Robe (2014, JIMF).** Flows and positioning in futures markets forecast returns and comovement; Büyükşahin–Robe in particular links hedge-fund participation to commodity–equity correlation, which is the closest precedent for the paper's investor-type decomposition.
- **Merton (1987, JF).** Investor recognition with participation costs. The formal source for the plan's κ. **Its absence from the bibliography is the most damaging of the blocked items**, since the entire §4 model is a Merton (1987) application.
- **Koijen & Yogo (2019, JPE).** Demand-system asset pricing — the modern statement that who holds an asset determines its price and its covariance structure. Optional but strengthens the framing.

### 4.2 What this strand implies for the paper's priors

Commodity financialization delivered a measurable, contested, macro-confounded increase in equity comovement. The honest prior for Bitcoin is therefore: **a positive but modest Δβ, heavily confounded by macro, and contested.** The plan's §3.5 point that "most practitioners would guess yes" is correct, but the commodity precedent suggests the interesting magnitude is smaller than practitioners expect and the attribution problem is the substance of the paper. This supports the plan's decision to make attribution (not sign) the headline.

---

## 5. Strand 4 — Event-study and structural-break evidence on the 2024 approval

### 5.1 `khatib2026from` — Al khatib & Alshaib (2026), *International Review of Economics & Finance*
### "From contagion to stabilization: Spot Bitcoin ETFs and the regime shift in crypto-equity integration"

**UNREAD — paywalled (ScienceDirect 403). This is the paper's nearest competitor and the highest-priority outstanding item.**

What can be said with confidence from the title and outlet alone, and *only* that:

1. The paper is about **spot Bitcoin ETFs** and **crypto–equity integration**, i.e. the same object as this paper's dependent variable.
2. It claims a **regime shift**, i.e. the descriptive claim "integration changed around the spot ETF" is already published.
3. The direction of the claim — "from contagion to *stabilization*" — is notable and **may cut against this paper's H1.** A "stabilization" framing suggests they find integration becoming *more orderly* or spillovers becoming *less* crisis-like after the ETF, not simply larger. If so, this paper's H1 (β rises) and their headline are not the same claim, and the two can coexist. The plan currently assumes they document a comovement *increase*; that assumption is not supported by the title and should not be written down until the paper is read.
4. *IREF* is a respectable field journal. The descriptive claim is therefore staked in a citable venue, and the plan's §3.4 conclusion — **the top-journal case rests entirely on identification and mechanism** — stands.

**Concrete instruction for whoever reads it.** Three questions determine the positioning, in order:
- (a) Do they use any **cross-asset counterfactual** (other coins, other assets, synthetic control)? If yes, design D1's novelty is substantially reduced and the paper must lead with D2.
- (b) Do they decompose by **trading session or intraday**? Almost certainly not, but if yes, the paper's central exhibit is gone and it must be rebuilt around D1 + the flow decomposition.
- (c) Do they use **flow data** at all, and do they distinguish flow types? If they use headline AUM, the plan's H3 basis-trade critique (§2) applies to them directly and becomes a named contribution: *this paper shows the flow measure used in the prior literature conflates market-neutral basis positions with directional allocation.*

Until (a)–(c) are answered, **the introduction's positioning paragraph cannot be finalized.**

### 5.2 `tang2026the` — Tang (2026), "The Structural Impact of Bitcoin Spot ETFs on Liquidity and Risk Spillovers"

**Read in full.** This is a **narrative literature review**, not an empirical paper, published in a low-tier non-finance outlet (Dean&Francis, *Science and Technology of Engineering Chemistry and Environmental Protection*), with visibly garbled passages and unverifiable secondary statistics. **It is not a credible competitor and should be cited sparingly, if at all.**

But it matters for calibration, because it **asserts in print, as settled, several of the mechanisms this paper proposes to test.** Specifically:

- *"The Authorized Participant (AP) subscription and redemption mechanism introduced by the ETFs effectively compresses price spreads across exchanges and enhances weekend market liquidity depth."* — the plan's D2 weekend-margin test.
- *"The daily creation and redemption mechanism of APs maps the liquidity of the U.S. stock trading session directly to the cryptocurrency spot market, thereby breaking the traditional assumption that 'cryptocurrencies are isolated islands'."* — **this is the plan's D2 session hypothesis, stated almost verbatim.** The review immediately concedes that "this cross-asset liquidity transmission mechanism has not yet been sufficiently studied."
- *"By incorporating Bitcoin into the traditional margin account system via ETFs, risk contagion has transformed from an 'extreme tail event' into a 'routine, strong feedback pattern,' gradually diminishing Bitcoin's hedging properties."* — the "risk assetization" thesis, i.e. the paper's H1, asserted as fact.
- It frames the crypto–traditional linkage literature as moving *"from 'hedge narrative' to 'risk assetization'."*

**Calibration consequence.** The *idea* that the AP mechanism imports US-session liquidity and equity-market risk into Bitcoin spot is in print. The paper cannot claim to have thought of it first. What is not in print, by this review's own admission, is a **test**: nobody has decomposed realized BTC–equity covariance by trading session, pre vs. post. The contribution is therefore identification and measurement, not conjecture. The drafting specialist should cite `tang2026the` *for the conjecture*, which strengthens rather than weakens the paper — it establishes that the mechanism is the one practitioners and reviewers already suspect, and that testing it is the open problem.

Descriptive figures from the review (**second-hand; verify before use**): by October 2025, US spot Bitcoin ETFs held ~1.358 million BTC (≈6% of circulating supply) with AUM > $169.48bn (≈6.79% of Bitcoin market value); IBIT accounted for >50% of average daily volume among these products; institutions were ~25.4% of spot-ETF AUM.

### 5.3 `guliyev2025from` — Guliyev & Ahmadova (2025), *Ledger*

**Read in full.** Daily data from 11 January 2024 to 16 May 2025. Tests cointegration between aggregate spot-Bitcoin-ETF net assets and the Bitcoin price using FMOLS, DOLS and CCR. Finds a positive long-run association — expanding ETF assets correspond to higher Bitcoin price levels — with **cointegration confirmed only at the 10% level.** They claim to be the first analysis of the long-run flows–price relation for crypto ETFs.

**Relationship to this paper.** Complementary, not competing: they study flows → **price level**; this paper studies flows → **factor loadings**. Three points of leverage:

1. **Their weak result supports the plan's H3.** Cointegration significant only at 10%, over a 16-month window with enormous flows, is a thin link. The plan's explanation — that a large fraction of headline AUM is market-neutral cash-and-carry rather than directional allocation — predicts exactly this attenuation. **The basis-vs-allocation decomposition can be motivated as resolving an existing puzzle in the published literature rather than as a hypothetical concern.** This materially strengthens §5.3 of the plan.
2. **Their design cannot decompose flows.** A cointegrating regression on aggregate net assets treats all flow as homogeneous. Stating this is fair and specific.
3. **Useful verified institutional facts from their text** (each attributed to their footnoted sources; verify independently before the paper quotes them): the SEC formally disapproved 20+ spot-Bitcoin-ETF filings between 2018 and 2023; BlackRock filed 15 June 2023; the SEC approved 11 spot Bitcoin ETFs on 10 January 2024 following the D.C. Circuit's vacatur of the Grayscale denial; trading began 11 January 2024 with **>$4.7bn traded on day one**; cumulative net inflows reached **~$10bn within two months**; the funds averaged **~2.8% of total US ETF trading volume** in early 2024; **Bitcoin's price was roughly unchanged (~$46,500) on launch day and the new ETFs traded down a few percent.**

**That last fact is important and the drafting specialist should use it.** A muted price reaction to a massively anticipated, massively-traded launch is direct evidence for the plan's anticipation problem (§5.5) and its donut specification — the news was in the price by January 11. It also sharpens the paper's framing: the ETF's effect is **not** a level effect that was arbitraged away in advance; it is a *persistent change in the return-generating process*, which cannot be pre-traded in the same way. This is a genuinely good argument for why studying betas rather than prices is the right move, and it is supported by published evidence.

For the earlier international precedent, they note Canada's Purpose Bitcoin ETF (BTCC, February 2021) gathered $1bn AUM in its first month, and that the US permitted only futures-based products from ProShares **BITO (October 2021)** onward, with roll costs. **An untreated-but-obvious extension: Canada's February 2021 spot ETF is an out-of-sample replication of the entire design, three years earlier, in a smaller market.** The plan does not mention it. It is worth a robustness subsection.

### 5.4 `pucher2026falsenews` — Pucher, Schiereck & Bormann (2026), *JAIS*

Not retrievable in this session (no DOI in the record; AIS eLibrary not reachable). From the title — *"False-News Triggers As New Manipulation Risk – Evidence From The Bitcoin ETF Approval"* — and the outlet (*Journal of the AIS*, a credible IS venue), it studies the **9 January 2024 compromised-SEC-account false approval tweet**. The plan's use of it is correct and should be preserved: E2 is a near-identical *news* shock with **no access change**, making it the ideal placebo against E3/E4. This is a complement; cite it generously and defer to it for event construction and timestamping. **Action for the next specialist: retrieve it from AIS eLibrary and extract their exact event timestamps and window conventions**, so the placebo is constructed on the same clock as the published record.

### 5.5 The 2021 futures ETF (BITO) and the GBTC discount — **unresolved gap**

The work order asks for this explicitly. **I found no published work on either topic in the accessible literature, and I could not run an external search.** I am not asserting that none exists — I am asserting that I could not check, which is a different and weaker statement, and the drafting specialist must not treat this gap as evidence of novelty.

What is needed:
- **BITO (October 2021).** A futures-based ETF that provided US-brokerage access *without* spot exposure and *with* roll costs. This is a near-ideal **partial-treatment control**: same wrapper, same habitat, same brokerage access, but an inferior access technology and no creation/redemption in spot BTC. If Bitcoin's equity beta rose in October 2021 as well, the "access" channel is confirmed but the "spot plumbing" channel is not distinguished; if it rose only in 2024, the paper has a second, independent event. **This is a materially valuable addition to the design that the plan does not currently exploit, and it should be added as a fifth event (E0) in D4 and as a second treatment date in the break tests.** Note the confound: BITO launched at the October–November 2021 cycle peak.
- **The GBTC discount collapse.** GBTC traded at a persistent discount to NAV (reportedly approaching −50% in late 2022) that converged to ~0 upon conversion in January 2024. This is the clearest possible evidence that the ETF **restored an arbitrage mechanism** that had been absent, and it is the single most legible quantitative fact supporting the paper's plumbing channel. It also drives the GBTC outflows the plan nets out of the flow series. Any published treatment of the discount's dynamics should be located and cited.

**Search strings for the next specialist with search access:** `"spot bitcoin ETF" approval event study abnormal returns`; `"BITO" OR "bitcoin futures ETF" launch event study 2021`; `"Grayscale Bitcoin Trust" discount premium closed-end arbitrage`; `bitcoin ETF flows institutional ownership 13F`; `cryptocurrency financialization index investment commodities` (the plan's §12 instruction — this is where an unnoticed competitor is most likely hiding); `bitcoin equity beta structural break 2024`; `cash and carry basis trade bitcoin ETF CME`.

---

## 6. Contribution calibration — what is new and what is already documented

This is the section the work order asked for. It is written to be used adversarially: assume a referee has read everything in §§2–5.

### 6.1 Already documented — do **not** claim as contribution

| Claim | Already established by | Strength |
|---|---|---|
| Bitcoin's correlation with US equities rose sharply from 2020 | `conlon2020safe`, `corbet2020the`; Iyer (2022, IMF) | Strong, uncontested |
| Bitcoin is not a reliable hedge or safe haven | `bouri2016on`, `conlon2020safe`, `corbet2020the` | Strong |
| Pre-2020 crypto was largely disconnected from equity factors | `liu2020risks`, `liu2022common`, `corbet2018exploring` | Strong, top-journal |
| **A regime shift in crypto–equity integration occurred around the spot ETF** | **`khatib2026from` (IREF)** | **Published, field journal — the descriptive claim is taken** |
| Spot ETF assets and Bitcoin's price are linked in the long run | `guliyev2025from` | Published, weak (10% level) |
| ETF ownership raises comovement and volatility of the underlying | `da2017exchange`, `bendavid2014do`, `brown2020etf` | Strong, top-journal |
| Index/category membership generates comovement absent fundamentals | `barberis2004comovement`, `boyer2011stylerelated`, `greenwood2007excess`, `vijh1994sp`, `froot1999how` | Strong, and closer to "fundamentals-free" than the plan concedes |
| New financial products raised commodity–equity comovement | Tang & Xiong (2012); Henderson, Pearson & Wang (2015) — *blocked* | Strong, and contested by Cheng & Xiong (2014) |
| The AP creation/redemption mechanism maps US-session liquidity into crypto spot | **Asserted in `tang2026the`**; untested | Conjecture in print |
| Bitcoin has entered institutional balance sheets and margin systems | `tang2026the`; BIS/IMF work | Descriptive |
| The 9 January 2024 false tweet is a studiable event | `pucher2026falsenews` | Published |

### 6.2 Genuinely new — ranked by defensibility

**1. The intraday session decomposition of the covariance *increase* (D2). Strongest claim to novelty.**
Nobody in the accessible literature decomposes BTC–equity realized covariance by trading session, pre vs. post. `tang2026the` conjectures the mechanism and explicitly states it "has not yet been sufficiently studied." `makarov2019trading` provides the venue-segmentation groundwork but does not do this test. **Crucially, D2 is also the only design that answers the Cheng–Xiong (2014) critique**, which is the strongest objection the financialization literature can raise: a common macro regime raises correlation in all sessions; only a US-listed-vehicle channel relocates covariance into US exchange hours. *Novelty: high. Referee-resistance: high. Cost: low.* **This should be the lead exhibit, as the plan says.**

**2. The basis-vs-allocation flow decomposition (D3).**
Novel in crypto. Note two precedents that partially anticipate the *logic*: commodity studies routinely classify traders using CFTC COT data (Büyükşahin & Robe 2014), and Henderson–Pearson–Wang (2015) isolate mechanically-driven hedging flow. The application — projecting ETF flow on the CME annualized basis and open interest to strip out cash-and-carry, validated against 13F filer types — appears to be new, and §5.3 above shows it **resolves an existing puzzle** (`guliyev2025from`'s weak cointegration despite enormous AUM). *Novelty: medium-high. Referee-resistance: medium (instrument and projection are contestable). Independent value as a data construct: high.*

**3. The staggered cross-coin DiD counterfactual for a crypto–equity beta (D1).**
Not found in the accessible literature. **Conditional on `khatib2026from` not already using a cross-asset counterfactual — unverified.** Weakened by SUTVA (`hu2019cryptocurrencies` documents the strong common crypto factor that guarantees spillovers) and by Bitcoin's non-exchangeability. *Novelty: medium, pending verification. Referee-resistance: medium-low — this is where the referee will push hardest.*

**4. The zero-cash-flow identification argument. High rhetorical value; must be narrowed.**
The plan calls this "the intellectual centerpiece" and says no equity study can claim it. **That is over-stated in three specific ways, and each should be fixed before drafting:**

- **`froot1999how` (twin shares) already holds cash flows exactly constant** — Royal Dutch and Shell are claims on the *same* cash flows and still comove with their respective local markets. This is a cleaner fundamentals control than "no cash flows," and it is a 1999 JFE paper. `boyer2011stylerelated` (mechanical reclassification) and `greenwood2007excess` (index-weight redefinition) are also near-fundamentals-invariant. **Correct framing: Bitcoin does not do something unprecedented; it does something the twin-share and reclassification designs achieve only for a handful of securities, and it does it for an entire asset class, continuously, with a large and well-dated treatment.** That is a defensible claim. "No prior study can claim this" is not.
- **"No cash flows" ≠ "no fundamentals."** Bitcoin has hashrate, halvings, on-chain activity, adoption, exchange failures, and a regulatory environment, all of which are fundamentals in the relevant sense and all of which could plausibly have become more correlated with the US macroeconomy over 2024–2025 (a US election that repriced crypto policy is *precisely* a shock that correlates Bitcoin's fundamentals with US asset prices). The defensible claim is narrower and should be written narrowly: **there are no cash-flow news events that could become more correlated with aggregate earnings news, which is the specific channel BSW's fundamentals view relies on.**
- **A discount-rate change is not automatically a clientele effect.** The plan's logic — no cash flows ⇒ any Δβ is discount-rate ⇒ clientele — skips a step. Bitcoin is a long-duration, zero-cash-flow asset whose valuation is highly sensitive to real rates; a common real-rate factor pricing both Bitcoin and equities is a *fundamental* discount-rate channel requiring no change in who holds the asset. **This is the most serious logical gap in the current framing.** The fix is already in the plan: D2 and the flow dose–response distinguish clientele-induced from commonly-priced discount-rate comovement. The introduction must make that step explicitly rather than leaving the inference to the reader. The plan's §6.4 factor-migration test (adding real yields, breakevens, DXY) is the other half of the answer and should be elevated.

*Assessment: the framing is the paper's best writing asset and its most attackable claim. Narrowed as above, it survives. Stated as in the current plan draft, a referee who knows `froot1999how` will open with it.*

**5. Magnitude decomposition (β = ρ·σ_BTC/σ_MKT) and the allocator-relevant translation.**
Not a novelty claim, but the plan's §5.0 and §11 discipline — reporting ρ² alongside every correlation, separating the correlation term from the volatility-ratio term, and translating into optimal sleeve weights — is genuinely rare in this literature and is the kind of thing that gets a paper cited by practitioners. Keep it. It is also a defence: if Bitcoin's own volatility fell over the sample, a rising ρ with flat β is possible, and no existing paper in §5 appears to make that distinction.

**6. Pre-committed null interpretation (plan §7.5).** Strengthened by the §2.2 `israeli2017is` / `glosten2020etf` tension: ETFs shift price informativeness from idiosyncratic toward *systematic earnings* information. Bitcoin has no earnings for that channel to operate on. A null therefore has a specific, citable micro-foundation rather than being a rationalization — it would localize habitat comovement in the shared-cash-flow-news channel. **This is a real intellectual asset and the drafting specialist should build it out.**

### 6.3 Net assessment of the contribution claim

**Defensible positioning:** *the descriptive fact is known and published (`khatib2026from`); this paper supplies the counterfactual, the mechanism, and the magnitude decomposition, in a setting where the cash-flow-news channel that confounds the entire index-comovement literature is unavailable.*

**Not defensible:** "we are the first to document that Bitcoin's correlation with equities changed after the ETF." **Not defensible:** "no prior setting holds fundamentals constant." **Not yet defensible, pending a read of `khatib2026from`:** "we are the first to use a cross-asset counterfactual."

**The single highest-value action for the pipeline is to obtain and read `khatib2026from`.** The second is to add the strand-3 references in §1.4, without which the paper cannot credibly claim to build on the financialization literature at all.

---

## 7. Open questions, conflicts, and items for human decision

1. **`khatib2026from` unread.** Paywalled. Positioning in plan §3.2/§3.3 is unverified inference. The title's "from contagion to *stabilization*" may not be the comovement-increase claim the plan assumes. **Blocking for the introduction.**
2. **Strand 3 is not citable.** Save budget exhausted at 30/30. Tang–Xiong, Basak–Pavlova (×2), Henderson–Pearson–Wang, Cheng–Xiong, Merton, Bekaert–Harvey, Karolyi–Stulz are all missing. **Blocking for the framing and the model section.**
3. **All econometric method citations are missing** (Engle, Bai–Perron, Andrews, Callaway–Sant'Anna, Sun–Abraham, Borusyak et al., Rambachan–Roth, Scholes–Williams, Dimson, Abadie et al.). **Blocking for the methods section.**
4. **IMF/BIS spillover work not recorded**, in particular Iyer (2022) "Cryptic Connections" — the pre-period benchmark for the paper's central quantity. If Iyer already attributes rising crypto–equity comovement to institutional entry, the paper's *hypothesis* is pre-existing and only its *identification* is new; the introduction must say so.
5. **BITO (2021) and GBTC-discount literature unsearched.** I could not check. Do not treat as a novelty gap.
6. **Recommended design addition, not in the plan:** add **BITO (October 2021)** as a partial-treatment event — same brokerage habitat, inferior access technology, no spot creation/redemption. It separates "access" from "spot plumbing" and gives a second dated treatment for the endogenous break tests. Confound: it launched at the 2021 cycle peak.
7. **Second recommended addition:** **Canada's Purpose Bitcoin ETF (February 2021)** as an out-of-sample replication in a smaller market with an earlier date.
8. **Unresolved tension to exploit, not suppress:** `israeli2017is` (ETFs degrade the information environment) vs. `glosten2020etf` (ETFs improve *systematic* informational efficiency). These reconcile as a shift from idiosyncratic to systematic informativeness. That reconciliation is the paper's best micro-foundation for both H1 and the §7.5 null.
9. **Retracted-paper hazard.** `corbet2018retracted` is in the bib and is a natural cite-from-memory. Flagged in §1.3; the reference-check reviewer should confirm it never appears.
10. **Human decision required:** whether the paper leads with the identification framing (JFE/RFS strategy — requires D1 and D2 both to deliver, and requires the §6.2(4) narrowing) or with the allocator-relevant magnitude decomposition (JFQA/*Review of Finance*/*Management Science* strategy — robust to a null). The literature does not settle this; the pre-trend plot (plan Figure 4) and the D2 exhibit do.

---

## 8. Structured bibliography

### 8.1 Comovement, habitat, and style investing
| Key | Reference |
|---|---|
| `pindyck1993the` | Pindyck, R.S. & Rotemberg, J.J. "The Comovement of Stock Prices." *QJE.* doi:10.2307/2118460 |
| `froot1999how` | Froot, K.A. & Dabora, E.M. "How are stock prices affected by the location of trade?" *JFE.* doi:10.1016/s0304-405x(99)00020-3 |
| `barberis2003style` | Barberis, N. & Shleifer, A. "Style investing." *JFE.* doi:10.1016/s0304-405x(03)00064-3 |
| `barberis2004comovement` | Barberis, N., Shleifer, A. & Wurgler, J. "Comovement." *JFE* (publ. 2005, 75(2), 283–317). doi:10.1016/j.jfineco.2004.04.003 |
| `greenwood2007excess` | Greenwood, R. "Excess Comovement of Stock Returns: Evidence from Cross-Sectional Variation in Nikkei 225 Weights." *RFS* (publ. 2008). doi:10.1093/rfs/hhm052 |
| `boyer2011stylerelated` | Boyer, B.H. "Style-Related Comovement: Fundamentals or Labels?" *JF.* doi:10.1111/j.1540-6261.2010.01633.x |

### 8.2 Index inclusion, demand curves, and beta
| Key | Reference |
|---|---|
| `shleifer1986do` | Shleifer, A. "Do Demand Curves for Stocks Slope Down?" *JF.* doi:10.1111/j.1540-6261.1986.tb04518.x |
| `harris1986price` | Harris, L. & Gurel, E. "Price and Volume Effects Associated with Changes in the S&P 500 List." *JF.* doi:10.1111/j.1540-6261.1986.tb04550.x |
| `vijh1994sp` | Vijh, A.M. "S&P 500 Trading Strategies and Stock Betas." *RFS.* doi:10.1093/rfs/7.1.215 |
| `chen2004the` | Chen, H., Noronha, G. & Singal, V. "The Price Response to S&P 500 Index Additions and Deletions." *JF.* doi:10.1111/j.1540-6261.2004.00683.x |
| `coles2022on` | Coles, J.L., Heath, D. & Ringgenberg, M.C. "On index investing." *JFE.* doi:10.1016/j.jfineco.2022.05.007 |
| `baltussen2018indexing` | Baltussen, G., van Bekkum, S. & Da, Z. "Indexing and stock market serial dependence around the world." *JFE* (publ. 2019). doi:10.1016/j.jfineco.2018.07.016 |

### 8.3 ETFs: comovement, volatility, arbitrage, information
| Key | Reference |
|---|---|
| `da2017exchange` | Da, Z. & Shive, S. "Exchange traded funds and asset return correlations." *European Financial Management* (publ. 2018, 24(1), 136–168). doi:10.1111/eufm.12137 |
| `bendavid2014do` | Ben-David, I., Franzoni, F. & Moussawi, R. "Do ETFs Increase Volatility?" *JF* (publ. 2018, 73(6), 2471–2535). doi:10.1111/jofi.12727 |
| `bendavid2017exchangetraded` | Ben-David, I., Franzoni, F. & Moussawi, R. "Exchange-Traded Funds." *Annual Review of Financial Economics.* doi:10.1146/annurev-financial-110716-032538 |
| `israeli2017is` | Israeli, D., Lee, C.M.C. & Sridharan, S.A. "Is there a dark side to exchange traded funds? An information perspective." *Review of Accounting Studies.* doi:10.1007/s11142-017-9400-8 |
| `glosten2020etf` | Glosten, L.R., Nallareddy, S. & Zou, Y. "ETF Activity and Informational Efficiency of Underlying Securities." *Management Science* (publ. 2021). doi:10.1287/mnsc.2019.3427 |
| `brown2020etf` | Brown, D., Davies, S. & Ringgenberg, M.C. "ETF Arbitrage, Non-Fundamental Demand, and Return Predictability." ***Review of Finance*** (publ. 2021 — journal field in bib is wrong). doi:10.1093/rof/rfaa027 |

### 8.4 Crypto asset pricing and comovement with traditional assets
| Key | Reference |
|---|---|
| `liu2020risks` | Liu, Y. & Tsyvinski, A. "Risks and Returns of Cryptocurrency." *RFS* (publ. 2021, 34(6)). doi:10.1093/rfs/hhaa113 |
| `liu2022common` | Liu, Y., Tsyvinski, A. & Wu, X. "Common Risk Factors in Cryptocurrency." *JF.* doi:10.1111/jofi.13119 |
| `makarov2019trading` | Makarov, I. & Schoar, A. "Trading and arbitrage in cryptocurrency markets." *JFE* (publ. 2020, 135(2)). doi:10.1016/j.jfineco.2019.07.001 |
| `biais2023equilibrium` | Biais, B., Bisière, C., Bouvard, M., Casamatta, C. & Menkveld, A.J. "Equilibrium Bitcoin Pricing." *JF.* doi:10.1111/jofi.13206 |
| `griffin2020is` | Griffin, J.M. & Shams, A. "Is Bitcoin Really Untethered?" *JF.* doi:10.1111/jofi.12903 |
| `hu2019cryptocurrencies` | Hu, A.S., Parlour, C.A. & Rajan, U. "Cryptocurrencies: Stylized facts on a new investible instrument." *Financial Management.* doi:10.1111/fima.12300 |
| `baur2017bitcoin` | Baur, D.G., Hong, K. & Lee, A.D. "Bitcoin: Medium of exchange or speculative assets?" *JIFMIM* (publ. 2018). doi:10.1016/j.intfin.2017.12.004 |
| `bouri2016on` | Bouri, E., Molnár, P., Azzi, G., Roubaud, D. & Hagfors, L.I. "On the hedge and safe haven properties of Bitcoin." *FRL* (publ. 2017). doi:10.1016/j.frl.2016.09.025 |
| `corbet2018exploring` | Corbet, S., Meegan, A., Larkin, C., Lucey, B.M. & Yarovaya, L. "Exploring the dynamic relationships between cryptocurrencies and other financial assets." *Economics Letters.* doi:10.1016/j.econlet.2018.01.004 |
| `conlon2020safe` | Conlon, T. & McGee, R. "Safe haven or risky hazard? Bitcoin during the Covid-19 bear market." *FRL.* doi:10.1016/j.frl.2020.101607 |
| `corbet2020the` | Corbet, S., Larkin, C. & Lucey, B.M. "The contagion effects of the COVID-19 pandemic: Evidence from gold and cryptocurrencies." *FRL.* doi:10.1016/j.frl.2020.101554 |
| ~~`corbet2018retracted`~~ | **RETRACTED — do not cite.** doi:10.1016/j.irfa.2018.09.003 |

### 8.5 Spot Bitcoin ETF (2024) — direct competitors and complements
| Key | Reference | Role |
|---|---|---|
| `khatib2026from` | Al khatib, A.M.G. & Alshaib, B.M. "From contagion to stabilization: Spot Bitcoin ETFs and the regime shift in crypto-equity integration." *IREF.* doi:10.1016/j.iref.2026.105664 | **Nearest competitor. UNREAD.** |
| `guliyev2025from` | Guliyev, T. & Ahmadova, A. "From Flows to Value: Cointegration Between Bitcoin Spot ETF Assets and Bitcoin Price." *Ledger* 10, 154–172. doi:10.5195/ledger.2025.393 | Complement; read in full |
| `tang2026the` | Tang, S. "The Structural Impact of Bitcoin Spot ETFs on Liquidity and Risk Spillovers in the Cryptocurrency Market." doi:10.61173/mpgy2h45 | Narrative review, weak outlet; conjectures the D2 mechanism |
| `pucher2026falsenews` | Pucher, A., Schiereck, D. & Bormann, M. "False-News Triggers As New Manipulation Risk – Evidence From The Bitcoin ETF Approval." *JAIS.* | Complement — supplies the D4 placebo event |

### 8.6 Adjacent, cite only if needed
`fantini2025informational` (JoES survey of crypto informational efficiency) · `apostolov2026diversification` (crypto vs. commodities as diversifiers) · `kang2025a` (ML prediction of dynamic crypto correlations)

### 8.7 Required but **not yet citable** — see §1.4 for save commands
Tang & Xiong (2012) · Basak & Pavlova (2013, 2016) · Henderson, Pearson & Wang (2015) · Cheng & Xiong (2014) · Hong & Yogo (2012) · Singleton (2014) · Büyükşahin & Robe (2014) · Merton (1987) · Bekaert & Harvey (1995) · Karolyi & Stulz (1996) · Koijen & Yogo (2019) · Cong, Li & Wang (2021) · Schilling & Uhlig (2019) · Borri (2019) · Auer & Tercero-Lucas (2022) · Makarov & Schoar (2022, BPEA) · Engle (2002, 2016) · Bai & Perron (1998, 2003) · Andrews (1993) · Callaway & Sant'Anna (2021) · Sun & Abraham (2021) · Borusyak, Jaravel & Spiess (2024) · Rambachan & Roth (2023) · Scholes & Williams (1977) · Dimson (1979) · Abadie, Diamond & Hainmueller (2010) · Diebold & Yilmaz (2012) · Iyer (2022, IMF GFSN 2022/001) · Auer et al. (2022, BIS WP 1013) · Cornelli et al. (2023, BIS Bulletin 69) · Aramonte, Huang & Schrimpf (2021, BIS QR) · SEC Release 34-99306 (2024) · *Grayscale v. SEC*, 82 F.4th 1239 (D.C. Cir. 2023)
