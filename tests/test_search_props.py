"""Search layer: scoring, logging every trial, choosing stable parameters, and making
sure walk-forward decisions never see their own test block.

Starter tests run on osprey's reference runner: parameter names are osprey's (drop/hold/stop as fractions) and
the tampered bars in the walk-forward look-ahead test keep high >= close >= low."""

import json

import numpy as np
import pandas as pd
import pytest
from hypothesis import given
from hypothesis import strategies as st

from lab.runner.reference import dip_buy
from lab.search.objective import evaluate_params
from lab.search.report import gates, overfitting_report
from lab.search.space import Param, from_dict
from lab.search.stability import stable_region
from lab.search.study import SearchConfig, load_trial_returns, load_trials, run_study
from lab.search.walkforward import walk_forward_optimize
from lab.validation.splits import walk_forward
from lab.validation.stats import annualized_sharpe

SPECS = [  # osprey dip_buy names; drop and stop are fractions (the starter used percent)
    Param("drop", "float", 0.03, 0.25),
    Param("lookback", "int", 2, 20),
    Param("hold", "int", 3, 40),
    Param("stop", "float", 0.03, 0.25),
]
ONE = SearchConfig(n_trials=8, n_workers=1, seed=7)


# Module-level backtests so Optuna can call them.
def flaky(params, bars):
    if params["lookback"] > 12:
        raise RuntimeError("simulated crash")
    return dip_buy(params, bars)


def fixed_returns(params, bars):
    r = pd.Series(params["r"], index=bars.index[1 : len(params["r"]) + 1])
    out = pd.DataFrame({"ret": r, "position": 1.0, "turnover": 0.0})
    out.attrs["trade_returns"] = [0.0] * params["n_trades"]
    return out


# ---------- space ----------

def test_param_units():
    assert Param("x", "float", 10, 20).to_unit(15) == pytest.approx(0.5)
    assert Param("x", "float", 1, 100, log=True).to_unit(10) == pytest.approx(0.5)  # geometric middle
    assert Param("x", "int", 5, 5).to_unit(5) == 0.0
    c = Param("m", "cat", choices=("a", "b", "c"))
    assert [c.to_unit(v) for v in "abc"] == [0, 0.5, 1]
    assert Param("m", "cat", choices=("only",)).to_unit("only") == 0
    with pytest.raises(ValueError):
        Param("x", "bogus").suggest(None)
    specs = from_dict({"a": {"kind": "int", "low": 1, "high": 5}, "m": {"kind": "cat", "choices": ("x", "y")}})
    assert [p.name for p in specs] == ["a", "m"] and specs[1].choices == ("x", "y")


# ---------- objective ----------

def test_score_is_mean_minus_penalty_times_spread(btc):
    rng = np.random.default_rng(0)
    r = rng.normal(0.001, 0.02, 400)
    res = evaluate_params(fixed_returns, {"r": r, "n_trades": 10}, btc, n_blocks=4, penalty=0.5)
    blocks = [annualized_sharpe(b) for b in np.array_split(r, 4)]
    assert res["block_sharpes"] == pytest.approx(blocks)
    assert res["score"] == pytest.approx(np.mean(blocks) - 0.5 * np.std(blocks))
    assert res["sharpe"] == pytest.approx(annualized_sharpe(r)) and res["n_trades"] == 10


def test_too_few_trades_is_penalized(btc):
    r = np.full(400, 0.01) + np.random.default_rng(1).normal(0, 1e-3, 400)
    assert evaluate_params(fixed_returns, {"r": r, "n_trades": 4}, btc, min_trades=5)["score"] == -10.0
    assert evaluate_params(fixed_returns, {"r": r, "n_trades": 5}, btc, min_trades=5)["score"] > 0


@given(spread=st.floats(0.1, 3.0))
def test_inconsistent_blocks_score_lower(btc, spread):
    rng = np.random.default_rng(2)
    base = rng.normal(0.002, 0.02, 400)
    lumpy = base.copy()
    lumpy[:100] += 0.004 * spread  # same average edge, all of it in one period
    lumpy[100:] -= 0.004 * spread / 3
    a = evaluate_params(fixed_returns, {"r": base, "n_trades": 9}, btc)
    b = evaluate_params(fixed_returns, {"r": lumpy, "n_trades": 9}, btc)
    assert np.std(b["block_sharpes"]) > np.std(a["block_sharpes"])


# ---------- studies ----------

@pytest.fixture(scope="module")
def bars(btc):
    return btc.iloc[:700]


def test_failing_trials_are_logged_and_the_search_continues(tmp_path, bars):
    trials = run_study("f", flaky, SPECS, bars, tmp_path, SearchConfig(n_trials=20, n_workers=1, seed=3))
    assert len(trials) == 20
    assert set(trials["state"]) == {"COMPLETE", "FAIL"}
    assert trials.loc[trials.state == "FAIL", "params_lookback"].gt(12).all()
    m = load_trial_returns("f", tmp_path)
    assert m.shape[1] == (trials.state == "COMPLETE").sum()


def test_resume_accumulates_trials(tmp_path, bars):
    run_study("r", dip_buy, SPECS, bars, tmp_path, ONE)
    trials = run_study("r", dip_buy, SPECS, bars, tmp_path, ONE)
    assert len(trials) == 16 and trials["number"].tolist() == list(range(16))
    assert load_trial_returns("r", tmp_path).shape[1] == (trials.state == "COMPLETE").sum()
    assert (tmp_path / "r" / "trials.parquet").exists()


def test_leftovers_from_a_crashed_run_are_ignored(tmp_path, bars):
    """A worker killed after writing returns but before Optuna recorded the result leaves
    an orphan file; it must not count as a trial in the DSR/PBO."""
    trials = run_study("c", dip_buy, SPECS, bars, tmp_path, ONE)
    pd.DataFrame({"t999": np.zeros(len(bars) - 1)}).to_parquet(tmp_path / "c" / "returns" / "trial_000999.parquet")
    m = load_trial_returns("c", tmp_path)
    assert "t999" not in m.columns and m.shape[1] == (trials.state == "COMPLETE").sum()


def test_single_worker_search_is_reproducible(tmp_path, bars):
    a = run_study("s", dip_buy, SPECS, bars, tmp_path / "a", ONE)
    b = run_study("s", dip_buy, SPECS, bars, tmp_path / "b", ONE)
    pd.testing.assert_frame_equal(a, b)


def test_meta_records_config_window_and_context(tmp_path, bars):
    run_study("m", dip_buy, SPECS, bars, tmp_path, ONE, context={"data_snapshot": "abc123"})
    meta = json.loads((tmp_path / "m" / "meta.json").read_text())
    assert meta["config"]["n_trials"] == 8 and meta["data_snapshot"] == "abc123"
    assert meta["window"] == [str(bars.index[0]), str(bars.index[-1])]
    assert len(load_trials("m", tmp_path)) == 8


def test_parallel_workers_split_the_budget(tmp_path, bars):
    trials = run_study("p", dip_buy, SPECS, bars, tmp_path, SearchConfig(n_trials=7, n_workers=3, seed=1))
    assert len(trials) == 7 and trials["number"].is_unique


# ---------- stable region ----------

def _trials(points, values, states=None):
    rows = [{"number": i, "state": (states or ["COMPLETE"] * len(values))[i], "value": v,
             "params_a": p[0], "params_b": p[1]} for i, (p, v) in enumerate(zip(points, values, strict=True))]
    return pd.DataFrame(rows)


AB = [Param("a", "float", 0, 1), Param("b", "float", 0, 1)]


def test_prefers_a_plateau_over_a_spike():
    rng = np.random.default_rng(0)
    plateau = [(0.2 + rng.uniform(-0.03, 0.03), 0.2 + rng.uniform(-0.03, 0.03)) for _ in range(12)]
    noise = [tuple(rng.uniform(0.5, 1, 2)) for _ in range(30)]
    spike = [(0.9, 0.1)]
    values = [1.0] * 12 + [-1.0] * 30 + [3.0]
    res = stable_region(_trials(plateau + noise + spike, values), AB, k=6)
    assert res["raw_best_params"] == {"a": 0.9, "b": 0.1} and res["raw_best_score"] == 3.0
    assert res["params"]["a"] < 0.3 and res["params"]["b"] < 0.3
    assert res["neighbourhood_score"] == pytest.approx(1.0)


def test_ignores_failed_and_nan_trials_and_small_k():
    t = _trials([(0.1, 0.1), (0.5, 0.5), (0.9, 0.9)], [1.0, np.nan, 50.0], ["COMPLETE", "COMPLETE", "FAIL"])
    res = stable_region(t, AB, k=10)
    assert res["trial_number"] == 0 and res["own_score"] == 1.0
    with pytest.raises(ValueError):
        stable_region(t[t.state == "FAIL"], AB)


@given(seed=st.integers(0, 2**16), n=st.integers(2, 12))
def test_tied_neighbourhoods_pick_the_best_own_score_whatever_the_trial_order(seed, n):
    """With k >= the number of trials every neighbourhood is the whole set, so every neighbourhood mean is the
    same number; the choice must not come down to summation-order rounding (merge finding: a stats change in
    the last bits moved the chosen trial). Ties go to the trial with the best own score."""
    rng = np.random.default_rng(seed)
    t = _trials([tuple(p) for p in rng.uniform(0, 1, (n, 2))], list(rng.normal(size=n) * 10 ** rng.uniform(-3, 3)))
    best = int(t.loc[t["value"].idxmax(), "number"])
    for order in range(3):
        shuffled = t.sample(frac=1, random_state=order)
        assert stable_region(shuffled, AB, k=n)["trial_number"] == best


def test_categorical_parameters():
    specs = [Param("a", "float", 0, 1), Param("b", "cat", choices=("x", "y", "z"))]
    pts = [(0.1, "x", 1), (0.12, "x", 1), (0.11, "x", 1), (0.13, "x", 1), (0.5, "z", 3), (0.55, "z", -2), (0.45, "z", -2)]
    t = pd.DataFrame([{"number": i, "state": "COMPLETE", "value": v, "params_a": a, "params_b": b}
                      for i, (a, b, v) in enumerate(pts)])
    res = stable_region(t, specs, k=3)
    assert res["params"]["b"] == "x" and res["raw_best_params"]["b"] == "z"


# ---------- walk-forward ----------

@pytest.fixture(scope="module")
def wf_setup(btc):
    bars = btc.iloc[:900]
    folds = walk_forward(len(bars), train_size=400, test_size=200, expanding=True)
    return bars, folds


def test_oos_returns_come_only_from_test_blocks(tmp_path, wf_setup):
    bars, folds = wf_setup
    wf = walk_forward_optimize("w", dip_buy, SPECS, bars, folds, tmp_path, ONE)
    idx = wf["oos_returns"].index
    assert idx.is_unique and idx.is_monotonic_increasing
    for f in folds:
        lo, hi = bars.index[f.test[0]], bars.index[f.test[-1]]
        part = idx[(idx > lo) & (idx <= hi)]
        assert len(part) == len(f.test) - 1  # every return decided inside the block, nothing else
    assert sum(len(f.test) - 1 for f in folds) == len(idx)
    assert wf["total_trials"] == 8 * len(folds) and len(wf["studies"]) == len(folds)


def test_fold_decisions_cannot_see_their_test_block(tmp_path, wf_setup):
    bars, folds = wf_setup
    a = walk_forward_optimize("w", dip_buy, SPECS, bars, folds[:1], tmp_path / "a", ONE)
    tampered = bars.copy()
    tampered.iloc[folds[0].test, tampered.columns.get_loc("close")] *= 1.5
    # keep the bars valid (osprey's runner rejects close > high): widen high and low around the new close
    tampered["high"] = tampered[["open", "high", "close"]].max(axis=1)
    tampered["low"] = tampered[["open", "low", "close"]].min(axis=1)
    b = walk_forward_optimize("w", dip_buy, SPECS, tampered, folds[:1], tmp_path / "b", ONE)
    pcols = [c for c in a["folds"].columns if c.startswith("p_")] + ["is_sharpe"]
    pd.testing.assert_frame_equal(a["folds"][pcols], b["folds"][pcols])
    # Merge restore: on osprey's runner (fills at the next open) the chosen parameters alone no longer moved
    # when the search was handed the test block too. Every trial the fold's search ran must be identical.
    study = a["studies"][0]
    pd.testing.assert_frame_equal(load_trials(study, tmp_path / "a"), load_trials(study, tmp_path / "b"))
    assert not np.allclose(a["oos_returns"], b["oos_returns"])  # the test block itself did change


def test_walk_forward_is_reproducible(tmp_path, wf_setup):
    bars, folds = wf_setup
    a = walk_forward_optimize("w", dip_buy, SPECS, bars, folds, tmp_path / "a", ONE)
    b = walk_forward_optimize("w", dip_buy, SPECS, bars, folds, tmp_path / "b", ONE)
    pd.testing.assert_series_equal(a["oos_returns"], b["oos_returns"])
    rep = overfitting_report(a, tmp_path / "a")
    assert rep["trials_raw"] == 8 * len(folds)
    assert 1 <= rep["trials_effective"] <= rep["trials_raw"]
    assert rep["oos_total_return"] == pytest.approx(np.prod(1 + a["oos_returns"]) - 1)
    assert rep["mc_drawdown_worst5pct"] <= rep["mc_drawdown_median"] <= 0


# ---------- gates ----------

def test_gates():
    good = {"oos_sharpe_annual": 1.2, "dsr_effective_count": 0.97, "pbo_mean": 0.1, "mc_drawdown_worst5pct": -0.2}
    assert all(gates(good).values())
    assert all(gates(good, budget_drawdown=0.25).values())
    assert not gates(good, budget_drawdown=0.15)["MC worst-5% drawdown within 15%"]
    for key, bad in [("oos_sharpe_annual", 0.99), ("dsr_effective_count", 0.94), ("pbo_mean", 0.26)]:
        g = gates({**good, key: bad})
        assert sum(not v for v in g.values()) == 1
    missing = gates({**good, "pbo_mean": float("nan"), "oos_sharpe_annual": float("nan")})
    assert not missing["pbo <= 0.25"] and not missing["oos_sharpe >= 1.0"]  # missing numbers fail, never pass


def dip_buy_modes(params, bars):
    stop = {"tight": 0.05, "loose": 0.20}[params["mode"]]
    return dip_buy({"drop": params["drop"], "lookback": 5, "hold": 10, "stop": stop}, bars)


def test_categorical_and_log_parameters_in_a_real_search(tmp_path, bars):
    specs = [Param("drop", "float", 0.02, 0.30, log=True), Param("mode", "cat", choices=("tight", "loose"))]
    trials = run_study("cat", dip_buy_modes, specs, bars, tmp_path, ONE)
    assert set(trials["params_mode"]) <= {"tight", "loose"}
    assert trials["params_drop"].between(0.02, 0.30).all()  # same range as the starter's 2-30 percent
    assert stable_region(trials, specs, k=3)["params"]["mode"] in ("tight", "loose")


def test_report_with_too_few_trials_has_no_pbo_and_fails_the_gate(tmp_path, wf_setup):
    bars, folds = wf_setup
    wf = walk_forward_optimize("one", dip_buy, SPECS, bars, folds, tmp_path, SearchConfig(n_trials=1, n_workers=1))
    rep = overfitting_report(wf, tmp_path)
    assert np.isnan(rep["pbo_mean"]) and rep["trials_effective"] == 1.0
    assert not gates(rep)["pbo <= 0.25"]
    # merge: no trial-Sharpe spread to deflate against, so DSR is missing and fails its gate (never passes)
    assert np.isnan(rep["dsr_raw_count"]) and np.isnan(rep["dsr_effective_count"])
    assert not gates(rep)["dsr (effective) >= 0.95"]
