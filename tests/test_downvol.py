"""downvol-steady (``lab/runner/downvol.py``, scouting only): the downside-volatility-scaled hold, vol-steady's rule with
one measure swapped in through a seam, and E1's q-only shift (``research/downvol-steady/PLAN.md`` sections 3-4, 15 (M1)
and 17; VP = vol-steady's PLAN.md, TP = trend-steady's).

Synthetic data and hand-built paths only: no catalog bar is read. vol-steady's helpers that downvol imports unchanged
(the basket return, m, q, the encoding, R_0's stitched schedule, P, the plateau, the verdict and headline) are tested in
``test_volsteady.py``, and trend-steady's executor, shift, N0, X and luck statistics in ``test_trend.py``; this file
tests the measure, the seam (with vol-steady's measure put back, every function equals vol-steady's bit for bit), the
rule end to end (look-ahead, live/batch parity, accounting against ``test_trend.vector_book``) and the q-only shift.
"""

from __future__ import annotations

import math
from functools import partial

import numpy as np
import pandas as pd
import pytest
from hypothesis import example, given
from hypothesis import strategies as st
from test_portfolio import random_panel, tamper_from
from test_trend import panel_on, regime_panel, same_fills, vector_book
from test_volsteady import vol_cases, vol_panels

from lab.runner import downvol as dv
from lab.runner import portfolio as pf
from lab.runner import steady as sd
from lab.runner import trend as tr
from lab.runner import volsteady as vs
from lab.runner.interface import validate_result
from lab.runner.reference import Costs
from lab.search.study import SearchConfig
from lab.search.walkforward import walk_forward_optimize
from lab.validation.splits import walk_forward

LIMITS = {"min_cash": 0.20, "max_coin": 0.60}  # Steady's limits as read (test_portfolio pins the real file)
COSTS = Costs()
SQ = math.sqrt(365.0)

# ------------------------------------------------------------------------------------------------ helpers


def P(lookback=10, target_vol=0.6, share=0.5) -> dict:
    return {"lookback": lookback, "target_vol": target_vol, "crypto_share": share}


def run(params, panel, limits=LIMITS, costs=COSTS, **kw) -> pd.DataFrame:
    return dv.downvol_backtest(params, panel, limits=limits, costs=costs, **kw)


def mondays(n: int, start: str = "2017-01-02") -> pd.DatetimeIndex:
    """n daily closes from a Monday (rows 0, 7, 14, ... are Mondays)."""
    return pd.date_range(start, periods=n, freq="D", tz="UTC", name="ts")


def independent_down(window) -> float:
    """The downside deviation written out independently: the squares of the negative returns only (an up day adds
    an exact zero to fsum), over L, times 2, around zero."""
    w = [float(v) for v in window]
    ss = math.fsum([v * v for v in w if v < 0.0])
    return math.sqrt(365.0) * math.sqrt(2.0 * ss / len(w))


def sample_sd(window) -> float:
    """vol-steady's sigma written out: sqrt(365) x the sample sd (ddof 1), two fsum passes."""
    w = [float(v) for v in window]
    mean = math.fsum(w) / len(w)
    return math.sqrt(365.0) * math.sqrt(math.fsum((v - mean) * (v - mean) for v in w) / (len(w) - 1))


def same_run(a: pd.DataFrame, b: pd.DataFrame) -> None:
    """Two runs equal bit for bit: every row and every attr the rule or the executor writes."""
    pd.testing.assert_frame_equal(a, b)
    for key in ("z", "share", "q", "checks", "targets", "orders", "order_targets", "switches"):
        assert np.array_equal(a.attrs[key], b.attrs[key]), key
    assert np.array_equal(a.attrs["sigma"], b.attrs["sigma"], equal_nan=True)
    assert a.attrs["activation"] == b.attrs["activation"] and a.attrs["order_hash"] == b.attrs["order_hash"]
    assert a.attrs["reasons"].tolist() == b.attrs["reasons"].tolist()


def share_path(n: int, changes: dict[int, float]) -> np.ndarray:
    out = np.zeros(n)
    for t, v in sorted(changes.items()):
        out[t:] = v
    return out


# ------------------------------------------------------------------------------------------------ pinned values


def test_the_pinned_values_are_the_plan_s():
    """Sections 3-5: the factor 2, sqrt(365), the defaults of the seam, and vol-steady's box, quarters and first
    active row (VP 5 unchanged); the q-only shift's helpers are exported."""
    assert dv.DOWN_FACTOR == 2.0 and dv.WEEKDAY == 0 and dv.F_SPLIT == 0.5
    assert vs.SQRT_365 == SQ and vs.FIRST_ACTIVE_ROW == 15 and vs.MIN_LOOKBACK == 2
    assert vs.BOX == {"lookback": (10.0, 120.0), "target_vol": (0.30, 1.20), "crypto_share": (0.30, 0.60)}
    assert vs.CALIBRATION_POINTS == ((10, 0.80, 0.50), (120, 0.80, 0.50))
    for fn in (dv.sigma_down, dv.downvol_path, dv.downvol_backtest):
        assert fn.__kwdefaults__["window"] is dv.downside
    assert set(dv.__all__) == {
        "DownVolStream",
        "StepSchedule",
        "downside",
        "downvol_backtest",
        "downvol_path",
        "q_shifted",
        "run_q_shift",
        "sigma_down",
        "stitched_steps",
    }


# ------------------------------------------------------------------------------------------------ the measure by hand


def test_the_downside_deviation_by_hand_divisor_l_factor_2_around_zero():
    """sigma_down = sqrt(365) x sqrt(2 x fsum(min(x, 0)^2) / L): the divisor is L (not L - 1), the factor 2 is there,
    and the reference is zero (not the window's mean)."""
    w = [-0.02, 0.0, 0.03, 0.01]
    want = SQ * math.sqrt(2.0 * ((-0.02) * (-0.02)) / 4)
    assert dv.downside(w) == want == independent_down(w)
    assert want == pytest.approx(SQ * math.sqrt(2e-4), rel=1e-15)
    assert want != pytest.approx(SQ * math.sqrt(2.0 * 4e-4 / 3), rel=1e-3)  # L - 1 would give this
    assert want != pytest.approx(SQ * math.sqrt(4e-4 / 4), rel=1e-3)  # no factor 2 would give this
    assert want != pytest.approx(math.sqrt(252.0) * math.sqrt(2e-4), rel=1e-3)  # not 252 days
    # zero is the reference: four equal down days have no spread around their mean, but a downside deviation
    flat_down = [-0.01] * 4
    assert vs._sigma(flat_down) == 0.0 and dv.downside(flat_down) == SQ * math.sqrt(2.0 * (4 * 1e-4) / 4)
    # ... and two up days with a spread around their mean have none around zero
    ups = [0.01, 0.03]
    assert vs._sigma(ups) > 0.0 and dv.downside(ups) == 0.0
    # an up day never counts, however large; a down day always does
    assert (
        dv.downside([-0.01, 5.0, 0.0])
        == dv.downside([-0.01, 0.0, 0.0])
        == independent_down([-0.01, 0.0, 0.0])
    )
    assert dv.downside([-0.01, -1e-9, 0.0]) > dv.downside([-0.01, 0.0, 0.0])


@pytest.mark.parametrize("lookback", [2, 4, 10, 30, 120])
@pytest.mark.parametrize("a", [0.003, 0.02, 0.07, 0.25])
def test_alternating_plus_minus_a_gives_sqrt_365_a_and_vol_steady_s_sigma_sqrt_l_over_l_minus_1(lookback, a):
    """For L returns alternating +a and -a (L even): sigma_down = sqrt(365) a and vol-steady's sigma = sqrt(365) a
    sqrt(L / (L - 1)), to 1e-12; on built returns and on a price path whose basket log returns alternate."""
    x = [math.nan, *([a, -a] * (lookback // 2 + 3))]
    c = len(x) - 1
    assert dv.sigma_down(x, lookback)[c] == pytest.approx(SQ * a, rel=1e-12, abs=0)
    assert vs.sigma_hat(x, lookback)[c] == pytest.approx(
        SQ * a * math.sqrt(lookback / (lookback - 1)), rel=1e-12
    )
    # on prices: both coins move together, so x_t = ln(C_t / C_t-1) = +-a up to the floats of exp and log1p
    n = lookback + 9
    closes = [100.0 * math.exp(a * (t % 2)) for t in range(n)]
    panel = panel_on(mondays(n), closes, [c_ * 0.07 for c_ in closes])
    xs = vs.basket_returns(panel)
    sig = dv.sigma_down(xs, lookback)
    for row in range(lookback, n):
        assert sig[row] == pytest.approx(SQ * a, rel=1e-12, abs=0)
        assert sig[row] == independent_down(xs[row - lookback + 1 : row + 1])


def test_no_down_day_gives_zero_and_the_full_share_even_when_up_days_are_far_wilder_than_tau():
    """The whole point of the rule: a window of only up days gives sigma_down = 0, so m = 1 and the full share,
    while vol-steady's sigma on the same path steps back to nothing."""
    n = 60
    closes = [100.0]
    for t in range(1, n):
        closes.append(closes[-1] * (1.30 if t % 2 else 1.0))  # +30% then flat, never a fall
    panel = panel_on(mondays(n), closes, [c * 0.05 for c in closes])
    down = dv.downvol_path(panel, 10, 0.30, 0.5)
    plain = vs.vol_path(panel, 10, 0.30, 0.5)
    assert down.activation == plain.activation == 14
    assert (down.sigma[down.checks] == 0.0).all() and (down.q[14:] == 1.0).all()
    assert (down.share[14:] == 0.5).all() and (down.share[:14] == 0.0).all()
    assert (plain.sigma[plain.checks] > 4 * 0.30).all() and (plain.q[14:] == 0.0).all()  # sigma > 4 tau: q 0
    assert vs.scale(0.0, 0.30) == 1.0


@given(n=st.integers(5, 80), lookback=st.integers(2, 12), data=st.data())
def test_sigma_down_reads_exactly_its_window_bit_for_bit(n, lookback, data):
    """sigma_down(c) equals the independent computation over x[c - L + 1 .. c] on every row c >= L, bit for bit
    (one fsum per window, no running sum); a change outside the window never moves it, a fall inside always does,
    and an up day inside that stays an up day never does."""
    rng = np.random.default_rng(data.draw(st.integers(0, 2**32 - 1)))
    x = np.concatenate([[math.nan], rng.normal(0.0, 0.03, n - 1)])
    sig = dv.sigma_down(x, lookback)
    for c in range(n):
        if c < lookback:
            assert math.isnan(sig[c])
        else:
            assert sig[c] == independent_down(x[c - lookback + 1 : c + 1])
    if n > lookback:
        c = data.draw(st.integers(lookback, n - 1))
        out = x.copy()
        outside = [t for t in range(1, n) if not c - lookback + 1 <= t <= c]
        out[outside] -= 0.5
        assert dv.sigma_down(out, lookback)[c] == sig[c]
        inside = x.copy()
        t = data.draw(st.integers(c - lookback + 1, c))
        inside[t] = min(inside[t], 0.0) - 0.5
        assert dv.sigma_down(inside, lookback)[c] > sig[c]
        up = x.copy()
        up[c - lookback + 1 : c + 1] = np.where(
            up[c - lookback + 1 : c + 1] >= 0.0,
            up[c - lookback + 1 : c + 1] + 3.0,
            up[c - lookback + 1 : c + 1],
        )
        assert dv.sigma_down(up, lookback)[c] == sig[c]
    # rows computed only where asked; the values are the same either way
    only = dv.sigma_down(x, lookback, rows=[n - 1, 0])
    assert np.isnan(only[: n - 1]).all() and (
        only[n - 1] == sig[n - 1] or (n - 1 < lookback and math.isnan(only[-1]))
    )


def test_q_on_a_path_exactly_on_each_quarter():
    """tau = sigma_down x 2^-k makes tau / sigma_down exactly 0.25, 0.5 or 1 at a check close, and the share in force
    from it is s x q; one ulp of tau below keeps the step (the 1e-9 tolerance), 4e-9 below drops a step."""
    panel = random_panel(120, 3, (0.04, 0.05), (0.0, 0.0))
    c = int(vs.first_check(panel.index, 20)) + 7
    sigma = dv.downvol_path(panel, 20, 1.0, 0.5).sigma[c]
    assert np.isfinite(sigma) and sigma > 0
    for k, q in ((2, 0.25), (1, 0.5), (0, 1.0)):
        tau = sigma * 2.0**-k
        assert tau / sigma == q
        p = dv.downvol_path(panel, 20, tau, 0.6)
        assert p.q[c] == q and p.share[c] == 0.6 * q
        assert dv.downvol_path(panel, 20, math.nextafter(tau, 0.0), 0.6).q[c] == q
        assert dv.downvol_path(panel, 20, tau * (1.0 - 4e-9), 0.6).q[c] == q - 0.25
    assert dv.downvol_path(panel, 20, sigma * 0.75, 0.6).q[c] == 0.75
    assert dv.downvol_path(panel, 20, sigma * 4.0, 0.6).q[c] == 1.0


def test_activation_the_checks_and_a_missing_monday_are_vol_steady_s():
    """Check closes are Mondays at rows >= L; before the first the book is all USDC; the share is held between checks,
    across a missing Monday too (the 13 closes from Monday 21 to Monday 35 once row 28 is gone); a panel with no check
    close is never invested; the daily-check description checks every close from row L."""
    panel = random_panel(70, 9, (0.06, 0.07), (0.01, 0.01))
    panel.index = mondays(70)
    p = dv.downvol_path(panel, 14, 0.4, 0.5)
    assert p.activation == 14 and p.checks.tolist() == [14, 21, 28, 35, 42, 49, 56, 63]
    assert (p.z[:14] == 0).all() and (p.z[14:] == 1).all() and (p.share[:14] == 0.0).all()
    moved = np.flatnonzero(np.diff(p.share)) + 1
    assert set(moved.tolist()) <= set(p.checks.tolist())
    res = run(P(14, 5.0, 0.5), panel)
    assert res.attrs["orders"][0] == 14 and res.attrs["reasons"][0] == "switch"
    assert (res["turnover"].iloc[:15] == 0.0).all() and res["turnover"].iloc[15] > 0
    gone = panel.drop(panel.index[28])
    q = dv.downvol_path(gone, 10, 0.4, 0.5)
    assert 21 in q.checks and 34 in q.checks and 27 not in q.checks
    assert (q.share[21:34] == q.share[21]).all() and (q.q[21:34] == q.q[21]).all()
    short = run(P(15, 5.0, 0.5), panel.iloc[:20])
    assert short.attrs["activation"] is None and short.attrs["orders"].size == 0
    assert np.isnan(short.attrs["sigma"]).all() and (short.attrs["z"] == 0).all()
    daily = dv.downvol_path(panel, 10, 0.4, 0.5, weekday=None)
    assert daily.checks.tolist() == list(range(10, 70)) and daily.activation == 10


def test_the_two_day_row_of_2018_01_13_enters_as_one_unscaled_return():
    """On the train grid close 2018-01-13 is missing: the window across it holds the 2-day basket return once."""
    panel = tr.random_walk_panel(5)
    idx = panel.index
    x = vs.basket_returns(panel)
    monday = idx.get_loc(pd.Timestamp("2018-01-15", tz="UTC"))
    row = idx.get_loc(pd.Timestamp("2018-01-14", tz="UTC"))
    cb, ce = panel[("BTC", "close")].to_numpy(), panel[("ETH", "close")].to_numpy()
    assert x[row] == math.log1p(0.5 * (cb[row] / cb[row - 1] - 1.0) + 0.5 * (ce[row] / ce[row - 1] - 1.0))
    for lookback in (2, 10, 50):
        assert dv.sigma_down(x, lookback)[monday] == independent_down(x[monday - lookback + 1 : monday + 1])
    assert monday in dv.downvol_path(panel, 10, 0.8, 0.5).checks


# ------------------------------------------------------------------------------------------------ point in time


@given(case=vol_cases(), data=st.data())
@example(case=(random_panel(120, 11, (0.05, 0.06), (0.01, 0.01)), P(10, 0.5, 0.5), LIMITS), data=None)
def test_no_look_ahead_in_the_measure_the_shares_the_orders_or_the_returns(case, data):
    """Tamper every field of both coins from the cut on (except the fill open of the cut): the measure, q, the shares,
    the targets, every result row, the orders and the fills before the cut are unchanged."""
    panel, params, limits = case
    base = run(params, panel, limits)
    act = base.attrs["activation"]
    if data is None:
        cuts = [c for c in (act, (act or 0) + 7, len(panel) - 1) if c is not None and 1 <= c < len(panel)]
    else:
        cuts = [data.draw(st.integers(1, len(panel) - 1))]
    for cut in cuts:
        bad = tamper_from(panel, cut, seed=cut)
        res = run(params, bad, limits)
        for key in ("share", "q", "z", "targets"):
            assert np.array_equal(res.attrs[key][:cut], base.attrs[key][:cut]), key
        assert np.array_equal(res.attrs["sigma"][:cut], base.attrs["sigma"][:cut], equal_nan=True)
        pd.testing.assert_frame_equal(res.iloc[:cut], base.iloc[:cut])
        before = base.attrs["orders"][base.attrs["orders"] < cut - 1]
        assert res.attrs["orders"][: len(before)].tolist() == before.tolist()
        same_fills(res, base, cut - 1)


def test_touching_the_present_moves_the_measure_at_t_never_before():
    """A fall on close t (a check close) moves sigma_down at t; nothing at t - 1."""
    panel = random_panel(80, 13, (0.04, 0.05), (0.0, 0.0))
    panel.index = mondays(80)
    t = 35
    base = dv.downvol_path(panel, 10, 0.5, 0.5)
    frames = {a: panel[a].copy() for a in pf.ASSETS}
    frames["BTC"].iloc[t, frames["BTC"].columns.get_loc("close")] *= 0.7
    frames["BTC"].iloc[t, frames["BTC"].columns.get_loc("low")] *= 0.7
    touched = dv.downvol_path(pf.make_panel(frames, snapshot_id="hand"), 10, 0.5, 0.5)
    assert touched.sigma[t] > base.sigma[t]
    assert np.array_equal(touched.share[:t], base.share[:t])


@given(
    panel=vol_panels(),
    lookback=st.integers(2, 30),
    tau=st.floats(0.05, 2.0),
    weekday=st.sampled_from([0, 4, None]),
)
def test_the_live_stream_equals_the_batch_on_every_close(panel, lookback, tau, weekday):
    """``DownVolStream`` fed one close at a time gives the batch share, q and sigma_down on every close, bit for bit."""
    path = dv.downvol_path(panel, lookback, tau, 0.55, weekday=weekday)
    stream = dv.DownVolStream(lookback, tau, 0.55, weekday=weekday)
    checks = set(path.checks.tolist())
    for t, (ts, b, e) in enumerate(
        zip(panel.index, panel[("BTC", "close")], panel[("ETH", "close")], strict=True)
    ):
        assert stream.update(ts, b, e) == path.share[t]
        assert stream.q == path.q[t]
        if t in checks:
            assert stream.sigma == path.sigma[t]


# ------------------------------------------------------------------------------------------------ the seam


@given(case=vol_cases(), weekday=st.sampled_from([0, 3, None]))
@example(case=(regime_panel(1002), P(30, 0.6, 0.5), LIMITS), weekday=0)
def test_with_vol_steady_s_measure_put_back_every_function_is_vol_steady_s_bit_for_bit(case, weekday):
    """The seam (section 17): with ``window=volsteady._sigma`` the measure, the path, the live stream and the
    BacktestFn equal vol-steady's bit for bit, so only the measure differs between the two studies."""
    panel, params, limits = case
    lookback, tau, s = params["lookback"], params["target_vol"], params["crypto_share"]
    x = vs.basket_returns(panel)
    assert np.array_equal(
        dv.sigma_down(x, lookback, window=vs._sigma), vs.sigma_hat(x, lookback), equal_nan=True
    )
    mine = dv.downvol_path(panel, lookback, tau, s, weekday=weekday, window=vs._sigma)
    theirs = vs.vol_path(panel, lookback, tau, s, weekday=weekday)
    for field in ("z", "share", "q", "checks"):
        assert np.array_equal(getattr(mine, field), getattr(theirs, field)), field
    assert np.array_equal(mine.sigma, theirs.sigma, equal_nan=True) and mine.activation == theirs.activation
    same_run(
        run(params, panel, limits, weekday=weekday, window=vs._sigma),
        vs.vol_backtest(params, panel, limits=limits, costs=COSTS, weekday=weekday),
    )
    a = dv.DownVolStream(lookback, tau, s, weekday=weekday, window=vs._sigma)
    b = vs.VolStream(lookback, tau, s, weekday=weekday)
    for ts, cb, ce in zip(panel.index, panel[("BTC", "close")], panel[("ETH", "close")], strict=True):
        assert a.update(ts, cb, ce) == b.update(ts, cb, ce) and a.q == b.q
        assert a.sigma == b.sigma or (math.isnan(a.sigma) and math.isnan(b.sigma))


def test_the_default_measure_differs_from_vol_steady_s_on_a_real_looking_path():
    """With the default measure the path is not vol-steady's (the seam is not a no-op)."""
    panel = regime_panel(1004)
    down, plain = dv.downvol_path(panel, 20, 0.6, 0.5), vs.vol_path(panel, 20, 0.6, 0.5)
    assert np.array_equal(down.checks, plain.checks) and down.activation == plain.activation
    assert not np.array_equal(down.sigma, plain.sigma, equal_nan=True) and not np.array_equal(down.q, plain.q)


# ------------------------------------------------------------------------------------------------ the encoding


def test_the_encoding_is_z_from_activation_and_the_share_split_50_50():
    """downvol_backtest is ``trend.run_states(in_force(z, share), states=z)``: targets (s q / 2, s q / 2); reasons
    switch (activation), re-cut (a step) and limit (a fix)."""
    panel = random_panel(200, 21, (0.06, 0.08), (0.01, 0.01))
    res = run(P(10, 0.4, 0.6), panel)
    path = dv.downvol_path(panel, 10, 0.4, 0.6)
    assert np.array_equal(res.attrs["targets"], np.column_stack([path.share * 0.5, path.share * 0.5]))
    direct = tr.run_states(panel, tr.in_force(path.z, path.share), limits=LIMITS, costs=COSTS, states=path.z)
    pd.testing.assert_frame_equal(res, direct)
    assert res.attrs["order_hash"] == direct.attrs["order_hash"]
    assert set(np.unique(path.q).tolist()) <= set(vs.QUARTERS) and len(set(path.q.tolist())) >= 3
    reasons = res.attrs["reasons"].tolist()
    assert reasons[0] == "switch" and reasons.count("switch") == 1 and "re-cut" in reasons
    validate_result(res, panel)


def test_a_target_above_every_sigma_is_n0_s_always_in_path_from_activation():
    """With tau above every sigma_down, q = 1 from activation: the run is the always-in path ordered at activation."""
    panel = regime_panel(1001)
    res = run(P(33, 1e6, 0.4), panel)
    act = res.attrs["activation"]
    n = len(panel)
    ref = tr.from_t0(
        panel,
        np.zeros((n, 2)),
        panel.index[act],
        tr.share_targets(0.4),
        limits=LIMITS,
        costs=COSTS,
        base_states=np.zeros((n, 2), dtype=np.int8),
        target_state=(1, 1),
    )
    pd.testing.assert_frame_equal(res, ref)
    assert res.attrs["order_hash"] == ref.attrs["order_hash"]


@given(case=vol_cases(), costs=st.sampled_from([COSTS, COSTS.stressed()]))
def test_accounting_equals_an_independent_book_of_coin_units_and_cash(case, costs):
    """Every return, cost and weight equals ``test_trend.vector_book`` (coin units and USDC cash), to 1e-12."""
    panel, params, limits = case
    res = run(params, panel, limits, costs)
    out, _, _, _ = vector_book(panel, res, costs)
    for col in ("ret", "turnover", "cost", "w_BTC", "w_ETH"):
        np.testing.assert_allclose(res[col].to_numpy(), out[col], rtol=0, atol=1e-12, err_msg=col)


def test_decisions_never_depend_on_costs_or_the_book_size():
    """The orders hash the same at 1x, 2x and other book sizes (stop rule 13)."""
    panel = regime_panel(1003)
    hashes = {
        run(P(20, 0.5, 0.5), panel, costs=c).attrs["order_hash"]
        for c in (COSTS, COSTS.stressed(), *(Costs(capital_usd=b) for b in (100.0, 500.0, 50_000.0)))
    }
    assert len(hashes) == 1


def test_h0_reproduces_walk_forward_optimize_bit_for_bit(tmp_path):
    panel = regime_panel()
    windows = tr.fold_windows(panel.index)
    fn = partial(dv.downvol_backtest, limits=LIMITS, costs=COSTS)
    folds = walk_forward(len(panel), 365, 365, expanding=True)
    wf = walk_forward_optimize(
        "downvol-t",
        fn,
        list(vs.SPECS),
        panel,
        folds,
        tmp_path,
        SearchConfig(n_trials=3, n_workers=1, seed=0),
        warmup=tr.WARMUP,
    )
    parts = []
    for i, window in enumerate(windows):
        row = wf["folds"].iloc[i]
        res = sd.run_h120(fn, {name: row[f"p_{name}"] for name in vs.PARAM_NAMES}, panel, window)
        parts.append(sd.kept_returns(res, window.t0))
        assert row["oos_trades"] == sd.kept_fills(res, window.t0)
    pd.testing.assert_series_equal(pd.concat(parts), wf["oos_returns"], check_names=False)


# ------------------------------------------------------------------------------------------------ refusals


def test_bad_inputs_are_refused_with_pinned_messages():
    with pytest.raises(ValueError, match=r"unknown params \['buffer'\]"):
        run({**P(), "buffer": 0.1}, random_panel(30, 1))
    with pytest.raises(ValueError, match="lookback must be >= 2"):
        run(P(lookback=1), random_panel(30, 1))
    with pytest.raises(ValueError, match="lookback must be an integer >= 2"):
        dv.sigma_down([math.nan, 0.1, 0.2], 1)
    with pytest.raises(ValueError, match="finite basket returns from row 1 on"):
        dv.sigma_down([math.nan, math.nan, 0.2], 2)
    with pytest.raises(ValueError, match="finite basket returns from row 1 on"):
        dv.sigma_down(np.zeros((2, 2)), 2)
    with pytest.raises(ValueError, match="row 5 is outside the 3 closes"):
        dv.sigma_down([math.nan, 0.1, 0.2], 2, rows=[5])
    assert np.isnan(dv.sigma_down([math.nan, 0.1, 0.2], 2, rows=[1])).all()  # a row before L stays NaN
    with pytest.raises(ValueError, match="weekday must be an integer in 0..6"):
        dv.downvol_path(random_panel(30, 1), 5, 0.5, 0.5, weekday=7)
    with pytest.raises(ValueError, match=r"target_vol must be in \(0.0, inf\)"):
        dv.downvol_path(random_panel(30, 1), 5, 0.0, 0.5)
    with pytest.raises(ValueError, match="lookback must be an integer >= 2"):
        dv.DownVolStream(1, 0.5, 0.5)
    stream = dv.DownVolStream(3, 0.5, 0.5)
    with pytest.raises(ValueError, match="tz-aware"):
        stream.update(pd.Timestamp("2021-01-01"), 1.0, 1.0)
    stream.update(pd.Timestamp("2021-01-02", tz="UTC"), 1.0, 1.0)
    with pytest.raises(ValueError, match="strictly increasing"):
        stream.update(pd.Timestamp("2021-01-02", tz="UTC"), 1.0, 1.0)
    with pytest.raises(ValueError, match=r"close must be in \(0.0, inf\)"):
        stream.update(pd.Timestamp("2021-01-03", tz="UTC"), 0.0, 1.0)
    with pytest.raises(ValueError, match="stop rule 12"):
        run(P(10, 5.0, 0.79), random_panel(40, 2))  # (0.395, 0.395) leaves 21% cash, below 20% + h


# ------------------------------------------------------------------------------------------------ the q-only shift


def two_fold_layout(s0=0.4, s1=0.6):
    """60 daily closes from a Monday; fold 0's test span rows 10..29 (checks 14, 21, 28), fold 1's rows 30..59
    (checks 35, 42, 49, 56). Each fold's H0 path is a prefix (rows 0 .. last_i) activated at row 7, its q set by hand
    at every Monday; its share is s_i x q."""
    idx = mondays(60)
    windows = [(idx[10], idx[29]), (idx[30], idx[59])]
    q0 = share_path(30, {7: 1.0, 14: 0.5, 21: 0.25, 28: 1.0})
    q1 = share_path(60, {7: 1.0, 14: 1.0, 21: 0.75, 28: 0.75, 35: 0.0, 42: 0.5, 49: 1.0, 56: 0.25})
    z0, z1 = np.zeros((30, 2), dtype=np.int8), np.zeros((60, 2), dtype=np.int8)
    z0[7:], z1[7:] = 1, 1
    steps = dv.stitched_steps(idx, windows, [z0, z1], [s0 * q0, s1 * q1], [q0, q1], [s0, s1])
    return idx, windows, steps, (z0, z1), (q0, q1)


def test_the_q_only_shift_by_hand_on_a_two_fold_path():
    """M1: share_u(c_k) = s_fold(c_k) x q(c_((k + u) mod W)): each check keeps its own fold's s and takes the step of
    the check u places on; the rows before c_0, the check closes and the fold labels are unchanged. VP's whole-schedule
    shift moves s with q, so it differs where the folds' s differ."""
    idx, windows, steps, _, (q0, _) = two_fold_layout()
    sch = steps.schedule
    assert sch.checks.tolist() == [14, 21, 28, 35, 42, 49, 56] and sch.fold.tolist() == [0, 0, 0, 1, 1, 1, 1]
    assert steps.q.tolist() == [0.5, 0.25, 1.0, 0.0, 0.5, 1.0, 0.25]
    assert steps.s.tolist() == [0.4, 0.4, 0.4, 0.6, 0.6, 0.6, 0.6]
    assert sch.share.tolist() == [0.2, 0.1, 0.4, 0.0, 0.3, 0.6, 0.15]
    assert np.array_equal(sch.head_share, 0.4 * q0[:14])  # fold 0's per-row head (VP's M1)
    got = dv.q_shifted(steps, 2)
    assert got.share.tolist() == [0.4, 0.0, 0.2, 0.6, 0.15, 0.3, 0.15]  # s_k x q_(k+2): 0.4 x 1, 0.4 x 0, ...
    assert tr.shifted(sch, 2).share.tolist() == [0.4, 0.0, 0.3, 0.6, 0.15, 0.2, 0.1]  # whole: s moves too
    for field in ("checks", "fold", "head_z", "head_share"):
        assert np.array_equal(getattr(got, field), getattr(sch, field)), field
    assert np.array_equal(dv.q_shifted(steps, 0).share, sch.share) and np.array_equal(
        dv.q_shifted(steps, 0).z, sch.z
    )
    for u in range(7):  # each check keeps its fold's s; the steps are a rotation (no price is read)
        sh = dv.q_shifted(steps, u)
        assert np.array_equal(sh.share, steps.s * np.roll(steps.q, -u))
        assert sorted((sh.share / steps.s).tolist()) == sorted(steps.q.tolist())
    # run as one book from row 0: rows before c_0 are fold 0's head, then the shifted entry of the latest check
    panel = random_panel(60, 4, (0.03, 0.04), (0.0, 0.0))
    panel.index = idx
    res = dv.run_q_shift(panel, steps, limits=LIMITS, costs=COSTS, u=2)
    want = np.concatenate(
        [0.4 * q0[:14], np.repeat([0.4, 0.0, 0.2, 0.6, 0.15, 0.3, 0.15], [7, 7, 7, 7, 7, 7, 4])]
    )
    assert np.array_equal(res.attrs["targets"], np.column_stack([want * 0.5, want * 0.5]))
    same_run_rows = tr.run_span(panel, sch, limits=LIMITS, costs=COSTS)
    pd.testing.assert_frame_equal(dv.run_q_shift(panel, steps, limits=LIMITS, costs=COSTS), same_run_rows)


def test_the_q_only_shift_moves_z_with_q():
    """The state pair (activation) travels with the step it belongs to; here a fold whose first check precedes its
    activation, so a q of 0 with z = (0, 0) moves."""
    idx = mondays(60)
    windows = [(idx[3], idx[29]), (idx[30], idx[59])]
    q0 = share_path(30, {14: 0.5, 21: 1.0, 28: 0.25})
    q1 = share_path(60, {14: 1.0, 35: 0.75, 42: 0.5, 49: 1.0, 56: 0.0})
    z0, z1 = np.zeros((30, 2), dtype=np.int8), np.zeros((60, 2), dtype=np.int8)
    z0[14:], z1[14:] = 1, 1
    steps = dv.stitched_steps(idx, windows, [z0, z1], [0.3 * q0, 0.5 * q1], [q0, q1], [0.3, 0.5])
    assert steps.schedule.checks.tolist() == [7, 14, 21, 28, 35, 42, 49, 56]
    assert steps.schedule.z[:, 0].tolist() == [0, 1, 1, 1, 1, 1, 1, 1]
    got = dv.q_shifted(steps, 1)
    assert got.z[:, 0].tolist() == [1, 1, 1, 1, 1, 1, 1, 0] and got.share.tolist()[-1] == 0.5 * 0.0


@given(u=st.integers(0, 6), s=st.sampled_from([0.3, 0.45, 0.6]))
def test_with_one_s_in_every_fold_the_q_only_shift_is_vp_s_whole_schedule_shift_bit_for_bit(u, s):
    """M1: with s held equal in every fold the q-only shift equals ``trend.shifted`` (VP's shift) bit for bit, the
    schedule and the run (every row, the orders and their hash)."""
    idx, _, steps, _, _ = two_fold_layout(s, s)
    a, b = dv.q_shifted(steps, u), tr.shifted(steps.schedule, u)
    assert (
        np.array_equal(a.share, b.share) and np.array_equal(a.z, b.z) and np.array_equal(a.checks, b.checks)
    )
    panel = random_panel(60, 6, (0.03, 0.04), (0.0, 0.0))
    panel.index = idx
    x = dv.run_q_shift(panel, steps, limits=LIMITS, costs=COSTS, u=u)
    y = tr.run_span(panel, steps.schedule, limits=LIMITS, costs=COSTS, u=u)
    pd.testing.assert_frame_equal(x, y)
    assert x.attrs["order_hash"] == y.attrs["order_hash"] and np.array_equal(
        x.attrs["targets"], y.attrs["targets"]
    )


def test_stitched_steps_and_q_shifted_refusals():
    idx, windows, steps, (z0, z1), (q0, q1) = two_fold_layout()
    with pytest.raises(ValueError, match="one q path and one s per fold"):
        dv.stitched_steps(idx, windows, [z0, z1], [0.4 * q0, 0.6 * q1], [q0], [0.4, 0.6])
    with pytest.raises(ValueError, match="one q path and one s per fold"):
        dv.stitched_steps(idx, windows, [z0, z1], [0.4 * q0, 0.6 * q1], [q0, q1], [0.4])
    with pytest.raises(ValueError, match="fold 1 q must be one step"):
        dv.stitched_steps(idx, windows, [z0, z1], [0.4 * q0, 0.6 * q1], [q0, q1[:-1]], [0.4, 0.6])
    with pytest.raises(ValueError, match="fold 0 q must be one step"):
        dv.stitched_steps(idx, windows, [z0, z1], [0.4 * q0, 0.6 * q1], [q0 * 0.9, q1], [0.4, 0.6])
    with pytest.raises(ValueError, match=r"crypto_share must be in \[0.0, 1.0\]"):
        dv.stitched_steps(idx, windows, [z0, z1], [0.4 * q0, 0.6 * q1], [q0, q1], [0.4, 1.2])
    with pytest.raises(ValueError, match=r"row 42 \(fold 1\) is not its fold's s x q"):
        dv.stitched_steps(idx, windows, [z0, z1], [0.4 * q0, 0.6 * q1], [q0, q1], [0.4, 0.5])
    with pytest.raises(ValueError, match=r"row 14 \(fold 0\) is not its fold's s x q"):
        dv.stitched_steps(idx, windows, [z0, z1], [0.4 * q0, 0.6 * q1], [q1[:30], q1], [0.4, 0.6])
    with pytest.raises(ValueError, match=r"u must be in 0..6, got 7"):
        dv.q_shifted(steps, 7)
    with pytest.raises(ValueError, match="u must be an integer >= 0"):
        dv.q_shifted(steps, -1)


# ------------------------------------------------------------------------------------------------ R_0 on the fold layout


FOLD_PARAMS = [P(10, 0.5, 0.30), P(30, 0.9, 0.60), P(60, 0.4, 0.45), P(120, 1.2, 0.50), P(15, 0.3, 0.35)]


class Span:
    def __init__(self):
        self.panel = regime_panel()
        self.windows = tr.fold_windows(self.panel.index)
        self.runs = [
            run(p, tr.h0_slice(self.panel, w)) for p, w in zip(FOLD_PARAMS, self.windows, strict=True)
        ]
        self.steps = dv.stitched_steps(
            self.panel.index,
            self.windows,
            [r.attrs["z"] for r in self.runs],
            [r.attrs["share"] for r in self.runs],
            [r.attrs["q"] for r in self.runs],
            [p["crypto_share"] for p in FOLD_PARAMS],
        )
        self.r0 = tr.run_span(self.panel, self.steps.schedule, limits=LIMITS, costs=COSTS)


@pytest.fixture(scope="module")
def span() -> Span:
    return Span()


def test_r0_s_steps_carry_each_fold_s_q_and_the_schedule_is_vp_s(span):
    """R_0's schedule is ``volsteady.stitched_schedule`` of the fold runs; each check's q and s are the fold's own;
    R_0 equals S on fold 0's kept rows and holds S's book at t0; shift 0 is R_0."""
    steps, sch = span.steps, span.steps.schedule
    vp = vs.stitched_schedule(
        span.panel.index,
        span.windows,
        [r.attrs["z"] for r in span.runs],
        [r.attrs["share"] for r in span.runs],
    )
    for field in ("checks", "z", "share", "fold", "head_z", "head_share"):
        assert np.array_equal(getattr(sch, field), getattr(vp, field)), field
    assert len(sch.checks) == 260
    for k, (c, i) in enumerate(zip(sch.checks.tolist(), sch.fold.tolist(), strict=True)):
        assert steps.q[k] == span.runs[i].attrs["q"][c] and steps.s[k] == FOLD_PARAMS[i]["crypto_share"]
        assert sch.share[k] == steps.s[k] * steps.q[k]
    w0 = span.windows[0]
    assert tr.same_book_at(span.r0, span.runs[0], w0.t0)
    k0 = sd.kept_returns(span.runs[0], w0.t0)
    assert np.array_equal(span.r0["ret"].loc[k0.index].to_numpy(), k0.to_numpy())
    pd.testing.assert_frame_equal(dv.run_q_shift(span.panel, steps, limits=LIMITS, costs=COSTS, u=0), span.r0)


def test_q_only_shifts_on_the_fold_layout_hold_s_s_book_and_keep_each_fold_s(span):
    steps = span.steps
    for u in (53, 120, 259):
        sh = dv.q_shifted(steps, u)
        assert np.array_equal(sh.share, steps.s * np.roll(steps.q, -u))
        whole = tr.shifted(steps.schedule, u)
        assert not np.array_equal(sh.share, whole.share)  # the folds' s differ, so the two nulls differ
        res = dv.run_q_shift(span.panel, steps, limits=LIMITS, costs=COSTS, u=u)
        assert tr.same_book_at(res, span.runs[0], span.windows[0].t0)
        sch = steps.schedule
        for i, w in enumerate(
            span.windows
        ):  # from each fold's first check on, the share in force is s_i x some q
            first = int(sch.checks[sch.fold == i][0])
            last = span.panel.index.get_loc(w.last)
            total = res.attrs["targets"][first : last + 1].sum(axis=1)
            assert set(np.round(total / FOLD_PARAMS[i]["crypto_share"], 12).tolist()) <= set(vs.QUARTERS)


# ------------------------------------------------------------------------------------------------ calibration (slow)


@pytest.mark.slow
@pytest.mark.parametrize(("lookback", "target_vol", "share"), vs.CALIBRATION_POINTS)
def test_e1_s_false_positive_rate_on_driftful_random_walks(lookback, target_vol, share):
    """Section 13 (VP 9): on 200 iid Gaussian random-walk panels (seeds 0..199; no clustering, no edge) the fixed rule
    runs in H0 as one span from row 0; its schedule over the 260 Monday checks of the fold layout is R_0, scored on the
    1820 kept rows against its 207 guarded q-only shifts at 1x (one s, so VP's shifts bit for bit), E1's rank-p rule.
    At most 18 of 200 panels may pass."""
    idx = tr.train_grid()
    windows = tr.fold_windows(idx)
    kept_rows = np.concatenate([np.flatnonzero((idx > w.t0) & (idx <= w.last)) for w in windows])
    assert len(kept_rows) == 1820
    ends = [idx.get_loc(w.last) + 1 for w in windows]
    offsets = tr.guarded_offsets(260)
    passes, moved = 0, 0
    for seed in range(200):
        panel = tr.random_walk_panel(seed)
        path = dv.downvol_path(panel, lookback, target_vol, share)
        steps = dv.stitched_steps(
            idx,
            windows,
            [path.z[:e] for e in ends],
            [path.share[:e] for e in ends],
            [path.q[:e] for e in ends],
            [share] * 5,
        )
        for u in (53, 259):
            assert np.array_equal(dv.q_shifted(steps, u).share, tr.shifted(steps.schedule, u).share)
        moved += len(set(steps.schedule.share.tolist())) > 1
        series = {
            u: dv.run_q_shift(panel, steps, limits=LIMITS, costs=COSTS, u=int(u))["ret"].to_numpy()[kept_rows]
            for u in [0, *offsets.tolist()]
        }
        passes += tr.e1_test(series[0], series, 260)["holds"]
    print(
        f"calibration ({lookback}, {target_vol}, {share}): {passes} of 200 pass E1; the share moved on {moved}"
    )
    assert moved >= 190, moved
    assert passes <= 18, passes
