# trend-steady: results

> **SCOUTING ONLY.** Every return, Sharpe ratio and drawdown below comes from the lab's reference portfolio engine
> (`lab/runner/portfolio.py`, driven by `lab/runner/trend.py`), not from NautilusTrader (AGENTS.md hard rule 3; the
> Nautilus work is on hold). All of them use the **placeholder** costs in `config/costs.yaml`. Exchange candles
> (Kraken in USD, Binance in USDT) stand in for Base prices. Every table below is SCOUTING. Nothing here goes into
> `reports/<strategy>/`, `strategies/` or `exports/`, and nothing here is an audit.

## In plain words

We tested a simple trend rule for the cautious ("Steady") level. Once a week, on Monday, each of BTC and ETH is
compared with its own recent average price. A coin that is clearly above it is held (each coin's slot is half of a
"crypto share" of 30-60% of the wallet). A coin that is clearly below it is sold to USDC cash. Each year a search
chose the average length, the buffer and the crypto share from earlier years only. The rule was then scored on
2018-2022, after placeholder costs.

It made **+212%** with a worst fall of **−37%** (Sharpe 0.90). Holding the same mix without timing made +145% and
fell −61% (Sharpe 0.63). Holding only BTC made +18% and fell −81% (Sharpe 0.43). So the rule looked better, mostly by
stepping aside in the 2018 and 2022 crashes. But about **1 in 12 randomly timed copies** of the same rule (same
trades, moved to other weeks) did as well, and its lead over plain holding could be luck (p = 0.18). Simply holding
S's own average amount of crypto each year, with no timing, did even better (Sharpe 0.98, +294%, worst fall −39%). It
**lost to plain holding in the bull years 2020 and 2021**, and it failed the boom-year check (without BTC's best years,
2020 and 2019, it no longer beat random timing or plain holding). A second search agrees, and so does
a second data source. The basic stop-loss ("sell after a 20/30/40% fall from the top, buy back when the trend turns
up") added nothing the luck checks could see. It trades about once a month (median), at most 4 times in any 30 days.

**Verdict: NO EDGE.** So the 2023 to mid-2024 validation data stay unused for this idea, and nothing here goes
further. A synthetic check before the run had already warned that this test is weak at spotting a real edge (power
0 of 20); the owner chose to run it anyway.

## Verdict and headline (SCOUTING)

**Train verdict: NO EDGE. Headline: NO EDGE. Stop-loss variant overall: NO EDGE.** PLAN.md section 12, applied
mechanically: NO EDGE when E1 or E2 fails.

- **E1 fails.** R_0 (S's own weekly schedule run as one span from fold 0's start, over all 1820 kept rows) has a
  Sharpe of 0.897. Of the 207 guarded
  weekly-segment shifts of the same schedule, 17 did as well or better: rank p = 18 / 208 = **0.087** (it needs
  < 0.05). The shifts' 5/50/95 percentiles are −0.14 / 0.39 / 1.03.
- **E2 fails.** S minus N0 (the same mix, held without timing) is D = 0.275 in Sharpe, with a paired stationary
  bootstrap p = **0.179** (10,000 resamples, mean block 60; it needs < 0.05).
- Both fail for seed B too (E1 rank p 0.183, E2 p 0.274) and on Binance (E8: E1 rank p 0.115, E2 p 0.403).
- **Stop rule 18:** one run, run 0, reported beside nothing. No amendment run.
- **No validate look** (stop rule 8). The validate window (closes 2023-01-02 .. 2024-07-01) stays unlooked for
  trend-steady. **Validate-window looks used: 0.** No `FROZEN.json` was written; `freeze.py` and `run_validate.py`
  were not run. G9 is NOT RUN.
- **The test window was never read.** Both panels were loaded through `lab.data.panel.load_panel` with `last_close`
  2023-01-01 00:00 UTC (Kraken 2190 rows, Binance 1963 rows, train only).

## The run

| | |
|---|---|
| Run | run 0 (real data), the only run |
| Commit | `587acfa` (clean tree); full tier, deep profile, ruff and dashboard passed on it (below) |
| Started | 2026-11-23 03:14 UTC; finished in 246 s (4.6 CPU-minutes projected, budget 60) |
| Data snapshot | `1746a21b75683e76` |
| Config hash | `eed7f8b885e08ead…` |
| Branch | R: crypto share s in {0.30, 0.40, 0.50, 0.60} as user settings; Steady budget 35% (`config/risk_levels.yaml` read as 0.35, `min_cash` 0.20, `max_coin` 0.60, coins BTC, ETH, USDC) |
| Trials | 12 studies × 200 = 2400 (raw); strict count 2479 (2493 with K4 as 15); 0 failed; −10 (too few trades) trials 5 and 1 in seed A's folds 0 and 1, 4 in seed B's fold 0 |
| Counted evaluation runs | 78 rows, 4650 evaluations in all |
| Outputs | `results/trend-steady/train/run0/` (git-ignored: `summary.json`, `trials.parquet`, `evaluations.parquet`, `oos.parquet`); committed: `trials.csv`, `evaluations.csv`, `RUNLOG.jsonl` (commit `91858ad`) |

## Stitched out-of-sample, 2018-2022 (seed A, 1820 rows, SCOUTING)

| Series | What it is | Sharpe | Total return | Max drawdown | Worst day |
|---|---|---|---|---|---|
| **S** | the rule, each year's search choice, 1x costs | **0.901** | **+212.3%** | **−37.5%** | −11.5% |
| S at 2x costs | | 0.858 | +192.5% | −38.6% | −11.5% |
| R_0 | S's schedule as one span from fold 0's start, all 1820 kept rows (E1's subject) | 0.897 | +198.9% | −37.5% | −11.5% |
| N0 | the same mix (s/2 each), held without timing | 0.626 | +145.4% | −60.6% | −25.3% |
| N0-span | N0 held from fold 0's start, never re-cut | 0.397 | +47.0% | −60.4% | −15.9% |
| X | S's average exposure each fold, held (E3) | 0.980 | +294.0% | −39.4% | −24.8% |
| B1 | buy and hold BTC | 0.429 | +18.4% | −81.4% | −38.9% |
| B2 | 50/50 BTC/USDC, rebalanced monthly | 0.428 | +56.5% | −53.6% | −17.3% |
| S on Binance (E8; 2019-2022, 1456 rows) | | 1.191 | +244.8% | −30.2% | −11.6% |

Seed B's S: Sharpe 0.789. Correlations of S's daily returns: B1 0.67, B2 0.69, N0 0.74, rebalance-steady's S_A 0.80.

## Research criteria (SCOUTING)

| Criterion | Seed A | Seed B | What it asks |
|---|---|---|---|
| E1 | **FAIL** (rank p 0.087) | FAIL (0.183) | Timing beats 207 random week-shifts of itself |
| E2 | **FAIL** (D 0.275, p 0.179) | FAIL (D 0.197, p 0.274) | Beats the same mix held, beyond luck |
| E3 | pass (S −37.5% / p5 −59.3% against X −39.4% / −61.8%) | FAIL | Falls no worse than X |
| E4 | pass (S 0.858 against N0 0.623 at 2x) | pass | Still ahead with costs doubled |
| E5 | FAIL: (a) the seeds differ on E3; (b) holds (every other weekday 0.69-0.82, daily check 0.84) | | Robust to the seed and the check day |
| E6 | **FAIL** | FAIL | Ahead of held in every year: seed A's yearly lead Δ_y 2018 +0.40, 2019 +0.09, **2020 −0.29, 2021 −0.26**, 2022 +0.30 |
| E7 | FAIL | FAIL | E1-E4 still hold without BTC's best year (2020) and two best (2020, 2019): E1 rank p 0.188 and 0.255, E2 p 0.134 and 0.220, E3 fails both |
| E8 | FAIL (E1 rank p 0.115, E2 p 0.403) | | The same on Binance |
| P | pass (76 coin-state changes in all 5 folds; 58 switch weeks; 20 BTC and 18 ETH out-spells) | pass (71) | Enough switches to test |

**Boom years and leave one year out** (seed A, descriptions): with each year removed, E1's rank p is 0.096 (no
2018), 0.125 (no 2019), 0.188 (no 2020), and E1 fails every time. With both bear years (2018 and 2022) removed, the
rule grows less than the held mix (Δ −0.455 in log growth) while staying slightly ahead on risk-adjusted return
(D +0.141 in Sharpe), and E1's rank p is 0.101: in 2019-2021 alone the timing gave up return for smaller swings, and
it was no better than random timing.

## Gates (AGENTS.md defaults, unchanged; SCOUTING)

At S, the walk-forward choice (seed A): **G1 FAIL** (Sharpe 0.901 < 1.0), G2 PASS (0.858 > 0.5 at 2x), **G3 FAIL**
(DSR raw 0.039, effective 0.513, strict 0.038, and 0.044 in the active-row reading; needs ≥ 0.95), **G4 FAIL** (mean
PBO 0.665 over all 12 studies, 0.603 in the active-row reading; needs ≤ 0.25), G5 PASS
(plateau ratio 0.80 ≥ 0.70), **G6 FAIL** (Monte Carlo 95th-percentile max drawdown −59.3% against the 35% budget;
seed B −69.6%), G7 PASS (beats B1 and B2 in full, without the best and without the two best bar-years), **G8-excess
FAIL** (expected: all the lead over the held mix comes in bear months, +1.18, against −1.09 in bull months; the
literal G8 fails too), G9 NOT RUN, R1 PASS.

**The range (Branch R).** The default is s = 0.50 (θ_final(A) has s = 0.513; the nearest allowed value), with
θ_final(A)'s L = 40 and δ = 0.0053. These fixed runs use the final search's choice over all of train, so they are
**IN-SAMPLE** checks, not evidence (AGENTS.md "Settings ranges").

| Grid step | Sharpe 1x | Sharpe 2x | Max drawdown | MC p5 drawdown (G6) | G6 |
|---|---|---|---|---|---|
| s = 0.30 | 1.220 | 1.182 | −21.2% | −36.2% | FAIL |
| s = 0.40 | 1.227 | 1.184 | −27.3% | −44.4% | FAIL |
| s = 0.50 (default) | 1.267 | 1.217 | −32.9% | −49.6% | FAIL |
| s = 0.60 | 1.218 | 1.163 | −37.9% | −57.0% | FAIL |

Every grid step fails G6 and G8-excess. The narrowing rule (section 8) cannot apply: "narrowing fails: G6 fails at S,
the walk-forward choice". **S(s_k)** (the walk-forward with s held at each allowed value): Sharpe 1.036 / 1.026 /
1.044 / 0.981, E1 holds at each (rank p 0.034 / 0.043 / 0.038 / 0.048), E2 fails at each (p 0.291 / 0.193 / 0.088
/ 0.220). The S(s_k) check FAILS: E2 fails at every share, and G1 (0.981 at s = 0.60) and G6 (MC p5 −43.5%, −52.5%,
−58.9% and −65.7% at s = 0.30 to 0.60) fail too. E1 holding at each fixed share but not at S is four extra looks
that can only add conditions; the verdict is decided at S, as planned.

## The stop-loss variant (section 11A; SCOUTING)

| Level φ | Stops fired | Sharpe (seed A) | Max drawdown | Line |
|---|---|---|---|---|
| 0.20 | 4 | 1.004 | −33.3% (S −37.5%) | NO EDGE: SL-E1, SL-E2, SL-T, SL-E5-SL-E8 fail; SL-B, SL-E3, SL-E4, SL-P hold |
| 0.30 | 2 | 0.891 | −37.2% | NO EDGE (LOW POWER: 2 stops) |
| 0.40 | 0 | 0.901 | −37.5% | NOT TRIGGERED |

**Overall: NO EDGE.** At 20% the stop cut the worst fall by about 4 points, but its own timing did not beat placebo
stops placed at random weeks (SL-T fails), and the plain criteria fail as above. Seed B is NO EDGE too, but not in
the same way at every level: at 0.20 it also fails SL-B and SL-E3 (which is one reason SL-E5 fails), and at 0.40 its
stop fired while seed A's did not.

## Trade frequency (owner decision 7: reported, not capped; SCOUTING)

Per 30 calendar days, over the kept closes of 2018-2022:

| | Fills: median / worst | Coin switches: median / worst | Legs: median / worst |
|---|---|---|---|
| S | 1 / 4 | 1 / 6 | 2 / 8 |
| Default (s = 0.50) | 1 / 4 | 2 / 6 | 2 / 6 |

R1 ("a few trades a month", section 12) passes at S, θ_final(A), the default and every grid step. Whipsaws (a switch
reversed within 4 weeks): 36. Their orders cost 3,366 USD, each order counted once, of
the 3,960 USD that all of S's kept fills cost (each fold's run starts with 10,000 USD at the first train close and
holds 16,100 to 127,500 USD at its fold's start). `summary.json` says 7,108 USD: the run's code counted an order twice
when two whipsaws shared it (bug #60, found by the audit; fixed after the run, and the corrected total recomputed
from run 0's logged fold choices; it decides nothing). Daily checking instead of weekly: 135 orders, Sharpe 0.84 (weekly
0.90).

## Per fold (seed A; out-of-sample year = fold + 2018; SCOUTING)

| Fold | Chosen L / δ / s | IS Sharpe | OOS Sharpe | Return | Max drawdown | Fills | Costs paid |
|---|---|---|---|---|---|---|---|
| 0 (2018) | 26 / 0.0071 / 0.599 | 2.74 | −0.52 | −18.0% | −37.5% | 19 | 2.52% |
| 1 (2019) | 32 / 0.0978 / 0.305 | 1.33 | 0.83 | +18.9% | −22.9% | 8 | 0.41% |
| 2 (2020) | 128 / 0.0108 / 0.531 | 1.40 | 2.17 | +118.0% | −26.9% | 5 | 0.52% |
| 3 (2021) | 42 / 0.0051 / 0.327 | 1.65 | 1.86 | +73.9% | −17.1% | 14 | 1.07% |
| 4 (2022) | 38 / 0.0055 / 0.555 | 1.70 | −0.62 | −15.5% | −27.5% | 12 | 2.10% |

Trades per parameter: 58 kept fills over 3 parameters, about 19 each, **flagged** (below 30), as expected.
Walk-forward efficiency 0.51. The chosen settings jump from year to year (L from 26 to 128; s from 0.31 to 0.60).
No Steady limit was broken at a close of S (0 closes in breach, highest coin 43.1%, lowest cash 20.5%).

## Luck statistics (SCOUTING)

- **DSR** (seed A): raw count (2400 trials) 0.039, effective count (16.7 trials) 0.513, strict count (2479) 0.038.
  G3's second reading, the active-row report (rows 204 on), gives an effective-count DSR of 0.044.
- **PBO:** mean 0.665 over all 12 studies (the gate's number; seed A's six alone 0.718, seed B's 0.612); in the
  active-row reading, 0.33 to 0.95 per study, mean 0.603.
- **Monte Carlo** of S: block bootstrap p5 / p50 max drawdown −59.3% / −38.0% (block 20) and −61.8% / −38.9% (block
  60); trade-period shuffle −52.2% / −38.2%.

## Risk descriptions (SCOUTING; see RISK.md)

- S's worst fall −37.5% (2018) and worst day −11.5%; the Monte Carlo 95th-percentile fall −59.3% is beyond Steady's
  35% budget, so the rule cannot be offered at Steady as tuned, at any allowed crypto share.
- Time in the market 62% of days; all in USDC on 38% of days, the longest unbroken all-USDC stretch 91 days. Longest
  delay from a trend turn to the exit order: 7 days (the weekly check).
- θ_final(A) over all of train (IN-SAMPLE): max drawdown −31.7%, Monte Carlo p5 −47.1%, worst day −12.9%, 20 legs a
  year, legs of 448 to 33,526 USD (p5-p95) on a 10,000 USD start; one close in breach of the cash floor (lowest cash
  19.7%), fixed at the next open as the rule says.
- Wallet size (R4): customer fees 0.7% a year at 100 USD to 2.1% at 50,000 USD (slippage grows with trade size);
  gas about 2.18 USD a year.

## Validate look

Not taken: the verdict is NO EDGE (stop rule 8). **Validate-window looks used for trend-steady: 0.**

## Deviations from the plan

| What | Why | Effect |
|---|---|---|
| MLflow logging not built | The Nautilus/MLflow work is on hold (PLAN.md section 14 names this) | Every trial is in `trials.parquet` / `trials.csv` instead |
| A0's power alarm fired (power 0 of 20); run 0 ran on the owner's written answer "run it anyway" | PLAN.md section 9 and stop rule 15 ([M27]) | `reports/director/2026-11-23-owner-answer-trend-a0-power.md`; the lead recommended running it before the owner answered (recorded) |
| The build agents' briefs held the lead's one-sentence summary of hold-mix-cap's results | The workflow brief predated [M22] | Logged in PLAN.md section 20 (row "Build"); no agent read a hold-mix-cap result file or number |
| Results written and risk notes drafted by the lead, one independent audit | The owner asked to "finish it lean" (usage limit) | RISK.md is the lead's, not a separate `risk-officer` review; no director review of this study yet |
| The whipsaw total in `summary.json` (7,108 USD) double-counted shared orders (bug #60, found by the audit) | A code bug in a description, fixed after the run with a regression test; no amendment run, since nothing decisive reads it (stop rule 18 (c)) | RESULTS.md gives the corrected 3,366 USD, recomputed from run 0's logged fold choices on train bars; `summary.json` is left as the run wrote it |
| This file lists the main tables, not every description of section 16 | Lean reporting | Every number of section 16 is in `results/trend-steady/train/run0/summary.json` (git-ignored); the committed `trials.csv` and `evaluations.csv` hold every trial and every counted run |

## Known weaknesses

- **Low power, measured before the run:** on synthetic markets with short trends the procedure never found an edge
  (A0 power 0 of 20). A NO EDGE here says the rule's edge is not strong enough to be told apart from luck in five
  years of weekly checks, not that there is none.
- **Five out-of-sample years, two of them crashes.** Almost all of the rule's lead comes from 2018 and 2022 (E6,
  G8-excess). A rule that helps only in crashes cannot be told apart from luck in five years, and it pays for that
  protection in booms (2020, 2021).
- **Unstable choices.** The search's choice moves a lot from year to year; walk-forward efficiency is 0.51 and PBO
  is high.
- **Scouting engine and placeholder costs.** Not NautilusTrader; not Base prices; costs not measured.

## Test tiers on the commits used

| Commit | Use | Tiers |
|---|---|---|
| `783ed2e` | The build; A1 and A0 ran on it | Full tier with coverage at `-n 2`: 2087 passed (14 slow), 100% branch (5806 statements, 1698 branches), 2206 s; deep profile 2073 passed, 909 s; ruff clean; dashboard 86 passed |
| `587acfa` | Run 0 (adds A1, A0, the owner record and the #59 test fix; no code change) | `uv run pytest -q -p no:cacheprovider -n 3 --ignore=tests/test_dashboard.py --cov=lab --cov-branch --cov-report=term-missing`: 2088 passed, 100% branch (5806 statements, 1698 branches), 2007 s; `HYPOTHESIS_PROFILE=deep uv run pytest -q -p no:cacheprovider -n 3 -m "not slow" --ignore=tests/test_dashboard.py`: 2074 passed, 626 s; `uv run ruff check`: clean; dashboard 86 passed; tree clean before and after |
