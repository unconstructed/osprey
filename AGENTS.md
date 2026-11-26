# AGENTS.md — Strategy Lab

Instructions for the coding agent team that builds and tests our trading strategies.

This repo is where strategies are **built, simulated at scale, validated and approved**. It feeds the app described in the [app docs](docs/app/README.md): approved strategies are exported as pinned configs (each setting's default and approved range; see "Ready for production") and run in production as NautilusTrader strategy nodes on paper "model accounts". User trades never happen here.

**Read first:** [research-methods.md](research-methods.md) explains *why* the pipeline below looks the way it does. [TESTING.md](TESTING.md) is the testing standard and the **first work order**: finish its open items before building anything new.

## What this repo does and doesn't do

| Does | Never does |
|---|---|
| Download and clean historical data into a Nautilus data catalog | Place, modify or cancel a real order anywhere |
| Build strategies as NautilusTrader strategies | Touch user wallets, the app backend or production infrastructure |
| Run thousands of backtests and parameter searches | Put an LLM in any strategy logic or trade path |
| Validate results against overfitting and luck | Use leverage, short selling, market making or arbitrage |
| Train and evaluate prediction models offline | Send network traffic anywhere except the data sources listed in `lab/data/` (the `director` may also read public web pages for research) |
| Export approved strategy configs for production | Approve its own work for production (the owner does that) |

## Setup

### 0. Prerequisites
- macOS or Linux, git, ~50 GB free disk for data and results
- [uv](https://docs.astral.sh/uv/) for Python and environments
- Python **3.13** (NautilusTrader v2 requires 3.13 or 3.14)

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv python install 3.13
```

### 1. Clone NautilusTrader as a read-only reference

The published tutorials still use the old v1 API. The current v2 API is shown by the repo's `python/examples/` and generated type stubs, so the agents need a local copy to read. **Don't build or install from this clone**; its `pyproject.toml` pins dependency dates for Nautilus's own development and is not our environment.

```bash
mkdir -p ~/code && cd ~/code
git clone https://github.com/nautechsystems/nautilus_trader.git
cd nautilus_trader
git fetch --tags
git tag -l 'v2.0.0*'            # pick the tag that matches our pinned version
git checkout v2.0.0rc9          # must match the version pinned in strategy-lab
```

Where to look in the clone:
- `python/examples/`: runnable v2 examples (backtests, strategies, data loading)
- `docs/`: concepts (backtesting, data catalog, fee and fill models)
- `RELEASES.md`: breaking changes between versions; read before every upgrade

### 2. Get the repo and build the environment

The repo is private on GitHub: `unconstructed/osprey`. The same agents, docs, code and tests come down on every machine.

```bash
cd ~/code
git clone https://github.com/unconstructed/osprey.git
cd osprey

# Installs everything in pyproject.toml, dev tools included. The engine is pinned to an
# exact v2 version (nautilus_trader==2.0.0rc9); a plain install would resolve to old 1.x.
uv sync

# Confirm the engine version starts with "2."
uv run python -c "import nautilus_trader as nt; print(nt.__version__)"
```

Commit `uv.lock` after the first `uv sync` so every machine gets identical package versions.

Optional, added only when needed (ask the owner first):
- `ray[tune]`: multi-machine sweeps (see [research-methods.md: Compute plan](research-methods.md#compute-plan))
- `vectorbt`: fast idea scouting in `research/` only (see [research-methods.md: Tools](research-methods.md#tools))
- A validation-statistics library (`ml4t-diagnostic` or `purgedcv`) to cross-check our own DSR/PBO/CPCV code
- Forecasting baselines (`statsforecast`) and pretrained time-series models (Chronos-2, TimesFM) for the prediction track

### 3. `.gitignore`

```
.env
.env.*
.venv/
__pycache__/
.ipynb_checkpoints/
.pytest_cache/
.ruff_cache/
/data/          # leading slash: ignore only the top-level folder, not lab/data/
/results/
/mlruns/
/mlflow.db      # the empty store a plain `mlflow ui` creates; ours is mlruns/mlflow.db
*.parquet
.hypothesis/
mutants/
.coverage
htmlcov/
```

## Repo layout

```
osprey/
├── CLAUDE.md                    # tells Claude Code to read AGENTS.md and TESTING.md first
├── docs/app/                    # the Osprey app plan: features, product, technical, business
├── AGENTS.md
├── TESTING.md                   # testing standard, bug log, open test work
├── .claude/agents/              # role files (see Desk roles)
├── config/
│   ├── splits.yaml              # global train / validate / test date ranges
│   ├── costs.yaml               # DEX cost model assumptions
│   └── risk_levels.yaml         # drawdown budgets and coin lists per risk level
├── lab/
│   ├── data/                    # loaders, downloaders, quality checks, catalog writer, panels, synthetic test data (built)
│   ├── costs/                   # Nautilus fee model for Base DEX trading (built, milestone 2)
│   ├── runner/                  # BacktestFn interface, reference engines, single-asset Nautilus runner (built)
│   ├── tracking/                # MLflow logging of search trials (built, milestone 2)
│   ├── search/                  # Optuna studies, walk-forward optimization, stable regions, reports (built)
│   ├── validation/              # purged splits, CPCV, DSR, PBO, Monte Carlo (built)
│   ├── models/                  # features, labels, baselines, training, artifacts, live parity (built)
│   └── reports/                 # audit reports and tearsheets
├── scripts/                     # demo.py (end-to-end demo on synthetic data); Nautilus throughput and real-data parity checks
├── strategies/<name>/           # strategy.py, params.yaml, README.md
├── research/                    # notebooks and scratch; never imported by lab/ or strategies/
├── exports/<name>/              # approved, pinned configs for production
├── reports/<name>/<date>.md     # audit reports (committed); director reviews in reports/director/
├── data/                        # git-ignored: raw downloads and the Nautilus catalog
├── results/                     # git-ignored: trial results (Parquet), Optuna journals
├── mlruns/                      # git-ignored: the MLflow store, mlruns/mlflow.db (SQLite)
└── tests/                       # property, leakage, known-answer, calibration and contract tests
```

## Data

| Source | What | Cost | Use |
|---|---|---|---|
| Kraken downloadable OHLCVT | Full candle history for every pair, plus quarterly updates | Free | Primary daily and hourly bars for BTC and ETH |
| Binance public data (data.binance.vision) | Zipped candle and trade files; BTC/USDT daily from August 2017 | Free | Second source; wider token coverage for the Bold list |
| Coinbase public REST candles | Recent candles | Free | Cross-check, and the closest match to Base prices |
| 0x Swap API price quotes (`api.0x.org`; approved, owner, 2026-11-25) | Indicative prices for swaps on Base at several trade sizes; read only, no order is ever sent | Free API key, in `.env` or the environment's secure store, never in code, chat or logs | Measuring the pool fee, aggregator fee and slippage for `config/costs.yaml` |
| A public Base RPC (read only; approved, owner, 2026-11-25) | Gas prices and cbBTC/USDC pool prices on Base | Free | Measuring gas and the gap between cbBTC on Base and BTC on Coinbase |
| Tardis (Nautilus integration) | Tick and order book data | Paid | Later, only if a strategy needs intraday detail |
| CoinAPI (Nautilus adapter, flat files) | Normalized multi-exchange data | Paid | Later, same |

Pipeline (owned by `data-engineer`):
1. Download raw files into `data/raw/<source>/` and record a SHA-256 of each file.
2. Normalize to one schema (UTC timestamps, bar close time, OHLCV), de-duplicate, check for gaps and bad ticks.
3. Write instruments and bars to the Nautilus `ParquetDataCatalog` in `data/catalog/`.
4. Write `data/catalog/SNAPSHOT.json`: sources, file hashes, date ranges, row counts. Every backtest records this snapshot ID.
5. Cross-check sources: the same day's BTC close from Kraken, Binance and Coinbase must agree within a small tolerance; log outliers.

Production trades happen on Base (cbBTC, ETH, USDC). Exchange candles are a proxy for Base prices; `data-engineer` measures the gap between cbBTC/USDC on Base and BTC/USD on Coinbase and reports it.

## Costs

Every backtest runs with the cost model on. A zero-cost backtest is not a result.

Production trades are swaps on Base through the 0x aggregator. Costs per trade = pool fee + aggregator fee (if any) + slippage (grows with trade size) + gas (we sponsor it, so it's our cost). Implement these as Nautilus v2 fee and fill model subclasses in `lab/costs/`.

Measured values (owner-approved 2026-11-25; [reports/costs/2026-11-25.md](reports/costs/2026-11-25.md), one evening of read-only 0x quotes on Base). Re-measure before launch; the routing (0x, direct pools, or 0x without the bad "LunarBase" source) is still open, and the report gives the costs for each:

```yaml
# config/costs.yaml — MEASURED 2026-11-25. 90th percentiles, rounded up.
venue: base_via_0x
pool_fee_bps: 0            # inside 0x's price; counted in slippage_bps
aggregator_fee_bps: 15     # 0x volume fee, measured on every sample
slippage_bps:              # by trade size in USD
  "100": 30
  "1000": 54
  "10000": 26
  "50000": 5
gas_usd_per_trade: 0.15    # sponsored by us; worst measured $0.12, plus margin
stress_multiplier: 2.0     # every finalist is re-run with all costs doubled
```

## Splits

```yaml
# config/splits.yaml — fixed. Changing it requires owner approval.
train:    { start: 2017-01-01, end: 2022-12-31 }   # includes the 2018 and 2022 crashes
validate: { start: 2023-01-01, end: 2024-06-30 }
test:     { start: 2024-07-01, end: latest }       # final holdout: run ONCE per strategy, at sign-off
```

Walk-forward and cross-validation happen inside train + validate. The test window is opened once per strategy, by `backtest-auditor`, after everything else passes. Once used, it's burned for that strategy.

## Risk levels

The owner set **five levels** on 2026-11-25, from least to most risk: Cash-first, Steady, Balanced, Bold and Explorer (working names; [docs/app/features.md](docs/app/features.md), "Strategies by risk level"). The file below still holds three. Cash-first and Explorer, with the owner's answers so far (Cash-first at about 8% crypto; interim budgets of 25% and 90%; a stop-loss required at Explorer only), are drafted in [reports/risk-officer/2026-11-25-new-risk-levels.md](reports/risk-officer/2026-11-25-new-risk-levels.md). `risk-officer` writes them into the file, with the test updates that proposal lists, once the TESTING.md 5.4 work is finished. The lab's code reads levels only from the file, so no study can use the new levels before then.

```yaml
# config/risk_levels.yaml — owned by risk-officer. Steady's budget is set (owner-approved); the others are TBD.
steady:
  coins: [BTC, ETH, USDC]
  min_cash_pct: 20
  max_coin_pct: 60
  max_drawdown_budget_pct: 35   # owner-approved 2026-11-21 (Monte Carlo 95th-percentile max drawdown)
  hold_mix_max_rebalances_per_30d: 2   # owner-approved 2026-11-22: the hold-this-mix tool only, not our strategies
balanced:
  coins: [BTC, ETH, USDC]        # plus vetted large tokens on Base, once listed
  stop_loss_required: true
  max_drawdown_budget_pct: TBD
bold:
  coins: []                      # vetted list of the most liquid tokens on Base
  max_drawdown_budget_pct: TBD
```

## Strategies to build first

| Strategy | Risk level | Idea | Free parameters (keep ≤ 4) |
|---|---|---|---|
| `rebalance-steady` | Steady | Hold BTC, ETH and USDC at target weights; rebalance when drift exceeds a band | Target weights, drift band, check frequency |
| `dip-buy-balanced` | Balanced | Buy BTC or ETH after a drop of X% over N days, capped per period; stop-loss | Drop %, lookback, cap, stop % |
| `momentum-bold` | Bold | Each week, hold the top K tokens by trailing return from the vetted list; rest in USDC | Lookback, K, rebalance day, cash filter |

Benchmarks every strategy must be compared against: buy-and-hold BTC, a 50/50 BTC/USDC monthly rebalance, and random-entry strategies with the same number of trades.

Cash-first and Explorer have no launch strategy yet. Like Bold, Explorer needs an engine that holds tokens other than BTC and ETH: `lab/runner/portfolio.py` and `risk_limits` accept BTC, ETH and USDC only.

## Starter code (already built and tested)

The smart search, validation statistics and prediction pipeline came as tested starter code (159 tests) and were merged with this repo on 2026-11-19 ([TESTING.md](TESTING.md) section 4a). Build on them; don't rewrite them. The current test count, coverage and bug log are in TESTING.md sections 3 and 4. **Start with [TESTING.md](TESTING.md) section 5**, then run `uv run pytest -n auto` and `uv run python scripts/demo.py`.

| Module | What it does |
|---|---|
| `lab/runner/interface.py` | **The contract.** `backtest_fn(params, bars) -> DataFrame` on exactly `bars.index`, with columns `ret` (net per-bar return after all costs; `ret[0] = 0`), `position`, `turnover` and `cost`, plus `attrs["trade_returns"]` and `attrs["n_trades"]`. A decision at the close of bar t fills at the open of bar t+1 ([TESTING.md 4a.5](TESTING.md#4a5-the-backtest-contract)). `validate_bars` and `validate_result` check both sides |
| `lab/runner/reference.py` | Small pure-Python dip-buy, buy-and-hold, constant-mix, random-entry and scheduled-target backtests with a `Costs` model (reads `config/costs.yaml`). Fills at the next open; positions are held as coin units between trades (weights drift); only trading bars pay costs. **Tests, demos and scouting only**; never in reports |
| `lab/search/space.py` | Parameter specs (`Param`) shared by Optuna and the stable-region finder |
| `lab/search/objective.py` | Score = mean annualized Sharpe across time blocks minus 0.5 × their spread, after costs; too few trades scores −10 |
| `lab/search/study.py` | Optuna TPE studies in parallel processes on a journal file; logs every trial's params, metrics and full return series to `results/<study>/` |
| `lab/search/stability.py` | Chooses parameters with the best *neighbourhood* score, not the single best trial |
| `lab/search/walkforward.py` | Search on each fold's past, trade the next unseen block, stitch the out-of-sample curve; reports walk-forward efficiency |
| `lab/search/report.py` | Deflated Sharpe (raw and effective trial counts), PBO per fold, Monte Carlo drawdowns, default gates |
| `lab/validation/splits.py` | Walk-forward and CPCV splitters with purge and embargo; CPCV path assembly |
| `lab/validation/stats.py` | Sharpe, PSR, expected max Sharpe, effective trials (entropy effective rank), DSR, PBO (CSCV) |
| `lab/validation/montecarlo.py` | Max drawdown, trade shuffle and bootstrap, stationary block bootstrap, degraded execution |
| `lab/models/features.py` | 15 point-in-time features (returns, volatilities, windowed EWMA volatility, range volatility, moving-average distance, drawdown, efficiency ratio, volume z-score) plus cross-sectional rank features |
| `lab/models/labels.py` | Forward volatility, forward regime (trend vs. sideways), forward return, cross-sectional forward rank |
| `lab/models/baselines.py` | Naive, long-run and EWMA volatility; regime persistence; momentum rank |
| `lab/models/train.py` | LightGBM (small, heavily regularized); CPCV evaluation against baselines on identical test rows; `walk_forward_predict` for production-style out-of-sample forecasts |
| `lab/models/artifact.py` | Saves model + metadata (features, horizon, train window, data snapshot, SHA-256); refuses to load a tampered file |
| `lab/models/online.py` | `FeatureBuffer` (live features identical to backtest features, tested) and `ModelPredictor` for use inside a Nautilus strategy |
| `lab/data/loaders.py` | Kraken OHLCVT and Binance kline CSV loaders (verify against real files) |
| `lab/data/synthetic.py` | Regime-switching, volatility-clustering synthetic bars for tests and demos only |

**What the demo taught us (synthetic data).** Rerun on 2026-11-19 after the backtester fixes and the starter merge (fills at the next open, costs from `config/costs.yaml`): [reports/demo/2026-11-19.md](reports/demo/2026-11-19.md).
- **Anchor volatility models to EWMA.** The model predicts a correction on top of an EWMA forecast, with a log-normal bias fix. A from-scratch model lost to EWMA. The saved model is now the anchored one that was validated (TESTING.md bug #17).
- **Regularize hard.** Small trees, large minimum leaf size, strong L2. The default settings in `make_model` reflect this.
- **Horizon matters.** The model beat EWMA in 80% of CPCV splits at 20 days and in 60% at 5 days (QLIKE 0.320 vs. 0.383 at 20 days; 0.523 vs. 0.519 at 5 days, a tie). Use the horizon that wins.
- **Sizing by forecast volatility did not help in the rerun.** The older demo showed the worst drawdown falling from about 69% to 19%. After the fixes, the vol-targeted dip buy did worse than the plain one: out-of-sample Sharpe -0.15 vs. 0.32 and max drawdown -53.1% vs. -33.5%. Both failed every gate, and both trailed buy-and-hold (Sharpe 0.83) and the 50/50 monthly rebalance (0.84). Treat model sizing as unproven until real data says otherwise.
- **The luck control works.** Shuffled data with no pattern still produced an in-sample Sharpe of 1.30; out of sample it was -0.75, with DSR 0.00 and PBO 0.70, so the checks rejected it.
- **Parallel searches aren't bit-reproducible.** Every trial is logged, and re-running logged parameters is exact. Run important searches twice with different seeds; a large difference flags a fragile strategy.

### Built since the starter code

| Module | What it does |
|---|---|
| `lab/runner/nautilus.py` | `BacktestFn` on NautilusTrader v2 (milestone 2): one `BacktestEngine` per run, disposed after use. A Nautilus strategy calls the reference rule's own decision function, so both runners decide with one piece of code; Nautilus holds the balances and books every fill and fee. Equal to the reference to `TOL` = 1e-9 (contract suite and parity test). **Single asset only.** `wrap(rule)` gives a picklable `BacktestFn` for parallel searches |
| `lab/costs/fees.py` | `DexFeeModel`: `config/costs.yaml` as a Nautilus fee model (pool + aggregator + size-based slippage + gas). Slippage is charged as a fee at the quoted price, so no fill model is needed |
| `lab/tracking/mlflow_log.py` | Copies a finished Optuna study into MLflow (SQLite store `mlruns/mlflow.db`): one parent run per study, one run per finished trial. The journal and Parquet files stay the record that DSR and PBO read |
| `lab/runner/portfolio.py` | Multi-asset reference engine (BTC, ETH and USDC cash), same costs and execution model; `risk_limits` reads `config/risk_levels.yaml`. **Scouting only: it has no Nautilus counterpart yet** |
| `lab/runner/steady.py`, `holdmix.py`, `trend.py` | The rebalance-steady, hold-mix-cap and trend-steady studies' harnesses on `portfolio.py` (scouting only) |
| `lab/data/` (`build.py`, `sources.py`, `catalog.py`, `quality.py`, `report.py`, `panel.py`, `futures.py`, `external.py`) | Milestone 1: downloads from the allow-listed sources, quality checks, the Nautilus catalog and `SNAPSHOT.json`, the data reports, the BTC + ETH panel, and Binance futures positioning data stored point in time |
| `lab/models/dips.py` | The dip-timing study's events, features, labels and event-level validation |

### What's left to build

1. **Done (milestone 2): `lab/runner/nautilus.py`.** It implements `BacktestFn` on a NautilusTrader v2 `BacktestEngine`, one engine per run, disposed after use; the caller passes the bars (from the catalog through `lab.data.catalog.load_bars`). It passes the backtest contract suite ([TESTING.md 5.6](TESTING.md#56-turn-the-backtester-tests-into-a-contract-every-runner-must-pass)) and the parity test, and agrees with the reference on Kraken BTC train bars ([reports/milestone2/2026-11-25.md](reports/milestone2/2026-11-25.md)). This item first named a `BacktestNode`, which builds the same engine from a run config and reads the catalog itself. The results are the same, and the owner kept `BacktestEngine` (owner, 2026-11-25).
2. **Done (milestone 2): `lab/costs/fees.py`**, the fee model above.
3. **Done (milestone 1): `lab/data/build.py`** and the rest of `lab/data/`.
4. **MLflow logging:** search trials done (milestone 2); model versions still to build (no milestone names them).
5. **A multi-asset Nautilus runner** (milestone 3). The launch strategies hold BTC, ETH and USDC, or K tokens, so it needs one instrument per coin. It passes the guarantees `tests/test_portfolio.py` pins for `portfolio.py` (no look-ahead, accounting against an independent book, costs), a parity test against `portfolio.py`, and a real-data parity check ("Milestones", closing a milestone).
6. **Strategies** in `strategies/`. Under the owner's option B (2026-11-25; [docs/app/technical.md](docs/app/technical.md), "Strategy settings"), each strategy's decision logic is written once, as a plain-Python decision function with no Nautilus import. A thin Nautilus strategy calls it (as `lab/runner/nautilus.py` calls the reference rules' decisions), the app's per-customer check runs the same function, and a decision-parity test pins the two together. Model-using strategies keep a `FeatureBuffer` and a `ModelPredictor`:

```python
# inside the Nautilus strategy that calls the decision function (v2 API: check python/examples/ in the reference clone)
def on_start(self):
    self.features = FeatureBuffer()
    self.vol_model = ModelPredictor("models/vol_20d")

def on_bar(self, bar):
    self.features.update(bar.ts_event, bar.open, bar.high, bar.low, bar.close, bar.volume)
    feats = self.features.latest()
    if feats is None:
        return  # still warming up
    # Forecasts are per bar (TESTING.md 4a.3) and vol_target is annual: annualise first
    # (bars_per_year = 365 for daily bars, 8760 for hourly bars).
    forecast_vol = self.vol_model.predict(feats) * math.sqrt(self.bars_per_year)
    size = min(self.max_weight, self.vol_target / forecast_vol)
    ...  # the decision function, then orders through Nautilus
```

## Running many simulations

Full method in [research-methods.md](research-methods.md). Implementation rules:

1. **One run = one engine.** `lab/runner/nautilus.py` builds one NautilusTrader v2 `BacktestEngine` per run and disposes of it after use, behind the `BacktestFn` interface, so the existing search and validation code runs unchanged. (A `BacktestNode` builds the same engine from one run config and reads the catalog itself; the results are the same, and the owner kept the engine, owner, 2026-11-25.)
2. **Parallel by process.** A worker pool runs many `run_one` calls at once, one per CPU core. Each trial is independent, so runs can be killed and resumed.
3. **Search smart, not exhaustive.** Optuna studies (TPE sampler) in `lab/search/`. Local runs use Optuna's journal file storage; multi-machine runs use a Postgres storage. The objective is a **walk-forward out-of-sample** score after costs, never in-sample return.
4. **Log every trial.** `lab.search.study` writes each trial's row and return series to the study's folder under `results/`, and `lab.tracking.mlflow_log` copies each finished study into MLflow, one run per trial: strategy, params, window, data snapshot ID, git commit, seed, all metrics, and failures. Pass the strategy, snapshot ID and git commit to `run_study` as `context`; MLflow tags anything missing `unrecorded`, and such a trial does not meet hard rule 7. The total trial count per strategy feeds the Deflated Sharpe Ratio.
5. **Measure throughput first.** Before any big sweep, time a single full-history backtest and report trials per hour per core. Size sweeps from that number. Measured for the single-asset Nautilus runner on 2026-11-25 (`scripts/nautilus_throughput.py`): about 60,000 daily runs (2017-2026; 12,000 with a fill on every bar) and 6,000-8,000 hourly runs (six train years) per hour per core, 10-25x slower than the reference engine.
6. **A result and its luck controls run on one engine.** S (the walk-forward result) and every control it is judged against that re-runs a backtest (random entries, shifted or placebo schedules, plateau steps, grid steps, doubled costs) run on NautilusTrader (hard rule 3). The reference engines are for scouting. Counted controls run on NautilusTrader only; a reference engine may not stand in for one, even with a parity test (owner, 2026-11-25). Bootstraps that only resample S's own returns are not re-runs and are unaffected.

## Validation gates

A strategy is **ready for paper** (production model account) when `backtest-auditor` reports PASS on all of these, on the walk-forward result as today **and at the default and at every combination of the allowed values** of the settings a user can change in the app (see "Settings ranges" below). Thresholds are defaults the owner can change:

| Gate | Default |
|---|---|
| Walk-forward out-of-sample Sharpe, after costs | ≥ 1.0 |
| Same, with costs doubled | > 0.5 |
| Deflated Sharpe Ratio (counting every trial) | ≥ 0.95 |
| Probability of Backtest Overfitting | ≤ 0.25 |
| Parameter plateau: every parameter ±20% | Keeps ≥ 70% of the Sharpe |
| Monte Carlo 95th-percentile max drawdown | Within the risk level's budget |
| Beats benchmarks | Better risk-adjusted return than buy-and-hold BTC and 50/50 rebalance over the walk-forward |
| Regimes | No single regime (bull, bear, sideways) produces most of the profit |
| Final test window, run once | Sharpe within a reasonable distance of walk-forward; no new failure modes |

**Settings ranges.** Users can change a strategy's settings in the app, so approval covers every combination a user can pick, not one tuned point.
- `risk-officer` sets each setting's allowed values inside the risk level's limits, in the study's pre-registration, before any result. The level's drawdown budget must be owner-approved before then. The pre-registration lists every earlier look at the same data that could inform the range (a study's prior looks, as in its plan). The app offers those values only.
- The allowed range lies inside the search box. Where the box reaches further, the walk-forward choice and θ_final can use values a user cannot pick, and the default can sit some way from θ_final. The walk-forward choice still has to pass every gate, and the grid covers what users can pick.
- A grid step is one full combination (one value for every setting a user can change). The grid is every combination of the per-setting values, and every gate below covers each combination (the table says how). Each setting's values include both ends of its range. The default takes, for each setting, the value nearest θ_final's (θ_final is the final search's stable-region pick, `lab/search/stability.py`). A setting users cannot change keeps θ_final's value.
- The thresholds above are unchanged. Where each gate is measured:

| Gate | Measured at |
|---|---|
| Walk-forward out-of-sample Sharpe, and the same with costs doubled | The walk-forward choice, as today, **and** every grid step held fixed over the same out-of-sample span |
| Deflated Sharpe Ratio; Probability of Backtest Overfitting | As today. Every grid run is logged and added to the total trial count (AGENTS.md "Running many simulations", rule 4), as the plateau and doubled-cost runs are (rebalance-steady's strict count, RESULTS.md). The effective count for correlated trials (`backtest-auditor` item 8) still comes from the search studies' trials, and the grid runs do not enter it: they were fixed before any result, so nothing was selected from them. The trial-Sharpe variance and PBO also still come from the search's trials. So the total-count DSR can only fall, and the effective-count DSR is unchanged |
| Parameter plateau | As today (each parameter ×0.8 and ×1.2 from the walk-forward choices, against the walk-forward Sharpe S), **and** each parameter ×0.8 and ×1.2 from the default, **and** every grid step. The default's steps and the grid steps are each held fixed over the walk-forward out-of-sample span, and each must keep ≥ 70% of S's Sharpe |
| Monte Carlo 95th-percentile max drawdown | The walk-forward choice, as today, **and** every grid step: S's drawdown and the deepest grid-step drawdown are both within the risk level's budget |
| Beats benchmarks; regimes | The walk-forward choice, as today, **and** the default and every grid step |
| Final test window, run once | One run covering the default and every grid step together. The default is judged against the walk-forward Sharpe S, as today; every other grid step against its own fixed run over the walk-forward out-of-sample span. The window is then burned for the whole range |

- A failing walk-forward result fails the strategy, as today. One failing grid step fails the range. After an audit, a range may be narrowed only to meet a risk limit (the drawdown budget or the level's limits), and only by dropping whole values from a setting's riskiest end, never to drop combinations whose Sharpe failed. A setting's riskiest end is the end whose grid steps include the deepest Monte Carlo 95th-percentile max drawdown, as measured. Each narrowing is logged with the new edge's margin to the budget, the dropped combinations stay in the trial count, and the range gates run again. The range is frozen before the test window opens.
- The default is chosen by the search, so its fixed runs on the search's own data are in-sample. That includes its runs and its ±20% steps over the walk-forward out-of-sample span, when the final search used those years. Those runs add checks, not evidence. Its out-of-sample evidence stays the walk-forward choice, the validate look and the test window. The other grid steps were fixed before any result, so they were not selected.
- The grid runner and the per-combination gate table ship with the tests [TESTING.md](TESTING.md) section 7 describes (hard rule 11), including a test that recomputes every reported number from its inputs.
- Fixed settings (no setting a user can change) ship θ_final, like today's pinned config. They are gated as today on the walk-forward result, plus θ_final's own runs wherever the table names the default. A range is fixed in the pre-registration: one that fails cannot be cut down to fixed settings afterwards, because that would drop combinations whose Sharpe failed.

**Ready for production (owner decision, not an agent's):** at least 4 weeks on paper model accounts, at the default and at the riskiest combination in the allowed range (the grid step with the deepest Monte Carlo 95th-percentile max drawdown), with results within tolerance of the backtest; the owner approves the default and the range; `risk-officer` writes `exports/<name>/config.yaml` with, for every setting a user can change, its default and its allowed values (a setting users can't change has one value), plus the risk level and its limits as read, the coin list, the backtested max drawdown and Monte Carlo 95th-percentile max drawdown for every combination, the code commit, the data snapshot ID and the model version (if any).

## Prediction models

Owned by `ml-researcher`. Full approach in [research-methods.md: Prediction models](research-methods.md#prediction-models).

- Start with targets that are more predictable than price direction: volatility, regime (trend vs. sideways), and cross-sectional ranking for the Bold list.
- Features and labels are computed point-in-time; cross-validation is purged and embargoed (CPCV).
- Every model is compared against naive baselines (last value, rolling average) and judged by **strategy profit after costs in Nautilus**, not by forecast error alone.
- Models are trained offline, versioned in MLflow, and loaded read-only by a Nautilus strategy. No retraining inside a backtest window; walk-forward retraining copies the production schedule.

## Self-directed tool studies

Added by the owner, owner, 2026-11-25. Some studies are about tools customers set up themselves, not about our strategies:
"hold this mix" (`research/hold-mix-cap/`), "protect my gains" (`research/protect-gains/`), the buy-the-dip
template and the starting values of rule templates. They claim no edge and approve nothing. They pick
recommended starting values and describe what a setting did in the past (worst falls, trades a month, fees).

- **Same discipline as a strategy study:** pre-registered before any result, costs on, no look-ahead, every run
  logged, the full tier passed on the commit (hard rules 4, 6, 7, 8 and 11).
- **Train data only,** unless the plan says otherwise and `backtest-auditor` agrees before the run. A look at the
  validate or test years would spend them for any later strategy of ours on the same idea (hard rule 5).
- **No validation gates:** nothing is approved, so the gates of "Validation gates" don't apply. The decision rules are
  the plan's own, fixed before the run, and `backtest-auditor` audits that the plan was followed.
- **Numbers a customer will see** (a default, a worst fall) are rerun on NautilusTrader before the app shows them
  (hard rule 3), with measured costs once they exist.
- The owner decides what the app offers; the record goes to `docs/app/`.

## Reporting back to the owner (all agents)

Owner's instruction, 2026-11-25. Every agent and session ends a task with this report, in plain English, short
enough to read on a phone. Details stay in the files; the report links to them.

```
**Tasks run:** one line per task.
**What was done:** results, with the key numbers. Say plainly what failed or was skipped.
**Why:** one or two lines: the reason for the work, or the rule or decision it follows.
**Token cost:** tokens written and re-read from cache for this task, and the estimate given before it.
**Questions for you:** numbered, each answerable in a line; put a recommendation first. "None" if none.
**What's next:** the next one to three steps, and whether each waits on an answer above.
```

No jargon without a plain explanation, no long tables, nothing the owner has to scroll back to understand.

### Token cost: warn first (owner, 2026-11-25)

Tokens cost the owner money. Keep every task lean, and warn before spending:

1. **Estimate before you start.** Before launching an agent, a workflow, a background job or any task likely to
   write more than about 500,000 tokens or run longer than about 15 minutes, tell the owner the rough token cost (tokens
   written, and tokens re-read from cache as the context grows) and wait for an OK. The same goes for adding scope to
   a running job (more rounds, more analysis).
2. **Pick the cheapest way that does the job.** Do small things directly instead of through an agent; use a lower
   effort setting unless the work needs more; brief agents to wait with one long wait instead of frequent checks, to
   skip analysis the task does not need, and to read only the parts of files they need. Long agent runs cost most in
   re-reading their own growing context on every step.
3. **Report what it cost** in the "Token cost" line above, next to the estimate. If a task is going well past its
   estimate, stop and tell the owner before going on.

## Hard rules (all agents)

1. **No secrets in code or chat.** Keys load from env vars or a git-ignored `.env`. Never print or log a key.
2. **No trading.** Nothing in this repo sends orders or connects to wallets or the app backend.
3. **NautilusTrader for every result that counts.** Scouting tools may suggest ideas; only Nautilus results go into reports.
4. **No look-ahead.** Signals at bar *t* use data available at the close of bar *t*; fills happen no earlier than bar *t+1*.
5. **Splits are fixed.** Nobody tunes on the test window. Validate-window looks are logged in the strategy README.
6. **Costs are always on**, and finalists are re-run with costs doubled.
7. **Deterministic and traceable.** Seed all randomness; every trial records data snapshot ID, git commit and seed.
8. **Every trial is logged**, including failures and abandoned variants. Hiding trials inflates results.
9. **Spot only.** No leverage, shorting, market making or arbitrage; only coins on the risk level's list.
10. **Ask the owner before** adding a dependency, changing `config/splits.yaml`, `config/costs.yaml` or `config/risk_levels.yaml`, or running anything that will cost money (cloud machines, paid data, or a large token spend: see "Token cost: warn first").
11. **No result from failing code.** A backtest, search or audit only counts if the full test tier passed on that commit. New features, models, strategies and runners ship with the tests [TESTING.md](TESTING.md) section 7 describes, including a tamper-the-future test.

## Desk roles

| Agent | Owns | Never does |
|---|---|---|
| `data-engineer` | `lab/data/`, the catalog, data snapshots, cost measurement | Write strategy logic or change validation thresholds |
| `quant-researcher` | Strategy hypotheses, `strategies/`, search spaces | Touch `config/`, open the test window, write audit reports |
| `ml-researcher` | `lab/models/`, features, labels, model training and evaluation | Put a model in a strategy without an audit; use future data |
| `backtest-auditor` | `lab/validation/`, audit reports, the one-time test-window run | Write or tune strategy logic |
| `lab-engineer` (added, owner, 2026-11-25) | The engines: `lab/runner/` (`interface.py`, `reference.py`, `portfolio.py`, `nautilus.py`; a study's harness stays with its researcher), `lab/costs/`, `lab/tracking/`, the contract and parity tests, throughput and real-data parity checks | Write strategy decision logic; change `config/`, gates or test tolerances |
| `risk-officer` | `config/risk_levels.yaml`, drawdown budgets, each setting's allowed range (set before any result, inside the level's limits), exports | Loosen a limit or widen an approved range without the owner's written approval |
| `director` | Reviewing how the desk works; researching better methods and tools; proposing improvements to agent files and docs on a branch for the owner | Change gates, `config/` or test tolerances to make things pass; approve strategies; merge its own changes |

Handoff for any new strategy: `quant-researcher` (or `ml-researcher`) and `risk-officer` pre-register the search box and the allowed ranges → `backtest-auditor` → `risk-officer` → paper model accounts → owner → export.

The `director` reviews the desk after every milestone and after any failed audit, and proposes changes on a `director/<date>` branch. The owner merges what they agree with.

## Milestones

| # | Milestone | Done when |
|---|---|---|
| 0 | Starter code verified | [TESTING.md](TESTING.md) definition of done met: full, deep and slow tiers pass; mutation targets met; demo rerun with the report and figures updated |
| 1 | Setup and data | Environment builds; BTC and ETH daily and hourly bars from Kraken and Binance in the catalog; `SNAPSHOT.json` written; data quality report committed |
| 2 | Costs and Nautilus runner | Fee and fill models in `lab/costs/` with tests; `lab/runner/nautilus.py` implements `BacktestFn` and passes the backtest contract suite; parity test against the reference passes; trials also logged to MLflow; throughput (trials per hour per core) measured |
| 3 | Launch strategies | A multi-asset Nautilus runner with its parity test against `lab/runner/portfolio.py`; the three strategies as Nautilus strategies, backtested on the train window with costs on, plus all benchmarks |
| 4 | Search and validation on real data | The demo pipeline rerun on real data with the Nautilus runner: walk-forward studies, CPCV, DSR, PBO, Monte Carlo; first audit reports written |
| 5 | Prediction track on real data | Volatility (5- and 20-day), regime and Bold-list ranking models vs. baselines with CPCV on real data; at least one model-sized strategy variant audited |

**Closing a milestone.**
1. The full tier, and the deep tier if `lab/` changed, passed on the commit that closes it (hard rule 11). The milestone report names that commit, and the commit each of its scripts ran on.
2. A milestone that adds or changes an engine (a runner, a cost model) also runs it against the reference on real catalog bars, train window only (closes up to 2023-01-01): Kraken and Binance, BTC and ETH, daily and hourly, costs at 1x and 2x. Every case the real data finds becomes a hand-built regression test (TESTING.md rule 3).
3. README.md "Status", HOWTO.md's status lines and `dashboard/status.json` are updated in the same commit. Then the `director` reviews the desk.

## Commands

```bash
uv sync                                                    # install everything in pyproject.toml
uv run pytest -m "not slow" -n auto                        # quick tier (every change)
uv run pytest -n auto --cov --cov-branch                   # full tier with coverage (before merging)
HYPOTHESIS_PROFILE=deep uv run pytest -m "not slow" -n auto  # deep tier (changes to lab/)
uv run mutmut run                                          # mutation testing (see TESTING.md)
uv run python scripts/demo.py --trials 150 --workers 4     # end-to-end demo on synthetic data

uv run python -m lab.data.build --sources kraken,binance   # download + build catalog (milestone 1)
uv run python scripts/nautilus_throughput.py              # trials per hour per core, Nautilus and reference
uv run python scripts/nautilus_parity_real.py --interval 1h  # Nautilus vs reference on real train bars
uv run python -m lab.tracking.mlflow_log results <study>  # copy a finished study's trials into MLflow
uv run mlflow ui --backend-store-uri sqlite:///mlruns/mlflow.db  # browse them; run from the repo root

# planned, not built yet (milestones 3–4)
uv run python -m lab.runner.run_one --strategy dip-buy-balanced --window train
uv run python -m lab.search.study --strategy dip-buy-balanced --trials 2000 --workers 8
uv run python -m lab.validation.audit --strategy dip-buy-balanced
```
