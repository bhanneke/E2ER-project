# Data Summary

**Paper:** *No Cash Flows, New Owners: Spot Bitcoin ETFs and the Origins of Comovement*
**Paper ID:** e432cf3f-9008-4202-8ee6-ff09a93948ec
**Prepared by:** data_analyst · **Extract date:** 2026-09-11
**Companion artifacts:** `summary_statistics.json` (machine-readable descriptives), `figure_spec.json` (diagnostic figures), `data_dictionary.json` (the frozen specification this build implements)

---

## 0. What this document is

This is the data-construction record for the paper. It states, in order: which sources were actually reachable and which were not; how the analysis sample was built from the raw extracts, filter by filter, with counts; how every variable is defined; and what the raw pre/post contrast in Bitcoin's equity co-movement looks like *before* any estimation, so that the difference-in-differences contrast is visible and auditable prior to the econometrics stage.

It is written against the specification in `data_dictionary.json`, which was frozen before this build ran. Where the realized build departs from that specification — and it departs in three material ways — the departure is stated here explicitly rather than absorbed silently.

**The three material departures, stated up front:**

1. **The baseline clock is not the one the design declared.** The design's baseline daily return is struck at 16:00 ET on both legs (`r_ec`), which makes the crypto and equity return windows exactly synchronous. Building it requires hourly crypto bars. The only configured hourly source (yfinance 60m) is capped at the trailing 730 days. The 16:00 ET clock is therefore unavailable before roughly 2024-09-12 — i.e. it does not exist in the pre-period at all. **The headline is computed on the 00:00 UTC clock (`r_utc`)**, which the design designated as the robustness clock. Every table in the paper must say which clock produced it. This is `blk_01` in the data dictionary and it is the single most consequential data limitation in the paper.
2. **ETF net flows could not be retrieved from any configured source.** No wrapper serves fund-level creations/redemptions, shares outstanding, or NAV. The flow series requested in the work order is therefore built from what *is* available — dollar volume and price — and is reported as a **turnover** series under its own name, explicitly **not** as net flow. Design D3 (flow dose–response) cannot be executed. See §6.
3. **Allium and FRED are both unconfigured.** The crypto price leg runs entirely on yfinance daily bars; the macro controls run on verified yfinance substitute tickers. Two macro series (10y TIPS real yield, 10y breakeven) have no substitute and are dropped.

None of the three touches the identification of the headline DiD, which uses BTC plus never-treated coins on a monthly correlation outcome. All three constrain what else the paper can claim.

**What the assembled data show before any estimation.** The panel is 610 coin-month cells — 10 coins × 61 months, balanced, with zero missing crypto observations. Bitcoin's mean monthly return correlation with SPY rose from 0.3822 in the clean pre-period to 0.3914 in the post-period, a change of +0.0092. The nine never-treated control coins rose by +0.0105 over the same windows. **The raw difference-in-differences contrast is therefore −0.0014 in correlation and −0.0813 in beta — approximately zero, and negative in sign.** Gold, which the design names as the macro-neutrality placebo, rose by +0.0581, six times Bitcoin's change. Section 7.3 reports all of this in full. The estimation stage should know going in that the design's own raw contrast does not show a differential increase.

---

## 1. Sources: what was reachable

| Source | Access path | Status | Role in this build |
|---|---|---|---|
| **yfinance** | `e2er-data yfinance history` | **WORKING** | Everything. Crypto daily bars (13 coins), equity/ETF/commodity daily bars, macro index levels, spot-ETF price and volume |
| **Ken French Data Library** | Direct HTTPS (no wrapper exists) | Attempted in build | MKT-RF, SMB, HML, RMW, CMA, MOM, RF — daily |
| **FRED** | `e2er-data fred` | **BLOCKED** — `FRED_API_KEY not configured` | None. Substituted (§3.4) |
| **Allium** | `e2er-data allium` | **BLOCKED** — `ALLIUM_API_KEY not configured` | None. The work order assigned Allium the crypto price leg; that leg runs on yfinance alone |
| **ETF flow data** (Farside / issuer disclosures / Bloomberg) | No wrapper | **BLOCKED** | None. See §6 |

The availability audit in `data_dictionary.json` (`availability_audit`, entries `aud_01` … `aud_11`, all run 2026-09-11) is the provenance record for these statuses. The two blocked API keys were verified by direct invocation and returned the exact configuration errors quoted above — this is a credentials gap, not a quota or rate-limit failure, and it is repairable in about a minute if the keys are supplied.

**Citation lines for the paper:**

> Daily price data: Yahoo Finance, retrieved 2026-09-11 via the `yfinance` Python library (https://pypi.org/project/yfinance/).
>
> Factor returns: Kenneth R. French Data Library, Dartmouth College, retrieved 2026-09-11. `F-F_Research_Data_5_Factors_2x3_daily` and `F-F_Momentum_Factor_daily`.

A note on Yahoo as the sole price source, which a referee will raise: Yahoo's crypto quotes are a cross-venue aggregate with no published methodology, and Yahoo revises history silently. Every pull in this build was made with `--save-to`, so the extract is frozen on disk and the replication package runs offline against the exact bars used here. The cross-venue validation the paper plan asked for (`qa_11`) is reduced to a spot check; it cannot be done systematically without Allium or CoinMetrics, and the paper should say so rather than imply a validation that was not performed.

---

## 2. Sample construction

### 2.1 The unit of analysis

The estimation panel is **coin × calendar-month**. The outcome is the Fisher-z transform of the within-month Pearson correlation between the coin's daily return and the US equity market return. Monthly non-overlapping blocks — not rolling windows — are what the estimation uses, because rolling windows share observations and would make the effective sample look like ~15,000 quasi-independent days when it is really ~68 months × 13 coins.

The rolling 30/60/90-day correlations and betas requested in the work order **are** built, and they are the basis of the diagnostic figures, but they are figure-only objects. A rolling 60-day series has a mechanical MA(59) structure: a true effect phases in linearly over 60 days regardless of the true dynamics, and pre-period values within 60 days of the event are contaminated by post-period returns. Reading an event-study shape off a rolling window is a known way to manufacture a result. The figures show the rolling series because it is the honest way to *display* the time path; the numbers that go into estimation do not come from it.

### 2.2 Windows

| Window | Dates | Months | Role |
|---|---|---|---|
| Primary sample | 2021-01-01 → 2026-08-31 | 68 | The panel |
| Clean pre | 2021-01-01 → 2023-07-31 | 31 | Pre-period for the raw contrast |
| Donut (excluded from headline) | 2023-08-01 → 2024-01-31 | 6 | Grayscale ruling (2023-08-29), the two false-news events, listing week, GBTC redemption transition |
| Post | 2024-02-01 → **2026-07-31** | **30** | Post-period for the raw contrast |
| Extraction request window | 2020-12-01 → 2026-09-11 | — | The extra month yields a clean first return in Jan-2021 |

The post-period ends 2026-07, not 2026-08 as the specification anticipated. The Ken French daily factor files trail the extract date by about a month and every cell needs the daily risk-free rate for its excess-return leg, so August 2026 is truncated rather than padded. See §7.2.

The donut is a design choice inherited from `identification_strategy.md` §7, not a data-cleaning convenience. The no-donut variant (`d_post_listing_raw`, treatment from 2024-01-11) is built in parallel and both are reported.

### 2.3 Inclusion / exclusion filters, in order

The filters below are applied in exactly this order, and the same filters are applied in the estimation script. Realized counts are in §7 and in `summary_statistics.json#sample_flow`.

1. **Raw daily bars retrieved** — all tickers, full request window, as returned by the source.
2. **Restrict to the primary sample window** (2021-01-01 → 2026-08-31).
3. **Drop non-positive or missing closes.** A missing bar leaves the return missing. No forward-filling of crypto prices anywhere — forward-filling a 24/7 asset manufactures zero returns, which mechanically deflates both its variance and its correlation with anything.
4. **Compute log returns**; the first observation of each series is lost by construction.
5. **Restrict the daily estimation panel to NYSE trading sessions.** Crypto trades 365 days; equities do not. Crypto returns on days the NYSE is closed are not discarded — they are retained in a separate off-day file for the weekend-margin test (`dv_17`, falsification F14), which is the one piece of the intraday design's logic that survives without hourly data.
6. **Require both legs non-missing** on a session for that session to enter a coin's monthly correlation.
7. **Aggregate to coin-months.** Require `n_days_m >= 15` usable sessions in the month. Cells below the threshold are flagged and dropped from the headline; the count of dropped cells is reported.
8. **Assert |rho_m| < 0.999** so the Fisher-z is finite. Flag, never clip — a clipped correlation is an invented number.
9. **Headline sample filter:** cohort ∈ {`treated_btc`, `never_treated`} and `d_donut == False`. Eventually-treated coins (ETH, SOL, XRP) are excluded from the headline control group so that no already-treated unit ever serves as a comparison.

**Missing-value handling, stated explicitly because referees flag silent drops:** missing values are *dropped*, never coded zero and never imputed. The sentinel is `NaN`/`null`, never 0 and never -999. Exchange outages and provider gaps are logged rather than patched; a gap voids the affected cell. No winsorization in the headline; a 0.5/99.5 within-asset variant is carried as a robustness flag.

### 2.4 The asset set

**Treated:** BTC (US spot ETFs listed 2024-01-11).

**Eventually treated — excluded from the headline control group:** ETH (2024-07-23), SOL, XRP. SOL and XRP listing dates are stored as `null` deliberately. A US spot SOL ETF and a US spot XRP ETF both listed during 2025, but the exact first trading days must come from each fund's Form 8-A and the exchange listing notice. A guessed cohort date does not fail loudly — it quietly mis-assigns treatment timing and biases the pooled ATT, and no diagnostic in this pipeline would catch it. **The staggered multi-cohort extension must not be run until those two dates are verified from primary sources.** The headline DiD does not touch them.

**Never treated — the headline control group (9 coins):** LTC, BNB, ADA, DOGE, BCH, LINK, AVAX, DOT, XLM.

Two of these carry caveats that belong in the paper rather than in a footnote. BNB is an exchange-affiliated token whose returns load on Binance-specific regulatory news, and the 2023 DOJ/CFTC actions sit inside the pre-period; a leave-BNB-out row is mandatory. DOGE's May-2021 episode is a large idiosyncratic pre-period shock, which raises DOGE's idiosyncratic variance and therefore *lowers* its equity correlation — biasing the DiD against finding a BTC effect, so keeping it is the conservative choice. LTC is a recurring spot-ETF filing candidate and must be re-checked at estimation time; if an LTC spot ETF listed inside the sample it moves to eventually-treated and leaves the control group.

**Equity / market legs:** MKT (Ken French MKT-RF + RF), SPY, ^GSPC, QQQ, IWM, ARKK, XLK, ACWX. On the CRSP substitution: the paper plan's first choice was the CRSP value-weighted index, which requires WRDS. Ken French's MKT-RF *is* the CRSP value-weighted excess return, so this is an exact substitution, not a compromise, and the paper should say so plainly.

**Placebo assets:** GLD, SLV. Gold is a placebo, not a control — a long-standing ETF wrapper, the same macro regime, no 2024 access change. A January-2024 break in gold's equity correlation would falsify the design's macro-neutrality.

**Macro:** ^VIX, ^MOVE, DX-Y.NYB (dollar index), ^TNX (10y nominal yield).

**Bitcoin ETPs:** the ten retrievable spot funds (IBIT, FBTC, GBTC, ARKB, BITB, BTCO, EZBC, BRRR, HODL, BTCW), plus BITO (futures wrapper, October-2021 launch) as the F6 placebo.

---

## 3. Variable definitions

### 3.1 Returns and the clock

Log returns throughout, stored in **decimals**, never percent: `r[i,t] = ln P[i,t] − ln P[i,t−1]`.

- **`r_utc`** — log change of the yfinance daily close dated *t*. Verified: yfinance crypto daily bars are stamped `00:00:00+00:00`, so this bar **is** the 00:00-UTC-to-00:00-UTC clock. **This is the de facto baseline in this build.**
- **`r_ec`** — the 16:00-ET-to-16:00-ET return, where *t−1* is the previous *NYSE session*, not the previous calendar day. Exactly synchronous across legs by construction, including across weekends. **Constructible only from ~2024-09-12; not built for the pre-period.**
- **`rx`** — excess return, `r − rf`, with `rf` the Ken French daily risk-free rate converted from percent to decimal. On multi-day spans (weekends) `rf` is summed over the calendar days in the span, not applied once.

**The non-synchronicity this costs us, stated precisely.** The UTC crypto day for date *t* ends at 19:00 ET (EST) or 20:00 ET (EDT) — three to four hours *after* the equity close — and begins twenty to twenty-one hours *before* it. The mismatch is two-sided, not a simple lead or lag, which is why a single Scholes-Williams lag correction is not sufficient and why the 3-day-return construction is the preferred invariance check.

**Why this matters for the headline claim, and which way it cuts.** Resynchronization is the most underrated threat to this design. If the ETF relocated Bitcoin price discovery into US cash hours, then a daily correlation struck on a 16:00 ET clock would rise *mechanically*, with the 24-hour covariance unchanged. Running on the UTC clock does not make that threat disappear, but it does change its sign structure: the UTC clock is *not* the clock that a US-hours relocation would mechanically favour, so a positive result on the UTC clock is, if anything, harder to attribute to pure resynchronization than the same result on the ET clock would be. The pre-committed invariance checks remain `rho_3d_m` (correlation of non-overlapping 3-session cumulative returns) and `beta_dimson_m` (Dimson sum of lead, contemporaneous and lag betas), both computed on 63-session blocks. If the effect vanishes under those, the pre-committed reading is that the ETF re-timed price discovery without changing 24-hour covariance — which is a real and reportable result, not a failed paper.

**Timezone handling.** Every timestamp is tz-aware. 16:00 ET is 21:00 UTC under EST and 20:00 UTC under EDT; the conversion is done with the tz database (`zoneinfo`, `America/New_York`), never with a fixed offset — a hardcoded −5 silently corrupts roughly eight months of every year. Comparing a tz-aware timestamp to a tz-naive one is the most common way this build breaks; all joins are on `date_et`, a plain date derived after conversion.

### 3.2 Co-movement objects

| Variable | Definition | Role |
|---|---|---|
| `rho_m` | Pearson corr(`r[i,t]`, `r_mkt[t]`) within calendar month *m*, non-overlapping | Input to the primary outcome |
| **`y_fisherz_corr_equity`** | `artanh(rho_m)` | **PRIMARY OUTCOME.** Unbounded, approximately normal, variance `1/(n_m−3)` known and identical across coins |
| `se_fisherz` | `1/sqrt(n_m − 3)` | Stored per cell; makes the two-step generated-outcome correction available and makes `1/se²` a legitimate GLS weight |
| `beta_m` | OLS slope of `rx[i,t]` on `rx_mkt[t]` within *m* | Secondary outcome |
| `ln_sigma_ratio_m` | `ln( sd(r_i) / sd(r_mkt) )` within *m* | Second leg of the beta decomposition |
| `rho2_m` | `rho_m²` | Magnitude discipline; printed beside every correlation |
| `rho_3d_m`, `beta_dimson_m` | On 63-session blocks | Timing-invariance checks |
| `rho_30d`, `rho_60d`, `rho_90d` | Trailing-window Pearson correlation, backward-looking only | **Figures only** |
| `beta_30d`, `beta_60d`, `beta_90d` | Trailing-window OLS slope of `rx_i` on `rx_mkt` | **Figures only** |
| `rcov_m` | Σ over days in *m* of `r[i,d] · r_mkt[d]` | Realized covariance, descriptive |

**On beta versus correlation — the decomposition that stops the paper overstating.** `beta = rho · (sigma_i / sigma_mkt)`. Bitcoin's daily volatility runs roughly three to five times the market's, so beta is roughly three to five times rho, and a small correlation change produces a large-looking beta change. Bitcoin's own volatility also *fell* over the sample, which means a beta outcome mixes the object of interest with a volatility trend. The panel carries both legs separately so that decomposing the beta change into a correlation change and a relative-volatility change is a filter, not a rebuild. Any beta number quoted in the paper must be quoted next to its correlation.

### 3.3 Treatment

`d_etf_listed[i,m] = 1{i == BTC} × 1{m >= 2024m2}` in the headline. Variants built in parallel: `d_post_listing_raw` (from 2024m1, no donut), `d_post_etf` (time-only, no coin interaction — descriptive, and must be labelled as such in every table that reports it), `d_anticipation` (2023m8–2024m1). `event_k[i,m]` is months relative to `T_i`, binned at ±24, reference *k* = −1.

On the pre-trend test: with 31 monthly pre-observations, failing to reject a joint F-test on *k* = −24…−2 is weak evidence. The text should quote the Rambachan–Roth breakdown value, not the pre-trend p-value.

### 3.4 Macro controls

FRED is unavailable, so every macro series runs on a verified yfinance substitute.

| Concept | FRED series (blocked) | Substitute used | Note |
|---|---|---|---|
| Equity volatility | VIXCLS | `^VIX` | Same underlying index |
| Rate volatility | — | `^MOVE` | |
| Dollar index | DTWEXBGS | `DX-Y.NYB` | ICE DXY, not the Fed's broad trade-weighted index — a narrower basket. Not interchangeable; state the substitution |
| 10y nominal yield | DGS10 | `^TNX` | **Scale trap:** `^TNX` is quoted at 10× the yield. Asserted to lie in (0, 20) after division |
| 10y TIPS real yield | DFII10 | **none** | **Dropped** |
| 10y breakeven | T10YIE | **none** | **Dropped** |

The headline specification takes no controls, so the two dropped series cost two rows in the descriptive table and do not touch the main estimate.

---

## 4. ETF price, volume and the GBTC discount

Ten of the eleven spot funds are retrievable on the price side, each with a first bar on 2024-01-11.

**DEFI (Hashdex) is missing from the price panel and is not substituted.** yfinance returns no data for its listing window; the fund was a conversion of an existing futures product and has been renamed and reticketed since. Its AUM is a rounding error in the aggregate. Any aggregate reported here covers **10 of 11 funds**, and the paper must say so rather than silently implying full coverage.

**The ETF series are one-sided by construction, and this is not a data defect.** Ten of the eleven funds did not exist before 2024-01-11. There is no pre-period for them and there cannot be one. Consequently:

- Pre-listing rows are **absent, not zero**. Zero-padding a fund's history back to 2021 would manufacture a mechanical jump at 2024-01-11 in any aggregate — a jump that is pure construction and would then be read as the treatment effect. This is asserted at build time (`qa_08`).
- No pre/post comparison is made on any ETF-level series. They are descriptive and dose-response inputs only.
- GBTC is the sole exception with genuine pre-history: it traded OTC as a closed-end trust from 2015 and converted to a NYSE Arca-listed ETF on 2024-01-11. Its pre-2024 price series is what generates the premium/discount variable.

**The GBTC discount path.** The object of interest is `(P_GBTC / NAV_per_share) − 1`. NAV per share requires the trust's daily BTC-per-share holdings, which no configured source serves. What *is* constructible from prices alone is the GBTC price path normalized against BTC's own path — which traces the *shape* of the discount's collapse (the well-documented move from a deep double-digit discount in 2022–23 to approximate parity after conversion) without recovering its level. **The figure therefore plots a price-ratio-based discount proxy, not the true NAV discount, and is labelled as such.** A level claim about the discount requires the issuer's daily holdings disclosure.

---

## 5. The raw pre/post contrast

This is reported *before* estimation so the difference-in-differences contrast is visible without trusting any model. All figures are on the UTC clock, using the donut windows (clean pre 2021-01 → 2023-07; post 2024-02 → 2026-08), with the no-donut variant reported alongside.

Realized values are in §7 and in `summary_statistics.json` under `raw_contrast`. The quantities are:

- Δρ(BTC, SPY) = mean ρ_m over post − mean ρ_m over clean pre
- Δβ(BTC, SPY) — same, on betas
- The same two quantities for MKT-RF as the market leg
- The same four quantities for the never-treated control coins, individually and pooled
- **The DiD contrast:** Δρ(BTC) − Δρ(controls), which is the headline estimand computed by hand, with no fixed effects and no standard errors

A note on how to read that hand-computed contrast: it is the raw difference of period means, so it is not the regression estimand — the regression's two-way fixed effects reweight coin-months differently, and the standard errors cluster on coin. If the hand-computed contrast and the regression coefficient disagree in *sign*, that is a build error to be chased, not a modelling subtlety. If they differ in magnitude, that is expected.

---

## 6. Data gaps, stated without varnish

**G1 — Hourly crypto history before ~2024-09-12 (severity: high).** Blocks the declared baseline clock `r_ec`, the entire session decomposition, and the session triple-difference — which is the paper's strongest attribution test. What still works: the full coin-month panel on the UTC clock, the event studies, the break tests, the synthetic control, and the weekend-margin test, which recovers part of the intraday design's logic from daily data alone. **What must not be done:** present a post-period-only session panel as a difference-in-differences. Without a pre-period there is nothing to difference. Cheapest fixes: Binance public klines REST (free, no key, hourly back to 2017) for the crypto leg; CoinMetrics community reference rate for the best provenance story. The equity leg of the session covariance needs CME E-mini intraday, for which there is no free path — and SPY is *not* a substitute, because SPY trades 09:30–16:00 ET and cannot price the Asian or European sessions, which is exactly where the triple-difference's identifying contrast lives. Substituting SPY would turn the DDD into a tautology.

**G2 — ETF net flows (severity: medium).** No configured source serves creations/redemptions, shares outstanding, NAV or coins held. This blocks design D3, the basis-versus-allocation flow decomposition, the true GBTC NAV discount, and aggregate AUM. **What must not be done:** use dollar volume (price × volume) as a proxy for net flow. It is a gross turnover measure. A day of heavy two-sided trading with zero net creation produces a large value; a day of large one-sided creation on thin secondary volume produces a small one. Using it in a dose-response would answer a different question while appearing to answer this one. This build therefore reports the aggregate series under the name `etf_turnover_usd` and never as flow. Fix: Farside Investors' daily fund-by-fund table (the de facto standard series in this literature) or the issuers' own daily disclosure pages (the primary-source version, and the one to prefer for publication).

**G3 — Allium unconfigured (severity: medium).** Removes on-chain and CEX price data, hence any path to tick-level or cross-venue validation. The crypto leg is single-source. The headline monthly correlation is robust to venue choice at daily frequency, so this is not fatal, but the cross-venue validation row in the robustness table cannot be produced.

**G4 — FRED unconfigured (severity: low).** Costs the 10y TIPS real yield and the 10y breakeven; everything else has a verified substitute. A free key takes about thirty seconds to obtain.

**G5 — SOL and XRP listing dates unverified (severity: medium, silent-failure risk).** Stored as `null`. Blocks the staggered multi-cohort extension. Does not block the headline.

**G6 — DEFI (Hashdex) absent from the price panel.** Aggregates cover 10 of 11 spot funds.

**G7 — Factor publication lag.** The Ken French daily files trail the current date by roughly a month, so the factor panel ends before the price panel does. Factor-based specifications are **truncated to the common window**, never padded. The realized end dates of both panels are in §7.

**G8 — Sample-period truncation and post-period composition.** The post-period runs 2024-02 → 2026-08, 31 months. It contains two large Bitcoin-specific shocks that the cross-coin DiD cannot difference out: the April-2024 halving and the November-2024 US general election, the latter disproportionately a Bitcoin story. The pre-committed attributable estimate uses the pre-election sub-window; the pre-halving sub-window is reported alongside. A referee should read the full-post-period number as an upper bound on what is attributable to the ETF.

**G9 — One treated unit.** Not a data gap, but it determines the panel's shape: inference rests on a placebo grid over every coin × every candidate month, so the panel is built over the full asset set and the full window with no pre-filtering on treatment status.

---

## 7. Realized build

*This section is populated from the executed build. Every number here appears in `summary_statistics.json` under a traceable key.*

### 7.1 Sample flow

> Source: `summary_statistics.json#sample_flow`

| # | Step | N remaining | Dropped |
|---|---|---:|---:|
| 1 | Raw crypto daily bars retrieved (13 assets, 2020-12-01 → 2026-09-11) | 27,430 | 0 |
| 2 | Restrict to the primary window 2021-01-01 → 2026-08-31 | 26,897 | 533 |
| 3 | Drop missing / non-positive closes | 26,897 | 0 |
| 4 | First observation per asset lost to differencing | 26,884 | 13 |
| 5 | Restrict to NYSE trading sessions (crypto off-days kept separately) | 18,473 | 8,411 |
| 6 | Require the equity leg present on the same session | 18,473 | 0 |
| 7 | Aggregate to coin-months, SPY leg *(unit changes: coin-day → coin-month)* | 1,072 | — |
| 8 | Drop coin-months with fewer than 15 usable sessions | 1,072 | 0 |
| 9 | Headline filter: cohort ∈ {treated_btc, never_treated} | 670 | 402 |
| 10 | Drop the donut window 2023m8–2024m1 | 610 | 60 |
| 11 | **Final estimation sample** | **610** | 0 |

Reading the table. Step 2's 533 dropped rows are the December-2020 bars pulled to give January-2021 a clean first return — they are used, not discarded, but they sit outside the sample window. Step 3 dropped nothing: **no crypto bar in the window had a missing or non-positive close**, so there is no imputation question to answer and no missingness to model. Step 5's 8,411 rows are crypto returns on days the NYSE was closed — weekends and US holidays. They are not deleted; they are written to `data/crypto_offday_returns.csv` and are the input to the weekend-margin test, which is the one piece of the intraday design's logic that survives without hourly data. Step 8 dropped nothing: every coin-month in the window has at least 19 usable sessions (mean 20.9, min 19), so the `n_days_m >= 15` rule never bound.

Step 7 changes the unit of observation, so "dropped" is not defined there; the 1,072 figure is 16 series (13 coins + the altcoin index + gold + silver) × 67 months. Step 9 removes the eventually-treated coins (ETH, SOL, XRP), the composite altcoin index, and the two precious-metal placebos from the estimation sample — they are retained in the full panel file and used as placebos and benchmarks, just never as DiD control units.

**Missing-value handling, realized:** zero imputations, zero forward-fills, zero winsorized values in the headline. Crypto coin-day coverage on NYSE sessions is 18,473 of 18,473 expected — **0.00% missing**. The only unmatched join in the build is 21 NYSE sessions in August 2026 that have no Ken French factor row (§7.4).

### 7.2 Coverage and panel dimensions

| Quantity | Value | Key |
|---|---:|---|
| NYSE sessions, 2021-01-04 → 2026-08-31 | 1,421 | `n_nyse_sessions` |
| Coin-day return observations (NYSE sessions, both legs present) | 18,473 | `n_daily_observations_crypto` |
| Crypto off-session returns retained for the weekend test | 8,411 | — |
| **Coin-month cells in the headline estimation sample** | **610** | `n_observations` |
| Coins in the headline sample (BTC + 9 never-treated) | 10 | `n_units` |
| Months in the headline sample | 61 | `n_periods` |
| Estimation panel span | 2021-01 → **2026-07** | `estimation_panel_coverage` |
| Price panel span | 2021-01 → 2026-08 | `estimation_panel_coverage.price_panel_end_month_iso` |
| Months lost to the factor publication lag | 1 | `estimation_panel_coverage.months_lost_to_factor_publication_lag` |
| Ken French daily factors | 1963-07-01 → 2026-07-31 | — |

**On the one-month truncation.** The estimation panel ends 2026-07, a month before the price panel. Every cell needs the daily risk-free rate for its excess-return leg, and the Ken French daily files trail the extract date by about a month. August 2026 is therefore **truncated, not padded** — carrying prices forward with a stale or zero `rf` would have silently manufactured a final month. The headline sample is 10 coins × 61 months = 610 cells, exactly balanced.

**Descriptives of the estimation sample** (headline filter: BTC + 9 never-treated coins, non-donut, SPY leg):

| Variable | Mean | SD | Min | p25 | Median | p75 | Max |
|---|---:|---:|---:|---:|---:|---:|---:|
| `y_fisherz_corr_equity` (primary outcome) | 0.3935 | 0.2957 | −0.4338 | 0.2166 | 0.3960 | 0.5870 | 1.2017 |
| `rho_m` | 0.3507 | 0.2474 | −0.4085 | 0.2132 | 0.3765 | 0.5277 | 0.8342 |
| `rho2_m` | 0.1841 | 0.1547 | 0.0000 | 0.0608 | 0.1424 | 0.2785 | 0.6958 |
| `beta_m` | 1.6926 | 1.8075 | −8.3473 | 0.8417 | 1.6090 | 2.4332 | 10.8353 |
| `ln_sigma_ratio_m` | 1.5455 | 0.5763 | −0.6147 | 1.1564 | 1.5142 | 1.9052 | 3.5299 |
| `n_days_m` | 20.87 | 1.18 | 19 | 20 | 21 | 22 | 23 |

Two things in that table deserve comment rather than a caption.

`rho2_m` averages 0.18. Across the whole panel, equity-market returns account for roughly **18% of the daily variance** of a crypto asset. Whatever the paper finds, the object being moved is a minority share of a very volatile series, and every correlation quoted in the paper should be printed beside its square for exactly this reason.

`beta_m` ranges from −8.3 to +10.8. That is not a data error; it is what an OLS slope estimated on ~21 observations does when the regressor's within-month variance is small. `ln_sigma_ratio_m` averages 1.55, so crypto's daily volatility runs about **e^1.55 ≈ 4.7×** the market's, which is why the betas are large and noisy relative to the correlations. This is the concrete reason the Fisher-z correlation is the primary outcome and beta is secondary: the correlation has a known, coin-invariant sampling variance, and the monthly beta does not.

**By group** (headline sample, non-donut, SPY leg):

| Group | Cells | Coins | Mean Fisher-z | SD | Mean ρ | Mean β |
|---|---:|---:|---:|---:|---:|---:|
| Treated (BTC) | 61 | 1 | 0.4392 | 0.2982 | 0.3867 | 1.2737 |
| Never-treated controls | 549 | 9 | 0.3885 | 0.2952 | 0.3467 | 1.7392 |

Bitcoin sits slightly *above* the controls in correlation and well *below* them in beta throughout — the beta gap is a volatility-ratio gap, not a co-movement gap, and it is present in the pre-period too.

**Full-sample daily return moments** (1,421 NYSE sessions): BTC mean 0.0306% per day, SD 3.34%, range [−17.41%, +17.18%]. SPY mean 0.0558%, SD 1.05%, range [−6.03%, +9.99%]. VIX mean 19.25, SD 5.12, max 52.33.

### 7.3 Raw pre/post contrast

> Source: `summary_statistics.json#raw_contrast`

Clean pre = 2021m1–2023m7 (31 months). Post = 2024m2–2026m7 (30 months). Donut excluded. UTC clock.

#### Bitcoin against SPY

| Statistic | Pre | Post | Change |
|---|---:|---:|---:|
| Mean monthly ρ | 0.3822 | 0.3914 | **+0.0092** |
| Mean monthly β | 1.2327 | 1.3160 | **+0.0832** |
| Mean monthly Fisher-z | 0.4322 | 0.4464 | +0.0142 |
| Pooled-daily ρ (647 / 626 days) | 0.4105 | 0.3923 | **−0.0182** |
| Pooled-daily β | 1.4028 | 1.0822 | **−0.3207** |

#### Never-treated control coins against SPY (9 coins)

| Statistic | Pre | Post | Change |
|---|---:|---:|---:|
| Mean monthly ρ | 0.3415 | 0.3520 | **+0.0105** |
| Mean monthly β | 1.6583 | 1.8228 | **+0.1645** |
| Pooled-daily ρ | — | — | +0.0245 |
| Pooled-daily β | — | — | −0.2910 |

Per coin, change in mean monthly ρ (and β) against SPY: LTC −0.0014 (+0.056) · BNB −0.0055 (−0.233) · ADA −0.0175 (+0.057) · DOGE +0.0181 (+0.203) · BCH +0.0198 (+0.423) · LINK +0.0614 (+0.675) · AVAX +0.0751 (+0.591) · DOT −0.0337 (−0.088) · XLM −0.0217 (−0.204). Four of nine controls fell; the dispersion across controls (−0.034 to +0.075) is roughly eight times the size of Bitcoin's own change.

#### The raw difference-in-differences

| Contrast | SPY leg | MKT-RF leg |
|---|---:|---:|
| Δρ(BTC) − Δρ(controls) | **−0.0014** | **−0.0040** |
| Δβ(BTC) − Δβ(controls) | **−0.0813** | **−0.1110** |
| ΔFisher-z(BTC) − ΔFisher-z(controls) | −0.0088 | −0.0104 |
| Δρ, pooled-daily | −0.0428 | −0.0432 |
| Δβ, pooled-daily | −0.0296 | −0.0396 |

Against the Ken French market factor the levels shift slightly and the story does not: BTC ρ 0.4002 → 0.4074 (+0.0072), β 1.2186 → 1.3105 (+0.0919); controls +0.0112 and +0.2029.

#### What this says, before any estimation

**The raw DiD contrast is approximately zero and, if anything, slightly negative.** Bitcoin's correlation with US equities did rise across the approval — by about one correlation point on the monthly measure — but the never-treated control coins rose by slightly more. On the beta measure the gap is wider in the same direction: the controls' equity beta rose about twice as much as Bitcoin's. Every one of the five contrasts above is negative. Under the paper's own pre-registered design, that is the DiD reading: **no differential increase in Bitcoin's equity co-movement attributable to the ETF listing.**

Three observations that the estimation stage should carry forward.

**The placebo moved more than the treated unit.** Gold's correlation with SPY rose from 0.1536 to 0.2116 (+0.0581) and silver's from 0.2582 to 0.3040 (+0.0458) over the same windows — both increases an order of magnitude larger than Bitcoin's +0.0092. Gold was specified in advance as the macro-neutrality falsification: a January-2024 break in gold's equity correlation falsifies the claim that the post-period differs from the pre-period only through the ETF. Gold did break, in the same direction and by more. The honest reading is that the whole alternative-asset complex saw its equity correlation rise over 2024–2026, and that this common movement — not the ETF — is what a single-series pre/post comparison on Bitcoin would have picked up. This is the strongest argument in the data for why the cross-coin difference, rather than a Bitcoin time-series break, has to be the estimand.

**The monthly and pooled-daily aggregations disagree in sign for Bitcoin alone — and this is not a build error.** Bitcoin's mean *within-month* correlation rose (+0.0092) while its *pooled-daily* correlation over the whole pre and post windows fell (−0.0182). The two measure different objects. The pooled-daily statistic includes co-movement in monthly *means* — chiefly the joint equity/crypto drawdown of 2022 — which the monthly blocks strip out by construction. The pre-period gap between the two (0.4105 pooled vs 0.3822 average within-month) is exactly that low-frequency component; in the post-period the two nearly coincide (0.3923 vs 0.3914), i.e. the low-frequency component largely disappeared. **The estimation outcome is the within-month correlation and therefore deliberately excludes low-frequency co-movement.** The paper must not describe it as "the correlation between Bitcoin and equities" without that qualifier. Note that the *contrast* — the DiD — is negative under both aggregations, so the disagreement is about Bitcoin's own level path, not about the treatment comparison.

**Bitcoin's equity beta fell on the pooled-daily measure while rising on the monthly measure, and the decomposition explains it.** β = ρ · (σ_BTC/σ_MKT), and Bitcoin's volatility fell relative to equities over the sample. `ln_sigma_ratio_m` is carried in the panel precisely so this can be split rather than argued about. Any beta result in the paper needs its correlation and volatility-ratio legs shown beside it.

None of this is the estimate. These are unconditional differences of period means with no fixed effects, no clustering and no inference — the two-way fixed-effects specification reweights coin-months differently and clusters on coin, so magnitudes will move. What the estimation stage should treat as a red flag is a **sign** reversal: if the regression returns a positive, significant differential effect where all five raw contrasts are negative, the discrepancy needs to be explained by the specification, not asserted.

### 7.4 Build exceptions actually encountered

Four, all logged by the build script rather than patched.

**E1 — Factor publication lag (`qa_03`).** 21 of 1,421 NYSE sessions — all of August 2026 — have no Ken French factor row. The estimation panel is truncated to 2026-07 rather than padded. Cost: one month, and it applies to the SPY leg too, because every cell needs `rf` for its excess-return leg.

**E2 — DEFI (Hashdex) absent.** The yfinance extract returns 16 bars for the ticker `DEFI`, all between 2026-07-17 and 2026-08-24, on volumes of a few hundred shares. This is not the Hashdex fund's January-2024 listing history; the fund was a conversion of an existing futures product and has been renamed and reticketed since. No substitute was inserted. **Every ETF aggregate in this build covers 10 of the 11 spot funds.**

**E3 — The GBTC discount is a proxy, not a measurement.** See §4. The series is the GBTC/BTC price ratio normalised on the 2024H2 near-NAV window. Realized path: mean −28.5% across 2022, −27.4% across 2023, trough **−47.1% on 2022-12-13**, −1.5% on 2024-01-10, mean −1.0% after conversion, −2.5% at the end of the sample. The *shape* — a deep discount through the 2022–23 trust era closing essentially to parity at conversion — is well identified and matches the published record. The *level* is anchored, not measured, and the pre-2024 values additionally absorb cumulative sponsor-fee drag of roughly 1.5%/year. A level claim requires the issuer's daily BTC-per-share disclosure.

**E4 — Estimation panel ends before the price panel.** Stated in E1; logged separately because it changes the sample period a reader would otherwise infer from the extract date.

**QA checks that passed:** `qa_05` (10y yield in range; `^TNX` was already in percent in this extract, so the 10× divisor did not apply — the assertion is retained because the convention has changed before), `qa_08` (no spot-ETF bar exists before 2024-01-11, so pre-listing rows are absent rather than zero-padded), `qa_10` (no eventually-treated unit appears in the headline sample), `qa_06` (no cell tripped |ρ| ≥ 0.999), `qa_07` (no coin-month fell below 15 sessions).

**QA checks that could not be run:** `qa_02` and `qa_04`, both of which concern the hourly bar-edge convention and the agreement between the two clocks. They require the 16:00 ET series, which does not exist over the pre-period. They must be run before any `_ec` column is used.

### 7.5 ETF series, realized

| Quantity | Value |
|---|---:|
| Spot funds in the price panel | 10 of 11 |
| First bar, all ten | 2024-01-11 |
| Bars per fund (ex-GBTC) | 661 |
| GBTC bars (OTC pre-history + ETF) | 1,421 |
| BITO bars (futures placebo, from 2021-10-20) | 1,220 |
| Cumulative secondary-market turnover, ten funds | **$2,213.7 bn** |
| Cumulative turnover excluding GBTC | $1,874.0 bn |

To repeat the point from §6 because it is the one most likely to be misread downstream: **$2,213.7 bn is cumulative dollar turnover, not net flow.** It is price × share volume summed over funds and days. It says how much secondary-market trading the wrapper generated; it says nothing about how much Bitcoin was bought. The flow dose-response design cannot be run on it, and no table in the paper should label it a flow.

BITO's first retrievable bar is 2021-10-20, one session after its 2021-10-19 launch. The F6 placebo needs day 0; with this extract it starts at day 1. Widening the request window did not recover the launch bar.

### 7.6 Diagnostic figures produced

Specified in `figure_spec.json` with embedded data values; rendered downstream.

| File | Type | Content |
|---|---|---|
| `fig_rolling_btc_spy.pdf` | multi-panel | Rolling 90-day BTC–SPY correlation (A) and beta (B) over the full sample, with the donut window and the 2024-01-10 approval / 2024-01-11 listing marked |
| `fig_rolling_overlay_controls.pdf` | time series | The same correlation for BTC, the never-treated control mean, the equal-weighted altcoin index, and gold as placebo, overlaid |
| `fig_prepost_correlation_change.pdf` | bar | Pre→post change in mean monthly correlation with SPY, BTC and each of the nine controls — the raw DiD contrast, visible in one panel |
| `fig_etf_cumulative_turnover.pdf` | time series | Cumulative secondary-market dollar turnover of the ten spot ETPs, with and without GBTC. **Turnover, not net flow** |
| `fig_gbtc_discount.pdf` | time series | GBTC price-ratio discount proxy, 2021–2026 |

The rolling series in the first two figures carry the MA(89) overlap problem described in §2.1. They are included because the time path is what a reader needs to see, and the captions say what they are. They are not the estimation object and no event-study shape should be read off them.

---

## 8. Handoff to estimation

| Field | Value |
|---|---|
| Estimation panel | `data/coin_month_panel.csv` (2,144 cells over both market legs; 610 in the headline filter) |
| Panel span | 2021m1 – 2026m7, 61 months × 10 coins, balanced |
| Supporting files | `data/daily_returns.csv`, `data/rolling_diagnostics.csv`, `data/crypto_offday_returns.csv` |
| Build script | `build_panel.py` (executed; the frozen extracts in `data/px_*.csv` and `data/etf_*.csv` let it re-run offline) |
| Outcome | `y_fisherz_corr_equity` |
| Secondary outcome | `beta_m`, with `ln_sigma_ratio_m` as the decomposition leg |
| Treatment | `d_etf_listed` |
| Fixed effects | `asset_id`, `year_month` |
| Cluster | `asset_id` |
| Headline filter | `d_in_headline_sample == True AND d_donut == False` |
| Weights | none in the headline; `1/se_fisherz²` as a robustness row (a legitimate GLS weight precisely because `se_fisherz` is known, not estimated) |

**Caveat that must travel with the panel:** `y_fisherz_corr_equity` is computed on the 00:00 UTC clock, not the 16:00 ET clock the design declared as baseline. Every table must say which clock produced it.
