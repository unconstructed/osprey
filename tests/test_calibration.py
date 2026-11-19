"""Calibration: on pure noise, the statistics must say "luck" at the advertised rate.

These simulate thousands of skill-less strategies, so they are marked slow:
    pytest -m slow
"""

import numpy as np
import pytest
from scipy import stats as st

from lab.validation import montecarlo as mc
from lab.validation.stats import (
    deflated_sharpe_ratio,
    expected_max_sharpe,
    probabilistic_sharpe_ratio,
    probability_of_backtest_overfitting,
    sharpe,
)

pytestmark = pytest.mark.slow


def _binomial_band(p, n, z=4.0):
    sd = np.sqrt(p * (1 - p) / n)
    return p - z * sd, p + z * sd


@pytest.mark.parametrize("dist", ["normal", "student_t"])
def test_psr_false_positive_rate_is_about_5pct(dist):
    rng = np.random.default_rng(0)
    reps, n = 3000, 500
    if dist == "normal":
        r = rng.normal(0, 0.02, (reps, n))
    else:
        r = rng.standard_t(5, (reps, n)) * 0.02  # fat tails like crypto
    psr = np.array([probabilistic_sharpe_ratio(x) for x in r])
    rate = (psr > 0.95).mean()
    lo, hi = _binomial_band(0.05, reps)
    assert lo < rate < hi, rate


def test_psr_detects_a_real_edge():
    rng = np.random.default_rng(1)
    # annual Sharpe ~2 over two years of daily data
    r = rng.normal(0.02 * 2 / np.sqrt(365), 0.02, (500, 730))
    assert np.mean([probabilistic_sharpe_ratio(x) > 0.95 for x in r]) > 0.8


@pytest.mark.parametrize("n_trials", [10, 100, 1000])
def test_expected_max_sharpe_matches_simulation(n_trials):
    rng = np.random.default_rng(2)
    n_obs, reps = 400, 300
    maxima, variances = [], []
    for _ in range(reps):
        r = rng.normal(0, 1, (n_trials, n_obs))
        srs = r.mean(axis=1) / r.std(axis=1, ddof=1)
        maxima.append(srs.max())
        variances.append(srs.var(ddof=1))
    predicted = expected_max_sharpe(n_trials, float(np.mean(variances)))
    assert np.mean(maxima) == pytest.approx(predicted, rel=0.06)


def test_selecting_the_best_of_many_fools_psr_but_not_dsr():
    """The core of the luck control: pick the best of 100 noise strategies. Plain PSR
    calls it skill most of the time; DSR must call it luck at <= ~5%."""
    rng = np.random.default_rng(3)
    reps, n_trials, n_obs = 400, 100, 500
    psr_hits = dsr_hits = 0
    for _ in range(reps):
        r = rng.normal(0, 0.02, (n_trials, n_obs))
        srs = np.array([sharpe(x) for x in r])
        best = r[np.argmax(srs)]
        psr_hits += probabilistic_sharpe_ratio(best) > 0.95
        dsr_hits += deflated_sharpe_ratio(best, srs)["dsr"] > 0.95
    assert psr_hits / reps > 0.8
    assert dsr_hits / reps < 0.08


@pytest.mark.parametrize("days, low, high", [(1000, 0.3, 0.65), (2000, 0.8, 1.0)])
def test_dsr_power_on_a_real_edge(days, low, high):
    """How often a genuinely good strategy (annual Sharpe 2.5) found among 50 trials passes
    DSR >= 0.95. Measured: ~46% with 2.7 years of daily data, >80% with 5.5 years. The
    gate is strict; short histories will reject some real edges."""
    rng = np.random.default_rng(4)
    passes = 0
    for _ in range(200):
        r = rng.normal(0, 0.02, (50, days))
        r[0] += 0.02 * 2.5 / np.sqrt(365)
        srs = np.array([sharpe(x) for x in r])
        best = r[np.argmax(srs)]
        passes += deflated_sharpe_ratio(best, srs)["dsr"] > 0.95
    assert low < passes / 200 <= high


def test_pbo_is_about_half_under_the_null():
    rng = np.random.default_rng(5)
    pbos = [probability_of_backtest_overfitting(rng.normal(0, 0.02, (800, 30)), n_blocks=10, seed=i)["pbo"]
            for i in range(60)]
    assert 0.35 < np.mean(pbos) < 0.65


def test_pbo_is_low_when_one_strategy_is_really_better():
    rng = np.random.default_rng(6)
    m = rng.normal(0, 0.02, (1000, 30))
    m[:, 7] += 0.004
    assert probability_of_backtest_overfitting(m, n_blocks=10)["pbo"] < 0.1


def test_block_bootstrap_keeps_volatility_clusters():
    """A stationary block bootstrap must keep the clustering an iid shuffle destroys, so
    its drawdowns are worse on clustered data."""
    rng = np.random.default_rng(7)
    sig = np.where((np.arange(2000) // 100) % 2 == 0, 0.01, 0.04)
    r = rng.normal(0.0005, 1, 2000) * sig
    iid = mc.bootstrap_trade_drawdowns(r, n_sims=500, seed=0)
    blk = mc.block_bootstrap_drawdowns(r, n_sims=500, mean_block=50, seed=0)
    assert np.median(blk) < np.median(iid)
    assert st.spearmanr(np.abs(r[:-1]), np.abs(r[1:])).statistic > 0.1  # the input really is clustered
