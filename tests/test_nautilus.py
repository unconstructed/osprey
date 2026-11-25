"""The NautilusTrader runner (``lab/runner/nautilus.py``) and the DEX fee model (``lab/costs/fees.py``).

The contract suite (``tests/contract/``) runs every guarantee on the Nautilus entries. This file adds:
- **parity**: the Nautilus runner equals the reference runner on the same rule, bars and costs, to the runner's
  written-down tolerance, column by column, fill by fill and trade by trade (AGENTS.md milestone 2);
- the fee model by hand, and what Nautilus booked for each fill (notional and commission in USD);
- the two documented differences from the reference (round-off legs, the rule's 12-decimal view of the weight);
- every refusal: an unaffordable fill, an order the engine refuses, a lost or split fill, a fee mismatch, a run
  that stops early, and a function that is not a reference rule.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from nautilus_trader.model import Currency, CurrencyType, Price, Quantity

from lab.costs import fees
from lab.costs.fees import INTENDED_TAG, DexFeeModel, fee_usd, intended_tag
from lab.runner import nautilus, reference
from lab.runner.interface import RESULT_COLUMNS, validate_result
from lab.runner.reference import Costs
from tests.contract.conftest import REFERENCE_RUNNERS
from tests.contract.test_backtest_contract import random_bars

COLS = list(RESULT_COLUMNS)


def assert_parity(ref: pd.DataFrame, nt: pd.DataFrame, n_bars: int) -> None:
    """Same fills on the same bars, every column within nautilus.TOL, the trade log and trade returns too."""
    assert nt.attrs["n_trades"] == ref.attrs["n_trades"]
    np.testing.assert_allclose(nt[COLS].to_numpy(), ref[COLS].to_numpy(), rtol=0, atol=nautilus.TOL)
    np.testing.assert_allclose(
        nt.attrs["trade_returns"], ref.attrs["trade_returns"], rtol=nautilus.TOL * n_bars
    )
    a, b = nt.attrs["trades"], ref.attrs["trades"]
    assert list(a["ts"]) == list(b["ts"]) and list(a["side"]) == list(b["side"])
    np.testing.assert_array_equal(a["price"].to_numpy(), b["price"].to_numpy())
    for col in ("weight_before", "weight_after", "turnover", "cost"):
        np.testing.assert_allclose(a[col].to_numpy(), b[col].to_numpy(), rtol=0, atol=nautilus.TOL)
    growth = np.prod(1.0 + nt["ret"].to_numpy())
    assert growth == pytest.approx(np.prod(1.0 + ref["ret"].to_numpy()), rel=nautilus.TOL * n_bars)


# ------------------------------------------------------------------------------------------------ parity

COST_MODELS = (
    Costs(),
    Costs().stressed(),
    Costs(pool_fee_bps=30.0, aggregator_fee_bps=10.0, gas_usd_per_trade=2.5),
)


@pytest.mark.parametrize("entry", REFERENCE_RUNNERS, ids=[r.name for r in REFERENCE_RUNNERS])
@settings(deadline=None)
@given(
    n=st.integers(20, 300),
    seed=st.integers(0, 2**32 - 1),
    # Moving prices only: on a flat path the reference trades round-off legs that this runner does not
    # (test_round_off_legs_are_not_traded pins that difference; on moving prices it is rare enough that these
    # draws never reach it, and scripts/nautilus_parity_real.py checks it on real hourly bars); every path must agree.
    vol=st.sampled_from([0.01, 0.04, 0.1]),
    gap=st.sampled_from([0.0, 0.005, 0.03]),
    costs=st.sampled_from(COST_MODELS),
)
def test_nautilus_equals_the_reference_on_every_contract_rule(entry, n, seed, vol, gap, costs):
    bars = random_bars(n, seed, vol, gap)
    ref = entry.fn(entry.params, bars, costs=costs)
    nt = nautilus.wrap(entry.fn)(entry.params, bars, costs=costs)
    validate_result(nt, bars)
    assert_parity(ref, nt, n)


@pytest.mark.parametrize(
    ("rule", "params"),
    [
        (reference.buy_and_hold, {}),
        (reference.constant_mix, {"weight": 0.5, "every": 30}),  # the 50/50 monthly benchmark
        (reference.dip_buy, {"drop": 0.1, "lookback": 20, "stop": 0.1, "hold": 30}),
        (reference.dip_buy, {"drop": 0.08, "lookback": 10, "vol_target": 0.6}),
    ],
    ids=["buy_and_hold", "fifty_fifty_monthly", "dip_buy_stop_hold", "dip_buy_vol_target"],
)
def test_parity_on_the_synthetic_market_with_the_config_costs(btc, rule, params):
    """1500 days of the regime-switching market (prices in the tens of thousands), costs from config/costs.yaml,
    at 1x and 2x: the Sharpe the search would read is the same to 1e-9."""
    for costs in (Costs.from_yaml(), Costs.from_yaml().stressed()):
        ref = rule(params, btc, costs)
        nt = nautilus.run(rule, params, btc, costs)
        assert ref.attrs["n_trades"] > 0
        assert_parity(ref, nt, len(btc))
        sharpe = [r["ret"].mean() / r["ret"].std() for r in (ref, nt)]
        assert sharpe[1] == pytest.approx(sharpe[0], abs=1e-9)


# ------------------------------------------------------------------------------------- the fee model


def test_fee_usd_by_hand():
    # 5 bps pool, 0 aggregator, slippage 10 / 15 / 30 bps at 100 / 1,000 / 10,000 USD, 0.10 USD gas
    costs = Costs()
    assert fee_usd(costs, 1000.0) == pytest.approx(1000.0 * (5 + 15) / 1e4 + 0.10, rel=1e-15)
    assert fee_usd(costs, 50.0) == pytest.approx(50.0 * (5 + 10) / 1e4 + 0.10, rel=1e-15)
    # between table points slippage is linear in log10(size): 10^2.5 USD is halfway from 100 to 1,000
    assert fee_usd(costs, 10**2.5) == pytest.approx(10**2.5 * (5 + 12.5) / 1e4 + 0.10, rel=1e-12)
    assert fee_usd(Costs.zero(), 1e6) == 0.0
    assert fee_usd(costs.stressed(2.0), 1000.0) == pytest.approx(2 * fee_usd(costs, 1000.0), rel=1e-15)


class _Order:
    def __init__(self, tags):
        self.tags = tags


USD = Currency("USDT1", 12, 0, "test dollar", CurrencyType.CRYPTO)


def test_the_fee_model_charges_the_intended_notional_else_the_fill_notional():
    model = DexFeeModel(Costs(), USD)
    qty, px = Quantity(2.5, 12), Price(400.0, 12)
    tagged = model.get_commission(_Order([intended_tag(1234.5)]), qty, px, None)
    assert tagged.currency == USD
    assert float(tagged) == pytest.approx(fee_usd(Costs(), 1234.5), abs=1e-12)
    plain = model.get_commission(_Order(None), qty, px, None)  # a model account's plain order: 2.5 x 400
    assert float(plain) == pytest.approx(fee_usd(Costs(), 1000.0), abs=1e-12)
    other = model.get_commission(_Order(["something-else"]), qty, px, None)
    assert float(other) == float(plain)
    assert intended_tag(0.1) == f"{INTENDED_TAG}0.1"
    assert float(intended_tag(1 / 3)[len(INTENDED_TAG) :]) == 1 / 3  # exact round trip of the float


def test_the_fee_model_refuses_bad_input():
    with pytest.raises(ValueError, match="costs must be a Costs instance"):
        DexFeeModel({"pool_fee_bps": 5}, USD)
    model = DexFeeModel(Costs(), USD)
    qty, px = Quantity(1.0, 12), Price(1.0, 12)
    with pytest.raises(ValueError, match="carries 2 intended_usd= tags"):
        model.get_commission(_Order([intended_tag(1.0), intended_tag(2.0)]), qty, px, None)
    for bad in ("0.0", "-5.0", "nan"):
        with pytest.raises(ValueError, match="intended notional must be positive"):
            model.get_commission(_Order([INTENDED_TAG + bad]), qty, px, None)


def test_nautilus_books_the_order_net_of_its_cost_by_hand():
    """Buy-and-hold on 3 bars: decided at close 0, filled at the open of bar 1. With V = 10,000 USD and target 1,
    the intended notional is 10,000 USD, the fee is fee_usd(10,000), and the order buys (V - fee) / open units:
    Nautilus books a notional of V - fee and a commission of exactly fee."""
    bars = random_bars(3, 1, 0.02, 0.01)
    costs = Costs()
    nt = nautilus.run(reference.buy_and_hold, {}, bars, costs)
    fee = fee_usd(costs, 10_000.0)
    booked = nt.attrs["fills_usd"]
    assert list(booked["ts"]) == [bars.index[1]]
    assert booked["commission_usd"].iloc[0] == pytest.approx(fee, abs=1e-9)
    assert booked["notional_usd"].iloc[0] == pytest.approx(10_000.0 - fee, abs=1e-6)
    assert nt["cost"].iloc[1] == pytest.approx(fee / 10_000.0, abs=1e-15)
    assert nt["position"].iloc[1] == pytest.approx(1.0, abs=1e-12)
    assert nt["turnover"].iloc[1] == pytest.approx(1.0, abs=1e-12)
    c, o = bars["close"].to_numpy(), bars["open"].to_numpy()
    assert 1 + nt["ret"].iloc[1] == pytest.approx((1 - fee / 1e4) * c[1] / o[1], abs=1e-12)
    assert 1 + nt["ret"].iloc[2] == pytest.approx(c[2] / c[1], abs=1e-12)


# ---------------------------------------------------------------------------- documented differences


def _flat_bars(n: int, price: float) -> pd.DataFrame:
    index = pd.date_range("2021-01-01", periods=n, freq="D", tz="UTC", name="ts")
    return pd.DataFrame(
        {"open": price, "high": price, "low": price, "close": price, "volume": 1.0}, index=index
    )


def test_round_off_legs_are_not_traded():
    """A leg of at most MIN_LEG of the book is never sent; one above it is. The reference trades any leg > 0."""
    bars = _flat_bars(5, 100.0)
    step = 2 * nautilus.MIN_LEG
    for tiny, traded in ((nautilus.MIN_LEG / 2, False), (step, True)):
        ladder = bars.assign(target=[0.5, 0.5 + tiny, 0.5, 0.5, 0.5])
        nt = nautilus.run(reference.scheduled, {"col": "target"}, ladder, Costs.zero())
        ref = reference.scheduled({"col": "target"}, ladder, Costs.zero())
        assert ref.attrs["n_trades"] == 3  # 0.5 at bar 1, the tiny leg at bar 2, back to 0.5 at bar 3
        assert nt.attrs["n_trades"] == (3 if traded else 1)


def test_a_leg_below_one_unit_step_is_not_sent():
    """At a price of 1e6 USD a book of 10 USD holds 1e-5 units; a leg of 2e-9 of it (2e-8 USD) is 2e-14 units,
    below the 1e-12-unit step, so no order is sent even though the leg is above MIN_LEG."""
    bars = _flat_bars(4, 1e6)
    ladder = bars.assign(target=[0.5, 0.5 + 2 * nautilus.MIN_LEG, 0.5, 0.5])
    costs = Costs(pool_fee_bps=0.0, slippage_bps=((1.0, 0.0),), gas_usd_per_trade=0.0, capital_usd=10.0)
    nt = nautilus.run(reference.scheduled, {"col": "target"}, ladder, costs)
    assert nt.attrs["n_trades"] == 1


def test_the_rule_sees_the_weight_to_twelve_decimals():
    """constant_mix with band 0 on flat prices: after the first buy the book is 0.5 to fixed-point noise, so the
    rule (which orders whenever the weight is not exactly 0.5) sends nothing more, with or without costs."""
    bars = _flat_bars(10, 123.456)
    for costs in (Costs.zero(), Costs()):
        nt = nautilus.run(reference.constant_mix, {"weight": 0.5}, bars, costs)
        assert nt.attrs["n_trades"] == 1


# ------------------------------------------------------------------------------------------ refusals


def test_a_fill_the_book_cannot_pay_raises_like_the_reference():
    bars = random_bars(10, 3, 0.02, 0.0)
    costs = Costs(gas_usd_per_trade=20.0, capital_usd=10.0)
    with pytest.raises(ValueError, match="it cannot pay them") as ref_err:
        reference.buy_and_hold({}, bars, costs)
    with pytest.raises(ValueError, match="it cannot pay them") as nt_err:
        nautilus.run(reference.buy_and_hold, {}, bars, costs)
    assert str(nt_err.value) == str(ref_err.value)


def test_bad_params_and_bars_raise_before_the_engine_and_the_reference_engine_is_restored():
    original = reference._simulate
    bars = random_bars(10, 3, 0.02, 0.0)
    with pytest.raises(ValueError):
        nautilus.run(reference.dip_buy, {"drop": 0.0, "lookback": 5}, bars)
    with pytest.raises(ValueError):
        nautilus.run(reference.buy_and_hold, {}, bars.iloc[:1])
    assert reference._simulate is original
    assert reference.buy_and_hold({}, bars).attrs["n_trades"] == 1  # the reference still runs its own engine


def test_a_function_that_is_not_a_reference_rule_is_refused():
    bars = random_bars(10, 3, 0.02, 0.0)
    with pytest.raises(ValueError, match="is not a reference rule"):
        nautilus.decider(lambda params, b: None, {}, bars, None)
    assert nautilus.wrap(reference.dip_buy).__name__ == "nautilus_dip_buy"


@pytest.fixture
def bars30():
    return random_bars(30, 11, 0.04, 0.005)


def test_an_order_past_the_cash_stops_the_engine(monkeypatch, bars30):
    """Size a buy at twice what the book can pay: Nautilus's risk engine denies it (a cash account cannot
    borrow), and the run stops with the engine's reason."""
    monkeypatch.setattr(nautilus, "_units", lambda x: Quantity(2 * float(x), nautilus.PRECISION))
    with pytest.raises(nautilus.NautilusRunError, match="order denied: .*NOTIONAL_EXCEEDS_FREE_BALANCE"):
        nautilus.run(reference.buy_and_hold, {}, bars30)


def test_an_order_the_engine_denies_or_rejects_stops_the_run(monkeypatch, bars30):
    for handler in ("on_order_denied", "on_order_rejected"):

        def refuse(self, event, handler=handler):
            getattr(nautilus._RuleStrategy, handler)(self, "a refusal")

        monkeypatch.setattr(nautilus._RuleStrategy, "on_order_filled", refuse)
        with pytest.raises(nautilus.NautilusRunError, match="order (denied|rejected): a refusal"):
            nautilus.run(reference.buy_and_hold, {}, bars30)


def test_a_lost_fill_stops_the_run(monkeypatch, bars30):
    monkeypatch.setattr(nautilus._RuleStrategy, "on_order_filled", lambda self, event: None)
    with pytest.raises(nautilus.NautilusRunError, match="but filled on bars"):
        nautilus.run(reference.buy_and_hold, {}, bars30)


def test_a_split_fill_stops_the_run(monkeypatch, bars30):
    original = nautilus._RuleStrategy.on_order_filled

    def twice(self, event):
        original(self, event)
        original(self, event)

    monkeypatch.setattr(nautilus._RuleStrategy, "on_order_filled", twice)
    with pytest.raises(nautilus.NautilusRunError, match="filled in 2 parts"):
        nautilus.run(reference.buy_and_hold, {}, bars30)


def test_a_commission_other_than_the_cost_model_stops_the_run(monkeypatch, bars30):
    monkeypatch.setattr(fees, "fee_usd", lambda costs, notional: costs.rate(notional) * notional)  # no gas
    with pytest.raises(nautilus.NautilusRunError, match="Nautilus charged"):
        nautilus.run(reference.buy_and_hold, {}, bars30)


def test_a_run_that_stops_early_is_refused(monkeypatch, bars30):
    original = nautilus._quotes
    monkeypatch.setattr(nautilus, "_quotes", lambda o, c, i: original(o, c, i)[:-1])
    with pytest.raises(nautilus.NautilusRunError, match="stopped at bar 28 of 29"):
        nautilus.run(reference.buy_and_hold, {}, bars30)


def test_precision_constants():
    assert nautilus.PRECISION == 12 and nautilus.TOL == 1e-9 and nautilus.MIN_LEG == 1e-9
    assert nautilus.USDX.precision == nautilus.COINX.precision == 12
    assert math.isclose(float(nautilus._units(1.23456789012399)), 1.234567890123)
    assert float(nautilus._units(-1.0)) == 0.0


def test_bars_from_the_catalog_run_on_nautilus_like_the_reference(tmp_path, btc):
    """The milestone path: bars written to a Nautilus ParquetDataCatalog, read back with
    ``lab.data.catalog.load_bars`` (with their snapshot id), and run on both runners with the config costs."""
    import json

    from lab.data import catalog as cat

    bars = btc.iloc[:400]
    precision = cat.price_precision(bars)
    instrument = cat.make_instrument("BTC/USD.KRAKEN", "XBT/USD", "BTC", "USD", precision)
    series = {"1d": cat.to_nautilus(bars, cat.bar_type("BTC/USD.KRAKEN", "1d"), precision)}
    cat.write_catalog(tmp_path, [instrument], series)
    (tmp_path / cat.SNAPSHOT_FILE).write_text(json.dumps({"snapshot_id": "0123456789abcdef"}))
    loaded = cat.load_bars("BTC/USD.KRAKEN", "1d", catalog_dir=tmp_path)
    assert loaded.attrs["snapshot_id"] == "0123456789abcdef" and len(loaded) == 400
    params = {"drop": 0.08, "lookback": 10, "stop": 0.1, "hold": 20}
    ref = reference.dip_buy(params, loaded)
    nt = nautilus.run(reference.dip_buy, params, loaded)
    assert ref.attrs["n_trades"] > 0
    assert_parity(ref, nt, len(loaded))


def test_the_nautilus_backtest_fn_runs_in_a_parallel_search(tmp_path, btc):
    """``wrap`` gives a picklable BacktestFn, so ``lab.search.study`` can hand it to spawned worker processes; the
    search's logged Sharpe of a trial equals a direct Nautilus run of the same params."""
    import pickle

    from lab.search.space import Param
    from lab.search.study import SearchConfig, run_study

    fn = nautilus.wrap(reference.dip_buy)
    assert pickle.loads(pickle.dumps(fn)).__name__ == "nautilus_dip_buy"
    specs = [Param("drop", "float", 0.03, 0.2), Param("lookback", "int", 3, 15)]
    bars = btc.iloc[:500]
    table = run_study("nt", fn, specs, bars, tmp_path, SearchConfig(n_trials=4, n_workers=2, seed=1))
    assert len(table) == 4 and (table["state"] == "COMPLETE").all()
    row = table.iloc[0]
    params = {"drop": row["params_drop"], "lookback": int(row["params_lookback"])}
    direct = fn(params, bars)
    assert row["n_trades"] == len(direct.attrs["trade_returns"])
