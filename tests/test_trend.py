"""trend-steady (``lab/runner/trend.py``, scouting only): the weekly trend rule, the one executor, the stop-loss
variant and the luck-control helpers of ``research/trend-steady/PLAN.md`` (sections 4-17; the section 17 test list).

Synthetic data and hand-built paths only: no catalog bar is read. The accounting is checked against independent
books in coin units and USDC cash (``vector_book``, the ``test_portfolio.unit_book`` computation with the target
vector of each order, and ``stop_book``, a one-pass book that also decides the stops), never against the weight
recursion the engine uses.
"""

from __future__ import annotations

import math
from functools import partial

import numpy as np
import pandas as pd
import pytest
from hypothesis import example, given
from hypothesis import strategies as st
from test_portfolio import ALL_COLUMNS, fill_bars_of, random_panel, tamper_from, unit_book

from lab.data.synthetic import synthetic_market
from lab.runner import portfolio as pf
from lab.runner import steady as sd
from lab.runner import trend as tr
from lab.runner.interface import validate_result
from lab.runner.reference import Costs
from lab.search.report import gates, overfitting_report
from lab.search.space import Param
from lab.search.study import SearchConfig, load_trial_returns, run_study
from lab.search.walkforward import walk_forward_optimize
from lab.validation import montecarlo as mc
from lab.validation import stats
from lab.validation.splits import walk_forward

LIMITS = {"min_cash": 0.20, "max_coin": 0.60}  # Steady's limits as read (test_portfolio pins the real file)
TIGHT = {"min_cash": 0.20, "max_coin": 0.40}  # a tighter coin cap, so drift breaches it sooner
COSTS = Costs()
COST_MODELS = (
    Costs(),
    Costs().stressed(),
    Costs(pool_fee_bps=30.0, aggregator_fee_bps=10.0, gas_usd_per_trade=25.0),
)
UP, DOWN = 0.5, -0.5  # exactly representable m: L = 2, closes 100 -> 300 and 300 -> 100
JUST_BELOW = math.nextafter(0.5, 0.0)
DAY = pd.Timedelta(days=1)

# ------------------------------------------------------------------------------------------------ helpers


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


def panel_on(index, btc, eth, btc_open=None, eth_open=None) -> pd.DataFrame:
    return pf.make_panel(
        {"BTC": bars_on(index, btc, btc_open), "ETH": bars_on(index, eth, eth_open)}, snapshot_id="hand"
    )


def days(n: int, start: str = "2017-01-02") -> pd.DatetimeIndex:
    return pd.date_range(start, periods=n, freq="D", tz="UTC", name="ts")


def path(n: int, base: float = 100.0, **at) -> list[float]:
    """``n`` closes at ``base``, with ``r<row>=price`` set from that row on (``r203=300``)."""
    out = [base] * n
    for key, price in sorted(((int(k[1:]), v) for k, v in at.items())):
        out[key:] = [price] * (n - key)
    return out


def states_of(panel, lookback=2, buffer=0.1, **kw) -> np.ndarray:
    return tr.trend_states(panel, lookback, buffer, **kw).z


def run(params, panel, limits=LIMITS, costs=COSTS, **kw) -> pd.DataFrame:
    return tr.trend_backtest(params, panel, limits=limits, costs=costs, **kw)


def P(lookback=2, buffer=0.1, share=0.5, stop=None) -> dict:
    p = {"lookback": lookback, "buffer": buffer, "crypto_share": share}
    if stop is not None:
        p["stop"] = stop
    return p


def breached(w, limits) -> bool:
    """The Steady limit test, written out (coins over 1 - min_cash or a coin over max_coin, beyond 1e-9)."""
    return w[0] + w[1] > 1.0 - limits["min_cash"] + 1e-9 or max(w) > limits["max_coin"] + 1e-9


def vector_book(panel, result, costs):
    """``test_portfolio.unit_book`` with the target vector of each order: at a fill bar t the target is the vector
    the rule put in force at the decision close t - 1 (``attrs["targets"]``). Same arithmetic as unit_book."""
    n = len(panel)
    assets = pf.ASSETS
    o = {a: panel[(a, "open")].to_numpy(dtype=float) for a in assets}
    c = {a: panel[(a, "close")].to_numpy(dtype=float) for a in assets}
    log = result.attrs["fills"]
    traded = {(int(b), a) for b, a in zip(log["bar"], log["asset"], strict=True)}
    fills = {int(t) for t in fill_bars_of(result)}
    vectors = result.attrs["targets"]
    units = dict.fromkeys(assets, 0.0)
    cash = costs.capital_usd
    value = np.full(n, np.nan)
    value[0] = cash
    out = {col: np.zeros(n) for col in ALL_COLUMNS}
    legs, v_open = [], []
    for t in range(1, n):
        if t in fills:
            target = dict(zip(assets, vectors[t - 1].tolist(), strict=True))
            vo = cash + sum(units[a] * o[a][t] for a in assets)
            usd = {a: abs(target[a] * vo - units[a] * o[a][t]) for a in assets}
            paid = 0.0
            for a in assets:
                if (t, a) in traded:
                    leg_cost = usd[a] * costs.rate(usd[a]) + costs.gas_usd_per_trade
                    paid += leg_cost
                    legs.append({"bar": t, "asset": a, "usd": usd[a], "cost": leg_cost, "after": target[a]})
            out["turnover"][t] = sum(usd[a] for a in assets if (t, a) in traded) / vo
            out["cost"][t] = paid / vo
            v_open.append(vo)
            after = vo - paid
            units = {a: target[a] * after / o[a][t] for a in assets}
            cash = (1.0 - sum(target.values())) * after
        value[t] = cash + sum(units[a] * c[a][t] for a in assets)
        out["ret"][t] = value[t] / value[t - 1] - 1.0
        for a in assets:
            out[f"w_{a}"][t] = units[a] * c[a][t] / value[t]
        out["position"][t] = out["w_BTC"][t] + out["w_ETH"][t]
    return out, legs, v_open, value


def stop_book(panel, z, share, phi, limits, costs, f=0.5):
    """An independent one-pass run of the stop-loss variant, in coin units and USDC cash: at each close, value the
    book, update the high from the reference close, decide a stop (f <= -phi locks both coins and restarts the high
    at the next close), unlock a coin on an out -> in turn after the latest stop, order when the in-force vector
    changes or a limit is breached, and fill at the next open with each leg's rate and gas. Returns the per-row
    returns, weights, the stop events and the locks."""
    n = len(panel)
    assets = pf.ASSETS
    o = {a: panel[(a, "open")].to_numpy(dtype=float) for a in assets}
    c = {a: panel[(a, "close")].to_numpy(dtype=float) for a in assets}
    w_in = (share * f, share * (1.0 - f))
    units, cash, capital = [0.0, 0.0], costs.capital_usd, costs.capital_usd
    ret, weights = np.zeros(n), np.zeros((n, 2))
    locks = np.zeros((n, 2), dtype=np.int8)
    locked, latest, ref, high = [0, 0], -1, 0, None
    events, previous, order, value = [], (0.0, 0.0), None, capital
    for t in range(n):
        if order is not None:
            vo = cash + sum(units[a] * o[x][t] for a, x in enumerate(assets))
            paid = 0.0
            for a, x in enumerate(assets):
                usd = abs(order[a] * vo - units[a] * o[x][t])
                if usd > 0.0:
                    paid += usd * costs.rate(usd) + costs.gas_usd_per_trade
            after = vo - paid
            units = [order[a] * after / o[x][t] for a, x in enumerate(assets)]
            cash = (1.0 - sum(order)) * after
        now = cash + sum(units[a] * c[x][t] for a, x in enumerate(assets))
        if t:
            ret[t] = now / value - 1.0
        value = now
        weights[t] = [units[a] * c[x][t] / now for a, x in enumerate(assets)]
        for a in range(2):
            before = z[t - 1, a] if t else 0
            if locked[a] and t > latest and before == 0 and z[t, a] == 1:
                locked[a] = 0
        if t >= ref:
            v = now / capital
            high = v if high is None else max(high, v)
            if v / high - 1.0 <= -phi:
                events.append(t)
                locked, latest, ref, high = [1, 1], t, t + 1, None
        locks[t] = locked
        vector = tuple(w_in[a] if z[t, a] and not locked[a] else 0.0 for a in range(2))
        order = vector if vector != previous or breached(weights[t], limits) else None
        previous = vector
    return ret, weights, events, locks


def same_fills(a, b, cut) -> None:
    """The fill logs of two runs agree on every leg up to bar ``cut``, value for value. (Compared by value: pandas 3
    infers ``str`` for the asset and side columns of a non-empty log and keeps ``object`` for an empty one.)"""
    fa, fb = a.attrs["fills"], b.attrs["fills"]
    fa, fb = fa[fa["bar"] <= cut], fb[fb["bar"] <= cut]
    assert list(fa.columns) == list(fb.columns) and len(fa) == len(fb)
    for col in fa.columns:
        assert list(fa[col]) == list(fb[col]), col


def windows_of(index) -> list:
    return tr.fold_windows(index)


def fold_runs(panel, params_per_fold, windows, limits=LIMITS, costs=COSTS):
    """S's per-fold runs in H0 (each from row 0 to the fold's last close)."""
    return [
        run(p, tr.h0_slice(panel, w), limits=limits, costs=costs)
        for p, w in zip(params_per_fold, windows, strict=True)
    ]


def kept(result, window) -> pd.Series:
    return sd.kept_returns(result, window.t0)


def stitched(runs, windows) -> pd.Series:
    return pd.concat([kept(r, w) for r, w in zip(runs, windows, strict=True)])


@st.composite
def trend_panels(draw, min_size: int = 205, max_size: int = 330) -> pd.DataFrame:
    n = draw(st.integers(min_size, max_size))
    seed = draw(st.integers(0, 2**32 - 1))
    vols = tuple(draw(st.sampled_from([0.01, 0.04, 0.08])) for _ in pf.ASSETS)
    gaps = tuple(draw(st.sampled_from([0.0, 0.005, 0.03])) for _ in pf.ASSETS)
    return random_panel(n, seed, vols, gaps)


@st.composite
def trend_cases(draw):
    """(panel, params, limits): a short lookback so that the states switch inside the drawn panel."""
    panel = draw(trend_panels())
    limits = draw(st.sampled_from([LIMITS, TIGHT]))
    top = 0.76 if limits is TIGHT else 0.78
    share = draw(st.one_of(st.sampled_from([0.3, 0.5, 0.6, top]), st.floats(0.05, top)))
    params = P(draw(st.integers(1, 40)), draw(st.sampled_from([0.0, 0.005, 0.02, 0.1])), share)
    return panel, params, limits


# ------------------------------------------------------------------------------------------------ pinned values


def test_the_pinned_values_are_the_plan_s():
    assert tr.SPECS == (
        Param("lookback", "int", 20, 200, log=True),
        Param("buffer", "float", 0.005, 0.10, log=True),
        Param("crypto_share", "float", 0.30, 0.60),
    )
    assert tr.PARAM_NAMES == ("lookback", "buffer", "crypto_share")
    assert (tr.HEADROOM, tr.R0, tr.S_SHARE, tr.F_SPLIT, tr.WEEKDAY, tr.WARMUP) == (
        0.02,
        199,
        0.50,
        0.50,
        0,
        2190,
    )
    assert tr.ALLOWED_S == (0.30, 0.40, 0.50, 0.60)
    assert tr.STOP_LEVELS == (0.20, 0.30, 0.40)
    assert (tr.RUN_BUDGET_MINUTES, tr.CONTROLS_BUDGET_MINUTES) == (60, 120)
    assert (tr.LEAD_GUARD, tr.FIRST_ACTIVE_ROW) == (52, 204)
    assert tr.TIMING_KEYS == ("study", "run", "stop_run", "bootstrap")
    assert tr.E5A_ITEMS == (
        "E1", "E2", "E3", "E4", "E6", "E7", "P", "G1", "G2", "G3", "G4", "G5(a)", "G6", "G7", "G8-excess",
    )  # fmt: skip


# ------------------------------------------------------------------------------------------------ the grid


def test_the_rebuilt_train_grid_reproduces_appendix_b():
    """Price-free, from DATA.md's counts: the fold table of section 7, row 199, the first check, the Mondays, W = 260
    with 52 per fold, the weekly segments of section 11A and the 2-day row of 2018-01-13."""
    idx = tr.train_grid()
    assert len(idx) == 2190 and idx.unit == "us" and str(idx.tz) == "UTC" and idx.name == "ts"
    assert (idx[0], idx[-1]) == (pd.Timestamp("2017-01-02", tz="UTC"), pd.Timestamp("2023-01-01", tz="UTC"))
    assert pd.Timestamp("2018-01-13", tz="UTC") not in idx
    gap = int(np.flatnonzero(np.diff(idx.asi8) != tr.DAY_US)[0])
    assert (idx[gap], idx[gap + 1]) == (
        pd.Timestamp("2018-01-12", tz="UTC"),
        pd.Timestamp("2018-01-14", tz="UTC"),
    )
    assert idx[199] == pd.Timestamp("2017-07-20", tz="UTC")
    mondays = tr.check_closes(idx, 0, tr.R0)
    assert mondays[0] == 203 and idx[203] == pd.Timestamp("2017-07-24", tz="UTC")
    assert len(tr.check_closes(idx, 0, 0)) == 313
    assert (
        tr.rolling_count(idx[tr.check_closes(idx, 0, 0)], idx).max() == 5
    )  # at most 5 Mondays in any 30 days
    windows = tr.fold_windows(idx)
    table = [(str(w.t0.date()), str(w.last.date())) for w in windows]
    assert table == [
        ("2018-01-02", "2019-01-02"),
        ("2019-01-03", "2020-01-02"),
        ("2020-01-03", "2021-01-01"),
        ("2021-01-02", "2022-01-01"),
        ("2022-01-02", "2023-01-01"),
    ]
    assert all(w.first_h120 == idx[0] for w in windows)  # H0: every slice starts at row 0
    folds = walk_forward(2190, 365, 365, expanding=True)
    assert [(f.train[0], f.train[-1], f.test[0], f.test[-1]) for f in folds] == [
        (0, 364, 365, 729), (0, 729, 730, 1094), (0, 1094, 1095, 1459), (0, 1459, 1460, 1824), (0, 1824, 1825, 2189),
    ]  # fmt: skip
    kept_rows = [len(idx[(idx > w.t0) & (idx <= w.last)]) for w in windows]
    assert kept_rows == [364] * 5
    z = [np.zeros((idx.get_loc(w.last) + 1, 2), dtype=np.int8) for w in windows]
    schedule = tr.stitched_schedule(idx, windows, z, [0.5] * 5)
    assert len(schedule.checks) == 260 and np.bincount(schedule.fold).tolist() == [52] * 5
    c = schedule.checks
    assert idx[c[0]] == pd.Timestamp("2018-01-08", tz="UTC") and idx[c[-1]] == pd.Timestamp(
        "2022-12-26", tz="UTC"
    )
    sizes = np.diff(np.append(c, len(idx) - 1))
    assert sizes[0] == 6 and sizes[-1] == 6 and (sizes[1:-1] == 7).all()  # segments 0 and 259 have 6 closes
    assert c[0] - idx.get_loc(windows[0].t0) == 6  # 2018-01-02 .. 2018-01-07 come before c_0
    assert [idx[c[52 * i]] - windows[i].t0 for i in range(5)] == [
        pd.Timedelta(days=d) for d in (6, 4, 3, 2, 1)
    ]
    binance = pd.date_range("2017-08-18", "2023-01-01", freq="D", tz="UTC", name="ts")
    assert len(binance) == 1963 and binance[199] == pd.Timestamp("2018-03-05", tz="UTC")
    assert binance[199].day_of_week == 0
    validate = pd.date_range("2017-01-02", "2024-07-01", freq="D", tz="UTC", name="ts").drop(
        pd.Timestamp("2018-01-13", tz="UTC")
    )
    assert len(validate) == 2737 and validate[2190] == pd.Timestamp("2023-01-02", tz="UTC")
    looks = tr.check_closes(validate[: len(validate) - 1], 0, 2190)  # checks whose orders fill by 2024-07-01
    assert len(looks) == 78 and validate[looks[-1]] == pd.Timestamp("2024-06-24", tz="UTC")
    assert [len(tr.guarded_offsets(w)) for w in (260, 208, 78)] == [207, 155, 25]


# ------------------------------------------------------------------------------------------------ the signal


def test_sma_and_distance_by_hand():
    close = [1.0, 2.0, 3.0, 4.0, 6.0]
    np.testing.assert_array_equal(tr.sma(close, 3), [np.nan, np.nan, 2.0, 3.0, 13.0 / 3.0])
    np.testing.assert_array_equal(
        tr.sma_distance(close, 3), [np.nan, np.nan, 0.5, 4.0 / 3.0 - 1.0, 6.0 / (13 / 3) - 1]
    )
    np.testing.assert_array_equal(tr.sma(close, 1), close)
    np.testing.assert_array_equal(tr.sma_distance(close, 1), [0.0] * 5)
    np.testing.assert_array_equal(tr.sma(close, 3, rows=[4, 1]), [np.nan, np.nan, np.nan, np.nan, 13.0 / 3.0])
    assert np.isnan(tr.sma(close, 6)).all()
    # the per-window sum is exactly rounded (math.fsum), so the order of the closes never matters
    big = [1e16, 1.0, 1.0, 1.0]
    assert tr.sma([*big, 2.0], 4)[3] == math.fsum(big) / 4 == (1e16 + 4.0) / 4
    running = 0.0
    for x in big:
        running += x
    assert running / 4 == 1e16 / 4  # a running sum loses the three 1.0s
    for bad, match in (
        (([1.0, 0.0, 1.0], 2), "finite prices > 0"),
        (([[1.0, 2.0]], 1), "1-D"),
        (([1.0, np.nan], 1), "finite"),
        (([1.0, 2.0], 0), "lookback must be an integer >= 1"),
        (([1.0, 2.0], 1.5), "lookback must be an integer"),
    ):
        with pytest.raises(ValueError, match=match):
            tr.sma(*bad)
    with pytest.raises(ValueError, match="outside the 2 closes"):
        tr.sma([1.0, 2.0], 1, rows=[2])


@given(n=st.integers(5, 60), lookback=st.integers(1, 12), data=st.data())
def test_the_average_reads_exactly_its_window(n, lookback, data):
    """Tamper the future and touch the present on SMA and m: changing close j moves SMA(t) and m(t) exactly when j
    is in t - L + 1 .. t; the rows before j never move."""
    rng = np.random.default_rng(data.draw(st.integers(0, 2**16)))
    close = np.exp(rng.normal(0.0, 0.05, n).cumsum()) * 100.0
    j = data.draw(st.integers(0, n - 1))
    other = close.copy()
    other[j] *= 0.7
    a, b = tr.sma(close, lookback), tr.sma(other, lookback)
    ma, mb = tr.sma_distance(close, lookback), tr.sma_distance(other, lookback)
    for t in range(n):
        inside = t >= lookback - 1 and t - lookback + 1 <= j <= t
        if t < lookback - 1:
            assert np.isnan(a[t]) and np.isnan(b[t]) and np.isnan(ma[t])
        elif inside:
            assert a[t] != b[t] and (lookback == 1 or ma[t] != mb[t])
        else:
            assert a[t] == b[t] and (t < j or ma[t] == mb[t])
    np.testing.assert_array_equal(ma[:j], mb[:j])


def test_check_closes_are_the_weekday_closes_from_the_start_row():
    idx = days(30)  # 2017-01-02 is a Monday
    np.testing.assert_array_equal(tr.check_closes(idx, 0, 0), [0, 7, 14, 21, 28])
    np.testing.assert_array_equal(tr.check_closes(idx, 0, 1), [7, 14, 21, 28])
    np.testing.assert_array_equal(tr.check_closes(idx, 0, 7), [7, 14, 21, 28])
    np.testing.assert_array_equal(tr.check_closes(idx, 2, 0), [2, 9, 16, 23])
    np.testing.assert_array_equal(tr.check_closes(idx, None, 25), [25, 26, 27, 28, 29])
    gappy = idx.drop(idx[14])  # a missing Monday is skipped, with no substitute
    np.testing.assert_array_equal(tr.check_closes(gappy, 0, 0), [0, 7, 20, 27])
    assert tr.check_closes(idx, 0, 0).dtype == np.int64
    for bad in (7, -1, True, 1.5, "0"):
        with pytest.raises(ValueError, match="weekday must be an integer in 0..6"):
            tr.check_closes(idx, bad, 0)
    with pytest.raises(ValueError, match="start_row must be an integer >= 0"):
        tr.check_closes(idx, 0, -1)


def test_activation_is_row_199_or_l_minus_1():
    assert [tr.activation(L) for L in (1, 2, 20, 200, 201, 240)] == [199, 199, 199, 199, 200, 239]
    idx = tr.train_grid()
    panel = tr.random_walk_panel(0)
    for lookback, first in ((2, 203), (20, 203), (200, 203), (201, 203), (240, 245)):
        st_ = tr.trend_states(panel, lookback, 0.01)
        assert st_.activation == tr.activation(lookback) and st_.checks[0] == first
        assert idx[first].day_of_week == 0
        assert (st_.z[:first] == 0).all()  # start out: all cash before the first check
        assert np.isnan(st_.m[:first]).all() and np.isfinite(st_.m[st_.checks]).all()
    # row 199 itself is a check when it is a Monday; the Monday before it (row 192) is not
    idx2 = days(230, "2020-01-03")
    assert idx2[199].day_of_week == 0 and idx2[192].day_of_week == 0
    btc = path(230, r191=100.0, r192=300.0, r193=100.0, r198=100.0, r199=300.0)
    z = states_of(panel_on(idx2, btc, [100.0] * 230))
    assert (z[:199, 0] == 0).all() and (z[199:, 0] == 1).all()
    # L > 200: activation L - 1 = 239, the first Monday on or after it
    idx3 = days(260, "2020-01-05")
    assert idx3[239].day_of_week == 0
    btc = path(260, r232=120.0, r239=300.0)
    st3 = tr.trend_states(panel_on(idx3, btc, [100.0] * 260), 240, 0.1)
    assert st3.checks[0] == 239 and (st3.z[:239, 0] == 0).all() and st3.z[239, 0] == 1


def test_states_switch_exactly_across_the_buffer():
    """L = 2 gives exactly representable m: 100 -> 300 is m = +0.5 and 300 -> 100 is m = -0.5. Both inequalities are
    strict, so m exactly at +delta or -delta changes nothing; one ulp of buffer less does."""
    idx = days(230)
    assert [idx[r].day_of_week for r in (203, 210, 217)] == [0, 0, 0]
    flat = [100.0] * 230
    up = path(230, r203=300.0, r209=300.0, r210=100.0)
    m = tr.sma_distance(up, 2)
    assert (m[203], m[210]) == (UP, DOWN)
    assert (states_of(panel_on(idx, up, flat), buffer=0.5)[:, 0] == 0).all()  # m = +0.5 is not above 0.5
    z = states_of(panel_on(idx, up, flat), buffer=JUST_BELOW)
    assert (z[:203, 0] == 0).all() and (z[203:210, 0] == 1).all() and (z[210:, 0] == 0).all()
    assert (z[:, 1] == 0).all()  # ETH flat: m = 0, never in
    # in with m = 0.6 at row 203; m = -0.5 exactly at 210 keeps it in; -0.54 at 217 takes it out
    hold = path(230, r203=400.0, r209=300.0, r210=100.0, r216=300.0, r217=90.0)
    z = states_of(panel_on(idx, hold, flat), buffer=0.5)
    assert (z[203:217, 0] == 1).all() and (z[217:, 0] == 0).all() and (z[:203, 0] == 0).all()
    # between check closes nothing changes, however far the price moves
    jumpy = path(230, r204=1000.0, r205=100.0, r211=10.0, r212=100.0)
    assert (states_of(panel_on(idx, jumpy, flat), buffer=0.0) == 0).all()


def test_a_missing_monday_is_skipped():
    full = days(230)
    idx = full.drop(full[210])
    btc = path(230, r209=300.0, r210=900.0, r211=300.0, r216=300.0, r217=900.0)
    btc = [p for r, p in enumerate(btc) if r != 210]
    z = states_of(panel_on(idx, btc, [100.0] * 229), buffer=0.1)
    tuesday = idx.get_loc(full[211])  # 900 -> 300 on the Tuesday after the missing Monday: m = -0.5, no check
    assert z[tuesday, 0] == 0 and z[tuesday - 1, 0] == 0
    monday = idx.get_loc(full[217])
    assert z[monday, 0] == 1 and z[monday - 1, 0] == 0  # the next Monday checks


def test_states_are_point_in_time_and_the_stream_equals_the_batch():
    panel = tr.random_walk_panel(4)
    batch = tr.trend_states(panel, 50, 0.02)
    stream = tr.TrendStream(50, 0.02)
    closes = (panel[(a, "close")] for a in pf.ASSETS)
    got = [stream.update(ts, b, e) for ts, b, e in zip(panel.index, *closes, strict=True)]
    np.testing.assert_array_equal(np.asarray(got, dtype=np.int8), batch.z)
    assert batch.z.sum() > 0 and (np.diff(batch.z[:, 0]) != 0).sum() >= 4
    with pytest.raises(ValueError, match="tz-aware"):
        tr.TrendStream(5, 0.1).update(pd.Timestamp("2020-01-01"), 1.0, 1.0)
    s = tr.TrendStream(5, 0.1)
    s.update(pd.Timestamp("2020-01-02", tz="UTC"), 1.0, 1.0)
    with pytest.raises(ValueError, match="strictly increasing"):
        s.update(pd.Timestamp("2020-01-02", tz="UTC"), 1.0, 1.0)
    with pytest.raises(ValueError, match="close must be in"):
        s.update(pd.Timestamp("2020-01-03", tz="UTC"), 0.0, 1.0)
    with pytest.raises(ValueError, match="start must be 'out'"):
        tr.TrendStream(5, 0.1, start="up")


@given(
    panel=trend_panels(),
    lookback=st.integers(1, 60),
    buffer=st.sampled_from([0.0, 0.005, 0.02, 0.1]),
    weekday=st.sampled_from([0, 3, None]),
    start=st.sampled_from(["out", "in"]),
)
def test_live_stream_equals_trend_states_on_every_bar(panel, lookback, buffer, weekday, start):
    """Live/batch parity: the state machine fed one close at a time gives trend_states' states on every bar, bit
    for bit (the same per-window fsum and the same strict comparisons)."""
    batch = tr.trend_states(panel, lookback, buffer, weekday=weekday, start=start)
    stream = tr.TrendStream(lookback, buffer, weekday=weekday, start=start)
    closes = [panel[(a, "close")].to_numpy().tolist() for a in pf.ASSETS]
    for t, ts in enumerate(panel.index):
        assert stream.update(ts, closes[0][t], closes[1][t]) == tuple(batch.z[t].tolist())


def tampered_closes(panel, cut, seed):
    return tamper_from(panel, cut, seed)


@given(case=trend_cases(), data=st.data())
@example(case=(random_panel(260, 3, (0.04, 0.05)), P(10, 0.02, 0.5), LIMITS), data=None)
def test_no_look_ahead_in_the_states_the_targets_or_the_returns(case, data):
    """Tamper every field of both assets from ``cut`` on (except the opens of bar cut, the fill prices of the order
    at close cut - 1): the states, m, the targets, every result row, the orders and fills before cut are unchanged,
    and so is the fill on bar cut. The ``@example``s cut at R0 and at a check close."""
    panel, params, limits = case
    cuts = [tr.R0, 203] if data is None else [data.draw(st.integers(1, len(panel) - 1))]
    for cut in cuts:
        seed = 7 if data is None else data.draw(st.integers(0, 2**16))
        other = tampered_closes(panel, cut, seed)
        a, b = run(params, panel, limits), run(params, other, limits)
        sa = tr.trend_states(panel, params["lookback"], params["buffer"])
        sb = tr.trend_states(other, params["lookback"], params["buffer"])
        np.testing.assert_array_equal(sa.z[:cut], sb.z[:cut])
        np.testing.assert_array_equal(sa.m[:cut], sb.m[:cut])
        np.testing.assert_array_equal(a.attrs["targets"][:cut], b.attrs["targets"][:cut])
        np.testing.assert_array_equal(a[ALL_COLUMNS].to_numpy()[:cut], b[ALL_COLUMNS].to_numpy()[:cut])
        assert (a["turnover"].iloc[cut], a["cost"].iloc[cut]) == (
            b["turnover"].iloc[cut],
            b["cost"].iloc[cut],
        )
        same_fills(a, b, cut)
        oa, ob = a.attrs["orders"], b.attrs["orders"]
        np.testing.assert_array_equal(oa[oa < cut], ob[ob < cut])
        np.testing.assert_array_equal(a.attrs["reasons"][oa < cut], b.attrs["reasons"][ob < cut])
        for col in ("BTC", "ETH"):
            m_a = tr.sma_distance(panel[(col, "close")], params["lookback"])
            m_b = tr.sma_distance(other[(col, "close")], params["lookback"])
            np.testing.assert_array_equal(m_a[:cut], m_b[:cut])


def test_touching_the_present_moves_the_average_and_can_flip_the_state_at_t_never_at_t_minus_1():
    idx = days(230)
    btc = path(230, r203=300.0)
    flat = [100.0] * 230
    z = states_of(panel_on(idx, btc, flat), buffer=0.1)
    assert z[203, 0] == 1 and z[202, 0] == 0
    lowered = list(btc)
    lowered[203] = 100.0  # the present close only
    zl = states_of(panel_on(idx, lowered, flat), buffer=0.1)
    assert zl[203, 0] == 0 and (zl[:203] == z[:203]).all()
    assert tr.sma(lowered, 20)[203] != tr.sma(btc, 20)[203]
    assert tr.sma_distance(lowered, 20)[203] != tr.sma_distance(btc, 20)[203]
    np.testing.assert_array_equal(tr.sma(lowered, 20)[:203], tr.sma(btc, 20)[:203])


# ------------------------------------------------------------------------------------------------ the executor


def test_one_coin_switching_re_cuts_the_other():
    """Both coins in at row 203; BTC drifts up; ETH turns out at 210. The order is the full vector (0.25, 0): the
    fill at the open of 211 sells ETH and re-cuts BTC back to 0.25."""
    idx = days(230)
    btc = path(230, r203=300.0, r205=330.0)
    eth = path(230, r203=300.0, r210=100.0)
    res = run(P(2, 0.1, 0.5), panel_on(idx, btc, eth))
    orders = res.attrs["orders"].tolist()
    assert orders == [203, 210]
    assert list(res.attrs["reasons"]) == ["switch", "switch"]
    assert res.attrs["switches"].tolist() == [2, 1]  # in-force coin changes: both in, then ETH out
    np.testing.assert_array_equal(res.attrs["order_targets"], [[0.25, 0.25], [0.25, 0.0]])
    fills = res.attrs["fills"]
    legs = fills[fills["bar"] == 211]
    assert list(legs["asset"]) == ["BTC", "ETH"] and list(legs["side"]) == ["sell", "sell"]
    btc_leg = legs[legs["asset"] == "BTC"].iloc[0]
    assert btc_leg["weight_after"] == 0.25 and btc_leg["weight_before"] > 0.25
    assert res["w_BTC"].iloc[211] == 0.25 and res["w_ETH"].iloc[211] == 0.0  # flat bar after the fill
    validate_result(res, panel_on(idx, btc, eth))


def test_a_breach_between_checks_is_fixed_at_the_next_open_and_a_switch_with_a_breach_is_one_order():
    """s = 0.6 under a 40% coin cap: BTC doubles on Wednesday 206, its weight passes 0.4 at that close, and the
    vector in force is ordered (a limit fix) for the open of 207. On Monday 217 ETH turns out while BTC breaches the
    cap again: one order, the switch."""
    idx = days(230)
    btc = path(230, r203=300.0, r206=600.0, r216=600.0, r217=1500.0)
    eth = path(230, r203=300.0, r216=300.0, r217=100.0)
    panel = panel_on(idx, btc, eth)
    res = run(P(2, 0.1, 0.6), panel, limits=TIGHT)
    w = res[["w_BTC", "w_ETH"]].to_numpy()
    assert breached(w[206], TIGHT) and not breached(w[205], TIGHT)
    assert res.attrs["orders"].tolist() == [203, 206, 217]
    assert list(res.attrs["reasons"]) == ["switch", "limit", "switch"]
    np.testing.assert_array_equal(res.attrs["order_targets"], [[0.3, 0.3], [0.3, 0.3], [0.3, 0.0]])
    assert w[207].tolist() == [0.3, 0.3]  # the fill re-cut the book to the targets (flat bar 207)
    assert breached(w[217], TIGHT) and w[218].tolist() == [0.3, 0.0]
    # the same path at the limits as read: no breach, so no limit fix
    assert run(P(2, 0.1, 0.6), panel).attrs["orders"].tolist() == [203, 217]


@given(
    panel=st.builds(random_panel, st.integers(20, 120), st.integers(0, 2**32 - 1), st.just((0.04, 0.08))),
    share=st.one_of(st.sampled_from([0.3, 0.6, 0.76]), st.floats(0.05, 0.76)),
    limits=st.sampled_from([LIMITS, TIGHT]),
    costs=st.sampled_from(COST_MODELS[:2]),
)
def test_always_in_targets_equal_rebalance_with_band_1_every_1_bit_for_bit(panel, share, limits, costs):
    """Identity: the executor fed (s/2, s/2) at every close is ``portfolio.rebalance`` with band 1.0 (never fires),
    every 1, the limits and h: it buys at close 0, then makes limit fixes only."""
    n = len(panel)
    targets = np.tile(tr.share_targets(share), (n, 1))
    a = tr.run_states(panel, targets, limits=limits, costs=costs)
    b = pf.rebalance(
        {
            "w_btc": share / 2,
            "w_eth": share / 2,
            "band": 1.0,
            "every": 1,
            "min_cash": limits["min_cash"],
            "max_coin": limits["max_coin"],
            "headroom": tr.HEADROOM,
        },
        panel,
        costs,
    )
    pd.testing.assert_frame_equal(a[ALL_COLUMNS], b[ALL_COLUMNS])
    np.testing.assert_array_equal(a.attrs["orders"], b.attrs["orders"])
    np.testing.assert_array_equal(a.attrs["trade_returns"], b.attrs["trade_returns"])
    same_fills(a, b, n)
    assert list(a.attrs["reasons"]) == ["re-cut"] + ["limit"] * (len(a.attrs["orders"]) - 1)


@given(case=trend_cases(), weekday=st.sampled_from([0, 4, None]), costs=st.sampled_from(COST_MODELS[:2]))
def test_the_executor_fed_one_run_s_targets_is_that_run_s_own_order_rule(case, weekday, costs):
    """Identity (M11): ``trend_backtest`` equals section 4's order rule written out on ``portfolio._simulate``: (1) at
    a check close where a state changed, order the new targets; (2) otherwise, on a limit breach at the close, the
    current targets; (3) otherwise nothing. Bit for bit, orders and fills included."""
    panel, params, limits = case
    st_ = tr.trend_states(panel, params["lookback"], params["buffer"], weekday=weekday)
    z, checks = st_.z, set(st_.checks.tolist())
    half = params["crypto_share"] * 0.5

    def target(t):
        return (half * z[t, 0], half * z[t, 1])

    def decide(t, w):
        if t in checks and (z[t] != (z[t - 1] if t else 0)).any():
            return target(t)
        if breached(w, limits):
            return target(t)
        return None

    want = pf._simulate(panel, costs, decide)
    got = run(params, panel, limits, costs, weekday=weekday)
    pd.testing.assert_frame_equal(got[ALL_COLUMNS], want[ALL_COLUMNS])
    np.testing.assert_array_equal(got.attrs["orders"], want.attrs["orders"])
    same_fills(got, want, len(panel))
    np.testing.assert_array_equal(got.attrs["z"], z)
    reasons = got.attrs["reasons"]
    for t, r in zip(got.attrs["orders"].tolist(), reasons, strict=True):
        assert r == ("switch" if t in checks and (z[t] != (z[t - 1] if t else 0)).any() else "limit")


@given(case=trend_cases(), costs=st.sampled_from(COST_MODELS), stop=st.sampled_from([None, 0.05, 0.2]))
@example(case=(random_panel(260, 3, (0.04, 0.05)), P(10, 0.02, 0.6), TIGHT), costs=COST_MODELS[2], stop=0.05)
def test_accounting_equals_an_independent_book_of_coin_units_and_cash(case, costs, stop):
    """Per bar, from coin units and USDC cash with each order's own target vector (``vector_book``, unit_book's
    arithmetic), to 1e-12: every result column and every leg's USD size and cost; for the plain rule and the stop
    variant alike."""
    panel, params, limits = case
    params = P(params["lookback"], params["buffer"], params["crypto_share"], stop)
    res = run(params, panel, limits, costs)
    validate_result(res, panel)
    fills = fill_bars_of(res)
    assert set(fills) <= set(res.attrs["orders"] + 1)
    out, legs, v_open, _ = vector_book(panel, res, costs)
    for col in ALL_COLUMNS:
        np.testing.assert_allclose(res[col].to_numpy(), out[col], rtol=0, atol=1e-12, err_msg=col)
    log = res.attrs["fills"]
    assert list(log["bar"]) == [leg["bar"] for leg in legs]
    assert list(log["asset"]) == [leg["asset"] for leg in legs]
    np.testing.assert_array_equal(log["weight_after"].to_numpy(), [leg["after"] for leg in legs])
    scale = np.array([v_open[list(fills).index(leg["bar"])] for leg in legs])
    for col in ("usd", "cost"):
        np.testing.assert_allclose(
            log[col].to_numpy() / scale, [leg[col] for leg in legs] / scale, rtol=0, atol=1e-12, err_msg=col
        )


def test_the_vector_book_is_unit_book_for_a_constant_target():
    """``vector_book`` adds nothing to ``test_portfolio.unit_book`` but the per-order target: with one target vector
    the two give the same numbers bit for bit."""
    panel = random_panel(90, 11)
    targets = np.tile((0.37, 0.2), (len(panel), 1))
    res = tr.run_states(panel, targets, limits=TIGHT, costs=COSTS)
    assert len(res.attrs["orders"]) >= 2  # the first buy and at least one limit fix
    out, legs, v_open, value = vector_book(panel, res, COSTS)
    want, want_legs, want_open, want_value, _ = unit_book(panel, {"BTC": 0.37, "ETH": 0.2}, res, COSTS)
    for col in ALL_COLUMNS:
        np.testing.assert_array_equal(out[col], want[col])
    assert v_open == want_open and [leg["usd"] for leg in legs] == [leg["usd"] for leg in want_legs]
    np.testing.assert_array_equal(value, want_value)


def test_decisions_never_depend_on_costs_or_the_book_size():
    """Stop rule 13: the orders (closes, reasons, targets) hash the same at 1x, at 2x and at every R4 book size;
    the stop variant's trend states hash the same, and its events are its own (they read the wallet)."""
    panel = tr.random_walk_panel(2)
    params = P(60, 0.02, 0.5)
    hashes, states = set(), set()
    for capital in (100.0, 500.0, 2_500.0, 10_000.0, 50_000.0):
        for costs in (Costs.from_yaml(capital_usd=capital), Costs.from_yaml(capital_usd=capital).stressed()):
            res = run(params, panel, costs=costs)
            hashes.add(res.attrs["order_hash"])
            states.add(res.attrs["state_hash"])
            res_phi = run(P(60, 0.02, 0.5, 0.2), panel, costs=costs)
            states.add(res_phi.attrs["state_hash"])
            assert res_phi.attrs["stop_events"].tolist() == tr.recompute_stop_events(res_phi["ret"], 0.2)
    assert len(hashes) == 1 and len(states) == 1
    assert res.attrs["order_hash"] == tr.order_hash(res)


def test_the_order_hash_layout_by_hand():
    import hashlib

    panel = random_panel(40, 1)
    targets = np.zeros((40, 2))
    targets[5:] = (0.3, 0.2)
    targets[20:] = (0.0, 0.2)
    res = tr.run_states(panel, targets, limits=LIMITS, costs=COSTS)
    assert res.attrs["orders"].tolist() == [5, 20]

    def part(name, data):
        return name.encode() + b"\0" + len(data).to_bytes(8, "little") + data

    times = np.asarray(panel.index.asi8[[5, 20]], dtype="<i8").tobytes()
    vectors = np.asarray([[0.3, 0.2], [0.0, 0.2]], dtype="<f8").tobytes()
    want = hashlib.sha256(
        part("closes", times) + part("reasons", b"re-cut\nre-cut") + part("targets", vectors)
    )
    assert res.attrs["order_hash"] == want.hexdigest()
    z = np.zeros((40, 2), dtype=np.int8)
    z[7:, 1] = 1
    raw = part("closes", np.asarray(panel.index.asi8, dtype="<i8").tobytes()) + part("z", z.tobytes())
    assert tr.state_hash(z, panel.index) == hashlib.sha256(raw).hexdigest()


def test_bad_inputs_are_refused_with_pinned_messages():
    panel = random_panel(30, 0)
    n = len(panel)
    good = np.zeros((n, 2))
    with pytest.raises(ValueError, match="costs must be a Costs instance"):
        tr.run_states(panel, good, limits=LIMITS, costs=None)
    with pytest.raises(ValueError, match="limits must hold min_cash and max_coin"):
        tr.run_states(panel, good, limits={"min_cash": 0.2, "max_coin": None}, costs=COSTS)
    with pytest.raises(ValueError, match=r"targets must be a finite \(30, 2\) array"):
        tr.run_states(panel, good[:-1], limits=LIMITS, costs=COSTS)
    with pytest.raises(ValueError, match="targets must be a finite"):
        tr.run_states(panel, np.full((n, 2), np.nan), limits=LIMITS, costs=COSTS)
    with pytest.raises(ValueError, match=r"w_BTC \+ w_ETH <= 1"):
        tr.run_states(panel, np.full((n, 2), 0.6), limits=LIMITS, costs=COSTS)
    with pytest.raises(ValueError, match="in \\[0, 1\\]"):
        tr.run_states(panel, np.full((n, 2), -0.1), limits=LIMITS, costs=COSTS)
    # stop rule 12: a vector the limits as read refuse (with h = 0.02) is refused before any bar is traded
    with pytest.raises(ValueError, match="breaks the limits as read \\(stop rule 12\\)"):
        tr.run_states(panel, np.full((n, 2), 0.395), limits=LIMITS, costs=COSTS)
    tr.run_states(panel, np.full((n, 2), 0.39), limits=LIMITS, costs=COSTS)  # 0.78 = 1 - 0.2 - h exactly
    with pytest.raises(ValueError, match="breaks the limits as read"):
        tr.run_states(panel, np.tile((0.59, 0.0), (n, 1)), limits=LIMITS, costs=COSTS)
    tr.run_states(panel, np.tile((0.58, 0.0), (n, 1)), limits=LIMITS, costs=COSTS)  # h = 0.02 inside the cap
    with pytest.raises(ValueError, match=r"states must be a \(30, 2\) array of 0 and 1"):
        tr.run_states(panel, good, limits=LIMITS, costs=COSTS, states=np.full((n, 2), 2))
    with pytest.raises(ValueError, match=r"locks must be a \(30, 2\) array"):
        tr.run_states(panel, good, limits=LIMITS, costs=COSTS, locks=np.zeros((n, 3)))
    with pytest.raises(ValueError, match="panel must be a pandas DataFrame"):
        tr.run_states(None, good, limits=LIMITS, costs=COSTS)


BAD_PARAMS = {
    "unknown key": ({**P(), "band": 0.1}, "unknown params \\['band'\\]"),
    "missing lookback": ({"buffer": 0.1, "crypto_share": 0.5}, "missing required param 'lookback'"),
    "missing buffer": ({"lookback": 2, "crypto_share": 0.5}, "missing required param 'buffer'"),
    "missing share": ({"lookback": 2, "buffer": 0.1}, "missing required param 'crypto_share'"),
    "lookback 0": (P(0), "lookback must be >= 1"),
    "lookback 2.5": (P(2.5), "lookback must be an integer"),
    "lookback True": (P(True), "lookback must be an integer"),
    "buffer < 0": (P(2, -0.01), "buffer must be in \\[0.0, inf\\)"),
    "buffer nan": (P(2, math.nan), "buffer must be in"),
    "share 0": (P(2, 0.1, 0.0), "crypto_share must be in \\(0.0, 1.0\\]"),
    "share > 1": (P(2, 0.1, 1.1), "crypto_share must be in"),
    "share str": (P(2, 0.1, "0.5"), "crypto_share must be a number"),
    "stop 0": (P(2, 0.1, 0.5, 0.0), "stop must be in \\(0.0, 1.0\\)"),
    "stop 1": (P(2, 0.1, 0.5, 1.0), "stop must be in"),
    "params list": ([1, 2], "trend: params must be a dict"),
}


@pytest.mark.parametrize("case", sorted(BAD_PARAMS))
def test_bad_trend_params_raise_with_pinned_messages(case):
    params, match = BAD_PARAMS[case]
    with pytest.raises(ValueError, match=match):
        run(params, random_panel(30, 0))


def test_strict_params_accept_the_box_and_a_stop_of_none():
    assert tr.parse_params({**P(20, 0.005, 0.3), "stop": None}) == {
        "lookback": 20,
        "buffer": 0.005,
        "crypto_share": 0.3,
        "stop": None,
    }
    assert (
        tr.parse_params(P(200.0, 0.1, 0.6, 0.2))["lookback"] == 200
    )  # an integral float, as Optuna may give
    for name in ("stop 0", "stop 1", "share 0", "buffer < 0", "lookback 0"):  # the parser itself refuses them
        params, match = BAD_PARAMS[name]
        with pytest.raises(ValueError, match=match):
            tr.parse_params(params)
    panel = random_panel(30, 0)
    a = run({**P(2, 0.1, 0.5), "stop": None}, panel)
    b = run(P(2, 0.1, 0.5), panel)
    pd.testing.assert_frame_equal(a, b)
    with pytest.raises(ValueError, match="weekday must be an integer in 0..6"):
        run(P(), panel, weekday=7)
    with pytest.raises(ValueError, match="start must be 'out'"):
        tr.trend_states(panel, 2, 0.1, start="flat")


# ------------------------------------------------------------------------------------------------ the harness

FOLD_PARAMS = [P(50, 0.02, 0.5), P(100, 0.05, 0.3), P(30, 0.01, 0.6), P(150, 0.08, 0.4), P(80, 0.03, 0.5)]
PHI = 0.2


def regime_panel(seed: int = 1001) -> pd.DataFrame:
    """The lab generator's regime-switching market on the train grid (2018-01-13 dropped)."""
    market = synthetic_market(2191, seed=seed, start="2017-01-02")
    drop = pd.Timestamp("2018-01-13", tz="UTC")
    return pf.make_panel({a: market[a].drop(drop) for a in pf.ASSETS}, snapshot_id="synthetic")


class Span:
    """S's five fold runs (plain and with the stop at PHI) on a synthetic train panel, R_0's schedule, R_0 and
    R_0^phi."""

    def __init__(self):
        self.panel = regime_panel()
        self.windows = tr.fold_windows(self.panel.index)
        self.runs = fold_runs(self.panel, FOLD_PARAMS, self.windows)
        self.shares = [p["crypto_share"] for p in FOLD_PARAMS]
        self.schedule = tr.stitched_schedule(
            self.panel.index, self.windows, [r.attrs["z"] for r in self.runs], self.shares
        )
        self.r0 = tr.run_span(self.panel, self.schedule, limits=LIMITS, costs=COSTS)
        self.runs_phi = fold_runs(self.panel, [{**p, "stop": PHI} for p in FOLD_PARAMS], self.windows)
        self.locks = tr.stitched_locks(
            self.panel.index, self.windows, [r.attrs["locks"] for r in self.runs_phi]
        )
        self.r0_phi = tr.run_span(self.panel, self.schedule, limits=LIMITS, costs=COSTS, locks=self.locks)
        self.kept = stitched(self.runs, self.windows).index


@pytest.fixture(scope="module")
def span() -> Span:
    return Span()


def test_r0_is_s_s_schedule_executed_continuously(span):
    """R_0 equals S on fold 0's kept rows bit for bit; it holds S's book at fold 0's t0; shift 0 is R_0; each check's
    entry is the state of the fold that holds it, with that fold's s; R_0 pays the fold-boundary trades S's stitched
    curve never pays."""
    w0 = span.windows[0]
    assert tr.same_book_at(span.runs[0], span.r0, w0.t0)
    k0 = kept(span.runs[0], w0)
    np.testing.assert_array_equal(span.r0["ret"].loc[k0.index].to_numpy(), k0.to_numpy())
    pd.testing.assert_frame_equal(
        tr.run_span(span.panel, span.schedule, limits=LIMITS, costs=COSTS, u=0), span.r0
    )
    for field in tr.Schedule._fields:
        np.testing.assert_array_equal(
            getattr(tr.shifted(span.schedule, 0), field), getattr(span.schedule, field)
        )
    sch = span.schedule
    for k, c in enumerate(sch.checks.tolist()):
        i = int(sch.fold[k])
        assert span.windows[i].t0 <= span.panel.index[c] <= span.windows[i].last
        np.testing.assert_array_equal(sch.z[k], span.runs[i].attrs["z"][c])
        assert sch.share[k] == span.shares[i]
    np.testing.assert_array_equal(sch.head_z, span.runs[0].attrs["z"][: sch.checks[0]])
    s_stitched = stitched(span.runs, span.windows)
    assert len(s_stitched) == 1820
    differ = span.r0["ret"].loc[s_stitched.index].to_numpy() != s_stitched.to_numpy()
    assert differ.any() and not differ[:364].any()


def test_a_shifted_schedule_carries_each_fold_s_and_moves_both_coins_together(span):
    sch = span.schedule
    for u in (1, 52, 53, 130, 259):
        sh = tr.shifted(sch, u)
        k = np.arange(len(sch.checks))
        np.testing.assert_array_equal(sh.z, sch.z[(k + u) % 260])
        np.testing.assert_array_equal(sh.share, sch.share[(k + u) % 260])
        np.testing.assert_array_equal(sh.fold, sch.fold[(k + u) % 260])
        np.testing.assert_array_equal(sh.checks, sch.checks)
        np.testing.assert_array_equal(sh.head_z, sch.head_z)
    with pytest.raises(ValueError, match="u must be in 0..259"):
        tr.shifted(sch, 260)
    with pytest.raises(ValueError, match="u must be an integer >= 0"):
        tr.shifted(sch, -1)


@given(
    w=st.integers(54, 120),
    seed=st.integers(0, 2**16),
    u=st.integers(0, 119),
    persist=st.sampled_from([0.5, 0.9, 0.98]),
)
def test_a_shift_keeps_each_state_pair_count_and_the_spell_lengths_up_to_the_splice(w, seed, u, persist):
    """Shift invariants: a shifted schedule holds every state pair (and every s) the same number of times, and its
    spells (runs of one entry) have the same lengths when the W entries are read as a circle, i.e. up to the one
    splice where the shifted schedule wraps."""
    u = u % w
    rng = np.random.default_rng(seed)
    z = np.zeros((w, 2), dtype=np.int8)
    for k in range(1, w):
        z[k] = z[k - 1] if rng.random() < persist else rng.integers(0, 2, 2)
    share = np.where(np.arange(w) < w // 2, 0.3, 0.6)
    sch = tr.Schedule(
        np.arange(10, 10 + w, dtype=np.int64), z, share, np.zeros(w, dtype=np.int64), z[:0], 0.3
    )
    sch = sch._replace(head_z=np.zeros((10, 2), dtype=np.int8))
    sh = tr.shifted(sch, u)

    def pairs(s):
        return sorted(zip(s.z[:, 0].tolist(), s.z[:, 1].tolist(), s.share.tolist(), strict=True))

    def circular_spells(entries):
        rows = [tuple(e) for e in entries]
        if len(set(rows)) == 1:
            return [len(rows)]
        start = next(k for k in range(len(rows)) if rows[k] != rows[k - 1])
        rot = rows[start:] + rows[:start]
        out, n = [], 1
        for a, b in zip(rot, rot[1:], strict=False):
            if a == b:
                n += 1
            else:
                out.append(n)
                n = 1
        return sorted([*out, n])

    assert pairs(sh) == pairs(sch)
    entries = lambda s: np.column_stack([s.z, s.share])  # noqa: E731
    assert circular_spells(entries(sh)) == circular_spells(entries(sch))


def test_a_shift_never_reads_a_price(span):
    """Tampering every price from fold 1 on leaves the shifted schedules' targets unchanged: a shift moves the
    schedule only."""
    other = tamper_from(span.panel, span.panel.index.get_loc(span.windows[1].t0), 3)
    for u in (53, 200):
        a = tr.run_span(span.panel, span.schedule, limits=LIMITS, costs=COSTS, u=u)
        b = tr.run_span(other, span.schedule, limits=LIMITS, costs=COSTS, u=u)
        np.testing.assert_array_equal(a.attrs["targets"], b.attrs["targets"])
        assert tr.same_book_at(a, span.r0, span.windows[0].t0)  # common start


def test_the_guarded_lead_and_lag_offsets():
    for w, n in ((260, 207), (208, 155), (78, 25)):
        u = tr.guarded_offsets(w)
        np.testing.assert_array_equal(u, np.arange(53, w))
        assert len(u) == n and u.dtype == np.int64
        np.testing.assert_array_equal(tr.lead_offsets(w), np.arange(1, 53))
        np.testing.assert_array_equal(tr.lag_offsets(w), np.arange(w - 52, w))
    assert tr.guarded_offsets(54).tolist() == [53]
    for w in (53, 52, 1):
        with pytest.raises(
            ValueError, match=f"W = {w} check closes leaves no shift beyond the lead guard G = 52"
        ):
            tr.guarded_offsets(w)
        with pytest.raises(ValueError, match="leaves no shift"):
            tr.lead_offsets(w)
    assert tr.guarded_offsets(10, guard=3).tolist() == list(range(4, 10))


def test_the_weekly_segment_shift_of_the_plain_schedule_is_b3_for_every_u(span):
    """For the plain rule (entries change only at check closes) the weekly-segment shift equals B3's check-close
    shift on every row, the last close included."""
    n = len(span.panel)
    v, z = tr.span_targets(span.schedule, n)
    for u in range(260):
        src = tr.segment_source_rows(span.panel.index, span.schedule.checks, u)
        vu, zu = tr.span_targets(tr.shifted(span.schedule, u), n)
        np.testing.assert_array_equal(v[src], vu, err_msg=str(u))
        np.testing.assert_array_equal(z[src], zu, err_msg=str(u))
    np.testing.assert_array_equal(
        tr.segment_source_rows(span.panel.index, span.schedule.checks, 0)[:-1], np.arange(n - 1)
    )


def test_the_segment_shift_by_hand_across_a_missing_close():
    """Segment 0 lacks a close (offset 5 is missing): a row at offset 5 of another segment takes segment 0's offset-4
    close, the latest whose offset is at most 5. Rows before c_0 keep their own entries; the last close takes the
    shifted entry of the close before it."""
    full = days(30)
    idx = full.drop(full[12])  # checks every 7 days from row 7: 7, 14 (13 after the drop), ...
    checks = np.array([7, 13, 20], dtype=np.int64)
    assert [idx[c].day_of_week for c in checks] == [0, 0, 0]
    src = tr.segment_source_rows(idx, checks, 2)  # segment k takes segment (k + 2) mod 3
    np.testing.assert_array_equal(src[:7], np.arange(7))
    np.testing.assert_array_equal(src[7:13], [20, 21, 22, 23, 24, 26])  # segment 0 <- 2: offsets 0..4 and 6
    np.testing.assert_array_equal(
        src[13:20], [7, 8, 9, 10, 11, 11, 12]
    )  # segment 1 <- segment 0, offset 5 missing
    np.testing.assert_array_equal(
        src[20:28], [13, 14, 15, 16, 17, 18, 19, 19]
    )  # segment 2 <- 1; offset 7 -> 6
    assert src[28] == src[27]  # the last close
    with pytest.raises(ValueError, match="before the last close but one"):
        tr.segment_source_rows(idx, [7, 28], 1)
    with pytest.raises(ValueError, match="u must be in 0..2"):
        tr.segment_source_rows(idx, checks, 3)
    with pytest.raises(ValueError, match="one entry per row"):
        tr.segment_shift(np.zeros(5), idx, checks, 1)


def test_h0_reproduces_walk_forward_optimize_bit_for_bit(span, tmp_path):
    """S is ``walk_forward_optimize(..., warmup=2190)``: every fold's run starts at row 0, and re-running each fold's
    chosen params on the H0 slice gives its ``oos_returns`` and ``oos_trades`` bit for bit (n_workers = 1)."""
    fn = partial(tr.trend_backtest, limits=LIMITS, costs=COSTS)
    folds = walk_forward(len(span.panel), 365, 365, expanding=True)
    cfg = SearchConfig(n_trials=3, n_workers=1, seed=0)
    wf = walk_forward_optimize(
        "trend-t", fn, list(tr.SPECS), span.panel, folds, tmp_path, cfg, warmup=tr.WARMUP
    )
    parts = []
    for i, window in enumerate(span.windows):
        row = wf["folds"].iloc[i]
        params = {name: row[f"p_{name}"] for name in tr.PARAM_NAMES}
        res = sd.run_h120(fn, params, span.panel, window)
        assert res.index[0] == span.panel.index[0]
        parts.append(kept(res, window))
        assert row["oos_trades"] == sd.kept_fills(res, window.t0)
    pd.testing.assert_series_equal(pd.concat(parts), wf["oos_returns"], check_names=False)
    assert wf["total_trials"] == 15


def test_n0_and_x_start_from_s_s_book_and_then_make_limit_fixes_only(span):
    """Common start (stop rule 14): N0 and X copy S's in-force targets up to close t0 - 1, so they hold S's book at
    t0 bit for bit; N0 orders (s/2, s/2) at t0 unless S already holds it; X orders the mean of S's weights."""
    for i, (res, window, p) in enumerate(zip(span.runs, span.windows, FOLD_PARAMS, strict=True)):
        piece = tr.h0_slice(span.panel, window)
        n0 = tr.always_in_n0(
            piece, res.attrs["targets"], window.t0, p["crypto_share"], limits=LIMITS, costs=COSTS,
            base_states=res.attrs["z"],
        )  # fmt: skip
        x, info = tr.exposure_x(piece, res, window.t0, limits=LIMITS, costs=COSTS)
        t0 = piece.index.get_loc(window.t0)
        for null in (n0, x):
            assert tr.same_book_at(res, null, window.t0)
            orders = null.attrs["orders"]
            assert (null.attrs["reasons"][orders > t0] == "limit").all()
        half = p["crypto_share"] / 2
        np.testing.assert_array_equal(n0.attrs["targets"][t0:], np.tile((half, half), (len(piece) - t0, 1)))
        already = tuple(res.attrs["targets"][t0 - 1]) == (half, half)
        assert (t0 in n0.attrs["orders"]) is (not already), i
        k = res.loc[window.t0 :].iloc[1:]
        assert info["mean"] == (math.fsum(k["w_BTC"]) / len(k), math.fsum(k["w_ETH"]) / len(k))
        assert not info["clipped"] and info["lambda"] == 1.0
        np.testing.assert_array_equal(x.attrs["targets"][t0:], np.tile(info["target"], (len(piece) - t0, 1)))
    with pytest.raises(ValueError, match="base_states needs the target_state"):
        tr.from_t0(
            piece,
            res.attrs["targets"],
            window.t0,
            (0.1, 0.1),
            limits=LIMITS,
            costs=COSTS,
            base_states=res.attrs["z"],
        )


def test_x_is_clipped_by_the_largest_passing_lambda():
    """X clipping (section 9): when S's average weights break the limits with h, both targets are scaled by the
    largest common lambda that passes, to 1e-12, and marked clipped; never a stop."""
    idx = days(10)
    frame = pd.DataFrame({"w_BTC": [0.0, 0.5, 0.5, 0.5], "w_ETH": [0.0, 0.40, 0.45, 0.50]}, index=idx[:4])
    info = tr.exposure_target(frame, idx[0], limits=LIMITS)
    mean = (0.5, 0.45)
    assert info["mean"] == pytest.approx(mean, rel=1e-15, abs=0) and info["clipped"]
    # check_targets allows round-off of LIMIT_TOL = 1e-9 past each cap, so the largest lambda includes it
    tol = pf.LIMIT_TOL
    lam = min(
        (1 - 0.2 - 0.02 + tol) / sum(info["mean"]), (0.6 - 0.02 + tol) / max(info["mean"])
    )  # 0.78 / 0.95
    assert info["lambda"] == pytest.approx(lam, abs=1e-12)
    assert info["target"] == (info["lambda"] * info["mean"][0], info["lambda"] * info["mean"][1])
    pf.check_targets(*info["target"], min_cash=0.2, max_coin=0.6, headroom=0.02)
    with pytest.raises(ValueError):
        top = info["lambda"] + 2e-12
        pf.check_targets(
            top * info["mean"][0], top * info["mean"][1], min_cash=0.2, max_coin=0.6, headroom=0.02
        )
    by_coin = pd.DataFrame({"w_BTC": [0.0, 0.7], "w_ETH": [0.0, 0.0]}, index=idx[:2])
    coin = tr.exposure_target(by_coin, idx[0], limits=LIMITS)
    assert coin["clipped"] and coin["lambda"] == pytest.approx((0.58 + tol) / 0.7, abs=1e-12)
    assert coin["target"][1] == 0.0
    inside = tr.exposure_target(frame.assign(w_ETH=[0.0, 0.125, 0.125, 0.125]), idx[0], limits=LIMITS)
    assert inside == {"target": (0.5, 0.125), "mean": (0.5, 0.125), "clipped": False, "lambda": 1.0}
    with pytest.raises(ValueError, match="no kept close after t0"):
        tr.exposure_target(frame, idx[3], limits=LIMITS)
    with pytest.raises(ValueError, match="refuse even an all-cash book"):
        tr.exposure_target(frame, idx[0], limits={"min_cash": 0.99, "max_coin": 0.6})


def test_a_re_cut_between_folds_is_one_order_and_never_a_switch():
    """M11: two folds with s 0.30 and 0.60 and BTC in across the boundary give exactly one re-cut, at the second
    fold's first check close, in R_0 and in R_0^phi; with both coins out, none. It counts as an order and a fill,
    and not as a switch (the switch counts and P)."""
    idx = days(300)  # Mondays at rows 0, 7, ..., 203, ..., 252
    btc, eth = path(300, r203=300.0), [100.0] * 300
    panel = panel_on(idx, btc, eth)
    windows = [(idx[220], idx[250]), (idx[251], idx[299])]
    z0 = states_of(panel.iloc[:251], buffer=0.1)
    z1 = states_of(panel, buffer=0.1)
    assert (z0[203:, 0] == 1).all() and (z1[203:, 0] == 1).all() and (z1[:, 1] == 0).all()
    sch = tr.stitched_schedule(idx, windows, [z0, z1], [0.30, 0.60])
    assert idx[sch.checks[sch.fold == 1][0]] == idx[252]
    zero_locks = np.zeros((300, 2), dtype=np.int8)
    for res in (
        tr.run_span(panel, sch, limits=LIMITS, costs=COSTS),
        tr.run_span(panel, sch, limits=LIMITS, costs=COSTS, locks=zero_locks),
    ):
        assert res.attrs["orders"].tolist() == [203, 252]
        assert list(res.attrs["reasons"]) == ["switch", "re-cut"]
        assert res.attrs["switches"].tolist() == [1, 0]
        np.testing.assert_array_equal(res.attrs["order_targets"], [[0.15, 0.0], [0.30, 0.0]])
        log = tr.order_log(res)
        assert log["filled"].tolist() == [idx[204], idx[253]] and log["switches"].tolist() == [1, 0]
        assert tr.rolling_order_count(log, idx[[253]]).tolist() == [1.0]
    power = tr.power_count([z0, z1], windows, idx)
    assert power["total"] == 0 and power["per_fold"] == [
        0,
        0,
    ]  # the first buy at 203 and the re-cut never count
    out = [np.zeros((251, 2), dtype=np.int8), np.zeros((300, 2), dtype=np.int8)]
    none = tr.run_span(
        panel, tr.stitched_schedule(idx, windows, out, [0.30, 0.60]), limits=LIMITS, costs=COSTS
    )
    assert none.attrs["orders"].tolist() == [] and none.attrs["n_trades"] == 0


def test_harness_refusals():
    idx = days(300)
    z0, z1 = np.zeros((251, 2), dtype=np.int8), np.zeros((300, 2), dtype=np.int8)
    with pytest.raises(ValueError, match="must be contiguous"):
        tr.stitched_schedule(idx, [(idx[220], idx[250]), (idx[252], idx[299])], [z0, z1], [0.3, 0.3])
    with pytest.raises(ValueError, match="one state path and one share per fold"):
        tr.stitched_schedule(idx, [(idx[220], idx[250])], [z0, z1], [0.3])
    with pytest.raises(ValueError, match="fold 0 must hold the first check close"):
        tr.stitched_schedule(idx, [(idx[246], idx[250]), (idx[251], idx[299])], [z0, z1], [0.3, 0.3])
    with pytest.raises(ValueError, match="at least one fold"):
        tr.stitched_schedule(idx, [], [], [])
    with pytest.raises(ValueError, match="is not in the index"):
        tr.stitched_schedule(idx, [(pd.Timestamp("2030-01-01", tz="UTC"), idx[250])], [z0], [0.3])
    sch = tr.stitched_schedule(idx, [(idx[220], idx[250]), (idx[251], idx[299])], [z0, z1], [0.3, 0.3])
    with pytest.raises(ValueError, match="does not fit the span"):
        tr.span_targets(sch, 200)
    with pytest.raises(ValueError, match="placebo stops need the locks"):
        tr.run_span(
            panel_on(idx, [100.0] * 300, [100.0] * 300), sch, limits=LIMITS, costs=COSTS, placebo=True
        )
    with pytest.raises(ValueError, match="one lock path per fold"):
        tr.stitched_locks(idx, [(idx[220], idx[250]), (idx[251], idx[299])], [z0])
    with pytest.raises(ValueError, match="the span ends at the last fold's last close"):
        tr.stitched_locks(idx, [(idx[220], idx[250]), (idx[251], idx[298])], [z0, z1[:299]])


# ------------------------------------------------------------------------------------------------ the stop-loss variant


def ret_of(values) -> np.ndarray:
    v = np.asarray(values, dtype=float)
    return np.concatenate([[0.0], v[1:] / v[:-1] - 1.0])


def test_a_fall_of_exactly_phi_fires_and_one_ulp_less_does_not():
    assert tr.recompute_stop_events([0.0, -0.5], 0.5) == [1]  # V 1 -> 0.5: f = -0.5 exactly
    # V one ulp above 0.5 (1 + nextafter(-0.5, 0) rounds back to 0.5 itself, half to even)
    assert 1.0 + math.nextafter(-0.5, 0.0) == 0.5
    above = math.nextafter(0.5, 1.0)
    assert 1.0 + (above - 1.0) == above
    assert tr.recompute_stop_events([0.0, above - 1.0], 0.5) == []
    assert tr.recompute_stop_events([0.0, 0.0, 0.0], 0.2) == []
    for bad in (0.0, 1.0, -0.2, math.nan, "0.2"):
        with pytest.raises(ValueError, match="stop must be"):
            tr.recompute_stop_events([0.0, -0.5], bad)


def test_the_high_restarts_after_a_stop_and_not_after_a_trend_exit():
    # a trend exit leaves the wallet 15% below its high of 2; the buy-back's later fall is measured from that high
    v = [1.0, 2.0, 1.7, 1.7, 1.8, 1.58]
    assert tr.recompute_stop_events(ret_of(v), 0.2) == [
        5
    ]  # 1.58 / 2 - 1 = -0.21 (from 1.8 it would be -0.12)
    # after a stop the high restarts at the close after it: 1.6 is the new high, 1.3 is -0.19 from it, 1.25 -0.22
    v = [1.0, 2.0, 1.5, 1.5, 1.6, 1.3, 1.6, 1.25]
    assert tr.recompute_stop_events(ret_of(v), 0.2) == [2, 7]
    # the close right after a stop is the reference: a fall on it is not an event (f = 0 there)
    v = [1.0, 0.7, 0.5, 0.5]
    assert tr.recompute_stop_events(ret_of(v), 0.2) == [1]


def test_lock_rules_by_hand():
    z = np.array(
        [[0, 0], [0, 0], [1, 0], [1, 0], [1, 0], [1, 1], [0, 1], [0, 1], [1, 1], [1, 1]], dtype=np.int8
    )
    locks = tr.lock_series(z, [3])
    # BTC in at the stop: stays locked through its out-turn at 6, unlocked by the in-turn at 8
    assert locks[:, 0].tolist() == [0, 0, 0, 1, 1, 1, 1, 1, 0, 0]
    # ETH out at the stop: back at its next up-turn (5), the close the plain rule buys it
    assert locks[:, 1].tolist() == [0, 0, 0, 1, 1, 0, 0, 0, 0, 0]
    # an up-turn on the stop close does not unlock: BTC turns in at 3, the stop is at 3
    z2 = np.array([[0, 0], [0, 0], [0, 0], [1, 0], [1, 0], [1, 0], [0, 0], [1, 0]], dtype=np.int8)
    assert tr.lock_series(z2, [3])[:, 0].tolist() == [0, 0, 0, 1, 1, 1, 1, 0]
    # a second stop while BTC is still locked relocks both; ETH's up-turn before it does not count after it
    z3 = np.array([[0, 0], [1, 0], [1, 0], [1, 1], [1, 1], [1, 1], [1, 0], [1, 1]], dtype=np.int8)
    l3 = tr.lock_series(z3, [2, 4])
    assert l3[:, 1].tolist() == [0, 0, 1, 0, 1, 1, 1, 0] and l3[:, 0].tolist() == [0, 0, 1, 1, 1, 1, 1, 1]
    in_force = tr.in_force(z3, 0.6, l3)
    np.testing.assert_array_equal(in_force[:, 1], [0, 0, 0, 0.3, 0, 0, 0, 0.3])
    assert (tr.lock_series(z, []) == 0).all()
    with pytest.raises(ValueError, match="stop events must be rows of the 10-row path"):
        tr.lock_series(z, [10])
    with pytest.raises(ValueError, match="event must be an integer >= 0"):
        tr.lock_series(z, [-1])


def gap_case():
    """BTC and ETH in at Monday 203; both drop 20% on Monday 210 (m = -0.11: both out); the open of 211 gaps 25% lower,
    so the exit's own fill takes the wallet past 20% below its high; Monday 217 turns both up again."""
    idx = days(240)
    c = path(240, r203=300.0, r210=240.0, r211=180.0, r217=400.0)
    o = [c[0], *c[:-1]]
    o[211] = 180.0
    return panel_on(idx, c, c, o, o)


def test_a_trend_exit_whose_own_fill_passes_phi_is_an_event_with_no_order():
    panel = gap_case()
    plain = run(P(2, 0.1, 0.6), panel)
    res = run(P(2, 0.1, 0.6, 0.2), panel)
    value = np.cumprod(1.0 + res["ret"].to_numpy())
    assert value[210] / value[:211].max() - 1.0 > -0.2  # the exit decision at 210 is not a stop
    assert res.attrs["stop_events"].tolist() == [211] and res.attrs["stop_ordered"].tolist() == [False]
    assert res["position"].iloc[211] == 0.0  # all cash when the event fires: nothing to sell
    assert res.attrs["orders"].tolist() == plain.attrs["orders"].tolist() == [203, 210, 217]
    assert list(res.attrs["reasons"]) == ["switch", "switch", "switch"]
    # the buy-back at 217 is not sold the next day: the high restarted at 212
    assert res["position"].iloc[218] > 0 and res["position"].iloc[-1] > 0
    assert (value[218] / value[212:219].max() - 1.0) > -0.2 and value[218] / value[:212].max() - 1.0 <= -0.2
    pd.testing.assert_frame_equal(res[ALL_COLUMNS], plain[ALL_COLUMNS])
    np.testing.assert_array_equal(res.attrs["locks"][211:217], 1)
    np.testing.assert_array_equal(res.attrs["locks"][217:], 0)


def test_a_coin_in_at_the_stop_stays_out_until_it_turns_out_and_in():
    """A 30% crash on Wednesday 212 takes the wallet past 20% below its high while both coins are in: the stop sells
    both (one order, the full vector (0, 0)). Both stay in trend, so they stay out of the book; on Monday 224 they
    turn out (no order: nothing held), on Monday 231 back in, which unlocks and buys them."""
    idx = days(260)
    c = path(260, r203=300.0, r212=150.0, r223=150.0, r224=100.0, r230=100.0, r231=300.0)
    panel = panel_on(idx, c, c)
    z = states_of(panel)
    assert z[212:224].tolist() == [[1, 1]] * 12 and (z[224:231] == 0).all() and (z[231:] == 1).all()
    res = run(P(2, 0.1, 0.6, 0.2), panel)
    assert res.attrs["stop_events"].tolist() == [212] and res.attrs["stop_ordered"].tolist() == [True]
    assert res.attrs["orders"].tolist() == [203, 212, 231]
    assert list(res.attrs["reasons"]) == ["switch", "stop", "switch"]
    np.testing.assert_array_equal(res.attrs["order_targets"], [[0.3, 0.3], [0.0, 0.0], [0.3, 0.3]])
    assert (res["position"].iloc[213:232] == 0.0).all() and res["position"].iloc[232] > 0
    plain = run(P(2, 0.1, 0.6), panel)
    assert plain.attrs["orders"].tolist() == [203, 224, 231]  # the plain rule rides the fall to its exit


def test_a_stop_comes_before_a_switch_and_a_limit_fix_on_the_same_close():
    panel = random_panel(40, 3, (0.2, 0.2))
    n = len(panel)
    z = np.zeros((n, 2), dtype=np.int8)
    z[5:] = 1
    z[20:, 1] = 0  # ETH's state changes on the stop close
    locks = tr.lock_series(z, [20])
    targets = tr.in_force(z, 0.76, locks)
    res = tr.run_states(panel, targets, limits=TIGHT, costs=COSTS, states=z, locks=locks)
    assert breached(res[["w_BTC", "w_ETH"]].to_numpy()[20], TIGHT)  # a limit breach on the stop close too
    assert 20 in res.attrs["orders"].tolist()
    at = res.attrs["orders"].tolist().index(20)
    assert res.attrs["reasons"][at] == "stop" and res.attrs["order_targets"][at].tolist() == [0.0, 0.0]
    assert len(set(res.attrs["orders"].tolist())) == len(res.attrs["orders"])  # one order per close
    # unlock with no state change (only in placebo series): its own reason
    placebo = np.zeros((n, 2), dtype=np.int8)
    placebo[10:15] = 1
    res = tr.run_states(
        panel, tr.in_force(z, 0.5, placebo), limits=LIMITS, costs=COSTS, states=z, locks=placebo
    )
    reasons = dict(zip(res.attrs["orders"].tolist(), res.attrs["reasons"], strict=True))
    assert (reasons[5], reasons[10], reasons[15], reasons[20]) == ("switch", "stop", "unlock", "switch")


def test_a_stop_at_the_last_close_is_never_filled():
    idx = days(230)
    c = path(230, r203=300.0, r229=180.0)
    panel = panel_on(idx, c, c)
    res = run(P(2, 0.1, 0.6, 0.2), panel)
    assert res.attrs["stop_events"].tolist() == [229] and res.attrs["stop_ordered"].tolist() == [False]
    plain = run(P(2, 0.1, 0.6), panel)
    pd.testing.assert_frame_equal(res[ALL_COLUMNS], plain[ALL_COLUMNS])
    np.testing.assert_array_equal(res.attrs["orders"], plain.attrs["orders"])
    assert res.attrs["passes"] == 2


@given(case=trend_cases(), costs=st.sampled_from(COST_MODELS[:2]))
def test_a_level_that_never_fires_is_the_plain_rule_bit_for_bit(case, costs):
    panel, params, limits = case
    plain = run(params, panel, limits, costs)
    value = np.cumprod(1.0 + plain["ret"].to_numpy())
    deepest = float((value / np.maximum.accumulate(value) - 1.0).min())
    phi = min(0.99, -deepest + 0.01)  # deeper than any fall of this path
    res = run({**params, "stop": phi}, panel, limits, costs)
    assert res.attrs["stop_events"].tolist() == [] and res.attrs["passes"] == 1
    pd.testing.assert_frame_equal(res[ALL_COLUMNS], plain[ALL_COLUMNS])
    for key in ("orders", "reasons", "targets", "order_targets", "switches"):
        np.testing.assert_array_equal(res.attrs[key], plain.attrs[key])
    assert res.attrs["order_hash"] == plain.attrs["order_hash"]


@given(case=trend_cases(), costs=st.sampled_from(COST_MODELS[:2]), phi=st.sampled_from([0.03, 0.08, 0.2]))
@example(case=(random_panel(300, 8, (0.08, 0.08)), P(5, 0.02, 0.76), TIGHT), costs=COST_MODELS[0], phi=0.03)
def test_the_re_running_equals_a_one_pass_book_of_coin_units_and_cash(case, costs, phi):
    """The re-running of section 11A equals an independent one-pass book that decides the stops itself (from its own
    value in coin units and USDC cash), on drawn paths: the same events and locks, and every return and weight to
    1e-12. Each run's events also equal ``recompute_stop_events`` on its own ``ret`` (stop rule 13)."""
    panel, params, limits = case
    res = run({**params, "stop": phi}, panel, limits, costs)
    z = tr.trend_states(panel, params["lookback"], params["buffer"]).z
    ret, weights, events, locks = stop_book(panel, z, params["crypto_share"], phi, limits, costs)
    assert res.attrs["stop_events"].tolist() == events
    np.testing.assert_array_equal(res.attrs["locks"], locks)
    np.testing.assert_allclose(res["ret"].to_numpy(), ret, rtol=0, atol=1e-12)
    np.testing.assert_allclose(res[["w_BTC", "w_ETH"]].to_numpy(), weights, rtol=0, atol=1e-12)
    assert tr.recompute_stop_events(res["ret"], phi) == events
    assert res.attrs["passes"] == len(events) + 1
    sent = set(res.attrs["orders"].tolist())
    assert res.attrs["stop_ordered"].tolist() == [e in sent for e in events]
    for e, ordered in zip(events, res.attrs["stop_ordered"].tolist(), strict=True):
        held = res["position"].iloc[e] > 0.0
        assert ordered == (
            held and e < len(panel) - 1
        )  # it sells when the book holds a coin, unless at the end


@given(case=trend_cases(), data=st.data(), phi=st.sampled_from([0.03, 0.1]))
def test_no_look_ahead_in_the_stops_the_locks_or_the_buy_backs(case, data, phi):
    """Tamper the future on the stop variant: every event, lock, order and result row decided before ``cut`` is the
    same; so is the fill on bar cut."""
    panel, params, limits = case
    cut = data.draw(st.integers(1, len(panel) - 1))
    other = tamper_from(panel, cut, data.draw(st.integers(0, 2**16)))
    a = run({**params, "stop": phi}, panel, limits)
    b = run({**params, "stop": phi}, other, limits)
    ea, eb = a.attrs["stop_events"], b.attrs["stop_events"]
    np.testing.assert_array_equal(ea[ea < cut], eb[eb < cut])
    np.testing.assert_array_equal(a.attrs["locks"][:cut], b.attrs["locks"][:cut])
    np.testing.assert_array_equal(a.attrs["targets"][:cut], b.attrs["targets"][:cut])
    np.testing.assert_array_equal(a[ALL_COLUMNS].to_numpy()[:cut], b[ALL_COLUMNS].to_numpy()[:cut])
    assert (a["turnover"].iloc[cut], a["cost"].iloc[cut]) == (b["turnover"].iloc[cut], b["cost"].iloc[cut])
    oa, ob = a.attrs["orders"], b.attrs["orders"]
    np.testing.assert_array_equal(oa[oa < cut], ob[ob < cut])
    same_fills(a, b, cut)


@given(case=trend_cases(), data=st.data(), phi=st.sampled_from([0.03, 0.1]))
def test_no_look_ahead_in_the_stops_with_cuts_at_the_stops_unlocks_and_highs(case, data, phi):
    """The same tamper with a third of the cuts at a stop event e, at e + 1, at an unlock close u or at u + 1, and a
    third at a close where the wallet's value sets a new high, where a leak of one close in the stop, the buy-back or
    the high shows at once (uniform cuts over 205-330 rows rarely land there, since nothing can happen before row
    199; #58)."""
    panel, params, limits = case
    n = len(panel)
    a = run({**params, "stop": phi}, panel, limits)
    locks = a.attrs["locks"]
    unlocks = (np.flatnonzero((np.diff(locks, axis=0) < 0).any(axis=1)) + 1).tolist()
    events = a.attrs["stop_events"].tolist()
    v = np.cumprod(1.0 + a["ret"].to_numpy())
    highs = (np.flatnonzero(v[1:] > np.maximum.accumulate(v)[:-1]) + 1).tolist()
    anchors = {
        "stops": sorted({c for x in events + unlocks for c in (x, x + 1) if 1 <= c <= n - 1}),
        "highs": [c for c in highs if 1 <= c <= n - 1],
    }
    where = data.draw(st.sampled_from(["stops", "highs", "any"]))
    if where != "any" and anchors[where]:
        cut = data.draw(st.sampled_from(anchors[where]))
    else:
        cut = data.draw(st.integers(1, n - 1))
    other = tamper_from(panel, cut, data.draw(st.integers(0, 2**16)))
    b = run({**params, "stop": phi}, other, limits)
    ea, eb = a.attrs["stop_events"], b.attrs["stop_events"]
    np.testing.assert_array_equal(ea[ea < cut], eb[eb < cut])
    np.testing.assert_array_equal(a.attrs["locks"][:cut], b.attrs["locks"][:cut])
    np.testing.assert_array_equal(a.attrs["targets"][:cut], b.attrs["targets"][:cut])
    np.testing.assert_array_equal(a[ALL_COLUMNS].to_numpy()[:cut], b[ALL_COLUMNS].to_numpy()[:cut])
    oa, ob = a.attrs["orders"], b.attrs["orders"]
    np.testing.assert_array_equal(oa[oa < cut], ob[ob < cut])
    same_fills(a, b, cut)


def test_the_stop_variant_on_the_folds_r0_phi_its_shifts_placebos_and_nulls(span):
    """R_0^phi equals S^phi on fold 0's kept rows; with every lock 0 it is R_0 bit for bit; its shifts, its placebo
    stops, N0^phi and X^phi hold S^phi's book at t0; placebo u = 0 reproduces R_0^phi; each fold's events equal
    ``recompute_stop_events`` on its own ret."""
    w0 = span.windows[0]
    assert sum(len(r.attrs["stop_events"]) for r in span.runs_phi) >= 3  # the synthetic regimes trigger it
    for r in span.runs_phi:
        assert r.attrs["stop_events"].tolist() == tr.recompute_stop_events(r["ret"], PHI)
    k0 = kept(span.runs_phi[0], w0)
    np.testing.assert_array_equal(span.r0_phi["ret"].loc[k0.index].to_numpy(), k0.to_numpy())
    assert tr.same_book_at(span.runs_phi[0], span.r0_phi, w0.t0)
    zero = tr.run_span(
        span.panel, span.schedule, limits=LIMITS, costs=COSTS, locks=np.zeros((2190, 2), np.int8)
    )
    pd.testing.assert_frame_equal(zero, span.r0)
    placebo0 = tr.run_span(
        span.panel, span.schedule, limits=LIMITS, costs=COSTS, locks=span.locks, placebo=True
    )
    pd.testing.assert_frame_equal(placebo0[ALL_COLUMNS], span.r0_phi[ALL_COLUMNS])
    np.testing.assert_array_equal(placebo0.attrs["orders"], span.r0_phi.attrs["orders"])
    v, _ = tr.span_targets(span.schedule, len(span.panel))
    entries = np.where(span.locks.astype(bool), 0.0, v)
    np.testing.assert_array_equal(span.r0_phi.attrs["targets"], entries)
    for u in (53, 159, 259):
        shift = tr.run_span(span.panel, span.schedule, limits=LIMITS, costs=COSTS, locks=span.locks, u=u)
        src = tr.segment_source_rows(span.panel.index, span.schedule.checks, u)
        np.testing.assert_array_equal(shift.attrs["targets"], entries[src])
        placebo = tr.run_span(
            span.panel, span.schedule, limits=LIMITS, costs=COSTS, locks=span.locks, u=u, placebo=True
        )
        e_u, l_u = tr.placebo_stops(v, span.locks, span.panel.index, span.schedule.checks, u)
        np.testing.assert_array_equal(placebo.attrs["targets"], e_u)
        np.testing.assert_array_equal(l_u, span.locks[src])
        for series in (shift, placebo):
            assert tr.same_book_at(span.runs_phi[0], series, w0.t0)
    for i, (res, window, p) in enumerate(zip(span.runs_phi, span.windows, FOLD_PARAMS, strict=True)):
        piece = tr.h0_slice(span.panel, window)
        n0 = tr.always_in_n0(
            piece, res.attrs["targets"], window.t0, p["crypto_share"], limits=LIMITS, costs=COSTS
        )
        x, info = tr.exposure_x(piece, res, window.t0, limits=LIMITS, costs=COSTS)
        assert tr.same_book_at(res, n0, window.t0) and tr.same_book_at(res, x, window.t0), i
        k = res.loc[window.t0 :].iloc[1:]  # X^phi holds S^phi's average crypto over the kept closes, by hand
        assert info["mean"] == (math.fsum(k["w_BTC"]) / len(k), math.fsum(k["w_ETH"]) / len(k))
        assert "stop_events" not in n0.attrs  # N0^phi runs no stop


def test_r0_phi_takes_each_fold_s_locks_on_its_test_rows_and_shifts_like_b3_without_locks(span):
    """l(t) is the lock pair of the fold whose test rows hold t (fold 0's before its t0); with no lock, R_0^phi's
    weekly-segment shift u is the plain B3 shift u in every column, reason and order hash."""
    idx = span.panel.index
    for i, (res, w) in enumerate(zip(span.runs_phi, span.windows, strict=True)):
        first = 0 if i == 0 else idx.get_loc(w.t0)
        rows = slice(first, idx.get_loc(w.last) + 1)
        np.testing.assert_array_equal(span.locks[rows], res.attrs["locks"][rows], err_msg=str(i))
    later = zip(span.runs_phi[1:], span.windows[1:], strict=True)
    assert any(
        r.attrs["locks"][idx.get_loc(w.t0) :].any() for r, w in later
    )  # the fixture locks a later fold
    v, _ = tr.span_targets(span.schedule, len(span.panel))
    np.testing.assert_array_equal(span.r0_phi.attrs["targets"], np.where(span.locks.astype(bool), 0.0, v))
    zero = np.zeros((len(span.panel), 2), dtype=np.int8)
    for u in (53, 211):
        plain = tr.run_span(span.panel, span.schedule, limits=LIMITS, costs=COSTS, u=u)
        no_lock = tr.run_span(span.panel, span.schedule, limits=LIMITS, costs=COSTS, locks=zero, u=u)
        pd.testing.assert_frame_equal(no_lock, plain)
        for key in ("orders", "reasons", "switches", "targets"):
            np.testing.assert_array_equal(no_lock.attrs[key], plain.attrs[key], err_msg=key)
        assert no_lock.attrs["order_hash"] == plain.attrs["order_hash"]


def test_stitched_locks_by_hand():
    """Fold 0's locks on rows 0 .. last_0 (before its t0 too), then each fold's on its own test rows only."""
    idx = days(300)
    windows = [(idx[220], idx[250]), (idx[251], idx[299])]
    l0 = np.zeros((251, 2), dtype=np.int8)
    l0[100:105, 0] = 1  # before fold 0's t0
    l0[230:240, 1] = 1
    l1 = np.ones((300, 2), dtype=np.int8)  # fold 1's run: locked everywhere, read on rows 251 .. 299 only
    l1[260:270] = 0
    got = tr.stitched_locks(idx, windows, [l0, l1])
    want = np.vstack([l0, l1[251:]])
    np.testing.assert_array_equal(got, want)
    assert got[100:105, 0].tolist() == [1] * 5 and got[250].tolist() == [0, 0] and got[251].tolist() == [1, 1]


def test_placebo_locks_move_by_whole_weeks_and_never_read_a_price(span):
    """A placebo's lock pattern at each check close is the real one of the shifted week, so the weeks that start
    locked, and their runs read as a circle, are kept exactly; prices are never read."""
    checks = span.schedule.checks
    real = span.locks[checks]
    for u in (53, 120, 259):
        _, l_u = tr.placebo_stops(np.zeros((2190, 2)), span.locks, span.panel.index, checks, u)
        np.testing.assert_array_equal(l_u[checks], real[(np.arange(260) + u) % 260])
        assert sorted(map(tuple, l_u[checks].tolist())) == sorted(map(tuple, real.tolist()))
    other = tamper_from(span.panel, 500, 9)
    a = tr.run_span(
        span.panel, span.schedule, limits=LIMITS, costs=COSTS, locks=span.locks, u=80, placebo=True
    )
    b = tr.run_span(other, span.schedule, limits=LIMITS, costs=COSTS, locks=span.locks, u=80, placebo=True)
    np.testing.assert_array_equal(a.attrs["targets"], b.attrs["targets"])
    assert "stop_events" not in a.attrs  # no stop search runs for a placebo


def test_the_fresh_customer_starts_from_10000_usd_in_usdc_at_t0(span):
    window = span.windows[2]
    piece = tr.h0_slice(span.panel, window)
    z = tr.trend_states(piece, 30, 0.01).z
    res, events = tr.fresh_customer(piece, z, 0.6, PHI, window.t0, limits=LIMITS, costs=COSTS)
    t0 = piece.index.get_loc(window.t0)
    assert res.index[0] == window.t0 and len(res) == len(piece) - t0
    np.testing.assert_array_equal(res.attrs["targets"], tr.in_force(z[t0:], 0.6, res.attrs["locks"]))
    first = tr.in_force(z[t0:], 0.6)[0]
    if first.any():
        assert res.attrs["orders"][0] == 0 and res.attrs["order_targets"][0].tolist() == first.tolist()
        assert res.attrs["fills"]["bar"].iloc[0] == 1  # filled at the open of t0 + 1
    assert res["ret"].iloc[0] == 0.0 and res["position"].iloc[0] == 0.0  # USDC at close t0
    assert events == tr.recompute_stop_events(res["ret"], PHI)
    assert (res.attrs["locks"][0] == 0).all()


# ------------------------------------------------------------------------------------------------ criteria


def sharpe_series(mu: float, n: int = 400, sd: float = 0.01) -> np.ndarray:
    """Returns whose annualised Sharpe rises with mu (the same +-sd pattern every time; equal mu, equal series)."""
    return mu + sd * np.tile([1.0, -1.0], n // 2)


def shift_dict(counts: dict[float, int], w: int, n: int = 400) -> dict[int, np.ndarray]:
    """Guarded offsets u = 53 .. W - 1 filled with series of the given means, in order; leads get junk."""
    means = [mu for mu, k in counts.items() for _ in range(k)]
    offsets = tr.guarded_offsets(w).tolist()
    assert len(means) == len(offsets)
    out = {u: sharpe_series(mu, n) for u, mu in zip(offsets, means, strict=True)}
    out.update({u: np.full(n, 1e3) for u in tr.lead_offsets(w).tolist()})  # never read
    return out


def test_e1_decides_on_the_rank_p_at_its_boundaries():
    r0 = sharpe_series(0.001)
    for w, holds_at, n in ((260, 9, 207), (208, 6, 155)):
        for above, holds in ((holds_at, True), (holds_at + 1, False)):
            res = tr.e1_test(r0, shift_dict({0.002: above, 0.0: n - above}, w), w)
            assert res["at_or_above"] == above and res["n_shifts"] == n
            assert res["rank_p"] == (1 + above) / (n + 1) and res["holds"] is holds
            assert tr.rank_holds(res["rank_p"]) is holds
        ties = tr.e1_test(r0, shift_dict({0.001: holds_at + 1, 0.0: n - holds_at - 1}, w), w)
        assert ties["at_or_above"] == holds_at + 1 and not ties["holds"]  # ties count against R_0
    # p95 says "holds" but 11 shifts are at or above (one tie): p = 12/208 = 0.058, E1 fails
    res = tr.e1_test(r0, shift_dict({0.0: 196, 0.001: 1, 0.002: 10}, 260), 260)
    assert res["p95_holds"] and res["rank_p"] == 12 / 208 and not res["holds"]
    assert tr.rank_holds(10 / 208) and not tr.rank_holds(11 / 208)
    # exactly 0.05 fails: 19 guarded shifts (W = 72), none at or above, give p = 1/20
    exact = tr.e1_test(r0, shift_dict({0.0: 19}, 72), 72)
    assert exact["rank_p"] == 0.05 and not exact["holds"] and not tr.rank_holds(0.05)
    assert tr.e1_test(r0, shift_dict({0.0: 20}, 73), 73)["holds"]  # 1/21
    assert tr.rank_holds(7 / 156) and not tr.rank_holds(8 / 156)
    with pytest.raises(ValueError, match="offset u = 53 is missing"):
        tr.e1_test(r0, {}, 260)
    with pytest.raises(ValueError, match="keep must be one flag per row"):
        tr.e1_test(r0, shift_dict({0.0: 207}, 260), 260, keep=[True])
    kept = tr.e1_test(r0, shift_dict({0.0: 207}, 260), 260, keep=np.arange(400) < 200)
    assert kept["holds"] and len(kept["draw_sharpes"]) == 207


def test_e2_decides_at_p_below_0_05_at_its_boundaries():
    assert tr.e2_holds(0.1, 500 / 10_001) and not tr.e2_holds(0.1, 501 / 10_001)  # 499 and 500 resamples <= 0
    assert not tr.e2_holds(0.0, 0.0001) and not tr.e2_holds(-0.1, 0.0001)
    idx = days(300)
    base = pd.Series(np.random.default_rng(5).normal(0.0, 0.02, 300), index=idx)
    better = base + 0.01  # every resample has D* > 0, so p = 1 / (n + 1) exactly
    for n, holds in ((19, False), (20, True)):
        res = tr.e2_test(better, base, n_resamples=n)
        assert res["p"] == 1 / (n + 1) and res["holds"] is holds
    full = tr.e2_test(better, base, n_resamples=200)
    want = sd.paired_bootstrap(better, base, n_resamples=200, mean_block=60, seed=0)
    assert full["d"] == want["d"] and full["p"] == want["p"] and full["mean_block"] == 60
    np.testing.assert_array_equal(full["d_star"], want["d_star"])


def test_e3_needs_both_drawdowns_strictly_shallower():
    assert tr.e3_holds(-0.2, -0.3, -0.25, -0.35)
    assert not tr.e3_holds(-0.25, -0.3, -0.25, -0.35)  # equal historical drawdowns fail
    assert not tr.e3_holds(-0.2, -0.35, -0.25, -0.35)  # equal Monte Carlo p5 fail
    assert not tr.e3_holds(-0.2, math.nan, -0.25, -0.35)


def test_e6_leave_one_year_out_by_hand():
    idx = pd.date_range("2018-01-03", "2021-01-01", freq="D", tz="UTC", name="ts")
    years = tr.bar_years(idx)
    assert years[0] == 2018 and (years[idx == pd.Timestamp("2019-01-01", tz="UTC")] == 2018).all()
    n0 = pd.Series(0.0, index=idx)
    one = pd.Series(np.where(years == 2019, 0.001, 0.0), index=idx)
    res = tr.loyo(one, n0)
    assert set(res["delta_y"]) == {2018, 2019, 2020} and res["delta_y"][2018] == 0.0
    assert res["delta"] == res["delta_y"][2019] > 0 and not res["holds"]  # Delta - Delta_2019 = 0 fails
    two = pd.Series(np.where(years >= 2019, 0.001, 0.0), index=idx)
    assert tr.loyo(two, n0)["holds"]  # removing either positive year leaves the other: it survives every year
    mixed = pd.Series(np.where(years == 2019, 0.001, np.where(years == 2020, -0.0001, 0.0)), index=idx)
    assert (
        tr.loyo(mixed, n0)["delta"] > 0 and not tr.loyo(mixed, n0)["holds"]
    )  # without 2019 the excess is < 0
    every = pd.Series(0.001, index=idx)
    got = tr.loyo(every, n0)
    assert got["holds"] and got["delta"] == math.fsum(got["delta_y"].values())
    want = {y: math.fsum([math.log1p(0.001)] * int((years == y).sum())) for y in (2018, 2019, 2020)}
    assert got["delta_y"] == want
    assert not tr.loyo(-every, n0)["holds"]
    with pytest.raises(ValueError, match="same kept closes"):
        tr.loyo(every, n0.iloc[1:])


def power_states(toggles: list[int], n: int) -> np.ndarray:
    z = np.zeros((n, 2), dtype=np.int8)
    for t in sorted(toggles):
        z[t:, 0] ^= 1
    return z


def test_p_counts_state_changes_that_fill_in_kept_rows_and_not_first_buys():
    idx = days(560)
    windows = [
        (idx[200 + 70 * i], idx[269 + 70 * i]) for i in range(5)
    ]  # t0 200, 270, ..., last 269, 339, ...

    def count(toggles, per_fold=None):
        z = power_states([100, *toggles], 560)  # row 100: BTC's first buy, never counted
        return tr.power_count([z[: 270 + 70 * i] for i in range(5)], windows, idx)

    four = [r for i in range(5) for r in (210 + 70 * i, 220 + 70 * i, 230 + 70 * i, 240 + 70 * i)]
    res = count(four)
    assert res["total"] == 20 and res["per_fold"] == [4] * 5 and res["folds_with"] == 5 and res["holds"]
    assert not count(four[:-1])["holds"] and count(four[:-1])["total"] == 19  # 19 switches fail P, 20 hold
    three_folds = [210 + 70 * i + 3 * k for i in range(3) for k in range(7)]  # 21 changes in 3 folds
    assert count(three_folds)["total"] == 21 and not count(three_folds)["holds"]
    assert count(three_folds + [500])["folds_with"] == 4 and count(three_folds + [500])["holds"]
    # the boundaries: a change at t0 counts (its order fills at t0 + 1); one at last does not
    edge = count([200, 269])
    assert edge["per_fold"] == [1, 0, 0, 0, 0] and edge["total"] == 1
    first = tr.power_count([power_states([210], 270)] * 1, windows[:1], idx)
    assert first["total"] == 0  # a coin's first change (out -> in) is its first buy
    res = count([210, 217, 290, 300])
    assert res["switch_weeks"] == 4 and res["out_spells"] == {"BTC": 2, "ETH": 0}
    with pytest.raises(ValueError, match="one state path per fold"):
        tr.power_count([], windows, idx)


def test_p_counts_each_coin_when_both_switch_on_one_close():
    """P counts coin-state changes, both coins counted (section 11), not orders or switch weeks: both coins out on
    one close are 2 changes, 1 order and 1 switch week (#58)."""
    idx = days(560)
    windows = [(idx[200 + 70 * i], idx[269 + 70 * i]) for i in range(5)]
    z = np.zeros((560, 2), dtype=np.int8)
    z[100:, :] = 1  # both coins' first buys, never counted
    z[210:, :] = 0  # both coins out on one close
    z[290:, 0] = 1  # BTC back in
    res = tr.power_count([z[: 270 + 70 * i] for i in range(5)], windows, idx)
    assert res["per_fold"] == [2, 1, 0, 0, 0] and res["total"] == 3 and res["folds_with"] == 2
    assert res["switch_weeks"] == 2 and res["out_spells"] == {"BTC": 1, "ETH": 0}


def test_same_book_at_compares_the_book_not_only_the_returns():
    """Stop rule 14's "same book at t0" compares turnover, cost and both weights too: on flat prices with no costs
    two books with different coins have equal returns on every row, and they are not the same book (#58)."""
    idx = days(30)
    panel = panel_on(idx, [100.0] * 30, [50.0] * 30)
    a = np.zeros((30, 2))
    b = a.copy()
    b[9:] = (0.2, 0.2)  # decided at close 9, filled at the open of row 10
    ra = tr.run_states(panel, a, limits=LIMITS, costs=Costs.zero())
    rb = tr.run_states(panel, b, limits=LIMITS, costs=Costs.zero())
    assert np.array_equal(ra["ret"].to_numpy(), rb["ret"].to_numpy())
    assert rb["turnover"].iloc[10] > 0 and rb["cost"].iloc[10] == 0.0
    assert tr.same_book_at(ra, rb, idx[9])
    assert not tr.same_book_at(ra, rb, idx[10]) and not tr.same_book_at(ra, rb, idx[20])


def test_keeps_share_is_the_70_percent_rule_with_a_positive_sharpe():
    assert tr.keeps_share(1.0, [0.7, 2.0]) and tr.keeps_share(2.0, [0.7 * 2.0])
    assert not tr.keeps_share(1.0, [math.nextafter(0.7, 0.0)])
    assert not tr.keeps_share(0.0, [0.5]) and not tr.keeps_share(-0.5, [-0.4, -0.3])  # E5(b) fails if S <= 0
    assert not tr.keeps_share(1.0, [math.nan]) and not tr.keeps_share(math.nan, [1.0])
    assert tr.keeps_share(1.0, [])


def test_the_boom_years_rank_by_btc_s_kept_rows_with_ties_to_the_earlier_year():
    idx = pd.date_range("2018-01-01", "2021-01-02", freq="D", tz="UTC", name="ts")
    close = pd.Series(100.0, index=idx)
    y = tr.bar_years(idx)
    close[(y == 2019) & (idx.day == 15)] = 200.0  # a round trip: 2019's compounded return is 0
    close[idx >= pd.Timestamp("2020-06-02", tz="UTC")] = 150.0  # 2020: +50%
    kept = idx[1:]
    ret = tr.year_returns(close, kept)
    assert ret[2020] == pytest.approx(0.5, abs=1e-15) and ret[2018] == 0.0
    assert ret[2019] == pytest.approx(0.0, abs=1e-14)
    close2 = close.copy()
    close2[y == 2019] = 100.0
    ranked = tr.boom_years(close2, kept)
    assert ranked == [2020, 2018, 2019, 2021]  # 2018, 2019 and 2021 (one bar) tie at 0: earlier first
    mask = tr.without_years(kept, [2020])
    assert not mask[tr.bar_years(kept) == 2020].any() and mask[tr.bar_years(kept) != 2020].all()
    with pytest.raises(ValueError, match="none of them the first"):
        tr.year_returns(close, idx)
    removals = [{"E1": True, "E2": True, "E3": True, "E4": True}] * 2
    assert tr.boom_holds(removals, tr.E7_ITEMS)
    assert not tr.boom_holds([*removals[:1], {"E1": True, "E2": True, "E3": None, "E4": True}], tr.E7_ITEMS)
    assert tr.E7_ITEMS == ("E1", "E2", "E3", "E4")
    assert tr.SL_E7_ITEMS == ("SL-E1", "SL-E2", "SL-E3", "SL-E4", "SL-T")
    with pytest.raises(ValueError, match="needs the boom-year removals"):
        tr.boom_holds([], tr.E7_ITEMS)


def test_e9_is_reject_only_with_its_25_guarded_shifts():
    shifts = {u: float(u) / 100 for u in range(1, 78)}
    guarded = tr.guarded(shifts, 78)
    assert len(guarded) == 25 and guarded[0] == 0.53 and float(np.median(guarded)) == 0.65
    assert tr.e9_holds(0.66, 1.0, 1.0, guarded)
    assert not tr.e9_holds(0.65, 1.0, 1.0, guarded)  # equal to the median fails
    assert not tr.e9_holds(0.66, 1.4, 1.0, guarded) and not tr.e9_holds(0.66, 1.0, 1.4, guarded)
    assert tr.e9_holds(0.66, 1.32, 1.32, guarded)  # >= half of S and of N0 on validate
    assert not tr.e9_holds(-0.1, -1.0, -1.0, [-0.5])
    junk = {**shifts, **{u: 99.0 for u in range(1, 53)}}  # the leads are never read
    assert tr.guarded(junk, 78) == guarded
    with pytest.raises(ValueError, match="no shift Sharpes"):
        tr.e9_holds(1.0, 1.0, 1.0, [])


def oracle_schedule(panel: pd.DataFrame) -> tr.Schedule:
    """In a coin exactly when its next check-to-check return (open after the check to open after the next check) is
    positive; the last check holds to the last close."""
    idx = panel.index
    windows = tr.fold_windows(idx)
    zeros = [np.zeros((idx.get_loc(w.last) + 1, 2), dtype=np.int8) for w in windows]
    base = tr.stitched_schedule(idx, windows, zeros, [0.5] * 5)
    c = base.checks
    z = np.zeros((len(c), 2), dtype=np.int8)
    for a, asset in enumerate(pf.ASSETS):
        o = panel[(asset, "open")].to_numpy()
        ends = np.append(o[c[1:] + 1], panel[(asset, "close")].iloc[-1])
        z[:, a] = ends / o[c + 1] - 1.0 > 0.0
    return base._replace(z=z)


@pytest.fixture(scope="module")
def oracle():
    panel = tr.random_walk_panel(17)
    schedule = oracle_schedule(panel)
    kept_idx = pd.DatetimeIndex(np.concatenate([w for w in [
        panel.index[(panel.index > win.t0) & (panel.index <= win.last)] for win in tr.fold_windows(panel.index)
    ]]))  # fmt: skip
    series = {
        u: tr.run_span(panel, schedule, limits=LIMITS, costs=COSTS, u=u)["ret"].loc[kept_idx].to_numpy()
        for u in range(260)
    }
    return panel, schedule, kept_idx, series


def test_an_oracle_schedule_ranks_above_every_guarded_shift_and_leads_never_enter(oracle):
    panel, schedule, kept_idx, series = oracle
    assert len(kept_idx) == 1820
    res = tr.e1_test(series[0], series, 260)
    assert res["rank_p"] == 1 / 208 and res["holds"] and res["at_or_above"] == 0
    junk = {**series, **{u: np.full(1820, 0.05) for u in range(1, 53)}}  # leads replaced by arbitrary values
    for keep in (None, tr.without_years(kept_idx, [2019]), tr.without_years(kept_idx, [2019, 2021])):
        a, b = tr.e1_test(series[0], series, 260, keep=keep), tr.e1_test(series[0], junk, 260, keep=keep)
        for key in ("sharpe", "rank_p", "holds", "p95_holds", "p5", "p50", "p95"):
            assert a[key] == b[key]
        np.testing.assert_array_equal(a["draw_sharpes"], b["draw_sharpes"])
    eight = {u: series[u] for u in range(208)}
    junk8 = {**eight, **{u: np.zeros(1820) for u in range(1, 53)}}
    a8, b8 = tr.e1_test(series[0], eight, 208), tr.e1_test(series[0], junk8, 208)
    assert a8["rank_p"] == b8["rank_p"] and a8["n_shifts"] == 155
    sharpes = [stats.annualized_sharpe(s) for s in tr.guarded(series, 78)]
    assert sharpes == [stats.annualized_sharpe(s) for s in tr.guarded(junk, 78)] and len(sharpes) == 25


def test_a_lock_placed_exactly_on_a_coin_s_falls_beats_its_placebo_stops():
    """The placebo oracle: always in at s = 0.5, each coin locked exactly in the weeks its check-to-check return is
    negative. It ranks first among its 207 placebo stops (p = 1/208), so SL-T holds."""
    panel = tr.random_walk_panel(23)
    schedule = oracle_schedule(panel)
    falls = 1 - schedule.z  # the oracle's out-weeks are the weeks that fall
    schedule = schedule._replace(z=np.ones_like(schedule.z), head_z=np.ones_like(schedule.head_z))
    c, n = schedule.checks, len(panel)
    locks = np.zeros((n, 2), dtype=np.int8)
    ends = np.append(c[1:], n)
    for k in range(len(c)):
        locks[c[k] : ends[k]] = falls[k]
    kept_idx = panel.index[np.isin(panel.index, np.concatenate([
        panel.index[(panel.index > w.t0) & (panel.index <= w.last)] for w in tr.fold_windows(panel.index)
    ]))]  # fmt: skip
    r0_phi = tr.run_span(panel, schedule, limits=LIMITS, costs=COSTS, locks=locks)["ret"].loc[kept_idx]
    placebos = {
        u: tr.run_span(panel, schedule, limits=LIMITS, costs=COSTS, locks=locks, u=u, placebo=True)[
            "ret"
        ].loc[kept_idx]
        for u in tr.guarded_offsets(260).tolist()
    }
    res = tr.e1_test(r0_phi.to_numpy(), {u: s.to_numpy() for u, s in placebos.items()}, 260)
    assert res["rank_p"] == 1 / 208 and res["holds"]


def test_e8_and_sl_e8_on_a_binance_style_panel_with_a_later_start(span):
    """Binance: folds 1-4 only, from Binance's own row 0 (2017-08-18); the schedule over their 208 check closes has
    155 guarded shifts; Binance R_0 equals Binance S on fold 1's kept rows; R_0^phi likewise."""
    idx = pd.date_range("2017-08-18", "2023-01-01", freq="D", tz="UTC", name="ts")
    panel = tr.random_walk_panel(31, index=idx)
    windows = span.windows[1:]
    params = FOLD_PARAMS[1:]
    runs = fold_runs(panel, params, windows)
    assert all(r.index[0] == idx[0] for r in runs)
    sch = tr.stitched_schedule(
        idx, windows, [r.attrs["z"] for r in runs], [p["crypto_share"] for p in params]
    )
    assert len(sch.checks) == 208 and len(tr.guarded_offsets(len(sch.checks))) == 155
    r0 = tr.run_span(panel, sch, limits=LIMITS, costs=COSTS)
    k1 = kept(runs[0], windows[0])
    np.testing.assert_array_equal(r0["ret"].loc[k1.index].to_numpy(), k1.to_numpy())
    assert stitched(runs, windows).index.equals(span.kept[364:])  # the Kraken folds 1-4 kept closes
    runs_phi = fold_runs(panel, [{**p, "stop": PHI} for p in params], windows)
    locks = tr.stitched_locks(idx, windows, [r.attrs["locks"] for r in runs_phi])
    r0_phi = tr.run_span(panel, sch, limits=LIMITS, costs=COSTS, locks=locks)
    k1 = kept(runs_phi[0], windows[0])
    np.testing.assert_array_equal(r0_phi["ret"].loc[k1.index].to_numpy(), k1.to_numpy())
    for u in (53, 207):
        shifted = tr.run_span(panel, sch, limits=LIMITS, costs=COSTS, locks=locks, u=u)
        assert tr.same_book_at(runs_phi[0], shifted, windows[0].t0)


# ------------------------------------------------------------------------------------------------ luck statistics


def test_the_active_row_report_equals_overfitting_report_at_row_0(span, tmp_path):
    fn = partial(tr.trend_backtest, limits=LIMITS, costs=COSTS)
    bars = span.panel.iloc[:730]
    for i, (name, n) in enumerate((("trend-a", 5), ("trend-b", 5), ("trend-c", 1))):
        run_study(name, fn, list(tr.SPECS), bars, tmp_path, SearchConfig(n_trials=n, n_workers=1, seed=i))
    oos = stitched(span.runs, span.windows)
    names = ["trend-a", "trend-b", "trend-c"]  # trend-c has one trial: both reports skip it
    wf = {"oos_returns": oos, "wf_efficiency": math.nan, "studies": names, "total_trials": 10}
    rep = overfitting_report(wf, tmp_path)
    full = tr.active_report(names, tmp_path, 0, oos_returns=oos, n_raw=10, n_strict=89)
    assert full["dsr_raw"] == rep["dsr_raw_count"] and full["dsr_effective"] == rep["dsr_effective_count"]
    assert full["trials_effective"] == rep["trials_effective"] and full["pbo_mean"] == rep["pbo_mean"]
    assert tr.g6_statistic(oos) == rep["mc_drawdown_worst5pct"]  # G6's statistic is the report's
    cut = [load_trial_returns(s, tmp_path).iloc[204:].dropna().to_numpy() for s in ("trend-a", "trend-b")]
    active = tr.active_report(["trend-a", "trend-b"], tmp_path, oos_returns=oos, n_raw=10, n_strict=89)
    want = tr.active_stats(cut, oos_returns=oos, n_raw=10, n_strict=89)
    for key in ("dsr_raw", "dsr_effective", "dsr_strict", "trials_effective", "pbo_mean"):
        assert active[key] == want[key], key
    assert active["trial_sharpes"] == want["trial_sharpes"] and len(active["trial_sharpes"]) == 10
    # rows 0 .. 203 are all cash for every trial: the active reading's trial-Sharpe spread is wider
    assert np.var(active["trial_sharpes"]) > np.var(full["trial_sharpes"])
    assert math.isnan(tr.active_report(["trend-a"], tmp_path, 700, oos_returns=oos)["dsr_raw"])


def test_the_active_statistics_by_hand_on_a_matrix_with_shared_zero_rows():
    rng = np.random.default_rng(3)
    m = np.vstack([np.zeros((6, 3)), rng.normal(0.001, 0.02, (40, 3))])
    cut = m[6:]
    oos = rng.normal(0.002, 0.02, 200)
    got = tr.active_stats([cut], oos_returns=oos, n_raw=30)
    sharpes = [stats.sharpe(cut[:, j]) for j in range(3)]
    n_eff = stats.effective_trials(cut)
    assert got["trial_sharpes"] == sharpes and got["trials_effective"] == n_eff
    assert got["pbo_mean"] == stats.pbo(cut, n_blocks=10)["pbo"]
    np.testing.assert_array_equal(got["logits_per_study"][0], stats.pbo(cut, n_blocks=10)["logits"])
    assert got["dsr_effective"] == stats.deflated_sharpe_ratio(oos, sharpes, n_trials=n_eff)["dsr"]
    assert got["dsr_raw"] == stats.deflated_sharpe_ratio(oos, sharpes, n_trials=30)["dsr"]
    assert math.isnan(got["dsr_strict"])
    full = tr.active_stats([m], oos_returns=oos, n_raw=30)
    assert full["trial_sharpes"] != sharpes  # the zero rows shrink every trial Sharpe
    empty = tr.active_stats([], oos_returns=oos, n_raw=30)
    assert empty["trials_effective"] == 1.0 and math.isnan(empty["pbo_mean"]) and math.isnan(empty["dsr_raw"])


def test_g3_and_g4_fail_when_either_reading_fails():
    rep = {"dsr_effective_count": 0.96, "pbo_mean": 0.2}
    act = {"dsr_effective": 0.97, "pbo_mean": 0.25}
    assert tr.g3_g4(rep, act) == {"G3": True, "G4": True}
    assert tr.g3_g4({**rep, "dsr_effective_count": 0.94}, act)["G3"] is False
    assert tr.g3_g4(rep, {**act, "dsr_effective": 0.949})["G3"] is False
    assert tr.g3_g4(rep, {**act, "dsr_effective": math.nan})["G3"] is False
    assert tr.g3_g4({**rep, "pbo_mean": 0.26}, act)["G4"] is False
    assert tr.g3_g4(rep, {**act, "pbo_mean": 0.2500001})["G4"] is False
    assert tr.g3_g4(rep, {**act, "pbo_mean": math.nan})["G4"] is False
    assert gates({"oos_sharpe_annual": 1.0, "dsr_effective_count": 0.95, "pbo_mean": 0.25})["pbo <= 0.25"]


def test_g6_compares_g6_s_statistic_with_the_recorded_budget():
    r = np.random.default_rng(1).normal(0.0005, 0.03, 400)
    draws = mc.block_bootstrap_drawdowns(r, mean_block=20, n_sims=1000, seed=0)
    assert tr.g6_statistic(r) == mc.percentiles(draws, (5,))["p5"]
    assert not tr.g6_holds(-0.33, 0.30) and tr.g6_holds(
        -0.33, 0.40
    )  # the budget recorded, never a typed 0.35
    assert tr.g6_holds(-0.35, 0.35) and not tr.g6_holds(math.nextafter(-0.35, -1.0), 0.35)
    assert not tr.g6_holds(-0.01, None)  # a MISSING budget fails


DYADIC = st.integers(-64, 64).map(lambda k: k / 16.0)


@given(bull=DYADIC, bear=DYADIC, side=DYADIC)
@example(bull=-1 / 16, bear=2.0, side=0.5)  # the negative regime is bull
@example(bull=1.0, bear=-1 / 16, side=1.0)  # bear
@example(bull=0.5, bear=1.0, side=-1 / 16)  # sideways
@example(bull=0.0, bear=0.5, side=0.5)  # both ends: 0 and exactly total / 2
def test_g8_excess_fails_whenever_a_regime_trails_and_passes_exactly_inside_0_to_half(bull, bear, side):
    """G8-excess (M10): with three regimes, "none above half the total" forces "none below 0". Exactly representable
    excesses, so the arithmetic is exact."""
    total = bull + bear + side
    split = {"excess": {"bull": bull, "bear": bear, "sideways": side}, "excess_total": total}
    got = tr.g8_excess_pass(split)
    inside = total > 0 and all(0.0 <= x <= total / 2 for x in (bull, bear, side))
    assert got is inside
    if total > 0 and min(bull, bear, side) < 0:
        assert not got


def test_g8_excess_on_a_regime_split_against_n0():
    idx = pd.date_range("2018-01-02", "2018-04-01", freq="D", tz="UTC", name="ts")
    btc = pd.Series(np.linspace(100.0, 200.0, len(idx)), index=idx)
    table = sd.regime_table(btc, idx[1:])
    s = pd.Series(0.002, index=idx[1:])
    n0 = pd.Series(0.001, index=idx[1:])
    split = sd.regime_split(s, table, benchmark=n0)
    assert tr.g8_excess_pass(split) is (
        split["excess_total"] > 0 and max(split["excess"].values()) <= split["excess_total"] / 2
    )
    with pytest.raises(ValueError, match="needs the N0 benchmark"):
        tr.g8_excess_pass(sd.regime_split(s, table))


def test_h0_slices_start_at_each_panel_s_own_first_row(span):
    for window in span.windows:
        pd.testing.assert_frame_equal(
            tr.h0_slice(span.panel, window), sd.harness_slice(span.panel, window.first_h120, window.last)
        )
    binance = tr.random_walk_panel(
        2, index=pd.date_range("2017-08-18", "2023-01-01", freq="D", tz="UTC", name="ts")
    )
    for window in span.windows[1:]:
        piece = tr.h0_slice(binance, window, like=span.panel)
        assert piece.index[0] == pd.Timestamp("2017-08-18", tz="UTC") and piece.index[-1] == window.last
    with pytest.raises(sd.SliceMismatchError, match="are not the Kraken panel's"):
        tr.h0_slice(binance, span.windows[0], like=span.panel)  # fold 0 holds 2018-01-13 on Binance only
    with pytest.raises(sd.SliceMismatchError, match="no H0 slice that holds"):
        tr.h0_slice(binance.drop(span.windows[2].last), span.windows[2])
    with pytest.raises(sd.SliceMismatchError, match="no H0 slice that holds"):
        tr.h0_slice(binance.drop(span.windows[2].t0), span.windows[2])
    piece = tr.h0_slice(span.panel, span.windows[0])
    t0 = piece.index.get_loc(span.windows[0].t0)
    a = np.zeros((len(piece), 2))
    b = a.copy()
    b[t0 - 1 :] = (0.2, 0.2)  # decided at t0 - 1, filled at the open of t0: the books part at close t0
    ra = tr.run_states(piece, a, limits=LIMITS, costs=COSTS)
    rb = tr.run_states(piece, b, limits=LIMITS, costs=COSTS)
    assert tr.same_book_at(ra, rb, piece.index[t0 - 1]) and not tr.same_book_at(ra, rb, span.windows[0].t0)
    w = span.windows[1]
    on_binance = run(FOLD_PARAMS[1], tr.h0_slice(binance, w))
    assert not tr.same_book_at(on_binance, span.runs[1], w.t0)  # other closes before t0
    assert not tr.same_book_at(run(FOLD_PARAMS[2], tr.h0_slice(span.panel, w)), span.runs[1], w.t0)
    assert tr.same_book_at(run(FOLD_PARAMS[1], tr.h0_slice(span.panel, w)), span.runs[1], w.t0)


# ------------------------------------------------------------------------------------------------ verdicts


ALL_HOLD = dict.fromkeys(tr.CRITERIA, True)


def test_the_mechanical_verdict():
    assert tr.verdict(ALL_HOLD) == {"verdict": "EDGE", "label": "EDGE", "look_earned": True}
    assert tr.verdict({**ALL_HOLD, "E9": True})["verdict"] == "EDGE"
    assert tr.verdict({**ALL_HOLD, "E9": False}) == {
        "verdict": "INCONCLUSIVE",
        "label": "INCONCLUSIVE",
        "look_earned": True,
    }
    for k in ("E1", "E2"):
        got = tr.verdict({**ALL_HOLD, k: False})
        assert got == {"verdict": "NO EDGE", "label": "NO EDGE", "look_earned": False}
        low = tr.verdict({**ALL_HOLD, k: None, "P": False}, switches=12)
        assert low["label"] == "NO EDGE (LOW POWER: 12 switches)" and low["verdict"] == "NO EDGE"
    for k in ("E3", "E4", "E5", "E6", "E7", "E8", "P"):
        got = tr.verdict({**ALL_HOLD, k: False})
        assert got["verdict"] == "INCONCLUSIVE" and not got["look_earned"]  # stop rule 8: no look
        assert tr.verdict({key: v for key, v in ALL_HOLD.items() if key != k})["verdict"] == "INCONCLUSIVE"
    stopped = tr.verdict(ALL_HOLD, stopped=True)
    assert stopped["verdict"] == "INCONCLUSIVE" and not stopped["look_earned"]


def all_points(value=True):
    return dict.fromkeys(tr.measurement_points(), value)


def test_the_measurement_points_are_section_10_s_table():
    points = tr.measurement_points()
    assert len(points) == len(set(points)) == 9 + 9 + 2 + 2 + 16 + 9 + 18 + 6 + 7 + 8  # 86
    by_item = {}
    for item, point in points:
        by_item.setdefault(item, []).append(point)
    grid = [f"grid s={s}" for s in ("0.30", "0.40", "0.50", "0.60")]
    sk = [f"S({s})" for s in ("0.30", "0.40", "0.50", "0.60")]
    assert by_item["G1"] == ["S", *grid, *sk]
    assert by_item["G2"] == [f"{p} at 2x" for p in ["S", *grid, *sk]]
    assert by_item["G3"] == ["S (all rows)", "S (active rows)"]
    assert by_item["G4"] == ["search studies (all rows)", "search studies (active rows)"]
    assert len(by_item["G5"]) == 16 and by_item["G5"][:2] == ["(a) lookback x0.8", "(a) lookback x1.2"]
    assert by_item["G5"][6] == "(b) default lookback x0.8" and by_item["G5"][-1] == "(c) grid s=0.60"
    assert by_item["G6"] == ["S", *grid, *sk]
    assert len(by_item["G7"]) == 18 and "theta_final(A)" not in " ".join(by_item["G7"])
    assert (
        by_item["G8-excess"] == ["S", "default", *grid] and "G8" not in by_item
    )  # G8-excess, not the literal G8
    assert by_item["R1"] == ["S", "theta_final(A)", "default", *grid]
    assert by_item["S(s_k) check"] == [f"{e} at {p}" for p in sk for e in ("E1", "E2")]


def test_every_measurement_point_alone_moves_the_headline_and_is_named():
    edge = tr.verdict(ALL_HOLD)
    assert tr.headline(edge, all_points()) == {"headline": "CANDIDATE FOR AUDIT", "failing": []}
    for key in tr.measurement_points():
        for bad in (False, None):
            got = tr.headline(edge, {**all_points(), key: bad})
            assert got == {"headline": "EDGE, NOT A CANDIDATE", "failing": [f"{key[0]} at {key[1]}"]}
        missing = all_points()
        del missing[key]
        assert tr.headline(edge, missing)["failing"] == [f"{key[0]} at {key[1]}"]
    # points the table does not list never move it: theta_final(A) for G7 or G8, seed B's numbers
    extra = {("G7", "theta_final(A)"): False, ("G8-excess", "theta_final(A)"): False, ("G1", "S_B"): False}
    assert tr.headline(edge, {**all_points(), **extra})["headline"] == "CANDIDATE FOR AUDIT"
    # E1 or E2 failing at one S(s_k) fails the range
    got = tr.headline(edge, {**all_points(), ("S(s_k) check", "E1 at S(0.40)"): False})
    assert got["failing"] == ["S(s_k) check at E1 at S(0.40)"]
    for v in ({**ALL_HOLD, "E1": False}, {**ALL_HOLD, "E3": False}):
        assert tr.headline(tr.verdict(v), all_points()) == {"headline": tr.verdict(v)["label"], "failing": []}
    low = tr.verdict({**ALL_HOLD, "E2": False, "P": False}, switches=7)
    assert tr.headline(low, all_points())["headline"] == "NO EDGE (LOW POWER: 7 switches)"


def test_e5a_compares_the_seeds_on_the_gates_at_s_only():
    a = dict.fromkeys(tr.E5A_ITEMS, True)
    assert tr.e5a_holds(a, dict(a), 1.2, 1.0) == {"differ": [], "sharpes_close": True, "holds": True}
    assert tr.e5a_holds(a, dict(a), 1.25, 1.0)["holds"] and not tr.e5a_holds(a, dict(a), 1.26, 1.0)["holds"]
    # a failure at a grid step only, at the default's plateau or at an S(s_k) leaves E5 unchanged
    extra_a = {**a, "G1 grid s=0.40": False, "G5(b)": False, "G6 S(0.60)": False}
    assert tr.e5a_holds(extra_a, a, 1.0, 1.0)["holds"]
    # a failure of G6 at S_B alone fails E5
    got = tr.e5a_holds(a, {**a, "G6": False}, 1.0, 1.0)
    assert got == {"differ": ["G6"], "sharpes_close": True, "holds": False}
    assert tr.e5a_holds({**a, "G8-excess": False}, {**a, "G8-excess": None}, 1.0, 1.0)["holds"]  # both fail
    assert not tr.e5a_holds(a, a, math.nan, 1.0)["holds"]


def test_the_stop_variant_s_verdict_per_level_and_overall():
    every = dict.fromkeys(tr.SL_ITEMS, True)
    assert tr.stop_verdict(False, {}, 0) == {"verdict": "NOT TRIGGERED", "label": "NOT TRIGGERED"}
    assert tr.stop_verdict(True, every, 4)["verdict"] == "STOP HELPS"
    for k in ("SL-E1", "SL-E2"):
        assert tr.stop_verdict(True, {**every, k: False}, 4)["verdict"] == "NO EDGE"
    for k in ("SL-B", "SL-E3", "SL-T"):  # verdict step 3, each failing alone
        assert tr.stop_verdict(True, {**every, k: False}, 4)["verdict"] == "STOP DOES NOT HELP"
    for k in ("SL-E4", "SL-E5", "SL-E6", "SL-E7", "SL-E8", "SL-P"):  # step 4, each failing alone
        assert tr.stop_verdict(True, {**every, k: False}, 4)["verdict"] == "INCONCLUSIVE"
    low = tr.stop_verdict(True, {**every, "SL-T": False, "SL-P": False}, 2)
    assert low == {"verdict": "STOP DOES NOT HELP", "label": "STOP DOES NOT HELP (LOW POWER: 2 stops)"}
    order = ["NO EDGE", "STOP DOES NOT HELP", "INCONCLUSIVE", "STOP HELPS"]
    for i, worst in enumerate(order):
        assert tr.overall_stop_outcome([*order[i:], "NOT TRIGGERED"]) == worst
    assert tr.overall_stop_outcome(["NOT TRIGGERED"] * 3) == "NOT TRIGGERED"
    assert tr.overall_stop_outcome(["NOT TRIGGERED", "STOP HELPS", "NOT TRIGGERED"]) == "STOP HELPS"
    with pytest.raises(ValueError, match="verdicts must be from"):
        tr.overall_stop_outcome(["STOP HELPS (LOW POWER: 2 stops)"])
    with pytest.raises(ValueError, match="verdicts must be from"):
        tr.overall_stop_outcome([])
    line = tr.stop_level_line("STOP HELPS", "INCONCLUSIVE")
    assert line == "STOP HELPS (not a finding on its own; overall: INCONCLUSIVE)"


def test_the_stop_variant_s_criteria_at_their_boundaries():
    def at(*dates):
        return pd.DatetimeIndex([pd.Timestamp(d, tz="UTC") for d in dates])

    assert not tr.sl_power(at("2018-03-01", "2019-03-01"))["holds"]  # 2 stops
    assert tr.sl_power(at("2018-03-01", "2018-05-01", "2019-03-01")) == {
        "stops": 3,
        "years": 2,
        "holds": True,
    }
    assert not tr.sl_power(at("2018-03-01", "2018-05-01", "2018-07-01"))["holds"]  # 1 bar-year
    assert tr.sl_power(at("2018-03-01", "2018-05-01", "2019-01-01"))["years"] == 1  # 2019-01-01 is a 2018 bar
    base = dict(
        sharpe_phi=1.0, sharpe_s=1.0, sharpe_phi_2x=0.8, sharpe_s_2x=0.8, dd_phi=-0.2, dd_s=-0.3, p5_phi=-0.3,
        p5_s=-0.4, removals=[{"sharpe_phi": 1.0, "sharpe_s": 1.0, "dd_phi": -0.2, "dd_s": -0.3}],
    )  # fmt: skip
    assert tr.sl_b(**base)["holds"]  # (i) and (ii) hold on equal Sharpes
    assert not tr.sl_b(**{**base, "dd_phi": -0.3})["iii"] and not tr.sl_b(**{**base, "dd_phi": -0.3})["holds"]
    assert not tr.sl_b(**{**base, "p5_phi": -0.4})["iv"]  # (iii) and (iv) fail on equal drawdowns
    assert not tr.sl_b(**{**base, "sharpe_phi_2x": 0.79})["ii"]
    worse = [{"sharpe_phi": 0.9, "sharpe_s": 1.0, "dd_phi": -0.2, "dd_s": -0.3}]
    assert not tr.sl_b(**{**base, "removals": worse})["v"]
    deeper = [*base["removals"], {"sharpe_phi": 1.0, "sharpe_s": 1.0, "dd_phi": -0.3, "dd_s": -0.3}]
    assert not tr.sl_b(**{**base, "removals": deeper})["v"]  # (iii) on the two-best removal: equal falls fail
    with pytest.raises(ValueError, match="needs the boom-year removals"):
        tr.sl_b(**{**base, "removals": []})
    s = np.array([0.01, -0.02, 0.0])
    assert not tr.triggered(s.copy(), s) and tr.triggered(s + np.array([0, 0, 1e-17]), s)
    with pytest.raises(ValueError, match="same kept rows"):
        tr.triggered(s[:2], s)
    assert tr.SL_E5_ITEMS == ("triggered", "SL-E1", "SL-E2", "SL-B", "SL-E3", "SL-T")
    assert tr.SL_ITEMS == (
        "SL-E1", "SL-E2", "SL-B", "SL-E3", "SL-T", "SL-E4", "SL-E5", "SL-E6", "SL-E7", "SL-E8", "SL-P",
    )  # fmt: skip
    assert tr.CRITERIA == ("E1", "E2", "E3", "E4", "E5", "E6", "E7", "E8", "P")
    a = {"triggered": True, "SL-E1": True, "SL-E2": False, "SL-B": True, "SL-E3": True, "SL-T": True}
    assert tr.sl_e5_holds(a, dict(a))["holds"]
    for k in ("triggered", "SL-E1", "SL-E2", "SL-B", "SL-E3", "SL-T"):  # SL-E5 reads SL-E3 and SL-T too
        assert tr.sl_e5_holds(a, {**a, k: not a[k]}) == {"differ": [k], "holds": False}
    assert tr.boom_holds([dict.fromkeys(tr.SL_E7_ITEMS, True)] * 2, tr.SL_E7_ITEMS)
    for k in ("SL-E3", "SL-T"):  # SL-E7 reads SL-E3 and SL-T
        assert not tr.boom_holds(
            [dict.fromkeys(tr.SL_E7_ITEMS, True), {**dict.fromkeys(tr.SL_E7_ITEMS, True), k: False}],
            tr.SL_E7_ITEMS,
        )


def test_a_variant_verdict_never_moves_the_plain_rule_s_verdict_or_headline():
    """The variant's verdict is its own line: the verdict and the headline take no stop input, so any stop outcome
    leaves them as they are."""
    edge = tr.verdict(ALL_HOLD)
    before = tr.headline(edge, all_points())
    for criteria in ({}, dict.fromkeys(tr.SL_ITEMS, True), dict.fromkeys(tr.SL_ITEMS, False)):
        for triggered in (False, True):
            tr.stop_verdict(triggered, criteria, 1)
            assert tr.verdict(ALL_HOLD) == edge and tr.headline(edge, all_points()) == before


def test_stop_rule_18_reports_the_less_favourable_run_unless_it_was_found_blind():
    def r(verdict, headline, stop, p1, p2):
        return {"verdict": verdict, "headline": headline, "stop_overall": stop, "e1_rank_p": p1, "e2_p": p2}

    run0 = r("EDGE", "CANDIDATE FOR AUDIT", "STOP HELPS", 0.01, 0.02)
    run1 = r("INCONCLUSIVE", "INCONCLUSIVE", "NO EDGE", 0.03, 0.04)
    for a, b in ((run0, run1), (run1, run0)):
        got = tr.reported_verdict(a, b, "other, after the verdict")
        assert (got["verdict"], got["headline"], got["stop_overall"]) == (
            "INCONCLUSIVE",
            "INCONCLUSIVE",
            "NO EDGE",
        )
        assert not got["superseded"]
        assert got["runs"] == [{"e1_rank_p": x["e1_rank_p"], "e2_p": x["e2_p"]} for x in (a, b)]
    for trigger in ("a", "b", "c"):
        got = tr.reported_verdict(run1, run0, trigger)
        assert got["verdict"] == "EDGE" and got["headline"] == "CANDIDATE FOR AUDIT" and got["superseded"]
        assert len(got["runs"]) == 2
    low = r("NO EDGE", "NO EDGE (LOW POWER: 9 switches)", "NOT TRIGGERED", 0.2, 0.3)
    got = tr.reported_verdict(run0, low, "other, after the verdict")
    assert got["headline"] == "NO EDGE (LOW POWER: 9 switches)" and got["stop_overall"] == "NOT TRIGGERED"
    edge_not = r("EDGE", "EDGE, NOT A CANDIDATE", "INCONCLUSIVE", 0.01, 0.01)
    assert (
        tr.reported_verdict(run0, edge_not, "other, after the verdict")["headline"] == "EDGE, NOT A CANDIDATE"
    )
    tie = r("EDGE", "EDGE, NOT A CANDIDATE", "STOP DOES NOT HELP (LOW POWER: 2 stops)", 0.0, 0.0)
    got = tr.reported_verdict(edge_not, tie, "other, after the verdict")
    assert (
        got["stop_overall"] == "STOP DOES NOT HELP (LOW POWER: 2 stops)"
        and got["headline"] == tie["headline"]
    )
    plain = r("NO EDGE", "NO EDGE", "STOP DOES NOT HELP", 0.3, 0.4)
    low_power = r(
        "NO EDGE", "NO EDGE (LOW POWER: 9 switches)", "STOP DOES NOT HELP (LOW POWER: 2 stops)", 0.5, 0.6
    )
    for a, b in ((plain, low_power), (low_power, plain)):  # equal ranks: the amendment run's strings
        got = tr.reported_verdict(a, b, "other, after the verdict")
        assert (got["headline"], got["stop_overall"]) == (b["headline"], b["stop_overall"])
    for bad in (None, "", "d", "other"):
        with pytest.raises(ValueError, match="must record its trigger"):
            tr.reported_verdict(run0, run1, bad)
    with pytest.raises(ValueError, match="unknown outcome"):
        tr.reported_verdict(run0, r("MAYBE", "MAYBE", "NO EDGE", 0, 0), "other, after the verdict")


# ------------------------------------------------------------------------------------------------ the range


def test_the_default_is_the_allowed_value_nearest_theta_final_s_s_ties_to_the_lower():
    assert [tr.default_share(s) for s in (0.30, 0.31, 0.37, 0.4499, 0.46, 0.58, 0.60)] == [
        0.30, 0.30, 0.40, 0.40, 0.50, 0.60, 0.60,
    ]  # fmt: skip
    assert abs(0.35 - 0.30) != abs(0.40 - 0.35)  # in binary the two distances differ ...
    assert tr.default_share(0.35) == 0.30  # ... by less than 1e-12: a tie, to the lower value
    assert tr.default_share(0.35 + 1e-13) == 0.30 and tr.default_share(0.35 - 1e-13) == 0.30
    assert tr.default_share(0.35 + 2e-12) == 0.40
    assert tr.default_share(0.45) == 0.40 and tr.default_share(0.55) == 0.50
    with pytest.raises(ValueError, match="at least two allowed values"):
        tr.default_share(0.4, (0.4,))


def test_the_riskiest_step_is_the_deepest_p5_ties_to_the_higher_s():
    assert tr.riskiest_step({0.3: -0.2, 0.4: -0.25, 0.5: -0.31, 0.6: -0.30}) == 0.5
    assert tr.riskiest_step({0.3: -0.2, 0.4: -0.31, 0.5: -0.31, 0.6: -0.30}) == 0.5
    assert tr.riskiest_step({0.3: -0.4, 0.6: -0.4}) == 0.6
    with pytest.raises(ValueError, match="finite G6 statistic"):
        tr.riskiest_step({0.3: math.nan})


def values_of(p5, risk=(), other=()):
    return {s: {"p5": v, "risk_fail": s in risk, "other_fail": s in other} for s, v in p5.items()}


def test_narrowing_drops_values_one_at_a_time_from_the_riskiest_end_only_for_a_risk_limit():
    p5 = {0.3: -0.20, 0.4: -0.27, 0.5: -0.33, 0.6: -0.38}
    got = tr.narrowing(values_of(p5, risk=(0.6,)), 0.4, 0.35)
    assert got["status"] == "keeps" and got["kept"] == [0.3, 0.4, 0.5] and got["dropped"] == [0.6]
    assert got["margins"][0][0] == 0.5 and got["margins"][0][1] == pytest.approx(0.02, abs=1e-15)
    assert got["line"] == "narrowing would keep {0.30, 0.40, 0.50}, with margin 0.0200"
    two = tr.narrowing(values_of({**p5, 0.5: -0.36}, risk=(0.5, 0.6)), 0.3, 0.35)
    assert two["kept"] == [0.3, 0.4] and two["dropped"] == [0.6, 0.5] and len(two["margins"]) == 2
    low_end = tr.narrowing(values_of({0.3: -0.5, 0.4: -0.3, 0.5: -0.2, 0.6: -0.1}, risk=(0.3,)), 0.6, 0.35)
    assert low_end["kept"] == [0.4, 0.5, 0.6] and low_end["dropped"] == [0.3]
    drops_default = tr.narrowing(values_of(p5, risk=(0.6,)), 0.6, 0.35)
    assert (
        drops_default["status"] == "fails"
        and drops_default["line"] == "narrowing fails: it would drop the default"
    )
    middle = tr.narrowing(values_of({0.3: -0.2, 0.4: -0.4, 0.5: -0.3, 0.6: -0.3}, risk=(0.4,)), 0.3, 0.35)
    assert middle["status"] == "not possible" and "s = 0.40" in middle["line"]
    middle5 = tr.narrowing(values_of({0.3: -0.2, 0.4: -0.3, 0.5: -0.4, 0.6: -0.3}, risk=(0.5,)), 0.3, 0.35)
    assert middle5["status"] == "not possible"
    sharpe = tr.narrowing(values_of(p5, risk=(0.6,), other=(0.3,)), 0.4, 0.35)
    assert sharpe["status"] == "fails" and "not a risk-limit failure" in sharpe["line"]
    at_s = tr.narrowing(values_of(p5, risk=(0.6,)), 0.4, 0.35, g6_fails_at_s=True)
    assert at_s["status"] == "fails" and "G6 fails at S" in at_s["line"]
    assert tr.narrowing(values_of(p5), 0.4, 0.35)["status"] == "not needed"
    with pytest.raises(ValueError, match="the default must be one of the values"):
        tr.narrowing(values_of(p5), 0.45, 0.35)


def test_the_box_and_every_plateau_step_pass_the_limits_as_read():
    limits = pf.risk_limits("steady")
    assert tr.check_feasibility(limits) == [0.24, 0.3, 0.4, 0.5, 0.6, 0.72]
    for s in tr.ALLOWED_S:
        assert tr.check_share(s, limits) == [(s / 2, s / 2), (s / 2, 0.0), (0.0, s / 2), (0.0, 0.0)]
    with pytest.raises(ValueError, match=r"crypto share 0.8 breaks the limits as read \(stop rule 12\)"):
        tr.check_share(0.8, limits)  # named, so a refusal during a run is recorded as stop rule 12 (#58)
    with pytest.raises(ValueError, match="crypto share 0.72 breaks the limits as read"):
        tr.check_feasibility({"min_cash": 0.2, "max_coin": 0.34})


@given(s=st.floats(0.24, 0.72))
@example(s=0.24)
@example(s=0.72)
def test_every_share_from_the_plateau_s_bottom_to_its_top_is_feasible(s):
    tr.check_share(s, pf.risk_limits("steady"))


def test_plateau_steps_by_hand():
    limits = LIMITS
    assert tr.plateau_step(P(20, 0.05, 0.5), "lookback", 0.8) == (P(16, 0.05, 0.5), "outside the box")
    assert tr.plateau_step(P(20, 0.05, 0.5), "lookback", 1.2) == (P(24, 0.05, 0.5), "inside the box")
    for L, down, up in (
        (1, 1, 2),
        (2, 1, 3),
        (3, 2, 4),
        (4, 3, 5),
        (100, 80, 120),
        (200, 160, 240),
        (13, 10, 16),
    ):
        assert tr.plateau_step(P(L), "lookback", 0.8)[0]["lookback"] == down
        assert tr.plateau_step(P(L), "lookback", 1.2)[0]["lookback"] == up
    assert tr.plateau_step(P(2, 0.1, 0.5), "buffer", 1.2) == (P(2, 0.1 * 1.2, 0.5), "outside the box")
    assert tr.plateau_step(P(2, 0.005, 0.5), "buffer", 0.8)[1] == "outside the box"
    assert tr.plateau_step(P(2, 0.05, 0.6), "crypto_share", 1.2) == (P(2, 0.05, 0.6 * 1.2), "outside the box")
    assert tr.plateau_step(P(2, 0.05, 0.5), "crypto_share", 0.8) == (P(2, 0.05, 0.5 * 0.8), "inside the box")
    assert tr.plateau_step(P(2, 0.05, 0.5, 0.2), "buffer", 0.8)[0]["stop"] == 0.2
    # a step that lands exactly on a box edge is inside the box (both ends inclusive)
    assert tr.plateau_step(P(25), "lookback", 0.8) == (P(20), "inside the box")
    assert tr.plateau_step(P(167), "lookback", 1.2) == (P(200), "inside the box")
    assert 0.5 * 1.2 == 0.6 and tr.plateau_step(P(2, 0.05, 0.5), "crypto_share", 1.2)[1] == "inside the box"
    assert 0.125 * 0.8 == 0.1 and tr.plateau_step(P(2, 0.125, 0.5), "buffer", 0.8)[1] == "inside the box"
    steps = tr.plateau_steps([P(100, 0.05, 0.5), P(200, 0.1, 0.6)], limits)
    assert [(st_["param"], st_["factor"]) for st_ in steps] == [
        (n, f) for n in tr.PARAM_NAMES for f in (0.8, 1.2)
    ]
    assert [st_["mark"] for st_ in steps] == ["inside the box", "outside the box"] * 3
    assert steps[1]["marks"] == ["inside the box", "outside the box"]
    assert steps[5]["params"] == [P(100, 0.05, 0.6), P(200, 0.1, 0.72)]
    with pytest.raises(ValueError, match="crypto share 0.84 breaks"):
        tr.plateau_steps([P(100, 0.05, 0.7)], limits)
    with pytest.raises(ValueError, match="at least one parameter set"):
        tr.plateau_steps([], limits)
    with pytest.raises(ValueError, match="name must be one of"):
        tr.plateau_step(P(), "stop", 0.8)
    with pytest.raises(ValueError, match="factor must not be 1"):
        tr.plateau_step(P(), "buffer", 1.0)


# ------------------------------------------------------------------------------------------------ orders in time


def test_trade_frequency_and_r1_by_hand():
    """Fills at days 5, 10 and 35 of a 60-day kept span (switches 2, 0 and 1; legs 2, 1 and 1), with day 20 missing:
    the 30-day window (t - 30 days, t] leaves out its first end and keeps its last."""
    idx = days(61, "2018-01-01")
    grid = idx.drop(idx[20])  # the panel lacks day 20
    kept_idx = grid[1:]
    log = pd.DataFrame(
        {
            "filled": idx[[5, 10, 35]],
            "decided": idx[[4, 9, 34]],
            "reason": ["switch", "limit", "switch"],
            "switches": [2, 0, 1],
            "legs": [2, 1, 1],
        }
    )
    count = tr.rolling_order_count(log, kept_idx)
    by_day = dict(zip(kept_idx, count.tolist(), strict=True))
    assert by_day[idx[4]] == 0 and by_day[idx[5]] == 1 and by_day[idx[10]] == 2
    assert by_day[idx[34]] == 2 and by_day[idx[35]] == 2  # day 5 = 35 - 30 is outside, day 35 inside
    assert by_day[idx[39]] == 2 and by_day[idx[40]] == 1 and by_day[idx[60]] == 1
    freq = tr.trade_frequency(log, kept_idx)
    switches = tr.rolling_count(log["filled"], kept_idx, log["switches"])
    assert switches[kept_idx.get_loc(idx[34])] == 2 and switches[kept_idx.get_loc(idx[36])] == 1
    assert freq["fills"] == {"median": float(np.median(count)), "worst": 2.0}
    assert (
        freq["switches"]["worst"] == 2.0 and freq["legs"]["worst"] == 3.0
    )  # days 10 .. 34: 2 + 0; legs 2 + 1
    other = tr.trade_frequency(log.assign(switches=[0, 0, 1]), kept_idx)  # fills are never weighted (#58)
    assert other["fills"] == freq["fills"] and other["switches"]["worst"] == 1.0
    covered = tr.covered_days(grid, kept_idx)
    assert covered == 60.0  # the row after the missing day 20 covers 2 days
    assert tr.covered_days(idx, kept_idx) == 59.0  # on a panel with day 20, its bar is simply not kept
    r1 = tr.r1_check(log, kept_idx, covered)
    assert r1 == {"orders": 3, "mean": 30 * 3 / 60.0, "most": 2, "holds": True}
    busy = pd.DataFrame({"filled": idx[[1, 2, 3, 4, 5, 6]], "switches": [0] * 6, "legs": [1] * 6})
    assert (
        tr.r1_check(busy, kept_idx, covered)["most"] == 6
        and not tr.r1_check(busy, kept_idx, covered)["holds"]
    )
    five = busy.iloc[:5]
    assert tr.r1_check(five, kept_idx, 75.0)["holds"] and not tr.r1_check(five, kept_idx, 74.0)["holds"]
    with pytest.raises(ValueError, match="none of them the first"):
        tr.covered_days(idx, idx)
    with pytest.raises(ValueError, match="one weight per time"):
        tr.rolling_count(idx[[1, 2]], kept_idx, [1.0])


def test_the_order_log_of_a_run():
    idx = days(230)
    btc = path(230, r203=300.0, r205=330.0)
    eth = path(230, r203=300.0, r210=100.0)
    res = run(P(2, 0.1, 0.5), panel_on(idx, btc, eth))
    log = tr.order_log(res)
    assert log["filled"].tolist() == [idx[204], idx[211]] and log["decided"].tolist() == [idx[203], idx[210]]
    assert log["reason"].tolist() == ["switch", "switch"] and log["switches"].tolist() == [2, 1]
    assert log["legs"].tolist() == [2, 2]
    assert tr.order_log(res, idx[204])["filled"].tolist() == [idx[211]]
    broken = res.copy()
    broken.attrs = {**res.attrs, "orders": np.array([203], dtype=np.int64)}
    with pytest.raises(ValueError, match="a fill row without an order"):
        tr.order_log(broken)


def test_the_projection_guard_by_hand():
    timings = {"study": 6.0, "run": 0.015, "stop_run": 0.08, "bootstrap": 1.5}
    counts = {"study": 12, "run": 3000, "stop_run": 30, "bootstrap": 35}
    minutes = tr.project_cpu_minutes(timings, counts)
    assert minutes == pytest.approx((72.0 + 45.0 + 2.4 + 52.5) / 60.0, rel=1e-15)
    assert tr.projection_allows(60.0, tr.RUN_BUDGET_MINUTES) and not tr.projection_allows(60.000001, 60)
    assert tr.projection_allows(120.0, tr.CONTROLS_BUDGET_MINUTES)
    with pytest.raises(ValueError, match="exactly the keys"):
        tr.project_cpu_minutes({**timings, "extra": 1.0}, counts)
    with pytest.raises(ValueError, match="timing run must be in"):
        tr.project_cpu_minutes({**timings, "run": -1.0}, counts)
    with pytest.raises(ValueError, match="stop_run must be an integer >= 0"):
        tr.project_cpu_minutes(timings, {**counts, "stop_run": 1.5})


def test_small_helpers_refuse_bad_input():
    with pytest.raises(ValueError, match="crypto_share must be in"):
        tr.share_targets(1.5)
    with pytest.raises(ValueError, match="f must be in"):
        tr.share_targets(0.5, f=-0.1)
    assert tr.share_targets(0.5, f=0.75) == (0.375, 0.125)
    z = np.ones((3, 2), dtype=np.int8)
    want = [[s * 0.75, s * (1.0 - 0.75)] for s in (0.2, 0.4, 0.6)]  # the products as computed, per row
    np.testing.assert_array_equal(tr.in_force(z, [0.2, 0.4, 0.6], f=0.75), want)
    with pytest.raises(ValueError, match="crypto_share must be in \\[0, 1\\]"):
        tr.in_force(z, 1.2)
    with pytest.raises(ValueError, match=r"z must be a \(3, 2\) array of 0 and 1"):
        tr.in_force(z * 2, 0.5)
    with pytest.raises(ValueError, match="u must be an integer"):
        tr.segment_source_rows(days(30), [7, 14], 1.0)
    with pytest.raises(ValueError, match="increasing rows"):
        tr.segment_source_rows(days(30), [14, 7], 1)


# ------------------------------------------------------------------------------------------------ the generators


def test_the_calibration_and_volatility_clustering_generators_are_pinned():
    """The slow calibration panel and A0's volatility-clustering panel j = 0, by hand: their first innovations and
    closes, on the train grid."""
    walk = tr.random_walk_panel(0)
    g = np.random.default_rng(0).standard_normal((2190, 2))
    r0 = (0.001 + 0.04 * g[0, 0], 0.001 + 0.05 * (0.8 * g[0, 0] + 0.6 * g[0, 1]))
    assert walk.index.equals(tr.train_grid())
    assert walk[("BTC", "close")].iloc[0] == 10_000.0 * math.exp(r0[0])
    assert walk[("ETH", "close")].iloc[0] == 500.0 * math.exp(r0[1])
    assert walk[("BTC", "open")].iloc[0] == walk[("BTC", "close")].iloc[0]
    assert walk[("ETH", "open")].iloc[1] == walk[("ETH", "close")].iloc[0]
    assert (walk.xs("volume", axis=1, level="field") == 1.0).all().all()
    garch = tr.garch_panel(0)
    x = np.random.default_rng(10_000).standard_t(5, size=(2190, 2)) / math.sqrt(5 / 3)
    eth0 = 0.8 * x[0, 0] + 0.6 * x[0, 1]
    var0 = 0.02 + 0.08 * 0.0 + 0.90 * 1.0  # omega + alpha * 0 + beta * 1 = 0.92
    g0 = (math.sqrt(var0) * x[0, 0], math.sqrt(var0) * eth0)
    var1 = 0.02 + 0.08 * g0[0] ** 2 + 0.90 * var0
    g1 = math.sqrt(var1) * x[1, 0]
    assert garch[("BTC", "close")].iloc[0] == pytest.approx(
        10_000.0 * math.exp(0.001 + 0.04 * g0[0]), rel=1e-15
    )
    assert garch[("ETH", "close")].iloc[0] == pytest.approx(500.0 * math.exp(0.001 + 0.05 * g0[1]), rel=1e-15)
    assert garch[("BTC", "close")].iloc[1] == pytest.approx(
        10_000.0 * math.exp(0.001 + 0.04 * g0[0] + 0.001 + 0.04 * g1), rel=1e-14
    )
    assert not tr.garch_panel(1).equals(garch)


# ------------------------------------------------------------------------------------------------ calibration (slow)


@pytest.mark.slow
@pytest.mark.parametrize(("lookback", "buffer"), [(50, 0.02), (200, 0.10)])
def test_e1_s_false_positive_rate_on_driftful_random_walks(lookback, buffer):
    """Section 9: on 200 iid Gaussian random-walk panels (seeds 0..199), the fixed rule at s = 0.50 runs in H0 as one
    span from row 0; its schedule over the 260 Monday checks of the fold layout is R_0, scored on the 1820 kept rows
    against its 207 guarded shifts at 1x costs, with E1's rank-p rule. At most 18 of 200 panels may pass."""
    idx = tr.train_grid()
    windows = tr.fold_windows(idx)
    kept_rows = np.concatenate([np.flatnonzero((idx > w.t0) & (idx <= w.last)) for w in windows])
    assert len(kept_rows) == 1820
    offsets = tr.guarded_offsets(260)
    passes = 0
    for seed in range(200):
        panel = tr.random_walk_panel(seed)
        z = tr.trend_states(panel, lookback, buffer).z
        zs = [z[: idx.get_loc(w.last) + 1] for w in windows]
        sch = tr.stitched_schedule(idx, windows, zs, [tr.S_SHARE] * 5)
        series = {
            u: tr.run_span(panel, sch, limits=LIMITS, costs=COSTS, u=int(u))["ret"].to_numpy()[kept_rows]
            for u in [0, *offsets.tolist()]
        }
        passes += tr.e1_test(series[0], series, 260)["holds"]
    assert passes <= 18, passes


def test_the_two_day_row_of_2018_01_13_on_the_rebuilt_grid():
    """Close 2018-01-13 is dropped (no ETH bar): the L-row average across it spans L + 1 days (rows, not days), the
    row of 2018-01-14 returns over two days, and the Monday checks are unaffected."""
    panel = tr.random_walk_panel(5)
    idx = panel.index
    row = idx.get_loc(pd.Timestamp("2018-01-14", tz="UTC"))
    assert idx[row - 1] == pd.Timestamp("2018-01-12", tz="UTC")
    close = panel[("BTC", "close")].to_numpy()
    for lookback in (2, 5, 50):
        window = close[row - lookback + 1 : row + 1].tolist()
        assert tr.sma(close, lookback)[row] == math.fsum(window) / lookback
        assert idx[row] - idx[row - lookback + 1] == pd.Timedelta(days=lookback)  # L rows span L + 1 days
    res = run(P(5, 0.0, 0.5), panel)
    w = res[["w_BTC", "w_ETH"]].to_numpy()[row - 1]
    c = panel.xs("close", axis=1, level="field").to_numpy()
    if res["turnover"].iloc[row] == 0.0:  # no fill on that bar: the plain two-day return of the book
        r = c[row] / c[row - 1] - 1.0
        assert res["ret"].iloc[row] == pytest.approx(w[0] * r[0] + w[1] * r[1], rel=1e-12, abs=1e-15)
    monday = idx.get_loc(pd.Timestamp("2018-01-15", tz="UTC"))
    assert monday in tr.check_closes(idx, 0, tr.R0) and monday - 1 == row
