# TESTING.md — Strategy Lab

How we test the lab, what's already done, and the exact work left. The coding agent
runs everything in this file. The person who wrote it did not run the final steps; the
agent is the one who executes, verifies and reports numbers.

**Why this matters.** The search, validation and model code decides which strategies
get real money. A bug here doesn't crash; it produces a confident wrong answer (a lucky
strategy that looks skilled, a backtest that quietly uses tomorrow's price). Tests are
how we know the numbers in an audit report mean what they say.

---

## 1. Rules for the agent

1. **Triage every failure before touching anything.** Decide: is the *code* wrong or is
   the *test* wrong? Write the answer in the bug log (section 4) either way.
2. **Never weaken a test to make it pass** (looser tolerance, narrower input range,
   deleting an assertion) without a written reason in the bug log. "It was flaky" is
   not a reason; find out why.
3. **A failing example becomes a permanent regression test.** When hypothesis finds a
   case, add it with `@example(...)` above the `@given` so it runs every time.
4. **Don't change validation thresholds** (`lab/search/report.py: gates`) or anything in
   `config/` to make tests pass. Those belong to the owner.
5. **Keep `filterwarnings = ["error::RuntimeWarning:lab.*"]`** in `pyproject.toml`. A
   divide-by-zero inside `lab/` is a bug, not noise.
6. **Seeds everywhere.** Any test using randomness passes a fixed seed. Searches in tests
   use `n_workers=1` (parallel Optuna is not bit-reproducible).
7. **Report with numbers** at the end (section 9 has the format).

---

## 2. Setup

```bash
uv sync                      # installs the dev group too: pytest, pytest-cov, pytest-xdist, hypothesis, mutmut, ruff
uv run python -c "import hypothesis, xdist, pytest_cov, mutmut; print('ok')"
```

Add these to `.gitignore` if missing: `.hypothesis/`, `mutants/`, `.coverage`, `htmlcov/`.

### Profiles and markers

| Setting | Meaning |
|---|---|
| `HYPOTHESIS_PROFILE=fast` (default) | 40 random cases per property. Every normal run. |
| `HYPOTHESIS_PROFILE=deep` | 500 cases per property. Before merging any change to `lab/`. |
| `@pytest.mark.slow` | Statistical calibration (thousands of simulated strategies). Skip with `-m "not slow"`. |

Profiles are registered in `tests/conftest.py`, which also provides the shared fixtures
`market` (synthetic 1500-day BTC + ETH, seed 21), `btc`, `features`, and the helper
`make_bars(close_path)` for hand-built price scenarios.

### Test tiers

| Tier | When | Command | Time (4 cores) |
|---|---|---|---|
| Quick | Every change | `uv run pytest -m "not slow" -n auto` | ~1.5 min |
| Full | Before merging | `uv run pytest -n auto --cov --cov-branch` | ~35 min at `-n 3` (2111 s on 2026-11-23; was ~2 min before the trend-steady tests) |
| Deep | Before merging changes to `lab/` | `HYPOTHESIS_PROFILE=deep uv run pytest -m "not slow" -n auto` | ~11 min at `-n 3` (667 s on 2026-11-23) |
| Mutation | Before each audit, and nightly once CI exists | `uv run mutmut run` (section 6) | ~10 min per area |

---

## 3. What exists today

Last full run (2026-11-25, `4038022`: the measured `config/costs.yaml`, the swap-cost probe `lab/data/swap_costs.py` and its 88 tests, the Nautilus sell fix #62, and the test fixes #63 and #64): **2500 tests passed, 100% branch coverage of `lab/`** (6751 statements, 1916 branches), in 1600 s at `-n 4`. On `11ebbb3` (the fix #62, before the cost change) the same 2500 passed, and the Nautilus tests and contract cases 230 passed at the deep profile. Earlier runs, and the full description of every test file: [docs/testing-history.md](docs/testing-history.md). `tests/test_dashboard.py` (86 tests) checks the
results dashboard, not `lab/`, and runs on its own. Tests per file in brackets.

| File | What it proves (full text in the history file) |
|---|---|
| `contract/test_backtest_contract.py` (415) | The backtest contract for every runner (9 reference + 9 Nautilus entries): no look-ahead, per-bar accounting, fills at the next open, costs, trade log, bounds, determinism, bad inputs refused |
| `test_nautilus.py` (32) | Nautilus runner and DEX fee model: parity with the reference to 1e-9 (drawn paths, synthetic market, catalog), the fee model by hand, documented differences (`MIN_LEG`, 12 decimals), refusals, a 2-worker search |
| `test_nautilus_portfolio.py` (30) | Multi-asset Nautilus runner (`lab/runner/nautilus_portfolio.py`, milestone 3): parity with `portfolio.py` to 1e-9 (drawn panels for `rebalance` and `random_rebalance` at 3 cost models; synthetic market at 1x and 2x; `hold_mix`; `trend_backtest` with and without the stop), tamper-the-future, accounting against `unit_book`, the documented differences of #65 by hand, full sells of either coin to exactly 0, refusals, a 2-worker search |
| `test_tracking.py` (7) | MLflow logging of search studies: one run per finished trial with params, metrics and context tags; idempotent; CLI |
| `test_reference_rules.py` (104) | Reference rules on hand-built paths: `scheduled`, dip-buy entries, stops and holds, vol-target sizing, benchmarks |
| `test_costs.py` (83) | The DEX cost model: slippage by hand, gas, stress, YAML loading (the measured file pinned; `Costs()` is the fixed test model, #63) |
| `test_swap_costs.py` (88) | The read-only swap-cost probe `lab/data/swap_costs.py`: allow-listed endpoints only, the key never logged, no network in tests |
| `test_stats_props.py` (53), `test_stats_exact.py` (151) | Sharpe, PSR, expected max Sharpe, DSR, effective trials, PBO: properties and every 5.3 known answer |
| `test_splits_props.py` (11), `test_splits_exact.py` (55) | Walk-forward and CPCV: brute-force match, exact purge and embargo, folds by hand |
| `test_montecarlo_props.py` (28), `test_montecarlo_exact.py` (70) | Drawdowns, trade shuffle and bootstrap, block bootstrap, degraded execution |
| `test_calibration.py` (12, slow) | False-positive rates and power under the null (PSR, DSR, PBO, expected max Sharpe) |
| `test_features_leakage.py` (54) | Look-ahead, present-bar reaction, hand values for all 15 features, live/batch parity bit for bit |
| `test_labels_props.py` (49) | Labels by hand over exactly their future window; baselines use only the past |
| `test_train_props.py` (14), `test_models.py` (5), `test_artifacts.py` (7) | Model metrics, CPCV on identical rows, the walk-forward horizon purge; end to end; artifacts round-trip, tamper refused, the saved vol model is the validated one |
| `test_search.py` (3), `test_search_props.py` (20) | Objective, failed trials logged, resume, stable region, fold decisions blind to their test block, report and gates |
| `test_loaders.py` (78), `test_synthetic.py` (20), `test_config.py` (6) | Kraken and Binance loaders; the synthetic generator; split windows by close time |
| `test_futures.py` (18), `test_external.py` (23), `test_positioning_build.py` (18) | Binance futures positioning data: parsing, point in time, download and build |
| `test_dips.py` (82) | The dip-timing study's computations, event purge and test-window guard |
| `test_portfolio.py` (157), `test_panel.py` (60) | Multi-asset rebalancer (no look-ahead, accounting against an independent unit book, refusals, `risk_limits` from the real file); the BTC + ETH panel (test-window guard, alignment, point in time) |
| `test_steady.py` (66), `test_steady_scripts.py` (73) | rebalance-steady harness and study scripts: guards, dry runs, every reported number recomputed, freeze and look |
| `test_holdmix.py` (159), `test_holdmix_run.py` (67) | The hold-this-mix tool, hold-mix-cap's decision rules and study script |
| `test_trend.py` (107, 2 slow), `test_trend_scripts.py` (96) | trend-steady rule, executor, stop variant, luck controls and study scripts |

---

## 4. Bug log

Bugs the tests found, all fixed in the code you have:

| # | Where | Bug | Fix |
|---|---|---|---|
| 1 | `stats.sharpe`, PBO | Sharpe of a near-constant series exploded to ~8e15 | Treat flat series as Sharpe 0 (`_is_flat`); **see 5.2, the tolerance itself is still wrong** |
| 2 | `stats.probabilistic_sharpe_ratio` | Returned NaN on all-zero returns | Flat series return 0 |
| 3 | `train.vol_metrics`, `regression_metrics` | A constant forecaster (the "flat" baseline) caused divide-by-zero warnings; empty input warned | `_corr` returns NaN for constant input; empty input returns NaN metrics |
| 4 | `reference.py` | Fractional positions were treated as rebalanced back to target **every day for free**, so daily P&L didn't match the trade log | Positions are held as coin units between trades; weights drift with price; turnover is target minus drifted weight; only trading bars pay costs |
| 5 | `reference.dip_buy` | An exit could re-enter on the same bar: the trade log charged two fees for a trade that never happened | No re-entry on the exit bar |
| 6 | `reference.constant_mix` | The 50/50 benchmark never paid to rebalance, which flattered it | Rebalances every bar and pays for it |
| 7 | `study.load_trial_returns` | A worker killed after writing its returns file but before Optuna recorded the trial left an orphan file that **counted as a trial in DSR and PBO** | Only trials Optuna marked COMPLETE are loaded |
| 8 | `stats._is_flat` (5.2A; starter) | The absolute floor `_ABS_SD_TOL = 1e-12` made Sharpe depend on units: `sharpe([1e-12, 0, 0]) = 0` but `sharpe(2r) = 0.577` | Osprey's relative flatness on unit-scaled data; 0.7319 for every scale 1e-300..1e300 (merge: osprey's stats.py kept) |
| 9 | `test_each_feature_reacts_to_the_present_bar` (5.2B; starter **test** bug) | Lowering only the close left high/low unchanged on a wide-range day, so `park_vol_20` correctly did not move (cut=362) | Osprey's test always widens the range; `@example(cut=362)` and `(cut=146)` kept. They were found on the starter's generator; on osprey's they are ordinary cuts |
| 10 | `stats` PBO, expected max Sharpe, PSR (starter) | PBO broke in-sample ties with `argmax` (PBO depended on column order); expected max Sharpe went negative for 1 < N ≤ 1.28 (DSR more lenient than PSR); the PSR `var_term` guard **does** fire in floating point and returned 0 above the benchmark; `column_sharpes` gave NaN plus warnings for < 2 rows; `effective_trials` raised `LinAlgError` on near-flat columns | Osprey's stats.py: ties score the worst OOS candidate, EMS floored at 0, guard handled and tested, < 2 rows give 0, flat columns dropped before the eigen-decomposition |
| 11 | `splits.walk_forward`, `montecarlo` (starter) | `step=-1` looped forever and `step=0` was silently replaced; `block_bootstrap_drawdowns([])` raised `IndexError`; `degrade_execution` drew an unbounded Exponential cost, so a period could lose more than 100% | Osprey's modules: every argument validated; empty input gives zero drawdowns; cost drawn from Uniform(0, 2) × bps, multiplicative, never below -100% |
| 12 | `reference.py` timing, hard rule 4 (starter) | A decision at close t filled at close t, the price the signal read; Nautilus fills at the next open | Osprey's reference fills at the open of t+1 (contract suite, `tests/contract/`) |
| 13 | `reference.py` accounting (starter) | With costs on, the trade log differed from the portfolio by up to 7.58e-4 per trip at 16 bps, 2.35e-3 at 50 bps (fees on the entry notional); buy-and-hold logged the gross price change; fees were paid from negative cash (coin worth 1.0016 of the portfolio at position 1.0) | Osprey's engine: trade log equals the portfolio with costs on, fees cut the coin units, spot only |
| 14 | `reference.py` inputs and costs (starter) | No bar or param validation (NaN close, reversed index, typo `stop_loss` all ran); gas as bps of a fixed $1000 notional times turnover; slippage clamped above the table; `Costs()` ignored `config/costs.yaml` | Osprey: strict validation; per-fill gas in USD, size-based slippage on the compounding portfolio, `Costs.from_yaml()` |
| 15 | `loaders.py` (starter) | Mixed ms/µs rows in one file put the ms rows in 1970; NaN prices, high < low, close > high and negative volume loaded silently; `resample` kept partial buckets; index was bar OPEN time (AGENTS.md says close time) | Osprey's loaders: per-value unit detection, bad ticks dropped and counted, complete buckets only, close-time index |
| 16 | `online.FeatureBuffer` (starter) | Crashed on Nautilus `Price`/`Quantity` (the AGENTS.md `on_bar` example); accepted out-of-order and invalid bars; live features matched batch only to rtol 1e-9 | Osprey's FeatureBuffer: `float()` inputs, validation, bit-exact parity on every bar |
| 17 | `artifact.train_final` + `online.ModelPredictor`, vol (starter) | **The deployed vol model was not the validated one**: CPCV and walk-forward scored the EWMA-anchored correction, but `train_final` fit log(vol) from scratch and the predictor returned `exp(pred)` (the variant that lost to EWMA). The starter test pinned `exp(model.predict)` | `train.AnchoredVolModel` used by `_fit_predict`, `train_final` and `ModelPredictor`; `test_saved_vol_model_is_the_model_that_was_validated`; the old assertion changed (it pinned the bug) |
| 18 | `loaders._read_fields` (osprey) | `on_bad_lines="skip"` took the first line's width: a first line without the trades field silently dropped every later full line, and over-wide lines vanished uncounted; pandas also shifts columns when the FIRST line is over-wide | Lines read whole and split per line: short lines padded, over-wide lines dropped and counted in `dropped_bad`; regression tests |
| 19 | `lab/config.splits` (osprey) | Documented selection `start <= ts < end + 1 day` is off by one bar under close-time labels (the last train day fell into validate) | `start < ts <= end + 1 day`, as `config.in_window`; `tests/test_config.py` |
| 20 | `search.stability.stable_region` (starter) | When k ≥ the number of trials every neighbourhood mean is the same number, and the pick came down to summation-order rounding (a last-bit stats change moved the chosen trial) | Neighbourhood scores sorted before averaging; ties go to the best own score; property test |
| 21 | merge integration (osprey runner + starter `lab/search`) | Osprey's runner keeps arrays and a fill frame in `attrs`; pandas copies them onto `res["ret"]`, so the starter's `study.py` `to_parquet` failed every trial and `walkforward`/demo `pd.concat` raised | The search layer strips `attrs` before saving or concatenating (runner-agnostic: the Nautilus runner needs it too) |
| 22 | `reference.dip_buy` (osprey) + demo units | Osprey's `dip_buy` silently ignored a `pred_vol` column, and osprey's vol forecasts are per bar while `vol_target` is annualised: the demo's vol-targeted variant would never have used the model | `vol_col` param (forecast at the signal close; NaN/inf fall back to realised vol; ≤ 0 means no entry); demo annualises the forecast; starter's sizing and model-column look-ahead tests ported |
| 23 | `search.report.overfitting_report` (starter) | With no study holding 2+ completed trials, the list of trial Sharpes was empty and DSR was computed with a trial-Sharpe variance of 0: not deflated at all, but reported as DSR | DSR is NaN, so its gate fails (missing numbers fail, never pass); asserted in `test_report_with_too_few_trials_has_no_pbo_and_fails_the_gate` |
| 24 | `features.py`, `labels.py`, `baselines.py` (starter) | Every volatility annualised with √365 whatever the bar size (off by √24 on the hourly bars of milestone 1; latent); flat prices gave NaN `efficiency_20` and `vol_ratio_5_60` after warm-up, flat or zero volume a NaN `volume_z_20`, a flat forward window a NaN regime label; `forward_realized_vol(h=1)` was silently all NaN; the EWMA baseline and the EWMA feature (the model's anchor) were two different estimators | Osprey's modules: per-bar units (annualise where an annual number such as `vol_target` is used), finite values on flat input, `h=1` rejected, the EWMA baseline equals the `ewma_vol_20` feature exactly |
| 25 | `synthetic.synthetic_market` (starter, minor) | No input validation: fewer than 2 days returned a 1-row frame that `validate_bars` rejects | Osprey's generator validates its inputs (`test_too_few_days_raise`) |
| 26 | `test_search_props.py::test_fold_decisions_cannot_see_their_test_block` (merge; **test** bug) | On osprey's runner (fills at the next open) the close-only tamper no longer moved the chosen parameters, so a walk-forward that searched on train + test block passed. The same break fails the test on the starter's code | The test also requires every logged trial of the fold's study (params, score, Sharpe, trade count) to be identical; that break and a 1-bar leak now fail it |
| 27 | `test_train_props.py::test_walk_forward_predictions_cannot_see_future_labels` (starter; **test** bug, also in `test_models.py::test_walk_forward_predict_never_uses_future_labels`) | Labels were corrupted by row (`>= cut`), not by when they become known, so a walk-forward with no horizon purge (`usable = train_pos < block_start`) or an off-by-one purge (`< block_start - horizon + 1`) passed every leak test | The test corrupts every label not fully known at `cut` (rows from `cut - horizon`); both breaks fail it. `test_models.py`'s copy is unchanged (4a.8) |
| 28 | `data/build.py` `--report-dir ''` (milestone 1) | Documented as "skip the report", but `Path('')` is the current directory, so a test run wrote a stray report into the repo root | Kept as a string and turned into a path only when non-empty; regression test runs `main` in an empty directory and asserts nothing is written |
| 29 | `data/loaders.load_binance_klines` (found by the real data) | Real Binance hourly files hold 55 rows per symbol that are not whole grid bars (11 cut short by maintenance, 43 shifted by 28m14.789s on 2018-02-09..11, 1 that closes before it opens on 2020-12-21); labelled open + actual length they put off-grid times into a 1-HOUR bar type | Grid mode `load_binance_klines(path, interval=...)`: on-grid opens labelled open + interval, off-grid bars dropped and counted, impossible lengths are bad rows; default mode unchanged |
| 30 | `data/sources.MultiPartHTTPReader` (milestone 1) | A range answer without an ETag was accepted even when the HEAD had one, so a Kraken part replaced mid-read could pass | Missing or different ETag raises `DownloadError`; members re-extracted under the strict check are byte-identical |
| 31 | `data/quality.cross_check` (milestone 1) | `pd.concat` on DatetimeIndex without `sort=True` warned that a future pandas would stop sorting the joined index | `sort=True` |
| 32 | `data/report.render_report` (milestone 1) | The report's `Command:` line left out `--tolerance`, so a build at another tolerance printed a command that rebuilds at 1% | Always prints `--tolerance` with the exact float; test parses the printed command and checks it reproduces the build options |
| 33 | `data/report.write_report` (positioning data) | Reports were named by date only, so a second snapshot built the same day (here: adding positioning data to `b08377c310126e3f`) would have overwritten the committed report of the first | `report_path`: a file whose first line names another snapshot is kept, and the new report gets `-<snapshot id>`; `test_a_second_snapshot_on_the_same_day_keeps_the_first_report` |
| 34 | `runner/portfolio._simulate` (rebalance-steady, new code) | With all-cash targets (w_btc = w_eth = 0) nothing fills, and building `trade_returns` crashed (`zip(..., strict=True)` over lists of different lengths) | No fill gives an empty `trade_returns` and `n_trades` 0; `test_edge_parameters_are_accepted` |
| 35 | `test_portfolio.py`, accounting against the unit book (**test** bug) | Leg USD sizes and units were compared at rtol 1e-12 of the leg itself, but a leg's size is abs(target − drifted) × V_open, so its round-off is a fraction of the book: a 0.39 USD leg (3.9e-5 of the book; `random_rebalance` w_btc 0.25, 2 rebalances, seed 253) differed by 2.1e-12 of itself, 8.2e-17 of the book | Leg USD, cost and units × price compared as fractions of that fill's V_open at atol 1e-12, the standard of the per-bar identities; `@example` |
| 36 | `test_portfolio.py::unit_book` (**test** bug) | The independent book decided on its own which legs trade. With an ETH target 1 ulp under 1 and an unconditional `random_rebalance` order on flat prices, the engine trades a 1.1e-12 USD leg (1.1e-16 of the book) and pays 0.10 USD gas for it (9.9e-6 of the book): a round-off judgement two computations cannot repeat bit for bit | `unit_book` takes the traded legs from the engine's fill log, and the test asserts every leg it did not trade is within 1e-12 of the book of its target; `@example`. Gas on a round-off leg is documented engine behaviour (as in `reference._simulate`), reachable only on flat prices or targets with no room to drift |
| 37 | `test_portfolio.py::test_flat_rate_cost_is_turnover_times_rate` (**test** bug; the audit's deep run) | Hypothesis drew a subnormal weight (w_eth = 2.225073858507e-311, k = 0.5): the bar-1 cost at 0.5× the rate is 2.2250738583e-314 against 0.5 × cost = 2.225073859e-314, one subnormal step (5e-324) apart, 2.2e-10 relative against rtol 1e-14. Below the smallest normal double (2.2e-308) a float has no relative precision. The case was saved in `.hypothesis/`, so the fast tier failed too | An absolute floor `np.finfo(float).tiny` (2.2e-308 of the book) next to the unchanged relative tolerances. **Reason (rule 2):** relative precision does not exist below it, and the floor only matters for costs under 2.2e-294 of the book (where rtol × cost < 2.2e-308), while the smallest real cost, one leg's gas, is 1e-5 of a 10,000 USD book. The input range is unchanged (subnormal weights are still drawn). Three `@example`s: the audit's case and two from the code review |
| 38 | `test_portfolio.py`, accounting test, side of each leg (**test** bug; code review, deep profile) | BTC target 1 ulp under 1 with flat ETH: the rebalance at bar 17 trades a BTC leg of 1.2e-12 USD (1.1e-16 of the book) that the engine logs as `buy` (from its drifted weight) and the unit book calls `sell` (from units): the side of a round-off leg is round-off | Sides compared on every leg larger than 1e-12 of the book; sizes, costs and weights still on every leg; `@example` |
| 39 | `tests/test_portfolio.py` (test gaps; code-review hand breaks) | Two deliberate breaks of `portfolio.py` passed every test: the target sum accepted up to 1 + 1e-9 (a cash target below 0), and a fill costing exactly 100% of the book accepted (`k > 1` for `k >= 1`). Three more died only on hypothesis-drawn cases: the band judged on weights drifted to the next open, check closes counted from the last order instead of close 0, and `LIMIT_TOL = 0` | `test_targets_above_one_by_round_off_are_refused`, `test_a_fill_costing_exactly_the_whole_book_raises`, and the hand-built `test_the_band_is_judged_at_the_close_not_at_the_next_open`, `test_check_closes_stay_on_the_grid_from_close_0_after_a_forced_order`, `test_targets_on_a_limit_up_to_round_off_are_accepted`. Each break now fails (the last three on their hand-built test alone). The code was right |
| 40 | `tests/test_panel.py` (test gaps; code-review hand breaks) | Two deliberate breaks of `load_panel` passed every test: the train and validate windows read from the default config instead of `config_dir` (only the cut was tested there), and `dropped`, `rows` and `missing` computed before the window filter (a bar outside the windows listed as dropped) | `test_the_windows_follow_config_dir`, `test_a_bar_outside_the_windows_is_not_listed_as_dropped`; each break now fails its test. The code was right |
| 41 | rebalance-steady plan and `lab/`: the Steady limits (risk-officer review) | The plan's adapter typed `min_cash` 0.20 and `max_coin` 0.60, and nothing in `lab/` read `config/risk_levels.yaml`: a change to the file would not have reached the study, and the drawdown budget (`TBD`) had no defined reading | `portfolio.risk_limits(level, config_dir)`: `min_cash_pct` and `max_coin_pct` as fractions, from the file's bytes with their SHA-256; the coin list must be exactly BTC, ETH and USDC; `max_drawdown_budget_pct` is a fraction only when it is a number in (0, 100], anything else is MISSING (`None`), so a gate that needs it fails. Tested with files in `tmp_path`. The adapter (not built yet) must pass these values, never literals |
| 42 | `portfolio.rebalance`: targets on a limit (risk-officer review) | Targets exactly on the Steady limits were accepted, and the plan's box reached them (s = 0.80, s·f = 0.60). The engine shares a fill's cost pro rata, so it holds exactly the targets after a fill; a live account books each fee out of its own swap, so the same fill would leave it past the limit and the rule would trade again at the next close | `headroom` param: targets must stay `headroom` inside every set limit (`ValueError` otherwise); breaches are still judged at the limits, so accepted targets run bit for bit as without it. `check_targets` applies the same check to a search box or a plateau step before any run. The headroom value (0.02 proposed) is the plan's to pin |
| 43 | `tests/test_steady.py` (test gaps) | Three hand breaks of `steady.py` passed every test (half-up rounding, regime bounds, E1 ties) | Boundary tests added; the code was right (full entry: history file) |
| 44 | rebalance-steady scripts | Failed trials carried no error text; three script breaks passed; two test bugs | `study.FailureLog`; tests added (full entry: history file) |
| 45 | `test_steady.py`, `test_steady_scripts.py` (test gaps) | E1/E2 threshold breaks and `overshoot` ignoring `max_coin` passed | Boundary tests; the code was right (full entry: history file) |
| 46 | rebalance-steady scripts (code bugs) | Dry runs could write into the real results folder; real runs accepted other folders; freeze and look guard gaps | `check_out_dir`, `check_real_paths`, triage, FROZEN.json checks (PLAN.md A5) (full entry: history file) |
| 47 | `test_steady_scripts.py` (test gaps) | Reported numbers were never recomputed from their inputs; 62 wiring breaks passed | Recompute tests; `study.gate_table` (full entry: history file) |
| 48 | `test_steady_scripts.py` (test bug) | Tests depended on the repo's recorded RUNLOG | `real_folders` stand-ins (full entry: history file) |
| 49 | `test_portfolio.py` (test bug) | A drawn ruined book reached the engine's documented refusal | `unit_book` refuses too; `run_checked` (full entry: history file) |
| 50 | `lab/runner/holdmix.py` and tests | Test bugs while building; one hand break passed | Tests fixed; the code was right (full entry: history file) |
| 51 | `research/hold-mix-cap/run.py` | A0 timing error escaped as a traceback; test bugs; a window break passed | Refusal added; tests (full entry: history file) |
| 52 | hold-mix-cap tests (test gaps) | Eleven hand breaks passed (fee span, min leg, ties, float `wait_days`, run.py stops) | 13 tests; the code was right (full entry: history file) |
| 53 | hold-mix-cap `run.py`, `holdmix.py` (code gaps) | Logged runs lost on a stop; boom-year check missing; rule D label; parity on metric errors; tz-naive guard | Blocks logged as they return; PLAN.md A5, A6; tests (full entry: history file) |
| 54 | `test_holdmix.py` (test bug) | A subnormal target broke the fee recovery check | The test accepts the fee check's refusal there (full entry: history file) |
| 55 | steady and hold-mix script tests (test bugs) | Tests depended on the real file's TBD budget | `edit_steady_entry`, `set_steady_budget` (full entry: history file) |
| 56 | `lab/runner/trend.py` and tests | `rolling_count` error type; missing H0 slice; test bugs; ten test gaps | Fixed; 113 of 114 hand breaks caught (full entry: history file) |
| 57 | trend-steady scripts | Four code bugs found by dry runs; the validate-check reading; decisions read inline | Fixed; decisions moved into pure rules; 78 of 82 breaks caught (full entry: history file) |
| 58 | trend-steady scripts (code review) | Stop rule 18 could be bypassed; no order-of-work guard; test gaps | `combine_reported`, `prior_amendments`; tests (full entry: history file) |
| 59 | `test_trend_scripts.py` (test bug) | Stand-in plans held duplicate A1/A0 rows | `without_prior_rows` (full entry: history file) |
| 60 | trend-steady `run_train.py` `episodes` | Whipsaw total double-counted shared orders | Each order counted once (full entry: history file) |
| 61 | `lab/runner/nautilus.py` (milestone 2, new code; failures while building it, against the contract suite; synthetic data only) | Each failure was triaged before any change; all were in the new runner, none in the tests or the reference. (a) **Negative cash on a full buy:** a target of 1 sized in floats spent up to 1.5e-11 USD more than the cash once Nautilus rounded the price and the fee to 12 decimals, and the cash account (no borrowing) refused the fill: 34 contract cases. (b) **Round-off legs:** after a fill the book's weight is off its target by fixed-point noise (~1e-14), so `constant_mix` with band 0 sent that difference back as an order on the next flat bar and paid 0.10 USD of gas for it: extra fills, and cost and turnover columns that broke `test_costs_scale_each_bar_return` and `validate_result` (a cost on a bar with zero turnover). (c) **Cost by subtraction:** `cost = 1 - V_after / V_open` gave 1e-15 instead of exactly 0 at zero cost. (d) **A knife-edge decision:** the same rule decided differently with and without costs when the noise put the weight exactly at, or 6e-15 under, its target | (a) Buys are capped at what the cash can pay in the engine's own fixed-point arithmetic (`_affordable`: the price and fee as Nautilus rounds them, one 1e-12 step held back), quantities rounded down. (b) A leg of at most `MIN_LEG` = 1e-9 of the book is not sent: the documented difference from the reference, which trades any leg > 0 in floats (#36); `test_round_off_legs_are_not_traded`. Mostly reachable on flat prices; on real data it also happens rarely when a moving price returns to within ~1e-9 of the last fill's weight: once in 1,750 hourly 50/50 rebalances of BTC 2017-2022 (2020-04-09 19:00, a leg of 3.3e-16 of the book on which the reference paid 0.10 USD of gas), found by `scripts/nautilus_parity_real.py`, which checks that the books then differ by that gas alone (within its later-cost bound). (c) `cost = commission / V_open`, from the commission Nautilus booked. (d) The rule sees the weight to the book's 12 decimals; `test_the_rule_sees_the_weight_to_twelve_decimals`. Then all 198 Nautilus contract cases pass at the fast and the deep profile, and the parity test holds to 1e-9 (observed: about 1e-14). **Nothing loosened (rule 2):** the contract's tests and tolerances are unchanged; the Nautilus entries use the runner's written-down `TOL` = 1e-9, which the conftest docstring anticipated for a fixed-precision engine. The parity test draws moving prices only, for the reason in (b). No `lab/` file other than the two new ones changed, and no study's config hash covers them. Validate-window looks used: 0 |
| 62 | `lab/runner/nautilus.py` (found by the quick tier during the swap-cost work; synthetic data only) | A sell was sized from the coin balance as a float. `Quantity(4451.041648603093, 12)` rounds to 4451.041648603094, one 1e-12 step above the account's 4451.041648603093 units, so Nautilus's risk engine denied the full sell (`CUMULATIVE_NOTIONAL_EXCEEDS_FREE_BALANCE`) and the run stopped. The sell-side twin of #61 (a). Hypothesis case: `ref_dip_buy_stop_hold_vol`, n 262, seed 37975, vol 0.1, gap 0.03, `Costs()` | Sells are capped at the exact balance read from the account as a decimal (a full sell sells exactly it). `@example(n=262, seed=37975, vol=0.1, gap=0.03, costs=Costs())` on `test_nautilus_equals_the_reference_on_every_contract_rule`; it fails before the fix. Nothing loosened (rule 2). Validate-window looks used: 0 |
| 63 | `tests/test_costs.py::test_yaml_loading_equals_the_placeholders` (an intended change, not a bug; the owner approved the measured costs of `reports/costs/2026-11-25.md` for `config/costs.yaml`, 2026-11-25) | The test pinned the placeholders in the file and `Costs.from_yaml() == Costs()`, with the note "when measured values replace them, update both" | Renamed `test_yaml_loading_equals_the_measured_costs`: it pins the measured values (pool 0, aggregator 15, slippage 30 / 54 / 26 / 5 bps at 100 / 1,000 / 10,000 / 50,000 USD, gas 0.15). The dataclass defaults were **not** updated, against that note. **Reason (rule 2):** no code outside `tests/` calls `Costs()`; every runner reads the file through `Costs.from_yaml()`. About 110 test uses rely on `Costs()` as a fixed cost model, some with hand-computed expectations (#49's refusal bound reads its 0.10 USD of gas), so the defaults stay the placeholders as a fixed test cost model. The test now pins both: `from_yaml()` differs from `Costs()`, and `Costs()` equals the placeholders. Nothing else loosened. Validate-window looks used: 0 |
| 64 | `tests/test_portfolio.py`, `test_holdmix_run.py`, `test_steady_scripts.py`, `test_trend_scripts.py` (**test** bugs; the full tier on `a9105c8`, the measured `config/costs.yaml`) | 7 failed, 2493 passed. The same class as #48, #55 and #59: tests that depended on the values the config file held. (a) Six tests told the 2x cost setting from 1x by `pool_fee_bps > 5` (or `== 5`, or `>` the file's pool fee). The measured pool fee is 0, and 2 x 0 = 0, so their injected faults never fired (`DID NOT RAISE Stop`, 0 stops or 0 failed runs where 3 or 12 were expected). (b) `test_first_buy_fills_at_the_open_of_bar_1_and_each_leg_pays_its_own_size` computed slippage by hand from the old file's table while reading the file. (c) Passed for the wrong reason: both `test_real_runs_use_the_pinned_folders_only` made a "zero-fee copy" with `replace("pool_fee_bps: 5", ...)`, which no longer changed anything (the copy was refused for its folder alone) | **Tests fixed; no code changed.** (a) The 2x setting is told by gas: `costs.gas_usd_per_trade >` (or `==`) `Costs.from_yaml().gas_usd_per_trade` (gas is doubled at 2x and is above 0). (b) The test uses the fixed test cost model `Costs()` (#63), so its hand computation is unchanged. (c) The copy sets `aggregator_fee_bps: 0` and asserts the file changed. Each of the 7 failed on `a9105c8` and passes now, with (c)'s two. **Nothing narrowed (rule 2):** no assertion, input range or tolerance changed. Validate-window looks used: 0 |
| 65 | `lab/runner/nautilus_portfolio.py` and `lab/costs/fees.py` (milestone 3, new code; failures while building, against `portfolio.py`; synthetic data) | Each failure triaged before any change; all in the new runner or the new tests. (a) **Code, idle coin:** after a fill on flat prices portfolio.py's untouched coin is exactly at target (traded 0) and is re-cut by its share of the fees with no gas; Nautilus saw ~1e-14 of fixed-point noise and sent it as a leg paying gas (cost 2x). (b) **Test draw:** hypothesis drew a target of 2.6e-126: portfolio.py buys a 2.6e-122 USD leg and pays 0.10 USD gas; Nautilus cannot (round-off leg). (c) **Code, negative cash:** with targets summing to 1 the fees come out of the coins; sells rounded down to 1e-12 units lost up to 2.8e-8 USD, and a fee-dominated sell (2.17 USD leg, 2.51 USD fee) sent before a net-positive one overdrew the cash account (Nautilus refused the fill). (d) **Fill-less extra orders:** a book all in one coin with band 0: portfolio.py's weight is exactly 1 (x / x), Nautilus keeps leftover cash below one unit step, so the rule sees 0.999999999999 and orders; the order fills nothing. (e) Earlier, in the build: the module's `_simulate` restored to the wrapper (the original was not kept), balances read right after a submit are stale (fills land after the handler), so buys could not see the sells' cash; a test expectation (3 fills, not 2) and an empty fee frame of object dtype | (a) A leg of at most `MIN_LEG` inside a fill is a re-cut: a zero-commission order (`fees.RECUT_TAG`) that carries out portfolio.py's pro-rata fee sharing; a re-cut that is charged stops the run. (b) Documented, like #61: a round-off leg is never sent; the drawn targets are 0 or >= 0.001 (study grids start at 0.05), and `test_a_target_of_round_off_size_is_not_bought` pins the gap (the books differ by that gas, 0.75 in cash and 0.25 in BTC). (c) Sells rounded up (capped at the exact balance, #62) and sent in descending order of net proceeds; buys go at a second open quote 1 ns later, each capped at the cash left in fixed point; `test_a_full_buy_of_both_coins_never_overdraws_the_cash`. (d) Documented: parity requires every portfolio.py order to be Nautilus's and every extra Nautilus order to fill nothing; `test_a_book_all_in_one_coin_with_band_0_lists_orders_that_fill_nothing`. (e) Fixed. **Nothing loosened (rule 2):** `TOL` = 1e-9 and the contract unchanged; `test_nautilus.py`, the 198 Nautilus contract cases and `test_portfolio.py` pass. Real-data parity (`scripts/nautilus_portfolio_parity_real.py`, snapshot `6cfd6765129440e3`, Kraken and Binance, 1d and 1h, 1x and 2x, 3 settings): no disagreement, largest difference 1.0e-12. Validate-window looks used: 0 |
| 66 | `tests/test_nautilus_portfolio.py::test_nautilus_equals_portfolio_on_drawn_panels` (**test** gap; the whole-suite deep profile on `791cfc1`: 1 failed, 2515 passed) | Hypothesis drew `random_rebalance` with w_btc 0 and w_eth one ulp under 1 (a cash target of 1.1e-16) on moving prices: the book has no room to drift, so the rebalance's ETH leg is round-off (about 1e-12 USD). portfolio.py trades it and pays 0.10 USD of gas; this runner does not send it (`MIN_LEG`, the documented difference of #61 (b) and #65 (b)), so `n_trades` was 1 against 2. The draw already kept each coin target at 0 or at least 0.001 for this reason, but not the cash target | The draw keeps the cash target at 0 or at least 0.001 too, with the same written reason (rule 2: the documented difference, not a wrong number; the study grids' smallest non-zero cash target is far above 0.001). `test_a_cash_target_of_round_off_size_trades_only_round_off_legs` pins the case by hand: every bar before the skipped fill agrees to TOL, the skipped leg is at most `MIN_LEG` of the book, and after it the books differ by that fill's cost alone. No code changed. Validate-window looks used: 0 |

Findings that are not bugs (keep them in mind):

- **DSR is strict.** With 50 trials, a genuinely good strategy (true annual Sharpe 2.5)
  passes DSR ≥ 0.95 only ~46% of the time with 2.7 years of daily data, and > 80% with
  5.5 years. Short histories will reject some real edges. That's the price of not
  approving luck.
- ~~**The PSR `var_term <= 0` guard can never fire.**~~ Wrong in floating point (bug #10):
  `r = [0.022996598285221187, 0.012996598285221187, 0.012996598285221187]` gives
  `var_term = -4.4e-16`. Mathematically `var_term ≥ 0` because kurtosis ≥ skew² + 1, but the
  rounded moments can break it. Osprey removed the pragma and tests the case.
- **`volume_z_20` saturates on big spikes** (design, not a leak). A z-score whose 20-bar window
  includes the present bar can't exceed 19/√20 = 4.2485, so every spike that dominates its window
  looks the same (the starter's tolerance-based present-bar test caught tripling a 5.9e6× spike
  moving it by 4e-11). Z-scoring log volume, as the starter did, only slows the saturation. Kept as
  is and pinned by `test_volume_z_is_bounded_by_its_window`; excluding the present bar from the
  window's mean and spread would remove the bound. Decision for `ml-researcher`.
- **A dip of exactly X% does not trigger in floating point unless the ratio is exact** (design of `close / peak - 1 <= -X`, shared by `reference._dip_signal` and `dips.dip_trigger`): `90 / 100 - 1 == -0.09999999999999998 > -0.1`. Boundary tests use exactly representable cases (50/100 at X = 50%). Real prices are never exactly on the boundary, so no study number depends on it.
- **`train.make_model` LightGBM cannot split on small event datasets** (finding for the models owner, not a bug): with `min_child_samples=200`, a training set under about 400 rows gives at most one split per tree, and on the dip study's ~450-500 day rows per CPCV split the T5 LightGBM model was close to constant (out-of-sample AUC 0.4965 ± 0.0135; its entries matched buying at once in 56 of 80 events on every path). The defaults were tuned for thousands of daily rows; event-level models need their own (pre-registered) settings.
- **Binance futures metrics changed their timestamp convention on 2024-04-26** (data, not a code bug).
  Until 2024-04-25 a row's `create_time` T is the END of its 5-minute period (its taker ratio equals the
  kline period [T-5, T), its open-interest value / open interest equals the price at T); from 2024-04-26 it
  is the START (period [T, T+5), price at T+5), for BTCUSDT and ETHUSDT alike. Reading `create_time` as
  "known at" would leak 5 minutes in the newer files. `known_at = create_time + 5 min` covers both, and the
  build re-checks every day against 5-minute futures klines and stops if any day's data reach further.
  Do not shorten `futures.METRICS_LAG` without rerunning that check.
- **B4's book never changes a number** (rebalance-steady; found in the review of part 2). B4 buys once, at the open
  of t0, outside the kept rows, and never trades in them, so its kept returns do not depend on the book it starts
  from: a dry run with B4 started from 10,000 USD instead of S's book gave a byte-identical `summary.json` results
  block, `evaluations.parquet` and `oos.parquet`. B4-span is book-free for the same reason, and B5's `every = 1` is
  irrelevant with band 1.0. Only B3's book matters (its rebalances fill inside the kept rows). A test of B4's book
  therefore does not protect E2; the recompute of B4's kept returns and of the paired bootstrap does (#47).

**Consequence of fixes 4–6:** every number from the old demo is stale. Rerun it (5.5). The merge changes
them again: fills at the next open, the `config/costs.yaml` cost model and osprey's generator (#12–#14, #22).

---

## 4a. Merge with the starter code (2026-11-19)

Osprey (this repo) was built from these docs while the owner's tested starter code lived in
`unconstructed/strategy-lab` (159 tests, 99.77% branch coverage, with 5.2A, 5.2B, 5.3 and 5.6 still open). The
owner asked to compare the two, bring over what osprey was missing (`lab/search`, `lab/models/train.py` and
`artifact.py`, and their tests), keep whichever version of each file is better tested, and log the choices here.
Before anything was merged, four comparers (runner, validation, data, models) ran each side's own suite (fast,
deep, coverage), then each side's tests against the other side's code through shims that mostly mapped names and
signatures. Starter files were then copied byte for byte, and every later edit is listed in 4a.3. A last check
broke the merged code by hand to find guarantees the dropped tests had pinned and the kept ones didn't (4a.6).
The bugs found are #8–#27 in the bug log.

Sections 4a.1-4a.4 (which files were kept, tests kept and ported, every edit, where the merge departed from a comparer) are in the history file.

### 4a.5 The backtest contract

Kept: osprey's `lab/runner/interface.py`, pinned for every runner by `tests/contract/`.

| | Starter | Kept (osprey) |
|---|---|---|
| Rows | `bars.index[1:]` | exactly `bars.index`, with `ret[0] = 0` |
| Columns | `ret`, `position`, `turnover` | `ret`, `position`, `turnover`, `cost` |
| `attrs` | `trade_returns`; an open trade at the end is dropped | `trade_returns` (an open round trip marked to market) and `n_trades` (fills) |
| Execution | a decision at close t fills at close t | a decision at close t fills at the open of t+1 |
| `position` | weight held over the period | weight at the close of bar t, after the fill and the move through the bar |
| Accounting | additive: `ret = w·r − turnover·bps` | multiplicative, per bar. Fill: `1 + ret = (1 + w0·g)(1 − cost)(1 + w·h)`; no fill: `1 + ret = 1 + w0·r` (g: gap from the previous close to the open, h: open to close) |
| Trade log | equals the portfolio at zero cost only | equals the portfolio for every round trip, with costs on |
| Costs | flat bps; gas as bps of a fixed 1000 USD notional × turnover; slippage clamped above the table | `config/costs.yaml`: pool + aggregator + slippage on the actual USD trade size + gas in USD per fill; fees cut the coin units (no negative cash); a cost the portfolio can't pay raises |
| Inputs | not checked | `validate_bars` and strict params |

Why: hard rule 4 says fills happen no earlier than bar t+1, and the starter filled at the price the signal read.
NautilusTrader's bar execution fills at the next bar's open, so the milestone-2 parity test can be exact. A
trade log equal to the portfolio with costs on keeps the Monte Carlo trade shuffle and bootstrap honest, since
they read that log. The starter's search code only needs `BacktestFn`, `res["ret"]` and `attrs["trade_returns"]`,
and runs unchanged apart from stripping `attrs` (#21). Note that the minimum-trades count in the objective can be
one higher than before, because an open round trip now counts. `lab/runner/nautilus.py` (milestone 2) must pass
this suite; adding it is one entry in `RUNNERS`.

Sections 4a.6 (lost-guarantee check) and 4a.7 (verification) are in the history file.

### 4a.8 Still open after the merge

- 5.4: mutation testing of the runner, search, models and data areas is not started. The hand breaks in 4a.6
  show those areas have survivors.
- 5.5: the full demo rerun, the committed report and the AGENTS.md figures. The numbers will change: the
  generator, the fill timing and the cost model all differ from the starter's.
- ~~AGENTS.md (the owner's file, not edited in the merge) is out of date in two places: the `on_bar` example
  computes `vol_target / forecast_vol`, but forecasts are per bar now, so a strategy must annualise them first
  (× √365 for daily bars, × √8760 for hourly); and the starter-module table still describes the contract as
  `ret, position, turnover` with close fills (4a.5).~~ Both fixed by the director's milestone-2 review
  (`reports/director/2026-11-25-milestone2.md`).
- `volume_z_20` saturation: a decision for `ml-researcher` (section 4, findings that are not bugs).
- `artifact.save_model` doesn't check that `features` match the columns the model was fit on, or that `kind`
  matches the model type (osprey's untested draft did both). Worth a check and a test (models owner).
- `test_models.py::test_walk_forward_predict_never_uses_future_labels` still has the weakness fixed in #27. The
  `test_train_props.py` version now pins the purge, so it can be tightened the same way or dropped.
- Live/backtest parity with Nautilus: `float(Price)` differs in the last bit from parsing the same decimal
  string for 4223 of 20000 random 2-decimal prices, so the batch path (catalog loader) must convert prices the
  same way as the live path (milestone 2). Both now call `float()` on the `Price`: `lab.data.catalog.load_bars`
  and `FeatureBuffer.update`. No test yet feeds catalog bars to a `FeatureBuffer` and compares the result with
  `compute_features` on `load_bars`'s output; add one with the first model-using strategy.

---

## 5. Open work, in order

### 5.1 Verify the refactor that was in progress

**Merge status: done.** Osprey's `lab/validation/` was written with these helpers from the start
(kept over the starter's, section 4a.1); the full and deep tiers pass (section 4a.7).

Details: history file.

### 5.2 Fix the two failures found by the deep profile

**Merge status: done** in osprey's kept files: A is bug #8, B is bug #9 (both `@example`s kept).

Details: history file.

### 5.3 Close the mutation-testing gaps in `lab/validation/`

**Merge status: done.** Every test listed below is in osprey's `test_stats_exact.py`,
`test_splits_exact.py` and `test_montecarlo_exact.py`; the merge added the tests that killed the 7
real survivors of the comparer's run and `tests/MUTATION_NOTES.md`. Result in section 4a.7.

Details: history file.

### 5.4 Extend mutation testing to the rest of `lab/`

**Merge status: not started.** The test files named below changed in the merge (section 4a.2):
`test_backtester_props.py` became `tests/contract/`, `test_reference_rules.py` and `test_costs.py`; the
artifact part of `test_artifacts_loaders.py` is `test_artifacts.py` and the loader part `test_loaders.py`.
`[tool.mutmut]` is set up for `lab/validation/`; section 6 says how to switch areas.

Do one area at a time. For each, set `tests_dir` to the matching test files, run, kill
real survivors with new tests, and document equivalents.

| Area | Test files |
|---|---|
| `lab/runner/reference.py` | `test_backtester_props.py`, `test_search.py` |
| `lab/search/` | `test_search_props.py`, `test_search.py` |
| `lab/models/` | `test_features_leakage.py`, `test_labels_props.py`, `test_train_props.py`, `test_artifacts_loaders.py`, `test_models.py` |
| `lab/data/loaders.py` | `test_artifacts_loaders.py` |

Targets: ≥ 90% for `lab/validation/` and `lab/runner/`; ≥ 80% for `lab/search/`,
`lab/models/` and `lab/data/`.

### 5.5 Rerun the demo and update the docs

**Merge status: in progress.** `scripts/demo.py` runs end to end on the merged code (small budget,
scratch directory, section 4a.7). The full rerun, the committed report and the AGENTS.md figures
are still to do. Expect new numbers: the generator, the fill timing and the cost model changed in the merge.

```bash
uv run python scripts/demo.py --trials 150 --workers 4
```
Fixes 4–6 change every backtest number (fractional positions now drift and only pay when
they trade; the 50/50 benchmark pays to rebalance). Then:
- Commit the new report the demo writes to `reports/demo/<date>.md` (the old one was deleted because its numbers were wrong).
- Update the figures in AGENTS.md → "What the demo taught us" (worst drawdown 69% → 19%,
  Sharpe 0.39 → 0.96, the 80% / 27% model win rates). Change the wording if a lesson no
  longer holds.

### 5.6 Turn the backtester tests into a contract every runner must pass

**Merge status: done** (osprey): `tests/contract/` runs every guarantee against 8 runner entries,
including one that sizes from a model forecast column; dip-buy and benchmark specifics are in
`tests/test_reference_rules.py`. The contract and why it was chosen: section 4a.5.

Details: history file.

### 5.7 Raise the coverage floor

**Merge status: done:** `fail_under = 100`; branch coverage of `lab/` is 100%.

Details: history file.

---

## 6. Mutation testing notes (mutmut 3.8)

Config lives in `pyproject.toml` under `[tool.mutmut]`. Things learned the hard way:
- `also_copy` must name a **directory** (`["tests"]`). A single file such as
  `tests/conftest.py` crashes because `mutants/tests/` doesn't exist yet.
- With this layout mutmut mutated all of `lab/` even though `paths_to_mutate` names only
  `lab/validation/`. Mutants marked "no tests" belong to modules outside the selected test
  files. Ignore them, or run one area at a time (check `uv run mutmut run --help` for
  name filters).
- Run with the fast profile: `HYPOTHESIS_PROFILE=fast uv run mutmut run --max-children 4`.
- `uv run mutmut results` lists survivors; `uv run mutmut show <name>` shows the diff.
- Delete `mutants/` between configuration changes.
- `only_mutate` (a list of files) keeps mutmut 3.8.1 to the area under test; the merged config sets it
  for `lab/validation/`. Change it together with `paths_to_mutate` and `tests_dir` per area (5.4).
- mutmut wraps functions in trampolines, so a changed default argument is invisible to
  `inspect.signature`: pin defaults by value (call with and without the argument), as
  `test_default_arguments_are_used_not_just_declared` does.

---

## 7. Patterns for new tests

Use these when you add a strategy, feature, model or runner.

| Pattern | How | Example |
|---|---|---|
| **Tamper the future** | Change data from bar `cut` onward; everything decided before `cut` must be identical | `test_no_feature_changes_when_the_future_changes`, `test_no_look_ahead` |
| **Touch the present** | Change only bar `t`; every feature at `t` must react (catches stale-by-one bugs) | `test_each_feature_reacts_to_the_present_bar` |
| **Hand-built paths** | `make_bars([...])` with a price path where the right answer is obvious | `test_stop_loss_exits_at_the_stop_bar` |
| **Known answers** | Compute the expected value by hand in the test, independently of the code | `test_known_feature_values` |
| **Identities** | Relations that must hold exactly | `ret = position × r − turnover × cost` |
| **Live/backtest parity** | Feed bars one at a time to the live object; compare with the batch result on every bar | `test_live_buffer_equals_backtest_for_every_bar` |
| **Calibration under the null** | Simulate many skill-less cases; the false-positive rate must match the advertised rate within a binomial band | `test_psr_false_positive_rate_is_about_5pct` |
| **Oracle** | A forecaster that equals the truth must score perfectly | `test_cpcv_rows_and_identical_test_sets` |
| **Crash recovery** | Simulate the leftovers of a killed process | `test_leftovers_from_a_crashed_run_are_ignored` |
| **Real prices are discrete** | Draw prices with the few decimals real quotes have, with flat bars and exact returns to an earlier price. Continuous synthetic prices never repeat, and an exact repeat is where round-off decisions live | #61: on the Kraken hourly bar closing 2020-04-09 19:00 UTC a 50/50 rebalance filled at an open of 7299.4, exactly the previous fill's open 30 bars earlier, so the reference traded a 3.3e-16 leg and paid gas for it; no synthetic draw reaches that. About 1 hourly close in 3,500 equals the close 30 hours earlier |
| **Real-data parity** | Run a new or changed engine against the reference on real catalog bars, train window only (Kraken and Binance, BTC and ETH, daily and hourly, costs at 1x and 2x); every disagreement becomes a hand-built regression test | `scripts/nautilus_parity_real.py` |
| **Stand-ins for recorded state** | A test that copies `config/`, a PLAN.md or a RUNLOG sets every value it depends on by key, inside the named entry, and never depends on what the repo has recorded so far (budgets, amendments, runs) | `edit_steady_entry` and `set_steady_budget` (#55), `real_folders` (#48), `without_prior_rows` (#59) |

Optuna objectives in tests must be module-level functions, and searches in tests use
`n_workers=1`.

---

## 8. Definition of done (this testing work)

- [x] Full, deep and slow tiers pass
  - Merge (2026-11-19): full 1003 passed (12 slow), deep 991 passed; `tests/test_dashboard.py` runs on its own (4a.7).
- [x] Bug log updated, including 5.2A and 5.2B
  - Merge: #8 and #9; #8–#27 were found in the merge.
- [ ] Mutation targets met for every area in 5.4; `tests/MUTATION_NOTES.md` lists every accepted survivor with a reason
  - Merge: `lab/validation/` done (100% of non-equivalent mutants, 35 equivalents listed). Runner, search, models and data not started.
- [x] Branch coverage 100% with `fail_under = 100`
  - Merge: 1390 statements, 402 branches, 0 missed.
- [ ] Demo rerun; the report and AGENTS.md figures updated
  - Merge: the demo runs on the merged code (small budget, scratch directory). The full rerun is 5.5.
- [x] Contract suite split out and parametrized over runners
  - Merge: osprey's `tests/contract/`, 8 runner entries (4a.5).
- [x] `uv run ruff check` clean
  - Merge: `.venv/bin/ruff check` passes.

## 9. Report back

Post this to the owner when done:

```
Tests: <n> total (<n> slow) — all passing (fast, full, deep)
Coverage: <x>% branch
Mutation score: validation <x>%, runner <x>%, search <x>%, models <x>%, data <x>%
Bugs found this round: <list, one line each: where, what, fix>
Demo after fixes: <headline numbers vs. before>
Anything you had to decide that the owner should know: <list>
```
