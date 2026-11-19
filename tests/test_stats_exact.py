"""Exact (known-answer) tests for lab/validation/stats.py: every stats.py item in TESTING.md 5.3.

Each pinned number is computed here independently of the code under test (stdlib ``NormalDist`` for Phi and
Phi^-1, moments written out by hand, numerical integration for E[max]), so a typo such as (1 + g) for (1 - g),
ddof=0 for ddof=1 or < for <= fails a fast test instead of shipping. Every ValueError message is pinned.
"""

from __future__ import annotations

import itertools
import math
import re
import statistics
import warnings

import numpy as np
import pytest
from scipy import integrate
from scipy import stats as scipy_stats

from lab.validation.stats import (
    annualized_sharpe,
    column_sharpes,
    cscv_splits,
    deflated_sharpe_ratio,
    effective_trials,
    expected_max_sharpe,
    pbo,
    probabilistic_sharpe_ratio,
    sharpe,
)

GAMMA = 0.5772156649
_ND = statistics.NormalDist()


def bailey_formula(n: float, v: float = 1.0) -> float:
    """Expected max Sharpe, Bailey & Lopez de Prado, with the stdlib normal quantile (independent of scipy)."""
    return math.sqrt(v) * ((1 - GAMMA) * _ND.inv_cdf(1 - 1 / n) + GAMMA * _ND.inv_cdf(1 - 1 / (n * math.e)))


# Pinned from bailey_formula(1000) above (stdlib NormalDist), not from the code under test.
E_MAX_1000 = 3.255121513652285


def expected_max_of_normals(n: int) -> float:
    """E[max of n iid standard normals] = integral of x * n * phi(x) * Phi(x)^(n-1) dx."""
    value, _ = integrate.quad(lambda x: x * n * _ND.pdf(x) * _ND.cdf(x) ** (n - 1), -12.0, 12.0, limit=200)
    return value


def psr_by_hand(r, sr_star: float = 0.0) -> float:
    """PSR from the paper's form, 1 - skew*SR + (kurt - 1)/4 * SR^2, with moments written out by hand."""
    n = len(r)
    mean = sum(r) / n
    d = [x - mean for x in r]
    m2, m3, m4 = (sum(x**p for x in d) / n for p in (2, 3, 4))
    sr = mean / math.sqrt(sum(x * x for x in d) / (n - 1))
    skew, kurt = m3 / m2**1.5, m4 / m2**2
    return _ND.cdf((sr - sr_star) * math.sqrt(n - 1) / math.sqrt(1 - skew * sr + (kurt - 1) / 4 * sr**2))


def two_point_zero_variance_sample(n: int, k: int, scale: float = 0.01) -> np.ndarray:
    """k values of b + 1 and n - k values of b, b chosen so skew * SR == 2 (SR with ddof=1): the PSR variance
    term (1 - skew*SR/2)^2 + (kurt - 1 - skew^2)*SR^2/4 is 0 in exact arithmetic (two-point: kurt == 1 + skew^2).
    """
    p = k / n
    b = 2 * p * (1 - p) * math.sqrt(n / (n - 1)) / (1 - 2 * p) - p
    return np.array([b + 1.0] * k + [b] * (n - k)) * scale


def psr_var_term(r) -> float:
    """The PSR variance term exactly as the code writes it, computed here with numpy only."""
    x = np.asarray(r, dtype=float)
    x = x / np.abs(x).max()
    d = x - x.mean()
    m2, m3, m4 = (np.mean(d**p) for p in (2, 3, 4))
    sr = x.mean() / x.std(ddof=1)
    skew, kurt = m3 / m2**1.5, m4 / m2**2
    return float((1 - skew * sr / 2) ** 2 + (kurt - 1 - skew**2) * sr**2 / 4)


# --------------------------------------------------------------------------------------------------------
# expected_max_sharpe
# --------------------------------------------------------------------------------------------------------


def test_expected_max_sharpe_two_trials_is_already_a_search():
    expected = GAMMA * _ND.inv_cdf(1 - 1 / (2 * math.e))  # Phi^-1(1 - 1/2) == 0, so only the g term is left
    assert expected == pytest.approx(0.52, abs=0.005)
    assert expected_max_sharpe(2, 1.0) == pytest.approx(expected, rel=1e-12)


def test_expected_max_sharpe_100_trials():
    assert expected_max_sharpe(100, 1.0) == pytest.approx(2.531, abs=5e-4)
    assert expected_max_sharpe(100, 1.0) == pytest.approx(bailey_formula(100), rel=1e-12)


def test_expected_max_sharpe_1000_trials_is_pinned():
    assert bailey_formula(1000) == pytest.approx(E_MAX_1000, rel=1e-12)
    assert expected_max_sharpe(1000, 1.0) == pytest.approx(E_MAX_1000, rel=1e-9)


@pytest.mark.parametrize("n", [2, 7.5, 100, 1000])
def test_expected_max_sharpe_scales_with_sqrt_variance(n):
    one = expected_max_sharpe(n, 1.0)
    assert one > 0
    assert expected_max_sharpe(n, 4.0) == 2 * one
    assert expected_max_sharpe(n, 0.25) == 0.5 * one
    assert expected_max_sharpe(n, 0.0) == 0.0


@pytest.mark.parametrize("n", [100, 1000])
def test_expected_max_sharpe_is_within_3pct_of_the_exact_expected_maximum(n):
    exact = expected_max_of_normals(n)
    assert exact == pytest.approx({100: 2.5076, 1000: 3.2414}[n], abs=1e-3)
    assert expected_max_sharpe(n, 1.0) == pytest.approx(exact, rel=0.03)


@pytest.mark.parametrize("n", [1, 0.5, 0, -3])
def test_expected_max_sharpe_without_a_search_is_zero(n):
    assert expected_max_sharpe(n, 1.0) == 0.0


@pytest.mark.parametrize("n", [1.0001, 1.1, 1.2, 1.28])
def test_expected_max_sharpe_is_floored_at_zero_just_above_one_trial(n):
    # The approximation goes negative here; a negative luck benchmark would make the DSR more lenient than PSR.
    assert bailey_formula(n) < 0
    assert expected_max_sharpe(n, 1.0) == 0.0


def test_expected_max_sharpe_floor_does_not_touch_positive_values():
    assert bailey_formula(1.3) > 0
    assert expected_max_sharpe(1.3, 1.0) == pytest.approx(bailey_formula(1.3), rel=1e-9)


@pytest.mark.parametrize(
    ("n", "v", "message"),
    [
        (float("nan"), 1.0, "n_trials must be finite, got nan"),
        (float("inf"), 1.0, "n_trials must be finite, got inf"),
        (10, -1.0, "variance must be finite and >= 0, got -1.0"),
        (10, float("nan"), "variance must be finite and >= 0, got nan"),
        (10, float("inf"), "variance must be finite and >= 0, got inf"),
    ],
)
def test_expected_max_sharpe_rejects_bad_arguments(n, v, message):
    with pytest.raises(ValueError, match=re.escape(message)):
        expected_max_sharpe(n, v)


# --------------------------------------------------------------------------------------------------------
# sharpe and annualized_sharpe
# --------------------------------------------------------------------------------------------------------


def test_sharpe_of_two_observations():
    assert sharpe([0.01, 0.03]) == pytest.approx(math.sqrt(2), rel=1e-12)  # mean 0.02 / sd 0.01*sqrt(2)
    assert sharpe([0.01, 0.03], ddof=0) == pytest.approx(2.0, rel=1e-12)  # population sd 0.01


def test_sharpe_matches_a_hand_computation():
    r = [0.01, -0.02, 0.03, 0.005, -0.004]
    assert sharpe(r) == pytest.approx(statistics.mean(r) / statistics.stdev(r), rel=1e-12)
    assert sharpe(r, ddof=0) == pytest.approx(statistics.mean(r) / statistics.pstdev(r), rel=1e-12)


@pytest.mark.parametrize("r", [[], [0.05], [-0.3]])
def test_sharpe_needs_two_observations(r):
    assert sharpe(r) == 0.0
    assert sharpe(r, ddof=0) == 0.0


@pytest.mark.parametrize("r", [[0.0, 0.0, 0.0], [0.01] * 7, [-0.02, -0.02]])
def test_sharpe_of_a_flat_series_is_zero(r):
    assert sharpe(r) == 0.0
    assert sharpe(r, ddof=0) == 0.0


def test_sharpe_accepts_a_pandas_series():
    import pandas as pd

    r = pd.Series([0.01, 0.03], index=pd.date_range("2024-01-01", periods=2, tz="UTC"))
    assert sharpe(r) == pytest.approx(math.sqrt(2), rel=1e-12)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"r": [0.01, 0.02], "ddof": 2}, "ddof must be 0 or 1, got 2"),
        ({"r": [0.01, 0.02], "ddof": -1}, "ddof must be 0 or 1, got -1"),
        ({"r": [[0.01, 0.02]]}, "returns must be 1-D, got 2-D"),
        ({"r": 0.01}, "returns must be 1-D, got 0-D"),
        ({"r": [0.01, float("nan")]}, "returns must be finite (no NaN or inf)"),
        ({"r": [0.01, float("inf")]}, "returns must be finite (no NaN or inf)"),
    ],
)
def test_sharpe_rejects_bad_arguments(kwargs, message):
    with pytest.raises(ValueError, match=re.escape(message)):
        sharpe(**kwargs)


def test_annualized_sharpe_defaults_to_365_periods():
    r = [0.01, -0.02, 0.03, 0.005]
    assert annualized_sharpe(r) == sharpe(r) * math.sqrt(365)
    assert annualized_sharpe(r, periods_per_year=252) == sharpe(r) * math.sqrt(252)
    assert annualized_sharpe([0.01, 0.03]) == pytest.approx(math.sqrt(2) * math.sqrt(365), rel=1e-12)


@pytest.mark.parametrize("ppy", [0, -365, float("nan"), float("inf")])
def test_annualized_sharpe_rejects_bad_periods(ppy):
    with pytest.raises(ValueError, match=re.escape(f"periods_per_year must be finite and > 0, got {ppy!r}")):
        annualized_sharpe([0.01, 0.02], periods_per_year=ppy)


# --------------------------------------------------------------------------------------------------------
# probabilistic_sharpe_ratio
# --------------------------------------------------------------------------------------------------------


def test_psr_on_exactly_three_non_flat_observations():
    r = [0.01, -0.02, 0.03]
    value = probabilistic_sharpe_ratio(r)
    assert 0.0 < value < 1.0
    assert value == pytest.approx(psr_by_hand(r), rel=1e-12)


def test_psr_matches_a_hand_computation_on_a_long_series():
    r = np.random.default_rng(7).standard_t(4, size=250) * 0.02 + 0.002
    for sr_star in (0.0, 0.05, -0.03):
        assert probabilistic_sharpe_ratio(r, sr_star) == pytest.approx(
            psr_by_hand(list(r), sr_star), rel=1e-12
        )


def test_psr_needs_three_observations():
    assert probabilistic_sharpe_ratio([0.01, 0.03]) == 0.0
    assert probabilistic_sharpe_ratio([0.01, 0.03], sr_benchmark=-5.0) == 0.0


@pytest.mark.parametrize("r", [[0.0] * 5, [0.01] * 5])
def test_psr_of_a_flat_series_is_zero(r):
    assert probabilistic_sharpe_ratio(r) == 0.0
    assert probabilistic_sharpe_ratio(r, sr_benchmark=-1.0) == 0.0


def test_psr_at_its_own_sharpe_is_one_half():
    r = [0.01, -0.02, 0.03, 0.004]
    assert probabilistic_sharpe_ratio(r, sr_benchmark=sharpe(r)) == 0.5


@pytest.mark.parametrize(
    ("n", "k"), [(3, 1), (4, 1), (5, 1), (6, 1), (7, 2), (7, 3), (9, 4), (11, 5), (20, 4)]
)
def test_psr_with_zero_sharpe_variance_is_a_step_at_the_benchmark(n, k):
    """Two-point samples with skew * SR == 2: var_term is 0 up to rounding (either sign). PSR is the limit of
    the formula, never NaN and never a warning: 1 above the benchmark, 0 below, 0.5 at it."""
    r = two_point_zero_variance_sample(n, k)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        sr = sharpe(r)
        assert probabilistic_sharpe_ratio(r) == 1.0
        assert probabilistic_sharpe_ratio(r, sr_benchmark=2 * sr) == 0.0
        assert probabilistic_sharpe_ratio(r, sr_benchmark=sr) == 0.5


def test_psr_variance_guard_is_reachable():
    """TESTING.md said the var_term <= 0 guard can never fire. It can: equality is reachable and rounding
    makes var_term negative (-8.9e-16 for [0.022996598285221187, 0.012996598285221187, 0.012996598285221187])."""
    samples = [
        two_point_zero_variance_sample(n, k) for n, k in [(3, 1), (4, 1), (6, 1), (7, 3), (9, 4), (11, 5)]
    ]
    assert any(psr_var_term(r) < 0 for r in samples)
    regression = [0.022996598285221187, 0.012996598285221187, 0.012996598285221187]
    assert probabilistic_sharpe_ratio(regression) == 1.0


def test_psr_variance_term_can_be_exactly_zero():
    # (n=20, k=4) gives var_term == 0.0 exactly: a "< 0" guard would divide by zero here.
    r = two_point_zero_variance_sample(20, 4)
    assert psr_var_term(r) == 0.0
    assert probabilistic_sharpe_ratio(r) == 1.0


@pytest.mark.parametrize("bench", [float("nan"), float("inf"), float("-inf")])
def test_psr_rejects_a_non_finite_benchmark(bench):
    with pytest.raises(ValueError, match=re.escape(f"sr_benchmark must be finite, got {bench!r}")):
        probabilistic_sharpe_ratio([0.01, -0.02, 0.03], sr_benchmark=bench)


def test_psr_rejects_bad_returns():
    with pytest.raises(ValueError, match=re.escape("returns must be finite (no NaN or inf)")):
        probabilistic_sharpe_ratio([0.01, float("nan"), 0.03])
    with pytest.raises(ValueError, match=re.escape("returns must be 1-D, got 2-D")):
        probabilistic_sharpe_ratio(np.zeros((3, 2)))


# --------------------------------------------------------------------------------------------------------
# effective_trials
# --------------------------------------------------------------------------------------------------------


def test_effective_trials_of_two_uncorrelated_columns_is_exactly_two():
    m = np.array([[1.0, 1.0], [0.0, -2.0], [-1.0, 1.0]])  # [1, 0, -1] and [1, -2, 1]: centered, orthogonal
    assert effective_trials(m) == 2.0


def test_effective_trials_of_a_duplicated_column_plus_an_orthogonal_one():
    a = np.array([1.0, 0.0, -1.0, 0.0])
    b = np.array([0.0, 1.0, 0.0, -1.0])
    expected = math.exp(-(1 / 3 * math.log(1 / 3) + 2 / 3 * math.log(2 / 3)))  # eigenvalues 0, 1, 2
    assert expected == pytest.approx(1.8899, abs=1e-4)
    assert effective_trials(np.c_[a, a, b]) == pytest.approx(expected, rel=1e-9)


def test_effective_trials_of_a_single_column_is_one():
    assert effective_trials(np.array([[0.01], [-0.02], [0.03]])) == 1.0


def test_effective_trials_drops_flat_columns_first():
    a = np.array([1.0, 0.0, -1.0])
    b = np.array([1.0, -2.0, 1.0])
    zero, const = np.zeros(3), np.full(3, 0.01)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert effective_trials(np.c_[a, zero, b, const]) == pytest.approx(2.0, rel=1e-12)
        assert effective_trials(np.c_[a, zero]) == 1.0
        assert effective_trials(np.c_[zero, const]) == 1.0


@pytest.mark.parametrize(
    ("m", "message"),
    [
        (np.zeros(5), "returns_matrix must be 2-D (rows = periods, columns = trials), got 1-D"),
        (np.zeros((1, 3)), "returns_matrix needs at least 2 rows and 1 column, got shape (1, 3)"),
        (np.zeros((4, 0)), "returns_matrix needs at least 2 rows and 1 column, got shape (4, 0)"),
        (np.array([[0.1, np.nan], [0.2, 0.3]]), "returns_matrix must be finite (no NaN or inf)"),
    ],
)
def test_effective_trials_rejects_bad_matrices(m, message):
    with pytest.raises(ValueError, match=re.escape(message)):
        effective_trials(m)


# --------------------------------------------------------------------------------------------------------
# deflated_sharpe_ratio
# --------------------------------------------------------------------------------------------------------

BEST = np.random.default_rng(3).normal(0.002, 0.02, size=400)
DSR_KEYS = {"dsr", "best_sharpe_per_period", "expected_max_sharpe", "trial_sharpe_variance", "n_trials"}


def test_dsr_trial_sharpe_variance_uses_ddof_1():
    # 0.1, 0.2, 0.3 aren't representable: numpy gives 0.009999999999999998, so 1e-12 relative is "exact";
    # ddof=0 would give 0.00667. With representable Sharpes the variance is bit-exact.
    assert deflated_sharpe_ratio(BEST, [0.1, 0.2, 0.3])["trial_sharpe_variance"] == pytest.approx(
        0.01, rel=1e-12
    )
    assert deflated_sharpe_ratio(BEST, [0.25, 0.5, 0.75])["trial_sharpe_variance"] == 0.0625


def test_dsr_with_two_trials_computes_the_variance():
    out = deflated_sharpe_ratio(BEST, [0.1, 0.2])
    assert out["trial_sharpe_variance"] == pytest.approx(0.005, rel=1e-12)
    assert out["expected_max_sharpe"] == pytest.approx(math.sqrt(0.005) * bailey_formula(2), rel=1e-9)
    assert out["dsr"] < probabilistic_sharpe_ratio(BEST)


def test_dsr_with_one_trial_is_the_psr():
    out = deflated_sharpe_ratio(BEST, [0.3])
    assert out["trial_sharpe_variance"] == 0.0
    assert out["expected_max_sharpe"] == 0.0
    assert out["dsr"] == probabilistic_sharpe_ratio(BEST)
    # Even with a large raw trial count: zero spread among trials means no luck to deflate.
    assert deflated_sharpe_ratio(BEST, [0.3], n_trials=500)["dsr"] == probabilistic_sharpe_ratio(BEST)


def test_dsr_returns_exactly_its_keys_and_consistent_values():
    trials = [0.02, 0.05, -0.01, 0.04, 0.03]
    out = deflated_sharpe_ratio(BEST, trials)
    assert set(out) == DSR_KEYS
    assert out["best_sharpe_per_period"] == sharpe(BEST)
    assert out["n_trials"] == 5
    variance = statistics.variance(trials)
    assert out["trial_sharpe_variance"] == pytest.approx(variance, rel=1e-12)
    assert out["expected_max_sharpe"] == pytest.approx(math.sqrt(variance) * bailey_formula(5), rel=1e-9)
    assert out["dsr"] == probabilistic_sharpe_ratio(BEST, sr_benchmark=out["expected_max_sharpe"])


@pytest.mark.parametrize("n_trials", [2000, 37.5, 1])
def test_dsr_uses_an_explicit_trial_count(n_trials):
    trials = [0.02, 0.05, -0.01, 0.04]
    out = deflated_sharpe_ratio(BEST, trials, n_trials=n_trials)
    assert out["n_trials"] == n_trials
    assert out["expected_max_sharpe"] == expected_max_sharpe(n_trials, out["trial_sharpe_variance"])
    assert out["dsr"] == probabilistic_sharpe_ratio(BEST, sr_benchmark=out["expected_max_sharpe"])


@pytest.mark.parametrize(
    ("trials", "n_trials", "message"),
    [
        ([], None, "trial_sharpes must not be empty"),
        ([[0.1, 0.2]], None, "trial_sharpes must be 1-D, got 2-D"),
        ([0.1, float("nan")], None, "trial_sharpes must be finite (no NaN or inf)"),
        ([0.1, 0.2], 0, "n_trials must be finite and >= 1, got 0"),
        ([0.1, 0.2], 0.5, "n_trials must be finite and >= 1, got 0.5"),
        ([0.1, 0.2], float("nan"), "n_trials must be finite and >= 1, got nan"),
        ([0.1, 0.2], float("inf"), "n_trials must be finite and >= 1, got inf"),
    ],
)
def test_dsr_rejects_bad_arguments(trials, n_trials, message):
    with pytest.raises(ValueError, match=re.escape(message)):
        deflated_sharpe_ratio(BEST, trials, n_trials=n_trials)


def test_dsr_rejects_bad_best_returns():
    with pytest.raises(ValueError, match=re.escape("returns must be finite (no NaN or inf)")):
        deflated_sharpe_ratio([0.01, float("nan"), 0.02], [0.1, 0.2])


# --------------------------------------------------------------------------------------------------------
# column_sharpes
# --------------------------------------------------------------------------------------------------------


def test_column_sharpes_exact_values_with_ddof_1():
    m = np.array([[0.01, 0.0, 0.02], [0.03, 0.0, -0.02], [0.02, 0.0, 0.03]])
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        out = column_sharpes(m)
    # col 0: mean 0.02, sd 0.01 -> 2; col 1: never trades -> exactly 0; col 2: mean 0.01, sd sqrt(7e-4) -> 1/sqrt(7)
    assert out.shape == (3,)
    assert out[0] == pytest.approx(2.0, rel=1e-12)
    assert out[1] == 0.0
    assert out[2] == pytest.approx(1 / math.sqrt(7), rel=1e-12)


def test_column_sharpes_judges_flatness_per_column():
    # A tiny-but-real column next to a large one keeps its own Sharpe (a matrix-wide scale would zero it).
    m = np.array([[1e-12, 10.0], [0.0, -10.0], [0.0, 5.0]])
    assert column_sharpes(m)[0] == pytest.approx(sharpe([1e-12, 0.0, 0.0]), rel=1e-12)
    assert column_sharpes(m)[0] == pytest.approx(1 / math.sqrt(3), rel=1e-12)


def test_column_sharpes_with_fewer_than_two_rows_are_zero():
    assert column_sharpes(np.array([[0.01, -0.02]])).tolist() == [0.0, 0.0]
    assert column_sharpes(np.zeros((0, 3))).tolist() == [0.0, 0.0, 0.0]


@pytest.mark.parametrize(
    ("m", "message"),
    [
        (np.zeros(4), "m must be 2-D (rows = periods, columns = trials), got 1-D"),
        (np.array([[0.1, np.inf], [0.2, 0.3]]), "m must be finite (no NaN or inf)"),
    ],
)
def test_column_sharpes_rejects_bad_matrices(m, message):
    with pytest.raises(ValueError, match=re.escape(message)):
        column_sharpes(m)


# --------------------------------------------------------------------------------------------------------
# cscv_splits
# --------------------------------------------------------------------------------------------------------


def test_cscv_splits_uncapped_is_every_combination():
    splits = cscv_splits(8, 1000, seed=0)
    assert len(splits) == math.comb(8, 4) == 70
    assert splits == list(itertools.combinations(range(8), 4))
    assert cscv_splits(8, 1000, seed=99) == splits  # no sampling: the seed is irrelevant


def test_cscv_splits_at_exactly_the_cap_is_every_combination():
    assert cscv_splits(6, 20, seed=0) == list(itertools.combinations(range(6), 3))  # C(6, 3) == 20


@pytest.mark.parametrize(("n_blocks", "cap"), [(6, 19), (16, 4000), (16, 12869), (20, 50), (24, 300)])
def test_cscv_splits_capped_is_a_distinct_seeded_subset_of_exact_size(n_blocks, cap):
    splits = cscv_splits(n_blocks, cap, seed=1)
    every = set(itertools.combinations(range(n_blocks), n_blocks // 2)) if n_blocks <= 16 else None
    assert len(splits) == cap
    assert len(set(splits)) == cap
    assert splits == sorted(splits)
    for s in splits:
        assert len(s) == n_blocks // 2 and list(s) == sorted(set(s))
        assert all(type(b) is int and 0 <= b < n_blocks for b in s)
        assert every is None or s in every
    assert cscv_splits(n_blocks, cap, seed=1) == splits
    assert cscv_splits(n_blocks, cap, seed=2) != splits


def test_cscv_splits_accepts_numpy_integers():
    assert cscv_splits(np.int64(4), np.int64(6), seed=0) == list(itertools.combinations(range(4), 2))


@pytest.mark.parametrize(
    ("n_blocks", "cap", "message"),
    [
        (3, 10, "n_blocks must be an even integer >= 2, got 3"),
        (0, 10, "n_blocks must be an even integer >= 2, got 0"),
        (-2, 10, "n_blocks must be an even integer >= 2, got -2"),
        (4.0, 10, "n_blocks must be an even integer >= 2, got 4.0"),
        (True, 10, "n_blocks must be an even integer >= 2, got True"),
        (4, 0, "max_combinations must be an integer >= 1, got 0"),
        (4, 2.5, "max_combinations must be an integer >= 1, got 2.5"),
        (4, True, "max_combinations must be an integer >= 1, got True"),
    ],
)
def test_cscv_splits_rejects_bad_arguments(n_blocks, cap, message):
    with pytest.raises(ValueError, match=re.escape(message)):
        cscv_splits(n_blocks, cap, seed=0)


# --------------------------------------------------------------------------------------------------------
# pbo
# --------------------------------------------------------------------------------------------------------

PBO_KEYS = {"pbo", "logits", "n_combinations", "n_trials"}


def blocks_matrix(block_levels) -> np.ndarray:
    """One 2-row block per entry of ``block_levels`` (a list of per-trial levels a): rows a + 1 and a - 1, so
    every trial's Sharpe in that block is a / sqrt(2), proportional to a."""
    rows = []
    for levels in block_levels:
        a = np.asarray(levels, dtype=float)
        rows += [(a + 1) * 0.01, (a - 1) * 0.01]
    return np.array(rows)


def test_pbo_returns_exactly_its_keys():
    m = np.random.default_rng(0).normal(0, 0.01, size=(40, 4))
    out = pbo(m, n_blocks=4)
    assert set(out) == PBO_KEYS
    assert isinstance(out["pbo"], float)
    assert out["n_combinations"] == 6 and out["n_trials"] == 4
    assert isinstance(out["logits"], np.ndarray) and out["logits"].shape == (6,)


def test_pbo_tie_rule_median_out_of_sample_counts_as_overfit():
    # Trials X, Y, Z. Block 0 levels (3, 2, 1): X best; block 1 levels (2, 3, 1): Y best, X median.
    # IS block 0 -> X, which is the OOS median in block 1 (rank 2 of 3); IS block 1 -> Y, the OOS median in
    # block 0. w = 2 / 4 = 0.5, logit exactly 0, which counts as overfit.
    m = blocks_matrix([[3, 2, 1], [2, 3, 1]])
    out = pbo(m, n_blocks=2)
    assert out["n_combinations"] == 2 and out["n_trials"] == 3
    assert out["logits"].tolist() == [0.0, 0.0]
    assert out["pbo"] == 1.0


def test_pbo_when_the_in_sample_winner_stays_best():
    out = pbo(blocks_matrix([[3, 2, 1], [3, 1, 2]]), n_blocks=2)
    # IS best is X both times and X is OOS best: rank 3 of 3, w = 3/4, logit ln 3.
    assert out["logits"] == pytest.approx([math.log(3), math.log(3)], rel=1e-12)
    assert out["pbo"] == 0.0


def test_pbo_when_the_in_sample_winner_is_out_of_sample_worst():
    out = pbo(blocks_matrix([[3, 2, 1], [1, 2, 3]]), n_blocks=2)
    # IS block 0 -> X, OOS worst; IS block 1 -> Z, OOS worst: rank 1 of 3, w = 1/4, logit -ln 3.
    assert out["logits"] == pytest.approx([-math.log(3), -math.log(3)], rel=1e-12)
    assert out["pbo"] == 1.0


def test_pbo_ties_out_of_sample_share_the_average_rank_and_in_sample_take_the_worst_candidate():
    # Block 0 levels (3, 2, 1), block 1 levels (2, 2, 1): X and Y tie in block 1.
    # IS block 0 -> X; OOS block 1: X ties Y above Z, average rank (2 + 3) / 2 = 2.5, w = 2.5 / 4.
    # IS block 1 -> X and Y tie in sample; score the worse OOS candidate, Y (rank 2 of 3 in block 0): logit 0.
    for m in (blocks_matrix([[3, 2, 1], [2, 2, 1]]), blocks_matrix([[3, 2, 1], [2, 2, 1]])[:, [1, 0, 2]]):
        out = pbo(m, n_blocks=2)
        assert out["logits"] == pytest.approx([math.log(2.5 / 1.5), 0.0], rel=1e-12, abs=1e-15)
        assert out["pbo"] == 0.5


def test_pbo_does_not_depend_on_the_order_of_tied_in_sample_winners():
    # Regression (found by hypothesis): with a 1-row in-sample half every IS Sharpe is 0, so all trials tie.
    # Picking the first column made PBO 0.0 in one column order and 1.0 in the other.
    m = np.array([[0.0017573, -0.00082105], [0.00690423, 0.001549], [-0.00485669, 0.00411595]])
    for cols in ([0, 1], [1, 0]):
        out = pbo(m[:, cols], n_blocks=2)
        # IS rows 0-1 -> trial 0 (Sharpe 1.19 vs 0.22); OOS row 2 alone: all 0, average rank 1.5, w = 1/2.
        # IS row 2 alone: tie -> worse OOS candidate on rows 0-1 is trial 1: rank 1 of 2, w = 1/3.
        assert out["logits"] == pytest.approx([0.0, math.log(0.5)], rel=1e-12, abs=1e-15)
        assert out["pbo"] == 1.0


def pbo_reference(m: np.ndarray, n_blocks: int, combos=None) -> list[float]:
    """Slow, independent CSCV: explicit row lists (first blocks get the extra rows), ``sharpe`` per column,
    scipy average ranks, the worst OOS rank among tied IS winners."""
    t, n = m.shape
    sizes = [t // n_blocks + (1 if i < t % n_blocks else 0) for i in range(n_blocks)]
    starts = np.cumsum([0, *sizes])
    blocks = [list(range(starts[i], starts[i + 1])) for i in range(n_blocks)]
    if combos is None:
        combos = itertools.combinations(range(n_blocks), n_blocks // 2)
    logits = []
    for combo in combos:
        is_rows = sorted(r for b in combo for r in blocks[b])
        oos_rows = sorted(set(range(t)) - set(is_rows))
        sr_is = [sharpe(m[is_rows, j]) for j in range(n)]
        sr_oos = [sharpe(m[oos_rows, j]) for j in range(n)]
        ranks = scipy_stats.rankdata(sr_oos, method="average")
        rank = min(ranks[j] for j in range(n) if sr_is[j] == max(sr_is))
        w = rank / (n + 1)
        logits.append(math.log(w / (1 - w)))
    return logits


@pytest.mark.parametrize(
    ("t", "n_blocks", "n", "seed"), [(7, 4, 3, 0), (9, 2, 4, 1), (3, 2, 3, 2), (13, 6, 5, 3)]
)
def test_pbo_matches_an_independent_cscv_with_uneven_blocks(t, n_blocks, n, seed):
    m = np.random.default_rng(seed).normal(0.001, 0.01, size=(t, n))
    out = pbo(m, n_blocks=n_blocks)
    expected = pbo_reference(m, n_blocks)
    assert out["logits"] == pytest.approx(expected, rel=1e-12, abs=1e-15)
    assert out["pbo"] == np.mean(np.array(expected) <= 0)


def test_pbo_capped_matches_the_independent_cscv_on_the_same_splits():
    m = np.random.default_rng(4).normal(0.001, 0.01, size=(70, 6))
    out = pbo(m, n_blocks=16, max_combinations=50, seed=9)
    expected = pbo_reference(m, 16, combos=cscv_splits(16, 50, seed=9))
    assert out["logits"] == pytest.approx(expected, rel=1e-12, abs=1e-15)


def test_pbo_with_a_trial_that_never_trades():
    rng = np.random.default_rng(5)
    m = rng.normal(0.0005, 0.01, size=(64, 5))
    m[:, 2] = 0.0
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        out = pbo(m, n_blocks=8)
    assert out["n_trials"] == 5 and out["n_combinations"] == 70
    assert 0.0 <= out["pbo"] <= 1.0
    assert np.isfinite(out["logits"]).all()


def test_pbo_when_no_trial_ever_trades_everything_is_overfit():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        out = pbo(np.zeros((8, 3)), n_blocks=4)
    # Every Sharpe is 0: all trials tie, the IS pick has the average rank 2 of 3, logit 0.
    assert out["logits"].tolist() == [0.0] * 6
    assert out["pbo"] == 1.0


def test_pbo_default_is_16_blocks_capped_at_4000_combinations():
    m = np.random.default_rng(11).normal(0, 0.01, size=(64, 3))
    out = pbo(m)
    assert math.comb(16, 8) == 12870
    assert out["n_combinations"] == 4000 == len(out["logits"])
    explicit = pbo(m, n_blocks=16, max_combinations=4000, seed=0)
    assert out["pbo"] == explicit["pbo"]
    assert np.array_equal(out["logits"], explicit["logits"])


def test_pbo_uses_uneven_blocks_when_rows_do_not_divide():
    m = np.random.default_rng(2).normal(0, 0.01, size=(13, 3))
    out = pbo(m, n_blocks=4)
    assert out["n_combinations"] == 6
    assert np.isfinite(out["logits"]).all()


@pytest.mark.parametrize(
    ("m", "kwargs", "message"),
    [
        (np.zeros((32, 1)), {}, "returns_matrix needs at least 2 trials (columns) for PBO, got 1"),
        (np.zeros((10, 3)), {}, "returns_matrix needs at least n_blocks=16 rows, got 10"),
        (np.zeros((10, 3)), {"n_blocks": 3}, "n_blocks must be an even integer >= 2, got 3"),
        (
            np.zeros((10, 3)),
            {"n_blocks": 4, "max_combinations": 0},
            "max_combinations must be an integer >= 1, got 0",
        ),
        (
            np.zeros(10),
            {"n_blocks": 2},
            "returns_matrix must be 2-D (rows = periods, columns = trials), got 1-D",
        ),
        (np.full((10, 2), np.nan), {"n_blocks": 2}, "returns_matrix must be finite (no NaN or inf)"),
    ],
)
def test_pbo_rejects_bad_arguments(m, kwargs, message):
    with pytest.raises(ValueError, match=re.escape(message)):
        pbo(m, **kwargs)
