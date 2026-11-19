"""Look-ahead and correctness tests for lab.models.features and the live FeatureBuffer (TESTING.md section 3).

- Tamper the future: changing any bar from ``cut`` on never changes a feature before ``cut``.
- Touch the present (TESTING 5.2B, fixed version): changing only bar ``t`` changes every feature at ``t``.
- Exact windows: each feature at ``t`` reads bars ``t - BARS_NEEDED + 1 .. t``, no more and no less.
- Price- and volume-scale invariance (exact for powers of two, within round-off otherwise).
- Known answers for every feature family, computed here with ``math``/``statistics`` loops.
- Live/backtest parity: ``FeatureBuffer`` equals ``compute_features`` bit for bit on every bar.
- Cross-sectional ranks: hand-checked values, ties, NaN, point in time.
"""

from __future__ import annotations

import math
import statistics
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest
from hypothesis import example, given
from hypothesis import strategies as st

from lab.data.synthetic import synthetic_market
from lab.models.features import (
    BARS_NEEDED,
    EWMA_SPAN,
    EWMA_WINDOW,
    FEATURES,
    RANK_SUFFIX,
    WARMUP,
    compute_features,
    cross_sectional_ranks,
)
from lab.models.online import FeatureBuffer

N_BARS = 1500  # length of the session ``market`` fixture
PRICE_COLS = ["open", "high", "low", "close"]


def scale_rows(bars: pd.DataFrame, rows, seed: int, sigma: float = 0.2) -> pd.DataFrame:
    """Copy of ``bars`` with each listed row's prices (one factor per row) and volume rescaled.

    Scaling a whole bar's OHLC by one factor keeps it a valid bar.
    """
    rows = np.asarray(list(rows), dtype=int)
    out = bars.copy()
    if len(rows) == 0:
        return out
    rng = np.random.default_rng(seed)
    price_f = np.exp(rng.normal(0.0, sigma, len(rows)))
    vol_f = np.exp(rng.normal(0.0, sigma, len(rows)))
    for col in PRICE_COLS:
        j = out.columns.get_loc(col)
        out.iloc[rows, j] = out.iloc[rows, j].to_numpy() * price_f
    j = out.columns.get_loc("volume")
    out.iloc[rows, j] = out.iloc[rows, j].to_numpy() * vol_f
    return out


def make_ohlcv(close, high_spread, low_spread, volume, start="2020-01-01") -> pd.DataFrame:
    """Bars with open = previous close and per-bar wick sizes (fractions above/below the body)."""
    close = np.asarray(close, dtype=float)
    open_ = np.concatenate([[close[0]], close[:-1]])
    high = np.maximum(open_, close) * (1 + np.asarray(high_spread, dtype=float))
    low = np.minimum(open_, close) * (1 - np.asarray(low_spread, dtype=float))
    index = pd.date_range(start, periods=len(close), freq="D", tz="UTC", name="ts")
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": np.asarray(volume, dtype=float)},
        index=index,
    )


# ---------------------------------------------------------------- names, shape, warm-up


def test_feature_names_and_order():
    assert FEATURES == (
        "ret_1",
        "ret_5",
        "ret_20",
        "ret_60",
        "vol_10",
        "vol_20",
        "vol_60",
        "ewma_vol_20",
        "park_vol_20",
        "ma_dist_20",
        "ma_dist_100",
        "drawdown_60",
        "eff_ratio_20",
        "volume_z_20",
        "vol_ratio_10_60",
    )
    assert set(BARS_NEEDED) == set(FEATURES)
    # the finite EWMA window (100 log returns = 101 closes) is the longest window
    assert EWMA_SPAN == 20 and EWMA_WINDOW == 100
    assert WARMUP == max(BARS_NEEDED.values()) == 101


def test_output_shape_and_warm_up(btc, features):
    assert list(features.columns) == list(FEATURES)
    assert features.index.equals(btc.index)
    assert (features.dtypes == np.float64).all()
    # a row is either entirely NaN (warming up) or entirely finite
    assert features.iloc[: WARMUP - 1].isna().all().all()
    assert np.isfinite(features.iloc[WARMUP - 1 :].to_numpy()).all()


def test_short_history(btc):
    assert compute_features(btc.iloc[: WARMUP - 1]).isna().all().all()
    just_enough = compute_features(btc.iloc[:WARMUP])
    assert just_enough.iloc[:-1].isna().all().all()
    assert np.isfinite(just_enough.iloc[-1].to_numpy()).all()


def test_invalid_bars_raise(btc):
    bad = btc.copy()
    bad.iloc[5, bad.columns.get_loc("close")] = -1.0
    with pytest.raises(ValueError, match="non-positive prices"):
        compute_features(bad)


# ---------------------------------------------------------------- look-ahead


@given(cut=st.integers(1, N_BARS - 1), seed=st.integers(0, 2**32 - 1))
def test_no_feature_changes_when_the_future_changes(btc, features, cut, seed):
    tampered = scale_rows(btc, range(cut, N_BARS), seed)
    got = compute_features(tampered)
    pd.testing.assert_frame_equal(got.iloc[:cut], features.iloc[:cut], check_exact=True)
    if cut >= WARMUP - 1:  # not vacuous: the tampered bar itself does move its features
        assert not np.array_equal(got.iloc[cut].to_numpy(), features.iloc[cut].to_numpy())


@example(cut=362)  # TESTING 5.2B: wide-range day where lowering only the close left high/low unchanged
@example(cut=146)  # the earlier drawdown case
@given(cut=st.integers(WARMUP - 1, N_BARS - 1))
def test_each_feature_reacts_to_the_present_bar(btc, features, cut):
    """Touch only bar ``cut``, always widening its range (the TESTING 5.2B fix), so every feature
    family, including range volatility, has something to react to."""
    tampered = btc.copy()
    col = tampered.columns.get_loc
    tampered.iloc[cut, col("close")] *= 0.7
    tampered.iloc[cut, col("high")] *= 1.05
    tampered.iloc[cut, col("low")] = min(tampered["low"].iloc[cut], tampered["close"].iloc[cut]) * 0.95
    tampered.iloc[cut, col("volume")] *= 3
    got = compute_features(tampered)
    pd.testing.assert_frame_equal(got.iloc[:cut], features.iloc[:cut], check_exact=True)
    unchanged = [name for name in FEATURES if got[name].iloc[cut] == features[name].iloc[cut]]
    assert unchanged == []


@given(
    t=st.integers(WARMUP - 1, N_BARS - 1),
    name=st.sampled_from(FEATURES),
    seed=st.integers(0, 2**32 - 1),
)
def test_each_feature_reads_exactly_its_window(btc, features, t, name, seed):
    need = BARS_NEEDED[name]
    oldest = t - need + 1
    # every bar before the window is irrelevant ...
    before = compute_features(scale_rows(btc, range(0, oldest), seed))
    assert before[name].iloc[t] == features[name].iloc[t]
    # ... and the oldest bar inside it matters: its close jumps tenfold (a new window high), its
    # range widens and its volume triples
    tampered = btc.copy()
    col = tampered.columns.get_loc
    tampered.iloc[oldest, col("close")] *= 10.0
    tampered.iloc[oldest, col("high")] = tampered["close"].iloc[oldest] * 1.05
    tampered.iloc[oldest, col("low")] *= 0.9
    tampered.iloc[oldest, col("volume")] *= 3.0
    inside = compute_features(tampered)
    assert inside[name].iloc[t] != features[name].iloc[t]


# ---------------------------------------------------------------- scale invariance


@given(power=st.integers(-30, 30))
def test_power_of_two_price_scale_is_exact(btc, features, power):
    scaled = btc.copy()
    scaled[PRICE_COLS] = scaled[PRICE_COLS] * 2.0**power
    pd.testing.assert_frame_equal(compute_features(scaled), features, check_exact=True)


@given(power=st.integers(-30, 30))
def test_power_of_two_volume_scale_is_exact(btc, features, power):
    scaled = btc.copy()
    scaled["volume"] = scaled["volume"] * 2.0**power
    pd.testing.assert_frame_equal(compute_features(scaled), features, check_exact=True)


@given(k=st.floats(1e-4, 1e4, allow_nan=False, allow_infinity=False))
def test_price_scale_invariance(btc, features, k):
    scaled = btc.copy()
    scaled[PRICE_COLS] = scaled[PRICE_COLS] * k
    # any factor: equal up to round-off in the price ratios
    np.testing.assert_allclose(compute_features(scaled).to_numpy(), features.to_numpy(), rtol=1e-9, atol=1e-12)


@given(k=st.floats(1e-4, 1e4, allow_nan=False, allow_infinity=False))
def test_volume_scale_invariance(btc, features, k):
    scaled = btc.copy()
    scaled["volume"] = scaled["volume"] * k
    np.testing.assert_allclose(compute_features(scaled).to_numpy(), features.to_numpy(), rtol=1e-9, atol=1e-12)


# ---------------------------------------------------------------- known answers


def hand_features(bars: pd.DataFrame, t: int) -> dict[str, float]:
    """Every feature at row t, written out with math/statistics loops (independent of the code)."""
    c = bars["close"].tolist()
    h = bars["high"].tolist()
    lo = bars["low"].tolist()
    v = bars["volume"].tolist()

    def r(i):  # log return of bar i
        return math.log(c[i] / c[i - 1])

    def vol(w):
        return statistics.stdev([r(i) for i in range(t - w + 1, t + 1)])

    lam = 1 - 2 / (20 + 1)
    ewma_num = sum(lam**age * r(t - age) ** 2 for age in range(100))
    ewma_den = sum(lam**age for age in range(100))
    park = math.sqrt(sum(math.log(h[i] / lo[i]) ** 2 for i in range(t - 19, t + 1)) / (20 * 4 * math.log(2)))
    path = sum(abs(c[i] - c[i - 1]) for i in range(t - 19, t + 1))
    vwin = v[t - 19 : t + 1]
    return {
        "ret_1": math.log(c[t] / c[t - 1]),
        "ret_5": math.log(c[t] / c[t - 5]),
        "ret_20": math.log(c[t] / c[t - 20]),
        "ret_60": math.log(c[t] / c[t - 60]),
        "vol_10": vol(10),
        "vol_20": vol(20),
        "vol_60": vol(60),
        "ewma_vol_20": math.sqrt(ewma_num / ewma_den),
        "park_vol_20": park,
        "ma_dist_20": c[t] / statistics.fmean(c[t - 19 : t + 1]) - 1,
        "ma_dist_100": c[t] / statistics.fmean(c[t - 99 : t + 1]) - 1,
        "drawdown_60": c[t] / max(c[t - 59 : t + 1]) - 1,
        "eff_ratio_20": abs(c[t] - c[t - 20]) / path,
        "volume_z_20": (v[t] - statistics.fmean(vwin)) / statistics.stdev(vwin),
        "vol_ratio_10_60": vol(10) / vol(60),
    }


@pytest.mark.parametrize("t", [WARMUP - 1, WARMUP, 250, 777, N_BARS - 1])
def test_known_feature_values_on_market_data(btc, features, t):
    expected = hand_features(btc, t)
    for name in FEATURES:
        assert features[name].iloc[t] == pytest.approx(expected[name], rel=1e-9, abs=1e-13), name


def test_known_feature_values_on_a_hand_built_path():
    n = WARMUP + 40
    i = np.arange(n)
    close = 100.0 * np.exp(0.002 * i + 0.03 * np.sin(i / 3.0) + 0.01 * np.cos(i * 1.7))
    bars = make_ohlcv(close, 0.004 + 0.003 * (i % 5), 0.002 + 0.002 * (i % 7), 1000.0 + 300.0 * np.sin(i))
    got = compute_features(bars)
    for t in (WARMUP - 1, WARMUP + 17, n - 1):
        expected = hand_features(bars, t)
        for name in FEATURES:
            assert got[name].iloc[t] == pytest.approx(expected[name], rel=1e-9, abs=1e-13), (t, name)


def test_constant_prices(make_bars):
    """No movement at all: returns, volatilities, distances and drawdown are 0; the efficiency ratio
    is 0 (nothing moved, not a trend); the 0/0 volatility ratio is 1; constant volume has z = 0."""
    spread = 0.01
    got = compute_features(make_bars([50.0] * (WARMUP + 5), spread=spread)).iloc[-1]
    zero = [n for n in FEATURES if n not in ("park_vol_20", "vol_ratio_10_60")]
    assert (got[zero] == 0.0).all(), got[zero]
    assert got["vol_ratio_10_60"] == 1.0
    log_range = math.log((1 + spread / 2) / (1 - spread / 2))
    assert got["park_vol_20"] == pytest.approx(log_range / math.sqrt(4 * math.log(2)), rel=1e-12)


def test_steady_growth_path(make_bars):
    """A straight line in log price: k-bar return = k * g, a perfect trend (efficiency 1), no drawdown,
    (numerically) no volatility so the ratio is the flat-case 1, and a closed-form SMA distance."""
    g = 0.01
    close = 100.0 * np.exp(g * np.arange(WARMUP + 10))
    got = compute_features(make_bars(close)).iloc[-1]
    for k in (1, 5, 20, 60):
        assert got[f"ret_{k}"] == pytest.approx(k * g, rel=1e-9)
    assert got["eff_ratio_20"] == pytest.approx(1.0, rel=1e-12)
    assert got["eff_ratio_20"] <= 1.0
    assert got["drawdown_60"] == 0.0
    for name in ("vol_10", "vol_20", "vol_60"):
        assert got[name] < 1e-14
    assert got["ewma_vol_20"] == pytest.approx(g, rel=1e-9)  # not demeaned: sqrt(mean of g**2)
    assert got["vol_ratio_10_60"] == 1.0
    for w in (20, 100):
        mean_ratio = np.mean(np.exp(-g * np.arange(w)))  # SMA / close
        assert got[f"ma_dist_{w}"] == pytest.approx(1 / mean_ratio - 1, rel=1e-9)


def test_drawdown_known_answer(make_bars):
    # rise to 200, then fall to 100 within 60 bars: drawdown -50%; 61 bars later the peak has left the window
    close = [100.0] * WARMUP + [200.0] + [100.0] * 30
    got = compute_features(make_bars(close))
    assert got["drawdown_60"].iloc[-1] == pytest.approx(-0.5, rel=1e-12)
    later = compute_features(make_bars(close + [100.0] * 30))
    assert later["drawdown_60"].iloc[-1] == 0.0


def test_efficiency_ratio_zigzag(make_bars):
    # 100, 101, 100, ...: twenty unit moves and no net move over every 20-bar window -> 0
    close = [100.0 + (i % 2) for i in range(WARMUP + 4)]
    assert (compute_features(make_bars(close))["eff_ratio_20"].iloc[WARMUP - 1 :] == 0.0).all()
    # last close 103 instead of 100: net move 3 (from 100), path 19 unit moves + a final move of 2 -> 3/21
    close[-1] = 103.0
    assert compute_features(make_bars(close))["eff_ratio_20"].iloc[-1] == pytest.approx(3 / 21, rel=1e-12)


def test_volume_spike_z_score(make_bars):
    """19 equal volumes and one spike: z = 19 / sqrt(20) whatever the sizes."""
    bars = make_bars([100.0] * (WARMUP + 1), volume=1000.0)
    bars.iloc[-1, bars.columns.get_loc("volume")] = 5000.0
    got = compute_features(bars)["volume_z_20"].iloc[-1]
    assert got == pytest.approx(19 / math.sqrt(20), rel=1e-12)


def test_all_zero_volume_is_flat(make_bars):
    assert (compute_features(make_bars([100.0] * WARMUP, volume=0.0))["volume_z_20"].iloc[-1]) == 0.0


def test_ewma_single_shock_known_answer(make_bars):
    """Flat prices, then one return r at age a: EWMA variance = lam**a * r**2 / sum(lam**j, j < 100)."""
    lam = 1 - 2 / 21
    norm = sum(lam**j for j in range(100))
    for age in (0, 1, 7, 99):
        close = [100.0] * (WARMUP + 10)
        jump = len(close) - 1 - age
        close[jump:] = [110.0] * (len(close) - jump)
        r = math.log(1.1)
        got = compute_features(make_bars(close))["ewma_vol_20"].iloc[-1]
        assert got == pytest.approx(math.sqrt(lam**age * r * r / norm), rel=1e-12), age
    # at age 100 the shock has left the finite window
    close = [100.0] * (WARMUP + 10)
    close[len(close) - 101 :] = [110.0] * 101
    assert compute_features(make_bars(close))["ewma_vol_20"].iloc[-1] == 0.0


# ---------------------------------------------------------------- live FeatureBuffer


def feed(buffer: FeatureBuffer, bars: pd.DataFrame):
    """Yield (row number, latest()) after feeding each bar."""
    for i, (ts, row) in enumerate(zip(bars.index, bars.itertuples(index=False), strict=True)):
        buffer.update(ts, row.open, row.high, row.low, row.close, row.volume)
        yield i, buffer.latest()


def assert_parity(bars: pd.DataFrame, buffer: FeatureBuffer) -> None:
    batch = compute_features(bars).to_numpy()
    for i, live in feed(buffer, bars):
        if i < WARMUP - 1:
            assert live is None, i
            assert np.isnan(batch[i]).all()
        else:
            assert list(live) == list(FEATURES)
            np.testing.assert_array_equal(np.array(list(live.values())), batch[i], err_msg=f"bar {i}")


@pytest.mark.parametrize("asset", ["BTC", "ETH"])
def test_live_buffer_equals_backtest_for_every_bar(market, asset):
    assert_parity(market[asset], FeatureBuffer())


def test_live_buffer_with_a_longer_memory(market):
    buffer = FeatureBuffer(maxlen=WARMUP + 50)
    assert_parity(market["ETH"].iloc[:400], buffer)
    assert len(buffer) == WARMUP + 50


@given(seed=st.integers(0, 2**32 - 1), n=st.integers(WARMUP - 3, WARMUP + 25))
def test_live_buffer_parity_on_random_markets(seed, n):
    assert_parity(synthetic_market(n, assets=("X",), seed=seed)["X"], FeatureBuffer())


def test_buffer_state_and_timestamps(btc):
    buffer = FeatureBuffer()
    assert len(buffer) == 0 and not buffer.ready and buffer.last_ts is None
    assert buffer.latest() is None
    row = btc.iloc[0]
    buffer.update(1_600_000_000_000_000_000, row.open, row.high, row.low, row.close, row.volume)  # ns int
    assert buffer.last_ts == pd.Timestamp("2020-09-13 12:26:40", tz="UTC")
    buffer.update(datetime(2020, 9, 14), row.open, row.high, row.low, row.close, row.volume)  # naive = UTC
    assert buffer.last_ts == pd.Timestamp("2020-09-14", tz="UTC")
    eastern = timezone(timedelta(hours=-5))
    buffer.update(datetime(2020, 9, 14, 1, tzinfo=eastern), row.open, row.high, row.low, row.close, row.volume)
    assert buffer.last_ts == pd.Timestamp("2020-09-14 06:00", tz="UTC")
    assert len(buffer) == 3


def test_buffer_accepts_price_objects(btc):
    """Nautilus Price/Quantity convert with float(); Decimal stands in for them here."""
    plain, objects = FeatureBuffer(), FeatureBuffer()
    for ts, row in btc.iloc[: WARMUP + 2].iterrows():
        plain.update(ts, row.open, row.high, row.low, row.close, row.volume)
        objects.update(ts, *(Decimal(repr(float(x))) for x in (row.open, row.high, row.low, row.close, row.volume)))
    assert objects.latest() == plain.latest()


def test_buffer_latest_returns_a_copy(btc):
    buffer = FeatureBuffer()
    for _ in feed(buffer, btc.iloc[:WARMUP]):
        pass
    first = buffer.latest()
    first["ret_1"] = 123.0
    assert buffer.latest()["ret_1"] != 123.0


@pytest.mark.parametrize("maxlen", [WARMUP - 1, 0, 2.5, True, "200"])
def test_buffer_rejects_bad_maxlen(maxlen):
    with pytest.raises(ValueError, match="maxlen must be an int"):
        FeatureBuffer(maxlen=maxlen)


@pytest.mark.parametrize(
    ("bar", "message"),
    [
        ((10.0, 11.0, 9.0, float("nan"), 1.0), "NaN or infinite"),
        ((10.0, float("inf"), 9.0, 10.0, 1.0), "NaN or infinite"),
        ((10.0, 11.0, 0.0, 10.0, 1.0), "non-positive"),
        ((10.0, 11.0, 9.0, 10.0, -1.0), "negative volume"),
        ((10.0, 9.5, 9.0, 10.0, 1.0), "low <= open, close <= high"),
        ((10.0, 11.0, 10.5, 10.6, 1.0), "low <= open, close <= high"),
    ],
)
def test_buffer_rejects_bad_bars_and_stays_unchanged(bar, message):
    buffer = FeatureBuffer()
    buffer.update("2024-01-01", 10.0, 11.0, 9.0, 10.0, 1.0)
    with pytest.raises(ValueError, match=message):
        buffer.update("2024-01-02", *bar)
    assert len(buffer) == 1 and buffer.last_ts == pd.Timestamp("2024-01-01", tz="UTC")


@pytest.mark.parametrize("ts", ["2024-01-01", "2023-12-31"])
def test_buffer_rejects_out_of_order_bars(ts):
    buffer = FeatureBuffer()
    buffer.update("2024-01-01", 10.0, 11.0, 9.0, 10.0, 1.0)
    with pytest.raises(ValueError, match="strictly increasing"):
        buffer.update(ts, 10.0, 11.0, 9.0, 10.0, 1.0)
    assert len(buffer) == 1


# ---------------------------------------------------------------- cross-sectional ranks


def test_cross_sectional_ranks_known_answer():
    idx = pd.date_range("2024-01-01", periods=3, freq="D", tz="UTC", name="ts")
    frames = {
        "A": pd.DataFrame({"f": [1.0, 2.0, np.nan], "g": [0.0, 0.0, 0.0]}, index=idx),
        "B": pd.DataFrame({"f": [2.0, 2.0, 5.0], "g": [1.0, 1.0, 1.0]}, index=idx),
        "C": pd.DataFrame({"f": [3.0, 1.0, 4.0], "g": [2.0, 2.0, 2.0]}, index=idx),
    }
    ranks = cross_sectional_ranks(frames, ["f"])
    assert list(ranks["A"].columns) == [f"f{RANK_SUFFIX}"] == ["f_xs_rank"]
    np.testing.assert_allclose(ranks["A"]["f_xs_rank"], [1 / 3, 2.5 / 3, np.nan])  # tie averaged; NaN unranked
    np.testing.assert_allclose(ranks["B"]["f_xs_rank"], [2 / 3, 2.5 / 3, 1.0])
    np.testing.assert_allclose(ranks["C"]["f_xs_rank"], [1.0, 1 / 3, 0.5])  # only 2 assets ranked on day 3


def test_cross_sectional_ranks_on_market_features(market):
    feats = {asset: compute_features(bars) for asset, bars in market.items()}
    ranks = cross_sectional_ranks(feats)
    for asset in market:
        assert list(ranks[asset].columns) == [f"{n}{RANK_SUFFIX}" for n in FEATURES]
        assert ranks[asset].index.equals(market[asset].index)
        assert ranks[asset].iloc[: WARMUP - 1].isna().all().all()
    # two assets: ranks are {0.5, 1.0}, or 0.75 each on a tie, so they always sum to 1.5
    total = ranks["BTC"].iloc[WARMUP - 1 :].to_numpy() + ranks["ETH"].iloc[WARMUP - 1 :].to_numpy()
    np.testing.assert_allclose(total, 1.5)
    btc_higher = feats["BTC"]["ret_20"] > feats["ETH"]["ret_20"]
    assert (ranks["BTC"]["ret_20_xs_rank"][btc_higher] == 1.0).all()


def test_cross_sectional_ranks_align_different_indexes():
    a_idx = pd.date_range("2024-01-01", periods=3, freq="D", tz="UTC", name="ts")
    b_idx = pd.date_range("2024-01-02", periods=3, freq="D", tz="UTC", name="ts")
    ranks = cross_sectional_ranks(
        {"A": pd.DataFrame({"f": [1.0, 1.0, 3.0]}, index=a_idx), "B": pd.DataFrame({"f": [2.0, 2.0, 2.0]}, index=b_idx)},
        ["f"],
    )
    assert ranks["A"].index.equals(a_idx) and ranks["B"].index.equals(b_idx)
    np.testing.assert_allclose(ranks["A"]["f_xs_rank"], [1.0, 0.5, 1.0])  # day 1: A alone
    np.testing.assert_allclose(ranks["B"]["f_xs_rank"], [1.0, 0.5, 1.0])  # day 4: B alone


@given(cut=st.integers(1, N_BARS - 1), seed=st.integers(0, 2**32 - 1))
def test_cross_sectional_ranks_are_point_in_time(market, cut, seed):
    feats = {asset: compute_features(bars) for asset, bars in market.items()}
    before = cross_sectional_ranks(feats)
    tampered = dict(feats, ETH=compute_features(scale_rows(market["ETH"], range(cut, N_BARS), seed)))
    after = cross_sectional_ranks(tampered)
    for asset in market:
        pd.testing.assert_frame_equal(after[asset].iloc[:cut], before[asset].iloc[:cut], check_exact=True)


def test_cross_sectional_ranks_errors(features):
    with pytest.raises(ValueError, match="empty"):
        cross_sectional_ranks({})
    with pytest.raises(ValueError, match="missing columns"):
        cross_sectional_ranks({"BTC": features[["ret_1"]]})
