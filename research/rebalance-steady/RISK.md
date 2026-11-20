# rebalance-steady: risk-officer review of the train results (SCOUTING)

Written 2026-11-20 by `risk-officer`. I reviewed RESULTS.md as it stood uncommitted on top of `a6ec37c`, along with
PLAN.md sections 4, 9 and 14 and run 0's stored outputs: `summary.json`, `oos.parquet`, `evaluations.parquet` and
the final studies' logged trial returns. I read no bars and ran no backtests. I recomputed numbers from the stored
outputs only, and I edited no file except this one. `config/risk_levels.yaml` still has run 0's start hash
`158d7c9f10eeb664618188455255ca099cc2b265c32833df8a1a37ffab3f16f8`.

Every return and drawdown below is **SCOUTING**. All of them come from the reference engine
(`lab/runner/portfolio.py`), not NautilusTrader, with the placeholder costs. Exchange candles stand in for Base
prices, and USDC is priced at 1.

## Outcome

- **No blocking item.** No reported configuration breaks the Steady limits, and RESULTS.md misstates no risk
  number. Every drawdown, worst day, Monte Carlo percentile and overshoot statistic I recomputed matches
  `summary.json` exactly.
- **Nothing here is approved.** The verdict is NO EDGE, the numbers are scouting and there is no audit. So I write
  no risk note in `reports/rebalance-steady/`, set no per-strategy limits and write nothing in `exports/`.
- **My budget proposal (PLAN.md section 9) stands as written.** Section 3 below gives four points for the owner
  before any number is computed.
- **Four small wording requests** for RESULTS.md are in section 4. None is blocking.

## 1. The Steady limits against the results

Limits as read at run 0's start: coins BTC, ETH and USDC; min_cash 0.20; max_coin 0.60; budget `TBD` (MISSING).
With the headroom h = 0.02, targets must keep cash ≥ 22% and each coin ≤ 58%.

| Check | Result |
|---|---|
| Spot only | Long-only weights in [0, 1] with cash ≥ 0, BTC and ETH against USDC. Nothing implies leverage, shorting, market making or arbitrage |
| Coins | BTC, ETH and USDC only, matching the Steady list |
| Targets of every reported configuration | I re-ran `check_targets` with the limits as read and h = 0.02 on all 176 target sets in `evaluations.parquet`: S per fold (1x, 2x, Kraken, Binance), B5, the 16 plateau steps, the 54 phase runs, and θ_final A and B. **All pass.** The lowest target cash is 33.9% and the highest target coin is 43.7%, both from seed B's ×1.2 plateau steps in fold 0 |
| Drift at closes, stitched S (kept rows) | 0 closes in breach. Lowest cash 28.6% (seed A) and 32.8% (seed B); highest single coin 42.4% and 50.0% |
| Drift at closes, θ_final over all of train (IN-SAMPLE) | 0 closes in breach. Lowest cash 57.7% (A) and 42.3% (B); highest single coin 32.5% and 44.5% |
| Forced rebalances | S never reached a limit in the kept rows. B5 (S's targets, rebalancing only on a breach) made 1 fill per seed, both in fold 2 (2021): the drifted book crossed a Steady limit at a close and was restored at the next open. That is the limit rule working as specified (readings 2, 5 and 6), not a breach of it. How far past the limit B5 went was not recorded; the plan did not ask for it |
| Not measured | Closes in breach for the plateau and phase runs, and in S's 120-row warmups. A breach there would force the same rebalance. None of these runs is a shippable configuration |
| Nulls | B3, B4 and B4-span do not apply the Steady limits (PLAN.md section 8). They are nulls, not Steady products |

The drift and θ_final rows come from `summary.json`, written by `study.overshoot`, which was tested by hand (bug
#45). I did not recompute them, because that needs bars.

**The plan's limit readings (section 4).** Nothing in the results conflicts with them. Two of them carry the
results, and the owner has not confirmed either (questions 2 and 6 were not asked; the defaults hold):
- **max_coin is per coin (reading 3).** At its lowest-cash close, the stitched S held 71.4% coins in total (seed A)
  and 67.2% (seed B), and the box allowed targets up to 77% coins. If the 60% applied to all coins together, the
  box, the rule and every number in RESULTS.md would be different.
- **max_coin does not apply to USDC (reading 4).** θ_final(A) holds 80% USDC at target and θ_final(B) 71%. 272 of
  the 400 final-study trials (s < 0.30) hold more than 70% cash. A 60% cap on USDC would forbid all of them; the
  coin share would have to be at least 0.40.
- **h = 0.02 (A2).** Nothing in the results argues for changing it. No chosen target came near a limit.

## 2. The drawdown picture in plain words (SCOUTING)

- **The rule's own book, 2019-2022.** Seed A fell 41.8% from peak to trough at its worst and lost 15.4% on its
  worst day (the bar of 12 March 2020). On 1 day in 100 it lost more than 4.9%. Seed B fell 36.7%, with a worst
  day of 13.7%. Seed A's book held 41-49% coins at target (seed B 34-55%), and drift took the coins to 71% of the
  book between rebalances.
- **What could plausibly happen.** The block bootstrap resamples 20-day stretches of the same returns. In 1
  resampled history out of 20, the fall reaches 58.6% (seed A) or 54.5% (seed B) or worse. This is the number G6
  would compare with a budget.
- **Against the comparators on the same days:**

  | Series | Max drawdown |
  |---|---|
  | Buy-and-hold BTC | −77.4% (worst day −38.9%) |
  | 50/50 BTC/cash, rebalanced monthly | −49.5% |
  | The same targets reset yearly and otherwise left alone (B4) | −46.4% |
  | The same targets held four years with no reset (B4-span) | −71% to −75% |

- **Costs do not move the drawdowns.** At 2x costs the drawdown is the same −41.8%. The losses come from prices.
- **The coin share sets the drawdown.** These figures are over all of train (2017-2022, with the 2018 and 2022
  crashes), IN-SAMPLE, for seed A's final study:

  | Coin share | Median max drawdown | Median bootstrap 5th percentile | Median Sharpe |
  |---|---|---|---|
  | 20-30% | −29% | −38% | 1.52 |
  | 70-77% | −69% | −82% | 1.36 |

  θ_final(A), with 20% coins and 80% cash, fell 28.9% (bootstrap 5th percentile −34.6%). θ_final(B), with 29%
  coins, fell 33.2% (−47.4%).
- **What it means for Steady.** Within today's limits, a Steady book can fall about as far as a coin-heavy
  portfolio. At the riskiest end of the box it lost about two thirds of its value in train's crashes. A 20% cash
  floor and a 60% per-coin cap do not, on their own, give the "smaller swings" `docs/app/product.md` promises Steady
  customers. Even the least risky configuration the search reached (80% cash) fell almost 30% in-sample.
- **The stitched S is not one configuration.** It mixes four per-fold configurations, so its −41.8% and −58.6% are
  not the drawdown of anything that could ship. At any future risk review I will judge the configuration that would
  ship, on its own out-of-sample and paper results.

None of these numbers sets, rounds or justifies the Steady budget (PLAN.md section 9).

## 3. The drawdown budget proposal: it stands

The proposal, unchanged:
- **Reference:** BTC 0.385, ETH 0.385, USDC 0.23 (the box's riskiest coin share, split evenly), rebalanced to target
  every 30 days, with the Steady limits on.
- **How it is run:** on train only, on the audited (Nautilus) engine.
- **Budget:** the reference's stationary block bootstrap 5th-percentile max drawdown (mean block 20, 1000 draws,
  seed 0), rounded up to the next 5 points.
- **Conditions:** the budget must sit below the Balanced and Bold budgets, needs the owner's written approval and
  applies to later audits only. It never rescores this study.

**Why it still stands.**
- It was pinned before any result and does not depend on the strategy, and these results show why that matters.
  S's drawdown describes four different per-fold configurations, and the final searches drifted to the box's lower
  edge (θ_final(A) at s = 0.20). A budget taken from S or θ_final would depend on where the search happened to land,
  and the riskier corners of the same box would fail it.
- It uses the same statistic as G6 (`overfitting_report`'s block bootstrap), so the budget and the gate measure the
  same thing.
- Nothing here touches it. G6 stays MISSING for this study (its train-start reading was `TBD`), the validate window
  is unlooked, and `risk_levels.yaml` is unchanged.

**Points for the owner.** These do not change the method; each is the owner's decision.
1. **It cannot be computed yet.** It needs the Nautilus runner (milestone 2, on hold). Until the owner approves a
   number in writing, G6 is MISSING = FAIL for every Steady study, so no Steady strategy can reach CANDIDATE FOR
   AUDIT.
2. **Expect a deep number.** The reference holds 77% coins. In this study, trials with 70-77% coins had bootstrap
   5th percentiles around −80%. Those trials used other bands and check intervals, ran on the reference engine and
   are in-sample, so this is not the reference's number and not a budget. It does indicate that the method will
   likely give a Steady budget close to what a coin-only portfolio loses.
3. **That may break the order of the levels.** Budgets must run Steady < Balanced < Bold with clear gaps.
   `product.md` describes Steady as "smaller swings" and Balanced as "normal crypto swings". A Steady budget near
   −80% leaves little room above it, and a stop-loss Balanced strategy may well fall less than a Steady book with
   77% coins.
   - The fix is not a different budget rule chosen after seeing these results. It is what the Steady limits allow.
   - I recommend the owner decide whether to tighten the Steady limits (a higher `min_cash_pct`, a lower
     `max_coin_pct`, or a cap on total coins) before the budget is computed. The reference then follows the
     tightened limits: the most coin-heavy even split that keeps the 0.02 headroom.
   - Tightening loosens nothing, but it edits `config/risk_levels.yaml`, which needs the owner's go-ahead (hard rule
     10). I give no number: a number picked after seeing the s-profile would be fitted to it.
   - This repeats my recommendation on owner question 3 (fix or cap the coin share), and the results strengthen it.
     In the final studies, the coin share moved the median drawdown from about −29% to −69% while the median Sharpe
     moved from 1.52 to 1.36.
4. **Compare like with like.** This was written after the results, but it comes from the fold layout pinned in
   PLAN.md section 7, not from any number here.
   - As written, the reference is measured over all of train: 2190 rows, 2017-2022, including the 2017 rise and the
     2018 crash. G6 compares the budget with the strategy's bootstrap 5th percentile over its out-of-sample span:
     here 1456 rows, 2019-2022.
   - A drawdown percentile depends on how long the series is and which crashes and rallies it holds. So the gate
     would partly measure the gap between two histories, in a direction nobody chose.
   - I propose running the reference on the same closes as the series G6 measures, with the same harness. For the
     lab's standard walk-forward on the fixed splits, that is closes 2019-01-04 .. 2023-01-01.
   - Nobody knows yet which way this moves the number, and that is why the span should be chosen before the number
     is computed. If the owner prefers all of train, the proposal stands as written.

## 4. RESULTS.md: risk statements checked

**Recomputed from stored outputs, all equal to `summary.json`:**
- the stitched max drawdowns, worst days and total returns of S, B1, B2, B4 and B5;
- G6's block bootstrap p5 and p50 for both seeds;
- θ_final's max drawdown, Monte Carlo p5 and p50, worst day and 1st-percentile day, from its logged trial returns;
- the s-profile's median and worst max drawdowns and Monte Carlo p5 per bin, for both final studies.

**Requests.** None of these is blocking.
1. **"Mostly cash, some ETH"** (In plain words). At target, seed A held 51-59% cash, and drift took it to 28.6% at
   one close. "About half cash at target" says the same thing without making the book sound safer than its −41.8%
   drawdown.
2. **Say where B3, B4 and B4-span first appear that they do not apply the Steady limits** (PLAN.md section 8).
   Without that, "the same mix ... left alone did as well" and item 4's "resetting the mix about once a year
   mattered for risk" can read as statements about Steady-compliant books. They describe nulls.
3. **Item 3 (B5).** Say that B5's one fill was a breach-forced rebalance in 2021, so B5's book crossed a Steady
   limit at one close. Also say that its drawdown was slightly deeper than S's for seed A: −43.2% against −41.8%
   stitched, and −31.4% against −26.5% in fold 2. "At least as well as S" is true of Sharpe only.
4. **Outside my remit.** "A second search and a second data source agree" is true of the verdict (E1 and E2 fail
   in both), but E4 records the seeds as FRAGILE. The auditor may prefer "agree on the verdict".

## 5. Not approved, and what an approval would need

- There is no risk note, no per-strategy limits (maximum allocation, the daily loss limit that pauses the strategy,
  the expected worst day) and no export. These start only after the auditor reports READY FOR RISK REVIEW on
  Nautilus results, and an export only after the owner approves production.
- For any later Steady strategy, the production notes in PLAN.md section 4 remain my requests:
  - sells before buys;
  - the caps and the cash floor checked after the trade, on the full order;
  - a breach restored at the next daily open, with an alert if it lasts more than one day;
  - gas booked to the paper account's book.

  The trade router and the auto-trading permission must allow only cbBTC, ETH and USDC.
- One description to keep in mind when a daily loss limit is set: a book with about 45% coins lost 15.4% in one
  day in March 2020.

## 6. Closing earlier items

- My first-draft review reached PLAN.md cut off after "Disclosures" (section 16). I have no copy of the missing
  text. I checked against the run instead: the disclosures that matter for risk are all in RESULTS.md (the scouting
  label, placeholder costs, candles as a proxy, USDC at 1 with no depeg, daily closes only, the headroom not
  modelled live, the unpaid turnover between folds). Nothing blocking is outstanding from my side.
- Owner questions 2 (per-coin cap, not on USDC) and 6 (h = 0.02) are still unasked, and their defaults hold.
  Section 1 shows that the results depend on question 2's answer.
