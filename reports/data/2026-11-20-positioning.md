# Positioning data report, snapshot `1746a21b75683e76`

- Created: 2026-11-20T02:49:20Z (UTC), online build
- Command: `uv run python -m lab.data.build --sources kraken,binance,coinbase,binance_futures --coins BTC,ETH --intervals 1d,1h --tolerance 0.01`
- Code: commit `f8d4208ebb9b11036bd51701e44cd0ff7407b441`, lab/ with uncommitted changes: yes
- Bars of this snapshot and their checks: `2026-11-20-1746a21b75683e76.md`
- Load with `lab.data.external.load_positioning(symbol, freq, start, end)`: one row per bar close, only values known before it, never past the validate window.

## 1. Files and what was verified

Every zip's SHA-256 matched its published `.CHECKSUM`; files were requested up to 2024-06-30 (the validate window's last day) and no later. Status: {'verified on disk': 2527}. Missing: none.

| Series | First file | Last file | Files asked for | Period before the first (online check) |
|---|---|---|---|---|
| BTCUSDT funding | 2020-01 | 2024-06 | 54 | 2019-12: not published (404) |
| BTCUSDT metrics | 2020-09-01 | 2024-06-30 | 1399 | 2020-08-31: not published (404) |
| BTCUSDT klines_5m | 2020-09 | 2024-06 | 46 | n/a |
| ETHUSDT funding | 2020-01 | 2024-06 | 54 | 2019-12: not published (404) |
| ETHUSDT metrics | 2021-12-01 | 2024-06-30 | 943 | 2021-11-30: not published (404) |
| ETHUSDT klines_5m | 2021-12 | 2024-06 | 31 | n/a |

## 2. Stored series

`ts` is the source's timestamp, `known_at` when the value became public (section 3). Missing = funding events or 5-minute rows absent between the first and the last (never filled).

| Series | Rows | First ts | Last ts | Last known_at | Gaps | Missing | File |
|---|---|---|---|---|---|---|---|
| BTCUSDT funding | 4929 | 2020-01-01T00:00:00+00:00 | 2024-06-30T16:00:00+00:00 | 2024-06-30T16:00:00+00:00 | 0 | 0 | ext/binance_futures/BTCUSDT/funding.parquet |
| BTCUSDT metrics | 402282 | 2020-09-01T00:00:00+00:00 | 2024-06-30T23:50:00+00:00 | 2024-06-30T23:55:00+00:00 | 154 | 629 | ext/binance_futures/BTCUSDT/metrics.parquet |
| ETHUSDT funding | 4929 | 2020-01-01T00:00:00+00:00 | 2024-06-30T16:00:00+00:00 | 2024-06-30T16:00:00+00:00 | 0 | 0 | ext/binance_futures/ETHUSDT/funding.parquet |
| ETHUSDT metrics | 271448 | 2021-12-01T00:00:00+00:00 | 2024-06-30T23:50:00+00:00 | 2024-06-30T23:55:00+00:00 | 8 | 135 | ext/binance_futures/ETHUSDT/metrics.parquet |

Daily bar closes of each split window that get a value from `external.positioning_at` (first such close in brackets). The test window is not stored.

| Symbol | Window | Daily closes | funding_last | funding_mean_7d | oi_last | oi_change_7d | ls_account_last | ls_top_position_last |
|---|---|---|---|---|---|---|---|---|
| BTCUSDT | train | 2191 | 1096 (2020-01-02) | 1090 (2020-01-08) | 849 (2020-09-02) | 839 (2020-09-09) | 830 (2020-09-02) | 531 (2020-09-02) |
| BTCUSDT | validate | 547 | 547 (2023-01-02) | 547 (2023-01-02) | 546 (2023-01-02) | 545 (2023-01-02) | 546 (2023-01-02) | 546 (2023-01-02) |
| ETHUSDT | train | 2191 | 1096 (2020-01-02) | 1090 (2020-01-08) | 395 (2021-12-02) | 387 (2021-12-09) | 376 (2021-12-02) | 77 (2021-12-02) |
| ETHUSDT | validate | 547 | 547 (2023-01-02) | 547 (2023-01-02) | 546 (2023-01-02) | 545 (2023-01-02) | 546 (2023-01-02) | 546 (2023-01-02) |

## 3. When a value is known (point in time)

Only values known strictly before a bar's close are used for that bar; stored values are all known before 2024-07-01T00:00:00+00:00 (only values known strictly before the close of the last validate bar (config/splits.yaml)).

- `known_at`: funding: calc_time; metrics: create_time + 5 min (create_time is the start of the 5-minute period in the newer files, its end in the older ones; checked per day, SNAPSHOT.json checks.metrics_timing)
- `row_at_close_t`: only values with known_at < t
- `funding_last`: newest rate, NaN if older than its interval + 5 min
- `funding_mean_kd`: mean of the rates known in [t - k days, t), NaN unless their intervals cover k x 24 hours
- `metrics_last`: newest valid value, NaN if older than 1 h
- `oi_change_kd`: oi_last(t) / oi_last(t - k days) - 1

Timestamp check of the metrics against 5-minute futures klines, per UTC day: which kline period the row's taker buy/sell ratio equals, and which moment's price its open-interest value / open interest equals. Data reach = how far past T a day's data go; the known_at lag is 5 min, and the build stops if any day reaches further.

| Symbol | From | To | Days | Taker ratio matches | OI value / OI matches | Data reach |
|---|---|---|---|---|---|---|
| BTCUSDT | 2020-09-01 | 2021-12-30 | 486 | period ending at T | price at T | T+0 min |
| BTCUSDT | 2021-12-31 | 2022-01-29 | 30 | inconclusive | price at T | T+0 min |
| BTCUSDT | 2022-01-30 | 2022-01-30 | 1 | period ending at T | price at T | T+0 min |
| BTCUSDT | 2022-01-31 | 2022-05-08 | 98 | inconclusive | price at T | T+0 min |
| BTCUSDT | 2022-05-09 | 2024-04-25 | 718 | period ending at T | price at T | T+0 min |
| BTCUSDT | 2024-04-26 | 2024-06-30 | 66 | period starting at T | price at T+5 min | T+5 min |
| ETHUSDT | 2021-12-01 | 2021-12-30 | 30 | period ending at T | price at T | T+0 min |
| ETHUSDT | 2021-12-31 | 2022-01-29 | 30 | inconclusive | price at T | T+0 min |
| ETHUSDT | 2022-01-30 | 2022-01-30 | 1 | period ending at T | price at T | T+0 min |
| ETHUSDT | 2022-01-31 | 2022-05-08 | 98 | inconclusive | price at T | T+0 min |
| ETHUSDT | 2022-05-09 | 2024-04-25 | 718 | period ending at T | price at T | T+0 min |
| ETHUSDT | 2024-04-26 | 2024-06-30 | 66 | period starting at T | price at T+5 min | T+5 min |

Days with no conclusive check: BTCUSDT 0, ETHUSDT 0; furthest reach: BTCUSDT 5 min, ETHUSDT 5 min.

## 4. Loading and cleaning

Bad rows dropped; duplicates keep the last row; values that are empty or not positive (e.g. `0E-8`) become NaN; a value unchanged for 1 h or more becomes NaN from that moment on (frozen feed; the run's earlier rows are kept, as they could not be known to be frozen at their time). Nothing is filled.

| Series | Files | Rows read | Bad dropped | Exact duplicates | Conflicting duplicates | Files out of time order | Rows outside the file's period | Known at/after the cut |
|---|---|---|---|---|---|---|---|---|
| BTCUSDT funding | 54 | 4929 | 0 | 0 | 0 | 0 | 0 | 0 |
| BTCUSDT metrics | 1399 | 477538 | 0 | 75255 | 0 | 59 | 0 | 1 |
| ETHUSDT funding | 54 | 4929 | 0 | 0 | 0 | 0 | 0 | 0 |
| ETHUSDT metrics | 943 | 271449 | 0 | 0 | 0 | 60 | 0 | 1 |

| Symbol | Field | Rows with a value | Empty | Not positive | Stale (frozen) | Longest stretch without a value |
|---|---|---|---|---|---|---|
| BTCUSDT | open_interest | 401905 | 0 | 143 | 234 | 2021-05-21T12:45:00+00:00 -> 2021-05-22T05:10:00+00:00 (194 rows) |
| BTCUSDT | open_interest_value | 401893 | 0 | 155 | 0 | 2021-05-21T12:45:00+00:00 -> 2021-05-22T05:10:00+00:00 (194 rows) |
| BTCUSDT | top_account_ls_ratio | 309895 | 92166 | 0 | 222 | 2022-09-03T08:50:00+00:00 -> 2022-12-14T15:30:00+00:00 (29457 rows) |
| BTCUSDT | top_position_ls_ratio | 309894 | 92167 | 0 | 222 | 2022-09-03T08:50:00+00:00 -> 2022-12-14T15:30:00+00:00 (29457 rows) |
| BTCUSDT | account_ls_ratio | 396277 | 5771 | 0 | 234 | 2021-12-30T14:35:00+00:00 -> 2022-01-19T13:15:00+00:00 (5744 rows) |
| BTCUSDT | taker_buy_sell_ratio | 365010 | 37290 | 2 | 0 | 2022-01-31T00:00:00+00:00 -> 2022-05-09T05:05:00+00:00 (28286 rows) |
| ETHUSDT | open_interest | 271315 | 0 | 133 | 0 | 2022-03-07T15:30:00+00:00 -> 2022-03-08T01:05:00+00:00 (116 rows) |
| ETHUSDT | open_interest_value | 271305 | 0 | 143 | 0 | 2022-03-07T15:30:00+00:00 -> 2022-03-08T01:05:00+00:00 (116 rows) |
| ETHUSDT | top_account_ls_ratio | 179293 | 92155 | 0 | 0 | 2022-09-03T08:50:00+00:00 -> 2022-12-14T15:30:00+00:00 (29457 rows) |
| ETHUSDT | top_position_ls_ratio | 179293 | 92155 | 0 | 0 | 2022-09-03T08:50:00+00:00 -> 2022-12-14T15:30:00+00:00 (29457 rows) |
| ETHUSDT | account_ls_ratio | 265687 | 5761 | 0 | 0 | 2021-12-30T14:35:00+00:00 -> 2022-01-19T13:15:00+00:00 (5744 rows) |
| ETHUSDT | taker_buy_sell_ratio | 234198 | 37247 | 3 | 0 | 2022-01-31T00:00:00+00:00 -> 2022-05-09T05:05:00+00:00 (28286 rows) |

- BTCUSDT: 14 stale runs; longest: open_interest 2021-05-21T12:45:00+00:00 -> 2021-05-22T04:20:00+00:00 (184 rows), account_ls_ratio 2021-05-21T12:45:00+00:00 -> 2021-05-22T04:20:00+00:00 (184 rows), top_account_ls_ratio 2021-05-21T12:45:00+00:00 -> 2021-05-22T00:10:00+00:00 (134 rows), top_position_ls_ratio 2021-05-21T12:45:00+00:00 -> 2021-05-22T00:10:00+00:00 (134 rows), open_interest 2021-04-27T07:50:00+00:00 -> 2021-04-27T11:05:00+00:00 (40 rows), top_account_ls_ratio 2021-04-27T07:50:00+00:00 -> 2021-04-27T11:05:00+00:00 (40 rows), top_position_ls_ratio 2021-04-27T07:50:00+00:00 -> 2021-04-27T11:05:00+00:00 (40 rows), account_ls_ratio 2021-04-27T07:50:00+00:00 -> 2021-04-27T11:05:00+00:00 (40 rows) ... (+6 more in SNAPSHOT.json); open-interest value without open interest: 234
- ETHUSDT: 0 stale runs; longest: none; open-interest value without open interest: 0

## 5. Gaps and values

- `BTCUSDT funding`: 0 gaps (0 events missing): none. Intervals (hours: events) {'8': 4929}; instants 0..47 ms from the interval grid (0 over 1 min). Rate min -0.003, p1 -0.000215148, median 0.0001, p99 0.00119989, max 0.003; largest: 2020-02-12T00:00:00+00:00 +0.003, 2020-03-13T08:00:00+00:00 -0.003, 2021-02-08T16:00:00+00:00 +0.00248993, 2021-01-04T08:00:00+00:00 +0.00236482, 2021-01-08T00:00:00+00:00 +0.00213517
- `BTCUSDT metrics`: 402282 of 402911 5-minute rows, 0 off the grid; 154 gaps (629 rows missing), 70 of 1399 days short of 288 rows (0 empty; the last day also lacks any row known only at or after the cut). Longest gaps: 2024-02-16T13:30:00+00:00 -> 2024-02-17T00:00:00+00:00 (125), 2021-02-19T20:00:00+00:00 -> 2021-02-20T01:20:00+00:00 (63), 2021-06-22T18:25:00+00:00 -> 2021-06-22T22:50:00+00:00 (52), 2021-06-22T00:20:00+00:00 -> 2021-06-22T03:30:00+00:00 (37), 2021-04-27T11:05:00+00:00 -> 2021-04-27T13:40:00+00:00 (30), 2021-06-22T12:45:00+00:00 -> 2021-06-22T14:30:00+00:00 (20), 2021-01-20T00:45:00+00:00 -> 2021-01-20T02:15:00+00:00 (17), 2021-02-19T00:30:00+00:00 -> 2021-02-19T01:35:00+00:00 (12), 2021-06-23T02:10:00+00:00 -> 2021-06-23T03:15:00+00:00 (12), 2020-11-15T03:10:00+00:00 -> 2020-11-15T04:10:00+00:00 (11). Largest 5-minute open-interest moves |log change| (kept: no causal rule tells a recovering feed from a real move): 2021-05-22T05:25:00+00:00 (0.856183), 2021-05-22T05:30:00+00:00 (0.541182), 2021-05-22T05:20:00+00:00 (0.464911), 2021-05-22T05:35:00+00:00 (0.370249), 2020-11-26T03:35:00+00:00 (0.136115). Longest unchanged open interest left after the stale rule: 12 rows, 2021-04-27T06:50:00+00:00 -> 2021-04-27T07:45:00+00:00
- `ETHUSDT funding`: 0 gaps (0 events missing): none. Intervals (hours: events) {'8': 4929}; instants 0..47 ms from the interval grid (0 over 1 min). Rate min -0.00356332, p1 -0.000185494, median 0.0001, p99 0.00156434, max 0.00375; largest: 2021-01-04T08:00:00+00:00 +0.00375, 2020-02-12T08:00:00.001000+00:00 +0.0036719, 2021-05-19T16:00:00.018000+00:00 -0.00356332, 2021-01-10T00:00:00+00:00 +0.00340522, 2022-09-15T00:00:00.019000+00:00 -0.00301937
- `ETHUSDT metrics`: 271448 of 271583 5-minute rows, 0 off the grid; 8 gaps (135 rows missing), 8 of 943 days short of 288 rows (0 empty; the last day also lacks any row known only at or after the cut). Longest gaps: 2024-02-16T13:30:00+00:00 -> 2024-02-17T00:00:00+00:00 (125), 2023-09-12T08:35:00+00:00 -> 2023-09-12T08:55:00+00:00 (3), 2021-12-04T05:20:00+00:00 -> 2021-12-04T05:35:00+00:00 (2), 2021-12-04T04:55:00+00:00 -> 2021-12-04T05:05:00+00:00 (1), 2021-12-15T19:00:00+00:00 -> 2021-12-15T19:10:00+00:00 (1), 2021-12-24T15:00:00+00:00 -> 2021-12-24T15:10:00+00:00 (1), 2021-12-29T23:20:00+00:00 -> 2021-12-29T23:30:00+00:00 (1), 2021-12-31T16:00:00+00:00 -> 2021-12-31T16:10:00+00:00 (1). Largest 5-minute open-interest moves |log change| (kept: no causal rule tells a recovering feed from a real move): 2023-06-14T20:10:00+00:00 (0.065718), 2023-03-12T17:30:00+00:00 (0.065422), 2021-12-04T05:35:00+00:00 (0.065056), 2023-08-17T21:45:00+00:00 (0.059743), 2023-01-14T00:40:00+00:00 (0.057329). Longest unchanged open interest left after the stale rule: 8 rows, 2022-05-28T16:40:00+00:00 -> 2022-05-28T17:15:00+00:00

## 6. Open items

- **Coverage is far shorter than the price history.** BTCUSDT: funding from 2020-01-01, open interest and long/short ratios from 2020-09-01; daily closes of the train window with an open-interest value: 849 of 2191; ETHUSDT: funding from 2020-01-01, open interest and long/short ratios from 2021-12-01; daily closes of the train window with an open-interest value: 395 of 2191. data.binance.vision publishes nothing earlier (checked in this build: the period before each first file answered 404). A model or rule using these series can only be trained and validated on that part of the history.
- **Publication delay of the live API not measured.** `known_at` adds no delay to funding (the rate is fixed at the funding instant) and 5 min to metrics (one 5-minute period; section 3). The futures API that would show the live delay (fapi.binance.com) is not on the network allow-list. For bar closes on the 5-minute grid the newest metrics row used was stamped at least 10 minutes before the close.
- **The test window was not downloaded.** Extending positioning data past 2024-07-01 is a separate, deliberate step for the backtest-auditor's one-time test run and for production; `load_positioning` refuses a later `end`.
- **USDT-margined perpetuals.** Funding rates are per 8-hour interval (a fraction, not annualised); open interest is in contracts (1 contract = 1 BTC or 1 ETH) and in USDT.
