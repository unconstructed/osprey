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
| Full | Before merging | `uv run pytest -n auto --cov --cov-branch` | ~2 min |
| Deep | Before merging changes to `lab/` | `HYPOTHESIS_PROFILE=deep uv run pytest -m "not slow" -n auto` | ~10 min |
| Mutation | Before each audit, and nightly once CI exists | `uv run mutmut run` (section 6) | ~10 min per area |

---

## 3. What exists today

Last full run (2026-11-19, after the merge with the starter code in section 4a): **1003 tests passed
(12 of them slow), 100% branch coverage of `lab/`** (1390 statements, 402 branches; `lab/data/synthetic.py`
excluded; it's test scaffolding), with `fail_under = 100`. `tests/test_dashboard.py` (86 tests) checks the
results dashboard, not `lab/`, and runs on its own. Tests per file in brackets.

| File | What it proves |
|---|---|
| `contract/test_backtest_contract.py` (195) | **The backtest contract, for every runner** (8 entries in `tests/contract/conftest.py`; the Nautilus runner will be one more): no look-ahead (every bar field from the cut on is tampered except the fill open); exact per-bar accounting identities with overnight gaps; only fills trade and every fill pays; the fill log lists every fill at the open; costs scale each bar's return; a flat-rate cost is exactly turnover × rate; trade log equals the portfolio at zero cost; bounds; determinism; bad params and bad bars raise; `validate_result` rejects 19 kinds of bad output |
| `test_reference_rules.py` (89) | **Reference rules on hand-built paths:** entry at the open after the drop bar; stop and hold exits (holds up to 25 bars); no re-entry on the exit bar; vol-target sizing by hand and from a model forecast column (NaN/inf fall back to realised vol, the forecast at the signal close is used, a forecast ≤ 0 never trades, no look-ahead in the column); drawn-parameter identities on 400-bar windows; trade log equals the portfolio with costs on; positions drift as coin units; buy-and-hold, constant-mix (every bar, band, schedule) and random-entry benchmarks |
| `test_costs.py` (83) | The DEX cost model from `config/costs.yaml`: slippage by hand and at the table points, growth with trade size, gas per fill, stress, YAML loading; costs change returns by exactly the cost paid; a cost the portfolio can't pay raises |
| `test_stats_props.py` (53), `test_stats_exact.py` (151) | Sharpe, PSR, expected max Sharpe, DSR, effective trials, PBO: scale invariance with no absolute floor (5.2A), bit-exact power-of-two scaling, every 5.3 known answer, the reachable PSR variance guard, the PBO tie rule and column-order independence, PBO against an independent CSCV, bounds, error messages pinned |
| `test_splits_props.py` (11), `test_splits_exact.py` (55) | Walk-forward and CPCV: match a brute-force version, no train/test overlap, purge and embargo gaps are exact, every row tested the right number of times, folds written out by hand (5.3), CPCV paths use each group's j-th appearance and cover every row once, bad arguments raise |
| `test_montecarlo_props.py` (28), `test_montecarlo_exact.py` (70) | Max drawdown known answers and bounds; shuffle, bootstrap and stationary block bootstrap: values, ranges, restart share, determinism, default lengths; no trades means no drawdown; degraded execution never helps, draws costs per period and averages `extra_cost_bps`; `percentiles` |
| `test_calibration.py` (12, slow) | On pure noise: PSR false-positive rate ≈ 5% (normal and fat-tailed); expected max Sharpe matches simulation; picking the best of 100 noise strategies fools PSR > 80% of the time but DSR < 8%; DSR power on a real edge; PBO ≈ 0.5 under the null and low with a real edge; block bootstrap keeps volatility clusters |
| `test_features_leakage.py` (54) | **Look-ahead:** changing any future bar never changes a past feature; every feature reacts to the present bar (5.2B fixed) and reads exactly its window; price and volume scale invariance (bit-exact for powers of two); hand-computed values for all 15 features and on hand-built paths (flat, growth, drawdown, zigzag, volume spike, zero volume); live `FeatureBuffer` equals backtest features bit for bit on every bar, takes Nautilus `Price` objects, rejects bad and out-of-order bars; cross-sectional ranks; feature ranges; the `volume_z_20` bound |
| `test_labels_props.py` (49) | Every label equals a hand computation over exactly its future window and is NaN without a full future; label names never appear as features; rewriting a label's window never changes the features; baselines use only the past, equal hand computations and equal the features they mirror |
| `test_train_props.py` (14) | Metric known answers (QLIKE punishes under-forecasting risk more); constant forecasters handled; CPCV scores every forecaster on identical rows (an oracle scores perfectly); walk-forward forecasts can't see labels that aren't fully known yet (the horizon purge) or future features; reproducible |
| `test_models.py` (5) | End to end on the synthetic market: features have no look-ahead, forward-vol label by hand, the model beats naive volatility, walk-forward forecasts ignore later labels, artifact round trip |
| `test_artifacts.py` (7) | Model files round-trip; a tampered model file is refused; `ModelPredictor` matches the raw model for all three model kinds and ignores column order; **the saved vol model is the model that was validated** (#17); the predictor takes the live buffer's dict and rejects a missing feature |
| `test_search.py` (3), `test_search_props.py` (20) | Parameter units; objective formula and the too-few-trades penalty; failing trials logged while the search continues; resume; orphan files from crashed workers ignored; reproducibility; stable region prefers plateaus over spikes and breaks ties by the trial's own score; **walk-forward decisions can't see their own test block** (every logged trial of the fold compared); report and gates (missing numbers fail, never pass, DSR with too few trials included) |
| `test_loaders.py` (78) | Kraken and Binance loaders: seconds, ms and µs (also mixed in one file), headers, duplicates keep the last row, bad rows dropped and counted, short and over-wide lines, bar close-time index, real Binance rows (2017 in ms and 2025 in µs, as CSV and .zip); resampling keeps complete buckets only |
| `test_synthetic.py` (20) | Generator: valid bars for any length, seed and number of assets; determinism; volatility clustering; realistic volatility and BTC/ETH correlation; the shuffled luck control keeps bar shapes and destroys clustering |
| `test_config.py` (6) | `splits()` reads the fixed windows as UTC with `latest` open-ended; daily and hourly close-time bars fall in the right window, with no gap or overlap (#19) |
| `test_futures.py` (18) | Binance futures files (positioning data): funding, metrics and 5-minute kline zips parsed by hand-built examples (headers, quotes, `""` and `0E-8`, short lines, other symbols, rows outside the file's period, exact vs conflicting duplicates); the frozen-feed rule marks a value only from the moment it has been unchanged for an hour, never earlier (causal: tampering later rows never changes earlier cleaned rows); funding and metrics checks by hand; the timing check finds each day's timestamp convention, flags data that reach past the 5-minute lag, and calls a day inconclusive without a clear winner |
| `test_external.py` (23) | **Point in time for positioning:** a value known at or after a bar's close never appears in its row (hypothesis tamper-the-future: rewrite, drop and add every later value, incl. one known exactly at the close); the newest value known before the close does (touch the present); funding last/1-day/7-day means and metrics last values by hand, with the exact `known_at < close` boundary and the age limits to the microsecond; the store round trip, a store file changed after the build is refused, a store with test-window values is refused, and `load_positioning` refuses any `end` after the last validate close |
| `test_positioning_build.py` (18) | Download (fake data.binance.vision): every zip checked against its `.CHECKSUM`, nothing after the last validate day requested (the July 2024 files exist on the fake server and are never asked for), a missing day listed and never filled, the start check stops when history begins earlier than recorded; the build stores the tables with `known_at`, drops the row known only at the cut, records the timing runs and per-window coverage, keeps the bars-only content hash, stops on missing files, on look-ahead in the metrics timing and on a table round-trip mismatch; reports, and a second snapshot the same day never overwrites the first one's report (#33) |

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
- **Binance futures metrics changed their timestamp convention on 2024-04-26** (data, not a code bug).
  Until 2024-04-25 a row's `create_time` T is the END of its 5-minute period (its taker ratio equals the
  kline period [T-5, T), its open-interest value / open interest equals the price at T); from 2024-04-26 it
  is the START (period [T, T+5), price at T+5), for BTCUSDT and ETHUSDT alike. Reading `create_time` as
  "known at" would leak 5 minutes in the newer files. `known_at = create_time + 5 min` covers both, and the
  build re-checks every day against 5-minute futures klines and stops if any day's data reach further.
  Do not shorten `futures.METRICS_LAG` without rerunning that check.

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

### 4a.1 Code: which version was kept

| File | Kept | Evidence (starter / osprey: own tests, coverage, cross-runs, mutation where measured) | Why |
|---|---|---|---|
| `lab/validation/stats.py` | osprey | Starter: its validation suite passes fast (52) and slow (12), `stats.py` 100% branch, but **deep fails** on 5.2A; most 5.3 known answers missing; mutation 80% for `lab/validation/` (5.3 baseline). Osprey: 349 validation tests pass fast and deep, 100% branch of `lab/validation/`, every 5.2A and 5.3 item pinned; mutation 96.3% raw (1010 of 1049 killed; 15 survivors in `stats.py`, 2 of them real). Cross-runs: osprey's stats tests on the starter 89 pass / 107 fail, catching 6 real starter bugs (#8, #10); the starter's on osprey 24 of 27 pass, the 3 failures by design (NaN input raises, `effective_trials` rejects 1-D input); calibration 12/12 on osprey | 5.2A fixed, every guarantee pinned, higher mutation score. Its tests find starter bugs; the starter's find none in osprey |
| `lab/validation/splits.py` | osprey | Starter: passes fast and deep, 100% branch; the 5.3 splits items missing; `walk_forward(..., step=-1)` never returns. Osprey: passes fast and deep, 100% branch, every 5.3 item, every bad argument raises with a pinned message; 7 mutation survivors, all equivalent. Cross-runs: osprey's splits and Monte Carlo tests on the starter 84 pass / 69 fail, nearly all missing validation, with no numeric disagreement on valid inputs; the starter's on osprey fail in 2 places, both by design (a raise instead of an empty result), and the rest pass deep | Full 5.3 set, validated arguments, no hang (#11) |
| `lab/validation/montecarlo.py` | osprey | Starter: 96% branch (the `mean_block < 1` raise untested), 5.3 items missing. Osprey: 100% branch, every 5.3 item plus empty input, total loss and inputs-not-modified; 17 mutation survivors, 13 equivalent and 4 small real ones. Cross-runs: osprey's tests catch the starter's empty-input crash and unbounded cost model (#11); the starter's on osprey fail once, by design (NaN in `max_drawdown` raises) | Bounded degraded execution, empty input handled |
| `lab/runner/interface.py` | osprey | Starter: `check_result` checks only `ret`, `position`, `turnover` and `trade_returns`; 100% branch. Osprey: `validate_bars` and `validate_result` (index, `cost` column, `n_trades`, bounds, cost only on fills), execution model written down; 75% branch, because no test fed it a bad result (a hand probe showed every branch raises correctly). Cross-runs: API differences only | Stricter contract with the `cost` and `n_trades` the 5.6 suite needs (4a.5). The merge added 19 rejection cases and negative volume: 100% |
| `lab/runner/reference.py` | osprey | Starter: 23 tests pass fast and deep, 100% branch of `lab/runner`; trade log with costs on and input validation not pinned. Osprey: 303 tests (contract, rules, costs) pass fast and deep, `reference.py` 100% branch. Cross-runs: the starter's tests on osprey 9 pass / 14 fail, all fill timing, cost semantics, tampered bars that broke high ≥ close, or the missing model column; osprey's tests on the starter 45 pass / 116 fail / 4 skipped, including real starter bugs: trade log off the portfolio by up to 7.58e-4 per trip at 16 bps (2.35e-3 at 50 bps), buy-and-hold logging the gross price change, fees paid from negative cash, no validation (#12–#14) | Fills at the next open (hard rule 4, as Nautilus does), trade log = portfolio with costs on, the `config/costs.yaml` model, input validation, random-entry and monthly 50/50 benchmarks. Its missing feature, sizing from a model forecast, was added (#22) |
| `lab/models/features.py` | osprey | Starter: its models-area suite (51 tests) passes, 100% branch of `lab/models`; deep fails (5.2B, a test bug); 6 of 15 features checked by hand; live parity only to rtol 1e-9 (bit-exact on 51 of 1399 bars); √365 on any bar size. Osprey: 101 tests (features and labels) pass fast and deep, 100% branch; all 15 features by hand; bit-exact live parity; bar validation. Cross-runs: the starter's tests on osprey 31 pass / 20 fail (names, units, signatures, and one real weakness, `volume_z_20` saturation, logged under section 4 findings); osprey's tests on the starter 16 pass / 85 fail (mostly names and units; weaker behaviour: features not exactly local to their window, inexact parity, no validation, NaN on flat input) | Every section 3 guarantee, 5.2B fixed, per-bar units that also work for hourly bars (#24) |
| `lab/models/labels.py`, `baselines.py` | osprey | Starter: see #24. Osprey: full-vector hand computations, exact future-window tamper, argument and bar validation, 100% branch; the EWMA baseline equals the `ewma_vol_20` feature exactly. Cross-runs: the differences are units (√365), log vs simple forward return and signatures; the regime label is numerically the same | Better tested and stricter |
| `lab/models/online.py` | merged | Starter `FeatureBuffer`: crashes on Nautilus `Price`/`Quantity` (the AGENTS.md `on_bar` example), accepts out-of-order and invalid bars. Osprey `FeatureBuffer`: validated, bit-exact, takes `Price`; but its draft `ModelPredictor` was untested (`online.py` 88%). The starter's `ModelPredictor` is covered by its artifact tests, which passed on osprey's features | Osprey's buffer (#16) and the starter's predictor (owner's instruction), changed to take a mapping (4a.3) |
| `lab/models/train.py` | starter | Starter: `test_train_props.py` and `test_models.py`, 100% branch. Osprey's draft: no tests, 15% covered | Owner's instruction, and the only tested version |
| `lab/models/artifact.py` | starter | Starter: round trip, tamper refusal, three model kinds, 100% branch. Osprey's draft: no tests, 19% | Same |
| `lab/search/*` (7 files) | starter | Not in osprey. The starter's 22 search tests on osprey's runner: every trial failed until the runner's `attrs` were stripped (#21); then 21 pass, and the last one passes once its tampered bars keep high ≥ close ≥ low | Missing in osprey |
| `lab/data/loaders.py` | osprey | Starter: 8 tests (loaders, resampling, generator), 100% branch; four defects (#15). Osprey: 72 tests, 100% branch, fast and deep; loads the real Binance zips. Cross-runs: the starter's tests on osprey 1 pass / 7 fail, all API or convention differences (close-time index, trades column, a fixture with `close_time = 0`); osprey's tests on the starter 13 pass / 76 fail, with 3 real starter bugs confirmed by probes. One osprey bug found (#18) | Bar close-time index (AGENTS.md data step 2), bad ticks dropped and counted, unit detected per value |
| `lab/data/synthetic.py` | osprey | Starter: 1 test, 100% branch, no input validation (#25). Osprey: 17 tests, 100% branch, fast and deep. Swaps: the starter's whole non-slow suite on osprey's generator 147/147; osprey's suites on the starter's generator 337/338 (the one is input validation) | Either keeps every suite green; osprey's adds the shuffled luck control, input validation and the `ts` index name |
| `lab/config.py` | osprey (no starter version) | 55% covered; `splits()` untested and documented with an off-by-one rule (#19) | Used by `reference.py`; fixed and tested in the merge |
| `tests/conftest.py` | osprey | Same hypothesis profiles (fast 40, deep 500) and the same `market` (1500 days, seed 21), `btc` and `features` fixtures; `make_bars` is a validated fixture | Superset |
| `pyproject.toml` | osprey + the starter's `[tool.mutmut]` | Osprey had the ruff and uv settings and no mutmut config; section 6 relies on the starter's block | `tests_dir` = the six kept validation test files, `only_mutate`, `also_copy` adds `config`; `fail_under` 95 → 100 (5.7) |
| `scripts/demo.py` | starter | Not in osprey | Edits in 4a.3 |
| `.gitignore` | osprey | | `.pytest_cache/` and `.ruff_cache/` added |

### 4a.2 Tests: kept, dropped and ported

| Test file (tests collected) | Kept | Why, and what was ported |
|---|---|---|
| starter `test_stats_props.py` (24), `test_splits_props.py` (8), `test_montecarlo_props.py` (9) | dropped | Superseded by osprey's `_props` and `_exact` files; the starter's stats file fails deep (5.2A). Ported into osprey's files: PSR penalises negative skew and fat tails; PSR rises with more data for the same edge; two groups of clones count as about 2 trials; the sorted order is the worst shuffle; adding a loss never reduces drawdown |
| starter `test_validation.py` (11) | dropped | Smoke tests covered by osprey's exact and property tests; two behavioural ones were ported anyway (PBO ≈ ½ on noise and low with a real edge; effective trials of near-clones vs independent columns). The file needed the old `label_horizon`, `cpcv_n_paths` and `cpcv_paths` APIs |
| osprey `test_stats_*`, `test_splits_*`, `test_montecarlo_*` | kept | Plus the ported tests above, 5 tests that kill the comparer's real mutation survivors, and tests for the `Fold`, `percentiles` and `probability_of_backtest_overfitting` additions (4a.3) |
| starter `test_calibration.py` (12, slow) | kept, unchanged | Osprey had none and section 3 requires them; 12/12 pass on osprey's modules |
| starter `test_backtester_props.py` (22) | dropped | Its assertions encode close fills and additive costs, and the 5.6 split already existed in osprey. Ported: the result-checker rejections (as 19 `validate_result` cases), model-forecast sizing (3 sizes, NaN fallback, a forecast ≤ 0 never trades), model-column look-ahead, drawn-parameter properties on 400-bar windows, and, after the lost-guarantee check, holds of 6, 10 and 25 bars. Everything else is covered by the contract and rules tests (4a.6) |
| osprey `tests/contract/*`, `test_reference_rules.py`, `test_costs.py` | kept | Plus the ports above, negative volume in the bad-bars cases, an inf fallback, a test that the forecast at the signal close is used, and a runner entry that sizes from a model column |
| starter `test_features_leakage.py` (11), `test_labels_props.py` (7) | dropped | 5.2B open; 6 of 15 features hand-checked; its future tamper made invalid bars. Ported: the `np.isclose` criterion in the present-bar test (it caught the `volume_z_20` saturation) and `test_feature_ranges`. Not ported: persistence score = efficiency (no such function now; the demo uses the `eff_ratio_20` feature), `rel_ret_20` and `benchmark=` (osprey has rank features only), the λ 0.94 EWMA (osprey's is span 20, checked by hand) |
| osprey `test_features_leakage.py`, `test_labels_props.py` | kept | Plus the ports above and `test_volume_z_is_bounded_by_its_window` |
| starter `test_train_props.py` (14) | kept | Goes with `train.py`. Edits in 4a.3; the future-label test strengthened (#27) |
| starter `test_models.py` (6) | kept (5) | Edits in 4a.3; `test_online_buffer_matches_batch_features` dropped, superseded by osprey's bit-exact parity tests on every bar |
| starter `test_artifacts_loaders.py` (13) | split | Artifact part kept as `test_artifacts.py` (7: the 5 artifact tests plus 2 new). Loader and synthetic part dropped, superseded by `test_loaders.py` and `test_synthetic.py`; its realism bands were ported |
| starter `test_search.py` (3), `test_search_props.py` (19) | kept (3, 20) | Go with `lab/search`. Edits in 4a.3; the tie-break property added (#20) |
| osprey `test_loaders.py`, `test_synthetic.py` | kept | Plus short and over-wide line regressions (#18), real Binance rows (2017 in ms and 2025 in µs, as CSV and .zip) and the starter's realism bands |
| `test_config.py` | new | `splits()` and the close-time window rule (#19) |
| osprey `tests/test_dashboard.py` | kept, untouched | Dashboard tests; they run on their own |

### 4a.3 Starter code brought over, and every edit to it

Brought over unchanged (byte for byte): `lab/search/__init__.py`, `lab/search/space.py`, `tests/test_calibration.py`.

| Starter file | Edit | Why |
|---|---|---|
| `lab/search/objective.py` | Returns `pd.Series(r, index=res.index, name="ret")` instead of `res["ret"]` | Osprey's runner keeps arrays and a fill frame in `attrs`; pandas copies them onto `res["ret"]`, and `to_parquet` failed every trial (#21) |
| `lab/search/walkforward.py` | `oos.attrs = {}` before `pd.concat`; `# noqa: B008` on the `SearchConfig()` default | #21; ruff flags the default, which is never mutated (callers use `dataclasses.replace`) |
| `lab/search/study.py` | `# noqa: B008` on the `SearchConfig()` default | Ruff only |
| `lab/search/stability.py` | Neighbourhood scores sorted before averaging; ties go to the trial with the best own score | #20 |
| `lab/search/report.py` | DSR is NaN when no study kept 2+ completed trials | #23 (osprey's DSR also rejects an empty trial list) |
| `lab/models/train.py` | `VOL_ANCHOR = "ewma_vol_20"`; new class `AnchoredVolModel` holds the arithmetic `_fit_predict` had; `cpcv` unpacked as `(train_idx, test_idx, groups)` | Osprey's EWMA feature (per bar, like the labels); one vol model for validation and deployment (#17); osprey's splitter returns 3-tuples |
| `lab/models/artifact.py` | `train_final("vol")` fits `AnchoredVolModel`; `datetime.UTC`; unused numpy import dropped | #17; ruff |
| `lab/models/online.py` (`ModelPredictor`) | Takes any mapping and reads features by name; a missing feature raises `ValueError`; columns default to `FEATURES`; "vol" goes through `AnchoredVolModel` | `FeatureBuffer.latest()` returns a dict, and the starter's `reindex` failed on it (the `on_bar` path); LightGBM would take a NaN silently; #17 |
| `scripts/demo.py` | Osprey names (`compute_features`, `FEATURES`, `forward_vol(bars, h)` and the other bars-based calls); parameters as fractions; `synthetic_market(3400, seed, start="2017-01-01")`; doubled costs via `Costs.from_yaml().stressed(2.0)`; the vol-targeted variant is `dip_buy` with `vol_col="pred_vol"`, the per-bar forecast × √365; the doubled-cost rerun uses the same backtest function and strips `attrs`; the EWMA baseline is `ewma_vol_20` (relabelled from "RiskMetrics", which is λ 0.94); the long-run baseline is still a 60-bar rolling vol; the regime baseline is `eff_ratio_20`; the 50/50 benchmark rebalances every 30 bars; `--results-dir` and `--report-dir` | Osprey APIs; keeps the 2017 start; #22 (without it the model-sized variant silently used realised vol); #21; a continuous regime score keeps the AUC meaningful; AGENTS.md asks for a monthly 50/50; trial runs that don't write into the repo |
| `tests/test_search.py` | Osprey parameter names; `test_reference_costs_reduce_returns` rewritten: `Costs.zero()` against a 50 bps pool fee, and buy-and-hold growth = price growth from the open of bar 1 × (1 − the entry cost charged), to `rtol=1e-12` (was `1e-3` against `Costs().bps`) | Osprey's `Costs` has no `.bps`, and it buys at the next open. Same three checks, tighter |
| `tests/test_search_props.py` | Parameters as fractions; `params_drop` in [0.02, 0.30] instead of `params_drop_pct` in [2, 30]; the tampered bars keep high ≥ close ≥ low; the fold test also compares every logged trial; DSR NaN asserted; the tie-break property added | Unit change only; osprey's runner rejects invalid bars; #26; #23; #20 |
| `tests/test_train_props.py` | Bars-based labels; the "flat" forecaster 0.5 → 0.5/√365; labels corrupted from `cut - 10` instead of `cut` | Per-bar units at the same level; #27 |
| `tests/test_models.py` | Osprey names; the manual forward vol has no √365; the live-buffer test dropped | Per-bar units; superseded (4a.2) |
| `tests/test_artifacts.py` | The artifact part of `test_artifacts_loaders.py`; for vol, `exp(model.predict)` → `model.predict`; added: deployed vol forecast = validated forecast, and the predictor takes the live buffer's dict and rejects a missing feature | #17 (the old assertion pinned the bug) |

No test was weakened: every changed range or tolerance is a unit change or tighter.

Osprey's own files were changed only so the starter code runs on them, each change thin and tested rather than
a fork of starter code: `stats.probability_of_backtest_overfitting = pbo` (the starter's name, used by
`report.py` and `test_calibration.py`); `walk_forward` returns a `Fold` named tuple with `.train` and `.test`
(used by `walkforward.py`; folds still unpack as pairs); `montecarlo.percentiles` (used by `report.py`);
`dip_buy(vol_col=...)` (#22). Plus the fixes #18 and #19 and the 19 `validate_result` rejection cases.

Behaviour that changed by keeping osprey's files (the owner should know):

- NaN returns raise `ValueError` in `sharpe`, PSR, `max_drawdown` and PBO instead of being dropped. `report.py`
  drops NaN rows first, and a backtest that returns NaN becomes a failed trial, which is logged.
- `walk_forward` raises when no fold fits (was `[]`); `cpcv` raises when purge plus embargo leave no train rows;
  `walk_forward(start=...)` means the first test row (no caller passes it).
- `degrade_execution` draws Uniform(0, 2) × bps applied multiplicatively instead of an Exponential subtracted
  from the return: same mean, bounded. `block_bootstrap_drawdowns` takes `(returns, mean_block, n_sims, seed)`
  positionally (callers use keywords). Capped `cscv_splits` come back sorted. PBO in-sample ties score the worst
  out-of-sample candidate. `EULER_GAMMA` is 0.5772156649, as 5.3 writes it (about 2.7e-12 relative difference in
  expected max Sharpe).
- Volatilities (features, labels, baselines, model forecasts) are per bar; annualise where they meet an annual
  number such as `vol_target`. `forward_return` is a simple return (the starter's was log); `long_run_vol` is
  expanding.
- Loaders index bars by close time, keep the `trades` column, and drop and count bad rows instead of raising.
- The runner: 4a.5.

### 4a.4 Where the merge departed from a comparer

- **PBO name and `percentiles`.** The validation comparer suggested editing `report.py` and `test_calibration.py`
  to call `pbo` and `np.percentile`. The merge kept those starter files as they were and added one alias and one
  validated helper to the kept modules instead.
- **Empty trial list in the report.** The comparer suggested `trial_sharpes or [0.0]`, which reproduces the
  starter's undeflated DSR. The merge reports DSR as missing (NaN), so its gate fails (#23).
- **`stable_region` ties.** The validation comparer only passed this on to the search area. The merge fixed it
  (#20), with a property test that fails on the starter's code.
- **Validated vs deployed vol model.** The models comparer flagged it for the train/artifact owner. The merge
  fixed it (#17) and changed the one starter assertion that pinned the bug.
- **`volume_z_20`.** Kept as the raw-volume z-score instead of switching to log volume: log volume saturates
  too, only more slowly (section 4, findings that are not bugs).
- **`test_regime_and_ranking_baselines`** (persistence score = efficiency feature) was not ported: the demo uses
  the `eff_ratio_20` feature column directly, so there is no separate function to test.
- **`pyproject.toml`.** Beyond the comparer's mutmut block: `only_mutate` (the comparer's own mutation run used
  it), `config` in `also_copy`, and `fail_under = 100` (the comparer said keep 95 until `lab/config.py` was
  tested; it now is).

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

### 4a.6 Lost-guarantee check

Every test in the dropped or replaced files (the starter's `test_backtester_props.py`, `test_validation.py`,
`test_stats_props.py`, `test_splits_props.py`, `test_montecarlo_props.py`, `test_features_leakage.py`,
`test_labels_props.py`, the loader and synthetic part of `test_artifacts_loaders.py`, the dropped
`test_online_buffer_matches_batch_features`, and every starter test edited in the merge) was mapped to a kept
test. Where the mapping wasn't obvious, the code was broken by hand in a scratch copy to see a kept test fail.
Osprey dropped no test file (its drafts of `train.py` and `artifact.py` had no tests). Three guarantees were no
longer pinned, or never had been; each is restored with a test that fails on the broken code:

| Guarantee | Was pinned by | Hand break that the kept suite let through | Restored by |
|---|---|---|---|
| A hold period is exact for long holds | starter `test_hold_days_is_exact` (holds 6, 10, 25) | `hold` capped at 10 bars: 281 runner tests passed (osprey's exact test stopped at hold 5; the drawn-params property checks identities, not exit bars) | `test_hold_period_exits_after_hold_bars` also runs holds 6, 10 and 25 |
| A walk-forward fold's search never sees its test block | starter `test_fold_decisions_cannot_see_their_test_block` | Searching on train + test block passed (#26) | The test also compares every logged trial of the fold's study; a 1-bar leak fails it too |
| Walk-forward model training waits until a label's whole window has passed (the horizon purge) | nothing: a gap in both starter test files (#27) | No purge, and an off-by-one purge: both passed the leak tests | `test_walk_forward_predictions_cannot_see_future_labels` corrupts every label not fully known at `cut` |

Checked and still pinned (the hand break failed a kept test): a model forecast read at the fill bar instead of
the signal close; an open round trip left out of the trade log; range volatility reading the next bar's range;
a vol predictor off by a factor of 1.0001. Starter guarantees that no longer apply, by design:
`Costs(per_side_bps=...)`, `.bps` and `from_config` (osprey's `Costs` reads `config/costs.yaml`, pinned by
`tests/test_costs.py`); NaN-tolerant `sharpe`, `max_drawdown` and `effective_trials` on 1-D input (osprey
rejects them with `ValueError`); bad prices raising in the loaders (osprey drops and counts them); bars indexed
by open time (osprey: close time); `rel_ret_20` and the `benchmark` argument of the cross-sectional features
(osprey has rank features only); `persistence_trend_score` (4a.4).

### 4a.7 Verification (4 shared CPUs, `-n 2`)

| Check | Command | Result |
|---|---|---|
| Full tier with coverage | `.venv/bin/python -m pytest -q -p no:cacheprovider -n 2 --ignore=tests/test_dashboard.py --cov=lab --cov-branch --cov-report=term-missing` | **1003 passed** (12 slow) in 47 s; **100% branch** of `lab/` (1390 statements, 402 branches, 0 missed); `fail_under = 100` reached. Osprey before the merge: 842 passed (fast tier), 76% |
| Deep | `HYPOTHESIS_PROFILE=deep .venv/bin/python -m pytest -q -p no:cacheprovider -n 2 -m "not slow" --ignore=tests/test_dashboard.py` | **991 passed** in 184 s |
| Mutation, `lab/validation/` | `HYPOTHESIS_PROFILE=fast mutmut run --max-children 2` with the `[tool.mutmut]` config, in a scratch copy | **1080 mutants, 1045 killed, 35 survived, all equivalent** (`tests/MUTATION_NOTES.md`): 96.8% raw, 100% of the non-equivalent. The one real survivor of the first run (an unpinned `percentiles` message) was killed by anchoring its `match=` |
| Demo | `scripts/demo.py --trials 8 --workers 2 --results-dir <scratch> --report-dir <scratch>` | Runs end to end in 25 s; no report kept (5.5) |
| Real data | `load_binance_klines` on the downloaded `BTCUSDT-1h-2025-06` and `BTCUSDT-1d-2017-08` zips | 720 rows from 2025-06-01 01:00 UTC; 15 rows from 2017-08-18 (first-row trades 3427) |
| Lint | `.venv/bin/ruff check` | All checks passed |
| Dashboard | `tests/test_dashboard.py` on its own; then the dashboard's TESTING.md parser on this file | 86 passed before this section was written; the parser reads this file with no warnings (27 bug-log rows, 5.1–5.7, 7 definition-of-done boxes) |

### 4a.8 Still open after the merge

- 5.4: mutation testing of the runner, search, models and data areas is not started. The hand breaks in 4a.6
  show those areas have survivors.
- 5.5: the full demo rerun, the committed report and the AGENTS.md figures. The numbers will change: the
  generator, the fill timing and the cost model all differ from the starter's.
- AGENTS.md (the owner's file, not edited in the merge) is out of date in two places: the `on_bar` example
  computes `vol_target / forecast_vol`, but forecasts are per bar now, so a strategy must annualise them first
  (× √365 for daily bars, × √8760 for hourly); and the starter-module table still describes the contract as
  `ret, position, turnover` with close fills (4a.5).
- `volume_z_20` saturation: a decision for `ml-researcher` (section 4, findings that are not bugs).
- `artifact.save_model` doesn't check that `features` match the columns the model was fit on, or that `kind`
  matches the model type (osprey's untested draft did both). Worth a check and a test (models owner).
- `test_models.py::test_walk_forward_predict_never_uses_future_labels` still has the weakness fixed in #27. The
  `test_train_props.py` version now pins the purge, so it can be tightened the same way or dropped.
- Live/backtest parity with Nautilus: `float(Price)` differs in the last bit from parsing the same decimal
  string for 4223 of 20000 random 2-decimal prices, so the batch path (catalog loader) must convert prices the
  same way as the live path (milestone 2).

---

## 5. Open work, in order

### 5.1 Verify the refactor that was in progress

**Merge status: done.** Osprey's `lab/validation/` was written with these helpers from the start
(kept over the starter's, section 4a.1); the full and deep tiers pass (section 4a.7).

Three helpers were pulled out of larger functions so they can be tested directly. The
fast validation tests passed after the change except the item in 5.2, but the full suite
was not rerun.

| Helper | Pulled from | Purpose |
|---|---|---|
| `montecarlo.stationary_bootstrap_indices(n, mean_block, rng)` | `block_bootstrap_drawdowns` | One stationary-bootstrap resample of positions; raises if `mean_block < 1` |
| `stats.column_sharpes(m)` | PBO's inner `block_sharpes` | Per-column Sharpe; 0 for a flat column |
| `stats.cscv_splits(n_blocks, max_combinations, seed)` | PBO | The in-sample block combinations, a distinct random subset when capped |

Run the full tier. Everything except the two failures in 5.2 must pass. Results must be
unchanged by the refactor: `block_bootstrap_drawdowns` and PBO outputs for a fixed seed
are identical to before (compare against `git stash` of the old version if in doubt).

### 5.2 Fix the two failures found by the deep profile

**Merge status: done** in osprey's kept files: A is bug #8, B is bug #9 (both `@example`s kept).

**A. Code bug: the flat-series check isn't scale invariant.**
Falsifying case: `r = [1e-12, 0, 0]`, `c = 2.0`. `sharpe(r) = 0` (its standard deviation
is under the absolute floor `_ABS_SD_TOL = 1e-12`) but `sharpe(2·r) = 0.577`. The
absolute floor means a strategy's Sharpe can change just by measuring returns in
different units.

Recommended fix: judge flatness relative to the series' own size, not an absolute number.
```python
_REL_SD_TOL = 1e-9

def _is_flat(sd, scale):
    """No real variation: spread is negligible next to the size of the values.
    All-zero data has scale 0 and sd 0, so it counts as flat."""
    return sd <= _REL_SD_TOL * scale
```
- In `sharpe` and `probabilistic_sharpe_ratio`: `scale = np.abs(r).max()`.
- In `column_sharpes`: `scale = np.abs(m).max(axis=0)` (one per column).
- Delete `_ABS_SD_TOL`.

Then:
- Add `@example(r=np.array([1e-12, 0.0, 0.0]), c=2.0)` to
  `test_sharpe_is_scale_invariant`, and the same scale-invariance property for
  `probabilistic_sharpe_ratio` and `column_sharpes`.
- Confirm the original bug #1 stays fixed: the near-constant series tests in
  `test_stats_props.py` must still pass.
- Log it in section 4 as bug #8.

**B. Test bug: the "present bar" tamper doesn't always change the high–low range.**
Falsifying case: `cut = 362`. The test lowers the close and only moves `low` if the new
close is below it. On a wide-range day it isn't, so high and low are unchanged and the
range-based volatility (`park_vol_20`) correctly doesn't move.

Fix the test, not the code: always widen the range, e.g.
```python
tampered.iloc[cut, col("close")] *= 0.7
tampered.iloc[cut, col("high")] *= 1.05
tampered.iloc[cut, col("low")] = min(tampered["low"].iloc[cut], tampered["close"].iloc[cut]) * 0.95
tampered.iloc[cut, col("volume")] *= 3
```
Add `@example(cut=362)` (and keep `cut=146`, the earlier drawdown case). Log it in
section 4 as a test bug.

Hypothesis also wrote `.hypothesis/patches/<date>--<hash>.patch` with these cases; you
can `git apply` it instead of typing the examples.

### 5.3 Close the mutation-testing gaps in `lab/validation/`

**Merge status: done.** Every test listed below is in osprey's `test_stats_exact.py`,
`test_splits_exact.py` and `test_montecarlo_exact.py`; the merge added the tests that killed the 7
real survivors of the comparer's run and `tests/MUTATION_NOTES.md`. Result in section 4a.7.

Mutation testing changes the code in small ways (`<` to `<=`, `1 − γ` to `1 + γ`) and
checks that some test fails. A mutant that survives is a change the tests can't see.

Baseline (fast profile, before 5.1–5.2): **492 killed, 3 timed out, 123 survived →
80%.** Several survivors are real blind spots. **Most important:** nothing in the fast
suite pins the expected-max-Sharpe formula. Only the slow calibration test checks it, so
a typo like `(1 + γ)` instead of `(1 − γ)` would ship.

Add these tests (a new file `tests/test_validation_exact.py` is fine):

**`stats.py`**
- `expected_max_sharpe`, pinned values from the Bailey & López de Prado formula
  `√V · ((1−γ)·Φ⁻¹(1 − 1/N) + γ·Φ⁻¹(1 − 1/(N·e)))`, γ = 0.5772156649:
  - N = 2, V = 1: equals `γ·Φ⁻¹(1 − 1/(2e))` ≈ 0.52 (proves N = 2 isn't treated as "no search")
  - N = 100, V = 1: ≈ 2.531; N = 1000, V = 1: compute and pin to `rel=1e-9`
  - Scales with √V: V = 4 gives exactly twice V = 1
  - Sanity: within 3% of the exact E[max of N standard normals] from numerical integration
    `∫ x · N · φ(x) · Φ(x)^(N−1) dx` for N = 100 and 1000
- `sharpe([0.01, 0.03]) == pytest.approx(√2)` (two observations are enough)
- `probabilistic_sharpe_ratio` on exactly 3 non-flat observations returns a value in (0, 1), not 0
- `annualized_sharpe(r) == sharpe(r) · √365` using the default argument
- `effective_trials` known answers:
  - columns `[1, 0, −1]` and `[1, −2, 1]` (exactly uncorrelated, 3 rows) → exactly 2.0
  - two identical columns plus one orthogonal column → `exp(entropy([1/3, 2/3]))` ≈ 1.8899
  - a single column → 1.0
- `deflated_sharpe_ratio`:
  - trial Sharpes `[0.1, 0.2, 0.3]` → `trial_sharpe_variance == 0.01` exactly
  - 2 trials → variance is computed (not 0)
  - 1 trial → variance 0 and `dsr == probabilistic_sharpe_ratio(best)`
  - exact key set of the returned dict; `best_sharpe_per_period == sharpe(best)`
- `column_sharpes`: exact values with `ddof=1` on a small hand matrix; a flat (all-zero)
  column gives exactly 0 with no warning
- PBO:
  - exact key set
  - a trial that never trades (all zeros) works, with no warning
  - **tie rule:** 3 trials and 2 blocks where the in-sample best is the out-of-sample
    median in both splits → `pbo == 1.0` (logit 0 counts as overfit). Build each block
    so trial Sharpes are known, e.g. a block's returns for a trial are `[a + 1, a − 1]`,
    so its Sharpe ∝ a.
  - `cscv_splits`: all combinations unique; capped count is exact; uncapped count = C(n, n/2)
  - default `n_blocks=16` gives `n_combinations == 4000`
- Pin every error message with `pytest.raises(ValueError, match=...)`.

**`splits.py`**
- `walk_forward` exact folds: `n=10, train_size=4, test_size=2` → tests `[4,5] [6,7]
  [8,9]`, rolling trains `[0..3] [2..5] [4..7]`; then the same with `step=1`, `purge=1`,
  `expanding=True` and `start=2`, each written out by hand
- The default `purge=0` means the train window ends right before the test block
- `train_size=0` and `test_size=0` raise
- `cpcv` defaults (no horizon, no embargo): train ∪ test = every row, every split
- `n_test_groups=0` raises
- `cpcv_paths` contract, "path j uses the group's j-th appearance": feed each split's
  predictions as its split index, then check every path cell equals the index of the
  j-th split containing that group

**`montecarlo.py`**
- `shuffled_trade_drawdowns([−0.1, −0.1, 0.5])`: every value ∈ {−0.19, −0.10};
  P(−0.19) ≈ 2/3 (binomial band); default length 5000; same seed identical, different
  seed different
- `bootstrap_trade_drawdowns([0.5, −0.1])` reaches ≈ −0.19 (drawing −10% twice requires
  replacement); the shuffle of the same trades never goes below −0.10
- `stationary_bootstrap_indices`: every index in [0, n); within a block each index is
  the previous + 1 (mod n); the share of block restarts ≈ 1/mean_block (binomial band);
  `mean_block=1` is an iid bootstrap; `mean_block < 1` raises
- `block_bootstrap_drawdowns` default length 2000
- `degrade_execution`:
  - zero turnover → every total equals `prod(1 + r) − 1` exactly
  - costs are drawn per period, not once per simulation: with zero returns, turnover 1
    and 100 periods, `std(totals) / |mean(totals)| < 0.3` (a single shared draw gives
    about 1)
  - the average extra cost ≈ `extra_cost_bps` (within 5%)
  - seeded reproducibility; default length 1000

**Known equivalent mutants (don't chase; list them in `tests/MUTATION_NOTES.md` with a
one-line reason):** `dtype=None` on inputs that are already floats; `fisher=None` (same
as `False`); mutations inside the pragma'd PSR guard; `len(combos) >= max_combinations`
(same set of combinations); in `cpcv`, `keep[...] = None` (same as `False` in a bool
array) and the embargo starting at `last − 1` (those rows are test rows anyway);
`block_id ± 1` and `starts` size `+ 1` in the bootstrap (same distribution); default
`seed` values.

**Target:** after these tests, rerun mutation testing on `lab/validation/`. Every
survivor is either killed or listed in `MUTATION_NOTES.md`. Expect ≥ 90% of non-equivalent
mutants killed.

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

`lab/runner/nautilus.py` (milestone 2) has to meet the same guarantees as the reference.
Split `test_backtester_props.py` into:
- `tests/contract/test_backtest_contract.py`: tests that hold for **any** runner (no
  look-ahead, accounting identity, drift and turnover, trade log equals portfolio at zero
  cost, cost linearity, interface). Parametrize over a `runner` fixture that today
  yields the reference `dip_buy`, and later the Nautilus runner running the same rules.
- `tests/test_reference_rules.py`: dip-buy specifics (stop, hold, vol-target, benchmarks).

Milestone 2 isn't done until the Nautilus runner passes the contract suite and the
parity test.

### 5.7 Raise the coverage floor

**Merge status: done:** `fail_under = 100`; branch coverage of `lab/` is 100%.

Once 5.1–5.3 are in, change `fail_under = 95` to `fail_under = 100` in `pyproject.toml`.
`# pragma: no cover` is allowed only with a comment proving the line can't run.

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
