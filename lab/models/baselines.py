"""Naive forecasters every model must beat. All point in time: the value at bar t uses bars <= t only.

Volatility baselines forecast ``lab.models.labels.forward_vol`` (per-bar std of log returns, ddof=1):
- ``naive_vol``: the last ``window`` bars' volatility ("tomorrow looks like the recent past"),
  identical to the ``vol_<window>`` feature.
- ``long_run_vol``: volatility of every return so far.
- ``ewma_vol``: the finite-window EWMA used by the ``ewma_vol_20`` feature (identical for span 20), and
  the anchor the volatility model corrects.
Regime and ranking baselines:
- ``regime_persistence``: the next window's regime equals the last window's.
- ``momentum_rank``: tomorrow's cross-sectional rank equals the trailing-return rank.
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd

from lab.models.features import (
    EWMA_WINDOW,
    efficiency_ratio,
    ewma_vol_rows,
    ewma_weights,
    log_returns,
    rolling_windows,
    row_std,
    row_sum,
)
from lab.runner.interface import validate_bars


def _check_int(name: str, value: int, minimum: int) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)) or value < minimum:
        raise ValueError(f"{name} must be an int >= {minimum}, got {value!r}")


def _close(bars: pd.DataFrame) -> np.ndarray:
    validate_bars(bars)
    return bars["close"].to_numpy(dtype=float)


def naive_vol(bars: pd.DataFrame, window: int = 20) -> pd.Series:
    """Std (ddof=1) of the last ``window`` log returns (bars t-window+1..t); NaN for t < window."""
    _check_int("window", window, 2)
    c = _close(bars)
    out = np.full(len(c), np.nan)
    if len(c) > window:
        out[window:] = row_std(rolling_windows(log_returns(c)[1:], window))
    return pd.Series(out, index=bars.index, name=f"naive_vol_{window}")


def long_run_vol(bars: pd.DataFrame, min_periods: int = 60) -> pd.Series:
    """Std (ddof=1) of every log return up to bar t; NaN until ``min_periods`` returns exist."""
    _check_int("min_periods", min_periods, 2)
    lr = pd.Series(log_returns(_close(bars)), index=bars.index)
    return lr.expanding(min_periods=min_periods).std().rename("long_run_vol")


def ewma_vol(bars: pd.DataFrame, span: int = 20, window: int = EWMA_WINDOW) -> pd.Series:
    """EWMA volatility over the last ``window`` log returns (weights ``(1 - 2/(span+1))**age``,
    normalised, not demeaned); NaN for t < window. Equals the ``ewma_vol_20`` feature for span 20."""
    _check_int("span", span, 1)
    _check_int("window", window, 1)
    c = _close(bars)
    out = np.full(len(c), np.nan)
    if len(c) > window:
        out[window:] = ewma_vol_rows(rolling_windows(log_returns(c)[1:], window), ewma_weights(span, window))
    return pd.Series(out, index=bars.index, name=f"ewma_vol_{span}")


def regime_persistence(bars: pd.DataFrame, window: int = 20, threshold: float = 0.3) -> pd.Series:
    """1.0 if the efficiency ratio of closes t-window..t is ``>= threshold`` else 0.0; NaN for t < window.

    The persistence forecast of ``lab.models.labels.forward_regime(bars, window, threshold)``.
    """
    _check_int("window", window, 1)
    if not 0.0 <= threshold <= 1.0:
        raise ValueError(f"threshold must be in [0, 1], got {threshold!r}")
    c = _close(bars)
    n = len(c)
    out = np.full(n, np.nan)
    if n > window:
        path = row_sum(rolling_windows(np.abs(np.diff(c)), window))
        out[window:] = (efficiency_ratio(c[window:] - c[: n - window], path) >= threshold).astype(float)
    return pd.Series(out, index=bars.index, name=f"regime_persistence_{window}")


def momentum_rank(bars_by_asset: Mapping[str, pd.DataFrame], lookback: int = 20) -> dict[str, pd.Series]:
    """Cross-sectional percentile rank of the trailing return ``close[t] / close[t-lookback] - 1``.

    Same rank convention as the cross-sectional label (``pct=True``, ties averaged, best = 1.0, NaN
    left out); NaN for t < lookback. One Series per asset on that asset's index.
    """
    _check_int("lookback", lookback, 1)
    if not bars_by_asset:
        raise ValueError("bars_by_asset is empty")
    trailing = {}
    for asset, bars in bars_by_asset.items():
        c = _close(bars)
        r = np.full(len(c), np.nan)
        if len(c) > lookback:
            r[lookback:] = c[lookback:] / c[: len(c) - lookback] - 1.0
        trailing[asset] = pd.Series(r, index=bars.index)
    ranks = pd.DataFrame(trailing).rank(axis=1, pct=True, method="average")
    name = f"momentum_rank_{lookback}"
    return {asset: ranks[asset].reindex(bars.index).rename(name) for asset, bars in bars_by_asset.items()}
