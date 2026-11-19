"""Labels and baselines (TESTING.md section 3).

- Every label equals a hand computation over exactly the right future window (bars t+1..t+h): bars
  outside the window never change it, the window's last bar does, and the last ``h`` rows are NaN.
- Labels never appear as features: separate name spaces (``LABEL_PREFIX``), and the features at t do
  not move when only the label window changes.
- Baselines use only the past (tamper the future), equal hand computations, and line up exactly with
  the labels they forecast (the baseline at t + h reads the same window as the label at t).
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest
from hypothesis import given
from hypothesis import strategies as st

from lab.models.baselines import ewma_vol, long_run_vol, momentum_rank, naive_vol, regime_persistence
from lab.models.features import FEATURES, RANK_SUFFIX, WARMUP, compute_features, cross_sectional_ranks
from lab.models.labels import (
    LABEL_PREFIX,
    cross_sectional_forward_rank,
    forward_regime,
    forward_return,
    forward_vol,
)

N_BARS = 1500
PRICE_COLS = ["open", "high", "low", "close"]


def scale_rows(bars: pd.DataFrame, rows, seed: int, sigma: float = 0.2) -> pd.DataFrame:
    """Copy of ``bars`` with each listed row's prices (one factor per row) and volume rescaled."""
    rows = np.asarray(list(rows), dtype=int)
    out = bars.copy()
    if len(rows) == 0:
        return out
    rng = np.random.default_rng(seed)
    price_f = np.exp(rng.normal(0.0, sigma, len(rows)))
    for col in PRICE_COLS:
        j = out.columns.get_loc(col)
        out.iloc[rows, j] = out.iloc[rows, j].to_numpy() * price_f
    j = out.columns.get_loc("volume")
    out.iloc[rows, j] = out.iloc[rows, j].to_numpy() * np.exp(rng.normal(0.0, sigma, len(rows)))
    return out


# ---------------------------------------------------------------- hand computations


def log_ret(c, i):
    return math.log(c[i] / c[i - 1])


def stdev(xs):
    mean = math.fsum(xs) / len(xs)
    return math.sqrt(math.fsum((x - mean) ** 2 for x in xs) / (len(xs) - 1))


def eff_ratio(c, a, b):
    """Efficiency ratio of closes a..b (0 when nothing moved)."""
    path = math.fsum(abs(c[i] - c[i - 1]) for i in range(a + 1, b + 1))
    return abs(c[b] - c[a]) / path if path > 0 else 0.0


def hand_forward_vol(c, t, h):
    return stdev([log_ret(c, i) for i in range(t + 1, t + h + 1)])


def hand_ewma(c, t, span, window):
    lam = 1 - 2 / (span + 1)
    num = math.fsum(lam**age * log_ret(c, t - age) ** 2 for age in range(window))
    den = math.fsum(lam**age for age in range(window))
    return math.sqrt(num / den)


@pytest.fixture(scope="module")
def short_btc(btc):
    return btc.iloc[:400]


# ---------------------------------------------------------------- labels: hand computations


@pytest.mark.parametrize("h", [2, 5, 20])
def test_forward_vol_equals_hand_computation(short_btc, h):
    c = short_btc["close"].tolist()
    y = forward_vol(short_btc, h)
    assert y.name == f"y_vol_{h}" and y.index.equals(short_btc.index)
    n = len(c)
    expected = [hand_forward_vol(c, t, h) for t in range(n - h)]
    np.testing.assert_allclose(y.iloc[: n - h], expected, rtol=1e-10)
    assert y.iloc[n - h :].isna().all()


@pytest.mark.parametrize("h", [1, 5, 20])
def test_forward_return_equals_hand_computation(short_btc, h):
    c = short_btc["close"].tolist()
    y = forward_return(short_btc, h)
    assert y.name == f"y_ret_{h}"
    n = len(c)
    np.testing.assert_allclose(y.iloc[: n - h], [c[t + h] / c[t] - 1 for t in range(n - h)], rtol=1e-12)
    assert y.iloc[n - h :].isna().all()


@given(h=st.integers(1, 30), threshold=st.floats(0.0, 1.0))
def test_forward_regime_equals_hand_computation(short_btc, h, threshold):
    c = short_btc["close"].tolist()
    y = forward_regime(short_btc, h, threshold)
    assert y.name == f"y_regime_{h}"
    n = len(c)
    for t in range(n - h):
        er = eff_ratio(c, t, t + h)
        if abs(er - threshold) > 1e-12:  # an exact tie can round either way between two float sums
            assert y.iloc[t] == float(er >= threshold), t
    assert y.iloc[n - h :].isna().all()
    assert set(y.iloc[: n - h].unique()) <= {0.0, 1.0}


def test_forward_regime_known_paths(make_bars):
    up = make_bars([100.0 + i for i in range(30)])
    assert (forward_regime(up, 10).iloc[:-10] == 1.0).all()  # straight line: efficiency 1
    zigzag = make_bars([100.0 + (i % 2) for i in range(30)])
    assert (forward_regime(zigzag, 10).iloc[:-10] == 0.0).all()  # back and forth: efficiency 0
    flat = make_bars([100.0] * 30)
    assert (forward_regime(flat, 10).iloc[:-10] == 0.0).all()  # no movement is sideways
    assert (forward_regime(flat, 10, threshold=0.0).iloc[:-10] == 1.0).all()  # threshold 0: all trend


def test_cross_sectional_forward_rank_known_answer(make_bars):
    a = make_bars([100.0, 110.0, 99.0, 100.0])  # forward 1-bar returns: +10%, -10%, +1.01%
    b = make_bars([100.0, 105.0, 105.0, 100.0])  # +5%, 0%, -4.76%
    c = make_bars([100.0, 101.0, 100.0, 100.0])  # +1%, -0.99%, 0%
    ranks = cross_sectional_forward_rank({"A": a, "B": b, "C": c}, 1)
    assert ranks["A"].name == "y_xs_rank_1"
    np.testing.assert_allclose(ranks["A"], [1.0, 1 / 3, 1.0, np.nan])
    np.testing.assert_allclose(ranks["B"], [2 / 3, 1.0, 1 / 3, np.nan])
    np.testing.assert_allclose(ranks["C"], [1 / 3, 2 / 3, 2 / 3, np.nan])


def test_cross_sectional_forward_rank_matches_forward_returns(market):
    ranks = cross_sectional_forward_rank(market, 5)
    fwd = {asset: forward_return(bars, 5) for asset, bars in market.items()}
    btc_better = fwd["BTC"] > fwd["ETH"]
    assert (ranks["BTC"][btc_better] == 1.0).all() and (ranks["ETH"][btc_better] == 0.5).all()
    assert ranks["BTC"].iloc[-5:].isna().all()


# ---------------------------------------------------------------- labels: exactly the right window


@given(t=st.integers(0, N_BARS - 31), h=st.integers(2, 30), seed=st.integers(0, 2**32 - 1))
def test_labels_read_exactly_the_future_window(btc, t, h, seed):
    labels = {
        "vol": lambda b: forward_vol(b, h),
        "ret": lambda b: forward_return(b, h),
        "regime": lambda b: forward_regime(b, h),
    }
    base = {k: f(btc).iloc[t] for k, f in labels.items()}
    outside = scale_rows(btc, [*range(0, t), *range(t + h + 1, N_BARS)], seed)  # everything but t..t+h
    for k, f in labels.items():
        assert f(outside).iloc[t] == base[k], k
    last = scale_rows(btc, [t + h], seed)  # the window's last bar moves the volatility and the return
    assert forward_vol(last, h).iloc[t] != base["vol"]
    assert forward_return(last, h).iloc[t] != base["ret"]


def test_labels_are_nan_without_a_full_future(make_bars):
    bars = make_bars([100.0, 101.0, 102.0])
    assert forward_vol(bars, 3).isna().all()
    assert forward_return(bars, 3).isna().all()
    assert forward_regime(bars, 3).isna().all()
    assert forward_vol(bars, 2).notna().tolist() == [True, False, False]


@pytest.mark.parametrize(
    ("call", "message"),
    [
        (lambda b: forward_vol(b, 1), "horizon must be an int >= 2"),
        (lambda b: forward_vol(b, 2.0), "horizon must be an int >= 2"),
        (lambda b: forward_return(b, 0), "horizon must be an int >= 1"),
        (lambda b: forward_return(b, True), "horizon must be an int >= 1"),
        (lambda b: forward_regime(b, 0), "horizon must be an int >= 1"),
        (lambda b: forward_regime(b, 5, threshold=1.5), r"threshold must be in \[0, 1\]"),
        (lambda b: forward_regime(b, 5, threshold=-0.1), r"threshold must be in \[0, 1\]"),
        (lambda b: cross_sectional_forward_rank({}, 5), "bars_by_asset is empty"),
    ],
)
def test_label_argument_errors(btc, call, message):
    with pytest.raises(ValueError, match=message):
        call(btc)


def test_labels_validate_bars(btc):
    bad = btc.copy()
    bad.iloc[3, bad.columns.get_loc("high")] = 0.5 * bad["low"].iloc[3]
    with pytest.raises(ValueError, match="low <= open, close <= high"):
        forward_vol(bad, 5)


# ---------------------------------------------------------------- labels never appear as features


def test_label_and_feature_names_never_overlap(market):
    feats = compute_features(market["BTC"])
    label_names = {
        forward_vol(market["BTC"], 5).name,
        forward_return(market["BTC"], 5).name,
        forward_regime(market["BTC"], 5).name,
        cross_sectional_forward_rank(market, 5)["BTC"].name,
    }
    assert all(name.startswith(LABEL_PREFIX) for name in label_names)
    assert not any(name.startswith(LABEL_PREFIX) for name in FEATURES)
    assert not any(str(col).startswith(LABEL_PREFIX) for col in feats.columns)
    ranks = cross_sectional_ranks({a: compute_features(b) for a, b in market.items()})
    assert not any(col.startswith(LABEL_PREFIX) for col in ranks["BTC"].columns)
    assert all(col.endswith(RANK_SUFFIX) for col in ranks["BTC"].columns)
    baseline_names = [
        naive_vol(market["BTC"]).name,
        long_run_vol(market["BTC"]).name,
        ewma_vol(market["BTC"]).name,
        regime_persistence(market["BTC"]).name,
        momentum_rank(market)["BTC"].name,
    ]
    assert not any(name.startswith(LABEL_PREFIX) for name in baseline_names)


@given(t=st.integers(WARMUP - 1, N_BARS - 21), h=st.integers(2, 20), seed=st.integers(0, 2**32 - 1))
def test_features_carry_no_information_about_their_label(btc, features, t, h, seed):
    """Rewriting the label window t+1..t+h changes the label at t but never the features at t."""
    tampered = scale_rows(btc, range(t + 1, t + h + 1), seed)
    assert forward_vol(tampered, h).iloc[t] != forward_vol(btc, h).iloc[t]
    np.testing.assert_array_equal(compute_features(tampered).iloc[t].to_numpy(), features.iloc[t].to_numpy())


# ---------------------------------------------------------------- baselines: only the past


def all_baselines(bars: pd.DataFrame) -> pd.DataFrame:
    return pd.concat(
        [
            naive_vol(bars, 20),
            long_run_vol(bars, 60),
            ewma_vol(bars, 20),
            ewma_vol(bars, 7, window=30),
            regime_persistence(bars, 20, 0.3),
        ],
        axis=1,
    )


@given(cut=st.integers(1, N_BARS - 1), seed=st.integers(0, 2**32 - 1))
def test_baselines_use_only_the_past(btc, cut, seed):
    base = all_baselines(btc)
    tampered = all_baselines(scale_rows(btc, range(cut, N_BARS), seed))
    pd.testing.assert_frame_equal(tampered.iloc[:cut], base.iloc[:cut], check_exact=True)


@given(cut=st.integers(1, N_BARS - 1), seed=st.integers(0, 2**32 - 1))
def test_momentum_rank_uses_only_the_past(market, cut, seed):
    base = momentum_rank(market, 20)
    tampered = momentum_rank(dict(market, ETH=scale_rows(market["ETH"], range(cut, N_BARS), seed)), 20)
    for asset in market:
        pd.testing.assert_series_equal(tampered[asset].iloc[:cut], base[asset].iloc[:cut], check_exact=True)


@given(cut=st.integers(WARMUP - 1, N_BARS - 1))
def test_volatility_baselines_react_to_the_present_bar(btc, cut):
    tampered = btc.copy()
    col = tampered.columns.get_loc
    tampered.iloc[cut, col("close")] *= 0.7
    tampered.iloc[cut, col("low")] = min(tampered["low"].iloc[cut], tampered["close"].iloc[cut])
    for f in (naive_vol, long_run_vol, ewma_vol):
        assert f(tampered).iloc[cut] != f(btc).iloc[cut], f.__name__


# ---------------------------------------------------------------- baselines: known answers and identities


def test_naive_and_long_run_vol_equal_hand_computation(short_btc):
    c = short_btc["close"].tolist()
    n = len(c)
    naive = naive_vol(short_btc, 10)
    assert naive.name == "naive_vol_10"
    assert naive.iloc[:10].isna().all()
    np.testing.assert_allclose(
        naive.iloc[10:],
        [stdev([log_ret(c, i) for i in range(t - 9, t + 1)]) for t in range(10, n)],
        rtol=1e-10,
    )
    lr = long_run_vol(short_btc, 30)
    assert lr.name == "long_run_vol"
    assert lr.iloc[:30].isna().all()  # 30 returns exist from bar 30 on
    np.testing.assert_allclose(
        lr.iloc[30:], [stdev([log_ret(c, i) for i in range(1, t + 1)]) for t in range(30, n)], rtol=1e-9
    )


@pytest.mark.parametrize(("span", "window"), [(20, 100), (7, 30), (1, 5)])
def test_ewma_vol_equals_hand_computation(short_btc, span, window):
    c = short_btc["close"].tolist()
    got = ewma_vol(short_btc, span, window=window)
    assert got.name == f"ewma_vol_{span}"
    assert got.iloc[:window].isna().all()
    np.testing.assert_allclose(
        got.iloc[window:], [hand_ewma(c, t, span, window) for t in range(window, len(c))], rtol=1e-10
    )


def test_ewma_span_one_is_the_last_absolute_return(short_btc):
    """span 1 puts all the weight on the newest return (lam = 0)."""
    c = short_btc["close"].to_numpy()
    got = ewma_vol(short_btc, 1, window=5)
    np.testing.assert_allclose(got.iloc[5:], np.abs(np.log(c[5:] / c[4:-1])), rtol=1e-12)


def test_volatility_baselines_equal_the_features(btc, features):
    """The vol model's EWMA anchor and the naive forecast are the very feature values (bit for bit)."""
    live = slice(WARMUP - 1, None)
    np.testing.assert_array_equal(ewma_vol(btc, 20).iloc[live], features["ewma_vol_20"].iloc[live])
    for w in (10, 20, 60):
        np.testing.assert_array_equal(naive_vol(btc, w).iloc[live], features[f"vol_{w}"].iloc[live])


@pytest.mark.parametrize("h", [2, 5, 20])
def test_naive_vol_is_the_forward_vol_seen_h_bars_later(btc, h):
    """naive_vol at t + h reads log returns t+1..t+h: exactly forward_vol's window at t."""
    fwd = forward_vol(btc, h).to_numpy()
    naive = naive_vol(btc, h).to_numpy()
    np.testing.assert_array_equal(naive[h:], fwd[:-h])


@pytest.mark.parametrize(("w", "threshold"), [(5, 0.3), (20, 0.3), (20, 0.6)])
def test_regime_persistence_is_the_regime_label_seen_w_bars_later(btc, w, threshold):
    fwd = forward_regime(btc, w, threshold).to_numpy()
    persist = regime_persistence(btc, w, threshold)
    assert persist.name == f"regime_persistence_{w}"
    assert persist.iloc[:w].isna().all()
    np.testing.assert_array_equal(persist.to_numpy()[w:], fwd[:-w])


def test_momentum_rank_known_answer(make_bars):
    a = make_bars([100.0, 100.0, 120.0, 90.0])  # 2-bar returns: +20%, -10%
    b = make_bars([100.0, 100.0, 110.0, 110.0])  # +10%, +10%
    ranks = momentum_rank({"A": a, "B": b}, 2)
    assert ranks["A"].name == "momentum_rank_2"
    np.testing.assert_allclose(ranks["A"], [np.nan, np.nan, 1.0, 0.5])
    np.testing.assert_allclose(ranks["B"], [np.nan, np.nan, 0.5, 1.0])


def test_baselines_are_nan_without_enough_history(make_bars):
    bars = make_bars([100.0, 101.0, 102.0])
    assert naive_vol(bars, 3).isna().all()
    assert ewma_vol(bars, 2, window=3).isna().all()
    assert regime_persistence(bars, 3).isna().all()
    assert long_run_vol(bars, 3).isna().all()
    assert momentum_rank({"A": bars}, 3)["A"].isna().all()


@pytest.mark.parametrize(
    ("call", "message"),
    [
        (lambda b: naive_vol(b, 1), "window must be an int >= 2"),
        (lambda b: long_run_vol(b, 1), "min_periods must be an int >= 2"),
        (lambda b: ewma_vol(b, 0), "span must be an int >= 1"),
        (lambda b: ewma_vol(b, 20, window=0), "window must be an int >= 1"),
        (lambda b: regime_persistence(b, 0), "window must be an int >= 1"),
        (lambda b: regime_persistence(b, 5, 2.0), r"threshold must be in \[0, 1\]"),
        (lambda b: momentum_rank({"A": b}, 0), "lookback must be an int >= 1"),
        (lambda b: momentum_rank({}, 5), "bars_by_asset is empty"),
        (lambda b: naive_vol(b, 2.5), "window must be an int >= 2"),
    ],
)
def test_baseline_argument_errors(btc, call, message):
    with pytest.raises(ValueError, match=message):
        call(btc)
