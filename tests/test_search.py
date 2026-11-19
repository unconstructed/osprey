import numpy as np

from lab.data.synthetic import synthetic_market
from lab.runner.reference import Costs, buy_and_hold, dip_buy
from lab.search.report import overfitting_report
from lab.search.space import Param
from lab.search.stability import stable_region
from lab.search.study import SearchConfig, load_trial_returns, run_study
from lab.search.walkforward import walk_forward_optimize
from lab.validation.splits import walk_forward

SPECS = [  # osprey dip_buy names; drop and stop are fractions (the starter used percent)
    Param("drop", "float", 0.03, 0.25),
    Param("lookback", "int", 2, 20),
    Param("hold", "int", 3, 40),
    Param("stop", "float", 0.03, 0.25),
]


def test_reference_costs_reduce_returns():
    """Rewritten for osprey's Costs (size-based slippage, per-fill gas) and fills at the next open."""
    bars = synthetic_market(600, seed=3)["BTC"]
    p = {"drop": 0.08, "lookback": 5, "hold": 10, "stop": 0.10}
    cheap = dip_buy(p, bars, Costs.zero())
    dear = dip_buy(p, bars, Costs(pool_fee_bps=50, slippage_bps=((1.0, 0.0),), gas_usd_per_trade=0.0))
    assert dear["ret"].sum() < cheap["ret"].sum()
    assert len(cheap.attrs["trade_returns"]) > 0
    bh = buy_and_hold({}, bars)
    growth = (1 + bh["ret"]).prod()
    price_growth = bars.close.iloc[-1] / bars.open.iloc[1]  # bought at the open of bar 1
    assert growth < price_growth  # entry cost paid
    assert bh["cost"].iloc[1] > 0 and (bh["cost"].iloc[2:] == 0).all()
    assert np.isclose(growth, price_growth * (1 - bh["cost"].iloc[1]), rtol=1e-12)


def test_study_logs_every_trial_and_stable_region(tmp_path):
    bars = synthetic_market(900, seed=4)["BTC"]
    cfg = SearchConfig(n_trials=24, n_workers=2, seed=1)
    trials = run_study("t", dip_buy, SPECS, bars, tmp_path, cfg)
    assert len(trials) == 24
    m = load_trial_returns("t", tmp_path)
    assert m.shape[1] == (trials["state"] == "COMPLETE").sum()
    chosen = stable_region(trials, SPECS, k=5)
    for p in SPECS:
        assert p.low <= chosen["params"][p.name] <= p.high


def test_walk_forward_and_report(tmp_path):
    bars = synthetic_market(1100, seed=5)["BTC"]
    folds = walk_forward(len(bars), train_size=500, test_size=200, expanding=True)
    wf = walk_forward_optimize("wf", dip_buy, SPECS, bars, folds, tmp_path, SearchConfig(n_trials=16, n_workers=1))
    assert len(wf["folds"]) == len(folds)
    assert wf["oos_returns"].index.is_monotonic_increasing
    assert wf["oos_returns"].index[0] > bars.index[folds[0].test[0]]
    rep = overfitting_report(wf, tmp_path)
    assert 0 <= rep["dsr_effective_count"] <= 1 and 0 <= rep["pbo_mean"] <= 1
    assert rep["trials_effective"] <= rep["trials_raw"]
