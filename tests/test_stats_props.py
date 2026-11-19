"""Property tests for lab/validation/stats.py (TESTING.md section 3, 5.2A and bug log #1, #2).

Sharpe, PSR, expected max Sharpe, DSR, effective trials, column Sharpes, CSCV splits and PBO: known answers,
invariances (scale, order, sign, column order), bounds and degenerate inputs.

Input strategies
- ``raw_returns``: any finite floats in [-10, 10], including subnormal, tiny and near-constant values. Used for
  bounds, never-NaN properties and the bit-exact power-of-two scaling property (multiplying by 2**k, k >= 0,
  is exact in floating point, so the code must return identical bits).
- ``nice_returns``: integers in [-1000, 1000] times one power of ten (1e-15 .. 10). Either exactly flat (all
  equal) or sd / max|r| >= ~1e-5, so rounding differences between equivalent computations (another scale,
  another order) stay below ~1e-11 and the flat decision never sits on its threshold. Magnitudes go down to
  1e-15, under the old 1e-12 absolute floor that made Sharpe depend on units (5.2A). Tolerances below are
  rel=1e-9 plus abs=1e-9 in Sharpe units, derived from that conditioning bound.
"""

from __future__ import annotations

import math
import warnings

import numpy as np
import pytest
from hypothesis import example, given
from hypothesis import strategies as st
from hypothesis.extra import numpy as hnp

from lab.validation.stats import (
    _REL_SD_TOL,
    column_sharpes,
    cscv_splits,
    deflated_sharpe_ratio,
    effective_trials,
    expected_max_sharpe,
    pbo,
    probabilistic_sharpe_ratio,
    sharpe,
)

TOL = {"rel": 1e-9, "abs": 1e-9}
SR_BOUND = (1 / _REL_SD_TOL) * (1 + 1e-12)  # |mean| <= max|r| and sd > 1e-9 * max|r| when not flat

finite = st.floats(-10, 10, allow_nan=False, allow_infinity=False)
raw_returns = hnp.arrays(np.float64, st.integers(0, 60), elements=finite)


def _scaled(ints, k) -> np.ndarray:
    return np.asarray(ints, dtype=float) * 10.0**k


nice_returns = st.builds(
    _scaled, st.lists(st.integers(-1000, 1000), min_size=2, max_size=60), st.integers(-15, 1)
)
nice_varied = nice_returns.filter(lambda r: len(r) >= 3 and len(set(r.tolist())) > 1)  # n >= 3, not flat
positive_scale = st.floats(1e-3, 1e3)


@st.composite
def nice_matrices(draw, min_rows=2, max_rows=30, min_cols=1, max_cols=6):
    """Integer matrix times a power of ten chosen PER COLUMN (columns of very different sizes side by side)."""
    rows = draw(st.integers(min_rows, max_rows))
    cols = draw(st.integers(min_cols, max_cols))
    ints = draw(hnp.arrays(np.int64, (rows, cols), elements=st.integers(-1000, 1000)))
    exps = draw(hnp.arrays(np.int64, cols, elements=st.integers(-15, 1)))
    return ints.astype(float) * 10.0 ** exps.astype(float)


raw_matrices = hnp.arrays(np.float64, st.tuples(st.integers(0, 30), st.integers(1, 6)), elements=finite)


def _no_warnings(fn, *args, **kwargs):
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        return fn(*args, **kwargs)


# --------------------------------------------------------------------------------------------------------
# sharpe
# --------------------------------------------------------------------------------------------------------


@given(r=nice_returns, c=positive_scale)
@example(r=np.array([1e-12, 0.0, 0.0]), c=2.0)  # 5.2A: was 0 under the absolute floor, 0.577 at 2x
def test_sharpe_is_scale_invariant(r, c):
    assert sharpe(c * r) == pytest.approx(sharpe(r), **TOL)
    assert sharpe(c * r, ddof=0) == pytest.approx(sharpe(r, ddof=0), **TOL)


@given(r=raw_returns, k=st.integers(0, 64))
@example(r=np.array([1e-12, 0.0, 0.0]), k=1)
@example(r=np.array([1e-160, 0.0, 0.0]), k=60)  # squares of 1e-160 underflow unless computed in unit scale
@example(r=np.array([5e-324, 1e-323, 0.0]), k=3)  # subnormal input
def test_sharpe_power_of_two_scaling_is_bit_exact(r, k):
    assert sharpe(r * 2.0**k) == sharpe(r)


def test_sharpe_of_tiny_returns_is_not_zero():
    assert sharpe([1e-12, 0.0, 0.0]) == pytest.approx(1 / math.sqrt(3), rel=1e-12)
    assert sharpe([1e-300, 0.0, 0.0]) == pytest.approx(1 / math.sqrt(3), rel=1e-12)


@given(r=raw_returns)
def test_sharpe_flips_sign_under_negation(r):
    assert sharpe(-r) == -sharpe(r)


@given(r=nice_returns, data=st.data())
def test_sharpe_is_order_invariant(r, data):
    perm = data.draw(st.permutations(range(len(r))))
    assert sharpe(r[list(perm)]) == pytest.approx(sharpe(r), **TOL)


@given(r=raw_returns)
def test_sharpe_is_finite_and_bounded(r):
    value = _no_warnings(sharpe, r)
    assert math.isfinite(value)
    assert abs(value) <= SR_BOUND


@given(value=finite, n=st.integers(0, 500))
def test_sharpe_of_a_constant_series_is_zero(value, n):
    # Bug #1: np.full(n, 0.01) has rounding noise in its mean (~1e-18), which used to give Sharpe ~8e15.
    assert sharpe(np.full(n, value)) == 0.0


@given(value=finite, noise=st.lists(st.integers(-1000, 1000), min_size=2, max_size=200))
def test_sharpe_of_a_near_constant_series_does_not_explode(value, noise):
    # Relative wiggle <= 1000 ulps (~2e-13) is rounding noise, not variation: flat, Sharpe exactly 0.
    r = value * (1.0 + np.asarray(noise, dtype=float) * np.finfo(float).eps)
    assert sharpe(r) == 0.0


@pytest.mark.parametrize("growth", [1e-4, 1e-3, 0.01, -0.002])
def test_sharpe_of_a_constant_growth_equity_curve_is_zero(growth):
    equity = (1 + growth) ** np.arange(400)
    r = equity[1:] / equity[:-1] - 1  # all ~growth, with rounding noise
    assert np.std(r) > 0  # genuinely near-constant, not constant
    assert sharpe(r) == 0.0
    assert probabilistic_sharpe_ratio(r) == 0.0


# --------------------------------------------------------------------------------------------------------
# probabilistic_sharpe_ratio
# --------------------------------------------------------------------------------------------------------


@given(r=nice_returns, c=positive_scale)
@example(r=np.array([1e-12, 0.0, 0.0]), c=2.0)  # 5.2A
def test_psr_is_scale_invariant(r, c):
    assert probabilistic_sharpe_ratio(c * r) == pytest.approx(probabilistic_sharpe_ratio(r), **TOL)


@given(r=raw_returns, k=st.integers(0, 64), bench=st.floats(-2, 2))
@example(r=np.array([1e-12, 0.0, 0.0]), k=1, bench=0.0)
@example(r=np.array([1e-300, 0.0, 0.0]), k=60, bench=0.0)  # 4th moments of 1e-300 underflow in raw units
def test_psr_power_of_two_scaling_is_bit_exact(r, k, bench):
    assert probabilistic_sharpe_ratio(r * 2.0**k, bench) == probabilistic_sharpe_ratio(r, bench)


@given(r=nice_returns, data=st.data())
def test_psr_is_order_invariant(r, data):
    perm = data.draw(st.permutations(range(len(r))))
    assert probabilistic_sharpe_ratio(r[list(perm)]) == pytest.approx(probabilistic_sharpe_ratio(r), **TOL)


@given(r=raw_returns, bench=st.floats(-5, 5))
def test_psr_is_a_probability(r, bench):
    value = _no_warnings(probabilistic_sharpe_ratio, r, bench)
    assert 0.0 <= value <= 1.0  # also rules out NaN


@given(r=raw_returns, b1=st.floats(-3, 3), b2=st.floats(-3, 3))
def test_psr_never_increases_with_the_benchmark(r, b1, b2):
    lo, hi = min(b1, b2), max(b1, b2)
    assert probabilistic_sharpe_ratio(r, lo) >= probabilistic_sharpe_ratio(r, hi)


@given(r=nice_varied)
def test_psr_at_its_own_sharpe_is_one_half(r):
    assert probabilistic_sharpe_ratio(r, sharpe(r)) == 0.5


@given(r=nice_varied, bench=st.floats(-1, 1))
def test_psr_negation_symmetry(r, bench):
    # Negating returns negates SR and skew and keeps kurtosis: z -> -z, so PSR -> 1 - PSR.
    assert probabilistic_sharpe_ratio(-r, -bench) == pytest.approx(
        1 - probabilistic_sharpe_ratio(r, bench), abs=1e-12
    )


@given(n=st.integers(0, 500), bench=st.floats(-5, 5))
def test_psr_of_all_zero_returns_is_zero_not_nan(n, bench):
    # Bug #2: all-zero returns gave NaN.
    assert _no_warnings(probabilistic_sharpe_ratio, np.zeros(n), bench) == 0.0


@given(r=hnp.arrays(np.float64, st.integers(0, 2), elements=finite), bench=st.floats(-5, 5))
def test_psr_needs_three_observations(r, bench):
    assert probabilistic_sharpe_ratio(r, bench) == 0.0


# --------------------------------------------------------------------------------------------------------
# expected_max_sharpe
# --------------------------------------------------------------------------------------------------------


@given(n=st.floats(-10, 1e7), v=st.floats(0, 100))
def test_expected_max_sharpe_is_finite_and_non_negative(n, v):
    value = expected_max_sharpe(n, v)
    assert math.isfinite(value) and value >= 0.0


@given(n1=st.floats(0, 1e6), n2=st.floats(0, 1e6), v=st.floats(0, 10))
def test_expected_max_sharpe_never_decreases_with_more_trials(n1, n2, v):
    lo, hi = min(n1, n2), max(n1, n2)
    assert expected_max_sharpe(lo, v) <= expected_max_sharpe(hi, v) + 1e-12


@given(n=st.floats(1, 1e6), v=st.floats(0, 10), c=st.floats(0, 10))
def test_expected_max_sharpe_scales_with_the_sharpe_spread(n, v, c):
    # Multiplying every trial Sharpe by c multiplies the variance by c^2 and the expected max by c.
    assert expected_max_sharpe(n, c * c * v) == pytest.approx(
        c * expected_max_sharpe(n, v), rel=1e-9, abs=1e-12
    )


# --------------------------------------------------------------------------------------------------------
# effective_trials
# --------------------------------------------------------------------------------------------------------


def _non_flat_columns(m: np.ndarray) -> int:
    """Independent count: for integer-times-power-of-ten columns, flat means all values equal."""
    return sum(len(set(m[:, j].tolist())) > 1 for j in range(m.shape[1]))


@given(m=nice_matrices())
def test_effective_trials_is_between_one_and_the_number_of_live_columns(m):
    value = _no_warnings(effective_trials, m)
    assert 1.0 - 1e-9 <= value <= max(1, _non_flat_columns(m)) + 1e-9


@given(m=raw_matrices.filter(lambda a: a.shape[0] >= 2))
def test_effective_trials_is_finite_on_any_input(m):
    value = _no_warnings(effective_trials, m)
    assert math.isfinite(value) and 1.0 - 1e-9 <= value <= m.shape[1] + 1e-9


@given(m=nice_matrices(), data=st.data())
def test_effective_trials_ignores_column_order(m, data):
    perm = data.draw(st.permutations(range(m.shape[1])))
    assert effective_trials(m[:, list(perm)]) == pytest.approx(effective_trials(m), rel=1e-9)


@given(m=nice_matrices(), data=st.data())
def test_effective_trials_ignores_column_scale_and_sign(m, data):
    signs = data.draw(hnp.arrays(np.float64, m.shape[1], elements=st.sampled_from([-1.0, 1.0])))
    scales = data.draw(hnp.arrays(np.float64, m.shape[1], elements=positive_scale))
    assert effective_trials(m * signs * scales) == pytest.approx(effective_trials(m), rel=1e-9)


@given(m=nice_matrices(), value=finite)
def test_effective_trials_ignores_flat_columns(m, value):
    flat = np.full((m.shape[0], 1), value)
    assert effective_trials(np.hstack([m, flat])) == effective_trials(m)


@given(m=nice_matrices(min_rows=3))
def test_copies_of_trials_are_not_new_trials(m):
    # corr([A, A]) has the eigenvalues of corr(A), doubled, plus zeros: same normalised entropy.
    assert effective_trials(np.hstack([m, m])) == pytest.approx(effective_trials(m), rel=1e-7)


@given(seed=st.integers(0, 2**32 - 1), k=st.integers(2, 8))
def test_independent_trials_count_almost_fully(seed, k):
    m = np.random.default_rng(seed).normal(size=(5000, k))
    assert effective_trials(m) == pytest.approx(k, rel=0.02)


# --------------------------------------------------------------------------------------------------------
# deflated_sharpe_ratio
# --------------------------------------------------------------------------------------------------------

trial_sharpe_lists = st.lists(st.floats(-0.5, 0.5), min_size=1, max_size=40)


@given(best=nice_returns, trials=trial_sharpe_lists, n_trials=st.one_of(st.none(), st.floats(1, 1e5)))
def test_dsr_is_a_probability_that_never_beats_the_psr(best, trials, n_trials):
    out = _no_warnings(deflated_sharpe_ratio, best, trials, n_trials)
    assert set(out) == {
        "dsr",
        "best_sharpe_per_period",
        "expected_max_sharpe",
        "trial_sharpe_variance",
        "n_trials",
    }
    assert 0.0 <= out["dsr"] <= probabilistic_sharpe_ratio(best) <= 1.0  # deflating never inflates
    assert out["best_sharpe_per_period"] == sharpe(best)
    assert out["expected_max_sharpe"] >= 0.0 and out["trial_sharpe_variance"] >= 0.0
    assert out["n_trials"] == (len(trials) if n_trials is None else n_trials)


@given(best=nice_returns, trials=trial_sharpe_lists, n1=st.floats(1, 1e5), n2=st.floats(1, 1e5))
def test_dsr_never_increases_with_more_trials(best, trials, n1, n2):
    lo, hi = min(n1, n2), max(n1, n2)
    assert (
        deflated_sharpe_ratio(best, trials, lo)["dsr"]
        >= deflated_sharpe_ratio(best, trials, hi)["dsr"] - 1e-9
    )


@given(best=nice_returns, trials=trial_sharpe_lists, data=st.data())
def test_dsr_ignores_the_order_of_trials(best, trials, data):
    perm = data.draw(st.permutations(trials))
    a, b = deflated_sharpe_ratio(best, trials), deflated_sharpe_ratio(best, perm)
    assert b["trial_sharpe_variance"] == pytest.approx(a["trial_sharpe_variance"], rel=1e-9, abs=1e-15)
    assert b["dsr"] == pytest.approx(a["dsr"], **TOL)


# --------------------------------------------------------------------------------------------------------
# column_sharpes
# --------------------------------------------------------------------------------------------------------


@given(m=nice_matrices(), c=positive_scale)
@example(m=np.array([[1e-12], [0.0], [0.0]]), c=2.0)  # 5.2A, per column
def test_column_sharpes_are_scale_invariant(m, c):
    assert column_sharpes(c * m) == pytest.approx(column_sharpes(m), **TOL)


@given(m=raw_matrices, ks=st.lists(st.integers(0, 64), min_size=6, max_size=6))
@example(m=np.array([[1e-160, 3.0], [0.0, 1.0], [0.0, 2.0]]), ks=[60, 0, 0, 0, 0, 0])
def test_column_sharpes_power_of_two_scaling_per_column_is_bit_exact(m, ks):
    factors = 2.0 ** np.asarray(ks[: m.shape[1]], dtype=float)
    assert np.array_equal(column_sharpes(m * factors), column_sharpes(m))


@given(m=nice_matrices())
def test_column_sharpes_equal_sharpe_of_each_column(m):
    expected = [sharpe(m[:, j]) for j in range(m.shape[1])]
    assert column_sharpes(m) == pytest.approx(expected, **TOL)


@given(m=raw_matrices)
def test_column_sharpes_are_finite_bounded_and_zero_for_flat_columns(m):
    out = _no_warnings(column_sharpes, m)
    assert out.shape == (m.shape[1],)
    assert np.isfinite(out).all() and (np.abs(out) <= SR_BOUND).all()
    for j in range(m.shape[1]):
        if len(set(m[:, j].tolist())) <= 1:
            assert out[j] == 0.0


# --------------------------------------------------------------------------------------------------------
# cscv_splits
# --------------------------------------------------------------------------------------------------------


@given(half=st.integers(1, 10), cap=st.integers(1, 400), seed=st.integers(0, 2**32 - 1))
def test_cscv_splits_are_distinct_half_sets_of_the_right_count(half, cap, seed):
    n_blocks = 2 * half
    splits = cscv_splits(n_blocks, cap, seed)
    assert len(splits) == min(math.comb(n_blocks, half), cap)
    assert len(set(splits)) == len(splits)
    assert splits == sorted(splits)
    for s in splits:
        assert len(s) == half and len(set(s)) == half and list(s) == sorted(s)
        assert 0 <= s[0] and s[-1] < n_blocks
    assert cscv_splits(n_blocks, cap, seed) == splits


# --------------------------------------------------------------------------------------------------------
# pbo
# --------------------------------------------------------------------------------------------------------


@st.composite
def pbo_cases(draw):
    n_blocks = 2 * draw(st.integers(1, 4))
    rows = draw(st.integers(n_blocks, 80))
    cols = draw(st.integers(2, 8))
    seed = draw(st.integers(0, 2**32 - 1))
    m = np.random.default_rng(seed).normal(0.0005, 0.01, size=(rows, cols))
    if draw(st.booleans()):
        m[:, draw(st.integers(0, cols - 1))] = 0.0  # a trial that never trades
    return m, n_blocks, draw(st.integers(1, 100)), draw(st.integers(0, 1000))


@given(case=pbo_cases())
def test_pbo_is_a_probability_with_one_bounded_logit_per_split(case):
    m, n_blocks, cap, seed = case
    out = _no_warnings(pbo, m, n_blocks, cap, seed)
    n = m.shape[1]
    assert out["n_trials"] == n
    assert out["n_combinations"] == len(out["logits"]) == min(math.comb(n_blocks, n_blocks // 2), cap)
    assert 0.0 <= out["pbo"] <= 1.0
    # w ranges over [1/(N+1), N/(N+1)], so |logit| <= ln N.
    assert (np.abs(out["logits"]) <= math.log(n) + 1e-12).all()
    assert out["pbo"] == np.mean(out["logits"] <= 0)


@st.composite
def pbo_relabellings(draw):
    """A PBO case plus a column permutation and per-column power-of-two exponents."""
    case = draw(pbo_cases())
    cols = case[0].shape[1]
    return (
        case,
        draw(st.permutations(range(cols))),
        draw(st.lists(st.integers(0, 20), min_size=cols, max_size=cols)),
    )


@given(relabel=pbo_relabellings())
@example(  # found by hypothesis: a 1-row IS half ties every trial; "first column wins" made PBO order-dependent
    relabel=(
        (np.array([[0.0017573, -0.00082105], [0.00690423, 0.001549], [-0.00485669, 0.00411595]]), 2, 1, 0),
        [1, 0],
        [0, 0],
    )
)
def test_pbo_ignores_trial_order_and_per_trial_power_of_two_scale(relabel):
    (m, n_blocks, cap, seed), perm, ks = relabel
    a = pbo(m, n_blocks, cap, seed)
    b = pbo((m * 2.0 ** np.asarray(ks, dtype=float))[:, list(perm)], n_blocks, cap, seed)
    assert b["pbo"] == a["pbo"]
    assert np.array_equal(b["logits"], a["logits"])


@given(
    half=st.integers(1, 4),
    per_block=st.integers(10, 15),
    cols=st.integers(2, 8),
    seed=st.integers(0, 2**32 - 1),
)
def test_pbo_of_a_dominant_trial_is_zero(half, per_block, cols, seed):
    # Trial 0 has mean/sd ~ 100 and beats every noise trial (Sharpe ~ t_9 / 3 at worst) in every half, in and
    # out of sample: its OOS rank is N every time, w = N / (N + 1), logit ln N > 0.
    n_blocks = 2 * half
    rng = np.random.default_rng(seed)
    m = rng.normal(0.0005, 0.01, size=(n_blocks * per_block, cols))
    m[:, 0] = 0.01 + 1e-4 * rng.standard_normal(m.shape[0])
    out = pbo(m, n_blocks=n_blocks, max_combinations=100, seed=seed)
    assert out["pbo"] == 0.0
    assert out["logits"] == pytest.approx(np.full(out["n_combinations"], math.log(cols)), rel=1e-12)
