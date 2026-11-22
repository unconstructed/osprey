# How to work in the Strategy Lab

A task-by-task guide for the owner and the agent team: `data-engineer`, `quant-researcher`, `ml-researcher`, `backtest-auditor` and `risk-officer`.

[AGENTS.md](AGENTS.md) and [TESTING.md](TESTING.md) are the source of truth. Every command for the starter code, and for modules still to build, is copied from them. If this file and those two disagree, they win. Fix this file.

Each section starts with its status:

| Status | Meaning |
|---|---|
| available now (this repo) | You can do it with what is in this repo today |
| built (starter code) | The code exists in the starter code. Copy the starter code in first |
| to build (milestone N) | Not written yet. Commands shown are the planned ones from AGENTS.md and do not run yet |
| not yet possible (no milestone) | Needs a strategy that has passed its audit. AGENTS.md's milestones 0 to 5 do not include paper trading or export |

## Contents

1. [Before you start](#before-you-start)
2. [Set up your machine](#set-up-your-machine)
3. [Set up the project](#set-up-the-project)
4. [Run the tests](#run-the-tests)
5. [Run the demo](#run-the-demo)
6. [Build the data catalog](#build-the-data-catalog)
7. [Run one backtest](#run-one-backtest)
8. [Search parameters](#search-parameters)
9. [Audit a strategy](#audit-a-strategy)
10. [Add a new strategy](#add-a-new-strategy)
11. [Add a prediction model](#add-a-prediction-model)
12. [Paper and export](#paper-and-export)
13. [Dashboard](#dashboard)
14. [Ask the owner first](#ask-the-owner-first)
15. [Troubleshooting](#troubleshooting)

## Before you start

Status: available now (this repo).

### What this repo is

The lab builds strategies, simulates them at scale, validates them against overfitting and luck, and exports approved configs for production. User trades never happen here.

| Does | Never does |
|---|---|
| Download and clean historical data into a Nautilus data catalog | Place, modify or cancel a real order anywhere |
| Build strategies as NautilusTrader strategies | Touch user wallets, the app backend or production infrastructure |
| Run thousands of backtests and parameter searches | Put an LLM in any strategy logic or trade path |
| Validate results against overfitting and luck | Use leverage, short selling, market making or arbitrage |
| Train and evaluate prediction models offline | Send network traffic anywhere except the data sources listed in `lab/data/` |
| Export approved strategy configs for production | Approve its own work for production (the owner does that) |

### What is here today

| Part | Where it is now |
|---|---|
| `README.md`, `HOWTO.md`, `AGENTS.md`, `TESTING.md`, `.gitignore` | This repo |
| The dashboard: `dashboard/`, `scripts/build_dashboard.py`, `tests/test_dashboard.py` | This repo |
| `lab/` (the built modules), the starter tests, `scripts/demo.py`, `pyproject.toml` | The starter code. The owner has it; copy it in ([Set up the project](#set-up-the-project)) |
| `lab/data/build.py`, `lab/costs/`, `lab/runner/nautilus.py`, MLflow logging, `strategies/` | Not written yet (milestones 1 to 3) |
| Real-data searches, audits, prediction models, exports | Not done yet (milestone 4 onward) |
| `research-methods.md` | Missing. AGENTS.md links to it, but it is not in this repo. Ask the owner |
| The app docs (`../caas-app/README.md`) | In the app's repo, not here |

### Read in this order

1. [AGENTS.md](AGENTS.md), all of it.
2. [TESTING.md](TESTING.md). Its section 5 is the first work order.
3. The section of this file for the task at hand.

## Set up your machine

Status: available now (this repo).

You need macOS or Linux, git, about 50 GB free disk for data and results, [uv](https://docs.astral.sh/uv/), and Python **3.13**. NautilusTrader v2 requires 3.13 or 3.14.

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv python install 3.13
```

### NautilusTrader reference clone

The published NautilusTrader tutorials still use the old v1 API. The current v2 API is shown by the repo's `python/examples/` and generated type stubs, so keep a local copy to read.

**Don't build or install from this clone.** Its `pyproject.toml` pins dependency dates for Nautilus's own development and is not our environment.

```bash
mkdir -p ~/code && cd ~/code
git clone https://github.com/nautechsystems/nautilus_trader.git
cd nautilus_trader
git fetch --tags
git tag -l 'v2.0.0*'            # pick the tag that matches our pinned version
git checkout v2.0.0rc9          # must match the version pinned in strategy-lab
```

| Where in the clone | What you find |
|---|---|
| `python/examples/` | Runnable v2 examples: backtests, strategies, data loading |
| `docs/` | Concepts: backtesting, data catalog, fee and fill models |
| `RELEASES.md` | Breaking changes between versions. Read it before every upgrade |

## Set up the project

Status: built (starter code). Option B works without it, but gives you an empty project.

### Option A: copy in the starter code

Use this option. AGENTS.md says to build on the starter code, not rewrite it, and that its `pyproject.toml` already lists every dependency.

1. Copy the starter code into the root of this checkout.
2. Keep this repo's `README.md`, `HOWTO.md`, `.gitignore`, `dashboard/`, `scripts/build_dashboard.py` and `tests/test_dashboard.py`. The `AGENTS.md` and `TESTING.md` here are the owner's current instructions. If the starter code has its own copies of any of these files, don't overwrite this repo's without asking the owner.
3. Check that `config/` came with it: `lab/runner/reference.py` reads `config/costs.yaml`. If `config/` is missing, ask the owner. Don't write `config/` files yourself.
4. Install and check:

```bash
uv sync                      # installs the dev group too: pytest, pytest-cov, pytest-xdist, hypothesis, mutmut, ruff
uv run python -c "import hypothesis, xdist, pytest_cov, mutmut; print('ok')"
uv run python -c "import nautilus_trader as nt; print(nt.__version__)"
```

The engine version must start with "2.".

### Option B: from scratch

These are AGENTS.md's commands. They create a new `strategy-lab` folder with its own git repo. You get the dependencies but none of the starter code.

```bash
cd ~/code
uv init --app --python 3.13 strategy-lab   # also creates the git repo
cd strategy-lab

# Engine: pin an exact v2 version. A plain install resolves to the old 1.x line.
uv add "nautilus_trader[visualization]==2.0.0rc9"

# Data, search, tracking, statistics, models
uv add polars pyarrow duckdb optuna mlflow scipy scikit-learn lightgbm joblib pyyaml httpx tabulate

# Dev tools (testing standard in TESTING.md)
uv add --dev pytest pytest-cov pytest-xdist hypothesis mutmut ruff

# Confirm the engine version starts with "2."
uv run python -c "import nautilus_trader as nt; print(nt.__version__)"
```

To set up inside this checkout instead, skip both `cd` lines. Run `uv init --app --python 3.13` with no folder name from the repo root. uv keeps the existing `README.md` and `.gitignore` and adds `pyproject.toml`, `.python-version` and `main.py`.

### Optional packages

Add these only when needed, and **ask the owner first**:

- `ray[tune]`: multi-machine sweeps
- `vectorbt`: fast idea scouting in `research/` only
- A validation-statistics library (`ml4t-diagnostic` or `purgedcv`) to cross-check our own DSR/PBO/CPCV code
- Forecasting baselines (`statsforecast`) and pretrained time-series models (Chronos-2, TimesFM) for the prediction track

### .gitignore

Already in this repo. It holds the list from AGENTS.md setup step 3, which includes the entries TESTING.md asks for (`.hypothesis/`, `mutants/`, `.coverage`, `htmlcov/`). `/data/`, `/results/` and `/mlruns/` (the root folders only) are ignored, so the data catalog, search runs and test results stay on your machine. They are anchored to the repo root on purpose: AGENTS.md's unanchored `data/` would also ignore every folder named `data`, including `lab/data/`. Keys go in a git-ignored `.env`.

## Run the tests

Status: built (starter code).

### Test tiers

From TESTING.md section 2:

| Tier | When | Command | Time (4 cores) |
|---|---|---|---|
| Quick | Every change | `uv run pytest -m "not slow" -n auto` | ~1.5 min |
| Full | Before merging | `uv run pytest -n auto --cov --cov-branch` | ~2 min |
| Deep | Before merging changes to `lab/` | `HYPOTHESIS_PROFILE=deep uv run pytest -m "not slow" -n auto` | ~10 min |
| Mutation | Before each audit, and nightly once CI exists | `uv run mutmut run` (section 6) | ~10 min per area |

`HYPOTHESIS_PROFILE=fast` is the default: 40 random cases per property. `deep` runs 500. Tests marked `slow` are statistical calibration; `-m "not slow"` skips them.

`tests/test_dashboard.py` from this repo sits in the same `tests/` folder, so the tiers run it too. Expect a higher test count than the starter code's own.

To feed the dashboard, run the full tier with two report flags: see [Test health: JUnit and coverage](#test-health-junit-and-coverage).

### First work order: TESTING.md section 5

**Finish [TESTING.md section 5](TESTING.md#5-open-work-in-order), in order, before building anything new.** TESTING.md has the exact tests to write.

| Step | Work | Done when |
|---|---|---|
| [5.1](TESTING.md#51-verify-the-refactor-that-was-in-progress) | Verify the refactor: three helpers pulled out of larger functions | Full tier passes except the two 5.2 failures; bootstrap and PBO outputs for a fixed seed are unchanged |
| [5.2](TESTING.md#52-fix-the-two-failures-found-by-the-deep-profile) | Fix the two deep-profile failures. A is a code bug (the flat-series check isn't scale invariant). B is a test bug (the present-bar tamper) | Both fixed with `@example` regressions; logged in the bug log as #8 and a test bug |
| [5.3](TESTING.md#53-close-the-mutation-testing-gaps-in-labvalidation) | Close the mutation gaps in `lab/validation/` with exact tests | Every survivor killed or listed in `tests/MUTATION_NOTES.md`; ≥ 90% of non-equivalent mutants killed |
| [5.4](TESTING.md#54-extend-mutation-testing-to-the-rest-of-lab) | Extend mutation testing to the rest of `lab/`, one area at a time | ≥ 90% for `lab/validation/` and `lab/runner/`; ≥ 80% for `lab/search/`, `lab/models/` and `lab/data/` |
| [5.5](TESTING.md#55-rerun-the-demo-and-update-the-docs) | Rerun the demo and update the docs | New `reports/demo/<date>.md` committed; AGENTS.md figures updated |
| [5.6](TESTING.md#56-turn-the-backtester-tests-into-a-contract-every-runner-must-pass) | Split the backtester tests into a contract every runner must pass | `tests/contract/test_backtest_contract.py` parametrized over a `runner` fixture; `tests/test_reference_rules.py` |
| [5.7](TESTING.md#57-raise-the-coverage-floor) | Raise the coverage floor | `fail_under = 100` in `pyproject.toml` |

When you finish an item, set it to `done` under `open_work` in `dashboard/status.json`. When an item of the [definition of done](TESTING.md#8-definition-of-done-this-testing-work) is met, tick its box in TESTING.md section 8. The dashboard reads both.

### Rules for agents

From [TESTING.md section 1](TESTING.md#1-rules-for-the-agent):

1. Triage every failure before touching anything. Is the code wrong or the test? Write the answer in the [bug log](TESTING.md#4-bug-log) either way.
2. **Never weaken a test to make it pass** (looser tolerance, narrower input range, deleted assertion) without a written reason in the bug log. "It was flaky" is not a reason.
3. A failing hypothesis example becomes a permanent regression test: add `@example(...)` above the `@given`.
4. **Don't change validation thresholds (`lab/search/report.py: gates`) or anything in `config/` to make tests pass.** They belong to the owner.
5. Keep `filterwarnings = ["error::RuntimeWarning:lab.*"]` in `pyproject.toml`. A divide-by-zero inside `lab/` is a bug, not noise.
6. Seed all randomness. Searches in tests use `n_workers=1`.
7. Report with numbers (below).

New tests follow the [patterns in TESTING.md section 7](TESTING.md#7-patterns-for-new-tests).

### Mutation testing

Config lives in `pyproject.toml` under `[tool.mutmut]`. Work one area at a time (TESTING.md 5.4 and [section 6](TESTING.md#6-mutation-testing-notes-mutmut-38)):

```bash
HYPOTHESIS_PROFILE=fast uv run mutmut run --max-children 4
uv run mutmut results            # lists survivors
uv run mutmut show <name>        # shows one mutant's diff
```

- Delete `mutants/` between configuration changes.
- Kill real survivors with new tests. List each accepted equivalent mutant in `tests/MUTATION_NOTES.md` with a one-line reason.
- After each area, save its numbers for the dashboard: see [Mutation results per area](#mutation-results-per-area).
- Known pitfalls are in [Troubleshooting](#troubleshooting).

### Report back

When the testing work is done, post this to the owner ([TESTING.md section 9](TESTING.md#9-report-back)):

```
Tests: <n> total (<n> slow) — all passing (fast, full, deep)
Coverage: <x>% branch
Mutation score: validation <x>%, runner <x>%, search <x>%, models <x>%, data <x>%
Bugs found this round: <list, one line each: where, what, fix>
Demo after fixes: <headline numbers vs. before>
Anything you had to decide that the owner should know: <list>
```

## Run the demo

Status: built (starter code).

```bash
uv run python scripts/demo.py --trials 150 --workers 4
```

The demo runs the pipeline end to end on synthetic data, using the reference backtester. Both are for tests and demos only. **Demo numbers are never strategy results** and never go in an audit report.

Fixes 4 to 6 in the [bug log](TESTING.md#4-bug-log) changed every backtest number, so every old demo number is stale. After you rerun it ([TESTING.md 5.5](TESTING.md#55-rerun-the-demo-and-update-the-docs)):

1. Commit the new report the demo writes to `reports/demo/<date>.md`.
2. Update the figures in AGENTS.md, "What the demo taught us". Change the wording if a lesson no longer holds.
3. Set open work 5.5 to `done` in `dashboard/status.json` and rebuild the dashboard. It lists `reports/demo/` under Reports, not as a strategy.

Parallel searches aren't bit-reproducible, so a rerun won't match the old numbers exactly. Re-running logged parameters is exact.

## Build the data catalog

Status: to build (milestone 1).

Owner: `data-engineer`.

Already built (starter code): `lab/data/loaders.py`, the Kraken OHLCVT and Binance kline CSV loaders (verify them against real files), and `lab/data/synthetic.py`, for tests and demos only. To build: `lab/data/build.py`, with downloaders, quality checks, the catalog writer and `SNAPSHOT.json`.

| Source | Use | Cost |
|---|---|---|
| Kraken downloadable OHLCVT | Primary daily and hourly bars for BTC and ETH | Free |
| Binance public data (data.binance.vision) | Second source; wider token coverage for the Bold list | Free |
| Coinbase public REST candles | Cross-check, and the closest match to Base prices | Free |
| Tardis, CoinAPI | Later, only if a strategy needs intraday detail | Paid: ask the owner first |

Pipeline (from AGENTS.md):

1. Download raw files into `data/raw/<source>/` and record a SHA-256 of each file.
2. Normalize to one schema (UTC timestamps, bar close time, OHLCV), de-duplicate, check for gaps and bad ticks.
3. Write instruments and bars to the Nautilus `ParquetDataCatalog` in `data/catalog/`.
4. Write `data/catalog/SNAPSHOT.json`: sources, file hashes, date ranges, row counts. Every backtest records this snapshot ID.
5. Cross-check sources: the same day's BTC close from Kraken, Binance and Coinbase must agree within a small tolerance. Log outliers.

Planned command. AGENTS.md lists it under "to build in milestones 1–4"; it does not exist yet:

```bash
uv run python -m lab.data.build --sources kraken,binance   # download + build catalog
```

Production trades happen on Base (cbBTC, ETH, USDC). Exchange candles are only a proxy for Base prices. Measure the gap between cbBTC/USDC on Base and BTC/USD on Coinbase, and report it.

### SNAPSHOT.json and the dashboard

The format isn't fixed yet. AGENTS.md requires sources, file hashes, date ranges and row counts. The dashboard reads the file leniently and shows these keys when they are present:

| Key | Meaning |
|---|---|
| `snapshot_id` (or `id`) | The ID every backtest records |
| `created` | When the snapshot was written |
| `sources` | The sources, as a list or an object |
| `series` | A list of `{instrument, source, bar, start, end, rows, gaps}` |

With any other shape, the dashboard lists the file's top-level keys and shows a warning.

Commit the data quality report as Markdown in `reports/data/`. AGENTS.md doesn't fix a path; `reports/data/*.md` is where the dashboard looks.

Done when (milestone 1): environment builds; BTC and ETH daily and hourly bars from Kraken and Binance in the catalog; `SNAPSHOT.json` written; data quality report committed.

## Run one backtest

Status: to build (milestone 2).

Every result that counts comes from NautilusTrader. The reference backtester (`lab/runner/reference.py`) is for tests and demos only, never for reports.

### The contract

`lab/runner/interface.py` (built) defines it: `backtest_fn(params, bars) -> DataFrame` with columns `ret` (net per-period return after all costs), `position`, `turnover`, plus `attrs["trade_returns"]`. A runner that meets it plugs into the existing search and validation code unchanged.

### What to build

1. `lab/costs/`: Nautilus v2 fee and fill model subclasses implementing `config/costs.yaml`: pool fee, aggregator fee, size-based slippage and gas.
2. `lab/runner/nautilus.py`: implements `BacktestFn` on a NautilusTrader v2 `BacktestNode`, reading bars from the catalog. One run config per node; dispose the node after use. Same columns and `trade_returns` as the reference.
3. MLflow logging of each trial and model version. Trials are already logged to Parquet.

### Costs

**Every backtest runs with the cost model on. A zero-cost backtest is not a result.**

Production trades are swaps on Base through the 0x aggregator. Cost per trade = pool fee + aggregator fee (if any) + slippage (grows with trade size) + gas (we sponsor it, so it's our cost). `config/costs.yaml` starts with pessimistic placeholders. `data-engineer` replaces them with measured values by sampling 0x price quotes on Base at several trade sizes. Changing `config/costs.yaml` needs the owner's approval.

### Tests that gate milestone 2

- Tests for the fee and fill models in `lab/costs/`.
- The backtest contract suite ([TESTING.md 5.6](TESTING.md#56-turn-the-backtester-tests-into-a-contract-every-runner-must-pass)): `tests/contract/test_backtest_contract.py`, parametrized over a `runner` fixture. The Nautilus runner must pass it.
- A parity test: the reference and Nautilus runners agree closely on a simple strategy with identical costs.

### Measure throughput

Before any big sweep, time a single full-history backtest and report trials per hour per core. Size sweeps from that number.

### Planned command

AGENTS.md lists it under "to build in milestones 1–4"; it does not exist yet. It also needs the strategy, which is milestone 3.

```bash
uv run python -m lab.runner.run_one --strategy dip-buy-balanced --window train
```

Once MLflow logging exists, browse every trial with `uv run mlflow ui`.

Done when (milestone 2): fee and fill models in `lab/costs/` with tests; `lab/runner/nautilus.py` implements `BacktestFn` and passes the backtest contract suite; parity test against the reference passes; trials also logged to MLflow; throughput (trials per hour per core) measured.

## Search parameters

Status: to build (milestone 4). The search code in `lab/search/` is built (starter code); real-data searches with the Nautilus runner are not.

### How the search works

- **Measure throughput first** ([Run one backtest](#measure-throughput)).
- Optuna studies (TPE sampler) run in parallel processes, one per CPU core. Local runs use Optuna's journal file storage; multi-machine runs use a Postgres storage.
- **The objective is a walk-forward out-of-sample score after costs, never in-sample return.** `lab/search/objective.py` scores the mean annualized Sharpe across time blocks minus 0.5 × their spread. Too few trades scores −10.
- `lab/search/walkforward.py` searches each fold's past, trades the next unseen block and stitches the out-of-sample curve. It reports walk-forward efficiency.
- `lab/search/stability.py` picks the parameters with the best neighbourhood score, not the single best trial.

### Splits

`config/splits.yaml` is fixed. Changing it requires owner approval.

| Window | Dates |
|---|---|
| Train | 2017-01-01 to 2022-12-31 (includes the 2018 and 2022 crashes) |
| Validate | 2023-01-01 to 2024-06-30 |
| Test | 2024-07-01 to latest: the final holdout, run once per strategy at sign-off |

Walk-forward and cross-validation happen inside train + validate. **Nobody tunes on the test window.** Log every look at the validate window in the strategy's README.

### Log every trial

**Every trial is logged, including failures and abandoned variants. Hiding trials inflates results.** Each trial records strategy, params, window, data snapshot ID, git commit, seed, all metrics and failures. The total trial count per strategy feeds the Deflated Sharpe Ratio.

`lab/search/study.py` (built) logs every trial's params, metrics and full return series to `results/<study>/`. AGENTS.md's logging rule also names `results/trials/*.parquet` and one MLflow run per trial. `results/` is git-ignored. The dashboard lists each folder in `results/`, except `results/tests/`, as a local search run.

### Run important searches twice

Parallel searches aren't bit-reproducible. Run important searches twice with different seeds; a large difference flags a fragile strategy. Re-running logged parameters is exact.

### Planned command

AGENTS.md lists it under "to build in milestones 1–4"; it does not exist yet as a command:

```bash
uv run python -m lab.search.study --strategy dip-buy-balanced --trials 2000 --workers 8
```

Multi-machine sweeps with `ray[tune]` are a new dependency: ask the owner first.

## Audit a strategy

Status: to build (milestone 4).

Owner: `backtest-auditor`, who never writes or tunes strategy logic.

**An audit only counts if the full test tier passed on that commit** (hard rule 11).

### The gates

A strategy is ready for paper when `backtest-auditor` reports PASS on all of these. Thresholds are defaults the owner can change. Don't change them yourself.

| Gate | Default | Key in the audit JSON |
|---|---|---|
| Walk-forward out-of-sample Sharpe, after costs | ≥ 1.0 | `wf_oos_sharpe` |
| Same, with costs doubled | > 0.5 | `wf_oos_sharpe_2x_costs` |
| Deflated Sharpe Ratio (counting every trial) | ≥ 0.95 | `dsr` |
| Probability of Backtest Overfitting | ≤ 0.25 | `pbo` |
| Parameter plateau: every parameter ±20% | Keeps ≥ 70% of the Sharpe | `plateau_retention` |
| Monte Carlo 95th-percentile max drawdown | Within the risk level's budget | `mc_p95_max_drawdown` |
| Beats benchmarks | Better risk-adjusted return than buy-and-hold BTC and 50/50 rebalance over the walk-forward | `beats_benchmarks` |
| Regimes | No single regime (bull, bear, sideways) produces most of the profit | `regime_max_profit_share` |
| Final test window, run once | Sharpe within a reasonable distance of walk-forward; no new failure modes | `final_test` |

Steady's drawdown budget in `config/risk_levels.yaml` is 35% (owner-approved 2026-11-21); Balanced's and Bold's are still TBD. The budget is a limit on the Monte Carlo 95th-percentile max drawdown, and `risk-officer` writes a budget only after the owner approves it (hard rule 10).

### Steps

1. Confirm the full test tier passed on the commit you audit.
2. On train + validate: walk-forward, CPCV, DSR with every trial counted, PBO, the parameter plateau and Monte Carlo drawdowns.
3. Re-run with all costs doubled (`stress_multiplier: 2.0` in `config/costs.yaml`).
4. Compare against the benchmarks: buy-and-hold BTC, a 50/50 BTC/USDC monthly rebalance, and random-entry strategies with the same number of trades.
5. Only after everything else passes, run the test window. **The test window is opened once per strategy, by `backtest-auditor`. Once used, it is burned for that strategy.**
6. Write the report to `reports/<name>/<YYYY-MM-DD>.md` and commit it.
7. Write the JSON sidecar next to it, `reports/<name>/<YYYY-MM-DD>.json`, in the [audit JSON schema](#audit-json-schema). The dashboard reads only the JSON. **Missing numbers fail, never pass.**

Planned command. AGENTS.md lists it under "to build in milestones 1–4"; it does not exist yet. When it is built, it should write both the report and the JSON sidecar.

```bash
uv run python -m lab.validation.audit --strategy dip-buy-balanced
```

## Add a new strategy

Status: to build (milestone 3).

Owner: `quant-researcher` (or `ml-researcher` for model-using strategies). `quant-researcher` never touches `config/`, opens the test window or writes audit reports.

### Files

```
strategies/<name>/
├── strategy.py
├── params.yaml
└── README.md
```

`strategy.py` is a NautilusTrader v2 strategy. Check the API in the reference clone's `python/examples/`; the published tutorials use v1. Log every look at the validate window in the strategy's `README.md`.

### Rules

- **Keep free parameters to 4 or fewer.**
- Trade only coins on the risk level's list in `config/risk_levels.yaml`. Spot only: no leverage, shorting, market making or arbitrage.
- No look-ahead: signals at bar *t* use data available at the close of bar *t*; fills happen no earlier than bar *t+1*.
- No LLM in any strategy logic or trade path.
- Costs always on.
- Compare against every benchmark: buy-and-hold BTC, a 50/50 BTC/USDC monthly rebalance, and random-entry strategies with the same number of trades.

### Tests

New strategies ship with the tests [TESTING.md section 7](TESTING.md#7-patterns-for-new-tests) describes, **including a tamper-the-future test**: change data from bar `cut` onward, and everything decided before `cut` must be identical. Other patterns there: touch the present, hand-built paths (`make_bars([...])`), known answers, identities.

### Launch strategies (milestone 3)

| Strategy | Risk level | Idea | Free parameters (keep ≤ 4) |
|---|---|---|---|
| `rebalance-steady` | Steady | Hold BTC, ETH and USDC at target weights; rebalance when drift exceeds a band | Target weights, drift band, check frequency |
| `dip-buy-balanced` | Balanced | Buy BTC or ETH after a drop of X% over N days, capped per period; stop-loss | Drop %, lookback, cap, stop % |
| `momentum-bold` | Bold | Each week, hold the top K tokens by trailing return from the vetted list; rest in USDC | Lookback, K, rebalance day, cash filter |

Done when (milestone 3): the three strategies as Nautilus strategies, backtested on the train window with costs on, plus all benchmarks.

### Handoff

`quant-researcher` (or `ml-researcher`) → `backtest-auditor` → `risk-officer` → paper model account → owner → export.

The dashboard shows a strategy as Built as soon as `strategies/<name>/strategy.py` exists.

## Add a prediction model

Status: built (starter code). Models on real data are to build (milestone 5).

Owner: `ml-researcher`, who never puts a model in a strategy without an audit and never uses future data.

Built (starter code), in `lab/models/`: point-in-time features and cross-sectional ranks (`features.py`), labels (`labels.py`), baselines (`baselines.py`), LightGBM training with CPCV against baselines on identical test rows and `walk_forward_predict` (`train.py`), model files that refuse to load if tampered with (`artifact.py`), and `FeatureBuffer` and `ModelPredictor` for live use (`online.py`).

### Steps

1. Pick a target that is more predictable than price direction: volatility, regime (trend vs. sideways), or cross-sectional ranking for the Bold list.
2. Compute features and labels point-in-time. Cross-validate with purged, embargoed CPCV.
3. Compare against naive baselines (last value, rolling average).
4. **Judge the model by strategy profit after costs in Nautilus**, not by forecast error alone.
5. Train offline and version the model in MLflow (MLflow logging is still to build: milestone 2 covers trials; AGENTS.md gives model-version logging no milestone). A Nautilus strategy loads it read-only.
6. No retraining inside a backtest window. Walk-forward retraining copies the production schedule.

### Lessons from the demo

These come from synthetic data, and the figures behind them predate the backtester fixes (see AGENTS.md, "What the demo taught us"):

- Anchor volatility models to EWMA: predict a correction on top of an EWMA forecast.
- Regularize hard. The defaults in `make_model` do.
- Horizon matters. Use the horizon that wins.
- Volatility forecasts are most useful for sizing.

### Using a model in a strategy

Model-using strategies keep a `FeatureBuffer` and a `ModelPredictor`. From AGENTS.md:

```python
# inside a Nautilus Strategy (v2 API: check python/examples/ in the reference clone)
def on_start(self):
    self.features = FeatureBuffer()
    self.vol_model = ModelPredictor("models/vol_20d")

def on_bar(self, bar):
    self.features.update(bar.ts_event, bar.open, bar.high, bar.low, bar.close, bar.volume)
    feats = self.features.latest()
    if feats is None:
        return  # still warming up
    forecast_vol = self.vol_model.predict(feats)
    size = min(self.max_weight, self.vol_target / forecast_vol)
    ...  # signal logic, then submit orders through Nautilus
```

`FeatureBuffer` gives live features identical to the backtest features; the starter tests check this on every bar.

`statsforecast` and pretrained time-series models (Chronos-2, TimesFM) are new dependencies: ask the owner first.

Done when (milestone 5): volatility (5- and 20-day), regime and Bold-list ranking models vs. baselines with CPCV on real data; at least one model-sized strategy variant audited.

## Paper and export

Status: not yet possible (no milestone). No strategy has been audited yet.

1. **Ready for paper:** `backtest-auditor` reports PASS on every gate.
2. **Paper:** at least 4 weeks on a paper model account, with results within tolerance of the backtest. Paper accounts run in the production app, not in this repo.
3. **Owner approval.** Ready for production is the owner's decision, never an agent's.
4. **Export:** `risk-officer` writes `exports/<name>/config.yaml` with pinned parameters, risk level, coin list and code commit. AGENTS.md doesn't fix the field names yet. Never put a key or secret in it.

`risk-officer` never loosens a limit without the owner's written approval.

Record paper status in `dashboard/status.json`, then rebuild the dashboard:

```json
"strategies": {
  "rebalance-steady": {"paper": {"status": "in_progress", "started": "YYYY-MM-DD", "note": ""}}
}
```

## Dashboard

Status: available now (this repo).

`dashboard/index.html` is one self-contained HTML page. `scripts/build_dashboard.py` builds it from files in this repo. [dashboard/README.md](dashboard/README.md) describes each section of the page.

### View it

Open [dashboard/index.html](dashboard/index.html) in a browser. It works from `file://` with no network: no CDN, no web fonts. GitHub shows the file's source, not the page. The header shows when the page was built (UTC) and from which git commit and branch.

### Rebuild it

From the repo root:

```bash
python3 scripts/build_dashboard.py                 # read repo root (cwd), write dashboard/index.html
uv run python scripts/build_dashboard.py           # same, inside the project env
python3 scripts/build_dashboard.py --root PATH     # read another checkout
python3 scripts/build_dashboard.py --out PATH      # write elsewhere (default: <root>/dashboard/index.html)
python3 scripts/build_dashboard.py --json PATH     # also write the collected data as JSON
python3 scripts/build_dashboard.py --sample --out /tmp/sample.html   # synthetic preview, SAMPLE banner, never writes into the repo by default
```

The builder uses the Python standard library only, so plain `python3` works without the project environment. It needs no third-party package; YAML files are only listed by path, never parsed. It prints a one-line summary of what it found and where it wrote. A missing, empty or broken input never stops it; the problem shows up in the page's Warnings section.

Rebuild and commit `index.html` when its inputs change: a status edit, a new audit, a new report. Test health, the data snapshot and search runs come from git-ignored files on your machine. A committed page shows whatever was on the builder's machine when it was built.

### Inputs

All inputs are optional. A missing one shows an empty state with a one-line hint on how to fill it.

| Dashboard section | Reads | In git | Made by | Status |
|---|---|---|---|---|
| Milestones, gates, launch strategies | `AGENTS.md`: the `## Milestones`, `## Validation gates` and `## Strategies to build first` tables | Yes | The owner | available now (this repo) |
| Definition of done, bug-log count, open work | `TESTING.md`: section 8 checkboxes, the section 4 bug table, the `### 5.N` headings | Yes | Tick boxes and add bug rows as work gets done | available now (this repo) |
| Hand-kept status | `dashboard/status.json` | Yes | The team, by hand ([format](#dashboardstatusjson)) | available now (this repo) |
| Test run | `results/tests/junit.xml` | No | [Full tier with JUnit report](#test-health-junit-and-coverage) | built (starter code) |
| Coverage | `results/tests/coverage.json` | No | [Full tier with JSON coverage report](#test-health-junit-and-coverage) | built (starter code) |
| Mutation score | `results/tests/mutation/<area>.json` | No | [Copied from mutmut per area](#mutation-results-per-area) | built (starter code) |
| Data snapshot | `data/catalog/SNAPSHOT.json` | No | `lab.data.build` ([format](#snapshotjson-and-the-dashboard)) | to build (milestone 1) |
| Data quality reports | `reports/data/*.md` | Yes | `data-engineer` | to build (milestone 1) |
| Search runs | Each folder in `results/` except `results/tests/`: Parquet file count, Optuna journal (`*.log`, `*.journal`, `journal*`), last modified | No | `lab/search/study.py` | built (starter code) |
| Audits | `reports/<strategy>/<YYYY-MM-DD>.json` | Yes | `backtest-auditor` ([schema](#audit-json-schema)) | to build (milestone 4) |
| Exports | `exports/<name>/config.yaml`: path and last-modified only, never parsed | Yes | `risk-officer` | not yet possible (no milestone) |
| Strategy folders | `strategies/<name>/`: whether `strategy.py`, `params.yaml`, `README.md` exist | Yes | `quant-researcher` | to build (milestone 3) |
| Git commit and branch | `git rev-parse`; "unknown" if that fails | - | git | available now (this repo) |
| Reports | Every `reports/**/*.md`, newest first | Yes | The demo, `data-engineer`, `backtest-auditor` | built (starter code): the demo report |

`reports/demo/` and `reports/data/` are not strategies.

### Test health: JUnit and coverage

Run the full tier with two report flags, then rebuild. From the repo root:

```bash
uv run pytest -n auto --cov --cov-branch --cov-report=term --cov-report=json:results/tests/coverage.json --junitxml=results/tests/junit.xml
python3 scripts/build_dashboard.py
```

That is the full tier from TESTING.md (`uv run pytest -n auto --cov --cov-branch`) plus:

| Flag | Writes | The dashboard shows |
|---|---|---|
| `--junitxml=results/tests/junit.xml` | pytest's JUnit XML report | Total, passed, failed, errors, skipped, time, timestamp |
| `--cov-report=json:results/tests/coverage.json` | coverage.py's JSON report | `totals.percent_covered`, and the lowest-covered files from `files.*.summary.percent_covered` |
| `--cov-report=term` | Nothing | Keeps the coverage table in your terminal; any `--cov-report` flag replaces the default one |

pytest and pytest-cov create `results/tests/` if it is missing. Both files are git-ignored. Use the full tier, not the quick tier, so the counts include the slow tests. A result only counts if the full tier passed on that commit.

The same two inputs from separate runs, if you prefer:

```bash
uv run pytest -n auto --junitxml=results/tests/junit.xml
uv run pytest -n auto --cov --cov-branch --cov-report=json:results/tests/coverage.json
```

### Mutation results per area

The dashboard reads one file per area, `results/tests/mutation/<area>.json`. It is mutmut's own stats file, copied after each area's run.

| `<area>` | Code mutated | Test files (TESTING.md 5.4) | Target |
|---|---|---|---|
| `validation` | `lab/validation/` | Not listed in 5.4; see [5.3](TESTING.md#53-close-the-mutation-testing-gaps-in-labvalidation) | ≥ 90% |
| `runner` | `lab/runner/reference.py` | `test_backtester_props.py`, `test_search.py` | ≥ 90% |
| `search` | `lab/search/` | `test_search_props.py`, `test_search.py` | ≥ 80% |
| `models` | `lab/models/` | `test_features_leakage.py`, `test_labels_props.py`, `test_train_props.py`, `test_artifacts_loaders.py`, `test_models.py` | ≥ 80% |
| `data` | `lab/data/loaders.py` | `test_artifacts_loaders.py` | ≥ 80% |

For each area, from the repo root:

```bash
rm -rf mutants/                                   # delete between configuration changes
# set [tool.mutmut] in pyproject.toml for this area (TESTING.md 5.4 and section 6)
HYPOTHESIS_PROFILE=fast uv run mutmut run --max-children 4
uv run mutmut results                             # kill real survivors or document them, then run again
uv run mutmut export-cicd-stats                   # writes mutants/mutmut-cicd-stats.json
mkdir -p results/tests/mutation
cp mutants/mutmut-cicd-stats.json results/tests/mutation/validation.json   # use this area's name
python3 scripts/build_dashboard.py
```

Copy the file right after the area's final run. The next area's `rm -rf mutants/` deletes it.

The dashboard reads the keys mutmut 3.8 writes: `killed`, `survived`, `timeout`, `suspicious`, `no_tests`, `skipped`, `total`, `segfault` and `check_was_interrupted_by_user`. It shows `segfault` when it is not 0, and warns that the counts are partial when `check_was_interrupted_by_user` is not 0. It computes:

```
score = (killed + timeout) / (killed + timeout + survived)
```

TESTING.md's baseline for `lab/validation/` is consistent with this formula: 492 killed, 3 timed out, 123 survived → 495/618 = 80%. `no_tests` mutants are not in the score. That matters because mutmut mutates all of `lab/` even when the config names one area (TESTING.md section 6). mutmut's own percentage (its `badge` command) divides by every mutant except skipped ones, so it can come out lower.

Optional: add `"equivalent": <n>` by hand to the copied file. `<n>` is the number of that area's survivors listed in `tests/MUTATION_NOTES.md`. The dashboard then also shows:

```
score_excluding_equivalent = (killed + timeout) / (killed + timeout + survived - equivalent)
```

The 5.3 target, "≥ 90% of non-equivalent mutants killed", is this second number.

### dashboard/status.json

The only file of hand-typed status. Edit it, rebuild, and commit both.

```json
{
  "updated": "YYYY-MM-DD",
  "note": "free text shown at the top",
  "milestones": {"0": {"status": "not_started", "note": "Starter code not yet copied into this repo"}},
  "open_work": {"5.1": "not_started"},
  "strategies": {"rebalance-steady": {"paper": {"status": "not_started", "started": null, "note": ""}}}
}
```

| Key | Holds |
|---|---|
| `updated` | Date of the last edit |
| `note` | Free text shown at the top of the page |
| `milestones."0"` to `milestones."5"` | `status` and `note` for each milestone |
| `open_work."5.1"` to `open_work."5.7"` | Status of each TESTING.md section 5 item |
| `strategies.<name>.paper` | The paper model account: `status`, `started` (a date or `null`), `note` |

Status values: `not_started`, `in_progress`, `done`, `blocked`. Any other value is shown as typed, with a warning. Mark a milestone `done` only when its "Done when" in AGENTS.md is met.

The committed file starts with every milestone and open-work item `not_started`, milestone 0's note "Starter code not yet copied into this repo", and the three launch strategies with paper `not_started`.

### Audit JSON schema

Schema `osprey.audit/1`. One file per audit, written by the audit step next to its report: `reports/<strategy>/<YYYY-MM-DD>.json` beside `reports/<strategy>/<YYYY-MM-DD>.md`. The newest date per strategy is the latest audit. Older files are its history; the dashboard shows their count and verdict trail.

The shape, with `null` where the audit fills in a number. Thresholds shown are AGENTS.md's defaults, except `regime_max_profit_share`, which AGENTS.md states only in words; confirm its number, and `<` versus `<=`, with the owner. Write the thresholds you actually used.

```json
{
  "schema": "osprey.audit/1",
  "strategy": "dip-buy-balanced",
  "date": "YYYY-MM-DD",
  "risk_level": "balanced",
  "verdict": "INCOMPLETE",
  "git_commit": "<short commit hash>",
  "data_snapshot": "<snapshot id>",
  "seed": null,
  "n_trials": null,
  "effective_trials": null,
  "window": {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"},
  "test_window_opened": false,
  "gates": {
    "wf_oos_sharpe":           {"value": null, "threshold": 1.0,  "op": ">=", "pass": null},
    "wf_oos_sharpe_2x_costs":  {"value": null, "threshold": 0.5,  "op": ">",  "pass": null},
    "dsr":                     {"value": null, "threshold": 0.95, "op": ">=", "pass": null},
    "pbo":                     {"value": null, "threshold": 0.25, "op": "<=", "pass": null},
    "plateau_retention":       {"value": null, "threshold": 0.70, "op": ">=", "pass": null},
    "mc_p95_max_drawdown":     {"value": null, "threshold": null, "op": "<=", "pass": null, "note": "risk budget TBD"},
    "beats_benchmarks":        {"value": null, "pass": null},
    "regime_max_profit_share": {"value": null, "threshold": 0.5,  "op": "<",  "pass": null},
    "final_test":              {"value": null, "pass": null, "note": "run once at sign-off"}
  },
  "metrics": {"wf_oos_sharpe": null, "cagr": null, "max_drawdown": null, "n_trades": null, "walk_forward_efficiency": null},
  "benchmarks": {
    "buy_hold_btc":    {"sharpe": null, "max_drawdown": null},
    "rebalance_50_50": {"sharpe": null, "max_drawdown": null},
    "random_entry":    {"sharpe_median": null, "sharpe_p95": null}
  },
  "equity": {"dates": [], "series": {"strategy": [], "buy_hold_btc": [], "rebalance_50_50": []}},
  "report_md": "reports/dip-buy-balanced/YYYY-MM-DD.md"
}
```

| Field | Type | Meaning |
|---|---|---|
| `schema` | string | Always `osprey.audit/1`. Any other value: the file is skipped with a warning |
| `strategy` | string | The strategy's folder name |
| `date` | string | Audit date, `YYYY-MM-DD`; matches the file name |
| `risk_level` | string | `steady`, `balanced` or `bold` |
| `verdict` | string | `PASS`, `FAIL` or `INCOMPLETE`, as the auditor judged it |
| `git_commit` | string | The commit the audit ran on |
| `data_snapshot` | string | The snapshot ID from `SNAPSHOT.json` |
| `seed` | integer | The seed used |
| `n_trials` | integer | Every trial run for this strategy, failures included |
| `effective_trials` | number | The effective trial count used for DSR |
| `window` | object | `start` and `end` dates of the data the audit used |
| `test_window_opened` | boolean | `true` once the final test window has been run. It is burned after that |
| `gates` | object | The nine gates below. Each has `value`, `pass` (`true`, `false` or `null`) and an optional `note`. Gates with a numeric threshold also have `threshold` and `op` (`>=`, `>`, `<=` or `<`). `beats_benchmarks` has a `true` or `false` value |
| `metrics` | object | `wf_oos_sharpe`, `cagr`, `max_drawdown`, `n_trades`, `walk_forward_efficiency` |
| `benchmarks` | object | `buy_hold_btc` and `rebalance_50_50` with `sharpe` and `max_drawdown`; `random_entry` with `sharpe_median` and `sharpe_p95` |
| `equity` | object | `dates`, and one series per name (`strategy`, `buy_hold_btc`, `rebalance_50_50`), each as long as `dates`. The chart normalises each series to 1 at the start |
| `report_md` | string | Repo-relative path of the Markdown report |

The nine gate keys, in AGENTS.md table order, with the label the dashboard shows:

| Key | Dashboard label | Default (AGENTS.md) |
|---|---|---|
| `wf_oos_sharpe` | Walk-forward OOS Sharpe after costs | ≥ 1.0 |
| `wf_oos_sharpe_2x_costs` | Same, costs doubled | > 0.5 |
| `dsr` | Deflated Sharpe Ratio | ≥ 0.95 |
| `pbo` | Probability of Backtest Overfitting | ≤ 0.25 |
| `plateau_retention` | Parameter plateau (+/-20% keeps Sharpe) | ≥ 0.70 (keeps ≥ 70% of the Sharpe) |
| `mc_p95_max_drawdown` | Monte Carlo p95 max drawdown | ≤ the risk level's budget (TBD) |
| `beats_benchmarks` | Beats benchmarks | Better risk-adjusted return than buy-and-hold BTC and 50/50 rebalance over the walk-forward |
| `regime_max_profit_share` | No single regime makes most of the profit | No single regime produces most of the profit. AGENTS.md gives no number; this schema encodes it as a share of total profit, threshold 0.5 |
| `final_test` | Final test window (run once) | Sharpe within a reasonable distance of walk-forward; no new failure modes |

**The dashboard does not re-judge values against thresholds.** It shows the thresholds in the file, because those are what the auditor used, and the owner may change them. It derives each strategy's state from the gates' `pass` flags only:

| Gate `pass` flags in the latest audit | State shown |
|---|---|
| Any gate is `false` | FAIL |
| All nine are `true` | READY FOR PAPER |
| The other eight are `true`; only `final_test` is pending | AWAITING FINAL TEST |
| Anything else: some `null` or missing | INCOMPLETE |
| The newest dated file can't be used (invalid JSON, unknown `schema`, not an object) | UNREADABLE |

A missing gate key counts as not passed: missing numbers fail, never pass. If `verdict` says `PASS` but the derived state is not READY FOR PAPER, the page shows an integrity warning. Write `verdict` to match the flags: `PASS` for READY FOR PAPER, `FAIL` for FAIL, `INCOMPLETE` for the other two states. Other mismatches get an ordinary warning. A gate marked `pass: true` with no finite `value` or `threshold` behind it (every gate except `beats_benchmarks` and `final_test`) also gets an integrity warning; its flag still decides the state.

Invalid JSON, an unknown `schema` or a file that is not a JSON object: the file can't be used, and the page still renders. It keeps its date in the history as UNREADABLE. If it is the newest file for the strategy, the strategy shows UNREADABLE with an integrity warning: an older audit is never promoted to latest in its place.

### Strategy lifecycle

The dashboard lists every strategy it finds in the AGENTS.md launch table, `strategies/*`, `reports/<strategy>/*.json` and `exports/*`, and shows how far each has got:

| Stage | Reached when |
|---|---|
| Planned | Listed, nothing built yet |
| Built | `strategies/<name>/strategy.py` exists |
| Audited | At least one audit JSON exists |
| Ready for paper | The latest audit's state is READY FOR PAPER |
| Paper | `status.json` paper status is `in_progress` or `done` |
| Exported | `exports/<name>/config.yaml` exists |

Approval for production is the owner's decision. The dashboard only reports state.

### Preview with sample data

```bash
python3 scripts/build_dashboard.py --sample --out /tmp/sample.html
```

`--sample` fills the page with synthetic data made at run time and puts a "SAMPLE DATA - not real results" banner on it. Without `--out`, it writes `osprey-dashboard-sample.html` to the system temp folder and prints the path. The synthetic tree is made in a temp folder and deleted after the build. `--sample` refuses (exit code 2) an `--out` inside a git checkout, this one or any other. **Never commit a sample page.**

### What the dashboard never does

- Contact the network. The page loads nothing from outside.
- Re-judge gate values. It shows the auditor's numbers and derives state from `pass` flags.
- Approve anything. Production approval is the owner's.
- Read secrets. Export configs are listed by path and time, never parsed.
- Write sample data into a git checkout. `--sample` refuses an `--out` inside one.
- Stop on bad input. Each problem becomes an entry in the page's Warnings.
- Run tests, searches or backtests. It reads files, and asks git for the commit and branch.
- Need a dependency. Standard library only.

No number on the page is typed by hand, except what is in `dashboard/status.json` (and an optional `equivalent` count in a mutation file).

## Ask the owner first

Status: available now (this repo).

From hard rule 10, ask the owner **before**:

- adding a dependency, including the optional packages in [Set up the project](#optional-packages);
- changing `config/splits.yaml`, `config/costs.yaml` or `config/risk_levels.yaml`;
- running anything that will cost money: cloud machines, paid data (Tardis, CoinAPI).

These are also the owner's alone:

- Validation thresholds (`lab/search/report.py: gates`). Never change them to make tests pass.
- Approving a strategy for production.
- Loosening a risk limit: `risk-officer` needs the owner's written approval.

### Desk roles

| Agent | Owns | Never does |
|---|---|---|
| `data-engineer` | `lab/data/`, the catalog, data snapshots, cost measurement | Write strategy logic or change validation thresholds |
| `quant-researcher` | Strategy hypotheses, `strategies/`, search spaces | Touch `config/`, open the test window, write audit reports |
| `ml-researcher` | `lab/models/`, features, labels, model training and evaluation | Put a model in a strategy without an audit; use future data |
| `backtest-auditor` | `lab/validation/`, audit reports, the one-time test-window run | Write or tune strategy logic |
| `risk-officer` | `config/risk_levels.yaml`, drawdown budgets, exports | Loosen a limit without the owner's written approval |

Handoff for any new strategy: `quant-researcher` (or `ml-researcher`) → `backtest-auditor` → `risk-officer` → paper model account → owner → export.

AGENTS.md puts role files in `.claude/agents/`. They are not in this repo.

## Troubleshooting

Status: available now (this repo). Most rows apply once the starter code is in.

| Problem | Cause | Fix |
|---|---|---|
| `nt.__version__` starts with `1.` | A plain `nautilus_trader` install resolves to the old 1.x line | Pin the exact v2 version: `uv add "nautilus_trader[visualization]==2.0.0rc9"` |
| Tutorial code doesn't match the API | The published tutorials use the old v1 API | Read `python/examples/` and the type stubs in the reference clone at `v2.0.0rc9` |
| mutmut crashes when `also_copy` names `tests/conftest.py` | `also_copy` must name a directory; `mutants/tests/` doesn't exist yet | Use `also_copy = ["tests"]` |
| Many mutants marked "no tests" | mutmut mutates all of `lab/` even when `paths_to_mutate` names one area | Ignore them, or run one area at a time (check `uv run mutmut run --help` for name filters) |
| Mutation results look stale after a config change | The old `mutants/` folder is still there | Delete `mutants/` between configuration changes |
| mutmut warns that `paths_to_mutate` or `tests_dir` is deprecated | mutmut 3.8 deprecates both names in favour of `source_paths` and `pytest_add_cli_args_test_selection` | The old names, which TESTING.md uses, still work. The warning is harmless |
| A rerun of a search gives different numbers | Parallel Optuna isn't bit-reproducible | Re-run logged parameters (exact). Run important searches twice with different seeds; a large difference flags a fragile strategy |
| A test fails on a `RuntimeWarning` from `lab/` | By design: `filterwarnings = ["error::RuntimeWarning:lab.*"]` | Fix the divide-by-zero in `lab/`. Keep the filter |
| An Optuna search inside a test fails or isn't reproducible | Tests need module-level objectives and one worker | Make the objective a module-level function; use `n_workers=1` |
| AGENTS.md links to `research-methods.md` are broken | It isn't in this repo yet | Ask the owner for it |
| A dashboard section is empty | Its input file is missing | Follow the hint on the page, or see [Inputs](#inputs) |
| The dashboard shows an integrity warning | An audit's `verdict` is `PASS` but its gate flags don't make READY FOR PAPER | Fix the audit, then its JSON. Never edit flags to match the verdict |
