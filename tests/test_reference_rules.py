"""Reference backtester rules (TESTING.md 5.6): dip-buy specifics and the benchmarks, on hand-built paths.

Runner-agnostic guarantees (look-ahead, identities, cost scaling, bounds) live in tests/contract/. This file
pins what the reference rules decide: entry at the open after the drop bar, stop and hold exits at the open
after their signal bar, vol-target sizing by hand, no re-entry on the exit bar (bug #5), weights that drift
as coin units (bug #4), a constant mix that pays every rebalance (bug #6), random-entry layout and seeds.

``make_bars`` paths have open == previous close (no gap), so a fill at the open of bar t trades at close[t-1].
"""

from __future__ import annotations

import math
import statistics

import numpy as np
import pandas as pd
import pytest
from hypothesis import given
from hypothesis import strategies as st

from lab.runner.interface import validate_result
from lab.runner.reference import Costs, buy_and_hold, constant_mix, dip_buy, random_entry, realised_vol

ZERO = Costs.zero()


def fill_bars(result: pd.DataFrame) -> list[int]:
    return np.flatnonzero(result["turnover"].to_numpy() > 0).tolist()


def sides(result: pd.DataFrame) -> list[str]:
    return result.attrs["trades"]["side"].tolist()


# ------------------------------------------------------------------------------------------------ dip buy


def test_entry_fills_at_the_open_after_the_drop_bar(make_bars):
    bars = make_bars([100.0] * 6 + [85.0, 90.0, 95.0])  # drop bar: 6 (85 is -15% from the 5-bar high)
    result = dip_buy({"drop": 0.1, "lookback": 5}, bars, ZERO)
    validate_result(result, bars)
    assert fill_bars(result) == [7]
    trades = result.attrs["trades"]
    assert trades["ts"].tolist() == [bars.index[7]]
    assert sides(result) == ["buy"]
    assert trades["price"].tolist() == [85.0] == [bars["open"].iloc[7]]
    assert (result["position"].iloc[:7] == 0.0).all() and (result["position"].iloc[7:] == 1.0).all()
    # still open at the end: marked to market at the last close, no exit fill
    assert result.attrs["n_trades"] == 1
    assert result.attrs["trade_returns"] == pytest.approx([95.0 / 85.0 - 1.0], rel=1e-12)


def test_a_drop_exactly_at_the_threshold_signals(make_bars):
    """The rule is close / peak - 1 <= -drop: 50 / 100 - 1 == -0.5 exactly, so drop 0.5 triggers; 51 doesn't."""
    exact = dip_buy({"drop": 0.5, "lookback": 5}, make_bars([100.0] * 6 + [50.0, 50.0]), ZERO)
    assert fill_bars(exact) == [7]
    short = dip_buy({"drop": 0.5, "lookback": 5}, make_bars([100.0] * 6 + [51.0, 51.0]), ZERO)
    assert fill_bars(short) == []


def test_a_signal_on_the_last_bar_is_never_filled(make_bars):
    bars = make_bars([100.0] * 6 + [80.0])  # the dip closes on the last bar: there is no next open
    result = dip_buy({"drop": 0.1, "lookback": 5}, bars, ZERO)
    assert fill_bars(result) == [] and result.attrs["n_trades"] == 0
    assert (result.to_numpy() == 0.0).all() and len(result.attrs["trade_returns"]) == 0


def test_entry_needs_a_full_lookback_window(make_bars):
    bars = make_bars([100.0, 100.0, 100.0, 80.0, 80.0, 80.0, 80.0])
    result = dip_buy({"drop": 0.1, "lookback": 5}, bars, ZERO)
    assert fill_bars(result) == [6]  # first full window [0..5] closes at bar 5, not at the drop (bar 3)


def test_stop_loss_exits_at_the_open_after_the_stop_bar(make_bars):
    # entry fills at open 7 = 85 -> stop level 80.75; closes 84, 82 hold; 80 at bar 9 triggers
    bars = make_bars([100.0] * 6 + [85.0, 84.0, 82.0, 80.0, 80.0])
    result = dip_buy({"drop": 0.1, "lookback": 5, "stop": 0.05}, bars, ZERO)
    assert fill_bars(result) == [7, 10]
    assert sides(result) == ["buy", "sell"]
    assert result.attrs["trades"]["price"].tolist() == [85.0, 80.0]
    assert result["position"].iloc[10] == 0.0
    assert result.attrs["trade_returns"] == pytest.approx([80.0 / 85.0 - 1.0], rel=1e-12)


def test_a_close_exactly_at_the_stop_level_exits(make_bars):
    """Exit when close <= fill * (1 - stop): entry fills at 80, stop 0.25 -> level 60.0 exactly."""
    exact = dip_buy(
        {"drop": 0.1, "lookback": 5, "stop": 0.25}, make_bars([100.0] * 6 + [80.0, 60.0, 60.0]), ZERO
    )
    assert fill_bars(exact) == [7, 8]
    assert exact.attrs["trade_returns"] == pytest.approx([60.0 / 80.0 - 1.0], rel=1e-12)
    above = dip_buy(
        {"drop": 0.1, "lookback": 5, "stop": 0.25}, make_bars([100.0] * 6 + [80.0, 60.01, 60.01]), ZERO
    )
    assert fill_bars(above) == [7]


def test_stop_is_measured_from_the_entry_fill_price(make_bars):
    bars = make_bars([100.0] * 6 + [85.0, 86.0, 86.0, 86.0])
    bars.loc[bars.index[7], "open"] = 90.0  # gap up: the entry fills at 90, not at the signal close of 85
    bars.loc[bars.index[7], "high"] = 90.0 * 1.005
    result = dip_buy({"drop": 0.1, "lookback": 5, "stop": 0.04}, bars, ZERO)
    # stop level 90 * 0.96 = 86.4: close 86 on bar 7 triggers (from 85 it would be 81.6 and never trigger)
    assert fill_bars(result) == [7, 8]
    assert result.attrs["trade_returns"] == pytest.approx([86.0 / 90.0 - 1.0], rel=1e-12)


@pytest.mark.parametrize("hold", [1, 2, 3, 5, 6, 10, 25])  # 6/10/25: the starter's test_hold_days_is_exact
def test_hold_period_exits_after_hold_bars(make_bars, hold):
    bars = make_bars([100.0] * 6 + [85.0] + [99.0] * (hold + 2))  # 99 is no dip: one round trip only
    result = dip_buy({"drop": 0.1, "lookback": 5, "hold": hold}, bars, ZERO)
    assert fill_bars(result) == [7, 7 + hold]
    pos = result["position"].to_numpy()
    assert (pos[7 : 7 + hold] > 0).all() and pos[7 + hold] == 0.0
    assert result.attrs["trade_returns"] == pytest.approx([99.0 / 85.0 - 1.0], rel=1e-12)


def test_no_re_entry_on_the_bar_an_exit_fills(make_bars):
    """TESTING.md bug #5. The dip signal is still on at the close of exit bar 8, but no entry is decided
    there. The next one is decided at close 9 and fills at 10."""
    bars = make_bars([100.0] * 6 + [80.0] * 8)
    result = dip_buy({"drop": 0.1, "lookback": 5, "hold": 1}, bars, ZERO)
    assert fill_bars(result) == [7, 8, 10, 11]
    assert sides(result) == ["buy", "sell", "buy", "sell"]
    assert result.attrs["n_trades"] == 4
    assert len(result.attrs["trade_returns"]) == 2


@given(start=st.integers(0, 1200), drop=st.sampled_from([0.03, 0.05, 0.1]), hold=st.integers(1, 6))
def test_fills_alternate_and_re_entry_waits_a_bar_after_every_exit(btc, start, drop, hold):
    bars = btc.iloc[start : start + 300]
    result = dip_buy({"drop": drop, "lookback": 5, "hold": hold, "stop": 0.03}, bars, Costs())
    at = bars.index.get_indexer(result.attrs["trades"]["ts"])
    side = sides(result)
    assert side[0::2] == ["buy"] * len(side[0::2]) and side[1::2] == ["sell"] * len(side[1::2])
    assert (np.diff(at) >= 1).all()  # at most one fill per bar
    sells = np.flatnonzero(np.array(side) == "sell")
    for i in sells[sells < len(at) - 1]:
        assert at[i + 1] >= at[i] + 2  # next entry fills two bars after the exit at the earliest


def test_vol_target_sizes_the_entry_by_hand(make_bars):
    closes = [100.0, 102.0, 100.0, 102.0, 100.0, 88.0, 88.0, 88.0]
    bars = make_bars(closes)
    params = {"drop": 0.1, "lookback": 3, "vol_target": 0.5, "vol_lookback": 4}
    result = dip_buy(params, bars, ZERO)
    # signal at close 5 (88 vs the 3-bar high 102); vol = std of the 4 log returns into bars 2..5, annualised
    vol = statistics.stdev([math.log(closes[i] / closes[i - 1]) for i in range(2, 6)]) * math.sqrt(365)
    expected = 0.5 / vol
    assert 0.3 < expected < 0.5  # the hand numbers make the cap bind
    assert fill_bars(result) == [6]
    assert result["turnover"].iloc[6] == pytest.approx(expected, rel=1e-12)
    assert result.attrs["trades"]["weight_after"].iloc[0] == pytest.approx(expected, rel=1e-12)
    assert result["position"].iloc[6] == pytest.approx(expected, rel=1e-12)  # flat bar: h == 0


def test_vol_target_never_raises_the_weight_above_its_cap(make_bars):
    bars = make_bars([100.0, 102.0, 100.0, 102.0, 100.0, 88.0, 88.0])
    params = {"drop": 0.1, "lookback": 3, "weight": 0.7, "vol_target": 100.0, "vol_lookback": 4}
    assert dip_buy(params, bars, ZERO)["turnover"].iloc[6] == 0.7


def test_vol_target_waits_for_a_defined_vol_and_zero_vol_is_uncapped(make_bars):
    # signal at close 1 already, but 2 returns are needed for the vol: the first sized entry is decided at
    # close 2. Both returns are log(0.5), so the vol is exactly 0 and the weight is the uncapped 0.6.
    bars = make_bars([128.0, 64.0, 32.0, 16.0, 16.0])
    params = {"drop": 0.4, "lookback": 1, "weight": 0.6, "vol_target": 0.1, "vol_lookback": 2}
    result = dip_buy(params, bars, ZERO)
    assert fill_bars(result) == [3]
    assert result["turnover"].iloc[3] == 0.6


# Ported from the starter's test_backtester_props.py (model-forecast sizing), shifted to fills at the next open:
# the size comes from the forecast at the signal close and the entry fills at the open after it.

MODEL_DIP = {"drop": 0.1, "lookback": 5, "hold": 5, "stop": 0.1, "vol_col": "pred_vol"}


def dip_then_flat(make_bars):
    """30 bars at 100, then 85 for 31 bars: the dip signals at close 30 and the entry fills at open 31 (= 85)."""
    return make_bars([100.0] * 30 + [85.0] * 31)


@pytest.mark.parametrize(("pred", "vt", "weight", "size"), [(0.8, 0.4, 1.0, 0.5), (0.2, 0.4, 1.0, 1.0), (0.2, 0.4, 0.7, 0.7)])
def test_vol_target_sizes_from_the_model(make_bars, pred, vt, weight, size):
    bars = dip_then_flat(make_bars).assign(pred_vol=pred)
    result = dip_buy({**MODEL_DIP, "vol_target": vt, "weight": weight}, bars, ZERO)
    assert fill_bars(result)[0] == 31
    assert result["turnover"].iloc[31] == pytest.approx(size, rel=1e-12)
    assert result["position"].iloc[31] == pytest.approx(size, rel=1e-12)  # flat bar 31: no drift


@pytest.mark.parametrize("missing", [math.nan, math.inf])
def test_vol_target_falls_back_to_realised_vol_where_the_model_has_no_forecast(btc, missing):
    bars = btc.iloc[:400].assign(pred_vol=missing)
    params = {"drop": 0.05, "lookback": 5, "hold": 10, "stop": 0.1, "vol_target": 0.3}
    result = dip_buy({**params, "vol_col": "pred_vol"}, bars, ZERO)
    plain = dip_buy(params, bars, ZERO)
    np.testing.assert_array_equal(result.to_numpy(), plain.to_numpy())
    t = fill_bars(result)[0]  # first entry; sized at close t-1 from the 20-bar realised volatility
    trailing = realised_vol(bars["close"].to_numpy(), 20)
    assert t - 1 >= 20 and result["turnover"].iloc[t] == pytest.approx(min(1.0, 0.3 / trailing[t - 1]), rel=1e-12)


def test_the_forecast_at_the_signal_close_is_used_not_a_later_one(make_bars):
    bars = dip_then_flat(make_bars)
    pred = np.full(len(bars), 0.8)
    pred[31:] = 0.1  # the forecast only drops after the signal close: the entry is still sized from 0.8
    result = dip_buy({**MODEL_DIP, "vol_target": 0.4}, bars.assign(pred_vol=pred), ZERO)
    assert result["turnover"].iloc[31] == pytest.approx(0.5, rel=1e-12)


@pytest.mark.parametrize("bad", [0.0, -0.5])
def test_non_positive_vol_forecast_never_trades(make_bars, bad):
    bars = dip_then_flat(make_bars).assign(pred_vol=bad)
    result = dip_buy({**MODEL_DIP, "vol_target": 0.4}, bars, ZERO)
    assert (result["position"] == 0.0).all() and result.attrs["n_trades"] == 0


@given(start=st.integers(0, 1000), cut=st.integers(30, 380), seed=st.integers(0, 2**16))
def test_no_look_ahead_in_model_column(btc, start, cut, seed):
    """Tamper the forecast column from ``cut`` on: every row up to and including ``cut`` is identical (the
    decision at close cut-1 read forecast[cut-1] and filled at open cut)."""
    rng = np.random.default_rng(seed)
    bars = btc.iloc[start : start + 400].copy()
    pred = rng.uniform(0.2, 1.2, len(bars))
    pred[rng.random(len(bars)) < 0.2] = np.nan  # some bars without a forecast: realised-vol fallback
    bars["pred_vol"] = pred
    tampered = bars.copy()
    tampered.iloc[cut:, tampered.columns.get_loc("pred_vol")] = rng.uniform(0.01, 3.0, len(bars) - cut)
    params = {"drop": 0.05, "lookback": 5, "hold": 10, "stop": 0.1, "vol_target": 0.4, "vol_col": "pred_vol"}
    a, b = dip_buy(params, bars, Costs()), dip_buy(params, tampered, Costs())
    np.testing.assert_array_equal(a.to_numpy()[: cut + 1], b.to_numpy()[: cut + 1])


DRAWN_DIP_PARAMS = st.fixed_dictionaries(
    {
        "drop": st.floats(0.02, 0.25),
        "lookback": st.integers(2, 20),
        "hold": st.integers(1, 40),
        "stop": st.floats(0.02, 0.30),
    },
    optional={"vol_target": st.floats(0.1, 1.0), "weight": st.floats(0.2, 1.0)},
)


@given(params=DRAWN_DIP_PARAMS, start=st.integers(0, 1000), cut=st.integers(30, 380), factor=st.floats(0.3, 3.0))
def test_drawn_params_keep_the_identities_and_never_look_ahead(btc, params, start, cut, factor):
    """Ported from the starter's params_st properties: drawn parameters on 400-bar windows of the regime-switching
    market reach long holds, many round trips and vol-target paths the fixed contract entries never hit."""
    bars = btc.iloc[start : start + 400]
    result = dip_buy(params, bars, Costs())
    validate_result(result, bars)
    o, c = bars["open"].to_numpy(), bars["close"].to_numpy()
    g, h, r = o[1:] / c[:-1] - 1, c[1:] / o[1:] - 1, c[1:] / c[:-1] - 1
    ret, pos, turnover, cost = (result[k].to_numpy() for k in ("ret", "position", "turnover", "cost"))
    w0, fill = pos[:-1], turnover[1:] > 0
    np.testing.assert_allclose((1 + ret[1:])[~fill], (1 + w0 * r)[~fill], rtol=0, atol=1e-12)
    target = pos[1:] / (1 + h * (1 - pos[1:]))
    expected = (1 + w0 * g) * (1 - cost[1:]) * (1 + target * h)
    np.testing.assert_allclose((1 + ret[1:])[fill], expected[fill], rtol=0, atol=1e-12)
    total = np.prod(1 + ret)
    assert np.prod(1 + result.attrs["trade_returns"]) == pytest.approx(total, rel=1e-10)
    # tamper the future (keep each bar valid): nothing decided before the cut moves
    tampered = bars.copy()
    for col in ("open", "high", "low", "close"):
        tampered.iloc[cut + 1 :, tampered.columns.get_loc(col)] *= factor
    tampered.iloc[cut, tampered.columns.get_loc("close")] *= factor
    tampered["high"] = tampered[["open", "high", "close"]].max(axis=1)
    tampered["low"] = tampered[["open", "low", "close"]].min(axis=1)
    other = dip_buy(params, tampered, Costs())
    np.testing.assert_array_equal(result.to_numpy()[:cut], other.to_numpy()[:cut])
    assert result["turnover"].iloc[cut] == other["turnover"].iloc[cut]


def test_realised_vol_by_hand():
    closes = np.array([100.0, 101.0, 99.0, 103.0, 102.0, 108.0])
    vol = realised_vol(closes, 3)
    assert np.isnan(vol[:3]).all()
    log_ret = [math.log(closes[i] / closes[i - 1]) for i in range(1, 6)]
    for t in range(3, 6):
        assert vol[t] == pytest.approx(statistics.stdev(log_ret[t - 3 : t]) * math.sqrt(365), rel=1e-12)
    assert np.isnan(realised_vol(closes[:3], 3)).all()  # too short for one window


def test_short_bars_never_signal(make_bars):
    bars = make_bars([100.0, 50.0, 25.0])
    assert fill_bars(dip_buy({"drop": 0.1, "lookback": 5}, bars, ZERO)) == []
    assert (
        fill_bars(dip_buy({"drop": 0.1, "lookback": 3}, bars, ZERO)) == []
    )  # exactly lookback bars: no window
    assert (
        fill_bars(dip_buy({"drop": 0.1, "lookback": 1, "vol_target": 0.5, "vol_lookback": 5}, bars, ZERO))
        == []
    )


def test_flat_prices_never_trade_and_the_fill_log_is_empty(make_bars):
    result = dip_buy({"drop": 0.05, "lookback": 2}, make_bars([100.0] * 10), Costs())
    assert (result.to_numpy() == 0.0).all()
    assert result.attrs["n_trades"] == 0 and len(result.attrs["trade_returns"]) == 0
    trades = result.attrs["trades"]
    assert trades.empty
    assert list(trades.columns) == [
        "ts",
        "side",
        "price",
        "weight_before",
        "weight_after",
        "turnover",
        "cost",
    ]


def test_off_values_for_optional_params(btc):
    bars = btc.iloc[:400]
    base = dip_buy({"drop": 0.05, "lookback": 5}, bars, Costs())
    for extra in ({"stop": 0}, {"stop": 0.0}, {"stop": None}, {"hold": None}, {"vol_target": None}):
        same = dip_buy({"drop": 0.05, "lookback": 5, **extra}, bars, Costs())
        pd.testing.assert_frame_equal(same, base)


def test_integral_numbers_are_accepted_for_integer_params(btc):
    bars = btc.iloc[:400]
    base = dip_buy({"drop": 0.05, "lookback": 5, "hold": 3}, bars, Costs())
    for lookback, hold in ((5.0, 3.0), (np.int64(5), np.int64(3))):
        same = dip_buy({"drop": np.float64(0.05), "lookback": lookback, "hold": hold}, bars, Costs())
        pd.testing.assert_frame_equal(same, base)


# --------------------------------------------------------------------------------------------- benchmarks


def test_fractional_positions_drift_as_coin_units(make_bars):
    """TESTING.md bug #4: a 50% position is NOT rebalanced to 50% each day for free."""
    bars = make_bars([100.0, 100.0, 200.0, 200.0, 100.0])
    result = buy_and_hold({"weight": 0.5}, bars, Costs())
    pos, ret = result["position"].to_numpy(), result["ret"].to_numpy()
    assert fill_bars(result) == [1]
    assert pos[1] == 0.5
    assert pos[2] == pytest.approx(2 / 3, rel=1e-12) and ret[2] == pytest.approx(0.5, rel=1e-12)
    assert pos[3] == pytest.approx(2 / 3, rel=1e-12) and ret[3] == 0.0
    assert pos[4] == pytest.approx(0.5, rel=1e-12) and ret[4] == pytest.approx(-1 / 3, rel=1e-12)
    assert (result["turnover"].iloc[2:] == 0.0).all() and (result["cost"].iloc[2:] == 0.0).all()


def test_buy_and_hold_buys_at_the_open_of_bar_1(btc):
    bars = btc.iloc[:100]
    result = buy_and_hold({}, bars, ZERO)
    assert fill_bars(result) == [1]
    expected = bars["close"].iloc[-1] / bars["open"].iloc[1] - 1.0
    assert result.attrs["trade_returns"] == pytest.approx([expected], rel=1e-12)
    assert np.prod(1.0 + result["ret"].to_numpy()) - 1.0 == pytest.approx(expected, rel=1e-12)


def test_constant_mix_rebalances_every_bar_and_pays_for_it(make_bars):
    """TESTING.md bug #6: the 50/50 benchmark trades back to 50% at every open and pays each time."""
    bars = make_bars([100.0, 105.0, 110.0, 99.0, 120.0, 90.0, 95.0])
    paid = constant_mix({"weight": 0.5}, bars, Costs())
    free = constant_mix({"weight": 0.5}, bars, ZERO)
    assert fill_bars(paid) == [1, 2, 3, 4, 5, 6]
    assert (paid["cost"].iloc[1:] > 0.0).all()
    # bar 1: buy 50% of 10,000 USD = 5,000 USD -> slippage 15 + 15 * log10(5) bps, plus 5 bps pool, plus gas
    k1 = 0.5 * (5.0 + 15.0 + 15.0 * math.log10(5.0)) / 1e4 + 0.10 / 10_000.0
    assert paid["cost"].iloc[1] == pytest.approx(k1, rel=1e-12)
    # bar 2: the weight drifted to 0.5 * 1.05 / 1.025 at close 1; selling back to 0.5 trades ~125 USD
    w_drift = 0.5 * 1.05 / 1.025
    v1 = 10_000.0 * (1.0 - k1) * (1.0 + 0.5 * 0.05)
    trade = (w_drift - 0.5) * v1
    assert 100.0 < trade < 1000.0
    k2 = (w_drift - 0.5) * (5.0 + 10.0 + 5.0 * math.log10(trade / 100.0)) / 1e4 + 0.10 / v1
    assert paid["turnover"].iloc[2] == pytest.approx(w_drift - 0.5, rel=1e-12)
    assert paid["cost"].iloc[2] == pytest.approx(k2, rel=1e-12)
    assert paid["position"].iloc[2] == pytest.approx(
        0.5 * (110 / 105) / (1 + 0.5 * (110 / 105 - 1)), rel=1e-12
    )
    # paying for every rebalance costs exactly prod(1 - cost)
    end_paid = np.prod(1.0 + paid["ret"].to_numpy())
    end_free = np.prod(1.0 + free["ret"].to_numpy())
    assert end_paid == pytest.approx(end_free * np.prod(1.0 - paid["cost"].to_numpy()), rel=1e-12)
    assert end_paid < end_free


def test_band_skips_small_drifts(make_bars):
    bars = make_bars([100.0, 100.0, 101.0, 100.0, 101.0, 100.0, 130.0, 130.0, 130.0])
    banded = constant_mix({"weight": 0.5, "band": 0.05}, bars, ZERO)
    assert fill_bars(banded) == [1, 7]  # 1% moves stay inside the band; the 30% jump (drift 0.065) doesn't
    assert fill_bars(constant_mix({"weight": 0.5}, bars, ZERO)) == [1, 3, 4, 5, 6, 7]


def test_a_drift_exactly_at_the_band_is_skipped(make_bars):
    """'Within the band' includes the edge. Tripling the price moves a 0.5 weight to exactly 0.75 (drift 0.25)."""
    bars = make_bars([100.0, 100.0, 300.0, 300.0])
    assert constant_mix({"weight": 0.5}, bars, ZERO)["position"].iloc[2] == 0.75
    assert fill_bars(constant_mix({"weight": 0.5, "band": 0.25}, bars, ZERO)) == [1]
    assert fill_bars(constant_mix({"weight": 0.5, "band": 0.2499}, bars, ZERO)) == [1, 3]


def test_zero_drift_at_the_close_sends_no_order_even_if_the_open_gaps(make_bars):
    """The band is judged at the decision close (the last price the rule sees), not at the next open."""
    bars = make_bars([100.0, 100.0, 100.0, 100.0])
    bars.loc[bars.index[2], ["open", "low"]] = [80.0, 79.0]  # bar 1 closes exactly on target, bar 2 gaps down
    result = constant_mix({"weight": 0.5}, bars, ZERO)
    assert result["position"].iloc[1] == 0.5
    assert 2 not in fill_bars(result)


def test_initial_buy_ignores_the_band(make_bars):
    bars = make_bars([100.0, 100.0, 150.0, 60.0, 100.0])
    result = constant_mix({"weight": 0.5, "band": 0.6}, bars, ZERO)
    assert fill_bars(result) == [1]


def test_every_schedules_rebalance_decisions(make_bars):
    bars = make_bars([100.0, 103.0, 99.0, 104.0, 98.0, 105.0, 97.0, 106.0, 96.0, 107.0])
    result = constant_mix({"weight": 0.5, "every": 3}, bars, ZERO)
    assert fill_bars(result) == [1, 4, 7]  # decided at closes 0, 3 and 6; close 9 is the last bar
    pos = result["position"].to_numpy()
    assert len(np.unique(np.round(pos[1:4], 12))) == 3  # drifts freely between rebalances


def test_random_entry_count_and_layout(btc):
    bars = btc.iloc[:200]
    result = random_entry({"n_trades": 6, "hold": 5, "seed": 11}, bars, Costs())
    validate_result(result, bars)
    assert result.attrs["n_trades"] == 12 and len(result.attrs["trade_returns"]) == 6
    assert sides(result) == ["buy", "sell"] * 6
    at = bars.index.get_indexer(result.attrs["trades"]["ts"])
    entries, exits = at[0::2], at[1::2]
    assert (exits - entries == 5).all()
    assert (entries[1:] > exits[:-1]).all()  # no overlap
    assert entries[0] >= 1 and exits[-1] <= len(bars) - 1


def test_random_entry_is_seeded(btc):
    bars = btc.iloc[:200]

    def run(seed):
        return random_entry({"n_trades": 6, "hold": 5, "seed": seed}, bars, Costs())

    a, b = run(3), run(3)
    pd.testing.assert_frame_equal(a, b)
    np.testing.assert_array_equal(a.attrs["trade_returns"], b.attrs["trade_returns"])
    assert len({tuple(fill_bars(run(seed))) for seed in range(5)}) == 5


def test_random_entry_tight_fit_has_one_layout(make_bars):
    bars = make_bars([100.0 + i for i in range(13)])  # 3 trips of 3 bars need exactly bars 1..12
    for seed in range(5):
        result = random_entry({"n_trades": 3, "hold": 3, "seed": seed}, bars, ZERO)
        assert fill_bars(result) == [1, 4, 5, 8, 9, 12]


def test_random_entry_reaches_every_layout(make_bars):
    bars = make_bars([100.0 + i for i in range(12)])
    singles = {
        fill_bars(random_entry({"n_trades": 1, "hold": 2, "seed": s}, bars, ZERO))[0] for s in range(300)
    }
    assert singles == set(range(1, 10))  # entry e needs its exit e + 2 <= 11
    pairs = {
        tuple(fill_bars(random_entry({"n_trades": 2, "hold": 2, "seed": s}, bars, ZERO))) for s in range(600)
    }
    assert len(pairs) == math.comb(7, 2)  # 2 blocks of 3 bars in 11 slots: C(11 - 6 + 2, 2) layouts
    assert all(b[2] > b[1] for b in pairs)


def test_random_entry_zero_trades_and_too_many(make_bars):
    bars = make_bars([100.0 + i for i in range(12)])
    none = random_entry({"n_trades": 0, "hold": 3}, bars, ZERO)
    assert none.attrs["n_trades"] == 0 and (none.to_numpy() == 0.0).all()
    with pytest.raises(ValueError, match="don't fit in 12 bars"):
        random_entry({"n_trades": 3, "hold": 3}, bars, ZERO)


@given(
    start=st.integers(0, 1100),
    length=st.integers(40, 400),
    costs=st.sampled_from([Costs(), Costs().stressed()]),
)
def test_trade_log_matches_the_portfolio_with_costs_on(btc, start, length, costs):
    """Reference only (the contract asks for zero cost): every round trip starts and ends flat, so the
    trade log compounds to the portfolio return with costs on as well."""
    bars = btc.iloc[start : start + length]
    cases = [
        (
            dip_buy,
            {"drop": 0.04, "lookback": 5, "stop": 0.05, "hold": 7, "vol_target": 0.8, "vol_lookback": 10},
        ),
        (buy_and_hold, {"weight": 0.6}),
        (constant_mix, {"weight": 0.4, "every": 5}),
        (random_entry, {"n_trades": 4, "hold": 5, "seed": start}),
    ]
    for fn, params in cases:
        result = fn(params, bars, costs)
        total = np.prod(1.0 + result["ret"].to_numpy())
        assert np.prod(1.0 + result.attrs["trade_returns"]) == pytest.approx(total, rel=1e-10)


# ------------------------------------------------------------------------------------------------- errors


BAD_PARAMS = [
    (dip_buy, [("drop", 0.1)], "params must be a dict"),
    (dip_buy, {"lookback": 5}, "missing required param 'drop'"),
    (dip_buy, {"drop": 0.1}, "missing required param 'lookback'"),
    (dip_buy, {"drop": 0.1, "lookback": 5, "stop_loss": 0.1}, r"unknown params \['stop_loss'\]"),
    (dip_buy, {"drop": "0.1", "lookback": 5}, "drop must be a number"),
    (dip_buy, {"drop": True, "lookback": 5}, "drop must be a number"),
    (dip_buy, {"drop": 0.0, "lookback": 5}, r"drop must be in \(0.0, 1.0\)"),
    (dip_buy, {"drop": 1.0, "lookback": 5}, r"drop must be in \(0.0, 1.0\)"),
    (dip_buy, {"drop": math.nan, "lookback": 5}, r"drop must be in \(0.0, 1.0\)"),
    (dip_buy, {"drop": 0.1, "lookback": 0}, "lookback must be >= 1"),
    (dip_buy, {"drop": 0.1, "lookback": 2.5}, "lookback must be an integer"),
    (dip_buy, {"drop": 0.1, "lookback": True}, "lookback must be an integer"),
    (dip_buy, {"drop": 0.1, "lookback": math.nan}, "lookback must be an integer"),
    (dip_buy, {"drop": 0.1, "lookback": "5"}, "lookback must be an integer"),
    (dip_buy, {"drop": 0.1, "lookback": 5, "stop": 1.0}, r"stop must be in \(0.0, 1.0\)"),
    (dip_buy, {"drop": 0.1, "lookback": 5, "stop": -0.05}, r"stop must be in \(0.0, 1.0\)"),
    (dip_buy, {"drop": 0.1, "lookback": 5, "stop": False}, "stop must be a number"),
    (dip_buy, {"drop": 0.1, "lookback": 5, "hold": 0}, "hold must be >= 1"),
    (dip_buy, {"drop": 0.1, "lookback": 5, "weight": 0.0}, r"weight must be in \(0.0, 1.0\]"),
    (dip_buy, {"drop": 0.1, "lookback": 5, "weight": 1.01}, r"weight must be in \(0.0, 1.0\]"),
    (dip_buy, {"drop": 0.1, "lookback": 5, "vol_target": 0.0}, r"vol_target must be in \(0.0, inf\)"),
    (dip_buy, {"drop": 0.1, "lookback": 5, "vol_target": math.inf}, r"vol_target must be in \(0.0, inf\)"),
    (
        dip_buy,
        {"drop": 0.1, "lookback": 5, "vol_target": 0.5, "vol_lookback": 1},
        "vol_lookback must be >= 2",
    ),
    (dip_buy, {"drop": 0.1, "lookback": 5, "vol_col": "close"}, "vol_col needs vol_target"),
    (dip_buy, {"drop": 0.1, "lookback": 5, "vol_target": 0.5, "vol_col": "pred_vol"}, "vol_col must name a column"),
    (dip_buy, {"drop": 0.1, "lookback": 5, "vol_target": 0.5, "vol_col": 3}, "vol_col must name a column"),
    (buy_and_hold, {"weight": 2.0}, r"weight must be in \(0.0, 1.0\]"),
    (buy_and_hold, {"size": 1.0}, r"buy_and_hold: unknown params \['size'\]"),
    (constant_mix, {"weight": 0.0}, r"weight must be in \(0.0, 1.0\]"),
    (constant_mix, {"every": 0}, "every must be >= 1"),
    (constant_mix, {"band": 1.0}, r"band must be in \[0.0, 1.0\)"),
    (constant_mix, {"band": -0.01}, r"band must be in \[0.0, 1.0\)"),
    (constant_mix, {"rebalance": 30}, r"constant_mix: unknown params \['rebalance'\]"),
    (random_entry, {"hold": 3}, "missing required param 'n_trades'"),
    (random_entry, {"n_trades": 3}, "missing required param 'hold'"),
    (random_entry, {"n_trades": -1, "hold": 3}, "n_trades must be >= 0"),
    (random_entry, {"n_trades": 1, "hold": 0}, "hold must be >= 1"),
    (random_entry, {"n_trades": 1, "hold": 3, "seed": -1}, "seed must be >= 0"),
    (random_entry, {"n_trades": 1, "hold": 3, "weight": 0.0}, r"weight must be in \(0.0, 1.0\]"),
    (random_entry, {"n_trades": 1, "hold": 3, "trades": 2}, r"random_entry: unknown params \['trades'\]"),
]


@pytest.mark.parametrize(
    ("fn", "params", "match"), BAD_PARAMS, ids=[f"{f.__name__}-{m}" for f, _, m in BAD_PARAMS]
)
def test_bad_params_raise_with_a_clear_message(btc, fn, params, match):
    with pytest.raises(ValueError, match=match):
        fn(params, btc.iloc[:50], Costs())


def test_costs_none_reads_the_yaml_and_anything_else_must_be_costs(btc):
    bars = btc.iloc[:300]
    params = {"drop": 0.05, "lookback": 5, "hold": 4}
    pd.testing.assert_frame_equal(dip_buy(params, bars), dip_buy(params, bars, Costs.from_yaml()))
    with pytest.raises(ValueError, match="costs must be a Costs instance or None, got dict"):
        dip_buy(params, bars, {"pool_fee_bps": 5.0})
