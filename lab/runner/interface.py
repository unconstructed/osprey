"""The backtest contract every runner implements.

``backtest_fn(params, bars) -> result``

``bars`` is a DataFrame indexed by bar *close* time (tz-aware UTC, strictly increasing) with float
columns ``open, high, low, close, volume``.

``result`` is a DataFrame on exactly ``bars.index`` with float columns:

- ``ret``: net return of the portfolio over bar t (close[t-1] -> close[t]) after all costs; ``ret[0] == 0``.
- ``position``: risky-asset weight at the close of bar t, after any trade on bar t and the price move
  through the bar. Spot only, so ``0 <= position <= 1``.
- ``turnover``: traded notional on bar t divided by portfolio value just before the trade
  (``|w_target - w_drifted|``); 0 on bars without a fill.
- ``cost``: fraction of portfolio value paid on bar t (fees + slippage + gas); 0 on bars without a fill.

and ``attrs``:

- ``trade_returns``: 1-D array of per-round-trip net returns in exit order
  (value after exit / value before entry - 1). A position still open at the end is marked to market.
- ``n_trades``: number of fills (entries, exits and rebalances).

Execution model (all runners): a decision at bar t uses data up to the close of bar t and fills at the
open of bar t+1. Positions are held as coin units between trades, so weights drift with price.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pandas as pd

BacktestFn = Callable[[dict, pd.DataFrame], pd.DataFrame]

BAR_COLUMNS = ("open", "high", "low", "close", "volume")
RESULT_COLUMNS = ("ret", "position", "turnover", "cost")

# Tolerance for float round-off in weights (positions are products of ratios).
WEIGHT_TOL = 1e-9


def validate_bars(bars: pd.DataFrame) -> None:
    """Raise ``ValueError`` unless ``bars`` follows the bar conventions above."""
    if not isinstance(bars, pd.DataFrame):
        raise ValueError("bars must be a pandas DataFrame")
    missing = [c for c in BAR_COLUMNS if c not in bars.columns]
    if missing:
        raise ValueError(f"bars is missing columns: {missing}")
    idx = bars.index
    if not isinstance(idx, pd.DatetimeIndex) or idx.tz is None or str(idx.tz) != "UTC":
        raise ValueError("bars index must be a tz-aware UTC DatetimeIndex of bar close times")
    if len(idx) < 2:
        raise ValueError("bars needs at least 2 rows")
    if not idx.is_monotonic_increasing or idx.has_duplicates:
        raise ValueError("bars index must be strictly increasing")
    values = bars.loc[:, list(BAR_COLUMNS)].to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise ValueError("bars contain NaN or infinite values")
    o, h, lo, c, v = values.T
    if (values[:, :4] <= 0).any():
        raise ValueError("bars contain non-positive prices")
    if (v < 0).any():
        raise ValueError("bars contain negative volume")
    if (h < np.maximum(o, c)).any() or (lo > np.minimum(o, c)).any():
        raise ValueError("bars violate low <= open, close <= high")


def validate_result(result: pd.DataFrame, bars: pd.DataFrame) -> None:
    """Raise ``ValueError`` unless ``result`` satisfies the backtest contract for ``bars``."""
    if not isinstance(result, pd.DataFrame):
        raise ValueError("result must be a pandas DataFrame")
    if not result.index.equals(bars.index):
        raise ValueError("result index must equal bars.index")
    missing = [c for c in RESULT_COLUMNS if c not in result.columns]
    if missing:
        raise ValueError(f"result is missing columns: {missing}")
    cols = result.loc[:, list(RESULT_COLUMNS)].to_numpy(dtype=float)
    if not np.isfinite(cols).all():
        raise ValueError("result contains NaN or infinite values")
    ret, pos, turnover, cost = cols.T
    if ret[0] != 0.0 or pos[0] != 0.0:
        raise ValueError("nothing can be filled on the first bar: ret[0] and position[0] must be 0")
    if (ret <= -1.0).any():
        raise ValueError("ret must be greater than -1")
    if (pos < -WEIGHT_TOL).any() or (pos > 1.0 + WEIGHT_TOL).any():
        raise ValueError("position must stay within [0, 1] (spot only, no leverage, no shorts)")
    if (turnover < 0).any() or (cost < 0).any():
        raise ValueError("turnover and cost must be non-negative")
    if (cost[turnover == 0.0] != 0.0).any():
        raise ValueError("cost must be 0 on bars without a fill")
    if "trade_returns" not in result.attrs or "n_trades" not in result.attrs:
        raise ValueError("result.attrs must contain 'trade_returns' and 'n_trades'")
    tr = np.asarray(result.attrs["trade_returns"], dtype=float)
    if tr.ndim != 1 or not np.isfinite(tr).all():
        raise ValueError("attrs['trade_returns'] must be a 1-D array of finite returns")
    n_trades = result.attrs["n_trades"]
    if isinstance(n_trades, bool) or not isinstance(n_trades, (int, np.integer)) or n_trades < 0:
        raise ValueError("attrs['n_trades'] must be a non-negative int")
