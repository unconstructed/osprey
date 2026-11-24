# vol-steady: results of run 0 (SCOUTING)

> **SCOUTING ONLY:** the reference engine, the placeholder costs, and exchange candles in place of Base prices. Not
> NautilusTrader. The lead wrote this on 2026-11-24 from `results/vol-steady/train/run0/summary.json`.
> - Run 0 ran on commit `cc03c2a`, after the full tier (2378 passed, 100% branch coverage) and the deep profile (2362
>   passed), with a clean tree.
> - The owner approved it after A0's power alarm
>   ([reports/director/2026-11-24-owner-answer-vol-a0-power.md](../../reports/director/2026-11-24-owner-answer-vol-a0-power.md)).
> - Validate-window looks used: 0. The test window was not read.

## Verdict: NO EDGE (headline: NO EDGE)

**In plain words.** The rule holds BTC and ETH up to a crypto share, and steps back in quarters when crypto has been
wilder than a target level. Over 2018-2022, out of sample:

- **It made money:** +210%, with a worst fall of 47%. Holding the same mix without the scaling made +170%, with a
  worst fall of 44%.
- **The edge over holding was small, and could be luck.** Its risk-adjusted return (Sharpe 0.80 against 0.72) beat
  holding by 0.08, but a test that resamples the history says a gap that size happens by chance about 1 time in 4.
- **It did not cut falls any better than simply holding less crypto.** Holding its own average mix, never stepping
  back, did better on every measure: Sharpe 0.98, +391%, worst fall 45%.
- **The timing looked meaningful with one search seed and not with the other.** With seed A, only 3 of 207 copies
  of its schedule shifted to other weeks did as well. With seed B, 57 of them did, and without the two bear years
  even seed A's lead disappears. A result that depends on the seed is fragile.
- **After 2018 the search mostly switched the scaling off.** Trained on 2017 only, it stepped back half the time in
  2018, and the 2018 crash is where its timing helped. From 2019 on, each fold chose a target near 100% a year,
  above crypto's usual volatility. So it held the full share about 90-97% of the days.

So scaling by plain volatility, as tested here, gives no edge we can trust. The owner's other angles were written down
before this run read any price
([the record](../../reports/director/2026-11-24-owner-answer-vol-a0-power.md)): downside volatility only, the
volatility trend, a forecast, and volatility as a crash warning. Downside volatility fits what this run saw: wild
up-moves in 2020-21 made the rule step back from rallies.

## Numbers (seed A, Kraken, 1820 out-of-sample days, 2018-01-03 .. 2023-01-01, costs 1x)

| Series | Sharpe | Total return | Worst fall | Worst day |
|---|---|---|---|---|
| S, the rule (walk-forward) | 0.80 | +210% | −47.3% | −14.7% |
| R_0, S's schedule run as one book | 0.86 | +247% | −41.5% | −17.0% |
| N0, always hold the fold's share s | 0.72 | +170% | −44.4% | −12.6% |
| X, hold S's average mix of each fold | 0.98 | +391% | −45.0% | −22.6% |
| B1, buy and hold BTC | 0.43 | +18% | −81.4% | −38.9% |
| B2, 50/50 BTC/USDC monthly | 0.43 | +56% | −53.6% | −17.3% |
| S at 2x costs | 0.79 | +205% | −47.3% | |
| S on Binance (folds 1-4) | 1.13 | +342% | −47.2% | |

## The criteria (PLAN.md section 11; TP 11)

| ID | Question | Seed A | Seed B | Holds |
|---|---|---|---|---|
| E1 | Timing beats the same schedule shifted in time | rank p 0.019 (3 of 207 shifts at or above) | rank p 0.279 | A only |
| E2 | Beats holding the same mix | D = +0.083, p 0.245 | D = +0.078, p 0.305 | No |
| E3 | Cuts falls beyond holding less crypto | S −47.3% / MC p5 −69.4% against X −45.0% / −67.7% | S −45.4% / −66.9% against X −39.3% / −67.4% | No |
| E4 | Survives doubled costs | S 0.79 > N0 0.72 | 0.66 > 0.59 | Yes |
| E5 | Not fragile (seeds and check day) | (a) E1 and G5(a) differ between seeds; (b) every weekday keeps ≥ 0.7 × Sharpe | | No |
| E6 | Not one year | the excess over N0 is negative in 2021 (−0.144), 2018 and 2022 | | No |
| E7 | Not the boom years | without 2020: E1 holds, E2 fails | | No |
| E8 | Binance | E1 rank p 0.090, E2 p 0.148 | | No |
| P | Enough information | 45 share changes in all 5 folds | 47 | Yes |

## The gates (AGENTS.md defaults; seed A)

| Gate | Result |
|---|---|
| G1, out-of-sample Sharpe ≥ 1.0 | FAIL (0.80) |
| G2, the same with costs doubled > 0.5 | PASS (0.79) |
| G3, deflated Sharpe ≥ 0.95 | FAIL (0.001 effective; 2,400 trials, about 16 effective) |
| G4, PBO ≤ 0.25 | FAIL (0.70) |
| G5, ±20% plateau | PASS |
| G6, Monte Carlo 95th-percentile fall within 35% | FAIL (−69.4%) |
| G7, beats buy-and-hold BTC and 50/50 | PASS (also without the best year and the best two years) |
| G8-excess, no regime carries the excess | FAIL |
| R1, a few trades a month | PASS (0.74 orders per 30 days; at most 5) |
| The allowed shares S(s_k) | FAIL (G6 at every share from 0.30 to 0.60) |

## What the search chose

| Fold (test year) | Lookback L | Target τ | Share s | Time at the full share | Mean step q |
|---|---|---|---|---|---|
| 0 (2018) | 10 days | 0.46 | 0.31 | 15% | 0.52 |
| 1 (2019) | 17 | 1.01 | 0.56 | 86% | 0.96 |
| 2 (2020) | 15 | 1.03 | 0.35 | 94% | 0.97 |
| 3 (2021) | 53 | 0.97 | 0.55 | 69% | 0.92 |
| 4 (2022) | 17 | 1.01 | 0.37 | 92% | 0.98 |

- **The final pick on all the train years** (θ_final, seed A) is L = 15, τ = 1.05 and s = 0.40. With τ = 1.05, the
  rule steps back only when crypto's volatility runs above 105% a year.
- **The 2018 step-back** ran from 2018-01-03 to 2018-07-08, while the 50/50 basket fell 42%. It is the bulk of the
  rule's timing value.

## Descriptions (decide nothing)

- **Without both bear years (2018 and 2022):** E1's rank p is 0.317. The timing lead lives in the bear years.
- **Correlations:**
  - with N0 0.95, and with rebalance-steady's S 0.96, so the rule is close to holding;
  - with trend-steady's S 0.75.
- **Check days:** every weekday gives a Sharpe of 0.71-0.82, and daily checks 0.75 (95 orders).
- **Costs:**
  - customer fees about 0.29% a year at a 10,000 USD wallet;
  - gas about 1.3 USD a year;
  - the Sharpe with gas charged is 0.88 at 500 USD.

## Record

- **The run:** run 0 on commit `cc03c2a`, config hash `266c6d43fb1789d7…`, snapshot `1746a21b75683e76`.
  - 2 seeds × 6 studies × 200 trials = 2,400 trials, none failed.
  - 190 s; the projection was 2.8 CPU-minutes.
- **Before the run:**
  - Amendments M1 (the build's readings), A1 (N = 200) and A0 (the power alarm; the owner: run it), all synthetic.
  - The full tier first failed on `2bdd7fd` for a test that read the committed plan (TESTING.md #68, a test bug). It
    was fixed on `efab65a` and formatted on `cc03c2a`, and the tiers passed there.
- **Deviations:** none from the plan as amended.
- **No validate look:** NO EDGE earns none (TP 13).
