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

> **Merged state (2026-11-19):** the starter code was merged into osprey. Which version of each
> file and test file was kept, and why, is in section 10; the table below describes the starter as
> it was.

Last full run (before the final refactor in 5.1): **159 tests passed, 100% branch
coverage of `lab/`** (`lab/data/synthetic.py` excluded; it's test scaffolding).

| File | What it proves |
|---|---|
| `test_validation.py`, `test_models.py`, `test_search.py` | The original 20 smoke and end-to-end tests |
| `test_splits_props.py` | Walk-forward and CPCV: no train/test overlap, purge and embargo gaps are exact, every row tested the right number of times, CPCV paths cover every row once, bad arguments raise |
| `test_stats_props.py` | Sharpe, PSR, expected max Sharpe, DSR, effective trials, PBO: known answers, invariances (scale, order), bounds, degenerate inputs |
| `test_montecarlo_props.py` | Max drawdown known answers and bounds; shuffle, bootstrap and block bootstrap shapes, ranges, determinism; degraded execution never helps |
| `test_features_leakage.py` | **Look-ahead:** changing any future bar never changes a past feature; every feature uses the newest bar; price and volume scale invariance; hand-computed values for each feature family; live `FeatureBuffer` equals backtest features on every bar; cross-sectional ranks |
| `test_labels_props.py` | Every label equals a hand computation over exactly the right future window; labels never appear as features; baselines use only the past |
| `test_train_props.py` | Metric known answers (QLIKE punishes under-forecasting risk more); constant forecasters handled; CPCV scores every forecaster on identical rows (an oracle scores perfectly); walk-forward forecasts can't see future labels or future features; reproducible |
| `test_artifacts_loaders.py` | Model files round-trip; a tampered model file is refused; `ModelPredictor` matches the raw model for all three model kinds and ignores column order; Kraken/Binance loaders (seconds, ms, µs, headers, duplicates, bad prices); resampling; synthetic data validity |
| `test_backtester_props.py` | **Reference backtester:** no look-ahead; exact accounting identity; positions drift as coin units between trades; trade log matches portfolio returns exactly at zero cost; costs change returns by exactly turnover × rate; stop-loss, hold period and vol-target sizing on hand-built paths; benchmarks; interface errors |
| `test_search_props.py` | Parameter units; objective formula and the too-few-trades penalty; failing trials logged while the search continues; resume; orphan files from crashed workers ignored; reproducibility; stable region prefers plateaus over spikes; **walk-forward decisions can't see their own test block**; report and gates (missing numbers fail, never pass) |
| `test_calibration.py` (slow) | On pure noise: PSR false-positive rate ≈ 5% (normal and fat-tailed); expected max Sharpe matches simulation; picking the best of 100 noise strategies fools PSR > 80% of the time but DSR < 8%; DSR power on a real edge; PBO ≈ 0.5 under the null and low with a real edge; block bootstrap keeps volatility clusters |

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
| 8 | `stats._is_flat` (5.2A) | The absolute floor `_ABS_SD_TOL = 1e-12` made Sharpe depend on units: `sharpe([1e-12, 0, 0]) = 0` but `sharpe(2r) = 0.577` | Osprey's relative flatness on unit-scaled data; 0.7319 for every scale 1e-300..1e300 (merge: osprey's stats.py kept) |
| 9 | `test_each_feature_reacts_to_the_present_bar` (5.2B, **test** bug) | Lowering only the close left high/low unchanged on a wide-range day, so `park_vol_20` correctly did not move (cut=362) | Osprey's test always widens the range; `@example(cut=362)` and `(cut=146)` kept. They were found on the starter's generator; on osprey's they are ordinary cuts |
| 10 | `stats` PBO, expected max Sharpe, PSR | PBO broke in-sample ties with `argmax` (PBO depended on column order); expected max Sharpe went negative for 1 < N ≤ 1.28 (DSR more lenient than PSR); the PSR `var_term` guard **does** fire in floating point and returned 0 above the benchmark; `column_sharpes` gave NaN plus warnings for < 2 rows; `effective_trials` raised `LinAlgError` on near-flat columns | Osprey's stats.py: ties score the worst OOS candidate, EMS floored at 0, guard handled and tested, < 2 rows give 0, flat columns dropped before the eigen-decomposition |
| 11 | `splits.walk_forward`, `montecarlo` | `step=-1` looped forever and `step=0` was silently replaced; `block_bootstrap_drawdowns([])` raised `IndexError`; `degrade_execution` drew an unbounded Exponential cost, so a period could lose more than 100% | Osprey's modules: every argument validated; empty input gives zero drawdowns; cost drawn from Uniform(0, 2) × bps, multiplicative, never below -100% |
| 12 | `reference.py` timing (hard rule 4) | A decision at close t filled at close t, the price the signal read; Nautilus fills at the next open | Osprey's reference fills at the open of t+1 (contract suite, `tests/contract/`) |
| 13 | `reference.py` accounting | With costs on, the trade log differed from the portfolio by up to 7.6e-4 per trip (fees on the entry notional); buy-and-hold logged the gross price change; fees were paid from negative cash (coin worth 1.0016 of the portfolio at position 1.0) | Osprey's engine: trade log equals the portfolio with costs on, fees cut the coin units, spot only |
| 14 | `reference.py` inputs and costs | No bar or param validation (NaN close, reversed index, typo `stop_loss` all ran); gas as bps of a fixed $1000 notional times turnover; slippage clamped above the table; `Costs()` ignored `config/costs.yaml` | Osprey: strict validation; per-fill gas in USD, size-based slippage on the compounding portfolio, `Costs.from_yaml()` |
| 15 | `loaders.py` | Mixed ms/µs rows in one file put the ms rows in 1970; NaN prices, high < low, close > high and negative volume loaded silently; `resample` kept partial buckets; index was bar OPEN time (AGENTS.md says close time) | Osprey's loaders: per-value unit detection, bad ticks dropped and counted, complete buckets only, close-time index |
| 16 | `online.FeatureBuffer` | Crashed on Nautilus `Price`/`Quantity` (the AGENTS.md `on_bar` example); accepted out-of-order and invalid bars; live features matched batch only to rtol 1e-9 | Osprey's FeatureBuffer: `float()` inputs, validation, bit-exact parity on every bar |
| 17 | `artifact.train_final` + `online.ModelPredictor` (vol) | **The deployed vol model was not the validated one**: CPCV and walk-forward scored the EWMA-anchored correction, but `train_final` fit log(vol) from scratch and the predictor returned `exp(pred)` (the variant that lost to EWMA). The starter test pinned `exp(model.predict)` | `train.AnchoredVolModel` used by `_fit_predict`, `train_final` and `ModelPredictor`; `test_saved_vol_model_is_the_model_that_was_validated`; the old assertion changed (it pinned the bug) |
| 18 | `loaders._read_fields` (osprey) | `on_bad_lines="skip"` took the first line's width: a first line without the trades field silently dropped every later full line, and over-wide lines vanished uncounted; pandas also shifts columns when the FIRST line is over-wide | Lines read whole and split per line: short lines padded, over-wide lines dropped and counted in `dropped_bad`; regression tests |
| 19 | `lab/config.splits` (osprey) | Documented selection `start <= ts < end + 1 day` is off by one bar under close-time labels (the last train day fell into validate) | `start < ts <= end + 1 day`, as `config.in_window`; `tests/test_config.py` |
| 20 | `search.stability.stable_region` | When k ≥ the number of trials every neighbourhood mean is the same number, and the pick came down to summation-order rounding (a last-bit stats change moved the chosen trial) | Neighbourhood scores sorted before averaging; ties go to the best own score; property test |
| 21 | merge integration | Osprey's runner keeps arrays and a fill frame in `attrs`; pandas copies them onto `res["ret"]`, so the starter's `study.py` `to_parquet` failed every trial and `walkforward`/demo `pd.concat` raised | The search layer strips `attrs` before saving or concatenating (runner-agnostic: the Nautilus runner needs it too) |
| 22 | `reference.dip_buy` (osprey) + demo units | Osprey's `dip_buy` silently ignored a `pred_vol` column, and osprey's vol forecasts are per bar while `vol_target` is annualised: the demo's vol-targeted variant would never have used the model | `vol_col` param (forecast at the signal close; NaN/inf fall back to realised vol; ≤ 0 means no entry); demo annualises the forecast; starter's sizing and model-column look-ahead tests ported |

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

**Consequence of fixes 4–6:** every number from the old demo is stale. Rerun it (5.5).

---

## 5. Open work, in order

### 5.1 Verify the refactor that was in progress

**Merge status: done.** Osprey's `lab/validation/` was written with these helpers from the start
(kept over the starter's, section 10.1); the quick, deep and slow tiers pass (section 10.4).

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
real survivors of the comparer's run and `tests/MUTATION_NOTES.md`. Result in section 10.4.

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

**Merge status: not started.** The test files named below changed in the merge (section 10.2).

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
scratch directory, section 10.4). The full rerun, the committed report and the AGENTS.md figures
are still to do.

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
`tests/test_reference_rules.py`.

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

- [ ] Full, deep and slow tiers pass
- [ ] Bug log updated, including 5.2A and 5.2B
- [ ] Mutation targets met for every area in 5.4; `tests/MUTATION_NOTES.md` lists every accepted survivor with a reason
- [ ] Branch coverage 100% with `fail_under = 100`
- [ ] Demo rerun; the report and AGENTS.md figures updated
- [ ] Contract suite split out and parametrized over runners
- [ ] `uv run ruff check` clean

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

---

## 10. Merge log: starter code into osprey (2026-11-19)

Owner's instruction: compare the starter with what osprey built, bring over what is missing
(`lab/search`, `lab/models/train.py` and `artifact.py`, and their tests), keep whichever version of
each file is better tested, and log the choices here. Four comparers ran each side's tests against the
other side's code, with name-only shims, before anything was merged; their evidence is summarised in
the "why" column. Starter files were copied byte for byte first; every later edit is listed.

### 10.1 Code: which version was kept

| File | Kept | Why | Edits made in the merge |
|---|---|---|---|
| `lab/validation/stats.py` | osprey | 5.2A fixed, every 5.3 known answer pinned, deep passes, mutation 96.3% raw (starter 80%). Osprey's tests caught 6 starter bugs (#8, #10); the starter's caught none in osprey | `probability_of_backtest_overfitting = pbo` (the starter's name, used by `search/report.py` and `test_calibration.py`) |
| `lab/validation/splits.py` | osprey | Full 5.3 set, every argument validated, no negative-step hang (#11) | `Fold(NamedTuple)` returned by `walk_forward`: the starter's `walkforward.py` reads `.train`/`.test`; folds still unpack as pairs |
| `lab/validation/montecarlo.py` | osprey | 100% branch (starter 96%), bounded degraded execution, empty input handled (#11) | `percentiles(values, qs)` (starter helper used by `report.py`), validated and tested |
| `lab/runner/interface.py` | osprey | Stricter contract: bar and result validators, `cost` column, `n_trades`, next-open execution written down | None (it was at 75% branch: rejection tests added) |
| `lab/runner/reference.py` | osprey | Fills at the next open (hard rule 4), trade log = portfolio with costs on, the costs.yaml model, validation, random-entry and monthly 50/50 benchmarks; 303 tests fast and deep. Osprey's tests found #12-#14 in the starter; the starter's found no osprey bug | `vol_col`: size from a model's annualised forecast column (#22) |
| `lab/models/features.py`, `labels.py`, `baselines.py` | osprey | Every section 3 guarantee incl. the 5.2B fix, all 15 features hand-checked, bit-exact live parity, bar validation; per-bar vol units (the starter annualised with √365 whatever the bar size, wrong for hourly bars) | None |
| `lab/models/online.py` | merged | Osprey's `FeatureBuffer` (#16) and the starter's `ModelPredictor` (owner's instruction) | `ModelPredictor` takes any mapping (`FeatureBuffer.latest()` is a dict), reads features by name, raises on a missing one instead of passing NaN; "vol" goes through `AnchoredVolModel` (#17) |
| `lab/models/train.py` | starter | Owner's instruction; osprey's draft was untested (15% covered) | `VOL_ANCHOR = "ewma_vol_20"`; cpcv 3-tuple unpacking; `AnchoredVolModel` shared by `_fit_predict` (same arithmetic as before) and `train_final` (#17) |
| `lab/models/artifact.py` | starter | Owner's instruction; osprey's draft was untested (19%) | `train_final("vol")` fits `AnchoredVolModel` (#17); `datetime.UTC` (ruff) |
| `lab/search/*` (7 files) | starter | Missing in osprey | `objective.py` returns a fresh Series without attrs, `walkforward.py` drops attrs before `concat` (#21); `report.py`: DSR is NaN, so its gate fails, when no study kept 2+ completed trials (osprey's DSR rejects an empty trial list; the starter silently used variance 0, i.e. no deflation); `stability.py` deterministic ties (#20); `# noqa: B008` on the never-mutated `SearchConfig()` defaults |
| `lab/data/loaders.py` | osprey | Close-time index, bad ticks dropped and counted, per-value units, verified on the real Binance zips; the starter had 4 defects (#15) | Per-line field counting (#18) |
| `lab/data/synthetic.py` | osprey | Either generator keeps every suite green (147/147 and 337/338 in swap runs); osprey's adds `shuffled_market`, input validation and the `ts` index name | None |
| `lab/config.py` | osprey (no starter version) | Used by `reference.py` | Selection rule fixed and `in_window` added (#19) |
| `tests/conftest.py` | osprey | Superset: the same `market`, `btc`, `features` fixtures | None |
| `pyproject.toml` | osprey + the starter's `[tool.mutmut]` | | `tests_dir` = the six kept validation test files; `only_mutate`; `also_copy` adds `config`; `fail_under` 95 → 100 (5.7) |
| `.gitignore` | osprey | | `.pytest_cache/`, `.ruff_cache/` added (as AGENTS.md lists them) |
| `scripts/demo.py` | starter | Missing in osprey | osprey names, `drop`/`stop` as fractions; `synthetic_market(3400, seed, start="2017-01-01")`; 2× costs via `Costs.from_yaml().stressed(2.0)`; the vol-targeted variant uses `vol_col` with the per-bar forecast annualised (#22); long-run baseline = 60-bar rolling vol, as before; the EWMA baseline is the span-20 feature (relabelled from "RiskMetrics", which is λ 0.94); regime baseline `eff_ratio_20` (continuous, so AUC stays meaningful); the 50/50 benchmark rebalances monthly (AGENTS.md); `--results-dir` and `--report-dir` |

### 10.2 Tests: which files were kept

| Test file | Kept | Notes |
|---|---|---|
| `test_stats_*`, `test_splits_*`, `test_montecarlo_*` (`_props` and `_exact`) | osprey | Ported from the starter: PSR penalises negative skew and fat tails; PSR rises with more data; effective trials of two clone groups ≈ 2 and of clones vs independent columns; PBO ≈ ½ on noise and < 0.1 with one real edge; the sorted order is the worst shuffle; adding a loss never reduces drawdown. Added: 5 mutation-survivor tests, `Fold`, `percentiles` and alias tests |
| `test_stats_props.py`, `test_splits_props.py`, `test_montecarlo_props.py` (starter) | dropped | Superseded; the starter's stats file fails deep on 5.2A |
| `test_validation.py` (starter) | dropped | 9 smoke tests, 8 of them covered by osprey's exact and props tests; the PBO noise/edge and effective-trials realistic-size tests were ported (above). It needed the old `label_horizon`, `cpcv_n_paths` and `cpcv_paths` APIs |
| `test_calibration.py` (starter, slow) | starter, unchanged | Osprey had none (section 3 requires them); 12/12 pass on osprey's modules |
| `tests/contract/*`, `test_reference_rules.py`, `test_costs.py` | osprey | Added: 19 `validate_result` rejection cases and negative volume (the starter's `test_check_result_rejects_bad_output`); a runner entry that sizes from a model column; the starter's model-sizing tests (3 sizes, NaN/inf fallback, ≤ 0 forecast never trades), model-column look-ahead, and its drawn-parameter properties on 400-bar windows |
| `test_backtester_props.py` (starter) | dropped | The 5.6 split is done in osprey; its assertions encode close fills and additive costs. Everything runner-agnostic or dip-buy-specific in it is covered or ported (row above) |
| `test_features_leakage.py`, `test_labels_props.py` | osprey | Added: the starter's tolerance criterion in the present-bar test, `test_feature_ranges`, the volume-z bound |
| `test_features_leakage.py`, `test_labels_props.py` (starter) | dropped | Open 5.2B bug; 6 of 15 features hand-checked |
| `test_models.py`, `test_train_props.py` | starter | Osprey names (`compute_features`, `FEATURES`, bars-based labels and baselines). Per-bar units: the "flat" forecaster 0.5 (annualised) became 0.5/√365 per bar, the same level, so the test keeps its meaning. `test_online_buffer_matches_batch_features` dropped: osprey's bit-exact every-bar parity tests supersede it |
| `test_artifacts.py` (from `test_artifacts_loaders.py`) | starter, artifact part | Loader and synthetic parts dropped (superseded by `test_loaders.py` and `test_synthetic.py`; the realism bands moved to `test_synthetic.py`). The vol predictor assertion changed from `exp(model.predict)` to `model.predict`: the old one pinned bug #17. Added: deployed vol forecast = validated forecast; the predictor takes the live buffer's dict and rejects a missing feature |
| `test_search.py`, `test_search_props.py` | starter | Osprey parameter names (`drop`, `hold`, `stop`; fractions over the same ranges); `synthetic_market(N, ...)`; `test_reference_costs_reduce_returns` rewritten for osprey's `Costs` and next-open fills (same three checks); the tampered closes in the walk-forward look-ahead test keep high ≥ close ≥ low; the log-parameter test checks `params_drop` in [0.02, 0.30] instead of `params_drop_pct` in [2, 30] (unit change only). Added: the tie-break property (#20) |
| `test_loaders.py`, `test_synthetic.py` | osprey | Added: short and over-wide line regressions (#18), real Binance rows (2017 ms and 2025 µs, as CSV and as .zip), realism bands |
| `test_config.py` | new | `splits()` and the close-time window rule (#19) |

### 10.3 Where the merge departed from a comparer

- **PBO name and `percentiles`.** The validation comparer suggested editing `report.py` and
  `test_calibration.py` to call `pbo` and `np.percentile`. The merge rule (thin, tested compatibility
  in the kept module rather than forking starter code) won: one alias and one helper, so those starter
  files keep their calls.
- **Empty trial list in the report.** The comparer suggested `trial_sharpes or [0.0]`, which reproduces
  the starter's undeflated DSR. The merge reports DSR as missing (NaN) instead, so the gate fails:
  missing numbers fail, never pass.
- **`volume_z_20`.** Kept as the raw-volume z-score instead of switching to log volume: log volume
  saturates too, only more slowly (section 4, findings that are not bugs).
- **`test_regime_and_ranking_baselines`** (persistence score equals the efficiency feature) was not
  ported: the demo now uses the `eff_ratio_20` feature column directly, so there is no separate function
  to test.

### 10.4 Verification (4 shared CPUs, `-n 2`, `tests/test_dashboard.py` excluded)

| Check | Command | Result |
|---|---|---|
| Quick tier | `.venv/bin/python -m pytest -q -p no:cacheprovider -n 2 -m "not slow" --ignore=tests/test_dashboard.py` | **988 passed** in 41 s (osprey before the merge: 842) |
| Coverage | the same with `--cov=lab --cov-branch --cov-report=term-missing` | **100% branch** of `lab/` (1390 statements, 402 branches; `synthetic.py` omitted); `fail_under = 100` holds |
| Deep | `HYPOTHESIS_PROFILE=deep` on `tests/contract` and every new or changed test file (17 files) | **856 passed** in 173 s. Edited after that run: only non-property assertions (DSR check in the too-few-trials report test, anchored `percentiles` messages, docstrings) |
| Slow | `-m slow tests/test_calibration.py` | **12 passed** in 18 s |
| Mutation, `lab/validation/` | `mutmut run --max-children 2` with the `[tool.mutmut]` config, fast profile, scratch copy | **1080 mutants, 1045 killed, 35 survived, all equivalent** (`tests/MUTATION_NOTES.md`): 96.8% raw, 100% of the non-equivalent |
| Demo | `scripts/demo.py --trials 8 --workers 2 --results-dir <scratch> --report-dir <scratch>` | Runs end to end in 25 s. No report kept (5.5: the full rerun and the AGENTS.md figures are still to do) |
| Lint | `.venv/bin/ruff check lab tests scripts/demo.py` | Clean |

Not done in the merge: mutation testing of the runner, search, models and data areas (5.4); the full demo
rerun and the docs update (5.5).

### 10.5 Lost-guarantee audit (after the merge)

Every test in the dropped or replaced files (the starter's `test_backtester_props.py`, `test_validation.py`,
`test_stats_props.py`, `test_splits_props.py`, `test_montecarlo_props.py`, `test_features_leakage.py`,
`test_labels_props.py`, the loader and synthetic part of `test_artifacts_loaders.py`, the dropped
`test_online_buffer_matches_batch_features`, and every starter test edited in the merge) was mapped to a
kept test. Where the mapping was not obvious, the code was broken by hand in a scratch copy to see a kept
test fail. Osprey dropped no test file (its drafts of `train.py` and `artifact.py` had no tests). Three
guarantees were not pinned any more, or never were; each is restored with a test that fails on the broken code:

| Guarantee | Was pinned by | Hand break that the kept suite let through | Restored by |
|---|---|---|---|
| A hold period is exact for long holds | starter `test_hold_days_is_exact` (holds 6, 10, 25) | `hold` capped at 10 bars: 281 runner tests passed (osprey's exact test stopped at hold 5; the drawn-params property checks identities, not exit bars) | `test_hold_period_exits_after_hold_bars` also runs holds 6, 10 and 25 |
| A walk-forward fold's search never sees its test block | starter `test_fold_decisions_cannot_see_their_test_block` | Searching on train + test block: passed. On osprey's runner (fills at the next open) the close-only tamper no longer moved the chosen parameters; the same break fails the test on the starter's code | The test also requires every logged trial of the fold's study (params, score, Sharpe, trade count) to be identical; searching one bar into the test block now fails too |
| Walk-forward model training waits until a label's whole window has passed (the horizon purge) | nothing (a gap in both suites; only the trial-count test `test_walk_forward_waits_until_enough_labels_are_known` failed, incidentally) | `usable = train_pos < block_start` (no purge) and the off-by-one `< block_start - horizon + 1`: both leak-tests passed, because they corrupted labels by row (`>= cut`), not by when they become known | `test_walk_forward_predictions_cannot_see_future_labels` corrupts every label not fully known at `cut` (rows from `cut - horizon`); both breaks fail it |

Checked and still pinned (hand break failed a kept test): a model forecast read at the fill bar instead
of the signal close; an open round trip left out of the trade log. Starter guarantees that no longer apply,
by design: `Costs(per_side_bps=...)`, `.bps` and `from_config` (osprey's `Costs` reads `config/costs.yaml`,
`tests/test_costs.py`); NaN-tolerant `sharpe`, `max_drawdown` and `effective_trials` on 1-D input (osprey
rejects non-finite or misshaped input with `ValueError`; `report.py` drops NaN rows first); bad prices raising
in the loaders (osprey drops and counts them); bars indexed by open time (osprey: close time);
`rel_ret_20` and the `benchmark` argument of the cross-sectional features (osprey has rank features only);
`persistence_trend_score` (10.3).

Rerun after these three test changes (`-n 2`, `tests/test_dashboard.py` excluded): quick **991 passed** in
27 s; full with `--cov=lab --cov-branch` **1003 passed** in 48 s, 100% branch; deep (`HYPOTHESIS_PROFILE=deep
-m "not slow"`, the whole suite) **991 passed** in 190 s, plus the two files edited after it (with
`test_reference_rules.py`) **123 passed** in 15 s; slow **12 passed** in 12 s; `ruff check lab tests scripts`
clean. `tests/test_dashboard.py` on its own: **86 passed**.
