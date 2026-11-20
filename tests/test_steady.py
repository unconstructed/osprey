"""The rebalance-steady adapter and harness (``lab/runner/steady.py``), against PLAN.md sections 4-12 and the
test list of section 14. SYNTHETIC data only: ``lab.data.synthetic``, ``portfolio.make_panel``, hand-built paths
and ``tmp_path`` configs. No catalog read.
"""

from __future__ import annotations

import hashlib
import math
import pickle
import struct
from dataclasses import replace
from functools import partial

import numpy as np
import pandas as pd
import pytest
from hypothesis import example, given
from hypothesis import strategies as st

from lab.data.synthetic import synthetic_market
from lab.runner import portfolio as pf
from lab.runner import reference
from lab.runner import steady as sd
from lab.runner.interface import BAR_COLUMNS, validate_result
from lab.runner.reference import Costs
from lab.search.report import overfitting_report
from lab.search.space import Param
from lab.search.stability import stable_region
from lab.search.study import SearchConfig, load_trials, run_study
from lab.search.walkforward import walk_forward_optimize
from lab.validation import stats
from lab.validation.splits import walk_forward

LIM = sd.steady_limits()  # config/risk_levels.yaml as read
COSTS = Costs.from_yaml()
RESULT_COLUMNS = ["ret", "position", "turnover", "cost", "w_BTC", "w_ETH"]
STEADY = "  coins: [BTC, ETH, USDC]\n  min_cash_pct: 20\n  max_coin_pct: 60\n  max_drawdown_budget_pct: TBD\n"
GOOD = {"coin_share": 0.5, "btc_share": 0.25, "band_rel": 0.1, "every": 7}

# ------------------------------------------------------------------------------------------------ helpers


def random_bars(n: int, seed: int, vol: float, gap: float, start: float, first="2021-01-01") -> pd.DataFrame:
    """Valid daily bars with overnight gaps (open != previous close)."""
    rng = np.random.default_rng(seed)
    body = rng.normal(0.0, vol, n)
    gaps = rng.normal(0.0, gap, n)
    gaps[0] = 0.0
    log_close = math.log(start) + np.cumsum(gaps + body)
    close = np.exp(log_close)
    open_ = np.exp(log_close - body)
    wick = rng.uniform(0.0, 0.02, (2, n))
    index = pd.date_range(first, periods=n, freq="D", tz="UTC", name="ts")
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


@st.composite
def panels(draw, min_size: int = 20, max_size: int = 120) -> pd.DataFrame:
    n = draw(st.integers(min_size, max_size))
    seed = draw(st.integers(0, 2**32 - 2))
    vols = tuple(draw(st.sampled_from([0.0, 0.01, 0.04, 0.1])) for _ in pf.ASSETS)
    gaps = tuple(draw(st.sampled_from([0.0, 0.005, 0.03])) for _ in pf.ASSETS)
    return random_panel(n, seed, vols, gaps)


box_params = st.fixed_dictionaries(
    {
        "coin_share": st.floats(0.20, 0.77),
        "btc_share": st.floats(0.25, 0.75),
        "band_rel": st.floats(0.02, 0.50),
        "every": st.integers(1, 90),
    }
)


def tamper_from(panel: pd.DataFrame, cut: int, seed: int) -> pd.DataFrame:
    """Change every field of every asset from bar ``cut`` on, except each asset's open of bar ``cut`` (the fill
    price of the decision taken at close cut-1)."""
    rng = np.random.default_rng(seed)
    n = len(panel)
    frames = {}
    for asset in pf.ASSETS:
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


def write_levels(path, steady: str) -> None:
    (path / "risk_levels.yaml").write_text(f"steady:\n{steady}balanced:\n  coins: [BTC]\n")


def chosen_params(wf: dict, i: int) -> dict:
    row = wf["folds"].iloc[i]
    return {name: row[f"p_{name}"] for name in sd.PARAM_NAMES}


def breached(w_btc: float, w_eth: float) -> bool:
    tol = pf.LIMIT_TOL
    return (
        w_btc + w_eth > 1.0 - LIM["min_cash"] + tol
        or w_btc > LIM["max_coin"] + tol
        or w_eth > LIM["max_coin"] + tol
    )


# ------------------------------------------------------------------------- a walk-forward on synthetic data


@pytest.fixture(scope="module")
def wf_run(tmp_path_factory):
    """``walk_forward_optimize`` exactly as PLAN.md section 7 runs it (expanding folds, warmup 120, stable region,
    ``n_workers = 1``), on a 700-row synthetic panel with 3 folds of 150 test rows and 12 trials per study, plus a
    final study at seed + 4000 and a 1-trial study (which the report skips)."""
    out = tmp_path_factory.mktemp("steady_wf")
    panel = pf.make_panel(synthetic_market(700, seed=5, start="2019-01-02"), snapshot_id="synthetic-5")
    fn = partial(sd.steady_backtest, limits=LIM, costs=COSTS)
    folds = walk_forward(len(panel), train_size=250, test_size=150, expanding=True)
    cfg = SearchConfig(n_trials=12, n_workers=1, seed=0)
    wf = walk_forward_optimize("rs-s0", fn, sd.SPECS, panel, folds, out, cfg, warmup=sd.WARMUP)
    run_study("rs-s0_final", fn, sd.SPECS, panel, out, replace(cfg, seed=4000))
    run_study("rs-one", fn, sd.SPECS, panel.iloc[:300], out, replace(cfg, n_trials=1))
    return {"out": out, "panel": panel, "fn": fn, "folds": folds, "wf": wf, "cfg": cfg}


# ----------------------------------------------------------------------------------- the strategy and limits


def test_specs_and_pinned_constants_are_the_plan_s():
    assert list(sd.SPECS) == [
        Param("coin_share", "float", 0.20, 0.77),
        Param("btc_share", "float", 0.25, 0.75),
        Param("band_rel", "float", 0.02, 0.50, log=True),
        Param("every", "int", 1, 90, log=True),
    ]
    assert sd.PARAM_NAMES == tuple(p.name for p in sd.SPECS)
    assert sd.HEADROOM == 0.02 and sd.WARMUP == 120
    assert (sd.B3_DRAWS, sd.BOOTSTRAP_RESAMPLES, sd.MEAN_BLOCK) == (1000, 10_000, 20)
    assert (sd.PLATEAU_FACTORS, sd.PLATEAU_KEEP, sd.REGIME_THRESHOLD) == ((0.8, 1.2), 0.7, 0.10)
    assert sd.MARKS == ("free", "clipped", "at the limit") and sd.REGIMES == ("bull", "bear", "sideways")


def test_the_limits_are_the_config_file_s():
    assert LIM == pf.risk_limits("steady")
    assert (LIM["min_cash"], LIM["max_coin"]) == (0.2, 0.6)


@given(s=st.floats(0.20, 0.77), f=st.floats(0.25, 0.75))
@example(s=0.77, f=0.75)
@example(s=0.77, f=0.25)
@example(s=0.20, f=0.25)
def test_every_point_of_the_box_keeps_the_headroom_from_both_limits_as_read(s, f):
    w_btc, w_eth = sd.targets({"coin_share": s, "btc_share": f, "band_rel": 0.1, "every": 5})
    assert (w_btc, w_eth) == (s * f, s * (1.0 - f))
    pf.check_targets(w_btc, w_eth, min_cash=LIM["min_cash"], max_coin=LIM["max_coin"], headroom=sd.HEADROOM)
    assert (1.0 - (w_btc + w_eth)) - LIM["min_cash"] >= sd.HEADROOM
    assert LIM["max_coin"] - max(w_btc, w_eth) >= sd.HEADROOM


def test_check_box_passes_the_box_with_the_limits_as_read():
    assert sd.check_box(sd.SPECS, LIM) == [(0.2, 0.25), (0.2, 0.75), (0.77, 0.25), (0.77, 0.75)]


def test_the_36_combinations_run_on_a_long_synthetic_panel():
    """A1's record: s in {0.20, 0.50, 0.77}, f in {0.25, 0.50, 0.75}, b in {0.02, 0.50}, every in {1, 90} on the
    2190-row synthetic panel of section 7, with the limits as read and h = 0.02."""
    panel = pf.make_panel(synthetic_market(2190, seed=21, start="2017-01-02"), snapshot_id="synthetic")
    for s in (0.20, 0.50, 0.77):
        for f in (0.25, 0.50, 0.75):
            for b in (0.02, 0.50):
                for every in (1, 90):
                    params = {"coin_share": s, "btc_share": f, "band_rel": b, "every": every}
                    validate_result(sd.steady_backtest(params, panel, limits=LIM, costs=COSTS), panel)


def test_tighter_limits_reach_rebalance_and_make_check_box_refuse_the_box(tmp_path, monkeypatch):
    write_levels(tmp_path, STEADY.replace("min_cash_pct: 20", "min_cash_pct: 30").replace("60", "28"))
    tight = sd.steady_limits(tmp_path)
    assert (tight["min_cash"], tight["max_coin"]) == (0.3, 0.28)
    with pytest.raises(
        ValueError,
        match=r"check_box: the box corner coin_share = 0.77, btc_share = 0.25 breaks the limits as read: rebalance: "
        r"the targets .* break the limits min_cash = 0.3, max_coin = 0.28, headroom = 0.02",
    ):
        sd.check_box(sd.SPECS, tight)
    write_levels(tmp_path, STEADY.replace("60", "50"))  # cash fine, a coin of 0.5775 > 0.48
    with pytest.raises(ValueError, match=r"corner coin_share = 0.77, btc_share = 0.25 breaks"):
        sd.check_box(sd.SPECS, sd.steady_limits(tmp_path))

    seen: list[dict] = []
    real = pf.rebalance

    def spy(params, bars, costs=None):
        seen.append(dict(params))
        return real(params, bars, costs)

    monkeypatch.setattr(sd, "rebalance", spy)
    params = {"coin_share": 0.5, "btc_share": 0.5, "band_rel": 0.5, "every": 30}
    panel = random_panel(150, seed=3)
    loose = sd.steady_backtest(params, panel, limits=LIM, costs=COSTS)
    strict = sd.steady_backtest(params, panel, limits=tight, costs=COSTS)
    assert (seen[0]["min_cash"], seen[0]["max_coin"]) == (0.2, 0.6)
    assert (seen[1]["min_cash"], seen[1]["max_coin"]) == (0.3, 0.28)
    assert {k: v for k, v in seen[0].items() if k not in ("min_cash", "max_coin")} == {
        k: v for k, v in seen[1].items() if k not in ("min_cash", "max_coin")
    }
    assert len(strict.attrs["orders"]) > len(loose.attrs["orders"])  # the 28% cap binds


@pytest.mark.parametrize(
    ("coins", "ok"),
    [
        ("[BTC, USDC]", False),
        ("[BTC, ETH, USDC, SOL]", False),
        ("[BTC, ETH]", False),
        ("[ETH, USDC, BTC]", True),
    ],
)
def test_the_coin_list_must_be_exactly_btc_eth_and_usdc(tmp_path, coins, ok):
    write_levels(tmp_path, STEADY.replace("[BTC, ETH, USDC]", coins))
    if ok:
        assert sd.steady_limits(tmp_path)["coins"] == ("ETH", "USDC", "BTC")
    else:
        with pytest.raises(ValueError, match="coins must be exactly"):
            sd.steady_limits(tmp_path)


def test_a_level_without_both_limits_is_refused(tmp_path):
    write_levels(tmp_path, STEADY.replace("  max_coin_pct: 60\n", ""))
    with pytest.raises(ValueError, match=r"steady: limits must hold min_cash and max_coin"):
        sd.steady_limits(tmp_path)
    panel = random_panel(30, seed=1)
    for limits in (
        {"min_cash": 0.2, "max_coin": None},
        {"min_cash": None, "max_coin": 0.6},
        {},
        None,
        (0.2, 0.6),
    ):
        with pytest.raises(ValueError, match=r"steady: limits must hold min_cash and max_coin"):
            sd.steady_backtest(GOOD, panel, limits=limits, costs=COSTS)
        with pytest.raises(ValueError, match=r"steady: limits must hold min_cash and max_coin"):
            sd.check_box(sd.SPECS, limits)
    with pytest.raises(ValueError, match=r"check_box: specs must include coin_share and btc_share"):
        sd.check_box(sd.SPECS[1:], LIM)


def test_the_mapping_by_hand():
    assert sd.rebalance_params(GOOD, LIM) == {
        "w_btc": 0.125,
        "w_eth": 0.375,
        "band": 0.05,
        "every": 7,
        "min_cash": 0.2,
        "max_coin": 0.6,
        "headroom": 0.02,
    }
    p = {"coin_share": 0.7, "btc_share": 0.3, "band_rel": 0.2, "every": 30.0}
    mapped = sd.rebalance_params(p, LIM)
    assert (mapped["w_btc"], mapped["w_eth"], mapped["band"]) == (0.7 * 0.3, 0.7 * (1.0 - 0.3), 0.2 * 0.7)
    assert mapped["every"] == 30 and isinstance(mapped["every"], int)
    assert sd.targets(p) == (mapped["w_btc"], mapped["w_eth"])
    panel = random_panel(90, seed=4)
    got = sd.steady_backtest(p, panel, limits=LIM, costs=COSTS)
    want = pf.rebalance(mapped, panel, COSTS)
    pd.testing.assert_frame_equal(got, want)
    np.testing.assert_array_equal(got.attrs["trade_returns"], want.attrs["trade_returns"])
    np.testing.assert_array_equal(got.attrs["orders"], want.attrs["orders"])
    pd.testing.assert_frame_equal(got.attrs["fills"], want.attrs["fills"])


@pytest.mark.parametrize(
    ("change", "match"),
    [
        ({"stop": 0.1}, r"steady: unknown params \['stop'\]"),
        ({"coin_share": None}, r"coin_share must be a number"),
        ({"coin_share": 0.0}, r"coin_share must be in \(0.0, 1.0\]"),
        ({"coin_share": 1.5}, r"coin_share must be in \(0.0, 1.0\]"),
        ({"btc_share": -0.1}, r"btc_share must be in \[0.0, 1.0\]"),
        ({"btc_share": 1.1}, r"btc_share must be in \[0.0, 1.0\]"),
        ({"band_rel": -0.01}, r"band_rel must be in \[0.0, inf\)"),
        ({"band_rel": math.nan}, r"band_rel must be in"),
        ({"every": 0}, r"every must be >= 1"),
        ({"every": 2.5}, r"every must be an integer"),
        ({"every": True}, r"every must be an integer"),
    ],
)
def test_bad_steady_params_raise(change, match):
    with pytest.raises(ValueError, match=match):
        sd.rebalance_params({**GOOD, **change}, LIM)


def test_missing_and_non_dict_params_raise():
    for key in sd.PARAM_NAMES:
        with pytest.raises(ValueError, match=f"missing required param '{key}'"):
            sd.targets({k: v for k, v in GOOD.items() if k != key})
    with pytest.raises(ValueError, match="steady: params must be a dict"):
        sd.targets([0.5, 0.5, 0.1, 7])


def test_costs_must_be_built_at_run_start():
    panel = random_panel(30, seed=2)
    with pytest.raises(ValueError, match="steady_backtest: costs must be a Costs instance"):
        sd.steady_backtest(GOOD, panel, limits=LIM, costs=None)
    validate_result(sd.steady_backtest(GOOD, panel, limits=LIM, costs=Costs()), panel)


def test_the_bound_adapter_pickles_and_runs_the_same():
    fn = partial(sd.steady_backtest, limits=LIM, costs=COSTS.stressed())
    back = pickle.loads(pickle.dumps(fn))
    panel = random_panel(60, seed=8)
    pd.testing.assert_frame_equal(fn(GOOD, panel), back(GOOD, panel))


@given(panel=panels(), params=box_params, data=st.data())
def test_no_look_ahead(panel, params, data):
    """Tamper every field of both assets from ``cut`` on, keeping the opens of bar ``cut`` (the fill prices of the
    decision at close cut-1): every output row before ``cut``, the fill on bar ``cut`` (turnover, cost, legs) and the
    orders before ``cut`` are unchanged (TESTING.md section 7)."""
    cut = data.draw(st.integers(1, len(panel) - 1))
    tampered = tamper_from(panel, cut, data.draw(st.integers(0, 2**16)))
    a = sd.steady_backtest(params, panel, limits=LIM, costs=COSTS)
    b = sd.steady_backtest(params, tampered, limits=LIM, costs=COSTS)
    np.testing.assert_array_equal(a[RESULT_COLUMNS].to_numpy()[:cut], b[RESULT_COLUMNS].to_numpy()[:cut])
    assert a["turnover"].iloc[cut] == b["turnover"].iloc[cut] and a["cost"].iloc[cut] == b["cost"].iloc[cut]
    fa, fb = a.attrs["fills"], b.attrs["fills"]
    pd.testing.assert_frame_equal(fa[fa["bar"] <= cut], fb[fb["bar"] <= cut])
    oa, ob = a.attrs["orders"], b.attrs["orders"]
    np.testing.assert_array_equal(oa[oa < cut], ob[ob < cut])


# --------------------------------------------------------------------------------------------- panel hash


def test_panel_hash_byte_layout_by_hand(make_bars):
    btc = make_bars([100.0, 101.5, 99.25])
    eth = make_bars([10.0, 10.5, 9.75], volume=250.0)
    panel = pf.make_panel({"BTC": btc, "ETH": eth}, snapshot_id="hand")
    epoch = pd.Timestamp("1970-01-01", tz="UTC")
    blob = b"".join(struct.pack("<q", (ts - epoch) // pd.Timedelta(microseconds=1)) for ts in btc.index)
    for t in range(len(btc)):
        row = [btc[c].iloc[t] for c in BAR_COLUMNS] + [eth[c].iloc[t] for c in BAR_COLUMNS]
        blob += struct.pack("<10d", *row)
    assert sd.panel_hash(panel) == hashlib.sha256(blob).hexdigest()


def test_panel_hash_reads_index_and_values_only(market):
    panel = pf.make_panel(market, snapshot_id="synthetic-21")
    h = sd.panel_hash(panel)
    other = panel.copy()
    other.attrs = {**panel.attrs, "snapshot_id": "renamed", "alignment": {"rule": "other"}}
    assert sd.panel_hash(other) == h  # attrs are not hashed
    first = pf.make_panel({a: frame.iloc[:400] for a, frame in market.items()}, snapshot_id="x")
    # the first k rows hash as a panel of k rows
    assert sd.panel_hash(panel.iloc[:400]) == sd.panel_hash(first)
    moved = panel.copy()
    moved.iloc[7, 3] = np.nextafter(moved.iloc[7, 3], np.inf)  # BTC close, 1 ulp
    assert sd.panel_hash(moved) != h
    shifted = panel.copy()
    shifted.index = panel.index[:-1].append(
        pd.DatetimeIndex([panel.index[-1] + pd.Timedelta(microseconds=1)])
    )
    shifted.index.name = "ts"
    assert sd.panel_hash(shifted) != h
    with pytest.raises(ValueError, match="panel must be a pandas DataFrame"):
        sd.panel_hash(panel[("BTC", "close")])


# ------------------------------------------------------------------------------------------------ harness


def test_fold_window_by_hand(wf_run):
    index = wf_run["panel"].index
    for fold in wf_run["folds"]:
        w = sd.fold_window(index, fold.test)
        assert w == (
            index[fold.test[0] - 120],
            index[fold.test[0] - 1],
            index[fold.test[0]],
            index[fold.test[-1]],
        )
    assert sd.fold_window(index, range(5, 11)) == (index[0], index[4], index[5], index[10])  # max(0, ...)
    assert sd.fold_window(index, [300, 301], warmup=125).first_h120 == index[175]  # phase sensitivity j = 5
    for bad in ([0, 1, 2], [5], [5, 7], [698, 699, 700], [5.0, 6.0], [[5, 6]]):
        with pytest.raises(ValueError, match="fold_window: test must be >= 2 contiguous rows"):
            sd.fold_window(index, bad)
    for warmup in (0, True, 1.5):
        with pytest.raises(ValueError, match="warmup must be an integer >= 1"):
            sd.fold_window(index, [300, 301], warmup=warmup)


def test_fold_windows_on_the_plan_s_date_grid():
    """The windows of PLAN.md sections 7 and 11 on the daily close grid rebuilt from DATA.md's counts (2017-01-02 ..
    2024-07-01 without 2018-01-13: 2190 train + 547 validate closes). Synthetic prices on that index; no catalog."""
    grid = pd.date_range("2017-01-02", "2024-07-01", freq="D", tz="UTC", name="ts")
    grid = grid[grid != pd.Timestamp("2018-01-13", tz="UTC")]
    assert len(grid) == 2737 and grid[2189] == pd.Timestamp("2023-01-01", tz="UTC")
    day = lambda s: pd.Timestamp(s, tz="UTC")  # noqa: E731
    folds = walk_forward(2190, train_size=730, test_size=365, expanding=True)
    expected = [
        ("2018-09-05", "2019-01-02", "2019-01-03", "2020-01-02"),
        ("2019-09-05", "2020-01-02", "2020-01-03", "2021-01-01"),
        ("2020-09-04", "2021-01-01", "2021-01-02", "2022-01-01"),
        ("2021-09-04", "2022-01-01", "2022-01-02", "2023-01-01"),
    ]
    assert [sd.fold_window(grid[:2190], f.test) for f in folds] == [tuple(map(day, e)) for e in expected]
    look = sd.fold_window(grid, np.arange(2190, 2737))
    assert look == (day("2022-09-04"), day("2023-01-01"), day("2023-01-02"), day("2024-07-01"))
    frames = synthetic_market(len(grid), seed=21)
    for frame in frames.values():
        frame.index = grid
    panel = pf.make_panel(frames, snapshot_id="synthetic")
    params = {"coin_share": 0.5, "btc_share": 0.5, "band_rel": 0.1, "every": 30}
    kept = sd.kept_returns(
        sd.run_h120(partial(sd.steady_backtest, limits=LIM, costs=COSTS), params, panel, look), look.t0
    )
    assert len(kept) == 546 and (kept.index[0], kept.index[-1]) == (day("2023-01-03"), day("2024-07-01"))
    assert len(sd.h1_slice(panel, look)) == 548 and len(sd.h120_slice(panel, look)) == 667


def test_h120_equals_walk_forward_optimize_bit_for_bit(wf_run):
    """H120 by close time, run with each fold's chosen params, reproduces ``walk_forward_optimize``'s stitched
    out-of-sample returns bit for bit, and k_i equals its ``oos_trades``."""
    panel, wf, fn = wf_run["panel"], wf_run["wf"], wf_run["fn"]
    parts = []
    for i, fold in enumerate(wf_run["folds"]):
        w = sd.fold_window(panel.index, fold.test)
        expected_slice = panel.iloc[fold.test[0] - 120 : fold.test[-1] + 1]
        pd.testing.assert_frame_equal(sd.h120_slice(panel, w), expected_slice)
        pd.testing.assert_frame_equal(sd.h1_slice(panel, w), panel.iloc[fold.test[0] - 1 : fold.test[-1] + 1])
        res = sd.run_h120(fn, chosen_params(wf, i), panel, w)
        kept = sd.kept_returns(res, w.t0)
        assert kept.attrs == {} and kept.index[0] == panel.index[fold.test[0] + 1] and len(kept) == 149
        assert sd.kept_fills(res, w.t0) == wf["folds"].iloc[i]["oos_trades"]
        parts.append(kept)
    stitched = pd.concat(parts)
    assert stitched.index.equals(wf["oos_returns"].index)
    np.testing.assert_array_equal(stitched.to_numpy(), wf["oos_returns"].to_numpy())


def binance_like(kraken: pd.DataFrame, offset: int, seed: int = 6) -> pd.DataFrame:
    """Other prices on the Kraken closes from row ``offset`` on (a later start, like Binance from 2017-08-18)."""
    frames = synthetic_market(len(kraken) - offset, seed=seed)
    for frame in frames.values():
        frame.index = kraken.index[offset:]
    return pf.make_panel(frames, snapshot_id="binance-like")


def test_a_binance_style_panel_gives_the_same_kept_index_by_close_time(wf_run):
    panel, fn = wf_run["panel"], wf_run["fn"]
    other = binance_like(panel, offset=37)
    p = chosen_params(wf_run["wf"], 0)
    for fold in wf_run["folds"]:
        w = sd.fold_window(panel.index, fold.test)
        kraken_kept = sd.kept_returns(sd.run_h120(fn, p, panel, w), w.t0)
        res = sd.run_h120(fn, p, other, w, like=panel)
        assert sd.kept_returns(res, w.t0).index.equals(kraken_kept.index)
        assert sd.h1_slice(other, w, like=panel).index.equals(sd.h1_slice(panel, w).index)
        rows = other.iloc[fold.test[0] - 120 : fold.test[-1] + 1].index  # row numbers would pick other dates
        assert not rows.equals(sd.h120_slice(panel, w).index)


def test_a_missing_close_inside_a_slice_stops_the_run(wf_run):
    panel, fn, folds = wf_run["panel"], wf_run["fn"], wf_run["folds"]
    other = binance_like(panel, offset=37)
    w1 = sd.fold_window(panel.index, folds[1].test)
    p = chosen_params(wf_run["wf"], 1)
    holed = other.drop(index=panel.index[folds[1].test[40]])  # a close inside fold 1's slices
    for run in (
        lambda: sd.run_h120(fn, p, holed, w1, like=panel),
        lambda: sd.h1_slice(holed, w1, like=panel),
        lambda: sd.buy_and_hold_b1(holed, w1, COSTS, like=panel),
        lambda: sd.static_b4(holed, w1, p, COSTS, 10_000.0, like=panel),
    ):
        with pytest.raises(sd.SliceMismatchError, match="does not have the Kraken panel's closes"):
            run()
    w0 = sd.fold_window(panel.index, folds[0].test)
    sd.run_h120(fn, p, holed, w0, like=panel)  # fold 0's slices do not contain the missing close
    no_start = panel.drop(index=w1.first_h1)
    with pytest.raises(sd.SliceMismatchError, match="no slice that starts at"):
        sd.h1_slice(no_start, w1)
    with pytest.raises(sd.SliceMismatchError, match="no slice that starts at"):
        sd.harness_slice(panel, w1.last, w1.first_h1)
    assert issubclass(sd.SliceMismatchError, ValueError)


def test_h1_draws_come_only_from_the_kept_decision_closes_and_b3_matches_k(wf_run):
    panel, fn, wf = wf_run["panel"], wf_run["fn"], wf_run["wf"]
    for i, fold in enumerate(wf_run["folds"]):
        w = sd.fold_window(panel.index, fold.test)
        p = chosen_params(wf, i)
        res = sd.run_h120(fn, p, panel, w)
        k = sd.kept_fills(res, w.t0)
        book = sd.book_value(res, w, COSTS)
        b3 = sd.random_b3(panel, w, p, k, COSTS, book, i, n_draws=6)
        assert b3["returns"].shape == (6, 149) and b3["index"].equals(sd.kept_returns(res, w.t0).index)
        np.testing.assert_array_equal(b3["seeds"], 10 * np.arange(6) + i)
        np.testing.assert_array_equal(b3["fills"], np.full(6, k))
        for closes in b3["closes"]:
            assert len(closes) == k and closes.min() >= w.t0 and closes.max() < w.last
        w_btc, w_eth = sd.targets(p)
        by_hand = pf.random_rebalance(
            {"w_btc": w_btc, "w_eth": w_eth, "n_rebalances": k, "seed": 10 * 3 + i},
            panel.loc[w.first_h1 : w.last],
            Costs.from_yaml(capital_usd=book),
        )
        np.testing.assert_array_equal(b3["returns"][3], by_hand["ret"].loc[w.t0 :].iloc[1:].to_numpy())


def test_random_b3_arguments_are_checked(wf_run):
    panel = wf_run["panel"]
    w = sd.fold_window(panel.index, wf_run["folds"][0].test)
    for kwargs, match in (
        ({"k": -1}, "k must be an integer >= 0"),
        ({"fold": 10}, r"fold must be in 0..9"),
        ({"fold": -1}, "fold must be an integer >= 0"),
        ({"n_draws": 0}, "n_draws must be an integer >= 1"),
        ({"k": 200}, "200 rebalances don't fit"),
    ):
        args = {"k": 3, "fold": 0, "n_draws": 2, **kwargs}
        with pytest.raises(ValueError, match=match):
            sd.random_b3(panel, w, GOOD, args["k"], COSTS, 10_000.0, args["fold"], args["n_draws"])


def test_book_value_by_hand(make_bars):
    """Costs off, targets 0.25 / 0.25 bought at the open of bar 1 (no gaps: open = previous close): BTC doubles on
    bar 2 (book 12,500), ETH doubles on bar 3 (15,000); no limit is breached and the band never fires."""
    panel = pf.make_panel(
        {
            "BTC": make_bars([100.0, 100.0, 200.0, 200.0, 200.0]),
            "ETH": make_bars([10.0, 10.0, 10.0, 20.0, 20.0]),
        },
        snapshot_id="hand",
    )
    params = {"coin_share": 0.5, "btc_share": 0.5, "band_rel": 1.0, "every": 90}
    res = sd.steady_backtest(params, panel, limits=LIM, costs=Costs.zero())
    assert list(res.attrs["orders"]) == [0]
    for close, book in ((1, 10_000.0), (2, 12_500.0), (3, 15_000.0)):
        w = sd.Window(panel.index[0], panel.index[close], panel.index[close + 1], panel.index[-1])
        assert sd.book_value(res, w, Costs.zero()) == pytest.approx(book, rel=1e-12)
    w = sd.Window(panel.index[0], panel.index[3], panel.index[4], panel.index[4])
    assert sd.book_value(res, w, replace(Costs.zero(), capital_usd=2.0)) == pytest.approx(3.0, rel=1e-12)
    with pytest.raises(ValueError, match="book_value: close .* is not a row of the result"):
        sd.book_value(res.iloc[:3], w, Costs.zero())


def test_b3_and_b4_start_from_s_s_book_and_b4_at_2x_equals_b4_at_1x(wf_run):
    panel, wf = wf_run["panel"], wf_run["wf"]
    fn2 = partial(sd.steady_backtest, limits=LIM, costs=COSTS.stressed())
    for i, fold in enumerate(wf_run["folds"]):
        w = sd.fold_window(panel.index, fold.test)
        p = chosen_params(wf, i)
        res = sd.run_h120(wf_run["fn"], p, panel, w)
        res2 = sd.run_h120(fn2, p, panel, w)
        book, book2 = sd.book_value(res, w, COSTS), sd.book_value(res2, w, COSTS.stressed())
        value = COSTS.capital_usd
        for r in res["ret"].loc[: w.first_h1]:
            value *= 1.0 + r
        assert book == value and book != book2
        assert sd.book_costs(COSTS, book) == Costs.from_yaml(capital_usd=book)
        assert sd.book_costs(COSTS.stressed(), book2) == Costs.from_yaml(capital_usd=book2).stressed()
        b4 = sd.static_b4(panel, w, p, COSTS, book)
        b4x = sd.static_b4(panel, w, p, COSTS.stressed(), book2)
        legs = b4.attrs["fills"]
        w_btc, w_eth = sd.targets(p)
        assert list(legs["bar"]) == [1, 1] and list(legs["ts"]) == [w.t0, w.t0]  # bought at the open of t0
        assert list(legs["usd"]) == [w_btc * book, w_eth * book]  # from S's book
        assert b4.attrs["n_trades"] == 1 and b4["cost"].iloc[1] > 0
        kept, kept2 = sd.kept_returns(b4, w.t0), sd.kept_returns(b4x, w.t0)
        np.testing.assert_array_equal(kept.to_numpy(), kept2.to_numpy())  # B4 at 2x == B4 at 1x, bit for bit
        assert (b4["cost"].loc[w.t0 :].iloc[1:] == 0.0).all() and sd.kept_fills(b4, w.t0) == 0


def test_b1_and_b2_are_the_reference_benchmarks_on_the_h120_slice(wf_run):
    panel, fold = wf_run["panel"], wf_run["folds"][1]
    w = sd.fold_window(panel.index, fold.test)
    btc = pf.asset_bars(panel.iloc[fold.test[0] - 120 : fold.test[-1] + 1], "BTC")
    b1 = sd.buy_and_hold_b1(panel, w, COSTS)
    b2 = sd.fifty_fifty_b2(panel, w, COSTS)
    pd.testing.assert_frame_equal(b1, reference.buy_and_hold({"weight": 1.0}, btc, COSTS))
    pd.testing.assert_frame_equal(b2, reference.constant_mix({"weight": 0.5, "every": 30}, btc, COSTS))
    assert b2.attrs["n_trades"] > 3  # it rebalances


def test_b5_rebalances_only_at_close_0_and_on_limit_breaches(wf_run):
    panel = wf_run["panel"]
    params = {"coin_share": 0.77, "btc_share": 0.75, "band_rel": 0.02, "every": 1}
    breaches = 0
    for fold in wf_run["folds"]:
        w = sd.fold_window(panel.index, fold.test)
        res = sd.limit_only_b5(panel, w, params, LIM, COSTS)
        validate_result(res, sd.h120_slice(panel, w))
        wb, we = res["w_BTC"].to_numpy(), res["w_ETH"].to_numpy()
        expected = [0] + [t for t in range(1, len(res) - 1) if breached(wb[t], we[t])]
        assert list(res.attrs["orders"]) == expected
        breaches += len(expected) - 1
    assert breaches > 0
    with pytest.raises(ValueError, match="steady: limits must hold"):
        sd.limit_only_b5(panel, w, params, {"min_cash": 0.2}, COSTS)


def test_b4_span_holds_fold_0_targets_to_the_last_fold_on_s_s_rows(wf_run):
    panel, wf, folds = wf_run["panel"], wf_run["wf"], wf_run["folds"]
    first, last = sd.fold_window(panel.index, folds[0].test), sd.fold_window(panel.index, folds[-1].test)
    keep = wf["oos_returns"].index
    p = chosen_params(wf, 0)
    book = 12_345.0
    span = sd.static_span_b4(panel, first, last, p, COSTS, book, keep)
    w_btc, w_eth = sd.targets(p)
    by_hand = pf.random_rebalance(
        {"w_btc": w_btc, "w_eth": w_eth, "n_rebalances": 0, "seed": 0},
        panel.loc[first.first_h1 : last.last],
        Costs.from_yaml(capital_usd=book),
    )
    assert span.index.equals(keep) and span.attrs == {} and len(span) == 3 * 149
    np.testing.assert_array_equal(span.to_numpy(), by_hand["ret"].loc[keep].to_numpy())
    assert list(by_hand.attrs["fills"]["ts"].unique()) == [first.t0]  # one buy at fold 0's t0, then held
    other = binance_like(panel, offset=37)
    sd.static_span_b4(other, first, last, p, COSTS, book, keep, like=panel)
    with pytest.raises(
        ValueError, match="static_span_b4: every kept close must be a slice close after first.t0"
    ):
        sd.static_span_b4(panel, first, last, p, COSTS, book, keep.insert(0, first.t0))


# ------------------------------------------------------------------------------------------------ G5 steps


@pytest.mark.parametrize(
    ("every", "down", "down_mark", "up"),
    [(1, 1, "at the limit", 2), (2, 1, "free", 3), (7, 6, "free", 8), (90, 72, "free", 108)],
)
def test_every_steps_by_hand(every, down, down_mark, up):
    params = {**GOOD, "every": every}
    lowered, mark = sd.plateau_step(params, "every", 0.8, LIM)
    assert (lowered, mark) == ({**params, "every": down}, down_mark) and isinstance(lowered["every"], int)
    assert sd.plateau_step(params, "every", 1.2, LIM) == ({**params, "every": up}, "free")


def test_every_rounds_half_up():
    """0.8 * e and 1.2 * e never end in exactly .5, so the half-up rule is pinned with other factors: 0.5 * 5 = 2.5
    rounds to 3 and 1.5 * 5 = 7.5 to 8 (half-down or banker's rounding would give 2 and 8, or 2)."""
    params = {**GOOD, "every": 5}
    assert sd.plateau_step(params, "every", 0.5, LIM) == ({**params, "every": 3}, "free")
    assert sd.plateau_step(params, "every", 1.5, LIM) == ({**params, "every": 8}, "free")
    # 0.5 * 3 = 1.5 rounds to 2
    assert sd.plateau_step({**GOOD, "every": 3}, "every", 0.5, LIM) == ({**GOOD, "every": 2}, "free")


def test_coin_share_on_its_feasible_edge_cannot_go_up():
    on_cash_edge = {"coin_share": 0.78, "btc_share": 0.5, "band_rel": 0.1, "every": 5}  # 1 - 0.2 - 0.02
    assert sd.plateau_step(on_cash_edge, "coin_share", 1.2, LIM) == (on_cash_edge, "at the limit")
    assert sd.plateau_step(on_cash_edge, "coin_share", 0.8, LIM) == (
        {**on_cash_edge, "coin_share": 0.78 * 0.8},
        "free",
    )
    on_coin_edge = {**on_cash_edge, "coin_share": 0.58 / 0.75, "btc_share": 0.75}  # s * f = 0.6 - 0.02
    assert sd.plateau_step(on_coin_edge, "coin_share", 1.2, LIM) == (on_coin_edge, "at the limit")
    corner = {"coin_share": 0.77, "btc_share": 0.75, "band_rel": 0.1, "every": 5}
    assert sd.plateau_step(corner, "coin_share", 1.2, LIM) == (
        {**corner, "coin_share": 0.58 / 0.75},
        "clipped",
    )
    low = {**corner, "coin_share": 0.2}
    assert sd.plateau_step(low, "coin_share", 1.2, LIM) == ({**low, "coin_share": 0.2 * 1.2}, "free")


def test_btc_share_at_the_box_edges_with_coin_share_0_77():
    up_edge = {"coin_share": 0.77, "btc_share": 0.75, "band_rel": 0.1, "every": 5}
    assert sd.plateau_step(up_edge, "btc_share", 1.2, LIM) == (
        {**up_edge, "btc_share": 0.58 / 0.77},
        "clipped",
    )
    assert sd.plateau_step(up_edge, "btc_share", 0.8, LIM) == ({**up_edge, "btc_share": 0.75 * 0.8}, "free")
    down_edge = {**up_edge, "btc_share": 0.25}
    lowered, mark = sd.plateau_step(down_edge, "btc_share", 0.8, LIM)
    assert (lowered, mark) == ({**down_edge, "btc_share": 1.0 - 0.58 / 0.77}, "clipped")
    assert sd.plateau_step(down_edge, "btc_share", 1.2, LIM) == (
        {**down_edge, "btc_share": 0.25 * 1.2},
        "free",
    )
    on_eth_edge = {**up_edge, "btc_share": 1.0 - 0.58 / 0.77}  # w_eth = 0.58 exactly as the clip computes it
    assert sd.plateau_step(on_eth_edge, "btc_share", 0.8, LIM) == (on_eth_edge, "at the limit")
    roomy = {**up_edge, "coin_share": 0.4, "btc_share": 0.75}  # 0.58 / 0.4 > 1: f is capped at 1, not reached
    assert sd.plateau_step(roomy, "btc_share", 1.2, LIM) == ({**roomy, "btc_share": 0.75 * 1.2}, "free")


def test_band_steps_are_never_clipped():
    params = {"coin_share": 0.77, "btc_share": 0.75, "band_rel": 0.5, "every": 5}
    assert sd.plateau_step(params, "band_rel", 0.8, LIM) == ({**params, "band_rel": 0.5 * 0.8}, "free")
    assert sd.plateau_step(params, "band_rel", 1.2, LIM) == ({**params, "band_rel": 0.5 * 1.2}, "free")


@given(params=box_params)
@example(params={"coin_share": 0.77, "btc_share": 0.75, "band_rel": 0.5, "every": 90})
@example(params={"coin_share": 0.77, "btc_share": 0.25, "band_rel": 0.02, "every": 1})
@example(params={"coin_share": 0.2, "btc_share": 0.25, "band_rel": 0.02, "every": 2})
def test_every_step_from_the_box_is_feasible_and_moves_the_right_way(params):
    for step in sd.plateau_steps([params], LIM):
        name, factor = step["param"], step["factor"]
        (moved,), (mark,) = step["params"], step["fold_marks"]
        assert step["mark"] == mark and mark in sd.MARKS
        assert {k: v for k, v in moved.items() if k != name} == {k: v for k, v in params.items() if k != name}
        w_btc, w_eth = sd.targets(moved)
        pf.check_targets(
            w_btc, w_eth, min_cash=LIM["min_cash"], max_coin=LIM["max_coin"], headroom=sd.HEADROOM
        )
        v, new = params[name], moved[name]
        if mark == "at the limit":
            assert new == v
        elif factor > 1:
            assert new > v
        else:
            assert new < v
        if name != "every":
            raw = v * factor
            assert (new == raw) == (mark == "free")
            assert min(v, raw) <= new <= max(v, raw)


def test_plateau_steps_apply_each_step_to_every_fold():
    folds = [
        {"coin_share": 0.5, "btc_share": 0.5, "band_rel": 0.1, "every": 1},
        {"coin_share": 0.77, "btc_share": 0.75, "band_rel": 0.2, "every": 7},
    ]
    steps = sd.plateau_steps(folds, LIM)
    assert [(s["param"], s["factor"]) for s in steps] == [
        (name, k) for name in sd.PARAM_NAMES for k in (0.8, 1.2)
    ]
    by = {(s["param"], s["factor"]): s for s in steps}
    assert by[("every", 0.8)]["fold_marks"] == ["at the limit", "free"]
    assert by[("every", 0.8)]["mark"] == "at the limit"
    assert [p["every"] for p in by[("every", 0.8)]["params"]] == [1, 6]
    assert by[("coin_share", 1.2)]["fold_marks"] == ["free", "clipped"]
    assert by[("coin_share", 1.2)]["mark"] == "clipped"
    assert by[("band_rel", 1.2)]["mark"] == "free"
    assert [p["band_rel"] for p in by[("band_rel", 1.2)]["params"]] == [0.1 * 1.2, 0.2 * 1.2]
    edge = {"coin_share": 0.78, "btc_share": 0.5, "band_rel": 0.1, "every": 1}
    assert sd.plateau_steps([edge, edge], LIM)[1]["fold_marks"] == ["at the limit", "at the limit"]


def test_plateau_step_arguments_are_checked():
    with pytest.raises(ValueError, match="plateau_step: name must be one of"):
        sd.plateau_step(GOOD, "band", 0.8, LIM)
    with pytest.raises(ValueError, match="plateau_step: factor must not be 1"):
        sd.plateau_step(GOOD, "every", 1.0, LIM)
    for factor in (0.0, -0.8, math.nan, math.inf, "0.8"):
        with pytest.raises(ValueError, match="factor must"):
            sd.plateau_step(GOOD, "every", factor, LIM)
    with pytest.raises(ValueError, match="steady: limits must hold"):
        sd.plateau_step(GOOD, "every", 0.8, {"min_cash": None, "max_coin": 0.6})
    with pytest.raises(ValueError, match="plateau_steps: chosen must hold every fold's chosen params"):
        sd.plateau_steps([], LIM)
    outside = {"coin_share": 0.9, "btc_share": 0.5, "band_rel": 0.1, "every": 5}  # not a feasible S
    with pytest.raises(ValueError, match="break the limits"):
        sd.plateau_step(outside, "every", 0.8, LIM)


def test_plateau_verdict():
    free, clipped, limit = "free", "clipped", "at the limit"
    marks = [free] * 8
    assert sd.plateau_verdict(1.0, [0.7] * 8, marks) == "PASS"  # exactly 70% passes
    assert sd.plateau_verdict(1.0, [0.7] * 7 + [0.69], marks) == "FAIL"
    assert sd.plateau_verdict(1.0, [1.0] * 8, [clipped, limit] + [free] * 6) == "PASS"
    assert sd.plateau_verdict(1.0, [1.0] * 8, [clipped, limit, clipped] + [free] * 5) == "PASS (weak)"
    assert sd.plateau_verdict(1.0, [0.5] * 8, [limit] * 8) == "FAIL"
    assert sd.plateau_verdict(0.0, [1.0] * 8, marks) == "FAIL"  # Sharpe(S) must be > 0
    assert sd.plateau_verdict(-1.0, [1.0] * 8, marks) == "FAIL"
    assert sd.plateau_verdict(math.nan, [1.0] * 8, marks) == "FAIL"
    assert sd.plateau_verdict(1.0, [1.0] * 7 + [math.nan], marks) == "FAIL"
    for sharpes, bad_marks in (([1.0] * 7, marks), ([1.0] * 8, marks[:7]), ([1.0] * 8, ["weak"] + marks[1:])):
        with pytest.raises(ValueError, match="plateau_verdict: needs 8 step Sharpes and 8 marks"):
            sd.plateau_verdict(1.0, sharpes, bad_marks)


# -------------------------------------------------------------------------------------------------- G8


def regime_panel(make_bars) -> pd.DataFrame:
    """Daily closes 2020-01-01 .. 2020-04-01 with BTC jumps on chosen closes, flat otherwise.

    January's bar days (closes 2020-01-02 .. 2020-02-01): +4.9% at the closes of Jan 15 and Feb 1, compounded
    10.04% (bull; summed it would be 9.8%). February (closes 2020-02-02 .. 2020-03-01, bar days to Feb 29): -20% on
    Feb 10, -1% on Mar 1: -20.8% (bear). March (closes 2020-03-02 .. 2020-04-01): +9% on Mar 10, -2% on Apr 1:
    +6.82% (sideways)."""
    index = pd.date_range("2020-01-01", "2020-04-01", freq="D", tz="UTC")
    jumps = {
        "2020-01-15": 1.049,
        "2020-02-01": 1.049,
        "2020-02-10": 0.8,
        "2020-03-01": 0.99,
        "2020-03-10": 1.09,
    }
    jumps["2020-04-01"] = 0.98
    step = np.array([jumps.get(str(ts.date()), 1.0) for ts in index])
    btc = 100.0 * np.cumprod(step)
    return pf.make_panel(
        {"BTC": make_bars(btc), "ETH": make_bars(np.full(len(index), 10.0))}, snapshot_id="hand"
    )


def test_regime_labels_by_hand_on_a_built_path(make_bars):
    panel = regime_panel(make_bars)
    kept = panel.index[1:]
    table = sd.regime_table(panel[("BTC", "close")], kept)
    assert list(table.columns) == ["month", "btc_ret", "month_ret", "regime"] and table.index.equals(kept)
    month_of = dict(zip(table.index, table["month"], strict=True))
    assert month_of[pd.Timestamp("2020-02-01", tz="UTC")] == "2020-01"  # bar day Jan 31
    assert month_of[pd.Timestamp("2020-03-01", tz="UTC")] == "2020-02"  # bar day Feb 29
    assert month_of[pd.Timestamp("2020-04-01", tz="UTC")] == "2020-03"
    by_month = table.groupby("month").agg(month_ret=("month_ret", "first"), regime=("regime", "first"))
    assert list(by_month.index) == ["2020-01", "2020-02", "2020-03"]
    np.testing.assert_allclose(
        by_month["month_ret"], [1.049**2 - 1, 0.8 * 0.99 - 1, 1.09 * 0.98 - 1], rtol=1e-12
    )
    assert list(by_month["regime"]) == ["bull", "bear", "sideways"]
    assert table.groupby("month")["regime"].nunique().eq(1).all()  # one label per month
    assert table.loc[pd.Timestamp("2020-01-15", tz="UTC"), "btc_ret"] == pytest.approx(0.049, rel=1e-12)
    # Over that month's KEPT rows only: without the Feb 1 close, January is +4.9% (sideways).
    fewer = kept.drop(pd.Timestamp("2020-02-01", tz="UTC"))
    assert set(sd.regime_table(panel[("BTC", "close")], fewer).query("month == '2020-01'")["regime"]) == {
        "sideways"
    }
    # The threshold is a parameter: at 5%, March (+6.82%) is bull.
    assert set(
        sd.regime_table(panel[("BTC", "close")], kept, 0.05).query("month == '2020-03'")["regime"]
    ) == {"bull"}


def test_a_month_exactly_on_the_threshold_is_bull_or_bear(make_bars):
    """The bounds are inclusive (>= +threshold bull, <= -threshold bear). 125 / 100 - 1 = 0.25 and 75 / 100 - 1 =
    -0.25 exactly in floating point, so at threshold 0.25 they sit on the bounds (0.10 has no such exact path)."""
    # close Jan 6: +25% (January); close Feb 6: -25% (February)
    btc = [100.0] * 5 + [125.0] * 31 + [93.75] * 29
    panel = pf.make_panel({"BTC": make_bars(btc), "ETH": make_bars([10.0] * len(btc))}, snapshot_id="hand")
    table = sd.regime_table(panel[("BTC", "close")], panel.index[1:], 0.25)
    by_month = table.groupby("month").agg(month_ret=("month_ret", "first"), regime=("regime", "first"))
    assert list(by_month.index) == ["2020-01", "2020-02", "2020-03"]  # closes run to Mar 6, flat in March
    assert list(by_month["month_ret"]) == [0.25, -0.25, 0.0]
    assert list(by_month["regime"]) == ["bull", "bear", "sideways"]


def test_regime_table_inputs_are_checked(make_bars):
    close = regime_panel(make_bars)[("BTC", "close")]
    for kept in (
        close.index,  # includes the first close
        close.index[[1, 3, 2]],  # not increasing
        close.index[[1, 1, 2]],  # duplicate
        close.index[1:].insert(0, close.index[0] - pd.Timedelta(days=5)),  # not a panel close
    ):
        with pytest.raises(ValueError, match="regime_table: kept must be strictly increasing panel closes"):
            sd.regime_table(close, kept)
    with pytest.raises(ValueError, match="threshold must be in"):
        sd.regime_table(close, close.index[1:], 0.0)


def test_regime_split_by_hand():
    index = pd.date_range("2021-01-02", periods=6, freq="D", tz="UTC")
    table = pd.DataFrame(
        {
            "month": ["2021-01", "2021-01", "2021-02", "2021-02", "2021-03", "2021-03"],
            "regime": ["bull", "bull", "bear", "bear", "sideways", "sideways"],
        },
        index=index,
    )
    logs = np.array([0.15, 0.10, 0.10, 0.05, 0.12, 0.08])  # bull 0.25, bear 0.15, sideways 0.20, total 0.60
    out = sd.regime_split(pd.Series(np.expm1(logs), index=index), table)
    assert out["profit"] == pytest.approx({"bull": 0.25, "bear": 0.15, "sideways": 0.20}, rel=1e-12)
    assert out["total"] == pytest.approx(0.60, rel=1e-12)
    assert out["share"] == pytest.approx(
        {"bull": 0.25 / 0.6, "bear": 0.15 / 0.6, "sideways": 0.2 / 0.6}, rel=1e-12
    )
    assert out["rows"] == {"bull": 2, "bear": 2, "sideways": 2} and out["months"] == {
        g: 1 for g in sd.REGIMES
    }
    assert out["pass"] is True and "excess" not in out

    one_sided = np.array([0.40, 0.10, -0.05, -0.05, 0.05, 0.05])  # bull 0.5 of a total 0.5
    assert sd.regime_split(pd.Series(np.expm1(one_sided), index=index), table)["pass"] is False
    losing = np.array([0.05, 0.05, -0.20, -0.10, 0.05, 0.05])  # total -0.1
    assert sd.regime_split(pd.Series(np.expm1(losing), index=index), table)["pass"] is False
    # Exactly half passes ("more than half" fails): bull and bear hold the same returns, sideways none.
    r = np.array([0.013, 0.021, 0.013, 0.021, 0.0, 0.0])
    half = sd.regime_split(pd.Series(r, index=index), table)
    assert half["profit"]["bull"] == half["profit"]["bear"] == half["total"] / 2 and half["pass"] is True
    flat = sd.regime_split(pd.Series(np.zeros(6), index=index), table)
    assert (
        flat["total"] == 0.0 and flat["pass"] is False and all(math.isnan(v) for v in flat["share"].values())
    )

    b4 = pd.Series(np.expm1(logs - 0.01), index=index)
    excess = sd.regime_split(pd.Series(np.expm1(logs), index=index), table, benchmark=b4)
    assert excess["excess"] == pytest.approx({g: 0.02 for g in sd.REGIMES}, rel=1e-9)
    assert excess["excess_total"] == pytest.approx(0.06, rel=1e-9)


def test_regime_split_inputs_are_checked():
    index = pd.date_range("2021-01-02", periods=3, freq="D", tz="UTC")
    table = pd.DataFrame({"month": ["2021-01"] * 3, "regime": ["bull", "bear", "sideways"]}, index=index)
    good = pd.Series([0.01, 0.0, -0.01], index=index)
    for returns in (
        good.to_numpy(),
        good.iloc[:2],
        pd.Series([0.01, 0.0, -0.01], index=index + pd.Timedelta(days=1)),
    ):
        with pytest.raises(
            ValueError, match="regime_split: returns must be a Series on the regime table's index"
        ):
            sd.regime_split(returns, table)
    for bad in ([0.01, -1.0, 0.0], [0.01, math.nan, 0.0], [math.inf, 0.0, 0.0]):
        with pytest.raises(ValueError, match="regime_split: returns must be finite and > -1"):
            sd.regime_split(pd.Series(bad, index=index), table)
    with pytest.raises(ValueError, match="regime_split: benchmark must be a Series"):
        sd.regime_split(good, table, benchmark=good.iloc[1:])
    with pytest.raises(ValueError, match="regime_split: regimes must be in"):
        sd.regime_split(good, table.assign(regime=["bull", "crash", "bear"]))


# ---------------------------------------------------------------------------------------------- E1, E2


def test_e1_rank_by_hand():
    rng = np.random.default_rng(3)
    base = rng.normal(0.0, 0.02, 200)
    s = pd.Series(base + 0.002)
    draws = np.vstack([base + shift for shift in (-0.002, 0.0, 0.001, 0.003)])  # Sharpe rises with the shift
    out = sd.e1_rank(s, draws)
    sharpes = [stats.annualized_sharpe(row) for row in draws]
    assert out["sharpe"] == stats.annualized_sharpe(s) and list(out["draw_sharpes"]) == sharpes
    assert sharpes == sorted(sharpes) and sharpes[2] < out["sharpe"] < sharpes[3]
    assert out["p95"] == np.percentile(sharpes, 95) and out["p5"] == np.percentile(sharpes, 5)
    assert out["p50"] == np.percentile(sharpes, 50)
    assert out["rank_p"] == (1 + 1) / 5 and out["holds"] is False  # one draw beats S; p95 is above S
    top = sd.e1_rank(pd.Series(base + 0.01), draws)
    assert top["rank_p"] == 1 / 5 and top["holds"] is True
    tied = sd.e1_rank(pd.Series(draws[3]), draws)  # a draw equal to S counts against S (>=)
    assert tied["rank_p"] == (1 + 1) / 5
    assert tied["holds"] is True  # S equals the top draw, above the interpolated 95th percentile
    for bad in (draws[:, :-1], draws[0], np.empty((0, 200))):
        with pytest.raises(ValueError, match="e1_rank: b3_returns must have one row per draw"):
            sd.e1_rank(s, bad)


def hand_indices(rng: np.random.Generator, n: int, mean_block: float) -> list[int]:
    """The stationary bootstrap written out: restart at t with probability 1/mean_block (always at t = 0) at a
    uniform start, else the next position (wrapping), drawing the restarts' uniforms first, then their starts."""
    u = rng.random(n)
    restart = [True] + [bool(x < 1.0 / mean_block) for x in u[1:]]
    starts = rng.integers(0, n, size=sum(restart))
    idx, block, cur = [], -1, 0
    for t in range(n):
        if restart[t]:
            block += 1
            cur = int(starts[block])
        else:
            cur = (cur + 1) % n
        idx.append(cur)
    return idx


def hand_sharpe(x: np.ndarray) -> float:
    return float(np.mean(x) / np.std(x, ddof=1) * math.sqrt(365))


def test_paired_bootstrap_equals_a_hand_resampler():
    rng = np.random.default_rng(11)
    index = pd.date_range("2019-01-04", periods=90, freq="D", tz="UTC")
    s = pd.Series(rng.normal(0.001, 0.02, 90), index=index)
    b = pd.Series(rng.normal(0.0, 0.025, 90), index=index)
    out = sd.paired_bootstrap(s, b, n_resamples=300, mean_block=20, seed=0)
    hand_rng = np.random.default_rng(0)
    d_star = []
    for _ in range(300):
        idx = hand_indices(hand_rng, 90, 20)
        d_star.append(hand_sharpe(s.to_numpy()[idx]) - hand_sharpe(b.to_numpy()[idx]))
    np.testing.assert_allclose(out["d_star"], d_star, rtol=1e-10, atol=1e-12)
    assert np.min(np.abs(d_star)) > 1e-6  # no resample is near the p boundary
    assert out["d"] == pytest.approx(hand_sharpe(s.to_numpy()) - hand_sharpe(b.to_numpy()), rel=1e-12)
    assert out["p"] == (1 + sum(x <= 0 for x in d_star)) / 301
    assert out["holds"] == (out["d"] > 0 and out["p"] < 0.05)
    assert (out["n_resamples"], out["mean_block"], out["seed"]) == (300, 20, 0)


def test_the_bootstrap_is_paired_and_its_defaults_are_the_plan_s():
    """With S equal to B4 every resample's D* is exactly 0 (the same rows for both): p = 1. Defaults: 10,000
    resamples, mean block 20, seed 0."""
    rng = np.random.default_rng(5)
    s = pd.Series(
        rng.normal(0.0, 0.01, 40), index=pd.date_range("2019-01-04", periods=40, freq="D", tz="UTC")
    )
    out = sd.paired_bootstrap(s, s.copy())
    assert (out["n_resamples"], out["mean_block"], out["seed"]) == (10_000, 20, 0)
    assert len(out["d_star"]) == 10_000 and (out["d_star"] == 0.0).all() and out["p"] == 1.0
    assert out["d"] == 0.0 and out["holds"] is False
    better = sd.paired_bootstrap(s + 0.01, s, n_resamples=200)
    assert better["d"] > 0 and better["p"] == 1 / 201 and better["holds"] is True


def test_e2_holds_only_below_5_percent():
    """E2's threshold is p < 0.05, strict (#45). S + 0.01 against S: the same spread and a higher mean, so every
    resample's D* > 0 and p = 1 / (n_resamples + 1) exactly: 1/20 = 0.05 fails, 1/15 fails, 1/21 holds."""
    rng = np.random.default_rng(5)
    s = pd.Series(
        rng.normal(0.0, 0.01, 40), index=pd.date_range("2019-01-04", periods=40, freq="D", tz="UTC")
    )
    at = sd.paired_bootstrap(s + 0.01, s, n_resamples=19)
    assert (at["d_star"] > 0).all() and at["d"] > 0
    assert at["p"] == 0.05 and at["holds"] is False  # exactly 5% fails
    between = sd.paired_bootstrap(s + 0.01, s, n_resamples=14)
    assert between["p"] == 1 / 15 and between["holds"] is False  # 6.7% fails
    below = sd.paired_bootstrap(s + 0.01, s, n_resamples=20)
    assert below["p"] == 1 / 21 and below["holds"] is True


def test_e1_needs_s_strictly_above_the_95th_percentile():
    """E1 holds only when Sharpe(S) > p95 (#45): with 21 draws whose Sharpes rise with i, p95 is exactly the 20th
    draw's Sharpe, and S equal to that draw does not hold."""
    rng = np.random.default_rng(3)
    base = rng.normal(0.0, 0.02, 200)
    draws = np.vstack([base + 0.0005 * i for i in range(21)])
    out = sd.e1_rank(pd.Series(draws[19]), draws)
    assert list(out["draw_sharpes"]) == sorted(out["draw_sharpes"])
    assert out["p95"] == out["draw_sharpes"][19] == out["sharpe"]
    assert out["holds"] is False and out["rank_p"] == 3 / 22  # draws 19 and 20 count against S
    above = sd.e1_rank(pd.Series(draws[19] + 1e-6), draws)
    assert above["sharpe"] > above["p95"] and above["holds"] is True


def test_paired_bootstrap_inputs_are_checked():
    index = pd.date_range("2019-01-04", periods=30, freq="D", tz="UTC")
    s = pd.Series(np.linspace(-0.01, 0.01, 30), index=index)
    for a, b in (
        (s.to_numpy(), s),
        (s, s.iloc[1:]),
        (s, pd.Series(s.to_numpy(), index=index + pd.Timedelta(days=1))),
    ):
        with pytest.raises(ValueError, match="paired_bootstrap: s and b must be Series on the same index"):
            sd.paired_bootstrap(a, b)
    with pytest.raises(ValueError, match="n_resamples must be an integer >= 1"):
        sd.paired_bootstrap(s, s, n_resamples=0)
    with pytest.raises(ValueError, match="seed must be an integer >= 0"):
        sd.paired_bootstrap(s, s, seed=-1)
    with pytest.raises(ValueError, match="mean_block must be >= 1"):
        sd.paired_bootstrap(s, s, n_resamples=2, mean_block=0.5)


# -------------------------------------------------------------------- numbers the report does not return


def test_report_trial_sharpes_and_study_pbo_are_the_report_s(wf_run):
    """The strict DSR's trial Sharpes and the per-study PBO are exactly what ``overfitting_report`` computes: its
    raw-count and effective-count DSR and its mean PBO come out bit for bit from them."""
    out, wf = wf_run["out"], wf_run["wf"]
    studies = [*wf["studies"], "rs-s0_final", "rs-one"]
    n_raw = sum(len(load_trials(s, out)) for s in studies)
    combined = {
        "oos_returns": wf["oos_returns"],
        "wf_efficiency": wf["wf_efficiency"],
        "studies": studies,
        "total_trials": n_raw,
    }
    rep = overfitting_report(combined, out)
    sharpes = sd.report_trial_sharpes(studies, out)
    assert len(sharpes) == 4 * 12 and n_raw == 4 * 12 + 1  # the 1-trial study is skipped, as the report does
    oos = wf["oos_returns"].to_numpy(float)
    assert stats.deflated_sharpe_ratio(oos, sharpes, n_trials=n_raw)["dsr"] == rep["dsr_raw_count"]
    assert (
        stats.deflated_sharpe_ratio(oos, sharpes, n_trials=rep["trials_effective"])["dsr"]
        == rep["dsr_effective_count"]
    )
    strict = stats.deflated_sharpe_ratio(oos, sharpes, n_trials=n_raw + 21)
    assert strict["n_trials"] == n_raw + 21 and strict["dsr"] <= rep["dsr_raw_count"]
    pbos = [sd.study_pbo(s, out) for s in studies]
    assert pbos[-1] is None and all(p is not None for p in pbos[:-1])
    assert float(np.mean([p["pbo"] for p in pbos[:-1]])) == rep["pbo_mean"]
    for p in pbos[:-1]:
        assert p["n_combinations"] == math.comb(10, 5) == len(p["logits"]) and p["n_trials"] == 12
        assert p["pbo"] == float(np.mean(p["logits"] <= 0))


def test_stable_neighbours_are_the_ones_stable_region_chose(wf_run):
    out, wf = wf_run["out"], wf_run["wf"]
    for i, study in enumerate([*wf["studies"], "rs-s0_final"]):
        trials = load_trials(study, out)
        hood = sd.stable_neighbours(trials, sd.SPECS)
        chosen = stable_region(trials, list(sd.SPECS))
        assert hood["trial_number"] == chosen["trial_number"]
        assert hood["neighbourhood_score"] == chosen["neighbourhood_score"]
        table = hood["neighbours"]
        assert len(table) == 10 and list(table.columns[:3]) == ["number", "value", "distance"]
        assert float(np.sort(table["value"].to_numpy()).mean()) == chosen["neighbourhood_score"]
        assert hood["trial_number"] in set(table["number"]) and table["distance"].is_monotonic_increasing
        me = table.loc[table["number"] == hood["trial_number"]].iloc[0]
        assert me["distance"] == 0.0
        assert {p.name: me[f"params_{p.name}"] for p in sd.SPECS} == chosen["params"]
        if i < len(wf["studies"]):
            assert chosen["params"] == chosen_params(wf, i)  # the params walk_forward_optimize traded
    small = sd.stable_neighbours(load_trials("rs-one", out), sd.SPECS)
    assert len(small["neighbours"]) == 1  # k = min(10, completed trials)
    with pytest.raises(ValueError, match="no completed trials"):
        sd.stable_neighbours(load_trials("rs-one", out).assign(state="FAIL"), sd.SPECS)
