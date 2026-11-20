# rebalance-steady: pre-registration

Written 2026-11-20 by `quant-researcher`, **before any result exists**. Finalized the same day after the
`backtest-auditor` and `risk-officer` reviews (section 16), still before any result. Repo HEAD at writing `04eb81f`,
plus the uncommitted part-1 code (`lab/runner/portfolio.py`, `lab/data/panel.py`, `tests/test_portfolio.py`,
`tests/test_panel.py`). Data snapshot `1746a21b75683e76` (bars content hash `08f5ca2c…`, created
2026-11-20T02:49:20Z). Risk level **Steady**: coins BTC and ETH, USDC is cash. Every profit number this study produces
is **SCOUTING** from the reference backtester, not NautilusTrader (hard rule 3; the Nautilus work is on hold), with
the **placeholder** costs of `config/costs.yaml`. It is labelled that way everywhere. Nothing goes into
`reports/<strategy>/` or `strategies/`.

The only real-data numbers in this file are coverage counts and dates from [DATA.md](DATA.md), and the dip-timing
study's numbers quoted in section 2. The fold dates in section 7 were derived from DATA.md's counts on a rebuilt
date grid. The catalog was not read, and no price was used. Every other number here comes from code, config files
or synthetic data, and says so.

## 1. Question and hypothesis

**Question.** A Steady portfolio holds BTC, ETH and USDC at target weights inside the Steady limits and rebalances
when drift exceeds a band. Does it earn a better risk-adjusted return after costs than:
- the same mix held without rebalancing for up to a year (B4, section 8);
- the same mix rebalanced as often, but at random closes;
- the lab benchmarks, buy-and-hold BTC and 50/50 BTC/USDC monthly?

And does it pass the AGENTS.md gates? "No edge" is an acceptable answer.

**Hypothesis.** BTC and ETH are very volatile. They move partly independently of each other and of cash.
Rebalancing to fixed weights sells what has risen and buys what has fallen. When relative prices swing back and
forth, this earns a rebalancing return that a static mix does not. The band makes the rule trade only when drift is
large. Why it might persist: the return comes from volatility and imperfect correlation, not from a pattern that
others trade away. Costs on Base are small next to large drifts.

**This is wrong if** (section 10) either of these fails on the walk-forward out-of-sample span (about the calendar
years 2019-2022) after costs:
- **E1:** the rule's Sharpe is above the 95th percentile of random rebalancing with the same targets and the same
  number of rebalances;
- **E2:** the rule's Sharpe is significantly above the same mix bought at the start of each one-year
  out-of-sample block and never rebalanced inside it. **E2 is a claim about horizons of up to about one year:** the
  static mix is reset to the targets, at no cost, at the start of each block (section 8, B4).

The main way it can fail is that crypto trends. Then rebalancing sells winners early and loses to the static mix.
The one-year reset of B4 makes that failure harder to see than a multi-year hold would (section 14, known
weaknesses); a multi-year static mix is reported as a description (B4-span). The dip-timing study is a warning for
E1: buying after a 15% drop did no better than buying at random times (research/dip-timing/RESULTS.md). A
rebalancer also buys after drops.

## 2. Prior looks (disclosure)

The recommendation to study `rebalance-steady` came **after** `research/dip-timing/RESULTS.md` was read. That file
reports descriptive numbers for two mixes close to this study's search space, on train **and** validate, with the
same cost model and engine. Quoted exactly:

| Mix in RESULTS.md | In this study's terms | Train (whole window) | Validate (whole window) |
|---|---|---|---|
| "Buy-and-hold": a USD 10,000 sleeve each in BTC and ETH, bought once | 50% BTC / 50% ETH, never rebalanced, no cash | Sharpe 1.242, +7985.4%, max drawdown −92.8% | Sharpe 1.917, +230.5%, −22.7% |
| "50/50 every 30 days": each sleeve 50% coin / 50% USDC (`constant_mix`) | about 25% BTC / 25% ETH / 50% USDC; each coin rebalanced against its own cash every 30 days, never BTC against ETH | Sharpe 1.339, +2216.4%, −68.0%, 146 trades | Sharpe 1.879, +90.0%, −12.4% |

The same file also gives: the average daily simple return over train, +0.21% BTC and +0.38% ETH; random-entry
Sharpe percentiles (5/50/95) of 0.389 / 0.902 / 1.311 on train and −0.166 / 0.763 / 2.006 on validate; the T1
dip-buying results; and the description of validate as a bull market.

**What this means.**
- The second mix is close to one point of this space: coin share 0.5, BTC share 0.5, every 30, band near 0. So we
  already know that one Steady-compatible mix had a Sharpe above 1.0 over all of train and over validate. Gate G1
  (OOS Sharpe ≥ 1.0) is therefore **weak evidence**: a pass was half expected when the study was chosen.
- **Counted honestly:** 0 looks at this rule; 1 prior look (P1, section 15) at 2 neighbouring mixes, on train and
  validate. Those 2 mixes are added to the strict trial count (section 12).
- Nothing known speaks to E1 or E2. Nobody has band-rebalanced a BTC/ETH/USDC mix on real data, run the
  random-rebalance null or the static mix of the same targets, or looked at the 2019-2022 out-of-sample span on its
  own.
- Validate is not fresh for "does a BTC/ETH mix do well?". The validate check (E6) can reject but not confirm.
- **Strategy-level selection.** `rebalance-steady` was chosen after dip-buying failed (dip-timing study: NO EDGE,
  audit PASS; owner decision). The DSR here counts the trials inside this study only, not that choice between
  strategies.
- The author knows the broad public price history (the 2017 bubble, the 2018 crash, the 2020-21 rise, the 2022 bear
  market, the 2023-24 recovery). That shapes priors and cannot be undone.
- While checking for prior looks, the author read the data quality reports (`reports/data/2026-11-20*.md`). They
  list the largest single-bar moves and wicks per series over the whole catalog, including some dates in the test
  window. These are data checks on single bars, not results of any strategy. No number from them is used here.

These looks were not looks at this strategy. They are logged in section 15. **Validate looks used for
rebalance-steady so far: 0.**

## 3. Data

| Item | Pinned |
|---|---|
| Primary | Kraken daily bars, `BTC/USD.KRAKEN` and `ETH/USD.KRAKEN`, through `lab.data.panel.load_panel("KRAKEN", "1d", last_close=...)` |
| Robustness | Binance daily bars, `BTCUSDT.BINANCE` and `ETHUSDT.BINANCE` (quoted in USDT, not USD), the same call with `"BINANCE"`. **No search on Binance:** the Kraken-chosen parameters are re-run on it (E5), on the same closes (section 8) |
| Train phase | `last_close = 2023-01-01 00:00 UTC`, the last train close. Kraken 2190 rows (closes 2017-01-02 .. 2023-01-01), Binance 1963 rows (from 2017-08-18). Validate closes are not loaded at all in this phase |
| Validate look | `last_close = 2024-07-01 00:00 UTC`, the last validate close. Kraken 2737 rows, validate = rows 2190-2736 (547 closes, 2023-01-02 .. 2024-07-01); Binance 2510 rows |
| Bars | Daily, close at 00:00 UTC. One panel row = one close. Decisions at a close, fills at the next open |
| Alignment | `load_panel`'s inner join on close time; nothing filled. Kraken drops one close, 2018-01-13 (no ETH bar). The rows for closes 2018-01-12 and 2018-01-14 are adjacent, so that one return spans 2 days. It lies inside every training window and in no warmup or out-of-sample slice. On Binance, the 228 train closes before 2017-08-18 do not exist; every Binance slice used (section 8) starts after that |
| Slicing | Every harness slice is defined by **close times** taken from the Kraken panel and applied with `.loc` to each panel (section 8). Row numbers are used only on the Kraken panel |
| Snapshot | Every run reads `data/catalog/SNAPSHOT.json` and records `snapshot_id` and `bars_content_sha256`. If the bars hash is not `08f5ca2ca56dbba2526673bcf3515e25ca6d097da4c91b6c08e492ae21b3cd1e`, stop and amend: the counts above would no longer hold |
| Test window | **Never read.** No call asks for a close after 2024-07-01 00:00 UTC. `load_panel` raises `HoldoutWindowError` for such a request or for any returned bar after it. Each script also asserts `panel.index.max() <= last_close` on every frame it loads |

## 4. The rule and the Steady limits

`lab.runner.portfolio.rebalance(params, bars, costs)` with `w_btc`, `w_eth`, `band`, `every`, `min_cash`,
`max_coin` and `headroom`. Its semantics, pinned (they match the code at the hashes in section 13, A3):

| Step | Rule |
|---|---|
| Targets | w_btc + w_eth ≤ 1 exactly (cash = the rest). They must keep `headroom` h inside every limit: w_btc + w_eth ≤ 1 − min_cash − h and each coin ≤ max_coin − h, up to 1e-9 (`LIMIT_TOL`); otherwise `rebalance` raises `ValueError`. h = 0.02 (A2) |
| Decision | At the close of row t, from the weights at that close (drifted by prices since the last fill) |
| Fill | At the open of row t+1. The order is the full target vector. Each coin is a swap against USDC at its own open. A leg with zero change does not trade. An order decided at the last close is never filled |
| First buy | Close 0 of a run (empty book) orders the targets |
| Check closes | Rows 0, every, 2·every, ... of the run's own slice, whatever orders a breach forced in between. So the check phase is set by where the run starts |
| Band | At a check close, order the targets if \|w_BTC − target_BTC\| > band or \|w_ETH − target_ETH\| > band (strict) |
| Limit breach | At **any** close, order the targets if w_BTC + w_ETH > 1 − min_cash + 1e-9 or either coin > max_coin + 1e-9 (today 0.80 and 0.60), whatever `every` and `band` say. Breaches are judged at the limits themselves, not at limit − h |
| Between fills | Coin units and cash are held. Weights drift. Nothing is rebalanced for free |
| Cash | USDC at price 1, no yield |
| Costs | `config/costs.yaml` via `Costs.from_yaml()`, built once per run, per leg: traded share × (5 bps pool + 0 aggregator + slippage at the leg's USD size) + USD 0.10 gas. The book starts at USD 10,000 at the start of every run and compounds (B3 and B4 start from S's book, section 8). Gas is 0.1 bp of a USD 10,000 book per leg, however small the leg, so a rule that trades daily pays gas daily. A fill's cost is shared pro rata by the post-trade book, so the engine holds exactly the targets after a fill |
| Results | `ret`, `position`, `turnover`, `cost`, `w_BTC`, `w_ETH`; `attrs`: `trade_returns` (one per fill row, from just before that fill's swaps to just before the next fill's; the last marked to market at the last close), `n_trades` (fill rows), `fills` (one row per leg), `orders` |

**Steady limits.** Read with `lab.runner.portfolio.risk_limits("steady")` from `config/risk_levels.yaml` at the
start of each run, never typed: `min_cash = min_cash_pct / 100`, `max_coin = max_coin_pct / 100` (today 20 and 60,
so 0.20 and 0.60), plus the file's SHA-256. `risk_limits` raises unless the Steady coin list is exactly BTC, ETH
and USDC. The values and the hash are recorded in every run's context and summary (section 12). The study never
edits the file. The readings used here, which are the `risk-officer`'s defaults for owner questions 1 and 2
(section 14):
1. The targets must satisfy the limits with headroom h: cash ≥ min_cash + h, each coin ≤ max_coin − h.
2. A drifted breach at any daily close forces a full rebalance to target at the next open. With targets-only
   limits a Steady book could drift like B4, past 80% coins.
3. `max_coin_pct` applies to **each** coin, not to all coins together. If it meant the total, `min_cash` would be
   redundant.
4. `max_coin_pct` does not apply to USDC (which is in the YAML's coin list): USDC is the cash that `min_cash_pct`
   governs, and capping it would force more crypto risk.
5. Breaches are judged at daily closes only. Intraday breaches are not seen. Between a breach close and the next
   open the book sits outside the limits.
6. A breach restores every leg to target, not just to the limit.

**These are interpretations. The owner should confirm them** (section 14).

**Why headroom (A2).** Within the engine the limits hold exactly at fills, because the fill's cost is shared pro
rata. A live account books each fee out of its own swap. The risk-officer rebooked an engine fill per leg on
synthetic data: with a target on a limit, the book ended a few millionths past it, so a live account would breach
again at the next close whatever prices do and re-trade every day. The first-draft box (s up to 0.80) reached the
limits exactly and turned into a limit-driven near-daily rebalancer near its edge. The headroom keeps every target
2 points inside every limit.

**Production notes, not engine behaviour** (for the eventual risk note; the engine fills both legs together at one
open): a production node sends sells before buys, so a buy can never take cash below the floor mid-order; the app
checks the caps after the trade, on the full order; a breach is restored by the strategy at the next daily open,
and the app alerts if a breach lasts more than one day; the paper model account must book gas the way the backtest
does (charged to the book), or the paper-versus-backtest comparison is skewed.

## 5. Search space

Four free parameters (the cap). The limits, the headroom and the cost model are fixed, not searched.

| Parameter | Kind | Range | Scale | Maps to |
|---|---|---|---|---|
| `coin_share` s | float | 0.20 - 0.77 | linear | w_btc + w_eth. Cash = 1 − s ≥ 0.23 |
| `btc_share` f | float | 0.25 - 0.75 | linear | w_btc = s·f, w_eth = s·(1 − f) |
| `band_rel` b | float | 0.02 - 0.50 | log | band = b·s, in weight units, the same for both coins |
| `every` | int | 1 - 90 | log | check every N rows (days) |

As `lab.search.space.Param` specs: `Param("coin_share", "float", 0.20, 0.77)`, `Param("btc_share", "float", 0.25,
0.75)`, `Param("band_rel", "float", 0.02, 0.50, log=True)`, `Param("every", "int", 1, 90, log=True)`.

- **Every point of the box keeps the headroom.** s ≤ 0.77 keeps cash ≥ 0.23, above min_cash + h = 0.22. With f
  in [0.25, 0.75] each coin is at most 0.77 × 0.75 = 0.5775 ≤ 0.60 − 0.02. s and s·max(f, 1 − f) are largest at
  the box corners, so the 4 (s, f) corners decide feasibility. `run_train.py` checks those corners with
  `portfolio.check_targets` against the limits as read and h, through the adapter's `check_box`, and **refuses to
  start** if any fails (a tighter `risk_levels.yaml` then needs an amended box before any run). No trial can break a
  target check, and no trial is rejected.
- On a 2190-row synthetic panel, all 36 combinations of s in {0.20, 0.50, 0.77}, f in {0.25, 0.50, 0.75}, b in
  {0.02, 0.50} and `every` in {1, 90} ran with the limits as read and h = 0.02 without an error (A1 record,
  section 13). A permanent hypothesis test is in the build list (section 14).
- **Left out:** single-coin sleeves (f near 0 or 1) at s below 0.6, where they would be feasible. This keeps the box
  a plain rectangle, which the stable-region finder needs (it measures distance in a fixed box).
- **Why a relative band.** A coin's drift scales with its weight. An absolute band means different things at s =
  0.2 and at s = 0.77. b is how far either coin may drift, as a share of the coin sleeve. At s = 0.5, b = 0.02 is a
  1-point band. At s = 0.77, b = 0.5 is a 0.385 band, so mostly only the limits can trigger.
- **Why log scales.** A band of 1 against 2 points matters as much as 20 against 40. A daily against a weekly check
  matters more than day 60 against day 67.
- **Implementation (adapter, section 14).** `steady_backtest(params, bars, *, limits, costs)` calls
  `rebalance({"w_btc": s·f, "w_eth": s·(1 − f), "band": b·s, "every": every, "min_cash": limits["min_cash"],
  "max_coin": limits["max_coin"], "headroom": HEADROOM}, bars, costs)` with `HEADROOM = 0.02`. `limits` is the dict
  `risk_limits("steady")` returned at the start of the run, and `costs` is `Costs.from_yaml()` (1x) or
  `Costs.from_yaml().stressed()` (2x, k = `stress_multiplier` = 2.0), both built once at run start. `run_train.py`
  binds them with `functools.partial` (picklable) and passes the result to `lab/search` as the `BacktestFn`.
  `lab/search` and `lab/validation` run unchanged.
- **Weak spot, disclosed now.** A Sharpe objective hardly identifies s: a cash/coin mix's Sharpe barely depends on
  the coin share. Only costs, the band and the limits make a difference. The stable-region pick in s therefore says
  little, and the folds may choose different s. Yet s drives drawdown. s is searched because the owner listed target
  weights as free (owner question 3). The report shows how score, Sharpe and drawdown depend on s (section 10, from
  the trial log, no new runs).

## 6. Objective

`lab.search.objective.evaluate_params` as is, through `lab.search.study.run_study`, with
`SearchConfig(n_trials=200, n_workers=1, n_blocks=4, penalty=0.5, seed=..., periods_per_year=365, min_trades=5)`
(N = 200 from A1).

- Score = the mean of 4 block Sharpes (annualised with √365) − 0.5 × their standard deviation, over the fold's
  training rows, after costs at 1x.
- **min_trades = 5, the lab default.** `evaluate_params` counts `len(trade_returns)`. For `rebalance`, that is one
  entry per fill row: each is the period from one fill to the next, and the initial buy counts. So 5 means the
  initial buy plus at least 4 rebalances in the training window, about one per objective block. A config that
  rebalances less is close to the static mix. That mix is measured anyway (B4), so the penalty does not hide it.
  Keeping the default adds no new choice. Scores of −10 are logged like any other.

## 7. Walk-forward, search and selection

**Folds.** `lab.validation.splits.walk_forward(2190, train_size=730, test_size=365, expanding=True)`, on the
Kraken train panel:

| Fold | Train rows (closes) | Test rows (closes) | Warmup starts (row, close) | Out-of-sample returns |
|---|---|---|---|---|
| 0 | 0-729 (2017-01-02 .. 2019-01-02) | 730-1094 (2019-01-03 .. 2020-01-02) | 610, 2018-09-05 | 364, closes 2019-01-04 .. 2020-01-02 |
| 1 | 0-1094 (.. 2020-01-02) | 1095-1459 (2020-01-03 .. 2021-01-01) | 975, 2019-09-05 | 364 |
| 2 | 0-1459 (.. 2021-01-01) | 1460-1824 (2021-01-02 .. 2022-01-01) | 1340, 2020-09-04 | 364 |
| 3 | 0-1824 (.. 2022-01-01) | 1825-2189 (2022-01-02 .. 2023-01-01) | 1705, 2021-09-04 | 364 |

- **Out-of-sample span:** 4 × 364 = 1456 daily returns, about the calendar years 2019-2022. `walk_forward_optimize`
  keeps the returns of rows test[0]+1 .. test[-1], the decisions made inside each block, and stitches them.
- **Expanding** windows. The rule has no fitted model, so more history only steadies the score. A two-year minimum
  puts the 2017 bubble and the 2018 crash in every training window.
- **No purge, no embargo** (`purge=0`). There are no labels. The training rows end before the test block, and the
  first return of each block is dropped anyway.
- **Warmup 120 rows** (`warmup=120`, the lab default). No indicator needs history. 120 > 90 ≥ `every`, so at least
  one check close falls inside the warmup. The book enters each block in an ordinary drifted state, and the initial
  buy is paid in the warmup.
- **Final study** for the validate look: `run_study` on all 2190 train rows, same settings, seed + 4000 (as if it
  were fold 4). Its stable-region pick is θ_final. It runs in the train phase, on train data only.

**Optuna.** TPE exactly as in `lab/search/study.py`: multivariate, `n_startup_trials = min(20, max(5, N // 4))` = 20
at N = 200, journal storage. `n_workers = 1`, so every study is exactly reproducible. Fold seeds are `seed + 1000·i`
(the lab's rule). The final study uses `seed + 4000`.

**N, trials per study = 200 (A1, fixed before the train run).** The rule, as amended by the review (a 200-trial
timing instead of 20, so TPE's per-trial cost growth toward 200 trials is in the measurement):
1. Time a 200-trial study of the steady adapter (n_workers = 1) on the largest training slice: the 2190 rows of
   `make_panel(synthetic_market(2190, seed=21, start="2017-01-02"), snapshot_id="synthetic")`.
2. Project the search phase as 10 × that time: every study is costed as the largest, which is conservative since 8
   of the 10 studies are shorter.
3. N = 200 (the lab default) if the projection is at most 60 CPU-minutes. Otherwise N is the largest multiple of 25
   that fits. If fewer than 50 fit, stop and ask the owner.
4. The measurement and N are recorded in A1 (section 13) and copied to RESULTS.md. If the built adapter's single
   backtest is more than 2× slower than the stand-in's on the same synthetic panel, A1 is redone before the run.

**Trial budget.** Per run: 2 seeds × (4 folds + 1 final) = 10 studies × 200 = **2000 trials**, all logged. Each
amendment rerun (at most 2, section 13) adds another 10 studies and 2000 trials, so N_raw is 2000 if nothing is
rerun and at most 6000. Every one of them counts in DSR and PBO (section 12). Strict count: N_raw + 21.

**Selection.** `stable_region(trials, specs, k=10)` inside `walk_forward_optimize`, unchanged. For every fold the
report gives the chosen trial, the range of each parameter over its 10 neighbours with their scores, and the raw
best trial. "Best stable region" means that neighbourhood, never the top trial alone.

**Two searches.** Seed A = 0 (primary) and seed B = 1. They are identical in everything but the seed: 2 × (4 folds +
final) = 10 studies. Every number is reported for both. **FRAGILE** if E1, E2, E3 or any of G1-G8 has a different
outcome for A and B, or if their out-of-sample Sharpes differ by more than 0.25 (a quarter of the G1 threshold).
The distance between the two seeds' chosen parameters (in unit space) is reported, but it does not decide
fragility, because s is weakly identified.

**Study names, one directory.** All studies of every run go in `results/rebalance-steady/train/` (the single
`out_dir` that `overfitting_report` reads). `walk_forward_optimize` appends `_wf00` .. `_wf03` to the name it is
given, so the run tag sits before the fold tag:
- run 0: `rebalance-steady-s0_wf00` .. `_wf03` and `rebalance-steady-s0_final`; the same with `s1`;
- amendment run k (k = 1, 2): `rebalance-steady-s0_a<k>_wf00` .. `_wf03` and `rebalance-steady-s0_a<k>_final`; the
  same with `s1`.

The `context` given to `run_study` holds the snapshot id, the bars hash, the git commit and dirty flag, the config
hash, the source, the interval, the seed, the run number, and the risk limits as read (`min_cash`, `max_coin`, the
raw budget value and the file's SHA-256) (hard rule 7).

## 8. Comparators

All comparators run with costs on (1x unless stated), on exactly the same kept out-of-sample rows as the strategy.

**Slices by close time.** For fold i of the Kraken train panel K (row numbers from `walk_forward` on K):
first_H120 = K.index[test[0] − 120], first_H1 = K.index[test[0] − 1], t0 = K.index[test[0]], last =
K.index[test[-1]]. Each panel P (Kraken or Binance) is sliced with `P.loc[first:last]`. **Before anything runs on a
Binance slice, assert that its index equals the Kraken slice's index; if not, stop.** Kept rows are the slice rows
closing after t0 (`res["ret"].loc[t0:].iloc[1:]`, as `walk_forward_optimize` does).
- **H120** copies `walk_forward_optimize`: run on the slice from first_H120 to last, keep the rows after t0,
  stitch. On K this is exactly `bars.iloc[test[0] − 120 : test[-1] + 1]`.
- **H1**: run on the slice from first_H1 to last. The book is bought at the open of t0, outside the kept rows.

| ID | Comparator | Run | Harness |
|---|---|---|---|
| S | The strategy | `walk_forward_optimize(...)["oos_returns"]` with the 1x steady adapter | H120 |
| B1 | Buy-and-hold BTC | `reference.buy_and_hold({"weight": 1.0}, asset_bars(slice, "BTC"))` | H120 |
| B2 | 50/50 BTC/USDC monthly | `reference.constant_mix({"weight": 0.5, "every": 30}, asset_bars(slice, "BTC"))` | H120 |
| B3 | Random rebalancing: same targets, same count | `portfolio.random_rebalance({"w_btc", "w_eth" of fold i's choice, "n_rebalances": k_i, "seed": 10·j + i})`, draws j = 0..999 | H1 |
| B4 | Static mix: the same targets, static within each 364-return block | `random_rebalance` with `n_rebalances = 0` | H1 |
| B5 | Limit-only rebalancer (description) | `rebalance` with fold i's w_btc and w_eth, `band` = 1.0 (never band-triggered), `every` = 1, the limits as read and h = 0.02: it rebalances only when a Steady limit is breached | H120 |
| B4-span | Multi-year static mix (description) | For each fold i's targets: `random_rebalance` with `n_rebalances = 0`, bought at the open of fold 0's t0 and held to fold 3's last close; S's 1456 kept rows are kept | H1 over the whole span |

- k_i is the number of S's fill rows among fold i's kept rows (`walk_forward_optimize`'s `oos_trades`). Forced limit
  rebalances count. B3 draws from slice closes 1 .. n−2, which are rows test[0] .. test[-1]−1: exactly the closes
  whose orders fill inside the kept rows. So the count matches exactly, and the draw never depends on prices.
- **B4 restated.** B4 is "static within each 364-return block, reset to the fold's targets at no cost at each block
  start". Across the stitched span it is re-targeted for free 3 times, about once a year. So E2 measures whether
  rebalancing helps over horizons of up to about one year, not over the whole span. B4-span is the multi-year static
  comparator; it is a description and does not enter the verdict.
- **Book size.** B3 and B4 start with `Costs.from_yaml(capital_usd=V)`, where V is S's book value at close
  test[0] − 1 in S's own H120 run of that fold (known before the kept rows). At 2x it is `Costs.from_yaml(
  capital_usd=V2).stressed()` with V2 from S at 2x; on Binance, V from S on Binance. So B3 and B4 trade legs priced
  on the same USD book as S. S's book at the open of t0 still differs from V by the overnight gap; this is small and
  disclosed.
- B3, B4 and B4-span do not apply the Steady limits. They are nulls, not products. B5 applies them: it shows whether
  `band` and `every` add anything beyond the rebalances a Steady product must make anyway.
- **B4 pays no cost in the kept rows** (its only buy fills at the open of t0, outside them), so B4 at 2x equals B4 at
  1x bit for bit.
- **Decisive:** B3 (E1) and B4 (E2, E3) for the research verdict. B1 and B2 for gate G7. B3 stands in for
  AGENTS.md's random-entry benchmark: a rebalancer's "trades" are rebalances. B5 and B4-span are descriptions.
- Also reported, as a description: the correlation of S's daily returns with B1 and B2. No other strategy exists in
  `strategies/` to check against.

## 9. Gates (AGENTS.md defaults, unchanged)

Computed on seed A's stitched out-of-sample series (Kraken, train). The same gates are computed for seed B for the
fragility check. **A missing number fails; it never passes.** `rep` is `overfitting_report(combined, out_dir)` on
the combined dict of section 12.

| Gate | Default | Computed as |
|---|---|---|
| G1 | OOS Sharpe after costs ≥ 1.0 | `lab.search.report.gates(rep)["oos_sharpe >= 1.0"]` |
| G2 | Same with costs doubled > 0.5 | S re-run at 2x costs (the 2x adapter, the same per-fold parameters, H120, no new search): Sharpe > 0.5 |
| G3 | DSR ≥ 0.95, counting every trial | `gates(rep)["dsr (effective) >= 0.95"]` |
| G4 | PBO ≤ 0.25 | `gates(rep)["pbo <= 0.25"]`: the mean of the per-study PBO (10 blocks) over every study |
| G5 | Plateau: every parameter ±20% keeps ≥ 70% of the Sharpe | See below |
| G6 | Monte Carlo 95th-percentile drawdown within the risk level's budget | See below. Today **MISSING = FAIL** |
| G7 | Beats benchmarks on risk-adjusted return | Sharpe(S) > Sharpe(B1) and Sharpe(S) > Sharpe(B2), on the same rows |
| G8 | No single regime makes most of the profit | See below |
| G9 | Final test window, run once | **NOT RUN.** Out of scope; the auditor runs it at sign-off |

**G6, drawdown budget.** `run_train.py` reads `risk_limits("steady")` **before it loads any real bar** and records
the raw `max_drawdown_budget_pct` value, the derived fraction `max_drawdown_budget` and the file's SHA-256 in the
`run_study` context and in `summary.json` (written at start, section 12). G6 uses only that recorded value, for the
whole study:
- `max_drawdown_budget` is `None` (the raw value is anything other than a finite number in (0, 100]; today it is
  `TBD`): G6 = **MISSING = FAIL**, whatever is set later.
- Otherwise G6 = `gates(rep, budget_drawdown=max_drawdown_budget)["MC worst-5% drawdown within ..."]`, i.e. PASS
  iff `rep["mc_drawdown_worst5pct"] >= -pct / 100`. The budget is passed as a fraction, never as a percentage.
- `freeze.py` and `run_validate.py` use only the train-start value. If the file changed since, they follow
  section 13 and never rescore G6.

`rep["mc_drawdown_worst5pct"]` is the stationary block bootstrap of S's stitched returns (mean block 20, 1000
draws, seed 0), as `overfitting_report` computes it.

**Drawdown budget (risk-officer, for the owner).** No number from this SCOUTING study sets, rounds or justifies the
Steady budget; S's drawdowns are descriptions only. A budget is proposed by `risk-officer` only from audited
(Nautilus) results, using a strategy-independent Steady reference pinned before any result. The risk-officer's
proposal for the owner: the riskiest target set this box allows at f = 0.5 (BTC 0.385, ETH 0.385, USDC 0.23),
rebalanced to target every 30 days, with the Steady limits on; budget = its Monte Carlo 95th-percentile max drawdown
(stationary block bootstrap, mean block 20, 1000 draws, seed 0), rounded up to the next 5 points. It must sit below
the Balanced and Bold budgets, needs the owner's written approval, applies only to later audits, never re-scores this
study, and is computed on train only, so it does not spend rebalance-steady's validate window. It is not computed in
this study.

**G5, plateau.** In the searched parametrisation, each of the 4 parameters is moved alone, ×0.8 and ×1.2. The step
applies to every fold's own chosen value at once. Each of the 8 variants is run in H120 and stitched. PASS if all 8
Sharpes are ≥ 0.7 × Sharpe(S) and Sharpe(S) > 0.
- `every`: down = max(1, min(round(0.8·e), e − 1)), up = max(round(1.2·e), e + 1). Rounding is half up.
- Steps are clipped to the **feasible set with headroom**, not to the search box: s ≤ 1 − min_cash − h and
  s·max(f, 1 − f) ≤ max_coin − h (today 0.78 and 0.58), with the other parameters unmoved; the clip moves the
  stepped parameter only. Every step is checked with `check_targets` before it runs; a refusal there is a bug in the
  clip (stop and triage). A clipped step is marked "clipped". A step that cannot move at all (s on its feasible edge
  going up, `every` = 1 going down) repeats S, which passes trivially; it is marked "at the limit".
- **PASS (weak)** if G5 passes and 3 or more of the 8 steps are "clipped" or "at the limit": a pass at the edges is
  not evidence of a plateau. It counts as PASS in the gate table and is named wherever G5 is reported.

**G8, regimes.**
- Each kept row t belongs to the UTC calendar month of its bar's day, the date of (close time − 1 day).
- A month is **bull** if BTC's compounded close-to-close return over that month's kept rows is ≥ +10%, **bear** if
  it is ≤ −10%, and **sideways** otherwise. The thresholds are fixed now and never fitted.
- Profit in a regime = the sum of ln(1 + S_t) over its rows. PASS if the total is > 0 and no regime has more than
  half of it.
- Also reported, as a description: the same split of the excess over B4, Σ ln(1 + S_t) − ln(1 + B4_t).
- **Flag for the owner:** a long-only portfolio makes its money in rising markets by construction. Read literally, G8
  is likely to fail for any Steady strategy. It is applied literally here and not reinterpreted.

**Reading G1 and G3.** A cash/coin mix's Sharpe hardly changes with coin share, so the spread of trial Sharpes that
DSR deflates by will come mostly from the different training windows (730-2190 rows), not from parameter choice.
Like G1 (section 2), G3 is weak evidence of an edge from rebalancing. E1 and E2 carry the research question.

## 10. Research criteria and verdict

Sharpe means `stats.annualized_sharpe(r, 365)` of the daily net returns. Seed A, Kraken, the train walk-forward,
unless stated otherwise.

| Criterion | Holds if |
|---|---|
| **E1** Timing beats chance | Sharpe(S) > the 95th percentile (`np.percentile`, linear) of B3's 1000 Sharpes (draw j's 4 fold pieces stitched into one 1456-row series). The rank p = (1 + #{B3_j ≥ S}) / 1001 is reported |
| **E2** Rebalancing beats holding, over horizons of up to about one year | D = Sharpe(S) − Sharpe(B4) > 0, and the one-sided paired bootstrap p < 0.05. B4 is static within each 364-return block and reset to the fold's targets at no cost at each block start. Bootstrap: 10,000 resamples of the 1456 stitched rows with `montecarlo.stationary_bootstrap_indices(n, 20, rng)`, `rng = np.random.default_rng(0)`, the same indices for S and B4. p = (1 + #{D* ≤ 0}) / 10,001 |
| **E3** It survives doubled costs | Sharpe(S at 2x) > Sharpe(B4 at 2x). B4 pays no cost in the kept rows, so B4 at 2x is B4 at 1x bit for bit: E3 asks whether S at 2x still beats the same static series |
| **E4** The two searches agree | Not FRAGILE (section 7) |
| **E5** It survives the other data source | E1 and E2 hold on Binance: seed A's per-fold parameters, H120 on the same closes, B3 (its own k_i, the same seeds) and B4 on Binance bars, with the same bootstrap |
| **E6** Validate does not contradict (reject-only) | At the look, θ_final(A) on Kraken validate at 1x: Sharpe > 0, ≥ 0.5 × Sharpe(S), > B4's validate Sharpe, and > the median of B3's 1000 validate Sharpes |

E1 and E2 must both hold. That is an intersection test, so each at 5% is conservative and needs no correction.

**Verdict, decided mechanically:**
- **NO EDGE:** E1 or E2 fails.
- **INCONCLUSIVE:** E1 and E2 hold, but any of E3-E6 fails, or the stop rules end the study early.
- **EDGE:** E1-E6 all hold. In words, wherever it is reported: "the band rule beat random rebalancing of the same
  targets, and beat holding the same mix unrebalanced over one-year blocks".

**Headline:**
- **CANDIDATE FOR AUDIT** if EDGE and G1-G8 all PASS.
- **EDGE, NOT A CANDIDATE** if EDGE and any gate FAILS or is MISSING. The failing gates are listed. While the
  drawdown budget is TBD, G6 is MISSING, so this is the best this study can report.
- Otherwise the verdict itself (**NO EDGE** or **INCONCLUSIVE**) is the headline.
- If an amendment run superseded an earlier run, RESULTS.md shows the superseded run's verdict and gate table next
  to the final one (section 13).

**Reported whatever the verdict** (train phase), for both seeds, every number labelled SCOUTING with placeholder
costs:
- per fold: chosen parameters (and w_btc, w_eth and band derived from them), the neighbourhood, the raw best, IS and
  OOS Sharpe, walk-forward efficiency, trades, turnover, costs paid, return, max drawdown and worst day over the
  kept rows;
- the same metrics, stitched, for S, B1-B5, B4-span (B3 as 5/50/95 percentiles and S's rank), S at 2x and Binance;
- the gate table (G5 with its "clipped" and "at the limit" marks); DSR with the effective, raw and strict counts;
  PBO per study and the distribution of each study's PBO logits (`stats.pbo(m, n_blocks=10)["logits"]` on the same
  matrix the report uses: 5/50/95 percentiles and the share ≤ 0, the combinatorial out-of-sample distribution);
- Monte Carlo, all descriptions next to G6's block bootstrap (p5 and p50): `montecarlo.shuffled_trade_drawdowns` on
  S's kept trade periods (the `trade_returns` entries whose fill row is a kept row; these are chained rebalance
  periods, not round trips) and `montecarlo.degrade_execution(S, S's kept turnover, extra_cost_bps=10,
  n_sims=1000, seed=0)` (5/50/95 percentiles of the total against S's total);
- **trades per parameter:** the total out-of-sample fill rows over the 4 folds divided by 4 free parameters,
  flagged if below 30 (fewer than 120 fill rows in 2019-2022);
- the plateau table; the regime table; the correlations;
- **the s-profile** from the trial log, no new runs: score and Sharpe by s-bin ([0.20, 0.30), [0.30, 0.40), ...,
  [0.70, 0.77]) for every study; for the 2 final studies also each trial's historical max drawdown and Monte Carlo
  p5 (block 20, 1000 draws, seed 0) from its logged returns, by s-bin;
- **phase sensitivity:** each fold's chosen parameters re-run with the slice starting j rows earlier, j = 0 .. every
  − 1 (so every check phase occurs; the warmup grows to 120 + j), the same kept rows: per fold, the min, median
  and max OOS Sharpe. These runs reuse trialled parameters, nothing is chosen from them, and their number is
  reported next to the strict count;
- **risk description (risk-officer):**
  1. per fold: the chosen s, w_btc and w_eth, with the historical max drawdown and worst day over the kept rows;
  2. θ_final as one fixed configuration over the whole Kraken train panel (rows 0-2189), labelled **IN-SAMPLE**
     (it is the final study's own trial, re-run): historical max drawdown; Monte Carlo p5 and p50 (block 20, 1000
     draws, seed 0); worst day and 1st-percentile day; lowest cash and highest single-coin weight at any close;
     the number of closes in breach of the limits; legs per year; the USD size of its legs (5/50/95 percentiles
     and max);
  3. the same overshoot statistics (lowest cash, highest coin, closes in breach) for the stitched S;
  4. one sentence: when the folds choose different s, S's Monte Carlo p5 is not the drawdown of any one shippable
     configuration;
- the turnover the stitched curve never paid when targets change between folds: the sum over the 3 boundaries of
  |next fold's targets − S's weights at the last kept close|, for both coins;
- every failure.

## 11. The single validate look

- **Runs only if E1-E5 all hold.** Otherwise E6 cannot change the verdict. The look is not used, and the validate
  window stays unlooked for this strategy.
- **Before it:** the train results are written, and `freeze.py` writes `results/rebalance-steady/FROZEN.json`.
  `freeze.py` first recomputes the config hash and every per-file hash and compares them with the `summary.json` of
  the run whose results are reported; if any differs it **exits non-zero without writing FROZEN.json** (the only
  exception is in section 13, stop rule 10). FROZEN.json holds:
  - the config hash and every frozen file's SHA-256 (section 12);
  - the SHA-256 of every file under `results/rebalance-steady/train/`;
  - θ_final(A) and θ_final(B), and the per-fold parameters;
  - N, the seeds and the run number;
  - the snapshot id, the bars hash and the train panel hash;
  - the risk limits and the drawdown budget as read at train start, with the file's SHA-256;
  - the git state.

  A byte-identical copy goes to `research/rebalance-steady/FROZEN.json`. The lead commits the copy (`results/` is
  git-ignored), with `trials.csv`, `evaluations.csv` and `RUNLOG.jsonl`, before the look.
- **Start guard.** `run_validate.py` refuses to run if the git tree is dirty, if any hash differs from FROZEN.json
  (same rule as `freeze.py`), or if `results/rebalance-steady/validate/STARTED` or `look.json` exists. Otherwise,
  **before loading any validate bar**, it appends its start to `RUNLOG.jsonl` and writes `validate/STARTED` with the
  UTC time. A crashed look counts as the look: any later look falls under stop rule 9 (a new pre-registration, and
  the verdict is INCONCLUSIVE), and it is logged in section 15 and RESULTS.md.
- **Consistency checks, before any validate number.** The panel is `load_panel("KRAKEN", "1d",
  last_close="2024-07-01")`, and the same with `"BINANCE"`. The Kraken panel's first 2190 rows and the Binance
  panel's first 1963 rows must hash to the train panels' hashes in FROZEN.json (section 12). θ_final(A) and
  θ_final(B), re-run on the 2190 Kraken rows, must reproduce the final studies' logged trial returns bit for bit.
  If either check fails, stop: the look is spent and the verdict is INCONCLUSIVE.
- **What runs, once, in one execution of `run_validate.py`.** Validate test rows are Kraken rows 2190-2736.
  - Slices by close time, as in section 8: H120 from close 2022-09-04 (Kraken row 2070) to 2024-07-01; H1 from close
    2023-01-01 (row 2189). t0 = 2023-01-02. Kept rows: closes 2023-01-03 .. 2024-07-01, 546 returns. Every Binance
    slice is `.loc` on the same close times, and its index must equal the Kraken slice's index, or stop.
  - **Decisive (E6):** θ_final(A), Kraken, 1x; with B3 (1000 draws, seeds 10·j, k = its own validate fills among the
    kept rows) and B4, both at 1x and starting from θ_final(A)'s book at close 2023-01-01.
  - **Descriptions only, which cannot change E6 or the verdict:** θ_final(B) with its own B3 and B4; θ_final(A) and
    θ_final(B) at 2x; B1, B2 and B5 at 1x; θ_final(A) on Binance at 1x with its B3 and B4; the regime split and the
    Monte Carlo drawdown.
- **After it:** nothing is tuned or changed. Any change needs a new pre-registration. The look is logged in section
  15 and in RESULTS.md.

## 12. Trial counting and logging

- **Raw count N_raw:** every trial Optuna recorded, in every state, in every study under
  `results/rebalance-steady/train/` (run 0 and every amendment run, crashed studies included, via
  `load_trials`). Nothing is deleted. Expected: 2000 with no rerun, at most 6000.
- **DSR and PBO:** `lab.search.report.overfitting_report`, unchanged, with `out_dir =
  results/rebalance-steady/train/`, on a combined dict built in the study script: `{"oos_returns": S_A,
  "wf_efficiency": wf_A["wf_efficiency"], "studies": <every study of every run>, "total_trials": N_raw}`.
  - The effective count is the sum of `effective_trials` over the studies.
  - Seed B gets the same report with S_B and its own walk-forward efficiency, against the same trial set.
- **Strict count, reported but not gated:** N_raw + 21, and the DSR at that count
  (`stats.deflated_sharpe_ratio(S_A, trial_sharpes, n_trials=N_raw + 21)` with the report's trial Sharpes). The 21:
  16 plateau variants (8 per seed), 2 runs at 2x costs, 1 Binance run (audit F5 of the dip study), and the 2
  neighbouring mixes seen in the dip study (section 2). Benchmarks and null draws (B1-B5, B4-span) are comparators,
  not strategy configurations. θ_final's IN-SAMPLE run is a logged trial, re-run. Phase-sensitivity runs reuse
  trialled parameters and nothing is chosen from them; their number is reported next to the strict count.
- **Config hash** (`study.config_hash()`): SHA-256 over a JSON blob of the per-file SHA-256s of these files (sorted
  by path) and the pinned values:
  - `research/rebalance-steady/PLAN.md`, `DATA.md`, `study.py`, `run_train.py`, `freeze.py`, `run_validate.py`;
  - `lab/runner/portfolio.py`, `reference.py`, `interface.py` and the adapter `lab/runner/steady.py`;
  - `lab/data/panel.py`, `catalog.py`, `external.py`; `lab/config.py`; every `.py` file in `lab/search/` and
    `lab/validation/`;
  - `config/costs.yaml`, `splits.yaml`, `risk_levels.yaml`; `pyproject.toml`, `uv.lock`;
  - the pinned values: the interpretations of section 4, `HEADROOM`, the `SearchConfig` values, N, the seeds, the
    folds and the warmup.

  `RESULTS.md`, `RUNLOG.jsonl` and the FROZEN.json copy are not hashed (they change by design).
- **Recorded before any data is loaded.** `run_train.py` writes `summary.json` at start with the git state, the
  config hash, every per-file hash, the snapshot id and bars hash, the risk limits and budget as read (with the
  file's SHA-256) and the run number. Right after loading the panels, before any backtest, it adds their hashes
  (Kraken and Binance; SHA-256 of the index as int64 microseconds followed by the float64 values, row-major). At the
  end it rewrites `summary.json` with the same start fields, unchanged, plus the results. `freeze.py` and
  `run_validate.py` compare against these start fields.
- **RUNLOG.** Every real-data run of `run_train.py` and `run_validate.py` first appends one line to the tracked
  `research/rebalance-steady/RUNLOG.jsonl`: UTC time, script, run number (or "validate"), git commit and dirty flag,
  config hash, snapshot id, "real". So a deleted-and-rerun train phase leaves a trace in git. Synthetic dry runs log
  to `<out>/RUNLOG.jsonl` in their scratch directory instead.
- **Files, git-ignored,** in `results/rebalance-steady/`:
  - `train/<study>/`: the lab's journal, `meta.json`, `returns/` and `trials.parquet`, for every study of every run;
  - `train/run<k>/summary.json` (start fields, then results);
  - `train/run<k>/trials.parquet`: every trial of every study of runs 0..k, with seed, fold, run, derived weights,
    block Sharpes and context;
  - `train/run<k>/evaluations.parquet`: every run that is not a search trial (comparators, 2x, Binance, plateau,
    phase, IN-SAMPLE θ_final);
  - `train/run<k>/oos.parquet`: the stitched series of S_A, S_B, B1, B2, B4, B5, B4-span and the B3 percentiles;
  - `FROZEN.json`;
  - `validate/STARTED`, `validate/look.json`.
- **Committed record** (the lead commits it): `research/rebalance-steady/trials.csv` and `evaluations.csv`,
  `RUNLOG.jsonl`, the `FROZEN.json` copy, `validate.csv` after the look, and `RESULTS.md`.
- **MLflow:** none. It is not built, and the Nautilus/MLflow work is on hold. This is a logged deviation from the
  "Parquet + MLflow" rule.
- **Synthetic dry runs** test the scripts on `make_panel(synthetic_market(...), snapshot_id="synthetic")`, in a
  scratch directory, never in `results/rebalance-steady/`. They are not trials, and no number from them is
  reported.

## 13. Stop rules, amendments and deviations

**Stop rules.**
1. No number counts unless the full tier (with coverage), the deep profile and ruff pass on the commit the run uses
   (hard rule 11). Before run 0, before each amendment run and before the look, the lead runs them on that commit
   and records the commands and counts in RESULTS.md. On real data, `run_train.py` and `run_validate.py` refuse a
   dirty git tree, so the commit is well defined.
2. The bars hash differs from section 3: stop and amend.
3. The throughput rule allows fewer than 50 trials per study: stop and ask the owner.
4. A study records a failed trial: finish the phase, then triage. If it is a code bug: fix it, add a regression test
   that fails on the old code, write the amendment (below) and rerun the whole train phase as an amendment run. The
   old trials stay and are counted. If triage finds no code bug, the run stands and the failed trials are reported
   and counted.
5. The test-window guard fires: stop. Nothing from that run is used, and it is logged.
6. A crashed run is not resumed: a resumed TPE study need not equal an uninterrupted one. Its trials stay and are
   counted, and the phase is rerun as an amendment run.
7. **Amendment runs** (bug fixes and crashes, after run 0): at most 2, numbered k = 1, 2.
   - `run_train.py` without `--amendment` is run 0. It refuses to start if `results/rebalance-steady/train/` exists.
   - `run_train.py --amendment k` refuses unless `train/run<k−1>/summary.json` exists (written at start, so a
     crashed run counts), and refuses if `train/run<k>/` or any study named with `_a<k>_` exists, or if k > 2.
   - Before run k starts, its amendment row (date, reason, how the bug was found, the regression test) is written
     in this section and committed, so run k's config hash includes it.
   - A bug found by reading train results, not only from a failed trial, follows the same route and counts toward
     the limit.
   - RESULTS.md reports the superseded run's full verdict and gate table (or what it completed) next to the
     final run's. DSR and PBO count every study of every run (section 12).
   - If a third rerun would be needed, stop: the verdict is INCONCLUSIVE and everything is reported.
8. NO EDGE on train: no validate look (section 11).
9. A bug found after the look that changes a validate number, or a second look (including after a crashed look):
   the verdict becomes INCONCLUSIVE. Any further look needs a new pre-registration.
10. **Changes between the train run and the look.** `freeze.py` and `run_validate.py` refuse if the config hash or
    any per-file hash differs from the train run's start record. A deliberate change goes through a Deviations row
    in RESULTS.md and, before the look, a new pre-registration. One exception, so the risk-officer can set a
    budget without blocking this study: if the only file that differs is `config/risk_levels.yaml` and
    `risk_limits("steady")` still gives the same coins, `min_cash` and `max_coin` as at train start, the freeze
    proceeds, records both file hashes, a Deviations row is written, and G6 keeps its train-start value (never
    rescored).

**Amendments.** Dated, written in this section and committed by the lead before the run they affect. All five
below were made on 2026-11-20, after the reviews and **before any run on real data**.
- **A1, N (from the throughput rule, section 7).** N = 200 trials per study. Measured by `quant-researcher` with
  [throughput.py](throughput.py) (synthetic only; output to a scratch directory), on the synthetic panel of section 7,
  with a stand-in for the adapter that makes the pinned `rebalance` call (limits from `risk_limits`, h = 0.02,
  `Costs.from_yaml()`), `n_workers = 1`:
  - a 200-trial study on the 2190 rows: 3.86 s wall, 3.08 s CPU (0.0193 s wall per trial, TPE included; a second
    run after a format-only edit of the script: 4.06 s); a 20-trial study: 0.39 s wall; a 200-trial study on the
    first 730 rows: 3.48 s wall;
  - one backtest on the 2190 rows, median of 20 timed runs: 0.0073 s (s 0.5, f 0.5, b 0.1, every 7) and 0.0088 s
    (s 0.77, f 0.75, b 0.02, every 1); one B3 draw on a 366-row slice, median of 50: 0.0038 s;
  - projection: 10 × 3.86 s = 38.6 s, far below 60 CPU-minutes, so N = 200;
  - Python 3.13.18, Optuna 5.1.0, 4 shared CPUs, load average 0.62 at the start.

  The same script ran the 36 combinations of section 5 without an error and passed the 4 box corners through
  `check_targets` with the limits as read (min_cash 0.2, max_coin 0.6, budget `TBD` → `None`, file SHA-256
  `158d7c9f10eeb664618188455255ca099cc2b265c32833df8a1a37ffab3f16f8`).
- **A2, headroom (risk-officer).** h = 0.02 between every target and every limit; the box's s range becomes
  0.20-0.77 (was 0.20-0.80); G5 steps clip to the feasible set with headroom; breaches are still judged at the
  limits. This tightens this strategy's targets; it does not edit `risk_levels.yaml`.
- **A3, review round.** Every other change in section 16: limits read from `risk_levels.yaml` (not typed), the G6
  budget read at train start, hashes recorded at train start and enforced by `freeze.py`, the STARTED marker,
  amendment runs and their layout, slices by close time, B4 restated, book size of B3 and B4, B5 and B4-span, the
  added descriptions, and the strict count 19 → 21. The pinned code is `lab/runner/portfolio.py` SHA-256
  `3f8088a9729586753b000dd911437336ef3cdfd2f14e24b9102d67cccd6fc597` and `lab/data/panel.py`
  `a3e672b5bd95f7557308df93664ec4f7c26705579a3f47d298444c772bd786f9` as of this amendment (the run records the
  hashes it actually uses).
- **A4, script clarifications (2026-11-20, before any run on real data).** Made while building `study.py`,
  `run_train.py`, `freeze.py` and `run_validate.py` (part-1 open items 4, 5 and 9):
  - **Writers.** `run_train.py` writes `research/rebalance-steady/trials.csv` (every trial of every study of runs
    0..k) and `evaluations.csv` (every evaluation of runs 0..k), rewriting both at the end of each real run.
    `run_validate.py` writes `validate.csv`; `freeze.py` writes the `FROZEN.json` copy. Synthetic dry runs write
    these to `<out>/tracked/`, never into the repo.
  - **Dirty.** A git tree is dirty when `git status --porcelain --untracked-files=all` prints anything: modified,
    staged, deleted and untracked files count; git-ignored files (`results/`, `data/`, caches) do not.
  - **Commit between runs.** A real `run_train.py` run appends to the tracked `RUNLOG.jsonl` and rewrites
    `trials.csv` and `evaluations.csv`, so the tree is dirty after it. The lead commits them before an amendment
    run or the look (the dirty-tree refusal enforces it), and commits the `FROZEN.json` copy before the look
    (section 11).
  - **Amendment row.** Stop rule 7's row for amendment run k is a line in this section that starts with
    `- **Amendment run k` and gives the date, the reason, how the bug was found and the regression test.
    `run_train.py --amendment k` refuses on real data without it.
  - **G6 with amendment runs** (open item 5). G6 uses run 0's train-start reading of `config/risk_levels.yaml`
    for the whole study, amendment runs included. An amendment run records its own reading and uses its
    `min_cash` and `max_coin` for the rule, but never its budget for G6.
  - **Seed B** (open item 9). Seed B's E1 and E2 use its own k_i, its own targets and its own book for B3
    (seeds 10·j + i) and B4, and the same paired bootstrap (rng seed 0); its 2x run and its plateau are its own.
    It differs from seed A only in its chosen parameters.
  - The scripts' other readings, where this plan is loosely worded, are listed in `study.py` (`INTERPRETATIONS`),
    which the config hash covers.
- **A5, review fixes to the scripts (2026-11-20, before any run on real data).** From the code review of part 2
  (TESTING.md bug log #45-#47). None of them changes the rule, a comparator, a criterion or a gate threshold; they
  enforce what sections 4, 11, 12 and 13 already say, or pin a reading:
  - **Folders.** A real run uses the pinned folders only: `--out-dir` `results/rebalance-steady/`, `--config-dir`
    unset (`config/`), `--catalog-dir` `data/catalog/`; all three scripts refuse anything else, so every run reads
    `config/costs.yaml`, `splits.yaml` and `risk_levels.yaml` and the look's marker is
    `results/rebalance-steady/validate/STARTED`. A synthetic dry run refuses `results/rebalance-steady/` and any
    folder inside the repo (section 12).
  - **Amendment runs** continue the same study: `--amendment k` refuses unless every earlier run has the same data
    (real or synthetic) and the same `--fast` setting. Only a `- **Amendment run k` row in this section's list of
    amendments counts (the lines from the Amendments heading to the Deviations heading).
  - **RUNLOG as a guard.** `run_train.py` refuses a run number the RUNLOG already holds for the same data, and
    `run_validate.py` refuses when it holds a look (stop rules 6, 7 and 9): a deleted or copied results folder
    reopens neither a run nor the look.
  - **The reported run** is the highest-numbered run, and it must be complete. A crashed or stopped last run blocks
    the freeze (stop rules 5-7 rerun it as an amendment run); the run it superseded is never frozen.
  - **Triage before the freeze** (stop rule 4). `freeze.py` refuses a run with failed trials unless it is given
    `--triaged "<note>"` (no code bug: the run stands), and FROZEN.json records the note.
  - **The look's own checks.** FROZEN.json's θ_final, per-fold parameters, E1-E5, train verdict, gates and train
    Sharpes must equal the reported run's `summary.json`, whose SHA-256 FROZEN.json holds. B3's kept fills must
    equal k at the look and on Binance in the train phase (E5's "same count"), as on Kraken; otherwise stop.
  - **Gates** are computed by `study.gate_table` from the numbers recorded next to them (`gate_inputs` in
    `summary.json`); a gate with any NaN number is MISSING (G7 has three: S, B1 and B2).

**Deviations.** Every departure from this plan, however small, goes in a Deviations table in RESULTS.md. Each row
says what changed, why, and when relative to which result, with its effect on any number.

**Not done in this study:**
- reading the test window;
- Nautilus, `lab/costs/`, MLflow, or files in `strategies/` or `reports/<strategy>/`;
- hourly bars, intraday limits or fills, other coins, leverage, shorting, or USDC yield;
- tuning on validate, a second look, new parameters or rules after seeing train results (other than a logged
  amendment run);
- setting, proposing or justifying a drawdown budget;
- edits to `config/*.yaml`, `lab/search`, `lab/validation` or the gates.

## 14. Build list, owner questions and known weaknesses

**Built (part 1)**, with the test status measured on 2026-11-20 on HEAD `04eb81f` plus the uncommitted part-1 files
at the hashes in A3 (section 16, row A-1):
- `lab/runner/portfolio.py`: `rebalance` (with `headroom`), `random_rebalance`, `asset_bars`, `make_panel`
  (`snapshot_id` keyword-only and required), `validate_panel`, `risk_limits`, `check_targets`; tested by
  `tests/test_portfolio.py`.
- `lab/data/panel.py`: `load_panel`; tested by `tests/test_panel.py`.

**To build** (all tested before any number counts: 100% branch coverage of `lab/`, the deep profile, ruff):
- **Adapter `lab/runner/steady.py`:**
  - Contents: `HEADROOM = 0.02`; `SPECS`; the parameter mapping; `steady_backtest(params, bars, *, limits, costs)`
    (raises if `limits["min_cash"]` or `limits["max_coin"]` is None); `check_box(specs, limits)` (the 4-corner
    check of section 5); the H120 and H1 harnesses by close time with the Binance index assert; the B3/B4 wrappers
    with S's book size; B5 and B4-span; the G5 steps with their clip and marks; the G8 regime labels and shares; the
    E2 paired bootstrap; the panel hash.
  - Tests:
    - every point of the box passes `check_targets` with ≥ h from both limits as read (a hypothesis property with
      `@example` corners (0.77, 0.75), (0.77, 0.25) and (0.20, 0.25));
    - a tmp `config_dir` with tighter limits changes what `steady_backtest` passes to `rebalance`, and makes
      `check_box` refuse the box; a coin list without ETH, or with an extra coin, raises;
    - the mapping by hand; tamper-the-future on `steady_backtest`;
    - H120 equals `walk_forward_optimize`'s `oos_returns` bit for bit on a synthetic panel (`n_workers=1`, a few
      trials); a Binance-style panel with an offset start gives the same kept index by close time, and a panel
      with a missing close inside a slice makes the assert fire; H1's draws come only from the kept decision
      closes, and B3's count equals k_i; B3/B4 start from S's book at close test[0] − 1; B4 at 2x equals B4 at 1x;
    - G5 steps by hand: `every` 1, 2, 7 and 90; s on the feasible edge; f at 0.75 with s = 0.77; each step passes
      `check_targets` and carries the right mark;
    - G8 labels by hand on a built path; the bootstrap equals a hand resampler.
- `research/rebalance-steady/study.py`, `run_train.py`, `freeze.py`, `run_validate.py`, each dry-run end to end on
  synthetic data in a scratch directory: the start guards (dirty tree, existing `train/`, `--amendment` rules,
  STARTED and look.json), the refusal of `freeze.py` on a changed hash, and the risk-levels exception.

**Owner questions, to answer before the run.** If there is no answer, the default holds and is logged.
1. Does a drifted breach of the Steady limits at any close force a full rebalance (default; risk-officer agrees),
   or do the limits bind only on targets?
2. Is `max_coin_pct: 60` per coin (default; risk-officer agrees) or for all coins together? Does it apply to USDC
   (default: no; if yes, s must be ≥ 0.40)?
3. Should the coin share be searched (default), or fixed or capped by Steady risk appetite? A Sharpe objective
   barely identifies it, and it drives drawdown; the risk-officer recommends fixing or capping it.
4. G8 read literally (default) is likely to fail for long-only portfolios. Does the owner want it defined on the
   excess over a benchmark instead? That would be a change to the gates, which only the owner makes.
5. G6 stays MISSING until a drawdown budget exists, so this study cannot produce CANDIDATE FOR AUDIT. The
   risk-officer's proposal for setting the budget is in section 9; it needs the owner's written approval and never
   re-scores this study.
6. The headroom h = 0.02 (A2) is the risk-officer's proposal. Default: keep it.

**Owner answers (2026-11-20, in chat, before any real-data run).** Q1: a drifted breach at any close forces a full
rebalance (the default). Q3: the coin share is searched over the box of section 5 (the default). Q4: G8 is read
literally (the default; no gate change). Q5: the drawdown budget stays TBD, so G6 is MISSING = FAIL and this study
cannot reach CANDIDATE FOR AUDIT (the default). Q2 and Q6 were not asked; their defaults hold (`max_coin_pct` per
coin and not applied to USDC; h = 0.02). No section of this plan changes.

**Known weaknesses.**
- Scouting on the reference engine, not Nautilus. Exchange candles are a proxy for Base prices. Kraken is quoted in
  USD and Binance in USDT, while Base trades against USDC.
- USDC is priced at 1 with no yield and no depeg. USDC briefly lost its peg in March 2023, inside validate.
- Decisions and breach checks happen only at 00:00 UTC closes; the book can sit outside the limits until the next
  open. The check phase depends on where a run starts (phase sensitivity is reported).
- The engine shares a fill's cost pro rata; a live account pays each leg's fee out of its own swap. The headroom
  covers the difference at fills; it is not modelled.
- The cost model holds pessimistic placeholders. Slippage grows with the compounding book. Every run restarts at
  USD 10,000 (B3 and B4 at S's book).
- **B4 is reset to target for free at each block start**, so E2 tests one-year horizons only. In the failure mode
  this study names (trends), a multi-year static mix would capture more of the trend than B4 does, which favours S.
  B4-span shows the multi-year comparison as a description.
- The stitched out-of-sample curve never pays to move from one fold's targets to the next, and the initial buy falls
  in the warmup. The unpaid turnover is reported.
- 4 out-of-sample years are few. TESTING.md section 4: even a strong true edge often fails DSR ≥ 0.95 at this length.
- The coin share is weakly identified (section 5). Prior looks make G1 weak evidence (section 2), and G3 is weak
  evidence of a rebalancing edge (section 9). The stitched S mixes per-fold configurations, so its drawdown is not
  the drawdown of anything that could ship; θ_final's in-sample risk numbers are reported for that.

## 15. Looks at the data

The dip-timing study's known looks come first (from research/dip-timing/PLAN.md section 9 and RESULTS.md "Looks at
the data"); they were not looks at this strategy, but they touched the same bars.

| # | Date | By | What was looked at |
|---|---|---|---|
| D0 | 2026-11-20 | `quant-researcher` (dip study) | Validate dip-trigger counts per coin for 9 (X, N) cells; the counting script read validate closes. Counts only |
| D0a | 2026-11-20 | `data-engineer` | Positioning data quality (funding, open interest, 5-minute futures klines for timestamp matching) over its whole stored span, validate days included. No strategy returns |
| D0b-D0e | 2026-11-20 | `ml-researcher` (dip study) | Train only: event counts, a pre-flight, the dip study's train run (V01-V40, with buy-and-hold and 50/50 every 30 days on train), a hand check of 5 events |
| D1 | 2026-11-20 03:28:34 UTC | `ml-researcher` (dip study) | The dip study's single validate look: Kraken BTC and ETH bars and positioning to 2024-07-01 00:00 UTC; V01-V16, nulls, random entry, buy-and-hold and 50/50 every 30 days |
| D1a | 2026-11-20, after D1 | `backtest-auditor`, `ml-researcher` | Re-reads of D1's stored outputs only |
| P1 | 2026-11-20 | `quant-researcher` | Read the dip study's RESULTS.md: train and validate numbers for the two mixes, the daily mean returns, the random-entry percentiles and the T1 results quoted in section 2. **0 looks at this rule; 1 prior look at 2 neighbouring mixes** (in the strict count) |
| P2 | 2026-11-20 | `data-engineer` | [DATA.md](DATA.md): coverage counts and close dates for this study (train and validate, daily and hourly, Kraken and Binance), from the panel's index and alignment record only. No prices |
| P3 | 2026-11-20 | `data-engineer`; read by `quant-researcher` | Data quality reports: the largest single-bar moves and wicks per series over the whole catalog, including some dates in the test window. Single bars, no strategy, nothing used here |
| P4 | 2026-11-20 | `quant-researcher` | Fold boundaries (section 7) computed with `walk_forward` on a date grid rebuilt from DATA.md's counts. No catalog read, no prices |
| P5 | 2026-11-20 | review round: `backtest-auditor`, `risk-officer`, the code builders, `quant-researcher` | The auditor read 2 metadata fields of `data/catalog/SNAPSHOT.json` (`snapshot_id`, `bars_content_sha256`) and rebuilt the date grid from DATA.md's counts. Everything else (harness checks, corner order counts, rebooked fills, throughput, the 36 combinations) ran on **synthetic** panels or hand-built paths. `config/risk_levels.yaml` was read for the limits (not market data). No catalog bar was read |
| 1 | reserved | | The single validate look (section 11), after the freeze, only if E1-E5 hold |

## 16. Review log

Reviews of the first draft, 2026-11-20: `backtest-auditor` (7 blocking items, 13 suggestions) and `risk-officer`
(4 blocking items and suggestions, two of them confirmations: the runner does what section 4 says, and the 2x runs
reuse the 1x parameters and isolate cost). **The risk-officer's review as relayed to this revision was cut off after its
suggestion list reached "Disclosures"; anything after that point was not available and is not addressed here.**

**Blocking items.**

| # | From | Item | Resolution |
|---|---|---|---|
| A-1 | auditor | The deep profile failed (`test_flat_rate_cost_is_turnover_times_rate`, a subnormal weight), so no number could count | Triaged as a test bug (the auditor's triage, confirmed and fixed by the runner's owner): TESTING.md bug #37 (an absolute floor `np.finfo(float).tiny` next to the unchanged relative tolerances, with the written reason rule 2 requires; three `@example`s, the audit's case among them; the input range is unchanged). Rerun by `quant-researcher` on HEAD `04eb81f` plus the uncommitted part-1 files: full tier with coverage `uv run pytest -q -p no:cacheprovider -n 2 --ignore=tests/test_dashboard.py --cov=lab --cov-branch` 1516 passed in 75.86 s, 100.00% branch coverage of `lab/` (3821 statements, 1138 branches, 0 missed); deep profile `HYPOTHESIS_PROFILE=deep uv run pytest -q -p no:cacheprovider -n 2 -m "not slow" --ignore=tests/test_dashboard.py` 1504 passed in 313.23 s; ruff `uv run ruff check` all checks passed. Stop rule 1 requires the same on the commit the run uses |
| A-2 | auditor | G6's budget was read at the freeze, after train results, so it could be fitted to pass G6; units unpinned | Read by `run_train.py` before any real bar, recorded in context and `summary.json`; anything but a finite number in (0, 100] is MISSING = FAIL for the whole study; `gates(rep, budget_drawdown=pct/100)` (section 9) |
| A-3 | auditor | Nothing stopped PLAN.md, code or configs changing between the train results and the freeze | Hashes recorded in `summary.json` at train start; `freeze.py` and `run_validate.py` refuse on any difference (stop rule 10), with one narrow exception for the risk-officer's budget (see R-3) |
| A-4 | auditor | A crashed `run_validate.py` could look twice | `validate/STARTED` written before any validate bar is loaded; refuse if it or `look.json` exists; a crashed look counts (section 11, stop rule 9) |
| A-5 | auditor | Amendment reruns contradicted the plan's own rules and could not be counted | Stop rule 7: up to 2 amendment runs after run 0, `--amendment k` with its refusals, one `out_dir`, names `..._a<k>_wfNN` / `..._a<k>_final` (the run tag precedes the fold tag because `walk_forward_optimize` appends `_wfNN` to the name it is given, and `lab/search` is not forked), every study of every run in DSR and PBO, the superseded verdict reported, bugs found by reading results count toward the limit, plus a regression test that fails on the old code |
| A-6 | auditor | Validate slices in Kraken row numbers were applied to Binance, where `iloc` silently picks other dates | Every harness slice by close time with `.loc`; assert the Binance slice index equals Kraken's before running, else stop (sections 3, 8, 11) |
| A-7 | auditor | B4 was called "never rebalanced" but is reset for free each block, which favours S in the named failure mode | B4 restated; E2 restated as a claim about horizons up to about one year, in the verdict wording too; E3 notes B4 at 2x ≡ B4 at 1x; known weakness added; B4-span added as a description (sections 1, 8, 10, 14) |
| R-1 | risk-officer | Steady limits typed in the adapter, not read from `risk_levels.yaml` | `portfolio.risk_limits("steady")` (TESTING.md bug #41) feeds the adapter; values and SHA-256 recorded; `run_train.py` refuses if the box breaks the limits as read (`check_box`); tests in section 14 |
| R-2 | risk-officer | Targets could sit exactly on the limits; G5 clipped to the same edge | A2: h = 0.02 via `rebalance(headroom=...)` (bug #42); box s 0.20-0.77; G5 clips to the feasible set with headroom; corner tests (0.77, 0.75), (0.77, 0.25), (0.20, 0.25) |
| R-3 | risk-officer | Budget read after train results; no rule for proposing a budget | As A-2, plus the "Drawdown budget" paragraph (section 9). The risk-officer asked that a later file change be logged as a deviation without rescoring G6; the auditor asked that any hash change block the freeze. Reconciled in stop rule 10: only a `risk_levels.yaml` change that leaves the Steady coins and limits as read may pass, G6 is never rescored |
| R-4 | risk-officer | The only drawdown described a stitched mix of per-fold configurations and skipped 2017-2018 | Section 10 "risk description": per-fold drawdowns, θ_final IN-SAMPLE over all of train, overshoot statistics, and the sentence about S's Monte Carlo p5 |

**Code changes and their plan consequences.** `make_panel` needs `snapshot_id` (section 7 fixed). `risk_limits` and
`check_targets` exist (sections 4, 5, 9). `rebalance` takes `headroom`; accepted targets run bit for bit as
without it (A2). All-cash targets give an empty `trade_returns` (bug #34); the box keeps s ≥ 0.20 and G5's lowest s
step is 0.16, so it is not reached. The tolerance fixes #35-#38 change no engine number.

**Suggestions.**

| From | Suggestion | Taken? |
|---|---|---|
| auditor | `make_panel(..., snapshot_id="synthetic")` | Yes (section 7) |
| auditor | Time a 200-trial study; record seconds per trial in A1 | Yes (section 7, A1) |
| auditor | θ_final(B)'s validate numbers descriptive only; pin the cost multiplier in the look | Yes (section 11) |
| auditor | Start B3/B4 from S's book at close test[0] − 1 | Yes (section 8) |
| auditor | Count P1 as a look at 2 neighbouring mixes (19 → 21); disclose the strategy-level selection | Yes (sections 2, 12, 15) |
| auditor | Trade shuffle and degraded execution as descriptions | Yes (section 10) |
| auditor | PBO logit distribution as the CPCV-style description | Yes (section 10) |
| auditor | Trades per parameter, flagged below 30 | Yes (section 10) |
| auditor | G5 "PASS (weak)" when 3+ steps are clipped or at the limit | Yes (section 9) |
| auditor | `run_validate.py` checks the first 2190 rows and θ_final's train reproduction | Yes (section 11) |
| auditor | Tracked `RUNLOG.jsonl` | Yes (section 12) |
| auditor | DSR interpretation note; placeholder-cost flag on every number | Yes (sections 9, 10) |
| risk-officer | Defaults for owner questions 1 and 2; USDC not capped | Yes (sections 4, 14) |
| risk-officer | Limits held at closes only; production caps as post-trade checks; alert after one day | Yes (sections 4, 14) |
| risk-officer | Sells before buys in production | Yes, as a production note; the engine is unchanged (section 4) |
| risk-officer | s-profile of drawdown and Monte Carlo p5 | Yes, for the final studies (section 10) |
| risk-officer | B5, a Steady-compliant limit-only null | Yes, as a description (section 8) |
| risk-officer | Calendar-anchored checks or a phase-sensitivity description | Phase sensitivity only: calendar anchoring would change the rule in `rebalance`, which part 1 froze; the phase range is reported (section 10) |
| risk-officer | Gas booking on the paper account; legs per year and leg USD sizes for θ_final | Yes (sections 4, 10) |
