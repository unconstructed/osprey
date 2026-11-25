"""The multi-asset reference rebalancer (``lab/runner/portfolio.py``): panel format, execution model, rules and
benchmarks. Scouting code (tests, demos and scouting only), held to the backtest contract's standard.

Execution model under test (module docstring of ``lab/runner/portfolio.py``): a decision at the close of bar t
fills at the OPEN of bar t+1; an order is the full target vector; each asset's change is its own swap against
USDC at its own open, paying ``Costs.rate`` on that leg's USD size plus gas per leg; the fill re-cuts the book to
the targets of what is left after costs; between fills the book holds coin units and cash.

The accounting is checked by an independent re-computation in coin units and cash (``unit_book``), not by the
weight recursion the engine uses.
"""

from __future__ import annotations

import copy
import hashlib
import math
import pickle
import re
import shutil
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest
from hypothesis import assume, example, given
from hypothesis import strategies as st

from lab.config import CONFIG_DIR, load_yaml
from lab.data.synthetic import synthetic_market
from lab.runner import holdmix, reference
from lab.runner import portfolio as pf
from lab.runner.interface import BAR_COLUMNS, RESULT_COLUMNS, WEIGHT_TOL, validate_bars, validate_result
from lab.runner.reference import Costs
from lab.search.objective import evaluate_params
from lab.search.report import gates, overfitting_report
from lab.search.space import Param
from lab.search.study import SearchConfig, load_trial_returns, run_study
from lab.search.walkforward import walk_forward_optimize
from lab.validation.splits import walk_forward

ASSETS = pf.ASSETS
ALL_COLUMNS = list(RESULT_COLUMNS) + list(pf.WEIGHT_COLUMNS)
CAPITAL = Costs().capital_usd
COST_MODELS = (
    Costs(),
    Costs().stressed(),
    Costs(pool_fee_bps=30.0, aggregator_fee_bps=10.0, gas_usd_per_trade=25.0),
)
FLAT_RATE = Costs(pool_fee_bps=20.0, slippage_bps=((1.0, 0.0),), gas_usd_per_trade=0.0)  # 20 bps, any size
GOOD = {"w_btc": 0.4, "w_eth": 0.3, "band": 0.02, "every": 3}

# ------------------------------------------------------------------------------------------------ helpers


def random_bars(n: int, seed: int, vol: float, gap: float, start: float) -> pd.DataFrame:
    """Valid daily bars with overnight gaps (open != previous close): ``vol`` is the std of log(close/open),
    ``gap`` the std of log(open/previous close)."""
    rng = np.random.default_rng(seed)
    body = rng.normal(0.0, vol, n)
    gaps = rng.normal(0.0, gap, n)
    gaps[0] = 0.0
    log_close = math.log(start) + np.cumsum(gaps + body)
    close = np.exp(log_close)
    open_ = np.exp(log_close - body)
    wick = rng.uniform(0.0, 0.02, (2, n))
    index = pd.date_range("2021-01-01", periods=n, freq="D", tz="UTC", name="ts")
    return pd.DataFrame(
        {
            "open": open_,
            "high": np.maximum(open_, close) * (1.0 + wick[0]),
            "low": np.minimum(open_, close) * (1.0 - wick[1]),
            "close": close,
            "volume": rng.uniform(100.0, 1000.0, n),
        },
        index=index,
    )


def random_panel(n: int, seed: int, vols=(0.04, 0.05), gaps=(0.01, 0.01)) -> pd.DataFrame:
    frames = {
        "BTC": random_bars(n, seed, vols[0], gaps[0], 30_000.0),
        "ETH": random_bars(n, seed + 1, vols[1], gaps[1], 2_000.0),
    }
    return pf.make_panel(frames, snapshot_id="test-panel")


def bars_from(opens, closes) -> pd.DataFrame:
    """Hand-built bars with explicit opens (for overnight gaps); wicks of 0.5% around the body."""
    o = np.asarray(opens, dtype=float)
    c = np.asarray(closes, dtype=float)
    index = pd.date_range("2020-01-01", periods=len(c), freq="D", tz="UTC", name="ts")
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


def hand_panel(make_bars, btc, eth) -> pd.DataFrame:
    """Two-asset panel from close paths (``make_bars``: open = previous close, so no overnight gaps)."""
    return pf.make_panel({"BTC": make_bars(btc), "ETH": make_bars(eth)}, snapshot_id="hand")


@st.composite
def panels(draw, min_size: int = 20, max_size: int = 120) -> pd.DataFrame:
    n = draw(st.integers(min_size, max_size))
    seed = draw(st.integers(0, 2**32 - 1))
    vols = tuple(draw(st.sampled_from([0.0, 0.01, 0.04, 0.1])) for _ in ASSETS)  # 0.0: flat bodies
    gaps = tuple(draw(st.sampled_from([0.0, 0.005, 0.03])) for _ in ASSETS)
    return random_panel(n, seed, vols, gaps)


@st.composite
def targets(draw) -> tuple[float, float]:
    w_btc = draw(st.one_of(st.sampled_from([0.0, 0.25, 0.4, 0.5, 0.6, 1.0]), st.floats(0.0, 1.0)))
    w_eth = draw(st.one_of(st.sampled_from([0.0, 0.2, 0.4, 1.0 - w_btc]), st.floats(0.0, 1.0 - w_btc)))
    assume(w_btc + w_eth <= 1.0)
    return w_btc, w_eth


@st.composite
def rebalance_params(draw) -> dict:
    w_btc, w_eth = draw(targets())
    params = {
        "w_btc": w_btc,
        "w_eth": w_eth,
        "band": draw(st.sampled_from([0.0, 0.005, 0.02, 0.1, 1.0])),
        "every": draw(st.integers(1, 10)),
    }
    # limits a small slack from the targets, so that breaches happen (uniform limits rarely bind)
    slack = st.one_of(st.sampled_from([0.0, 0.005, 0.02, 0.05]), st.floats(0.0, 1.0))
    if draw(st.booleans()):
        params["min_cash"] = max(0.0, 1.0 - (w_btc + w_eth) - draw(slack))
    if draw(st.booleans()):
        params["max_coin"] = min(1.0, max(w_btc, w_eth) + draw(slack))
    return params


@st.composite
def cases(draw):
    """(panel, rule, params) for either rule: the generic guarantees hold for both."""
    panel = draw(panels())
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


def tamper_from(panel: pd.DataFrame, cut: int, seed: int) -> pd.DataFrame:
    """Change every field of every asset from bar ``cut`` on, except each asset's open of bar ``cut`` (the fill
    price of the decision taken at close cut-1), as ``tests/contract`` does for one asset."""
    rng = np.random.default_rng(seed)
    n = len(panel)
    frames = {}
    for asset in ASSETS:
        o, h, lo, c, v = (panel[(asset, f)].to_numpy(dtype=float, copy=True) for f in BAR_COLUMNS)
        c[cut:] *= np.exp(rng.normal(0.0, 0.2, n - cut))
        o[cut + 1 :] *= np.exp(rng.normal(0.0, 0.2, n - cut - 1))
        h[cut:] = np.maximum(o, c)[cut:] * (1.0 + rng.uniform(0.0, 0.05, n - cut))
        lo[cut:] = np.minimum(o, c)[cut:] * (1.0 - rng.uniform(0.0, 0.05, n - cut))
        v[cut:] = rng.uniform(1.0, 5000.0, n - cut)
        frames[asset] = pd.DataFrame(
            {"open": o, "high": h, "low": lo, "close": c, "volume": v}, index=panel.index
        )
    return pf.make_panel(frames, snapshot_id=panel.attrs["snapshot_id"])


def unit_book(panel: pd.DataFrame, target: dict[str, float], result: pd.DataFrame, costs: Costs):
    """Independent re-computation in coin units and USDC cash.

    At each fill bar of ``result``: value the book at the opens, swap each asset to ``target`` of the value left
    after costs (leg notional = |target * V_open - units * open|, leg cost = usd * rate(usd) + gas), then hold the
    units. Which legs trade is read from the engine's fill log: a leg trades when its weight change is > 0, and a
    change of round-off size (a book already at target to the last bit) is a judgement this book cannot repeat
    exactly. So ``dust`` returns the size (as a fraction of V_open) of every leg this book did NOT trade at an order's
    next open, for the caller to check that it is round-off. Returns the result columns, the per-leg log, V_open of
    every fill, the value at every close and ``dust``.

    A fill whose legs cost the whole book or more (paid >= V_open) cannot be paid: nothing would be left to swap. The
    book stops at that bar, with its cost share (>= 1) in ``cost`` and its V_open last in the list; later rows stay 0
    and later values NaN. The engine refuses the same fill (``run_checked``), so a run the engine completed must
    never stop the book.
    """
    n = len(panel)
    o = {a: panel[(a, "open")].to_numpy(dtype=float) for a in ASSETS}
    c = {a: panel[(a, "close")].to_numpy(dtype=float) for a in ASSETS}
    log = result.attrs["fills"]
    traded = {(int(b), a) for b, a in zip(log["bar"], log["asset"], strict=True)}
    fills = {int(t) for t in fill_bars_of(result)}
    probes = {int(t) + 1 for t in result.attrs["orders"]}
    units = dict.fromkeys(ASSETS, 0.0)
    cash = costs.capital_usd
    value = np.full(n, np.nan)
    value[0] = cash
    out = {col: np.zeros(n) for col in ALL_COLUMNS}
    legs: list[dict] = []
    v_open: list[float] = []
    dust: list[float] = []
    for t in range(1, n):
        if t in fills or t in probes:
            vo = cash + sum(units[a] * o[a][t] for a in ASSETS)
            usd = {a: abs(target[a] * vo - units[a] * o[a][t]) for a in ASSETS}
            dust += [usd[a] / vo for a in ASSETS if (t, a) not in traded]
        if t in fills:
            paid = 0.0
            for a in ASSETS:
                if (t, a) in traded:
                    leg_cost = usd[a] * costs.rate(usd[a]) + costs.gas_usd_per_trade
                    paid += leg_cost
                    before = units[a] * o[a][t] / vo
                    legs.append(
                        {
                            "bar": t,
                            "asset": a,
                            "side": "buy" if target[a] > before else "sell",
                            "units": usd[a] / o[a][t],
                            "price": o[a][t],
                            "usd": usd[a],
                            "cost": leg_cost,
                            "weight_before": before,
                            "weight_after": target[a],
                        }
                    )
            out["turnover"][t] = sum(usd[a] for a in ASSETS if (t, a) in traded) / vo
            out["cost"][t] = paid / vo
            v_open.append(vo)
            if paid >= vo:  # it cannot pay this fill: the book stops here
                break
            after = vo - paid
            units = {a: target[a] * after / o[a][t] for a in ASSETS}
            cash = (1.0 - sum(target.values())) * after
        value[t] = cash + sum(units[a] * c[a][t] for a in ASSETS)
        out["ret"][t] = value[t] / value[t - 1] - 1.0
        for a in ASSETS:
            out[f"w_{a}"][t] = units[a] * c[a][t] / value[t]
        out["position"][t] = out["w_BTC"][t] + out["w_ETH"][t]
    return out, legs, v_open, value, np.asarray(dust)


def target_of(params: dict) -> dict[str, float]:
    return {"BTC": float(params["w_btc"]), "ETH": float(params["w_eth"])}


def fill_bars_of(result: pd.DataFrame) -> np.ndarray:
    return np.flatnonzero(result["turnover"].to_numpy() > 0)


REFUSAL = re.compile(
    r"costs of the fill on (.+) are (\d+\.\d)% of a portfolio worth (\S+) USD: it cannot pay them "
    r"\(raise capital_usd or check the cost model\)"
)


def run_checked(rule, params: dict, panel: pd.DataFrame, costs: Costs) -> tuple[pd.DataFrame, pd.DataFrame]:
    """``(panel, rule(params, panel, costs))``; or, when the engine refuses a fill it cannot pay, that refusal
    checked against the independent book, and the engine's run on the bars before the refused fill.

    A drawn case can ruin the book (a crash and daily rebalancing at 25 USD of gas per leg: TESTING.md #49), and the
    engine raises on a fill costing the whole book or more (``test_a_fill_costing_exactly_the_whole_book_raises``).
    The refusal is right only if ``unit_book``, replaying the rule's orders with ``costs``, can pay every earlier fill
    and stops at the refused one: the same bar, and the message's cost share and book value are the book's to their
    printed digits (0.1% and 4 significant digits). The orders come from a zero-cost run of the rule, which never
    refuses (cost 0), and are the orders of the run with costs: a rule decides on the weights, which costs never
    change (``test_costs_off_vs_on_scale_each_bar_return``). The bars before the refused fill are then rerun through
    the engine with the same orders (the last of them, at the close before that fill, is never filled), so the
    caller's checks still cover every bar the engine accepted; their weights and turnover are the zero-cost run's
    bit for bit.
    """
    try:
        return panel, rule(params, panel, costs)
    except ValueError as exc:
        match = REFUSAL.fullmatch(str(exc))
        if match is None:
            raise
    t = panel.index.get_loc(pd.Timestamp(match[1]))
    free = rule(params, panel, Costs.zero())
    out, _, v_open, _, _ = unit_book(panel, target_of(params), free, costs)
    paid = out["cost"]
    # the book's first fill it cannot pay is the refused one: every earlier fill was payable
    np.testing.assert_array_equal(np.flatnonzero(paid >= 1.0), [t])
    assert paid[t] == pytest.approx(float(match[2]) / 100.0, abs=0.0005 + 1e-12, rel=1e-12)
    assert v_open[-1] == pytest.approx(float(match[3]), rel=5.000001e-4, abs=0.0)
    targets = (float(params["w_btc"]), float(params["w_eth"]))
    orders = set(free.attrs["orders"].tolist())
    before = pf._simulate(panel.iloc[:t], costs, lambda s, w: targets if s in orders else None)
    np.testing.assert_array_equal(before.attrs["orders"], free.attrs["orders"][free.attrs["orders"] < t - 1])
    for col in ("position", "turnover", *pf.WEIGHT_COLUMNS):
        np.testing.assert_array_equal(before[col].to_numpy(), free[col].to_numpy()[:t], err_msg=col)
    return panel.iloc[:t], before


# --------------------------------------------------------------------------------------------- the panel


def test_make_panel_builds_the_pinned_format(market):
    panel = pf.make_panel(market, snapshot_id="synthetic-21")
    pf.validate_panel(panel)
    assert list(panel.columns.names) == ["asset", "field"]
    assert list(panel.columns) == [
        (a, f) for a in ("BTC", "ETH") for f in ("open", "high", "low", "close", "volume")
    ]
    assert panel.index.name == "ts" and panel.index.unit == "us" and str(panel.index.tz) == "UTC"
    assert (panel.dtypes == np.float64).all()
    assert set(panel.attrs) == {"snapshot_id", "instruments", "bar_type", "alignment"}
    assert panel.attrs["snapshot_id"] == "synthetic-21"
    assert panel.attrs["instruments"] == {"BTC": "BTC", "ETH": "ETH"}
    for asset in ASSETS:
        np.testing.assert_array_equal(panel[asset].to_numpy(), market[asset][list(BAR_COLUMNS)].to_numpy())
        assert (panel.index == market[asset].index).all()


def test_make_panel_takes_explicit_attrs_and_rejects_bad_frames(market):
    panel = pf.make_panel(
        market,
        snapshot_id="abc",
        instruments={"BTC": "BTC/USD.X", "ETH": "ETH/USD.X"},
        bar_type={"BTC": "BTC/USD.X-1-DAY", "ETH": "ETH/USD.X-1-DAY"},
        alignment={"rule": "given"},
    )
    assert panel.attrs["instruments"]["ETH"] == "ETH/USD.X"
    assert panel.attrs["bar_type"]["BTC"] == "BTC/USD.X-1-DAY"
    assert panel.attrs["alignment"] == {"rule": "given"}
    with pytest.raises(ValueError, match=r"make_panel: frames must map exactly \('BTC', 'ETH'\)"):
        pf.make_panel({"BTC": market["BTC"]}, snapshot_id="x")
    with pytest.raises(ValueError, match="make_panel: frames must map exactly"):
        pf.make_panel([market["BTC"], market["ETH"]], snapshot_id="x")
    with pytest.raises(ValueError, match="every asset needs the same index"):
        pf.make_panel({"BTC": market["BTC"], "ETH": market["ETH"].iloc[1:]}, snapshot_id="x")
    with pytest.raises(ValueError, match="make_panel: asset ETH: bars contain NaN"):
        eth = market["ETH"].copy()
        eth.iloc[3, 3] = np.nan
        pf.make_panel({"BTC": market["BTC"], "ETH": eth}, snapshot_id="x")
    with pytest.raises(ValueError, match="snapshot_id'] must be a non-empty string"):
        pf.make_panel(market, snapshot_id="")


def test_panel_survives_slicing_and_pickling(market):
    """lab/search slices bars with ``bars.iloc[...]`` and spawn workers pickle them: both keep a valid panel."""
    panel = pf.make_panel(market, snapshot_id="synthetic-21")
    for piece in (panel.iloc[100:400], panel.iloc[np.arange(50, 90)], pickle.loads(pickle.dumps(panel))):
        pf.validate_panel(piece)
        assert piece.attrs == panel.attrs


def _breaker(fn):
    def apply(panel: pd.DataFrame) -> pd.DataFrame:
        bad = panel.copy()
        bad.attrs = copy.deepcopy(panel.attrs)
        return fn(bad)

    return apply


def _set_attr(key, value):
    def fn(p):
        p.attrs[key] = value
        return p

    return _breaker(fn)


def _drop_attr(key):
    def fn(p):
        del p.attrs[key]
        return p

    return _breaker(fn)


def _set_value(asset, field, row, value):
    def fn(p):
        p.iloc[row, p.columns.get_loc((asset, field))] = value
        return p

    return _breaker(fn)


def _with_columns(columns):
    def fn(p):
        p.columns = columns
        return p

    return _breaker(fn)


def _with_index(transform):
    def fn(p):
        p.index = transform(p.index)
        return p

    return _breaker(fn)


def _reattr(fn):
    """For pandas operations that build a new frame: keep the original attrs on the result."""

    def apply(panel):
        out = fn(panel)
        out.attrs = copy.deepcopy(panel.attrs)
        return out

    return apply


_FIELDS = list(BAR_COLUMNS)
BAD_PANELS = {
    "not_a_frame": (lambda p: p[("BTC", "close")], "panel must be a pandas DataFrame"),
    "single_level_columns": (lambda p: p["BTC"], r"2-level MultiIndex named \('asset', 'field'\)"),
    "unnamed_levels": (
        _with_columns(pd.MultiIndex.from_product([ASSETS, _FIELDS])),
        r"2-level MultiIndex named \('asset', 'field'\)",
    ),
    "assets_swapped": (_reattr(lambda p: p[["ETH", "BTC"]]), "in that order"),
    "fields_reordered": (
        _reattr(lambda p: p[[(a, f) for a in ASSETS for f in ("close", "open", "high", "low", "volume")]]),
        "in that order",
    ),
    "missing_field": (_reattr(lambda p: p.drop(columns=[("ETH", "volume")])), "in that order"),
    "extra_asset": (_reattr(lambda p: p.join(p[["BTC"]].rename(columns={"BTC": "SOL"}))), "in that order"),
    "int_volume": (_breaker(lambda p: p.astype({("BTC", "volume"): "int64"})), "must all be float64"),
    "naive_index": (
        _with_index(lambda i: i.tz_localize(None)),
        "UTC DatetimeIndex named 'ts' in microseconds",
    ),
    "other_tz": (_with_index(lambda i: i.tz_convert("Asia/Tokyo")), "UTC DatetimeIndex named 'ts'"),
    "ns_unit": (_with_index(lambda i: i.as_unit("ns")), "UTC DatetimeIndex named 'ts' in microseconds"),
    "unnamed_index": (_with_index(lambda i: i.rename(None)), "UTC DatetimeIndex named 'ts'"),
    "range_index": (_breaker(lambda p: p.reset_index(drop=True)), "UTC DatetimeIndex named 'ts'"),
    "unsorted": (_reattr(lambda p: p.iloc[::-1]), "strictly increasing"),
    "duplicate_ts": (_reattr(lambda p: pd.concat([p.iloc[:3], p.iloc[2:]])), "strictly increasing"),
    "missing_alignment": (_drop_attr("alignment"), r"attrs must be exactly \['alignment', 'bar_type'"),
    "extra_attr": (
        _set_attr("interval", "1d"),
        r"attrs must be exactly .*got \['alignment', 'bar_type', 'instr",
    ),
    "snapshot_not_str": (_set_attr("snapshot_id", 123), r"attrs\['snapshot_id'\] must be a non-empty string"),
    "snapshot_empty": (_set_attr("snapshot_id", ""), r"attrs\['snapshot_id'\] must be a non-empty string"),
    "instruments_missing_eth": (_set_attr("instruments", {"BTC": "x"}), r"attrs\['instruments'\] must map"),
    "instruments_not_str": (
        _set_attr("instruments", {"BTC": 1, "ETH": 2}),
        r"attrs\['instruments'\] must map",
    ),
    "instruments_list": (_set_attr("instruments", ["BTC", "ETH"]), r"attrs\['instruments'\] must map"),
    "bar_type_none": (_set_attr("bar_type", None), r"attrs\['bar_type'\] must be a bar type string or map"),
    "bar_type_partial": (_set_attr("bar_type", {"BTC": "x"}), r"attrs\['bar_type'\] must be"),
    "alignment_not_dict": (_set_attr("alignment", "inner"), r"attrs\['alignment'\] must be a dict"),
    "one_row": (_reattr(lambda p: p.iloc[:1]), "panel asset BTC: bars needs at least 2 rows"),
    "nan_eth_close": (_set_value("ETH", "close", 5, np.nan), "panel asset ETH: bars contain NaN"),
    "inf_btc_open": (_set_value("BTC", "open", 5, np.inf), "panel asset BTC: bars contain NaN or infinite"),
    "btc_non_positive": (_set_value("BTC", "low", 4, -1.0), "panel asset BTC: bars contain non-positive"),
    "eth_negative_volume": (
        _set_value("ETH", "volume", 7, -1.0),
        "panel asset ETH: bars contain negative volume",
    ),
    "eth_high_below_close": (_set_value("ETH", "high", 6, 1.0), r"panel asset ETH: bars violate low <= open"),
}


@pytest.mark.parametrize("case", list(BAD_PANELS.values()), ids=list(BAD_PANELS))
def test_bad_panels_raise_with_pinned_messages(case):
    panel = random_panel(40, seed=3)
    breaker, match = case
    bad = breaker(panel)
    for check in (
        pf.validate_panel,
        lambda b: pf.rebalance(GOOD, b, Costs()),
        lambda b: pf.random_rebalance({"w_btc": 0.5, "w_eth": 0.2, "n_rebalances": 2}, b, Costs()),
        lambda b: pf.asset_bars(b, "BTC"),
    ):
        with pytest.raises(ValueError, match=match):
            check(bad)
    pf.validate_panel(panel)  # breaking a copy left the original valid


def test_asset_bars_gives_standard_bars_with_the_panel_attrs():
    panel = random_panel(60, seed=4)
    panel.attrs["bar_type"] = {"BTC": "BTC-1-DAY", "ETH": "ETH-1-DAY"}
    for asset in ASSETS:
        bars = pf.asset_bars(panel, asset)
        validate_bars(bars)
        assert list(bars.columns) == list(BAR_COLUMNS)
        assert bars.index.equals(panel.index)
        np.testing.assert_array_equal(bars.to_numpy(), panel[asset].to_numpy())
        assert bars.attrs == {
            "snapshot_id": "test-panel",
            "instrument": asset,
            "bar_type": f"{asset}-1-DAY",
            "asset": asset,
            "alignment": panel.attrs["alignment"],
        }
    bars = pf.asset_bars(panel, "BTC")
    bars.iloc[0, 0] = 1.0  # a copy: the panel is untouched
    assert panel.iloc[0, 0] != 1.0
    bars.attrs["alignment"]["rule"] = "changed"
    assert panel.attrs["alignment"]["rule"] != "changed"
    panel.attrs["bar_type"] = "one-type"
    assert pf.asset_bars(panel, "ETH").attrs["bar_type"] == "one-type"
    with pytest.raises(ValueError, match=r"asset must be one of \('BTC', 'ETH'\), got 'USDC'"):
        pf.asset_bars(panel, "USDC")


# -------------------------------------------------------------------------------------------- params


BAD_REBALANCE = {
    "not_a_dict": ([0.4, 0.3], "rebalance: params must be a dict, got list"),
    "unknown_key": (
        {**GOOD, "bands": 0.1},
        r"rebalance: unknown params \['bands'\]; allowed: \['band', 'every'",
    ),
    "missing_w_btc": ({k: v for k, v in GOOD.items() if k != "w_btc"}, "missing required param 'w_btc'"),
    "missing_w_eth": ({k: v for k, v in GOOD.items() if k != "w_eth"}, "missing required param 'w_eth'"),
    "missing_band": ({k: v for k, v in GOOD.items() if k != "band"}, "missing required param 'band'"),
    "missing_every": ({k: v for k, v in GOOD.items() if k != "every"}, "missing required param 'every'"),
    "w_btc_negative": ({**GOOD, "w_btc": -0.1}, r"w_btc must be in \[0.0, 1.0\], got -0.1"),
    "w_eth_above_one": ({**GOOD, "w_eth": 1.5}, r"w_eth must be in \[0.0, 1.0\], got 1.5"),
    "w_btc_nan": ({**GOOD, "w_btc": math.nan}, r"w_btc must be in \[0.0, 1.0\], got nan"),
    "w_btc_bool": ({**GOOD, "w_btc": True}, "w_btc must be a number, got True"),
    "w_eth_str": ({**GOOD, "w_eth": "0.3"}, "w_eth must be a number, got '0.3'"),
    "sum_above_one": (
        {**GOOD, "w_btc": 0.7, "w_eth": 0.4},
        r"rebalance: w_btc \+ w_eth must be <= 1 \(the rest",
    ),
    "band_negative": ({**GOOD, "band": -0.01}, r"band must be in \[0.0, inf\), got -0.01"),
    "band_inf": ({**GOOD, "band": math.inf}, r"band must be in \[0.0, inf\), got inf"),
    "band_none": ({**GOOD, "band": None}, "band must be a number, got None"),
    "every_zero": ({**GOOD, "every": 0}, "every must be >= 1, got 0"),
    "every_fraction": ({**GOOD, "every": 2.5}, "every must be an integer, got 2.5"),
    "every_bool": ({**GOOD, "every": True}, "every must be an integer, got True"),
    "min_cash_above_one": ({**GOOD, "min_cash": 1.2}, r"min_cash must be in \[0.0, 1.0\], got 1.2"),
    "max_coin_negative": ({**GOOD, "max_coin": -0.1}, r"max_coin must be in \[0.0, 1.0\], got -0.1"),
    "targets_break_min_cash": (
        {**GOOD, "w_btc": 0.5, "w_eth": 0.4, "min_cash": 0.2},
        r"rebalance: the targets w_btc = 0.5, w_eth = 0.4 break the limits min_cash = 0.2, max_coin = None",
    ),
    "targets_break_max_coin": (
        {**GOOD, "w_btc": 0.7, "w_eth": 0.1, "max_coin": 0.6},
        r"the targets w_btc = 0.7, w_eth = 0.1 break the limits min_cash = None, max_coin = 0.6",
    ),
    "eth_target_breaks_max_coin": (
        {**GOOD, "w_btc": 0.1, "w_eth": 0.65, "max_coin": 0.6},
        "break the limits",
    ),
    "headroom_negative": (
        {**GOOD, "max_coin": 0.6, "headroom": -0.01},
        r"headroom must be in \[0.0, 1.0\], got -0.01",
    ),
    "headroom_nan": (
        {**GOOD, "max_coin": 0.6, "headroom": math.nan},
        r"headroom must be in \[0.0, 1.0\], got nan",
    ),
    "headroom_none": ({**GOOD, "max_coin": 0.6, "headroom": None}, "headroom must be a number, got None"),
    "headroom_str": ({**GOOD, "max_coin": 0.6, "headroom": "0.02"}, "headroom must be a number, got '0.02'"),
    "headroom_without_limits": (
        {**GOOD, "headroom": 0.02},
        r"rebalance: headroom = 0.02 needs a limit \(min_cash or max_coin\)",
    ),
    "targets_inside_the_cash_headroom": (
        {**GOOD, "w_btc": 0.4, "w_eth": 0.39, "min_cash": 0.2, "headroom": 0.02},
        r"the targets w_btc = 0.4, w_eth = 0.39 break the limits min_cash = 0.2, max_coin = None, headroom = 0.02",
    ),
    "btc_target_inside_the_coin_headroom": (
        {**GOOD, "w_btc": 0.59, "w_eth": 0.1, "max_coin": 0.6, "headroom": 0.02},
        r"break the limits min_cash = None, max_coin = 0.6, headroom = 0.02",
    ),
    "eth_target_inside_the_coin_headroom": (
        {**GOOD, "w_btc": 0.1, "w_eth": 0.5801, "max_coin": 0.6, "headroom": 0.02},
        "break the limits",
    ),
}


@pytest.mark.parametrize("case", list(BAD_REBALANCE.values()), ids=list(BAD_REBALANCE))
def test_bad_rebalance_params_raise_with_pinned_messages(case):
    panel = random_panel(30, seed=1)
    params, match = case
    with pytest.raises(ValueError, match=match):
        pf.rebalance(params, panel, Costs())


BAD_RANDOM = {
    "unknown_key": (
        {"w_btc": 0.5, "w_eth": 0.2, "n_rebalances": 2, "band": 0.1},
        r"random_rebalance: unknown",
    ),
    "missing_n": ({"w_btc": 0.5, "w_eth": 0.2}, "missing required param 'n_rebalances'"),
    "missing_target": ({"w_btc": 0.5, "n_rebalances": 2}, "missing required param 'w_eth'"),
    "negative_n": ({"w_btc": 0.5, "w_eth": 0.2, "n_rebalances": -1}, "n_rebalances must be >= 0, got -1"),
    "negative_seed": (
        {"w_btc": 0.5, "w_eth": 0.2, "n_rebalances": 1, "seed": -1},
        "seed must be >= 0, got -1",
    ),
    "sum_above_one": (
        {"w_btc": 0.6, "w_eth": 0.6, "n_rebalances": 1},
        r"random_rebalance: w_btc \+ w_eth must",
    ),
    "too_many": (
        {"w_btc": 0.5, "w_eth": 0.2, "n_rebalances": 29},
        r"random_rebalance: 29 rebalances don't fit in the 28 closes 1..28 \(close 0 is the first buy",
    ),
}


@pytest.mark.parametrize("case", list(BAD_RANDOM.values()), ids=list(BAD_RANDOM))
def test_bad_random_rebalance_params_raise_with_pinned_messages(case):
    panel = random_panel(30, seed=1)
    params, match = case
    with pytest.raises(ValueError, match=match):
        pf.random_rebalance(params, panel, Costs())


# ------------------------------------------------------------------------------- risk limits and headroom


def write_levels(path, steady: str) -> None:
    """A risk_levels.yaml in ``path`` whose ``steady`` entry is ``steady`` (YAML lines, indented by the caller)."""
    (path / "risk_levels.yaml").write_text(f"steady:\n{steady}balanced:\n  coins: [BTC]\n")


STEADY = "  coins: [BTC, ETH, USDC]\n  min_cash_pct: 20\n  max_coin_pct: 60\n  max_drawdown_budget_pct: TBD\n"


def steady_lines(lines: list[str]) -> range:
    """The line numbers of the ``steady:`` entry of a risk_levels.yaml split into lines: its key line up to the
    next line that starts in the first column (the next level, or a comment there), or the end of the file."""
    start = next(i for i, x in enumerate(lines) if x.startswith("steady:"))
    end = next((i for i in range(start + 1, len(lines)) if lines[i][:1].strip()), len(lines))
    return range(start, end)


def edit_steady_entry(cfg, old: str, new: str) -> None:
    """Replace ``old`` with ``new`` in the ``steady:`` entry of ``cfg/risk_levels.yaml`` only, where ``old`` must
    occur exactly once. Never the first occurrence in the file: balanced and bold hold the same keys, so a copy of
    the real file with Steady's budget set would have had balanced's ``TBD`` edited instead (#55)."""
    path = cfg / "risk_levels.yaml"
    lines = path.read_text().splitlines(keepends=True)
    span = steady_lines(lines)
    block = "".join(lines[span.start : span.stop])
    assert block.count(old) == 1, f"{old!r} is not exactly once in the steady entry of {path}"
    path.write_text("".join(lines[: span.start]) + block.replace(old, new) + "".join(lines[span.stop :]))


def set_steady_budget(cfg, value: str) -> None:
    """Write ``max_drawdown_budget_pct: <value>`` (a YAML scalar: ``TBD``, ``30``) into the ``steady:`` entry of
    ``cfg/risk_levels.yaml``, whatever the copied file held there, so a test sets up the budget state it is about
    instead of depending on the real file's (#55). The line's comment is dropped; nothing else changes."""
    path = cfg / "risk_levels.yaml"
    lines = path.read_text().splitlines(keepends=True)
    hits = [i for i in steady_lines(lines) if lines[i].lstrip().startswith("max_drawdown_budget_pct:")]
    assert len(hits) == 1, f"the steady entry of {path} must hold max_drawdown_budget_pct exactly once"
    line = lines[hits[0]]
    lines[hits[0]] = f"{line[: len(line) - len(line.lstrip())]}max_drawdown_budget_pct: {value}\n"
    path.write_text("".join(lines))


def test_the_real_file_sets_steady_s_budget_at_35_and_leaves_balanced_and_bold_missing():
    """``config/risk_levels.yaml`` as committed: Steady's Monte Carlo 95th-percentile max drawdown budget is 35%
    (owner-approved 2026-11-21, ``reports/director/2026-11-21-owner-answers-trend-steady.md`` item 1), read as the
    fraction 0.35; balanced and bold are still TBD, so a gate that needs their budget is MISSING (None). The hash
    is of the file's bytes."""
    data = (CONFIG_DIR / "risk_levels.yaml").read_bytes()
    steady = pf.risk_limits("steady")
    assert steady["max_drawdown_budget"] == 0.35 and steady["max_drawdown_budget_pct"] == 35
    assert steady["sha256"] == hashlib.sha256(data).hexdigest()
    balanced = pf.risk_limits("balanced")
    assert balanced["max_drawdown_budget"] is None and balanced["max_drawdown_budget_pct"] == "TBD"
    assert balanced["sha256"] == steady["sha256"]
    raw = load_yaml("risk_levels")
    assert sorted(raw) == ["balanced", "bold", "steady"]
    # bold's coin list is still empty, which risk_limits refuses (this runner holds BTC and ETH only), so its
    # budget is read with risk_limits' own rule
    assert raw["bold"]["max_drawdown_budget_pct"] == "TBD"
    assert pf._budget(raw["bold"]["max_drawdown_budget_pct"]) is None


HOLD_MIX_CAP_KEY = "hold_mix_max_rebalances_per_30d"


def test_the_real_file_caps_the_hold_this_mix_tool_at_2_rebalances_in_30_days_in_steady_only():
    """``config/risk_levels.yaml`` as committed: Steady's hard limit for the self-directed hold-this-mix tool, at
    most 2 rebalances in any 30 days (owner-approved 2026-11-22). The app's rule engine reads it; no ``lab/`` code
    does, and it is not a cap on our own strategies. The key is in the steady entry only, written once, and its
    value is the integer 2 (not a bool, a float or a string)."""
    raw = load_yaml("risk_levels")
    assert sorted(raw) == ["balanced", "bold", "steady"]
    value = raw["steady"][HOLD_MIX_CAP_KEY]
    assert type(value) is int and value == 2
    assert HOLD_MIX_CAP_KEY not in raw["balanced"] and HOLD_MIX_CAP_KEY not in raw["bold"]
    # written once, as a key of the steady entry (a duplicate key would load as its last value without a word)
    lines = (CONFIG_DIR / "risk_levels.yaml").read_text().splitlines()
    hits = [i for i, x in enumerate(lines) if HOLD_MIX_CAP_KEY in x]
    assert len(hits) == 1 and hits[0] in steady_lines(lines)
    assert lines[hits[0]].strip() == f"{HOLD_MIX_CAP_KEY}: 2"


def test_the_hold_this_mix_cap_is_a_15_day_wait_in_the_engine():
    """The cap of 2 a month is enforced as at least 15 days between trades back to the mix: ``holdmix.wait_days``
    gives 15 for the file's value, and ``check_path``'s count, ceil(30 / W), allows 2 such trades in any
    30-day stretch [ts, ts + 30 days). Limit fixes are outside that count (the wait never holds them back), but
    they restart the wait, as in the engine."""
    value = load_yaml("risk_levels")["steady"][HOLD_MIX_CAP_KEY]
    assert holdmix.wait_days(2) == 15
    assert holdmix.wait_days(value) == 15
    assert holdmix.MONTH_DAYS == 30 and math.ceil(holdmix.MONTH_DAYS / holdmix.wait_days(value)) == 2


def test_the_hold_this_mix_cap_leaves_steady_s_risk_limits_unchanged(tmp_path):
    """``risk_limits("steady")`` returns what it returned before the key was added: the same keys (no key for the
    cap) and the file's own values. Only ``sha256`` moves: the file without the key's line gives the same dict but
    for its hash and path. The values are read from the file, not typed here, so an owner-approved change to
    Steady's other limits does not fail this test (#55); the real file's budget is pinned by
    ``test_the_real_file_sets_steady_s_budget_at_35_and_leaves_balanced_and_bold_missing``."""
    raw = load_yaml("risk_levels")["steady"]
    lim = pf.risk_limits("steady")
    assert lim == {
        "level": "steady",
        "path": str(CONFIG_DIR / "risk_levels.yaml"),
        "sha256": hashlib.sha256((CONFIG_DIR / "risk_levels.yaml").read_bytes()).hexdigest(),
        "coins": tuple(raw["coins"]),
        "min_cash": raw["min_cash_pct"] / 100.0,
        "max_coin": raw["max_coin_pct"] / 100.0,
        "max_drawdown_budget": pf._budget(raw["max_drawdown_budget_pct"]),
        "max_drawdown_budget_pct": raw["max_drawdown_budget_pct"],
    }
    shutil.copy(CONFIG_DIR / "risk_levels.yaml", tmp_path / "risk_levels.yaml")
    edit_steady_entry(tmp_path, f"  {HOLD_MIX_CAP_KEY}: {raw[HOLD_MIX_CAP_KEY]}\n", "")
    without = pf.risk_limits("steady", tmp_path)
    assert HOLD_MIX_CAP_KEY not in load_yaml("risk_levels", tmp_path)["steady"]
    assert without["sha256"] != lim["sha256"]
    for key in ("sha256", "path"):
        del without[key], lim[key]
    assert without == lim


def test_the_steady_entry_helpers_edit_the_steady_entry_only(tmp_path):
    """The test helpers that edit a copied risk_levels.yaml touch the steady entry and nothing else (#55)."""
    shutil.copy(CONFIG_DIR / "risk_levels.yaml", tmp_path / "risk_levels.yaml")
    real = load_yaml("risk_levels", tmp_path)
    set_steady_budget(tmp_path, "TBD")
    got = load_yaml("risk_levels", tmp_path)
    assert got["steady"] == {**real["steady"], "max_drawdown_budget_pct": "TBD"}
    assert {k: v for k, v in got.items() if k != "steady"} == {k: v for k, v in real.items() if k != "steady"}
    edit_steady_entry(tmp_path, "max_drawdown_budget_pct: TBD", "max_drawdown_budget_pct: 30")
    assert pf.risk_limits(config_dir=tmp_path)["max_drawdown_budget"] == 0.3
    assert load_yaml("risk_levels", tmp_path)["balanced"] == real["balanced"]
    # the only TBD left is balanced's
    with pytest.raises(AssertionError, match="is not exactly once in the steady entry"):
        edit_steady_entry(tmp_path, "max_drawdown_budget_pct: TBD", "max_drawdown_budget_pct: 25")
    assert load_yaml("risk_levels", tmp_path)["balanced"] == real["balanced"]
    write_levels(tmp_path, STEADY)  # steady is not the last entry: the span stops at the next level
    set_steady_budget(tmp_path, "40")
    want = f"steady:\n{STEADY.replace('TBD', '40')}balanced:\n  coins: [BTC]\n"
    assert (tmp_path / "risk_levels.yaml").read_text() == want


def test_risk_limits_are_the_config_file_s_numbers_as_fractions():
    raw = load_yaml("risk_levels")["steady"]
    data = (CONFIG_DIR / "risk_levels.yaml").read_bytes()
    lim = pf.risk_limits()
    assert lim == pf.risk_limits("steady", CONFIG_DIR)
    assert lim == {
        "level": "steady",
        "path": str(CONFIG_DIR / "risk_levels.yaml"),
        "sha256": hashlib.sha256(data).hexdigest(),
        "coins": tuple(raw["coins"]),
        "min_cash": raw["min_cash_pct"] / 100.0,
        "max_coin": raw["max_coin_pct"] / 100.0,
        "max_drawdown_budget": pf._budget(raw["max_drawdown_budget_pct"]),
        "max_drawdown_budget_pct": raw["max_drawdown_budget_pct"],
    }
    assert lim["min_cash"] is not None and lim["max_coin"] is not None  # Steady sets both limits


def test_risk_limits_follow_config_dir_and_rebalance_uses_them(tmp_path):
    """A tighter file in another directory gives tighter limits, and rebalance applies those: targets of 0.75 in
    coins pass min_cash 20% and break min_cash 30%. The hash is of the bytes the values came from."""
    write_levels(tmp_path, STEADY)
    loose = pf.risk_limits(config_dir=tmp_path)
    assert (loose["min_cash"], loose["max_coin"]) == (0.2, 0.6)
    assert loose["sha256"] == hashlib.sha256((tmp_path / "risk_levels.yaml").read_bytes()).hexdigest()
    write_levels(tmp_path, STEADY.replace("min_cash_pct: 20", "min_cash_pct: 30").replace("60", "45"))
    tight = pf.risk_limits(config_dir=tmp_path)
    assert (tight["min_cash"], tight["max_coin"]) == (0.3, 0.45) and tight["sha256"] != loose["sha256"]
    panel = random_panel(40, seed=2)
    params = {"w_btc": 0.4, "w_eth": 0.35, "band": 0.05, "every": 5}
    pf.rebalance({**params, "min_cash": loose["min_cash"], "max_coin": loose["max_coin"]}, panel, Costs())
    with pytest.raises(ValueError, match="break the limits min_cash = 0.3, max_coin = 0.45"):
        pf.rebalance({**params, "min_cash": tight["min_cash"], "max_coin": tight["max_coin"]}, panel, Costs())


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("TBD", None),
        ("35", 0.35),
        ("12.5", 0.125),
        ("100", 1.0),
        ("0", None),
        ("-5", None),
        ("100.5", None),
        (".nan", None),
        (".inf", None),
        ("true", None),
        ("'30'", None),
        ("null", None),
        (None, None),  # the key is absent
    ],
)
def test_the_drawdown_budget_is_a_fraction_or_missing(tmp_path, value, expected):
    """Only a finite number in (0, 100] is a budget (as a fraction); anything else is MISSING (None), and the
    raw value is kept as read."""
    line = "" if value is None else f"  max_drawdown_budget_pct: {value}\n"
    write_levels(tmp_path, STEADY.replace("  max_drawdown_budget_pct: TBD\n", line))
    lim = pf.risk_limits(config_dir=tmp_path)
    assert lim["max_drawdown_budget"] == expected
    raw = load_yaml("risk_levels", tmp_path)["steady"].get("max_drawdown_budget_pct")
    kept = lim["max_drawdown_budget_pct"]
    assert kept == raw or (math.isnan(raw) and math.isnan(kept))  # the raw value as read (NaN != NaN)


@pytest.mark.parametrize(
    ("coins", "ok"),
    [
        ("[USDC, ETH, BTC]", True),
        ("[BTC, USDC]", False),
        ("[BTC, ETH, USDC, SOL]", False),
        ("[BTC, BTC, ETH, USDC]", False),
        ("[BTC, ETH, USDT]", False),
        ("[]", False),
        ("BTC, ETH, USDC", False),
        ("[BTC, ETH, 1]", False),
        (None, False),  # absent
    ],
)
def test_the_coin_list_must_be_exactly_btc_eth_and_usdc(tmp_path, coins, ok):
    line = "" if coins is None else f"  coins: {coins}\n"
    write_levels(tmp_path, STEADY.replace("  coins: [BTC, ETH, USDC]\n", line))
    if ok:
        assert pf.risk_limits(config_dir=tmp_path)["coins"] == ("USDC", "ETH", "BTC")
        return
    with pytest.raises(
        ValueError, match=r"risk level 'steady': coins must be exactly \['BTC', 'ETH', 'USDC'\]"
    ):
        pf.risk_limits(config_dir=tmp_path)


@pytest.mark.parametrize(
    ("key", "value", "match"),
    [
        ("min_cash_pct", "120", r"min_cash_pct must be in \[0.0, 100.0\], got 120"),
        ("min_cash_pct", "-1", r"min_cash_pct must be in \[0.0, 100.0\], got -1"),
        ("max_coin_pct", ".nan", r"max_coin_pct must be in \[0.0, 100.0\], got nan"),
        ("max_coin_pct", "'60'", "max_coin_pct must be a number, got '60'"),
        ("min_cash_pct", "true", "min_cash_pct must be a number, got True"),
        ("max_coin_pct", "null", "max_coin_pct must be a number, got None"),
    ],
)
def test_bad_limits_in_the_file_raise(tmp_path, key, value, match):
    default = "20" if key == "min_cash_pct" else "60"
    write_levels(tmp_path, STEADY.replace(f"{key}: {default}", f"{key}: {value}"))
    with pytest.raises(ValueError, match=match):
        pf.risk_limits(config_dir=tmp_path)


def test_an_absent_limit_is_no_limit_and_bounds_are_allowed(tmp_path):
    write_levels(
        tmp_path, STEADY.replace("  min_cash_pct: 20\n", "").replace("max_coin_pct: 60", "max_coin_pct: 100")
    )
    lim = pf.risk_limits(config_dir=tmp_path)
    assert lim["min_cash"] is None and lim["max_coin"] == 1.0
    write_levels(tmp_path, STEADY.replace("min_cash_pct: 20", "min_cash_pct: 0"))
    assert pf.risk_limits(config_dir=tmp_path)["min_cash"] == 0.0


def test_unknown_or_malformed_levels_raise(tmp_path):
    write_levels(tmp_path, STEADY)
    with pytest.raises(ValueError, match=r"risk level 'medium' is not in .*levels: \['balanced', 'steady'\]"):
        pf.risk_limits("medium", tmp_path)
    with pytest.raises(ValueError, match=r"risk level 'balanced': coins must be exactly"):
        pf.risk_limits("balanced", tmp_path)
    (tmp_path / "risk_levels.yaml").write_text("steady: 5\n")
    with pytest.raises(ValueError, match="risk level 'steady' in .* must be a mapping, got int"):
        pf.risk_limits(config_dir=tmp_path)
    for text in ("", "- steady\n"):
        (tmp_path / "risk_levels.yaml").write_text(text)
        with pytest.raises(ValueError, match=r"risk level 'steady' is not in .*levels: \[\]"):
            pf.risk_limits(config_dir=tmp_path)


def test_check_targets_is_rebalance_s_check():
    """At the limit with no headroom; exactly at the headroom; and past it by more than round-off."""
    pf.check_targets(0.4, 0.4, min_cash=0.2, max_coin=0.6)
    pf.check_targets(0.6, 0.2, min_cash=0.2, max_coin=0.6)
    pf.check_targets(0.39, 0.39, min_cash=0.2, headroom=0.02)  # 0.78 = 1 - 0.2 - 0.02
    pf.check_targets(0.58, 0.1, max_coin=0.6, headroom=0.02)
    pf.check_targets(0.1, 0.58, max_coin=0.6, headroom=0.02)
    pf.check_targets(0.77 * 0.75, 0.77 * 0.25, min_cash=0.2, max_coin=0.6, headroom=0.02)
    pf.check_targets(0.0, 0.0)
    for args, kwargs, match in (
        ((0.4, 0.39), {"min_cash": 0.2, "headroom": 0.02}, "headroom = 0.02"),
        ((0.581, 0.1), {"max_coin": 0.6, "headroom": 0.02}, "break the limits"),
        ((0.1, 0.581), {"max_coin": 0.6, "headroom": 0.02}, "break the limits"),
        ((0.61, 0.1), {"max_coin": 0.6}, "headroom = 0.0"),
        ((0.5, 0.5000000000000002), {}, r"w_btc \+ w_eth must be <= 1"),
        ((1.2, 0.0), {}, r"w_btc must be in \[0.0, 1.0\]"),
        ((0.1, 0.1), {"headroom": 0.02}, "needs a limit"),
        ((0.1, 0.1), {"min_cash": 0.2, "headroom": -1.0}, r"headroom must be in"),
    ):
        with pytest.raises(ValueError, match=match):
            pf.check_targets(*args, **kwargs)
        params = {"w_btc": args[0], "w_eth": args[1], "band": 0.1, "every": 1, **kwargs}
        with pytest.raises(ValueError, match=match):
            pf.rebalance(params, random_panel(20, 3), Costs())


def test_headroom_constrains_the_targets_only(make_bars):
    """Accepted targets run exactly as without headroom: breaches are judged at the limits, not inside the
    headroom. Hand-built: BTC at 130 puts it at 0.65 / 1.15 = 0.565, inside the 0.05 headroom of max_coin 0.6 but
    not past the limit, so nothing is forced; at 160 (0.8 / 1.3 = 0.615) it is."""
    panel = random_panel(300, seed=21, vols=(0.06, 0.08))
    params = {"w_btc": 0.4, "w_eth": 0.3, "band": 0.1, "every": 5, "min_cash": 0.22, "max_coin": 0.45}
    plain = pf.rebalance(params, panel, Costs())
    roomy = pf.rebalance({**params, "headroom": 0.05}, panel, Costs())
    free = pf.rebalance({**params, "min_cash": None, "max_coin": None}, panel, Costs())
    assert len(plain.attrs["orders"]) > len(free.attrs["orders"])  # the limits bind on this panel
    np.testing.assert_array_equal(plain[ALL_COLUMNS].to_numpy(), roomy[ALL_COLUMNS].to_numpy())
    np.testing.assert_array_equal(plain.attrs["orders"], roomy.attrs["orders"])
    pd.testing.assert_frame_equal(plain.attrs["fills"], roomy.attrs["fills"])
    hand = {"w_btc": 0.5, "w_eth": 0.2, "band": 5.0, "every": 1000, "max_coin": 0.6, "headroom": 0.05}
    inside = pf.rebalance(
        hand, hand_panel(make_bars, [100.0, 100.0, 130.0, 130.0], [100.0] * 4), Costs.zero()
    )
    assert inside["w_BTC"].iloc[2] == pytest.approx(0.65 / 1.15, rel=1e-14)
    np.testing.assert_array_equal(inside.attrs["orders"], [0])
    past = pf.rebalance(hand, hand_panel(make_bars, [100.0, 100.0, 160.0, 160.0], [100.0] * 4), Costs.zero())
    np.testing.assert_array_equal(past.attrs["orders"], [0, 2])


def test_costs_must_be_a_costs_instance_and_default_to_the_config():
    panel = random_panel(80, seed=2)
    for rule, params in (
        (pf.rebalance, GOOD),
        (pf.random_rebalance, {"w_btc": 0.5, "w_eth": 0.2, "n_rebalances": 3}),
    ):
        with pytest.raises(ValueError, match="costs must be a Costs instance or None, got dict"):
            rule(params, panel, {"pool_fee_bps": 5.0})
        default = rule(params, panel)
        config = rule(params, panel, Costs.from_yaml())
        np.testing.assert_array_equal(default[ALL_COLUMNS].to_numpy(), config[ALL_COLUMNS].to_numpy())


def test_edge_parameters_are_accepted():
    panel = random_panel(80, seed=5)
    cash = pf.rebalance({"w_btc": 0.0, "w_eth": 0.0, "band": 0.0, "every": 1}, panel, Costs())
    validate_result(cash, panel)
    assert (cash[ALL_COLUMNS].to_numpy() == 0.0).all()  # all USDC: nothing trades, nothing moves
    assert cash.attrs["n_trades"] == 0 and len(cash.attrs["trade_returns"]) == 0
    assert cash.attrs["fills"].empty and list(cash.attrs["fills"].columns) == FILL_COLUMNS
    np.testing.assert_array_equal(cash.attrs["orders"], [0])
    full = pf.rebalance({"w_btc": 0.6, "w_eth": 0.4, "band": 0.0, "every": 1}, panel, Costs())
    validate_result(full, panel)
    all_coins = full["position"].iloc[1:].to_numpy()
    assert (np.abs(all_coins - 1.0) <= WEIGHT_TOL).all()  # no cash left, and it never goes negative
    as_float = pf.rebalance({**GOOD, "every": 3.0}, panel, Costs())
    np.testing.assert_array_equal(as_float["ret"], pf.rebalance(GOOD, panel, Costs())["ret"])
    huge_band = pf.rebalance({**GOOD, "band": 1e6}, panel, Costs())
    np.testing.assert_array_equal(huge_band.attrs["orders"], [0])  # a static mix


def test_a_fill_the_portfolio_cannot_pay_raises():
    panel = random_panel(30, seed=6)
    with pytest.raises(ValueError, match=r"costs of the fill on .* it cannot pay them"):
        pf.rebalance(GOOD, panel, Costs(gas_usd_per_trade=6000.0))  # two legs of 6000 USD gas on 10000 USD


def test_a_fill_costing_exactly_the_whole_book_raises():
    """Two legs of 5000 USD gas on 10000 USD and no fees: the cost is exactly 100%, which leaves nothing."""
    gas = Costs(pool_fee_bps=0.0, slippage_bps=((1.0, 0.0),), gas_usd_per_trade=5000.0)
    with pytest.raises(
        ValueError, match=r"costs of the fill on .* are 100\.0% of a portfolio worth 1e\+04 USD"
    ):
        pf.rebalance({"w_btc": 0.5, "w_eth": 0.3, "band": 1.0, "every": 1}, random_panel(30, 6), gas)


@pytest.mark.parametrize("w_eth", [0.5000000000000002, 0.5000000005])
def test_targets_above_one_by_round_off_are_refused(w_eth):
    """Spot only: a cash target below 0, even by 1 ulp, raises (no tolerance on the sum of the targets)."""
    assert 0.5 + w_eth > 1.0
    panel = random_panel(30, 1)
    with pytest.raises(ValueError, match=r"rebalance: w_btc \+ w_eth must be <= 1"):
        pf.rebalance({"w_btc": 0.5, "w_eth": w_eth, "band": 0.1, "every": 1}, panel, Costs())
    with pytest.raises(ValueError, match=r"random_rebalance: w_btc \+ w_eth must be <= 1"):
        pf.random_rebalance({"w_btc": 0.5, "w_eth": w_eth, "n_rebalances": 1}, panel, Costs())


# ------------------------------------------------------------------------------- generic guarantees


FILL_COLUMNS = [
    "bar",
    "ts",
    "asset",
    "side",
    "units",
    "price",
    "usd",
    "cost",
    "weight_before",
    "weight_after",
]


def test_rules_trade_on_the_synthetic_market(market):
    """Non-vacuity: on the 1500-day synthetic market both rules rebalance many times."""
    panel = pf.make_panel(market, snapshot_id="synthetic-21")
    a = pf.rebalance({"w_btc": 0.45, "w_eth": 0.3, "band": 0.03, "every": 7, "max_coin": 0.6}, panel, Costs())
    validate_result(a, panel)
    assert a.attrs["n_trades"] >= 20
    assert set(a.attrs["fills"]["asset"]) == {"BTC", "ETH"}
    b = pf.random_rebalance({"w_btc": 0.45, "w_eth": 0.3, "n_rebalances": 40, "seed": 1}, panel, Costs())
    validate_result(b, panel)
    assert b.attrs["n_trades"] == 41  # the first buy and 40 rebalances, all of which trade on moving prices


def test_result_shape_and_types():
    panel = random_panel(150, seed=7)
    result = pf.rebalance(GOOD, panel, Costs())
    validate_result(result, panel)
    assert list(result.columns) == ALL_COLUMNS
    assert result.index.equals(panel.index)
    assert all(result[col].dtype == np.float64 for col in ALL_COLUMNS)
    assert (
        isinstance(result.attrs["trade_returns"], np.ndarray)
        and result.attrs["trade_returns"].dtype == np.float64
    )
    assert isinstance(result.attrs["n_trades"], int)
    assert result.attrs["orders"].dtype == np.int64
    assert result.attrs["snapshot_id"] == "test-panel"
    fills = result.attrs["fills"]
    assert list(fills.columns) == FILL_COLUMNS
    assert fills["bar"].dtype == np.int64
    for col in ("units", "price", "usd", "cost", "weight_before", "weight_after"):
        assert fills[col].dtype == np.float64
    assert list(fills["ts"]) == list(panel.index[fills["bar"].to_numpy()])


@given(case=cases(), data=st.data())
def test_no_look_ahead(case, data):
    """Tamper every field of every asset from ``cut`` on (keeping the opens of bar ``cut``, the fill prices of the
    decision at close cut-1): every output row before ``cut`` is identical, the fill on bar ``cut`` too (turnover,
    cost, its legs), and so are the orders before ``cut`` and every trade return that ended by ``cut``."""
    panel, rule, params = case
    cut = data.draw(st.integers(1, len(panel) - 1))
    tampered = tamper_from(panel, cut, data.draw(st.integers(0, 2**16)))
    a = rule(params, panel, Costs())
    b = rule(params, tampered, Costs())
    np.testing.assert_array_equal(a[ALL_COLUMNS].to_numpy()[:cut], b[ALL_COLUMNS].to_numpy()[:cut])
    assert a["turnover"].iloc[cut] == b["turnover"].iloc[cut]
    assert a["cost"].iloc[cut] == b["cost"].iloc[cut]
    fa, fb = a.attrs["fills"], b.attrs["fills"]
    pd.testing.assert_frame_equal(fa[fa["bar"] <= cut], fb[fb["bar"] <= cut])
    oa, ob = a.attrs["orders"], b.attrs["orders"]
    np.testing.assert_array_equal(oa[oa < cut], ob[ob < cut])
    ended = max(0, int((fill_bars_of(a) <= cut).sum()) - 1)  # periods closed by a later fill at or before cut
    np.testing.assert_array_equal(a.attrs["trade_returns"][:ended], b.attrs["trade_returns"][:ended])


@given(case=cases(), costs=st.sampled_from(COST_MODELS))
# a 0.55 USD leg (5.5e-5 of the book): its round-off is a fraction of the book, not of the leg (test bug, fixed)
@example(
    case=(
        random_panel(20, 5, (0.01, 0.0), (0.005, 0.0)),
        pf.random_rebalance,
        {"w_btc": 0.25, "w_eth": 0.0, "n_rebalances": 2, "seed": 253},
    ),
    costs=Costs(),
)
# targets 1 - 1 ulp of ETH: the rebalance at bar 17 trades a round-off leg the unit book can't size identically
@example(
    case=(
        random_panel(20, 0, (0.0, 0.01), (0.0, 0.0)),
        pf.random_rebalance,
        {"w_btc": 0.0, "w_eth": 0.9999999999999999, "n_rebalances": 1, "seed": 0},
    ),
    costs=Costs(),
)
# BTC target 1 ulp under 1, flat ETH: the rebalance at bar 17 trades a BTC leg of round-off size (1.2e-12 USD,
# 1e-16 of the book) whose side the engine (from the drifted weight) and the unit book (from units) call
# differently (test bug, fixed)
@example(
    case=(
        random_panel(20, 175, (0.01, 0.0), (0.0, 0.0)),
        pf.random_rebalance,
        {"w_btc": 0.9999999999999999, "w_eth": 0.0, "n_rebalances": 1, "seed": 0},
    ),
    costs=Costs(),
)
# a ruined book (test bug, fixed): BTC falls from 30000 to ~7500 and daily rebalancing pays 2 x 25 USD of gas, so the
# fill on bar 98 (2021-04-09) costs 50.00 USD on a 15.86 USD book (315.2%) and the engine rightly refuses it
@example(
    case=(
        random_panel(99, 168, (0.1, 0.0), (0.0, 0.0)),
        pf.rebalance,
        {"w_btc": 0.75, "w_eth": 0.2, "band": 0.0, "every": 1},
    ),
    costs=Costs(pool_fee_bps=30.0, aggregator_fee_bps=10.0, gas_usd_per_trade=25.0),
)
# the same with overnight gaps (V_open != the last close's value), BTC only: 25 USD a day drains the cash; bar 116
@example(
    case=(
        random_panel(120, 10, (0.1, 0.0), (0.03, 0.0)),
        pf.rebalance,
        {"w_btc": 0.6, "w_eth": 0.0, "band": 0.0, "every": 1},
    ),
    costs=Costs(pool_fee_bps=30.0, aggregator_fee_bps=10.0, gas_usd_per_trade=25.0),
)
# the boundary: two legs of 5000 USD gas on 10000 USD and no fees cost exactly 100% at bar 1, which the book can't pay
@example(
    case=(random_panel(30, 6), pf.rebalance, {"w_btc": 0.5, "w_eth": 0.3, "band": 1.0, "every": 1}),
    costs=Costs(pool_fee_bps=0.0, slippage_bps=((1.0, 0.0),), gas_usd_per_trade=5000.0),
)
def test_accounting_equals_an_independent_book_of_coin_units_and_cash(case, costs):
    """Per bar, recomputed from coin units and USDC cash (``unit_book``) with overnight gaps, to 1e-12: ret,
    position, turnover, cost and both weights; and the fill log leg by leg (asset, side, units, open price, USD
    size, leg cost = usd * rate(usd) + gas, weights before and after). The book can pay every fill the engine made;
    where the engine refuses a fill, ``run_checked`` checks the refusal against the book and these checks run on
    every bar before it."""
    panel, rule, params = case
    panel, result = run_checked(rule, params, panel, costs)
    fills = fill_bars_of(result)
    assert set(fills) <= set(result.attrs["orders"] + 1)  # a fill is the next open of an order
    out, legs, v_open, _, dust = unit_book(panel, target_of(params), result, costs)
    assert (out["cost"] < 1.0).all()  # the book could pay every fill the engine made
    assert (dust <= 1e-12).all()  # every leg the engine did not trade was at its target to round-off
    for col in ALL_COLUMNS:
        np.testing.assert_allclose(result[col].to_numpy(), out[col], rtol=0, atol=1e-12, err_msg=col)
    log = result.attrs["fills"]
    assert len(log) == len(legs)
    assert list(log["bar"]) == [leg["bar"] for leg in legs]
    assert list(log["asset"]) == [leg["asset"] for leg in legs]
    np.testing.assert_array_equal(log["price"].to_numpy(), [leg["price"] for leg in legs])
    np.testing.assert_array_equal(log["weight_after"].to_numpy(), [leg["weight_after"] for leg in legs])
    # USD amounts as fractions of the book's value at that open, to the same 1e-12 as the per-bar identities: a
    # leg's size is |target - drifted| x V_open, so its round-off is a fraction of V_open, not of the leg (a
    # 0.55 USD leg in a 10000 USD book carries ~7e-13 USD of it).
    scale = np.array([v_open[list(fills).index(leg["bar"])] for leg in legs])
    # sides on every leg larger than round-off (> 1e-12 of the book); a round-off leg's side is round-off too
    real = [leg["usd"] / v > 1e-12 for leg, v in zip(legs, scale, strict=True)]
    assert [s for s, r in zip(log["side"], real, strict=True) if r] == [
        leg["side"] for leg, r in zip(legs, real, strict=True) if r
    ]
    for col in ("usd", "cost"):
        np.testing.assert_allclose(
            log[col].to_numpy() / scale, [leg[col] for leg in legs] / scale, rtol=0, atol=1e-12, err_msg=col
        )
    np.testing.assert_allclose(
        (log["units"] * log["price"]).to_numpy() / scale,
        [leg["units"] * leg["price"] for leg in legs] / scale,
        rtol=0,
        atol=1e-12,
    )
    np.testing.assert_allclose(
        log["weight_before"].to_numpy(), [leg["weight_before"] for leg in legs], rtol=0, atol=1e-12
    )


@given(case=cases())
def test_only_fills_trade_and_every_fill_pays(case):
    panel, rule, params = case
    result = rule(params, panel, Costs())
    validate_result(result, panel)
    turnover, cost = result["turnover"].to_numpy(), result["cost"].to_numpy()
    assert result.attrs["n_trades"] == int((turnover > 0).sum()) == len(result.attrs["trade_returns"])
    assert (cost[turnover == 0] == 0.0).all()
    assert (cost[turnover > 0] > 0.0).all()  # costs on: no fill is free
    log = result.attrs["fills"]
    assert set(log["bar"]) == set(fill_bars_of(result))
    assert (log["cost"] > 0).all() and (log["usd"] > 0).all()
    assert (
        log.groupby("bar")["asset"].apply(list).map(lambda x: x in (["BTC"], ["ETH"], ["BTC", "ETH"])).all()
    )
    by_bar = log.groupby("bar")["usd"].sum()
    v_before = log.groupby("bar")["usd"].sum() / turnover[by_bar.index.to_numpy()]
    np.testing.assert_allclose(  # the bar's cost is the sum of its legs' USD costs over the same V_open
        cost[by_bar.index.to_numpy()], log.groupby("bar")["cost"].sum() / v_before, rtol=1e-12, atol=0
    )


@given(case=cases(), costs=st.sampled_from(COST_MODELS))
@example(  # a ruined book (TESTING.md #49): the fill on bar 98 is refused; the 98 bars before it are compared
    case=(
        random_panel(99, 168, (0.1, 0.0), (0.0, 0.0)),
        pf.rebalance,
        {"w_btc": 0.75, "w_eth": 0.2, "band": 0.0, "every": 1},
    ),
    costs=Costs(pool_fee_bps=30.0, aggregator_fee_bps=10.0, gas_usd_per_trade=25.0),
)
def test_costs_off_vs_on_scale_each_bar_return(case, costs):
    """Decisions and weights don't depend on costs, so (1 + ret_paid) == (1 + ret_free) * (1 - cost_paid). Where
    the engine refuses a fill the book cannot pay (``run_checked``), on every bar before it."""
    panel, rule, params = case
    free = rule(params, panel, Costs.zero())
    bars, paid = run_checked(rule, params, panel, costs)
    n = len(bars)
    assert (free["cost"] == 0.0).all()
    for col in ("position", "turnover", *pf.WEIGHT_COLUMNS):
        np.testing.assert_array_equal(paid[col].to_numpy(), free[col].to_numpy()[:n])
    orders = free.attrs["orders"]
    np.testing.assert_array_equal(paid.attrs["orders"], orders[orders < n - 1])
    gross, net = 1 + free["ret"].to_numpy()[:n], 1 + paid["ret"].to_numpy()
    np.testing.assert_allclose(net, gross * (1 - paid["cost"].to_numpy()), rtol=0, atol=1e-15)
    assert paid.attrs["n_trades"] == int((fill_bars_of(free) < n).sum())
    assert (paid["cost"][paid["turnover"] > 0] > 0).all()


@given(case=cases(), k=st.floats(0.25, 8.0))
# subnormal costs (test bug, fixed): a weight of 2.2e-311 makes a cost of ~1e-314, where a float has only absolute
# precision (spacing 5e-324), so k * cost and the cost at k x the rate differ by 1 subnormal step (2.2e-10 relative)
@example(
    case=(
        random_panel(20, 0),
        pf.random_rebalance,
        {"w_btc": 0.0, "w_eth": 2.225073858507e-311, "n_rebalances": 0, "seed": 0},
    ),
    k=0.5,
)
@example(
    case=(
        random_panel(20, 0),
        pf.rebalance,
        {"w_btc": 2.2250738585e-313, "w_eth": 0.0, "band": 0.0, "every": 1},
    ),
    k=2.0,
)
@example(
    case=(
        random_panel(20, 0),
        pf.random_rebalance,
        {"w_btc": 0.0, "w_eth": 1.1125369292536007e-308, "n_rebalances": 0, "seed": 0},
    ),
    k=2.0,
)
def test_flat_rate_cost_is_turnover_times_rate(case, k):
    """With a size-independent rate and no gas, cost == turnover * rate (to round-off: the legs are summed one at
    a time) and stressing the cost model by k scales the cost by k.

    Relative to the cost, with an absolute floor of the smallest NORMAL double (2.2e-308 of the book): below it a
    float has no relative precision left, only steps of 5e-324. The floor matters only for costs under ~2e-294 of
    the book; the smallest real cost is one leg's gas, ~1e-5 of a 10000 USD book (TESTING.md bug log)."""
    panel, rule, params = case
    base = rule(params, panel, FLAT_RATE)
    stressed = rule(params, panel, FLAT_RATE.stressed(k))
    floor = np.finfo(float).tiny
    np.testing.assert_allclose(base["cost"], 0.002 * base["turnover"], rtol=1e-15, atol=floor)
    np.testing.assert_allclose(stressed["cost"], k * base["cost"], rtol=1e-14, atol=floor)


@given(case=cases(), costs=st.sampled_from((Costs.zero(), *COST_MODELS)))
@example(  # a ruined book (TESTING.md #49): the fill on bar 98 is refused; the 98 bars before it are chained
    case=(
        random_panel(99, 168, (0.1, 0.0), (0.0, 0.0)),
        pf.rebalance,
        {"w_btc": 0.75, "w_eth": 0.2, "band": 0.0, "every": 1},
    ),
    costs=Costs(pool_fee_bps=30.0, aggregator_fee_bps=10.0, gas_usd_per_trade=25.0),
)
def test_trade_returns_chain_the_portfolio_from_fill_to_fill(case, costs):
    """trade_returns[i] = V_open(fill i+1) / V_open(fill i) - 1 (each period carries the costs of the fill that
    opens it), the last one ends at the last close; so prod(1 + trade_returns) = V[n-1] / V_open(first fill)
    = prod(1 + ret), the book being all cash until the first fill. Where the engine refuses a fill the book cannot
    pay (``run_checked``), on the bars before it."""
    panel, rule, params = case
    panel, result = run_checked(rule, params, panel, costs)
    _, _, v_open, value, _ = unit_book(panel, target_of(params), result, costs)
    tr = result.attrs["trade_returns"]
    assert len(tr) == len(v_open) == result.attrs["n_trades"]
    ends = [*v_open[1:], value[-1]]
    np.testing.assert_allclose(1.0 + tr, np.array(ends) / np.array(v_open), rtol=1e-12, atol=0)
    growth = np.prod(1.0 + result["ret"].to_numpy())
    assert np.prod(1.0 + tr) == pytest.approx(growth, rel=1e-12)
    if len(v_open):
        assert v_open[0] == pytest.approx(costs.capital_usd, rel=1e-15)
        assert np.prod(1.0 + tr) == pytest.approx(value[-1] / v_open[0], rel=1e-12)


@given(case=cases())
def test_outputs_stay_in_bounds(case):
    panel, rule, params = case
    result = rule(params, panel, Costs())
    validate_result(result, panel)
    w = result[list(pf.WEIGHT_COLUMNS)].to_numpy()
    assert (w >= 0.0).all() and (w <= 1.0 + WEIGHT_TOL).all()  # spot only: no shorts, no leverage
    np.testing.assert_allclose(result["position"], w.sum(axis=1), rtol=0, atol=1e-15)
    assert (result["turnover"] <= 2.0 + WEIGHT_TOL).all()  # two legs, each at most the whole book
    assert (result["cost"] < 1.0).all() and (result["ret"] > -1.0).all()
    assert np.isfinite(result.attrs["trade_returns"]).all() and (result.attrs["trade_returns"] > -1.0).all()


@given(panel=panels(), params=rebalance_params())
def test_orders_follow_the_rule(panel, params):
    """Re-derive every order from the weights at each close: close 0; any close where a limit is breached; and
    the check closes 0, every, 2*every, ... where some asset is more than ``band`` off its target. The last close
    never sends one. Each order trades exactly the weights that drifted to the next open back to target."""
    result = pf.rebalance(params, panel, Costs())
    wb, we = (result[col].to_numpy() for col in pf.WEIGHT_COLUMNS)
    tb, te, band, every = params["w_btc"], params["w_eth"], params["band"], params["every"]
    min_cash, max_coin = params.get("min_cash"), params.get("max_coin")

    def breached(t):
        too_little_cash = min_cash is not None and wb[t] + we[t] > 1.0 - min_cash + 1e-9
        too_much_coin = max_coin is not None and max(wb[t], we[t]) > max_coin + 1e-9
        return too_little_cash or too_much_coin

    expected = [
        t
        for t in range(len(panel) - 1)
        if t == 0 or breached(t) or (t % every == 0 and (abs(wb[t] - tb) > band or abs(we[t] - te) > band))
    ]
    np.testing.assert_array_equal(result.attrs["orders"], expected)
    o = {a: panel[(a, "open")].to_numpy() for a in ASSETS}
    c = {a: panel[(a, "close")].to_numpy() for a in ASSETS}
    for t in expected:
        g = {a: o[a][t + 1] / c[a][t] - 1.0 for a in ASSETS}
        grow = 1.0 + wb[t] * g["BTC"] + we[t] * g["ETH"]
        drifted = (wb[t] * (1 + g["BTC"]) / grow, we[t] * (1 + g["ETH"]) / grow)
        traded = abs(tb - drifted[0]) + abs(te - drifted[1])
        assert result["turnover"].iloc[t + 1] == pytest.approx(traded, rel=1e-12, abs=1e-15)


def test_runs_are_deterministic_and_leave_inputs_alone():
    panel = random_panel(200, seed=8)
    before = panel.copy()
    attrs_before = copy.deepcopy(panel.attrs)
    for rule, params in (
        (pf.rebalance, {**GOOD, "min_cash": 0.2, "max_coin": 0.5}),
        (pf.random_rebalance, {"w_btc": 0.5, "w_eth": 0.2, "n_rebalances": 9, "seed": 4}),
    ):
        params_before = dict(params)
        a = rule(params, panel, Costs())
        b = rule(params, panel, Costs())
        np.testing.assert_array_equal(a[ALL_COLUMNS].to_numpy(), b[ALL_COLUMNS].to_numpy())
        np.testing.assert_array_equal(a.attrs["trade_returns"], b.attrs["trade_returns"])
        np.testing.assert_array_equal(a.attrs["orders"], b.attrs["orders"])
        pd.testing.assert_frame_equal(a.attrs["fills"], b.attrs["fills"])
        assert a.attrs["n_trades"] == b.attrs["n_trades"]
        assert params == params_before
    pd.testing.assert_frame_equal(panel, before)
    assert panel.attrs == attrs_before


# --------------------------------------------------------------------------- hand-built two-asset panels


def test_first_buy_fills_at_the_open_of_bar_1_and_each_leg_pays_its_own_size(make_bars):
    """Targets 0.5 BTC / 0.3 ETH from 10000 USD: legs of 5000 and 3000 USD at the opens of bar 1. Slippage by hand
    from the fixed test cost model ``Costs()`` (log10-linear between 1000 USD -> 15 bps and 10000 USD -> 30 bps;
    #64: not the config file, whose values the owner may change)."""
    panel = hand_panel(make_bars, [100.0, 105.0, 110.0], [50.0, 49.0, 48.0])
    costs = Costs()
    result = pf.rebalance({"w_btc": 0.5, "w_eth": 0.3, "band": 1.0, "every": 1}, panel, costs)

    def slip(usd):  # 1000 < usd < 10000
        return 15.0 + (30.0 - 15.0) * (math.log10(usd) - 3.0) / (4.0 - 3.0)

    leg_btc = 5000.0 * (5.0 + 0.0 + slip(5000.0)) / 1e4 + 0.10
    leg_eth = 3000.0 * (5.0 + 0.0 + slip(3000.0)) / 1e4 + 0.10
    log = result.attrs["fills"]
    assert (
        list(log["bar"]) == [1, 1]
        and list(log["asset"]) == ["BTC", "ETH"]
        and list(log["side"]) == ["buy"] * 2
    )
    np.testing.assert_array_equal(log["price"], [100.0, 50.0])  # the opens of bar 1 (= the closes of bar 0)
    assert log["usd"].tolist() == pytest.approx([5000.0, 3000.0], rel=1e-15)
    assert log["units"].tolist() == pytest.approx([50.0, 60.0], rel=1e-15)
    assert log["cost"].tolist() == pytest.approx([leg_btc, leg_eth], rel=1e-14)
    cost = (leg_btc + leg_eth) / 10_000.0
    assert result["cost"].iloc[1] == pytest.approx(cost, rel=1e-14)
    assert result["turnover"].iloc[1] == pytest.approx(0.8, rel=1e-15)
    h_btc, h_eth = 105.0 / 100.0 - 1.0, 49.0 / 50.0 - 1.0
    assert result["ret"].iloc[1] == pytest.approx(
        (1.0 - cost) * (1.0 + 0.5 * h_btc + 0.3 * h_eth) - 1.0, rel=1e-13
    )
    assert result["ret"].iloc[0] == 0.0 and result["position"].iloc[0] == 0.0


def test_a_later_rebalance_prices_each_leg_on_its_own_usd_size(make_bars):
    """The rebalance at bar 5 (ordered at close 4): V_open from the units bought at bar 1, each leg's size
    |target * V_open - units * open|, leg cost = usd * rate(usd) + gas, all by hand."""
    panel = hand_panel(make_bars, [100.0, 120.0, 140.0, 149.0, 151.0, 151.0, 151.0], [100.0] * 7)
    costs = Costs()
    result = pf.rebalance({"w_btc": 0.4, "w_eth": 0.4, "band": 0.1, "every": 1}, panel, costs)
    np.testing.assert_array_equal(result.attrs["orders"], [0, 4])
    first = (0.4 * 10_000.0) * costs.rate(4000.0) + costs.gas_usd_per_trade
    after = 10_000.0 - 2 * first
    units = 0.4 * after / 100.0  # BTC and ETH: both opened at 100
    cash = 0.2 * after
    v_open = cash + units * 151.0 + units * 100.0  # the opens of bar 5
    usd_btc = abs(0.4 * v_open - units * 151.0)
    usd_eth = abs(0.4 * v_open - units * 100.0)
    log = result.attrs["fills"].query("bar == 5")
    assert list(log["asset"]) == ["BTC", "ETH"] and list(log["side"]) == ["sell", "buy"]
    assert log["usd"].tolist() == pytest.approx([usd_btc, usd_eth], rel=1e-13)
    legs = [usd * costs.rate(usd) + costs.gas_usd_per_trade for usd in (usd_btc, usd_eth)]
    assert log["cost"].tolist() == pytest.approx(legs, rel=1e-13)
    assert result["cost"].iloc[5] == pytest.approx(sum(legs) / v_open, rel=1e-13)
    assert result["turnover"].iloc[5] == pytest.approx((usd_btc + usd_eth) / v_open, rel=1e-13)


def test_gas_is_paid_per_leg(make_bars):
    gas_only = Costs(pool_fee_bps=0.0, slippage_bps=((1.0, 0.0),), gas_usd_per_trade=1.0)
    panel = hand_panel(make_bars, [100.0, 101.0, 102.0], [50.0, 50.5, 51.0])
    two = pf.rebalance({"w_btc": 0.5, "w_eth": 0.3, "band": 1.0, "every": 1}, panel, gas_only)
    one = pf.rebalance({"w_btc": 0.5, "w_eth": 0.0, "band": 1.0, "every": 1}, panel, gas_only)
    assert two["cost"].iloc[1] == pytest.approx(2.0 / 10_000.0, rel=1e-15)
    assert one["cost"].iloc[1] == pytest.approx(1.0 / 10_000.0, rel=1e-15)
    assert len(two.attrs["fills"]) == 2 and len(one.attrs["fills"]) == 1


def test_coin_units_drift_between_fills(make_bars):
    """A static 0.5 BTC / 0.25 ETH mix at zero cost: 50 BTC units at 100 and 50 ETH units at 50 plus 2500 USD
    cash, held while BTC rises 10% a day and ETH stays flat; the weights drift, by hand."""
    btc = [100.0, 110.0, 121.0, 133.1, 146.41]
    panel = hand_panel(make_bars, btc, [50.0] * 5)
    result = pf.rebalance({"w_btc": 0.5, "w_eth": 0.25, "band": 1.0, "every": 1}, panel, Costs.zero())
    value = [10_000.0] + [2500.0 + 50.0 * p + 50.0 * 50.0 for p in btc[1:]]
    for t in range(1, 5):
        assert result["w_BTC"].iloc[t] == pytest.approx(50.0 * btc[t] / value[t], rel=1e-14)
        assert result["w_ETH"].iloc[t] == pytest.approx(2500.0 / value[t], rel=1e-14)
        assert result["ret"].iloc[t] == pytest.approx(value[t] / value[t - 1] - 1.0, rel=1e-13)
    assert result.attrs["n_trades"] == 1
    assert result.attrs["fills"]["units"].tolist() == pytest.approx([50.0, 50.0], rel=1e-15)
    # the units implied by the weights stay constant between fills
    v = CAPITAL * np.cumprod(1.0 + result["ret"].to_numpy())
    units = result["w_BTC"].to_numpy()[1:] * v[1:] / np.array(btc[1:])
    np.testing.assert_allclose(units, 50.0, rtol=1e-13)


@pytest.mark.parametrize(
    ("btc", "eth", "orders"),
    [
        # BTC up: its weight passes 0.4 + 0.1 at the close of 151 (0.5017; 149 gives 0.4983)
        ([100.0, 120.0, 140.0, 149.0, 151.0, 151.0, 151.0], [100.0] * 7, [0, 4]),
        # ETH down alone: its weight falls below 0.4 - 0.1 at 64 (0.2991; 65 gives 0.3023), BTC stays in band
        ([100.0] * 7, [100.0, 80.0, 70.0, 65.0, 64.0, 64.0, 64.0], [0, 4]),
        # never more than the band off: no rebalance
        ([100.0, 120.0, 140.0, 149.0, 149.0], [100.0] * 5, [0]),
        # the trigger at the LAST close is never sent (it could not fill)
        ([100.0, 120.0, 140.0, 149.0, 151.0], [100.0] * 5, [0]),
    ],
)
def test_band_any_asset_off_by_more_than_band_rebalances_every_leg(make_bars, btc, eth, orders):
    panel = hand_panel(make_bars, btc, eth)
    result = pf.rebalance({"w_btc": 0.4, "w_eth": 0.4, "band": 0.1, "every": 1}, panel, Costs.zero())
    np.testing.assert_array_equal(result.attrs["orders"], orders)
    np.testing.assert_array_equal(fill_bars_of(result), np.array(orders) + 1)
    if len(orders) == 2:  # both legs go back to target at the next open
        t = orders[1] + 1
        legs = result.attrs["fills"].query(f"bar == {t}")
        assert list(legs["asset"]) == ["BTC", "ETH"]
        np.testing.assert_array_equal(legs["weight_after"], [0.4, 0.4])
        assert result["w_BTC"].iloc[t] == pytest.approx(0.4, rel=1e-15)  # flat bar after the fill


def test_band_is_strict(make_bars):
    """0.5 BTC and 0.5 cash; a close of 300 puts the BTC weight at exactly 0.75 = 0.5 + band: not more than the
    band, so no order; at 301 it is more."""
    at = pf.rebalance(
        {"w_btc": 0.5, "w_eth": 0.0, "band": 0.25, "every": 1},
        hand_panel(make_bars, [100.0, 300.0, 300.0, 300.0], [10.0] * 4),
        Costs.zero(),
    )
    assert at["w_BTC"].iloc[1] == 0.75
    np.testing.assert_array_equal(at.attrs["orders"], [0])
    above = pf.rebalance(
        {"w_btc": 0.5, "w_eth": 0.0, "band": 0.25, "every": 1},
        hand_panel(make_bars, [100.0, 301.0, 301.0, 301.0], [10.0] * 4),
        Costs.zero(),
    )
    np.testing.assert_array_equal(above.attrs["orders"], [0, 1])


@pytest.mark.parametrize(("every", "orders"), [(1, [0, 1]), (2, [0, 2]), (3, [0, 3]), (5, [0, 5]), (10, [0])])
def test_every_checks_only_at_multiples_of_every_from_close_0(make_bars, every, orders):
    """BTC jumps to 160 at close 1 and stays there (weight 0.5161 against 0.4 + 0.1): the first check close at or
    after 1 rebalances; with every = 10 there is none before the last close."""
    panel = hand_panel(make_bars, [100.0] + [160.0] * 8, [100.0] * 9)
    result = pf.rebalance({"w_btc": 0.4, "w_eth": 0.4, "band": 0.1, "every": every}, panel, Costs.zero())
    np.testing.assert_array_equal(result.attrs["orders"], orders)


def test_check_closes_stay_on_the_grid_from_close_0_after_a_forced_order(make_bars):
    """0.5 BTC / 0.2 ETH, max_coin 0.6, band 0.05, every 4. BTC at 160 breaches at close 2 (1.6/2.6 = 0.615): a
    forced order off the grid. BTC at 208 puts it at 1.3/2.3 = 0.565 at close 4, more than the band but inside the
    limit: close 4 is a check close (counted from close 0, not from the forced order at 2), so it orders there,
    not at close 6."""
    panel = hand_panel(make_bars, [100.0, 100.0, 160.0, 160.0, 208.0, 208.0, 208.0, 208.0], [100.0] * 8)
    params = {"w_btc": 0.5, "w_eth": 0.2, "band": 0.05, "every": 4, "max_coin": 0.6}
    result = pf.rebalance(params, panel, Costs.zero())
    assert result["w_BTC"].iloc[2] == pytest.approx(1.6 / 2.6, rel=1e-14)
    assert result["w_BTC"].iloc[4] == pytest.approx(1.3 / 2.3, rel=1e-14)
    np.testing.assert_array_equal(result.attrs["orders"], [0, 2, 4])


def test_the_band_is_judged_at_the_close_not_at_the_next_open():
    """0.4 / 0.4, band 0.1: BTC closes bar 1 at 151 (weight 0.604 / 1.204 = 0.5017, out of the band) and opens bar 2
    at 120 (0.48 / 1.08 = 0.444, back in it). The order decided at close 1 is sent and fills at that open; a rule
    peeking at the next open would not send it."""
    btc = bars_from([100.0, 100.0, 120.0, 120.0], [100.0, 151.0, 120.0, 120.0])
    panel = pf.make_panel({"BTC": btc, "ETH": bars_from([100.0] * 4, [100.0] * 4)}, snapshot_id="hand")
    result = pf.rebalance({"w_btc": 0.4, "w_eth": 0.4, "band": 0.1, "every": 1}, panel, Costs.zero())
    assert result["w_BTC"].iloc[1] == pytest.approx(0.604 / 1.204, rel=1e-14)
    np.testing.assert_array_equal(result.attrs["orders"], [0, 1])
    legs = result.attrs["fills"].query("bar == 2")
    assert legs["weight_before"].iloc[0] == pytest.approx(0.48 / 1.08, rel=1e-14)
    assert legs["price"].iloc[0] == 120.0


def test_max_coin_breach_forces_a_rebalance_off_schedule(make_bars):
    """0.5 BTC / 0.2 ETH with max_coin 0.6, a band and a schedule that never trigger: BTC at 160 puts it at
    160/260 = 0.615 > 0.6 at close 3, which forces the order at close 3 (filled at the open of bar 4)."""
    panel = hand_panel(make_bars, [100.0, 110.0, 130.0, 160.0, 160.0, 160.0], [100.0] * 6)
    params = {"w_btc": 0.5, "w_eth": 0.2, "band": 5.0, "every": 1000}
    off = pf.rebalance(params, panel, Costs.zero())
    np.testing.assert_array_equal(off.attrs["orders"], [0])
    on = pf.rebalance({**params, "max_coin": 0.6}, panel, Costs.zero())
    assert on["w_BTC"].iloc[3] == pytest.approx(160.0 / 260.0, rel=1e-14)
    np.testing.assert_array_equal(on.attrs["orders"], [0, 3])
    np.testing.assert_array_equal(fill_bars_of(on), [1, 4])
    assert on["w_BTC"].iloc[4] == pytest.approx(0.5, rel=1e-15)


def test_min_cash_breach_forces_a_rebalance_off_schedule(make_bars):
    """0.35 / 0.35 with 0.3 cash and min_cash 0.2: both coins at 180 leave 3000/15600 = 0.192 cash at close 4."""
    path = [100.0, 120.0, 150.0, 160.0, 180.0, 180.0, 180.0]
    panel = hand_panel(make_bars, path, path)
    params = {"w_btc": 0.35, "w_eth": 0.35, "band": 1.0, "every": 1000}
    np.testing.assert_array_equal(pf.rebalance(params, panel, Costs.zero()).attrs["orders"], [0])
    on = pf.rebalance({**params, "min_cash": 0.2}, panel, Costs.zero())
    cash = 1.0 - on["position"].to_numpy()
    assert cash[3] == pytest.approx(3000.0 / 14200.0, rel=1e-13) and cash[4] == pytest.approx(
        3000.0 / 15600.0, rel=1e-13
    )
    np.testing.assert_array_equal(on.attrs["orders"], [0, 4])
    assert 1.0 - on["position"].iloc[5] == pytest.approx(0.3, rel=1e-14)


def test_a_breach_is_judged_at_the_close_and_filled_at_the_next_open(make_bars):
    """BTC closes bar 1 at 160 (weight 0.8 / 1.3 = 0.615 > max_coin 0.6) and opens bar 2 at 110, where its drifted
    weight is back inside the limit: the order decided at close 1 still fills at the open of bar 2."""
    btc = bars_from([100.0, 100.0, 110.0, 110.0], [100.0, 160.0, 110.0, 110.0])
    panel = pf.make_panel({"BTC": btc, "ETH": make_bars([100.0] * 4)}, snapshot_id="hand")
    result = pf.rebalance(
        {"w_btc": 0.5, "w_eth": 0.2, "band": 5.0, "every": 1000, "max_coin": 0.6}, panel, Costs()
    )
    np.testing.assert_array_equal(result.attrs["orders"], [0, 1])
    legs = result.attrs["fills"].query("bar == 2")
    assert legs["weight_before"].iloc[0] < 0.6
    assert legs["price"].iloc[0] == 110.0


def test_targets_exactly_at_the_limits_are_allowed_and_round_off_never_forces_a_trade(make_bars):
    panel = hand_panel(make_bars, [100.0] * 6, [50.0] * 6)
    result = pf.rebalance(
        {"w_btc": 0.5, "w_eth": 0.3, "band": 0.0, "every": 1, "min_cash": 0.2, "max_coin": 0.5},
        panel,
        Costs(),
    )
    np.testing.assert_array_equal(result.attrs["orders"], [0])


def test_targets_on_a_limit_up_to_round_off_are_accepted(make_bars):
    """0.2 + 0.4 == 0.6000000000000001 > 1 - 0.4: decimal targets exactly on min_cash are accepted (LIMIT_TOL), and
    on flat prices the book at target never counts as a breach."""
    assert 0.2 + 0.4 > 1.0 - 0.4
    panel = hand_panel(make_bars, [100.0] * 6, [50.0] * 6)
    result = pf.rebalance(
        {"w_btc": 0.2, "w_eth": 0.4, "band": 0.0, "every": 1, "min_cash": 0.4}, panel, Costs()
    )
    np.testing.assert_array_equal(result.attrs["orders"], [0])


def test_static_mix_never_rebalances_after_the_first_buy():
    panel = random_panel(300, seed=9, vols=(0.08, 0.1))
    for band in (1.0, 3.5):
        result = pf.rebalance({"w_btc": 0.5, "w_eth": 0.3, "band": band, "every": 1}, panel, Costs())
        np.testing.assert_array_equal(result.attrs["orders"], [0])
        assert result.attrs["n_trades"] == 1 and len(result.attrs["trade_returns"]) == 1
    limited = pf.rebalance(
        {"w_btc": 0.5, "w_eth": 0.3, "band": 1.0, "every": 1, "max_coin": 0.55}, panel, Costs()
    )
    assert len(limited.attrs["orders"]) > 1  # a limit still forces trades whatever the band


# --------------------------------------------------------------------------------------------- parity


@given(
    panel=panels(),
    w_btc=st.one_of(st.sampled_from([0.1, 0.5, 0.6, 1.0]), st.floats(1e-6, 1.0)),
    every=st.integers(1, 12),
    band=st.one_of(st.sampled_from([0.0, 0.01, 0.05]), st.floats(0.0, 0.99)),
    costs=st.sampled_from((Costs.zero(), *COST_MODELS)),
)
@example(panel=random_panel(60, seed=1), w_btc=0.5, every=1, band=0.0, costs=Costs())
@example(  # a ruined book (TESTING.md #49): 25 USD of gas a day drains the cash, and both refuse the fill on bar 116
    panel=random_panel(120, 10, (0.1, 0.0), (0.03, 0.0)),
    w_btc=0.6,
    every=1,
    band=0.0,
    costs=Costs(pool_fee_bps=30.0, aggregator_fee_bps=10.0, gas_usd_per_trade=25.0),
)
def test_btc_only_equals_reference_constant_mix_bit_for_bit(panel, w_btc, every, band, costs):
    """With w_eth = 0 and no limits, the portfolio equals ``reference.constant_mix`` on the BTC bars exactly (no
    tolerance) in ret, position, turnover and cost, with costs on: the same execution model, operation for
    operation. A fill the book cannot pay is refused by both, with the same message (``run_checked`` checks it
    against the unit book), and both runs are compared on the bars before it."""
    params = {"w_btc": w_btc, "w_eth": 0.0, "band": band, "every": every}
    bars, mine = run_checked(pf.rebalance, params, panel, costs)
    if len(bars) < len(panel):
        with pytest.raises(ValueError, match="it cannot pay them") as refused:
            pf.rebalance(params, panel, costs)
        with pytest.raises(ValueError, match="it cannot pay them") as ref_refused:
            reference.constant_mix(
                {"weight": w_btc, "every": every, "band": band}, pf.asset_bars(panel, "BTC"), costs
            )
        assert str(ref_refused.value) == str(refused.value)
    ref = reference.constant_mix(
        {"weight": w_btc, "every": every, "band": band}, pf.asset_bars(bars, "BTC"), costs
    )
    for col in RESULT_COLUMNS:
        np.testing.assert_array_equal(mine[col].to_numpy(), ref[col].to_numpy(), err_msg=col)
    np.testing.assert_array_equal(mine["w_BTC"].to_numpy(), mine["position"].to_numpy())
    assert (mine["w_ETH"] == 0.0).all()
    assert mine.attrs["n_trades"] == ref.attrs["n_trades"]
    assert set(mine.attrs["fills"]["asset"]) <= {"BTC"}
    trades = ref.attrs["trades"]
    np.testing.assert_array_equal(mine.attrs["fills"]["price"].to_numpy(), trades["price"].to_numpy())
    np.testing.assert_array_equal(
        mine.attrs["fills"]["weight_before"].to_numpy(), trades["weight_before"].to_numpy()
    )
    # constant_mix logs one round trip, still open at the end; the chained fill periods multiply to the same growth
    assert np.prod(1.0 + mine.attrs["trade_returns"]) == pytest.approx(
        1.0 + ref.attrs["trade_returns"][0], rel=1e-12
    )


# ------------------------------------------------------------------------------------- random_rebalance


def test_random_rebalance_draws_distinct_seeded_closes_never_the_last():
    panel = random_panel(120, seed=10)
    params = {"w_btc": 0.5, "w_eth": 0.3, "n_rebalances": 12, "seed": 3}
    result = pf.random_rebalance(params, panel, Costs())
    closes = result.attrs["rebalance_closes"]
    assert len(closes) == 12 == len(set(closes.tolist()))
    assert closes.min() >= 1 and closes.max() <= len(panel) - 2
    assert (np.diff(closes) > 0).all()
    np.testing.assert_array_equal(result.attrs["orders"], [0, *closes])
    np.testing.assert_array_equal(
        fill_bars_of(result), [1, *(closes + 1)]
    )  # every one trades on moving prices
    assert result.attrs["n_trades"] == 13
    same = pf.random_rebalance(params, panel, Costs())
    np.testing.assert_array_equal(same.attrs["rebalance_closes"], closes)
    other = pf.random_rebalance({**params, "seed": 4}, panel, Costs())
    assert not np.array_equal(other.attrs["rebalance_closes"], closes)
    # the draw depends on len(bars) and the seed only, never on prices
    elsewhere = pf.random_rebalance(params, random_panel(120, seed=99, vols=(0.1, 0.01)), Costs())
    np.testing.assert_array_equal(elsewhere.attrs["rebalance_closes"], closes)
    # the default seed is 0
    seedless = {k: v for k, v in params.items() if k != "seed"}
    np.testing.assert_array_equal(
        pf.random_rebalance(seedless, panel, Costs()).attrs["rebalance_closes"],
        pf.random_rebalance({**seedless, "seed": 0}, panel, Costs()).attrs["rebalance_closes"],
    )


def test_random_rebalance_extremes():
    panel = random_panel(30, seed=11)
    none = pf.random_rebalance({"w_btc": 0.5, "w_eth": 0.3, "n_rebalances": 0}, panel, Costs())
    np.testing.assert_array_equal(none.attrs["orders"], [0])
    assert len(none.attrs["rebalance_closes"]) == 0
    every_close = pf.random_rebalance({"w_btc": 0.5, "w_eth": 0.3, "n_rebalances": 28}, panel, Costs())
    np.testing.assert_array_equal(every_close.attrs["rebalance_closes"], np.arange(1, 29))
    np.testing.assert_array_equal(every_close.attrs["orders"], np.arange(0, 29))
    two_bars = random_panel(2, seed=12)
    tiny = pf.random_rebalance({"w_btc": 0.5, "w_eth": 0.3, "n_rebalances": 0}, two_bars, Costs())
    assert tiny.attrs["n_trades"] == 1


@given(panel=panels(), params=rebalance_params(), seed=st.integers(0, 2**16))
def test_random_rebalance_with_the_rule_s_count_matches_its_trades(panel, params, seed):
    """The luck benchmark at the same number of rebalances as the rule: same number of orders, same targets."""
    rule = pf.rebalance(params, panel, Costs())
    n_reb = len(rule.attrs["orders"]) - 1
    luck = pf.random_rebalance(
        {"w_btc": params["w_btc"], "w_eth": params["w_eth"], "n_rebalances": n_reb, "seed": seed},
        panel,
        Costs(),
    )
    assert len(luck.attrs["orders"]) == len(rule.attrs["orders"])
    validate_result(luck, panel)


# --------------------------------------------------------------------------------------- lab/search


SPECS = [
    Param("w_btc", "float", 0.1, 0.5),
    Param("w_eth", "float", 0.05, 0.3),
    Param("band", "float", 0.0, 0.15),
    Param("every", "int", 1, 30),
]


def test_evaluate_params_counts_fill_bars_as_trades():
    """objective.evaluate_params counts len(attrs["trade_returns"]): for this runner, the fill bars (the first
    buy plus every rebalance that traded). A static mix has 1, under min_trades = 5, so it scores -10."""
    panel = random_panel(300, seed=13)
    params = {"w_btc": 0.4, "w_eth": 0.2, "band": 0.02, "every": 5}
    res = evaluate_params(pf.rebalance, params, panel)
    direct = pf.rebalance(params, panel)
    assert res["n_trades"] == direct.attrs["n_trades"] == len(direct.attrs["trade_returns"]) >= 5
    assert res["score"] > -10.0
    np.testing.assert_array_equal(res["returns"].to_numpy(), direct["ret"].to_numpy())
    static = evaluate_params(pf.rebalance, {**params, "band": 1.0}, panel)
    assert static["n_trades"] == 1 and static["score"] == -10.0


def test_lab_search_runs_unchanged_on_a_two_asset_panel(tmp_path):
    """run_study (n_workers=1), walk_forward_optimize on 2 folds, overfitting_report and gates, as they are,
    with rebalance as the backtest function on a synthetic BTC + ETH panel."""
    panel = pf.make_panel(synthetic_market(600, seed=5, start="2019-01-01"), snapshot_id="synthetic-5")
    cfg = SearchConfig(n_trials=6, n_workers=1, seed=0)
    trials = run_study("rb", pf.rebalance, SPECS, panel.iloc[:300], tmp_path, cfg)
    assert len(trials) == 6 and (trials["state"] == "COMPLETE").all()
    assert np.isfinite(trials["value"]).all() and np.isfinite(trials["sharpe"]).all()
    assert (trials["n_trades"] >= 1).all()
    assert {f"params_{p.name}" for p in SPECS} <= set(trials.columns)
    returns = load_trial_returns("rb", tmp_path)
    assert returns.shape == (300, 6) and np.isfinite(returns.to_numpy()).all()

    folds = walk_forward(len(panel), train_size=250, test_size=100)[:2]
    wf = walk_forward_optimize(
        "wf", pf.rebalance, SPECS, panel, folds, tmp_path, replace(cfg, n_trials=5), warmup=30
    )
    assert len(wf["folds"]) == 2 and wf["total_trials"] == 10
    assert len(wf["oos_returns"]) == 2 * 99  # each test block minus its first bar (decided before the block)
    assert np.isfinite(wf["oos_returns"].to_numpy()).all() and np.isfinite(wf["oos_sharpe"])
    assert wf["oos_returns"].index.is_monotonic_increasing
    for name in ("w_btc", "w_eth", "band", "every"):
        assert f"p_{name}" in wf["folds"].columns
    rep = overfitting_report(wf, tmp_path)
    assert set(rep) == {
        "oos_sharpe_annual",
        "oos_total_return",
        "oos_max_drawdown",
        "wf_efficiency",
        "trials_raw",
        "trials_effective",
        "dsr_raw_count",
        "dsr_effective_count",
        "pbo_mean",
        "mc_drawdown_worst5pct",
        "mc_drawdown_median",
    }
    finite = set(rep) - {"wf_efficiency", "trials_raw", "trials_effective"}
    for key in sorted(finite):
        assert np.isfinite(rep[key]), key
    assert 0.0 <= rep["dsr_effective_count"] <= 1.0 and 0.0 <= rep["pbo_mean"] <= 1.0
    assert rep["trials_raw"] == 10
    verdict = gates(rep, budget_drawdown=0.5)
    assert len(verdict) == 4 and all(isinstance(v, (bool, np.bool_)) for v in verdict.values())
