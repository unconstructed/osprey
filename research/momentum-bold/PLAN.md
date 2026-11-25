# momentum-bold: pre-registration

**Status: PRE-REGISTRATION.** Written 2026-11-25 from the owner's answers
([reports/director/2026-11-25-owner-answer-momentum-bold.md](../../reports/director/2026-11-25-owner-answer-momentum-bold.md)),
before any bar of the Bold data was read. The code was built and tested on synthetic coins only. The owner asked for
low token use: one short plan, one builder, no separate code review, one audit after run 0.

> **SCOUTING ONLY.** Every number comes from the lab's reference engine (`lab/runner/momentum.py`, built on
> `lab/runner/portfolio.py`'s execution model), not NautilusTrader (AGENTS.md hard rule 3). Costs are the placeholder
> costs of `config/costs.yaml`. Binance candles stand in for Base prices, and the pool holds coins that are not on
> Bold's (empty) vetted Base list: production could only trade vetted Base coins (owner decision 2). Nothing here makes
> anything ready for paper.

## 1. Hypothesis

Coins that rose most over the last few weeks keep beating the other large coins over the next week. Why it could
persist: attention and flows chase recent winners on exchanges, news reaches holders slowly, and many holders cannot
short, so winners are not arbitraged away quickly (cross-sectional crypto momentum at 1-4 week horizons is reported
in the literature, e.g. Liu, Tsyvinski and Wu 2022). **What proves it wrong:** after costs, the rule's walk-forward
Sharpe is not above 95% of random selections from the same universe with the same cash share (E1), or it does not
beat the equal-weight top-20 basket (G7), or its profit comes from one regime (G8). Six timing studies on BTC and ETH
found no edge; this one tests selection across coins, which is a different idea and should be little correlated with
them (both hold mostly crypto in bull markets, so the daily-return correlation with the Steady studies is reported,
not gated).

## 2. Level, coins, bars, holding

- Risk level **Bold**. Drawdown budget **60%** (Monte Carlo 95th-percentile max drawdown), read from
  `config/risk_levels.yaml` (`bold.max_drawdown_budget_pct`), never typed.
- Pool: at each Monday, the top 20 Binance USDT spot coins by trading volume at that time, delisted coins included
  (owner decision 2; section 4). Spot only, long only, the rest in USDC.
- Daily bars (close at 00:00 UTC). Holding period one week (Monday close to Monday close).
- Free parameters: **3** (lookback, K, cash filter). The rebalance day is pinned to Monday (the bar of Sunday, as
  `trend.py`), so AGENTS.md's fourth parameter is not searched.
- Settings ranges: **fixed settings**. No setting a user can change is studied (AGENTS.md "Fixed settings"); a range
  would need `risk-officer`'s pre-registration by a dated amendment before run 0.

## 3. Data

- `lab/data/bold.py: load_bold_daily(end, catalog_dir="data/catalog_bold")` (built by the data agent in parallel):
  {Binance symbol: daily frame with `open, high, low, close, volume, quote_volume`}, indexed by tz-aware UTC bar
  close time, missing days left missing, refusing anything after the 2024-07-01 close. `bold_snapshot()` gives the
  snapshot id and hash.
- **Train window only.** The run asks for `end = 2023-01-01 00:00 UTC` (the last train close, `config/splits.yaml`)
  and stops (stop rule 3) if any returned close is later. No validate and no test bar is read in this study's run 0.
- **Snapshot pin (amendment D1, before run 0).** When the data agent's catalog exists, the lead writes its snapshot id
  and hash into `run.py`'s `SNAPSHOT` and into section 12 here, in one dated amendment. A real run refuses while
  `SNAPSHOT` is None or differs from `bold_snapshot()`.
- **Panel.** `momentum.make_wide_panel`: one column block per symbol (`open, high, low, close, volume, quote_volume`),
  on the daily grid from the first close of any symbol to 2023-01-01; a day a coin lacks is NaN. The run keeps rows
  from BTCUSDT's first close on, and stops (stop rule 2) unless BTCUSDT has every close from there to 2023-01-01, every
  close is at 00:00 UTC and every bar is valid (positive prices, low <= open, close <= high, volumes >= 0).

## 4. Universe (point in time, each Monday close t)

A coin is **eligible** at t when all hold:
1. It is not excluded (below). BTC and ETH are never excluded.
2. It has a bar at t.
3. Its first bar in the panel is at least **91 rows** (days) before t (minimum history; it also guarantees a close at
   or before t - 91 for the longest lookback).
4. Its trailing 30-day quote volume, the sum of `quote_volume` over rows t-29..t (a missing day counts 0), is > 0.

The **universe** U(t) is the 20 eligible coins with the largest 30-day quote volume (fewer if fewer are eligible;
ties to the symbol first in ascending order).

**Exclusions** (by base asset, the symbol without `USDT`), fixed lists in `momentum.py`:
- Stablecoins: USDC, BUSD, TUSD, USDP, PAX, USDS, USDSB, DAI, FDUSD, SUSD, UST, USTC, GUSD, USDD, PYUSD, EURI, AEUR,
  USDJ, FRAX, LUSD, USDE, USD1, BFUSD, XUSD.
- Fiat: EUR, GBP, AUD, JPY, TRY, BRL, RUB, UAH, NGN, ZAR, IDRT, BIDR, BVND, BKRW, ARS, PLN, RON, MXN, COP, CZK.
- Wrapped or pegged: WBTC, WBETH, BETH, STETH, RENBTC, PAXG, XAUT, BTCB, WETH, CBETH, RETH.
- Leveraged tokens (patterns): a base `<X>UP` or `<X>DOWN` where X is one of Binance's 20 leveraged-token
  underlyings (BTC, ETH, BNB, ADA, LINK, DOT, XRP, LTC, TRX, EOS, XTZ, YFI, SXP, FIL, UNI, SUSHI, AAVE, BCH, XLM,
  1INCH), and any base ending in `BULL` or `BEAR` (BULL and BEAR themselves included). A plain coin ending in UP
  (JUP) is not excluded.

The lists are fixed now. A coin missed by them that turns up in run 0's universe is reported, never removed after the
fact (a removal is an amendment run with its trials counted).

## 5. The rule and execution

Each Monday close t:
1. For every coin in U(t), the trailing return R = close_t / (its last close at or before row t - L) - 1. A coin
   without such a close is not ranked.
2. Rank by R, highest first (ties to the symbol first). Select the top K.
3. Cash filter:
   - `none`: keep the K.
   - `abs_mom`: keep only those with R > 0 (strict).
   - `btc_sma200`: keep the K only if BTC's close at t is strictly above the mean of its 200 closes t-199..t
     (`math.fsum` / 200); otherwise hold nothing. Without 200 closes the filter holds nothing.
4. Targets: each kept coin **1/K** of the wallet, the rest USDC (fewer coins means more cash).

Execution (hard rule 4): the order decided at close t fills at the open of t+1. Every Monday the whole book is cut
back to the targets (no band). The book holds coin units and USDC; weights drift between Mondays. A fill follows
`portfolio.py`: V_open = cash + units x open; a coin's leg is |target - drifted weight| x V_open in USD and costs
`usd x rate(usd) + gas`; the legs' costs come out of the book pro rata; then units = target x V_after / open. A coin
targeted but without a bar at the fill row is not bought (its share stays cash). No order is sent on other days; the
decision at the last close is never filled. Start: 10,000 USD, all USDC.

**Grid (the search box):** lookback L in {14, 28, 56, 91} days x K in {3, 5, 10} x filter in {none, btc_sma200,
abs_mom}: 36 settings, searched as categorical choices.

## 6. Delisting

A held coin with no bar at row t (its data ended, or a missing day) is sold at row t at **its last close x (1 - 0.30)**
(a 30% haircut, pinned), paying the coin's leg cost on the proceeds (capped at the proceeds), before any fill on
that row. The haircut counts as cost. This is point in time: the absence is known at row t. A coin that comes back
after a missing day is not bought back until the next Monday. Forced sales are counted and reported.

## 7. Costs

From `config/costs.yaml`, per leg: BTC and ETH pay the placeholder pool fee + aggregator fee + slippage (by trade
size) + gas; every other coin pays the pool fee and slippage times `small_coin_cost_multiplier` (2.0, owner decision 4;
`momentum.coin_costs` reads the key, which `Costs.from_yaml` ignores), with the aggregator fee and gas unchanged. The
2x rerun (G2) multiplies every cost, gas included (`Costs.stressed(2.0)`), on top of the small-coin multiplier.
Costs are always on.

## 8. Luck control: the random-selection null (E1)

For each draw j = 0..199 and fold i, the fold's chosen setting runs with its selection replaced (seed
`10000 (i + 1) + j`). Every Monday the null holds as many coins as the rule kept (n, each at 1/K). It keeps as many
of its own previous coins as the rule kept of its previous selection (capped by its previous coins still ranked and
by n), chosen at random among those, and draws the rest at random from that Monday's ranked coins it did not hold
(then, if too few, from its previous coins not kept). Draws are uniform without replacement. So the null has the
rule's universe, Mondays, coin count, cash share (the filter's timing is the rule's) and number of swaps, hence about
the same turnover (both means are reported), and differs only in which coins. Draws are stitched over the folds as S.

**E1 holds** when rank p = (1 + #{draws with Sharpe >= Sharpe(S)}) / 201 <= 0.05 (at most 9 of 200 at or above).

## 9. Benchmarks (G7), run on S's slices and stitched as S

- B1 buy-and-hold BTC (bought at the slice's first row).
- B2 50/50 BTC/USDC, restored every 30 rows from the slice's first row ("monthly").
- B3 the equal-weight universe: each Monday every coin of U(t) at 1/|U(t)|, fully invested.

All at 1x costs through the same engine.

## 10. Validation (train window only)

- **Folds.** `walk_forward(n, n - 4 x 365, 365, expanding=True)` on the panel's n rows: four 365-day test blocks
  ending at 2023-01-01, train from row 0. Each block is run with 200 warmup rows (`momentum.WARMUP`, so every window
  of the rule is full at the block's first row).
- **Search.** `lab.search.walkforward.walk_forward_optimize` unchanged: per fold an Optuna TPE study of **60 trials**
  (seed 0 + 1000 i, one worker, so it is reproducible) over the 36 settings, score = `objective.evaluate_params`
  (block Sharpe after costs), the choice by `stability.stable_region` (k = 10). Every trial is logged under
  `results/momentum-bold/run<k>/studies/`, failures included. S = the stitched out-of-sample returns.
- **Trial count.** Raw = 240 search trials. Strict = raw + 4 plateau steps + 1 run at 2x = **245**. The random draws
  and benchmarks are not candidates and are not counted.
- **Gates** (AGENTS.md defaults; PASS, FAIL or MISSING; a missing number never passes):

| Gate | Rule |
|---|---|
| G1 | Annualised Sharpe of S (365 days) >= 1.0 |
| G2 | Sharpe of S rerun at 2x costs (same chosen settings) > 0.5 |
| G3 | DSR of S with every search trial's Sharpe (`overfitting_report`'s) at the strict count >= 0.95 (the effective-count DSR is reported) |
| G4 | Mean PBO over the four studies (`overfitting_report`) <= 0.25 |
| G5 | Plateau: lookback and K each x0.8 and x1.2 in every fold (rounded half up; K within 1..20), held fixed over S's span: each keeps >= 0.7 x Sharpe(S); fails whenever Sharpe(S) <= 0 |
| G6 | `overfitting_report`'s Monte Carlo worst-5% drawdown of S (block bootstrap, mean block 20, 1000 draws) >= -budget (-0.60) |
| G7 | Sharpe(S) strictly above each of B1, B2 and B3 |
| G8 | Regimes as `steady.regime_split`: months by BTC's bar-day return (>= +10% bull, <= -10% bear, else sideways); passes when S's total log growth > 0 and no regime holds more than half of it |

- **Verdict.** CANDIDATE FOR AUDIT only when G1-G8 all PASS and E1 holds; otherwise NOT A CANDIDATE with the failing
  items. Either way one `backtest-auditor` audit follows. A candidate would still need a NautilusTrader rerun, the
  validate look (by a later plan) and the test window before paper.
- **Reported, not gated:** each fold's choice; total return, max drawdown, turnover a year, cost paid, fill rows, mean
  coins held and forced sales of S, S at 2x, the plateau steps and the benchmarks (and the null's mean turnover, fill
  rows and forced sales); the null's p5/p50/p95 Sharpe; walk-forward efficiency; the effective trial count; and the
  correlation of S's daily returns with B1 and B3. The correlation with the Steady studies' S (their results folders)
  is left to the audit.

## 11. Trade frequency and known weaknesses

- One rebalance a week: about 52 orders a year, each with up to K + (coins leaving) legs. With K = 10 and 0.10 USD gas
  a leg, gas alone is about 0.5% a year on 10,000 USD; small-coin slippage is the bigger cost.
- 2017-2018 has few USDT coins (the universe is often under 20), so fold 0 trains on a thin market.
- The 30% haircut is a guess; real delistings vary. The sale happens a day after the last close.
- Binance volume includes wash trading on some coins; volume rank is a proxy for liquidity on Base, not a measure.
- Momentum is known to crash after sharp reversals; a 60% budget may still be too small for K = 3.
- Four folds of one year each: G3 and G4 have little data; a real edge can fail them (TESTING.md: DSR is strict).

## 12. Stop rules and amendments

1. A real run starts only on a commit where the full test tier passed (hard rule 11) and from a clean git tree.
2. Data: the snapshot must equal `SNAPSHOT`; the bars must make a valid panel with BTCUSDT complete; otherwise stop.
3. A close after 2023-01-01 00:00 UTC returned by the loader stops the run; nothing from it is used, and the owner is
   told.
4. A failing trial is logged by Optuna and the search goes on; failed trials are counted and listed.
5. S rerun from the chosen settings must equal `walk_forward_optimize`'s out-of-sample returns bit for bit.
6. Run 0 runs once. An amendment run k (1..2) needs a dated `- **Amendment run k**` row below and counts every
   earlier trial. A run number is never reused, and a run is never resumed.
7. A real run refuses when the `--time` projection is above **120 CPU-minutes**.
8. A hashed file (run.py's `frozen_paths`, config included) changing during the run stops it.

Amendments (dated rows, appended; none yet):

- D1 (before run 0): the data snapshot id and hash, written into `run.py`'s `SNAPSHOT` and here.

## 13. Order of work and outputs

1. This plan, `lab/runner/momentum.py`, `research/momentum-bold/run.py` and their tests
   (`tests/test_momentum.py`, `tests/test_momentum_run.py`), on synthetic data only.
2. The full test tier on the build's commit (lead).
3. Amendment D1 when the data agent's snapshot exists; `run.py --time` on the run machine.
4. Run 0: `.venv/bin/python research/momentum-bold/run.py`. Outputs in `results/momentum-bold/run0/`: `start.json`
   (written with the RUNLOG line before any bar is read), `summary.json`, `oos.parquet` (S, S at 2x, the plateau steps,
   B1-B3), `null.parquet`, `folds.csv`, `studies/`. `research/momentum-bold/RUNLOG.jsonl` is tracked.
5. `RESULTS.md`, then one `backtest-auditor` audit. No validate look and no test look in this study.

**Validate-window looks used: 0.**
