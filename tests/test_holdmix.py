"""The "hold this mix" engine, metrics and decision rules (``lab/runner/holdmix.py``), against
``research/hold-mix-cap/PLAN.md`` (sections 4-10 and the test list of section 14; tests 1-22 are its numbers).
SYNTHETIC data only: hand-built close paths, ``test_portfolio``'s random panels and hand-made runs tables. No catalog
read.

Hand-built paths have no overnight gaps (open = the previous close), so a fill re-cuts the book to the targets at the
previous close's prices: the weights at a close are then the targets drifted by the moves since the last fill, and the
comments give them to 3 or 4 digits (each test asserts the ones it relies on).
"""

from __future__ import annotations

import hashlib
import math
import struct
from fractions import Fraction

import numpy as np
import pandas as pd
import pytest
from hypothesis import assume, example, given
from hypothesis import strategies as st
from test_portfolio import (
    ALL_COLUMNS,
    COST_MODELS,
    fill_bars_of,
    panels,
    random_panel,
    run_checked,
    tamper_from,
    target_of,
    unit_book,
)

from lab.runner import holdmix as hm
from lab.runner import portfolio as pf
from lab.runner.interface import validate_result
from lab.runner.reference import Costs
from lab.validation import stats
from lab.validation.montecarlo import max_drawdown

LIM = pf.risk_limits("steady")  # config/risk_levels.yaml as read
MIN_CASH, MAX_COIN = LIM["min_cash"], LIM["max_coin"]
COSTS = Costs.from_yaml()
DAY = pd.Timedelta(days=1)
STEADY = "  coins: [BTC, ETH, USDC]\n  min_cash_pct: {cash}\n  max_coin_pct: {coin}\n  max_drawdown_budget_pct: TBD\n"

# ------------------------------------------------------------------------------------------------ helpers


def frame(closes, index) -> pd.DataFrame:
    c = np.asarray(closes, dtype=float)
    o = np.concatenate([[c[0]], c[:-1]])
    return pd.DataFrame(
        {
            "open": o,
            "high": np.maximum(o, c) * 1.005,
            "low": np.minimum(o, c) * 0.995,
            "close": c,
            "volume": np.full(len(c), 1000.0),
        },
        index=index,
    )


def path_panel(btc, eth, *, start="2020-01-01", skip=()) -> pd.DataFrame:
    """BTC and ETH from close paths (open = the previous close), one close a day from ``start``; the day offsets in
    ``skip`` are left out of the index (a missing close, as Kraken's 2018-01-13)."""
    days = [d for d in range(len(btc) + len(skip)) if d not in skip]
    index = pd.DatetimeIndex([pd.Timestamp(start, tz="UTC") + d * DAY for d in days], name="ts")
    return pf.make_panel({"BTC": frame(btc, index), "ETH": frame(eth, index)}, snapshot_id="hand")


def params(w_btc, w_eth, band, wait=1, *, steady=False, reset=None, first_buy_waits=None, **limits) -> dict:
    p = {
        "w_btc": w_btc,
        "w_eth": w_eth,
        "band": band,
        "wait_days": wait,
        "min_cash": MIN_CASH if steady else limits.get("min_cash"),
        "max_coin": MAX_COIN if steady else limits.get("max_coin"),
        "headroom": hm.HEADROOM if steady else limits.get("headroom", 0.0),
    }
    if reset is not None:
        p["reset_days"] = reset
    if first_buy_waits is not None:
        p["first_buy_waits"] = first_buy_waits
    return p


def run(p: dict, panel: pd.DataFrame, costs: Costs = COSTS) -> pd.DataFrame:
    return hm.hold_mix(p, panel, costs)


def flags(result: pd.DataFrame) -> tuple[list, list, list, list]:
    a = result.attrs
    return a["orders"].tolist(), list(a["reasons"]), a["in_wait"].tolist(), a["held"].tolist()


def metrics(result: pd.DataFrame, p: dict) -> dict:
    return hm.path_metrics(
        result,
        targets=(p["w_btc"], p["w_eth"]),
        band=p["band"],
        min_cash=p["min_cash"],
        max_coin=p["max_coin"],
        wait=p["wait_days"],
        first_buy_waits=p.get("first_buy_waits", False),
    )


def flat(n: int) -> list[float]:
    return [100.0] * n


# ------------------------------------------------------------------------------- 1. wait_days and cap labels


def test_wait_days_by_hand():
    expected = {None: 1, 8: 4, 4: 8, 2: 15, 1: 30, 0.5: 60, 0.25: 120, 0.3: 100, 7: 5, 31: 1}
    assert {cap: hm.wait_days(cap) for cap in expected} == expected
    assert [hm.wait_days(cap) for cap in hm.CAPS] == [1, 4, 8, 15, 30, 60, 120]
    assert hm.wait_days(np.float64(0.3)) == 100 and hm.wait_days(np.int64(8)) == 4
    assert hm.wait_days(Fraction(1, 3)) == 90 and hm.wait_days(30) == 1 and hm.wait_days(29) == 2
    assert all(isinstance(hm.wait_days(cap), int) for cap in hm.CAPS)
    assert tuple(hm.cap_label(cap) for cap in hm.CAPS) == hm.CAP_LABELS
    assert hm.cap_label(8.0) == "8" and hm.cap_label(0.5) == "0.5"
    assert hm.FINITE_CAPS == tuple(reversed(hm.CAP_LABELS[1:]))  # tightest first


@given(st.one_of(st.integers(1, 10_000), st.decimals("0.001", "100", places=3).map(float)))
def test_wait_days_is_the_exact_decimal_ceiling(cap):
    exact = Fraction(30) / Fraction(str(cap))
    w = hm.wait_days(cap)
    assert w == math.ceil(exact) and w - 1 < exact <= w


@pytest.mark.parametrize(
    ("cap", "wait"), [(3.333333333333333, 10), (1.6666666666666665, 19), (0.8571428571428571, 36)]
)
def test_wait_days_is_exact_where_floating_point_division_is_not(cap, wait):
    """Caps whose shortest decimal is not exact in binary: 30 / cap in floats gives another ceiling (#52)."""
    assert math.ceil(30 / cap) != wait
    assert hm.wait_days(cap) == wait


@pytest.mark.parametrize("bad", [0, 0.0, -1, -0.5, math.nan, math.inf, -math.inf, True, False, "2", [2]])
def test_wait_days_rejects_bad_caps(bad):
    with pytest.raises(ValueError, match="cap must be None .no cap. or a number of rebalances a month > 0"):
        hm.wait_days(bad)
    with pytest.raises(ValueError, match="cap must be None"):
        hm.cap_label(bad)


# ----------------------------------------------------------------------------------------- 2. strict params

GOOD = params(0.3, 0.2, 0.2, 15, steady=True)
BAD_PARAMS = {
    "not_a_dict": ([0.3, 0.2], "hold_mix: params must be a dict, got list"),
    "unknown_key": (
        {**GOOD, "every": 1},
        r"hold_mix: unknown params \['every'\]; allowed: \['band', 'first_buy",
    ),
    "missing_w_btc": ({k: v for k, v in GOOD.items() if k != "w_btc"}, "missing required param 'w_btc'"),
    "missing_band": ({k: v for k, v in GOOD.items() if k != "band"}, "missing required param 'band'"),
    "missing_wait": (
        {k: v for k, v in GOOD.items() if k != "wait_days"},
        "missing required param 'wait_days'",
    ),
    "missing_min_cash": (
        {k: v for k, v in GOOD.items() if k != "min_cash"},
        "missing required param 'min_cash'",
    ),
    "missing_max_coin": (
        {k: v for k, v in GOOD.items() if k != "max_coin"},
        "missing required param 'max_coin'",
    ),
    "missing_headroom": (
        {k: v for k, v in GOOD.items() if k != "headroom"},
        "missing required param 'headroom'",
    ),
    "negative_band": ({**GOOD, "band": -0.1}, r"band must be in \[0.0, inf\), got -0.1"),
    "nan_band": ({**GOOD, "band": math.nan}, r"band must be in \[0.0, inf\), got nan"),
    "inf_band": ({**GOOD, "band": math.inf}, r"band must be in \[0.0, inf\), got inf"),
    "string_band": ({**GOOD, "band": "0.2"}, "band must be a number, got '0.2'"),
    "wait_0": ({**GOOD, "wait_days": 0}, "wait_days must be >= 1, got 0"),
    "wait_1.5": ({**GOOD, "wait_days": 1.5}, "wait_days must be an integer, got 1.5"),
    "wait_bool": ({**GOOD, "wait_days": True}, "wait_days must be an integer, got True"),
    "reset_0": ({**GOOD, "reset_days": 0}, "reset_days must be >= 1, got 0"),
    "reset_2.5": ({**GOOD, "reset_days": 2.5}, "reset_days must be an integer, got 2.5"),
    "first_buy_waits_1": ({**GOOD, "first_buy_waits": 1}, "first_buy_waits must be True or False, got 1"),
    "first_buy_waits_none": (
        {**GOOD, "first_buy_waits": None},
        "first_buy_waits must be True or False, got None",
    ),
    "sum_above_1": (
        params(0.6, 0.5, 0.1),
        r"hold_mix: w_btc \+ w_eth must be <= 1 \(the rest is USDC\), got 0.6 \+ 0.5",
    ),
    "negative_target": ({**GOOD, "w_eth": -0.1}, r"w_eth must be in \[0.0, 1.0\], got -0.1"),
    "cash_inside_headroom": (
        params(0.4, 0.39, 0.1, steady=True),
        r"hold_mix: the targets w_btc = 0.4, w_eth = 0.39 break the limits min_cash = 0.2, max_coin = 0.6, "
        r"headroom = 0.02",
    ),
    "coin_inside_headroom": (params(0.59, 0.0, 0.1, steady=True), "hold_mix: the targets w_btc = 0.59"),
    "coin_over_limit": (
        params(0.0, 0.7, 0.1, max_coin=0.6),
        "hold_mix: the targets w_btc = 0.0, w_eth = 0.7",
    ),
    "headroom_without_limit": (
        params(0.3, 0.2, 0.1, headroom=0.02),
        r"hold_mix: headroom = 0.02 needs a limit",
    ),
    "negative_headroom": ({**GOOD, "headroom": -0.01}, r"headroom must be in \[0.0, 1.0\], got -0.01"),
    "min_cash_above_1": ({**GOOD, "min_cash": 1.5}, r"min_cash must be in \[0.0, 1.0\], got 1.5"),
    "max_coin_string": ({**GOOD, "max_coin": "0.6"}, "max_coin must be a number, got '0.6'"),
}


@pytest.mark.parametrize("case", list(BAD_PARAMS.values()), ids=list(BAD_PARAMS))
def test_bad_params_raise_with_pinned_messages(case):
    bad, match = case
    panel = random_panel(30, seed=1)
    with pytest.raises(ValueError, match=match):
        hm.hold_mix(bad, panel, COSTS)


def test_costs_must_be_a_costs_instance_and_bars_a_panel():
    panel = random_panel(30, seed=1)
    with pytest.raises(ValueError, match="costs must be a Costs instance or None, got dict"):
        hm.hold_mix(GOOD, panel, {"pool_fee_bps": 5})
    with pytest.raises(ValueError, match="panel must be a pandas DataFrame"):
        hm.hold_mix(GOOD, [1, 2], COSTS)
    np.testing.assert_array_equal(  # costs=None reads config/costs.yaml
        hm.hold_mix(GOOD, panel).to_numpy(), hm.hold_mix(GOOD, panel, Costs.from_yaml()).to_numpy()
    )


def test_optional_keys_default_to_no_reset_and_the_lab_reading():
    panel = random_panel(80, seed=2)
    base = hm.hold_mix(GOOD, panel, COSTS)
    explicit = hm.hold_mix({**GOOD, "reset_days": None, "first_buy_waits": False}, panel, COSTS)
    pd.testing.assert_frame_equal(base, explicit)
    assert flags(base) == flags(explicit)


@given(
    w_btc=st.floats(0.0, 1.0),
    w_eth=st.floats(0.0, 1.0),
    min_cash=st.one_of(st.none(), st.floats(0.0, 1.0)),
    max_coin=st.one_of(st.none(), st.floats(0.0, 1.0)),
    headroom=st.one_of(st.just(0.0), st.floats(0.0, 0.1)),
)
@example(w_btc=0.39, w_eth=0.39, min_cash=0.2, max_coin=0.6, headroom=0.02)  # the 0.78 / 0.5 edge of the grid
@example(w_btc=0.0, w_eth=0.58, min_cash=0.2, max_coin=0.6, headroom=0.02)
def test_hold_mix_accepts_exactly_the_targets_check_targets_accepts(
    w_btc, w_eth, min_cash, max_coin, headroom
):
    try:
        pf.check_targets(w_btc, w_eth, min_cash=min_cash, max_coin=max_coin, headroom=headroom)
        ok = True
    except ValueError as exc:
        ok = False
        message = str(exc).replace("rebalance:", "hold_mix:")
    p = {"w_btc": w_btc, "w_eth": w_eth, "band": 0.1, "wait_days": 1}
    p.update(min_cash=min_cash, max_coin=max_coin, headroom=headroom)
    panel = random_panel(5, seed=0)
    if ok:
        hm.hold_mix(p, panel, COSTS)
    else:
        with pytest.raises(ValueError) as caught:
            hm.hold_mix(p, panel, COSTS)
        assert str(caught.value) == message


def test_mix_targets_by_hand_and_bad_shares():
    assert hm.mix_targets(0.78, 0.5) == (0.39, 0.39)
    assert hm.mix_targets(0.6, 0.0) == (0.0, 0.6) and hm.mix_targets(0.6, 1.0) == (0.6, 0.0)
    assert hm.mix_targets(0.3, 0.25) == (0.3 * 0.25, 0.3 * (1.0 - 0.25))
    with pytest.raises(ValueError, match=r"s must be in \[0.0, 1.0\], got 1.2"):
        hm.mix_targets(1.2, 0.5)
    with pytest.raises(ValueError, match=r"f must be in \[0.0, 1.0\], got -0.1"):
        hm.mix_targets(0.5, -0.1)


# -------------------------------------------------------------------------------------- 3. the relative band


def test_the_band_is_relative_to_each_coin_s_target():
    """Targets 45% / 15%, b = 0.2: ETH may move 3 points (20% of 15%), BTC 9 points (20% of 45%)."""
    p = params(0.45, 0.15, 0.2, steady=True)
    y = 0.19 * 0.85 / (0.15 * 0.81)  # ETH's price ratio that puts it at 19% with BTC flat
    up = run(p, path_panel(flat(6), [100.0, 100.0 * y, *[100.0 * y] * 4]))
    assert up["w_ETH"].iloc[1] == pytest.approx(0.19, abs=1e-12)  # 4 points off: more than 3
    assert flags(up)[:2] == ([0, 1], ["first", "band"])
    x = 0.49 * 0.55 / (0.45 * 0.51)  # BTC's price ratio that puts it at 49% with ETH flat
    down = run(p, path_panel([100.0, *[100.0 * x] * 5], flat(6)))
    assert down["w_BTC"].iloc[1] == pytest.approx(0.49, abs=1e-12)  # 4 points off: less than 9
    assert abs(down["w_ETH"].iloc[1] - 0.15) < 0.03  # and ETH stayed inside its own band
    assert flags(down)[0] == [0]


@pytest.mark.parametrize("coin", ["BTC", "ETH"])
@pytest.mark.parametrize("direction", [1.2, 0.8])
def test_the_band_is_strict(coin, direction):
    """A weight exactly b * T off its target does not order; one ulp of band less does. Targets of 0.25 (a power of
    two) make b * T exact: b = deviation * 4."""
    move = [100.0, 100.0 * direction, 100.0 * direction]
    btc, eth = (move, flat(3)) if coin == "BTC" else (flat(3), move)
    panel = path_panel(btc + [btc[-1]], eth + [eth[-1]])
    p = params(0.25, 0.25, 1000.0)
    w = run(p, panel)[f"w_{coin}"].iloc[1]  # the weight at close 1, before any band order
    dev = abs(w - 0.25)
    band = dev * 4.0
    assert band * 0.25 == dev
    assert flags(run({**p, "band": band}, panel))[0] == [0]  # exactly on the band: inside
    assert flags(run({**p, "band": np.nextafter(band, 0.0)}, panel))[0] == [0, 1]  # just outside


def test_the_metrics_judge_the_band_boundary_as_the_rule_does():
    """path_metrics' in-band test is the rule's, strict: a weight exactly b * T off is in band (and the rule does
    not order); one ulp of band less, it is out (and the rule orders). #52"""
    panel = path_panel([100.0, 120.0, 120.0, 120.0], flat(4))
    p = params(0.25, 0.25, 1000.0)
    w = run(p, panel)["w_BTC"].iloc[1]
    band = abs(w - 0.25) * 4.0
    assert band * 0.25 == abs(w - 0.25)
    for b, inside in ((band, True), (np.nextafter(band, 0.0), False)):
        res = run({**p, "band": b}, panel)
        m = hm.path_metrics(res, targets=(0.25, 0.25), band=b, min_cash=None, max_coin=None, wait=1)
        assert (m["in_band_share"] == 1.0) is inside
        assert (res.attrs["orders"].tolist() == [0]) is inside  # the rule agrees


# --------------------------------------------------------------------------------------------- 4. target 0


@pytest.mark.parametrize("f", [0.0, 1.0])
def test_a_coin_with_target_0_never_orders_and_stays_exactly_0(f):
    w_btc, w_eth = hm.mix_targets(0.5, f)
    zero, held = ("w_BTC", "w_ETH") if f == 0.0 else ("w_ETH", "w_BTC")
    rng = np.random.default_rng(3)
    wild = list(100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.2, 40))))
    # the zero coin's price swings wildly while the held coin is flat: at b = 0 nothing ever orders
    panel = path_panel(flat(40), wild) if f == 1.0 else path_panel(wild, flat(40))
    result = run(params(w_btc, w_eth, 0.0), panel)
    assert (result[zero].to_numpy() == 0.0).all()
    assert (result[held].to_numpy()[1:] == 0.5).all()
    assert flags(result)[0] == [0]
    # the held coin moving orders at every close at b = 0, and the zero coin's weight is still exactly 0
    panel = path_panel(wild, flat(40)) if f == 1.0 else path_panel(flat(40), wild)
    moving = run(params(w_btc, w_eth, 0.0), panel)
    assert (moving[zero].to_numpy() == 0.0).all()
    assert flags(moving)[0] == list(range(39))
    m = metrics(moving, params(w_btc, w_eth, 0.0))
    assert m["dist_mean"] > 0.0 and m["breach_closes"] == 0


# ------------------------------------------------------------------------------------------------ 5. the wait


ETH_WAIT = [100.0, 120.0, 120.0, *[150.0] * 17]  # out of band at close 1, in at 2, out again from close 3


@pytest.mark.parametrize(
    ("wait", "orders", "held"),
    [(1, [0, 1, 3], []), (3, [0, 1, 4], [3]), (15, [0, 1, 16], list(range(3, 16)))],
)
def test_a_band_break_inside_the_wait_is_held_until_w_days_after_the_last_counted_order(wait, orders, held):
    """Targets 25% / 25%, b = 0.1 (2.5 points). ETH at 120 puts it at 28.6% (out), the fill at the next open puts it
    back; ETH at 150 puts it at 29.4% (out) until the next fill."""
    p = params(0.25, 0.25, 0.1, wait)
    result = run(p, path_panel(flat(20), ETH_WAIT))
    assert result["w_ETH"].iloc[1] == pytest.approx(0.3 / 1.05, abs=1e-12)
    assert result["w_ETH"].iloc[3] == pytest.approx(0.3125 / 1.0625, abs=1e-12)
    assert result["w_ETH"].iloc[2] == 0.25
    got = flags(result)
    assert got[0] == orders and got[3] == held
    assert got[1] == ["first", "band", "band"] and got[2] == [False, False, False]


@pytest.mark.parametrize("wait", [5, 15])
def test_a_held_band_break_is_forgotten_when_the_mix_comes_back(wait):
    eth = [100.0, 120.0, 120.0, 150.0, 150.0, 150.0, *[120.0] * 14]  # back at the fill price from close 6
    result = run(params(0.25, 0.25, 0.1, wait), path_panel(flat(20), eth))
    # back at its target to round-off (the drift ratios chain: 5.6e-17 off), far inside the 2.5-point band
    np.testing.assert_allclose(result["w_ETH"].iloc[6:], 0.25, rtol=0, atol=1e-15)
    assert flags(result)[0] == [0, 1] and flags(result)[3] == [3, 4, 5]


# ------------------------------------------------------------------------------------------- 6. the first buy


def test_the_first_buy_does_not_start_the_wait_and_the_first_rebalance_does():
    """W = 5. ETH at 130 on day 1 is out of band: it orders on day 1. ETH at 169 on day 2 is out again: the wait
    from day 1 holds it until day 6."""
    p = params(0.25, 0.25, 0.1, 5)
    result = run(p, path_panel(flat(12), [100.0, 130.0, *[169.0] * 10]))
    assert flags(result) == ([0, 1, 6], ["first", "band", "band"], [False, False, False], [2, 3, 4, 5])


def test_with_first_buy_waits_the_first_buy_starts_the_wait():
    eth = [100.0, *[130.0] * 11]
    lab = run(params(0.25, 0.25, 0.1, 5), path_panel(flat(12), eth))
    other = run(params(0.25, 0.25, 0.1, 5, first_buy_waits=True), path_panel(flat(12), eth))
    assert flags(lab)[0] == [0, 1] and flags(lab)[3] == []
    assert flags(other) == ([0, 5], ["first", "band"], [False, False], [1, 2, 3, 4])


@pytest.mark.parametrize("first_buy_waits", [False, True])
def test_the_reset_counts_from_the_first_buy(first_buy_waits):
    result = run(
        params(0.25, 0.25, 0.1, 5, reset=10, first_buy_waits=first_buy_waits), path_panel(flat(25), flat(25))
    )
    assert flags(result) == ([0, 10, 20], ["first", "reset", "reset"], [False] * 3, [])


def test_the_first_buy_is_not_a_rebalance_and_pays_no_counted_fees():
    p = params(0.3, 0.2, 0.2, 15, steady=True)
    result = run(p, path_panel(flat(30), flat(30)))
    m, t, money = metrics(result, p), hm.trade_sizes(result), hm.money_metrics(result, COSTS)
    assert (m["rebalances"], m["legs"], m["empty_orders"], m["max_in_30d"]) == (0, 0, 0, 0)
    assert money["fees_pct_per_year"] == money["gas_pct_per_year"] == money["fees_usd_per_year"] == 0.0
    assert t["first_legs"] == 2 and t["first_turnover_pct"] == pytest.approx(50.0, abs=1e-12)
    assert money["first_cost_pct"] > 0.0 and money["first_gas_usd"] == 2 * COSTS.gas_usd_per_trade
    assert (t["max_leg_pct"], t["max_day_turnover_pct"]) == (0.0, 0.0) and math.isnan(t["min_leg_usd"])


# ---------------------------------------------------------------------------------------- 7. the limit override

# Targets 39% / 39% (s = 0.78, cash 22%), b = 0.05 (1.95 points), W = 10, the Steady limits as read.
BTC_LIMIT = [100.0, 130.0, 130.0, 130.0, 130.0, *[143.0] * 12]
ETH_LIMIT = [100.0, 100.0, 100.0, 110.0, *[143.0] * 13]


def limit_case(first_buy_waits=None):
    p = params(0.39, 0.39, 0.05, 10, steady=True, first_buy_waits=first_buy_waits)
    return p, run(p, path_panel(BTC_LIMIT, ETH_LIMIT))


def test_a_breach_inside_the_wait_orders_at_once_counts_and_restarts_the_wait():
    """Close 1: BTC +30% puts the coins at 80.3% (cash under 20%): limit, before any counted order, so not inside a
    wait. Close 3: ETH +10% puts it at 41.3%, out of band (held: wait from close 1). Close 4: ETH +43% since its fill
    puts the coins at 81.2%: limit inside the wait; the wait restarts. Close 5: BTC +10% since its fill, out of band:
    held until close 14 (4 + 10), when it orders."""
    p, result = limit_case()
    w = result[list(pf.WEIGHT_COLUMNS)].to_numpy()
    assert w[1].sum() > 0.8 and w[4].sum() > 0.8  # breaches
    assert w[3].sum() < 0.8 and abs(w[3, 1] - 0.39) > 0.0195  # a band break, not a breach
    orders, reasons, in_wait, held = flags(result)
    assert orders == [0, 1, 4, 14]
    assert reasons == ["first", "limit", "limit", "band"]
    assert in_wait == [False, False, True, False]
    assert held == [3, *range(5, 14)]
    m = metrics(result, p)
    assert (m["rebalances"], m["rebalances_limit"], m["rebalances_band"], m["limit_in_wait"]) == (3, 2, 1, 1)


def test_with_first_buy_waits_a_breach_right_after_the_first_buy_is_inside_the_wait():
    _, result = limit_case(first_buy_waits=True)
    orders, reasons, in_wait, _ = flags(result)
    assert orders[:3] == [0, 1, 4] and reasons[:3] == ["first", "limit", "limit"]
    assert in_wait[:3] == [False, True, True]


def test_breaches_are_judged_at_the_limits_not_at_the_limits_minus_headroom():
    """BTC at 59% (inside max_coin but past max_coin - h): no limit order with a band that never fires."""
    x = 0.59 * 0.55 / (0.45 * 0.41)  # BTC 45% -> 59% with ETH flat at 0% and cash
    p = params(0.45, 0.0, hm.LIMIT_ONLY_BAND, steady=True)
    result = run(p, path_panel([100.0, *[100.0 * x] * 5], flat(6)))
    assert result["w_BTC"].iloc[1] == pytest.approx(0.59, abs=1e-12)
    assert flags(result)[0] == [0]
    assert metrics(result, p)["breach_closes"] == 0


# ------------------------------------------------------------------------------------------- 8. the same close


def test_a_breach_and_a_band_break_on_one_close_make_one_limit_order():
    p, result = limit_case()
    assert abs(result["w_BTC"].iloc[1] - 0.39) > 0.0195  # close 1 is also a band break
    assert flags(result)[1][1] == "limit"
    assert metrics(result, p)["rebalances"] == 3  # one order per close


def test_a_band_break_and_a_due_reset_on_one_close_make_one_band_order():
    p = params(0.25, 0.25, 0.1, 1, reset=5)
    result = run(p, path_panel(flat(10), [*flat(5), *[130.0] * 5]))
    assert flags(result)[:2] == ([0, 5], ["first", "band"])
    m = metrics(result, p)
    assert (m["rebalances"], m["rebalances_band"], m["rebalances_reset"]) == (1, 1, 0)


# ------------------------------------------------------------------------------------------------ 9. the reset


def test_the_reset_fires_inside_the_band_waits_when_r_is_below_w_and_restarts_the_wait():
    """R = 4, W = 6 on flat prices: resets at 4 (no wait yet), then due at 8 but held until 10, and so on."""
    p = params(0.25, 0.25, 0.1, 6, reset=4)
    result = run(p, path_panel(flat(25), flat(25)))
    assert flags(result) == (
        [0, 4, 10, 16, 22],
        ["first", *["reset"] * 4],
        [False] * 5,
        [8, 9, 14, 15, 20, 21],
    )
    m = metrics(result, p)
    assert (
        m["empty_orders"] == 4 and m["legs"] == 0
    )  # orders on a book at its targets trade nothing, but count
    assert m["rebalances"] == m["rebalances_reset"] == 4


def test_a_reset_restarts_the_wait_for_a_band_break():
    """After the reset at close 4, ETH at 130 from close 6 is out of band: held until 10 (4 + 6), a band order."""
    p = params(0.25, 0.25, 0.1, 6, reset=4)
    result = run(p, path_panel(flat(25), [*flat(6), *[130.0] * 19]))
    orders, reasons, _, held = flags(result)
    assert orders == [0, 4, 10, 16, 22] and reasons == ["first", "reset", "band", "reset", "reset"]
    assert held == [6, 7, 8, 9, 14, 15, 20, 21]


def test_a_reset_longer_than_the_wait_is_never_held():
    result = run(params(0.25, 0.25, 0.1, 3, reset=10), path_panel(flat(25), flat(25)))
    assert flags(result)[0] == [0, 10, 20] and flags(result)[3] == []


# ------------------------------------------------------------------------------------ 10. calendar days, not rows


def test_the_wait_is_counted_in_calendar_days_across_a_missing_close():
    """Day 3 is missing. The band order on day 1 starts a wait of W = 3 days: the band break of day 2 is held and
    ordered on day 4, which is row 3 (a row-counting wait would order one row later, on day 5)."""
    p = params(0.25, 0.25, 0.1, 3)
    panel = path_panel(flat(8), [100.0, 130.0, *[169.0] * 6], skip=(3,))
    assert panel.index[3] - panel.index[2] == 2 * DAY
    result = run(p, panel)
    assert flags(result)[0] == [0, 1, 3] and flags(result)[3] == [2]
    assert result.index[3] == panel.index[1] + 3 * DAY
    m = metrics(result, p)
    # rows 1, 2 and 3 (days 1, 2 and 4) are out of band: one spell of 4 calendar days
    assert m["longest_out_days"] == 4.0
    assert m["out_days_per_year"] == 365 * 3 / 7


# ----------------------------------------------------------------------------------------------- 11. counting


def test_the_last_close_s_decision_is_never_sent_or_counted():
    p = params(0.25, 0.25, 0.1, 1)
    result = run(p, path_panel(flat(10), [*flat(9), 130.0]))
    assert abs(result["w_ETH"].iloc[-1] - 0.25) > 0.025  # out of band at the last close
    assert flags(result)[0] == [0] and metrics(result, p)["rebalances"] == 0


def test_a_hold_at_the_last_close_is_not_listed():
    p = params(0.25, 0.25, 0.1, 10)
    result = run(p, path_panel(flat(6), [100.0, 130.0, *[169.0] * 4]))
    assert flags(result)[0] == [0, 1]
    assert flags(result)[3] == [2, 3, 4]  # close 5, the last, would be held too: not listed


def test_reasons_and_flags_align_with_the_engine_s_orders():
    _, result = limit_case()
    a = result.attrs
    assert len(a["reasons"]) == len(a["in_wait"]) == len(a["orders"])
    assert a["reasons"].dtype == object and a["in_wait"].dtype == bool and a["held"].dtype == np.int64
    assert set(np.asarray(a["reasons"])[a["in_wait"]]) == {"limit"}  # only limit orders inside the wait
    validate_result(result, path_panel(BTC_LIMIT, ETH_LIMIT))


# --------------------------------------------------------------------------------------- strategies (12-17)


def drop_close(panel: pd.DataFrame, i: int) -> pd.DataFrame:
    """The panel without row ``i`` (a missing close: the next row's return spans two days)."""
    keep = np.ones(len(panel), dtype=bool)
    keep[i] = False
    frames = {
        a: pd.DataFrame({f: panel[(a, f)].to_numpy()[keep] for f in pf.FIELDS}, index=panel.index[keep])
        for a in pf.ASSETS
    }
    return pf.make_panel(frames, snapshot_id=panel.attrs["snapshot_id"])


@st.composite
def gappy_panels(draw) -> pd.DataFrame:
    panel = draw(panels())
    if draw(st.booleans()):
        panel = drop_close(panel, draw(st.integers(1, len(panel) - 2)))
    return panel


def _limits(draw, w_btc: float, w_eth: float) -> dict:
    kind = draw(st.sampled_from(["none", "steady", "near"]))
    if kind == "steady":
        try:
            pf.check_targets(w_btc, w_eth, min_cash=MIN_CASH, max_coin=MAX_COIN, headroom=hm.HEADROOM)
            return {"min_cash": MIN_CASH, "max_coin": MAX_COIN, "headroom": hm.HEADROOM}
        except ValueError:
            kind = "near"
    if kind == "near":  # limits a small slack from the targets, so that breaches happen
        slack = st.one_of(st.sampled_from([0.0, 0.005, 0.02, 0.05]), st.floats(0.0, 1.0))
        return {
            "min_cash": max(0.0, 1.0 - (w_btc + w_eth) - draw(slack)) if draw(st.booleans()) else None,
            "max_coin": min(1.0, max(w_btc, w_eth) + draw(slack)) if draw(st.booleans()) else None,
            "headroom": 0.0,
        }
    return {"min_cash": None, "max_coin": None, "headroom": 0.0}


@st.composite
def hold_params(draw, first_buy_waits=None) -> dict:
    s = draw(st.one_of(st.sampled_from([0.0, 0.2, 0.5, 0.78, 1.0]), st.floats(0.0, 1.0)))
    f = draw(st.one_of(st.sampled_from([0.0, 0.25, 0.5, 0.75, 1.0]), st.floats(0.0, 1.0)))
    w_btc, w_eth = hm.mix_targets(s, f)
    assume(w_btc + w_eth <= 1.0)
    return {
        "w_btc": w_btc,
        "w_eth": w_eth,
        "band": draw(st.sampled_from([0.0, 0.01, 0.05, 0.1, 0.2, 0.5, hm.LIMIT_ONLY_BAND])),
        "wait_days": draw(st.one_of(st.sampled_from([1, 2, 3, 4, 5, 7, 15, 30]), st.integers(1, 90))),
        "reset_days": draw(st.one_of(st.none(), st.sampled_from([2, 3, 5, 10, 30]))),
        "first_buy_waits": draw(st.booleans() if first_buy_waits is None else first_buy_waits),
        **_limits(draw, w_btc, w_eth),
    }


def assert_same_result(a: pd.DataFrame, b: pd.DataFrame) -> None:
    np.testing.assert_array_equal(a[ALL_COLUMNS].to_numpy(), b[ALL_COLUMNS].to_numpy())
    for key in ("orders", "trade_returns"):
        np.testing.assert_array_equal(a.attrs[key], b.attrs[key], err_msg=key)
    assert a.attrs["n_trades"] == b.attrs["n_trades"] and a.attrs["snapshot_id"] == b.attrs["snapshot_id"]
    pd.testing.assert_frame_equal(a.attrs["fills"], b.attrs["fills"])


def outcome(rule, p, panel, costs):
    """The rule's result, or the message of the refusal it raised (a fill costing the whole wallet)."""
    try:
        return rule(p, panel, costs)
    except ValueError as exc:
        return str(exc)


RUIN = Costs(
    pool_fee_bps=30.0, aggregator_fee_bps=10.0, gas_usd_per_trade=25.0
)  # TESTING.md #49's cost model

# --------------------------------------------------------------------------- 12. identity with portfolio.rebalance


@given(
    panel=gappy_panels(),
    s=st.one_of(st.sampled_from([0.0, 0.2, 0.5, 0.78, 1.0]), st.floats(0.0, 1.0)),
    f=st.sampled_from([0.0, 0.5, 1.0]),
    b=st.sampled_from([0.0, 0.01, 0.05, 0.1, 0.3, 1.0, 5.0]),
    data=st.data(),
    costs=st.sampled_from(COST_MODELS),
)
# a ruined book (TESTING.md #49): BTC only at 60%, b = 0 and 25 USD of gas a leg; both refuse the fill on bar 116
@example(panel=random_panel(120, 10, (0.1, 0.0), (0.03, 0.0)), s=0.6, f=1.0, b=0.0, data=None, costs=RUIN)
@example(panel=random_panel(60, 4), s=0.78, f=0.5, b=0.05, data=None, costs=Costs())
def test_with_w_1_and_one_absolute_band_hold_mix_equals_rebalance_bit_for_bit(panel, s, f, b, data, costs):
    """Where the relative band is one absolute band for both coins (f = 0.5: equal targets; f = 0 or 1: one coin),
    W = 1 and no reset, hold_mix is rebalance(band = b * T, every = 1) with the same limits and headroom: every
    column, orders, fills, trade returns and n_trades, or the same refusal. Also without limits."""
    w_btc, w_eth = hm.mix_targets(s, f)
    limits = (
        {"min_cash": MIN_CASH, "max_coin": MAX_COIN, "headroom": hm.HEADROOM}
        if data is None
        else _limits(data.draw, w_btc, w_eth)
    )
    if data is None and s == 0.6:
        limits = {"min_cash": None, "max_coin": None, "headroom": 0.0}
    target = max(w_btc, w_eth)  # the non-zero target (both are equal at f = 0.5)
    hold = {"w_btc": w_btc, "w_eth": w_eth, "band": b, "wait_days": 1, **limits}
    reb = {"w_btc": w_btc, "w_eth": w_eth, "band": b * target, "every": 1, **limits}
    a, c = outcome(hm.hold_mix, hold, panel, costs), outcome(pf.rebalance, reb, panel, costs)
    if isinstance(a, str) or isinstance(c, str):
        assert a == c
        return
    assert_same_result(a, c)
    assert set(a.attrs["reasons"][1:]) <= {"limit", "band"} and not a.attrs["in_wait"].any()
    assert len(a.attrs["held"]) == 0


# ------------------------------------------------------------------------------- 13. identity with limit-only


@given(
    panel=gappy_panels(), p=hold_params(first_buy_waits=st.just(False)), costs=st.sampled_from(COST_MODELS)
)
@example(
    panel=random_panel(80, 5, (0.1, 0.1)),
    p=params(0.39, 0.39, hm.LIMIT_ONLY_BAND, 30, steady=True),
    costs=Costs(),
)
def test_a_band_that_never_fires_is_limit_only_for_any_wait(panel, p, costs):
    """With b * T >= 1 for every coin with T > 0 and no reset, hold_mix is rebalance(band = 1.0, every = 1) bit for
    bit, whatever W: only the first buy and limit fixes trade, and limit fixes ignore the wait."""
    positive = [t for t in (p["w_btc"], p["w_eth"]) if t > 0.0]
    assume(not positive or min(positive) >= 1e-3)
    p = {**p, "band": hm.LIMIT_ONLY_BAND, "reset_days": None}
    assert all(p["band"] * t >= 1.0 for t in positive)
    reb = {k: p[k] for k in ("w_btc", "w_eth", "min_cash", "max_coin", "headroom")}
    a = outcome(hm.hold_mix, p, panel, costs)
    c = outcome(pf.rebalance, {**reb, "band": 1.0, "every": 1}, panel, costs)
    if isinstance(a, str) or isinstance(c, str):
        assert a == c
        return
    assert_same_result(a, c)
    assert set(a.attrs["reasons"][1:]) <= {"limit"} and len(a.attrs["held"]) == 0


# -------------------------------------------------------------------------- 14. decisions do not depend on costs


@given(panel=gappy_panels(), p=hold_params())
def test_decisions_and_weights_do_not_depend_on_costs_or_the_wallet_size(panel, p):
    base = hm.hold_mix(p, panel, Costs.zero())
    digest = hm.path_hash(base)
    for book in hm.BOOKS:
        one = Costs.from_yaml(capital_usd=book)
        for costs in (one, one.stressed()):
            result = hm.hold_mix(p, panel, costs)
            for key in ("orders", "reasons", "in_wait", "held"):
                np.testing.assert_array_equal(result.attrs[key], base.attrs[key], err_msg=key)
            for col in ("position", "turnover", *pf.WEIGHT_COLUMNS):
                np.testing.assert_array_equal(result[col].to_numpy(), base[col].to_numpy(), err_msg=col)
            assert hm.path_hash(result) == digest


# ---------------------------------------------------------------------------------- 15. accounting identities

RUINED = (random_panel(99, 168, (0.1, 0.0), (0.0, 0.0)), params(0.75, 0.2, 0.0, 1), RUIN)  # refused on bar 98


@given(panel=gappy_panels(), p=hold_params(), costs=st.sampled_from(COST_MODELS))
@example(panel=RUINED[0], p=RUINED[1], costs=RUINED[2])
def test_accounting_equals_an_independent_book_of_coin_units_and_cash(panel, p, costs):
    """Per bar, from coin units and USDC cash (``test_portfolio.unit_book``), to 1e-12: every result column, and
    every leg (asset, side, units, open price, USD size, cost = usd * rate(usd) + gas, weights). Where the engine
    refuses a fill the book cannot pay (``run_checked``), on every bar before it."""
    panel, result = run_checked(hm.hold_mix, p, panel, costs)
    out, legs, v_open, _, dust = unit_book(panel, target_of(p), result, costs)
    assert (out["cost"] < 1.0).all() and (dust <= 1e-12).all()
    for col in ALL_COLUMNS:
        np.testing.assert_allclose(result[col].to_numpy(), out[col], rtol=0, atol=1e-12, err_msg=col)
    log = result.attrs["fills"]
    assert list(log["bar"]) == [leg["bar"] for leg in legs] and list(log["asset"]) == [
        leg["asset"] for leg in legs
    ]
    np.testing.assert_array_equal(log["price"].to_numpy(), [leg["price"] for leg in legs])
    scale = np.array([v_open[list(fill_bars_of(result)).index(leg["bar"])] for leg in legs])
    for col in ("usd", "cost"):
        np.testing.assert_allclose(
            log[col].to_numpy() / scale, [leg[col] for leg in legs] / scale, rtol=0, atol=1e-12, err_msg=col
        )
    expected = [u * costs.rate(u) + costs.gas_usd_per_trade for u in log["usd"].tolist()]
    np.testing.assert_array_equal(
        log["cost"].to_numpy(), expected
    )  # each leg pays its own size's rate plus gas


@given(panel=gappy_panels(), p=hold_params(), costs=st.sampled_from(COST_MODELS))
@example(panel=RUINED[0], p=RUINED[1], costs=RUINED[2])
def test_costs_off_vs_on_only_fills_pay_and_trade_returns_chain(panel, p, costs):
    free = hm.hold_mix(p, panel, Costs.zero())
    bars, paid = run_checked(hm.hold_mix, p, panel, costs)
    n = len(bars)
    gross, net = 1 + free["ret"].to_numpy()[:n], 1 + paid["ret"].to_numpy()
    np.testing.assert_allclose(net, gross * (1 - paid["cost"].to_numpy()), rtol=0, atol=1e-15)
    turnover, cost = paid["turnover"].to_numpy(), paid["cost"].to_numpy()
    assert (cost[turnover == 0] == 0.0).all() and (cost[turnover > 0] > 0.0).all()
    assert paid.attrs["n_trades"] == int((turnover > 0).sum()) == len(paid.attrs["trade_returns"])
    _, _, v_open, value, _ = unit_book(bars, target_of(p), paid, costs)
    tr = paid.attrs["trade_returns"]
    np.testing.assert_allclose(
        1.0 + tr, np.array([*v_open[1:], value[-1]][: len(tr)]) / np.array(v_open), rtol=1e-12
    )
    assert np.prod(1.0 + tr) == pytest.approx(np.prod(net), rel=1e-12)


# ---------------------------------------------------------------------------------------- 16. tamper the future


@given(panel=gappy_panels(), p=hold_params(), data=st.data())
def test_no_look_ahead(panel, p, data):
    """Every field of both assets changed from row ``cut`` on, except the opens of ``cut`` (the fill prices of the
    decision at close cut-1): every result row, order, reason, in-wait flag and held close before ``cut`` is
    identical, and so is the fill on row ``cut``."""
    cut = data.draw(st.integers(1, len(panel) - 1))
    tampered = tamper_from(panel, cut, data.draw(st.integers(0, 2**16)))
    a, b = hm.hold_mix(p, panel, COSTS), hm.hold_mix(p, tampered, COSTS)
    np.testing.assert_array_equal(a[ALL_COLUMNS].to_numpy()[:cut], b[ALL_COLUMNS].to_numpy()[:cut])
    assert a["turnover"].iloc[cut] == b["turnover"].iloc[cut] and a["cost"].iloc[cut] == b["cost"].iloc[cut]
    fa, fb = a.attrs["fills"], b.attrs["fills"]
    pd.testing.assert_frame_equal(fa[fa["bar"] <= cut], fb[fb["bar"] <= cut])
    for result in (a, b):
        result.attrs["_before"] = result.attrs["orders"] < cut
    for key in ("orders", "reasons", "in_wait"):
        np.testing.assert_array_equal(a.attrs[key][a.attrs["_before"]], b.attrs[key][b.attrs["_before"]])
    ha, hb = a.attrs["held"], b.attrs["held"]
    np.testing.assert_array_equal(ha[ha < cut], hb[hb < cut])


@given(panel=gappy_panels(), p=hold_params(), data=st.data())
def test_a_shorter_panel_equals_the_longer_one_cut_at_its_last_close(panel, p, data):
    m = data.draw(st.integers(2, len(panel)))
    long, short = hm.hold_mix(p, panel, COSTS), hm.hold_mix(p, panel.iloc[:m], COSTS)
    np.testing.assert_array_equal(short[ALL_COLUMNS].to_numpy(), long[ALL_COLUMNS].to_numpy()[:m])
    sent = long.attrs["orders"] < m - 1
    for key in ("orders", "reasons", "in_wait"):
        np.testing.assert_array_equal(short.attrs[key], long.attrs[key][sent], err_msg=key)
    held = long.attrs["held"]
    np.testing.assert_array_equal(short.attrs["held"], held[held <= m - 2])
    fl = long.attrs["fills"]
    pd.testing.assert_frame_equal(short.attrs["fills"], fl[fl["bar"] <= m - 1])


# ------------------------------------------------------------------------------------- 17. orders follow the rule


def rule_by_hand(result: pd.DataFrame, p: dict) -> tuple[list, list, list, list]:
    """Steps 1-5 of PLAN.md section 4.2, from the result's weights and close times (pandas Timedeltas, plain loops)."""
    index, n = result.index, len(result)
    wb, we = result["w_BTC"].tolist(), result["w_ETH"].tolist()
    targets, band = (p["w_btc"], p["w_eth"]), p["band"]
    wait = pd.Timedelta(days=p["wait_days"])
    reset = None if p.get("reset_days") is None else pd.Timedelta(days=p["reset_days"])
    min_cash, max_coin = p["min_cash"], p["max_coin"]
    orders, reasons, in_wait, held = [], [], [], []
    last_any = last_wait = None
    for t in range(n - 1):  # the last close's decision is never sent
        w, now = (wb[t], we[t]), index[t]
        waiting = last_wait is not None and now - last_wait < wait
        if t == 0:
            reason = "first"
        else:
            breach = (min_cash is not None and w[0] + w[1] > 1 - min_cash + 1e-9) or (
                max_coin is not None and (w[0] > max_coin + 1e-9 or w[1] > max_coin + 1e-9)
            )
            out = any(targets[a] > 0 and abs(w[a] - targets[a]) > band * targets[a] for a in (0, 1))
            due = reset is not None and now - last_any >= reset
            if breach:
                reason = "limit"
            elif out or due:
                if waiting:
                    held.append(t)
                    continue
                reason = "band" if out else "reset"
            else:
                continue
        orders.append(t)
        reasons.append(reason)
        in_wait.append(reason == "limit" and waiting)
        last_any = now
        if reason != "first" or p.get("first_buy_waits", False):
            last_wait = now
    return orders, reasons, in_wait, held


@given(panel=gappy_panels(), p=hold_params())
@example(panel=path_panel(BTC_LIMIT, ETH_LIMIT), p=params(0.39, 0.39, 0.05, 10, steady=True))
@example(panel=path_panel(flat(25), flat(25)), p=params(0.25, 0.25, 0.1, 6, reset=4))
def test_orders_follow_the_rule(panel, p):
    """Every order, reason, in-wait flag and held close is the one steps 1-5 give, recomputed from the result's
    weights and close times. No order that is not a limit order comes less than W days after the previous order
    that starts the wait (with first_buy_waits: the first buy too), and no 30 days hold more than ceil(30 / W)."""
    result = hm.hold_mix(p, panel, COSTS)
    first_buy_waits = p.get("first_buy_waits", False)
    assert flags(result) == rule_by_hand(result, p)
    hm.check_path(result, wait=p["wait_days"], first_buy_waits=first_buy_waits)
    orders, reasons, _, _ = flags(result)
    starts = [
        result.index[t] for t, r in zip(orders, reasons, strict=True) if r != "first" or first_buy_waits
    ]
    ordinary = [result.index[t] for t, r in zip(orders, reasons, strict=True) if r in ("band", "reset")]
    for t in ordinary:
        before = [s for s in starts if s < t]
        assert not before or t - before[-1] >= pd.Timedelta(days=p["wait_days"])
    most = max((sum(1 for u in ordinary if t <= u < t + 30 * DAY) for t in ordinary), default=0)
    assert most <= math.ceil(30 / p["wait_days"])


# ------------------------------------------------------------------------------------- 18. path metrics by hand


def metrics_by_hand(result: pd.DataFrame, p: dict) -> dict:
    """PLAN.md section 8 with plain loops over the result's weights, close times and fill log."""
    index, n = result.index, len(result)
    span = (index[-1] - index[0]) / DAY
    targets, band = (p["w_btc"], p["w_eth"]), p["band"]
    wb, we = result["w_BTC"].tolist(), result["w_ETH"].tolist()
    out, dist, drift, breaches = [], [], [], 0
    for t in range(1, n):
        w = (wb[t], we[t])
        devs = [abs(w[a] - targets[a]) for a in (0, 1) if targets[a] > 0]
        out.append(any(abs(w[a] - targets[a]) > band * targets[a] for a in (0, 1) if targets[a] > 0))
        dist.append(max([abs(w[a] - targets[a]) / targets[a] for a in (0, 1) if targets[a] > 0], default=0.0))
        assert len(devs) == sum(1 for a in (0, 1) if targets[a] > 0)
        drift.append(100 * abs(w[0] + w[1] - (targets[0] + targets[1])))
        cash_low = p["min_cash"] is not None and w[0] + w[1] > 1 - p["min_cash"] + 1e-9
        coin_high = p["max_coin"] is not None and max(w) > p["max_coin"] + 1e-9
        breaches += cash_low or coin_high
    longest, start = 0.0, None
    for i, o in enumerate(out + [False]):
        t = i + 1
        if o and start is None:
            start = t
        if not o and start is not None:
            longest = max(longest, (index[t - 1] - index[start]) / DAY + 1)
            start = None
    orders, reasons, in_wait, held = flags(result)
    counted = [t for t, r in zip(orders, reasons, strict=True) if r != "first"]
    limit = sum(r == "limit" for r in reasons)
    most = max(
        (sum(1 for u in counted if index[t] <= index[u] < index[t] + 30 * DAY) for t in counted), default=0
    )
    fills = result.attrs["fills"]
    legs = sum(1 for b in fills["bar"] if b >= 2)
    return {
        "rows": n,
        "span_days": span,
        "wait_days": p["wait_days"],
        "rebalances": len(counted),
        "rebalances_band": sum(r == "band" for r in reasons),
        "rebalances_limit": limit,
        "rebalances_reset": sum(r == "reset" for r in reasons),
        "rebalances_per_30d": 30 * len(counted) / span,
        "rebalances_per_30d_no_limit": 30 * (len(counted) - limit) / span,
        "limit_in_wait": sum(in_wait),
        "limit_in_wait_per_year": 365 * sum(in_wait) / span,
        "held": len(held),
        "held_per_year": 365 * len(held) / span,
        "max_in_30d": most,
        "legs": legs,
        "legs_per_year": 365 * legs / span,
        "empty_orders": sum(1 for t in counted if result["turnover"].iloc[t + 1] == 0.0),
        "in_band_share": out.count(False) / (n - 1),
        "out_days_per_year": 365 * sum(out) / (n - 1),
        "longest_out_days": longest,
        "dist_mean": sum(dist) / len(dist),
        "dist_worst": max(dist),
        "drift_mean_pts": sum(drift) / len(drift),
        "drift_worst_pts": max(drift),
        "breach_closes": breaches,
    }


def assert_metrics_equal(got: dict, want: dict) -> None:
    assert set(got) == set(want)
    for key, value in want.items():
        assert got[key] == pytest.approx(value, rel=1e-12, abs=1e-12), key
        assert isinstance(got[key], type(value)) or isinstance(value, float), key


def test_path_metrics_by_hand_on_a_built_path():
    """ETH_WAIT with W = 1 and no costs: out of band at closes 1 and 3 only (each fill at the next open puts the mix
    back), so a metric that read the weights one row late (after the fill) would see one out-of-band close, at 2."""
    p = params(0.25, 0.25, 0.1, 1)
    result = run(p, path_panel(flat(20), ETH_WAIT), Costs.zero())
    m = metrics(result, p)
    assert_metrics_equal(m, metrics_by_hand(result, p))
    w1_btc, w1_eth, w3_btc, w3_eth = 0.25 / 1.05, 0.3 / 1.05, 0.25 / 1.0625, 0.3125 / 1.0625
    assert m["out_days_per_year"] == pytest.approx(365 * 2 / 19) and m["in_band_share"] == pytest.approx(
        17 / 19
    )
    assert m["longest_out_days"] == 1.0 and m["span_days"] == 19.0
    assert (m["rebalances"], m["rebalances_band"], m["max_in_30d"], m["legs"], m["held"]) == (2, 2, 2, 4, 0)
    assert m["rebalances_per_30d"] == pytest.approx(60 / 19)
    assert m["dist_worst"] == pytest.approx((w3_eth - 0.25) / 0.25, rel=1e-12)
    assert m["dist_mean"] == pytest.approx(((w1_eth - 0.25) / 0.25 + (w3_eth - 0.25) / 0.25) / 19, rel=1e-12)
    assert m["drift_worst_pts"] == pytest.approx(
        100 * (w3_btc + w3_eth - 0.5), rel=1e-12
    )  # 2.94 > 2.38 at close 1
    assert m["drift_mean_pts"] == pytest.approx(
        100 * (w1_btc + w1_eth - 0.5 + w3_btc + w3_eth - 0.5) / 19, rel=1e-12
    )
    t = hm.trade_sizes(result)
    assert t["max_leg_pct"] == pytest.approx(100 * (w3_eth - 0.25), rel=1e-12)
    assert t["max_day_turnover_pct"] == pytest.approx(100 * ((w3_eth - 0.25) + (0.25 - w3_btc)), rel=1e-12)
    assert t["min_leg_usd"] == pytest.approx(
        125.0, rel=1e-12
    )  # BTC's leg at row 2: (0.25 - 0.25 / 1.05) * 10500
    assert (t["first_legs"], t["first_max_leg_pct"], t["first_turnover_pct"]) == (2, 25.0, 50.0)
    assert t["first_min_leg_usd"] == pytest.approx(2500.0, rel=1e-15)


@pytest.mark.parametrize("case", ["limit", "wait", "reset", "gap"])
def test_path_metrics_by_hand_on_the_rule_s_paths(case):
    if case == "limit":
        p, result = limit_case()
    else:
        p = {
            "wait": params(0.25, 0.25, 0.1, 15),
            "reset": params(0.25, 0.25, 0.1, 6, reset=4),
            "gap": params(0.25, 0.25, 0.1, 3),
        }[case]
        panel = {
            "wait": path_panel(flat(20), ETH_WAIT),
            "reset": path_panel(flat(25), [*flat(6), *[130.0] * 19]),
            "gap": path_panel(flat(8), [100.0, 130.0, *[169.0] * 6], skip=(3,)),
        }[case]
        result = run(p, panel)
    assert_metrics_equal(metrics(result, p), metrics_by_hand(result, p))
    if case == "limit":
        m = metrics(result, p)
        assert (m["held"], m["max_in_30d"], m["legs"], m["breach_closes"]) == (10, 3, 6, 2)
        assert m["rebalances_per_30d_no_limit"] == pytest.approx(30 / 16)
        assert m["limit_in_wait_per_year"] == pytest.approx(365 / 16)


@given(panel=gappy_panels(), p=hold_params())
def test_path_metrics_equal_the_hand_computation(panel, p):
    result = hm.hold_mix(p, panel, COSTS)
    assert_metrics_equal(metrics(result, p), metrics_by_hand(result, p))


def test_path_metrics_reject_bad_arguments():
    p, result = limit_case()
    kw = {"targets": (0.39, 0.39), "band": 0.05, "min_cash": MIN_CASH, "max_coin": MAX_COIN, "wait": 10}
    for change, match in [
        ({"targets": (1.2, 0.0)}, r"targets\[0\] must be in \[0.0, 1.0\]"),
        ({"targets": (0.3, -0.1)}, r"targets\[1\] must be in \[0.0, 1.0\]"),
        ({"band": -1.0}, r"band must be in \[0.0, inf\)"),
        ({"min_cash": 2.0}, r"min_cash must be in \[0.0, 1.0\]"),
        ({"max_coin": "x"}, "max_coin must be a number"),
        ({"wait": 0}, "wait must be an integer >= 1, got 0"),
        ({"wait": 2.0}, "wait must be an integer >= 1, got 2.0"),
    ]:
        with pytest.raises(ValueError, match=match):
            hm.path_metrics(result, **{**kw, **change})


def test_trade_sizes_without_any_trade():
    result = run(
        params(0.0, 0.0, 0.1), path_panel(flat(10), flat(10))
    )  # all cash: the first buy trades nothing
    t = hm.trade_sizes(result)
    assert (t["first_legs"], t["first_max_leg_pct"], t["first_turnover_pct"], t["max_leg_pct"]) == (
        0,
        0.0,
        0.0,
        0.0,
    )
    assert math.isnan(t["first_min_leg_usd"]) and math.isnan(t["min_leg_usd"])
    two = run(params(0.5, 0.0, 0.1), path_panel([100.0, 200.0], flat(2)))  # two rows: no row 2
    assert hm.trade_sizes(two)["max_day_turnover_pct"] == 0.0


def test_the_smallest_rebalance_leg_leaves_out_the_first_buy():
    """A hand-made fill log: the first buy (row 1) holds the smallest leg (10 USD); the rebalances' smallest is 50
    USD (section 8: trade sizes from rows 2 and later). #52"""
    index = pd.DatetimeIndex([pd.Timestamp("2021-03-01", tz="UTC") + d * DAY for d in range(5)], name="ts")
    result = pd.DataFrame({"turnover": [0.0, 0.5, 0.0, 0.02, 0.0]}, index=index)
    result.attrs["fills"] = pd.DataFrame(
        {
            "bar": np.array([1, 1, 3, 3], dtype=np.int64),
            "usd": [10.0, 1000.0, 50.0, 60.0],
            "weight_before": [0.0, 0.0, 0.30, 0.20],
            "weight_after": [0.01, 0.49, 0.29, 0.21],
        }
    )
    t = hm.trade_sizes(result)
    assert t["min_leg_usd"] == 50.0 and t["first_min_leg_usd"] == 10.0
    assert t["first_legs"] == 2 and t["max_day_turnover_pct"] == 2.0


# ------------------------------------------------------------------------------------ 19. money metrics by hand


def crafted(ret, days, start="2021-03-01") -> pd.DataFrame:
    """A result with these returns on these day offsets and no fill (money_metrics reads ret, cost and the log)."""
    index = pd.DatetimeIndex([pd.Timestamp(start, tz="UTC") + d * DAY for d in days], name="ts").as_unit("us")
    result = pd.DataFrame({"ret": np.asarray(ret, dtype=float), "cost": 0.0}, index=index)
    empty = np.array([], dtype=float)
    result.attrs["fills"] = pd.DataFrame(
        {
            "bar": np.array([], dtype=np.int64),
            "usd": empty,
            "cost": empty,
            "weight_before": empty,
            "weight_after": empty,
        }
    )
    return result


def test_falls_by_hand_start_as_peak_ties_and_a_week_ending_on_a_missing_close():
    """Equity 1 (close 0), 0.5 on days 1-6, 0.25 on day 8, 0.3 on days 9-10; day 7 is missing. The worst 7-day fall
    is days 1 -> 8 (-50%): the pair 0 -> 7 does not exist (a version taking the next close, day 8, would give -75%).
    The fall from the start: -75% from close 0 (a peak) to day 8. Days 1 and 8 tie as worst day: the first counts."""
    ret = [0.0, -0.5, 0.0, 0.0, 0.0, 0.0, 0.0, -0.5, 0.2, 0.0]
    result = crafted(ret, [0, 1, 2, 3, 4, 5, 6, 8, 9, 10])
    m = hm.money_metrics(result, Costs.zero())
    day = lambda d: pd.Timestamp("2021-03-01", tz="UTC") + d * DAY  # noqa: E731
    assert (m["max_drawdown"], m["mdd_peak"], m["mdd_trough"]) == (-0.75, day(0), day(8))
    assert (m["worst_day"], m["worst_day_close"]) == (-0.5, day(1))
    assert (m["worst_week"], m["worst_week_start"], m["worst_week_end"]) == (-0.5, day(1), day(8))
    assert m["total_return"] == pytest.approx(0.25 * 1.2 - 1.0, rel=1e-15)
    assert m["sharpe"] == stats.annualized_sharpe(np.asarray(ret[1:]), 365)
    assert m["fees_pct_per_year"] == m["gas_pct_per_year"] == m["first_cost_pct"] == 0.0


def test_a_tied_peak_and_a_tied_trough_take_the_first_close():
    m = hm.money_metrics(crafted([0.0, 0.1, -0.5, 1.0, -0.5, 0.0], range(6)), Costs.zero())
    day = lambda d: pd.Timestamp("2021-03-01", tz="UTC") + d * DAY  # noqa: E731
    assert (m["max_drawdown"], m["mdd_peak"], m["mdd_trough"]) == (-0.5, day(1), day(2))
    assert math.isnan(m["worst_week"]) and m["worst_week_start"] is pd.NaT and m["worst_week_end"] is pd.NaT
    # two equal peaks before the trough (equity 1, 1.1, 1.1, 0.55): the peak is the first of them (TESTING.md #50)
    flat_top = hm.money_metrics(crafted([0.0, 0.1, 0.0, -0.5], range(4)), Costs.zero())
    assert (flat_top["max_drawdown"], flat_top["mdd_peak"], flat_top["mdd_trough"]) == (-0.5, day(1), day(3))
    from_start = hm.money_metrics(crafted([0.0, 0.0, -0.5], range(3)), Costs.zero())
    assert (from_start["mdd_peak"], from_start["mdd_trough"]) == (day(0), day(2))  # the start is the first peak
    rising = hm.money_metrics(crafted([0.0, 0.1, 0.1], range(3)), Costs.zero())
    assert (rising["max_drawdown"], rising["mdd_peak"], rising["mdd_trough"]) == (0.0, day(0), day(0))


@pytest.mark.parametrize("book", [500.0, 5000.0, 50000.0])
def test_fees_and_gas_by_hand_from_the_fill_log(book):
    p, _ = limit_case()
    for costs in (Costs.from_yaml(capital_usd=book), Costs.from_yaml(capital_usd=book).stressed()):
        result = run(p, path_panel(BTC_LIMIT, ETH_LIMIT), costs)
        m = hm.money_metrics(result, costs)
        year = 365 / 16
        fees = gas = fees_usd = 0.0
        legs = result.attrs["fills"]
        for leg in legs.itertuples():
            if leg.bar >= 2:
                v_open = leg.usd / abs(leg.weight_after - leg.weight_before)
                fees += (leg.cost - costs.gas_usd_per_trade) / v_open
                gas += costs.gas_usd_per_trade / v_open
                fees_usd += leg.cost - costs.gas_usd_per_trade
        assert m["fees_pct_per_year"] == pytest.approx(100 * year * fees, rel=1e-12)
        assert m["gas_pct_per_year"] == pytest.approx(100 * year * gas, rel=1e-12)
        assert m["fees_usd_per_year"] == pytest.approx(year * fees_usd, rel=1e-12)
        assert m["gas_usd_per_year"] == pytest.approx(year * 6 * costs.gas_usd_per_trade, rel=1e-15)
        paid = result["cost"].to_numpy()[2:].sum()
        assert m["fees_pct_per_year"] + m["gas_pct_per_year"] == pytest.approx(100 * year * paid, rel=1e-12)
        first = legs[legs["bar"] == 1]
        assert m["first_cost_usd"] == pytest.approx(first["cost"].sum(), rel=1e-15)
        assert m["first_cost_pct"] == pytest.approx(100 * first["cost"].sum() / book, rel=1e-12)
        assert m["first_gas_usd"] == 2 * costs.gas_usd_per_trade
        r = result["ret"].to_numpy()[1:]
        assert m["total_return"] == pytest.approx(np.prod(1 + r) - 1, rel=1e-12)
        assert m["max_drawdown"] == max_drawdown(r) and m["sharpe"] == stats.annualized_sharpe(r, 365)
        assert m["worst_day"] == r.min() and m["worst_day_close"] == result.index[1 + int(np.argmin(r))]


def test_fees_per_year_use_the_calendar_span_across_a_missing_close():
    """Day 9 is missing: 17 rows over 17 calendar days. Fees and gas a year are 365 / span (17), not 365 / (n - 1)
    (16), as section 8 writes. #52"""
    p, _ = limit_case()
    result = run(p, path_panel(BTC_LIMIT, ETH_LIMIT, skip=(9,)))
    span = (result.index[-1] - result.index[0]) / DAY
    assert span == 17 and len(result) - 1 == 16
    m = hm.money_metrics(result, COSTS)
    legs = result.attrs["fills"]
    later = legs[legs["bar"] >= 2]
    assert len(later)
    v_open = later["usd"] / (later["weight_after"] - later["weight_before"]).abs()
    gas = COSTS.gas_usd_per_trade
    year = 365 / span
    assert m["fees_pct_per_year"] == pytest.approx(100 * year * ((later["cost"] - gas) / v_open).sum(), rel=1e-12)
    assert m["gas_pct_per_year"] == pytest.approx(100 * year * (gas / v_open).sum(), rel=1e-12)
    assert m["fees_usd_per_year"] == pytest.approx(year * (later["cost"] - gas).sum(), rel=1e-12)
    assert m["gas_usd_per_year"] == pytest.approx(year * gas * len(later), rel=1e-12)


@given(panel=gappy_panels(), p=hold_params(), costs=st.sampled_from((*COST_MODELS[:2], Costs.zero())))
def test_money_metrics_by_brute_force(panel, p, costs):
    result = hm.hold_mix(p, panel, costs)
    m = hm.money_metrics(result, costs)
    r = result["ret"].to_numpy()[1:]
    e = np.cumprod(np.concatenate(([1.0], 1.0 + r)))
    index = result.index
    pairs = [(u, t) for u in range(len(e)) for t in range(len(e)) if index[t] - index[u] == 7 * DAY]
    if pairs:
        falls = [e[t] / e[u] - 1.0 for u, t in pairs]
        i = int(np.argmin(falls))
        assert m["worst_week"] == falls[i]
        assert (m["worst_week_start"], m["worst_week_end"]) == (index[pairs[i][0]], index[pairs[i][1]])
    else:
        assert math.isnan(m["worst_week"])
    peak = [max(e[: t + 1]) for t in range(len(e))]
    dd = [e[t] / peak[t] - 1.0 for t in range(len(e))]
    trough = dd.index(min(dd))
    assert m["max_drawdown"] == min(dd) and m["mdd_trough"] == index[trough]
    assert m["mdd_peak"] == index[[t for t in range(trough + 1) if e[t] == peak[trough]][0]]
    # fees and gas a year, leg by leg, over the calendar span (the panels drop closes: #52)
    year = 365 / ((index[-1] - index[0]) / DAY)
    gas = costs.gas_usd_per_trade
    fees = gas_frac = fees_usd = 0.0
    n_legs = 0
    for leg in result.attrs["fills"].itertuples():
        if leg.bar >= 2:
            v_open = leg.usd / abs(leg.weight_after - leg.weight_before)
            fees += (leg.cost - gas) / v_open
            gas_frac += gas / v_open
            fees_usd += leg.cost - gas
            n_legs += 1
    assert m["fees_pct_per_year"] == pytest.approx(100 * year * fees, rel=1e-12, abs=1e-12)
    assert m["gas_pct_per_year"] == pytest.approx(100 * year * gas_frac, rel=1e-12, abs=1e-12)
    assert m["fees_usd_per_year"] == pytest.approx(year * fees_usd, rel=1e-12, abs=1e-12)
    assert m["gas_usd_per_year"] == pytest.approx(year * gas * n_legs, rel=1e-12)


def test_money_metrics_refuse_another_cost_model_and_a_broken_cost_column(monkeypatch):
    p, result = limit_case()
    with pytest.raises(
        hm.ConsistencyError, match="leg costs are not usd . rate.usd. . gas of this cost model"
    ):
        hm.money_metrics(result, COSTS.stressed())
    with pytest.raises(ValueError, match="costs must be a Costs instance, got NoneType"):
        hm.money_metrics(result, None)
    broken = result.copy()
    broken.attrs = result.attrs
    broken.iloc[5, broken.columns.get_loc("cost")] *= 1.0 + 1e-9
    with pytest.raises(hm.ConsistencyError, match=r"customer fees \+ gas .* differ from the cost column"):
        hm.money_metrics(broken, COSTS)
    monkeypatch.setattr(hm, "max_drawdown", lambda r: -0.123)
    with pytest.raises(hm.ConsistencyError, match="differs from montecarlo.max_drawdown"):
        hm.money_metrics(result, COSTS)


# ------------------------------------------------------------------------------------- check_path and path_hash


def broken(result: pd.DataFrame, **attrs) -> pd.DataFrame:
    out = result.copy()
    out.attrs = {**result.attrs, **attrs}
    return out


def test_check_path_refuses_each_kind_of_broken_path():
    p, good = limit_case()  # orders [0, 1, 4, 14]: first, limit, limit (inside the wait), band; W = 10
    hm.check_path(good, wait=10)
    a = good.attrs
    cases = [
        (broken(good, reasons=a["reasons"][:3]), "not aligned with the engine's orders"),
        (broken(good, in_wait=a["in_wait"][:3]), "not aligned with the engine's orders"),
        (
            broken(good, reasons=np.array(["band", "limit", "limit", "band"], dtype=object)),
            "one order at close 0",
        ),
        (
            broken(good, reasons=np.array(["first", "first", "limit", "band"], dtype=object)),
            "one order at close 0",
        ),
        (broken(good, orders=np.array([1, 2, 4, 14]), reasons=a["reasons"]), "one order at close 0"),
        (
            broken(
                good, orders=np.array([], dtype=np.int64), reasons=a["reasons"][:0], in_wait=a["in_wait"][:0]
            ),
            "one order at close 0",
        ),
        (
            broken(good, reasons=np.array(["first", "limit", "stop", "band"], dtype=object)),
            "orders must be increasing",
        ),
        (broken(good, orders=np.array([0, 4, 1, 14])), "orders must be increasing"),
        (broken(good, orders=np.array([0, 1, 4, 16])), "orders must be increasing"),
        (
            broken(good, in_wait=np.array([False, False, False, False])),
            "in-wait flag of the order at 2020-01-05",
        ),
        (
            broken(good, in_wait=np.array([False, False, True, True])),
            "in-wait flag of the order at 2020-01-15",
        ),
        (broken(good, held=np.array([0, 3])), "held closes must be"),
        (broken(good, held=np.array([3, 16])), "held closes must be"),  # 16 is the last close (n - 1)
        (broken(good, held=np.array([5, 3])), "held closes must be"),
        (broken(good, held=np.array([3, 4])), "held closes must be"),
    ]
    for result, match in cases:
        with pytest.raises(hm.ConsistencyError, match=match):
            hm.check_path(result, wait=10)
        with pytest.raises(hm.ConsistencyError, match=match):  # path_metrics runs the check first
            metrics(result, p)
    with pytest.raises(ValueError, match="wait must be an integer >= 1, got True"):
        hm.check_path(good, wait=True)


def test_check_path_refuses_orders_that_break_the_wait():
    fast = run(params(0.25, 0.25, 0.1, 1), path_panel(flat(20), ETH_WAIT))  # band orders at closes 1 and 3
    hm.check_path(fast, wait=1)
    hm.check_path(fast, wait=2)
    with pytest.raises(
        hm.ConsistencyError,
        match=r"2 orders that are not limit orders in one 30-day stretch, more "
        r"than ceil\(30 / 30\) = 1",
    ):
        hm.check_path(fast, wait=30)
    with pytest.raises(
        hm.ConsistencyError, match="a band order at 2020-01-04 .* comes less than 15 days after"
    ):
        hm.check_path(fast, wait=15)  # 2 orders in 30 days is allowed at W = 15, the 2-day gap is not
    early = run(
        params(0.25, 0.25, 0.1, 5), path_panel(flat(12), [100.0, *[130.0] * 11])
    )  # a band order at close 1
    hm.check_path(early, wait=5)
    with pytest.raises(hm.ConsistencyError, match="a band order at 2020-01-02 .* comes less than 5 days"):
        hm.check_path(early, wait=5, first_buy_waits=True)
    _, limit_lab = limit_case()
    with pytest.raises(hm.ConsistencyError, match="in-wait flag of the order at 2020-01-02"):
        hm.check_path(
            limit_lab, wait=10, first_buy_waits=True
        )  # under that reading close 1 is inside the wait


def hash_by_hand(result: pd.DataFrame) -> str:
    def part(name: str, data: bytes) -> bytes:
        return name.encode() + b"\x00" + struct.pack("<Q", len(data)) + data

    a = result.attrs
    blob = part("orders", struct.pack(f"<{len(a['orders'])}q", *a["orders"].tolist()))
    blob += part("reasons", "\n".join(a["reasons"]).encode())
    blob += part("in_wait", bytes(int(x) for x in a["in_wait"]))
    for col in ("w_BTC", "w_ETH"):
        blob += part(col, struct.pack(f"<{len(result)}d", *result[col].tolist()))
    return hashlib.sha256(blob).hexdigest()


def test_path_hash_by_hand_and_what_moves_it():
    _, result = limit_case()
    digest = hm.path_hash(result)
    assert digest == hash_by_hand(result) and len(digest) == 64
    a = result.attrs
    moved = [
        broken(result, orders=np.array([0, 1, 4, 13])),
        broken(result, reasons=np.array(["first", "limit", "limit", "reset"], dtype=object)),
        broken(result, in_wait=np.array([False, False, False, False])),
    ]
    weight = result.copy()
    weight.attrs = a
    weight.iloc[7, weight.columns.get_loc("w_ETH")] = np.nextafter(weight["w_ETH"].iloc[7], 1.0)
    for other in (*moved, weight):
        assert hm.path_hash(other) != digest
    assert hm.path_hash(broken(result, held=np.array([3]))) == digest  # held is not hashed
    costly = result.copy()
    costly.attrs = a
    costly["cost"] = 0.5
    assert hm.path_hash(costly) == digest


# ------------------------------------------------------------------------------------------- 20. windows by hand


def utc(day: str) -> pd.Timestamp:
    return pd.Timestamp(day, tz="UTC")


def calendar_panel(first: str, last: str, missing=()) -> pd.DataFrame:
    """A random-walk panel on every daily close first .. last except ``missing`` (shaped like DATA.md's panels)."""
    grid = pd.date_range(utc(first), utc(last), freq="D", name="ts")
    index = grid[~grid.isin(pd.DatetimeIndex([utc(d) for d in missing]))]
    rng = np.random.default_rng(11)
    closes = {a: 100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.03, len(index)))) for a in pf.ASSETS}
    return pf.make_panel({a: frame(closes[a], index) for a in pf.ASSETS}, snapshot_id="calendar")


KRAKEN_LIKE = calendar_panel("2017-01-02", "2023-01-01", missing=("2018-01-13",))
BINANCE_LIKE = calendar_panel("2017-08-01", "2023-01-01")  # holds k = 7's first close, 2017-08-02


def test_kraken_windows_by_hand():
    windows = hm.rolling_windows("KRAKEN")
    assert [k for k, _, _ in windows] == list(range(60))
    by_k = {k: (first, last) for k, first, last in windows}
    expected = {
        0: ("2017-01-02", "2018-01-01"),
        1: ("2017-02-02", "2018-02-01"),
        12: ("2018-01-02", "2019-01-01"),
        25: ("2019-02-02", "2020-02-01"),
        26: ("2019-03-02", "2020-03-01"),
        37: ("2020-02-02", "2021-02-01"),
        38: ("2020-03-02", "2021-03-01"),
        59: ("2021-12-02", "2022-12-01"),
    }
    assert {k: by_k[k] for k in expected} == {k: (utc(a), utc(b)) for k, (a, b) in expected.items()}
    assert all(last <= utc("2023-01-01") for _, _, last in windows)
    assert all(first.hour == 0 and first.day == 2 and last.day == 1 for _, first, last in windows)
    rows = {
        k: len(hm.window_slice(KRAKEN_LIKE, a, b, missing=hm.MISSING_CLOSES["KRAKEN"])) for k, a, b in windows
    }
    assert {k for k, r in rows.items() if r == 364} == set(range(1, 13))  # the windows holding 2018-01-13
    assert {k for k, r in rows.items() if r == 366} == set(
        range(26, 38)
    )  # the windows holding 29 February 2020
    assert sum(r == 365 for r in rows.values()) == 36
    first, last = hm.full_window("KRAKEN")
    assert (first, last) == (utc("2017-01-02"), utc("2023-01-01"))
    assert len(hm.window_slice(KRAKEN_LIKE, first, last, missing=hm.MISSING_CLOSES["KRAKEN"])) == 2190


def test_binance_windows_come_from_the_calendar_not_the_panel():
    windows = hm.rolling_windows("BINANCE")
    assert [k for k, _, _ in windows] == list(range(8, 60))
    assert windows[0][1:] == (utc("2017-09-02"), utc("2018-09-01"))
    assert utc("2017-08-02") in BINANCE_LIKE.index  # k = 7 would fit this panel, and is not listed
    rows = [len(hm.window_slice(BINANCE_LIKE, a, b)) for _, a, b in windows]
    assert rows.count(365) == 40 and rows.count(366) == 12
    assert hm.full_window("BINANCE") == (utc("2017-08-18"), utc("2023-01-01"))
    assert hm.MISSING_CLOSES == {"BINANCE": (), "KRAKEN": (utc("2018-01-13"),)}
    with pytest.raises(ValueError, match=r"source must be one of \('KRAKEN', 'BINANCE'\), got 'COINBASE'"):
        hm.rolling_windows("COINBASE")
    with pytest.raises(ValueError, match="source must be one of"):
        hm.full_window("kraken")


def test_window_slice_refuses_a_missing_or_an_extra_close():
    _, first, last = hm.rolling_windows("KRAKEN")[5]
    with pytest.raises(
        hm.WindowSliceError, match=r"364 closes, expected 365; missing \['2018-01-13T00:00:00\+00:00'\]"
    ):
        hm.window_slice(KRAKEN_LIKE, first, last)  # the missing close is not pinned for this call
    with pytest.raises(hm.WindowSliceError, match=r"extra \['2018-01-13T00:00:00\+00:00'\]"):
        hm.window_slice(BINANCE_LIKE, first, last, missing=hm.MISSING_CLOSES["KRAKEN"])
    with pytest.raises(hm.WindowSliceError, match=r"missing \['2017-01-01T00:00:00\+00:00'\]"):
        hm.window_slice(KRAKEN_LIKE, utc("2017-01-01"), utc("2017-03-01"))  # the panel lacks the first close
    off_grid = drop_close(calendar_panel("2020-01-01", "2020-01-10"), 4)
    noon = off_grid.index.insert(4, utc("2020-01-05 12:00"))
    shifted = pf.make_panel(
        {a: frame(np.linspace(100.0, 110.0, 10), noon) for a in pf.ASSETS}, snapshot_id="x"
    )
    with pytest.raises(hm.WindowSliceError, match=r"extra \['2020-01-05T12:00:00\+00:00'\]"):
        hm.window_slice(shifted, utc("2020-01-01"), utc("2020-01-10"), missing=[utc("2020-01-05")])
    piece = hm.window_slice(KRAKEN_LIKE, "2019-01-02", "2019-01-31")  # naive means UTC
    assert len(piece) == 30 and piece.attrs == KRAKEN_LIKE.attrs
    with pytest.raises(ValueError, match="panel must be a pandas DataFrame"):
        hm.window_slice("panel", first, last)


# ------------------------------------------------------------------------------------------------ 21. the grid


def test_the_27_mixes_pass_the_limits_as_read_and_the_8_left_out_are_refused():
    assert len(hm.MIXES) == 27 and len(set(hm.MIXES)) == 27
    hm.check_grid(MIN_CASH, MAX_COIN)
    assert hm.feasible_mixes(MIN_CASH, MAX_COIN) == list(hm.MIXES)
    for s, f in hm.MIXES:
        pf.check_targets(*hm.mix_targets(s, f), min_cash=MIN_CASH, max_coin=MAX_COIN, headroom=hm.HEADROOM)
    assert (0.78, 0.5) in hm.MIXES  # the edge: cash exactly 22%
    left_out = sorted({(s, f) for s in hm.S_VALUES for f in hm.F_VALUES} - set(hm.MIXES))
    assert left_out == [
        (0.6, 0.0),
        (0.6, 1.0),
        (0.7, 0.0),
        (0.7, 1.0),
        (0.78, 0.0),
        (0.78, 0.25),
        (0.78, 0.75),
        (0.78, 1.0),
    ]
    for s, f in left_out:
        with pytest.raises(ValueError, match="break the limits"):
            pf.check_targets(
                *hm.mix_targets(s, f), min_cash=MIN_CASH, max_coin=MAX_COIN, headroom=hm.HEADROOM
            )
    largest = max(max(hm.mix_targets(s, f)) for s, f in hm.MIXES)
    assert largest == pytest.approx(0.525) and min(1 - s for s, _ in hm.MIXES) == pytest.approx(0.22)
    assert hm.LIMIT_ONLY_BAND * min(t for s, f in hm.MIXES for t in hm.mix_targets(s, f) if t > 0) >= 50.0


def test_a_tighter_risk_levels_file_refuses_some_mixes(tmp_path):
    (tmp_path / "risk_levels.yaml").write_text("steady:\n" + STEADY.format(cash=25, coin=50))
    tight = pf.risk_limits("steady", config_dir=tmp_path)
    assert (tight["min_cash"], tight["max_coin"]) == (0.25, 0.5)
    with pytest.raises(
        ValueError, match=r"the grid's mixes \[.*\(0.5, 0.0\).*\(0.78, 0.5\)\] break min_cash = 0.25"
    ):
        hm.check_grid(tight["min_cash"], tight["max_coin"])
    kept = hm.feasible_mixes(tight["min_cash"], tight["max_coin"])
    assert (0.78, 0.5) not in kept and (0.5, 0.0) not in kept and (0.5, 0.5) in kept and len(kept) < 27


def test_the_pinned_grid_values():
    assert hm.BANDS == (0.05, 0.10, 0.15, 0.20, 0.30, 0.50) and hm.CAPS == (None, 8, 4, 2, 1, 0.5, 0.25)
    assert hm.BOOKS == (500.0, 5000.0, 50000.0) and hm.HEADROOM == 0.02 and hm.RESET_DAYS == 365
    assert (hm.EXTRA_OUT_MEDIAN, hm.EXTRA_OUT_P90, hm.RATE_MAX, hm.FEE_MAX) == (7.0, 30.0, 1.0, 0.25)
    assert (hm.CLOSE_SHARE, hm.VALUE_FACTOR) == (0.90, 2.0)
    # the other readings of the Steady limits (PLAN.md section 9), from the limits as read with h
    assert hm.CASH_READING_MIN_S == pytest.approx(1 - (MAX_COIN - hm.HEADROOM), abs=1e-12)
    assert hm.TOGETHER_READING_MAX_S == pytest.approx(MAX_COIN - hm.HEADROOM, abs=1e-12)
    assert sum(s >= hm.CASH_READING_MIN_S for s, _ in hm.MIXES) == 12
    assert sum(s <= hm.TOGETHER_READING_MAX_S for s, _ in hm.MIXES) == 20


# ------------------------------------------------------------------------------- 22. decision rules: the tables

TABLE_MIXES = ((0.5, 0.5), (0.2, 0.0))
TABLE_WINDOWS = (
    0,
    1,
    2,
    3,
    4,
)  # 10 pairs: the 90th percentile is v[8] + 0.1 * (v[9] - v[8]) of the sorted values
DIST = {
    "none": 0.0,
    "8": 0.5,
    "4": 1.0,
    "2": 2.0,
    "1": 4.0,
    "0.5": 6.0,
    "0.25": 8.0,
}  # with Dist_L = 10: I = 1 - D/10
FEES = {"none": 0.25, "8": 0.25, "4": 0.125, "2": 0.0625, "1": 0.03125, "0.5": 0.0, "0.25": 0.0}  # F_L = 0
GRID_KEYS = dict(scope="rolling", comparator="grid", reading="lab", R=math.nan)


def runs_table(*, source="KRAKEN", mixes=TABLE_MIXES, windows=TABLE_WINDOWS, books=hm.BOOKS) -> pd.DataFrame:
    """A pool: one row per pair, band, cap, wallet size and cost level; ``pair`` numbers the pairs 0 .. 9."""
    rows = [
        {
            "source": source,
            **GRID_KEYS,
            "window": k,
            "s": s,
            "f": f,
            "b": b,
            "cap": cap,
            "V": book,
            "cost": cost,
            "status": "ok",
            "pair": i * len(windows) + j,
            "out_days_per_year": 0.0,
            "rebalances_per_30d": 0.5,
            "fees_pct_per_year": FEES[cap],
            "dist_mean": DIST[cap],
            "gas_usd_per_year": 2.0,
        }
        for i, (s, f) in enumerate(mixes)
        for j, k in enumerate(windows)
        for b in hm.BANDS
        for cap in hm.CAP_LABELS
        for book in books
        for cost in hm.COST_LABELS
    ]
    return pd.DataFrame(rows)


def limit_table(*, source="KRAKEN", mixes=TABLE_MIXES, windows=TABLE_WINDOWS, bands=False) -> pd.DataFrame:
    """Limit-only rows: one per pair, wallet size and cost level (with ``bands``, also one per grid band)."""
    rows = [
        {
            "source": source,
            **GRID_KEYS,
            "comparator": "limit-only",
            "window": k,
            "s": s,
            "f": f,
            "b": b,
            "cap": "none",
            "V": book,
            "cost": cost,
            "status": "ok",
            "dist_mean": 10.0,
            "fees_pct_per_year": 0.0,
            "gas_usd_per_year": 1.0,
            "out_days_per_year": 100.0,
        }
        for s, f in mixes
        for k in windows
        for b in (hm.BANDS if bands else (math.nan,))
        for book in hm.BOOKS
        for cost in hm.COST_LABELS
    ]
    return pd.DataFrame(rows)


RUNS = runs_table()
LIMIT_ONLY = limit_table()


def where(table: pd.DataFrame, **equal) -> np.ndarray:
    mask = np.ones(len(table), dtype=bool)
    for col, value in equal.items():
        mask &= table[col].to_numpy() == value
    return mask


def put(table: pd.DataFrame, col: str, value, **equal) -> pd.DataFrame:
    out = table.copy()
    out.loc[where(out, **equal), col] = value
    return out


# ------------------------------------------------------------------------------------------- 22. rule B


def test_rule_b_a_median_of_exactly_7_passes_and_a_hair_above_fails():
    t = put(RUNS, "out_days_per_year", 7.0, b=0.1)
    t.loc[where(t, b=0.1, cap="none"), "out_days_per_year"] = 0.0
    r = hm.cap_for_band(t, 0.1)
    assert r["N_star"] == "0.25" and r["pairs"] == 10 and r["band"] == 0.1
    assert r["caps"]["2"] == {"median": 7.0, "p90": 7.0, "passes": True}
    worse = put(t, "out_days_per_year", 7.0 + 1e-9, b=0.1, cap="2")
    assert hm.cap_for_band(worse, 0.1)["caps"]["2"]["passes"] is False
    assert hm.cap_for_band(worse, 0.1)["N_star"] == "4"  # tighter caps pass, but cap 2 fails: the guard


def test_rule_b_a_90th_percentile_of_exactly_30_passes():
    t = put(RUNS, "out_days_per_year", 100.0, b=0.2, cap="0.25")
    t.loc[where(t, b=0.2, cap="0.5"), "out_days_per_year"] = 100.0
    t.loc[where(t, b=0.2, cap="1") & np.isin(t["pair"], [8, 9]), "out_days_per_year"] = 30.0
    r = hm.cap_for_band(t, 0.2)
    assert r["caps"]["1"] == {"median": 0.0, "p90": 30.0, "passes": True} and r["N_star"] == "1"
    t.loc[where(t, b=0.2, cap="1", pair=9), "out_days_per_year"] = 30.000001
    assert hm.cap_for_band(t, 0.2)["caps"]["1"]["p90"] > 30.0 and hm.cap_for_band(t, 0.2)["N_star"] == "2"


def test_rule_b_subtracts_the_no_cap_run_and_8_failing_is_more_than_8():
    t = put(RUNS, "out_days_per_year", 50.0, b=0.05)
    t.loc[where(t, b=0.05, cap="8"), "out_days_per_year"] = 57.0  # extra 7 against no cap's 50: passes
    assert hm.cap_for_band(t, 0.05)["caps"]["8"]["median"] == 7.0
    t.loc[where(t, b=0.05, cap="8"), "out_days_per_year"] = 58.0
    r = hm.cap_for_band(t, 0.05)
    assert r["N_star"] == hm.MORE_THAN_8 and r["caps"]["4"]["passes"] is True
    # only the 5,000 USD 1x runs count: another wallet size's numbers change nothing
    assert hm.cap_for_band(put(t, "out_days_per_year", 999.0, V=500.0), 0.05) == r


def test_rule_b_missing_and_bad_tables():
    failed = put(RUNS, "status", "failed", b=0.1, cap="2", V=5000.0, cost="1x", pair=3)
    assert hm.cap_for_band(failed, 0.1) == {"band": 0.1, "N_star": hm.MISSING, "pairs": None, "caps": None}
    assert hm.cap_for_band(put(RUNS, "status", "failed", b=0.1, V=500.0), 0.1)["N_star"] == "0.25"
    with pytest.raises(ValueError, match=r"band must be one of the grid bands .*got 0.07"):
        hm.cap_for_band(RUNS, 0.07)
    with pytest.raises(ValueError, match="no runs at band 0.3, 5,000 USD and 1x"):
        hm.cap_for_band(RUNS[RUNS["b"] != 0.3], 0.3)
    with pytest.raises(ValueError, match="two runs for one pair and cap"):
        hm.cap_for_band(pd.concat([RUNS, RUNS[where(RUNS, b=0.1, V=5000.0, cost="1x")].iloc[:1]]), 0.1)
    with pytest.raises(ValueError, match="every pair needs one run at each cap"):
        hm.cap_for_band(RUNS[~where(RUNS, b=0.1, cap="4", pair=2)], 0.1)
    with pytest.raises(ValueError, match="every pair needs one run at each cap"):
        hm.cap_for_band(RUNS[RUNS["cap"] != "8"], 0.1)


# ------------------------------------------------------------------------------------------- 22. rule A

CAPS_2 = dict.fromkeys(hm.BANDS, "2")


def test_rule_a_a_rate_of_exactly_1_and_fees_of_exactly_0_25_pass():
    t = put(RUNS, "rebalances_per_30d", 1.0, b=0.05, cap="2")
    t.loc[where(t, b=0.05, cap="2"), "fees_pct_per_year"] = 0.25
    r = hm.default_band(t, CAPS_2, 5000.0, "1x")
    assert (r["b_star"], r["band"], r["cap"], r["flag"]) == (0.05, 0.05, "2", None)
    assert r["bands"][0.05] == {"N": "2", "rate_median": 1.0, "fees_median": 0.25, "acceptable": True}
    faster = put(t, "rebalances_per_30d", 1.0 + 1e-12, b=0.05, cap="2", V=5000.0, cost="1x")
    assert hm.default_band(faster, CAPS_2, 500.0, "2x")["b_star"] == 0.10  # the rate comes from 5,000 USD 1x
    dearer = put(t, "fees_pct_per_year", 0.25 + 1e-12, b=0.05, cap="2", V=500.0, cost="1x")
    assert hm.default_band(dearer, CAPS_2, 500.0, "1x")["b_star"] == 0.10  # fees at the wallet size and costs
    assert hm.default_band(dearer, CAPS_2, 5000.0, "1x")["b_star"] == 0.05
    assert hm.default_band(put(t, "rebalances_per_30d", 9.0, V=500.0), CAPS_2, 500.0, "1x")["b_star"] == 0.05


def test_rule_a_the_guard_on_wider_bands_none_and_missing():
    gap = put(RUNS, "rebalances_per_30d", 2.0, b=0.3, cap="2")
    assert hm.default_band(gap, CAPS_2, 5000.0, "1x")["b_star"] == 0.5  # 0.05-0.2 pass, but 0.3 does not
    none = put(RUNS, "rebalances_per_30d", 2.0, b=0.5, cap="4")
    r = hm.default_band(none, {**CAPS_2, 0.5: "4"}, 5000.0, "1x")
    assert (r["b_star"], r["flag"], r["band"], r["cap"]) == (hm.NO_BAND, hm.NO_BAND_FLAG, 0.5, "4")
    r = hm.default_band(RUNS, {**CAPS_2, 0.05: hm.MORE_THAN_8}, 5000.0, "1x")
    assert r["b_star"] == 0.10 and r["bands"][0.05]["acceptable"] is False
    r = hm.default_band(RUNS, {**CAPS_2, 0.2: hm.MISSING}, 5000.0, "1x")
    assert (r["b_star"], r["band"], r["cap"]) == (hm.MISSING, hm.MISSING, hm.MISSING)
    failed = put(RUNS, "status", "failed", b=0.15, cap="2", V=500.0, cost="2x", pair=0)
    assert hm.default_band(failed, CAPS_2, 500.0, "2x")["b_star"] == hm.MISSING
    assert hm.default_band(failed, CAPS_2, 500.0, "1x")["b_star"] == 0.05
    with pytest.raises(ValueError, match="caps must map each band"):
        hm.default_band(RUNS, {0.05: "2"}, 5000.0, "1x")
    with pytest.raises(ValueError, match="caps must map each band"):
        hm.default_band(RUNS, {**CAPS_2, 0.1: "none"}, 5000.0, "1x")
    with pytest.raises(ValueError, match=r"cap must be one of \('0.25'"):
        hm.acceptable(RUNS, 0.1, "none", 5000.0, "1x")
    with pytest.raises(ValueError, match="the runs at 500/1x must be the pairs of 5000/1x"):
        hm.acceptable(RUNS[~where(RUNS, b=0.1, cap="2", V=500.0, cost="1x", pair=4)], 0.1, "2", 500.0, "1x")


def test_the_app_default_is_the_widest_band_over_wallet_sizes():
    defaults = [hm.default_band(RUNS, CAPS_2, book, "1x") for book in hm.BOOKS]
    app = hm.app_default(defaults)
    assert (app["b_star"], app["cap"], app["per_book_differs"]) == (0.05, "2", False)
    small = put(RUNS, "fees_pct_per_year", 0.3, V=500.0, cap="2", b=0.05)
    small.loc[where(small, V=500.0, cap="2", b=0.1), "fees_pct_per_year"] = 0.3
    app = hm.app_default([hm.default_band(small, CAPS_2, book, "1x") for book in hm.BOOKS])
    assert app["b_star"] == 0.15 and app["per_book"] == {500.0: 0.15, 5000.0: 0.05, 50000.0: 0.05}
    assert app["per_book_differs"] is True
    none = put(RUNS, "fees_pct_per_year", 0.3, V=50000.0, cap="2")
    app = hm.app_default([hm.default_band(none, CAPS_2, book, "1x") for book in hm.BOOKS])
    assert (app["b_star"], app["flag"], app["band"], app["cap"]) == (hm.NO_BAND, hm.NO_BAND_FLAG, 0.5, "2")
    missing = put(RUNS, "status", "failed", V=500.0, cost="1x", pair=1)
    assert (
        hm.app_default([hm.default_band(missing, CAPS_2, book, "1x") for book in hm.BOOKS])["b_star"]
        == hm.MISSING
    )
    with pytest.raises(ValueError, match="one cost level and one caps mapping"):
        hm.app_default([defaults[0], hm.default_band(RUNS, CAPS_2, 500.0, "2x")])


# ------------------------------------------------------------------------------------------- 22. rule C


def rule_c(runs=RUNS, limit_only=LIMIT_ONLY, book=5000.0, cost="1x", **kw):
    return hm.upper_limit(runs, limit_only, book, cost, **kw)


def test_rule_c_i_of_exactly_0_90_passes_and_the_value_test_by_hand():
    r = rule_c()
    assert r["I"]["4"] == 0.9 and r["I"]["8"] == 0.95 and r["I"]["2"] == 0.8
    assert (r["outcome"], r["N_up"], r["value_test"]) == (hm.EVIDENCE, "4", hm.SUPPORTED)
    assert r["label"] == "EVIDENCE FOR A LIMIT AT 4, value test SUPPORTED" and r["status"] == hm.STATUS
    assert r["C"]["4"] == 0.5 and r["Dist_L"] == 10.0 and r["F_L"] == 0.0 and r["held_back"] == []
    short = put(RUNS, "dist_mean", 1.0000001, cap="4")
    assert rule_c(short)["N_up"] == "8"


def test_rule_c_is_above_8_when_8_falls_short_even_if_a_tighter_cap_meets_it():
    t = put(RUNS, "dist_mean", 2.0, cap="8")  # I(8) = 0.8 < 0.9, I(4) = 0.9
    r = rule_c(t)
    assert (r["outcome"], r["N_up"], r["value_test"], r["held_back"]) == (hm.ABOVE_8, None, None, None)
    assert r["label"] == hm.ABOVE_8


@pytest.mark.parametrize("dist_l", [0.0, -1.0])
def test_rule_c_no_evidence_comes_first(dist_l):
    """Limit-only as close as unlimited rebalancing (or closer): NO EVIDENCE, though I also falls short at 8."""
    r = rule_c(put(RUNS, "dist_mean", 2.0, cap="8"), put(LIMIT_ONLY, "dist_mean", dist_l))
    assert (r["outcome"], r["N_up"], r["value_test"]) == (hm.NO_EVIDENCE, None, None)
    assert all(v is None for v in r["I"].values())


def test_rule_c_value_test_at_the_factor_2_boundary():
    fees = {"none": 10.0, "8": 9.0, "4": 8.0, "2": 6.0, "1": 4.0, "0.5": 2.0, "0.25": 1.0}
    t = RUNS.assign(fees_pct_per_year=RUNS["cap"].map(fees))
    r = rule_c(t)
    assert r["C"]["4"] == 0.8 and 1 - r["C"]["4"] == 2 * (1 - r["I"]["4"])  # exactly on the boundary: passes
    assert r["value_test"] == hm.SUPPORTED
    assert rule_c(put(t, "fees_pct_per_year", 8.000001, cap="4"))["value_test"] == hm.WEAK


@pytest.mark.parametrize("fees_l", [0.25, 0.5])
def test_rule_c_value_test_is_weak_when_unlimited_rebalancing_costs_no_more_than_limit_only(fees_l):
    r = rule_c(limit_only=put(LIMIT_ONLY, "fees_pct_per_year", fees_l))  # F(none) = 0.25: F(none) - F_L <= 0
    assert r["outcome"] == hm.EVIDENCE and all(v is None for v in r["C"].values())
    assert r["value_test"] == hm.WEAK
    assert hm._value_test(None, 0.0) == hm.WEAK and hm._value_test(0.99, None) == hm.WEAK


def test_rule_c_bands_held_back_per_band_numbers_and_gas():
    t = put(RUNS, "out_days_per_year", 100.0, b=0.5, cap="8")  # N*(0.5) = more than 8
    t.loc[where(t, b=0.3, cap="4"), "out_days_per_year"] = 100.0  # N*(0.3) = 8, above N_up = 4
    t.loc[where(t, b=0.05, cap="2"), "out_days_per_year"] = 100.0  # N*(0.05) = 4: not held back
    t.loc[where(t, b=0.05), "dist_mean"] = t.loc[where(t, b=0.05), "dist_mean"] * 0.5
    r = rule_c(t)
    assert r["N_up"] == "4" and r["held_back"] == [0.3, 0.5]
    assert r["per_band"][0.05]["I"]["2"] == 0.9 and r["per_band"][0.05]["N_up"] == "2"
    assert r["per_band"][0.1]["N_up"] == "4" and r["per_band"][0.1]["outcome"] == hm.EVIDENCE
    gas = rule_c(book=500.0, cost="2x")["gas"]
    assert gas["4"] == {"usd": 2.0, "pct": 0.4} and gas["limit-only"] == {"usd": 1.0, "pct": 0.2}
    assert rule_c()["days"] is None


def test_rule_c_days_outside_the_band_yardstick():
    bands = limit_table(bands=True)
    t = RUNS.assign(out_days_per_year=RUNS["cap"].map({c: 10.0 * v for c, v in DIST.items()}))
    days = rule_c(t, limit_only_bands=bands)["days"]
    assert days["D_out_L"] == 100.0 and days["I"]["4"] == 0.9 and days["N_up"] == "4"
    with pytest.raises(ValueError, match="limit_only_bands needs one row per band"):
        rule_c(t, limit_only_bands=bands[bands["b"] != 0.1])
    failed = put(bands, "status", "failed", b=0.1, V=5000.0, cost="1x", window=2)
    assert rule_c(t, limit_only_bands=failed)["outcome"] == hm.MISSING


def test_rule_c_missing_and_bad_tables():
    for runs, lo in (
        (put(RUNS, "status", "failed", cap="1", V=5000.0, cost="1x", pair=7), LIMIT_ONLY),
        (put(RUNS, "status", "failed", cap="1", V=500.0, cost="2x", pair=7), LIMIT_ONLY),
        (RUNS, put(LIMIT_ONLY, "status", "failed", V=5000.0, cost="1x", window=3)),
    ):
        r = rule_c(runs, lo, book=500.0, cost="2x")
        assert (r["outcome"], r["label"], r["N_up"], r["value_test"]) == (hm.MISSING, hm.MISSING, None, None)
    with pytest.raises(ValueError, match="rule C needs every band"):
        rule_c(RUNS[RUNS["b"] != 0.15])
    with pytest.raises(ValueError, match="limit-only runs of the same mixes and windows"):
        rule_c(limit_only=LIMIT_ONLY[LIMIT_ONLY["window"] != 4])
    with pytest.raises(ValueError, match="needs the same number of runs"):
        rule_c(RUNS[~where(RUNS, b=0.2, cap="8", pair=0, V=5000.0, cost="1x")])
    assert hm.outcome_label(hm.EVIDENCE, "2") == "EVIDENCE FOR A LIMIT AT 2"
    assert hm.outcome_label(hm.NO_EVIDENCE, None, hm.WEAK) == hm.NO_EVIDENCE


# ----------------------------------------------------------------------------------- 22. pools and rule E


def test_pool_selects_one_source_s_rolling_grid_runs_without_a_reset():
    other = put(
        RUNS[where(RUNS, V=5000.0, cost="1x") & (RUNS["cap"] != "none").to_numpy()], "reading", "other"
    )
    full = RUNS.assign(scope="full", window=-1)
    reset = RUNS.assign(R=365.0)
    binance = RUNS.assign(source="BINANCE")
    table = pd.concat([RUNS, other, full, reset, binance, LIMIT_ONLY], ignore_index=True)
    lab = hm.pool(table, "KRAKEN")
    cols = [c for c in RUNS.columns if c != "pair"]  # concatenating with limit-only rows makes ``pair`` float
    pd.testing.assert_frame_equal(lab[cols].reset_index(drop=True), RUNS[cols])
    o = hm.pool(table, "KRAKEN", reading="other")
    assert len(o) == len(other) + 10 * 6  # plus the lab's no-cap runs at 5,000 USD 1x as the reference
    assert set(o.loc[o["reading"] == "lab", "cap"]) == {"none"} and set(o["V"]) == {5000.0}
    assert len(hm.pool(table, "BINANCE")) == len(RUNS)
    lo = hm.limit_only_pool(table, "KRAKEN")
    pd.testing.assert_frame_equal(lo[list(LIMIT_ONLY.columns)].reset_index(drop=True), LIMIT_ONLY)
    with pytest.raises(ValueError, match="reading must be 'lab' or 'other', got 'first'"):
        hm.pool(table, "KRAKEN", reading="first")
    with pytest.raises(ValueError, match="source must be one of"):
        hm.limit_only_pool(table, "COINBASE")


def test_drop_failed_pairs_drops_every_run_of_a_pair_with_a_failure():
    table = pd.concat([RUNS, LIMIT_ONLY], ignore_index=True)
    kept, dropped = hm.drop_failed_pairs(table)
    assert dropped == [] and len(kept) == len(table)
    failed = put(table, "status", "failed", b=0.3, cap="1", V=500.0, cost="2x", s=0.5, window=3)
    failed = put(failed, "status", "failed", comparator="limit-only", s=0.2, window=0, V=50000.0)
    kept, dropped = hm.drop_failed_pairs(failed)
    assert dropped == [("KRAKEN", "rolling", 0, 0.2, 0.0), ("KRAKEN", "rolling", 3, 0.5, 0.5)]
    assert len(kept) == len(table) - 2 * (6 * 7 * 6 + 6)
    assert (kept["status"] == "ok").all()
    assert not ((kept["s"] == 0.5) & (kept["window"] == 3)).any()
    assert hm.cap_for_band(hm.pool(kept, "KRAKEN"), 0.3)["pairs"] == 8


# ----------------------------------------------------------------------------------- 22. one source, rule D


def test_decide_source_runs_rules_b_a_and_c_for_every_setting():
    bundle = hm.decide_source(RUNS, LIMIT_ONLY, limit_only_bands=limit_table(bands=True))
    settings = {"500/1x", "5000/1x", "50000/1x", "500/2x", "5000/2x", "50000/2x"}
    assert bundle["source"] == "KRAKEN" and bundle["N_star"] == dict.fromkeys(hm.BANDS, "0.25")
    assert set(bundle["rule_A"]) == set(bundle["rule_C"]) == settings
    assert set(bundle["accept"][0.1]["2"]) == settings and set(bundle["accept"][0.1]) == set(hm.FINITE_CAPS)
    assert bundle["rule_A"]["500/2x"] == hm.default_band(RUNS, bundle["N_star"], 500.0, "2x")
    assert bundle["app_default"]["1x"]["b_star"] == 0.05 and set(bundle["app_default"]) == {"1x", "2x"}
    assert bundle["rule_C"]["5000/1x"]["label"] == "EVIDENCE FOR A LIMIT AT 4, value test SUPPORTED"
    assert bundle["rule_C"]["5000/1x"]["days"] is not None
    with pytest.raises(
        ValueError, match=r"decide_source needs one source's pool, got \['BINANCE', 'KRAKEN'\]"
    ):
        hm.decide_source(RUNS, LIMIT_ONLY.assign(source="BINANCE"))


I_DEFAULT = {"none": 1.0, "8": 0.95, "4": 0.9, "2": 0.8, "1": 0.6, "0.5": 0.4, "0.25": 0.2}


def fake_bundle(
    stars, *, source="KRAKEN", acc=None, outcome=(hm.EVIDENCE, "4"), shares=None, spent=None
) -> dict:
    """A decide_source bundle from its parts: ``acc(b, cap, book, cost)`` gives acceptability (True, False or
    MISSING); rule A and the app default follow from it and ``stars`` as rule A computes them; rule C is
    ``outcome`` = (outcome, N_up) at every setting, with I = ``shares`` and C per cost level = ``spent``."""
    acc = acc or (lambda b, cap, book, cost: True)
    shares = I_DEFAULT if shares is None else shares
    spent = spent or {c: dict.fromkeys(hm.CAP_LABELS, 0.5) for c in hm.COST_LABELS}
    settings = [(book, cost) for cost in hm.COST_LABELS for book in hm.BOOKS]
    key = hm._setting
    accept = {
        b: {
            cap: {key(*setting): {"acceptable": acc(b, cap, *setting)} for setting in settings}
            for cap in hm.FINITE_CAPS
        }
        for b in hm.BANDS
    }
    rule_a = {}
    for setting in settings:
        bands = {
            b: {
                "N": stars[b],
                "acceptable": accept[b][stars[b]][key(*setting)]["acceptable"]
                if stars[b] in hm.FINITE_CAPS
                else (hm.MISSING if stars[b] == hm.MISSING else False),
            }
            for b in hm.BANDS
        }
        b_star = hm._narrowest({b: bands[b]["acceptable"] for b in hm.BANDS})
        rule_a[key(*setting)] = {
            "book": setting[0],
            "cost": setting[1],
            "b_star": b_star,
            "caps": dict(stars),
            "bands": bands,
        }
    kind, n_up = outcome
    i = dict.fromkeys(hm.CAP_LABELS) if kind in (hm.NO_EVIDENCE, hm.MISSING) else shares
    rule_c = {
        key(*setting): {
            "outcome": kind,
            "N_up": n_up,
            "I": i,
            "C": spent[setting[1]],
            "value_test": hm._value_test(i[n_up], spent[setting[1]][n_up]) if kind == hm.EVIDENCE else None,
        }
        for setting in settings
    }
    return {
        "source": source,
        "N_star": dict(stars),
        "accept": accept,
        "rule_A": rule_a,
        "app_default": {c: hm.app_default([rule_a[key(b, c)] for b in hm.BOOKS]) for c in hm.COST_LABELS},
        "rule_C": rule_c,
    }


STARS_2 = dict.fromkeys(hm.BANDS, "2")


def test_robust_on_two_identical_sources_is_robust():
    r = hm.robust(fake_bundle(STARS_2), fake_bundle(STARS_2, source="BINANCE"))
    assert r["label"] == hm.ROBUST and r["moved"] == [] and r["status"] == hm.STATUS
    assert (
        r["N_star"] == STARS_2 and r["b_star"] == dict.fromkeys(hm.BOOKS, 0.05) and r["app_default"] == 0.05
    )
    assert (r["outcome"], r["N_up"], r["value_test"]) == (hm.EVIDENCE, "4", hm.SUPPORTED)
    assert r["value_tests"] == {
        "KRAKEN 1x": "SUPPORTED",
        "KRAKEN 2x": "SUPPORTED",
        "BINANCE 1x": "SUPPORTED",
        "BINANCE 2x": "SUPPORTED",
    }
    assert r["outcome_label"] == "EVIDENCE FOR A LIMIT AT 4, value test SUPPORTED"
    assert (r["held_back"], r["conflict"], r["under_limit"], r["flag"]) == ([], False, None, None)
    assert r["headline"] == {"band": 0.05, "cap": "2"} and r["primary_check"] == {
        "conflict": False,
        "under_limit": None,
    }


def test_robust_takes_the_larger_cap_per_band():
    binance = {**STARS_2, 0.1: "4", 0.2: hm.MORE_THAN_8}
    r = hm.robust(fake_bundle(STARS_2), fake_bundle(binance, source="BINANCE"))
    assert r["N_star"] == {**STARS_2, 0.1: "4", 0.2: hm.MORE_THAN_8}
    assert r["b_star"] == dict.fromkeys(
        hm.BOOKS, 0.3
    )  # 0.2 cannot meet the conditions: the guard on wider bands
    assert r["held_back"] == [0.2] and r["label"] == hm.NOT_ROBUST
    moved = {m["value"]: m for m in r["moved"]}
    assert moved["N*(0.1)"] == {"value": "N*(0.1)", "primary": "2", "robust": "4", "settings": ["BINANCE"]}
    assert (
        moved["b*(500)"]["settings"] == ["BINANCE 1x", "BINANCE 2x"] and moved["app default"]["robust"] == 0.3
    )
    assert hm._larger_cap("2", hm.MISSING) == hm.MISSING


def test_the_robust_band_needs_both_sources_and_both_cost_levels_at_the_robust_cap():
    r = hm.robust(
        fake_bundle(STARS_2),
        fake_bundle(STARS_2, source="BINANCE", acc=lambda b, cap, bk, c: (b, c) != (0.05, "2x")),
    )
    assert r["b_star"] == dict.fromkeys(hm.BOOKS, 0.1)
    assert {m["value"]: m["settings"] for m in r["moved"]}["b*(5000)"] == ["BINANCE 2x"]
    # Kraken is acceptable at its own N*(0.05) = 2 but not at the robust 4: the robust band is read at 4
    kraken = fake_bundle(STARS_2, acc=lambda b, cap, bk, c: (b, cap) != (0.05, "4"))
    r = hm.robust(kraken, fake_bundle({**STARS_2, 0.05: "4"}, source="BINANCE"))
    assert kraken["rule_A"]["5000/1x"]["b_star"] == 0.05 and r["b_star"][5000.0] == 0.1
    two_x = fake_bundle(STARS_2, acc=lambda b, cap, bk, c: (b, c) != (0.05, "2x"))
    r = hm.robust(two_x, fake_bundle(STARS_2, source="BINANCE"))
    assert {m["value"]: m["settings"] for m in r["moved"]}["b*(50000)"] == ["KRAKEN 2x"]


@pytest.mark.parametrize(
    ("kraken", "binance", "expected", "label"),
    [
        ((hm.EVIDENCE, "2"), (hm.EVIDENCE, "4"), (hm.EVIDENCE, "4"), hm.NOT_ROBUST),
        ((hm.EVIDENCE, "8"), (hm.ABOVE_8, None), (hm.ABOVE_8, None), hm.NOT_ROBUST),
        ((hm.ABOVE_8, None), (hm.EVIDENCE, "8"), (hm.ABOVE_8, None), hm.ROBUST),
        ((hm.NO_EVIDENCE, None), (hm.NO_EVIDENCE, None), (hm.NO_EVIDENCE, None), hm.ROBUST),
        ((hm.NO_EVIDENCE, None), (hm.EVIDENCE, "2"), (hm.EVIDENCE, "2"), hm.NOT_ROBUST),
        ((hm.EVIDENCE, "1"), (hm.NO_EVIDENCE, None), (hm.EVIDENCE, "1"), hm.NOT_ROBUST),
        ((hm.MISSING, None), (hm.EVIDENCE, "1"), (hm.MISSING, None), hm.MISSING),
    ],
)
def test_the_robust_outcome_is_the_larger_and_one_source_no_evidence_is_not_robust(
    kraken, binance, expected, label
):
    r = hm.robust(
        fake_bundle(STARS_2, outcome=kraken), fake_bundle(STARS_2, source="BINANCE", outcome=binance)
    )
    assert (r["outcome"], r["N_up"]) == expected and r["label"] == label
    one = (kraken[0] == hm.NO_EVIDENCE) != (binance[0] == hm.NO_EVIDENCE) and hm.MISSING not in (
        kraken[0],
        binance[0],
    )
    assert r["one_source_no_evidence"] is one
    if one:
        assert {
            "value": "N_up",
            "primary": hm.outcome_label(*kraken),
            "robust": hm.outcome_label(*expected),
            "settings": ["one source NO EVIDENCE"],
        } in r["moved"]
    if expected[0] != hm.EVIDENCE:
        assert (r["value_test"], r["value_tests"], r["held_back"], r["conflict"]) == (None, None, None, None)


def test_the_robust_value_test_runs_at_the_robust_n_up_on_each_source():
    """Kraken's own N_up is 2, where its test is WEAK; at the robust N_up (4, Binance's) all four tests pass."""
    spent = {c: {**dict.fromkeys(hm.CAP_LABELS, 0.5), "2": 0.9} for c in hm.COST_LABELS}
    kraken = fake_bundle(STARS_2, outcome=(hm.EVIDENCE, "2"), spent=spent)
    assert kraken["rule_C"]["5000/1x"]["value_test"] == hm.WEAK
    r = hm.robust(kraken, fake_bundle(STARS_2, source="BINANCE"))
    assert (r["N_up"], r["value_test"]) == ("4", hm.SUPPORTED)
    moved = {
        "value": "value test",
        "primary": hm.WEAK,
        "robust": hm.SUPPORTED,
        "settings": ["BINANCE 1x", "BINANCE 2x"],
    }
    assert moved in r["moved"]  # Binance's own test, at its own N_up of 4, is the one that differs
    weak_2x = {"1x": dict.fromkeys(hm.CAP_LABELS, 0.5), "2x": dict.fromkeys(hm.CAP_LABELS, 0.95)}
    r = hm.robust(fake_bundle(STARS_2), fake_bundle(STARS_2, source="BINANCE", spent=weak_2x))
    assert r["value_tests"]["BINANCE 2x"] == hm.WEAK and r["value_test"] == hm.WEAK  # one of four fails
    assert {m["value"]: m["settings"] for m in r["moved"]}["value test"] == ["BINANCE 2x"]
    r = hm.robust(
        fake_bundle(STARS_2, outcome=(hm.NO_EVIDENCE, None)), fake_bundle(STARS_2, source="BINANCE")
    )
    assert r["value_tests"]["KRAKEN 1x"] == hm.WEAK and r["value_test"] == hm.WEAK  # Kraken's I is undefined


def test_conflict_when_the_default_band_needs_more_than_the_upper_limit():
    stars = {0.05: "8", 0.1: "8", 0.15: "4", 0.2: "2", 0.3: "2", 0.5: "8"}
    r = hm.robust(fake_bundle(stars), fake_bundle(stars, source="BINANCE"))
    assert (r["app_default"], r["N_up"], r["conflict"]) == (0.05, "4", True)
    assert r["held_back"] == [0.05, 0.1, 0.5]
    assert r["under_limit"] == {"b_star": 0.15, "cap": "4", "per_book": dict.fromkeys(hm.BOOKS, 0.15)}
    assert r["primary_check"]["conflict"] is True and r["primary_check"]["under_limit"] == r["under_limit"]
    # at 500 USD neither 0.2 nor 0.5 is acceptable: no band there (CONFLICT through "none"), and under the limit the
    # guard on wider candidate bands stops at 0.2, so 500 USD gets 0.3; then the widest over wallet sizes
    acc = lambda b, cap, book, cost: not (book == 500.0 and b in (0.2, 0.5))  # noqa: E731
    r = hm.robust(fake_bundle(stars, acc=acc), fake_bundle(stars, source="BINANCE"))
    assert (r["b_star"][500.0], r["app_default"], r["conflict"]) == (hm.NO_BAND, hm.NO_BAND, True)
    assert r["under_limit"]["per_book"] == {500.0: 0.3, 5000.0: 0.15, 50000.0: 0.15}
    assert r["under_limit"]["b_star"] == 0.3 and r["under_limit"]["cap"] == "2"
    tight = {**stars, 0.15: "8", 0.2: "8", 0.3: "8"}  # no band has N* <= 4
    r = hm.robust(fake_bundle(tight), fake_bundle(tight, source="BINANCE"))
    assert r["under_limit"] == {
        "b_star": hm.NO_BAND,
        "cap": None,
        "per_book": dict.fromkeys(hm.BOOKS, hm.NO_BAND),
    }


def test_conflict_when_no_band_meets_the_conditions_and_none_without_a_numeric_limit():
    stars = {**STARS_2, 0.5: hm.MORE_THAN_8}  # 0.50 cannot be acceptable: no band
    r = hm.robust(fake_bundle(stars), fake_bundle(stars, source="BINANCE"))
    assert (r["app_default"], r["flag"], r["conflict"]) == (hm.NO_BAND, hm.NO_BAND_FLAG, True)
    assert r["headline"] == {"band": 0.5, "cap": "none"}  # no cap when N*_rob(0.50) is "more than 8"
    no = dict.fromkeys(hm.BANDS, "4")
    r = hm.robust(fake_bundle(no, acc=lambda b, *a: b != 0.5), fake_bundle(no, source="BINANCE"))
    assert r["headline"] == {"band": 0.5, "cap": "4"} and r["conflict"] is True
    r = hm.robust(
        fake_bundle(STARS_2, outcome=(hm.ABOVE_8, None)),
        fake_bundle(STARS_2, source="BINANCE", outcome=(hm.ABOVE_8, None)),
    )
    assert (r["conflict"], r["under_limit"], r["primary_check"]["conflict"]) == (None, None, None)


def test_the_primary_check_uses_kraken_at_1x_and_its_own_n_up():
    eights = dict.fromkeys(hm.BANDS, "8")
    r = hm.robust(fake_bundle(STARS_2), fake_bundle(eights, source="BINANCE"))
    assert r["conflict"] is True and r["primary_check"] == {"conflict": False, "under_limit": None}
    r = hm.robust(fake_bundle(eights, outcome=(hm.EVIDENCE, "2")), fake_bundle(STARS_2, source="BINANCE"))
    assert r["N_up"] == "4" and r["conflict"] is True  # robust: N*_rob = 8 > 4
    assert (
        r["primary_check"]["conflict"] is True and r["primary_check"]["under_limit"]["b_star"] == hm.NO_BAND
    )


def test_the_robust_label_compares_the_default_under_the_limit():
    """Everything else equal (N*, b*, the app default 0.15, N_up 4, the value test, CONFLICT on both), but Binance
    refuses 0.05: under the limit the primary values give 0.05 (Kraken alone) and the robust ones 0.2. The label is
    NOT ROBUST and names the moved value (amendment A6)."""
    stars = {0.05: "2", 0.1: "8", 0.15: "8", 0.2: "2", 0.3: "2", 0.5: "8"}
    kraken = fake_bundle(stars, acc=lambda b, cap, book, cost: b != 0.1)
    binance = fake_bundle(stars, source="BINANCE", acc=lambda b, cap, book, cost: b not in (0.05, 0.1))
    r = hm.robust(kraken, binance)
    assert (r["app_default"], kraken["app_default"]["1x"]["b_star"], r["N_up"]) == (0.15, 0.15, "4")
    assert r["conflict"] is True and r["primary_check"]["conflict"] is True
    assert r["primary_check"]["under_limit"]["b_star"] == 0.05 and r["under_limit"]["b_star"] == 0.2
    assert r["label"] == hm.NOT_ROBUST
    assert r["moved"] == [
        {
            "value": "default under the limit",
            "primary": (0.05, "2"),
            "robust": (0.2, "2"),
            "settings": ["rule D, acceptable on both sources at both cost levels"],
        }
    ]
    # the same sources without Binance's refusal: equal, ROBUST
    same = hm.robust(kraken, fake_bundle(stars, source="BINANCE", acc=lambda b, cap, book, cost: b != 0.1))
    assert same["label"] == hm.ROBUST and same["moved"] == []
    # a CONFLICT flag that differs is named too (here with the values it comes from)
    eights = dict.fromkeys(hm.BANDS, "8")
    r = hm.robust(fake_bundle(STARS_2), fake_bundle(eights, source="BINANCE"))
    moved = {m["value"]: m for m in r["moved"]}
    assert moved["CONFLICT"] == {
        "value": "CONFLICT",
        "primary": False,
        "robust": True,
        "settings": ["rule D, from the values above"],
    }


def test_robust_with_a_missing_acceptability_is_missing():
    acc = lambda b, cap, book, cost: hm.MISSING if (book, cost) == (500.0, "1x") else True  # noqa: E731
    r = hm.robust(fake_bundle(STARS_2, acc=acc), fake_bundle(STARS_2, source="BINANCE"))
    assert r["b_star"][500.0] == hm.MISSING and r["app_default"] == hm.MISSING and r["conflict"] == hm.MISSING
    assert r["label"] == hm.MISSING and r["headline"] == {"band": hm.MISSING, "cap": hm.MISSING}
    missing = fake_bundle({**STARS_2, 0.1: hm.MISSING}, outcome=(hm.MISSING, None))
    r = hm.robust(missing, fake_bundle(STARS_2, source="BINANCE"))
    assert r["N_star"][0.1] == hm.MISSING and r["outcome"] == hm.MISSING and r["label"] == hm.MISSING


def test_robust_end_to_end_from_two_runs_tables():
    kraken = hm.decide_source(RUNS, LIMIT_ONLY)
    binance = hm.decide_source(RUNS.assign(source="BINANCE"), LIMIT_ONLY.assign(source="BINANCE"))
    r = hm.robust(kraken, binance)
    assert r["label"] == hm.ROBUST and r["headline"] == {"band": 0.05, "cap": "0.25"}
    assert r["outcome_label"] == "EVIDENCE FOR A LIMIT AT 4, value test SUPPORTED"
    slower = put(RUNS, "out_days_per_year", 100.0, b=0.05, cap="2").assign(source="BINANCE")
    r = hm.robust(kraken, hm.decide_source(slower, LIMIT_ONLY.assign(source="BINANCE")))
    assert r["N_star"][0.05] == "4" and r["label"] == hm.NOT_ROBUST
    assert {m["value"]: m["settings"] for m in r["moved"]}["N*(0.05)"] == ["BINANCE"]


# -------------------------------------------------------------------------------------- 22. descriptions


def described_table() -> tuple[pd.DataFrame, pd.DataFrame]:
    runs = runs_table(mixes=hm.MIXES, windows=(0, 12, 13))
    other = runs[where(runs, V=5000.0, cost="1x") & (runs["cap"] != "none").to_numpy()].copy()
    other["reading"] = "other"
    other.loc[other["cap"] == "8", "out_days_per_year"] = 100.0  # the other reading: N* = more than 8
    lab_slow = put(runs, "out_days_per_year", 100.0, cap="0.25", window=0)  # window 0 (2017) is busier
    return pd.concat([lab_slow, other], ignore_index=True), limit_table(mixes=hm.MIXES, windows=(0, 12, 13))


def test_descriptions_other_reading_limit_readings_and_years():
    runs, lo = described_table()
    d = hm.descriptions(runs, lo)["KRAKEN"]
    assert d["other_reading"]["N_star"] == dict.fromkeys(hm.BANDS, hm.MORE_THAN_8)
    assert d["other_reading"]["rule_A"]["b_star"] == hm.NO_BAND
    assert d["limit_readings"]["cash"]["mixes"] == 12 and d["limit_readings"]["together"]["mixes"] == 20
    cash = d["limit_readings"]["cash"]["decisions"]
    kept = runs[(runs["reading"] == "lab").to_numpy() & (runs["s"] >= 0.42).to_numpy()]
    assert cash["N_star"] == hm.decide_source(kept, lo[lo["s"] >= 0.42])["N_star"]
    assert set(d["years"][0.1]) == {2017, 2018}
    assert d["years"][0.1][2017]["0.25"]["median"] == 100.0 and d["years"][0.1][2018]["0.25"]["median"] == 0.0
    assert d["non_overlapping_windows"] == [0, 12]
    assert d["non_overlapping"][0.1]["0.25"] == {
        "median": 50.0,
        "p90": 100.0,
        "passes": False,
    }  # 27 x 100, 27 x 0


def test_descriptions_without_the_other_reading_or_non_overlapping_windows_and_with_failures():
    runs, lo = runs_table(windows=(1, 2, 3)), limit_table(windows=(1, 2, 3))
    d = hm.descriptions(runs, lo, limit_only_bands=limit_table(windows=(1, 2, 3), bands=True))["KRAKEN"]
    assert (
        d["other_reading"] is None
        and d["non_overlapping"][0.1] is None
        and d["non_overlapping_windows"] == []
    )
    assert d["limit_readings"]["cash"]["decisions"]["rule_C"]["5000/1x"]["days"] is not None
    failed = put(runs, "status", "failed", b=0.2, V=5000.0, cost="1x", window=2, s=0.5)
    d = hm.descriptions(failed, lo)["KRAKEN"]
    assert d["years"][0.2] == hm.MISSING and d["non_overlapping"][0.2] == hm.MISSING
    both = hm.descriptions(
        pd.concat([runs, runs.assign(source="BINANCE")]), pd.concat([lo, lo.assign(source="BINANCE")])
    )
    assert list(both) == ["KRAKEN", "BINANCE"]


# ------------------------------------------------------------------------------------------- 22. falls

FALL_MIXES = ((0.5, 0.5), (0.5, 0.25), (0.2, 0.0))
HEADLINE = {"band": 0.2, "cap": "2"}


def falls_runs() -> pd.DataFrame:
    """Rolling runs (3 windows) and full runs (with and without the yearly reset) at 5,000 USD 1x, plus rows the
    falls must ignore: another wallet size, 2x, the other reading and limit-only, each with a deeper fall."""
    rows = []
    for s, f in FALL_MIXES:
        for b in hm.BANDS:
            for cap in hm.CAP_LABELS:
                for scope, k, reset in [
                    ("rolling", 0, math.nan),
                    ("rolling", 1, math.nan),
                    ("rolling", 2, math.nan),
                    ("full", -1, math.nan),
                    ("full", -1, 365.0),
                ]:
                    rows.append(
                        {
                            "source": "KRAKEN",
                            "scope": scope,
                            "window": k,
                            "comparator": "grid",
                            "reading": "lab",
                            "s": s,
                            "f": f,
                            "b": b,
                            "cap": cap,
                            "R": reset,
                            "V": 5000.0,
                            "cost": "1x",
                            "status": "ok",
                            "max_drawdown": -0.1,
                            "mdd_peak": utc("2018-01-01"),
                            "mdd_trough": utc("2018-02-01"),
                            "worst_day": -0.05,
                            "worst_day_close": utc("2020-03-13"),
                            "worst_week": -0.1,
                            "worst_week_start": utc("2020-03-06"),
                            "worst_week_end": utc("2020-03-13"),
                            "first_close": utc("2017-01-02") + pd.DateOffset(months=k),
                            "last_close": utc("2018-01-01"),
                        }
                    )
    t = pd.DataFrame(rows)
    head = where(t, b=0.2, cap="2")
    for (s, f), dd in zip(
        FALL_MIXES, ([-0.1, -0.4, -0.2], [-0.3, -0.3, -0.05], [-0.05, -0.06, -0.07]), strict=True
    ):
        for k, v in enumerate(dd):
            t.loc[head & where(t, s=s, f=f, scope="rolling", window=k), "max_drawdown"] = v
    t.loc[where(t, s=0.5, f=0.5, b=0.05, cap="none", window=2, scope="rolling"), "max_drawdown"] = -0.6
    t.loc[
        where(t, s=0.5, f=0.5, b=0.1, cap="8", window=0, scope="rolling"), "max_drawdown"
    ] = -0.6  # a later tie
    full = head & where(t, scope="full")
    t.loc[full & t["R"].isna().to_numpy() & where(t, f=0.25), ["max_drawdown", "worst_day", "worst_week"]] = (
        -0.5,
        -0.15,
        -0.25,
    )
    t.loc[full & where(t, R=365.0, f=0.5), "max_drawdown"] = -0.45
    t.loc[full & t["R"].isna().to_numpy() & where(t, f=0.25), "mdd_trough"] = utc("2018-12-15")
    ignored = [
        t.assign(V=500.0),
        t.assign(cost="2x"),
        t.assign(reading="other"),
        t.assign(comparator="limit-only"),
    ]
    deeper = pd.concat(ignored, ignore_index=True).assign(
        max_drawdown=-0.99, worst_day=-0.99, worst_week=-0.99
    )
    return pd.concat([t, deeper], ignore_index=True)


def test_falls_tables_by_crypto_share_with_positive_sizes_and_the_worst_window_named():
    table = hm.falls_tables(falls_runs(), HEADLINE)
    assert list(table.columns) == list(hm.FALLS_COLUMNS)
    assert list(zip(table["level"], table["s"], table["f"].fillna(-1.0), strict=True)) == [
        ("share", 0.2, -1.0),
        ("mix", 0.2, 0.0),
        ("share", 0.5, -1.0),
        ("mix", 0.5, 0.25),
        ("mix", 0.5, 0.5),
    ]
    assert (
        (table["label"] == hm.LABEL).all()
        and (table["note"] == hm.FALLS_NOTE).all()
        and not table["missing"].any()
    )
    mix = table.set_index(["level", "s", "f"]).loc["mix"]
    # the worst window: the minimum of the signed number, not its median (20%) or 90th percentile (12%)
    assert mix.loc[(0.5, 0.5), ["window_fall_pct", "window_k"]].tolist() == [40.0, 1]
    assert mix.loc[(0.5, 0.25), ["window_fall_pct", "window_k"]].tolist() == [
        30.0,
        0,
    ]  # a tie: the first window
    assert mix.loc[(0.5, 0.5), "window_first"] == utc("2017-02-02")
    assert mix.loc[(0.5, 0.5), ["grid_fall_pct", "grid_b", "grid_cap", "grid_k"]].tolist() == [
        60.0,
        0.05,
        "none",
        2,
    ]
    assert mix.loc[
        (0.5, 0.25), ["full_fall_pct", "full_trough", "worst_day_pct", "worst_week_pct"]
    ].tolist() == [50.0, utc("2018-12-15"), 15.0, 25.0]
    assert mix.loc[(0.5, 0.5), "full_reset_fall_pct"] == pytest.approx(45.0)
    share = table[(table["level"] == "share") & (table["s"] == 0.5)].iloc[0]
    assert (share["window_fall_pct"], share["window_f"], share["window_k"]) == (40.0, 0.5, 1)
    assert (share["full_fall_pct"], share["full_f"], share["full_reset_f"]) == (50.0, 0.25, 0.5)
    assert (share["worst_day_pct"], share["worst_day_f"], share["grid_f"]) == (15.0, 0.25, 0.5)
    low = table[(table["level"] == "share") & (table["s"] == 0.2)].iloc[0]
    assert (low["window_fall_pct"], low["window_k"], low["window_f"]) == (pytest.approx(7.0), 2, 0.0)


def test_a_tie_between_mixes_of_one_share_names_the_first_f():
    """(0.5, 0.25)'s window 2 set to -0.4 at the headline ties (0.5, 0.5)'s worst, -0.4 in window 1: the share row
    names the first f in grid order, 0.25, and its window. #52"""
    t = falls_runs()
    head = where(t, b=0.2, cap="2")
    t.loc[head & where(t, s=0.5, f=0.25, scope="rolling", window=2), "max_drawdown"] = -0.4
    table = hm.falls_tables(t, HEADLINE)
    share = table[(table["level"] == "share") & (table["s"] == 0.5)].iloc[0]
    assert (share["window_fall_pct"], share["window_f"], share["window_k"]) == (40.0, 0.25, 2)


def test_falls_tables_mark_missing_rows_and_refuse_a_bad_headline():
    runs = falls_runs()
    failed = put(
        runs,
        "status",
        "failed",
        s=0.5,
        f=0.25,
        b=0.3,
        cap="1",
        window=1,
        V=5000.0,
        reading="lab",
        comparator="grid",
        cost="1x",
    )
    table = hm.falls_tables(failed, HEADLINE)
    by_row = dict(
        zip(
            zip(table["level"], table["s"], table["f"].fillna(-1.0), strict=True),
            table["missing"],
            strict=True,
        )
    )
    assert by_row == {
        ("share", 0.2, -1.0): False,
        ("mix", 0.2, 0.0): False,
        ("share", 0.5, -1.0): True,
        ("mix", 0.5, 0.25): True,
        ("mix", 0.5, 0.5): False,
    }
    assert table.loc[table["missing"], "window_fall_pct"].isna().all()
    lacking = runs[~where(runs, s=0.2, scope="full", R=365.0)]
    assert hm.falls_tables(lacking, HEADLINE).set_index("level").loc["mix"].query("s == 0.2")["missing"].all()
    with pytest.raises(ValueError, match=r"headline cap must be one of"):
        hm.falls_tables(runs, {"band": 0.2, "cap": "3"})
    with pytest.raises(ValueError, match="band must be one of the grid bands"):
        hm.falls_tables(runs, {"band": 0.25, "cap": "2"})


# -------------------------------------------------------------------------- 23. the boom-year addendum (A5)


def test_year_returns_by_bar_day_from_the_last_bar_of_the_year_before():
    """Closes 2019-12-31 .. 2021-01-02 with 2021-01-01 missing: 2019 holds closes 2019-12-31 and 2020-01-01 (bar
    days 30 and 31 December) and starts at its own first bar (no 2018 bar); 2020 ends on its last bar, close
    2020-12-31, because 2021-01-01 is missing; 2021 (close 2021-01-02) starts from that bar."""
    n = 368
    btc = [100.0 + i + (i % 7) for i in range(n)]
    panel = path_panel(btc, flat(n), start="2019-12-31", skip=(367,))
    c = panel[("BTC", "close")]
    assert utc("2021-01-01") not in panel.index and panel.index[-1] == utc("2021-01-02")
    want = {
        2019: c[utc("2020-01-01")] / c[utc("2019-12-31")] - 1.0,
        2020: c[utc("2020-12-31")] / c[utc("2020-01-01")] - 1.0,
        2021: c[utc("2021-01-02")] / c[utc("2020-12-31")] - 1.0,
    }
    assert hm.year_returns(panel) == want
    eth = hm.year_returns(panel, "ETH")
    assert eth == dict.fromkeys(want, 0.0)
    assert hm.bar_years(pd.DatetimeIndex([utc("2021-01-01"), utc("2021-01-02")])).tolist() == [2020, 2021]


def test_the_best_years_are_ranked_largest_first_with_ties_to_the_earlier_year():
    r = {2017: 0.5, 2018: -0.7, 2019: 0.9, 2020: 0.9, 2021: 0.6, 2022: -0.6}
    assert hm.best_years(r, 1) == [2019] and hm.best_years(r, 2) == [2019, 2020] and hm.best_years(r, 3)[2] == 2021
    for bad in (0, 7, True):
        with pytest.raises(ValueError):
            hm.best_years(r, bad)
    with pytest.raises(ValueError, match="finite yearly returns"):
        hm.best_years({**r, 2018: math.nan}, 1)


def test_windows_overlap_a_year_when_one_of_their_months_is_in_it():
    """By hand (A5's examples), and against the calendar: a window overlaps Y exactly when one of its bars (close
    minus 1 day, section 6) falls in Y."""
    kraken = [k for k, _, _ in hm.rolling_windows("KRAKEN")]
    binance = [k for k, _, _ in hm.rolling_windows("BINANCE")]
    assert hm.windows_without(kraken, [2017]) == hm.windows_without(binance, [2017]) == list(range(12, 60))
    assert hm.windows_without(kraken, [2020]) == [*range(0, 25), *range(48, 60)]
    assert hm.windows_without(binance, [2020]) == [*range(8, 25), *range(48, 60)]
    assert hm.windows_without(kraken, [2022]) == list(range(0, 49))
    assert hm.windows_without(binance, [2019, 2021]) == [8, 9, 10, 11, 12, 36]
    assert hm.windows_without(kraken, [2017, 2020]) == [*range(12, 25), *range(48, 60)]
    for k, first, last in hm.rolling_windows("KRAKEN"):
        years = set(hm.bar_years(pd.date_range(first, last, freq="D")).tolist())
        for y in hm.TRAIN_YEARS:
            assert hm.overlaps(k, y) is (y in years), (k, y)
    assert not hm.overlaps(0, 2018) and hm.overlaps(1, 2018) and hm.overlaps(59, 2022) and not hm.overlaps(36, 2021)


KRAKEN_K = tuple(range(60))
BINANCE_K = tuple(range(8, 60))
BOOM_RETURNS = {2017: 13.0, 2018: -0.73, 2019: 0.95, 2020: 3.0, 2021: 0.6, 2022: -0.64}  # made-up numbers


def test_the_boom_plan_removes_each_year_then_the_best_ones():
    plan = hm.boom_plan(BOOM_RETURNS, {"KRAKEN": KRAKEN_K, "BINANCE": BINANCE_K})
    assert [(e["name"], e["years"]) for e in plan] == [
        *((str(y), [y]) for y in hm.TRAIN_YEARS),
        ("best 1", [2017]),
        ("best 2", [2017, 2020]),
    ]
    assert all(e["status"] == hm.OK and e["reason"] is None for e in plan)
    kept = {e["name"]: {s: len(ks) for s, ks in e["windows"].items()} for e in plan}
    assert kept == {
        "2017": {"KRAKEN": 48, "BINANCE": 48},
        "2018": {"KRAKEN": 37, "BINANCE": 36},
        "2019": {"KRAKEN": 37, "BINANCE": 29},
        "2020": {"KRAKEN": 37, "BINANCE": 29},
        "2021": {"KRAKEN": 37, "BINANCE": 29},
        "2022": {"KRAKEN": 49, "BINANCE": 41},
        "best 1": {"KRAKEN": 48, "BINANCE": 48},
        "best 2": {"KRAKEN": 25, "BINANCE": 25},
    }
    # 2019 and 2021 as the best two leave Binance 6 windows: MISSING, with the reason
    other = {**BOOM_RETURNS, 2017: 0.1, 2019: 5.0, 2020: 0.2, 2021: 4.0}
    best2 = hm.boom_plan(other, {"KRAKEN": KRAKEN_K, "BINANCE": BINANCE_K})[-1]
    assert best2["years"] == [2019, 2021] and best2["windows"]["BINANCE"] == [8, 9, 10, 11, 12, 36]
    assert best2["status"] == hm.MISSING and best2["reason"] == "fewer than 12 windows kept: {'BINANCE': 6}"
    six = hm.boom_plan(other, {"KRAKEN": KRAKEN_K, "BINANCE": BINANCE_K}, min_windows=6)[-1]
    assert six["status"] == hm.OK  # exactly the minimum is enough
    with pytest.raises(ValueError, match="min_windows must be an integer >= 1"):
        hm.boom_plan(BOOM_RETURNS, {"KRAKEN": KRAKEN_K, "BINANCE": BINANCE_K}, min_windows=0)
    with pytest.raises(ValueError, match=r"no yearly return for \[2022\]"):
        hm.boom_removals({y: r for y, r in BOOM_RETURNS.items() if y != 2022})


def test_boom_compare_names_each_headline_value_it_keeps():
    head = hm.robust(fake_bundle(STARS_2), fake_bundle(STARS_2, source="BINANCE"))
    same = hm.boom_compare(head, head)
    assert list(same) == [
        *(f"N*({b:g})" for b in hm.BANDS),
        "b*(500)",
        "b*(5000)",
        "b*(50000)",
        "app default",
        "N_up",
        "value test",
        "CONFLICT",
        "all",
    ]
    assert all(v is True for v in same.values())
    moved = hm.robust(fake_bundle({**STARS_2, 0.1: "4"}), fake_bundle(STARS_2, source="BINANCE"))
    got = hm.boom_compare(head, moved)
    assert got["N*(0.1)"] is False and got["all"] is False and got["N*(0.05)"] is True
    no_limit = hm.robust(
        fake_bundle(STARS_2, outcome=(hm.ABOVE_8, None)),
        fake_bundle(STARS_2, source="BINANCE", outcome=(hm.ABOVE_8, None)),
    )
    got = hm.boom_compare(head, no_limit)
    assert (got["N_up"], got["value test"], got["CONFLICT"], got["app default"]) == (False, False, False, True)
    acc = lambda b, cap, book, cost: hm.MISSING if (book, cost) == (500.0, "1x") else True  # noqa: E731
    missing = hm.robust(fake_bundle(STARS_2, acc=acc), fake_bundle(STARS_2, source="BINANCE"))
    got = hm.boom_compare(head, missing)
    assert got["b*(500)"] == hm.MISSING and got["CONFLICT"] == hm.MISSING and got["all"] == hm.MISSING
    assert got["N*(0.05)"] is True and got["b*(5000)"] is True
