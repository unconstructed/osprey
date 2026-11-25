"""keep-risk-steady (``lab/runner/keeprisk.py``, scouting only): the rule, its executor, the live stream, the
yardsticks, the measures, the luck control (RISK-X with Holm, E1 on exposure-neutral copies, the equivalence reading),
the labels and the rules D1-D3 of ``research/keep-risk-steady/PLAN.md`` (the section 12 test list).

Synthetic data and hand-built paths only: no catalog bar is read. Where a boundary needs an exact weight, the engine is
replaced by a stub that hands the rule chosen weights (the rule's decisions are the subject there); everywhere else
the real ``portfolio._simulate`` runs, and the accounting is checked against ``test_trend.vector_book``, a book of coin
units and cash written in the tests.
"""

from __future__ import annotations

import math
from dataclasses import replace
from fractions import Fraction
from functools import partial

import numpy as np
import pandas as pd
import pytest
from hypothesis import example, given
from hypothesis import strategies as st
from test_portfolio import random_bars, tamper_from
from test_trend import vector_book

from lab.data.synthetic import synthetic_market
from lab.runner import keeprisk as K
from lab.runner import portfolio as pf
from lab.runner import protect as P
from lab.runner import trend as T
from lab.runner import volsteady as V
from lab.runner.interface import validate_result
from lab.runner.reference import Costs
from lab.validation.montecarlo import stationary_bootstrap_indices

LIM = {"min_cash": 0.20, "max_coin": 0.60}  # Steady's limits (section 4; test_portfolio pins the real file)
COSTS = Costs.from_yaml(capital_usd=5000.0)
COSTS_2X = COSTS.stressed(2.0)
ZERO = replace(Costs.zero(), capital_usd=5000.0)
DAY_US = 86_400_000_000
UP, DOWN = math.inf, -math.inf

# ------------------------------------------------------------------------------------------------ helpers


def days(n: int, start: str = "2017-01-02") -> pd.DatetimeIndex:
    return pd.date_range(start, periods=n, freq="D", tz="UTC", name="ts")


def bars_on(index, closes, opens=None) -> pd.DataFrame:
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


def panel_on(index, btc, eth=None) -> pd.DataFrame:
    eth = btc if eth is None else eth
    return pf.make_panel({"BTC": bars_on(index, btc), "ETH": bars_on(index, eth)}, snapshot_id="hand")


def rand_panel(n: int, seed: int, start: str = "2017-01-02", scale: float = 1.0, drop=()) -> pd.DataFrame:
    """Random bars with overnight gaps on daily closes from ``start``, closes ``drop`` (row numbers) removed."""
    idx = days(n, start)
    frames = {}
    for i, (asset, vol, p0) in enumerate((("BTC", 0.04, 30_000.0), ("ETH", 0.05, 2_000.0))):
        bars = random_bars(n, seed + i, vol * scale, 0.01, p0)
        bars.index = idx
        frames[asset] = bars.drop(index=idx[list(drop)])
    return pf.make_panel(frames, snapshot_id="test-panel")


def nxt(x: float, toward: float) -> float:
    return float(np.nextafter(x, toward))


def qpath_of(q, checks=(), q_on=None) -> K.QPath:
    q = np.asarray(q, dtype=float)
    c = np.asarray(checks, dtype=np.int64)
    return K.QPath(q, c, q[c], np.full(len(c), np.nan), float(q[0] if q_on is None else q_on), math.nan, 0)


def rule(panel, w=0.08, s=0.5, f=0.5, costs=ZERO, start=0, stop=None, band=K.BAND):
    qp = K.q_path(panel, w, f, start=start, stop=stop)
    bars = panel.iloc[start:stop]
    res = K.ride_run(bars, K.rule_targets(qp.q, s, f), limits=LIM, costs=costs, band=band)
    return qp, res


def fake_simulate(weights):
    """A stand-in for ``portfolio._simulate`` that hands ``decide`` the given weights at each close."""

    def sim(bars, costs, decide):
        n = len(bars)
        orders = [t for t in range(n) if decide(t, tuple(weights[t])) is not None and t < n - 1]
        res = pd.DataFrame({"ret": np.zeros(n)}, index=bars.index)
        res.attrs["orders"] = np.asarray(orders, dtype=np.int64)
        return res

    return sim


def by_hand_sigma(x, c, lookback=14) -> float:
    window = [float(v) for v in x[c - lookback + 1 : c + 1]]
    mean = math.fsum(window) / lookback
    return math.sqrt(365.0) * math.sqrt(math.fsum((v - mean) ** 2 for v in window) / (lookback - 1))


# ------------------------------------------------------------------------------------------------ pinned values


def test_the_pinned_values_are_the_plan_s():
    assert K.W_VALUES == (0.08, 0.10, 0.12, 0.15) and K.LOOKBACK == 14 and K.DESCRIBE_LOOKBACKS == (7, 28)
    assert (
        K.MIXES == tuple((s, f) for s in (0.30, 0.40, 0.50, 0.60) for f in (0.50, 0.75)) and len(K.MIXES) == 8
    )
    assert (K.BAND, K.WEEKDAY, K.HEADROOM, K.DEPOSIT, K.SMALL_DEPOSIT) == (0.25, 0, 0.02, 5000.0, 500.0)
    assert (K.STEADY_MIN_CASH, K.STEADY_MAX_COIN) == (0.20, 0.60)
    assert [round(K.level(w), 4) for w in K.W_VALUES] == [0.5777, 0.7221, 0.8665, 1.0832]  # section 5.3
    assert K.level(0.10) == 0.10 * math.sqrt(365.0 / 7.0)
    assert (K.MEAN_BLOCK, K.RESAMPLES, K.RESAMPLE_SEED, K.ALPHA) == (60, 10_000, 0, 0.05)
    assert K.EQ_BOUND == math.log(0.9) and K.COST_MARGIN == 0.02 and K.COST_MARGIN_POINTS == 2.0
    assert (K.LEAD_GUARD, K.REBOUND_DAYS, K.BOOM_MIN_WINDOWS) == (52, 90, 12)
    assert K.LABELS == (
        "MISSING",
        "DOES NOT STEP BACK",
        "ROUGHER THAN HOLDING LESS",
        "CALMER THAN HOLDING LESS",
        "SMALLER, BUT BELOW NOTICE",
        "NO NOTICEABLE DIFFERENCE",
        "CAN'T TELL",
    )
    assert K.REASONS == ("first", "step", "drift", "limit") and K.YARDSTICK_REASONS == (
        "first",
        "drift",
        "limit",
    )


def test_every_target_of_the_grid_passes_the_steady_limits_with_headroom():
    margins = []
    for s, f in K.MIXES:
        tg = K.rule_targets((1.0, 0.75, 0.5, 0.25, 0.0), s, f)
        for q, (b, e) in zip((1.0, 0.75, 0.5, 0.25, 0.0), tg.tolist(), strict=True):
            assert (b, e) == (s * q * f, s * q * (1.0 - f))
            pf.check_targets(b, e, min_cash=0.20, max_coin=0.60, headroom=0.02)
            margins.append(min(0.58 - b, 0.58 - e, (1.0 - b - e) - 0.22))
    assert min(margins) == pytest.approx(0.13)  # s 0.60, f 0.75, q 1 (section 14)
    for x in np.arange(0, 601) / 1000.0:  # X's share in [0, 0.60]
        for f in K.F_VALUES:
            pf.check_targets(x * f, x * (1 - f), min_cash=0.20, max_coin=0.60, headroom=0.02)


# ------------------------------------------------------------------------------------------------ the signal


def test_basket_returns_by_hand_and_at_an_even_split_vol_steady_s():
    p = panel_on(days(3), [100.0, 110.0, 99.0], [100.0, 95.0, 100.0])
    x = K.basket_returns(p, 0.75)
    assert math.isnan(x[0])
    assert x[1] == math.log1p(0.75 * (110.0 / 100.0 - 1.0) + 0.25 * (95.0 / 100.0 - 1.0))
    assert x[2] == math.log1p(0.75 * (99.0 / 110.0 - 1.0) + 0.25 * (100.0 / 95.0 - 1.0))
    with pytest.raises(ValueError, match="f must be in"):
        K.basket_returns(p, 1.5)


@given(seed=st.integers(0, 10_000), n=st.integers(20, 80), miss=st.booleans())
def test_at_f_half_the_basket_and_the_swing_are_vol_steady_s_bit_for_bit(seed, n, miss):
    p = rand_panel(n, seed, drop=(n // 2,) if miss else ())
    x = K.basket_returns(p, 0.5)
    assert np.array_equal(x, V.basket_returns(p), equal_nan=True)
    assert np.array_equal(K.swing(p, 0.5), V.sigma_hat(x, 14), equal_nan=True)


def test_sigma_by_hand_over_exactly_its_14_returns():
    p = rand_panel(60, 3)
    for f in K.F_VALUES:
        x = K.basket_returns(p, f)
        sig = K.swing(p, f)
        assert np.isnan(sig[:14]).all()
        for c in range(14, 60):
            assert sig[c] == by_hand_sigma(x, c)  # ddof 1, sqrt(365), rows c-13 .. c
            assert sig[c] == pytest.approx(
                float(np.std(x[c - 13 : c + 1], ddof=1)) * math.sqrt(365.0), rel=1e-12
            )
        assert K.swing(p, f, lookback=7)[7] == by_hand_sigma(x, 7, 7)


def test_q_at_its_edges():
    tau = K.level(0.10)
    assert K._q(4.0, 3.0) == 0.75  # tau / sigma exactly 0.75
    assert K._q(nxt(4.0, UP), 3.0) == 0.75  # one ulp below the quarter: inside the 1e-9 tolerance
    assert K._q(4.0 * (1.0 + 1e-9), 3.0) == 0.5  # beyond it: the next one down, a floor
    for k, q in ((2.0, 0.5), (4.0, 0.25)):
        assert K._q(k * tau, tau) == q
        assert K._q(nxt(k * tau, UP), tau) == q
        assert K._q(k * tau * (1.0 + 1e-9), tau) == q - 0.25
    assert K._q(4.0 * tau * (1.0 + 1e-9), tau) == 0.0
    assert K._q(tau / 0.74, tau) == 0.5  # 0.74 floors to 0.5 (rounding would give 0.75)
    assert K._q(0.0, tau) == 1.0 and K._q(tau, tau) == 1.0 and K._q(tau / 2.0, tau) == 1.0


def test_q_path_with_a_sigma_put_in_steps_at_its_edges():
    p = rand_panel(50, 1)  # 2017-01-02 is a Monday: checks at rows 14, 21, 28, 35, 42, 49
    tau = K.level(0.12)
    sig = np.full(50, np.nan)
    sig[14:] = 0.5 * tau
    sig[21], sig[28], sig[35], sig[42], sig[49] = (
        2.0 * tau,
        nxt(2.0 * tau, UP),
        2.0 * tau * (1 + 1e-9),
        0.0,
        9e9,
    )
    qp = K.q_path(p, 0.12, 0.5, sigma=sig)
    assert qp.checks.tolist() == [14, 21, 28, 35, 42, 49]
    assert qp.q_checks.tolist() == [1.0, 0.5, 0.5, 0.25, 1.0, 0.0]
    assert qp.q.tolist() == [1.0] * 21 + [0.5] * 14 + [0.25] * 7 + [1.0] * 7 + [0.0]
    flat = panel_on(days(40), [100.0] * 40)
    assert (K.q_path(flat, 0.08, 0.5).q == 1.0).all()  # sigma = 0 gives q = 1
    calm = K.q_path(rand_panel(200, 2), 100.0, 0.75)
    assert (calm.q == 1.0).all() and len(calm.checks) == 27  # tau above every sigma never steps


def test_the_switch_on_decision():
    p = rand_panel(60, 5, scale=3.0, start="2017-01-04")  # a Wednesday; Mondays at rows 5, 12, 19, ...
    sig = K.swing(p, 0.5)
    tau = K.level(0.08)
    on = K.q_path(p, 0.08, 0.5, start=20)  # row 20 (a Tuesday), 20 returns of history
    assert on.q_on == K._q(sig[20], tau) < 1.0 and on.sigma_on == sig[20]
    assert on.checks.tolist() == [6, 13, 20, 27, 34]  # panel rows 26, 33, ... (> 20)
    assert (on.q[:6] == on.q_on).all() and on.start == 20
    early = K.q_path(p, 0.08, 0.5, start=13)  # 13 returns: q = 1 until the first Monday check (row 19)
    assert early.q_on == 1.0 and math.isnan(early.sigma_on)
    assert early.checks[0] == 19 - 13 and (early.q[:6] == 1.0).all() and early.q[6] == K._q(sig[19], tau)
    monday = K.q_path(p, 0.08, 0.5, start=19)  # a Monday at row >= 14: one decision there, the switch-on
    assert monday.q_on == K._q(sig[19], tau) and monday.checks[0] == 7
    window0 = K.q_path(
        pf.make_panel(_train_frames(9), snapshot_id="t"), 0.08, 0.5, stop=731
    )  # Kraken window 0
    assert window0.q_on == 1.0 and window0.checks[0] == 14 and (window0.q[:14] == 1.0).all()


def _train_frames(seed: int) -> dict:
    grid = T.train_grid()
    out = {}
    for asset, bars in synthetic_market(2190, seed=seed, start="2017-01-02").items():
        bars = bars.copy()
        bars.index = grid
        out[asset] = bars
    return out


def test_q_path_refuses_bad_runs():
    p = rand_panel(30, 1)
    for kw, msg in (
        ({"start": 29}, "not a run"),
        ({"stop": 31}, "not a run"),
        ({"sigma": np.zeros(5)}, "one value per close"),
        ({"lookback": 1}, "lookback must be"),
    ):
        with pytest.raises(ValueError, match=msg):
            K.q_path(p, 0.1, 0.5, **kw)
    with pytest.raises(ValueError, match="w must be in"):
        K.level(0.0)


def test_q_hash_moves_with_the_path():
    p = rand_panel(60, 4, scale=3.0)
    a, b = K.q_path(p, 0.08, 0.5), K.q_path(p, 0.15, 0.5)
    assert K.q_hash(a) == K.q_hash(K.q_path(p, 0.08, 0.5)) and K.q_hash(a) != K.q_hash(b)


# ------------------------------------------------------------------------------------------------ live and batch


@given(
    seed=st.integers(0, 10_000),
    n=st.integers(20, 70),
    start=st.integers(0, 60),
    w=st.sampled_from(K.W_VALUES),
    f=st.sampled_from(K.F_VALUES),
    miss=st.booleans(),
    weekday=st.sampled_from(["2017-01-02", "2017-01-05"]),
)
@example(seed=1, n=40, start=0, w=0.08, f=0.5, miss=True, weekday="2017-01-02")
@example(seed=2, n=40, start=13, w=0.08, f=0.75, miss=False, weekday="2017-01-02")
@example(seed=3, n=40, start=14, w=0.08, f=0.5, miss=False, weekday="2017-01-02")
def test_the_live_stream_gives_the_batch_q_on_every_close(seed, n, start, w, f, miss, weekday):
    p = rand_panel(n, seed, start=weekday, scale=2.0, drop=(n // 3,) if miss else ())
    start = min(start, len(p) - 2)
    qp = K.q_path(p, w, f, start=start)
    stream = K.KeepRiskStream(w, f)
    cb, ce = (p[(a, "close")].to_numpy() for a in pf.ASSETS)
    for t in range(start):
        assert stream.update(p.index[t], cb[t], ce[t]) is None
    stream.update(p.index[start], cb[start], ce[start])
    assert stream.switch_on() == qp.q_on == stream.q
    for t in range(start + 1, len(p)):
        assert stream.update(p.index[t], cb[t], ce[t]) == qp.q[t - start]
        if t - start in qp.checks.tolist():
            k = qp.checks.tolist().index(t - start)
            assert stream.sigma == qp.sigma_checks[k]


def test_the_live_stream_refuses_bad_closes():
    s = K.KeepRiskStream(0.1, 0.5)
    with pytest.raises(ValueError, match="feed the switch-on close"):
        s.switch_on()
    with pytest.raises(ValueError, match="tz-aware"):
        s.update(pd.Timestamp("2017-01-02"), 1.0, 1.0)
    s.update(pd.Timestamp("2017-01-02", tz="UTC"), 1.0, 1.0)
    with pytest.raises(ValueError, match="strictly increasing"):
        s.update(pd.Timestamp("2017-01-02", tz="UTC"), 1.0, 1.0)
    s.switch_on()
    with pytest.raises(ValueError, match="switch on once"):
        s.switch_on()


# ------------------------------------------------------------------------------------------------ the executor


def test_the_first_buy_fills_at_the_next_open_and_an_all_usdc_start_sends_no_order():
    p = rand_panel(30, 6, scale=0.1)  # calm prices: no drift order
    _, res = rule(p, w=100.0, s=0.5, f=0.75, costs=COSTS)
    assert res.attrs["orders"].tolist() == [0] and res.attrs["reasons"].tolist() == ["first"]
    assert (
        res["turnover"].iloc[1] > 0 and res["turnover"].iloc[0] == 0 and res.attrs["fills"]["bar"].min() == 1
    )
    q = [0.0] * 14 + [0.5] * 16  # all USDC through the Monday at row 7: no order there; the first is a step
    res = K.run_rule(p, qpath_of(q, (7, 14)), 0.4, 0.5, limits=LIM, costs=ZERO)
    assert res.attrs["orders"].tolist() == [14] and res.attrs["reasons"].tolist() == ["step"]


@pytest.mark.parametrize("side", ["above", "below"])
def test_the_band_is_relative_strict_and_judged_only_at_a_monday(monkeypatch, side):
    idx = days(16)  # Mondays at rows 0, 7, 14
    p = panel_on(idx, [100.0] * 16)
    edge = 0.3125 if side == "above" else 0.1875  # 0.25 x (1 +- 0.25), exactly
    beyond = nxt(edge, UP if side == "above" else DOWN)
    weights = [(0.25, 0.25)] * 16
    weights[3] = (beyond, 0.25)  # a Thursday: never a drift order
    weights[7] = (edge, 0.25)  # exactly b T away: no order
    weights[14] = (beyond, 0.25)  # one ulp more: a drift order
    monkeypatch.setattr(K, "_simulate", fake_simulate(weights))
    res = K.ride_run(p, K.constant_targets(0.5, 16, 0.5), limits=LIM, costs=ZERO)
    assert res.attrs["orders"].tolist() == [0, 14] and res.attrs["reasons"].tolist() == ["first", "drift"]


def test_a_coin_with_target_0_never_orders_and_an_infinite_band_never_drifts(monkeypatch):
    p = panel_on(days(15), [100.0] * 15)
    weights = [(0.3, 0.0)] * 15
    weights[7] = (0.3, 0.45)  # far from its target 0, judged against b x 0
    monkeypatch.setattr(K, "_simulate", fake_simulate(weights))
    tg = np.tile([0.3, 0.0], (15, 1))
    assert K.ride_run(p, tg, limits=LIM, costs=ZERO).attrs["orders"].tolist() == [0]
    weights[7] = (0.5, 0.0)
    assert K.ride_run(p, tg, limits=LIM, costs=ZERO).attrs["orders"].tolist() == [0, 7]
    assert K.ride_run(p, tg, limits=LIM, costs=ZERO, band=math.inf).attrs["orders"].tolist() == [0]


def test_a_limit_breach_on_a_thursday_is_fixed_at_that_close():
    btc = [100.0] * 20
    btc[3:] = [200.0] * 17  # row 3 (2017-01-05, a Thursday): BTC doubles
    p = panel_on(days(20), btc, [100.0] * 20)
    res = K.ride_run(p, K.constant_targets(0.6, 20, 0.75), limits=LIM, costs=ZERO)
    assert res["w_BTC"].iloc[3] == pytest.approx(0.9 / 1.45) and res["w_BTC"].iloc[3] > 0.60
    assert res.attrs["orders"].tolist() == [0, 3] and res.attrs["reasons"].tolist() == ["first", "limit"]
    assert res["w_BTC"].iloc[4] == pytest.approx(0.45)  # restored at the next open


def test_a_breach_and_a_step_on_one_monday_give_one_order():
    btc = [100.0] * 20
    btc[7:] = [200.0] * 13  # row 7 (2017-01-09, a Monday): BTC doubles, and q steps down the same close
    p = panel_on(days(20), btc, [100.0] * 20)
    q = [1.0] * 7 + [0.5] * 13
    res = K.run_rule(p, qpath_of(q, (7, 14)), 0.6, 0.75, limits=LIM, costs=ZERO)
    assert res["w_BTC"].iloc[7] > 0.60
    assert res.attrs["orders"].tolist() == [0, 7] and res.attrs["reasons"].tolist() == ["first", "step"]
    assert res.attrs["order_targets"][1].tolist() == [0.6 * 0.5 * 0.75, 0.6 * 0.5 * 0.25]


def test_the_calendar_across_kraken_s_missing_saturday_and_the_last_close():
    p = rand_panel(30, 8, start="2018-01-01", scale=4.0, drop=(12,))  # 2018-01-13 (a Saturday) missing
    assert pd.Timestamp("2018-01-13", tz="UTC") not in p.index and len(p) == 29
    x = K.basket_returns(p, 0.5)
    c = p[("BTC", "close")].to_numpy()
    e = p[("ETH", "close")].to_numpy()
    assert x[12] == math.log1p(0.5 * (c[12] / c[11] - 1.0) + 0.5 * (e[12] / e[11] - 1.0))  # one 2-day return
    assert p.index[12] == pd.Timestamp("2018-01-14", tz="UTC")
    mondays = T.check_closes(p.index, 0, 0).tolist()
    assert mondays == [0, 7, 13, 20, 27] and p.index[13] == pd.Timestamp("2018-01-15", tz="UTC")
    qp = K.q_path(p, 0.08, 0.5)
    assert qp.checks.tolist() == [20, 27]
    # a decision at the last close is never filled: a step there (a Monday) is not an order
    end = panel_on(p.index[:28], [100.0] * 28)  # flat prices: no drift order
    q = np.ones(28)
    q[27] = 0.25
    res = K.run_rule(end, qpath_of(q, (27,)), 0.5, 0.5, limits=LIM, costs=ZERO)
    assert res.attrs["orders"].tolist() == [0] and end.index[27].day_of_week == 0


def test_ride_run_refuses_bad_inputs():
    p = rand_panel(20, 1)
    ok = K.constant_targets(0.5, 20, 0.5)
    for kw, msg in (
        ({"costs": None}, "Costs instance"),
        ({"limits": {"min_cash": 0.2}}, "min_cash and max_coin"),
        ({"band": -1.0}, "band must be"),
        ({"band": math.nan}, "band must be"),
    ):
        args = {"limits": LIM, "costs": ZERO, **kw}
        with pytest.raises(ValueError, match=msg):
            K.ride_run(p, ok, **args)
    with pytest.raises(ValueError, match="target vectors"):
        K.ride_run(p, ok[:5], limits=LIM, costs=ZERO)
    with pytest.raises(ValueError, match="breaks the Steady limits"):
        K.ride_run(p, np.tile([0.59, 0.0], (20, 1)), limits=LIM, costs=ZERO)
    with pytest.raises(ValueError, match="cover the run"):
        K.run_rule(p, qpath_of(np.ones(5)), 0.5, 0.5, limits=LIM, costs=ZERO)


# ------------------------------------------------------------------------------------------------ identities

panel_seeds = st.integers(0, 10_000)


@given(seed=panel_seeds, n=st.integers(30, 120), w=st.sampled_from(K.W_VALUES), s=st.sampled_from(K.S_VALUES))
def test_with_an_infinite_band_ride_run_is_trend_run_states(seed, n, w, s):
    p = rand_panel(n, seed, scale=2.5, drop=(n // 2,))
    qp = K.q_path(p, w, 0.75)
    tg = K.rule_targets(qp.q, s, 0.75)
    a = K.ride_run(p, tg, limits=LIM, costs=COSTS, band=math.inf)
    b = T.run_states(p, tg, limits=LIM, costs=COSTS)
    assert a.equals(b) and np.array_equal(a.attrs["orders"], b.attrs["orders"])
    assert np.array_equal(a.attrs["order_targets"], b.attrs["order_targets"])


@given(seed=panel_seeds, n=st.integers(30, 120), s=st.sampled_from(K.S_VALUES), scale=st.floats(0.5, 6.0))
@example(seed=11, n=60, s=0.6, scale=6.0)
def test_a_constant_target_is_portfolio_rebalance_every_7_with_a_band_of_a_quarter_target(seed, n, s, scale):
    p = rand_panel(n, seed, scale=scale)  # starts on a Monday, no missing close
    a = K.ride_run(p, K.constant_targets(s, n, 0.5), limits=LIM, costs=COSTS)
    t = s * 0.5
    b = pf.rebalance(
        {"w_btc": t, "w_eth": t, "band": 0.25 * t, "every": 7, "min_cash": 0.20, "max_coin": 0.60}, p, COSTS
    )
    assert a.equals(b) and np.array_equal(a.attrs["orders"], b.attrs["orders"])


def test_a_setting_that_never_steps_gives_rule_x_and_n_bit_for_bit():
    p = pf.make_panel(_train_frames(4), snapshot_id="t").iloc[:729]  # a 729-row window: n - 1 = 728
    for s, f in K.MIXES:
        qp = K.q_path(p, 100.0, f)
        assert (qp.q == 1.0).all()
        share = s * qp.q
        x = K.matched_share(share)
        assert x == s
        r = K.run_rule(p, qp, s, f, limits=LIM, costs=COSTS)
        n_run = K.run_yardstick(p, s, f, limits=LIM, costs=COSTS)
        x_run = K.run_yardstick(p, x, f, limits=LIM, costs=COSTS)
        assert r.equals(n_run) and r.equals(x_run)
        assert K.ride_v(K.down_day(r["ret"].to_numpy()[1:]), K.down_day(x_run["ret"].to_numpy()[1:])) == 0.0
    assert (
        math.fsum([0.4] * 728) / 728 != 0.4
    )  # the plan's double rounding (READINGS_PINNED["matched_share"])


@given(seed=panel_seeds, w=st.sampled_from(K.W_VALUES), s=st.sampled_from(K.S_VALUES), u=st.integers(0, 30))
def test_copy_0_is_the_rule_and_the_rotation_is_trend_shifted_s(seed, w, s, u):
    p = rand_panel(240, seed, scale=2.5)
    qp = K.q_path(p, w, 0.5)
    sch = K.copy_schedule(qp, s)
    u = u % len(qp.checks)
    tg0, sh0 = K.shifted_copy(sch, 0, len(p), 0.5)
    assert np.array_equal(tg0, K.rule_targets(qp.q, s, 0.5)) and np.array_equal(sh0, s * qp.q)
    a = K.run_rule(p, qp, s, 0.5, limits=LIM, costs=COSTS)
    assert K.ride_run(p, tg0, limits=LIM, costs=COSTS).equals(a)
    tg, sh = K.shifted_copy(sch, u, len(p), 0.5)
    moved = T.shifted(sch, u)
    assert np.array_equal(tg, T.span_targets(moved, len(p), f=0.5)[0])
    w_ = len(qp.checks)
    rot = (s * qp.q_checks)[(np.arange(w_) + u) % w_]
    assert np.array_equal(sh[qp.checks], rot) and (sh[: qp.checks[0]] == s * qp.q_on).all()
    assert sorted(moved.share.tolist()) == sorted(sch.share.tolist())
    assert np.array_equal(T.in_force(np.ones((len(p), 2), dtype=np.int8), sh, f=0.5), tg)


def test_copy_schedule_needs_a_check():
    p = rand_panel(10, 1)
    with pytest.raises(ValueError, match="no Monday check"):
        K.copy_schedule(K.q_path(p, 0.1, 0.5), 0.5)


@given(seed=panel_seeds, n=st.integers(20, 100), w=st.sampled_from(K.W_VALUES), s=st.sampled_from(K.S_VALUES))
def test_the_accounting_equals_an_independent_book_with_each_order_s_target(seed, n, w, s):
    p = rand_panel(n, seed, scale=2.5, drop=(n // 2,))
    for costs in (COSTS, COSTS_2X):
        _, res = rule(p, w=w, s=s, f=0.75, costs=costs)
        out, legs, _, _ = vector_book(p, res, costs)
        for col in ("ret", "w_BTC", "w_ETH", "turnover", "cost", "position"):
            assert np.allclose(res[col].to_numpy(), out[col], rtol=0, atol=1e-12)
        validate_result(res, p[pf.ASSETS[0]])


def test_keep_risk_is_a_backtest_fn():
    p = rand_panel(60, 2, scale=3.0)
    fn = partial(K.keep_risk, limits=LIM, costs=COSTS)
    res = fn({"w": 0.08, "s": 0.5, "f": 0.75}, p)
    qp = K.q_path(p, 0.08, 0.75)
    assert np.array_equal(res.attrs["q"], qp.q) and res.attrs["q_on"] == qp.q_on
    assert np.array_equal(res.attrs["checks"], qp.checks) and np.array_equal(res.attrs["share"], 0.5 * qp.q)
    seven = fn({"w": 0.08, "s": 0.5, "f": 0.75, "lookback": 7}, p)
    assert np.array_equal(seven.attrs["q"], K.q_path(p, 0.08, 0.75, lookback=7).q)
    for bad, msg in (
        ({"w": 0.1, "s": 0.5}, "missing required"),
        ({"w": 0.1, "s": 0.5, "f": 0.5, "x": 1}, "unknown"),
    ):
        with pytest.raises(ValueError, match=msg):
            fn(bad, p)


# ------------------------------------------------------------------------------------------------ point in time


@st.composite
def tamper_cases(draw):
    seed = draw(panel_seeds)
    n = draw(st.integers(40, 90))
    p = rand_panel(n, seed, scale=draw(st.floats(1.5, 5.0)), drop=(n // 2,) if draw(st.booleans()) else ())
    start = draw(st.integers(0, len(p) - 12))
    w = draw(st.sampled_from(K.W_VALUES))
    s, f = draw(st.sampled_from(K.MIXES))
    qp, res = rule(p, w=w, s=s, f=f, costs=COSTS, start=start)
    anchors = sorted({start, *(start + qp.checks).tolist(), *(start + res.attrs["orders"]).tolist()})
    cut = draw(
        st.sampled_from([a + d for a in anchors for d in (0, 1) if start < a + d < len(p)] or [len(p) - 1])
    )
    return p, start, w, s, f, cut, draw(st.integers(0, 1000))


@given(case=tamper_cases())
def test_no_look_ahead_in_the_swing_the_steps_the_targets_the_orders_and_every_row(case):
    p, start, w, s, f, cut, seed = case
    q = tamper_from(p, cut, seed)
    for f_ in (f,):
        a, b = K.swing(p, f_), K.swing(q, f_)
        assert np.array_equal(a[:cut], b[:cut], equal_nan=True)
    qa, ra = rule(p, w=w, s=s, f=f, costs=COSTS, start=start)
    qb, rb = rule(q, w=w, s=s, f=f, costs=COSTS, start=start)
    k = cut - start
    assert np.array_equal(qa.q[:k], qb.q[:k]) and qa.q_on == qb.q_on
    assert np.array_equal(ra.attrs["targets"][:k], rb.attrs["targets"][:k])
    before = [t for t in ra.attrs["orders"].tolist() if t < k]
    assert before == [t for t in rb.attrs["orders"].tolist() if t < k]
    assert ra.attrs["reasons"].tolist()[: len(before)] == rb.attrs["reasons"].tolist()[: len(before)]
    assert ra.iloc[:k].equals(rb.iloc[:k])
    x = K.matched_share(s * qa.q)  # the yardstick: its target held fixed, only the prices tampered
    xa = K.run_yardstick(p.iloc[start:], x, f, limits=LIM, costs=COSTS)
    xb = K.run_yardstick(q.iloc[start:], x, f, limits=LIM, costs=COSTS)
    assert xa.iloc[:k].equals(xb.iloc[:k])
    na = K.run_yardstick(p.iloc[start:], s, f, limits=LIM, costs=COSTS)
    nb = K.run_yardstick(q.iloc[start:], s, f, limits=LIM, costs=COSTS)
    assert na.iloc[:k].equals(nb.iloc[:k])


@given(seed=panel_seeds, t=st.integers(14, 59), f=st.sampled_from(K.F_VALUES))
def test_touching_the_present_moves_sigma_and_x_at_that_close_only(seed, t, f):
    p = rand_panel(60, seed)
    frames = {}
    for asset in pf.ASSETS:
        bars = p[asset].copy()
        bars.iloc[t, bars.columns.get_loc("close")] *= 1.3
        bars.iloc[t, bars.columns.get_loc("high")] = max(bars["high"].iloc[t], bars["close"].iloc[t])
        frames[asset] = bars
    q = pf.make_panel(frames, snapshot_id="test-panel")
    xa, xb = K.basket_returns(p, f), K.basket_returns(q, f)
    sa, sb = K.swing(p, f), K.swing(q, f)
    assert xa[t] != xb[t] and sa[t] != sb[t]
    assert np.array_equal(xa[:t], xb[:t], equal_nan=True) and np.array_equal(sa[:t], sb[:t], equal_nan=True)


# ------------------------------------------------------------------------------------------------ the yardsticks


def test_matched_share_is_the_exactly_rounded_mean_of_rows_0_to_n_minus_2():
    share = [0.3, 0.3, 0.15, 0.0, 0.3, 0.45]  # the last row's decision never fills
    want = float((Fraction(0.3) * 3 + Fraction(0.15) + Fraction(0.0) + Fraction(0.0)) / 5)
    assert K.matched_share(share) == want == K.exact_mean(share[:-1])
    assert K.matched_share([0.4] * 729) == 0.4
    with pytest.raises(ValueError, match="at least 2"):
        K.matched_share([0.5])
    with pytest.raises(ValueError, match="no values"):
        K.exact_mean([])


def test_equal_calm_share_and_its_clip():
    a = K.equal_calm_share(0.4, -0.1, 0.5, LIM)
    assert a == {"share": 0.4 * math.exp(-0.1), "x_eq": 0.4 * math.exp(-0.1), "clipped": False, "lambda": 1.0}
    b = K.equal_calm_share(0.6, 0.5, 0.5, LIM)  # x_eq = 0.989: cash below 0.22
    assert b["clipped"] and b["x_eq"] == 0.6 * math.exp(0.5)
    pf.check_targets(b["share"] * 0.5, b["share"] * 0.5, min_cash=0.2, max_coin=0.6, headroom=0.02)
    assert b["share"] == pytest.approx(0.78, abs=2e-9) and b["lambda"] == pytest.approx(
        0.78 / b["x_eq"], abs=3e-9
    )
    above = (b["lambda"] + 2e-12) * b["x_eq"]
    with pytest.raises(ValueError):
        pf.check_targets(above * 0.5, above * 0.5, min_cash=0.2, max_coin=0.6, headroom=0.02)
    c = K.equal_calm_share(0.6, 0.3, 0.75, LIM)  # x_eq 0.81: BTC binds first at f 0.75
    assert c["clipped"] and c["share"] * 0.75 == pytest.approx(0.58, abs=2e-9)


def test_the_yardstick_and_order_checks_fire():
    p = rand_panel(40, 3, scale=3.0)
    x = K.run_yardstick(p, 0.45, 0.5, limits=LIM, costs=COSTS)
    K.check_yardstick(x, 0.45, 0.5)
    with pytest.raises(K.ConsistencyError, match="not its share"):
        K.check_yardstick(x, nxt(0.45, UP), 0.5)
    _, r = rule(p, w=0.08, s=0.5, f=0.5, costs=COSTS)
    assert "step" in r.attrs["reasons"].tolist()
    with pytest.raises(K.ConsistencyError, match="ordered for"):
        K.check_yardstick(r, 0.5, 0.5)
    K.check_order_targets(r, LIM)
    r.attrs["order_targets"] = np.asarray([[0.59, 0.0]])
    with pytest.raises(K.ConsistencyError, match="break the Steady limits"):
        K.check_order_targets(r, LIM)


def test_step_hash_reads_the_step_orders_only():
    p = rand_panel(60, 4, scale=3.0)
    _, a = rule(p, w=0.08, costs=COSTS)
    _, b = rule(p, w=0.08, costs=COSTS_2X)
    assert K.step_hash(a) == K.step_hash(b)
    n = K.run_yardstick(p, 0.5, 0.5, limits=LIM, costs=COSTS)
    assert K.step_hash(n) == K.step_hash(K.run_yardstick(p, 0.3, 0.75, limits=LIM, costs=COSTS))
    empty = n.copy()
    empty.attrs = {"orders": np.zeros(0, dtype=np.int64), "reasons": np.zeros(0, dtype=object)}
    assert K.step_hash(empty) == K.step_hash(n)  # no step order either way


# ------------------------------------------------------------------------------------------------ the measures


def test_the_down_day_is_around_zero_and_v_is_its_log_ratio():
    r = [0.01, -0.02, 0.03, -0.04]
    assert K.down_day(r) == math.sqrt((0.02**2 + 0.04**2) / 4)  # not around the mean, not over 2 down days
    assert K.down_day(r, keep=[True, False, True, True]) == math.sqrt(0.04**2 / 3)
    assert K.ride_v(0.02, 0.01) == math.log(0.02) - math.log(0.01)
    assert K.ride_v(0.0, 0.01) is None and K.ride_v(0.01, 0.0) is None
    with pytest.raises(ValueError, match="no returns"):
        K.down_day([0.1], keep=[False])


def test_run_measures_by_hand():
    idx = days(22)  # Mondays at rows 0, 7, 14, 21
    btc = [100.0, 100.0, 110.0, 99.0, 99.0, 99.0, 99.0, 99.0] + [99.0] * 14
    p = panel_on(idx, btc, [100.0] * 22)
    q = [1.0] * 7 + [0.5] * 7 + [1.0] * 8
    res = K.run_rule(p, qpath_of(q, (7, 14, 21)), 0.5, 1.0, limits=LIM, costs=ZERO)
    m = K.run_measures(res, ZERO, s=0.5, w=0.08)
    r = res["ret"].to_numpy()[1:]
    assert m["DD"] == math.sqrt(math.fsum(min(v, 0.0) ** 2 for v in r) / 21)
    assert m["cagr"] == float(np.prod(1.0 + r)) ** (365 / 21) - 1.0
    week1 = math.sqrt(math.fsum((r[0:7] ** 2).tolist()))
    assert week1 > 0.04 and m["over_cap"] == 1 / 3  # weeks 0-7, 7-14, 14-21; only the first moves
    assert m["realised"] == math.fsum(res["position"].to_numpy()[1:].tolist()) / 21
    assert (m["orders"], m["orders_first"], m["orders_step"], m["orders_drift"], m["orders_limit"]) == (
        3,
        1,
        2,
        0,
        0,
    )
    assert m["orders_per_year"] == 2 * 365 / 21 and m["busiest_30d"] == 2
    assert m["F"] == pytest.approx(0.1 * 0.55 / 1.05) and m["worst_day"] == r[2] == r.min()
    mr = K.rule_measures(
        qpath_of(q, (7, 14, 21)), res, K.run_yardstick(p, 0.5, 1.0, limits=LIM, costs=ZERO), [1.0] * 22
    )
    assert mr["q_lt1"] == 7 / 21 and mr["q_le_half"] == 7 / 21 and mr["longest_back_days"] == 7.0
    assert (mr["step_downs"], mr["step_ups"], mr["steps_back"]) == (1, 1, True)
    assert K.rule_measures(qpath_of([1.0] * 22, (7,)), res, res, [1.0] * 22)["steps_back"] is False
    assert K.rule_measures(qpath_of([0.5] * 22, ()), res, res, [1.0] * 22)["steps_back"] is True


def test_the_longest_stretch_runs_to_the_last_close_and_the_weeks_need_two_mondays():
    idx = days(10)
    assert K._longest(np.array([1.0, 0.5, 0.5, 1.0, 0.25, 0.25, 0.25, 0.0, 0.0, 0.0]), idx) == 5.0
    assert K._longest(np.ones(10), idx) == 0.0
    flat = K.run_yardstick(panel_on(days(6, "2017-01-03"), [100.0] * 6), 0.5, 0.5, limits=LIM, costs=ZERO)
    assert math.isnan(K._over_cap(flat, 0.04))  # no Monday at all


def test_the_missed_rebound_by_hand():
    idx = days(200)
    i_close = np.linspace(2.0, 1.0, 200)
    i_close[50] = 0.5  # the lowest I, first at row 50; t_end = row 140 (90 days later)
    rn = np.zeros(200)
    rr = np.zeros(200)
    rn[51], rn[140], rn[141] = 0.10, 0.10, 0.5
    rr[60] = 0.05
    got = K.missed_rebound(rr, rn, idx, i_close)
    assert got == pytest.approx(100.0 * (1.1 * 1.1 - 1.05), rel=1e-14)
    late = np.linspace(2.0, 1.0, 200)
    late[190] = 0.1  # fewer than 90 days left: to the last close
    rn2 = np.zeros(200)
    rn2[199] = 0.2
    assert K.missed_rebound(np.zeros(200), rn2, idx, late) == pytest.approx(20.0)
    assert (
        K.missed_rebound(np.zeros(200), rn2, idx, np.linspace(2.0, 1.0, 200)) == 0.0
    )  # t_low the last close


def test_compare_by_hand():
    rule_ = {"DD": 0.02, "cagr": 0.10, "realised": 0.40}
    n = {"DD": 0.03, "cagr": 0.15, "realised": 0.50}
    x = {"DD": 0.025, "cagr": 0.08, "realised": 0.39}
    out = K.compare(rule_, n, x, {"cagr": 0.12})
    assert out["V_X"] == math.log(0.02) - math.log(0.025) and out["V_N"] == math.log(0.02) - math.log(0.03)
    assert out["c_N"] == 100.0 * (0.15 - 0.10) and out["c_X"] == 100.0 * (0.08 - 0.10)
    assert out["c_eq"] == 100.0 * (0.12 - 0.10) and out["realised_gap"] == 0.40 - 0.39
    assert (
        K.compare(rule_, n, {**x, "DD": 0.0}, None)["V_X"] is None
        and K.compare(rule_, n, x, None)["c_eq"] is None
    )


# ------------------------------------------------------------------------------------------------ the statistics


def hand_resampler(n: int, b: int, mean_block: float = 60.0, seed: int = 0) -> np.ndarray:
    """The stationary bootstrap written out: each position restarts at a uniform index with probability 1 / mean
    block (always at 0), else follows the previous one (mod n); one generator for every resample, in order."""
    rng = np.random.default_rng(seed)
    out = np.empty((b, n), dtype=np.int64)
    for i in range(b):
        restart = rng.random(n) < 1.0 / mean_block
        restart[0] = True
        starts = iter(rng.integers(0, n, size=int(restart.sum())).tolist())
        pos = 0
        for t in range(n):
            pos = next(starts) if restart[t] else (pos + 1) % n
            out[i, t] = pos
    return out


def test_the_index_sets_are_a_hand_stationary_resampler_from_seed_0():
    got = K.index_set(97, resamples=40)
    assert np.array_equal(got, hand_resampler(97, 40)) and got.dtype == np.int32
    rng = np.random.default_rng(0)
    first, second = stationary_bootstrap_indices(97, 60, rng), stationary_bootstrap_indices(97, 60, rng)
    assert np.array_equal(got[0], first) and np.array_equal(got[1], second)
    assert not np.array_equal(K.index_set(97, resamples=5, seed=1), got[:5])
    d = np.random.default_rng(3).standard_normal(97)
    assert np.array_equal(K.resampled_means(d, got, chunk=7), np.array([np.mean(d[i]) for i in got]))
    with pytest.raises(ValueError, match="one index row"):
        K.resampled_means(d[:5], got)


def test_risk_x_by_hand_on_three_resamples():
    a = np.array([-0.02, 0.01, -0.01, 0.03])
    b = np.array([-0.01, 0.02, -0.03, 0.00])
    idx = np.array([[0, 1, 2, 3], [0, 0, 1, 1], [2, 2, 3, 3]])
    out = K.risk_x(a, b, idx, keep=True)
    da, db = np.minimum(a, 0) ** 2, np.minimum(b, 0) ** 2
    vs = [0.5 * (math.log(np.mean(da[i])) - math.log(np.mean(db[i]))) for i in idx]
    assert np.allclose(out["V_star"], vs, rtol=0, atol=1e-15)
    assert out["V"] == math.log(K.down_day(a)) - math.log(K.down_day(b))
    assert vs[0] < 0 and vs[1] > 0 and vs[2] < K.EQ_BOUND
    assert out["p_calm"] == 2 / 4 and out["p_rough"] == 3 / 4 and out["p_eq"] == 3 / 4
    diff = np.log1p(a) - np.log1p(b)
    assert out["g"] == 365 * math.fsum(diff.tolist()) / 4
    gs = [365 * np.mean(diff[i]) for i in idx]
    assert out["cost_p"] == (1 + sum(g >= -0.02 for g in gs)) / 4 and out["cost_flag"] is False
    assert out["V_lo"] == float(np.percentile(out["V_star"], 5)) and out["V_hi"] == float(
        np.percentile(out["V_star"], 95)
    )
    assert out["missing"] is None and "V_star" not in K.risk_x(a, b, idx)


def test_risk_x_is_missing_on_a_zero_dd_or_a_resample_with_no_down_day():
    a = np.array([-0.02, 0.01, -0.01, 0.03])
    assert (
        K.risk_x(a, np.array([0.01, 0.02, 0.0, 0.0]), np.zeros((2, 4), dtype=int))["missing"] == "a DD of 0"
    )
    out = K.risk_x(a, a, np.array([[1, 1, 3, 3], [0, 1, 2, 3]]))
    assert out["missing"] == "a resample with a zero mean" and out["p_calm"] is None
    with pytest.raises(ValueError, match="one length"):
        K.risk_x(a, a[:3], np.zeros((1, 4), dtype=int))


def test_the_p_values_hold_at_500_of_10001_and_fail_at_501():
    base = {"missing": False, "steps": True, "v": 0.01, "p_eq": 0.5, "holm_pass": False, "e1_holds": False}
    assert K.ride_label(**base, p_rough=500 / 10_001) == K.ROUGHER
    assert K.ride_label(**base, p_rough=501 / 10_001) == K.CANT_TELL
    nd = {**base, "p_rough": 0.5}
    assert K.ride_label(**{**nd, "p_eq": 500 / 10_001}) == K.NO_DIFFERENCE
    assert K.ride_label(**{**nd, "p_eq": 501 / 10_001}) == K.CANT_TELL
    assert K._p(499, 10_000) == 500 / 10_001


def test_holm_by_hand():
    assert K.holm({0.08: 125 / 10_001, 0.10: 0.9, 0.12: 0.9, 0.15: 0.9}) == {
        0.08: True,
        0.10: False,
        0.12: False,
        0.15: False,
    }  # 0.012499 < 0.0125
    assert K.holm({0.08: 126 / 10_001, 0.10: 0.9, 0.12: 0.9, 0.15: 0.9})[0.08] is False  # 0.0126 >= 0.0125
    every = K.holm({0.08: 0.001, 0.10: 0.02, 0.12: 0.01, 0.15: 0.04})  # 0.0125, 0.0167, 0.025, 0.05
    assert all(every.values())
    stops = K.holm({0.08: 0.001, 0.10: 0.018, 0.12: 0.02, 0.15: 0.03})  # 0.018 >= 0.0167: the step-down stops
    assert stops == {0.08: True, 0.10: False, 0.12: False, 0.15: False}
    ties = K.holm({0.08: 0.014, 0.10: 0.014, 0.12: 0.9, 0.15: 0.9})
    assert ties[0.08] is False and ties[0.10] is False  # 0.014 >= 0.0125
    assert K.holm({0.08: 0.001, 0.10: None, 0.12: 0.9, 0.15: math.nan}) == dict.fromkeys(K.W_VALUES)
    assert K.holm({0.08: 0.04})[0.08] is True  # one setting: 0.05


def test_e1_counts_ties_against_the_rule():
    v0 = -0.05
    copies = [v0] * 2 + [-0.06] * 9 + [0.0] * 247  # 11 at or below
    out = K.e1(v0, copies)
    assert (out["at_or_below"], out["rank_p"], out["holds"], out["copies"]) == (11, 12 / 259, True, 258)
    out = K.e1(v0, [v0] * 3 + [-0.06] * 9 + [0.0] * 246)
    assert (out["at_or_below"], out["rank_p"], out["holds"]) == (12, 13 / 259, False)
    assert K.e1(None, [0.1])["holds"] is None and K.e1(0.1, [0.1, math.nan])["holds"] is None
    assert K.e1(0.1, [])["holds"] is None


def test_each_copy_is_judged_against_its_own_mix():
    """The rule's raw DD is the smallest of all, but its copies held less crypto: against their own mixes they are
    calmer than the rule is against its own, so E1 fails though a raw-DD rank would pass."""
    rule_dd, x_dd = 0.010, 0.0105
    copies = [
        (0.0101 + 0.0001 * i, 0.0120 + 0.0001 * i) for i in range(25)
    ]  # each copy: (its DD, its mix's DD)
    v0 = K.ride_v(rule_dd, x_dd)
    raw = K.e1(rule_dd, [d for d, _ in copies])
    by_v = K.e1(v0, [K.ride_v(d, m) for d, m in copies])
    assert raw["holds"] is True and by_v["holds"] is False and by_v["at_or_below"] == 25


def test_every_label_at_its_boundary_in_its_order():
    base = {
        "missing": False,
        "steps": True,
        "v": -0.05,
        "p_rough": 0.9,
        "p_eq": 0.3,
        "holm_pass": True,
        "e1_holds": True,
    }
    lab = lambda **kw: K.ride_label(**{**base, **kw})  # noqa: E731
    assert lab() == K.CALMER
    assert lab(missing=True) == K.MISSING and lab(v=None) == K.MISSING and lab(p_eq=math.nan) == K.MISSING
    assert lab(steps=False) == K.NOT_STEPPING
    assert lab(p_rough=0.04) == K.ROUGHER and lab(steps=False, p_rough=0.01) == K.NOT_STEPPING
    assert lab(p_eq=0.049) == K.BELOW_NOTICE and lab(p_eq=0.05) == K.CALMER
    assert lab(v=0.0) == K.CANT_TELL and lab(v=0.0, p_eq=0.01) == K.NO_DIFFERENCE
    assert lab(holm_pass=False) == K.CANT_TELL and lab(e1_holds=False, p_eq=0.01) == K.NO_DIFFERENCE
    assert lab(holm_pass=None) == K.MISSING and lab(e1_holds=None) == K.MISSING
    assert (
        lab(holm_pass=None, e1_holds=False) == K.CANT_TELL
        and lab(holm_pass=False, e1_holds=None) == K.CANT_TELL
    )


def test_label_family_puts_a_setting_that_never_steps_in_holm_at_1():
    cells = [
        {
            "w": 0.08,
            "missing": False,
            "steps": True,
            "V": -0.1,
            "p_calm": 0.012,
            "p_rough": 0.9,
            "p_eq": 0.3,
            "e1_holds": True,
        },
        {
            "w": 0.10,
            "missing": False,
            "steps": True,
            "V": -0.1,
            "p_calm": 0.016,
            "p_rough": 0.9,
            "p_eq": 0.3,
            "e1_holds": True,
        },
        {
            "w": 0.12,
            "missing": False,
            "steps": True,
            "V": -0.1,
            "p_calm": 0.024,
            "p_rough": 0.9,
            "p_eq": 0.3,
            "e1_holds": True,
        },
        {
            "w": 0.15,
            "missing": False,
            "steps": False,
            "V": 0.0,
            "p_calm": 0.0001,
            "p_rough": 1.0,
            "p_eq": 1e-4,
            "e1_holds": False,
        },
    ]
    out = K.label_family(cells)
    assert [c["holm"] for c in out] == [True, True, True, False]
    assert [c["label"] for c in out] == [K.CALMER, K.CALMER, K.CALMER, K.NOT_STEPPING]
    cells[3]["p_calm"] = 0.0001
    cells[3]["steps"] = True  # stepping: its own small p goes first and moves the others' thresholds
    assert [c["holm"] for c in K.label_family(cells)] == [True, True, True, True]
    cells[0]["missing"] = True
    cells[0]["p_calm"] = None
    assert [c["holm"] for c in K.label_family(cells)] == [None] * 4


# ------------------------------------------------------------------------------------------------ the rules


def pool(vx=None, cx=None, labels=None, settings=K.W_VALUES, mixes=K.MIXES, n=49, status=None):
    """A hand-made pool: ``vx``/``cx`` map (w, s, f) to a list of n window values (default: all calmer, cost 0),
    ``labels`` (w, s, f) to a label (default CAN'T TELL)."""
    rows, labs = [], []
    for w in settings:
        for s, f in mixes:
            v = (vx or {}).get((w, s, f), [-0.01] * n)
            c = (cx or {}).get((w, s, f), [0.0] * n)
            for k in range(n):
                rows.append(
                    {
                        "kind": "rule",
                        "status": K.OK,
                        "w": w,
                        "s": s,
                        "f": f,
                        "window": k,
                        "V_X": v[k],
                        "c_X": c[k],
                    }
                )
                rows.append(
                    {
                        "kind": "X_eq",
                        "status": K.OK,
                        "w": w,
                        "s": s,
                        "f": f,
                        "window": k,
                        "V_X": None,
                        "c_X": None,
                    }
                )
            labs.append(
                {"w": w, "s": s, "f": f, "label": (labels or {}).get((w, s, f), K.CANT_TELL), "failed": False}
            )
    frame = pd.DataFrame(rows)
    for i, st_ in (status or {}).items():
        frame.loc[i, "status"] = st_
    return frame, pd.DataFrame(labs)


def test_d1_picks_the_gentlest_usable_setting_and_calmer_first():
    win, lab = pool()
    assert K.d1(win, lab)["default"] == 0.15  # every setting usable: the larger w
    calm = {(0.10, s, f): K.CALMER for s, f in K.MIXES}
    win, lab = pool(labels=calm)
    out = K.d1(win, lab)
    assert out["default"] == 0.10 and out["windows"] == 49
    assert [st_["calmer_all"] for st_ in out["settings"]] == [False, True, False, False]
    partly = {**calm, (0.15, 0.3, 0.5): K.CALMER}
    assert K.d1(*pool(labels=partly))["default"] == 0.10  # CALMER at all 8 mixes, not at one


def test_d1_rule_1_needs_25_of_49_calmer_windows():
    key = (0.15, 0.4, 0.75)
    ok = {key: [-0.01] * 25 + [0.0] * 24}  # V_X = 0 is not calmer
    assert K.d1(*pool(vx=ok))["default"] == 0.15
    out = K.d1(*pool(vx={key: [-0.01] * 24 + [0.01] * 25}))
    assert out["default"] == 0.12
    top = out["settings"][3]
    assert top["usable"] is False and top["first_failure"] == {"mix": (0.4, 0.75), "rule": 1}
    assert top["mixes"][3]["calmer_windows"] == 24


def test_d1_rule_3_a_median_cost_of_exactly_2_points_passes():
    key = (0.15, 0.6, 0.5)
    assert K.d1(*pool(cx={key: [2.0] * 25 + [9.0] * 24}))["default"] == 0.15
    out = K.d1(*pool(cx={key: [nxt(2.0, UP)] * 25 + [0.0] * 24}))
    assert out["default"] == 0.12 and out["settings"][3]["first_failure"] == {"mix": (0.6, 0.5), "rule": 3}


def test_d1_rule_2_and_no_default():
    labels = {(w, 0.3, 0.5): K.NO_DIFFERENCE for w in K.W_VALUES}
    out = K.d1(*pool(labels=labels))
    assert out["default"] == K.NO_DEFAULT and out["reason"] == "no usable setting"
    assert all(st_["first_failure"] == {"mix": (0.3, 0.5), "rule": 2} for st_ in out["settings"])
    for bad in (K.ROUGHER, K.BELOW_NOTICE, K.NOT_STEPPING):
        assert K.d1(*pool(labels={(0.15, 0.5, 0.75): bad}))["default"] == 0.12


def test_d1_missing_flows_through():
    win, lab = pool()
    assert K.d1(win, lab, settings=K.W_VALUES)["default"] == 0.15
    w2 = win.copy()
    w2.loc[w2.index[w2["kind"] == "X_eq"][0], "status"] = (
        "failed"  # a failed X_eq: a description, not MISSING
    )
    assert K.d1(w2, lab)["default"] == 0.15
    w3 = win.copy()
    w3.loc[0, "status"] = "failed"
    assert K.d1(w3, lab) == {
        "default": K.MISSING,
        "reason": "a run of the pool failed (stop rule 4)",
        "windows": None,
        "settings": [],
    }
    l2 = lab.copy()
    l2.loc[0, "failed"] = True
    assert K.d1(win, l2)["default"] == K.MISSING
    nan = K.d1(*pool(vx={(0.08, 0.3, 0.5): [math.nan] + [-0.01] * 48}))
    assert nan["default"] == K.MISSING and nan["settings"][0]["usable"] is None
    lab_missing = K.d1(*pool(labels={(0.10, 0.3, 0.5): K.MISSING}))
    assert lab_missing["default"] == K.MISSING
    failing_too = K.d1(*pool(labels={(0.10, 0.3, 0.5): K.MISSING, (0.10, 0.4, 0.5): K.ROUGHER}))
    assert failing_too["settings"][1]["usable"] is False  # a failure decides, MISSING elsewhere or not
    cost_nan = K.d1(*pool(cx={(0.15, 0.3, 0.5): [math.nan] * 49}))
    assert cost_nan["settings"][3]["usable"] is None
    with pytest.raises(ValueError, match="one run per window"):
        K.d1(win.iloc[2:], lab)


def test_d2_labels_and_their_order():
    head = {"default": 0.12}
    assert K.d2(head, {"a": {"default": 0.12}, "b": {"default": 0.12}})["label"] == K.ROBUST
    assert K.d2({"default": K.NO_DEFAULT}, {"a": {"default": K.NO_DEFAULT}})["label"] == K.ROBUST
    out = K.d2(head, {"a": {"default": 0.15}, "b": None, "c": {"default": K.MISSING}})
    assert out["label"] == "NOT ROBUST (a, b: MISSING, c: MISSING)" and out["moved"] == ["a"]
    assert K.d2(head, {"a": None})["label"] == "MISSING (a)"
    assert K.d2({"default": K.MISSING}, {"a": {"default": 0.1}})["label"] == "MISSING (headline)"


def test_the_boom_windows_by_hand():
    assert P.windows_without(range(49), [2017]) == list(range(12, 49))
    assert P.windows_without(range(49), [2017, 2020]) == [12, 48]  # fewer than 12: MISSING


def test_d3_by_hand():
    rows = []
    for k, (vx, cn, f_) in enumerate(((-0.1, 1.0, 0.20), (0.1, 3.0, 0.40), (-0.2, 2.0, 0.30))):
        base = {"w": 0.1, "s": 0.5, "f": 0.5, "window": k, "year": 2017 + k // 2}
        common = {"worst_week": -0.1 * (k + 1), "over_cap": 0.1 * k}
        rows.append(
            {
                **base,
                **common,
                "kind": "rule",
                "V_X": vx,
                "V_N": vx - 0.1,
                "c_N": cn,
                "c_X": -cn,
                "c_eq": math.nan if k == 1 else 0.5,
                "x": 0.4,
                "x_eq": 0.38,
                "fees_pct_per_year": 0.2,
                "F": f_,
                "q_lt1": 0.3,
                "longest_back_days": 14.0 * k,
                "rebound_gap": 5.0 * k,
                "orders_per_year": 10.0,
                "busiest_30d": k + 2,
            }
        )
        rows.append({**base, **common, "kind": "N", "F": f_ + 0.1})
        rows.append({**base, **common, "kind": "X", "F": f_ - 0.05})
    out = K.d3_cell(pd.DataFrame(rows), 0.35)
    assert out["V_X"]["median"] == -0.1 and out["V_X"]["share_above_0"] == 1 / 3 and out["c_eq"]["n"] == 2
    assert out["cut_X"]["median"] == pytest.approx(100 * (1 - math.exp(-0.1)))
    assert out["F"]["N"] == {
        "median": 0.4,
        "Q": float(np.percentile([0.3, 0.5, 0.4], 90)),
        "worst": 0.5,
        "past_budget": 2 / 3,
    }
    assert out["F"]["rule"]["past_budget"] == 1 / 3 and K._falls([0.1], None)["past_budget"] is None
    assert (
        out["worst_week"]["rule"] == pytest.approx(-0.3)
        and out["busiest_30d"] == 4
        and out["calmer_windows"] == 2
    )
    assert out["rebound_gap"] == {"median": 5.0, "worst": 10.0} and out["windows"] == 3
    assert out["by_year"] == {
        2017: {"V_X": 0.0, "c_N": 2.0, "F": 0.30000000000000004},
        2018: {"V_X": -0.2, "c_N": 2.0, "F": 0.3},
    }
    assert K.describe([]) == {"n": 0, "p10": None, "median": None, "p90": None, "share_above_0": None}
    spans = pd.DataFrame([{"w": 0.1, "s": 0.5, "f": 0.5, "label": K.CANT_TELL}])
    d = K.d3(pd.DataFrame(rows), spans, 0.1, 0.35)
    assert d["cells"][0]["default"] and d["cells"][0]["span"]["label"] == K.CANT_TELL
    assert K.d3(pd.DataFrame(rows), spans.iloc[:0], K.NO_DEFAULT, None)["cells"][0]["span"] is None


@given(seed=panel_seeds, n=st.integers(30, 120), w=st.sampled_from(K.W_VALUES), miss=st.booleans())
def test_after_the_first_monday_check_the_q_path_is_vol_steady_s(seed, n, w, miss):
    p = rand_panel(n, seed, scale=2.5, drop=(n // 2,) if miss else ())
    mine = K.q_path(p, w, 0.5)
    theirs = V.vol_path(p, 14, K.level(w), 1.0)
    c0 = int(mine.checks[0])
    assert theirs.activation == c0 and np.array_equal(mine.q[c0:], theirs.q[c0:])
    assert np.array_equal(mine.sigma_checks, theirs.sigma[theirs.checks])


@pytest.mark.parametrize("cut", [3, 4, 7])
def test_no_look_ahead_at_a_limit_fix(cut):
    btc = [100.0] * 20
    btc[3:] = [200.0] * 17  # the limit fix at the close of row 3 (a Thursday), filled at row 4's open
    p = panel_on(days(20), btc, [100.0] * 20)
    q = tamper_from(p, cut, 5)
    a = K.ride_run(p, K.constant_targets(0.6, 20, 0.75), limits=LIM, costs=COSTS)
    b = K.ride_run(q, K.constant_targets(0.6, 20, 0.75), limits=LIM, costs=COSTS)
    assert a.attrs["reasons"].tolist()[:2] == ["first", "limit"]
    assert [t for t in a.attrs["orders"].tolist() if t < cut] == [
        t for t in b.attrs["orders"].tolist() if t < cut
    ]
    assert a.iloc[:cut].equals(b.iloc[:cut])


def test_p_eq_reads_a_cut_of_exactly_a_tenth():
    """V* = ln 0.85 on both resamples, between ln 0.8 and ln 0.9: inside the 10% bound, outside a 20% one."""
    a, b = np.array([-0.0085, 0.01]), np.array([-0.01, 0.01])
    out = K.risk_x(a, b, np.array([[0, 1], [1, 0]]), keep=True)
    assert np.allclose(out["V_star"], math.log(0.85), rtol=0, atol=1e-15)
    assert math.log(0.8) < out["V_star"].max() < K.EQ_BOUND
    assert out["p_eq"] == 3 / 3 and out["p_calm"] == 1 / 3 and out["p_rough"] == 3 / 3
