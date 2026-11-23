"""vol-steady (``lab/runner/volsteady.py``, scouting only): the volatility-scaled hold, encoded in trend-steady's one
executor (``research/vol-steady/PLAN.md`` sections 4-11 and the section 17 test list; TP = trend-steady's PLAN.md).

Synthetic data and hand-built paths only: no catalog bar is read. The executor, the shift, N0, X and the luck
statistics are ``lab.runner.trend``'s and are tested in ``test_trend.py``; this file tests the rule, its encoding into
them, the helpers that differ, and the composition (accounting against ``test_trend.vector_book``, an independent book
in coin units and USDC cash).
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

from lab.runner import portfolio as pf
from lab.runner import steady as sd
from lab.runner import trend as tr
from lab.runner import volsteady as vs
from lab.runner.interface import validate_result
from lab.runner.reference import Costs
from lab.search.space import Param
from lab.search.study import SearchConfig
from lab.search.walkforward import walk_forward_optimize
from lab.validation.splits import walk_forward

LIMITS = {"min_cash": 0.20, "max_coin": 0.60}  # Steady's limits as read (test_portfolio pins the real file)
TIGHT = {"min_cash": 0.20, "max_coin": 0.40}
COSTS = Costs()
SQ = math.sqrt(365.0)
ALL_HOLD = dict.fromkeys(tr.CRITERIA, True)

# ------------------------------------------------------------------------------------------------ helpers


def V(lookback=10, target_vol=0.6, share=0.5) -> dict:
    return {"lookback": lookback, "target_vol": target_vol, "crypto_share": share}


def run(params, panel, limits=LIMITS, costs=COSTS, **kw) -> pd.DataFrame:
    return vs.vol_backtest(params, panel, limits=limits, costs=costs, **kw)


def mondays(n: int, start: str = "2017-01-02") -> pd.DatetimeIndex:
    """n daily closes from a Monday (rows 0, 7, 14, ... are Mondays)."""
    return pd.date_range(start, periods=n, freq="D", tz="UTC", name="ts")


def two_pass(window) -> float:
    """sqrt(365) x the sample sd, written out independently: fsum mean, fsum of squared deviations, ddof 1."""
    w = [float(v) for v in window]
    mean = math.fsum(w) / len(w)
    return math.sqrt(365.0) * math.sqrt(math.fsum((v - mean) * (v - mean) for v in w) / (len(w) - 1))


def basket(panel) -> list[float]:
    cb = panel[("BTC", "close")].to_numpy().tolist()
    ce = panel[("ETH", "close")].to_numpy().tolist()
    return [math.nan] + [
        math.log1p(0.5 * (cb[t] / cb[t - 1] - 1.0) + 0.5 * (ce[t] / ce[t - 1] - 1.0))
        for t in range(1, len(cb))
    ]


def windows_of(index) -> list:
    return tr.fold_windows(index)


def fold_runs(panel, params_per_fold, windows, limits=LIMITS, costs=COSTS):
    return [
        run(p, tr.h0_slice(panel, w), limits=limits, costs=costs)
        for p, w in zip(params_per_fold, windows, strict=True)
    ]


def kept(result, window) -> pd.Series:
    return sd.kept_returns(result, window.t0)


@st.composite
def vol_panels(draw, min_size: int = 60, max_size: int = 260) -> pd.DataFrame:
    n = draw(st.integers(min_size, max_size))
    seed = draw(st.integers(0, 2**32 - 1))
    vols = tuple(draw(st.sampled_from([0.005, 0.02, 0.05, 0.09])) for _ in pf.ASSETS)
    gaps = tuple(draw(st.sampled_from([0.0, 0.005, 0.03])) for _ in pf.ASSETS)
    return random_panel(n, seed, vols, gaps)


@st.composite
def vol_cases(draw):
    """(panel, params, limits): short lookbacks and targets near the drawn panels' volatility, so q moves."""
    panel = draw(vol_panels())
    limits = draw(st.sampled_from([LIMITS, TIGHT]))
    top = 0.76 if limits is TIGHT else 0.78
    share = draw(st.one_of(st.sampled_from([0.3, 0.5, 0.6, top]), st.floats(0.05, top)))
    tau = draw(st.one_of(st.sampled_from([0.1, 0.3, 0.6, 1.2]), st.floats(0.05, 2.0)))
    return panel, V(draw(st.integers(2, 40)), tau, share), limits


# ------------------------------------------------------------------------------------------------ pinned values


def test_the_pinned_values_are_the_plan_s():
    """Section 5's box, the allowed values, the quarters, the first active row and the calibration points."""
    assert vs.SPECS == (
        Param("lookback", "int", 10, 120, log=True),
        Param("target_vol", "float", 0.30, 1.20, log=True),
        Param("crypto_share", "float", 0.30, 0.60),
    )
    assert vs.PARAM_NAMES == ("lookback", "target_vol", "crypto_share")
    assert vs.BOX == {"lookback": (10.0, 120.0), "target_vol": (0.30, 1.20), "crypto_share": (0.30, 0.60)}
    assert vs.ALLOWED_S == (0.30, 0.40, 0.50, 0.60)
    assert vs.QUARTERS == (0.0, 0.25, 0.5, 0.75, 1.0) and vs.Q_TOL == 1e-9
    assert vs.SQRT_365 == math.sqrt(365.0) and vs.MIN_LOOKBACK == 2
    assert vs.CALIBRATION_POINTS == ((10, 0.80, 0.50), (120, 0.80, 0.50))
    assert vs.TIMING_KEYS == ("study", "run", "bootstrap")
    assert (vs.MIN_CHANGES, vs.MIN_CHANGE_FOLDS) == (20, 4)
    # the first active row: L = 10 first checks at row 14 (Monday 2017-01-16) of the train grid; filled at row 15
    grid = tr.train_grid()
    assert vs.first_check(grid, 10) == 14 and grid[14] == pd.Timestamp("2017-01-16", tz="UTC")
    assert vs.FIRST_ACTIVE_ROW == vs.first_check(grid, 10) + 1 == 15
    assert vs.first_check(grid, 8) == 14  # the plateau's smallest L (0.8 x 10) starts no earlier


# ------------------------------------------------------------------------------------------------ the signal by hand


def test_basket_returns_by_hand():
    """x_t = log1p(0.5 (C_BTC,t / C_BTC,t-1 - 1) + 0.5 (C_ETH,t / C_ETH,t-1 - 1)); NaN at row 0."""
    idx = mondays(4)
    panel = panel_on(idx, [100.0, 110.0, 99.0, 99.0], [50.0, 50.0, 60.0, 30.0])
    x = vs.basket_returns(panel)
    assert math.isnan(x[0])
    assert x[1] == math.log1p(0.5 * (110.0 / 100.0 - 1.0) + 0.5 * 0.0)
    assert x[2] == math.log1p(0.5 * (99.0 / 110.0 - 1.0) + 0.5 * (60.0 / 50.0 - 1.0))
    assert x[3] == math.log1p(0.0 + 0.5 * (30.0 / 60.0 - 1.0)) == math.log(0.75)
    assert x.tolist()[1:] == basket(panel)[1:]


def test_sigma_by_hand_sqrt_365_ddof_1_and_a_flat_path():
    """sigma = sqrt(365) x the sample sd (ddof 1), two fsum passes; a flat path gives sigma = 0, so m = 1 and q = 1."""
    x = np.array([math.nan, 0.01, -0.01, 0.02])
    sig = vs.sigma_hat(x, 2)
    assert np.isnan(sig[:2]).all()
    assert sig[2] == SQ * math.sqrt(((0.01 - 0.0) ** 2 + (-0.01 - 0.0) ** 2) / 1)  # mean 0, ddof 1
    assert sig[2] == pytest.approx(math.sqrt(365.0 * 2e-4), rel=1e-15)
    assert sig[2] != pytest.approx(math.sqrt(365.0 * 1e-4), rel=1e-3)  # ddof 0 would give this
    assert sig[2] != pytest.approx(math.sqrt(252.0 * 2e-4), rel=1e-3)  # not 252 days
    assert sig[3] == two_pass([-0.01, 0.02])
    assert vs.sigma_hat(x, 3)[3] == two_pass([0.01, -0.01, 0.02])
    assert vs.sigma_hat(x, 3)[3] == pytest.approx(np.std([0.01, -0.01, 0.02], ddof=1) * SQ, rel=1e-14)
    # rows computed only where asked; the values are the same either way
    only = vs.sigma_hat(x, 2, rows=[3, 0])
    assert np.isnan(only[:3]).all() and only[3] == sig[3]
    # a flat path: x = 0, sigma = 0, m = 1, q = 1, the full share from activation
    idx = mondays(30)
    flat = panel_on(idx, [100.0] * 30, [50.0] * 30)
    path = vs.vol_path(flat, 5, 0.3, 0.5)
    assert path.activation == 7 and (path.sigma[path.checks] == 0.0).all()
    assert vs.scale(0.0, 0.3) == 1.0 and (path.q[7:] == 1.0).all() and (path.share[7:] == 0.5).all()


@given(n=st.integers(5, 80), lookback=st.integers(2, 12), data=st.data())
def test_sigma_reads_exactly_its_window_bit_for_bit(n, lookback, data):
    """sigma(c) equals the independent two-pass over x[c - L + 1 .. c] on every row c >= L, bit for bit (no running
    sum), and changing an x outside that window never moves it while changing one inside does."""
    rng = np.random.default_rng(data.draw(st.integers(0, 2**32 - 1)))
    x = np.concatenate([[math.nan], rng.normal(0.0, 0.03, n - 1)])
    sig = vs.sigma_hat(x, lookback)
    for c in range(n):
        if c < lookback:
            assert math.isnan(sig[c])
        else:
            assert sig[c] == two_pass(x[c - lookback + 1 : c + 1])
    if n > lookback:
        c = data.draw(st.integers(lookback, n - 1))
        out = x.copy()
        outside = [t for t in range(1, n) if not c - lookback + 1 <= t <= c]
        out[outside] += 0.5
        assert vs.sigma_hat(out, lookback)[c] == sig[c]
        inside = x.copy()
        inside[c - lookback + 1] += 0.5
        assert vs.sigma_hat(inside, lookback)[c] != sig[c]


def test_quarter_steps_at_their_boundaries():
    """q = floor(4 m + 1e-9) / 4: exactly on 0.25, 0.5, 0.75 and 1 gives that step; one ulp below gives it too (the
    1e-9 tolerance, as pinned); 1e-9 below gives the step under it. A floor, not a rounding."""
    for b in (0.25, 0.5, 0.75, 1.0):
        assert vs.quarter(b) == b
        assert vs.quarter(math.nextafter(b, 0.0)) == b
        assert vs.quarter(b - 1e-9) == b - 0.25
        assert vs.quarter(b - 2.4e-10) == b  # inside the tolerance (1e-9 / 4 = 2.5e-10)
        assert vs.quarter(b - 2.6e-10) == b - 0.25
    assert vs.quarter(0.0) == 0.0 and vs.quarter(0.2499) == 0.0
    assert vs.quarter(0.49) == 0.25 and vs.quarter(0.74) == 0.5 and vs.quarter(0.99) == 0.75
    assert vs.scale(0.8, 0.4) == 0.5 and vs.scale(0.4, 0.8) == 1.0 and vs.scale(2.0, 0.3) == 0.15
    assert vs.quarter(vs.scale(4.0, 1.0)) == 0.25 and vs.quarter(vs.scale(4.0 + 1e-6, 1.0)) == 0.0


def test_q_on_a_path_exactly_on_each_quarter():
    """On a real path, tau = sigma x 2^-k makes tau / sigma exactly 0.25, 0.5 or 1 at a check close, and the share in
    force from it is s x q; one ulp of tau below the boundary keeps the step, 4e-9 below drops a step."""
    panel = random_panel(120, 3, (0.04, 0.05), (0.0, 0.0))
    c = int(vs.first_check(panel.index, 20)) + 7
    sigma = vs.vol_path(panel, 20, 1.0, 0.5).sigma[c]
    assert np.isfinite(sigma) and sigma > 0
    for k, q in ((2, 0.25), (1, 0.5), (0, 1.0)):
        tau = sigma * 2.0**-k
        assert tau / sigma == q
        p = vs.vol_path(panel, 20, tau, 0.6)
        assert p.q[c] == q and p.share[c] == 0.6 * q
        assert vs.vol_path(panel, 20, math.nextafter(tau, 0.0), 0.6).q[c] == q
        assert vs.vol_path(panel, 20, tau * (1.0 - 4e-9), 0.6).q[c] == q - 0.25
    three = vs.vol_path(panel, 20, sigma * 0.75, 0.6)
    assert three.q[c] == 0.75 and three.share[c] == 0.6 * 0.75
    assert vs.vol_path(panel, 20, sigma * 4.0, 0.6).q[c] == 1.0  # tau above sigma: the full share


def test_activation_is_the_first_monday_at_or_after_row_l_and_the_book_starts_all_usdc():
    """Check closes are Mondays at rows >= L (inclusive); before the first, z = 0, the share is 0 and nothing is
    ordered; the first order (at activation) fills at the next open."""
    idx = mondays(60)
    panel = random_panel(60, 5, (0.04, 0.05), (0.01, 0.01))
    panel.index = idx
    assert vs.first_check(idx, 14) == 14 and vs.first_check(idx, 15) == 21 and vs.first_check(idx, 7) == 7
    assert vs.first_check(idx[:20], 15) is None
    res = run(V(14, 5.0, 0.5), panel)
    assert res.attrs["activation"] == 14 and res.attrs["checks"].tolist() == [14, 21, 28, 35, 42, 49, 56]
    assert (res.attrs["z"][:14] == 0).all() and (res.attrs["z"][14:] == 1).all()
    assert (res.attrs["share"][:14] == 0.0).all() and (res.attrs["share"][14:] == 0.5).all()
    assert res.attrs["orders"][0] == 14 and res.attrs["reasons"][0] == "switch"
    assert (res["turnover"].iloc[:15] == 0.0).all() and res["turnover"].iloc[15] > 0
    assert (res[["w_BTC", "w_ETH"]].iloc[:15].to_numpy() == 0.0).all()
    # no check close in the panel: never invested
    short = run(V(15, 5.0, 0.5), panel.iloc[:20])
    assert short.attrs["activation"] is None and short.attrs["orders"].size == 0
    assert (short["turnover"] == 0.0).all() and (short.attrs["z"] == 0).all()


def test_the_share_changes_only_at_check_closes_and_a_missing_monday_is_skipped():
    """Between Mondays the share is held; with a Monday close missing, the next check is the following Monday; the
    daily-check description (weekday None) checks every close from row L."""
    panel = random_panel(70, 9, (0.06, 0.07), (0.0, 0.0))
    panel.index = mondays(70)
    p = vs.vol_path(panel, 10, 0.4, 0.5)
    moved = np.flatnonzero(np.diff(p.share)) + 1
    assert set(moved.tolist()) <= set(p.checks.tolist())
    assert all(panel.index[c].day_of_week == 0 for c in p.checks)
    gone = panel.drop(panel.index[28])  # a Monday
    q = vs.vol_path(gone, 10, 0.4, 0.5)
    assert gone.index[q.checks].day_of_week.tolist() == [0] * len(q.checks)
    assert pd.Timestamp(panel.index[28]) not in gone.index[q.checks]
    # the share decided at Monday 21 is held for the 13 closes to the next Monday (row 34 once row 28 is gone)
    moved_gone = np.flatnonzero(np.diff(q.share)) + 1
    assert set(moved_gone.tolist()) <= set(q.checks.tolist()) and 21 in q.checks and 34 in q.checks
    assert q.share[21] > 0 and (q.share[21:34] == q.share[21]).all() and (q.q[21:34] == q.q[21]).all()
    daily = vs.vol_path(panel, 10, 0.4, 0.5, weekday=None)
    assert daily.checks.tolist() == list(range(10, 70)) and daily.activation == 10


def test_the_two_day_row_of_2018_01_13_enters_as_one_unscaled_return():
    """Close 2018-01-13 is dropped on the train grid: x at 2018-01-14 is the 2-day basket return, unscaled, and an
    L-row window across it spans L + 1 days."""
    panel = tr.random_walk_panel(5)
    idx = panel.index
    row = idx.get_loc(pd.Timestamp("2018-01-14", tz="UTC"))
    assert idx[row - 1] == pd.Timestamp("2018-01-12", tz="UTC")
    x = vs.basket_returns(panel)
    cb, ce = panel[("BTC", "close")].to_numpy(), panel[("ETH", "close")].to_numpy()
    assert x[row] == math.log1p(0.5 * (cb[row] / cb[row - 1] - 1.0) + 0.5 * (ce[row] / ce[row - 1] - 1.0))
    monday = idx.get_loc(pd.Timestamp("2018-01-15", tz="UTC"))
    for lookback in (2, 10, 50):
        assert vs.sigma_hat(x, lookback)[monday] == two_pass(x[monday - lookback + 1 : monday + 1])
        # the L returns of the window run from close c - L to close c: L + 1 days across the missing close
        assert idx[monday] - idx[monday - lookback] == pd.Timedelta(days=lookback + 1)
    assert monday in vs.vol_path(panel, 10, 0.8, 0.5).checks


# ------------------------------------------------------------------------------------------------ point in time


@given(case=vol_cases(), data=st.data())
@example(case=(random_panel(120, 11, (0.05, 0.06), (0.01, 0.01)), V(10, 0.5, 0.5), LIMITS), data=None)
def test_no_look_ahead_in_sigma_the_shares_the_targets_or_the_returns(case, data):
    """Tamper every field of both coins from the cut on (except the fill open of the cut): sigma, q, the shares, the
    targets, every result row, the orders and the fills before the cut are unchanged."""
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


def test_touching_the_present_moves_sigma_at_t_never_before():
    """Changing only close t (a check close) changes sigma and can change the share at t; nothing at t - 1."""
    panel = random_panel(80, 13, (0.04, 0.05), (0.0, 0.0))
    panel.index = mondays(80)
    t = 35
    base = vs.vol_path(panel, 10, 0.5, 0.5)
    frames = {a: panel[a].copy() for a in pf.ASSETS}
    frames["BTC"].iloc[t, frames["BTC"].columns.get_loc("close")] *= 1.3
    frames["BTC"].iloc[t, frames["BTC"].columns.get_loc("high")] *= 1.3
    touched = vs.vol_path(pf.make_panel(frames, snapshot_id="hand"), 10, 0.5, 0.5)
    assert touched.sigma[t] != base.sigma[t]
    assert np.array_equal(touched.share[:t], base.share[:t])


@given(
    panel=vol_panels(),
    lookback=st.integers(2, 30),
    tau=st.floats(0.05, 2.0),
    weekday=st.sampled_from([0, 4, None]),
)
def test_the_live_stream_equals_the_batch_on_every_close(panel, lookback, tau, weekday):
    """``VolStream`` fed one close at a time gives the batch share, q and sigma on every close, bit for bit."""
    path = vs.vol_path(panel, lookback, tau, 0.55, weekday=weekday)
    stream = vs.VolStream(lookback, tau, 0.55, weekday=weekday)
    for t, (ts, b, e) in enumerate(
        zip(panel.index, panel[("BTC", "close")], panel[("ETH", "close")], strict=True)
    ):
        assert stream.update(ts, b, e) == path.share[t]
        assert stream.q == path.q[t]
        if t in set(path.checks.tolist()):
            assert stream.sigma == path.sigma[t]


# ------------------------------------------------------------------------------------------------ the encoding


def test_the_encoding_is_z_from_activation_and_the_share_split_50_50():
    """vol_backtest is ``trend.run_states(in_force(z, share), states=z)``: targets (s q / 2, s q / 2); reasons read
    switch (activation), re-cut (a quarter step) and limit (a fix)."""
    panel = random_panel(200, 21, (0.06, 0.08), (0.01, 0.01))
    res = run(V(10, 0.4, 0.6), panel)
    path = vs.vol_path(panel, 10, 0.4, 0.6)
    assert np.array_equal(res.attrs["targets"], np.column_stack([path.share * 0.5, path.share * 0.5]))
    assert np.array_equal(res.attrs["share"], path.share) and np.array_equal(res.attrs["z"], path.z)
    direct = tr.run_states(panel, tr.in_force(path.z, path.share), limits=LIMITS, costs=COSTS, states=path.z)
    pd.testing.assert_frame_equal(res, direct)
    assert res.attrs["order_hash"] == direct.attrs["order_hash"]
    assert set(np.unique(path.q).tolist()) <= set(vs.QUARTERS) and len(set(path.q.tolist())) >= 3
    reasons = res.attrs["reasons"].tolist()
    assert reasons[0] == "switch" and reasons.count("switch") == 1
    assert set(reasons[1:]) <= {"re-cut", "limit"} and "re-cut" in reasons
    validate_result(res, panel)


def test_a_target_above_every_sigma_is_n0_s_always_in_path_from_activation():
    """With tau above every sigma, q = 1 from activation: the run equals the always-in path (s/2, s/2) ordered at the
    activation close, bit for bit (``trend.from_t0`` from an all-USDC book), its order hash included."""
    for seed, lookback, share in ((1, 10, 0.5), (2, 33, 0.3), (3, 120, 0.6)):
        panel = regime_panel(1000 + seed)
        res = run(V(lookback, 1e6, share), panel)
        act = res.attrs["activation"]
        assert (res.attrs["q"][act:] == 1.0).all()
        n = len(panel)
        ref = tr.from_t0(
            panel,
            np.zeros((n, 2)),
            panel.index[act],
            tr.share_targets(share),
            limits=LIMITS,
            costs=COSTS,
            base_states=np.zeros((n, 2), dtype=np.int8),
            target_state=(1, 1),
        )
        pd.testing.assert_frame_equal(res, ref)
        assert res.attrs["order_hash"] == ref.attrs["order_hash"]


@given(case=vol_cases(), costs=st.sampled_from([COSTS, COSTS.stressed()]))
def test_accounting_equals_an_independent_book_of_coin_units_and_cash(case, costs):
    """Every return, cost and weight equals ``test_trend.vector_book`` (coin units and USDC cash, each order's own
    target vector), to 1e-12."""
    panel, params, limits = case
    res = run(params, panel, limits, costs)
    out, _, _, _ = vector_book(panel, res, costs)
    for col in ("ret", "turnover", "cost", "w_BTC", "w_ETH"):
        np.testing.assert_allclose(res[col].to_numpy(), out[col], rtol=0, atol=1e-12, err_msg=col)


def test_decisions_never_depend_on_costs_or_the_book_size():
    """The orders (closes, reasons, targets) hash the same at 1x, 2x and every R4 book size (stop rule 13)."""
    panel = regime_panel(1003)
    hashes = {
        run(V(20, 0.5, 0.5), panel, costs=c).attrs["order_hash"]
        for c in (COSTS, COSTS.stressed(), *(Costs(capital_usd=b) for b in (100.0, 500.0, 50_000.0)))
    }
    assert len(hashes) == 1


# ------------------------------------------------------------------------------------------------ refusals


@pytest.mark.parametrize(
    ("params", "match"),
    [
        ([], "params must be a dict"),
        ({**V(), "buffer": 0.1}, r"unknown params \['buffer'\]"),
        ({"lookback": 10, "crypto_share": 0.5}, "missing required param 'target_vol'"),
        (V(lookback=1), "lookback must be >= 2"),
        (V(lookback=10.5), "lookback must be an integer"),
        (V(lookback=True), "lookback must be an integer"),
        (V(target_vol=0.0), r"target_vol must be in \(0.0, inf\)"),
        (V(target_vol=math.nan), r"target_vol must be in \(0.0, inf\)"),
        (V(share=0.0), r"crypto_share must be in \(0.0, 1.0\]"),
        (V(share=1.01), r"crypto_share must be in \(0.0, 1.0\]"),
    ],
)
def test_bad_params_raise_with_pinned_messages(params, match):
    with pytest.raises(ValueError, match=match):
        vs.parse_params(params)


def test_strict_params_accept_the_box_and_integral_floats():
    assert vs.parse_params({"lookback": 10.0, "target_vol": 0.3, "crypto_share": 0.6}) == V(10, 0.3, 0.6)
    assert vs.parse_params(V(2, 1e-9, 1.0)) == V(2, 1e-9, 1.0)


def test_bad_inputs_are_refused_with_pinned_messages():
    with pytest.raises(ValueError, match="lookback must be an integer >= 2"):
        vs.sigma_hat([math.nan, 0.1, 0.2], 1)
    with pytest.raises(ValueError, match="finite basket returns from row 1 on"):
        vs.sigma_hat([math.nan, math.nan, 0.2], 2)
    with pytest.raises(ValueError, match="finite basket returns from row 1 on"):
        vs.sigma_hat(np.zeros((2, 2)), 2)
    with pytest.raises(ValueError, match="row 5 is outside the 3 closes"):
        vs.sigma_hat([math.nan, 0.1, 0.2], 2, rows=[5])
    with pytest.raises(ValueError, match=r"m must be in \[0.0, 1.0\]"):
        vs.quarter(1.0000001)
    with pytest.raises(ValueError, match=r"m must be in \[0.0, 1.0\]"):
        vs.quarter(-0.1)
    with pytest.raises(ValueError, match=r"sigma must be in \[0.0, inf\)"):
        vs.scale(-0.1, 0.5)
    with pytest.raises(ValueError, match=r"target_vol must be in \(0.0, inf\)"):
        vs.scale(0.5, 0.0)
    with pytest.raises(ValueError, match="weekday must be an integer in 0..6"):
        vs.vol_path(random_panel(30, 1), 5, 0.5, 0.5, weekday=7)
    with pytest.raises(ValueError, match="lookback must be an integer >= 2"):
        vs.first_check(mondays(10), 1)
    stream = vs.VolStream(3, 0.5, 0.5)
    with pytest.raises(ValueError, match="tz-aware"):
        stream.update(pd.Timestamp("2021-01-01"), 1.0, 1.0)
    stream.update(pd.Timestamp("2021-01-02", tz="UTC"), 1.0, 1.0)
    with pytest.raises(ValueError, match="strictly increasing"):
        stream.update(pd.Timestamp("2021-01-02", tz="UTC"), 1.0, 1.0)
    with pytest.raises(ValueError, match=r"close must be in \(0.0, inf\)"):
        stream.update(pd.Timestamp("2021-01-03", tz="UTC"), 0.0, 1.0)
    with pytest.raises(ValueError, match="lookback must be an integer >= 2"):
        vs.VolStream(1, 0.5, 0.5)
    with pytest.raises(ValueError, match="stop rule 12"):
        run(V(10, 5.0, 0.79), random_panel(40, 2))  # (0.395, 0.395) leaves 21% cash, below 20% + h
    with pytest.raises(ValueError, match=r"exactly the keys \('study', 'run', 'bootstrap'\)"):
        vs.project_cpu_minutes(
            {"study": 1.0, "run": 1.0, "stop_run": 1.0}, {"study": 1, "run": 1, "bootstrap": 1}
        )
    with pytest.raises(ValueError, match="bootstrap must be an integer >= 0"):
        vs.project_cpu_minutes({k: 1.0 for k in vs.TIMING_KEYS}, {"study": 1, "run": 1, "bootstrap": 1.5})


# ------------------------------------------------------------------------------------------------ feasibility


def test_every_s_times_q_of_the_box_the_range_and_the_plateau_is_feasible():
    """Stop rule 12 before any bar: every s x q for s in the box ends, the allowed values and 0.24 / 0.72."""
    shares = vs.check_feasibility(LIMITS)
    want = sorted({s * q for s in (0.24, 0.30, 0.40, 0.50, 0.60, 0.72) for q in vs.QUARTERS})
    assert shares == want and max(shares) == 0.72 and min(shares) == 0.0
    assert vs.check_shares(0.6, LIMITS) == [0.0, 0.15, 0.3, 0.6 * 0.75, 0.6]
    with pytest.raises(ValueError, match="crypto share 0.72 breaks the limits as read"):
        vs.check_feasibility({"min_cash": 0.20, "max_coin": 0.35})  # 0.36 per coin > 0.35 - 0.02
    with pytest.raises(ValueError, match="stop rule 12"):
        vs.check_shares(0.79, LIMITS)


# ------------------------------------------------------------------------------------------------ R_0's schedule


FOLD_PARAMS = [V(10, 0.5, 0.30), V(30, 0.9, 0.60), V(60, 0.4, 0.45), V(120, 1.2, 0.50), V(15, 0.3, 0.35)]


class Span:
    def __init__(self):
        self.panel = regime_panel()
        self.windows = windows_of(self.panel.index)
        self.runs = fold_runs(self.panel, FOLD_PARAMS, self.windows)
        self.schedule = vs.stitched_schedule(
            self.panel.index,
            self.windows,
            [r.attrs["z"] for r in self.runs],
            [r.attrs["share"] for r in self.runs],
        )
        self.r0 = tr.run_span(self.panel, self.schedule, limits=LIMITS, costs=COSTS)
        self.kept = pd.concat([kept(r, w) for r, w in zip(self.runs, self.windows, strict=True)]).index


@pytest.fixture(scope="module")
def span() -> Span:
    return Span()


def test_r0_executes_s_s_share_schedule_with_a_per_row_head(span):
    """Each check's entry is the share in force of the fold holding it (its s times its q); the head is fold 0's
    per-row share; R_0 equals S on fold 0's kept rows bit for bit and holds S's book at t0; shift 0 is R_0."""
    sch, w0 = span.schedule, span.windows[0]
    assert len(sch.checks) == 260 and isinstance(sch.head_share, np.ndarray)
    first = int(sch.checks[0])
    assert np.array_equal(sch.head_share, span.runs[0].attrs["share"][:first])
    assert len(set(sch.head_share.tolist())) >= 3  # the share moved weekly before c_0
    for k, (c, i) in enumerate(zip(sch.checks.tolist(), sch.fold.tolist(), strict=True)):
        assert sch.share[k] == span.runs[i].attrs["share"][c] and tuple(sch.z[k]) == (1, 1)
        assert span.windows[i].t0 <= span.panel.index[c] <= span.windows[i].last
    v, z = tr.span_targets(sch, len(span.panel))
    assert np.array_equal(v[:first], span.runs[0].attrs["targets"][:first])
    last0 = span.panel.index.get_loc(w0.last)
    assert np.array_equal(v[: last0 + 1], span.runs[0].attrs["targets"])
    assert tr.same_book_at(span.r0, span.runs[0], w0.t0)
    k0 = kept(span.runs[0], w0)
    assert np.array_equal(span.r0["ret"].loc[k0.index].to_numpy(), k0.to_numpy())
    zero = tr.run_span(span.panel, sch, limits=LIMITS, costs=COSTS, u=0)
    pd.testing.assert_frame_equal(zero, span.r0)


def test_a_shift_moves_the_whole_share_path_each_entry_carrying_its_fold_s(span):
    sch = span.schedule
    for u in (1, 53, 259):
        sh = tr.shifted(sch, u)
        order = (np.arange(260) + u) % 260
        assert np.array_equal(sh.share, sch.share[order]) and np.array_equal(sh.fold, sch.fold[order])
        assert np.array_equal(sh.head_share, sch.head_share) and np.array_equal(sh.checks, sch.checks)
        res = tr.run_span(span.panel, sch, limits=LIMITS, costs=COSTS, u=u)
        assert tr.same_book_at(res, span.runs[0], span.windows[0].t0)
    # a shift never reads a price: the schedule is built once, from the fold runs
    assert sorted(tr.shifted(sch, 100).share.tolist()) == sorted(sch.share.tolist())


def test_n0_and_x_hold_s_s_book_at_t0(span):
    for i, (w, r, p) in enumerate(zip(span.windows, span.runs, FOLD_PARAMS, strict=True)):
        piece = tr.h0_slice(span.panel, w)
        n0 = tr.always_in_n0(
            piece,
            r.attrs["targets"],
            w.t0,
            p["crypto_share"],
            limits=LIMITS,
            costs=COSTS,
            base_states=r.attrs["z"],
        )
        assert tr.same_book_at(n0, r, w.t0), i
        x, info = tr.exposure_x(piece, r, w.t0, limits=LIMITS, costs=COSTS)
        assert tr.same_book_at(x, r, w.t0) and info["clipped"] is False


def test_h0_reproduces_walk_forward_optimize_bit_for_bit(span, tmp_path):
    fn = partial(vs.vol_backtest, limits=LIMITS, costs=COSTS)
    folds = walk_forward(len(span.panel), 365, 365, expanding=True)
    cfg = SearchConfig(n_trials=3, n_workers=1, seed=0)
    wf = walk_forward_optimize(
        "vol-t", fn, list(vs.SPECS), span.panel, folds, tmp_path, cfg, warmup=tr.WARMUP
    )
    parts = []
    for i, window in enumerate(span.windows):
        row = wf["folds"].iloc[i]
        params = {name: row[f"p_{name}"] for name in vs.PARAM_NAMES}
        res = sd.run_h120(fn, params, span.panel, window)
        assert res.index[0] == span.panel.index[0]
        parts.append(kept(res, window))
        assert row["oos_trades"] == sd.kept_fills(res, window.t0)
    pd.testing.assert_series_equal(pd.concat(parts), wf["oos_returns"], check_names=False)


def test_schedule_refusals(span):
    z = [r.attrs["z"] for r in span.runs]
    s = [r.attrs["share"] for r in span.runs]
    with pytest.raises(ValueError, match="one z path and one share path per fold"):
        vs.stitched_schedule(span.panel.index, span.windows, z, s[:4])
    with pytest.raises(ValueError, match="fold 2 shares must be"):
        vs.stitched_schedule(span.panel.index, span.windows, z, [*s[:2], s[2][:-1], *s[3:]])
    with pytest.raises(ValueError, match="fold 0 shares must be"):
        vs.stitched_schedule(span.panel.index, span.windows, z, [np.full(len(s[0]), 1.5), *s[1:]])
    with pytest.raises(ValueError, match="must be contiguous"):
        vs.stitched_schedule(span.panel.index, [span.windows[0], span.windows[2]], z[::2][:2], s[::2][:2])
    with pytest.raises(ValueError, match="at least one fold"):
        vs.stitched_schedule(span.panel.index, [], [], [])
    with pytest.raises(ValueError, match="fold 0 must hold the first check close"):
        idx = span.panel.index[:368]  # rows 365-367: Tuesday 2018-01-02 .. Thursday, no Monday
        vs.stitched_schedule(idx, [(idx[365], idx[367])], [z[0][:368]], [s[0][:368]])
    with pytest.raises(ValueError, match="one share path per fold"):
        vs.power_count(s[:4], span.windows, span.panel.index)


# ------------------------------------------------------------------------------------------------ P


def share_path(n: int, changes: dict[int, float]) -> np.ndarray:
    out = np.zeros(n)
    for t, v in sorted(changes.items()):
        out[t:] = v
    return out


def test_p_counts_share_changes_filled_in_kept_rows_never_the_first_buy():
    """Per fold: changes at t0 .. last - 1 count (a change at last fills outside), the run's first change (from 0) never
    does, even inside the kept rows; 19 fail and 20 hold; 3 folds fail and 4 hold; ups, downs and to-zero."""
    idx = tr.train_grid()
    windows = windows_of(idx)
    t0s = [idx.get_loc(w.t0) for w in windows]
    lasts = [idx.get_loc(w.last) for w in windows]

    def fold(i: int, k: int, *, last_change: bool = False) -> np.ndarray:
        """Fold i's path: a first buy at row 14, then k alternating changes from t0 (0.15, 0.3, ...)."""
        ch = {14: 0.3, **{t0s[i] + 7 * j: (0.15 if j % 2 == 0 else 0.3) for j in range(k)}}
        if last_change:
            ch[lasts[i]] = 0.0  # decided at the last close: fills after the fold, not counted
        return share_path(lasts[i] + 1, ch)

    got = vs.power_count([fold(i, 5, last_change=True) for i in range(5)], windows, idx)
    assert got["per_fold"] == [5] * 5 and got["total"] == 25 and got["holds"] is True
    assert (got["ups"], got["downs"], got["to_zero"]) == (10, 15, 0)
    # a change exactly at t0 counts and one at last - 1 counts
    edge = share_path(lasts[0] + 1, {14: 0.3, t0s[0]: 0.15, lasts[0] - 1: 0.0})
    assert vs.power_count([edge, *[fold(i, 0) for i in range(1, 5)]], windows, idx)["per_fold"][0] == 2
    # the first buy inside the kept rows is still not counted
    late = share_path(lasts[0] + 1, {t0s[0]: 0.3, t0s[0] + 7: 0.0})
    one = vs.power_count([late, *[fold(i, 0) for i in range(1, 5)]], windows, idx)
    assert one["per_fold"][0] == 1 and one["to_zero"] == 1
    # 20 changes in 4 folds hold; 19 fail
    assert vs.power_count([fold(0, 5), fold(1, 5), fold(2, 5), fold(3, 5), fold(4, 0)], windows, idx)["holds"]
    nineteen = vs.power_count([fold(0, 4), fold(1, 5), fold(2, 5), fold(3, 5), fold(4, 0)], windows, idx)
    assert nineteen["total"] == 19 and nineteen["holds"] is False
    # 20 or more in only 3 folds fail
    three = vs.power_count([fold(0, 10), fold(1, 5), fold(2, 5), fold(3, 0), fold(4, 0)], windows, idx)
    assert three["total"] == 20 and three["folds_with"] == 3 and three["holds"] is False


def test_p_reads_the_fold_runs_share_paths(span):
    got = vs.power_count([r.attrs["share"] for r in span.runs], span.windows, span.panel.index)
    manual = 0
    for r, w in zip(span.runs, span.windows, strict=True):
        s = r.attrs["share"]
        prev = np.concatenate([[0.0], s[:-1]])
        rows = np.flatnonzero(s != prev)[1:]
        p0, pl = r.index.get_loc(w.t0), r.index.get_loc(w.last)
        manual += sum(1 for t in rows if p0 <= t <= pl - 1)
        assert all(t in set(r.attrs["checks"].tolist()) for t in rows)
    assert got["total"] == manual > 0


# ------------------------------------------------------------------------------------------------ G5 plateau


def test_plateau_steps_by_hand():
    step = vs.plateau_step
    assert step(V(10, 0.6, 0.5), "lookback", 0.8) == (V(8, 0.6, 0.5), vs.OUTSIDE)
    assert step(V(10, 0.6, 0.5), "lookback", 1.2) == (V(12, 0.6, 0.5), vs.INSIDE)
    assert step(V(120, 0.6, 0.5), "lookback", 1.2) == (V(144, 0.6, 0.5), vs.OUTSIDE)
    assert step(V(120, 0.6, 0.5), "lookback", 0.8) == (V(96, 0.6, 0.5), vs.INSIDE)
    assert step(V(2, 0.6, 0.5), "lookback", 0.8)[0]["lookback"] == 1  # max(1, min(half_up(1.6), 1))
    assert step(V(13, 0.6, 0.5), "lookback", 1.2)[0]["lookback"] == 16  # half_up(15.6)
    assert step(V(25, 0.6, 0.5), "lookback", 0.8)[0]["lookback"] == 20
    assert step(V(10, 1.2, 0.5), "target_vol", 1.2) == (V(10, 1.2 * 1.2, 0.5), vs.OUTSIDE)
    assert step(V(10, 0.375, 0.5), "target_vol", 0.8) == (V(10, 0.375 * 0.8, 0.5), vs.INSIDE)  # lands on 0.30
    assert step(V(10, 0.6, 0.5), "crypto_share", 1.2) == (V(10, 0.6, 0.5 * 1.2), vs.INSIDE)
    assert step(V(10, 0.6, 0.6), "crypto_share", 1.2)[1] == vs.OUTSIDE
    steps = vs.plateau_steps([V(10, 0.6, 0.5), V(120, 0.3, 0.6)], LIMITS)
    assert [(s["param"], s["factor"]) for s in steps] == [(n, f) for n in vs.PARAM_NAMES for f in (0.8, 1.2)]
    assert steps[0]["marks"] == [vs.OUTSIDE, vs.INSIDE] and steps[0]["mark"] == vs.OUTSIDE
    with pytest.raises(ValueError, match="stop rule 12"):
        vs.plateau_steps([V(10, 0.6, 0.6)], {"min_cash": 0.20, "max_coin": 0.35})
    with pytest.raises(ValueError, match="at least one parameter set"):
        vs.plateau_steps([], LIMITS)
    with pytest.raises(ValueError, match="name must be one of"):
        step(V(), "buffer", 0.8)
    with pytest.raises(ValueError, match="factor must not be 1"):
        step(V(), "lookback", 1.0)


# ------------------------------------------------------------------------------------------------ verdict and headline


def test_the_verdict_reads_p_as_share_changes():
    assert vs.verdict(ALL_HOLD) == {"verdict": "EDGE", "label": "EDGE", "look_earned": True}
    low = vs.verdict({**ALL_HOLD, "E1": False, "P": False}, changes=12)
    assert low == {
        "verdict": "NO EDGE",
        "label": "NO EDGE (LOW POWER: 12 share changes)",
        "look_earned": False,
    }
    assert vs.verdict({**ALL_HOLD, "E1": False}, changes=30)["label"] == "NO EDGE"
    assert vs.verdict({**ALL_HOLD, "P": False}, changes=3)["label"] == "INCONCLUSIVE"
    assert vs.verdict(ALL_HOLD, stopped=True)["verdict"] == "INCONCLUSIVE"


def test_the_measurement_points_are_tp_10_s_table_with_vol_steady_s_parameters():
    points = vs.measurement_points()
    assert len(points) == len(set(points)) == 86
    g5 = [p for i, p in points if i == "G5"]
    assert g5[:6] == [f"(a) {n} x{f}" for n in vs.PARAM_NAMES for f in ("0.8", "1.2")]
    assert g5[6:12] == [f"(b) default {n} x{f}" for n in vs.PARAM_NAMES for f in ("0.8", "1.2")]
    assert "(a) target_vol x0.8" in g5 and not any("buffer" in p for p in g5)
    trend_points = tr.measurement_points()
    assert [i for i, _ in points] == [i for i, _ in trend_points]
    assert [p for i, p in points if i != "G5"] == [p for i, p in trend_points if i != "G5"]


def test_every_measurement_point_alone_moves_the_headline_and_is_named():
    edge = vs.verdict(ALL_HOLD)
    full = dict.fromkeys(vs.measurement_points(), True)
    assert vs.headline(edge, full) == {"headline": "CANDIDATE FOR AUDIT", "failing": []}
    for key in vs.measurement_points():
        for bad in (False, None):
            got = vs.headline(edge, {**full, key: bad})
            assert got == {"headline": "EDGE, NOT A CANDIDATE", "failing": [f"{key[0]} at {key[1]}"]}
    extra = {("G7", "theta_final(A)"): False, ("G5", "(a) buffer x0.8"): False, ("G1", "S_B"): False}
    assert vs.headline(edge, {**full, **extra})["headline"] == "CANDIDATE FOR AUDIT"
    low = vs.verdict({**ALL_HOLD, "E2": False, "P": False}, changes=7)
    assert vs.headline(low, full)["headline"] == "NO EDGE (LOW POWER: 7 share changes)"


def run_record(verdict, headline=None, e1=0.5, e2=0.5) -> dict:
    return {"verdict": verdict, "headline": headline or verdict, "e1_rank_p": e1, "e2_p": e2}


def test_stop_rule_18_with_no_stop_outcome():
    a = run_record("EDGE", "CANDIDATE FOR AUDIT", 0.01, 0.02)
    b = run_record("NO EDGE (LOW POWER: 9 share changes)", e1=0.3, e2=0.4)
    for trig in ("a", "b", "c"):
        got = vs.reported_verdict(a, b, trig)
        assert got == {
            "verdict": b["verdict"],
            "headline": b["headline"],
            "superseded": True,
            "runs": [{"e1_rank_p": 0.01, "e2_p": 0.02}, {"e1_rank_p": 0.3, "e2_p": 0.4}],
        }
    for first, second in ((a, b), (b, a)):
        got = vs.reported_verdict(first, second, "other, after the verdict")
        assert (
            got["verdict"] == b["verdict"] and got["headline"] == b["headline"] and got["superseded"] is False
        )
    # a tie (the same outcome, other labels) goes to the amendment run's string (TP #56: two equal string literals
    # are one interned object, so a tie case built from them cannot tell the runs apart)
    tie_old = run_record("NO EDGE (LOW POWER: 3 share changes)")
    tie_new = run_record("NO EDGE (LOW POWER: 9 share changes)")
    for key in ("verdict", "headline"):
        assert vs.reported_verdict(tie_old, tie_new, "other, after the verdict")[key] == tie_new[key]
        assert vs.reported_verdict(tie_new, tie_old, "other, after the verdict")[key] == tie_old[key]
    mixed = vs.reported_verdict(
        run_record("EDGE", "CANDIDATE FOR AUDIT"),
        run_record("EDGE", "EDGE, NOT A CANDIDATE"),
        "other, after the verdict",
    )
    assert mixed["headline"] == "EDGE, NOT A CANDIDATE"
    for bad in (None, "d", "other"):
        with pytest.raises(ValueError, match="must record its trigger"):
            vs.reported_verdict(a, b, bad)
    with pytest.raises(ValueError, match="unknown outcome"):
        vs.reported_verdict(run_record("MAYBE"), b, "other, after the verdict")


def test_the_projection_by_hand():
    timings = {"study": 6.0, "run": 0.015, "bootstrap": 1.5}
    counts = {"study": 12, "run": 3000, "bootstrap": 35}
    assert vs.project_cpu_minutes(timings, counts) == pytest.approx((72.0 + 45.0 + 52.5) / 60.0, rel=1e-15)
    assert vs.project_cpu_minutes(dict.fromkeys(vs.TIMING_KEYS, 0.0), counts) == 0.0


# ------------------------------------------------------------------------------------------------ calibration (slow)


@pytest.mark.slow
@pytest.mark.parametrize(("lookback", "target_vol", "share"), vs.CALIBRATION_POINTS)
def test_e1_s_false_positive_rate_on_driftful_random_walks(lookback, target_vol, share):
    """Section 9: on 200 iid Gaussian random-walk panels (seeds 0..199; constant volatility, so no clustering and no
    edge), the fixed rule runs in H0 as one span from row 0; its share schedule over the 260 Monday checks of the fold
    layout is R_0, scored on the 1820 kept rows against its 207 guarded shifts at 1x costs, with E1's rank-p rule. At
    most 18 of 200 panels may pass."""
    idx = tr.train_grid()
    windows = windows_of(idx)
    kept_rows = np.concatenate([np.flatnonzero((idx > w.t0) & (idx <= w.last)) for w in windows])
    assert len(kept_rows) == 1820
    ends = [idx.get_loc(w.last) + 1 for w in windows]
    offsets = tr.guarded_offsets(260)
    passes, moved = 0, 0
    for seed in range(200):
        panel = tr.random_walk_panel(seed)
        path = vs.vol_path(panel, lookback, target_vol, share)
        sch = vs.stitched_schedule(idx, windows, [path.z[:e] for e in ends], [path.share[:e] for e in ends])
        moved += len(set(sch.share.tolist())) > 1
        series = {
            u: tr.run_span(panel, sch, limits=LIMITS, costs=COSTS, u=int(u))["ret"].to_numpy()[kept_rows]
            for u in [0, *offsets.tolist()]
        }
        passes += tr.e1_test(series[0], series, 260)["holds"]
    assert moved >= 190, moved  # tau near the walks' volatility: the share moves on (almost) every panel
    assert passes <= 18, passes
