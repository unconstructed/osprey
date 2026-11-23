# protect-gains: results of run 0 (SCOUTING)

> **SCOUTING ONLY.** Every number comes from the lab's reference portfolio engine (`lab/runner/portfolio.py`, driven
> by `lab/runner/protect.py`), not NautilusTrader, with the **placeholder** costs of `config/costs.yaml` and exchange
> candles standing in for Base prices. The study claims no edge and approves nothing. Written by the lead on
> 2026-11-23 from run 0's `decision.json`, `runs.parquet` and `stops.parquet`.

## In plain words

We put a "protect my gains" brake on top of the "hold this mix" tool and replayed it over 49 overlapping two-year
periods (2017-2022, Kraken prices), on 6 mixes from 30% to 70% crypto, for every line level and buy-back way in the
plan. That is 82,050 simulations.

**The answer the rules give is: no starting setting for either line, so the owner decides.**

- **Line A, "sell if it falls X% below its highest value", at 10% with the trend buy-back, was the only setting that
  gave the protection the plan asks for.** In a bad period (the 90th-percentile two-year fall) the wallet fell 26%
  instead of 65%, every mix was protected, and the worst fall was 31% instead of 74%.
- **But that setting failed the whipsaw rule.** It fired in every two-year period, a median of 3 times, and sat in
  USDC about two thirds of the time. After 36% of its buy-backs it sold again within a month; the plan allows at
  most 25%.
- **It also cost a lot in normal times.** A two-year wallet ended a median 23% below the same wallet without the
  brake, and the brake did better in only 28% of the periods.
- **Every looser line A level, and every line B level, failed to cut the bad-case fall by the plan's one third for
  every mix.** Line A at 15-20% (trend or wait-180) cut the pooled bad case by a third, but not for every mix;
  most settings cut it by less than a quarter, and some made the worst fall deeper.
- **"Buy back when prices return to where we sold" did not work.** At tight levels it sold and bought back again and
  again; the bad-case fall barely moved (87-93% of the fall without the brake at 10%), and up to half of its
  buy-backs were sold again within a month.
- **Line B ("keep Y% of my profit") rarely helped.** It cut the bad-case fall by at most 22% and protected no mix to
  the plan's standard. It sold below the deposit 101 times, the worst 17% below. The check is daily, so a crash day
  can carry it through the line.
- **Should the brake's trades count against the tool's 2-a-month limit?** The run cannot say, because no line had a
  starting setting under either reading. "Counts" stays in force.

The brake does what it says on a steep crash, but the tight settings that do that are expensive and jumpy, and the
gentle settings barely help.

## Headline (`decision.json`)

| Item | Result |
|---|---|
| Line A default (D1-D2) | **NO DEFAULT.** D1: meaningful only at X = 10% with the trend buy-back. D2: trend's re-stop share 36.4% > 25%, so not eligible; wait-30 has NO DEFAULT; case "neither: the owner decides" |
| Line B default | **NO DEFAULT.** D1: no level is meaningful for any buy-back way |
| Shown first (D3) | none |
| Limit reading (D6) | **"counts" in force**; recommended "counts" because no line type has a default under both readings, so nothing was compared |
| Robustness (D4) | Line A, line B and "first": **MISSING (boom: without the best 2)**. The other checks gave the same answer: Binance 1x NO DEFAULT, Kraken 2x NO DEFAULT, without 2017 NO DEFAULT. Without 2017 and 2020 only windows 12 and 48 remain (fewer than 12), as the plan expected |
| Promise number (D5) | **MISSING** for both lines (no default) |
| Stop events at the defaults | none (no default) |

## The tool alone (R, the reference)

The "hold this mix" tool at the owner's default (band 0.30, 2 trades a month), no brake, Kraken 1x, 294 two-year
windows:

| Mix (crypto s, BTC's share f) | Median two-year worst fall | Worst | 90th percentile (Q0, per mix) |
|---|---|---|---|
| 30%, 50% | 30.4% | 41.1% | 40.6% |
| 30%, 75% | 27.1% | 38.5% | 38.5% |
| 50%, 50% | 46.9% | 62.0% | 62.0% |
| 50%, 75% | 41.3% | 55.3% | 54.6% |
| 70%, 50% | 59.0% | 74.2% | 74.2% |
| 70%, 75% | 52.5% | 69.5% | 69.4% |
| **All 6 (the pool)** | **40.6%** | **74.2%** | **Q0 = 64.9%** |

The tool keeps buying crypto back to its mix as prices fall, so in 2018 and 2022 a 30% crypto mix still fell
about 40%. The median two-year total return was +114%.

## The one setting that protected: line A at 10%, trend buy-back

**Kraken 1x, "counts" reading.** The "separate" reading gives the same numbers, because a trend buy-back was never
held by the tool's wait.

- **Protection:**
  - Q = 25.9% against Q0 = 64.9%, so 0.40 of Q0 (the plan needs at most 0.67).
  - All 6 mixes pass on their own.
  - The worst fall was 31.1% against 74.2%.
- **Robustness:** it is meaningful on Binance too (Q 25.6%) and at 2x costs (Q 26.7%), with re-stop shares of 34.5%
  and 36.4%. It fails D2 there as well.
- **How often it acts:**
  - It fired in every window: a median of 3 stops per two years, at most 6.
  - Over the pool the stops fall on 92 distinct sale dates: 18 in 2017, 30 in 2018, 22 in 2019, 9 in 2020, 12 in
    2021 and 1 in 2022.
  - Median time in USDC: 68% of the days. A median stop stayed out 91 days, and 196 stops were never bought back
    before the window ended.
- **Whipsaw:** 282 of its 774 buy-backs (36.4%) were followed by another stop within 30 days. D2 allows 25%.
- **Cost against the tool alone:**
  - Median C 22.8%, mean 21.4%. The brake ended ahead in 28% of the windows.
  - By the window's start year (median C): 2017 +31%, 2018 +0.4%, 2019 +51%, 2020 +18%, 2021 −27% (the brake
    helped).
  - Per mix the median cost was 15-20% at 30% crypto, 36-40% at 50% and 54-59% at 70%.
  - The brake's own trading fees came to a median 0.33% of the wallet a year, plus 0.01% of gas (the tool's own:
    0.02% and 0.004%).
- **How far below the line it sold:**
  - Largest: 19.0% below the line, at the close of 12 March 2020 (timestamp 2020-03-13 00:00 UTC), when BTC fell
    about 39% in a day.
  - 95th percentile: 7.7%.
  - The same day's sale missed a 71% rebound of the mix's index before the trend buy-back came.

At 15% (trend) the bad-case fall was 39.7% (0.61 of Q0), but only 3 of 6 mixes passed (both 30% crypto mixes and the
50% mix with 75% BTC did not), and the median cost was 26.0%. Line A at 10% with wait-180 (a slow customer) protected 4
of 6 mixes.

## What did not work

- **The rebound buy-backs (r = −5%, 0, +5%):**
  - At X = 10% they cut Q only to 0.87-0.93 of Q0, and re-stopped after 44-51% of buy-backs.
  - At X = 25-40% several made the worst fall deeper than the tool alone (up to 81.2% against 74.2%).
  - Buying back "near where we sold" in a falling market sells again a few days later, and each round trip loses
    the gap plus costs.
- **wait-30 (an attentive customer):** at best 0.66 of Q0 with 2 of 6 mixes (X = 10%), with 38% re-stops.
- **Line B (Y = 40-80%):**
  - It was active in 69-92% of windows and fired in 63-74%.
  - It cut Q to at best 0.78 of Q0 (wait-180, Y = 70%), with no mix passing, and its worst fall reached 84.0% in
    places.
  - Where it was active, a wallet kept a median 67-71% of its peak profit at the window's end (wait-30).
  - It sold below the deposit 101 times over the stage-1 pool, the worst 17.2% below D.
- **Loose line A levels (X ≥ 25%):** fired in 52-85% of windows, with Q at 0.78-1.08 of Q0 and no mix passing.

## For the owner

The pre-registered rules give no starting setting. Options, each the owner's call:

1. **Offer the brake with no suggested setting.** The customer picks a line and a buy-back, and the app shows this
   study's table for their mix: how often it fires, how much it cut the bad case, what it cost, and how far below
   the line it sold. This keeps the tool honest about the trade-off.
2. **Suggest line A at 10% with the trend buy-back anyway.** This overrides the whipsaw rule (36% re-stops against
   25%) after seeing the result, so it would be the owner's written decision, not a lab default. Its cost is large
   in normal markets: a median 23% over two years, and more for higher-crypto mixes.
3. **Don't offer the brake for now.** Point customers who want less risk to a lower crypto share instead. In this
   run, going from 70% to 30% crypto cut the tool's bad-case fall from 74% to about 41% with no brake at all.

Whichever is chosen, the app should not promise a floor. Even the 10% line sold up to 19% below it on 2020-03-13.

## Full table (stage 1: Kraken 1x, "counts" reading, 294 windows per row)

Q0 = 64.9% and R's worst fall is 74.2% for every row. A row passes D1 only with Q / Q0 ≤ 0.667, 6 of 6 mixes
protected and a worst fall ≤ 74.2%. C > 0 means the brake ended below the tool alone. The "separate" reading's table
and the Binance 1x and Kraken 2x tables are in `decision.json` (`stage2.tables`).

| Line | Level | Buy-back | Fires (share of windows) | Q, 90th-pct fall | Q / Q0 | Mixes protected | Worst fall | C̃ (median cost) | C̄ (mean cost) | Re-stops | Median time in USDC | Largest sale below the line |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | X = 10% | trend | 100% | 25.9% | 0.40 | 6 of 6 | 31.1% | +22.8% | +21.4% | 36% | 68% | 19.0% |
| A | X = 15% | trend | 100% | 39.7% | 0.61 | 3 of 6 | 48.4% | +26.0% | +18.0% | 17% | 48% | 26.1% |
| A | X = 20% | trend | 89% | 42.2% | 0.65 | 2 of 6 | 61.2% | +9.1% | +10.4% | 3% | 28% | 26.2% |
| A | X = 25% | trend | 85% | 50.5% | 0.78 | 0 of 6 | 53.0% | +6.4% | +11.1% | 0% | 25% | 26.6% |
| A | X = 30% | trend | 77% | 54.8% | 0.84 | 0 of 6 | 56.8% | +3.6% | +9.5% | 0% | 19% | 21.3% |
| A | X = 35% | trend | 63% | 58.3% | 0.90 | 0 of 6 | 63.9% | +0.0% | +8.8% | 0% | 15% | 15.3% |
| A | X = 40% | trend | 52% | 60.5% | 0.93 | 0 of 6 | 70.5% | +0.0% | +5.7% | 0% | 5% | 11.9% |
| A | X = 10% | rebound+5 | 100% | 57.6% | 0.89 | 1 of 6 | 65.7% | +16.1% | +18.0% | 44% | 41% | 27.4% |
| A | X = 15% | rebound+5 | 100% | 52.2% | 0.80 | 0 of 6 | 68.8% | +16.0% | +12.7% | 18% | 28% | 26.1% |
| A | X = 20% | rebound+5 | 89% | 65.5% | 1.01 | 0 of 6 | 71.5% | +14.7% | +14.8% | 5% | 7% | 26.2% |
| A | X = 25% | rebound+5 | 85% | 66.3% | 1.02 | 0 of 6 | 78.8% | +13.6% | +12.8% | 2% | 5% | 26.6% |
| A | X = 30% | rebound+5 | 77% | 68.4% | 1.05 | 0 of 6 | 80.7% | +7.7% | +10.0% | 1% | 4% | 21.3% |
| A | X = 35% | rebound+5 | 63% | 62.4% | 0.96 | 0 of 6 | 70.7% | +2.0% | +6.8% | 0% | 2% | 15.3% |
| A | X = 40% | rebound+5 | 52% | 56.5% | 0.87 | 0 of 6 | 76.5% | +0.0% | +2.0% | 0% | 1% | 11.9% |
| A | X = 10% | rebound0 | 100% | 56.6% | 0.87 | 0 of 6 | 76.4% | +25.0% | +23.8% | 48% | 29% | 19.0% |
| A | X = 15% | rebound0 | 100% | 58.1% | 0.90 | 0 of 6 | 71.8% | +15.6% | +14.8% | 20% | 22% | 26.1% |
| A | X = 20% | rebound0 | 89% | 60.9% | 0.94 | 0 of 6 | 72.5% | +10.5% | +11.4% | 5% | 5% | 26.2% |
| A | X = 25% | rebound0 | 85% | 65.2% | 1.00 | 0 of 6 | 70.7% | +11.8% | +11.6% | 1% | 3% | 26.6% |
| A | X = 30% | rebound0 | 77% | 63.9% | 0.98 | 0 of 6 | 80.0% | +3.0% | +8.0% | 3% | 3% | 21.4% |
| A | X = 35% | rebound0 | 63% | 64.2% | 0.99 | 0 of 6 | 76.5% | +1.3% | +6.3% | 0% | 2% | 15.4% |
| A | X = 40% | rebound0 | 52% | 60.7% | 0.94 | 0 of 6 | 75.1% | +0.0% | +1.9% | 0% | 1% | 11.9% |
| A | X = 10% | rebound-5 | 100% | 60.4% | 0.93 | 0 of 6 | 74.0% | +17.3% | +21.4% | 51% | 26% | 19.0% |
| A | X = 15% | rebound-5 | 100% | 57.3% | 0.88 | 0 of 6 | 69.4% | +13.6% | +13.4% | 19% | 12% | 26.1% |
| A | X = 20% | rebound-5 | 89% | 62.1% | 0.96 | 0 of 6 | 71.2% | +8.3% | +10.5% | 8% | 4% | 26.2% |
| A | X = 25% | rebound-5 | 85% | 65.9% | 1.02 | 0 of 6 | 74.5% | +9.3% | +10.5% | 1% | 3% | 26.6% |
| A | X = 30% | rebound-5 | 77% | 68.6% | 1.06 | 0 of 6 | 81.2% | +2.6% | +7.1% | 3% | 2% | 21.4% |
| A | X = 35% | rebound-5 | 63% | 65.6% | 1.01 | 0 of 6 | 77.9% | +0.0% | +5.6% | 0% | 2% | 15.4% |
| A | X = 40% | rebound-5 | 52% | 60.6% | 0.93 | 0 of 6 | 74.6% | +0.0% | +1.6% | 0% | 1% | 11.9% |
| A | X = 10% | wait30 | 100% | 43.1% | 0.66 | 2 of 6 | 57.5% | +5.0% | -4.7% | 38% | 33% | 19.0% |
| A | X = 15% | wait30 | 100% | 48.9% | 0.75 | 0 of 6 | 72.3% | +7.8% | +3.9% | 14% | 16% | 26.1% |
| A | X = 20% | wait30 | 89% | 59.2% | 0.91 | 0 of 6 | 72.1% | +7.4% | +8.3% | 10% | 12% | 26.2% |
| A | X = 25% | wait30 | 85% | 64.9% | 1.00 | 0 of 6 | 77.2% | +3.9% | +10.0% | 6% | 8% | 27.9% |
| A | X = 30% | wait30 | 77% | 69.9% | 1.08 | 0 of 6 | 80.3% | +0.0% | +6.7% | 0% | 4% | 22.7% |
| A | X = 35% | wait30 | 63% | 63.9% | 0.99 | 0 of 6 | 77.3% | +0.0% | +4.8% | 0% | 4% | 15.3% |
| A | X = 40% | wait30 | 52% | 63.0% | 0.97 | 0 of 6 | 79.7% | +0.0% | +1.8% | 0% | 4% | 11.9% |
| A | X = 10% | wait180 | 100% | 31.2% | 0.48 | 4 of 6 | 41.7% | +31.2% | +23.3% | 36% | 74% | 19.0% |
| A | X = 15% | wait180 | 100% | 41.6% | 0.64 | 3 of 6 | 54.8% | +20.9% | +15.7% | 15% | 55% | 26.1% |
| A | X = 20% | wait180 | 89% | 48.2% | 0.74 | 1 of 6 | 55.4% | +17.5% | +15.4% | 11% | 49% | 26.2% |
| A | X = 25% | wait180 | 85% | 54.2% | 0.84 | 0 of 6 | 62.0% | +12.5% | +15.2% | 5% | 38% | 26.6% |
| A | X = 30% | wait180 | 77% | 57.9% | 0.89 | 0 of 6 | 72.8% | +13.3% | +16.5% | 5% | 25% | 21.3% |
| A | X = 35% | wait180 | 63% | 60.1% | 0.93 | 0 of 6 | 73.3% | +0.0% | +9.9% | 0% | 25% | 15.3% |
| A | X = 40% | wait180 | 52% | 56.4% | 0.87 | 0 of 6 | 72.9% | +0.0% | +7.5% | 0% | 5% | 11.9% |
| B | Y = 40% | trend | 65% | 57.2% | 0.88 | 0 of 6 | 73.6% | +0.0% | +7.3% | 7% | 13% | 28.1% |
| B | Y = 50% | trend | 70% | 54.6% | 0.84 | 0 of 6 | 71.1% | +0.0% | +8.2% | 12% | 17% | 26.9% |
| B | Y = 60% | trend | 67% | 55.9% | 0.86 | 0 of 6 | 74.2% | +0.0% | +7.2% | 14% | 22% | 27.6% |
| B | Y = 70% | trend | 73% | 53.0% | 0.82 | 0 of 6 | 74.2% | +0.0% | +7.4% | 19% | 25% | 9.0% |
| B | Y = 80% | trend | 63% | 52.9% | 0.82 | 0 of 6 | 74.2% | +0.0% | +5.0% | 29% | 12% | 9.9% |
| B | Y = 40% | rebound+5 | 65% | 60.0% | 0.92 | 0 of 6 | 81.1% | +3.1% | +5.9% | 6% | 2% | 25.3% |
| B | Y = 50% | rebound+5 | 70% | 65.3% | 1.01 | 0 of 6 | 82.5% | +3.2% | +6.4% | 7% | 3% | 24.2% |
| B | Y = 60% | rebound+5 | 67% | 64.5% | 0.99 | 0 of 6 | 82.6% | +4.1% | +7.7% | 14% | 3% | 25.1% |
| B | Y = 70% | rebound+5 | 73% | 61.5% | 0.95 | 0 of 6 | 79.2% | +5.4% | +7.3% | 16% | 3% | 11.6% |
| B | Y = 80% | rebound+5 | 63% | 61.5% | 0.95 | 0 of 6 | 77.0% | +0.0% | +2.7% | 31% | 2% | 12.9% |
| B | Y = 40% | rebound0 | 65% | 62.9% | 0.97 | 0 of 6 | 80.9% | +2.6% | +5.2% | 5% | 2% | 25.6% |
| B | Y = 50% | rebound0 | 70% | 63.9% | 0.99 | 0 of 6 | 82.7% | +2.4% | +5.7% | 8% | 2% | 25.0% |
| B | Y = 60% | rebound0 | 67% | 64.0% | 0.99 | 0 of 6 | 78.1% | +4.2% | +6.8% | 12% | 3% | 25.6% |
| B | Y = 70% | rebound0 | 73% | 63.8% | 0.98 | 0 of 6 | 77.8% | +5.8% | +7.7% | 16% | 3% | 11.1% |
| B | Y = 80% | rebound0 | 63% | 63.5% | 0.98 | 0 of 6 | 76.7% | +0.6% | +5.6% | 31% | 2% | 12.7% |
| B | Y = 40% | rebound-5 | 65% | 63.1% | 0.97 | 0 of 6 | 80.7% | +0.5% | +4.5% | 6% | 1% | 25.3% |
| B | Y = 50% | rebound-5 | 70% | 64.7% | 1.00 | 0 of 6 | 82.4% | +0.9% | +4.9% | 8% | 2% | 25.0% |
| B | Y = 60% | rebound-5 | 67% | 64.3% | 0.99 | 0 of 6 | 81.5% | +2.6% | +6.2% | 13% | 2% | 25.8% |
| B | Y = 70% | rebound-5 | 73% | 63.7% | 0.98 | 0 of 6 | 80.8% | +5.3% | +6.7% | 17% | 2% | 11.1% |
| B | Y = 80% | rebound-5 | 63% | 63.2% | 0.97 | 0 of 6 | 76.5% | +0.6% | +4.9% | 30% | 2% | 12.7% |
| B | Y = 40% | wait30 | 65% | 62.7% | 0.97 | 0 of 6 | 80.2% | +0.0% | +3.1% | 11% | 4% | 25.5% |
| B | Y = 50% | wait30 | 70% | 67.2% | 1.04 | 0 of 6 | 84.0% | +0.0% | +5.4% | 13% | 4% | 29.5% |
| B | Y = 60% | wait30 | 67% | 65.0% | 1.00 | 0 of 6 | 75.6% | +0.0% | +2.7% | 15% | 8% | 24.7% |
| B | Y = 70% | wait30 | 73% | 58.0% | 0.89 | 0 of 6 | 74.7% | +0.0% | -0.3% | 15% | 8% | 12.4% |
| B | Y = 80% | wait30 | 63% | 59.5% | 0.92 | 0 of 6 | 74.5% | +0.0% | +0.5% | 27% | 4% | 14.6% |
| B | Y = 40% | wait180 | 65% | 55.1% | 0.85 | 0 of 6 | 73.4% | +0.0% | +6.3% | 6% | 23% | 26.0% |
| B | Y = 50% | wait180 | 70% | 54.4% | 0.84 | 0 of 6 | 69.5% | +0.0% | +6.5% | 9% | 25% | 26.5% |
| B | Y = 60% | wait180 | 67% | 54.7% | 0.84 | 0 of 6 | 74.2% | +0.0% | +10.4% | 14% | 25% | 25.9% |
| B | Y = 70% | wait180 | 73% | 50.8% | 0.78 | 0 of 6 | 74.2% | +7.6% | +10.2% | 14% | 36% | 18.5% |
| B | Y = 80% | wait180 | 63% | 52.5% | 0.81 | 0 of 6 | 74.2% | +0.0% | +3.9% | 31% | 25% | 9.9% |

## Record

- **Run 0:** commit `5e99d68`, config hash `8ce56c34fad2aed6fbe4e70a51f120b01be23f89f1e85ad62ff2182eedd35368`,
  snapshot `1746a21b75683e76`, clean tree.
- **Tests on that commit:** full tier 2200 passed with 100% branch coverage (6600 statements, 1980 branches); deep
  profile 2186 passed; dashboard 86 passed.
- **Size:**
  - 82,050 runs (stage 1: 42,630; stage 2: 39,420), 0 failed, 191,858 stops logged, no consistency stop.
  - 753 s on 3 worker processes; A1 had projected 95.1 CPU-minutes. Results do not depend on the number of
    workers (tested).
- **Data:** train window only. No validate or test bar was read. Validate-window looks used: 0.

**Deviations:** none from the plan as amended (A1, A2). The two-best-years boom check is MISSING, as section 8
expected.
