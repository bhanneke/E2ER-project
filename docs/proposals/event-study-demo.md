# Proposal: the first study on `event-study-finance`

Status: proposal, awaiting the maintainer's approval. Nothing has been run with a
model. The counts below come from the data, fetched read-only on 2026-09-28.

## Question

How do US bank stocks respond to changes in the Federal Reserve's target rate?
An event study of FOMC target-rate changes, 2015–2025.

## Data (open connectors only)

| What | Source | Checked |
|---|---|---|
| Target range, upper limit | FRED `DFEDTARU` | 31 changes between 2015-01-01 and 2025-12-31 (20 increases, 11 cuts) |
| Bank stocks | yfinance `KBE` (primary), `XLF` (secondary) | 3,018 trading days, 2014-01-02 to 2025-12-31, no missing closes |
| Market | yfinance `SPY` | same calendar, no missing closes |
| Surprise proxy | FRED `DGS2` (2-year Treasury yield) | present on all 31 event days |

The trading calendar is SPY's. From 2014-01-02 there are enough trading days
before the first event (2015-12-16) for a 250-day estimation window.

## Events and the data problem to fix first

`DFEDTARU` records the date the new target takes effect. For 28 of the 31
changes that is one trading day after the FOMC statement: the statement is
released at 2 p.m. on day t, and FRED dates the change t+1. Using FRED dates as
day 0 would put the announcement at day -1. Day 0 is therefore the statement
date, taken from the Federal Reserve's FOMC calendars (federalreserve.gov) and
matched to each change as the last statement on or before the FRED date. The
two emergency cuts in March 2020 are included; the second was announced on
Sunday 2020-03-15, so its day 0 is Monday 2020-03-16.

Day 0 of the 31 events: 2015-12-16, 2016-12-14, 2017-03-15, 2017-06-14,
2017-12-13, 2018-03-21, 2018-06-13, 2018-09-26, 2018-12-19, 2019-07-31,
2019-09-18, 2019-10-30, 2020-03-03, 2020-03-16, 2022-03-16, 2022-05-04,
2022-06-15, 2022-07-27, 2022-09-21, 2022-11-02, 2022-12-14, 2023-02-01,
2023-03-22, 2023-05-03, 2023-07-26, 2024-09-18, 2024-11-07, 2024-12-18,
2025-09-17, 2025-10-29, 2025-12-10.

The statement dates are not in FRED or yfinance, so they enter the study as a
researcher file (`data/fomc_statement_dates.csv`, the 31 dates above with the
FRED change date next to each); everything else is fetched by the connectors.

## Hypotheses

- H1. The mean cumulative abnormal return of KBE over [-1,+1] around a
  target-rate change differs from zero, estimated separately for increases
  (20 events) and cuts (11 events). Two-sided: higher rates can widen banks'
  interest margins and lower the value of their fixed-rate assets.
- H2. Across the 31 events, the CAR over [-1,+1] is related to the change in the
  2-year Treasury yield on day 0, the part of the decision markets did not
  expect. Two-sided.

Most changes were anticipated, so H1 may well be null; H2 is where the
information is expected to be. A null is reported as a null.

## Design

- Market model, KBE on SPY, estimated by OLS over trading days [-250,-12]
  (239 days). Days inside another event's [-1,+5] window are left out of the
  estimation sample: 28 of the 31 estimation windows contain an earlier event.
- Event windows [-1,+1] and [0,+5].
- `event_design.json` as specified in `skills/files/econometrics/event-study.md`,
  one event per statement date, asset `KBE`, calendar = the SPY price table.

The `event_window` check, run on this design with real data and the template's
defaults (120 days, gap 10, overlap 0), passes: estimation window 239 days, gap
10 days, 0 of 31 events overlapping (the closest pair, 2020-03-03 and
2020-03-16, are 9 trading days apart, so their [-1,+5] windows do not touch).
A first draft with the window ending at -11 failed it (gap 9), which is the
check doing its job.

## Analysis plan

1. CAR per event and window; mean CAR by direction (H1) with the
   Boehmer-Musumeci-Poulsen test and a sign test.
2. OLS of CAR[-1,+1] on the day-0 change in DGS2 (H2), heteroskedasticity-robust
   standard errors.
3. Robustness: XLF instead of KBE; market-adjusted returns; without the three
   crisis events (2020-03-03, 2020-03-16, and 2023-03-22, which falls in the
   March 2023 bank failures); CAR[0,+5].
4. Report N, mean and median CARs, test statistics and both windows for every
   specification, including the ones that do not reject.

## Scope and cost

Two tickers plus one index, three FRED series, 31 events, single-pass run. No
paid data.

## Alternative of the same scope, if the default is judged too thin

All 88 scheduled FOMC statements 2015–2025 (including the meetings
without a change), with the DGS2 change as the surprise. More events and
surprises in both directions, at the cost of a longer researcher-supplied date
file. The default above is feasible as it stands.
