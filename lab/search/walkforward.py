"""Walk-forward optimization: search on the past, trade the next unseen block.

For each fold: run an Optuna study on the fold's training bars, choose parameters from
the stable region, then run them once on the following test block. Stitching the test
blocks together gives an equity curve made only of decisions the search never saw.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pandas as pd

from ..runner.interface import BacktestFn
from ..validation.splits import Fold
from ..validation.stats import annualized_sharpe
from .space import Param
from .stability import stable_region
from .study import SearchConfig, run_study


def walk_forward_optimize(
    name: str,
    backtest_fn: BacktestFn,
    specs: list[Param],
    bars: pd.DataFrame,
    folds: list[Fold],
    out_dir: str | Path,
    cfg: SearchConfig = SearchConfig(),  # noqa: B008 - never mutated (callers use dataclasses.replace)
    warmup: int = 120,
    context: dict | None = None,
) -> dict:
    parts, rows, total_trials = [], [], 0
    for i, fold in enumerate(folds):
        study_name = f"{name}_wf{i:02d}"
        trials = run_study(
            study_name, backtest_fn, specs, bars.iloc[fold.train], out_dir,
            replace(cfg, seed=cfg.seed + 1000 * i), context,
        )
        total_trials += len(trials)
        chosen = stable_region(trials, specs)

        is_res = backtest_fn(chosen["params"], bars.iloc[fold.train])
        ctx_start = max(0, fold.test[0] - warmup)
        res = backtest_fn(chosen["params"], bars.iloc[ctx_start : fold.test[-1] + 1])
        oos = res["ret"].loc[bars.index[fold.test[0]] :].iloc[1:]  # decisions made inside the test block
        oos.attrs = {}  # the runner's attrs (arrays, frames) would make pd.concat raise
        parts.append(oos)
        rows.append(
            {
                "fold": i,
                "study": study_name,
                "train_start": bars.index[fold.train[0]].date(),
                "train_end": bars.index[fold.train[-1]].date(),
                "test_start": bars.index[fold.test[0]].date(),
                "test_end": bars.index[fold.test[-1]].date(),
                "trials": len(trials),
                "is_sharpe": annualized_sharpe(is_res["ret"]),
                "oos_sharpe": annualized_sharpe(oos),
                "oos_trades": int((res.loc[oos.index, "turnover"] > 0).sum()),
                **{f"p_{k}": v for k, v in chosen["params"].items()},
            }
        )
    oos_returns = pd.concat(parts)
    folds_df = pd.DataFrame(rows)
    is_mean = folds_df["is_sharpe"].mean()
    oos_sharpe = annualized_sharpe(oos_returns)
    return {
        "oos_returns": oos_returns,
        "folds": folds_df,
        "oos_sharpe": oos_sharpe,
        "wf_efficiency": float(oos_sharpe / is_mean) if is_mean > 0 else float("nan"),
        "total_trials": int(total_trials),
        "studies": list(folds_df["study"]),
    }
