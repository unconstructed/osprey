"""lab/models/dips.py: dip events, features, labels, entry schedules, the event purge and the test-window guard.

TESTING.md section 7 patterns: tamper-the-future (events, day rows and targets decided before ``cut`` never move
when bars from ``cut`` on change), labels and features by hand on hand-built paths, an oracle for the CPCV paths,
the purge property, and the guard that refuses the test window. Expected numbers are computed here by hand.
"""

from __future__ import annotations

import dataclasses
import math

import numpy as np
import pandas as pd
import pytest
from hypothesis import given
from hypothesis import strategies as st

from lab.data.external import HoldoutWindowError
from lab.models import dips
from lab.models.features import FEATURES, compute_features
from lab.runner.reference import Costs, _dip_signal, scheduled

ZERO = Costs.zero()
CUT = pd.Timestamp("2024-07-01", tz="UTC")
# A small definition for hand-built paths: 10% below the 5-bar high, hold 5, entries on 3 days, labels 2 ahead.
SMALL = dips.DipSpec(drop=0.10, lookback=5, hold=5, entry_window=3, first_bar=0, bounce_horizon=2)


def random_bars(n: int, seed: int, vol: float = 0.04) -> pd.DataFrame:
    """Valid daily bars with gaps between close and next open, wide enough to trigger dips often."""
    rng = np.random.default_rng(seed)
    body = rng.normal(0.0, vol, n)
    gaps = rng.normal(0.0, vol / 4, n)
    gaps[0] = 0.0
    log_close = math.log(100.0) + np.cumsum(gaps + body)
    close = np.exp(log_close)
    open_ = np.exp(log_close - body)
    wick = rng.uniform(0.0, 0.03, (2, n))
    index = pd.date_range("2018-01-02", periods=n, freq="D", tz="UTC", name="ts")
    return pd.DataFrame(
        {
            "open": open_,
            "high": np.maximum(open_, close) * (1 + wick[0]),
            "low": np.minimum(open_, close) * (1 - wick[1]),
            "close": close,
            "volume": rng.uniform(100.0, 1000.0, n),
        },
        index=index,
    )


def tamper_from(bars: pd.DataFrame, cut: int, seed: int) -> pd.DataFrame:
    """Rewrite every bar from ``cut`` on (prices, ranges, volume), keeping valid bars and the length."""
    rng = np.random.default_rng(seed)
    out = bars.copy()
    k = len(bars) - cut
    c = out["close"].to_numpy(copy=True)
    o = out["open"].to_numpy(copy=True)
    c[cut:] *= np.exp(rng.normal(0.0, 0.3, k))
    o[cut:] *= np.exp(rng.normal(0.0, 0.3, k))
    out["close"], out["open"] = c, o
    out.iloc[cut:, out.columns.get_loc("high")] = np.maximum(o, c)[cut:] * (1 + rng.uniform(0, 0.1, k))
    out.iloc[cut:, out.columns.get_loc("low")] = np.minimum(o, c)[cut:] * (1 - rng.uniform(0, 0.1, k))
    out.iloc[cut:, out.columns.get_loc("volume")] = rng.uniform(1.0, 9000.0, k)
    return out


# ------------------------------------------------------------------------------------------------ the spec


def test_default_spec_is_d0():
    s = dips.DipSpec()
    assert (s.drop, s.lookback, s.hold, s.entry_window, s.stop, s.first_bar) == (0.15, 20, 30, 10, 0.15, 100)
    assert (s.ladder, s.bounce_tol, s.bounce_horizon, s.span) == ((0.05, 0.10), 0.05, 10, 31)


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"drop": 0.0}, "drop must be a fraction"),
        ({"drop": 1.0}, "drop must be a fraction"),
        ({"drop": True}, "drop must be a fraction"),
        ({"lookback": 0}, "lookback must be an int >= 1"),
        ({"lookback": True}, "lookback must be an int >= 1"),
        ({"hold": 0}, "hold must be an int >= 1"),
        ({"entry_window": 0}, "entry_window must be an int >= 1"),
        ({"stop": 1.5}, "stop must be a fraction"),
        ({"first_bar": -1}, "first_bar must be an int >= 0"),
        ({"bounce_tol": 0.0}, "bounce_tol must be a fraction"),
        ({"bounce_horizon": 0}, "bounce_horizon must be an int >= 1"),
        ({"entry_window": 31}, r"entry_window \(31\) must be <= hold \(30\)"),
        ({"bounce_horizon": 30}, "must stay inside the event span"),
        ({"ladder": ()}, "ladder must be a non-empty tuple"),
        ({"ladder": (0.0,)}, "ladder step must be a fraction"),
        ({"ladder": (0.10, 0.05)}, "strictly increasing"),
        ({"ladder": (0.05, 0.05)}, "strictly increasing"),
    ],
)
def test_bad_specs_raise(kwargs, match):
    with pytest.raises(ValueError, match=match):
        dips.DipSpec(**kwargs)


def test_stop_none_is_allowed():
    assert dips.DipSpec(stop=None).stop is None


# ----------------------------------------------------------------------------------------------- triggers


@pytest.mark.parametrize(("drop", "lookback"), [(0.05, 5), (0.15, 20), (0.2, 30), (0.1, 1)])
def test_trigger_is_the_dip_buy_signal(btc, drop, lookback):
    close = btc["close"].to_numpy()
    np.testing.assert_array_equal(dips.dip_trigger(close, drop, lookback), _dip_signal(close, drop, lookback))


def test_trigger_by_hand_and_at_the_exact_threshold():
    close = np.array([100.0, 100.0, 60.0, 50.0, 49.0, 100.0])  # 50 / 100 - 1 == -0.5 exactly: triggers
    np.testing.assert_array_equal(dips.dip_trigger(close, 0.5, 2), [False, False, False, True, False, False])
    np.testing.assert_array_equal(dips.dip_trigger(close, 0.15, 2), [False, False, True, True, True, False])
    assert dips.dip_trigger(np.array([5.0]), 0.1, 2).tolist() == [False]  # no full window


# ------------------------------------------------------------------------------------------------- events


def test_events_by_hand(make_bars):
    """Triggers at 6, 7, 8 (one event at 6, the others inside its 6-bar cool-off) and at 14 (a new event)."""
    closes = [100.0] * 6 + [88.0, 87.0, 86.0, 91.0, 95.0, 99.0, 100.0, 100.0, 85.0] + [92.0] * 7
    bars = make_bars(closes)
    ev = dips.find_events(bars, SMALL)
    assert list(ev.columns) == list(dips.EVENT_COLUMNS)
    assert ev["t0"].tolist() == [6, 14]
    assert ev["ref_bar"].tolist() == [5, 13]  # the LATEST bar holding the trailing high
    assert ev["end_bar"].tolist() == [12, 20]
    assert ev["p_ref"].tolist() == [100.0, 100.0]
    assert ev["ts0"].tolist() == [bars.index[6], bars.index[14]]
    assert ev["ts_ref"].tolist() == [bars.index[5], bars.index[13]]
    assert ev["ts_end"].tolist() == [bars.index[12], bars.index[20]]


def test_dropped_events_still_block_their_cool_off(make_bars):
    """first_bar=7 drops the event at 6, and its cool-off still swallows the triggers at 7 and 8 (PLAN.md
    section 2 reading, which reproduces the counting run's numbers). An event too close to the end is dropped."""
    closes = [100.0] * 6 + [88.0, 87.0, 86.0, 91.0, 95.0, 99.0, 100.0, 100.0, 85.0] + [92.0] * 5
    bars = make_bars(closes)
    late = dips.find_events(bars, dataclasses.replace(SMALL, first_bar=7))
    assert late.empty  # 6 dropped (too early), 14 dropped (needs bar 20, the last is 19)
    assert list(late.columns) == list(dips.EVENT_COLUMNS)
    assert dips.find_events(bars, SMALL)["t0"].tolist() == [6]


@given(seed=st.integers(0, 2**16), drop=st.sampled_from([0.05, 0.1, 0.15]), lookback=st.integers(2, 25),
       hold=st.integers(3, 40), first_bar=st.integers(0, 60))
def test_events_match_a_brute_force_scan(seed, drop, lookback, hold, first_bar):
    bars = random_bars(300, seed)
    spec = dips.DipSpec(drop=drop, lookback=lookback, hold=hold, entry_window=3, first_bar=first_bar,
                        bounce_horizon=2)
    close = bars["close"].to_numpy()
    expected, blocked_until = [], -1
    for t in range(lookback, len(close)):
        if close[t] / close[t - lookback : t + 1].max() - 1 <= -drop and t > blocked_until:
            blocked_until = t + hold
            if t >= first_bar and t + hold + 1 <= len(close) - 1:
                expected.append(t)
    assert dips.find_events(bars, spec)["t0"].tolist() == expected


@given(seed=st.integers(0, 2**16), cut=st.integers(30, 299), tamper=st.integers(0, 2**16))
def test_events_before_the_cut_never_see_the_future(seed, cut, tamper):
    """Tamper the future: the events triggered before ``cut`` (t0, P_ref, its bar) are identical."""
    bars = random_bars(300, seed)
    spec = dips.DipSpec(drop=0.1, lookback=10, hold=8, entry_window=3, first_bar=20, bounce_horizon=2)
    a = dips.find_events(bars, spec)
    b = dips.find_events(tamper_from(bars, cut, tamper), spec)
    cols = ["t0", "ref_bar", "p_ref"]
    pd.testing.assert_frame_equal(a.loc[a["t0"] < cut, cols], b.loc[b["t0"] < cut, cols])


def test_window_events_needs_the_whole_span(make_bars):
    bars = make_bars([100.0] * 40, start="2022-12-20")
    ev = pd.DataFrame({"ts0": bars.index[[5, 8, 13]], "ts_end": bars.index[[11, 14, 20]]})
    train = (pd.Timestamp("2017-01-01", tz="UTC"), pd.Timestamp("2022-12-31", tz="UTC"))  # last close 2023-01-01
    validate = (pd.Timestamp("2023-01-01", tz="UTC"), pd.Timestamp("2024-06-30", tz="UTC"))
    assert bars.index[12] == pd.Timestamp("2023-01-01", tz="UTC")
    assert dips.window_events(ev, train).tolist() == [True, False, False]
    assert dips.window_events(ev, validate).tolist() == [False, False, True]


def test_trigger_months_use_the_trigger_day():
    ev = pd.DataFrame({"ts0": pd.DatetimeIndex(["2020-02-01", "2020-02-02", "2021-01-01"], tz="UTC")})
    assert dips.trigger_months(ev).tolist() == ["2020-01", "2020-02", "2020-12"]


# ----------------------------------------------------------------------------------------------- features


def test_range_ratio_up_day_and_narrow_range_by_hand(make_bars):
    bars = make_bars([100.0, 102.0, 101.0, 105.0, 104.0, 103.0, 106.0, 106.5])
    rng = np.log(bars["high"].to_numpy() / bars["low"].to_numpy())
    ratio = dips.range_ratio(bars)
    assert np.isnan(ratio[:5]).all()
    for t in (5, 6, 7):
        assert ratio[t] == pytest.approx(rng[t] / rng[t - 5 : t].mean(), rel=1e-12)
    assert dips.narrow_range(bars).tolist() == [False] * 5 + [bool(r < 1.0) for r in ratio[5:]]
    high = bars["high"].to_numpy()
    close = bars["close"].to_numpy()
    assert dips.up_day(bars).tolist() == [False] + [bool(close[t] > high[t - 1]) for t in range(1, 8)]


def test_range_ratio_needs_six_bars(make_bars):
    bars = make_bars([100.0, 101.0, 102.0, 101.0, 100.0])
    assert np.isnan(dips.range_ratio(bars)).all() and not dips.narrow_range(bars).any()


def test_range_ratio_on_flat_bars(make_bars):
    """Five bars with high == low: a flat bar after them has ratio 1.0, a bar with any range +inf."""
    bars = make_bars([100.0] * 7 + [101.0], spread=0.0)
    ratio = dips.range_ratio(bars)
    assert ratio[5] == 1.0 and ratio[6] == 1.0 and ratio[7] == math.inf
    assert dips.narrow_range(bars)[5:].tolist() == [False, False, False]


def test_event_features_and_day_rows_by_hand(btc):
    spec = dips.DipSpec()
    feats = compute_features(btc)
    ev = dips.find_events(btc, spec)
    assert len(ev) >= 5
    q = dips.event_features(btc, ev, spec, feats)
    e = 2
    t0, ref, p_ref = int(ev.at[e, "t0"]), int(ev.at[e, "ref_bar"]), float(ev.at[e, "p_ref"])
    assert q.at[e, "q_speed"] == (t0 - ref) / 20
    assert q.at[e, "q_ma_dist_100"] == feats["ma_dist_100"].iloc[t0]
    assert q.at[e, "q_vol_ratio_10_60"] == feats["vol_ratio_10_60"].iloc[t0]
    assert q.at[e, "ewma_vol_20"] == feats["ewma_vol_20"].iloc[t0]
    rows = dips.day_rows(btc, ev, spec, feats)
    assert list(rows.columns) == list(dips.DAY_COLUMNS)
    assert len(rows) == 10 * len(ev) and not rows.isna().any().any()
    block = rows[rows["event"] == e].reset_index(drop=True)
    assert block["offset"].tolist() == list(range(10)) and block["d"].tolist() == list(range(t0, t0 + 10))
    close, low = btc["close"].to_numpy(), btc["low"].to_numpy()
    high = btc["high"].to_numpy()
    for o in (0, 4, 9):
        d = t0 + o
        r = block.iloc[o]
        assert r["b_days"] == o
        ewma = feats["ewma_vol_20"].iloc[d]
        assert r["b_depth"] == pytest.approx(math.log(close[d] / p_ref) / (ewma * math.sqrt(20)), rel=1e-12)
        assert r["b_bounce"] == pytest.approx(math.log(close[d] / low[t0 : d + 1].min()), rel=1e-12, abs=1e-15)
        hl = np.log(high / low)
        assert r["b_range_ratio"] == pytest.approx(hl[d] / hl[d - 5 : d].mean(), rel=1e-12)
        assert r["b_up_day"] == float(close[d] > high[d - 1])
        assert r["b_volume_z"] == feats["volume_z_20"].iloc[d]
        np.testing.assert_array_equal(r[list(FEATURES)].to_numpy(dtype=float), feats.iloc[d].to_numpy())
        for name in dips.Q_FEATURES:
            assert r[name] == q.at[e, name]
    pd.testing.assert_frame_equal(rows, dips.day_rows(btc, ev, spec))  # features computed when not given


def test_day_rows_of_no_events_is_an_empty_frame(btc):
    ev = dips.find_events(btc.iloc[:150], dips.DipSpec(drop=0.9))
    rows = dips.day_rows(btc.iloc[:150], ev, dips.DipSpec(drop=0.9))
    assert rows.empty and list(rows.columns) == list(dips.DAY_COLUMNS)


def test_features_must_belong_to_the_bars(btc):
    spec = dips.DipSpec()
    ev = dips.find_events(btc, spec)
    feats = compute_features(btc)
    with pytest.raises(ValueError, match="must be compute_features"):
        dips.event_features(btc, ev, spec, feats.iloc[1:])
    with pytest.raises(ValueError, match="must be compute_features"):
        dips.day_rows(btc, ev, spec, feats[list(reversed(FEATURES))])
    broken = feats.copy()
    broken["ewma_vol_20"] = 0.0
    with pytest.raises(ValueError, match="ewma_vol_20 is not positive"):
        dips.day_rows(btc, ev, spec, broken)


@given(seed=st.integers(0, 2**16), cut=st.integers(120, 399), tamper=st.integers(0, 2**16))
def test_day_rows_before_the_cut_never_see_the_future(seed, cut, tamper):
    """Tamper the future: every day row with d < cut (features at d, the event's trigger features) is identical."""
    bars = random_bars(400, seed)
    spec = dips.DipSpec(drop=0.1, lookback=10, hold=12, entry_window=6, first_bar=100, bounce_horizon=4)
    tampered = tamper_from(bars, cut, tamper)
    a = dips.day_rows(bars, dips.find_events(bars, spec), spec)
    b = dips.day_rows(tampered, dips.find_events(tampered, spec), spec)
    pd.testing.assert_frame_equal(a[a["d"] < cut].reset_index(drop=True), b[b["d"] < cut].reset_index(drop=True))


# ------------------------------------------------------------------------------------------------- labels


def test_bottom_label_by_hand(make_bars):
    # make_bars: low = min(open, close) * (1 - 0.005)
    bars = make_bars([100.0, 100.0, 96.0, 99.0, 90.0, 95.0, 97.0, 98.0])
    spec = dips.DipSpec(hold=5, entry_window=3, bounce_horizon=2, first_bar=0)
    low, close = bars["low"].to_numpy(), bars["close"].to_numpy()
    y = dips.bottom_label(bars, np.arange(8), spec)
    for d in range(6):
        assert y[d] == float(low[d + 1 : d + 3].min() >= close[d] * 0.95)
    assert y[:6].tolist() == [1.0, 1.0, 0.0, 0.0, 1.0, 1.0]
    assert np.isnan(y[6:]).all()  # no full 2-bar future


def test_bottom_label_boundary_is_inclusive(make_bars):
    bars = make_bars([100.0, 100.0, 100.0, 100.0], spread=0.0)
    bars.iloc[2, bars.columns.get_loc("low")] = 95.0  # exactly 5% below close[0]: still a bottom
    spec = dips.DipSpec(hold=5, entry_window=3, bounce_horizon=2, first_bar=0)
    assert dips.bottom_label(bars, [0], spec).tolist() == [1.0]
    bars.iloc[2, bars.columns.get_loc("low")] = 94.99
    assert dips.bottom_label(bars, [0], spec).tolist() == [0.0]
    assert np.isnan(dips.bottom_label(bars.iloc[:2], [0], spec)).all()  # fewer bars than the window


@given(seed=st.integers(0, 2**16), d=st.integers(0, 80))
def test_bottom_label_reads_exactly_its_window(seed, d):
    """Rewriting bars after d + h, or before d, never changes y_B(d); it reads close[d] and low[d+1..d+h]."""
    bars = random_bars(100, seed)
    spec = dips.DipSpec(hold=12, entry_window=3, bounce_horizon=8, first_bar=0)
    base = dips.bottom_label(bars, [d], spec)
    after = tamper_from(bars, d + 9, seed + 1)
    assert dips.bottom_label(after, [d], spec).tolist() == base.tolist()
    before = bars.copy()
    before.iloc[:d, :] = before.iloc[:d, :].to_numpy() * 1.5
    assert dips.bottom_label(before, [d], spec).tolist() == base.tolist()


def test_positioning_features_by_hand(make_bars):
    bars = make_bars([100.0] * 10)
    ev = pd.DataFrame({"t0": [5, 8], "ref_bar": [2, 6]})
    pos = pd.DataFrame(
        {"funding_mean_7d": [0.001, np.nan, 0.002], "oi_last": [200.0, 250.0, np.nan]},
        index=bars.index[[2, 5, 6]],
    )
    funding, chg = dips.positioning_features(bars, ev, pos)
    assert np.isnan(funding[[0, 1, 3, 4, 5, 7, 8, 9]]).all()
    assert funding[2] == 0.001 and funding[6] == 0.002
    assert chg[0] == pytest.approx(math.log(250.0 / 200.0), rel=1e-15)
    assert np.isnan(chg[1])  # OI unknown at the ref bar's close and at t0


# -------------------------------------------------------------------------------------------- entry plans


def test_fires_has_a_round_off_tolerance():
    theta = 0.3
    assert dips.fires([0.3, 0.3 - 1e-10, 0.3 - 1e-8, 0.31], theta).tolist() == [True, True, False, True]


def test_first_signal_plan():
    assert dips.first_signal_plan([False, True, True]) == (((1, 1.0),), False)
    assert dips.first_signal_plan([False, False, False]) == (((2, 1.0),), True)
    with pytest.raises(ValueError, match="one value per entry day"):
        dips.first_signal_plan([])


@pytest.mark.parametrize(
    ("closes", "plan"),
    [
        ([85.0, 82.0, 79.0, 74.0, 90.0, 90.0], ((0, 1 / 3), (2, 2 / 3), (3, 1.0))),
        ([85.0, 74.0, 90.0, 90.0, 90.0, 90.0], ((0, 1 / 3), (1, 1.0))),  # two levels on one day
        ([80.0, 85.0, 85.0, 85.0, 85.0, 85.0], ((0, 2 / 3),)),  # the trigger close already reaches level 1
        ([85.0, 86.0, 87.0, 88.0, 70.0, 70.0], ((0, 1 / 3),)),  # a close after the window doesn't count
    ],
)
def test_ladder_plan_by_hand(closes, plan):
    """P_ref 100, X 15%: levels 80 and 75; entry window 4 closes."""
    spec = dips.DipSpec(entry_window=4)
    got = dips.ladder_plan(np.array(closes), 0, 100.0, spec)
    assert [o for o, _ in got] == [o for o, _ in plan]
    assert [w for _, w in got] == pytest.approx([w for _, w in plan], rel=1e-15)
    assert all(type(w) is float for _, w in got)


def test_targets_t1_hold_and_exit(make_bars):
    bars = make_bars([100.0] * 12)
    t, info = dips.event_targets(bars, 2, ((0, 1.0),), SMALL)
    assert t.tolist() == [1.0, 1.0, 1.0, 1.0, 1.0, 0.0]  # decided at closes 2..7; exit fills at the open of 8
    assert info == {"entered": True, "fill_bars": [3], "avg_fill": 100.0, "stop_bar": None, "exit_bar": 8,
                    "final_weight": 1.0}


def test_targets_stop_below_the_average_fill_and_no_re_entry(make_bars):
    """Ladder 1/3 at t0 (fills at 100), 2/3 at t0+1 (fills at 95): average 97.5, stop level 82.875. A close of 80
    at t0+3 stops; the plan's last tranche (t0+4) is cancelled. A close of 83.5 there doesn't stop."""
    spec = dips.DipSpec(drop=0.10, lookback=5, hold=7, entry_window=5, first_bar=0, bounce_horizon=2)
    plan = ((0, 1 / 3), (1, 2 / 3), (4, 1.0))
    bars = make_bars([100.0, 100.0, 100.0, 95.0, 90.0, 80.0, 99.0, 99.0, 99.0, 99.0, 99.0])
    t, info = dips.event_targets(bars, 2, plan, spec)
    assert t.tolist() == pytest.approx([1 / 3, 2 / 3, 2 / 3, 0.0, 0.0, 0.0, 0.0, 0.0], rel=1e-15)
    assert info["avg_fill"] == pytest.approx(97.5, rel=1e-14)
    assert info["fill_bars"] == [3, 4] and info["stop_bar"] == 5 and info["exit_bar"] == 6
    assert info["final_weight"] == pytest.approx(2 / 3, rel=1e-15)
    above = make_bars([100.0, 100.0, 100.0, 95.0, 90.0, 83.5, 99.0, 99.0, 99.0, 99.0, 99.0])
    t2, info2 = dips.event_targets(above, 2, plan, spec)
    assert info2["stop_bar"] is None and info2["fill_bars"] == [3, 4, 7] and t2.tolist()[4:] == [1.0, 1.0, 1.0, 0.0]


def test_a_close_exactly_at_the_stop_level_stops(make_bars):
    level = 100.0 * (1.0 - 0.15)
    hit = make_bars([100.0, 100.0, 100.0, level, 100.0, 100.0, 100.0, 100.0, 100.0])
    assert dips.event_targets(hit, 2, ((0, 1.0),), dataclasses.replace(SMALL, stop=0.15))[1]["stop_bar"] == 3
    miss = make_bars([100.0, 100.0, 100.0, level + 1e-9, 100.0, 100.0, 100.0, 100.0, 100.0])
    assert dips.event_targets(miss, 2, ((0, 1.0),), dataclasses.replace(SMALL, stop=0.15))[1]["stop_bar"] is None


def test_targets_stop_waits_for_a_fill_and_can_be_off(make_bars):
    """A close far below everything before the entry has filled is no stop; stop=None never stops."""
    closes = [100.0, 100.0, 100.0, 50.0, 100.0, 100.0, 40.0, 40.0, 40.0, 40.0, 40.0]
    bars = make_bars(closes)
    spec = dips.DipSpec(drop=0.10, lookback=5, hold=7, entry_window=3, first_bar=0, bounce_horizon=2)
    t, info = dips.event_targets(bars, 2, ((2, 1.0),), spec)  # decided at close 4, filled at 100 on bar 5
    assert info["fill_bars"] == [5] and info["stop_bar"] == 6
    assert t.tolist() == [0.0, 0.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0]
    off = dataclasses.replace(spec, stop=None)
    t_off, info_off = dips.event_targets(bars, 2, ((2, 1.0),), off)
    assert info_off["stop_bar"] is None and t_off.tolist() == [0.0, 0.0] + [1.0] * 5 + [0.0]


def test_targets_of_a_skipped_event(make_bars):
    t, info = dips.event_targets(make_bars([100.0] * 12), 2, (), SMALL)
    assert (t == 0).all() and not info["entered"] and math.isnan(info["avg_fill"])
    assert info["exit_bar"] is None and info["fill_bars"] == []


@pytest.mark.parametrize(
    "plan",
    [((3, 1.0),), ((-1, 1.0),), ((0, 0.5), (0, 1.0)), ((0, 0.5), (1, 0.4)), ((0, 1.5),), ((0, 0.0),),
     ((True, 1.0),), ((0.0, 1.0),)],
)
def test_bad_plans_raise(make_bars, plan):
    with pytest.raises(ValueError, match="bad entry plan"):
        dips.event_targets(make_bars([100.0] * 12), 2, plan, SMALL)


def test_event_must_fit_in_the_bars(make_bars):
    with pytest.raises(ValueError, match="needs bars up to 11"):
        dips.event_targets(make_bars([100.0] * 11), 5, ((0, 1.0),), SMALL)


@given(seed=st.integers(0, 2**16), cut_after=st.integers(1, 30), tamper=st.integers(0, 2**16),
       plan_id=st.integers(0, 3))
def test_targets_before_the_cut_never_see_the_future(seed, cut_after, tamper, plan_id):
    """Tamper the future: the targets decided at closes before ``cut`` are identical, even though the open of
    ``cut`` (a fill price) changes too. Plans: T1, a ladder, a late entry, a skip."""
    bars = random_bars(80, seed, vol=0.06)
    spec = dips.DipSpec(drop=0.1, lookback=5, hold=30, entry_window=10, first_bar=0, stop=0.08)
    plan = [((0, 1.0),), ((0, 1 / 3), (3, 2 / 3), (7, 1.0)), ((9, 1.0),), ()][plan_id]
    t0 = 10
    cut = t0 + cut_after
    a, _ = dips.event_targets(bars, t0, plan, spec)
    b, _ = dips.event_targets(tamper_from(bars, cut, tamper), t0, plan, spec)
    np.testing.assert_array_equal(a[: cut - t0], b[: cut - t0])


def test_schedule_column(make_bars):
    ev = pd.DataFrame({"t0": [1, 5]}, index=[10, 11])
    col = dips.schedule_column(10, ev, {10: np.array([1.0, 1.0, 0.0]), 11: np.array([0.5, 0.0])})
    assert col.tolist() == [0.0, 1.0, 1.0, 0.0, 0.0, 0.5, 0.0, 0.0, 0.0, 0.0]
    assert dips.schedule_column(10, ev, {11: np.array([0.5, 0.0])}).tolist()[1] == 0.0  # 10 skipped
    with pytest.raises(ValueError, match="overlaps"):
        dips.schedule_column(10, pd.DataFrame({"t0": [1, 2]}), {0: np.ones(3), 1: np.ones(3)})
    with pytest.raises(ValueError, match="runs past"):
        dips.schedule_column(6, ev, {11: np.ones(3)})


# --------------------------------------------------------------------------------------------- one event


def test_run_event_t1_by_hand(make_bars):
    """Zero cost, no gaps: T1 buys at the open of t0+1 (close of t0) and sells at the open of t0+H+1."""
    closes = [100.0, 100.0, 90.0, 80.0, 85.0, 95.0, 99.0, 104.0, 104.0, 104.0]
    bars = make_bars(closes)
    out = dips.run_event(bars, 2, ((0, 1.0),), SMALL, ZERO)
    assert out["r"] == pytest.approx(104.0 / 90.0 - 1.0, rel=1e-12)  # opens of bars 3 and 8 = closes 2 and 7
    assert out["n_fills"] == 2 and out["exit_bar"] == 8
    low = bars["low"].to_numpy()
    assert out["distance"] == pytest.approx(90.0 / low[2:8].min() - 1.0, rel=1e-12)
    assert out["mae"] == pytest.approx(min(low[3:8].min(), 99.0) / 90.0 - 1.0, rel=1e-12)


def test_run_event_equals_the_engine_on_the_event_bars(btc):
    spec = dips.DipSpec(drop=0.08, lookback=10)
    ev = dips.find_events(btc, spec)
    costs = Costs.from_yaml()
    for e in range(min(4, len(ev))):
        t0 = int(ev.at[e, "t0"])
        plan = dips.ladder_plan(btc["close"].to_numpy(), t0, float(ev.at[e, "p_ref"]), spec)
        out = dips.run_event(btc, t0, plan, spec, costs)
        targets, _ = dips.event_targets(btc, t0, plan, spec)
        piece = btc.iloc[t0 : t0 + spec.span + 1]
        col = np.append(targets, 0.0)
        res = scheduled({"col": "x"}, piece.assign(x=col), costs)
        assert out["r"] == np.prod(1.0 + res["ret"].to_numpy()) - 1.0
        if out["entered"]:
            assert out["r"] == pytest.approx(res.attrs["trade_returns"][0], rel=1e-12)


def test_run_event_skipped_is_zero(btc):
    spec = dips.DipSpec()
    t0 = int(dips.find_events(btc, spec).at[0, "t0"])
    out = dips.run_event(btc, t0, (), spec, Costs())
    assert out["r"] == 0.0 and out["n_fills"] == 0 and math.isnan(out["distance"]) and math.isnan(out["mae"])


# ------------------------------------------------------------------------------------------------- models


def _xy(n=200, seed=0):
    rng = np.random.default_rng(seed)
    X = pd.DataFrame({"a": rng.normal(5, 3, n), "b": rng.normal(-2, 0.1, n), "c": np.ones(n)})
    y = (X["a"] + rng.normal(0, 2, n) > 5).astype(float)
    return X, y


def test_logistic_standardises_with_training_rows_only():
    from sklearn.linear_model import LogisticRegression

    X, y = _xy()
    model = dips.DipClassifier("logistic").fit(X.iloc[:150], y.iloc[:150])
    x = X.iloc[:150].to_numpy()
    mean, sd = x.mean(axis=0), x.std(axis=0)
    sd[sd == 0] = 1.0  # the constant column is centred only
    ref = LogisticRegression(C=1.0, max_iter=1000).fit((x - mean) / sd, y.iloc[:150])
    np.testing.assert_allclose(model.predict(X.iloc[150:]), ref.predict_proba((X.iloc[150:].to_numpy() - mean) / sd)[:, 1],
                               rtol=0, atol=1e-15)


def test_lightgbm_is_the_lab_model():
    from lab.models.train import make_model

    X, y = _xy(600)
    got = dips.DipClassifier("lightgbm", seed=3).fit(X.iloc[:500], y.iloc[:500]).predict(X.iloc[500:])
    ref = make_model("classification", 3).fit(X.iloc[:500], y.iloc[:500]).predict_proba(X.iloc[500:])[:, 1]
    np.testing.assert_array_equal(got, ref)


def test_one_class_training_predicts_that_class():
    X, _ = _xy(20)
    assert dips.DipClassifier("logistic").fit(X, np.ones(20)).predict(X).tolist() == [1.0] * 20
    assert dips.DipClassifier("lightgbm").fit(X, np.zeros(20)).predict(X).tolist() == [0.0] * 20


def test_classifier_rejects_bad_input():
    X, y = _xy(20)
    with pytest.raises(ValueError, match="kind must be"):
        dips.DipClassifier("forest")
    with pytest.raises(ValueError, match="finite features and 0/1 labels"):
        dips.DipClassifier("logistic").fit(X, y.replace(1.0, 2.0))
    with pytest.raises(ValueError, match="finite features and 0/1 labels"):
        dips.DipClassifier("logistic").fit(X.assign(a=np.nan), y)
    with pytest.raises(ValueError, match="finite features and 0/1 labels"):
        dips.DipClassifier("logistic").fit(X, y.iloc[:5])
    with pytest.raises(ValueError, match="finite features and 0/1 labels"):
        dips.DipClassifier("logistic").fit(X.iloc[:0], y.iloc[:0])
    model = dips.DipClassifier("logistic").fit(X, y)
    with pytest.raises(ValueError, match="predict needs the columns"):
        model.predict(X[["b", "a", "c"]])


# ---------------------------------------------------------------------------------------- event-level CPCV


@st.composite
def event_spans(draw):
    n = draw(st.integers(12, 60))
    gaps = draw(st.lists(st.integers(1, 40), min_size=n, max_size=n))
    lengths = draw(st.lists(st.integers(5, 45), min_size=n, max_size=n))
    start = pd.Timestamp("2018-01-01", tz="UTC") + pd.to_timedelta(np.cumsum(gaps), unit="D")
    return pd.DatetimeIndex(start), pd.DatetimeIndex(start + pd.to_timedelta(lengths, unit="D"))


@given(spans=event_spans(), embargo_days=st.integers(0, 40))
def test_no_training_event_reaches_a_test_span_plus_the_embargo(spans, embargo_days):
    """The purge property (PLAN.md section 9), and minimality: every event left out of training does overlap a
    test group's span or trigger inside its embargo."""
    ts0, ts_end = spans
    embargo = pd.Timedelta(days=embargo_days)
    groups = np.array_split(np.arange(len(ts0)), 6)
    try:
        result = dips.event_cpcv(ts0, ts_end, 6, 2, embargo)
    except ValueError as exc:
        assert "leave no training event" in str(exc)
        return
    assert len(result) == 15
    for train, test, test_groups in result:
        spans_ = [(ts0[groups[g]].min(), ts_end[groups[g]].max()) for g in test_groups]
        assert np.array_equal(test, np.concatenate([groups[g] for g in test_groups]))
        for i in train:
            for lo, hi in spans_:
                assert ts_end[i] < lo or ts0[i] > hi + embargo
        dropped = np.setdiff1d(np.setdiff1d(np.arange(len(ts0)), test), train)
        for i in dropped:
            assert any(ts0[i] <= hi + embargo and ts_end[i] >= lo for lo, hi in spans_)


def test_event_cpcv_by_hand():
    """12 events on days 0, 20, .., 220, each 10 days long: 6 groups of 2. Split 0 tests groups 0 and 1 (events
    0-3; group 1 spans days 40..70). Embargo 15 days: event 4 (day 80) is embargoed, 5.. train. With 25-day
    spans and no embargo, event 4 (days 80..105) overlaps group 1 (days 40..85) and is purged instead."""
    start = pd.Timestamp("2019-01-01", tz="UTC") + pd.to_timedelta(np.arange(12) * 20, unit="D")
    end = start + pd.Timedelta(days=10)
    result = dips.event_cpcv(start, end, 6, 2, pd.Timedelta(days=15))
    train, test, groups = result[0]
    assert groups == (0, 1) and test.tolist() == [0, 1, 2, 3]
    # group 1 ends at event 3's end (day 70); event 4 starts at day 80 <= 70 + 15: embargoed
    assert train.tolist() == [5, 6, 7, 8, 9, 10, 11]
    overlap = dips.event_cpcv(start, start + pd.Timedelta(days=25), 6, 2, pd.Timedelta(0))[0][0]
    assert overlap.tolist() == [5, 6, 7, 8, 9, 10, 11]  # event 4 overlaps event 3's span (days 60..85)


def test_event_cpcv_rejects_bad_input():
    start = pd.DatetimeIndex(pd.date_range("2020-01-01", periods=12, freq="10D", tz="UTC"))
    with pytest.raises(ValueError, match="sorted by ts0"):
        dips.event_cpcv(start[::-1], start[::-1], 6, 2)
    with pytest.raises(ValueError, match="sorted by ts0"):
        dips.event_cpcv(start, start[:5], 6, 2)
    with pytest.raises(ValueError, match="ends before it starts"):
        dips.event_cpcv(start, start - pd.Timedelta(days=1), 6, 2)
    with pytest.raises(ValueError, match="embargo must be >= 0"):
        dips.event_cpcv(start, start, 6, 2, pd.Timedelta(days=-1))
    with pytest.raises(ValueError, match="leave no training event"):
        dips.event_cpcv(start, start + pd.Timedelta(days=500), 6, 2)


def test_event_paths_oracle():
    """Feed every split its test events' own indices: each path is every event's index exactly once."""
    start = pd.DatetimeIndex(pd.date_range("2020-01-01", periods=30, freq="40D", tz="UTC"))
    splits_ = dips.event_cpcv(start, start + pd.Timedelta(days=31), 6, 2)
    paths = dips.event_paths(30, 6, 2, [test.astype(float) for _, test, _ in splits_])
    assert paths.shape == (5, 30)
    np.testing.assert_array_equal(paths, np.tile(np.arange(30.0), (5, 1)))


# ---------------------------------------------------------------------------------------------- inference


def test_month_bootstrap_known_answers():
    months = np.array(["a", "a", "b", "c"])
    const = dips.month_bootstrap([0.02, 0.02, 0.02, 0.02], months, n_draws=200, seed=1)
    assert const["mean"] == 0.02 and const["p"] == pytest.approx(1 / 201)  # every draw is exactly 0.02
    assert const["ci_low"] == pytest.approx(0.02) and const["ci_high"] == pytest.approx(0.02)
    assert (const["n_events"], const["n_months"]) == (4, 3)
    zero = dips.month_bootstrap([0.0, 0.0, 0.0], ["a", "b", "c"], n_draws=50)
    assert zero["p"] == 1.0


@given(seed=st.integers(0, 2**16), draws=st.integers(1, 300))
def test_month_bootstrap_equals_a_hand_resampler(seed, draws):
    """Same draws (``default_rng(seed).integers``) resampled by hand: whole months, means over their events."""
    rng = np.random.default_rng(seed + 1)
    n = int(rng.integers(3, 30))
    delta = rng.normal(0.01, 0.05, n)
    months = rng.choice(["2018-01", "2018-02", "2019-05", "2020-07", "2021-11"], size=n)
    got = dips.month_bootstrap(delta, months, n_draws=draws, seed=seed)
    uniq = sorted(set(months.tolist()))
    pick = np.random.default_rng(seed).integers(0, len(uniq), size=(draws, len(uniq)))
    means = np.array([np.concatenate([delta[months == uniq[j]] for j in row]).mean() for row in pick])
    mean = delta.mean()
    assert got["mean"] == pytest.approx(mean, rel=1e-12)
    assert got["p"] == (1 + np.sum(means - mean >= mean)) / (draws + 1)
    assert got["ci_low"] == pytest.approx(np.quantile(means, 0.025), rel=1e-9)
    assert got["ci_high"] == pytest.approx(np.quantile(means, 0.975), rel=1e-9)
    assert got["n_months"] == len(uniq)


def test_month_bootstrap_rejects_bad_input():
    with pytest.raises(ValueError, match="non-empty 1-D finite"):
        dips.month_bootstrap([], [])
    with pytest.raises(ValueError, match="non-empty 1-D finite"):
        dips.month_bootstrap([0.1, np.nan], ["a", "b"])
    with pytest.raises(ValueError, match="non-empty 1-D finite"):
        dips.month_bootstrap([0.1, 0.2], ["a"])
    with pytest.raises(ValueError, match="n_draws must be"):
        dips.month_bootstrap([0.1], ["a"], n_draws=0)


def test_holm_by_hand():
    np.testing.assert_allclose(dips.holm([0.01, 0.04, 0.03]), [0.03, 0.06, 0.06], rtol=1e-15)
    np.testing.assert_allclose(dips.holm([0.5, 0.6]), [1.0, 1.0])
    np.testing.assert_allclose(dips.holm([0.02]), [0.02])
    with pytest.raises(ValueError, match="probabilities"):
        dips.holm([0.1, 1.2])


# ------------------------------------------------------------------------------------- test-window guard


def _fake_bars(first: str, last: str) -> pd.DataFrame:
    index = pd.date_range(first, last, freq="D", tz="UTC", name="ts")
    frame = pd.DataFrame({"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0}, index=index)
    frame.attrs = {"snapshot_id": "0123456789abcdef"}
    return frame


def test_study_bars_keep_train_and_validate_only():
    calls = []

    def loader(instrument, interval, start, end, catalog_dir):
        calls.append((instrument, interval, start, end))
        return _fake_bars("2016-12-30", "2024-07-01")

    bars = dips.load_study_bars("BTC/USD.KRAKEN", "2024-07-01", loader=loader)
    assert calls == [("BTC/USD.KRAKEN", "1d", pd.Timestamp("2017-01-02", tz="UTC"), CUT)]
    assert bars.index[0] == pd.Timestamp("2017-01-02", tz="UTC") and bars.index[-1] == CUT
    assert bars.attrs["snapshot_id"] == "0123456789abcdef"


def test_the_guard_fires_when_data_reach_the_test_window():
    """PLAN.md section 8: the assert that index.max() <= 2024-07-01 00:00 UTC fires."""
    with pytest.raises(HoldoutWindowError, match="after 2024-07-01"):
        dips.load_study_bars("BTC/USD.KRAKEN", "2024-07-01",
                             loader=lambda *a, **k: _fake_bars("2024-06-01", "2024-07-02"))
    with pytest.raises(HoldoutWindowError):
        dips.check_before_holdout(pd.DatetimeIndex([CUT + pd.Timedelta(microseconds=1)]))
    dips.check_before_holdout(pd.DatetimeIndex([CUT]))
    dips.check_before_holdout(pd.DatetimeIndex([]))


def test_a_request_past_the_cut_is_refused_before_loading():
    def loader(*args, **kwargs):
        raise AssertionError("must not be called")

    for last in ("2024-07-01 00:00:01", pd.Timestamp("2024-07-02", tz="UTC"), "2025-01-01"):
        with pytest.raises(HoldoutWindowError, match="test window"):
            dips.load_study_bars("BTC/USD.KRAKEN", last, loader=loader)
        with pytest.raises(HoldoutWindowError, match="test window"):
            dips.load_study_positioning("BTCUSDT", last, loader=loader)


def test_default_loaders_are_the_catalog_and_the_positioning_store(monkeypatch):
    import lab.data.catalog as catalog
    import lab.data.external as external

    monkeypatch.setattr(catalog, "load_bars", lambda *a, **k: _fake_bars("2022-12-01", "2023-01-01"))
    assert dips.load_study_bars("ETH/USD.KRAKEN", pd.Timestamp("2023-01-01", tz="UTC")).index[-1] == pd.Timestamp(
        "2023-01-01", tz="UTC"
    )
    seen = {}

    def fake_positioning(symbol, freq, end, catalog_dir, config_dir):
        seen.update(symbol=symbol, freq=freq, end=end)
        return pd.DataFrame({"funding_mean_7d": [0.0]}, index=pd.DatetimeIndex([end]))

    monkeypatch.setattr(external, "load_positioning", fake_positioning)
    pos = dips.load_study_positioning("ETHUSDT", "2023-01-01")
    assert seen == {"symbol": "ETHUSDT", "freq": "1d", "end": pd.Timestamp("2023-01-01", tz="UTC")}
    assert len(pos) == 1
    explicit = dips.load_study_positioning("BTCUSDT", CUT, loader=fake_positioning)
    assert seen["symbol"] == "BTCUSDT" and explicit.index[-1] == CUT
    monkeypatch.setattr(external, "load_positioning",
                        lambda *a, **k: pd.DataFrame(index=pd.DatetimeIndex([CUT + pd.Timedelta(days=1)])))
    with pytest.raises(HoldoutWindowError):
        dips.load_study_positioning("ETHUSDT", "2023-01-01")
