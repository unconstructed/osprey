"""The backtest contract: guarantees that hold for ANY runner (TESTING.md 5.6, spec "Identities every runner
must satisfy"). Every test runs once per entry of ``RUNNERS`` in ``tests/contract/conftest.py``.

Execution model under test: a decision at the close of bar t fills at the OPEN of bar t+1; between fills the
book holds coin units (weights drift); per bar, with g = open[t]/close[t-1] - 1, h = close[t]/open[t] - 1,
r = close[t]/close[t-1] - 1 and w0 = position[t-1]:

    fill:    1 + ret = (1 + w0 g)(1 - cost)(1 + w h),  position = w(1+h)/(1+wh),  turnover = |w - w0(1+g)/(1+w0 g)|
    no fill: 1 + ret = 1 + w0 r,                       position = w0(1+r)/(1+w0 r), turnover = cost = 0

The target w is not a result column. It is recovered from the position: w = p / (1 + h (1 - p)).
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest
from hypothesis import given
from hypothesis import strategies as st

from lab.runner.interface import BAR_COLUMNS, RESULT_COLUMNS, WEIGHT_TOL, validate_result
from lab.runner.reference import Costs

# ------------------------------------------------------------------------------------------------ helpers


def random_bars(n: int, seed: int, vol: float, gap: float) -> pd.DataFrame:
    """Valid daily bars with overnight gaps (open != previous close), so the drift at the open is exercised.

    ``vol``: std of log(close/open) per bar; ``gap``: std of log(open/previous close).
    """
    rng = np.random.default_rng(seed)
    body = rng.normal(0.0, vol, n)
    gaps = rng.normal(0.0, gap, n)
    gaps[0] = 0.0
    log_close = math.log(100.0) + np.cumsum(gaps + body)
    close = np.exp(log_close)
    open_ = np.exp(log_close - body)
    wick = rng.uniform(0.0, 0.02, (2, n))
    index = pd.date_range("2021-01-01", periods=n, freq="D", tz="UTC", name="ts")
    return pd.DataFrame(
        {
            "open": open_,
            "high": np.maximum(open_, close) * (1.0 + wick[0]),
            "low": np.minimum(open_, close) * (1.0 - wick[1]),
            "close": close,
            "volume": rng.uniform(100.0, 1000.0, n),
        },
        index=index,
    )


@st.composite
def bar_paths(draw, min_size: int = 20, max_size: int = 120) -> pd.DataFrame:
    n = draw(st.integers(min_size, max_size))
    seed = draw(st.integers(0, 2**32 - 1))
    vol = draw(st.sampled_from([0.0, 0.01, 0.04, 0.1]))  # 0.0: flat prices (no signal, zero volatility)
    gap = draw(st.sampled_from([0.0, 0.005, 0.03]))
    return random_bars(n, seed, vol, gap)


@st.composite
def paths_with_cut(draw) -> tuple[pd.DataFrame, int]:
    bars = draw(bar_paths())
    return bars, draw(st.integers(1, len(bars) - 1))


def tamper_from(bars: pd.DataFrame, cut: int, seed: int) -> pd.DataFrame:
    """Change every bar from ``cut`` on, except the open of bar ``cut``.

    That open is the fill price of the decision taken at close cut-1, so the turnover and cost of bar ``cut``
    must not move either. Only the price path through bar ``cut`` (h) may change its return and position.
    """
    rng = np.random.default_rng(seed)
    n = len(bars)
    o, h, lo, c, v = (bars[col].to_numpy(dtype=float, copy=True) for col in BAR_COLUMNS)
    c[cut:] *= np.exp(rng.normal(0.0, 0.2, n - cut))
    o[cut + 1 :] *= np.exp(rng.normal(0.0, 0.2, n - cut - 1))
    h[cut:] = np.maximum(o, c)[cut:] * (1.0 + rng.uniform(0.0, 0.05, n - cut))
    lo[cut:] = np.minimum(o, c)[cut:] * (1.0 - rng.uniform(0.0, 0.05, n - cut))
    v[cut:] = rng.uniform(1.0, 5000.0, n - cut)
    return pd.DataFrame({"open": o, "high": h, "low": lo, "close": c, "volume": v}, index=bars.index)


def moves(bars: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(g, h, r) for bars 1..n-1: gap into the open, open-to-close, close-to-close."""
    o = bars["open"].to_numpy(dtype=float)
    c = bars["close"].to_numpy(dtype=float)
    return o[1:] / c[:-1] - 1.0, c[1:] / o[1:] - 1.0, c[1:] / c[:-1] - 1.0


def columns(result: pd.DataFrame) -> tuple[np.ndarray, ...]:
    return tuple(result[col].to_numpy(dtype=float) for col in RESULT_COLUMNS)


def round_trips(result: pd.DataFrame) -> list[tuple[int, int | None]]:
    """(entry fill bar, exit fill bar or None while still open) of every round trip, read off the columns:
    a round trip starts with a fill out of a flat book and ends with the fill that makes it flat again."""
    _, pos, turnover, _ = columns(result)
    trips: list[tuple[int, int | None]] = []
    start = None
    for t in range(1, len(pos)):
        if turnover[t] > 0 and pos[t - 1] == 0.0:
            start = t
        elif turnover[t] > 0 and pos[t] == 0.0:
            trips.append((start, t))
            start = None
    if start is not None:
        trips.append((start, None))
    return trips


COST_MODELS = (
    Costs(),
    Costs().stressed(),
    Costs(pool_fee_bps=30.0, aggregator_fee_bps=10.0, gas_usd_per_trade=25.0),
)
FLAT_RATE = Costs(pool_fee_bps=20.0, slippage_bps=((1.0, 0.0),), gas_usd_per_trade=0.0)  # 20 bps, any size


# ------------------------------------------------------------------------------------------ the contract


def test_runner_trades_on_the_synthetic_market(runner, btc):
    """Non-vacuity: every entry trades, so the properties below are about real fills."""
    result = runner.run(btc, Costs())
    validate_result(result, btc)
    assert result.attrs["n_trades"] >= 1
    assert len(result.attrs["trade_returns"]) >= 1
    assert (result["turnover"] > 0).sum() == result.attrs["n_trades"]


def test_result_shape_and_types(runner, btc):
    result = runner.run(btc.iloc[:200])
    validate_result(result, btc.iloc[:200])
    assert result.index.equals(btc.index[:200])
    for col in RESULT_COLUMNS:
        assert result[col].dtype == np.float64
    assert isinstance(result.attrs["trade_returns"], np.ndarray)
    assert result.attrs["trade_returns"].dtype == np.float64
    assert isinstance(result.attrs["n_trades"], int)


@given(case=paths_with_cut(), tamper_seed=st.integers(0, 2**16))
def test_no_look_ahead(runner, case, tamper_seed):
    """Tamper the future from ``cut`` (keeping open[cut], the fill price of the last decision before it):
    every output row before ``cut`` is identical, the fill on bar ``cut`` too, and so is the trade log."""
    bars, cut = case
    tampered = tamper_from(bars, cut, tamper_seed)
    a = runner.run(bars, Costs())
    b = runner.run(tampered, Costs())
    cols = list(RESULT_COLUMNS)
    np.testing.assert_array_equal(a[cols].to_numpy()[:cut], b[cols].to_numpy()[:cut])
    assert a["turnover"].iloc[cut] == b["turnover"].iloc[cut]
    assert a["cost"].iloc[cut] == b["cost"].iloc[cut]
    closed = sum(1 for _, exit_bar in round_trips(a) if exit_bar is not None and exit_bar <= cut)
    np.testing.assert_array_equal(a.attrs["trade_returns"][:closed], b.attrs["trade_returns"][:closed])
    if "trades" in a.attrs:
        known = bars.index[cut]
        pd.testing.assert_frame_equal(
            a.attrs["trades"][a.attrs["trades"]["ts"] <= known],
            b.attrs["trades"][b.attrs["trades"]["ts"] <= known],
        )


@given(bars=bar_paths())
def test_per_bar_accounting_identities(runner, bars):
    result = runner.run(bars, Costs())
    ret, pos, turnover, cost = columns(result)
    g, h, r = moves(bars)
    w0 = pos[:-1]
    fill = turnover[1:] > 0
    tol = runner.tol
    assert ret[0] == pos[0] == turnover[0] == cost[0] == 0.0
    # no fill: coin units drift with the price; no free rebalance (TESTING.md bug #4)
    np.testing.assert_allclose((1 + ret[1:])[~fill], (1 + w0 * r)[~fill], rtol=0, atol=tol)
    np.testing.assert_allclose(pos[1:][~fill], (w0 * (1 + r) / (1 + w0 * r))[~fill], rtol=0, atol=tol)
    # fill at the open: drift to the open, trade to the target, pay, then ride the bar at the target
    drifted = w0 * (1 + g) / (1 + w0 * g)
    target = pos[1:] / (1 + h * (1 - pos[1:]))
    np.testing.assert_allclose(turnover[1:][fill], np.abs(target - drifted)[fill], rtol=0, atol=tol)
    expected = (1 + w0 * g) * (1 - cost[1:]) * (1 + target * h)
    np.testing.assert_allclose((1 + ret[1:])[fill], expected[fill], rtol=0, atol=tol)


@given(bars=bar_paths())
def test_only_fills_trade_and_every_fill_pays(runner, bars):
    result = runner.run(bars, Costs())
    _, _, turnover, cost = columns(result)
    assert result.attrs["n_trades"] == int((turnover > 0).sum())
    assert (cost[turnover == 0] == 0.0).all()
    assert (cost[turnover > 0] > 0.0).all()  # costs on: no fill is free (TESTING.md bug #6)


@given(bars=bar_paths())
def test_fill_log_lists_every_fill_at_the_open(runner, bars):
    result = runner.run(bars, Costs())
    if "trades" not in result.attrs:
        pytest.skip(f"{runner.name} keeps no fill log (optional)")
    trades = result.attrs["trades"]
    _, pos, turnover, cost = columns(result)
    g, h, _ = moves(bars)
    at = np.flatnonzero(turnover > 0)
    assert len(trades) == result.attrs["n_trades"] == len(at)
    assert list(trades["ts"]) == list(bars.index[at])
    np.testing.assert_array_equal(trades["price"].to_numpy(), bars["open"].to_numpy()[at])
    np.testing.assert_allclose(trades["turnover"].to_numpy(), turnover[at], rtol=0, atol=runner.tol)
    np.testing.assert_allclose(trades["cost"].to_numpy(), cost[at], rtol=0, atol=runner.tol)
    w0, gi, hi = pos[at - 1], g[at - 1], h[at - 1]
    np.testing.assert_allclose(
        trades["weight_before"].to_numpy(), w0 * (1 + gi) / (1 + w0 * gi), atol=runner.tol
    )
    target = pos[at] / (1 + hi * (1 - pos[at]))
    np.testing.assert_allclose(trades["weight_after"].to_numpy(), target, rtol=0, atol=runner.tol)
    buys = trades["weight_after"].to_numpy() > trades["weight_before"].to_numpy()
    assert list(trades["side"]) == ["buy" if b else "sell" for b in buys]


@given(bars=bar_paths(), costs=st.sampled_from(COST_MODELS))
def test_costs_scale_each_bar_return(runner, bars, costs):
    """Decisions don't depend on costs, so (1 + ret_with_costs) == (1 + ret_zero_cost) * (1 - cost) bar by bar."""
    free = runner.run(bars, Costs.zero())
    paid = runner.run(bars, costs)
    tol = runner.tol
    assert (free["cost"] == 0.0).all()
    np.testing.assert_allclose(paid["position"], free["position"], rtol=0, atol=tol)
    np.testing.assert_allclose(paid["turnover"], free["turnover"], rtol=0, atol=tol)
    np.testing.assert_allclose(1 + paid["ret"], (1 + free["ret"]) * (1 - paid["cost"]), rtol=0, atol=tol)
    assert paid.attrs["n_trades"] == free.attrs["n_trades"]


@given(bars=bar_paths(), k=st.floats(0.25, 8.0))
def test_flat_rate_cost_is_turnover_times_rate(runner, bars, k):
    """With a size-independent rate and no gas, cost == turnover * rate, and stressing by k scales it by k."""
    base = runner.run(bars, FLAT_RATE)
    stressed = runner.run(bars, FLAT_RATE.stressed(k))
    np.testing.assert_allclose(base["cost"], 0.002 * base["turnover"], rtol=0, atol=runner.tol)
    np.testing.assert_allclose(stressed["cost"], k * base["cost"], rtol=0, atol=runner.tol)


@given(bars=bar_paths())
def test_trade_returns_match_the_portfolio_at_zero_cost(runner, bars):
    """Each round trip's return equals the portfolio's growth from just before its entry to just after its
    exit (an open one is marked at the last close), and prod(1 + trade_returns) == prod(1 + ret)."""
    result = runner.run(bars, Costs.zero())
    value = np.cumprod(1.0 + result["ret"].to_numpy())  # value at each close, starting at 1
    trips = round_trips(result)
    trade_returns = result.attrs["trade_returns"]
    assert len(trade_returns) == len(trips)
    expected = np.array([value[-1 if x is None else x] / value[e - 1] for e, x in trips])
    rtol = runner.tol * len(bars)
    np.testing.assert_allclose(1.0 + trade_returns, expected, rtol=rtol, atol=0)
    assert np.prod(1.0 + trade_returns) == pytest.approx(value[-1], rel=rtol)


@given(bars=bar_paths())
def test_outputs_stay_in_bounds(runner, bars):
    result = runner.run(bars, Costs())
    validate_result(result, bars)
    ret, pos, turnover, cost = columns(result)
    assert (pos >= 0.0).all() and (pos <= 1.0 + WEIGHT_TOL).all()  # spot only: no shorts, no leverage
    assert (turnover >= 0.0).all() and (turnover <= 1.0 + WEIGHT_TOL).all()
    assert (cost >= 0.0).all() and (cost < 1.0).all()
    assert (ret > -1.0).all()
    assert np.isfinite(result.attrs["trade_returns"]).all() and (result.attrs["trade_returns"] > -1.0).all()


def test_runs_are_deterministic_and_leave_inputs_alone(runner, btc):
    bars = btc.iloc[:300].copy()
    bars_before = bars.copy()
    params_before = dict(runner.params)
    a = runner.run(bars, Costs())
    b = runner.run(bars, Costs())
    cols = list(RESULT_COLUMNS)
    np.testing.assert_array_equal(a[cols].to_numpy(), b[cols].to_numpy())
    np.testing.assert_array_equal(a.attrs["trade_returns"], b.attrs["trade_returns"])
    assert a.attrs["n_trades"] == b.attrs["n_trades"]
    pd.testing.assert_frame_equal(bars, bars_before)
    assert runner.params == params_before


def test_bad_params_raise_value_error(runner, btc):
    assert runner.bad_params, "each runner entry lists parameter sets it must reject"
    for bad in runner.bad_params:
        with pytest.raises(ValueError):
            runner.fn(bad, btc)


BAD_BARS = {
    "not_a_frame": lambda b: b["close"],
    "one_row": lambda b: b.iloc[:1],
    "missing_volume": lambda b: b.drop(columns="volume"),
    "naive_index": lambda b: b.tz_localize(None),
    "unsorted": lambda b: b.iloc[::-1],
    "duplicate_ts": lambda b: pd.concat([b.iloc[:3], b.iloc[2:]]),
    "nan_close": lambda b: b.assign(close=b["close"].where(b.index != b.index[5])),
    "non_positive_price": lambda b: b.assign(low=-b["low"]),
    "high_below_close": lambda b: b.assign(high=b["close"] * 0.5),
}


@pytest.mark.parametrize("breaker", list(BAD_BARS.values()), ids=list(BAD_BARS))
def test_bad_bars_raise_value_error(runner, btc, breaker):
    with pytest.raises(ValueError):
        runner.run(breaker(btc.iloc[:60]))
