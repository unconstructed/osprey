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

Findings that are not bugs (keep them in mind):

- **DSR is strict.** With 50 trials, a genuinely good strategy (true annual Sharpe 2.5)
  passes DSR ≥ 0.95 only ~46% of the time with 2.7 years of daily data, and > 80% with
  5.5 years. Short histories will reject some real edges. That's the price of not
  approving luck.
- **The PSR `var_term <= 0` guard can never fire.** `var_term = (1 − skew·SR/2)² +
  (kurt − 1 − skew²)·SR²/4 ≥ 0` because kurtosis ≥ skew² + 1. It's marked
  `# pragma: no cover` with that explanation.

**Consequence of fixes 4–6:** every number from the old demo is stale. Rerun it (5.5).

---

## 5. Open work, in order

### 5.1 Verify the refactor that was in progress

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
