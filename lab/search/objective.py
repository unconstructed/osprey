"""Scoring a parameter set: consistency across time, not the best single number.

The window is cut into contiguous time blocks. The score is the mean annualized Sharpe
across blocks minus a penalty times their standard deviation, so parameters that only
work in one period score poorly. Scores are always after costs.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..runner.interface import BacktestFn
from ..validation.stats import annualized_sharpe


def evaluate_params(
    backtest_fn: BacktestFn,
    params: dict,
    bars: pd.DataFrame,
    n_blocks: int = 4,
    penalty: float = 0.5,
    periods_per_year: int = 365,
    min_trades: int = 5,
) -> dict:
    res = backtest_fn(params, bars)
    r = res["ret"].to_numpy(float)
    blocks = np.array_split(r, n_blocks)
    block_sharpes = [annualized_sharpe(b, periods_per_year) for b in blocks]
    n_trades = len(res.attrs.get("trade_returns", []))
    score = float(np.mean(block_sharpes) - penalty * np.std(block_sharpes))
    if n_trades < min_trades:
        score = -10.0  # too few trades to judge
    return {
        "score": score,
        "block_sharpes": [float(x) for x in block_sharpes],
        "sharpe": annualized_sharpe(r, periods_per_year),
        "n_trades": n_trades,
        # A fresh Series without the runner's attrs: arrays and frames in attrs break to_parquet and pd.concat.
        "returns": pd.Series(r, index=res.index, name="ret"),
    }
