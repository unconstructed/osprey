# Research Methods: Mass Simulation and Prediction Models

[← Strategy Lab](AGENTS.md) · [App docs](docs/app/README.md)

*How we run very large numbers of simulations to find strategies that hold up live, and how to use prediction models without fooling ourselves. Researched 2026-11-19.*

## The core problem: more simulations means more false winners

Run 10,000 variants and some will look brilliant by pure luck. The best backtest out of many is almost always worse in real life, because picking the top result also picks up its luck.

So mass simulation is **not** "find the highest number." It is:
1. Explore widely and cheaply
2. Find **stable regions** of parameters, not single peaks
3. Prove the winners aren't luck, with statistics that account for **how many things we tried**
4. Confirm on data the search never saw, then on live paper trading

Everything below follows from that.

## The research funnel

| Stage | What happens | Candidates (illustrative) | Data used |
|---|---|---|---|
| 0. Data | Download, clean, snapshot, cross-check sources | — | All |
| 1. Idea screen | Cheap first look at each idea with sensible default parameters | Dozens of ideas | Train |
| 2. Search | Optuna explores each surviving idea's parameter space; objective is a walk-forward out-of-sample score after costs | Thousands of trials per idea | Train + validate (walk-forward) |
| 3. Robustness battery | Parameter plateau, doubled costs, Monte Carlo, regime breakdown, benchmarks | Top 10–50 configurations | Train + validate |
| 4. Overfitting statistics | Deflated Sharpe Ratio (counting every trial), Probability of Backtest Overfitting, combinatorial purged cross-validation | Top handful | Train + validate |
| 5. Final holdout | Run **once** on the test window | 1–3 per idea | Test |
| 6. Paper model accounts | Weeks of live prices, fake money, in production | Approved strategies | Live |

With a settings range ([AGENTS.md: Validation gates](AGENTS.md#validation-gates), "Settings ranges"), stages 3 and 5 also cover every combination of settings a user can pick, on top of the counts above.

## Tools

| Job | Tool | Why | Notes |
|---|---|---|---|
| Engine for every result that counts | **NautilusTrader v2** | Same strategy code in backtest, paper and live; v2 supports custom fee and fill models in Python, which we need for Base swap costs | The lab builds one `BacktestEngine` per run (a `BacktestNode` builds the same engine from one configuration); run many in parallel processes. Measured on one core (2026-11-25): about 60,000 daily (12,000 with a fill on every bar) or 6,000-8,000 hourly full-history runs per hour, 10-25x slower than the reference engine |
| Parameter search | **Optuna** | Bayesian search (TPE) finds good regions far faster than exhaustive grids; parallel across processes and machines | Journal file storage on one machine; Postgres storage across machines |
| Scale-out | **Ray** (Ray Tune) | Turns the same sweep into a multi-machine job; supports AWS spot instances | Only once one machine is too slow |
| Experiment tracking | **MLflow** | Every trial's parameters, data snapshot, code commit and metrics in one place; integrates with Ray Tune | The trial count feeds the Deflated Sharpe Ratio. The local store is SQLite, `mlruns/mlflow.db` (MLflow 3.18 refuses plain-folder stores); browse it with `uv run mlflow ui --backend-store-uri sqlite:///mlruns/mlflow.db` |
| Results analysis | **Parquet + DuckDB / Polars** | Query hundreds of thousands of trial rows in seconds | One row per trial |
| Overfitting statistics | **ml4t-diagnostic** or **purgedcv**, cross-checked by our own tested code | Deflated Sharpe Ratio, Probability of Backtest Overfitting, combinatorial purged cross-validation | Libraries are young; verify against known examples |
| Prediction models | **LightGBM**, scikit-learn; **statsforecast** baselines; pretrained time-series models (Chronos-2, TimesFM 2.5, Moirai 2) as zero-shot baselines | Gradient boosting is the workhorse for tabular market features; pretrained models are cheap to test | Judge everything by trading profit after costs |
| Optional fast scout | **vectorbt** (open-source edition) | Vectorized engine: thousands of simple signal combinations in seconds | Ideas only, in `research/`. Anything promising is rebuilt in Nautilus. Add it only if Nautilus sweeps become the bottleneck |
| Data | Kraken OHLCVT, Binance public data, Coinbase REST (free); Tardis, CoinAPI (paid, both have Nautilus integrations) | Free sources cover daily and hourly bars for years | Paid tick data only if a strategy needs it |

**Why not a second engine?** We chose one engine to keep things simple. The cost is speed: an event-driven engine is slower than a vectorized one. Smart search (Optuna) and parallel processes recover most of that. If sweeps still take too long, vectorbt can scout ideas, but its numbers never go into a report. The lab's small pure-Python reference engines serve tests, demos and scouting (`lab/runner/reference.py` is pinned to Nautilus by a parity test; the multi-asset `portfolio.py` is not yet); a result and the luck controls it is judged against run on one engine ([AGENTS.md: Running many simulations](AGENTS.md#running-many-simulations), rule 6).

## Validation methods

| Method | What it catches | How we use it |
|---|---|---|
| **Fixed train / validate / test splits** | Tuning on the data you report | Test window opened once per strategy, at sign-off |
| **Walk-forward analysis** | Parameters that only worked in one period | Re-fit on a rolling window, score on the next unseen block, with a purge gap between them. This is the Optuna objective |
| **Combinatorial purged cross-validation (CPCV)** | Luck from having only one historical path | Many train/test combinations with purging and embargo; gives a distribution of results instead of one number. Research comparing methods found CPCV better than walk-forward alone at preventing false discoveries |
| **Deflated Sharpe Ratio (DSR)** | A high Sharpe that's just the best of many tries | Haircuts the Sharpe for the number of trials, return length, skew and fat tails. Bayesian search produces correlated trials, so use an effective trial count, not the raw count |
| **Probability of Backtest Overfitting (PBO)** | Picking the in-sample winner that ranks poorly out of sample | Computed across all of the search's trials; complements DSR rather than replacing walk-forward |
| **Parameter plateau** | A sharp peak that collapses if anything shifts | Every parameter ±20%, and every combination of settings a user can pick; the result must stay mostly intact |
| **Cost stress** | Edges that only exist at unrealistically low costs | Re-run finalists with costs doubled |
| **Monte Carlo** | Results that depend on the exact order of events | Shuffle trade order; resample blocks of regimes; randomly worsen fills. Use the 95th-percentile drawdown to set each risk level's budget |
| **Regime breakdown** | One lucky stretch producing all the profit | Split results by bull, bear and sideways periods, including the 2018 and 2022 crashes |
| **Benchmarks** | Complexity that doesn't beat doing nothing | Buy-and-hold BTC, 50/50 BTC/USDC rebalance, random entries with the same trade count |

## Prediction models

### What the evidence says

- Financial returns are hard to predict: low signal, frequent regime changes, fat tails.
- Recent studies of pretrained time-series models (TimesFM, Chronos, Moirai and others) find them useful as cheap starting points, but not reliable sources of trading profit. Good scores on general forecasting benchmarks don't automatically become profitable forecasts.
- Simple baselines (last value, ARIMA) often win at short horizons.
- Finance-specific pretrained models (for example Kronos, trained on candlestick data) report better results than general models, but these are author-run studies without real execution costs.

### How we use models

1. **Predict things that are more predictable than direction.**
   - *Volatility:* calm and wild periods cluster, so volatility is far more forecastable than price. Use it for position sizing and to pause strategies in extreme conditions.
   - *Regime:* trending vs. sideways. Use it to switch a strategy on or off; trend strategies lose in sideways markets.
   - *Ranking:* which tokens on the Bold list are likely to outperform the others next week. Relative ranking is easier than absolute direction.
2. **Features are point-in-time:** trailing returns and volatility over several windows, volume, BTC's share of the market, cross-asset moves. Nothing computed with future data, and nothing fitted on the full series before splitting.
3. **Validate with purged, embargoed CPCV.** Overlapping labels leak information between folds otherwise.
4. **Judge by money, not error.** A model only earns its place if a strategy using it beats the same strategy without it, after costs, in Nautilus, through the same validation gates.
5. **Always include baselines:** naive forecast, rolling average and `statsforecast` models, plus a zero-shot pretrained model. If a model can't beat these, it doesn't ship.
6. **Production fit:** models train offline, are versioned in MLflow, and are loaded read-only by a Nautilus strategy. Walk-forward retraining copies the production retraining schedule. No LLM ever sits in the trade path.

## Compute plan

| Step | Setup | When to move on |
|---|---|---|
| A | One computer: a process pool plus Optuna with journal file storage | A full study takes more than an overnight run |
| B | One large cloud machine (many cores, spot pricing) running the same code | A study takes more than a day on one machine |
| C | Ray cluster on AWS spot instances, Optuna on Postgres storage, MLflow tracking server | Only when step B isn't enough |

- **Measure before scaling:** time one full-history backtest per strategy and record trials per hour per core. That number decides whether a sweep is a laptop job or a cloud job. The first numbers, for the single-asset Nautilus runner, are in [reports/milestone2/2026-11-25.md](reports/milestone2/2026-11-25.md).
- **Spot instances are fine:** every trial is independent and logged, so an interrupted machine only loses its current trial.
- **Budget guard:** set a monthly cloud spending cap before step B; the owner approves anything above it.

## Specifics for our app

- **Costs match production:** swaps on Base through 0x. Pool fee + aggregator fee + size-dependent slippage + gas (sponsored by us). Measure slippage by sampling live 0x quotes at several trade sizes, and replace the placeholders in `config/costs.yaml`.
- **Price proxy:** backtests use exchange candles; measure how far cbBTC/USDC on Base drifts from BTC/USD on Coinbase, and add that drift to the slippage assumption if it's material.
- **Risk-level budgets:** each level's maximum drawdown budget comes from the Monte Carlo 95th-percentile drawdown of its strategies, rounded up. The owner approves a level's budget before any settings range at that level is pre-registered ([AGENTS.md: Validation gates](AGENTS.md#validation-gates), "Settings ranges"). How a level's first budget is set, before any of its strategies has been audited, is still open with the owner.
- **Strategy card numbers:** backtest figures (labeled hypothetical) come from the walk-forward results; live figures come only from the production model account at the default settings.
- **Customer rule backtests (Phase 2):** the advanced rule builder's Backtest button runs the same cost model and the same Nautilus `RuleStrategy` used here.

## Sources

**NautilusTrader**
- [Installation (v2 release candidates, `--pre`, outside a source checkout)](https://nautilustrader.io/docs/latest/getting_started/installation)
- [Getting started (Python 3.13/3.14; full examples in the repository)](https://nautilustrader.io/docs/latest/getting_started)
- [1.231.0 release notes (v2 transition; tutorials still v1; Python fee and fill model subclasses)](https://newreleases.io/project/github/nautechsystems/nautilus_trader/release/v1.231.0)
- [Backtest APIs and repeated runs (one config per BacktestNode)](https://nautilustrader.io/docs/nightly/concepts/backtesting/apis-and-runs/)
- [Data catalog](https://nautilustrader.io/docs/latest/concepts/data/catalog/)
- [Loading external data into the catalog](https://nautilustrader.io/docs/latest/how_to/loading_external_data/)
- [Tardis integration](https://nautilustrader.io/docs/latest/integrations/tardis/)
- [CoinAPI integration](https://nautilustrader.io/docs/latest/integrations/coinapi/)

**Data**
- [Kraken downloadable OHLCVT data](https://support.kraken.com/articles/360047124832-downloadable-historical-ohlcvt-open-high-low-close-volume-trades-data)
- [Historical crypto data APIs compared, including Binance public data (Coinranking)](https://coinranking.com/blog/best-historical-crypto-data-apis/)
- [Binance public data guide](https://dev.to/pi19404/a-technical-guide-to-downloading-and-managing-binance-historical-crypto-market-data-d82)

**Search, scale and tracking**
- [Optuna: easy parallelization](https://optuna.readthedocs.io/en/stable/tutorial/10_key_features/004_distributed.html)
- [Ray Tune: distributed experiments and spot instances](https://docs.ray.io/en/latest/tune-distributed.html)
- [Ray + MLflow integration (Databricks)](https://databricks.com/blog/2021/02/03/ray-mlflow-taking-distributed-machine-learning-applications-to-production.html)
- [vectorbt open-source edition](https://git.huazai-net.workers.dev/polakowo/vectorbt)

**Validation**
- [AlgoXpert framework: IS, walk-forward and OOS protocol (arXiv 2026)](https://arxiv.org/html/2603.09219)
- [Backtesting and research methodology collection (Trading Strategy)](https://tradingstrategy.ai/docs/learn/backtesting.html)
- [Comparison of cross-validation methods for backtest overfitting (SSRN 4778909)](https://www.scribd.com/document/725401650/SSRN-id4778909)
- [Deflated Sharpe Ratio with correlated Optuna trials (MQL5)](https://www.mql5.com/en/articles/24238)
- [ml4t-diagnostic](https://pypi.org/project/ml4t-diagnostic/)
- [purgedcv](https://pypi.org/project/purgedcv/)
- [Probability of Backtest Overfitting (LuxAlgo)](https://www.luxalgo.com/library/concept/probability-of-backtest-overfitting/)
- [Monte Carlo robustness tests (StrategyQuant)](https://strategyquant.com/blog/new-robustness-tests-on-the-strategyquant-codebase-5-monte-carlo-methods-to-bulletproof-your-trading-strategies/)

**Prediction models**
- [Pretrained time-series foundation models for financial return forecasting (arXiv 2606.27100)](https://econpapers.repec.org/paper/arxpapers/2606.27100.htm)
- [AI in equity and crypto markets: limits of automated investing (arXiv 2609.04917)](https://arxiv.org/pdf/2609.04917)
- [Comparing classical and foundation models for stock forecasting (Leiden thesis 2026)](https://theses.liacs.nl/pdf/2025-2026-KourntidisDDimitrios.pdf)
- [Kronos: a foundation model for financial markets (arXiv 2508.02739)](https://arxiv.org/pdf/2508.02739)
