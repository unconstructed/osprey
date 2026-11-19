"""The DEX cost model (config/costs.yaml): values by hand, YAML loading, stress, and how costs change returns.

Hand numbers for the placeholder table (pool 5 bps, aggregator 0, slippage 10/15/30 bps at 100/1,000/10,000
USD, gas 0.10 USD): slippage is linear in log10(trade size) between points, flat below 100 USD and extended
along the last segment (15 bps per decade) above 10,000 USD.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
import yaml
from hypothesis import given
from hypothesis import strategies as st

from lab.config import CONFIG_DIR
from lab.runner.reference import Costs, buy_and_hold, constant_mix, dip_buy, random_entry

# ------------------------------------------------------------------------------------------ values by hand

SLIPPAGE_BY_HAND = [
    (100.0, 10.0),
    (1000.0, 15.0),
    (10000.0, 30.0),
    (10**2.5, 12.5),  # halfway between 100 and 1,000 in log10 size
    (10**3.5, 22.5),
    (200.0, 10.0 + 5.0 * math.log10(2.0)),
    (5000.0, 15.0 + 15.0 * math.log10(5.0)),
    (0.0, 10.0),  # flat below the smallest point
    (1.0, 10.0),
    (99.0, 10.0),
    (20000.0, 30.0 + 15.0 * math.log10(2.0)),  # extended above the largest point
    (1e5, 45.0),
    (1e6, 60.0),
]


@pytest.mark.parametrize(("trade_usd", "bps"), SLIPPAGE_BY_HAND)
def test_slippage_by_hand(trade_usd, bps):
    assert Costs().slippage(trade_usd) == pytest.approx(bps, rel=1e-12)


@pytest.mark.parametrize(("trade_usd", "bps"), [(100, 10.0), (1000, 15.0), (10000, 30.0)])
def test_slippage_is_exact_at_the_table_points(trade_usd, bps):
    assert Costs().slippage(trade_usd) == bps


@pytest.mark.parametrize(("trade_usd", "bps"), SLIPPAGE_BY_HAND)
def test_rate_is_pool_plus_aggregator_plus_slippage(trade_usd, bps):
    assert Costs().rate(trade_usd) == pytest.approx((5.0 + bps) / 1e4, rel=1e-12)
    assert Costs(aggregator_fee_bps=3.0).rate(trade_usd) == pytest.approx((8.0 + bps) / 1e4, rel=1e-12)


def test_rate_at_the_table_points():
    costs = Costs()
    assert costs.rate(100) == pytest.approx(0.0015, rel=1e-15)
    assert costs.rate(1000) == pytest.approx(0.0020, rel=1e-15)
    assert costs.rate(10000) == pytest.approx(0.0035, rel=1e-15)


@given(x=st.floats(0.0, 1e9), y=st.floats(0.0, 1e9))
def test_slippage_grows_with_size(x, y):
    lo, hi = sorted((x, y))
    assert Costs().slippage(lo) <= Costs().slippage(hi) + 1e-12


@pytest.mark.parametrize("point", [100.0, 1000.0, 10000.0])
def test_slippage_is_continuous_at_the_points(point):
    costs = Costs()
    for eps in (1e-9, -1e-9):
        assert costs.slippage(point * (1 + eps)) == pytest.approx(costs.slippage(point), abs=1e-6)


def test_a_falling_table_is_never_extended_downward():
    costs = Costs(slippage_bps=((100.0, 20.0), (1000.0, 10.0)))
    assert costs.slippage(10**2.5) == pytest.approx(15.0, rel=1e-12)  # interpolated inside the table
    assert costs.slippage(1e4) == 10.0 and costs.slippage(1e9) == 10.0  # pessimistic: held flat above


def test_a_single_point_table_is_flat():
    costs = Costs(slippage_bps=((500.0, 7.0),))
    assert costs.slippage(0.0) == costs.slippage(500.0) == costs.slippage(1e9) == 7.0


def test_gas_fraction_by_hand():
    assert Costs().gas_fraction(10_000.0) == pytest.approx(1e-5, rel=1e-15)
    assert Costs().gas_fraction(100.0) == pytest.approx(1e-3, rel=1e-15)
    assert Costs(gas_usd_per_trade=2.5).gas_fraction(1000.0) == pytest.approx(2.5e-3, rel=1e-15)
    for bad in (0.0, -1.0, math.nan, math.inf):
        with pytest.raises(ValueError, match="portfolio_usd must be in"):
            Costs().gas_fraction(bad)


@pytest.mark.parametrize("bad", [-1.0, math.nan, math.inf, "100", None])
def test_slippage_rejects_bad_sizes(bad):
    with pytest.raises(ValueError, match="trade_usd must be"):
        Costs().slippage(bad)


# ------------------------------------------------------------------------------------------- zero, stress


@given(x=st.floats(0.0, 1e12), v=st.floats(1e-6, 1e12))
def test_zero_costs_nothing(x, v):
    zero = Costs.zero()
    assert zero.rate(x) == 0.0
    assert zero.gas_fraction(v) == 0.0


def test_stressed_doubles_everything_including_gas():
    base, stressed = Costs(), Costs().stressed()
    assert stressed.pool_fee_bps == 10.0 and stressed.aggregator_fee_bps == 0.0
    assert stressed.slippage_bps == ((100.0, 20.0), (1000.0, 30.0), (10000.0, 60.0))
    assert stressed.gas_usd_per_trade == pytest.approx(0.20, rel=1e-15)
    assert stressed.capital_usd == base.capital_usd and stressed.stress_multiplier == base.stress_multiplier
    for x in (0.0, 50.0, 100.0, 300.0, 1000.0, 5000.0, 1e4, 1e6):
        assert stressed.rate(x) == pytest.approx(2.0 * base.rate(x), rel=1e-12)
    assert stressed.gas_fraction(5000.0) == pytest.approx(2.0 * base.gas_fraction(5000.0), rel=1e-15)
    assert Costs(stress_multiplier=3.0).stressed().pool_fee_bps == 15.0


@given(k=st.floats(0.01, 100.0), x=st.floats(0.0, 1e9), v=st.floats(1.0, 1e9))
def test_stressed_k_scales_rate_and_gas_by_k(k, x, v):
    base = Costs(aggregator_fee_bps=2.0)
    stressed = base.stressed(k)
    assert stressed.rate(x) == pytest.approx(k * base.rate(x), rel=1e-12)
    assert stressed.gas_fraction(v) == pytest.approx(k * base.gas_fraction(v), rel=1e-12)


@pytest.mark.parametrize("bad", [0.0, -2.0, math.nan, math.inf, True])
def test_stressed_rejects_bad_multipliers(bad):
    with pytest.raises(ValueError, match="k must be"):
        Costs().stressed(bad)


# --------------------------------------------------------------------------------------------- loading


def test_yaml_loading_equals_the_placeholders():
    raw = yaml.safe_load((CONFIG_DIR / "costs.yaml").read_text())
    costs = Costs.from_yaml()
    assert costs.pool_fee_bps == raw["pool_fee_bps"] == 5
    assert costs.aggregator_fee_bps == raw["aggregator_fee_bps"] == 0
    assert costs.slippage_bps == tuple(sorted((float(k), float(v)) for k, v in raw["slippage_bps"].items()))
    assert costs.slippage_bps == ((100.0, 10.0), (1000.0, 15.0), (10000.0, 30.0))
    assert costs.gas_usd_per_trade == raw["gas_usd_per_trade"] == 0.10
    assert costs.stress_multiplier == raw["stress_multiplier"] == 2.0
    assert costs.capital_usd == 10_000.0
    # the dataclass defaults mirror the placeholders: when measured values replace them, update both
    assert costs == Costs()
    assert Costs.from_yaml(capital_usd=1e6).capital_usd == 1e6


def _write(tmp_path, text, name="costs.yaml"):
    path = tmp_path / name
    path.write_text(text)
    return path


GOOD_YAML = """
venue: somewhere
pool_fee_bps: 1
aggregator_fee_bps: 2
slippage_bps: {"5000": 40, "50": 3, "500": 8}
gas_usd_per_trade: 0.5
stress_multiplier: 3
"""


def test_from_yaml_reads_another_file_and_sorts_the_table(tmp_path):
    path = _write(tmp_path, GOOD_YAML)
    costs = Costs.from_yaml(path, capital_usd=2000.0)
    assert costs == Costs(
        pool_fee_bps=1.0,
        aggregator_fee_bps=2.0,
        slippage_bps=((50.0, 3.0), (500.0, 8.0), (5000.0, 40.0)),
        gas_usd_per_trade=0.5,
        stress_multiplier=3.0,
        capital_usd=2000.0,
    )
    assert Costs.from_yaml(str(path)) == Costs.from_yaml(path)  # a str path works too


@pytest.mark.parametrize(
    ("text", "name", "match"),
    [
        (GOOD_YAML, "costs.yml", r"must be a \.yaml file"),
        ("pool_fee_bps: 5\n", "costs.yaml", r"missing \['aggregator_fee_bps', 'slippage_bps'"),
        (GOOD_YAML.replace('{"5000": 40, "50": 3, "500": 8}', "[10, 15]"), "costs.yaml", "must map trade size"),
        (GOOD_YAML.replace('"5000"', '"lots"'), "costs.yaml", "sizes must be numbers"),
        (GOOD_YAML.replace("pool_fee_bps: 1", "pool_fee_bps: -1"), "costs.yaml", "pool_fee_bps must be in"),
        (GOOD_YAML.replace("gas_usd_per_trade: 0.5", "gas_usd_per_trade: null"), "costs.yaml", "must be a number"),
        (GOOD_YAML.replace('"50": 3', '"50": -3'), "costs.yaml", r"slippage \(bps\) must be in"),
    ],
)
def test_from_yaml_rejects_bad_files(tmp_path, text, name, match):
    with pytest.raises(ValueError, match=match):
        Costs.from_yaml(_write(tmp_path, text, name))


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"pool_fee_bps": -1.0}, "pool_fee_bps must be in"),
        ({"aggregator_fee_bps": math.nan}, "aggregator_fee_bps must be in"),
        ({"gas_usd_per_trade": -0.1}, "gas_usd_per_trade must be in"),
        ({"gas_usd_per_trade": "0.1"}, "gas_usd_per_trade must be a number"),
        ({"stress_multiplier": 0.0}, r"stress_multiplier must be in \(0.0, inf\)"),
        ({"capital_usd": 0.0}, r"capital_usd must be in \(0.0, inf\)"),
        ({"capital_usd": math.inf}, "capital_usd must be in"),
        ({"slippage_bps": ()}, "non-empty sequence of"),
        ({"slippage_bps": None}, "non-empty sequence of"),
        ({"slippage_bps": (5.0, 10.0)}, "non-empty sequence of"),
        ({"slippage_bps": ((100.0, 10.0, 1.0),)}, "non-empty sequence of"),
        ({"slippage_bps": ((0.0, 10.0),)}, r"slippage trade size \(USD\) must be in"),
        ({"slippage_bps": ((100.0, -1.0),)}, r"slippage \(bps\) must be in"),
        ({"slippage_bps": ((1000.0, 15.0), (100.0, 10.0))}, "strictly increasing"),
        ({"slippage_bps": ((100.0, 10.0), (100.0, 12.0))}, "strictly increasing"),
    ],
)
def test_invalid_costs_raise(kwargs, match):
    with pytest.raises(ValueError, match=match):
        Costs(**kwargs)


def test_costs_accept_sequences_and_normalise_to_float_tuples():
    costs = Costs(pool_fee_bps=np.int64(4), slippage_bps=[[100, 10], [1000, 15]])
    assert costs.slippage_bps == ((100.0, 10.0), (1000.0, 15.0))
    assert isinstance(costs.pool_fee_bps, float) and costs.pool_fee_bps == 4.0
    assert hash(costs) == hash(Costs(pool_fee_bps=4.0, slippage_bps=((100.0, 10.0), (1000.0, 15.0))))


# ---------------------------------------------------------------------------------- costs change returns

RULES = [
    (dip_buy, {"drop": 0.05, "lookback": 5, "hold": 6}),
    (dip_buy, {"drop": 0.04, "lookback": 5, "stop": 0.05, "hold": 9, "weight": 0.9, "vol_target": 0.6, "vol_lookback": 10}),
    (buy_and_hold, {"weight": 0.7}),
    (constant_mix, {}),
    (constant_mix, {"weight": 0.3, "every": 7, "band": 0.02}),
    (random_entry, {"n_trades": 3, "hold": 5, "seed": 4}),
]
COST_MODELS = [Costs(), Costs().stressed(), Costs(capital_usd=500.0), Costs(capital_usd=1e7, aggregator_fee_bps=4.0)]


@given(
    rule=st.sampled_from(RULES),
    start=st.integers(0, 1100),
    length=st.integers(30, 400),
    costs=st.sampled_from(COST_MODELS),
)
def test_costs_change_returns_by_exactly_the_cost_paid(btc, rule, start, length, costs):
    """Same decisions with and without costs; (1 + ret) == (1 + ret_zero_cost) * (1 - cost) on every bar,
    and every bar's cost is turnover * rate(turnover * V_open) + gas / V_open, rebuilt from the equity curve."""
    fn, params = rule
    bars = btc.iloc[start : start + length]
    paid = fn(params, bars, costs)
    free = fn(params, bars, Costs.zero())
    pos, turnover, cost = (paid[c].to_numpy() for c in ("position", "turnover", "cost"))
    np.testing.assert_array_equal(pos, free["position"].to_numpy())
    np.testing.assert_array_equal(turnover, free["turnover"].to_numpy())
    np.testing.assert_allclose(1 + paid["ret"], (1 + free["ret"]) * (1 - cost), rtol=0, atol=1e-14)
    value = costs.capital_usd * np.cumprod(1.0 + paid["ret"].to_numpy())  # USD at each close
    gap = bars["open"].to_numpy()[1:] / bars["close"].to_numpy()[:-1] - 1.0
    v_open = value[:-1] * (1.0 + pos[:-1] * gap)  # USD at the open of bars 1..n-1, before any trade
    for t in np.flatnonzero(turnover > 0):
        trade_usd = turnover[t] * v_open[t - 1]
        expected = turnover[t] * costs.rate(trade_usd) + costs.gas_usd_per_trade / v_open[t - 1]
        assert cost[t] == pytest.approx(expected, rel=1e-9)
    if paid.attrs["n_trades"]:
        assert np.prod(1.0 + paid["ret"].to_numpy()) < np.prod(1.0 + free["ret"].to_numpy())


@pytest.mark.parametrize(("capital", "slippage_bps"), [(50.0, 10.0), (100.0, 10.0), (1e4, 30.0), (1e6, 60.0)])
def test_trade_size_in_usd_sets_the_slippage(make_bars, capital, slippage_bps):
    bars = make_bars([100.0, 100.0, 101.0])
    costs = Costs(gas_usd_per_trade=0.0, capital_usd=capital)
    result = buy_and_hold({}, bars, costs)  # buys 100% of capital at the open of bar 1
    assert result["cost"].iloc[1] == pytest.approx((5.0 + slippage_bps) / 1e4, rel=1e-12)


def test_a_cost_the_portfolio_cannot_pay_raises(make_bars):
    bars = make_bars([100.0, 100.0, 101.0])
    with pytest.raises(ValueError, match="cannot pay them"):
        buy_and_hold({}, bars, Costs(gas_usd_per_trade=20_000.0))
