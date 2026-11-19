"""Properties of lab.validation.montecarlo (TESTING.md section 3).

Max drawdown known answers and bounds; shuffle, bootstrap and block bootstrap shapes, ranges and determinism;
degraded execution never helps.
"""

from __future__ import annotations

import math
from itertools import permutations, product

import numpy as np
import pytest
from hypothesis import example, given
from hypothesis import strategies as st

from lab.validation.montecarlo import (
    block_bootstrap_drawdowns,
    bootstrap_trade_drawdowns,
    degrade_execution,
    max_drawdown,
    shuffled_trade_drawdowns,
    stationary_bootstrap_indices,
)

TOL = 1e-12

# A per-period or per-trade return: from a total loss (-1) up to +200%, with some exact edge values mixed in.
returns_value = st.one_of(
    st.floats(min_value=-1.0, max_value=2.0, allow_nan=False, allow_subnormal=False),
    st.sampled_from([-1.0, -0.5, -0.1, 0.0, 0.1, 0.5]),
)
returns_list = st.lists(returns_value, min_size=0, max_size=30)
seeds = st.integers(0, 2**32 - 1)


def brute_force_max_drawdown(r) -> float:
    """min(0, worst compounded return over any window r[i..j]), the definition written directly."""
    worst = 0.0
    for i in range(len(r)):
        for j in range(i, len(r)):
            worst = min(worst, math.prod(1.0 + x for x in r[i : j + 1]) - 1.0)
    return worst


# ---------------------------------------------------------------- max_drawdown


@pytest.mark.parametrize(
    ("r", "expected"),
    [
        ([], 0.0),
        ([0.0, 0.0], 0.0),
        ([0.1, 0.2, 0.05], 0.0),  # never falls
        ([-0.5], -0.5),  # the start counts as a peak
        ([0.5, -0.5], -0.5),
        ([-0.1, -0.1], -0.19),
        ([0.1, -0.1, -0.1, 0.5, -0.2], -0.2),  # 1.1 -> 0.891 is -0.19; 1.3365 -> 1.0692 is -0.20
        ([0.2, -0.25, 0.1, -0.2], -0.34),  # 1.2 -> 0.9 -> 0.99 -> 0.792: one drawdown of 0.792/1.2 - 1
        ([-1.0, 0.5], -1.0),  # wiped out
        ([1.0, -0.5, 1.0, -0.4], -0.5),  # 2 -> 1 is -0.5; 2 -> 1.2 is -0.4
    ],
)
def test_max_drawdown_known_answers(r, expected):
    assert max_drawdown(r) == pytest.approx(expected, abs=TOL)


@given(returns_list)
@example([0.1, -0.1, -0.1, 0.5, -0.2])
@example([-1.0, 2.0])
def test_max_drawdown_matches_the_definition(r):
    assert max_drawdown(r) == pytest.approx(brute_force_max_drawdown(r), rel=1e-9, abs=1e-12)


@given(returns_list)
def test_max_drawdown_bounds(r):
    dd = max_drawdown(r)
    assert isinstance(dd, float)
    assert -1.0 <= dd <= 0.0
    losses = [x for x in r if x < 0]
    if losses:
        assert dd <= min(losses) + TOL  # every single loss is itself a fall from a level at or below the peak
        assert dd >= math.prod(1.0 + x for x in losses) - 1.0 - TOL  # no worse than every loss back to back
    else:
        assert dd == 0.0


@given(returns_list, returns_value)
def test_max_drawdown_never_improves_when_a_period_is_appended(r, extra):
    assert max_drawdown([*r, extra]) <= max_drawdown(r)


@given(returns_list)
def test_max_drawdown_accepts_arrays_and_series_alike(r):
    import pandas as pd

    expected = max_drawdown(r)
    assert max_drawdown(np.array(r, dtype=float)) == expected
    assert max_drawdown(pd.Series(r, dtype=float)) == expected


# ---------------------------------------------------------------- trade shuffle and bootstrap

small_trades = st.lists(returns_value, min_size=1, max_size=5)


@given(small_trades, seeds, st.integers(1, 30))
@example([-0.1, -0.1, 0.5], 0, 30)
def test_shuffle_outcomes_are_drawdowns_of_permutations(trades, seed, n_sims):
    dd = shuffled_trade_drawdowns(trades, n_sims=n_sims, seed=seed)
    assert dd.shape == (n_sims,) and dd.dtype == np.float64
    possible = {max_drawdown(list(p)) for p in permutations(trades)}
    assert all(any(abs(d - q) <= TOL for q in possible) for d in dd)


@given(st.lists(returns_value, min_size=1, max_size=4), seeds, st.integers(1, 30))
def test_bootstrap_outcomes_are_drawdowns_of_resamples_with_replacement(trades, seed, n_sims):
    dd = bootstrap_trade_drawdowns(trades, n_sims=n_sims, seed=seed)
    assert dd.shape == (n_sims,) and dd.dtype == np.float64
    possible = {max_drawdown(list(p)) for p in product(trades, repeat=len(trades))}
    assert all(any(abs(d - q) <= TOL for q in possible) for d in dd)


@given(returns_list, seeds, st.integers(1, 40))
@example([1.0], 0, 1)  # no losing trade: every ordering has drawdown 0
def test_shuffle_range_and_determinism(trades, seed, n_sims):
    dd = shuffled_trade_drawdowns(trades, n_sims=n_sims, seed=seed)
    assert dd.shape == (n_sims,)
    assert np.all((dd >= -1.0) & (dd <= 0.0))
    losses = [x for x in trades if x < 0]
    if losses:
        assert np.all(dd <= min(losses) + TOL)  # the worst trade is in every ordering
        assert np.all(dd >= math.prod(1.0 + x for x in losses) - 1.0 - TOL)  # all losses back to back
    else:
        assert np.all(dd == 0.0)
    assert np.array_equal(dd, shuffled_trade_drawdowns(trades, n_sims=n_sims, seed=seed))


def worst_case_resample(r) -> float:
    """Lower bound for any resample of r with replacement: the worst value every time (0 if nothing loses)."""
    return min(0.0, (1.0 + min(r)) ** len(r) - 1.0) if len(r) else 0.0


@given(returns_list, seeds, st.integers(1, 40))
# Regression (test bug): the bound (1 + min r)^k - 1 is positive when no trade loses; it must be capped at 0.
@example([1.0], 0, 1)
def test_bootstrap_range_and_determinism(trades, seed, n_sims):
    dd = bootstrap_trade_drawdowns(trades, n_sims=n_sims, seed=seed)
    assert dd.shape == (n_sims,)
    assert np.all((dd >= -1.0) & (dd <= 0.0))
    assert np.all(dd >= worst_case_resample(trades) - TOL)  # the worst trade every time
    assert np.array_equal(dd, bootstrap_trade_drawdowns(trades, n_sims=n_sims, seed=seed))


# ---------------------------------------------------------------- stationary bootstrap


@given(st.integers(1, 200), st.floats(min_value=1.0, max_value=1e6, allow_nan=False), seeds)
@example(1, 1.0, 0)
def test_stationary_bootstrap_indices_shape_range_and_determinism(n, mean_block, seed):
    idx = stationary_bootstrap_indices(n, mean_block, np.random.default_rng(seed))
    assert idx.shape == (n,)
    assert np.all((idx >= 0) & (idx < n))
    assert np.array_equal(idx, stationary_bootstrap_indices(n, mean_block, np.random.default_rng(seed)))


@given(st.integers(1, 200), seeds)
def test_stationary_bootstrap_without_restarts_is_a_circular_shift(n, seed):
    idx = stationary_bootstrap_indices(n, math.inf, np.random.default_rng(seed))
    assert np.array_equal(idx, (idx[0] + np.arange(n)) % n)


@given(st.lists(returns_value, min_size=1, max_size=40), st.floats(1.0, 50.0), seeds, st.integers(1, 30))
@example([1.0], 1.0, 0, 1)  # regression (test bug): same uncapped bound as above
def test_block_bootstrap_shape_range_and_determinism(r, mean_block, seed, n_sims):
    dd = block_bootstrap_drawdowns(r, mean_block=mean_block, n_sims=n_sims, seed=seed)
    assert dd.shape == (n_sims,) and dd.dtype == np.float64
    assert np.all((dd >= -1.0) & (dd <= 0.0))
    assert np.all(dd >= worst_case_resample(r) - TOL)
    if min(r) >= 0:
        assert np.all(dd == 0.0)
    assert np.array_equal(dd, block_bootstrap_drawdowns(r, mean_block=mean_block, n_sims=n_sims, seed=seed))


@given(st.lists(returns_value, min_size=1, max_size=4), st.floats(1.0, 10.0) | st.just(math.inf), seeds)
@example([1.0], 1.0, 0)  # regression (test bug): the first version of this test used the uncapped bound
@example([-0.1, 0.5, -0.1, 0.2], math.inf, 3)
def test_block_bootstrap_resamples_only_observed_returns(r, mean_block, seed):
    # Every resample is a same-length sequence of r's values, so its drawdown is that of one of the sequences
    # drawn from r with replacement.
    dd = block_bootstrap_drawdowns(r, mean_block=mean_block, n_sims=20, seed=seed)
    possible = {max_drawdown(list(p)) for p in product(r, repeat=len(r))}
    assert all(any(abs(d - q) <= TOL for q in possible) for d in dd)


# ---------------------------------------------------------------- degraded execution never helps


@st.composite
def returns_and_turnover(draw):
    r = draw(st.lists(returns_value, min_size=0, max_size=40))
    turnover = draw(
        st.lists(st.floats(0.0, 1.0, allow_subnormal=False) | st.just(0.0), min_size=len(r), max_size=len(r))
    )
    return np.array(r, dtype=float), np.array(turnover, dtype=float)


@given(returns_and_turnover(), st.floats(0.0, 500.0), seeds, st.integers(1, 30))
@example((np.array([0.1, -0.2]), np.array([1.0, 1.0])), 5000.0, 0, 5)
def test_degraded_execution_never_helps(rt, bps, seed, n_sims):
    r, turnover = rt
    totals = degrade_execution(r, turnover, extra_cost_bps=bps, n_sims=n_sims, seed=seed)
    base = math.prod(1.0 + r) - 1.0
    assert totals.shape == (n_sims,) and totals.dtype == np.float64
    assert np.all(totals <= base)  # exact: each period's factor (1 + r) * (1 - extra) <= (1 + r)
    assert np.all(totals >= -1.0)
    assert np.array_equal(
        totals, degrade_execution(r, turnover, extra_cost_bps=bps, n_sims=n_sims, seed=seed)
    )


@given(returns_and_turnover(), st.floats(0.0, 200.0), st.floats(0.0, 200.0), seeds)
def test_more_extra_cost_never_helps_with_the_same_draws(rt, bps_a, bps_b, seed):
    r, turnover = rt
    low, high = sorted([bps_a, bps_b])
    totals_low = degrade_execution(r, turnover, extra_cost_bps=low, n_sims=20, seed=seed)
    totals_high = degrade_execution(r, turnover, extra_cost_bps=high, n_sims=20, seed=seed)
    assert np.all(totals_high <= totals_low)


@given(returns_and_turnover(), seeds)
def test_zero_extra_cost_changes_nothing(rt, seed):
    r, turnover = rt
    totals = degrade_execution(r, turnover, extra_cost_bps=0.0, n_sims=10, seed=seed)
    assert np.all(totals == math.prod(1.0 + r) - 1.0)


@given(returns_and_turnover(), st.floats(1.0, 200.0), seeds)
def test_any_turnover_with_extra_cost_hurts(rt, bps, seed):
    r, turnover = rt
    # Make one trading period with a survivable return: the extra cost there is positive with probability one.
    if r.size == 0:
        r, turnover = np.array([0.0]), np.array([0.0])
    r = np.clip(r, -0.9, None)
    turnover[0] = 1.0
    totals = degrade_execution(r, turnover, extra_cost_bps=bps, n_sims=10, seed=seed)
    assert np.all(totals < math.prod(1.0 + r) - 1.0)
