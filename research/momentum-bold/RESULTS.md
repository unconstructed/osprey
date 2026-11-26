# momentum-bold: results of run 0

**Verdict: NOT A CANDIDATE.** Every gate fails (G1-G8), and so does the luck control (E1).

Run 0 started on commit `f6be3aa`, after the full, deep, ruff and dashboard tiers passed with a clean tree. It used:
- config hash `c7e711f5…`;
- snapshot `81b2116f5f4b562a`;
- the train window only, closes 2017-08-18 to 2023-01-01, a panel of 1963 rows and 418 symbols. The out-of-sample years are 2019-2022.

No validate or test bar was read. The record is `results/momentum-bold/run0/`, with copies of `summary.json`, `start.json` and `folds.csv` in `run0/`; the RUNLOG is `RUNLOG.jsonl`. Every number below is taken from `summary.json`, except the by-year returns (`oos.parquet`) and the by-year choices (`folds.csv`). The audit is `AUDIT.md` (the run PASS, the numbers PASS).

## In plain words

Each Monday the rule held the coins that had risen most recently, chosen from the 20 most traded. Over the four test years (2019-2022) it lost **42%** of the wallet. At its worst it was **85%** below its peak.

Simpler choices all did better:
- holding BTC: Sharpe 0.87;
- 50/50 BTC and cash, rebalanced monthly: 0.90;
- an equal share of all 20 coins, every Monday: 0.51;
- the rule itself: **0.39**.

Picking coins at random with about the same amount of trading did as well or better in most draws: 169 of 200 random draws had a Sharpe at or above the rule's, and the median draw was 0.54. The rule's choice of coins showed no skill, and its shortfall against the random picks is itself within luck. It traded about 25 times its wallet a year. Compounded, its costs cut the wallet by about 46% against the same trades at no cost (the audit's figure; the day-by-day sum of cost fractions is 0.60, which includes the LEND haircut below).

## The record

| Item | Value | Needed | Result |
|---|---|---|---|
| G1 walk-forward Sharpe (2019-2022, after costs) | 0.388 | ≥ 1.0 | FAIL |
| G2 the same at 2x costs | 0.270 | > 0.5 | FAIL |
| G3 deflated Sharpe, strict count (245: 240 search trials, 4 plateau steps, 1 run at 2x costs) | 0.0076 | ≥ 0.95 | FAIL |
| G4 probability of backtest overfitting | 0.69 | ≤ 0.25 | FAIL |
| G5 plateau: lookback and K ×0.8 / ×1.2 | 0.457, 0.261, 0.366, 0.516 | each ≥ 0.272 (0.7 × 0.388) | FAIL (lookback ×1.2) |
| G6 Monte Carlo 95th-percentile max drawdown | 99.0% | ≤ 60% (Bold budget) | FAIL |
| G7 beats BTC hold, 50/50 and the equal-weight 20 | 0.388 vs 0.870, 0.904, 0.513 | above all three | FAIL |
| G8 regimes: total growth > 0, no regime over half | total log growth -0.54 | | FAIL |
| E1 rank among 200 same-turnover random picks | rank p 0.846 (random p5 0.30, p50 0.54, p95 0.84) | ≤ 0.05 | FAILS |

Other readings:
- **Deflated Sharpe with the raw and the effective trial counts:** 0.0078 and 0.15. The effective count is 10.6 trials.
- **Out-of-sample max drawdown:** 85.3%, against BTC hold's 77.4% over the same span.
- **Regimes, in log growth:** bull months +3.88, bear months -2.64, sideways months -1.78.
- **Correlation of daily returns:** 0.66 with BTC hold, 0.85 with the equal-weight 20.
- **Turnover a year:** the rule 25.3, the random picks 25.5. The random picks' turnover is about equal to the rule's, by design (PLAN.md section 8).

## By year (each fold's choice, then its next year)

| Test year | Chosen (lookback days, K, filter) | Sharpe that year | Rule's return (calendar year) | BTC hold's return |
|---|---|---|---|---|
| 2019 | 91, 3, none | 1.12 | +87% | +88% |
| 2020 | 91, 3, none | 0.06 | -54% | +312% |
| 2021 | 56, 10, abs_mom | 1.62 | +248% | +61% |
| 2022 | 56, 10, abs_mom | -2.25 | -81% | -66% |

The choice moved between folds. The rule swung hard: it lost 54% in 2020 while BTC gained 312%, more than tripled in 2021, and lost 81% in 2022.

**The one forced sale.** S's only forced sale was LENDUSDT on 2020-10-14, while it held 3 coins; the pinned 30% haircut for a coin with no further bar cost about 10% of the wallet that day (-11.0% on the day). LEND most likely moved to AAVE rather than failing (public history, not the data). Without the haircut, the audit puts Sharpe at about 0.41 and the total return at about -35%; no gate moves. Later Bold plans should say in advance how coin migrations and renames are handled.

## What this means

The plan's verdict rule gives NOT A CANDIDATE: weekly momentum across the top-20 coins shows no edge on 2017-2022 after costs. The rule was beaten by random coin picks with the same turnover, by holding BTC, and by an equal mix of the same coins. Nothing goes to the app from this study. No amendment run is planned: every gate fails, and only the plateau gate (G5) is near its line (0.261 against 0.272). As the plan says, one independent audit follows.
