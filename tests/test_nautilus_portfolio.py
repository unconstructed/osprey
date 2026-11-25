"""The multi-asset NautilusTrader runner (``lab/runner/nautilus_portfolio.py``; milestone 3).

- **parity** with ``lab/runner/portfolio.py``: ``rebalance`` and ``random_rebalance`` on drawn panels with moving
  prices at three cost models, and ``holdmix.hold_mix`` and ``trend.trend_backtest`` (plain and with the stop), to
  ``nautilus.TOL`` on every column, order by order and leg by leg;
- **tamper-the-future** and **accounting** against ``tests/test_portfolio.py::unit_book``, on the Nautilus book;
- the documented differences (TESTING.md #65): round-off legs of either coin are not sent (no gas); a coin at its
  target to round-off while the other trades is re-cut at no cost, as portfolio.py's pro-rata fees do;
- full sells of either coin leave exactly 0 units (the sell cap, #62); a full buy of both coins never overdraws;
- refusals: an unpayable fill raises portfolio.py's message; bad params and panels raise before the engine and
  every rule module gets its engine back; a function that is not a portfolio rule is refused;
- ``wrap`` pickles and runs in a 2-worker ``run_study``.
"""

from __future__ import annotations

import functools
import pickle

import numpy as np
import pandas as pd
import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from lab.costs import fees
from lab.runner import holdmix as hm
from lab.runner import nautilus_portfolio as npf
from lab.runner import portfolio as pf
from lab.runner import reference
from lab.runner import trend as tr
from lab.runner.interface import validate_result
from lab.runner.reference import Costs
from tests.test_portfolio import (
    ALL_COLUMNS,
    REFUSAL,
    SPECS,
    fill_bars_of,
    random_panel,
    tamper_from,
    target_of,
    unit_book,
)

TOL = npf.TOL
COST_MODELS = (
    Costs(),
    Costs().stressed(),
    Costs(pool_fee_bps=30.0, aggregator_fee_bps=10.0, gas_usd_per_trade=2.5),
)
LOOSE = {"min_cash": 0.0, "max_coin": 1.0}  # trend executor limits that let a hand-built test use any targets


@st.composite
def moving_panels(draw, min_size: int = 20, max_size: int = 150) -> pd.DataFrame:
    """Moving prices only: on flat prices portfolio.py trades round-off legs this runner does not send (#65)."""
    n = draw(st.integers(min_size, max_size))
    seed = draw(st.integers(0, 2**32 - 1))
    vols = tuple(draw(st.sampled_from([0.01, 0.04, 0.1])) for _ in pf.ASSETS)
    gaps = tuple(draw(st.sampled_from([0.0, 0.005, 0.03])) for _ in pf.ASSETS)
    return random_panel(n, seed, vols, gaps)


@st.composite
def targets(draw) -> tuple[float, float]:
    """Each target 0 or at least 0.001 (the study grids start at 0.05). A target of round-off size is a round-off
    leg, which this runner does not send and portfolio.py pays gas for (#65 (b);
    test_a_target_of_round_off_size_is_not_bought)."""
    weight = st.one_of(st.just(0.0), st.sampled_from([0.25, 0.4, 0.5, 0.6, 1.0]), st.floats(0.001, 1.0))
    w_btc = draw(weight)
    w_eth = draw(st.one_of(st.just(0.0), st.just(1.0 - w_btc), st.floats(0.001, 1.0)))
    assume(w_btc + w_eth <= 1.0 and (w_eth == 0.0 or w_eth >= 0.001))
    return w_btc, w_eth


@st.composite
def rebalance_params(draw) -> dict:
    """``tests/test_portfolio.py``'s draw of rebalance params, on these targets."""
    w_btc, w_eth = draw(targets())
    params = {
        "w_btc": w_btc,
        "w_eth": w_eth,
        "band": draw(st.sampled_from([0.0, 0.005, 0.02, 0.1, 1.0])),
        "every": draw(st.integers(1, 10)),
    }
    slack = st.one_of(st.sampled_from([0.0, 0.005, 0.02, 0.05]), st.floats(0.0, 1.0))
    if draw(st.booleans()):
        params["min_cash"] = max(0.0, 1.0 - (w_btc + w_eth) - draw(slack))
    if draw(st.booleans()):
        params["max_coin"] = min(1.0, max(w_btc, w_eth) + draw(slack))
    return params


@st.composite
def cases(draw):
    panel = draw(moving_panels())
    if draw(st.booleans()):
        return panel, pf.rebalance, draw(rebalance_params())
    w_btc, w_eth = draw(targets())
    params = {
        "w_btc": w_btc,
        "w_eth": w_eth,
        "n_rebalances": draw(st.integers(0, min(15, len(panel) - 2))),
        "seed": draw(st.integers(0, 2**16)),
    }
    return panel, pf.random_rebalance, params


def assert_parity(ref: pd.DataFrame, nt: pd.DataFrame) -> None:
    """Same orders, fills and legs; every column, leg size (as a share of its V_open), leg cost and trade return
    within TOL."""
    n = len(ref)
    # Orders: Nautilus may list extra closes where the rule saw its fixed-point leftover cash and ordered, and that
    # order filled nothing (#65 (d)); every order of portfolio.py is Nautilus's too.
    extra = sorted(set(nt.attrs["orders"].tolist()) - set(ref.attrs["orders"].tolist()))
    assert set(ref.attrs["orders"].tolist()) <= set(nt.attrs["orders"].tolist())
    assert not set(t + 1 for t in extra) & set(nt.attrs["fills"]["bar"].tolist()), extra
    assert nt.attrs["n_trades"] == ref.attrs["n_trades"]
    assert nt.attrs["snapshot_id"] == ref.attrs["snapshot_id"]
    np.testing.assert_allclose(nt[ALL_COLUMNS].to_numpy(), ref[ALL_COLUMNS].to_numpy(), rtol=0, atol=TOL)
    np.testing.assert_allclose(nt.attrs["trade_returns"], ref.attrs["trade_returns"], rtol=TOL * n, atol=TOL)
    a, b = nt.attrs["fills"], ref.attrs["fills"]
    assert list(a["bar"]) == list(b["bar"]) and list(a["asset"]) == list(b["asset"])
    np.testing.assert_array_equal(a["price"].to_numpy(), b["price"].to_numpy())
    np.testing.assert_array_equal(a["weight_after"].to_numpy(), b["weight_after"].to_numpy())
    np.testing.assert_allclose(a["weight_before"].to_numpy(), b["weight_before"].to_numpy(), rtol=0, atol=TOL)
    real = (
        b["weight_after"] - b["weight_before"]
    ).abs().to_numpy() > TOL  # a round-off leg's side is round-off
    assert list(a["side"][real]) == list(b["side"][real])
    scale = b["usd"].to_numpy() / np.maximum(
        np.abs(b["weight_after"] - b["weight_before"]).to_numpy(), 1e-300
    )
    for col in ("usd", "cost"):
        np.testing.assert_allclose(
            a[col].to_numpy(), b[col].to_numpy(), rtol=TOL, atol=TOL * scale.max(initial=1)
        )
    usd = nt.attrs["fills_usd"]
    assert list(usd["asset"]) == list(a["asset"])
    np.testing.assert_allclose(usd["commission_usd"].to_numpy(), a["cost"].to_numpy(), rtol=0, atol=1e-9)
    assert np.prod(1.0 + nt["ret"].to_numpy()) == pytest.approx(
        np.prod(1.0 + ref["ret"].to_numpy()), rel=TOL * n
    )


def both(rule, params, panel, costs):
    """``(reference result, Nautilus result)``; an unpayable fill must raise the same message on both."""
    try:
        ref = rule(params, panel, costs)
    except ValueError as exc:
        assert REFUSAL.fullmatch(str(exc)), exc
        with pytest.raises(ValueError) as nt_err:
            npf.run(rule, params, panel, costs)
        assert str(nt_err.value) == str(exc)
        return None, None
    return ref, npf.run(rule, params, panel, costs)


# ------------------------------------------------------------------------------------------------ parity


@settings(deadline=None)
@given(case=cases(), costs=st.sampled_from(COST_MODELS))
def test_nautilus_equals_portfolio_on_drawn_panels(case, costs):
    panel, rule, params = case
    ref, nt = both(rule, params, panel, costs)
    if ref is None:
        return
    validate_result(nt, panel)
    assert_parity(ref, nt)
    if rule is pf.random_rebalance:
        np.testing.assert_array_equal(nt.attrs["rebalance_closes"], ref.attrs["rebalance_closes"])


@pytest.mark.parametrize(
    "params",
    [
        {"w_btc": 0.5, "w_eth": 0.5, "band": 0.05, "every": 1},
        {"w_btc": 0.35, "w_eth": 0.25, "band": 0.03, "every": 7, "min_cash": 0.2, "max_coin": 0.6},
        {"w_btc": 1.0, "w_eth": 0.0, "band": 0.0, "every": 1},
        {"w_btc": 0.0, "w_eth": 1.0, "band": 0.1, "every": 30},
    ],
)
@pytest.mark.parametrize("stress", [1.0, 2.0])
def test_parity_on_the_synthetic_market_with_the_config_costs(market, params, stress):
    panel = pf.make_panel(market, snapshot_id="synthetic-21")
    costs = Costs.from_yaml().stressed(stress)
    ref, nt = both(pf.rebalance, params, panel, costs)
    assert ref.attrs["n_trades"] > 0
    assert_parity(ref, nt)


def test_hold_mix_runs_on_nautilus_with_its_own_attrs():
    panel = random_panel(400, 9, (0.03, 0.04), (0.005, 0.005))
    costs = Costs.from_yaml()
    p = {
        "w_btc": 0.35,
        "w_eth": 0.2,
        "band": 0.2,
        "wait_days": 15,
        "min_cash": 0.2,
        "max_coin": 0.6,
        "headroom": 0.02,
        "reset_days": 120,
    }
    ref, nt = hm.hold_mix(p, panel, costs), npf.run(hm.hold_mix, p, panel, costs)
    assert ref.attrs["n_trades"] > 2
    assert_parity(ref, nt)
    for key in ("reasons", "in_wait", "held"):
        np.testing.assert_array_equal(nt.attrs[key], ref.attrs[key])


@pytest.mark.parametrize("stop", [None, 0.1])
def test_trend_runs_on_nautilus_with_its_own_attrs(stop):
    panel = random_panel(400, 9, (0.03, 0.04), (0.005, 0.005))
    costs = Costs.from_yaml()
    limits = {"min_cash": 0.2, "max_coin": 0.6}
    p = {"lookback": 20, "buffer": 0.02, "crypto_share": 0.5, **({} if stop is None else {"stop": stop})}
    ref = tr.trend_backtest(p, panel, limits=limits, costs=costs)
    nt = npf.run(tr.trend_backtest, p, panel, limits=limits, costs=costs)
    assert ref.attrs["n_trades"] > 2
    assert_parity(ref, nt)
    for key in ("reasons", "order_hash", "state_hash"):
        np.testing.assert_array_equal(nt.attrs[key], ref.attrs[key])


# ------------------------------------------------------------------------------- no look-ahead, accounting


@settings(deadline=None)
@given(case=cases(), cut_at=st.floats(0.2, 0.9), seed=st.integers(0, 2**16))
def test_no_look_ahead(case, cut_at, seed):
    """Every field of both coins changed from bar ``cut`` on, except the opens of ``cut`` (the fill prices of the
    decision at close cut - 1): every row before ``cut``, every order before it and the legs that fill at its open
    are unchanged, bit for bit."""
    panel, rule, params = case
    cut = max(1, int(len(panel) * cut_at))
    tampered = tamper_from(panel, cut, seed)
    a, b = npf.run(rule, params, panel, Costs()), npf.run(rule, params, tampered, Costs())
    pd.testing.assert_frame_equal(a.iloc[:cut], b.iloc[:cut])
    np.testing.assert_array_equal(
        a.attrs["orders"][a.attrs["orders"] < cut], b.attrs["orders"][b.attrs["orders"] < cut]
    )
    la, lb = a.attrs["fills"], b.attrs["fills"]
    pd.testing.assert_frame_equal(
        la[la["bar"] <= cut].reset_index(drop=True), lb[lb["bar"] <= cut].reset_index(drop=True)
    )


@settings(deadline=None)
@given(case=cases(), costs=st.sampled_from(COST_MODELS))
def test_accounting_equals_an_independent_book_of_coin_units_and_cash(case, costs):
    """The Nautilus book against ``unit_book`` (coin units and USDC cash, sharing no code with either engine), to
    TOL: every column and every leg. A leg it did not trade at an order's next open is at most MIN_LEG off target."""
    panel, rule, params = case
    try:
        result = npf.run(rule, params, panel, costs)
    except ValueError as exc:
        assert REFUSAL.fullmatch(str(exc)), exc
        return
    out, legs, v_open, _, dust = unit_book(panel, target_of(params), result, costs)
    assert (out["cost"] < 1.0).all()
    assert (dust <= npf.MIN_LEG * (1 + 1e-6)).all()
    for col in ALL_COLUMNS:
        np.testing.assert_allclose(result[col].to_numpy(), out[col], rtol=0, atol=TOL, err_msg=col)
    log = result.attrs["fills"]
    fills = list(fill_bars_of(result))
    assert list(log["bar"]) == [leg["bar"] for leg in legs]
    assert list(log["asset"]) == [leg["asset"] for leg in legs]
    scale = np.array([v_open[fills.index(leg["bar"])] for leg in legs])
    for col in ("usd", "cost"):
        np.testing.assert_allclose(
            log[col].to_numpy() / scale, [leg[col] for leg in legs] / scale, rtol=0, atol=TOL, err_msg=col
        )


# ------------------------------------------------------------------------------- hand-built cases


def flat_panel(n: int, btc: float = 30_000.0, eth: float = 2_000.0) -> pd.DataFrame:
    index = pd.date_range("2021-01-01", periods=n, freq="D", tz="UTC", name="ts")

    def bars(price):
        return pd.DataFrame(
            {"open": price, "high": price, "low": price, "close": price, "volume": 1.0}, index=index
        )

    return pf.make_panel({"BTC": bars(btc), "ETH": bars(eth)}, snapshot_id="flat")


@pytest.mark.parametrize("coin", [0, 1])
def test_round_off_legs_are_not_sent_for_either_coin(coin):
    """A target change of at most MIN_LEG on one coin, on flat prices, is not sent; one of 2 x MIN_LEG is (and
    the other coin's leg goes with it, re-cut by its share of the fees as portfolio.py does)."""
    panel = flat_panel(5)
    for tiny, sent in ((npf.MIN_LEG / 2, False), (2 * npf.MIN_LEG, True)):
        rows = [[0.3, 0.3] for _ in range(5)]
        rows[1][coin] += tiny
        rows[2][coin] += tiny  # ordered at close 1 (fills at 2) and back at close 3 (fills at 4)
        nt = npf.run(tr.run_states, panel, rows, limits=LOOSE, costs=Costs())
        ref = tr.run_states(panel, rows, limits=LOOSE, costs=Costs())
        assert ref.attrs["n_trades"] == 3  # the first buy, the tiny change at bar 2, back at bar 4
        assert nt.attrs["n_trades"] == (3 if sent else 1)
        if sent:
            assert_parity(ref, nt)


def test_rebalancing_a_flat_book_with_band_0_sends_nothing_after_the_first_buy():
    """The rule sees the weights to 12 decimals: after the first buy, a flat book is at target to fixed-point
    noise, so band 0 orders nothing more (portfolio.py would trade round-off legs here and pay gas)."""
    for w in ((0.6, 0.0), (0.0, 0.6), (0.4, 0.3)):
        nt = npf.run(
            pf.rebalance, {"w_btc": w[0], "w_eth": w[1], "band": 0.0, "every": 1}, flat_panel(10), Costs()
        )
        assert nt.attrs["n_trades"] == 1


def test_full_sells_of_either_coin_leave_exactly_zero_units(make_bars):
    """Awkward prices, both coins bought, then each sold out in turn and both: a full sell sells exactly the
    account's balance (the sell cap, #62), so the weight is exactly 0, never a dust balance or a denied order."""
    btc = [4451.041648603093, 4460.7, 4433.01, 4501.123456789, 4499.9, 4512.0, 4400.0, 4410.0]
    eth = [301.4142135623731, 300.1, 302.71828182845, 299.99, 303.3, 301.0, 300.5, 299.0]
    panel = pf.make_panel({"BTC": make_bars(btc), "ETH": make_bars(eth)}, snapshot_id="hand")
    rows = [
        (0.45, 0.45),
        (0.45, 0.45),
        (0.0, 0.45),
        (0.0, 0.45),
        (0.45, 0.0),
        (0.45, 0.0),
        (0.0, 0.0),
        (0.0, 0.0),
    ]
    for costs in COST_MODELS:
        nt = npf.run(tr.run_states, panel, rows, limits=LOOSE, costs=costs)
        ref = tr.run_states(panel, rows, limits=LOOSE, costs=costs)
        assert_parity(ref, nt)
        w_btc, w_eth = nt["w_BTC"].to_numpy(), nt["w_ETH"].to_numpy()
        assert w_btc[3] == 0.0 and w_btc[4] == 0.0 and w_eth[5] == 0.0 and w_eth[6] == 0.0
        assert w_btc[7] == 0.0 and w_eth[7] == 0.0 and nt["position"].iloc[7] == 0.0


def test_a_target_of_round_off_size_is_not_bought():
    """Hypothesis's first find (#65 (b)): ETH's target 2.6e-126 is a leg of 2.6e-122 USD, a round-off leg
    (<= MIN_LEG). portfolio.py buys it and pays 0.10 USD of gas, and cuts BTC to 0.25 of the book after both legs'
    fees; Nautilus sends BTC's leg alone, so it keeps that gas: 0.75 of it as cash, 0.25 of it in BTC."""
    panel = random_panel(20, 0, (0.04, 0.04), (0.01, 0.01))
    params = {"w_btc": 0.25, "w_eth": 2.6283530881300087e-126, "n_rebalances": 0, "seed": 0}
    ref, nt = both(pf.random_rebalance, params, panel, Costs())
    assert list(ref.attrs["fills"]["asset"]) == ["BTC", "ETH"] and list(nt.attrs["fills"]["asset"]) == ["BTC"]
    gas = Costs().gas_usd_per_trade
    v_ref = Costs().capital_usd * np.cumprod(1.0 + ref["ret"].to_numpy())
    v_nt = Costs().capital_usd * np.cumprod(1.0 + nt["ret"].to_numpy())
    btc = panel[("BTC", "close")].to_numpy() / panel[("BTC", "open")].iloc[1]
    np.testing.assert_allclose(v_nt[1:] - v_ref[1:], gas * (0.75 + 0.25 * btc[1:]), rtol=0, atol=1e-7)
    assert (nt["w_ETH"] == 0.0).all()
    params["w_eth"] = 0.0
    assert npf.run(pf.random_rebalance, params, panel, Costs()).attrs["n_trades"] == 1


def test_a_book_all_in_one_coin_with_band_0_lists_orders_that_fill_nothing():
    """#65 (d): portfolio.py's weight of a book all in one coin is exactly 1 (x / x). Nautilus keeps the cash a
    buy cannot spend (below one 1e-12-unit step, up to ~3e-8 USD at BTC's price); once that is 5e-13 of the book
    the rule sees 0.999999999999 and, with band 0, orders. The order is a round-off leg and fills nothing, so the
    book, the fills and every column are portfolio.py's; only ``orders`` lists the extra closes. (At ETH's price of
    ~2000 the leftover is smaller; hypothesis found it there with w_eth = 1 on an 81-bar panel.)"""
    panel = random_panel(81, 5, (0.04, 0.04), (0.01, 0.01))
    params = {"w_btc": 1.0, "w_eth": 0.0, "band": 0.0, "every": 1}
    ref, nt = both(pf.rebalance, params, panel, Costs())
    assert list(ref.attrs["orders"]) == [0]
    assert len(nt.attrs["orders"]) > 1 and nt.attrs["n_trades"] == 1
    assert_parity(ref, nt)


def test_a_full_buy_of_both_coins_never_overdraws_the_cash():
    """Targets summing to 1: every buy is capped at what the cash left can pay, so no order is denied."""
    panel = random_panel(200, 4, (0.05, 0.06), (0.01, 0.01))
    for costs in COST_MODELS:
        ref, nt = both(pf.rebalance, {"w_btc": 0.5, "w_eth": 0.5, "band": 0.0, "every": 1}, panel, costs)
        assert_parity(ref, nt)
        assert (nt["position"] <= 1.0).all()


def test_a_coin_exactly_at_target_while_the_other_trades_is_re_cut_at_no_cost():
    """Binary-exact prices and fees: after the first buy ETH is exactly 0.5 of the book. A new BTC target then
    trades BTC alone; portfolio.py re-cuts ETH by its share of the fees without a swap and without gas, and so does
    this runner, with a zero-commission re-cut order (#65 (a)). The fill log and the fees list BTC alone."""
    panel = flat_panel(4, btc=4.0, eth=2.0)
    rows = [(0.25, 0.5), (0.25, 0.5), (0.3, 0.5), (0.3, 0.5)]
    gas_only = Costs(
        pool_fee_bps=0.0, aggregator_fee_bps=0.0, slippage_bps=((1.0, 0.0),), gas_usd_per_trade=1.0
    )
    for costs in (gas_only, Costs.zero()):
        ref = tr.run_states(panel, rows, limits=LOOSE, costs=costs)
        nt = npf.run(tr.run_states, panel, rows, limits=LOOSE, costs=costs)
        assert list(ref.attrs["fills"]["asset"]) == ["BTC", "ETH", "BTC"]
        assert_parity(ref, nt)
        assert list(nt.attrs["fills_usd"]["asset"]) == ["BTC", "ETH", "BTC"]
    assert nt["cost"].iloc[2] == 0.0 and ref["w_ETH"].iloc[3] == 0.5


# ------------------------------------------------------------------------------------------ refusals


def test_a_fill_the_book_cannot_pay_raises_portfolio_s_message():
    panel = random_panel(10, 3, (0.02, 0.02), (0.0, 0.0))
    costs = Costs(gas_usd_per_trade=20.0, capital_usd=10.0)
    params = {"w_btc": 0.5, "w_eth": 0.3, "band": 0.0, "every": 1}
    with pytest.raises(ValueError, match="it cannot pay them") as ref_err:
        pf.rebalance(params, panel, costs)
    with pytest.raises(ValueError, match="it cannot pay them") as nt_err:
        npf.run(pf.rebalance, params, panel, costs)
    assert str(nt_err.value) == str(ref_err.value)


def test_bad_params_and_panels_raise_before_the_engine_and_every_module_gets_its_engine_back(monkeypatch):
    def no_engine(*args):
        raise AssertionError("the engine was built")

    monkeypatch.setattr(npf, "_engine", no_engine)
    panel = random_panel(30, 3)
    with pytest.raises(ValueError, match="w_btc"):
        npf.run(pf.rebalance, {"w_btc": 0.8, "w_eth": 0.3, "band": 0.0, "every": 1}, panel)
    with pytest.raises(ValueError, match="panel"):
        npf.run(
            pf.rebalance, {"w_btc": 0.5, "w_eth": 0.3, "band": 0.0, "every": 1}, panel.droplevel(0, axis=1)
        )
    with pytest.raises(ValueError):
        npf.run(hm.hold_mix, {"w_btc": 0.5}, panel, Costs())
    with pytest.raises(ValueError, match="stop rule 12"):
        npf.run(
            tr.run_states, panel, [(0.5, 0.5)] * 30, limits={"min_cash": 0.2, "max_coin": 0.6}, costs=Costs()
        )
    with pytest.raises(AssertionError, match="the engine was built"):
        npf.run(pf.rebalance, {"w_btc": 0.5, "w_eth": 0.3, "band": 0.0, "every": 1}, panel)
    for module in (pf, hm, tr):
        assert module._simulate is npf._ENGINE
    assert pf.rebalance({"w_btc": 0.5, "w_eth": 0.3, "band": 0.0, "every": 1}, panel).attrs["n_trades"] >= 1


def test_a_function_that_is_not_a_portfolio_rule_is_refused():
    panel = random_panel(10, 3)
    with pytest.raises(ValueError, match="is not a portfolio rule .its module has no"):
        npf.run(reference.buy_and_hold, {}, panel)
    with pytest.raises(ValueError, match="is not a portfolio rule .it never reached the engine"):
        npf.run(pf.validate_panel, panel)
    assert pf._simulate is npf._ENGINE


def test_engine_problems_stop_the_run(monkeypatch):
    panel = random_panel(30, 11, (0.04, 0.04), (0.005, 0.005))
    params = {"w_btc": 0.5, "w_eth": 0.3, "band": 0.0, "every": 1}
    for handler in ("on_order_denied", "on_order_rejected"):

        def refuse(self, event, handler=handler):
            getattr(npf._Strategy, handler)(self, "a refusal")

        monkeypatch.setattr(npf._Strategy, "on_order_filled", refuse)
        with pytest.raises(npf.NautilusRunError, match="order (denied|rejected): a refusal"):
            npf.run(pf.rebalance, params, panel)
    monkeypatch.setattr(npf._Strategy, "on_order_filled", lambda self, event: None)
    with pytest.raises(npf.NautilusRunError, match="orders sent but 0 filled"):
        npf.run(pf.rebalance, params, panel)
    monkeypatch.undo()

    original = npf._Strategy.on_order_filled

    def twice(self, event):
        original(self, event)
        original(self, event)

    monkeypatch.setattr(npf._Strategy, "on_order_filled", twice)
    with pytest.raises(npf.NautilusRunError, match="filled in 2 parts"):
        npf.run(pf.rebalance, params, panel)
    monkeypatch.undo()

    monkeypatch.setattr(npf, "fee_usd", lambda costs, notional: costs.rate(notional) * notional + 1.0)
    with pytest.raises(npf.NautilusRunError, match="Nautilus charged"):
        npf.run(pf.rebalance, params, panel)
    monkeypatch.undo()

    quotes = npf._quotes
    monkeypatch.setattr(npf, "_quotes", lambda o, c, i: quotes(o, c, i)[:-2])
    with pytest.raises(npf.NautilusRunError, match="stopped at bar 28 of 29"):
        npf.run(pf.rebalance, params, panel)


def test_a_re_cut_that_pays_a_commission_stops_the_run(monkeypatch):
    """A re-cut is free (``fees.RECUT_TAG``); a fee model that charges it is refused."""
    monkeypatch.setattr(fees, "RECUT_TAG", "not-a-tag")  # the fee model no longer sees the re-cut tag
    panel = flat_panel(4, btc=4.0, eth=2.0)
    rows = [(0.25, 0.5), (0.25, 0.5), (0.3, 0.5), (0.3, 0.5)]
    with pytest.raises(npf.NautilusRunError, match="for re-cuts, which are free"):
        npf.run(tr.run_states, panel, rows, limits=LOOSE, costs=Costs())


def test_a_partial_of_a_portfolio_rule_runs_on_nautilus():
    panel = random_panel(40, 2, (0.04, 0.04), (0.01, 0.01))
    params = {"w_btc": 0.4, "w_eth": 0.3, "band": 0.02, "every": 3}
    fn = functools.partial(pf.rebalance, costs=Costs.from_yaml())
    assert_parity(fn(params, panel), npf.run(fn, params, panel))
    assert npf.wrap(fn).__name__ == "nautilus_rule"


def test_a_leg_below_one_unit_step_is_not_sent():
    """At 1e6 USD a coin, a book of 10 USD: a leg of 2e-9 of it (2e-14 units) is above MIN_LEG but below the
    1e-12-unit step, so it pays nothing and only the other coin's leg is sent; with both that small, no fill."""
    panel = flat_panel(4, btc=1e6, eth=1e6)
    costs = Costs(pool_fee_bps=0.0, slippage_bps=((1.0, 0.0),), gas_usd_per_trade=0.0, capital_usd=10.0)
    step = 2 * npf.MIN_LEG
    nt = npf.run(
        tr.run_states,
        panel,
        [(0.3, 0.3), (0.3 + step, 0.3 + step), (0.3, 0.3), (0.3, 0.3)],
        limits=LOOSE,
        costs=costs,
    )
    assert nt.attrs["n_trades"] == 1


# --------------------------------------------------------------------------------------- parallel search


def test_the_backtest_fn_pickles_and_runs_in_a_parallel_search(tmp_path, market):
    from lab.search.study import SearchConfig, run_study

    fn = npf.wrap(pf.rebalance)
    assert pickle.loads(pickle.dumps(fn)).__name__ == "nautilus_rebalance"
    panel = pf.make_panel(market, snapshot_id="synthetic-21").iloc[:300]
    table = run_study("ntp", fn, SPECS, panel, tmp_path, SearchConfig(n_trials=4, n_workers=2, seed=1))
    assert len(table) == 4 and (table["state"] == "COMPLETE").all()
    row = table.iloc[0]
    params = {s.name: row[f"params_{s.name}"] for s in SPECS}
    params = {k: (int(v) if k == "every" else float(v)) for k, v in params.items()}
    direct = fn(params, panel)
    assert row["n_trades"] == len(direct.attrs["trade_returns"])
