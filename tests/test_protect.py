"""protect-gains (``lab/runner/protect.py``, scouting only): the tool copy, the brake overlay with its lines, buy-backs
and readings, the index and its SMA, the measures of section 7 and the rules D1-D6 of ``research/protect-gains/PLAN.md``
(the section 10 test list).

Synthetic data and hand-built paths only: no catalog bar is read. The accounting is checked against books in coin
units and USDC cash written here (``order_book``, ``one_pass``), never against the weight recursion the engine uses;
``one_pass`` also decides every order itself (the tool's steps, the line, the buy-back and the reading) in one pass,
so the re-running of section 5 is checked against an independent engine.
"""

from __future__ import annotations

import math
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest
from hypothesis import example, given
from hypothesis import strategies as st
from test_portfolio import ALL_COLUMNS, random_panel, tamper_from

from lab.runner import holdmix as H
from lab.runner import portfolio as pf
from lab.runner import protect as P
from lab.runner import trend
from lab.runner.reference import Costs

LIMITS = {"min_cash": 0.20, "max_coin": 0.60}  # Steady's limits as read (test_portfolio pins the real file)
NONE = {"min_cash": None, "max_coin": None}
COSTS = Costs.from_yaml(capital_usd=5000.0)
COSTS_2X = COSTS.stressed(2.0)
ZERO = replace(Costs.zero(), capital_usd=5000.0)
D = 5000.0
DAY = pd.Timedelta(days=1)
DAY_US = 86_400_000_000

# ------------------------------------------------------------------------------------------------ helpers


def days(n: int, start: str = "2017-01-02") -> pd.DatetimeIndex:
    return pd.date_range(start, periods=n, freq="D", tz="UTC", name="ts")


def bars_on(index, closes, opens=None) -> pd.DataFrame:
    """Valid bars on ``index``: open = previous close (or ``opens``), wicks of 0.5%, volume 1000."""
    c = np.asarray(closes, dtype=float)
    o = np.concatenate([[c[0]], c[:-1]]) if opens is None else np.asarray(opens, dtype=float)
    return pd.DataFrame(
        {
            "open": o,
            "high": np.maximum(o, c) * 1.005,
            "low": np.minimum(o, c) * 0.995,
            "close": c,
            "volume": np.full(len(c), 1000.0),
        },
        index=pd.DatetimeIndex(index, name="ts"),
    )


def panel_on(index, btc, eth=None, btc_open=None, eth_open=None) -> pd.DataFrame:
    eth = btc if eth is None else eth
    eth_open = btc_open if eth is btc and eth_open is None else eth_open
    return pf.make_panel(
        {"BTC": bars_on(index, btc, btc_open), "ETH": bars_on(index, eth, eth_open)}, snapshot_id="hand"
    )


def path(n: int, base: float = 100.0, **at) -> list[float]:
    """``n`` closes at ``base``, with ``r<row>=price`` set from that row on (``r40=130``)."""
    out = [base] * n
    for key, price in sorted(((int(k[1:]), v) for k, v in at.items())):
        out[key:] = [price] * (n - key)
    return out


def tool(targets=(0.25, 0.25), limits=NONE, band=0.30, wait=15, reset=None, first_buy_waits=False) -> dict:
    on = limits["min_cash"] is not None or limits["max_coin"] is not None
    return {
        "w_btc": targets[0],
        "w_eth": targets[1],
        "band": band,
        "wait_days": wait,
        "min_cash": limits["min_cash"],
        "max_coin": limits["max_coin"],
        "headroom": 0.02 if on else 0.0,
        "reset_days": reset,
        "first_buy_waits": first_buy_waits,
    }


def brake(line="A", level=0.10, mode="wait30", reading="counts") -> dict:
    return {"line": line, "level": level, "mode": mode, "reading": reading}


def run(panel, tool_p, brake_p=None, costs=ZERO, f=0.5, signal=None) -> pd.DataFrame:
    sig = P.index_signal(panel, f) if signal is None else signal
    return P.protect({**tool_p, **(brake_p or {})}, panel, costs, sig if brake_p else None)


def all_checks(res, panel, costs, f=0.5) -> None:
    """Every consistency check of section 9 the run makes."""
    sig = P.index_signal(panel, f)
    reading = None if res.attrs["brake"] is None else res.attrs["brake"]["reading"]
    P.check_orders(res, wait_days=res.attrs["wait_days"], reading=reading)
    P.check_book(res, panel, costs)
    if reading is not None:
        P.check_events(res, sig)


def values_of(res, costs=ZERO) -> np.ndarray:
    return P.wallet_values(res["ret"].to_numpy(), costs.capital_usd)


def order_book(panel, result, costs):
    """``test_portfolio.unit_book`` with each order's own target vector (``attrs["order_targets"]``): returns the
    per-row returns, weights and V, from coin units and USDC cash."""
    n = len(panel)
    o = {a: panel[(a, "open")].to_numpy(dtype=float) for a in pf.ASSETS}
    c = {a: panel[(a, "close")].to_numpy(dtype=float) for a in pf.ASSETS}
    log = result.attrs["fills"]
    traded = {(int(b), a) for b, a in zip(log["bar"], log["asset"], strict=True)}
    at = {
        int(t) + 1: w
        for t, w in zip(result.attrs["orders"], result.attrs["order_targets"].tolist(), strict=True)
    }
    fills = set(np.flatnonzero(result["turnover"].to_numpy() > 0).tolist())
    units, cash = dict.fromkeys(pf.ASSETS, 0.0), costs.capital_usd
    value = np.full(n, np.nan)
    value[0] = cash
    out = {col: np.zeros(n) for col in ALL_COLUMNS}
    for t in range(1, n):
        if t in fills:
            target = dict(zip(pf.ASSETS, at[t], strict=True))
            vo = cash + sum(units[a] * o[a][t] for a in pf.ASSETS)
            paid = 0.0
            for a in pf.ASSETS:
                if (t, a) in traded:
                    usd = abs(target[a] * vo - units[a] * o[a][t])
                    paid += usd * costs.rate(usd) + costs.gas_usd_per_trade
            after = vo - paid
            units = {a: target[a] * after / o[a][t] for a in pf.ASSETS}
            cash = (1.0 - sum(target.values())) * after
        value[t] = cash + sum(units[a] * c[a][t] for a in pf.ASSETS)
        out["ret"][t] = value[t] / value[t - 1] - 1.0
        for a in pf.ASSETS:
            out[f"w_{a}"][t] = units[a] * c[a][t] / value[t]
    return out, value


def one_pass(panel, tool_p, brake_p, costs, f=0.5):
    """An independent one-pass engine in coin units and USDC cash: at each close, value the book, then decide (the
    brake's buy-back while stopped, the line while armed, the tool's steps otherwise: first buy, limit fix, wait,
    relative band), and fill each order at the next open with each leg's rate and gas. Returns the orders with their
    reasons, the per-row returns and weights, and the stops and buy-backs."""
    n = len(panel)
    times = panel.index.asi8.tolist()
    o = [panel[(a, "open")].to_numpy(dtype=float) for a in pf.ASSETS]
    c = [panel[(a, "close")].to_numpy(dtype=float) for a in pf.ASSETS]
    sig = P.index_signal(panel, f)
    i_close, avg = sig["I"].to_numpy(), sig["sma"].to_numpy()
    targets = (tool_p["w_btc"], tool_p["w_eth"])
    wait = tool_p["wait_days"] * DAY_US
    mc, mx = tool_p["min_cash"], tool_p["max_coin"]
    line, level, mode, reading = brake_p["line"], brake_p["level"], brake_p["mode"], brake_p["reading"]
    gain = P.B_GAIN.get(level, math.nan) if line == "B" else math.nan
    kind, point = P.MODE_SPECS[mode]
    units, cash = [0.0, 0.0], costs.capital_usd
    ret, weights = np.zeros(n), np.zeros((n, 2))
    orders, reasons = [], []
    stops, buybacks = [], []
    order, value = None, costs.capital_usd
    clock = None
    armed, start, high, sale, dipped, due = True, 1, None, None, False, None
    for t in range(n):
        if order is not None:
            vo = cash + sum(units[a] * o[a][t] for a in range(2))
            paid = 0.0
            for a in range(2):
                usd = abs(order[a] * vo - units[a] * o[a][t])
                if usd > 0.0:
                    paid += usd * costs.rate(usd) + costs.gas_usd_per_trade
            after = vo - paid
            units = [order[a] * after / o[a][t] for a in range(2)]
            cash = (1.0 - sum(order)) * after
        now = cash + sum(units[a] * c[a][t] for a in range(2))
        if t:
            ret[t] = now / value - 1.0
        value = now
        w = [units[a] * c[a][t] / now for a in range(2)]
        weights[t] = w
        order, reason = None, None
        if t == 0:
            order, reason = targets, "first"
        elif not armed:
            elapsed = times[t] - times[sale]
            if due is None:
                if kind == "wait":
                    hit = elapsed >= point * DAY_US
                elif kind == "rebound":
                    hit = elapsed >= 7 * DAY_US and i_close[t] >= (1.0 + point) * i_close[sale]
                else:
                    ok = not math.isnan(avg[t])
                    hit = (
                        elapsed >= 7 * DAY_US
                        and dipped
                        and panel.index[t].day_of_week == 0
                        and ok
                        and i_close[t] > 1.02 * avg[t]
                    )
                    if not hit and ok and i_close[t] <= 1.02 * avg[t]:
                        dipped = True
                if hit:
                    due = t
            held_back = reading == "counts" and clock is not None and times[t] - clock < wait
            if due is not None and not held_back and t < n - 1:
                order, reason = targets, "buyback"
                buybacks.append(t)
                clock = times[t]
                armed, start, due = True, t + 1, None
        else:
            v = now
            high = v if t == start else max(high, v)
            if line == "A":
                fires = v <= (1.0 - level) * high
            else:
                fires = high >= (1.0 + gain) * costs.capital_usd and v <= costs.capital_usd + level * (
                    high - costs.capital_usd
                )
            if fires and t < n - 1:
                order, reason = P.CASH, "stop"
                stops.append(t)
                armed, sale, dipped, due = False, t, False, None
            elif not fires:
                breach = (mc is not None and w[0] + w[1] > 1.0 - mc + 1e-9) or (
                    mx is not None and (w[0] > mx + 1e-9 or w[1] > mx + 1e-9)
                )
                waiting = clock is not None and times[t] - clock < wait
                band = any(
                    abs(w[a] - targets[a]) > tool_p["band"] * targets[a] for a in range(2) if targets[a] > 0
                )
                if breach:
                    order, reason = targets, "limit"
                elif band and not waiting:
                    order, reason = targets, "band"
                if order is not None:
                    clock = times[t]
        if order is not None and t < n - 1:
            orders.append(t)
            reasons.append(reason)
        elif t == n - 1:
            order = None
    return {
        "orders": orders,
        "reasons": reasons,
        "ret": ret,
        "weights": weights,
        "stops": stops,
        "buybacks": buybacks,
    }


@st.composite
def cases(draw, min_size: int = 60, max_size: int = 160):
    """(panel, tool params, brake params, f): volatile drawn panels, so that every line fires and buys back."""
    n = draw(st.integers(min_size, max_size))
    seed = draw(st.integers(0, 2**32 - 1))
    vols = tuple(draw(st.sampled_from([0.02, 0.05, 0.09])) for _ in pf.ASSETS)
    gaps = tuple(draw(st.sampled_from([0.0, 0.01, 0.04])) for _ in pf.ASSETS)
    panel = random_panel(n, seed, vols, gaps)
    s, f = draw(st.sampled_from(P.MIXES))
    limits = draw(st.sampled_from([LIMITS, {"min_cash": 0.20, "max_coin": 0.55}]))
    band = draw(st.sampled_from([0.02, 0.05, 0.30]))
    tp = tool(H.mix_targets(s, f), limits, band=band, wait=draw(st.sampled_from([1, 4, 15, 30])))
    line = draw(st.sampled_from(P.LINES))
    level = draw(st.sampled_from(P.LEVELS[line] if line == "B" else (0.05, 0.10, 0.20)))
    mode = draw(st.sampled_from(("rebound-5", "rebound0", "rebound+5", "wait30")))
    bp = brake(line, level, mode, draw(st.sampled_from(P.READINGS)))
    return panel, tp, bp, f


@st.composite
def long_cases(draw):
    """Cases long enough for the trend buy-back (SMA200 from row 199)."""
    panel, tp, bp, f = draw(cases(min_size=230, max_size=330))
    return panel, tp, {**bp, "mode": draw(st.sampled_from((*P.MODES, "trend", "trend")))}, f


BUSY_TREND = (
    random_panel(300, 11, (0.06, 0.06), (0.01, 0.01)),
    tool((0.35, 0.35), LIMITS, 0.05, 15),
    brake("A", 0.05, "trend", "counts"),
    0.5,
)
BUSY_B = (
    random_panel(120, 13, (0.09, 0.09), (0.04, 0.04)),
    tool((0.35, 0.35), LIMITS, 0.05, 15),
    brake("B", 0.40, "rebound+5", "counts"),
    0.5,
)


# ------------------------------------------------------------------------------------------------ pinned values


def test_the_pinned_values_are_the_plan_s():
    assert P.MIXES == ((0.3, 0.5), (0.3, 0.75), (0.5, 0.5), (0.5, 0.75), (0.7, 0.5), (0.7, 0.75))
    assert P.LEVELS == {"A": (0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40), "B": (0.40, 0.50, 0.60, 0.70, 0.80)}
    assert P.B_GAIN == {0.40: 0.20, 0.50: 0.25, 0.60: 1.0 / 3.0, 0.70: 0.50, 0.80: 1.00}
    assert 0.10 / (0.90 - 0.70) != 0.50 and 0.10 / (0.90 - 0.80) != 1.00  # why the table is pinned as values
    for y, g in P.B_GAIN.items():  # R3: the line starts at least 10% below the high (exactly 10% in reals)
        assert g == pytest.approx(0.10 / (0.90 - y), rel=1e-12)
        assert (
            P.parse_brake("B", y, "wait30", "counts").gain == g
        )  # the pinned value, never the float formula
        assert P.parse_brake("B", y, "wait30", "counts").record()["gain"] == g
        h = (1.0 + g) * D
        assert (D + y * (h - D)) / h == pytest.approx(0.90, rel=1e-12)
    assert P.MODES == ("rebound-5", "rebound0", "rebound+5", "trend", "wait30", "wait180")
    assert P.MODE_SPECS["rebound-5"] == ("rebound", -0.05) and P.MODE_SPECS["wait180"] == ("wait", 180.0)
    assert P.AUTO_MODES == ("rebound-5", "rebound0", "rebound+5", "trend")
    assert P.D2_TIE_ORDER == ("trend", "rebound+5", "rebound0", "rebound-5")
    assert P.READINGS == ("separate", "counts") and P.IN_FORCE == "counts"
    assert (P.TOOL_BAND, P.TOOL_CAP, P.TOOL_WAIT, P.HEADROOM, P.DEPOSIT) == (0.30, 2, 15, 0.02, 5000.0)
    assert (P.MIN_DAYS, P.TREND_LOOKBACK, P.TREND_BAND, P.FIRST_SIGNAL_ROW, P.RESTOP_DAYS) == (
        7,
        200,
        1.02,
        199,
        30,
    )
    assert (P.PERCENTILE, P.PROTECT_LEFT, P.PROTECT_RIGHT, P.RESTOP_MAX, P.TIE_TOL) == (
        90.0,
        3.0,
        2.0,
        0.25,
        1e-12,
    )
    assert (P.PROMISE_PERCENTILE, P.BOOM_MIN_WINDOWS, P.N_WINDOWS, P.WINDOW_MONTHS) == (95.0, 12, 49, 24)
    for s, f in P.MIXES:  # section 4: every mix passes check_targets with the Steady limits and h = 0.02
        pf.check_targets(*H.mix_targets(s, f), **LIMITS, headroom=0.02)
    assert H.mix_targets(0.70, 0.75) == pytest.approx((0.525, 0.175))
    assert set(P.READINGS_PINNED) >= {"V", "due", "wait_restart", "missed_rebound", "c_tie", "stage2_reading"}


def test_tool_params_are_the_owner_s_default():
    p = P.tool_params((0.35, 0.35), {"min_cash": 0.2, "max_coin": 0.6})
    assert p == {
        "w_btc": 0.35,
        "w_eth": 0.35,
        "band": 0.30,
        "wait_days": 15,
        "min_cash": 0.2,
        "max_coin": 0.6,
        "headroom": 0.02,
        "reset_days": None,
        "first_buy_waits": False,
    }
    H._hold_params(p)


# ------------------------------------------------------------------------------------------------ windows


def test_the_24_month_windows_from_the_calendar():
    k = P.rolling_windows("KRAKEN")
    assert [w for w, _, _ in k] == list(range(49))
    assert k[0][1:] == (pd.Timestamp("2017-01-02", tz="UTC"), pd.Timestamp("2019-01-01", tz="UTC"))
    assert k[48][1:] == (pd.Timestamp("2021-01-02", tz="UTC"), pd.Timestamp("2023-01-01", tz="UTC"))
    assert k[13][1:] == (pd.Timestamp("2018-02-02", tz="UTC"), pd.Timestamp("2020-02-01", tz="UTC"))
    b = P.rolling_windows("BINANCE")
    assert [w for w, _, _ in b] == list(range(8, 49)) and len(b) == 41
    assert b[0][1] == pd.Timestamp(
        "2017-09-02", tz="UTC"
    )  # window 7 would start 2017-08-02, before 2017-08-18
    with pytest.raises(ValueError, match="source must be one of"):
        P.rolling_windows("COINBASE")


def test_window_overlap_by_hand_and_against_the_calendar():
    # by hand: 2017 is months 0..11, so the windows 0..11 (k <= 11); 2020 the windows 13..47; 2022 the 37..48
    assert [k for k in range(49) if P.overlaps(k, 2017)] == list(range(12))
    assert [k for k in range(49) if P.overlaps(k, 2018)] == list(range(24))
    assert [k for k in range(49) if P.overlaps(k, 2020)] == list(range(13, 48))
    assert [k for k in range(49) if P.overlaps(k, 2022)] == list(range(37, 49))
    for k, first, last in P.rolling_windows("KRAKEN"):
        bar_days = pd.date_range(first, last, freq="D") - DAY  # a bar's day is its close minus 1 day
        for year in range(2016, 2024):
            assert P.overlaps(k, year) == bool((bar_days.year == year).any()), (k, year)
    assert P.windows_without(range(49), [2017, 2020]) == [12, 48]
    assert P.windows_without(range(49), []) == list(range(49))


def test_boom_removals_take_the_best_years_ties_to_the_earlier():
    returns = {2017: 9.0, 2018: -0.7, 2019: 0.9, 2020: 3.0, 2021: 0.6, 2022: -0.6}
    assert P.boom_removals(returns) == [
        {"name": "boom: without the best 1", "years": [2017]},
        {"name": "boom: without the best 2", "years": [2017, 2020]},
    ]
    tie = {**returns, 2020: 9.0}
    assert P.boom_removals(tie)[0]["years"] == [2017] and P.boom_removals(tie)[1]["years"] == [2017, 2020]
    with pytest.raises(ValueError, match=r"no yearly return for \[2022\]"):
        P.boom_removals({y: 0.0 for y in range(2017, 2022)})


# ------------------------------------------------------------------------------------------------ the index


def test_the_index_is_chain_linked_by_hand():
    idx = days(4)
    btc, eth = [100.0, 110.0, 99.0, 99.0], [200.0, 180.0, 198.0, 198.0]
    panel = panel_on(
        idx, btc, eth, btc_open=[100.0, 104.0, 110.0, 90.0], eth_open=[200.0, 200.0, 190.0, 198.0]
    )
    sig = P.index_signal(panel, 0.75)
    i1 = 1.0 * (1.0 + 0.75 * (110.0 / 100.0 - 1.0) + 0.25 * (180.0 / 200.0 - 1.0))
    i2 = i1 * (1.0 + 0.75 * (99.0 / 110.0 - 1.0) + 0.25 * (198.0 / 180.0 - 1.0))
    i3 = i2 * (1.0 + 0.75 * (99.0 / 99.0 - 1.0) + 0.25 * (198.0 / 198.0 - 1.0))
    assert sig["I"].tolist() == [1.0, i1, i2, i3]
    assert i1 == pytest.approx(1.05) and i2 == pytest.approx(1.05 * 0.95)
    o1 = 1.0 * (1.0 + 0.75 * (104.0 / 100.0 - 1.0) + 0.25 * (200.0 / 200.0 - 1.0))
    o3 = i2 * (1.0 + 0.75 * (90.0 / 99.0 - 1.0) + 0.25 * (198.0 / 198.0 - 1.0))
    assert math.isnan(sig["I_open"].iloc[0]) and sig["I_open"].iloc[1] == o1 and sig["I_open"].iloc[3] == o3
    assert sig["sma"].isna().all() and list(sig.columns) == ["I", "I_open", "sma"]
    with pytest.raises(ValueError, match=r"f must be in \[0.0, 1.0\]"):
        P.index_signal(panel, 1.5)


def test_the_sma_is_trend_sma_from_row_199_and_the_index_is_scale_free():
    panel = random_panel(260, 4)
    sig = P.index_signal(panel, 0.5)
    i = sig["I"].to_numpy()
    assert np.isnan(sig["sma"].to_numpy()[:199]).all()
    for t in (199, 200, 259):
        assert sig["sma"].iloc[t] == math.fsum(i[t - 199 : t + 1].tolist()) / 200
    np.testing.assert_array_equal(sig["sma"].to_numpy(), trend.sma(i, 200))
    # every price times a power of 2: the returns, so I and its SMA, are the same bit for bit
    frames = {a: pf.asset_bars(panel, a) for a in pf.ASSETS}
    for a in pf.ASSETS:
        frames[a][["open", "high", "low", "close"]] *= 8.0
    scaled = pf.make_panel(frames, snapshot_id="x")
    pd.testing.assert_frame_equal(P.index_signal(scaled, 0.5), sig)


def test_the_rule_is_unchanged_by_rescaling_the_index():
    """I times a power of 2 (another start date, up to rounding) gives the same decisions bit for bit."""
    panel = random_panel(300, 9, (0.06, 0.06))
    sig = P.index_signal(panel, 0.5)
    scaled = sig.assign(I=sig["I"] * 0.25, I_open=sig["I_open"] * 0.25, sma=sig["sma"] * 0.25)
    for mode in P.MODES:
        a = run(panel, tool(), brake("A", 0.10, mode), COSTS, signal=sig)
        b = run(panel, tool(), brake("A", 0.10, mode), COSTS, signal=scaled)
        pd.testing.assert_frame_equal(a, b)
        np.testing.assert_array_equal(a.attrs["orders"], b.attrs["orders"])


def test_signal_rows_and_the_signal_checks():
    panel = random_panel(30, 2)
    sig = P.index_signal(panel, 0.5)
    piece = panel.iloc[5:20]
    pd.testing.assert_frame_equal(P.signal_rows(sig, piece.index), sig.iloc[5:20])
    with pytest.raises(ValueError, match="the signal has no row for 1 closes"):
        P.signal_rows(sig.iloc[:19], piece.index)
    with pytest.raises(ValueError, match="signal must be a DataFrame with columns"):
        P.signal_rows(sig[["I"]], piece.index)
    tp, bp = tool(), brake()
    with pytest.raises(ValueError, match="a brake needs the index signal"):
        P.protect({**tp, **bp}, piece, ZERO)
    with pytest.raises(ValueError, match="signal must be on exactly the bars' index"):
        P.protect({**tp, **bp}, piece, ZERO, sig)
    bad = {
        "signal I must be finite": sig.assign(I=sig["I"].where(sig.index != sig.index[3], 0.0)),
        "signal I_open must be finite": sig.assign(I_open=np.nan),
        "signal sma must be NaN": sig.assign(sma=-1.0),
    }
    for message, frame in bad.items():
        with pytest.raises(ValueError, match=message):
            P.protect({**tp, **bp}, panel, ZERO, frame)
    P.protect(
        {**tp, **bp}, panel, ZERO, sig.assign(I_open=sig["I_open"].where(sig.index != sig.index[0], np.nan))
    )


# ------------------------------------------------------------------------------------------------ lines (exact)


def test_line_a_on_its_exact_float_expression():
    b = P.parse_brake("A", 0.10, "wait30", "counts")
    high = 8192.0
    on = (1.0 - 0.10) * high
    assert P.line_fires(b, on, high, D) and not P.line_fires(b, math.nextafter(on, math.inf), high, D)
    assert P.line_value(b, high, D) == on
    v = np.array([4096.0, 8192.0, 8000.0, math.nextafter(on, math.inf), on, 1.0])
    assert P.next_stop(v, 1, b, D) == 4  # exactly on the line fires, one ulp above does not
    assert P.next_stop(v[:4], 1, b, D) is None
    assert P.next_stop(v, 6, b, D) is None
    # the high is the running maximum from the start row: from row 3 the high is 7372.8...
    assert P.next_stop(v, 3, b, D) == 5
    with pytest.raises(ValueError, match="start must be an integer >= 1"):
        P.next_stop(v, 0, b, D)


def test_line_b_activation_and_line_on_their_exact_float_expressions():
    for y, g in P.B_GAIN.items():
        b = P.parse_brake("B", y, "wait30", "counts")
        h = (1.0 + g) * D
        below = math.nextafter(h, 0.0)
        line = D + y * (h - D)
        assert P.line_fires(b, line, h, D) and not P.line_fires(b, math.nextafter(line, math.inf), h, D)
        assert not P.line_fires(b, line, below, D)  # inactive one ulp below (1 + g) * D, whatever V
        assert not P.line_fires(b, 1.0, below, D)
        assert P.line_value(b, h, D) == line and math.isnan(P.line_value(b, below, D))
        assert P.next_stop([D, h, line], 1, b, D) == 2
        assert P.next_stop([D, below, 1.0], 1, b, D) is None
    # g = 1/3: (1 + 1/3) * 5000 = 6666.666666666666 is the pinned float
    assert (1.0 + P.B_GAIN[0.60]) * D == 6666.666666666666


def test_bad_brakes_and_params_are_refused_with_pinned_messages():
    bad = {
        ("C", 0.1, "wait30", "counts"): "line must be one of",
        ("A", 0.0, "wait30", "counts"): r"level must be in \(0.0, 1.0\)",
        ("A", 1.0, "wait30", "counts"): r"level must be in \(0.0, 1.0\)",
        ("B", 0.45, "wait30", "counts"): "line B's level must be one of",
        ("B", True, "wait30", "counts"): "line B's level must be one of",
        ("A", 0.1, "wait60", "counts"): "mode must be one of",
        ("A", 0.1, "wait30", "both"): "reading must be one of",
    }
    for args, message in bad.items():
        with pytest.raises(ValueError, match=message):
            P.parse_brake(*args)
    panel = random_panel(30, 1)
    with pytest.raises(ValueError, match=r"protect: unknown params \['stop'\]"):
        P.protect({**tool(), "stop": 0.1}, panel, ZERO)
    with pytest.raises(ValueError, match=r"protect: \['mode'\] given without a line"):
        P.protect({**tool(), "mode": "wait30"}, panel, ZERO)
    with pytest.raises(ValueError, match=r"missing \['reading'\]"):
        P.protect(
            {**tool(), "line": "A", "level": 0.1, "mode": "wait30"}, panel, ZERO, P.index_signal(panel, 0.5)
        )
    with pytest.raises(ValueError, match="hold_mix: the targets"):
        P.protect(tool((0.7, 0.0), LIMITS), panel, ZERO)
    with pytest.raises(ValueError, match="ret must be a non-empty 1-D array"):
        P.wallet_values([], D)
    with pytest.raises(ValueError, match="deposit must be in"):
        P.wallet_values([0.0], 0.0)
    assert P.wallet_values([0.0, 0.5, -0.5], 4.0).tolist() == [4.0, 6.0, 3.0]
    assert P.cost_vs_reference(4500.0, 5000.0) == 1.0 - 0.9 and P.cost_vs_reference(6000.0, 5000.0) < 0


# ------------------------------------------------------------------------------------------------ buy-backs (exact)


def _signal_case(mode, i_close, avg=None, day_offsets=None, reading="counts"):
    n = len(i_close)
    offsets = list(range(n)) if day_offsets is None else day_offsets
    stamps = [pd.Timestamp("2017-01-02", tz="UTC") + pd.Timedelta(days=d) for d in offsets]
    times = [s.value // 1000 for s in stamps]
    monday = [s.day_of_week == 0 for s in stamps]
    b = P.parse_brake("A", 0.1, mode, reading)
    avg = [math.nan] * n if avg is None else avg
    return b, times, monday, avg


def test_rebound_at_exactly_its_point_with_the_7_day_minimum_from_the_fill_instant():
    for mode, r in (("rebound-5", -0.05), ("rebound0", 0.0), ("rebound+5", 0.05)):
        at = (1.0 + r) * 0.8
        i_close = [0.8] + [at] * 9
        b, times, monday, avg = _signal_case(mode, i_close)
        got = [P._buyback_signal(b, c, 0, times, i_close, avg, monday, False) for c in range(10)]
        assert got == [False] * 7 + [True] * 3, mode  # 7 days after the sale's order close, not 6
        below = [0.8] + [math.nextafter(at, 0.0)] * 9
        assert not any(P._buyback_signal(b, c, 0, times, below, avg, monday, False) for c in range(10))
    # a missing close: the minimum counts calendar days, not rows
    i_close = [1.0] * 6
    b, times, monday, avg = _signal_case("rebound0", i_close, day_offsets=[0, 1, 2, 3, 7, 8])
    assert [P._buyback_signal(b, c, 0, times, i_close, avg, monday, False) for c in range(6)] == [
        False
    ] * 4 + [True] * 2


def test_wait_d_at_exactly_d_days():
    for mode, d in (("wait30", 30), ("wait180", 180)):
        i_close = [1.0] * (d + 2)
        b, times, monday, avg = _signal_case(mode, i_close, day_offsets=[*range(d - 1), d, d + 1, d + 2])
        got = [P._buyback_signal(b, c, 0, times, i_close, avg, monday, False) for c in range(len(i_close))]
        assert got == [False] * (d - 1) + [True] * 3, mode  # the row d-1 is day d: a missing close before it
        b, times, monday, avg = _signal_case(mode, [1.0] * (d + 1))
        assert [
            P._buyback_signal(b, c, 0, times, [1.0] * (d + 1), avg, monday, False) for c in (d - 1, d)
        ] == [
            False,
            True,
        ]


def test_the_trend_signal_needs_a_monday_the_minimum_a_dip_and_an_sma():
    i_close = [1.0] * 15
    avg = [0.9] * 15
    b, times, monday, _ = _signal_case("trend", i_close, avg)
    # 2017-01-02 is a Monday: rows 7 and 14 are Mondays
    assert [c for c in range(15) if monday[c]] == [0, 7, 14]
    assert [c for c in range(15) if P._buyback_signal(b, c, 0, times, i_close, avg, monday, True)] == [7, 14]
    assert not any(
        P._buyback_signal(b, c, 0, times, i_close, avg, monday, False) for c in range(15)
    )  # no dip
    exact = [1.02 * 0.9] * 15  # I exactly 1.02 * SMA: a dip, never a signal
    assert not any(P._buyback_signal(b, c, 0, times, exact, avg, monday, True) for c in range(15))
    assert all(P._is_dip(c, exact, avg) for c in range(15))
    above = [math.nextafter(1.02 * 0.9, 2.0)] * 15
    assert P._buyback_signal(b, 7, 0, times, above, avg, monday, True) and not P._is_dip(7, above, avg)
    nan = [math.nan] * 15  # no SMA: neither a signal nor a dip
    assert not P._buyback_signal(b, 7, 0, times, i_close, nan, monday, True) and not P._is_dip(
        7, i_close, nan
    )


# ------------------------------------------------------------------------------------------------ the overlay by hand


def test_line_a_fires_sells_at_the_next_open_and_the_high_restarts_after_the_buy_back():
    """Zero costs and one price for both coins (s = 0.5): V = cash + units x P. The high 5500 (P = 120) and P = 97
    give 4925 <= 4950: the stop at row 3, sold at row 4's open. wait-30 buys back at row 33 (30 days). After it the
    high restarts: V falls 8.6% from the new high (19% from the old one) and nothing fires, then 10.3% and it does."""
    n = 80
    c = path(n, r2=120.0, r3=97.0, r40=90.0, r50=77.0)
    panel = panel_on(days(n), c)
    res = run(panel, tool(), brake("A", 0.10, "wait30"))
    assert res.attrs["stops"].tolist() == [3, 50] and res.attrs["buybacks"].tolist() == [33]
    assert res.attrs["orders"].tolist() == [0, 3, 33, 50]
    assert list(res.attrs["reasons"]) == ["first", "stop", "buyback", "stop"]
    np.testing.assert_array_equal(res.attrs["order_targets"], [[0.25, 0.25], [0, 0], [0.25, 0.25], [0, 0]])
    v = values_of(res)
    assert v[2] == pytest.approx(5500.0) and v[3] == pytest.approx(4925.0)
    assert (res["position"].iloc[4:34] == 0.0).all() and res["position"].iloc[34] > 0
    # after the buy-back at P = 97 the book is 4925: P = 90 is 4747.3 (3.6% down), 77 is 4417.3 (10.3%); with the
    # old high 5500, P = 90 would be 13.7% down and the stop would have fired at row 40
    units = 0.5 * 4925.0 / 97.0
    assert v[40] == pytest.approx(0.5 * 4925.0 + units * 90.0) and v[50] == pytest.approx(
        0.5 * 4925.0 + units * 77.0
    )
    assert v[40] / 5500.0 - 1.0 < -0.10 and v[40] / v[34:41].max() - 1.0 > -0.10
    assert v[50] / v[34:51].max() - 1.0 <= -0.10
    res2 = run(
        panel_on(days(n), path(n, r2=120.0, r3=97.0, r40=90.0, r50=85.0)), tool(), brake("A", 0.05, "wait30")
    )
    assert res2.attrs["stops"].tolist() == [3, 50]  # 6.2% from the restarted high; 3.6% at row 40 is not 5%
    all_checks(res, panel, ZERO)
    assert (
        res.attrs["passes"] == 3 and res.attrs["not_bought_back"]
    )  # wait-30 from row 50 is past the last close


def test_overshoot_by_hand_on_a_gap_down():
    """The stop close (P = 97.9: V = 4947.5 <= 4950) and a gap to 80 at the next open: the sale gets 2500 + 25 x 80 =
    4500, 450 below the line: 450 / 4950 in the app's unit, 450 / 5500 per type. With costs the sale's legs cost
    exactly V_open - V_sale."""
    n = 40
    c = path(n, r2=120.0, r3=98.5, r4=97.9, r5=80.0)
    o = [c[0], *c[:-1]]
    o[5] = 80.0
    panel = panel_on(days(n), c, btc_open=o)
    res = run(panel, tool(), brake("A", 0.10, "wait180"))
    assert res.attrs["stops"].tolist() == [4] and res.attrs["not_bought_back"]
    sig = P.index_signal(panel, 0.5)
    (row,) = P.stop_rows(res, panel, sig)
    assert row["high"] == pytest.approx(5500.0) and row["line_value"] == pytest.approx(4950.0)
    assert row["v_sale"] == pytest.approx(4500.0) and row["v_open"] == pytest.approx(4500.0)
    assert row["overshoot"] == pytest.approx(450.0 / 4950.0) and row["overshoot_type"] == pytest.approx(
        450.0 / 5500.0
    )
    assert row["overshoot_before"] == pytest.approx(row["overshoot"])
    assert row["usdc_days"] == 35.0 and row["not_bought_back"] and row["buyback"] == -1
    assert math.isnan(row["restop"]) and row["missed_rebound"] == pytest.approx(80.0 / 80.0 - 1.0)
    with_costs = run(panel, tool(), brake("A", 0.10, "wait180"), COSTS)
    (r2,) = P.stop_rows(with_costs, panel, sig)
    paid = with_costs.attrs["fills"].query("bar == 5")["cost"].sum()
    assert r2["v_open"] - r2["v_sale"] == pytest.approx(paid, rel=1e-9)
    assert r2["overshoot"] - r2["overshoot_before"] == pytest.approx(paid / r2["line_value"], rel=1e-9)


def test_line_b_waits_for_its_gain_and_a_buy_back_below_it_disarms_it():
    """Y = 0.40, g = 0.20: B switches on at H >= 6000 (P >= 140). P = 139 (V 5975) then 100 (V 5000) fires nothing
    (A at 10% would). P = 141 (V 6025) arms it; P = 115 (V 5375 <= 5410) fires at row 6. wait-30 buys back at P = 115
    (V 5375 < 6000): B is off until the new high reaches 6000 again, so P = 90 fires nothing; P = 150 rearms it
    (V 6193), and P = 119 (V 5468 <= 5477) fires."""
    n = 110
    c = path(n, r2=139.0, r3=100.0, r5=141.0, r6=115.0, r50=90.0, r60=150.0, r70=120.0, r80=119.0)
    panel = panel_on(days(n), c)
    res = run(panel, tool(), brake("B", 0.40, "wait30"))
    assert res.attrs["stops"].tolist() == [6, 80] and res.attrs["buybacks"].tolist() == [36]
    a = run(panel, tool(), brake("A", 0.10, "wait180"))
    assert a.attrs["stops"].tolist()[0] == 3
    v = values_of(res)
    units = 0.5 * v[37] / 115.0  # the buy-back at P = 115: half of 5375 in coins
    assert v[37] == pytest.approx(5375.0) and v[60] == pytest.approx(0.5 * 5375.0 + units * 150.0)
    sig = P.index_signal(panel, 0.5)
    rows = P.stop_rows(res, panel, sig)
    assert rows[0]["high"] == pytest.approx(6025.0) and rows[0]["line_value"] == pytest.approx(5410.0)
    assert rows[1]["line_value"] == pytest.approx(5000.0 + 0.4 * (v[60] - 5000.0))
    assert not rows[0]["below_d"] and rows[0]["kept_share"] == pytest.approx(375.0 / 1025.0)
    m, _ = P.run_measures(res, panel, ZERO, sig)
    assert m["b_active"] and m["b_below_d"] == 0 and math.isnan(m["b_worst_below_d"])
    all_checks(res, panel, ZERO)


def test_a_b_sale_below_the_deposit_is_counted():
    n = 30
    c = path(n, r5=141.0, r6=116.0, r7=90.0)
    o = [c[0], *c[:-1]]
    o[7] = 90.0
    panel = panel_on(days(n), c, btc_open=o)
    res = run(panel, tool(), brake("B", 0.40, "wait180"))
    assert res.attrs["stops"].tolist() == [6]
    m, rows = P.run_measures(res, panel, ZERO, P.index_signal(panel, 0.5))
    assert rows[0]["below_d"] and rows[0]["sale_vs_d"] == pytest.approx(4750.0 / 5000.0 - 1.0)
    assert m["b_below_d"] == 1 and m["b_worst_below_d"] == pytest.approx(-0.05)
    assert m["b_kept_end"] == pytest.approx((4750.0 - 5000.0) / (6025.0 - 5000.0))
    never = run(panel_on(days(n), path(n, r5=139.0, r6=60.0)), tool(), brake("B", 0.40, "wait180"))
    mn, _ = P.run_measures(never, panel, ZERO, P.index_signal(panel, 0.5))
    assert not mn["b_active"] and math.isnan(mn["b_kept_end"]) and mn["stops"] == 0


def test_rebound_buys_back_at_the_first_close_7_days_on_with_the_index_back():
    n = 40
    c = path(n, r2=120.0, r3=97.0, r6=103.0)
    panel = panel_on(days(n), c)
    up = run(panel, tool(), brake("A", 0.10, "rebound+5"))
    assert up.attrs["stops"].tolist() == [3] and up.attrs["buybacks"].tolist() == [10]  # I up 6.2% from row 6
    flat = run(panel_on(days(n), path(n, r2=120.0, r3=97.0, r6=101.0)), tool(), brake("A", 0.10, "rebound+5"))
    assert flat.attrs["buybacks"].tolist() == [] and flat.attrs["not_bought_back"]
    down = run(panel_on(days(n), path(n, r2=120.0, r3=97.0, r6=93.0)), tool(), brake("A", 0.10, "rebound-5"))
    assert down.attrs["buybacks"].tolist() == [10]


def test_trend_waits_for_a_dip_below_its_average_then_a_monday_above_it_and_never_before_row_199():
    """Flat at 100 to row 204 (SMA 100), a high at 205 (V 5750), the stop at 206 (V 5000, 13% down). From 207 I stays
    10% above its SMA (no dip): no buy-back. A dip at row 224 (I back to 1.0, at or below 1.02 SMA) and I up again from
    225: the first Monday after it with I above 1.02 SMA buys back."""
    n = 260
    idx = days(n)
    c = path(n, r205=130.0, r206=100.0, r207=110.0)
    panel = panel_on(idx, c)
    res = run(panel, tool(), brake("A", 0.10, "trend"))
    sig = P.index_signal(panel, 0.5)
    assert res.attrs["stops"].tolist() == [206] and res.attrs["buybacks"].tolist() == []
    assert (sig["I"].to_numpy()[207:] > 1.02 * sig["sma"].to_numpy()[207:]).all()
    c2 = path(n, r205=130.0, r206=100.0, r207=110.0, r224=100.0, r225=110.0)
    panel2 = panel_on(idx, c2)
    sig2 = P.index_signal(panel2, 0.5)
    res2 = run(panel2, tool(), brake("A", 0.10, "trend"))
    i, avg = sig2["I"].to_numpy(), sig2["sma"].to_numpy()
    assert i[224] <= 1.02 * avg[224]
    want = next(t for t in range(225, n) if idx[t].day_of_week == 0 and i[t] > 1.02 * avg[t])
    assert res2.attrs["buybacks"].tolist() == [want] and idx[want].day_of_week == 0
    # a stop before row 199: dips without an SMA do not count, and nothing buys back before a dip after row 199
    c3 = path(n, r20=130.0, r21=100.0, r202=95.0, r203=120.0)
    panel3 = panel_on(idx, c3)
    sig3 = P.index_signal(panel3, 0.5)
    res3 = run(panel3, tool(), brake("A", 0.10, "trend"))
    i3, a3 = sig3["I"].to_numpy(), sig3["sma"].to_numpy()
    dip = next(t for t in range(199, n) if i3[t] <= 1.02 * a3[t])
    want3 = next(t for t in range(dip + 1, n) if idx[t].day_of_week == 0 and i3[t] > 1.02 * a3[t])
    assert res3.attrs["stops"].tolist()[0] == 21 and res3.attrs["buybacks"].tolist()[0] == want3 > 199
    for r, p in ((res2, panel2), (res3, panel3)):
        all_checks(r, p, ZERO)


def test_under_counts_a_buy_back_inside_the_tool_s_wait_waits_then_counts():
    """A band trade at row 3 (band 5%, P 100 -> 115) starts the tool's 15-day wait. The stop at row 5 and rebound 0 make
    the buy-back due at row 12 (7 days on, I back). 'separate' orders it there; 'counts' holds it until row 18, the
    first close 15 days after row 3, then counts (it restarts the wait)."""
    n = 60
    c = path(n, r3=115.0, r5=100.0, r12=101.0)
    panel = panel_on(days(n), c)
    sep = run(panel, tool(band=0.05), brake("A", 0.05, "rebound0", "separate"))
    cnt = run(panel, tool(band=0.05), brake("A", 0.05, "rebound0", "counts"))
    for res in (sep, cnt):
        assert res.attrs["orders"].tolist()[:3] == [0, 3, 5]
        assert list(res.attrs["reasons"][:3]) == ["first", "band", "stop"]
    assert sep.attrs["buybacks"].tolist() == [12] and sep.attrs["buyback_held"].tolist() == []
    assert cnt.attrs["buybacks"].tolist() == [18] and cnt.attrs["buyback_due"].tolist() == [12]
    assert cnt.attrs["buyback_held"].tolist() == list(range(12, 18))
    assert list(sep.attrs["in_wait"][:4]) == [False, False, False, True]  # sent inside the wait, exempt
    assert list(cnt.attrs["in_wait"][:4]) == [False, False, False, False]
    for res in (sep, cnt):
        all_checks(res, panel, ZERO)
    with pytest.raises(P.ConsistencyError, match="a buyback order at close 12 comes less than 15 days"):
        P.check_orders(sep, wait_days=15, reading="counts")  # 'separate''s buy-back judged as a counted trade
    m, rows = P.run_measures(cnt, panel, ZERO, P.index_signal(panel, 0.5))
    assert m["buyback_held"] == 6 and rows[0]["held_days"] == 6.0


def test_both_readings_restart_the_tool_s_wait_at_the_buy_back():
    """After the buy-back (row 12, 'separate') a band break at row 20 waits until row 27, 15 days after it."""
    n = 60
    c = path(n, r3=115.0, r5=100.0, r12=101.0, r20=125.0)
    panel = panel_on(days(n), c)
    res = run(panel, tool(band=0.05), brake("A", 0.05, "rebound0", "separate"))
    assert res.attrs["buybacks"].tolist() == [12]
    assert res.attrs["orders"].tolist()[3:5] == [12, 27] and res.attrs["reasons"][4] == "band"
    assert res.attrs["held"].tolist()[:7] == list(range(20, 27))
    all_checks(res, panel, ZERO)


def test_the_brake_wins_one_order_and_no_tool_order_while_stopped():
    """P 100 -> 50 at row 4 breaks the band (crypto 33%, below 35%) and the 20% line on one close: one order, the
    stop. While stopped P swings 50 -> 200 (a band break every close for a held mix): the tool is never asked."""
    n = 60
    c = path(n, r4=50.0, r10=200.0, r15=60.0)
    panel = panel_on(days(n), c)
    res = run(panel, tool(), brake("A", 0.20, "wait30"))
    assert res.attrs["orders"].tolist() == [0, 4, 34]
    assert list(res.attrs["reasons"]) == ["first", "stop", "buyback"]
    plain = H.hold_mix(tool(), panel, ZERO)
    assert plain.attrs["orders"].tolist()[:2] == [0, 4] and plain.attrs["reasons"][1] == "band"
    calls = []

    class Spy(P.ToolStep):
        def decide(self, t, w):
            calls.append(t)
            return super().decide(t, w)

    p = H._hold_params(tool())
    times = panel.index.asi8.tolist()
    sig = P.index_signal(panel, 0.5)
    spied = P.run_overlay(
        panel, ZERO, lambda: Spy(p, times), P.parse_brake("A", 0.20, "wait30", "counts"), sig
    )
    assert spied.attrs["orders"].tolist() == [0, 4, 34]
    last_pass = calls[-(n - 31) :]  # the last pass asks the tool at every close but 4 .. 34
    assert set(range(n)) - set(last_pass) >= set(range(4, 35)) and not set(range(4, 35)) & set(last_pass)
    all_checks(res, panel, ZERO)


def test_a_line_crossed_at_the_last_close_is_not_filled():
    n = 30
    panel = panel_on(days(n), path(n, r2=120.0, r29=90.0))
    res = run(panel, tool(), brake("A", 0.10, "wait30"))
    assert res.attrs["stops"].tolist() == [] and res.attrs["unfilled"].tolist() == [29]
    assert res.attrs["passes"] == 1 and not res.attrs["not_bought_back"]
    ref = run(panel, tool())
    pd.testing.assert_frame_equal(res[ALL_COLUMNS], ref[ALL_COLUMNS])
    m, rows = P.run_measures(res, panel, ZERO, P.index_signal(panel, 0.5))
    assert rows == [] and m["unfilled"] and m["stops"] == 0 and not m["fired"]
    P.check_events(res, P.index_signal(panel, 0.5))


def test_a_buy_back_due_at_the_last_close_is_never_sent():
    n = 34
    panel = panel_on(days(n), path(n, r2=120.0, r3=97.0))
    res = run(panel, tool(), brake("A", 0.10, "wait30"))
    assert res.attrs["stops"].tolist() == [3] and res.attrs["buybacks"].tolist() == []
    assert res.attrs["not_bought_back"] and res.attrs["orders"].tolist() == [0, 3]
    all_checks(res, panel, ZERO)


def test_a_toy_dip_buyer_is_blocked_while_stopped_and_resumes_after_the_buy_back():
    """The overlay wraps any step (owner, 2026-11-23): a toy dip buyer holds 30% BTC and buys up to 50% when BTC closes
    10% below its last 5 closes' highest. It is not asked while the wallet is stopped (no dip bought there, though BTC
    dips), is told of the buy-back, and buys the next dip after it."""

    class DipBuyer:
        def __init__(self, closes, times):
            self.closes = closes
            self.targets = (0.30, 0.0)
            self.reason_at, self.in_wait_at, self.held = {}, {}, []
            self.asked, self.told = [], []
            self.loaded = False

        def decide(self, t, w):
            self.asked.append(t)
            if t == 0:
                self.reason_at[t], self.in_wait_at[t] = "first", False
                return self.targets
            top = max(self.closes[max(0, t - 5) : t])
            if not self.loaded and self.closes[t] <= 0.9 * top:
                self.loaded = True
                self.reason_at[t], self.in_wait_at[t] = "dip", False
                return (0.50, 0.0)
            return None

        def waiting(self, t):
            return False

        def bought_back(self, t):
            self.told.append(t)
            self.loaded = False

    n = 80
    # BTC dips at 3 (89: bought, V 3.3% down), falls to 70 at 6 (V 13.6% down: the stop), dips to 50 at 10 while
    # stopped (not asked), and dips to 44 at 45 after the buy-back at 36 (bought)
    c = path(n, r3=89.0, r6=70.0, r10=50.0, r45=44.0)
    panel = panel_on(days(n), c, path(n))
    steps = []

    def make():
        steps.append(DipBuyer(c, panel.index.asi8.tolist()))
        return steps[-1]

    sig = P.index_signal(panel, 1.0)
    res = P.run_overlay(panel, ZERO, make, P.parse_brake("A", 0.10, "wait30", "counts"), sig)
    last = steps[-1]
    assert res.attrs["orders"].tolist() == [0, 3, 6, 36, 45]
    assert list(res.attrs["reasons"]) == ["first", "dip", "stop", "buyback", "dip"]
    np.testing.assert_array_equal(
        res.attrs["order_targets"], [[0.3, 0], [0.5, 0], [0, 0], [0.3, 0], [0.5, 0]]
    )
    assert not set(range(6, 37)) & set(last.asked) and last.told == [36]
    assert set(range(6)) | set(range(37, n)) == set(last.asked)
    assert res.attrs["stops"].tolist() == [6] and res.attrs["buybacks"].tolist() == [36]
    out, _ = order_book(panel, res, ZERO)
    np.testing.assert_allclose(res["ret"].to_numpy(), out["ret"], rtol=0, atol=1e-12)


# ------------------------------------------------------------------------------------------------ identities


@given(
    panel=st.builds(
        random_panel,
        st.integers(40, 140),
        st.integers(0, 2**32 - 1),
        st.tuples(st.sampled_from([0.01, 0.04, 0.1]), st.sampled_from([0.01, 0.04, 0.1])),
    ),
    data=st.data(),
)
@example(panel=random_panel(120, 5, (0.1, 0.1)), data=None)
def test_the_tool_copy_equals_hold_mix_bit_for_bit(panel, data):
    """With the brake off the copy is hold_mix (section 9): drawn limits close to the targets (so limit fixes come
    inside the wait), waits, bands, resets, both first-buy readings and a missing close."""
    if data is None:
        params, drop = tool((0.5, 0.0), {"min_cash": 0.2, "max_coin": 0.55}, band=0.02, wait=15), 30
    else:
        s, f = data.draw(st.sampled_from(P.MIXES))
        limits = data.draw(st.sampled_from([NONE, LIMITS, {"min_cash": 0.2, "max_coin": 0.55}]))
        params = tool(
            H.mix_targets(s, f),
            limits,
            band=data.draw(st.sampled_from([0.0, 0.02, 0.3])),
            wait=data.draw(st.integers(1, 30)),
            reset=data.draw(st.sampled_from([None, 7, 40])),
            first_buy_waits=data.draw(st.booleans()),
        )
        drop = data.draw(st.integers(2, len(panel) - 3))
    panel = pf.make_panel(
        {a: pf.asset_bars(panel, a).drop(panel.index[drop]) for a in pf.ASSETS}, snapshot_id="x"
    )  # a missing close: the wait counts calendar days
    for costs in (COSTS, COSTS_2X):
        copy = P.protect(params, panel, costs)
        P.check_tool_copy(copy, H.hold_mix(params, panel, costs))
        P.check_orders(
            copy, wait_days=params["wait_days"], reading=None, first_buy_waits=params["first_buy_waits"]
        )
        P.check_book(copy, panel, costs)
        assert copy.attrs["brake"] is None


def test_the_tool_copy_resets_as_hold_mix_does():
    """The reset, by hand (#67: the reset branch of ``ToolStep.decide`` was reached only by drawn cases, so 100%
    coverage depended on the draws). Flat prices keep both coins on target, so nothing but the reset orders: the
    first buy at close 0, then a reset every 7 days from the last order, and never at the last close. The copy
    equals ``hold_mix`` bit for bit; with a reset longer than the window nothing follows the first buy."""
    n = 60
    panel = panel_on(days(n), path(n))
    params = tool((0.25, 0.25), NONE, band=0.30, wait=1, reset=7)
    for costs in (ZERO, COSTS):
        copy = P.protect(params, panel, costs)
        P.check_tool_copy(copy, H.hold_mix(params, panel, costs))
        assert copy.attrs["orders"].tolist() == list(range(0, n - 1, 7))
        assert copy.attrs["reasons"].tolist() == ["first"] + ["reset"] * 8
    never = P.protect({**params, "reset_days": 90}, panel, ZERO)
    P.check_tool_copy(never, H.hold_mix({**params, "reset_days": 90}, panel, ZERO))
    assert never.attrs["orders"].tolist() == [0] and never.attrs["reasons"].tolist() == ["first"]


@given(case=cases(), costs=st.sampled_from([COSTS, COSTS_2X]))
def test_a_level_that_never_fires_is_the_reference_bit_for_bit(case, costs):
    panel, tp, bp, f = case
    ref = run(panel, tp, costs=costs, f=f)
    never = run(panel, tp, {**bp, "line": "A", "level": 0.99}, costs, f)
    assert never.attrs["stops"].tolist() == [] and never.attrs["passes"] == 1
    pd.testing.assert_frame_equal(never[ALL_COLUMNS], ref[ALL_COLUMNS])
    for key in ("orders", "reasons", "in_wait", "held", "order_targets"):
        np.testing.assert_array_equal(never.attrs[key], ref.attrs[key])
    assert never.attrs["fills"].equals(ref.attrs["fills"])


# ------------------------------------------------------------------------------------------------ re-running and checks


@given(case=cases(), costs=st.sampled_from([COSTS, COSTS_2X]))
@example(
    case=(
        random_panel(150, 11, (0.09, 0.09), (0.04, 0.04)),
        tool((0.35, 0.35), LIMITS, 0.05, 15),
        brake("A", 0.05, "rebound0", "counts"),
        0.5,
    ),
    costs=COSTS,
)
@example(case=BUSY_B, costs=COSTS)
@example(case=(BUSY_B[0], BUSY_B[1], {**BUSY_B[2], "reading": "separate"}, 0.5), costs=COSTS_2X)
def test_the_re_running_equals_an_independent_one_pass_engine(case, costs):
    """Section 5's re-running against ``one_pass``, which decides every order itself in coin units and USDC cash: the
    same orders, reasons, stops and buy-backs, and every return and weight to 1e-12. Every check of section 9 passes,
    and the run's stops and buy-backs equal recompute_events'."""
    panel, tp, bp, f = case
    res = run(panel, tp, bp, costs, f)
    book = one_pass(panel, tp, bp, costs, f)
    assert res.attrs["orders"].tolist() == book["orders"]
    assert list(res.attrs["reasons"]) == book["reasons"]
    assert res.attrs["stops"].tolist() == book["stops"] and res.attrs["buybacks"].tolist() == book["buybacks"]
    np.testing.assert_allclose(res["ret"].to_numpy(), book["ret"], rtol=0, atol=1e-12)
    np.testing.assert_allclose(res[["w_BTC", "w_ETH"]].to_numpy(), book["weights"], rtol=0, atol=1e-12)
    all_checks(res, panel, costs, f)
    assert res.attrs["passes"] == len(book["stops"]) + 1


@given(case=long_cases(), costs=st.sampled_from([COSTS, COSTS_2X]))
@example(case=BUSY_TREND, costs=COSTS)
def test_the_re_running_equals_the_one_pass_engine_with_the_trend_buy_back(case, costs):
    panel, tp, bp, f = case
    res = run(panel, tp, bp, costs, f)
    book = one_pass(panel, tp, bp, costs, f)
    assert res.attrs["orders"].tolist() == book["orders"] and list(res.attrs["reasons"]) == book["reasons"]
    np.testing.assert_allclose(res["ret"].to_numpy(), book["ret"], rtol=0, atol=1e-12)
    all_checks(res, panel, costs, f)


@given(case=cases(), costs=st.sampled_from([COSTS, COSTS_2X]))
def test_accounting_equals_a_book_of_coin_units_and_cash(case, costs):
    panel, tp, bp, f = case
    res = run(panel, tp, bp, costs, f)
    out, value = order_book(panel, res, costs)
    for col in ("ret", "w_BTC", "w_ETH"):
        np.testing.assert_allclose(res[col].to_numpy(), out[col], rtol=0, atol=1e-12, err_msg=col)
    np.testing.assert_allclose(values_of(res, costs), value, rtol=1e-12)
    P.check_book(res, panel, costs)
    m, _ = P.run_measures(res, panel, costs, P.index_signal(panel, f))  # the fee check and the split


def _anchors(res) -> list[int]:
    events = [
        *res.attrs["stops"].tolist(),
        *res.attrs["buybacks"].tolist(),
        *res.attrs["buyback_held"].tolist(),
    ]
    return sorted({x for t in events for x in (t, t + 1, t + 2)})


def same_before(panel, other, tp, bp, f, cut) -> None:
    """Everything decided before ``cut`` is the same on ``panel`` and on ``other`` (tampered from ``cut`` on)."""
    a, b = run(panel, tp, bp, COSTS, f), run(other, tp, bp, COSTS, f)
    sa, sb = P.index_signal(panel, f), P.index_signal(other, f)
    np.testing.assert_array_equal(sa[["I", "sma"]].to_numpy()[:cut], sb[["I", "sma"]].to_numpy()[:cut])
    np.testing.assert_array_equal(sa["I_open"].to_numpy()[: cut + 1], sb["I_open"].to_numpy()[: cut + 1])
    for key in ("stops", "buybacks", "buyback_due", "buyback_held", "orders", "held"):
        ka, kb = a.attrs[key], b.attrs[key]
        np.testing.assert_array_equal(ka[ka < cut], kb[kb < cut], err_msg=key)
    np.testing.assert_array_equal(a[ALL_COLUMNS].to_numpy()[:cut], b[ALL_COLUMNS].to_numpy()[:cut])
    assert (a["turnover"].iloc[cut], a["cost"].iloc[cut]) == (b["turnover"].iloc[cut], b["cost"].iloc[cut])
    oa, ob = a.attrs["orders"] < cut, b.attrs["orders"] < cut
    np.testing.assert_array_equal(a.attrs["order_targets"][oa], b.attrs["order_targets"][ob])
    assert list(a.attrs["reasons"][oa]) == list(b.attrs["reasons"][ob])
    assert list(a.attrs["in_wait"][oa]) == list(b.attrs["in_wait"][ob])
    keep = ("stop", "high", "line_value", "v_stop", "v_open", "v_sale", "overshoot", "days_from_start")
    ra = [{k: r[k] for k in keep} for r in P.stop_rows(a, panel, sa) if r["stop"] + 1 < cut]
    rb = [{k: r[k] for k in keep} for r in P.stop_rows(b, other, sb) if r["stop"] + 1 < cut]
    assert ra == rb


def test_no_look_ahead_at_every_anchor_of_a_busy_run():
    """The busy trend run (3 stops bought back, 'counts' buy-backs held): tampered from each stop, buy-back and held
    close, and the close after each (the re-arm), nothing decided before the cut moves."""
    panel, tp, bp, f = BUSY_TREND
    a = run(panel, tp, bp, COSTS, f)
    anchors = sorted(
        {x for t in (*a.attrs["stops"], *a.attrs["buybacks"], *a.attrs["buyback_held"]) for x in (t, t + 1)}
    )
    assert len(anchors) >= 10
    for i, cut in enumerate(anchors):
        same_before(panel, tamper_from(panel, int(cut), i), tp, bp, f, int(cut))


@given(case=long_cases(), data=st.data())
def test_no_look_ahead_in_the_stops_lines_buy_backs_index_or_results(case, data):
    """Tamper the future on the full panel (every field of both coins from ``cut`` on, the fill open of ``cut`` kept):
    every stop, buy-back, order, index value, SMA and result row decided before ``cut`` is the same. Half the cuts land
    at a stop, a buy-back, or the close after one (the re-arm)."""
    panel, tp, bp, f = case
    n = len(panel)
    a = run(panel, tp, bp, COSTS, f)
    anchors = [c for c in _anchors(a) if 1 <= c <= n - 1]
    if anchors and data.draw(st.booleans()):
        cut = data.draw(st.sampled_from(anchors))
    else:
        cut = data.draw(st.integers(1, n - 1))
    same_before(panel, tamper_from(panel, cut, data.draw(st.integers(0, 2**16))), tp, bp, f, cut)


def test_every_check_fires_on_a_broken_result():
    panel = random_panel(150, 11, (0.09, 0.09), (0.04, 0.04))
    tp = tool((0.35, 0.35), LIMITS, 0.05, 15)
    bp = brake("A", 0.05, "rebound0", "counts")
    sig = P.index_signal(panel, 0.5)
    res = run(panel, tp, bp, COSTS)
    assert len(res.attrs["stops"]) >= 2 and len(res.attrs["buyback_held"]) >= 1
    all_checks(res, panel, COSTS)

    def broken(**attrs):
        out = res.copy()
        out.attrs = {**res.attrs, **attrs}
        return out

    stops = res.attrs["stops"]
    with pytest.raises(P.ConsistencyError, match="the re-running's stops"):
        P.check_events(broken(stops=stops[:-1]), sig)
    with pytest.raises(P.ConsistencyError, match="buyback_held"):
        P.check_events(broken(buyback_held=res.attrs["buyback_held"][1:]), sig)
    reasons = res.attrs["reasons"].copy()
    reasons[1] = "band" if reasons[1] != "band" else "limit"
    orders = res.attrs["orders"]
    cases_ = {
        "not aligned": broken(in_wait=res.attrs["in_wait"][:-1]),
        "the one order at close 0": broken(reasons=np.asarray(["band", *reasons[1:]], dtype=object)),
        "increasing closes": broken(reasons=np.asarray([*reasons[:-1], "switch"], dtype=object)),
        "the stops and buy-backs listed": broken(stops=stops[:-1]),
        "in-wait flag": broken(in_wait=~res.attrs["in_wait"]),
        "held closes": broken(held=np.asarray([orders[1]], dtype=np.int64)),
        "buyback_held closes": broken(buyback_held=np.asarray([1], dtype=np.int64)),
    }
    for message, bad in cases_.items():
        with pytest.raises(P.ConsistencyError, match=message):
            P.check_orders(bad, wait_days=15, reading="counts")
    with pytest.raises(P.ConsistencyError, match="comes less than 60 days after the wait started"):
        P.check_orders(res, wait_days=60, reading="counts")
    targets = res.attrs["order_targets"].copy()
    s_at = int(np.flatnonzero(res.attrs["reasons"] == "stop")[0])
    targets[s_at] = [0.1, 0.0]
    with pytest.raises(P.ConsistencyError, match="does not order all USDC"):
        P.check_orders(broken(order_targets=targets), wait_days=15, reading="counts")
    swapped = res.attrs["reasons"].copy()
    b_at = int(np.flatnonzero(swapped == "buyback")[0])
    swapped[b_at] = "band"
    with pytest.raises(P.ConsistencyError, match="alternate"):
        P.check_orders(
            broken(reasons=swapped, buybacks=res.attrs["buybacks"][1:]), wait_days=15, reading="counts"
        )
    tampered = res.copy()
    tampered.attrs = dict(res.attrs)
    tampered.iloc[60, tampered.columns.get_loc("ret")] += 1e-9
    with pytest.raises(P.ConsistencyError, match="the return or value on row 60"):
        P.check_book(tampered, panel, COSTS)
    tampered = res.copy()
    tampered.attrs = dict(res.attrs)
    tampered.iloc[60, tampered.columns.get_loc("w_BTC")] += 1e-9
    with pytest.raises(P.ConsistencyError, match="the weights on row 60"):
        P.check_book(tampered, panel, COSTS)
    fills = res.attrs["fills"].copy()
    fills.loc[3, "cost"] += 1e-6
    with pytest.raises(P.ConsistencyError, match="the leg of"):
        P.check_book(broken(fills=fills), panel, COSTS)
    with pytest.raises(P.ConsistencyError, match="a fill row follows no order"):
        P.check_book(broken(orders=orders[1:], order_targets=res.attrs["order_targets"][1:]), panel, COSTS)
    with pytest.raises(ValueError, match="check_book: costs must be a Costs instance"):
        P.check_book(res, panel, None)


def test_check_orders_catches_tool_orders_while_stopped_and_an_unsold_stop():
    n = 60
    panel = panel_on(days(n), path(n, r4=50.0, r10=200.0, r15=60.0))
    res = run(panel, tool(), brake("A", 0.20, "wait30"))
    bad = res.copy()
    bad.attrs = {
        **res.attrs,
        "reasons": np.asarray(["first", "stop", "band"], dtype=object),
        "buybacks": np.asarray([], dtype=np.int64),
    }
    with pytest.raises(
        P.ConsistencyError, match=r"a tool order \(band\) at close 34 while the wallet is stopped"
    ):
        P.check_orders(bad, wait_days=15, reading="counts")
    unsold = res.copy()
    unsold.attrs = dict(res.attrs)
    unsold.iloc[5, unsold.columns.get_loc("position")] = 0.1
    with pytest.raises(P.ConsistencyError, match="did not leave the wallet all USDC"):
        P.check_orders(unsold, wait_days=15, reading="counts")


def test_check_tool_copy_names_what_differs():
    panel = random_panel(60, 3)
    tp = tool(band=0.02, wait=4)
    a, b = P.protect(tp, panel, COSTS), H.hold_mix(tp, panel, COSTS)
    P.check_tool_copy(a, b)

    def with_attr(key, value):
        out = a.copy()
        out.attrs = {**a.attrs, key: value}
        return out

    shifted = a.copy()
    shifted.attrs = dict(a.attrs)
    shifted.iloc[-1, shifted.columns.get_loc("ret")] = np.nextafter(a["ret"].iloc[-1], 1.0)
    cases_ = {
        "differs from hold_mix's": shifted,
        "orders differs": with_attr("orders", a.attrs["orders"][:-1]),
        "in_wait differs": with_attr("in_wait", ~a.attrs["in_wait"]),
        "held differs": with_attr("held", np.asarray([1], dtype=np.int64)),
        "reasons differ": with_attr(
            "reasons", np.asarray(["first", *["limit"] * (len(a.attrs["reasons"]) - 1)], dtype=object)
        ),
        "fills differ": with_attr("n_trades", -1),
        "another index": a.iloc[:-1],
    }
    for message, bad in cases_.items():
        with pytest.raises(P.ConsistencyError, match=message):
            P.check_tool_copy(bad, b)


def test_a_known_stop_while_stopped_is_a_consistency_error():
    n = 60
    panel = panel_on(days(n), path(n, r2=120.0, r3=97.0))
    p = H._hold_params(tool())
    times = panel.index.asi8.tolist()
    b = P.parse_brake("A", 0.10, "wait30", "counts")
    arrays = P._signal_arrays(P.index_signal(panel, 0.5), panel)
    with pytest.raises(P.ConsistencyError, match="fell while the wallet was stopped"):
        P._pass(panel, ZERO, P.ToolStep(p, times), b, arrays, [3, 10])


# ------------------------------------------------------------------------------------------------ measures


def test_run_measures_by_hand_on_a_re_stop_and_the_fee_split():
    """Two stops, at 3 and at 40: wait-30 buys back at 33 (V 4925, P 97), the new high is P 110 (V 5255) and P 88
    (V 4697, 10.6% down) stops again at 40, 7 days after the buy-back: a re-stop. The buy-back at 70 is followed by no
    stop."""
    n = 90
    c = path(n, r2=120.0, r3=97.0, r36=110.0, r40=88.0)
    panel = panel_on(days(n), c)
    res = run(panel, tool(), brake("A", 0.10, "wait30"), COSTS)
    assert res.attrs["stops"].tolist() == [3, 40] and res.attrs["buybacks"].tolist() == [33, 70]
    sig = P.index_signal(panel, 0.5)
    m, rows = P.run_measures(res, panel, COSTS, sig)
    assert [r["restop"] for r in rows] == [True, False]  # 40 - 33 = 7 days; after 70 no stop
    assert m["restops"] == 1 and m["buybacks"] == 2 and m["stops"] == 2 and m["fired"]
    assert m["first_stop_days"] == 3.0 and rows[1]["days_from_start"] == 40.0
    assert [r["usdc_days"] for r in rows] == [30.0, 30.0] and m["usdc_days"] == 60.0
    assert m["usdc_share"] == 60.0 / (n - 1)
    assert rows[0]["missed_rebound"] == pytest.approx(sig["I_open"].iloc[34] / sig["I_open"].iloc[4] - 1.0)
    money = H.money_metrics(res, COSTS)
    assert m["F"] == -money["max_drawdown"] and m["fees_pct_per_year"] == money["fees_pct_per_year"]
    assert m["fees_pct_per_year_tool"] == 0.0 and m["fees_pct_per_year_brake"] == pytest.approx(
        money["fees_pct_per_year"]
    )
    assert m["tool_orders"] == 0 and m["passes"] == 3 and m["v_end"] == values_of(res, COSTS)[-1]
    assert m["overshoot_max"] == max(r["overshoot"] for r in rows)
    ref, _ = P.run_measures(run(panel, tool(), costs=COSTS), panel, COSTS, None)
    assert (ref["stops"], ref["fired"], ref["buybacks"], ref["passes"]) == (0, False, 0, 1)
    assert math.isnan(ref["first_stop_days"]) and math.isnan(ref["overshoot_max"])
    assert set(m) == set(P.RUN_MEASURES)
    assert set(rows[0]) == set(P.STOP_COLUMNS)


def test_a_re_stop_is_a_stop_at_most_30_days_after_the_buy_back():
    """wait-30 buys back at row 33 (V 4925 at P 97); P 77 (10.3% down) stops again exactly 30 days later (row 63: a
    re-stop, inclusive) or 31 days later (row 64: not)."""
    n = 100
    for drop, want in ((63, True), (64, False)):
        panel = panel_on(days(n), path(n, r2=120.0, r3=97.0, **{f"r{drop}": 77.0}))
        res = run(panel, tool(), brake("A", 0.10, "wait30"))
        assert res.attrs["stops"].tolist() == [3, drop] and res.attrs["buybacks"].tolist()[0] == 33
        m, rows = P.run_measures(res, panel, ZERO, P.index_signal(panel, 0.5))
        assert rows[0]["restop"] is want and m["restops"] == int(want)


def test_the_missed_rebound_runs_from_the_sale_s_fill_open_to_the_buy_back_s_fill_open():
    """The stop at row 3 sells at row 4's open (97, no gap); wait-30 buys back at row 33, filled at row 34's open, which
    gaps from 97 to 105: one price for both coins, so I moves with it and the missed rebound is 105 / 97 - 1 (read at
    the buy-back's close it would be 0). Not bought back, it runs to the last close (P 110)."""
    n = 60
    c = path(n, r2=120.0, r3=97.0, r34=105.0, r50=110.0)
    o = [c[0], *c[:-1]]
    o[34] = 105.0
    panel = panel_on(days(n), c, btc_open=o)
    res = run(panel, tool(), brake("A", 0.10, "wait30"))
    assert res.attrs["stops"].tolist() == [3] and res.attrs["buybacks"].tolist() == [33]
    (row,) = P.stop_rows(res, panel, P.index_signal(panel, 0.5))
    assert row["missed_rebound"] == pytest.approx(105.0 / 97.0 - 1.0, rel=1e-12)
    later = run(panel, tool(), brake("A", 0.10, "wait180"))
    (row,) = P.stop_rows(later, panel, P.index_signal(panel, 0.5))
    assert row["not_bought_back"] and row["missed_rebound"] == pytest.approx(110.0 / 97.0 - 1.0, rel=1e-12)


def test_the_fee_split_must_add_up():
    panel = random_panel(120, 11, (0.09, 0.09))
    res = run(panel, tool(band=0.05), brake("A", 0.05, "rebound0"), COSTS)
    original = H.money_metrics

    def off(result, costs):
        out = original(result, costs)
        return {**out, "fees_pct_per_year": out["fees_pct_per_year"] * 1.001}

    H.money_metrics = off
    try:
        with pytest.raises(P.ConsistencyError, match="do not add up"):
            P.run_measures(res, panel, COSTS, P.index_signal(panel, 0.5))
    finally:
        H.money_metrics = original


# ------------------------------------------------------------------------------------------------ the rules


MIX2 = ((0.3, 0.5), (0.7, 0.75))


def pool_table(spec: dict, ref_f, windows: int = 11, ref_c=None) -> pd.DataFrame:
    """A hand-made pool: reference runs with falls ``ref_f[mix][window]`` and, per (line, level, mode, reading), falls
    and costs ``spec[key] = (F per mix and window, C per mix and window, buybacks, restops)`` (scalars broadcast)."""
    rows = []
    for m, (s, f) in enumerate(MIX2):
        for w in range(windows):
            rows.append(
                {
                    "run_id": f"R:{m}:{w}",
                    "source": "KRAKEN",
                    "cost": "1x",
                    "reading": "none",
                    "line": "R",
                    "level": math.nan,
                    "mode": "none",
                    "s": s,
                    "f": f,
                    "window": w,
                    "status": "ok",
                    "F": ref_f[m][w],
                    "C": 0.0,
                    "buybacks": 0,
                    "restops": 0,
                }
            )
    for (line, level, mode, reading), (fall, cost, buybacks, restops) in spec.items():
        for m, (s, f) in enumerate(MIX2):
            for w in range(windows):
                rows.append(
                    {
                        "run_id": f"{line}:{level}:{mode}:{reading}:{m}:{w}",
                        "source": "KRAKEN",
                        "cost": "1x",
                        "reading": reading,
                        "line": line,
                        "level": level,
                        "mode": mode,
                        "s": s,
                        "f": f,
                        "window": w,
                        "status": "ok",
                        "F": fall[m][w] if isinstance(fall, list) else fall,
                        "C": cost[m][w] if isinstance(cost, list) else cost,
                        "buybacks": buybacks if not w and not m else 0,
                        "restops": restops if not w and not m else 0,
                    }
                )
    return pd.DataFrame(rows)


def ref_falls(q0=0.375) -> list[list[float]]:
    """11 windows per mix: the 90th percentile (row 9 of 10) is exactly ``q0`` per mix and pooled (rows 18 and 19 of
    22 are both q0), the worst 0.5."""
    one = [0.1] * 9 + [q0, 0.5]
    return [one, one]


def falls(q) -> list[list[float]]:
    one = [0.05] * 9 + [q, 0.45]
    return [one, one]


def test_d1_meaningful_protection_at_exactly_3q_equals_2q0_pooled_and_per_mix():
    key = ("A", 0.10, "wait30", "counts")
    spec = {key: (falls(0.25), -0.01, 4, 1)}
    t = pool_table(spec, ref_falls())
    d = P.d1(t, "A", "wait30", "counts")
    (entry,) = d["table"]
    assert (d["Q0"], entry["Q"]) == (0.375, 0.25) and 3.0 * 0.25 == 2.0 * 0.375
    assert entry["pooled"] and entry["per_mix"] and entry["worst_guard"] and d["default"] == 0.10
    above = math.nextafter(0.25, 1.0)
    d = P.d1(pool_table({key: (falls(above), -0.01, 4, 1)}, ref_falls()), "A", "wait30", "counts")
    assert not d["table"][0]["pooled"] and d["default"] == P.NO_DEFAULT
    # per mix: the second mix's own 90th percentile one ulp too high while the pool's holds (0.05 + 0.9 x (above -
    # 0.05) is below 0.25): per_mix alone fails the level (#63, P16)
    mixed = [[0.05] * 10 + [0.45], [0.05] * 9 + [above, 0.45]]
    ref_mixed = [[0.1] * 9 + [0.375, 0.5], [0.1] * 9 + [0.375, 0.5]]
    d = P.d1(pool_table({key: (mixed, -0.01, 4, 1)}, ref_mixed), "A", "wait30", "counts")
    e = d["table"][0]
    assert e["pooled"] and e["worst_guard"] and not e["per_mix"] and not e["meaningful"]
    assert d["default"] == P.NO_DEFAULT
    assert e["Q_mix"] == {"0.3/0.5": 0.05, "0.7/0.75": above} and e["Q0_mix"] == {
        "0.3/0.5": 0.375,
        "0.7/0.75": 0.375,
    }
    at = [[0.05] * 10 + [0.45], [0.05] * 9 + [0.25, 0.45]]  # exactly 3 Q = 2 Q0 in the second mix: meaningful
    assert P.d1(pool_table({key: (at, -0.01, 4, 1)}, ref_mixed), "A", "wait30", "counts")["default"] == 0.10


def test_d1_the_worst_fall_guard_and_q0_zero():
    key = ("A", 0.10, "wait30", "counts")
    worse = [[0.05] * 9 + [0.25, 0.5], [0.05] * 9 + [0.25, math.nextafter(0.5, 1.0)]]
    d = P.d1(pool_table({key: (worse, -0.01, 4, 1)}, ref_falls()), "A", "wait30", "counts")
    assert d["table"][0]["pooled"] and d["table"][0]["per_mix"] and not d["table"][0]["worst_guard"]
    assert d["default"] == P.NO_DEFAULT
    equal = [[0.05] * 9 + [0.25, 0.5], [0.05] * 9 + [0.25, 0.5]]
    assert (
        P.d1(pool_table({key: (equal, -0.01, 4, 1)}, ref_falls()), "A", "wait30", "counts")["default"] == 0.10
    )
    zero = [[0.0] * 11, [0.0] * 11]
    d = P.d1(pool_table({key: (zero, 0.0, 0, 0)}, zero), "A", "wait30", "counts")
    assert d["default"] == P.NO_DEFAULT and d["reason"].startswith("Q0 = 0")


def test_d1_ranks_by_the_median_cost_with_ties_broken_by_the_mean_then_the_looser_level():
    good = falls(0.25)
    spec = {
        ("A", 0.10, "trend", "counts"): (good, -0.020, 1, 0),
        ("A", 0.20, "trend", "counts"): (good, [[-0.020 + 1e-12] * 11, [-0.020 + 1e-12] * 11], 1, 0),
        ("A", 0.30, "trend", "counts"): (good, -0.019, 1, 0),
        ("A", 0.40, "trend", "counts"): (falls(0.3), -0.5, 1, 0),  # cheapest but not meaningful
    }
    t = pool_table(spec, ref_falls())
    d = P.d1(t, "A", "trend", "counts")
    # 0.10 and 0.20 tie on C~ (within 1e-12); their means tie exactly too? no: 0.20's mean is 1e-12 higher
    assert d["candidates"] == [0.10, 0.20] and d["default"] == 0.10
    spec[("A", 0.20, "trend", "counts")] = (good, -0.020, 1, 0)  # an exact tie: the looser level (larger X)
    assert P.d1(pool_table(spec, ref_falls()), "A", "trend", "counts")["default"] == 0.20
    low_mean = [[-0.020] * 6 + [-0.5] + [-0.019] * 4, [-0.020] * 11]
    spec[("A", 0.20, "trend", "counts")] = (good, low_mean, 1, 0)  # the same median, a lower mean
    assert P.d1(pool_table(spec, ref_falls()), "A", "trend", "counts")["default"] == 0.20
    b = {
        ("B", 0.40, "trend", "counts"): (good, -0.02, 1, 0),
        ("B", 0.60, "trend", "counts"): (good, -0.02, 1, 0),
    }
    assert P.d1(pool_table(b, ref_falls()), "B", "trend", "counts")["default"] == 0.40  # looser B: smaller Y


def test_d1_missing_and_bad_tables():
    key = ("A", 0.10, "wait30", "counts")
    t = pool_table({key: (falls(0.25), -0.01, 4, 1)}, ref_falls())
    failed = t.copy()
    failed.loc[30, "status"] = "failed"
    d = P.d1(failed, "A", "wait30", "counts")
    assert d["default"] == P.MISSING and "failed" in d["reason"]
    assert P.d1(t, "A", "trend", "counts")["default"] == P.MISSING
    assert P.d1(t[t["line"] != "R"], "A", "wait30", "counts")["default"] == P.MISSING
    with pytest.raises(ValueError, match="d1: unknown"):
        P.d1(t, "A", "wait45", "counts")
    with pytest.raises(ValueError, match="does not hold exactly the reference runs"):
        P.d1(t[t["run_id"] != "A:0.1:wait30:counts:0:3"], "A", "wait30", "counts")
    dup = pd.concat([t, t[t["line"] == "R"].iloc[:1]], ignore_index=True)
    with pytest.raises(ValueError, match="repeat a"):
        P.d1(dup, "A", "wait30", "counts")


def d1_result(level, c_med=0.0, c_mean=0.0, buybacks=10, restops=1, mode="trend"):
    if isinstance(level, str):
        return {"default": level, "table": [], "mode": mode}
    share = restops / buybacks if buybacks else P.MISSING
    entry = {"level": level, "C_med": c_med, "C_mean": c_mean, "buybacks": buybacks, "restops": restops}
    return {"default": level, "mode": mode, "table": [{**entry, "restop_share": share}]}


def modes(**kw):
    """d1s by mode, with keys rebound_m5, rebound0, rebound_p5, trend, wait30, wait180."""
    names = {"rebound_m5": "rebound-5", "rebound0": "rebound0", "rebound_p5": "rebound+5"}
    out = {m: d1_result(P.NO_DEFAULT, mode=m) for m in P.MODES}
    for k, v in kw.items():
        out[names.get(k, k)] = v
    return out


def test_d2_eligibility_at_a_re_stop_share_of_exactly_25_percent():
    at = modes(trend=d1_result(0.2, -0.05, -0.05, 4, 1), wait30=d1_result(0.3, -0.01, -0.01))
    d = P.d2(at, "A")
    assert d["mode"] == "trend" and d["level"] == 0.2 and d["automatic"][0]["eligible"]
    over = modes(trend=d1_result(0.2, -0.05, -0.05, 4, 2), wait30=d1_result(0.3, -0.01, -0.01))
    d = P.d2(over, "A")
    assert d["mode"] == P.WAIT and d["level"] == 0.3 and d["basis"] == "wait30"
    assert d["case"] == "no automatic mode is eligible or has a default"
    none = modes(trend=d1_result(0.2, -0.05, -0.05, 0, 0), wait30=d1_result(0.3, -0.01, -0.01))
    assert P.d2(none, "A")["mode"] == P.WAIT  # no buy-backs: the share is MISSING, not eligible


def test_d2_the_case_table():
    auto = d1_result(0.2, -0.05, -0.05)
    cheap_wait, dear_wait = d1_result(0.3, -0.06, -0.06), d1_result(0.3, -0.01, -0.01)
    assert P.d2(modes(trend=auto, wait30=dear_wait), "A")["case"] == "automatic no larger than wait-30"
    d = P.d2(modes(trend=auto, wait30=cheap_wait), "A")
    assert (d["mode"], d["level"], d["case"]) == (P.WAIT, 0.3, "wait-30 smaller")
    tie = d1_result(0.3, -0.05 + 1e-12, -0.05)  # C~ within 1e-12, C- equal: no larger, the automatic mode
    assert P.d2(modes(trend=auto, wait30=tie), "A")["mode"] == "trend"
    d = P.d2(modes(trend=auto), "A")
    assert (d["mode"], d["case"]) == ("trend", "wait-30 has NO DEFAULT")
    d = P.d2(modes(), "A")
    assert (d["mode"], d["level"], d["case"]) == (P.NO_DEFAULT, P.NO_DEFAULT, "neither: the owner decides")
    d = P.d2(modes(trend=auto, rebound0=d1_result(P.MISSING)), "A")
    assert d["mode"] == P.MISSING and "rebound0" in d["case"]
    assert (
        P.d2(modes(trend=auto, wait180=d1_result(P.MISSING)), "A")["mode"] == "trend"
    )  # wait-180 decides nothing


def test_d2_the_best_automatic_mode_and_its_ties():
    kw = dict(
        rebound_m5=d1_result(0.1, -0.03, -0.03, 10, 1),
        rebound0=d1_result(0.1, -0.03, -0.03, 10, 1),
        rebound_p5=d1_result(0.1, -0.03, -0.03, 10, 1),
        trend=d1_result(0.1, -0.03, -0.03, 10, 1),
    )
    assert P.d2(modes(**kw), "A")["mode"] == "trend"  # the tie order
    kw["trend"] = d1_result(0.1, -0.03, -0.03, 11, 1)
    assert P.d2(modes(**kw), "A")["mode"] == "rebound+5"  # fewer buy-backs first
    kw["rebound_m5"] = d1_result(0.1, -0.03, -0.031, 50, 1)
    assert P.d2(modes(**kw), "A")["mode"] == "rebound-5"  # a lower mean
    kw["rebound0"] = d1_result(0.1, -0.04, 0.5, 50, 1)
    assert P.d2(modes(**kw), "A")["mode"] == "rebound0"  # a lower median wins whatever the mean


def d2_result(line, mode, level, c_med=0.0, c_mean=0.0):
    return {"line": line, "mode": mode, "level": level, "basis": mode, "C_med": c_med, "C_mean": c_mean}


def test_d3_which_line_comes_first():
    a, b = d2_result("A", "trend", 0.2, -0.05, -0.05), d2_result("B", "wait", 0.4, -0.06, -0.06)
    assert P.d3(a, b) == {"line": "B", "mode": "wait", "level": 0.4}
    assert P.d3(a, d2_result("B", "trend", 0.4, -0.05, -0.05))["line"] == "A"  # a tie goes to A
    assert P.d3(a, d2_result("B", P.NO_DEFAULT, P.NO_DEFAULT))["line"] == "A"
    assert P.d3(d2_result("A", P.NO_DEFAULT, P.NO_DEFAULT), b)["line"] == "B"
    none = d2_result("A", P.NO_DEFAULT, P.NO_DEFAULT)
    assert P.d3(none, {**none, "line": "B"}) == {"line": P.NONE, "mode": P.NONE, "level": P.NONE}
    assert P.d3(d2_result("A", P.MISSING, P.MISSING), b)["line"] == P.MISSING


def test_d6_both_ways():
    def by(sep_a, cnt_a, sep_b, cnt_b):
        return {"separate": {"A": sep_a, "B": sep_b}, "counts": {"A": cnt_a, "B": cnt_b}}

    cheap, dear = d2_result("A", "trend", 0.2, -0.06, -0.06), d2_result("A", "trend", 0.2, -0.05, -0.05)
    none = d2_result("B", P.NO_DEFAULT, P.NO_DEFAULT)
    d = P.d6(by(cheap, dear, none, none))
    assert (d["recommended"], d["in_force"], d["needs_owner_approval"]) == ("separate", "counts", True)
    d = P.d6(by(dear, cheap, none, none))
    assert (d["recommended"], d["in_force"]) == ("counts", "counts")
    d = P.d6(by(dear, dear, none, none))  # equal is not strictly smaller
    assert d["recommended"] == "counts"
    tie_mean = d2_result("A", "trend", 0.2, -0.05 + 1e-13, -0.051)
    assert P.d6(by(tie_mean, dear, none, none))["recommended"] == "separate"  # C~ tie, then C-
    b_dear = d2_result("B", "trend", 0.4, -0.01, -0.01)
    b_cheap = d2_result("B", "trend", 0.4, -0.02, -0.02)
    assert P.d6(by(cheap, dear, b_dear, b_cheap))["recommended"] == "counts"  # every type must agree
    assert P.d6(by(cheap, dear, b_cheap, b_dear))["recommended"] == "separate"
    assert (
        P.d6(by(cheap, none | {"line": "A"}, none, none))["recommended"] == "counts"
    )  # no type under both readings
    assert P.d6(by(cheap, d2_result("A", P.MISSING, P.MISSING), none, none))["recommended"] == P.MISSING


def defaults_of(a_key, b_key=None, first=None):
    def d2_of(key, line):
        if isinstance(key, str):
            return {"line": line, "mode": key, "level": key}
        return {"line": key[0], "mode": key[1], "level": key[2]}

    b_key = P.NO_DEFAULT if b_key is None else b_key
    first = first or (a_key if not isinstance(a_key, str) else P.NONE)
    d3 = (
        {"line": first, "mode": first, "level": first}
        if isinstance(first, str)
        else dict(zip(("line", "mode", "level"), first, strict=True))
    )
    return {"D2": {"A": d2_of(a_key, "A"), "B": d2_of(b_key, "B")}, "D3": d3}


def test_d4_labels():
    head = defaults_of(("A", "trend", 0.2))
    same = defaults_of(("A", "trend", 0.2))
    labels = P.d4(head, {"Binance": same, "2x costs": same, "boom 1": same})
    assert (
        labels["A"]["label"] == P.ROBUST
        and labels["B"]["label"] == P.ROBUST
        and labels["first"]["label"] == P.ROBUST
    )
    moved = defaults_of(("A", "trend", 0.25))
    labels = P.d4(head, {"Binance": moved, "2x costs": same, "boom 1": None})
    assert labels["A"]["label"] == "NOT ROBUST (Binance, boom 1: MISSING)" and labels["A"]["moved"] == [
        "Binance"
    ]
    assert labels["B"]["label"] == "MISSING (boom 1)"  # NO DEFAULT on both sides elsewhere
    labels = P.d4(head, {"Binance": defaults_of(("A", "rebound0", 0.2), ("B", "wait", 0.4))})
    assert (
        labels["B"]["label"] == "NOT ROBUST (Binance)" and labels["first"]["label"] == "NOT ROBUST (Binance)"
    )
    missing_head = defaults_of(P.MISSING, first=P.MISSING)
    assert P.d4(missing_head, {"Binance": same})["A"]["label"] == "MISSING (headline)"
    check_missing = defaults_of(P.MISSING)
    assert P.d4(head, {"Binance": check_missing})["A"]["label"] == "MISSING (Binance)"


def test_d5_the_promise_number():
    runs = pd.DataFrame(
        {
            "run_id": ["a", "b", "c", "x"],
            "line": ["B", "B", "B", "B"],
            "mode": ["trend", "trend", "trend", "wait30"],
            "level": [0.4, 0.4, 0.4, 0.4],
            "reading": ["counts"] * 4,
            "status": ["ok"] * 4,
            "F": [0.2, 0.3, 0.25, 0.9],
        }
    )
    over = [0.01 * k for k in range(1, 21)]
    stops = pd.DataFrame(
        {
            "run_id": ["a"] * 10 + ["b"] * 10 + ["x"],
            "overshoot": over + [0.9],
            "below_d": [False] * 19 + [True, True],
            "sale_vs_d": [0.1] * 19 + [-0.03, -0.5],
        }
    )
    d = P.d5(runs, stops, {"line": "B", "mode": "trend", "basis": "trend", "level": 0.4}, "counts")
    assert d["status"] == "ok" and d["stops"] == 20 and d["Z"] == 0.2
    assert (
        d["Z_p95"] == float(np.percentile(over, 95)) and d["worst_F"] == 0.3 and d["b_worst_below_d"] == -0.03
    )
    none_below = stops.assign(below_d=False)
    assert (
        P.d5(runs, none_below, {"line": "B", "mode": "trend", "basis": "trend", "level": 0.4}, "counts")[
            "b_worst_below_d"
        ]
        == P.NONE
    )
    a_runs = runs.assign(line="A")
    assert (
        P.d5(a_runs, stops, {"line": "A", "mode": "trend", "basis": "trend", "level": 0.4}, "counts")[
            "b_worst_below_d"
        ]
        is None
    )
    no_stops = stops[stops["run_id"] == "x"]
    assert (
        P.d5(runs, no_stops, {"line": "B", "mode": "trend", "basis": "trend", "level": 0.4}, "counts")[
            "status"
        ]
        == P.MISSING
    )
    failed = runs.assign(status=["ok", "failed", "ok", "ok"])
    assert (
        P.d5(failed, stops, {"line": "B", "mode": "trend", "basis": "trend", "level": 0.4}, "counts")[
            "status"
        ]
        == P.MISSING
    )
    assert (
        P.d5(
            runs, stops, {"line": "B", "mode": P.NO_DEFAULT, "basis": None, "level": P.NO_DEFAULT}, "counts"
        )["status"]
        == P.MISSING
    )
    waited = P.d5(runs, stops, {"line": "B", "mode": P.WAIT, "basis": "wait30", "level": 0.4}, "counts")
    assert waited["Z"] == 0.9 and waited["b_worst_below_d"] == -0.5


def test_defaults_and_the_level_table_end_to_end_on_a_hand_table():
    spec = {}
    for mode in P.MODES:
        for level in (0.10, 0.20):
            spec[("A", level, mode, "counts")] = (falls(0.25 if level == 0.10 else 0.3), -0.01 * level, 4, 1)
        spec[("B", 0.40, mode, "counts")] = (falls(0.25), -0.003, 4, 2)
    t = pool_table(spec, ref_falls())
    t = t.assign(
        fired=True,
        b_active=t["line"] == "B",
        b_kept_end=np.where(t["line"] == "B", 0.6, np.nan),
        stops=1,
        buyback_held=0,
        usdc_share=0.1,
        unfilled=False,
        not_bought_back=False,
        fees_pct_per_year_tool=0.01,
        fees_pct_per_year_brake=0.02,
    )
    d = P.defaults(t, "counts")
    assert d["D2"]["A"]["mode"] == "trend" and d["D2"]["A"]["level"] == 0.10  # every mode ties: the tie order
    assert d["D2"]["B"]["mode"] == P.WAIT  # B's re-stop share 50%: no automatic mode is eligible
    assert d["D3"] == {"line": "B", "mode": P.WAIT, "level": 0.40}  # B's C~ -0.003 is below A's -0.001
    stops = pd.DataFrame(
        {
            "run_id": t["run_id"],
            "overshoot": 0.01,
            "overshoot_before": 0.005,
            "stop_ts": pd.Timestamp("2018-01-01", tz="UTC"),
            "missed_rebound": 0.1,
            "below_d": False,
        }
    )
    table = P.level_table(t, stops)
    assert len(table) == 1 + len(spec)
    ref = next(e for e in table if e["line"] == "R")
    assert ref["level"] is None and ref["runs"] == 22 and ref["Q"] == 0.375
    row = next(e for e in table if e["line"] == "A" and e["level"] == 0.1 and e["mode"] == "trend")
    assert (
        row["fire_rate"] == 1.0
        and row["Q"] == 0.25
        and row["restop_share"] == 0.25
        and row["distinct_sale_dates"] == 1
    )
    assert row["Q_mix"] == {"0.3/0.5": 0.25, "0.7/0.75": 0.25} and row["overshoot_p95"] == 0.01
    assert row["fire_rate_mix"] == {"0.3/0.5": 1.0, "0.7/0.75": 1.0} and row["C_med_mix"]["0.3/0.5"] == -0.001
    assert (row["b_active_runs"], row["b_kept_end_median"]) == (0, None)
    b_row = next(e for e in table if e["line"] == "B" and e["mode"] == "trend")
    assert (b_row["b_active_runs"], b_row["b_kept_end_median"]) == (22, 0.6)
    failed = t.copy()
    failed.loc[0, "status"] = "failed"
    assert next(e for e in P.level_table(failed, stops) if e["line"] == "R")["failed"] == 1
    failed.loc[failed["line"] == "R", "status"] = "failed"
    ref = next(e for e in P.level_table(failed, stops) if e["line"] == "R")
    assert ref == {"line": "R", "level": None, "mode": "none", "reading": "none", "runs": 22, "failed": 22}
