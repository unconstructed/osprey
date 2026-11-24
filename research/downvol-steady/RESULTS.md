# downvol-steady: results of run 0 (SCOUTING)

> **SCOUTING ONLY:** the reference engine, the placeholder costs, and exchange candles in place of Base prices. Not
> NautilusTrader. Written on 2026-11-24 from `results/downvol-steady/train/run0/summary.json` and `oos.parquet`,
> and revised the same day after the audit ([AUDIT.md](AUDIT.md)) and a fact-check.
> The Numbers table, E1's counts, E2's bootstrap, the fold table and the 2020 path were rebuilt from those files (and
> the train panel) with separate code, and match `summary.json`. The other numbers are read from it.
> - Run 0 ran on commit `e62233e`, after the full tier (2646 passed, 100% branch coverage) and the deep profile (2628
>   passed), with a clean tree.
> - The owner approved it after A0's power alarm
>   ([reports/director/2026-11-24-owner-answer-downvol-a0-power.md](../../reports/director/2026-11-24-owner-answer-downvol-a0-power.md)).
> - Validate-window looks used: 0. The test window was not read.

## Verdict: NO EDGE (headline: NO EDGE)

**The test could not tell (the owner's condition for this run).** As the owner decided before the run, this NO EDGE is
reported as **"the test could not tell"**, with the pre-check's (A0's) power numbers next to it
([the record](../../reports/director/2026-11-24-owner-answer-downvol-a0-power.md)):
- **A0's power was 1 of 20.** On 20 made-up markets built to contain the effect, the test confirmed an edge once (the
  plan wants at least 4). The timing test (E1) held on 5 of the 20, including that one. The test against holding (E2)
  held on 1, the same one.
- **On 200 made-up markets where volatility clusters** (with no momentum), the timing test passed on 17 (8.5%). That
  is the power where the mechanism is real.
- **A0 raised 0 false positives in 20** markets with no edge.

So a pass would have been rare even if downside scaling has a small real edge, and this run cannot rule such an edge
out.

**In plain words.** The rule holds BTC and ETH half and half, up to a crypto share s. Every Monday it steps back in
quarters when crypto's falling days have been wilder than a target level τ. Over 2018-2022, out of sample:

- **It made +26%, with a worst fall of 61%.** Holding the same share without the scaling (N0) made +221%, with a worst
  fall of 63%.
- **It also did worse than holding.** Its risk-adjusted return (Sharpe) was 0.31, against 0.77 for holding. A test
  that resamples the history found the rule ahead of holding in only 62 of 10,000 resampled histories. That reading is
  a description, not a pre-registered test, and most of it is one year, 2020 (below).
- **Its timing looked like chance.** 171 of 207 copies of its step pattern, moved to other weeks, did at least as well.
- **It did not cut falls any better than simply holding less crypto.** Holding its own average mix of each year, never
  stepping (X), did better on Sharpe, return and worst fall: 0.74, +186% and 47%. X did worse only on the worst single
  day (−18.0% against −11.6%).
- **Most of the shortfall is the walk-forward's 2020 pick.** Trained on 2017-2019, the search chose an 85-day window
  and a 0.35 target for 2020. The March 2020 crash then kept the rule out of crypto for 12 weeks, during which the
  basket nearly doubled. For the rest of the year it held half its share (three quarters for four weeks from 10
  August) while prices tripled. It ended 2020 up 33%, against 166% for holding (by bar-year; section "2020, step by
  step").
- **That pick, more than the downside measure, made the 2020 gap** (the audit's reruns, below). At this run's 2020
  settings, plain volatility also sat out about 11 weeks and made +48% (this rule: +32% over the same days). With
  vol-steady's 2020 settings, the downside rule made +141%.

**What the shortfall against holding means, and what it does not.**
- **What it means.** E2 is one-sided: it asks only "did the rule beat holding?". Here the gap D is −0.46, and p is
  0.994. Read backward, the rule came out ahead in under 1% of resampled histories (0.4-0.6% with four different
  random draws; 1.6% for the second search, seed B).
- **The backward reading is not a pre-registered test.** It is a description. It decides nothing, and no correction is
  made for the other things looked at.
- **It is mostly one year, and one settings pick.** Without 2020 the rule is still behind (D −0.17), but it came out
  ahead in about 12% of the resamples (E7's row). The 2020 part is mostly the window and target the search picked for
  that year (above). The bootstrap's p is also optimistic: the plan notes that five years hold few independent blocks
  (TP 11).
- **Part of it may be the comparator, but this is not measured.** N0 re-cuts to the year's share at the start of each
  year and then drifts, so its crypto grew from 41% to about 78% in 2020. The rule drifts between its steps too (from
  21% to 39% crypto after its September 2020 step). And even a holding bought once at the start of 2018 and never
  re-cut, apart from limit fixes (N0-span), beat the rule: Sharpe 0.40 against 0.31.
- **It is about this rule as the walk-forward chose it, not about downside volatility in general.** The settings fitted
  on all the train years (θ_final, below) look very different, but they were picked on these same years, so they are no
  evidence either way.
- **E1 is not evidence of bad timing.** A rank as low as this one happens about 1 time in 6 by chance.

**Compared with vol-steady run 0** ([RESULTS.md](../vol-steady/RESULTS.md), [AUDIT.md](../vol-steady/AUDIT.md)):
- Both are NO EDGE. vol-steady made +210% against +170% for holding, a small lead that could be luck (E2 p 0.25).
  This rule made +26% against +221%. Each study's "holding" uses its own yearly shares s, so the two holding figures
  differ.
- Both rules stepped down on these four Mondays of 2020-21: 16 March 2020, and 25 January, 24 May and 28 June 2021.
  This rule also stepped down on 7 September 2020.
  - On 16 March this rule went from half its share to nothing, vol-steady from full to a quarter. On 24 May this rule
    went from full to half, vol-steady to three quarters.
  - vol-steady's audit (finding 2) expected these shared step-backs, because falling days carried most of the variance
    at those checks (amendment M1). Counting only falling days did not remove them.
  - In 2021 this rule trailed holding by 0.16 in log terms (vol-steady: 0.14).
- The two runs part in 2020, mostly through the window and target each search picked for that year (15 days and τ 1.03
  there, 85 days and τ 0.35 here), more than through the measure (below).
- The two rules' daily returns correlate at 0.89.

**Next.** The owner asked for a more sensitive follow-up to be designed first. Its design note,
[reports/director/2026-11-24-downvol-followup-design.md](../../reports/director/2026-11-24-downvol-followup-design.md),
was committed before run 0 read any bar. It asks a different question: at the same average crypto, are the rule's down
days smaller than a steadily held mix's?
- **The follow-up is not started.** It would be its own pre-registered study (its own PLAN.md), listing this run, its
  audit (whose 2020 reruns are new looks at the train years) and vol-steady run 0 as prior looks.
- Run 0 produced an S, so the note's "void" condition (its section 3.2) does not apply. Whether to build it is the
  note's owner question 8.
- This file computes none of the follow-up's statistics, and neither did the audit (no weekly re-cut mix, no down-day
  size of S).
- "It did not cut falls any better than simply holding less crypto" (above) is E3's reading: worst falls against X,
  which drifts up in rallies and so leans toward the rule. E3 failed anyway. It is not the follow-up's question.

## Numbers (seed A, Kraken, 1820 out-of-sample days, 2018-01-03 .. 2023-01-01, costs 1x)

| Series | Sharpe | Total return | Worst fall | Worst day |
|---|---|---|---|---|
| S, the rule (walk-forward) | 0.31 | +26% | −60.6% | −11.6% |
| R_0, S's schedule run as one book | 0.20 | +6% | −60.6% | −11.6% |
| N0, always hold the fold's share s | 0.77 | +221% | −62.5% | −20.4% |
| X, hold S's average mix of each fold | 0.74 | +186% | −47.5% | −18.0% |
| B1, buy and hold BTC | 0.43 | +18% | −81.4% | −38.9% |
| B2, 50/50 BTC/USDC monthly | 0.43 | +56% | −53.6% | −17.3% |
| S at 2x costs | 0.28 | +21% | −61.4% | |
| S on Binance (folds 1-4, 1456 days) | 0.87 | +146% | −36.4% | |
| N0 on Binance (folds 1-4) | 1.29 | +499% | −37.0% | |

- S's worst fall ran from 14 January to 16 December 2018. N0's ran from 14 January 2018 to 8 February 2019.
- By bar-year, S made −48%, +40%, +33%, +67% and −22% (2018 to 2022). N0 made −45%, +43%, +166%, +96% and −22%.
- Seed B's S: Sharpe 0.37, +40%, worst fall −60.3%.

## The criteria (PLAN.md sections 6-13: VP 11 and TP 11; E1 per amendment M1)

| ID | Question | Seed A | Seed B | Holds |
|---|---|---|---|---|
| E1 | Timing beats chance: the rule's step pattern, moved to other weeks with each year's share s kept, does worse (the q-only shifts of M1; at most 9 of 207 may be at or above) | rank p 0.827 (171 of 207 shifts at or above) | rank p 0.721 (149) | No |
| E2 | Beats holding the same share (N0), by more than chance | D = −0.460, p 0.994 | D = −0.394, p 0.984 | No |
| E3 | Cuts falls beyond holding less crypto (X): actual and Monte Carlo falls both shallower | S −60.6% / MC p5 −79.6% against X −47.5% / −71.0% | S −60.3% / −78.1% against X −47.7% / −66.5% | No |
| E4 | Still beats holding with costs doubled | S 0.28 against N0 0.77 | 0.35 against 0.76 | No |
| E5 | Not fragile: the two search seeds agree, and other check days keep ≥ 0.7 × the Sharpe | (a) the seeds differ on G5(a) only (A fails, B passes); Sharpes 0.31 and 0.37, within 0.25. (b) Sunday checks give 0.214, just under 0.7 × 0.308 = 0.215 | | No |
| E6 | Not one year: the lead over N0 survives dropping any year | the lead is negative overall (−0.93 in log terms) and in every year; 2020 alone is −0.69 | −0.85; positive only in 2022 (+0.04) | No |
| E7 | Not the boom years: E1-E4 still hold without BTC's best year(s) (2020, then 2019) | without 2020: E1 rank p 0.365, E2 D −0.17 p 0.88; without 2020 and 2019: E1 0.514, E2 D −0.28 p 0.90; E3 and E4 fail in both | | No |
| E8 | The same on Binance (folds 1-4) | E1 rank p 0.609 (94 of 155 shifts at or above); E2 D −0.42, p 0.998 | | No |
| P | Enough information: at least 20 share changes, in at least 4 folds | 80 share changes in all 5 folds (37, 2, 4, 6, 31) | 77 (37, 2, 6, 4, 28) | Yes |

- **E1's statistic is R_0's Sharpe** (0.20 for seed A). The q-only shifts' median is 0.36.
- **E1-whole** (VP's whole-schedule shifts, where s moves with q) is a description under M1, and decides nothing.
  Seed A: rank p 0.832 (172 at or above), median 0.46. Seed B: 0.702 (145). Both nulls say the same.
- E8's Kraken twin: on folds 1-4, S's Sharpe is 0.83 against N0's 1.25 (D −0.42).
- **Why NO EDGE:** E1 and E2 both fail (TP 12, step 1). Only P holds, so the headline has no LOW POWER label.

## The gates (AGENTS.md defaults; seed A)

| Gate | Result |
|---|---|
| G1, out-of-sample Sharpe ≥ 1.0 | FAIL (0.31; also every allowed share S(s_k), 0.29-0.45, and every grid step, 0.90-0.92) |
| G2, the same with costs doubled > 0.5 | FAIL (0.28; every S(s_k) fails too, 0.26-0.43; the grid steps pass, 0.89-0.92) |
| G3, deflated Sharpe ≥ 0.95 | FAIL (0.00003 effective; 2,400 trials, about 18 effective; 0.00002 on active rows) |
| G4, PBO ≤ 0.25 | FAIL (0.78; 0.76 on active rows) |
| G5, ±20% plateau | FAIL: (a) s × 1.2 keeps 0.67 of S's Sharpe; (b) the default's L × 1.2 (143 days) also 0.67. Both steps reach outside the search box, which the plan allows |
| G6, Monte Carlo 95th-percentile fall within 35% | FAIL (−79.6% at S; −63% to −87% at every S(s_k); −35.8% at the default) |
| G7, beats buy-and-hold BTC and 50/50 | FAIL at S (0.31 against 0.43 and 0.43). It passes without the best year and the best two, and at the default and every grid step |
| G8-excess, no regime carries the lead over N0 | FAIL (S trails N0 in bull, bear and sideways months; the default and the grid trail in bull months) |
| R1, a few trades a month | PASS (1.35 orders per 30 days, at most 5; the default and the grid 0.21, at most 2) |
| The allowed shares S(s_k) | FAIL: E1 fails at every share (rank p 0.82-0.86), and so does E2 (D −0.38 to −0.51, p 0.97-0.99) |

**The stop at the gates.** G6 is the drawdown budget the owner approved in writing: a 35% fall at the 95th
percentile, read from `config/risk_levels.yaml` before any bar.
- S's actual worst fall (−60.6%) breaks it on its own.
- Narrowing the range cannot help (TP 8, M19). AGENTS.md allows a narrowing only for a risk-limit failure, never for
  failed Sharpes, and a G6 failure at S, the walk-forward choice, fails the strategy outright. `summary.json` records
  "narrowing fails: G6 fails at S, the walk-forward choice".

**The allowed shares** (the walk-forward's L and τ in each fold, with s held at each allowed value; out of sample):

| s_k | Sharpe | Total return | Worst fall | G6 statistic | E1 rank p | E2 D, p |
|---|---|---|---|---|---|---|
| 0.30 | 0.45 | +50% | −37.4% | −62.6% | 0.851 | −0.39, 0.975 |
| 0.40 | 0.36 | +37% | −46.9% | −73.4% | 0.856 | −0.38, 0.980 |
| 0.50 | 0.35 | +35% | −55.2% | −80.5% | 0.851 | −0.51, 0.992 |
| 0.60 | 0.29 | +20% | −62.4% | −86.7% | 0.817 | −0.43, 0.992 |

**The default and the grid** (in-sample: θ_final(A)'s L = 119 and τ = 0.31, picked on these same years, held fixed at
each allowed s). The default is s = 0.60, the allowed value nearest θ_final(A)'s 0.587.
- Sharpe 0.92, 0.92, 0.91 and 0.90 at s 0.30-0.60, with worst falls of 10-19%. G6's statistic is −19.7%, −25.6%,
  −30.8% and −35.8%: the default misses the budget by 0.8 points.
- These are in-sample, so they are no evidence either way. They made less than their own holding at the same s
  (+97% against +221% at s = 0.60), with much less crypto: θ_final's steps held a quarter of the share on 78% of days.
  Their Sharpe was higher than that holding's (0.90 against 0.73 at s = 0.60; 0.73-0.74 at every s).
- The plateau step to a 143-day window drops the default's Sharpe to 0.21.

## What the search chose

| Fold (test year) | Lookback L | Target τ | Share s | Time at the full share | Mean step q |
|---|---|---|---|---|---|
| 0 (2018) | 10 days | 0.61 | 0.57 | 31% | 0.67 |
| 1 (2019) | 22 | 1.20 | 0.52 | 96% | 0.99 |
| 2 (2020) | 85 | 0.35 | 0.41 | 0% (all USDC on 23% of days) | 0.40 |
| 3 (2021) | 22 | 1.16 | 0.42 | 85% | 0.95 |
| 4 (2022) | 10 | 0.47 | 0.34 | 38% | 0.68 |

- **The q path was recomputed for this file** with `lab.runner.downvol` on the Kraken train panel (panel hash as TP 3).
  Every fold's time at each step and mean q match `summary.json`, and every fold's S reproduces `oos.parquet` exactly.
- **Seed B chose nearly the same L and τ in 2018-2021.** Its 2020 pick was 81 days and 0.35, with s 0.49. For 2022
  it chose 16 days and 0.38.
- **2019 and 2021:** with τ near 1.2, the scaling was mostly off, as in vol-steady.
- **2018:** the search picked a high share, 0.57 (vol-steady's seed A picked 0.31). With 37 steps and 15 reversed
  within four weeks, the rule lost 48%, a little more than holding (−45%).
- **2022:** it ended level with holding (−22% each). Stepping back from May to July 2022 helped, and the rest of the
  year gave it back.
- **The final pick on all the train years** (θ_final, seed A) is L = 119, τ = 0.31, s = 0.59. It steps back almost
  always: over the kept rows it held a quarter of its share on 78% of days, half on 15%, and nothing on 6.5%. Seed B's
  is L = 16, τ = 0.84, s = 0.37.

### 2020, step by step (a description; seed A)

The rule's 2020 settings: an 85-day window, a target of 0.35 and a share of 0.41. Holding (N0) bought 41% crypto at
the start of the year (decided at the 3 January close) and then only drifted.

| 2020 stretch (check closes) | The rule held | Basket (50/50 BTC/ETH, bought and held) | S | N0 | S minus N0 (log) |
|---|---|---|---|---|---|
| 3 Jan - 16 Mar | half its share (about 21% crypto at the start, up to 32% on 15 February, 25% just before the crash, 16% after it) | −13% | −2.5% | −5.4% | +0.03 |
| 16 Mar - 8 Jun (12 weeks) | nothing (all USDC) | +91% | −0.05% | +35% | −0.30 |
| 8 Jun - 10 Aug | half its share | +40% | +8.1% | +23% | −0.13 |
| 10 Aug - 7 Sep | three quarters | −11% | −3.4% | −6.6% | +0.03 |
| 7 Sep - 1 Jan 2021 | half its share (21% crypto, drifting to 39%) | +146% | +30% | +81% | −0.33 |
| The whole year | | +400% | +32% | +165% | −0.69 |

How to read the table:
- **The dates.** The first boundary is fold 2's start, the 3 January close. The others are the Monday check closes
  where the step changed (16 March, 8 June, 10 August, 7 September). Each order filled at the next open, so a
  stretch's first day still carries the old holding until that open.
- **The basket** is a 50/50 BTC/ETH mix bought at the start of each stretch and held, with no rebalancing.
- **The year row** covers fold 2's kept rows, from the 3 January close to the 1 January 2021 close. So it differs
  slightly from the bar-year figures under the Numbers table (S +33%, N0 +166%).

In plain words:
- **It stepped back after the crash, not before it.** On 12 March the basket fell 42% in one day, with the rule at half
  its share (about 25% crypto). On Monday 16 March its downside volatility read 1.73 a year, more than four times the
  target, so it sold all its crypto (BTC was about 5,300).
- **The crash then kept it out for 12 weeks.** The crash days stayed in its 85-day window until the check of 8 June.
  It bought back half its share then, with BTC about 9,800. In between, the basket nearly doubled.
- **The target was out of reach all year.** Outside the crash window, downside volatility ran at 0.43-0.70 a year,
  above the 0.35 target. So the rule never held its full share in 2020, while BTC went from about 7,000 to about
  29,000 (from about 9,800 after the June buy-back).
- **Holding let its crypto grow** from 41% to about 78% of the wallet by year-end.
- **The cost in log terms:** 0.30 for the 12 weeks in USDC, and 0.46 for half a share through the two rallies. The two
  falls gave back 0.06, for −0.69 in all (the parts are rounded).

**The same crash, the other rule.** vol-steady also stepped back on 16 March (to a quarter). Its 15-day window forgot
the crash within three weeks, and it bought back its full share on 7 April (the check of 6 April), early in the
rebound. It ended 2020 ahead of holding (+0.17 in log terms; its audit found that this came from rebalancing, not
timing). Here the search, trained on 2017-2019, chose a long window and a low target for 2020.

**Window or measure?** These are the audit's descriptions (its finding 1), rechecked for this file. They decide
nothing. The audit reran 2020 (fold 2) with both measures and both studies' 2020 settings, all at this run's 2020
share (0.414):

| 2020, at s = 0.414 | Steps (check dates) | 2020 return | Against its own N0 (log) |
|---|---|---|---|
| Downside measure, 85 days, τ 0.35 (this run) | nothing from 16 March to 8 June; never the full share | +32% | −0.69 |
| Plain volatility, 85 days, τ 0.35 | nothing from 23 March to 8 June; never the full share | +48% | −0.59 |
| Downside measure, 15 days, τ 1.03 (vol-steady's 2020 settings) | a quarter for two weeks, back to full on 30 March | +141% | +0.01 |
| Plain volatility, 15 days, τ 1.03 (vol-steady's 2020 rule) | a quarter, back to full on 6 April | +156% | +0.16 |

- **At the same settings, the two measures behave almost alike.** With an 85-day window and a 0.35 target, plain
  volatility would also have sat out about 11 weeks, and never held its full share in 2020.
- **With a 15-day window, the downside rule forgot the crash faster than vol-steady did:** two weeks, not three. So
  the gap between vol-steady's three weeks and this run's twelve is the window (15 days against 85), not the measure.
- **The measure did cost something at fixed settings.** In 2020 the downside rule made less than plain volatility at
  both settings: 0.11 and 0.06 in log terms on the returns (0.11 and 0.15 against each run's own N0).
- **Over all five years at this run's own settings,** plain volatility gives a Sharpe of 0.41 against 0.31. The steps
  differ at 61 of the 260 checks, mostly in the 10-day windows of 2018 and 2022.
- **The N0 column is each run's own holding, as the plan defines it.** In the two 15-day runs the rule already held its
  full share when 2020 began, so N0 kept the drifted book (35% and 30% crypto) instead of buying 41%. Compare the
  returns first.
- **What one run cannot tell:** whether the downside measure made the search pick (85 days, 0.35) for 2020. The
  walk-forward's picks are noisy (PBO 0.78).

## Descriptions (decide nothing)

- **Without both bear years (2018 and 2022):** E1's rank p is 0.841 and D is −0.42.
- **Leave one year out:** E1's rank p is 0.78, 0.93, 0.37, 0.93 and 0.84 without 2018 .. 2022. E2 fails every time
  (D −0.17 to −0.62).
- **The q-only shifts in more detail (M2, M3):**
  - the 207 guarded shifts: p5 0.08, median 0.36, p95 0.65, against R_0's 0.20;
  - B3-lead (the 52 shifts that move the pattern earlier, a look-ahead profile): median 0.46, R_0's rank p 0.906;
  - the lag shifts (the pattern 1-52 weeks later): p5 0.01, median 0.23, p95 0.43; R_0's rank among them 0.585.
- **E2 with 20-day blocks:** D −0.46, p 0.993.
- **Correlations:**
  - with N0 0.90, vol-steady's S 0.89 and rebalance-steady's S 0.88;
  - with trend-steady's S 0.75, B1 0.82 and B2 0.83.
- **Check days:** the other weekdays give Sharpes of 0.21-0.37. Daily checks give 0.37, with 157 orders against 82.
- **Active-row re-scoring:** re-scoring each search on the rows where a trial can hold crypto would change the pick in
  3 of 12 studies (seed A folds 1, 3 and 4).
- **Deflated Sharpe at other trial counts:** about 2e-16 at 2,400 trials, and 4e-18 at the strict 4,849.
- **Monte Carlo:** the 60-day-block p5 fall is −82%; the shuffled-trade p5 is −72%.
- **Trades:** 82 kept fills (37 in 2018, 31 in 2022).
  - That is 27 for each of the 3 searched parameters, under the audit checklist's 30, so it is flagged.
  - `summary.json` divides by 2, as TP wrote it for two parameters, and gives 41, unflagged.
  - 29 steps were reversed within 28 days, 15 of them in 2018.
- **Limits (R2):** the rule trades only when its step changes, so between steps its crypto drifts. Twice it held just
  over 80% crypto: 80.1% on 26 June 2019 and 80.6% on 4 January 2021. Each broke the 20% cash floor and was fixed at
  the next open.
- **Time in crypto (R3, R5):**
  - full share on 50% of days, all USDC on 5.4%;
  - the longest all-USDC stretch is 84 days (2020);
  - worst day −11.6%, 1st-percentile day −5.2%.
- **Costs (R4, θ_final(A) run in-sample, not S):**
  - customer fees about 0.13% a year at a 10,000 USD wallet;
  - gas about 0.52 USD a year;
  - the Sharpe with gas charged is 0.89-0.90 at every wallet size from 100 to 50,000 USD.

## Record

- **The run:** run 0 on commit `e62233e`, config hash `04d418e9899a96d4…`, snapshot `1746a21b75683e76`.
  - 2026-11-24, 18:08:56 to 18:12:48 UTC: 231.6 s. The projection was 3.3 CPU-minutes (budget 60).
  - 2 seeds × 6 studies × 200 trials = 2,400 trials, none failed. `evaluations.csv` has 2,031 rows, 48 of them
    counted.
  - **The strict trial count** is N_raw + 49 + 2,400 = 2,400 + 49 + 2,400 = **4,849**, the last 2,400 being vol-steady
    run 0's trials (W1). With K4 counted as 15 it is 4,863.
  - The train window only. The panels end at 2023-01-01 00:00 UTC, with TP 3's panel hashes. Kraken has 2,190 rows
    from 2017-01-02 and lacks only 2018-01-13. Binance has 1,963 rows from 2017-08-18.
- **Before the run:**
  - Amendments M1 (E1 on q-only shifts), M2 (the build's readings), M3 (the lag percentiles), A1 (N = 200) and A0
    (power alarm; the owner: run it, and design a follow-up first). None of them read a market bar.
  - The follow-up's design note was committed in `e62233e`, before run 0 read any bar.
- **Tiers on `e62233e`:**
  - the full tier: 2646 passed, 100% branch coverage of `lab/` (7665 statements, 2288 branches), 3488 s at `-n 3`;
  - the deep profile (`-m "not slow"`): 2628 passed in 1095 s;
  - ruff clean, dashboard 86 passed, the tree clean before and after.
  - TESTING.md section 3 records the same run (written there in commit `7257575`).
- **Run at the same time as buy-the-dip run 0.**
  - Both read a clean tree at `e62233e` before either wrote its RUNLOG line. buy-the-dip ran on 2 workers alongside.
  - The audit (finding 8) estimates that this run's dirty-tree check passed less than a second before buy-the-dip
    created its RUNLOG file. Losing that race would have refused the start; it could not have run changed code. Start
    real runs one after the other.
  - All 41 files in this run's start record still hash as recorded, so buy-the-dip changed none of them. This run
    writes only into `results/downvol-steady/` and its own RUNLOG and CSVs.
  - Otherwise the two shared only CPU time and the read-only catalog.
- **For this file:** the q paths, the 2020 path and the audit's 2020 reruns (finding 1) were recomputed on the Kraken
  train panel, through a loader that refuses any request or bar after 2023-01-01 00:00 UTC. No validate or test bar
  was read.
- **PLAN.md** is byte-identical to run 0's start (M3). Its section 20 row for run 0, and a run 0 line in README.md,
  can be added now that no look is earned.
- **Audit:** `backtest-auditor`, 2026-11-24, PASS for the run and its verdict ([AUDIT.md](AUDIT.md)). The strategy
  goes back to research (not ready for risk review); the plan stops here.
  - It rebuilt every decisive number with its own code (its own downside measure, Monday checks and coin-and-cash
    book), and each matches `summary.json` to round-off. Nothing can flip NO EDGE.
  - It also checked the protocol (one run 0, a clean tree, all 41 hashed files unchanged, no bar after 2023-01-01),
    reran two logged searches bit for bit, and ran 80 tamper-the-future cases on real train bars.
  - Its corrections to this file's claims were applied the same day. No number in the Numbers, criteria or gates
    tables changed; the 2020 table now uses the check dates.
  - Its 2020 reruns are new looks at the train years, and this file's recheck repeats them. Any later study on these
    years, the follow-up included, lists the audit as a prior look.
- **Deviations:** none found from the plan as amended.
- **No validate look:** NO EDGE earns none (TP 13).
