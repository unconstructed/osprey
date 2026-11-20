"""SYNTHETIC ONLY. Throughput for the rebalance-steady trial budget (PLAN.md section 7 rule, amendment A1).

Never reads the catalog. Writes only into the scratch directory given as the first argument:

    uv run python research/rebalance-steady/throughput.py <scratch dir>

``steady`` is a stand-in for the adapter (``lab/runner/steady.py``, not built yet): the same ``rebalance`` call as
PLAN.md section 5 pins (limits from ``risk_limits("steady")``, headroom 0.02, ``Costs.from_yaml()``). It also checks
the 4 box corners with ``check_targets`` and runs the 36 combinations of PLAN.md section 5.
"""

from __future__ import annotations

import json
import platform
import sys
import time
from dataclasses import replace
from pathlib import Path

import numpy as np

from lab.data.synthetic import synthetic_market
from lab.runner.portfolio import check_targets, make_panel, random_rebalance, rebalance, risk_limits
from lab.runner.reference import Costs
from lab.search.space import Param
from lab.search.study import SearchConfig, run_study

OUT = Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)
LIM = risk_limits("steady")
HEADROOM = 0.02
COSTS = Costs.from_yaml()
SPECS = [
    Param("coin_share", "float", 0.20, 0.77),
    Param("btc_share", "float", 0.25, 0.75),
    Param("band_rel", "float", 0.02, 0.50, log=True),
    Param("every", "int", 1, 90, log=True),
]


def steady(params, bars):
    s, f = params["coin_share"], params["btc_share"]
    return rebalance(
        {
            "w_btc": s * f,
            "w_eth": s * (1.0 - f),
            "band": params["band_rel"] * s,
            "every": params["every"],
            "min_cash": LIM["min_cash"],
            "max_coin": LIM["max_coin"],
            "headroom": HEADROOM,
        },
        bars,
        COSTS,
    )


def main() -> None:
    panel = make_panel(synthetic_market(2190, seed=21, start="2017-01-02"), snapshot_id="synthetic")
    out = {
        "limits": {
            k: LIM[k]
            for k in ("min_cash", "max_coin", "max_drawdown_budget", "max_drawdown_budget_pct", "sha256")
        }
    }
    # box corners: limits as read, headroom 0.02
    corners = [(s, f) for s in (0.20, 0.77) for f in (0.25, 0.75)]
    for s, f in corners:
        check_targets(
            s * f, s * (1 - f), min_cash=LIM["min_cash"], max_coin=LIM["max_coin"], headroom=HEADROOM
        )
    # 36 combinations on the full synthetic panel
    n36 = 0
    for s in (0.20, 0.5, 0.77):
        for f in (0.25, 0.5, 0.75):
            for b in (0.02, 0.5):
                for e in (1, 90):
                    steady({"coin_share": s, "btc_share": f, "band_rel": b, "every": e}, panel)
                    n36 += 1
    out["combos_ran_without_error"] = n36
    # one evaluation, typical and worst (every=1, band small)
    for label, p in {
        "typical": {"coin_share": 0.5, "btc_share": 0.5, "band_rel": 0.1, "every": 7},
        "worst": {"coin_share": 0.77, "btc_share": 0.75, "band_rel": 0.02, "every": 1},
    }.items():
        steady(p, panel)
        ts = []
        for _ in range(20):
            t0 = time.perf_counter()
            steady(p, panel)
            ts.append(time.perf_counter() - t0)
        out[f"backtest_2190_{label}_median_s"] = float(np.median(ts))
    # B3 draw on a 366-row slice
    sl = panel.iloc[729:1095]
    ts = []
    for j in range(50):
        t0 = time.perf_counter()
        random_rebalance({"w_btc": 0.25, "w_eth": 0.25, "n_rebalances": 20, "seed": j}, sl, COSTS)
        ts.append(time.perf_counter() - t0)
    out["b3_draw_366_median_s"] = float(np.median(ts))
    # studies: 20 trials (old rule) and 200 trials on 2190 rows; 200 trials on 730 rows
    cfg = SearchConfig(
        n_trials=200, n_workers=1, n_blocks=4, penalty=0.5, seed=0, periods_per_year=365, min_trades=5
    )
    for label, rows, n in (("t20_r2190", 2190, 20), ("t200_r2190", 2190, 200), ("t200_r730", 730, 200)):
        t0 = time.perf_counter()
        c0 = time.process_time()
        trials = run_study(f"tp_{label}", steady, SPECS, panel.iloc[:rows], OUT, replace(cfg, n_trials=n))
        out[f"study_{label}"] = {
            "wall_s": time.perf_counter() - t0,
            "cpu_s": time.process_time() - c0,
            "trials": len(trials),
            "states": trials["state"].value_counts().to_dict(),
        }
    out["python"] = platform.python_version()
    print(json.dumps(out, indent=1, default=str))
    (OUT / "throughput.json").write_text(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
