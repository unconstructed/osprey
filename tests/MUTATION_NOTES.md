# Mutation testing notes: accepted survivors

TESTING.md 5.3: every surviving mutant is either killed by a test or listed here with the reason it can't
change a result. Names are mutmut 3.8.1's (`uv run mutmut show <name>` prints the diff).

## `lab/validation/` (2026-11-19, merge of the starter code)

Run: the `[tool.mutmut]` config in `pyproject.toml` (`only_mutate` = stats.py, splits.py, montecarlo.py;
the six validation test files), `HYPOTHESIS_PROFILE=fast`, `--max-children 2`.
Result: **1080 mutants, 1045 killed, 0 timed out, 35 survived, all equivalent**: 96.8% raw, 100% of the
non-equivalent mutants. The comparer's pre-merge run had 39 survivors of 1049, 7 of them real; the merge
added the tests that kill those 7 and anchored the messages of the new `percentiles` helper (its "XX"
string mutant survived an unanchored `match=`).

### Equivalent: dtype on inputs that are converted anyway (12)

`np.asarray(x, dtype=float)` mutated to `dtype=None` or no dtype. Every caller passes numbers, and each
function turns them into floats before any arithmetic whose result could differ (division by the largest
value, `1.0 + r`, comparisons with float bounds), so the outputs are identical.

- `stats.x__vector__mutmut_3`, `stats.x__vector__mutmut_5`
- `stats.x__matrix__mutmut_3`, `stats.x__matrix__mutmut_5`
- `splits.x_cpcv_paths__mutmut_44`, `splits.x_cpcv_paths__mutmut_46`
- `montecarlo.x__returns__mutmut_3`, `montecarlo.x__returns__mutmut_5`
- `montecarlo.x_degrade_execution__mutmut_13`, `montecarlo.x_degrade_execution__mutmut_15`
- `montecarlo.x_percentiles__mutmut_3`, `montecarlo.x_percentiles__mutmut_5`

### Equivalent: a flag given None, or a default removed, meaning the same as the original (7)

- `stats.x_probabilistic_sharpe_ratio__mutmut_38`: `kurtosis(fisher=None)` is falsy, i.e. Pearson
  kurtosis, the same as `fisher=False`.
- `stats.x_effective_trials__mutmut_27`: `np.corrcoef(rowvar=None)` is tested with `not rowvar`, the same as
  `False`.
- `stats.x_cscv_splits__mutmut_38`, `stats.x_cscv_splits__mutmut_50`: `rng.choice(replace=None)` is falsy,
  the same as `replace=False`.
- `montecarlo.x_bootstrap_trade_drawdowns__mutmut_29`: `replace=True` removed; it is `rng.choice`'s default.
- `splits.x_cpcv__mutmut_54`, `splits.x_cpcv__mutmut_62`: `keep[...] = None` in a boolean array stores
  `False`.

### Equivalent: `zip(..., strict=...)` after an explicit length check (6)

The lengths are checked and a ValueError raised before the loop, so `strict` can never trigger.

- `splits.x_cpcv_paths__mutmut_37`, `_40`, `_41` (`strict=None`, removed, `False`)
- `montecarlo.x_degrade_execution__mutmut_61`, `_64`, `_67` (same three)

### Equivalent: the same distribution of resamples (4)

`stationary_bootstrap_indices` draws a uniform random start per block and walks forward by 1 mod n. These
mutants change only a deterministic shift of the start, or a probability-zero event, so every property and
distribution is unchanged (and any seed is a valid draw).

- `montecarlo.x_stationary_bootstrap_indices__mutmut_16`: `<` vs `<=` against a continuous uniform draw
  (equal with probability ~2^-53; for `mean_block=1` both are always true).
- `montecarlo.x_stationary_bootstrap_indices__mutmut_25`: `block_id - 2` pairs each block with the previous
  block's random start and first position: still a uniform start, still consecutive within the block.
- `montecarlo.x_stationary_bootstrap_indices__mutmut_32`: `rng.integers(n)` draws the same values as
  `rng.integers(0, n)`.
- `montecarlo.x_stationary_bootstrap_indices__mutmut_37`: `+` instead of `-` adds a deterministic shift to a
  uniform random start modulo n: the same distribution.

### Equivalent: other (6)

- `montecarlo.x__drawdown__mutmut_4`: starting equity 2.0 instead of 1.0 scales the whole curve; drawdown is a
  ratio to the running peak, so it is unchanged.
- `stats.x_expected_max_sharpe__mutmut_10`: `n_trials <= 1` vs `< 1`: at exactly 1 the formula gives
  `Phi^-1(0) = -inf`, floored at 0, the same 0.0 as the early return.
- `stats.x_cscv_splits__mutmut_1`: default `seed` 0 vs 1. Any seed gives a valid distinct random subset; no
  seed is more correct (TESTING.md lists default seeds as equivalent).
- `stats.x_cscv_splits__mutmut_17`: `total <= max_combinations` vs `<`: at equality, sampling all `total`
  combinations without replacement and sorting them returns the same full list as enumerating them.
- `stats.x_cscv_splits__mutmut_26`, `stats.x_cscv_splits__mutmut_27`: the threshold that chooses between
  "enumerate then sample" and "draw random halves, reject repeats". Both return exactly `max_combinations`
  distinct, sorted, seeded combinations (the contract the tests pin); only the random stream and the speed
  differ.

Total: 12 + 7 + 6 + 4 + 6 = 35.
