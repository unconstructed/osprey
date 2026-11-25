"""momentum-bold's engine (lab/runner/momentum.py; research/momentum-bold/PLAN.md sections 3-10). Synthetic and
hand-built panels only."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest
from hypothesis import example, given
from hypothesis import strategies as st

from lab.runner import momentum as M
from lab.runner import portfolio as pf
from lab.runner.interface import validate_result
from lab.runner.reference import Costs
from lab.search.walkforward import walk_forward_optimize
from lab.validation.splits import walk_forward

START = "2020-01-06"  # row 0 is a Monday close
ZERO = M.CoinCosts(Costs.zero(), Costs.zero())
ONE = M.coin_costs()
COSTS = {"zero": ZERO, "1x": ONE, "2x": ONE.stressed(2.0)}


def frame(closes, qv=1.0, start=START) -> pd.DataFrame:
    """Daily bars from a close path (None = no bar that day); open = the previous close (or the close)."""
    idx = pd.date_range(start, periods=len(closes), freq="D", tz="UTC", name="ts")
    qv = np.broadcast_to(np.asarray(qv, dtype=float), (len(closes),))
    rows = []
    for i, c in enumerate(closes):
        if c is None:
            continue
        o = closes[i - 1] if i > 0 and closes[i - 1] is not None else c
        rows.append((idx[i], o, max(o, c), min(o, c), c, qv[i] / c, qv[i]))
    f = pd.DataFrame(rows, columns=["ts", *M.FIELDS]).set_index("ts")
    return f


def wide(frames: dict) -> pd.DataFrame:
    return M.make_wide_panel(frames, snapshot_id="test")


def random_frames(seed: int, n: int = 260, m: int = 7) -> dict:
    rng = np.random.default_rng(seed)
    idx = pd.date_range(START, periods=n, freq="D", tz="UTC", name="ts")
    out = {}
    for s in ["BTCUSDT", "ETHUSDT", *(f"R{i}USDT" for i in range(m)), "USDCUSDT"]:
        major = s in ("BTCUSDT", "ETHUSDT")
        first = 0 if major else int(rng.integers(0, 120))
        last = n - 1 if major or rng.random() < 0.6 else int(rng.integers(first + 95, n))
        close = 100.0 * np.exp(np.cumsum(rng.normal(0.001, 0.04, n)))
        prev = np.concatenate([[close[0]], close[:-1]])
        o = prev * np.exp(rng.normal(0.0, 0.01, n))
        qv = 10 ** rng.uniform(3, 6) * np.exp(rng.normal(0.0, 0.3, n))
        f = pd.DataFrame(
            {"open": o, "high": np.maximum(o, close) * 1.01, "low": np.minimum(o, close) * 0.99, "close": close,
             "volume": qv / close, "quote_volume": qv},
            index=idx,
        ).iloc[first : last + 1]
        if not major:
            f = f.drop(f.index[rng.choice(len(f), size=2, replace=False)])
        out[s] = f
    return out


PARAMS = st.fixed_dictionaries({
    "lookback": st.sampled_from([3, 14, 28, 91, 109]),
    "k": st.sampled_from([1, 2, 3, 5, 10, 20]),
    "filter": st.sampled_from(M.FILTERS),
})


# ------------------------------------------------------------------------------------------------ the universe


@pytest.mark.parametrize(
    ("symbol", "why"),
    [
        ("BTCUSDT", None), ("ETHUSDT", None), ("JUPUSDT", None), ("BTCSTUSDT", None), ("SUPERUSDT", None),
        ("USDCUSDT", "stablecoin"), ("FDUSDUSDT", "stablecoin"), ("EURUSDT", "fiat"), ("TRYUSDT", "fiat"),
        ("WBTCUSDT", "wrapped or pegged"), ("PAXGUSDT", "wrapped or pegged"), ("BTCUPUSDT", "leveraged token"),
        ("1INCHDOWNUSDT", "leveraged token"), ("ETHBULLUSDT", "leveraged token"), ("BEARUSDT", "leveraged token"),
        ("XUPUSDT", None),
    ],
)
def test_exclusions_by_hand(symbol, why):
    assert M.exclusion(symbol) == why


@pytest.mark.parametrize("bad", ["BTCUSD", "USDT", 7, "BTC"])
def test_base_of_refuses_other_symbols(bad):
    with pytest.raises(ValueError, match="not a Binance USDT symbol"):
        M.base_of(bad)


def test_the_universe_by_hand():
    """Monday t = 98: eligible = not excluded, a bar at t, a first bar at row <= 7, 30-day volume (rows 69..98) > 0.
    JUP and SPK2 tie at 30,000 (JUP first by symbol); NEW1 (first bar row 7) is in, NEW2 (row 8) out; GAP (no bar at
    t) out; SPK's only volume is at row 68, outside the window; the excluded coins trade most and never enter."""
    n, t = 100, 98
    spike = lambda row: [1e6 if i == row else 0.0 for i in range(n)]  # noqa: E731
    spk2 = [30000.0 if i == 69 else 0.0 for i in range(n)]
    frames = {
        "BTCUSDT": frame([100.0] * n, 800.0),
        "ETHUSDT": frame([50.0] * n, 700.0),
        "JUPUSDT": frame([1.0] * n, 1000.0),
        "SPK2USDT": frame([1.0] * n, spk2),
        "SPKUSDT": frame([1.0] * n, spike(68)),
        "NEW1USDT": frame([None] * 7 + [1.0] * (n - 7), 900.0),
        "NEW2USDT": frame([None] * 8 + [1.0] * (n - 8), 5000.0),
        "GAPUSDT": frame([1.0] * t + [None, 1.0], 5000.0),
        **{f"{b}USDT": frame([1.0] * n, 5000.0) for b in ("USDC", "BTCUP", "EUR", "WBTC", "ETHBULL")},
        **{f"C{i:02d}USDT": frame([1.0] * n, 10.0 + i) for i in range(22)},
    }
    p = M.plan(wide(frames), {"lookback": 14, "k": 3, "filter": "none"})
    expected = ("JUPUSDT", "SPK2USDT", "NEW1USDT", "BTCUSDT", "ETHUSDT", *(f"C{i:02d}USDT" for i in range(21, 6, -1)))
    assert p["universe"][t] == expected
    assert sorted(p["universe"]) == list(range(0, n, 7))  # every Monday close, and only those


def test_the_universe_at_the_history_boundary():
    """Row 91 is the first Monday where a coin from row 0 is eligible (first bar <= t - 91)."""
    n = 99
    p = M.plan(wide({"BTCUSDT": frame([100.0] * n), "AUSDT": frame([None] + [1.0] * (n - 1))}),
               {"lookback": 7, "k": 2, "filter": "none"})
    assert p["universe"][84] == ()
    assert p["universe"][91] == ("BTCUSDT",)  # A's first bar is row 1 > 91 - 91
    assert p["universe"][98] == ("AUSDT", "BTCUSDT")  # equal volume: ascending symbol


# ------------------------------------------------------------------------------------------------ the rule


def ranking_panel():
    """t = 98, L = 14: R = 0.5 (A), 0.3 (E: no bar at row 84, its close at row 83 counts), 0.2 (B and F, a tie),
    0.0 exactly (C), -0.2 (D)."""
    path = lambda end: [100.0] * 85 + [end] * 14  # noqa: E731
    e = [100.0] * 84 + [None] + [130.0] * 14
    return wide({
        "BTCUSDT": frame(path(100.0)), "AUSDT": frame(path(150.0)), "BUSDT": frame(path(120.0)),
        "CUSDT": frame(path(100.0)), "DUSDT": frame(path(80.0)), "EUSDT": frame(e), "FUSDT": frame(path(120.0)),
    })


@pytest.mark.parametrize(
    ("k", "filt", "selected"),
    [
        (3, "none", ("AUSDT", "EUSDT", "BUSDT")),
        (4, "none", ("AUSDT", "EUSDT", "BUSDT", "FUSDT")),
        (7, "abs_mom", ("AUSDT", "EUSDT", "BUSDT", "FUSDT")),  # C (R = 0) and D drop out
        (7, "btc_sma200", ()),  # no 200 closes: nothing
        (20, "none", ("AUSDT", "EUSDT", "BUSDT", "FUSDT", "BTCUSDT", "CUSDT", "DUSDT")),
    ],
)
def test_the_ranking_and_filters_by_hand(k, filt, selected):
    p = M.plan(ranking_panel(), {"lookback": 14, "k": k, "filter": filt})
    assert p["selected"][98] == selected
    assert p["schedule"][98] == {s: 1.0 / k for s in sorted(selected)}
    ranked = dict(p["ranked"][98])
    assert ranked["AUSDT"] == 0.5 and ranked["CUSDT"] == 0.0 and ranked["EUSDT"] == pytest.approx(0.3, abs=1e-15)


def test_a_lookback_past_a_coin_s_history_leaves_it_unranked():
    p = M.plan(ranking_panel(), {"lookback": 99, "k": 3, "filter": "none"})
    assert p["ranked"][98] == ()
    p = M.plan(ranking_panel(), {"lookback": 98, "k": 3, "filter": "none"})
    assert len(p["ranked"][98]) == 7


@pytest.mark.parametrize(("last", "on"), [(100.0, False), (101.0, True), (None, False)])
def test_the_btc_sma200_filter_is_strict(last, on):
    """t = 245: 200 closes rows 46..245. All 100 -> mean 100, not strictly above; 101 -> on; a missing close -> off."""
    n = 246
    btc = [100.0] * (n - 1) + [101.0 if last == 101.0 else 100.0]
    if last is None:
        btc[100] = None
    p = M.plan(wide({"BTCUSDT": frame(btc), "AUSDT": frame([1.0] * 240 + [2.0] * 6)}),
               {"lookback": 14, "k": 2, "filter": "btc_sma200"})
    assert p["selected"][245] == (("AUSDT", "BTCUSDT") if on else ())


@pytest.mark.parametrize(
    ("params", "match"),
    [
        ({"lookback": 14, "k": 21, "filter": "none"}, "k must be <= 20"),
        ({"lookback": 14, "k": 3, "filter": "sma"}, "filter must be one of"),
        ({"lookback": 0, "k": 3, "filter": "none"}, "lookback must be >= 1"),
        ({"lookback": 14, "k": 3, "filter": "none", "seed": 1}, "unknown params"),
        ({"lookback": 14, "k": 3}, "filter must be one of"),
    ],
)
def test_bad_params_are_refused(params, match):
    with pytest.raises(ValueError, match=match):
        M.momentum(params, ranking_panel(), ZERO)


def test_the_null_keeps_the_rule_s_count_cash_and_swaps():
    panel = wide(random_frames(3, n=400, m=12))
    params = {"lookback": 28, "k": 5, "filter": "abs_mom"}
    rule = M.plan(panel, params)
    null = M.plan(panel, params, np.random.default_rng(11))
    prev_r = prev_n = set()
    for t in rule["selected"]:
        r, z = set(rule["selected"][t]), set(null["selected"][t])
        ranked = {s for s, _ in rule["ranked"][t]}
        assert len(z) == len(r) and z <= ranked
        kept = min(len(r & prev_r), len(prev_n & ranked), len(r))
        fresh = len(ranked - prev_n)
        assert len(z & prev_n) == (kept if fresh >= len(r) - kept else len(r) - fresh)
        prev_r, prev_n = r, z
    assert null["selected"] != rule["selected"]
    with pytest.raises(ValueError, match="missing required param 'seed'"):
        M.random_select(params, panel, ZERO)
    a = M.random_select({**params, "seed": 11}, panel, ZERO)
    b = M.random_select({**params, "seed": 11}, panel, ZERO)
    assert a["ret"].equals(b["ret"]) and a.attrs["selected"] == null["selected"]


# ------------------------------------------------------------------------------------------------ the engine


def test_delisting_sells_at_the_last_close_with_the_haircut():
    """X bought at row 1 (500 units at 10); its data ends at row 5 (close 20): sold at row 6 at 20 x 0.7."""
    n = 10
    panel = wide({"BTCUSDT": frame([100.0] * n), "XUSDT": frame([10.0, 10, 12, 12, 15, 20] + [None] * 4)})
    res = M.simulate(panel, ZERO, {0: {"XUSDT": 0.5}})
    v5, v6 = 5000.0 + 500.0 * 20.0, 5000.0 + 500.0 * 20.0 * (1.0 - 0.30)
    assert res["ret"].iloc[6] == pytest.approx(v6 / v5 - 1.0, rel=1e-15)
    assert res["turnover"].iloc[6] == pytest.approx(10000.0 / v5, rel=1e-15)
    assert res["cost"].iloc[6] == pytest.approx(3000.0 / v5, rel=1e-12)
    assert res["n_held"].tolist() == [0, 1, 1, 1, 1, 1, 0, 0, 0, 0]
    f = res.attrs["fills"]
    assert f["forced"].tolist() == [False, True] and f["price"].tolist() == [10.0, 20.0]
    assert res.attrs["forced"] == 1 and res.attrs["n_trades"] == 2
    assert math.prod(1.0 + res.attrs["trade_returns"]) == pytest.approx(math.prod(1.0 + res["ret"]), rel=1e-12)


def test_a_missing_day_forces_a_sale_and_a_coin_without_a_fill_bar_is_not_bought():
    n = 12
    panel = wide({"BTCUSDT": frame([100.0] * n), "YUSDT": frame([10.0] * 6 + [None] + [10.0] * 5)})
    res = M.simulate(panel, ZERO, {0: {"YUSDT": 0.5}, 5: {"YUSDT": 0.5}, 8: {"YUSDT": 0.5}})
    assert res["n_held"].tolist() == [0, 1, 1, 1, 1, 1, 0, 0, 0, 1, 1, 1]
    assert res["ret"].iloc[6] == pytest.approx(-0.15, rel=1e-12)  # half the book loses 30%
    assert res.attrs["orders"].tolist() == [0, 5, 8]


def test_a_forced_sale_never_pays_more_than_its_proceeds():
    big = Costs(pool_fee_bps=0.0, slippage_bps=((1.0, 0.0),), gas_usd_per_trade=1e6, capital_usd=1e12)
    panel = wide({"BTCUSDT": frame([100.0] * 6), "XUSDT": frame([10.0] * 3 + [None] * 3)})
    res = M.simulate(panel, M.CoinCosts(big, big), {0: {"XUSDT": 1e-10}})
    f = res.attrs["fills"]
    assert f.loc[f["forced"], "cost"].iloc[0] == pytest.approx(f.loc[f["forced"], "usd"].iloc[0], rel=1e-12)


def test_a_fill_costing_the_whole_book_raises():
    big = Costs(pool_fee_bps=0.0, slippage_bps=((1.0, 0.0),), gas_usd_per_trade=1e5)
    panel = wide({"BTCUSDT": frame([100.0] * 4), "XUSDT": frame([10.0] * 4)})
    with pytest.raises(ValueError, match="cannot pay them"):
        M.simulate(panel, M.CoinCosts(big, big), {0: {"XUSDT": 0.5}})


@pytest.mark.parametrize(
    ("schedule", "match"),
    [
        ({9: {"XUSDT": 0.5}}, "bad schedule entry"),
        ({0: {"QUSDT": 0.5}}, "bad schedule entry"),
        ({0: {"XUSDT": -0.1}}, "bad schedule entry"),
        ({0: {"XUSDT": 0.6, "BTCUSDT": 0.4 + 1e-9}}, "bad schedule entry"),
        ({0.0: {"XUSDT": 0.5}}, "bad schedule entry"),
        ({3: {"XUSDT": 0.5}}, "no bar at its decision row"),
    ],
)
def test_bad_schedules_are_refused(schedule, match):
    panel = wide({"BTCUSDT": frame([100.0] * 5), "XUSDT": frame([10.0] * 3 + [None, 10.0])})
    with pytest.raises(ValueError, match=match):
        M.simulate(panel, ZERO, schedule)
    with pytest.raises(ValueError, match="costs must be a CoinCosts"):
        M.simulate(panel, Costs.zero(), {})


def unit_book(panel: pd.DataFrame, costs: M.CoinCosts, schedule) -> pd.DataFrame:
    """An independent book of coin units and USDC cash (PLAN.md sections 5-7), written apart from the engine."""
    syms = sorted(set(panel.columns.get_level_values(0)))
    o = {s: panel[(s, "open")].to_numpy() for s in syms}
    c = {s: panel[(s, "close")].to_numpy() for s in syms}
    cash, units, last, prev = costs.capital_usd, {}, {}, costs.capital_usd
    out = []
    for t in range(1, len(panel)):
        for s in syms:
            if np.isfinite(c[s][t - 1]):
                last[s] = c[s][t - 1]
        here = {s for s in syms if np.isfinite(c[s][t])}
        before = cash + sum(u * (o[s][t] if s in here else last[s]) for s, u in units.items())
        paid = traded = 0.0
        for s in sorted(set(units) - here):
            usd = units.pop(s) * last[s]
            gross = usd * 0.7
            fee = min(gross * costs.costs_for(s).rate(gross) + costs.costs_for(s).gas_usd_per_trade, gross)
            cash, paid, traded = cash + gross - fee, paid + usd - gross + fee, traded + usd
        if t - 1 in schedule:
            v_open = cash + sum(u * o[s][t] for s, u in units.items())
            want = {s: w for s, w in schedule[t - 1].items() if w > 0 and s in here}
            fees = 0.0
            for s in set(units) | set(want):
                usd = abs(want.get(s, 0.0) - units.get(s, 0.0) * o[s][t] / v_open) * v_open
                if usd > 0:
                    cc = costs.costs_for(s)
                    fees, traded = fees + usd * cc.rate(usd) + cc.gas_usd_per_trade, traded + usd
            paid += fees
            units = {s: w * (v_open - fees) / o[s][t] for s, w in want.items()}
            cash = max(0.0, 1.0 - sum(want.values())) * (v_open - fees)
        value = cash + sum(u * c[s][t] for s, u in units.items())
        out.append((value / prev - 1.0, traded / before if traded else 0.0, paid / before if traded else 0.0))
        prev = value
    return pd.DataFrame([(0.0, 0.0, 0.0), *out], columns=["ret", "turnover", "cost"], index=panel.index)


@given(seed=st.integers(0, 10**6), params=PARAMS, costs=st.sampled_from(sorted(COSTS)), null=st.booleans())
@example(seed=5, params={"lookback": 14, "k": 20, "filter": "none"}, costs="2x", null=False)
def test_accounting_equals_an_independent_book(seed, params, costs, null):
    panel = wide(random_frames(seed))
    cc = COSTS[costs]
    res = M.random_select({**params, "seed": seed}, panel, cc) if null else M.momentum(params, panel, cc)
    sched = M.plan(panel, params, np.random.default_rng(seed) if null else None)["schedule"]
    book = unit_book(panel, cc, sched)
    for col in ("ret", "turnover", "cost"):
        np.testing.assert_allclose(res[col], book[col], rtol=1e-12, atol=1e-15)
    validate_result(res, pd.DataFrame(index=panel.index))
    assert (res["turnover"] > 0).sum() == res.attrs["n_trades"] == len(res.attrs["trade_returns"])
    assert math.prod(1.0 + res.attrs["trade_returns"]) == pytest.approx(math.prod(1.0 + res["ret"]), rel=1e-11)
    f = res.attrs["fills"][~res.attrs["fills"]["forced"]]
    assert f["cost"].tolist() == [cc.leg_cost(s, u) for s, u in zip(f["symbol"], f["usd"], strict=True)]


def two_coin(seed: int, n: int = 300):
    from lab.data.synthetic import synthetic_market

    mk = synthetic_market(n, seed=seed, start=START)
    for f in mk.values():
        f["quote_volume"] = f["volume"] * f["close"]
    return pf.make_panel(mk, snapshot_id="s"), wide({"BTCUSDT": mk["BTC"], "ETHUSDT": mk["ETH"]})


def weight(top: float):
    return st.one_of(st.just(0.0), st.floats(1e-6, top))  # subnormal targets: the engines' round-off differs (#54)


@given(seed=st.integers(0, 10**5), w=st.tuples(weight(0.6), weight(0.4)), every=st.integers(1, 40),
       costs=st.sampled_from(["zero", "1x", "2x"]))
def test_two_coins_with_fixed_targets_equal_portfolio(seed, w, every, costs):
    panel, mp = two_coin(seed)
    cc = COSTS[costs]
    ref = pf._simulate(panel, cc.major, lambda t, _: w if t % every == 0 else None)
    res = M.hold_fixed({"weights": {"BTCUSDT": w[0], "ETHUSDT": w[1]}, "every": every}, mp, cc)
    for col in ("ret", "position", "turnover", "cost"):
        np.testing.assert_allclose(res[col], ref[col], rtol=1e-12, atol=1e-15)
    assert res.attrs["n_trades"] == ref.attrs["n_trades"]


def test_the_rule_on_btc_and_eth_alone_is_a_monday_50_50_rebalance():
    panel, mp = two_coin(4, n=400)
    mondays = {t for t in range(91, 400) if mp.index[t].day_of_week == 0}
    ref = pf._simulate(panel, ONE.major, lambda t, _: (0.5, 0.5) if t in mondays else None)
    res = M.momentum({"lookback": 28, "k": 2, "filter": "none"}, mp, ONE)
    np.testing.assert_allclose(res["ret"], ref["ret"], rtol=1e-12, atol=1e-15)
    b = M.basket({}, mp, ONE)
    np.testing.assert_allclose(b["ret"], ref["ret"], rtol=1e-12, atol=1e-15)
    held = M.hold_fixed({"weights": {"BTCUSDT": 1.0}, "every": None}, mp, ONE)
    assert held.attrs["orders"].tolist() == [0] and (held["position"].iloc[1:] == 1.0).all()


# ------------------------------------------------------------------------------------------------ no look-ahead


def tampered(frames: dict, cut_ts, rng) -> dict:
    out = {}
    for s, f in frames.items():
        f = f.copy()
        later = f.index >= cut_ts
        k = np.exp(rng.normal(0.0, 0.3, later.sum()))
        for col in ("open", "high", "low", "close"):
            f.loc[later, col] *= k
        f.loc[later, ["volume", "quote_volume"]] *= np.exp(rng.normal(0.0, 1.0, (later.sum(), 1)))
        f = f[~later] if s == "R0USDT" else f  # R0's data ends at the cut
        if len(f):
            out[s] = f
    new = frames["BTCUSDT"].loc[cut_ts:].copy()
    out["AAAUSDT"] = new.assign(quote_volume=1e12)
    return out


@given(seed=st.integers(0, 10**6), cut=st.integers(92, 258), params=PARAMS, null=st.booleans())
@example(seed=1, cut=98, params={"lookback": 14, "k": 3, "filter": "abs_mom"}, null=True)
def test_no_look_ahead_in_the_universe_ranking_targets_and_results(seed, cut, params, null):
    frames = random_frames(seed)
    a, b = wide(frames), wide(tampered(frames, frames["BTCUSDT"].index[cut], np.random.default_rng(seed)))
    rng = (lambda: np.random.default_rng(seed)) if null else (lambda: None)
    pa, pb = M.plan(a, params, rng()), M.plan(b, params, rng())
    for key in ("universe", "ranked", "selected", "schedule"):
        assert {t: v for t, v in pa[key].items() if t < cut} == {t: v for t, v in pb[key].items() if t < cut}
    fn = M.random_select if null else M.momentum
    p = {**params, "seed": seed} if null else params
    ra, rb = fn(p, a, ONE), fn(p, b, ONE)
    pd.testing.assert_frame_equal(ra.iloc[:cut], rb.iloc[:cut])
    fa, fb = ra.attrs["fills"], rb.attrs["fills"]
    pd.testing.assert_frame_equal(fa[fa["bar"] < cut].reset_index(drop=True), fb[fb["bar"] < cut].reset_index(drop=True))


def test_touch_the_present_moves_the_monday_ranking():
    panel = ranking_panel()
    p = M.plan(panel, {"lookback": 14, "k": 1, "filter": "none"})
    panel2 = panel.copy()
    panel2.loc[panel.index[98], ("DUSDT", "close")] = 200.0
    panel2.loc[panel.index[98], ("DUSDT", "high")] = 200.0
    p2 = M.plan(panel2, {"lookback": 14, "k": 1, "filter": "none"})
    assert p["selected"][98] == ("AUSDT",) and p2["selected"][98] == ("DUSDT",)


def test_a_slice_with_the_warmup_decides_as_the_full_panel():
    panel = wide(random_frames(9, n=600))
    params = {"lookback": 91, "k": 5, "filter": "btc_sma200"}
    full = M.plan(panel, params)
    for start in (50, 137, 300):
        part = M.plan(panel.iloc[start:], params)
        for t, sel in part["selected"].items():
            if t >= M.WARMUP:
                assert sel == full["selected"][t + start] and part["universe"][t] == full["universe"][t + start]


def test_stitch_is_walk_forward_optimize_s_oos_returns(tmp_path):
    from functools import partial

    from lab.search.space import Param
    from lab.search.study import SearchConfig

    panel = wide(random_frames(2, n=700))
    folds = walk_forward(700, 700 - 2 * 150, 150, expanding=True)
    specs = [Param("lookback", "cat", choices=(14, 28)), Param("k", "cat", choices=(3,)),
             Param("filter", "cat", choices=("none",))]
    fn = partial(M.momentum, costs=ONE)
    wf = walk_forward_optimize("m", fn, specs, panel, folds, tmp_path, SearchConfig(n_trials=3, n_workers=1),
                               warmup=M.WARMUP)
    chosen = [{"lookback": int(r.p_lookback), "k": int(r.p_k), "filter": r.p_filter} for r in wf["folds"].itertuples()]
    s = M.stitch(fn, chosen, panel, folds)
    assert s.index.equals(wf["oos_returns"].index) and np.array_equal(s, wf["oos_returns"])
    fr = M.stitch_frame(fn, chosen, panel, folds)
    assert list(fr.columns) == list(M.KEPT_COLUMNS) and fr.attrs["forced"] >= 0


# ------------------------------------------------------------------------------------------------ costs, config


def test_coin_costs_read_the_small_coin_multiplier(tmp_path):
    cc = M.coin_costs()
    assert cc.minor.pool_fee_bps == 2 * cc.major.pool_fee_bps
    assert cc.minor.slippage_bps == tuple((s, 2 * b) for s, b in cc.major.slippage_bps)
    assert cc.minor.gas_usd_per_trade == cc.major.gas_usd_per_trade
    assert cc.minor.aggregator_fee_bps == cc.major.aggregator_fee_bps
    assert cc.leg_cost("SOLUSDT", 1000.0) == pytest.approx(1000.0 * (10 + 30) / 1e4 + 0.10, rel=1e-15)
    assert cc.leg_cost("ETHUSDT", 1000.0) == pytest.approx(1000.0 * (5 + 15) / 1e4 + 0.10, rel=1e-15)
    s = cc.stressed(2.0)
    assert s.minor.pool_fee_bps == 20 and s.minor.gas_usd_per_trade == 0.2
    text = (M.CONFIG_DIR / "costs.yaml").read_text()
    for bad in ("", "small_coin_cost_multiplier: 0.5\n", "small_coin_cost_multiplier: true\n"):
        body = "\n".join(x for x in text.splitlines() if not x.startswith("small_coin")) + "\n" + bad
        (tmp_path / "costs.yaml").write_text(body)
        with pytest.raises(ValueError, match="small_coin_cost_multiplier must be a number >= 1"):
            M.coin_costs(tmp_path)


def test_bold_budget_is_read_from_the_file(tmp_path):
    assert M.bold_budget() == 0.60
    (tmp_path / "risk_levels.yaml").write_text("bold:\n  max_drawdown_budget_pct: TBD\n")
    assert M.bold_budget(tmp_path) is None
    (tmp_path / "risk_levels.yaml").write_text("steady: {}\n")
    assert M.bold_budget(tmp_path) is None


# ------------------------------------------------------------------------------------------------ the panel


def _bad(panel, how):
    p = panel.copy()
    if how == "type":
        return p.to_numpy()
    if how == "names":
        p.columns = p.columns.set_names(["a", "b"])
    elif how == "order":
        p = p[p.columns[::-1]]
    elif how == "symbol":
        p.columns = pd.MultiIndex.from_tuples([("BTCUSD", f) for _, f in p.columns], names=["symbol", "field"])
    elif how == "nobtc":
        p.columns = pd.MultiIndex.from_tuples([("XXUSDT", f) for _, f in p.columns], names=["symbol", "field"])
    elif how == "dtype":
        p = p.astype(object)
    elif how == "index":
        p.index = p.index.as_unit("ns")
    elif how == "rows":
        p = p.iloc[:1]
    elif how == "gap":
        p = p.drop(p.index[2])
    elif how == "hour":
        p.index = p.index + pd.Timedelta(hours=1)
    elif how == "attrs":
        p.attrs = {}
    elif how == "partial":
        p.iloc[1, 0] = np.nan
    elif how == "price":
        p.iloc[1, 3] = -1.0
    elif how == "volume":
        p.iloc[1, 5] = -1.0
    elif how == "ohlc":
        p.iloc[1, 1] = p.iloc[1, 3] * 0.5
    return p


@pytest.mark.parametrize(
    ("how", "match"),
    [("type", "must be a pandas DataFrame"), ("names", "MultiIndex named"), ("order", "fields"),
     ("symbol", "not a Binance USDT symbol"), ("nobtc", "must hold BTCUSDT"), ("dtype", "float64"),
     ("index", "microseconds"), ("rows", "at least 2 rows"), ("gap", "one day apart"), ("hour", "00:00 UTC"),
     ("attrs", "snapshot_id"), ("partial", "all NaN"), ("price", "non-positive"), ("volume", "negative volume"),
     ("ohlc", "low <= open")],
)
def test_bad_panels_are_refused(how, match):
    panel = wide({"BTCUSDT": frame([100.0, 101.0, 99.0, 100.0])})
    with pytest.raises(ValueError, match=match):
        M.validate_wide(_bad(panel, how))


def test_make_wide_panel_refuses_bad_frames():
    good = frame([1.0, 2.0])
    with pytest.raises(ValueError, match="non-empty mapping"):
        M.make_wide_panel({}, snapshot_id="x")
    with pytest.raises(ValueError, match="lacks"):
        M.make_wide_panel({"BTCUSDT": good.drop(columns="quote_volume")}, snapshot_id="x")
    with pytest.raises(ValueError, match="tz-aware"):
        M.make_wide_panel({"BTCUSDT": good.tz_localize(None)}, snapshot_id="x")
    with pytest.raises(ValueError, match="00:00 UTC"):
        M.make_wide_panel({"BTCUSDT": good.set_axis(good.index + pd.Timedelta(hours=1))}, snapshot_id="x")
    with pytest.raises(ValueError, match="holds NaN"):
        M.make_wide_panel({"BTCUSDT": good.assign(volume=np.nan)}, snapshot_id="x")


# ------------------------------------------------------------------------------------------------ gates


BASE = {"sharpe": 1.5, "sharpe_2x": 1.0, "dsr_strict": 0.99, "pbo": 0.1, "plateau": [1.2] * 4, "mc_p5": -0.5,
        "budget": 0.6, "bench": {"B1": 1.0, "B2": 1.0, "B3": 1.0}, "regimes_pass": True}


@pytest.mark.parametrize(
    ("change", "gate", "outcome"),
    [
        ({"sharpe": 1.0, "plateau": [0.7] * 4, "bench": {"B1": 0.9, "B2": 0.9, "B3": 0.9}}, "G1", "PASS"),
        ({"sharpe": math.nextafter(1.0, 0), "bench": {"B1": 0.9, "B2": 0.9, "B3": 0.9}}, "G1", "FAIL"),
        ({"sharpe_2x": 0.5}, "G2", "FAIL"),
        ({"dsr_strict": 0.95}, "G3", "PASS"),
        ({"dsr_strict": math.nan}, "G3", "MISSING"),
        ({"pbo": 0.25}, "G4", "PASS"),
        ({"pbo": math.nextafter(0.25, 1)}, "G4", "FAIL"),
        ({"plateau": [0.7 * 1.5] * 4}, "G5", "PASS"),
        ({"plateau": [1.2, 1.2, 1.2, math.nextafter(0.7 * 1.5, 0)]}, "G5", "FAIL"),
        ({"mc_p5": -0.6}, "G6", "PASS"),
        ({"mc_p5": math.nextafter(-0.6, -1)}, "G6", "FAIL"),
        ({"budget": None}, "G6", "MISSING"),
        ({"bench": {"B1": 1.0, "B2": 1.5, "B3": 1.0}}, "G7", "FAIL"),
        ({"bench": {"B1": 1.0, "B2": 1.0}}, "G7", "FAIL"),
        ({"regimes_pass": False}, "G8", "FAIL"),
        ({"regimes_pass": None}, "G8", "MISSING"),
    ],
)
def test_the_gates_at_their_boundaries(change, gate, outcome):
    g = M.gate_table({**BASE, **change})
    assert g[gate] == outcome
    assert all(v == "PASS" for k, v in g.items() if k != gate)


def test_the_plateau_fails_whenever_sharpe_is_not_positive():
    assert M.gate_table({**BASE, "sharpe": 0.0, "plateau": [5.0] * 4})["G5"] == "FAIL"


@pytest.mark.parametrize(("p", "e1", "verdict"), [(0.05, "HOLDS", "CANDIDATE FOR AUDIT"),
                                                  (math.nextafter(0.05, 1), "FAILS", "NOT A CANDIDATE"),
                                                  (math.nan, "MISSING", "NOT A CANDIDATE")])
def test_the_verdict(p, e1, verdict):
    v = M.verdict(M.gate_table(BASE), p)
    assert (v["e1"], v["verdict"]) == (e1, verdict)
    assert M.verdict({**M.gate_table(BASE), "G4": "MISSING"}, 0.01)["failing"] == ["G4"]


def test_plateau_steps_by_hand():
    steps = M.plateau_steps([{"lookback": 14, "k": 3, "filter": "none"}, {"lookback": 91, "k": 20, "filter": "abs_mom"}])
    got = [(s["param"], s["factor"], [(f["lookback"], f["k"]) for f in s["folds"]]) for s in steps]
    assert got == [
        ("lookback", 0.8, [(11, 3), (73, 20)]), ("lookback", 1.2, [(17, 3), (109, 20)]),
        ("k", 0.8, [(14, 2), (91, 16)]), ("k", 1.2, [(14, 4), (91, 20)]),
    ]
    assert M.plateau_steps([{"lookback": 1, "k": 1, "filter": "none"}])[0]["folds"][0]["lookback"] == 1
