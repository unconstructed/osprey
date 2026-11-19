"""Exact and statistical known answers for lab.validation.montecarlo (TESTING.md 5.3, montecarlo.py items).

Statistical checks use fixed seeds and binomial bands of +/- 4 standard deviations, so with the fixed seed they are
deterministic and a correct implementation would fail them with probability well under 1e-4 for any seed.
"""

from __future__ import annotations

import inspect
import math

import numpy as np
import pytest

from lab.validation.montecarlo import (
    block_bootstrap_drawdowns,
    bootstrap_trade_drawdowns,
    degrade_execution,
    max_drawdown,
    shuffled_trade_drawdowns,
    stationary_bootstrap_indices,
)

TOL = 1e-12


def in_binomial_band(count: int, trials: int, p: float, k: float = 4.0) -> bool:
    sd = math.sqrt(trials * p * (1 - p))
    return abs(count - trials * p) <= k * sd


# ---------------------------------------------------------------- trade shuffle and bootstrap


def test_shuffle_of_two_losses_and_a_gain():
    # Orders: (-.1,-.1,.5) and (.5,-.1,-.1) put the losses together: 0.9 * 0.9 = 0.81 -> -0.19.
    # (-.1,.5,-.1) separates them: 0.9 then 1.35 -> 1.215, each fall is -0.10. So P(-0.19) = 2/3.
    dd = shuffled_trade_drawdowns([-0.1, -0.1, 0.5])
    is_19 = np.isclose(dd, -0.19, rtol=0, atol=TOL)
    is_10 = np.isclose(dd, -0.10, rtol=0, atol=TOL)
    assert np.all(is_19 | is_10)
    assert in_binomial_band(int(is_19.sum()), dd.size, 2 / 3)
    assert 0 < is_10.sum()


def test_trade_simulation_default_lengths_and_seeds():
    assert inspect.signature(shuffled_trade_drawdowns).parameters["n_sims"].default == 5000
    assert inspect.signature(bootstrap_trade_drawdowns).parameters["n_sims"].default == 5000
    trades = [-0.1, -0.1, 0.5, 0.2, -0.3]
    for fn in (shuffled_trade_drawdowns, bootstrap_trade_drawdowns):
        dd = fn(trades)
        assert dd.shape == (5000,) and dd.dtype == np.float64
        assert np.array_equal(dd, fn(trades, seed=0))  # default seed is 0
        assert np.array_equal(fn(trades, seed=7), fn(trades, seed=7))  # same seed, same draws
        assert not np.array_equal(fn(trades, seed=7), fn(trades, seed=8))  # different seed, different draws
        assert fn(trades, n_sims=3).shape == (3,)


def test_bootstrap_repeats_a_loss_the_shuffle_cannot():
    # Drawing -10% twice needs replacement: the bootstrap reaches 0.9^2 - 1 = -0.19, the shuffle never passes -0.10.
    boot = bootstrap_trade_drawdowns([0.5, -0.1])
    shuf = shuffled_trade_drawdowns([0.5, -0.1])
    assert boot.min() == pytest.approx(-0.19, abs=TOL)
    assert shuf.min() >= -0.10 - TOL
    assert shuf.min() == pytest.approx(-0.10, abs=TOL)
    # Bootstrap outcomes: (.5,.5) -> 0, one -0.1 -> -0.10, (-.1,-.1) -> -0.19, with probabilities 1/4, 1/2, 1/4.
    assert in_binomial_band(int(np.isclose(boot, -0.19, rtol=0, atol=TOL).sum()), boot.size, 0.25)
    assert in_binomial_band(int(np.isclose(boot, -0.10, rtol=0, atol=TOL).sum()), boot.size, 0.50)
    assert in_binomial_band(int((boot == 0.0).sum()), boot.size, 0.25)


def test_no_trades_means_no_drawdown():
    assert np.array_equal(shuffled_trade_drawdowns([], n_sims=4), np.zeros(4))
    assert np.array_equal(bootstrap_trade_drawdowns([], n_sims=4), np.zeros(4))
    assert np.array_equal(block_bootstrap_drawdowns([], n_sims=4), np.zeros(4))


def test_a_total_loss_is_minus_one():
    assert shuffled_trade_drawdowns([0.2, -1.0], n_sims=10).tolist() == [-1.0] * 10
    assert max_drawdown([0.5, -1.0, 0.3]) == -1.0


# ---------------------------------------------------------------- stationary_bootstrap_indices


@pytest.mark.parametrize(("n", "mean_block"), [(1, 1), (1, 5.0), (7, 1), (7, 3.5), (50, 20), (500, 1000)])
def test_stationary_bootstrap_indices_in_range(n, mean_block):
    rng = np.random.default_rng(3)
    for _ in range(200):
        idx = stationary_bootstrap_indices(n, mean_block, rng)
        assert idx.shape == (n,)
        assert idx.dtype == np.int64
        assert idx.min() >= 0 and idx.max() < n


def test_stationary_bootstrap_within_a_block_each_index_is_the_previous_plus_one_mod_n():
    # mean_block = inf never restarts after position 0: one block, a circular shift of 0..n-1.
    rng = np.random.default_rng(11)
    wrapped = 0
    for _ in range(100):
        idx = stationary_bootstrap_indices(9, math.inf, rng)
        assert idx.tolist() == [(idx[0] + k) % 9 for k in range(9)]
        wrapped += idx[0] > 0  # the block ran past n - 1 and continued at 0
    assert wrapped > 50


def test_stationary_bootstrap_huge_finite_block_is_one_block_too():
    idx = stationary_bootstrap_indices(1000, 1e15, np.random.default_rng(5))
    assert idx.tolist() == [(idx[0] + k) % 1000 for k in range(1000)]


@pytest.mark.parametrize("mean_block", [2.5, 5, 20, 100])
def test_stationary_bootstrap_restart_share_is_one_over_mean_block(mean_block):
    # A break (idx[t] != idx[t-1] + 1 mod n) happens when position t restarts at an index other than the next one:
    # probability p * (1 - 1/n) per position, p = 1 / mean_block.
    n = 200_000
    idx = stationary_bootstrap_indices(n, mean_block, np.random.default_rng(1))
    breaks = int(np.sum(idx[1:] != (idx[:-1] + 1) % n))
    assert in_binomial_band(breaks, n - 1, (1 / mean_block) * (1 - 1 / n))


def test_stationary_bootstrap_mean_block_1_is_iid():
    # Every position restarts: indices are iid uniform, so idx[t] == idx[t-1] + 1 (mod n) only by chance (1/n),
    # and every index is equally likely.
    n, reps = 20, 5000
    rng = np.random.default_rng(2)
    draws = np.array([stationary_bootstrap_indices(n, 1, rng) for _ in range(reps)])
    continues = int(np.sum(draws[:, 1:] == (draws[:, :-1] + 1) % n))
    assert in_binomial_band(continues, reps * (n - 1), 1 / n)
    counts = np.bincount(draws.ravel(), minlength=n)
    assert all(in_binomial_band(int(c), reps * n, 1 / n) for c in counts)
    # The first position is uniform as well (it always starts a block).
    first = np.bincount(draws[:, 0], minlength=n)
    assert all(in_binomial_band(int(c), reps, 1 / n) for c in first)


def test_stationary_bootstrap_rng_seed_or_generator():
    assert np.array_equal(stationary_bootstrap_indices(30, 4, 9), stationary_bootstrap_indices(30, 4, 9))
    rng = np.random.default_rng(9)
    first = stationary_bootstrap_indices(30, 4, rng)
    second = stationary_bootstrap_indices(30, 4, rng)  # the generator advanced in place
    assert np.array_equal(first, stationary_bootstrap_indices(30, 4, 9))
    assert not np.array_equal(first, second)


@pytest.mark.parametrize("mean_block", [0.999, 0.5, 0, -3, math.nan, -math.inf])
def test_stationary_bootstrap_mean_block_below_one_raises(mean_block):
    with pytest.raises(ValueError, match=r"^mean_block must be >= 1, got "):
        stationary_bootstrap_indices(10, mean_block, np.random.default_rng(0))


def test_stationary_bootstrap_bad_n_raises():
    with pytest.raises(ValueError, match=r"^n must be >= 1, got 0$"):
        stationary_bootstrap_indices(0, 2, np.random.default_rng(0))
    with pytest.raises(ValueError, match=r"^n must be an integer, got 3\.0$"):
        stationary_bootstrap_indices(3.0, 2, np.random.default_rng(0))


# ---------------------------------------------------------------- block_bootstrap_drawdowns


def test_block_bootstrap_default_length_and_seeds():
    params = inspect.signature(block_bootstrap_drawdowns).parameters
    assert params["n_sims"].default == 2000
    assert params["mean_block"].default == 20
    r = np.random.default_rng(4).normal(0.0005, 0.02, 300)
    dd = block_bootstrap_drawdowns(r)
    assert dd.shape == (2000,) and dd.dtype == np.float64
    assert np.array_equal(dd, block_bootstrap_drawdowns(r, seed=0))
    assert not np.array_equal(
        block_bootstrap_drawdowns(r, n_sims=50, seed=1), block_bootstrap_drawdowns(r, n_sims=50)
    )


def test_block_bootstrap_is_max_drawdown_of_stationary_resamples():
    # The refactor in TESTING 5.1: the drawdowns are exactly those of successive stationary_bootstrap_indices draws
    # from one generator seeded with `seed`.
    r = np.random.default_rng(6).normal(0.0, 0.03, 120)
    rng = np.random.default_rng(42)
    expected = [max_drawdown(r[stationary_bootstrap_indices(r.size, 7, rng)]) for _ in range(300)]
    assert block_bootstrap_drawdowns(r, mean_block=7, n_sims=300, seed=42).tolist() == expected


def test_block_bootstrap_with_one_block_is_a_rotation():
    # mean_block = inf: each resample is a circular shift; a single -10% day among flat days always gives -0.10.
    r = np.zeros(30)
    r[17] = -0.1
    assert np.allclose(block_bootstrap_drawdowns(r, mean_block=math.inf, n_sims=50), -0.1, rtol=0, atol=TOL)


def test_block_bootstrap_bad_arguments_raise():
    with pytest.raises(ValueError, match=r"^mean_block must be >= 1, got 0\.5$"):
        block_bootstrap_drawdowns([0.01, -0.02], mean_block=0.5)
    with pytest.raises(ValueError, match=r"^mean_block must be >= 1, got 0\.5$"):
        block_bootstrap_drawdowns([], mean_block=0.5)  # checked even when there is nothing to resample
    with pytest.raises(ValueError, match=r"^n_sims must be >= 1, got 0$"):
        block_bootstrap_drawdowns([0.01], n_sims=0)


# ---------------------------------------------------------------- degrade_execution


def test_degrade_with_zero_turnover_equals_the_plain_compounded_return_exactly():
    r = np.random.default_rng(8).normal(0.001, 0.02, 250)
    expected = math.prod(1.0 + r) - 1.0
    for bps in (10.0, 50.0):
        totals = degrade_execution(r, np.zeros(250), extra_cost_bps=bps, n_sims=200)
        assert np.all(totals == expected)


def test_degrade_draws_costs_per_period_not_once_per_simulation():
    # Zero returns, turnover 1, 100 periods: a total is -(1 - prod(1 - c_t)), about -sum(c_t). With independent
    # per-period draws the spread across runs is small (~0.06 of the mean). One shared draw per run would make
    # it a scaled copy of that single draw (~0.58 of the mean for Uniform(0, 2x)), shown below for contrast.
    totals = degrade_execution(np.zeros(100), np.ones(100), extra_cost_bps=10.0, seed=3)
    ratio = totals.std() / abs(totals.mean())
    assert 0 < ratio < 0.3
    shared = (1 - np.random.default_rng(3).uniform(0, 2, 1000) * 10.0 / 1e4) ** 100 - 1
    assert shared.std() / abs(shared.mean()) > 0.3


@pytest.mark.parametrize(("bps", "turnover"), [(10.0, 1.0), (25.0, 1.0), (10.0, 0.5), (4.0, 0.25)])
def test_degrade_average_extra_cost_is_extra_cost_bps_per_unit_turnover(bps, turnover):
    periods = 100
    totals = degrade_execution(np.zeros(periods), np.full(periods, turnover), extra_cost_bps=bps, seed=5)
    per_period_cost = 1 - (1 + totals) ** (1 / periods)  # geometric average cost per period, each run
    assert per_period_cost.mean() * 1e4 == pytest.approx(bps * turnover, rel=0.05)


def test_degrade_default_length_and_seeds():
    params = inspect.signature(degrade_execution).parameters
    assert params["n_sims"].default == 1000
    assert params["extra_cost_bps"].default == 10.0
    r = np.random.default_rng(1).normal(0.0, 0.01, 60)
    to = np.random.default_rng(2).uniform(0, 1, 60)
    totals = degrade_execution(r, to)
    assert totals.shape == (1000,) and totals.dtype == np.float64
    assert np.array_equal(totals, degrade_execution(r, to, seed=0))
    assert np.array_equal(degrade_execution(r, to, seed=4), degrade_execution(r, to, seed=4))
    assert not np.array_equal(degrade_execution(r, to, seed=4), degrade_execution(r, to, seed=5))


def test_degrade_accepts_a_total_cost_of_exactly_100_percent():
    # 5000 bps drawn up to 2x on turnover 1 is at most 100% of the portfolio: allowed, never below -1.
    totals = degrade_execution([0.0, 0.1], [0.0, 1.0], extra_cost_bps=5000.0, n_sims=500)
    assert np.all(totals >= -1.0) and np.all(totals <= 0.1)


def test_degrade_with_no_periods_is_zero():
    assert np.array_equal(degrade_execution([], [], n_sims=3), np.zeros(3))


@pytest.mark.parametrize(
    ("returns", "turnover", "kwargs", "match"),
    [
        ([0.0, 0.1], [1.0], {}, r"^turnover must have the same shape as returns \(2,\), got \(1,\)$"),
        ([0.0, 0.1], [1.0, -0.1], {}, r"^turnover must be finite and >= 0$"),
        ([0.0, 0.1], [1.0, math.nan], {}, r"^turnover must be finite and >= 0$"),
        ([0.0, 0.1], [1.0, math.inf], {}, r"^turnover must be finite and >= 0$"),
        (
            [0.0, 0.1],
            [1.0, 1.0],
            {"extra_cost_bps": -1.0},
            r"^extra_cost_bps must be finite and >= 0, got -1\.0$",
        ),
        (
            [0.0, 0.1],
            [1.0, 1.0],
            {"extra_cost_bps": math.nan},
            r"^extra_cost_bps must be finite and >= 0, got nan$",
        ),
        (
            [0.0, 0.1],
            [1.0, 1.0],
            {"extra_cost_bps": math.inf},
            r"^extra_cost_bps must be finite and >= 0, got inf$",
        ),
        ([0.0, 0.1], [1.0, 1.0], {"extra_cost_bps": 5000.5}, r"^extra cost could reach 1 of the portfolio"),
        (
            [0.0, 0.1],
            [0.5, 2.0],
            {"extra_cost_bps": 3000.0},
            r"^extra cost could reach 1\.2 of the portfolio",
        ),
        ([0.0, 0.1], [1.0, 1.0], {"n_sims": 0}, r"^n_sims must be >= 1, got 0$"),
        ([0.0, -1.5], [1.0, 1.0], {}, r"^returns must be >= -1 \(a loss can't exceed 100%\), got min -1\.5$"),
    ],
)
def test_degrade_bad_arguments_raise(returns, turnover, kwargs, match):
    with pytest.raises(ValueError, match=match):
        degrade_execution(returns, turnover, **kwargs)


# ---------------------------------------------------------------- input validation shared by every function


@pytest.mark.parametrize(
    ("values", "match"),
    [
        ([0.1, math.nan], r"must be finite \(no NaN or inf\)$"),
        ([0.1, math.inf], r"must be finite \(no NaN or inf\)$"),
        ([0.1, -1.01], r"must be >= -1 \(a loss can't exceed 100%\), got min -1\.01$"),
        ([[0.1, 0.2]], r"must be 1-D, got shape \(1, 2\)$"),
        (0.1, r"must be 1-D, got shape \(\)$"),
    ],
)
def test_invalid_returns_raise_everywhere(values, match):
    with pytest.raises(ValueError, match=r"^r " + match):
        max_drawdown(values)
    with pytest.raises(ValueError, match=r"^trade_returns " + match):
        shuffled_trade_drawdowns(values)
    with pytest.raises(ValueError, match=r"^trade_returns " + match):
        bootstrap_trade_drawdowns(values)
    with pytest.raises(ValueError, match=r"^returns " + match):
        block_bootstrap_drawdowns(values)


@pytest.mark.parametrize(
    "fn", [shuffled_trade_drawdowns, bootstrap_trade_drawdowns, block_bootstrap_drawdowns]
)
@pytest.mark.parametrize(
    ("n_sims", "match"),
    [(0, r"^n_sims must be >= 1, got 0$"), (2.0, r"^n_sims must be an integer, got 2\.0$")],
)
def test_bad_n_sims_raises(fn, n_sims, match):
    with pytest.raises(ValueError, match=match):
        fn([0.01, -0.02], n_sims=n_sims)


def test_inputs_are_not_modified():
    r = np.array([0.1, -0.2, 0.05])
    to = np.array([1.0, 0.0, 0.5])
    shuffled_trade_drawdowns(r, n_sims=5)
    bootstrap_trade_drawdowns(r, n_sims=5)
    block_bootstrap_drawdowns(r, mean_block=2, n_sims=5)
    degrade_execution(r, to, n_sims=5)
    assert r.tolist() == [0.1, -0.2, 0.05] and to.tolist() == [1.0, 0.0, 0.5]
