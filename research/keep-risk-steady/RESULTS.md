# keep-risk-steady: results of run 0 (SCOUTING)

> **SCOUTING ONLY:** the reference engine (`lab/runner/keeprisk.py` on `lab/runner/trend.py`'s executor), the
> placeholder costs of `config/costs.yaml`, and Kraken and Binance daily candles in place of Base prices. Not
> NautilusTrader. Written 2026-11-25 by the lead from the committed record (`decision.json`, `spans.csv`, `runs.csv`)
> and `results/keep-risk-steady/run0/`.
> - Run 0 ran on commit `2a43cc4` with a clean tree, config hash `de32565d…`, data snapshot `1746a21b75683e76`. On that
>   commit the full tier passed (2750 tests, 18 slow, 100% branch coverage of `lab/`), the deep profile passed (2732),
>   ruff was clean and the dashboard passed (86).
> - 117,760 runs, 0 failed, in 501 s on 4 workers (the start's own projection: 24.7 CPU-minutes, under 240). Every
>   consistency check passed: the counts, copy 0, the steps (1,536 groups, no pair whose orders differ), the sigma
>   recheck (no near-integer case).
> - The study claims **no return edge**. It asks whether a user tool gives a calmer ride than simply holding less
>   crypto, and picks a suggested setting if one passes.
> - Validate-window looks used: 0 (none is planned). The test window was not read. No bar after 2023-01-01 00:00 UTC
>   was read.

## Default: NO DEFAULT. Label: MISSING (boom: without the best 2)

`decision.json`: default "NO DEFAULT" (no usable setting), label "MISSING (boom: without the best 2)". The Binance,
2x-cost and without-the-best-year checks also give NO DEFAULT; without BTC's two best years (2017 and 2020) only
windows 12 and 48 are left, fewer than 12, so that check is MISSING, as section 16 expected.

## In plain words

- **The question:** "If I switch on *keep my risk steady*, is my ride calmer than if I simply held less crypto all the
  time? And what does it cost?"
- **Against the user's full mix, it does what it says.** Down days were 3-33% smaller and the worst falls smaller
  (more so at the lower settings), because the tool holds less crypto on average. That calm was bought by giving up a
  median 0.4-29 points of return a year, mostly in the boom periods.
- **Against simply holding the same average amount of crypto, it made no difference worth showing.** The down days
  were a median 0-4% smaller, and the full-span reading rules out a cut as large as 10% at 31 of the 32 cells
  (NO NOTICEABLE DIFFERENCE). The worst falls were about the same or *deeper* than the plain lower mix's (up to 5 points
  at w = 8%). Its return was a median -1.2 to +6.3 points a year lower (lower at 28 of 32 cells).
- **Its timing is not random.** At w = 8% and 10% the tool ranked in the top 4% of the guarded time-shifted copies of
  its own stepping back (E1 at all 8 mixes; rank p 0.004-0.035): it does step back at better moments than chance. The gain is just too
  small to beat a plain lower crypto share.
- **A plain lower crypto share with the same calm** (the yardstick X_eq) returned 1-9 points a year more than the tool
  over 2017-2022, at every cell.
- **So no setting is suggested.** For a calmer ride the honest suggestion is a lower crypto share. Users can still
  switch the tool on and pick w; the app shows each setting's card with the CAN'T TELL sentence (amendment M3) and
  NO DEFAULT's sentence: "We don't suggest a setting: in 2017-2022, no setting rode clearly calmer than simply holding
  less crypto. To get a calmer ride, consider a lower crypto share."
- **Caveat (A0, amendment M3):** on made-up markets, the "no noticeable difference" reading was overconfident in one
  direction: it can say "no difference" when the tool really cuts more. So the app never shows that label, only
  "can't tell". The decision rule is unchanged and stays cautious.

## What the tool did, per setting (Kraken 1x, the headline pool)

Medians over each cell's 49 windows; ranges over the 8 mixes. "cut vs X" is 100 × (1 − exp(V_X)), positive is calmer
than holding the same average crypto steadily. c_X is the return a year given up against X (positive: the tool earned
less). "F rule − F X" is the median worst fall of the tool minus that of X (positive: the tool fell further).

| w | E1 holds at | calmer windows (range over mixes) | cut vs X | c_X | F rule − F X (median, points) | same calm, more return (X_eq − rule, full span) | D1 first failure |
|---|---|---|---|---|---|---|---|
| 8% | 8 of 8 mixes | 31-46 of 49 | 0.7 to 3.9% | 2.09 to 6.32 | +0.9 to +5.3 | +3.0 to +8.7 points a year | rule 2 at (30%, 50% BTC) |
| 10% | 8 of 8 mixes | 31-48 of 49 | 2.2 to 3.7% | -0.67 to 1.32 | +0.0 to +3.0 | +1.1 to +7.6 points a year | rule 2 at (30%, 50% BTC) |
| 12% | 1 of 8 mixes | 36-47 of 49 | 0.6 to 2.8% | 0.91 to 5.14 | +0.1 to +2.0 | +1.6 to +6.3 points a year | rule 2 at (30%, 50% BTC) |
| 15% | 0 of 8 mixes | 22-48 of 49 | -0.1 to 1.2% | -1.21 to 3.08 | -0.7 to +0.3 | +1.2 to +4.5 points a year | rule 2 at (30%, 50% BTC) |

**D1 at every setting fails rule 2 first** (the full-span label at (30%, 50% BTC) is NO NOTICEABLE DIFFERENCE, not
CALMER or CAN'T TELL). Rule 1 (calmer in at least 25 of 49 windows) holds at every cell but one (w 15%, 60% crypto,
75% BTC: 22 of 49). Rule 3 (c_X median at most 2.0 points a year) fails at w 8% at every mix, at w 12% at 5 mixes and
at w 15% at 2 mixes.

## The full table per setting and mix (Kraken 1x)

V, its 90% interval and the p-values are the full span (2,189 return rows, rows from 2017-01-01 to 2023-01-01);
the window columns are medians over the 49 two-year windows. F is the worst fall (median, then the 90th percentile Q).
"D1 rules 1-3" marks each rule ✓ or ✗ at that mix.

| w | crypto s | BTC f | label (computed) | V [90% interval] | p_calm | p_rough | p_eq | E1 rank p | calmer windows | cut vs X (median) | cut vs full mix | c_N | c_X | avg crypto x | F rule / N / X (median) | F rule / N / X (90th) | orders a year | fees a year | D1 rules 1-3 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 8% | 30% | 50% | NO NOTICEABLE DIFFERENCE | -0.025 [-0.100, 0.048] | 0.293 | 0.707 | 0.0397 | 0.0039 | 31 of 49 | 0.7% | 33.0% | 12.3 | 2.09 | 20.8% | 25.1 / 31.7 / 21.7% | 32.1 / 40.9 / 27.8% | 25.0 | 0.39% | ✓✗✗ |
| 8% | 30% | 75% | NO NOTICEABLE DIFFERENCE | -0.015 [-0.092, 0.062] | 0.383 | 0.617 | 0.0261 | 0.0077 | 46 of 49 | 2.4% | 29.3% | 12.8 | 2.61 | 21.7% | 21.9 / 27.3 / 21.0% | 28.4 / 35.7 / 24.6% | 24.5 | 0.38% | ✓✗✗ |
| 8% | 40% | 50% | NO NOTICEABLE DIFFERENCE | -0.029 [-0.101, 0.042] | 0.255 | 0.745 | 0.0430 | 0.0039 | 39 of 49 | 1.9% | 33.4% | 16.2 | 2.62 | 27.7% | 32.2 / 38.9 / 29.4% | 39.1 / 50.5 / 36.6% | 25.5 | 0.55% | ✓✗✗ |
| 8% | 40% | 75% | NO NOTICEABLE DIFFERENCE | -0.019 [-0.097, 0.059] | 0.355 | 0.645 | 0.0339 | 0.0077 | 46 of 49 | 3.3% | 29.6% | 17.8 | 4.09 | 29.0% | 28.3 / 34.8 / 27.1% | 36.2 / 45.3 / 32.1% | 24.5 | 0.52% | ✓✗✗ |
| 8% | 50% | 50% | NO NOTICEABLE DIFFERENCE | -0.027 [-0.099, 0.048] | 0.281 | 0.719 | 0.0372 | 0.0039 | 38 of 49 | 1.7% | 33.5% | 18.8 | 3.49 | 34.6% | 38.7 / 47.1 / 34.5% | 46.6 / 59.7 / 43.6% | 25.0 | 0.69% | ✓✗✗ |
| 8% | 50% | 75% | NO NOTICEABLE DIFFERENCE | -0.020 [-0.099, 0.059] | 0.344 | 0.656 | 0.0369 | 0.0077 | 46 of 49 | 3.6% | 30.1% | 21.9 | 4.73 | 36.2% | 34.3 / 41.7 / 32.8% | 43.5 / 54.8 / 39.6% | 24.0 | 0.67% | ✓✗✗ |
| 8% | 60% | 50% | NO NOTICEABLE DIFFERENCE | -0.031 [-0.104, 0.042] | 0.248 | 0.752 | 0.0474 | 0.0039 | 37 of 49 | 3.0% | 32.3% | 29.1 | 2.76 | 41.5% | 44.7 / 53.3 / 39.5% | 53.5 / 67.0 / 49.5% | 25.0 | 0.85% | ✓✗✗ |
| 8% | 60% | 75% | CAN'T TELL | -0.032 [-0.114, 0.050] | 0.268 | 0.732 | 0.0692 | 0.0077 | 46 of 49 | 3.9% | 30.2% | 26.8 | 6.32 | 43.4% | 40.0 / 48.1 / 38.1% | 50.7 / 62.9 / 47.1% | 23.5 | 0.83% | ✓✓✗ |
| 10% | 30% | 50% | NO NOTICEABLE DIFFERENCE | -0.029 [-0.084, 0.029] | 0.210 | 0.790 | 0.0102 | 0.0154 | 44 of 49 | 3.7% | 20.9% | 5.8 | 0.08 | 24.9% | 27.7 / 31.7 / 26.7% | 37.7 / 40.9 / 32.3% | 23.5 | 0.34% | ✓✗✓ |
| 10% | 30% | 75% | NO NOTICEABLE DIFFERENCE | -0.017 [-0.077, 0.037] | 0.322 | 0.678 | 0.0076 | 0.0232 | 43 of 49 | 2.8% | 17.2% | 4.8 | -0.61 | 25.8% | 24.1 / 27.3 / 24.1% | 32.4 / 35.7 / 28.7% | 20.0 | 0.28% | ✓✗✓ |
| 10% | 40% | 50% | NO NOTICEABLE DIFFERENCE | -0.007 [-0.063, 0.052] | 0.425 | 0.575 | 0.0021 | 0.0309 | 35 of 49 | 2.2% | 20.6% | 7.4 | 0.93 | 33.2% | 35.5 / 38.9 / 33.4% | 47.4 / 50.5 / 41.9% | 23.0 | 0.47% | ✓✗✓ |
| 10% | 40% | 75% | NO NOTICEABLE DIFFERENCE | -0.018 [-0.078, 0.038] | 0.322 | 0.678 | 0.0090 | 0.0232 | 45 of 49 | 3.0% | 17.2% | 5.9 | 1.32 | 34.4% | 31.1 / 34.8 / 30.9% | 40.9 / 45.3 / 37.8% | 19.5 | 0.38% | ✓✗✓ |
| 10% | 50% | 50% | NO NOTICEABLE DIFFERENCE | -0.017 [-0.072, 0.041] | 0.324 | 0.677 | 0.0041 | 0.0347 | 31 of 49 | 2.5% | 21.0% | 9.5 | -0.03 | 41.5% | 42.8 / 47.1 / 40.0% | 55.9 / 59.7 / 49.1% | 23.0 | 0.60% | ✓✗✓ |
| 10% | 50% | 75% | NO NOTICEABLE DIFFERENCE | -0.032 [-0.096, 0.027] | 0.199 | 0.801 | 0.0282 | 0.0193 | 48 of 49 | 3.3% | 17.4% | 6.4 | 1.31 | 43.0% | 37.7 / 41.7 / 37.2% | 48.9 / 54.8 / 45.4% | 19.0 | 0.49% | ✓✗✓ |
| 10% | 60% | 50% | NO NOTICEABLE DIFFERENCE | -0.024 [-0.083, 0.036] | 0.261 | 0.739 | 0.0106 | 0.0347 | 36 of 49 | 3.2% | 20.2% | 14.6 | 0.10 | 49.8% | 49.5 / 53.3 / 46.5% | 62.8 / 67.0 / 56.7% | 22.5 | 0.74% | ✓✗✓ |
| 10% | 60% | 75% | NO NOTICEABLE DIFFERENCE | -0.015 [-0.078, 0.044] | 0.360 | 0.640 | 0.0092 | 0.0270 | 37 of 49 | 3.0% | 16.9% | 6.2 | -0.67 | 51.6% | 43.9 / 48.1 / 43.1% | 56.2 / 62.9 / 53.3% | 17.5 | 0.61% | ✓✗✓ |
| 12% | 30% | 50% | NO NOTICEABLE DIFFERENCE | -0.014 [-0.051, 0.025] | 0.284 | 0.716 | 0.0001 | 0.0347 | 47 of 49 | 2.3% | 12.7% | 4.1 | 1.16 | 27.0% | 29.1 / 31.7 / 28.8% | 38.6 / 40.9 / 36.3% | 19.5 | 0.24% | ✓✗✓ |
| 12% | 30% | 75% | NO NOTICEABLE DIFFERENCE | -0.009 [-0.049, 0.028] | 0.369 | 0.631 | 0.0004 | 0.0772 | 47 of 49 | 1.4% | 9.7% | 3.7 | 2.03 | 27.6% | 25.5 / 27.3 / 25.4% | 34.7 / 35.7 / 31.3% | 15.0 | 0.20% | ✓✗✗ |
| 12% | 40% | 50% | NO NOTICEABLE DIFFERENCE | -0.010 [-0.050, 0.033] | 0.349 | 0.651 | 0.0001 | 0.0502 | 47 of 49 | 2.2% | 12.4% | 5.1 | 1.93 | 36.0% | 37.3 / 38.9 / 35.8% | 48.3 / 50.5 / 45.5% | 18.5 | 0.33% | ✓✗✓ |
| 12% | 40% | 75% | NO NOTICEABLE DIFFERENCE | -0.004 [-0.047, 0.035] | 0.444 | 0.556 | 0.0003 | 0.1120 | 41 of 49 | 1.9% | 9.8% | 6.3 | 4.25 | 36.8% | 32.7 / 34.8 / 32.5% | 43.8 / 45.3 / 41.0% | 13.5 | 0.26% | ✓✗✗ |
| 12% | 50% | 50% | NO NOTICEABLE DIFFERENCE | -0.015 [-0.056, 0.028] | 0.281 | 0.720 | 0.0001 | 0.0618 | 46 of 49 | 2.1% | 13.1% | 5.9 | 0.91 | 45.0% | 44.9 / 47.1 / 43.3% | 57.0 / 59.7 / 54.2% | 18.5 | 0.42% | ✓✗✓ |
| 12% | 50% | 75% | NO NOTICEABLE DIFFERENCE | -0.010 [-0.055, 0.031] | 0.378 | 0.622 | 0.0007 | 0.1158 | 47 of 49 | 1.5% | 9.4% | 5.8 | 5.14 | 46.0% | 39.2 / 41.7 / 39.1% | 51.8 / 54.8 / 50.1% | 13.5 | 0.32% | ✓✗✗ |
| 12% | 60% | 50% | NO NOTICEABLE DIFFERENCE | -0.028 [-0.071, 0.016] | 0.149 | 0.851 | 0.0015 | 0.0618 | 43 of 49 | 2.8% | 13.2% | 11.6 | 2.32 | 54.0% | 51.8 / 53.3 / 49.7% | 64.8 / 67.0 / 60.9% | 17.5 | 0.52% | ✓✗✗ |
| 12% | 60% | 75% | NO NOTICEABLE DIFFERENCE | 0.004 [-0.038, 0.044] | 0.585 | 0.415 | 0.0002 | 0.1351 | 36 of 49 | 0.6% | 9.3% | 4.7 | 2.67 | 55.3% | 45.3 / 48.1 / 45.1% | 59.6 / 62.9 / 57.6% | 13.0 | 0.39% | ✓✗✗ |
| 15% | 30% | 50% | NO NOTICEABLE DIFFERENCE | -0.002 [-0.022, 0.018] | 0.467 | 0.533 | 0.0001 | 0.2432 | 40 of 49 | 0.8% | 5.0% | 1.2 | 0.20 | 28.9% | 30.3 / 31.7 / 30.7% | 40.3 / 40.9 / 39.2% | 12.0 | 0.15% | ✓✗✓ |
| 15% | 30% | 75% | NO NOTICEABLE DIFFERENCE | -0.007 [-0.032, 0.014] | 0.331 | 0.669 | 0.0001 | 0.1313 | 48 of 49 | 1.0% | 3.8% | 1.9 | 1.20 | 29.1% | 26.8 / 27.3 / 26.5% | 36.0 / 35.7 / 33.4% | 10.0 | 0.13% | ✓✗✓ |
| 15% | 40% | 50% | NO NOTICEABLE DIFFERENCE | 0.001 [-0.026, 0.027] | 0.536 | 0.465 | 0.0001 | 0.2432 | 35 of 49 | 1.1% | 4.2% | 2.5 | 0.86 | 38.6% | 37.7 / 38.9 / 37.9% | 50.4 / 50.5 / 48.4% | 10.5 | 0.19% | ✓✗✓ |
| 15% | 40% | 75% | NO NOTICEABLE DIFFERENCE | -0.003 [-0.029, 0.022] | 0.441 | 0.559 | 0.0001 | 0.1892 | 44 of 49 | 1.2% | 4.3% | 4.3 | 3.08 | 38.8% | 34.2 / 34.8 / 33.9% | 45.5 / 45.3 / 43.4% | 10.5 | 0.16% | ✓✗✗ |
| 15% | 50% | 50% | NO NOTICEABLE DIFFERENCE | -0.003 [-0.031, 0.022] | 0.437 | 0.563 | 0.0001 | 0.2664 | 38 of 49 | 1.2% | 5.2% | 0.4 | -1.21 | 48.2% | 45.1 / 47.1 / 45.8% | 59.0 / 59.7 / 57.5% | 10.0 | 0.23% | ✓✗✓ |
| 15% | 50% | 75% | NO NOTICEABLE DIFFERENCE | -0.007 [-0.033, 0.018] | 0.370 | 0.630 | 0.0001 | 0.1892 | 41 of 49 | 0.9% | 3.7% | 3.4 | 2.63 | 48.4% | 41.0 / 41.7 / 40.7% | 53.9 / 54.8 / 52.9% | 9.5 | 0.19% | ✓✗✗ |
| 15% | 60% | 50% | NO NOTICEABLE DIFFERENCE | 0.007 [-0.017, 0.028] | 0.697 | 0.303 | 0.0001 | 0.2934 | 32 of 49 | 0.7% | 4.4% | 2.8 | 0.25 | 57.8% | 51.9 / 53.3 / 52.4% | 66.4 / 67.0 / 66.7% | 9.5 | 0.25% | ✓✗✓ |
| 15% | 60% | 75% | NO NOTICEABLE DIFFERENCE | -0.001 [-0.026, 0.020] | 0.506 | 0.495 | 0.0001 | 0.2432 | 22 of 49 | -0.1% | 3.2% | 4.0 | 1.47 | 58.1% | 47.2 / 48.1 / 47.0% | 61.5 / 62.9 / 60.7% | 8.5 | 0.22% | ✗✗✓ |

## The label in each check (the 32 cells)

| Pool | Rows | Labels of the 32 cells |
|---|---|---|
| KRAKEN 1x | all | CAN'T TELL 1; NO NOTICEABLE DIFFERENCE 31 |
| KRAKEN 1x | without 2017 | CAN'T TELL 3; NO NOTICEABLE DIFFERENCE 29 |
| KRAKEN 1x | without 2018 | NO NOTICEABLE DIFFERENCE 32 |
| KRAKEN 1x | without 2019 | CAN'T TELL 9; NO NOTICEABLE DIFFERENCE 23 |
| KRAKEN 1x | without 2020 | CAN'T TELL 6; NO NOTICEABLE DIFFERENCE 26 |
| KRAKEN 1x | without 2021 | NO NOTICEABLE DIFFERENCE 31; ROUGHER THAN HOLDING LESS 1 |
| KRAKEN 1x | without 2022 | CAN'T TELL 14; NO NOTICEABLE DIFFERENCE 18 |
| KRAKEN 1x | without the best 1 | CAN'T TELL 3; NO NOTICEABLE DIFFERENCE 29 |
| KRAKEN 1x | without the best 2 | CAN'T TELL 8; NO NOTICEABLE DIFFERENCE 24 |
| BINANCE 1x | all | CAN'T TELL 8; NO NOTICEABLE DIFFERENCE 24 |
| KRAKEN 2x | all | CAN'T TELL 1; NO NOTICEABLE DIFFERENCE 31 |
| KRAKEN 1x L7 | all | CAN'T TELL 4; NO NOTICEABLE DIFFERENCE 28 |
| KRAKEN 1x L28 | all | NO NOTICEABLE DIFFERENCE 32 |
| KRAKEN 1x 500 USD | all | (no label: no copies) 32 |

The labels move between NO NOTICEABLE DIFFERENCE and CAN'T TELL as years are removed (most without 2022: 14 CAN'T
TELL), never to CALMER. One ROUGHER appears without 2021 (w 15%, 60% crypto, 50% BTC); it decides nothing. The
500 USD wallet has no copies, so no label (as pinned); its numbers are in the descriptions below.

## By the year of each window's first close (Kraken 1x)

Median over the 8 mixes of each year's median: the cut against X, c_N (points a year given up against the full mix)
and the tool's worst fall F.

| w | 2017: cut vs X / c_N / F | 2018: cut vs X / c_N / F | 2019: cut vs X / c_N / F | 2020: cut vs X / c_N / F | 2021: cut vs X / c_N / F |
|---|---|---|---|---|---|
| 8% | 1.4% / 17.5 / 41% | 0.8% / 3.3 / 33% | 6.4% / 30.3 / 25% | 4.1% / 18.8 / 34% | 0.1% / 5.4 / 39% |
| 10% | 1.8% / 13.2 / 48% | 1.1% / 1.2 / 36% | 5.9% / 13.9 / 27% | 4.1% / 5.3 / 37% | 1.0% / 1.7 / 43% |
| 12% | 1.5% / 8.3 / 50% | 1.5% / 2.5 / 38% | 3.1% / 14.0 / 28% | 1.7% / 5.0 / 37% | 0.1% / 2.8 / 44% |
| 15% | 0.2% / 6.2 / 52% | 0.4% / 0.8 / 39% | 1.2% / 5.4 / 28% | 1.3% / 2.6 / 38% | 0.6% / 1.1 / 45% |

The cut against X is largest in windows starting in 2019 and 2020 (the March 2020 crash), 4-6% at w 8-10%, and about
0-2% in windows starting in 2017, 2018 and 2021.

## The descriptions (decide nothing)

Medians over the 8 mixes of each cell's window median.

| Pool | w | cut vs X (median over mixes) | c_X | F rule − F X (points) | avg crypto x |
|---|---|---|---|---|---|
| KRAKEN 1x | 8% | 2.7% | 3.12 | +2.4 | 32% |
| KRAKEN 1x | 10% | 3.0% | 0.09 | +0.9 | 38% |
| KRAKEN 1x | 12% | 2.0% | 2.17 | +0.2 | 41% |
| KRAKEN 1x | 15% | 1.0% | 1.03 | +0.0 | 43% |
| BINANCE 1x | 8% | 2.9% | 1.17 | +3.6 | 32% |
| BINANCE 1x | 10% | 4.2% | -1.53 | +1.7 | 38% |
| BINANCE 1x | 12% | 2.3% | 0.90 | -0.1 | 41% |
| BINANCE 1x | 15% | 1.0% | 0.77 | -0.2 | 44% |
| KRAKEN 2x | 8% | 2.6% | 4.14 | +2.5 | 32% |
| KRAKEN 2x | 10% | 2.9% | 0.96 | +0.9 | 38% |
| KRAKEN 2x | 12% | 2.0% | 2.61 | +0.3 | 41% |
| KRAKEN 2x | 15% | 1.0% | 1.15 | +0.0 | 43% |
| KRAKEN 1x L7 | 8% | 4.9% | 3.80 | +0.2 | 33% |
| KRAKEN 1x L7 | 10% | 3.7% | 2.27 | +0.8 | 38% |
| KRAKEN 1x L7 | 12% | 2.6% | 1.98 | +0.6 | 41% |
| KRAKEN 1x L7 | 15% | 1.6% | 3.19 | +0.9 | 43% |
| KRAKEN 1x L28 | 8% | -0.8% | 1.95 | +3.8 | 31% |
| KRAKEN 1x L28 | 10% | 2.2% | 4.45 | +0.8 | 38% |
| KRAKEN 1x L28 | 12% | 1.4% | 2.76 | +0.5 | 41% |
| KRAKEN 1x L28 | 15% | -0.4% | 4.51 | -0.4 | 43% |
| KRAKEN 1x 500 USD | 8% | 2.6% | 3.74 | +2.6 | 32% |
| KRAKEN 1x 500 USD | 10% | 3.0% | 0.48 | +1.0 | 38% |
| KRAKEN 1x 500 USD | 12% | 2.0% | 2.53 | +0.3 | 41% |
| KRAKEN 1x 500 USD | 15% | 1.0% | 1.17 | +0.1 | 43% |

Binance, 2x costs, the 500 USD wallet and the 7- and 28-return look-backs tell the same story: a median cut of about -1 to
5% against holding the same crypto steadily, falls about the same or deeper, and some return given up. The cost flag (section 9.5)
fired at no cell of the headline pool.

**A post-hoc reading (decides nothing, added by the lead).** At w = 10%, D1's rules 1 and 3 hold at all 8 mixes; only
rule 2 fails. A0 says NO NOTICEABLE DIFFERENCE can be wrong when the tool helps. Read as CAN'T TELL, w = 10% would
have passed D1. But its cut against X is still a median 2-4%, its falls 0-3 points deeper than X's, and the steady
share with the same calm returned 1-8 points a year more. This is not a default: the rules were fixed before the run,
and M3 keeps them unchanged.

## The 32 cards (Kraken 1x; shown with the CAN'T TELL sentence, amendment M3)

Each card is filled from D3 (`decision.json`). Numbers are SCOUTING until rerun on NautilusTrader. The 49 windows
overlap: "calmer in 31 of 49 periods" is not 31 separate tests. Seven studies have now looked at Steady claims on these
rows (PLAN.md section 2); no single 5% accounts for that.

**w = 8%, 30% crypto, 50% of it BTC** (computed label: NO NOTICEABLE DIFFERENCE; shown as CAN'T TELL, amendment M3)

> **Keep my risk steady, at w = 8% a week**, with your mix (30% crypto, 50% of it BTC). In two-year periods of 2017-2022:
> - It held a median 21% crypto and stepped back 74% of the time.
> - **Against keeping your full mix:** down days 33% smaller; worst fall 25% against 32% (median; the worst period 32% against 41%); it gave up a median 12.3 points a year (from 1.7 to 24.7).
> - **Against simply holding 21% crypto steadily:** Its down days were smaller than holding 21% crypto steadily in 31 of 49 two-year periods (a median 0.7%), but we can't rule out that this was luck.
> - About 2.1 trades a month (up to 5 in a busy month); fees about 0.39% a year.
> - After the worst low of a period it trailed your full mix by a median 5.9 points over the next three months.
> - Holding crypto steadily at the share with the same calm returned 3.0 points a year more than this setting over 2017-2022.

A0's power: CALMER at any setting on 10 of 100 made-up markets with a real effect (PG) and 21 of 100 (PR). Full span: V -0.025 [-0.100, 0.048], p_eq 0.0397, E1 rank p 0.0039.

**w = 8%, 30% crypto, 75% of it BTC** (computed label: NO NOTICEABLE DIFFERENCE; shown as CAN'T TELL, amendment M3)

> **Keep my risk steady, at w = 8% a week**, with your mix (30% crypto, 75% of it BTC). In two-year periods of 2017-2022:
> - It held a median 22% crypto and stepped back 66% of the time.
> - **Against keeping your full mix:** down days 29% smaller; worst fall 22% against 27% (median; the worst period 28% against 36%); it gave up a median 12.8 points a year (from 3.6 to 20.7).
> - **Against simply holding 22% crypto steadily:** Its down days were smaller than holding 22% crypto steadily in 46 of 49 two-year periods (a median 2.4%), but we can't rule out that this was luck.
> - About 2.0 trades a month (up to 5 in a busy month); fees about 0.38% a year.
> - After the worst low of a period it trailed your full mix by a median 4.7 points over the next three months.
> - Holding crypto steadily at the share with the same calm returned 3.3 points a year more than this setting over 2017-2022.

A0's power: CALMER at any setting on 10 of 100 made-up markets with a real effect (PG) and 21 of 100 (PR). Full span: V -0.015 [-0.092, 0.062], p_eq 0.0261, E1 rank p 0.0077.

**w = 8%, 40% crypto, 50% of it BTC** (computed label: NO NOTICEABLE DIFFERENCE; shown as CAN'T TELL, amendment M3)

> **Keep my risk steady, at w = 8% a week**, with your mix (40% crypto, 50% of it BTC). In two-year periods of 2017-2022:
> - It held a median 28% crypto and stepped back 74% of the time.
> - **Against keeping your full mix:** down days 33% smaller; worst fall 32% against 39% (median; the worst period 39% against 50%); it gave up a median 16.2 points a year (from 0.3 to 36.3).
> - **Against simply holding 28% crypto steadily:** Its down days were smaller than holding 28% crypto steadily in 39 of 49 two-year periods (a median 1.9%), but we can't rule out that this was luck.
> - About 2.1 trades a month (up to 5 in a busy month); fees about 0.55% a year.
> - After the worst low of a period it trailed your full mix by a median 8.4 points over the next three months.
> - Holding crypto steadily at the share with the same calm returned 3.2 points a year more than this setting over 2017-2022.

A0's power: CALMER at any setting on 10 of 100 made-up markets with a real effect (PG) and 21 of 100 (PR). Full span: V -0.029 [-0.101, 0.042], p_eq 0.0430, E1 rank p 0.0039.

**w = 8%, 40% crypto, 75% of it BTC** (computed label: NO NOTICEABLE DIFFERENCE; shown as CAN'T TELL, amendment M3)

> **Keep my risk steady, at w = 8% a week**, with your mix (40% crypto, 75% of it BTC). In two-year periods of 2017-2022:
> - It held a median 29% crypto and stepped back 66% of the time.
> - **Against keeping your full mix:** down days 30% smaller; worst fall 28% against 35% (median; the worst period 36% against 46%); it gave up a median 17.8 points a year (from 4.0 to 31.5).
> - **Against simply holding 29% crypto steadily:** Its down days were smaller than holding 29% crypto steadily in 46 of 49 two-year periods (a median 3.3%), but we can't rule out that this was luck.
> - About 2.0 trades a month (up to 5 in a busy month); fees about 0.52% a year.
> - After the worst low of a period it trailed your full mix by a median 6.5 points over the next three months.
> - Holding crypto steadily at the share with the same calm returned 5.1 points a year more than this setting over 2017-2022.

A0's power: CALMER at any setting on 10 of 100 made-up markets with a real effect (PG) and 21 of 100 (PR). Full span: V -0.019 [-0.097, 0.059], p_eq 0.0339, E1 rank p 0.0077.

**w = 8%, 50% crypto, 50% of it BTC** (computed label: NO NOTICEABLE DIFFERENCE; shown as CAN'T TELL, amendment M3)

> **Keep my risk steady, at w = 8% a week**, with your mix (50% crypto, 50% of it BTC). In two-year periods of 2017-2022:
> - It held a median 35% crypto and stepped back 74% of the time.
> - **Against keeping your full mix:** down days 33% smaller; worst fall 39% against 47% (median; the worst period 47% against 60%); it gave up a median 18.8 points a year (from -0.9 to 43.6).
> - **Against simply holding 35% crypto steadily:** Its down days were smaller than holding 35% crypto steadily in 38 of 49 two-year periods (a median 1.7%), but we can't rule out that this was luck.
> - About 2.1 trades a month (up to 5 in a busy month); fees about 0.69% a year.
> - After the worst low of a period it trailed your full mix by a median 11.0 points over the next three months.
> - Holding crypto steadily at the share with the same calm returned 3.8 points a year more than this setting over 2017-2022.

A0's power: CALMER at any setting on 10 of 100 made-up markets with a real effect (PG) and 21 of 100 (PR). Full span: V -0.027 [-0.099, 0.048], p_eq 0.0372, E1 rank p 0.0039.

**w = 8%, 50% crypto, 75% of it BTC** (computed label: NO NOTICEABLE DIFFERENCE; shown as CAN'T TELL, amendment M3)

> **Keep my risk steady, at w = 8% a week**, with your mix (50% crypto, 75% of it BTC). In two-year periods of 2017-2022:
> - It held a median 36% crypto and stepped back 66% of the time.
> - **Against keeping your full mix:** down days 30% smaller; worst fall 34% against 42% (median; the worst period 44% against 55%); it gave up a median 21.9 points a year (from 3.1 to 36.0).
> - **Against simply holding 36% crypto steadily:** Its down days were smaller than holding 36% crypto steadily in 46 of 49 two-year periods (a median 3.6%), but we can't rule out that this was luck.
> - About 2.0 trades a month (up to 5 in a busy month); fees about 0.67% a year.
> - After the worst low of a period it trailed your full mix by a median 9.0 points over the next three months.
> - Holding crypto steadily at the share with the same calm returned 6.5 points a year more than this setting over 2017-2022.

A0's power: CALMER at any setting on 10 of 100 made-up markets with a real effect (PG) and 21 of 100 (PR). Full span: V -0.020 [-0.099, 0.059], p_eq 0.0369, E1 rank p 0.0077.

**w = 8%, 60% crypto, 50% of it BTC** (computed label: NO NOTICEABLE DIFFERENCE; shown as CAN'T TELL, amendment M3)

> **Keep my risk steady, at w = 8% a week**, with your mix (60% crypto, 50% of it BTC). In two-year periods of 2017-2022:
> - It held a median 42% crypto and stepped back 74% of the time.
> - **Against keeping your full mix:** down days 32% smaller; worst fall 45% against 53% (median; the worst period 53% against 68%); it gave up a median 29.1 points a year (from -1.9 to 66.1).
> - **Against simply holding 42% crypto steadily:** Its down days were smaller than holding 42% crypto steadily in 37 of 49 two-year periods (a median 3.0%), but we can't rule out that this was luck.
> - About 2.1 trades a month (up to 5 in a busy month); fees about 0.85% a year.
> - After the worst low of a period it trailed your full mix by a median 14.6 points over the next three months.
> - Holding crypto steadily at the share with the same calm returned 4.5 points a year more than this setting over 2017-2022.

A0's power: CALMER at any setting on 10 of 100 made-up markets with a real effect (PG) and 21 of 100 (PR). Full span: V -0.031 [-0.104, 0.042], p_eq 0.0474, E1 rank p 0.0039.

**w = 8%, 60% crypto, 75% of it BTC** (computed label: CAN'T TELL; shown as CAN'T TELL, amendment M3)

> **Keep my risk steady, at w = 8% a week**, with your mix (60% crypto, 75% of it BTC). In two-year periods of 2017-2022:
> - It held a median 43% crypto and stepped back 66% of the time.
> - **Against keeping your full mix:** down days 30% smaller; worst fall 40% against 48% (median; the worst period 51% against 64%); it gave up a median 26.8 points a year (from 1.0 to 48.5).
> - **Against simply holding 43% crypto steadily:** Its down days were smaller than holding 43% crypto steadily in 46 of 49 two-year periods (a median 3.9%), but we can't rule out that this was luck.
> - About 2.0 trades a month (up to 5 in a busy month); fees about 0.83% a year.
> - After the worst low of a period it trailed your full mix by a median 12.8 points over the next three months.
> - Holding crypto steadily at the share with the same calm returned 8.7 points a year more than this setting over 2017-2022.

A0's power: CALMER at any setting on 10 of 100 made-up markets with a real effect (PG) and 21 of 100 (PR). Full span: V -0.032 [-0.114, 0.050], p_eq 0.0692, E1 rank p 0.0077.

**w = 10%, 30% crypto, 50% of it BTC** (computed label: NO NOTICEABLE DIFFERENCE; shown as CAN'T TELL, amendment M3)

> **Keep my risk steady, at w = 10% a week**, with your mix (30% crypto, 50% of it BTC). In two-year periods of 2017-2022:
> - It held a median 25% crypto and stepped back 46% of the time.
> - **Against keeping your full mix:** down days 21% smaller; worst fall 28% against 32% (median; the worst period 38% against 41%); it gave up a median 5.8 points a year (from 1.3 to 14.8).
> - **Against simply holding 25% crypto steadily:** Its down days were smaller than holding 25% crypto steadily in 44 of 49 two-year periods (a median 3.7%), but we can't rule out that this was luck.
> - About 2.0 trades a month (up to 5 in a busy month); fees about 0.34% a year.
> - After the worst low of a period it trailed your full mix by a median 2.0 points over the next three months.
> - Holding crypto steadily at the share with the same calm returned 2.7 points a year more than this setting over 2017-2022.

A0's power: CALMER at any setting on 10 of 100 made-up markets with a real effect (PG) and 21 of 100 (PR). Full span: V -0.029 [-0.084, 0.029], p_eq 0.0102, E1 rank p 0.0154.

**w = 10%, 30% crypto, 75% of it BTC** (computed label: NO NOTICEABLE DIFFERENCE; shown as CAN'T TELL, amendment M3)

> **Keep my risk steady, at w = 10% a week**, with your mix (30% crypto, 75% of it BTC). In two-year periods of 2017-2022:
> - It held a median 26% crypto and stepped back 38% of the time.
> - **Against keeping your full mix:** down days 17% smaller; worst fall 24% against 27% (median; the worst period 33% against 36%); it gave up a median 4.8 points a year (from 0.8 to 10.6).
> - **Against simply holding 26% crypto steadily:** Its down days were smaller than holding 26% crypto steadily in 43 of 49 two-year periods (a median 2.8%), but we can't rule out that this was luck.
> - About 1.7 trades a month (up to 5 in a busy month); fees about 0.28% a year.
> - After the worst low of a period it trailed your full mix by a median 1.8 points over the next three months.
> - Holding crypto steadily at the share with the same calm returned 1.1 points a year more than this setting over 2017-2022.

A0's power: CALMER at any setting on 10 of 100 made-up markets with a real effect (PG) and 21 of 100 (PR). Full span: V -0.017 [-0.077, 0.037], p_eq 0.0076, E1 rank p 0.0232.

**w = 10%, 40% crypto, 50% of it BTC** (computed label: NO NOTICEABLE DIFFERENCE; shown as CAN'T TELL, amendment M3)

> **Keep my risk steady, at w = 10% a week**, with your mix (40% crypto, 50% of it BTC). In two-year periods of 2017-2022:
> - It held a median 33% crypto and stepped back 46% of the time.
> - **Against keeping your full mix:** down days 21% smaller; worst fall 36% against 39% (median; the worst period 47% against 50%); it gave up a median 7.4 points a year (from 0.6 to 21.2).
> - **Against simply holding 33% crypto steadily:** Its down days were smaller than holding 33% crypto steadily in 35 of 49 two-year periods (a median 2.2%), but we can't rule out that this was luck.
> - About 1.9 trades a month (up to 5 in a busy month); fees about 0.47% a year.
> - After the worst low of a period it trailed your full mix by a median 3.1 points over the next three months.
> - Holding crypto steadily at the share with the same calm returned 6.1 points a year more than this setting over 2017-2022.

A0's power: CALMER at any setting on 10 of 100 made-up markets with a real effect (PG) and 21 of 100 (PR). Full span: V -0.007 [-0.063, 0.052], p_eq 0.0021, E1 rank p 0.0309.

**w = 10%, 40% crypto, 75% of it BTC** (computed label: NO NOTICEABLE DIFFERENCE; shown as CAN'T TELL, amendment M3)

> **Keep my risk steady, at w = 10% a week**, with your mix (40% crypto, 75% of it BTC). In two-year periods of 2017-2022:
> - It held a median 34% crypto and stepped back 38% of the time.
> - **Against keeping your full mix:** down days 17% smaller; worst fall 31% against 35% (median; the worst period 41% against 46%); it gave up a median 5.9 points a year (from 1.2 to 18.0).
> - **Against simply holding 34% crypto steadily:** Its down days were smaller than holding 34% crypto steadily in 45 of 49 two-year periods (a median 3.0%), but we can't rule out that this was luck.
> - About 1.6 trades a month (up to 5 in a busy month); fees about 0.38% a year.
> - After the worst low of a period it trailed your full mix by a median 2.5 points over the next three months.
> - Holding crypto steadily at the share with the same calm returned 3.4 points a year more than this setting over 2017-2022.

A0's power: CALMER at any setting on 10 of 100 made-up markets with a real effect (PG) and 21 of 100 (PR). Full span: V -0.018 [-0.078, 0.038], p_eq 0.0090, E1 rank p 0.0232.

**w = 10%, 50% crypto, 50% of it BTC** (computed label: NO NOTICEABLE DIFFERENCE; shown as CAN'T TELL, amendment M3)

> **Keep my risk steady, at w = 10% a week**, with your mix (50% crypto, 50% of it BTC). In two-year periods of 2017-2022:
> - It held a median 42% crypto and stepped back 46% of the time.
> - **Against keeping your full mix:** down days 21% smaller; worst fall 43% against 47% (median; the worst period 56% against 60%); it gave up a median 9.5 points a year (from 0.5 to 27.5).
> - **Against simply holding 42% crypto steadily:** Its down days were smaller than holding 42% crypto steadily in 31 of 49 two-year periods (a median 2.5%), but we can't rule out that this was luck.
> - About 1.9 trades a month (up to 5 in a busy month); fees about 0.60% a year.
> - After the worst low of a period it trailed your full mix by a median 4.3 points over the next three months.
> - Holding crypto steadily at the share with the same calm returned 7.6 points a year more than this setting over 2017-2022.

A0's power: CALMER at any setting on 10 of 100 made-up markets with a real effect (PG) and 21 of 100 (PR). Full span: V -0.017 [-0.072, 0.041], p_eq 0.0041, E1 rank p 0.0347.

**w = 10%, 50% crypto, 75% of it BTC** (computed label: NO NOTICEABLE DIFFERENCE; shown as CAN'T TELL, amendment M3)

> **Keep my risk steady, at w = 10% a week**, with your mix (50% crypto, 75% of it BTC). In two-year periods of 2017-2022:
> - It held a median 43% crypto and stepped back 38% of the time.
> - **Against keeping your full mix:** down days 17% smaller; worst fall 38% against 42% (median; the worst period 49% against 55%); it gave up a median 6.4 points a year (from -1.3 to 19.5).
> - **Against simply holding 43% crypto steadily:** Its down days were smaller than holding 43% crypto steadily in 48 of 49 two-year periods (a median 3.3%), but we can't rule out that this was luck.
> - About 1.6 trades a month (up to 5 in a busy month); fees about 0.49% a year.
> - After the worst low of a period it trailed your full mix by a median 3.3 points over the next three months.
> - Holding crypto steadily at the share with the same calm returned 3.2 points a year more than this setting over 2017-2022.

A0's power: CALMER at any setting on 10 of 100 made-up markets with a real effect (PG) and 21 of 100 (PR). Full span: V -0.032 [-0.096, 0.027], p_eq 0.0282, E1 rank p 0.0193.

**w = 10%, 60% crypto, 50% of it BTC** (computed label: NO NOTICEABLE DIFFERENCE; shown as CAN'T TELL, amendment M3)

> **Keep my risk steady, at w = 10% a week**, with your mix (60% crypto, 50% of it BTC). In two-year periods of 2017-2022:
> - It held a median 50% crypto and stepped back 46% of the time.
> - **Against keeping your full mix:** down days 20% smaller; worst fall 50% against 53% (median; the worst period 63% against 68%); it gave up a median 14.6 points a year (from 0.5 to 36.8).
> - **Against simply holding 50% crypto steadily:** Its down days were smaller than holding 50% crypto steadily in 36 of 49 two-year periods (a median 3.2%), but we can't rule out that this was luck.
> - About 1.9 trades a month (up to 5 in a busy month); fees about 0.74% a year.
> - After the worst low of a period it trailed your full mix by a median 6.0 points over the next three months.
> - Holding crypto steadily at the share with the same calm returned 6.9 points a year more than this setting over 2017-2022.

A0's power: CALMER at any setting on 10 of 100 made-up markets with a real effect (PG) and 21 of 100 (PR). Full span: V -0.024 [-0.083, 0.036], p_eq 0.0106, E1 rank p 0.0347.

**w = 10%, 60% crypto, 75% of it BTC** (computed label: NO NOTICEABLE DIFFERENCE; shown as CAN'T TELL, amendment M3)

> **Keep my risk steady, at w = 10% a week**, with your mix (60% crypto, 75% of it BTC). In two-year periods of 2017-2022:
> - It held a median 52% crypto and stepped back 38% of the time.
> - **Against keeping your full mix:** down days 17% smaller; worst fall 44% against 48% (median; the worst period 56% against 64%); it gave up a median 6.2 points a year (from -3.7 to 23.9).
> - **Against simply holding 52% crypto steadily:** Its down days were smaller than holding 52% crypto steadily in 37 of 49 two-year periods (a median 3.0%), but we can't rule out that this was luck.
> - About 1.5 trades a month (up to 5 in a busy month); fees about 0.61% a year.
> - After the worst low of a period it trailed your full mix by a median 5.9 points over the next three months.
> - Holding crypto steadily at the share with the same calm returned 2.7 points a year more than this setting over 2017-2022.

A0's power: CALMER at any setting on 10 of 100 made-up markets with a real effect (PG) and 21 of 100 (PR). Full span: V -0.015 [-0.078, 0.044], p_eq 0.0092, E1 rank p 0.0270.

**w = 12%, 30% crypto, 50% of it BTC** (computed label: NO NOTICEABLE DIFFERENCE; shown as CAN'T TELL, amendment M3)

> **Keep my risk steady, at w = 12% a week**, with your mix (30% crypto, 50% of it BTC). In two-year periods of 2017-2022:
> - It held a median 27% crypto and stepped back 31% of the time.
> - **Against keeping your full mix:** down days 13% smaller; worst fall 29% against 32% (median; the worst period 39% against 41%); it gave up a median 4.1 points a year (from 0.1 to 10.9).
> - **Against simply holding 27% crypto steadily:** Its down days were smaller than holding 27% crypto steadily in 47 of 49 two-year periods (a median 2.3%), but we can't rule out that this was luck.
> - About 1.6 trades a month (up to 5 in a busy month); fees about 0.24% a year.
> - After the worst low of a period it trailed your full mix by a median 1.2 points over the next three months.
> - Holding crypto steadily at the share with the same calm returned 1.6 points a year more than this setting over 2017-2022.

A0's power: CALMER at any setting on 10 of 100 made-up markets with a real effect (PG) and 21 of 100 (PR). Full span: V -0.014 [-0.051, 0.025], p_eq 0.0001, E1 rank p 0.0347.

**w = 12%, 30% crypto, 75% of it BTC** (computed label: NO NOTICEABLE DIFFERENCE; shown as CAN'T TELL, amendment M3)

> **Keep my risk steady, at w = 12% a week**, with your mix (30% crypto, 75% of it BTC). In two-year periods of 2017-2022:
> - It held a median 28% crypto and stepped back 22% of the time.
> - **Against keeping your full mix:** down days 10% smaller; worst fall 26% against 27% (median; the worst period 35% against 36%); it gave up a median 3.7 points a year (from 0.8 to 9.2).
> - **Against simply holding 28% crypto steadily:** Its down days were smaller than holding 28% crypto steadily in 47 of 49 two-year periods (a median 1.4%), but we can't rule out that this was luck.
> - About 1.2 trades a month (up to 5 in a busy month); fees about 0.20% a year.
> - After the worst low of a period it trailed your full mix by a median 0.2 points over the next three months.
> - Holding crypto steadily at the share with the same calm returned 2.1 points a year more than this setting over 2017-2022.

A0's power: CALMER at any setting on 10 of 100 made-up markets with a real effect (PG) and 21 of 100 (PR). Full span: V -0.009 [-0.049, 0.028], p_eq 0.0004, E1 rank p 0.0772.

**w = 12%, 40% crypto, 50% of it BTC** (computed label: NO NOTICEABLE DIFFERENCE; shown as CAN'T TELL, amendment M3)

> **Keep my risk steady, at w = 12% a week**, with your mix (40% crypto, 50% of it BTC). In two-year periods of 2017-2022:
> - It held a median 36% crypto and stepped back 31% of the time.
> - **Against keeping your full mix:** down days 12% smaller; worst fall 37% against 39% (median; the worst period 48% against 50%); it gave up a median 5.1 points a year (from -0.1 to 17.1).
> - **Against simply holding 36% crypto steadily:** Its down days were smaller than holding 36% crypto steadily in 47 of 49 two-year periods (a median 2.2%), but we can't rule out that this was luck.
> - About 1.5 trades a month (up to 5 in a busy month); fees about 0.33% a year.
> - After the worst low of a period it trailed your full mix by a median 0.9 points over the next three months.
> - Holding crypto steadily at the share with the same calm returned 4.3 points a year more than this setting over 2017-2022.

A0's power: CALMER at any setting on 10 of 100 made-up markets with a real effect (PG) and 21 of 100 (PR). Full span: V -0.010 [-0.050, 0.033], p_eq 0.0001, E1 rank p 0.0502.

**w = 12%, 40% crypto, 75% of it BTC** (computed label: NO NOTICEABLE DIFFERENCE; shown as CAN'T TELL, amendment M3)

> **Keep my risk steady, at w = 12% a week**, with your mix (40% crypto, 75% of it BTC). In two-year periods of 2017-2022:
> - It held a median 37% crypto and stepped back 22% of the time.
> - **Against keeping your full mix:** down days 10% smaller; worst fall 33% against 35% (median; the worst period 44% against 46%); it gave up a median 6.3 points a year (from 1.9 to 15.3).
> - **Against simply holding 37% crypto steadily:** Its down days were smaller than holding 37% crypto steadily in 41 of 49 two-year periods (a median 1.9%), but we can't rule out that this was luck.
> - About 1.1 trades a month (up to 5 in a busy month); fees about 0.26% a year.
> - After the worst low of a period it trailed your full mix by a median 0.2 points over the next three months.
> - Holding crypto steadily at the share with the same calm returned 4.9 points a year more than this setting over 2017-2022.

A0's power: CALMER at any setting on 10 of 100 made-up markets with a real effect (PG) and 21 of 100 (PR). Full span: V -0.004 [-0.047, 0.035], p_eq 0.0003, E1 rank p 0.1120.

**w = 12%, 50% crypto, 50% of it BTC** (computed label: NO NOTICEABLE DIFFERENCE; shown as CAN'T TELL, amendment M3)

> **Keep my risk steady, at w = 12% a week**, with your mix (50% crypto, 50% of it BTC). In two-year periods of 2017-2022:
> - It held a median 45% crypto and stepped back 31% of the time.
> - **Against keeping your full mix:** down days 13% smaller; worst fall 45% against 47% (median; the worst period 57% against 60%); it gave up a median 5.9 points a year (from -0.4 to 21.1).
> - **Against simply holding 45% crypto steadily:** Its down days were smaller than holding 45% crypto steadily in 46 of 49 two-year periods (a median 2.1%), but we can't rule out that this was luck.
> - About 1.5 trades a month (up to 5 in a busy month); fees about 0.42% a year.
> - After the worst low of a period it trailed your full mix by a median 1.2 points over the next three months.
> - Holding crypto steadily at the share with the same calm returned 3.1 points a year more than this setting over 2017-2022.

A0's power: CALMER at any setting on 10 of 100 made-up markets with a real effect (PG) and 21 of 100 (PR). Full span: V -0.015 [-0.056, 0.028], p_eq 0.0001, E1 rank p 0.0618.

**w = 12%, 50% crypto, 75% of it BTC** (computed label: NO NOTICEABLE DIFFERENCE; shown as CAN'T TELL, amendment M3)

> **Keep my risk steady, at w = 12% a week**, with your mix (50% crypto, 75% of it BTC). In two-year periods of 2017-2022:
> - It held a median 46% crypto and stepped back 22% of the time.
> - **Against keeping your full mix:** down days 9% smaller; worst fall 39% against 42% (median; the worst period 52% against 55%); it gave up a median 5.8 points a year (from -0.4 to 16.5).
> - **Against simply holding 46% crypto steadily:** Its down days were smaller than holding 46% crypto steadily in 47 of 49 two-year periods (a median 1.5%), but we can't rule out that this was luck.
> - About 1.1 trades a month (up to 5 in a busy month); fees about 0.32% a year.
> - After the worst low of a period it trailed your full mix by a median 0.3 points over the next three months.
> - Holding crypto steadily at the share with the same calm returned 6.3 points a year more than this setting over 2017-2022.

A0's power: CALMER at any setting on 10 of 100 made-up markets with a real effect (PG) and 21 of 100 (PR). Full span: V -0.010 [-0.055, 0.031], p_eq 0.0007, E1 rank p 0.1158.

**w = 12%, 60% crypto, 50% of it BTC** (computed label: NO NOTICEABLE DIFFERENCE; shown as CAN'T TELL, amendment M3)

> **Keep my risk steady, at w = 12% a week**, with your mix (60% crypto, 50% of it BTC). In two-year periods of 2017-2022:
> - It held a median 54% crypto and stepped back 31% of the time.
> - **Against keeping your full mix:** down days 13% smaller; worst fall 52% against 53% (median; the worst period 65% against 68%); it gave up a median 11.6 points a year (from -0.5 to 34.5).
> - **Against simply holding 54% crypto steadily:** Its down days were smaller than holding 54% crypto steadily in 43 of 49 two-year periods (a median 2.8%), but we can't rule out that this was luck.
> - About 1.5 trades a month (up to 5 in a busy month); fees about 0.52% a year.
> - After the worst low of a period it trailed your full mix by a median 2.9 points over the next three months.
> - Holding crypto steadily at the share with the same calm returned 4.1 points a year more than this setting over 2017-2022.

A0's power: CALMER at any setting on 10 of 100 made-up markets with a real effect (PG) and 21 of 100 (PR). Full span: V -0.028 [-0.071, 0.016], p_eq 0.0015, E1 rank p 0.0618.

**w = 12%, 60% crypto, 75% of it BTC** (computed label: NO NOTICEABLE DIFFERENCE; shown as CAN'T TELL, amendment M3)

> **Keep my risk steady, at w = 12% a week**, with your mix (60% crypto, 75% of it BTC). In two-year periods of 2017-2022:
> - It held a median 55% crypto and stepped back 22% of the time.
> - **Against keeping your full mix:** down days 9% smaller; worst fall 45% against 48% (median; the worst period 60% against 64%); it gave up a median 4.7 points a year (from -2.3 to 19.5).
> - **Against simply holding 55% crypto steadily:** Its down days were smaller than holding 55% crypto steadily in 36 of 49 two-year periods (a median 0.6%), but we can't rule out that this was luck.
> - About 1.1 trades a month (up to 5 in a busy month); fees about 0.39% a year.
> - After the worst low of a period it trailed your full mix by a median 1.4 points over the next three months.
> - Holding crypto steadily at the share with the same calm returned 5.4 points a year more than this setting over 2017-2022.

A0's power: CALMER at any setting on 10 of 100 made-up markets with a real effect (PG) and 21 of 100 (PR). Full span: V 0.004 [-0.038, 0.044], p_eq 0.0002, E1 rank p 0.1351.

**w = 15%, 30% crypto, 50% of it BTC** (computed label: NO NOTICEABLE DIFFERENCE; shown as CAN'T TELL, amendment M3)

> **Keep my risk steady, at w = 15% a week**, with your mix (30% crypto, 50% of it BTC). In two-year periods of 2017-2022:
> - It held a median 29% crypto and stepped back 11% of the time.
> - **Against keeping your full mix:** down days 5% smaller; worst fall 30% against 32% (median; the worst period 40% against 41%); it gave up a median 1.2 points a year (from -0.1 to 4.9).
> - **Against simply holding 29% crypto steadily:** Its down days were smaller than holding 29% crypto steadily in 40 of 49 two-year periods (a median 0.8%), but we can't rule out that this was luck.
> - About 1.0 trades a month (up to 4 in a busy month); fees about 0.15% a year.
> - After the worst low of a period it trailed your full mix by a median 0.0 points over the next three months.
> - Holding crypto steadily at the share with the same calm returned 1.9 points a year more than this setting over 2017-2022.

A0's power: CALMER at any setting on 10 of 100 made-up markets with a real effect (PG) and 21 of 100 (PR). Full span: V -0.002 [-0.022, 0.018], p_eq 0.0001, E1 rank p 0.2432.

**w = 15%, 30% crypto, 75% of it BTC** (computed label: NO NOTICEABLE DIFFERENCE; shown as CAN'T TELL, amendment M3)

> **Keep my risk steady, at w = 15% a week**, with your mix (30% crypto, 75% of it BTC). In two-year periods of 2017-2022:
> - It held a median 29% crypto and stepped back 9% of the time.
> - **Against keeping your full mix:** down days 4% smaller; worst fall 27% against 27% (median; the worst period 36% against 36%); it gave up a median 1.9 points a year (from 0.7 to 5.9).
> - **Against simply holding 29% crypto steadily:** Its down days were smaller than holding 29% crypto steadily in 48 of 49 two-year periods (a median 1.0%), but we can't rule out that this was luck.
> - About 0.8 trades a month (up to 4 in a busy month); fees about 0.13% a year.
> - After the worst low of a period it trailed your full mix by a median 0.0 points over the next three months.
> - Holding crypto steadily at the share with the same calm returned 1.2 points a year more than this setting over 2017-2022.

A0's power: CALMER at any setting on 10 of 100 made-up markets with a real effect (PG) and 21 of 100 (PR). Full span: V -0.007 [-0.032, 0.014], p_eq 0.0001, E1 rank p 0.1313.

**w = 15%, 40% crypto, 50% of it BTC** (computed label: NO NOTICEABLE DIFFERENCE; shown as CAN'T TELL, amendment M3)

> **Keep my risk steady, at w = 15% a week**, with your mix (40% crypto, 50% of it BTC). In two-year periods of 2017-2022:
> - It held a median 39% crypto and stepped back 11% of the time.
> - **Against keeping your full mix:** down days 4% smaller; worst fall 38% against 39% (median; the worst period 50% against 50%); it gave up a median 2.5 points a year (from -1.4 to 8.1).
> - **Against simply holding 39% crypto steadily:** Its down days were smaller than holding 39% crypto steadily in 35 of 49 two-year periods (a median 1.1%), but we can't rule out that this was luck.
> - About 0.9 trades a month (up to 4 in a busy month); fees about 0.19% a year.
> - After the worst low of a period it trailed your full mix by a median 0.0 points over the next three months.
> - Holding crypto steadily at the share with the same calm returned 3.9 points a year more than this setting over 2017-2022.

A0's power: CALMER at any setting on 10 of 100 made-up markets with a real effect (PG) and 21 of 100 (PR). Full span: V 0.001 [-0.026, 0.027], p_eq 0.0001, E1 rank p 0.2432.

**w = 15%, 40% crypto, 75% of it BTC** (computed label: NO NOTICEABLE DIFFERENCE; shown as CAN'T TELL, amendment M3)

> **Keep my risk steady, at w = 15% a week**, with your mix (40% crypto, 75% of it BTC). In two-year periods of 2017-2022:
> - It held a median 39% crypto and stepped back 9% of the time.
> - **Against keeping your full mix:** down days 4% smaller; worst fall 34% against 35% (median; the worst period 45% against 46%); it gave up a median 4.3 points a year (from 1.8 to 7.9).
> - **Against simply holding 39% crypto steadily:** Its down days were smaller than holding 39% crypto steadily in 44 of 49 two-year periods (a median 1.2%), but we can't rule out that this was luck.
> - About 0.9 trades a month (up to 4 in a busy month); fees about 0.16% a year.
> - After the worst low of a period it trailed your full mix by a median 0.0 points over the next three months.
> - Holding crypto steadily at the share with the same calm returned 3.1 points a year more than this setting over 2017-2022.

A0's power: CALMER at any setting on 10 of 100 made-up markets with a real effect (PG) and 21 of 100 (PR). Full span: V -0.003 [-0.029, 0.022], p_eq 0.0001, E1 rank p 0.1892.

**w = 15%, 50% crypto, 50% of it BTC** (computed label: NO NOTICEABLE DIFFERENCE; shown as CAN'T TELL, amendment M3)

> **Keep my risk steady, at w = 15% a week**, with your mix (50% crypto, 50% of it BTC). In two-year periods of 2017-2022:
> - It held a median 48% crypto and stepped back 11% of the time.
> - **Against keeping your full mix:** down days 5% smaller; worst fall 45% against 47% (median; the worst period 59% against 60%); it gave up a median 0.4 points a year (from -2.9 to 8.2).
> - **Against simply holding 48% crypto steadily:** Its down days were smaller than holding 48% crypto steadily in 38 of 49 two-year periods (a median 1.2%), but we can't rule out that this was luck.
> - About 0.8 trades a month (up to 4 in a busy month); fees about 0.23% a year.
> - After the worst low of a period it trailed your full mix by a median 0.0 points over the next three months.
> - Holding crypto steadily at the share with the same calm returned 1.9 points a year more than this setting over 2017-2022.

A0's power: CALMER at any setting on 10 of 100 made-up markets with a real effect (PG) and 21 of 100 (PR). Full span: V -0.003 [-0.031, 0.022], p_eq 0.0001, E1 rank p 0.2664.

**w = 15%, 50% crypto, 75% of it BTC** (computed label: NO NOTICEABLE DIFFERENCE; shown as CAN'T TELL, amendment M3)

> **Keep my risk steady, at w = 15% a week**, with your mix (50% crypto, 75% of it BTC). In two-year periods of 2017-2022:
> - It held a median 48% crypto and stepped back 9% of the time.
> - **Against keeping your full mix:** down days 4% smaller; worst fall 41% against 42% (median; the worst period 54% against 55%); it gave up a median 3.4 points a year (from -0.7 to 8.5).
> - **Against simply holding 48% crypto steadily:** Its down days were smaller than holding 48% crypto steadily in 41 of 49 two-year periods (a median 0.9%), but we can't rule out that this was luck.
> - About 0.8 trades a month (up to 4 in a busy month); fees about 0.19% a year.
> - After the worst low of a period it trailed your full mix by a median 0.1 points over the next three months.
> - Holding crypto steadily at the share with the same calm returned 4.5 points a year more than this setting over 2017-2022.

A0's power: CALMER at any setting on 10 of 100 made-up markets with a real effect (PG) and 21 of 100 (PR). Full span: V -0.007 [-0.033, 0.018], p_eq 0.0001, E1 rank p 0.1892.

**w = 15%, 60% crypto, 50% of it BTC** (computed label: NO NOTICEABLE DIFFERENCE; shown as CAN'T TELL, amendment M3)

> **Keep my risk steady, at w = 15% a week**, with your mix (60% crypto, 50% of it BTC). In two-year periods of 2017-2022:
> - It held a median 58% crypto and stepped back 11% of the time.
> - **Against keeping your full mix:** down days 4% smaller; worst fall 52% against 53% (median; the worst period 66% against 68%); it gave up a median 2.8 points a year (from -2.7 to 13.3).
> - **Against simply holding 58% crypto steadily:** Its down days were smaller than holding 58% crypto steadily in 32 of 49 two-year periods (a median 0.7%), but we can't rule out that this was luck.
> - About 0.8 trades a month (up to 4 in a busy month); fees about 0.25% a year.
> - After the worst low of a period it trailed your full mix by a median 0.0 points over the next three months.
> - Holding crypto steadily at the share with the same calm returned 4.4 points a year more than this setting over 2017-2022.

A0's power: CALMER at any setting on 10 of 100 made-up markets with a real effect (PG) and 21 of 100 (PR). Full span: V 0.007 [-0.017, 0.028], p_eq 0.0001, E1 rank p 0.2934.

**w = 15%, 60% crypto, 75% of it BTC** (computed label: NO NOTICEABLE DIFFERENCE; shown as CAN'T TELL, amendment M3)

> **Keep my risk steady, at w = 15% a week**, with your mix (60% crypto, 75% of it BTC). In two-year periods of 2017-2022:
> - It held a median 58% crypto and stepped back 9% of the time.
> - **Against keeping your full mix:** down days 3% smaller; worst fall 47% against 48% (median; the worst period 63% against 64%); it gave up a median 4.0 points a year (from -1.6 to 12.0).
> - **Against simply holding 58% crypto steadily:** Its down days were smaller than holding 58% crypto steadily in 22 of 49 two-year periods (a median -0.1%), but we can't rule out that this was luck.
> - About 0.7 trades a month (up to 4 in a busy month); fees about 0.22% a year.
> - After the worst low of a period it trailed your full mix by a median 0.2 points over the next three months.
> - Holding crypto steadily at the share with the same calm returned 2.0 points a year more than this setting over 2017-2022.

A0's power: CALMER at any setting on 10 of 100 made-up markets with a real effect (PG) and 21 of 100 (PR). Full span: V -0.001 [-0.026, 0.020], p_eq 0.0001, E1 rank p 0.2432.

## Deviations and notes

- **None in the run.** It ran once, on the pinned folders, with the plan's grid, and completed.
- **The tiers ran twice.** On `8f87bd8` (amendment M3) the full and deep tiers and the dashboard passed, but ruff
  found 5 style errors in A0's diagnostic `a0_first_range/block_check.py` (imports and two statements on one line).
  The fix (`2a43cc4`) changed no logic, and the three tiers were rerun on it (at `-n 4`) before run 0.
- **Amendment M3 (the owner, 2026-11-25):** A0's alarm A0-4 (PG's lower tail 96 of 400). The decision rules are
  unchanged; NO NOTICEABLE DIFFERENCE, SMALLER BUT BELOW NOTICE and ROUGHER are shown with the CAN'T TELL sentence.
  The computed labels are reported above as they came out.
- **A0's power next to every CAN'T TELL:** CALMER at any setting on 10 of 100 PG panels and 21 of 100 PR panels; E1 on
  87-100 and 71-100. So a CALMER label was unlikely even if the tool helped; this run's E1 results (holding at w 8%
  and 10%) fit that.
- **"Stepped back" in the cards** is the share of days with q < 1 (rows), not of Mondays.
- **The same-calm return** on each card is CAGR(X_eq) − CAGR(rule) over the full span (`flags`), a point estimate.

## Reproduce

```bash
uv run python research/keep-risk-steady/run.py --workers 4    # refuses: run 0 is recorded (RUNLOG)
```

The tables above come from `decision.json` and `spans.csv`; every number can be rebuilt from `runs.parquet`,
`spans.parquet` and `series.parquet` in `results/keep-risk-steady/run0/` (not committed).
